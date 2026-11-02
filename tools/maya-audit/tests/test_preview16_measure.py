"""team-preview-16, run 3 (DECISIONS 219): the step timing table, robots.txt samples without idle waiting, page reading
never cut for the checks, Fast check, and the web app's two switches.

Every site here is made up (demo-kafe.test) and answered by an httpx mock transport; nothing is requested. Time is a
fake monotonic clock: a wait moves it forward at once, and each answer takes 0.2 s of it. No test sleeps for real.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

import httpx
import pytest

from maya_audit import cli
from maya_audit.audit import run_audit
from maya_audit.config import CrawlConfig, estimated_duration_s, external_link_cap
from maya_audit.report import build_report, render_markdown
from maya_audit import timeplan
from test_web_app import web  # noqa: F401  (the web app fixture: demo sites, mock transports)

KAFE = "https://demo-kafe.test"
ANSWER_S = 0.2


class FakeClock:
    """time.monotonic and time.sleep for one test: sleeping moves the clock, nothing waits."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += max(0.0, seconds)

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    fake = FakeClock()
    monkeypatch.setattr(time, "monotonic", fake.monotonic)
    monkeypatch.setattr(time, "sleep", fake.sleep)
    return fake


def page(body: str = "", title: str = "Demo Kafe") -> str:
    words = " ".join(["kahve", "menü", "tatlı", "çay", "sabah", "kahvaltı"] * 40)
    return (f"<html lang='tr'><head><title>{title}</title><meta name='description' content='Demo Kafe'></head>"
            f"<body><main><h1>{title}</h1><p>{words}</p>{body}</main></body></html>")


def site(clock: FakeClock, pages: int = 10, sitemap_only: int = 0, external: int = 0, llms: int = 0, images: int = 0):
    """A made-up cafe: a homepage linking `pages` pages, a sitemap listing `sitemap_only` more that no page links,
    `external` links to other sites on the homepage, `llms` same-site links in llms.txt and `images` images."""
    paths = [f"/sayfa-{i}" for i in range(pages)]
    extra = [f"/liste-{i}" for i in range(sitemap_only)]
    links = "".join(f'<a href="{p}">{p}</a>' for p in paths)
    links += "".join(f'<a href="https://other-{i}.test/sayfa">other {i}</a>' for i in range(external))
    imgs = "".join(f'<img src="/img/{i}.jpg" alt="foto {i}">' for i in range(images))
    sitemap = ('<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
               + "".join(f"<url><loc>{KAFE}{p}</loc></url>" for p in paths + extra) + "</urlset>")
    llms_text = "# Demo Kafe\n\n" + "".join(f"- [Menü {i}]({KAFE}/menu-{i})\n" for i in range(llms))
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        clock.advance(ANSWER_S)
        seen.append(str(request.url))
        if request.url.host != "demo-kafe.test":
            if request.url.path == "/robots.txt":
                return httpx.Response(200, text="User-agent: *\nAllow: /\n", headers={"content-type": "text/plain"})
            return httpx.Response(200, text="ok", headers={"content-type": "text/plain"})
        path = request.url.path
        if path == "/robots.txt":
            return httpx.Response(200, text=f"User-agent: *\nAllow: /\nSitemap: {KAFE}/sitemap.xml\n",
                                  headers={"content-type": "text/plain"})
        if path == "/sitemap.xml":
            return httpx.Response(200, text=sitemap, headers={"content-type": "application/xml"})
        if path == "/llms.txt" and llms:
            return httpx.Response(200, text=llms_text, headers={"content-type": "text/plain"})
        if path.startswith("/img/"):
            return httpx.Response(200, content=b"\xff\xd8\xff", headers={"content-type": "image/jpeg"})
        if path == "/":
            return httpx.Response(200, text=page(links + imgs), headers={"content-type": "text/html; charset=utf-8"})
        if path in paths or path in extra or path.startswith("/menu-"):
            return httpx.Response(200, text=page(title=f"Demo Kafe {path}"), headers={"content-type": "text/html; charset=utf-8"})
        return httpx.Response(404, text="yok", headers={"content-type": "text/plain"})

    transport = httpx.MockTransport(handler)
    transport.seen = seen
    return transport


