"""RND-1..RND-7 against local fake websites, with real headless rendering where the check needs it."""

import json
import socket
import subprocess
import sys
import threading
import time

import pytest

from fakeserver import FakeServer, Response, Site
from fakeserver.rnd_scenarios import FAST_RND, RND_SCENARIOS, csr_site, third_party_site
from fakeserver.scenarios import robots
from maya_audit.audit import run_audit
from maya_audit.config import CrawlConfig


def names(item):
    return sorted(u.rsplit("/", 1)[-1] or "/" for u in item.scope["urls"])


def _browser_available() -> str | None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return "Playwright is not installed"
    try:
        with sync_playwright() as p:
            p.chromium.launch(headless=True).close()
    except Exception as exc:  # noqa: BLE001
        return f"headless Chromium unavailable: {exc}"
    return None


class CsrRun:
    def __init__(self, outcome, site_requests, third_party_requests, config, base):
        self.outcome = outcome
        self.result = outcome.result
        self.gates = {g.check_id: g for g in outcome.gates}
        self.checks = {c.check_id: c for c in outcome.checks}
        self.site_requests = site_requests
        self.third_party_requests = third_party_requests
        self.config = config
        self.base = base

    def findings(self, check_id, severity=None, confidence=None):
        return [f for f in self.checks[check_id].findings
                if (severity is None or f.severity.value == severity) and (confidence is None or f.confidence.value == confidence)]


FACTS = (("/pricing", "Pro plan $49/mo"), ("/pricing", "Enterprise: contact sales"),
         ("/pricing", "Starter plan $9/mo"), ("/ssr", "Founded in 2012"))


def run_csr(**overrides) -> CsrRun:
    with FakeServer(third_party_site()) as third_party, FakeServer(csr_site(lambda: third_party.base_url)) as site:
        options = {**FAST_RND, "render_budget": 7, "key_pages": (site.base_url + "/pricing",),
                   "critical_facts": FACTS, **overrides}
        config = CrawlConfig(**options)
        outcome = run_audit(site.base_url + "/", config)
        return CsrRun(outcome, list(site.requests), list(third_party.requests), config, site.base_url)


@pytest.fixture(scope="module")
def csr():
    reason = _browser_available()
    if reason:
        pytest.skip(f"T1 rendering tests need a headless browser: {reason}")
    return run_csr()


def test_rendering_gap(csr):
    [missing] = csr.findings("RND-1", "S2", "verified")
    assert names(missing) == ["/", "pricing"]
    assert missing.cost_tier == "T1" and "Google renders JavaScript" in missing.notes[0]
    row = next(r for r in missing.evidence["pages"] if r["url"].endswith("/pricing"))
    assert row["raw_words"] < 50 and row["rendered_words"] > 200
    assert {h["text"] for h in row["headings_only_after_render"]} >= {"Plans", "Team plan"}
    [partial] = [f for f in csr.findings("RND-1", "S3") if names(f) == ["partial"]]
    assert names(partial) == ["partial"]
    # The gap is quoted, not only counted, and the data request made while rendering is named.
    delta = partial.evidence["pages"][0]["content_delta"]
    assert delta["statement"].startswith("This text was absent from the initial HTML response")
    assert any(b["text"].startswith("client0 client1") for b in delta["missing_text_blocks"])
    assert not any("server0 server1" in b["text"] for b in delta["missing_text_blocks"])  # raw text is not a gap
    assert [r["url"].rsplit("/", 1)[-1] for r in delta["data_requests_during_render"]] == ["extra.json"]
    assert delta["data_requests_during_render"][0]["type"] == "fetch"
    pricing = next(r for r in missing.evidence["pages"] if r["url"].endswith("/pricing"))["content_delta"]
    # /pricing is a key page, so its raw markup was kept: "Enterprise: contact sales" sits in a JSON script there.
    where = {b["text"]: b["in_raw_response"] for b in pricing["missing_text_blocks"]}
    assert where["Pro plan $49/mo"] is None
    [suspected] = csr.findings("RND-1", "S3", "estimated")
    assert names(suspected) == ["zz-shell"]
    assert any("#__next" in s for s in suspected.evidence["pages"][0]["signals"])