BASE = dict(request_delay_s=1.0, robots_samples=3, robots_sample_interval_s=120.0, render_enabled=False, prf_enabled=False,
            refetch_delay_s=0.0, probe_retry_cooldown_s=0.0, time_limit_s=3600.0)


def audit(transport, **options):
    return run_audit(KAFE + "/", CrawlConfig(**{**BASE, **options}), transport)


def paced(result):
    return [r for r in result.requests if r.purpose != "render_subresource"]


# -- (b) robots.txt samples without idle waiting --------------------------------------------------------------------------

def test_robots_samples_are_sent_when_due_between_other_requests_with_no_idle_gap(clock):
    # At the fixed 1 s pace (adaptive pacing off, DECISIONS 219 part 2): a narrower gap ends Maya's steps sooner.
    # 200 sitemap URLs asked (the cap is 100 in Quick since DECISIONS 294): Maya's steps last long enough for both samples.
    # One request at a time (site_concurrency 1): this fake clock moves on every sleep, so threads waiting together would
    # move it several times over; the shared limit has its own tests (tests/test_v03_speed.py).
    outcome = audit(site(clock, pages=40, sitemap_only=220), max_pages=60, adaptive_pacing=False, sitemap_check_max=200,
                    site_concurrency=1)
    result = outcome.result
    log = paced(result)
    robots = [r for r in log if r.purpose in ("robots", "robots_sample") and r.url == f"{KAFE}/robots.txt"]
    assert [r.purpose for r in robots] == ["robots", "robots_sample", "robots_sample"]
    assert len(result.access.robots_samples) == 3
    # Decision 12 stays: each sample at least 120 s after the one before it.
    assert robots[1].started_mono - robots[0].started_mono >= 120 and robots[2].started_mono - robots[1].started_mono >= 120
    # ... and no request waited for them: every gap is the 1 s between requests, never a 120 s idle wait.
    gaps = [b.started_mono - a.ended_mono for a, b in zip(log, log[1:])]
    assert max(gaps) < 1.01
    assert log.index(robots[2]) < len(log) - 1  # sent among the other requests, not after them
    steps = [row["step"] for row in result.steps]
    assert "robots_wait" not in steps
    # The step timing table: each of Maya's steps once, in order, with its requests and its waiting.
    assert steps[:2] == ["sitemap", "crawl"] and steps.index("access") < steps.index("index") < steps.index("structure") \
        < steps.index("sitemap_check") < steps.index("llms_links")
    assert sum(row["requests"] for row in result.steps) == len(result.requests)
    crawl_row = next(row for row in result.steps if row["step"] == "crawl")
    read = len(result.pages)
    assert crawl_row["requests"] == read and read * 1.0 - 1 <= crawl_row["waiting_s"] <= crawl_row["seconds"]
    assert set(crawl_row) == {"step", "started_at", "seconds", "requests", "waiting_s"}


def test_a_sample_still_not_due_when_the_last_step_ends_is_waited_for_then_and_only_then(clock):
    outcome = audit(site(clock, pages=2), max_pages=5)
    result = outcome.result
    log = paced(result)
    assert [r.purpose for r in log[-2:]] == ["robots_sample", "robots_sample"]  # after everything else
    first = next(r for r in log if r.purpose == "robots")
    assert log[-2].started_mono - first.started_mono >= 120 and log[-1].started_mono - log[-2].started_mono >= 120
    wait = next(row for row in result.steps if row["step"] == "robots_wait")
    assert wait["requests"] == 2 and wait["waiting_s"] > 200 and result.steps[-1]["step"] == "robots_wait"
    assert len(result.access.robots_samples) == 3


def test_healthy_with_fast_check_off_the_request_log_is_todays_order_apart_from_the_robots_samples(clock):
    def order(samples):
        result = audit(site(clock, pages=12, sitemap_only=30, llms=5, images=4), max_pages=20, robots_samples=samples).result
        # The soft-404 probe asks a new made-up address each run: compared without its random part.
        rows = [(r.purpose, r.url.split("no-such-page-")[0]) for r in result.requests if r.purpose != "robots_sample"]
        # The sitemap check asks 4 at a time (DECISIONS 294): its requests are compared as a set, the rest in order.
        return [row for row in rows if row[0] != "sitemap_check"] + sorted(row for row in rows if row[0] == "sitemap_check"), result

    three, with_samples = order(3)
    one, _ = order(1)
    assert three == one
    assert sum(1 for r in with_samples.requests if r.purpose == "robots_sample") == 2
    assert with_samples.skipped_for_time == [] and with_samples.config["fast_check"] is False


# -- (f) page reading is never cut; the later steps give way, in order ---------------------------------------------------

def test_the_deadline_in_the_late_steps_names_what_was_skipped_and_page_reading_is_not_cut(clock):
    transport = site(clock, pages=40, sitemap_only=100, external=8)
    # Asked in turn (adaptive pacing off): with the other-site pool they no longer hold up the sitemap check.
    outcome = audit(transport, max_pages=41, time_limit_s=70.0, robots_samples=1, adaptive_pacing=False)
    result = outcome.result
    # 41 pages at 1.2 s each take about 50 s, past the 60 % (42 s) the crawl used to stop at: every page was read.
    assert result.stop_reason.value == "page_cap" and len([p for p in result.pages if p.status == 200]) == 41
    # Links to other sites gave way first (the sitemap check still needed its time), then the sitemap check ran out.
    assert result.skipped_for_time == ["other_site_links", "sitemap_check"]
    assert not any("other-" in url for url in transport.seen)
    assert result._external.not_asked.get("time_limit") == 8
    note = ("Skipped because the time limit was reached: links to other sites, the sitemap check. Run again with Fast check "
            "off or a larger time limit.")
    assert note in render_markdown(result, outcome.gates, outcome.checks)
    report = build_report(result, outcome.gates, outcome.checks)
    assert report["crawl"]["skipped_for_time"] == ["other_site_links", "sitemap_check"]
    assert report["crawl"]["config"]["crawl_time_share"] == 1.0

    from maya_audit_web import strings, summary
    try:
        assert summary.skipped_note(report) == note
        strings.set_language("tr")
        assert summary.skipped_note(report) == ("Süre sınırına ulaşıldığı için atlandı: diğer sitelere bağlantılar, site "
                                                "haritası kontrolü. Hızlı kontrolü kapatıp veya daha uzun bir süre sınırıyla "
                                                "yeniden çalıştırın.")
    finally:
        strings.set_language("en")


def test_the_skip_order_and_a_stopped_audit_names_nothing():
    assert timeplan.SKIP_ORDER == ("other_site_links", "llms_links", "sitemap_check", "performance", "rendering")
    stopped = SimpleNamespace(stopped=True, collector_errors={"render": "overall audit deadline reached"})
    assert timeplan.skipped_for_time(stopped) == [] and timeplan.skipped_note([]) is None
    cut = SimpleNamespace(stopped=False, config={}, collector_errors={"performance": "overall audit deadline reached before this"},
                          render=SimpleNamespace(reason="overall audit deadline reached before all render samples completed"))
    assert timeplan.skipped_for_time(cut) == ["performance", "rendering"]


# -- (g) Fast check ---------------------------------------------------------------------------------------------------------

def config(*argv):
    return cli._crawl_config(cli._parser().parse_args(["crawl", KAFE + "/", *argv]))