def test_render_sample_and_int3_disclosure(csr):
    int3 = csr.gates["INT-3"]
    assert int3.evidence["rendering_mode"] == "raw_plus_sampled_render"
    assert len(int3.evidence["rendered_pages"]) == 7 and all(p["ok"] for p in int3.evidence["rendered_pages"])
    assert int3.evidence["render_order"][0]["why"] == "homepage"
    assert [t["sample_url"].rsplit("/", 1)[-1] for t in int3.evidence["templates_not_rendered"]] == ["zz-shell"]
    # A noindexed page is disclosed as deliberately skipped, not as a template the budget missed.
    assert [u.rsplit("/", 1)[-1] for u in int3.evidence["noindexed_not_rendered"]] == ["onboarding"]
    assert "cannot be cited" in int3.summary
    assert "Resources on other origins were not loaded" in int3.summary


def test_rendering_safety_seen_from_the_server(csr):
    assert [r.path for r in csr.site_requests if r.method != "GET"] == []  # the page's POST /track was aborted
    assert [r.path for r in csr.site_requests if r.path.startswith("/private/")] == []  # robots.txt disallows it
    assert csr.third_party_requests == []  # third-party resources not loaded
    # The browser identified as Maya-Audit. The only other user agents are ACC-4's tagged browser/Googlebot check on a
    # site whose ownership is not verified (DECISIONS 205).
    assert {r.user_agent for r in csr.site_requests if not r.headers.get("x-maya-probe")} == {csr.config.user_agent}
    aborted = [(r["url"].rsplit("/", 1)[-1], r["reason"]) for e in csr.result.render.pages.values()
               for r in e["requests"] if r["action"] == "aborted"]
    reasons = dict(aborted)
    assert "robots.txt" in reasons["data.js"] and "third-party" in reasons["widget.js"] and "POST" in reasons["track"]
    int4 = csr.gates["INT-4"]
    assert int4.state == "compliant", int4.summary
    purposes = int4.evidence["requests_by_purpose"]
    # The sample of 7, plus the homepage and the key page rendered during the crawl to look for links.
    assert csr.result.render_discovery["pages_rendered"] == 2
    assert purposes["render"] == 7 + 2 and purposes["render_subresource"] > 0


def test_critical_facts(csr):
    after_js = next(f for f in csr.findings("RND-2", "S2", "verified") if "after JavaScript" in f.title)
    assert [r["fact"] for r in after_js.evidence["facts"]] == ["Pro plan $49/mo"]
    markup = next(f for f in csr.findings("RND-2", "S2", "verified") if "inside markup" in f.title)
    assert [r["fact"] for r in markup.evidence["facts"]] == ["Enterprise: contact sales"]
    [review] = csr.checks["RND-2"].review_items
    assert [r["fact"] for r in review.evidence["facts"]] == ["Starter plan $9/mo"]
    assert [r["fact"] for r in csr.checks["RND-2"].evidence["found_in_raw_html"]] == ["Founded in 2012"]
    [auto] = csr.findings("RND-2", "S3", "estimated")
    home = next(p for p in auto.evidence["pages"] if p["url"] == csr.base + "/")
    assert "Acme Analytics" in home["headings_only_after_render"]


def test_content_behind_interaction(csr):
    [revealed] = csr.findings("RND-3", "S3", "verified")
    assert names(revealed) == ["interactive"]
    page = revealed.evidence["pages"][0]
    clicked = [c["text"] for c in page["clicked"]]
    assert "Specifications" in clicked and "Load more" in clicked
    assert "Overview" not in clicked  # already-selected tab
    assert "Load more results" not in clicked  # inside a form
    assert "FORMCLICKED" not in page["new_text_sample"].upper()
    assert page["words_after"] - page["words_before"] >= 100
    # 70 words appeared by themselves (a timer) while waiting without clicking: late loading, not interaction.
    assert page["compared_against"].startswith("control snapshot")
    assert "late0" not in page["new_text_sample"]
    [late] = csr.checks["RND-3"].observations
    assert any(p["url"].endswith("/interactive") and p["words_after_waiting_without_clicking"]
               - p["words_at_first_snapshot"] >= 70 for p in late["pages"])


def test_noindexed_pages_are_not_reported_as_content_gaps(raw_scenario):
    """A page the site marks noindex cannot be cited, so a content gap on it is not a citation problem
    (ACC-3 reports the directive). Seen on a 50-page live audit of a real site."""
    run = raw_scenario("rnd_nontext_payload")
    rnd1 = run.checks["RND-1"]
    assert any(u.endswith("/onboarding") for u in rnd1.evidence["excluded_noindex"])
    for check_id in ("RND-1", "RND-3", "RND-4", "RND-7"):
        assert not any(u.endswith("/onboarding") for f in run.checks[check_id].findings for u in f.scope["urls"])