def test_fast_check_gives_the_reduced_caps_and_leaves_the_rest_unchanged():
    normal, fast = config(), config("--fast")
    assert (normal.render_budget, normal.sitemap_check_max, normal.llms_link_checks_max, normal.image_checks_max,
            normal.external_link_checks_max, normal.fast_check) == (20, 100, 50, 30, 100, False)  # 100 in Quick (DECISIONS 294)
    assert (fast.render_budget, fast.sitemap_check_max, fast.llms_link_checks_max, fast.image_checks_max,
            fast.external_link_checks_max, fast.fast_check) == (6, 50, 20, 10, 30, True)
    # Unchanged: the page cap, robots.txt samples, ACC-4, redirect re-checks.
    for name in ("max_pages", "robots_samples", "robots_sample_interval_s", "ua_check_urls", "probes_enabled",
                 "redirect_recheck_attempts", "request_delay_s"):
        assert getattr(fast, name) == getattr(normal, name), name
    assert config("--fast", "--max-pages", "500").sitemap_check_max == 50 and config("--max-pages", "500").sitemap_check_max == 300  # DECISIONS 294
    # The estimate takes the smaller caps.
    assert fast.time_limit_s < normal.time_limit_s
    assert estimated_duration_s(50, 0, 1.0, True, 6, True, 50, external_link_cap(30, 20, 50)) < \
        estimated_duration_s(50, 0, 1.0, True, 20, True, 200, external_link_cap(100, 20, 50))
    assert "fast_check" in normal.snapshot()


def test_fast_check_sends_the_reduced_counts(clock):
    def counts(fast):
        options = dict(sitemap_check_max=50, llms_link_checks_max=20, image_checks_max=10, key_image_checks_max=15,
                       fast_check=True) if fast else {}
        result = audit(site(clock, pages=3, sitemap_only=80, llms=30, images=30), max_pages=4, robots_samples=1, **options).result
        purposes = [r.purpose for r in result.requests]
        return (purposes.count("sitemap_check"), purposes.count("llms_link_check"), purposes.count("image_status"),
                result.config["fast_check"])

    # The 30 images are the homepage's: every one is sized in a full audit (P1, key_image_checks_max 40); a fast check
    # sizes 15 of them plus a sample of 10.
    assert counts(False) == (80, 30, 30, False)
    assert counts(True) == (50, 20, 25, True)


def test_rendering_with_fast_check_samples_six_pages():
    from maya_audit.models import FetchClass
    from maya_audit.render import choose_render_sample

    from maya_audit.analysis import analyze_html

    pages = [SimpleNamespace(url=f"{KAFE}/" if kind == "home" else f"{KAFE}/{kind}/urun-{i}", fetch_class=FetchClass.OK, status=200, analysis=analyze_html(page()), headers={},
                             depth=0 if kind == "home" else 1, outlinks=[])
             for kind in ("home", "a", "b", "c", "d", "e", "f", "g", "h") for i in range(1 if kind == "home" else 2)]
    result = SimpleNamespace(pages=pages)
    assert len(choose_render_sample(result, config("--fast"), [])) == 6
    assert len(choose_render_sample(result, config(), [])) > 6


# -- (a) the table in the Markdown report, the web app and the PDF -------------------------------------------------------

def test_the_step_table_is_an_appendix_with_the_page_reader_as_its_own_row():
    steps = [{"step": "crawl", "started_at": "2026-10-15T10:00:00+00:00", "seconds": 146.2, "requests": 51, "waiting_s": 51.0},
             {"step": "sitemap_check", "started_at": "2026-10-15T10:03:00+00:00", "seconds": 12.0, "requests": 10, "waiting_s": 10.0}]
    firecrawl = {"used": True, "requests_sent": 47, "coverage": {"elapsed_s": 197.04}}
    lines = timeplan.markdown_lines(steps, firecrawl)
    assert lines[:4] == ["## Step timing", "", "| Step | Time | Requests | Of which waiting |", "|---|---|---|---|"]
    assert "| Reading pages | 2 min 26 s | 51 | 51.0 s |" in lines and "| Firecrawl page reader | 3 min 17 s | 47 | — |" in lines
    rows = timeplan.step_rows(steps, firecrawl)
    assert rows[-1] == {"step": "page_reader", "started_at": None, "seconds": 197.0, "requests": 47, "waiting_s": None}
    assert timeplan.step_rows(steps, {"used": False}) == steps

    from maya_audit_web import strings, summary
    report = {"crawl": {"steps": rows}}
    try:
        table = summary.step_table(report)
        assert table["columns"] == ["Step", "Time", "Requests", "Of which waiting"]
        assert table["rows"][0] == {"step": "crawl", "label": "Reading pages", "time": "2 min 26 s", "requests": "51", "waiting": "51.0 s"}
        strings.set_language("tr")
        table = summary.step_table(report)
        assert table["title"] == "Adım süreleri" and table["columns"] == ["Adım", "Süre", "İstekler", "Bunun bekleme süresi"]
        assert table["rows"][-1]["label"] == "Firecrawl sayfa okuyucu" and table["rows"][-1]["waiting"] == "—"
    finally:
        strings.set_language("en")
    assert summary.step_table({"crawl": {}}) is None