def test_render_survives_a_network_that_never_goes_idle(csr):
    """A resource-heavy page must still yield a rendered DOM. The first audit of a client site lost all
    five renders to a networkidle timeout and produced no rendered view at all."""
    entry = next(e for u, e in csr.result.render.pages.items() if u.endswith("/ssr"))
    assert entry["ok"] and entry["network_idle"] is False
    assert "late-loading part" in entry["settle_note"]
    # The slow request takes 3 s; the DOM is read when the 1.5 s settle window closes, not when it lands.
    assert entry["rendered"]["visible_words"] > 200
    assert entry["elapsed_ms"] <= csr.config.render_timeout_s * 1000 + csr.config.render_settle_ms
    int3 = csr.gates["INT-3"]
    assert "had not gone idle" in int3.summary
    assert any(p["network_idle"] is False for p in int3.evidence["rendered_pages"])


def test_images_media_and_fonts_are_not_fetched_and_int3_counts_them(csr):
    entry = next(e for u, e in csr.result.render.pages.items() if u.endswith("/ssr"))
    [image] = [r for r in entry["requests"] if r["url"].endswith("/slow-image.png")]
    assert image["action"] == "aborted" and image["skipped_type"] == "image" and "not fetched" in image["reason"]
    rendered_requests = [r for r in csr.result.requests if r.purpose.startswith("render")]
    assert not any(r.url.endswith(".png") for r in rendered_requests)
    int3 = csr.gates["INT-3"]
    row = next(p for p in int3.evidence["rendered_pages"] if p["url"].endswith("/ssr"))
    assert row["requests_skipped_by_type"] == {"image": 1}
    assert "image, media and font request(s) were not fetched while rendering" in int3.summary


def test_subresources_are_fetched_at_most_four_at_a_time():
    reason = _browser_available()
    if reason:
        pytest.skip(f"T1 rendering tests need a headless browser: {reason}")
    lock, in_flight, peak = threading.Lock(), [0], [0]

    def slow_part(site, request):
        with lock:
            in_flight[0] += 1
            peak[0] = max(peak[0], in_flight[0])
        time.sleep(0.4)
        with lock:
            in_flight[0] -= 1
        return Response(body=json.dumps({"text": "part" + request.route_path.rsplit("/", 1)[-1]}),
                        content_type="application/json")

    page = ("<!doctype html><html><head><title>Parts</title></head><body><main><h1>Parts</h1><p id='out'></p></main>"
            "<script>for (let i = 0; i < 10; i++) fetch('/part/' + i).then(r => r.json()).then(d => {"
            "document.getElementById('out').append(d.text + ' '); });</script></body></html>")
    routes = {"/robots.txt": robots("User-agent: *\nAllow: /\n"), "/sitemap.xml": Response(404, "", content_type="text/plain"),
              "/": Response(body=page), **{f"/part/{i}": slow_part for i in range(10)}}
    with FakeServer(Site(routes)) as site:
        config = CrawlConfig(**{**WEBSOCKET_RENDER, "render_settle_ms": 3000})
        result = run_audit(site.base_url + "/", config).result
    [entry] = result.render.pages.values()
    assert entry["ok"] and entry["network_idle"] is True
    assert entry["rendered"]["visible_words"] >= 11  # the heading and all ten parts
    assert 2 <= peak[0] <= 4
    assert entry["elapsed_ms"] < 10 * 400  # ten 0.4 s requests, not one after another


def test_a_page_that_never_reaches_dom_ready_still_yields_a_rendered_view(raw_scenario):
    """Seen twice on a client site: the homepage did not reach DOM-ready inside the render timeout and
    the whole render was discarded. The partial DOM is kept, and INT-3 says it may be partial."""
    reason = _browser_available()
    if reason:
        pytest.skip(f"T1 rendering tests need a headless browser: {reason}")
    run = raw_scenario("rnd_slow_navigation")
    [entry] = list(run.result.render.pages.values())
    assert entry["ok"] and entry["navigation_timed_out"].startswith("Page.goto")
    assert entry["rendered"]["visible_words"] > 50  # the content already in the DOM was read anyway
    assert "may be partial" in run.gates["INT-3"].summary


WEBSOCKET_RENDER = {"max_pages": 1, "time_limit_s": 15, "request_timeout_s": 3, "request_delay_s": 0, "robots_samples": 1,
                    "robots_sample_interval_s": 0, "render_enabled": True, "render_budget": 1, "render_timeout_s": 4,
                    "render_settle_ms": 100, "render_control_wait_ms": 0, "render_interactions": False,
                    "probes_enabled": False, "prf_enabled": False}


def _websocket_page(socket_url_js: str) -> Site:
    html = ("<!doctype html><html><head><title>WebSocket test</title></head><body><main><h1>WebSocket test</h1>"
            "<p>" + "A static audit page with enough ordinary text to test the renderer. " * 25 + "</p></main>"
            f"<script>window.auditSocket = new WebSocket({socket_url_js});</script>"
            "</body></html>")
    return Site({"/robots.txt": robots("User-agent: *\nAllow: /\n"),
                 "/sitemap.xml": Response(404, "", content_type="text/plain"),
                 "/": Response(body=html)})


def _audit_in_subprocess(url: str, options: dict) -> dict:
    """Run the audit in a child process, so a renderer that hangs fails the test instead of the suite."""
    from offline_process import environment
    code = (
        "import faulthandler; faulthandler.dump_traceback_later(10, repeat=True); "
        "import json,sys; from maya_audit.audit import run_audit; from maya_audit.config import CrawlConfig; "
        "r=run_audit(sys.argv[1],CrawlConfig(**json.loads(sys.argv[2]))).result; "
        "print(json.dumps({'elapsed_s':r.elapsed_s,'pages':r.render.pages}))"
    )
    completed = subprocess.run([sys.executable, "-c", code, url, json.dumps(options)], capture_output=True,
                               text=True, timeout=25, check=True, env=environment())
    return json.loads(completed.stdout.strip().splitlines()[-1])


def test_websocket_page_finishes_within_deadline_without_opening_a_socket():
    reason = _browser_available()
    if reason:
        pytest.skip(f"T1 rendering tests need a headless browser: {reason}")

    with FakeServer(_websocket_page("'ws://' + location.host + '/audit-socket'")) as site:
        payload = _audit_in_subprocess(site.base_url + "/", WEBSOCKET_RENDER)
        assert payload["elapsed_s"] < 15
        assert payload["pages"]
        assert not [request for request in site.requests if request.route_path == "/audit-socket"]


def test_websocket_server_that_accepts_and_never_replies_does_not_hold_up_the_render():
    """The server takes the connection and then says nothing, so a handshake would wait forever. The
    render must not wait with it: one page is done within render_timeout_s + render_settle_ms."""
    reason = _browser_available()
    if reason:
        pytest.skip(f"T1 rendering tests need a headless browser: {reason}")

    silent = socket.socket()
    silent.bind(("127.0.0.1", 0))
    silent.listen(5)
    held, stop = [], threading.Event()

    def accept_and_say_nothing():
        silent.settimeout(0.1)
        while not stop.is_set():
            try:
                held.append(silent.accept()[0])  # kept open, never answered
            except OSError:
                continue

    acceptor = threading.Thread(target=accept_and_say_nothing, daemon=True)
    acceptor.start()
    options = {**WEBSOCKET_RENDER, "render_settle_ms": 1000}
    try:
        with FakeServer(_websocket_page(f"'ws://127.0.0.1:{silent.getsockname()[1]}/silent'")) as site:
            payload = _audit_in_subprocess(site.base_url + "/", options)
    finally:
        stop.set()
        acceptor.join()
        for connection in held:
            connection.close()
        silent.close()
    [entry] = payload["pages"].values()
    assert entry["ok"] and entry["rendered"]["visible_words"] > 200
    assert entry["elapsed_ms"] <= options["render_timeout_s"] * 1000 + options["render_settle_ms"]
    assert entry["websocket_blocking"] == "blocked" and held == []  # the handshake never left the browser


def test_noindexed_pages_get_no_render_slot(csr):
    """Rendering a page that cannot be cited wastes the budget, and its rendered-only headings are not
    findings either (the 50-page live audit reported one on a noindexed /onboarding page)."""
    order = [o["url"] for o in csr.gates["INT-3"].evidence["render_order"]]
    assert not any(u.endswith("/onboarding") for u in order)
    assert not any(u.endswith("/onboarding") for f in csr.checks["RND-2"].findings
                   for p in f.evidence.get("pages", []) for u in [p["url"]])