def test_the_audit_report_holds_the_steps_and_the_markdown_ends_with_the_table(clock):
    outcome = audit(site(clock, pages=3), max_pages=5, robots_samples=1)
    report = build_report(outcome.result, outcome.gates, outcome.checks)
    assert [row["step"] for row in report["crawl"]["steps"]][:2] == ["sitemap", "crawl"]
    markdown = render_markdown(outcome.result, outcome.gates, outcome.checks)
    assert "## Step timing" in markdown and markdown.index("## Integrity checks") < markdown.index("## Step timing") \
        < markdown.index("## Important limits")


# -- (h) the web switches ---------------------------------------------------------------------------------------------------

def test_the_web_switches_reach_the_command_line_and_the_fingerprint(web, monkeypatch):
    from maya_audit_web import runner

    seen = []
    real = cli._crawl_config

    def spy(args):
        seen.append((args.fast, args.no_external_links))
        return real(args)

    monkeypatch.setattr(runner.cli, "_crawl_config", spy)
    engine = runner.Engine()
    base = {"url": KAFE + "/", "mode": "quick", "key_pages": []}
    both = runner.crawl_config(engine, {**base, "switches": {"fast_check": True, "external_links": False}}, None, resume=False)
    assert seen[-1] == (True, True) and both.fast_check and not both.check_external_links and both.sitemap_check_max == 50
    plain = runner.crawl_config(engine, base, None, resume=False)
    assert seen[-1] == (False, False) and not plain.fast_check and plain.check_external_links
    # The estimate takes the smaller caps.
    assert runner.plan_shape(engine, "quick", [], {"fast_check": True})["up_to_minutes"] < runner.plan_shape(engine, "quick", [])["up_to_minutes"]

    from test_web_app import plan, start
    client = web()
    default = plan(client)
    named = plan(client, fast_check=False, external_links=True)
    fast = plan(client, fast_check=True)
    no_links = plan(client, external_links=False)
    assert default["fingerprint"] == named["fingerprint"]  # the defaults leave a plan's fingerprint as it was
    assert len({default["fingerprint"], fast["fingerprint"], no_links["fingerprint"]}) == 3  # a changed switch is a new plan
    assert default["switches"]["fast_check"] is False and default["switches"]["external_links"] is True
    assert fast["switches"]["fast_label"] == "Fast check" and "6 pages instead of 20" in fast["switches"]["fast_help"]
    assert no_links["switches"]["external_links"] is False
    assert default["switches"]["external_help"] == f"Check links to other sites (one light request each, at most {default['switches']['external_cap']})."
    done = start(client, fast)
    report = client.get(f"/api/v1/audits/{done['id']}/result")
    assert report.status_code == 200, report.text
    saved = report.json()
    assert saved["crawl"]["config"]["fast_check"] is True and saved["crawl"]["config"]["sitemap_check_max"] == 50
    assert saved["crawl"]["steps"] and saved["crawl"]["steps"][0]["step"] == "sitemap"
    view = client.get(f"/api/v1/audits/{done['id']}/summary").json()
    assert view["coverage"]["steps"]["columns"] == ["Step", "Time", "Requests", "Of which waiting"]
    printed = client.get(f"/api/v1/audits/{done['id']}/print?full=true")
    assert printed.status_code == 200 and "Step timing" in printed.text