def test_rnd7_does_not_repeat_rnd1_root_causes(csr):
    rnd7 = csr.checks["RND-7"]
    excluded = {u.rsplit("/", 1)[-1] or "/" for u in rnd7.evidence["excluded_as_rnd1_root_cause"]}
    assert {"/", "pricing", "partial", "zz-shell"} <= excluded
    assert not any(u in excluded for f in rnd7.findings for u in names(f))


def test_browser_launch_failure_falls_back_to_raw_heuristics():
    run = run_csr(render_browser_channel="no-such-browser-channel")
    int3 = run.gates["INT-3"]
    assert int3.evidence["rendering_mode"] == "raw_html_only"
    assert "could not be launched" in int3.evidence["reason"]
    assert run.findings("RND-1", "S2", "verified") == []
    [suspected] = run.findings("RND-1", "S3", "estimated")
    assert {"/", "pricing", "zz-shell"} <= set(names(suspected))
    assert run.checks["RND-3"].findings == [] or all(f.confidence.value == "estimated" for f in run.checks["RND-3"].findings)


@pytest.fixture
def raw_scenario(run_audit_scenario):
    return run_audit_scenario


def test_walls_and_paywalls(raw_scenario):
    run = raw_scenario("rnd_walls")
    findings = run.checks["RND-5"].findings
    by_sev = {f.severity.value: f for f in findings}
    assert names(by_sev["S1"]) == ["members-only"] and by_sev["S1"].confidence.value == "verified"
    assert names(by_sev["S3"]) == ["article", "tr-cerez", "wine-shop"] and by_sev["S3"].confidence.value == "estimated"
    assert names(by_sev["S4"]) == ["story"]
    assert [p["url"].rsplit("/", 1)[-1] for p in run.checks["RND-5"].evidence["paywalls_with_structured_data"]] == ["story-sd"]
    # A normal page with a cookie banner and the login page itself are not walls.
    assert not any(u.endswith(("/normal", "/login")) for f in findings for u in f.scope["urls"])


def test_the_turkish_cookie_wall_is_found_now_that_the_signatures_cover_turkish(raw_scenario):
    run = raw_scenario("rnd_walls")
    rnd5 = run.checks["RND-5"]
    not_assessed = {r["url"].rsplit("/", 1)[-1]: r["reason"] for r in rnd5.evidence["text_signatures_not_assessed"]}
    assert "tr-cerez" not in not_assessed and "en-plain" not in not_assessed
    wall = next(page for f in rnd5.findings for page in f.evidence["pages"] if page["url"].endswith("/tr-cerez"))
    assert wall["signatures"] == ["cookie consent"]
    assert rnd5.evidence["text_signatures_language"] == "English and Turkish"


def test_wall_marking(raw_scenario):
    from maya_audit.intent import IntentMarking

    run = raw_scenario("rnd_walls", intent_markings=(IntentMarking("m-age", "RND-5", "wall_in_place", "/wine-shop"),))
    marked = next(f for f in run.checks["RND-5"].findings if f.intent)
    assert names(marked) == ["wine-shop"] and marked.intent["severity_otherwise"] == "S2"


def test_non_text_payload_and_main_share(raw_scenario):
    run = raw_scenario("rnd_nontext_payload")
    rnd4 = {f.title.split(" ", 3)[3][:12]: f for f in run.checks["RND-4"].findings}
    kinds = {(f.confidence.value, tuple(names(f))) for f in run.checks["RND-4"].findings}
    assert kinds == {("inferred", ("embed",)), ("verified", ("chart",)), ("estimated", ("banner",))}
    banner = next(f for f in run.checks["RND-4"].findings if names(f) == ["banner"])
    assert sorted(i["src"] for i in banner.evidence["items"]) == ["/banner.png", "/banner2.png"]
    chart = next(f for f in run.checks["RND-4"].findings if names(f) == ["chart"])
    assert len(chart.evidence["items"]) == 1  # the canvas with an aria-label is fine
    assert next(f for f in run.checks['RND-4'].findings if names(f)==['embed']).severity.value=='Info'
    assert all(f.severity.value == "S4" for f in run.checks["RND-4"].findings if names(f)!=['embed'])
    assert run.checks["RND-4"].observations[0]["value"] == 1
    assert rnd4

    rnd6 = run.checks["RND-6"].findings
    assert sorted(names(f)[0] for f in rnd6) == ["big", "big"]
    assert all(f.severity.value == "S4" for f in rnd6)

    rnd7 = run.checks["RND-7"].findings
    assert sorted(names(f)[0] for f in rnd7)==['boilerplate','no-main']
    assert all(f.severity.value=='Info' for f in rnd7)
