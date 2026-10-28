"""Review fixes of package W3 (index checks and one cause, one finding): H09, H10, H13, H20, H22 (B02/B03), B12, B16
(C21), B17 (C22) and CR-28. Each test is one site, or one function, with the defect the review found."""

from __future__ import annotations

from types import SimpleNamespace

from fakeserver import FakeServer
from fakeserver.scenarios import page, robots, sitemap
from fakeserver.server import Response, Site
from maya_audit.audit import run_audit
from maya_audit.checks.index import idx2_tls
from maya_audit.checks.integrity import int2_crawl_completeness
from maya_audit.config import CrawlConfig
from maya_audit.index_data import address_pairs, canonical_variant
from maya_audit.report import build_report

FAST = {"request_delay_s": 0.0, "robots_sample_interval_s": 0.05, "probe_retry_cooldown_s": 0.0, "refetch_delay_s": 0.0,
        "render_enabled": False, "prf_round_gap_s": 0.0}
TEXT = ("Kettles boil water quickly and switch themselves off. This page describes one kettle, its capacity, its "
        "warranty and how to descale it so it lasts for years. ") * 4


class Audit:
    def __init__(self, routes: dict, **config) -> None:
        with FakeServer(Site(routes)) as server:
            self.base = server.base_url
            self.outcome = run_audit(server.base_url + "/", CrawlConfig(**{**FAST, "max_pages": 40, **config}))
        self.by_id = {check.check_id: check for check in self.outcome.checks}
        self.findings = [f for check in self.outcome.checks for f in check.findings]

    def paths(self, finding) -> set[str]:
        return {u.replace(self.base, "") or "/" for u in finding.scope.get("_all_urls") or finding.scope.get("urls") or []}

    def titled(self, check_id: str, words: str) -> list:
        return [f for f in self.by_id[check_id].findings if words in f.title]


def doc(title: str | None, body: str, head: str = "") -> Response:
    title_tag = f"<title>{title}</title>" if title is not None else ""
    return Response(body=f"<!doctype html><html lang='en'><head>{title_tag}{head}</head><body><main>{body}</main></body></html>")


# -- H10: one dead URL is one finding ----------------------------------------------------------------------------------

def test_a_dead_target_linked_from_four_pages_is_one_finding_with_its_sources():
    routes = {"/robots.txt": robots("User-agent: *\nAllow: /\n"),
              "/": page("Home", "/a", "/b", "/c", extra=f"<p>{TEXT}</p>"),
              **{f"/{name}": page(name.upper(), "/gone", "/", extra=f"<p>{name} {TEXT}</p>") for name in "abc"},
              "/gone": Response(404, "<html><title>Not found</title></html>")}
    routes["/"] = page("Home", "/a", "/b", "/c", "/gone", extra=f"<p>{TEXT}</p>")
    run = Audit(routes)
    dead = [f for f in run.findings if "/gone" in run.paths(f) or "/gone" in str(f.evidence.get("target"))
            or "/gone" in str(f.evidence.get("target_urls"))]
    assert len(dead) == 1, [f.title for f in dead]
    [finding] = dead
    assert finding.check_id == "IDX-1" and finding.title.endswith("; linked from 4 page(s)")
    # DECISIONS 278: the scope is the four pages to edit; the dead URL is the target, kept apart.
    assert run.paths(finding) == {"/", "/a", "/b", "/c"}
    assert [u.replace(run.base, "") for u in finding.evidence["target_urls"]] == ["/gone"]
    [row] = finding.evidence["broken_links"]
    assert row["target"].endswith("/gone") and row["status"] == 404 and row["linked_from_count"] == 4
    idx6 = run.by_id["IDX-6"]
    assert not [f for f in idx6.findings if f.title.startswith("Link target returns")]
    assert "1 broken target(s) are said under IDX-1" in idx6.summary
    # The headline and the priority list count the dead URL once.
    report = build_report(run.outcome.result, run.outcome.gates, run.outcome.checks)
    by_id = {f["id"]: f for check in report["checks"] for f in check["findings"]}
    listed = [i for i in report["findings_in_priority_order"]
              if "/gone" in str(by_id[i]["scope"]) + str(by_id[i]["title"]) + str(by_id[i]["evidence"].get("target_urls"))]
    assert listed == [finding.id]


# -- H09: Cloudflare's e-mail obfuscation ------------------------------------------------------------------------------

def test_an_address_hidden_by_cloudflare_without_a_link_is_a_note():
    routes = {"/robots.txt": robots("User-agent: *\nAllow: /\n"),
              "/": page("Home", "/contact", extra=f"<p>{TEXT}</p>"),
              "/contact": doc("Contact", f"<p>Write to <span class='__cf_email__' data-cfemail='7a1b'>[email&#160;protected]</span></p><p>{TEXT}</p>")}
    run = Audit(routes)
    [note] = run.titled("IDX-6", "Cloudflare e-mail obfuscation")
    assert note.severity.value == "Info" and run.paths(note) == {"/contact"}
    assert not [f for f in run.by_id["IDX-1"].findings if "4xx" in f.title]


# -- H13: drafts, and pages that only look like them ------------------------------------------------------------------

def test_a_demo_page_with_a_title_and_links_is_not_a_draft():
    routes = {"/robots.txt": robots("User-agent: *\nAllow: /\n\nSitemap: {base}/sitemap.xml\n"),
              "/sitemap.xml": sitemap("/", "/request-demo", "/deneme-1"),
              "/": page("Home", "/request-demo", extra=f"<p>{TEXT}</p>"),
              "/request-demo": page("Request a demo", "/", extra=f"<p>{TEXT}</p>"),
              "/deneme-1": doc(None, f"<p>{TEXT}</p>")}
    run = Audit(routes)
    [drafts] = run.titled("IDX-5", "draft or test page(s)")
    assert run.paths(drafts) == {"/deneme-1"} and "noindex" in drafts.how_to_fix
    assert not [f for f in run.by_id["IDX-7"].findings if "/deneme-1" in run.paths(f)]
    assert not [f for f in run.by_id["STR-1"].findings if "/deneme-1" in run.paths(f)]
    assert "draft or test pages reported under IDX-5" in run.by_id["STR-1"].summary


# -- H20: one page at two addresses ------------------------------------------------------------------------------------

def test_one_page_in_two_letter_cases_is_one_pair_and_not_a_shared_title():
    about = page("About us", "/", extra=f"<p>{TEXT}</p>")
    routes = {"/robots.txt": robots("User-agent: *\nAllow: /\n"),
              "/": page("Home", "/About", "/about", extra=f"<p>Home {TEXT}</p>"),
              "/About": about, "/about": about}
    run = Audit(routes)
    [pair] = run.titled("IDX-8", "reachable at two addresses")
    assert run.paths(pair) == {"/About", "/about"} and pair.severity.value == "S4"
    assert pair.evidence["pairs"][0]["differs_in"] == "letter case"
    assert not run.titled("STR-1", "are shared by") and "one page at two addresses" in run.by_id["STR-1"].summary
    assert not [f for f in run.by_id["IDX-8"].findings if "copies" in f.title or "identical" in f.title]


def test_address_pairs_need_the_same_text():
    def fake(url, digest):
        return SimpleNamespace(url=url, analysis={"text_sha256": digest})
    pairs = address_pairs([fake("https://ex.com/Hesabim.aspx", "a"), fake("https://ex.com/Hesabim", "a"),
                           fake("https://ex.com/sepet.php", "b"), fake("https://ex.com/sepet", "c")])
    assert pairs == [{"urls": ["https://ex.com/Hesabim", "https://ex.com/Hesabim.aspx"], "kept": "https://ex.com/Hesabim",
                      "other": "https://ex.com/Hesabim.aspx", "differs_in": "file extension"}]


# -- H22 / B02 / B03: canonicals ---------------------------------------------------------------------------------------

def test_a_canonical_on_the_http_or_www_variant_is_judged_as_the_same_address():
    assert canonical_variant("http://ex.com/a", "https://ex.com/a") == {"counterpart": "https://ex.com/a", "differs_in": "scheme"}
    assert canonical_variant("https://www.ex.com/b?x=1", "https://ex.com/a") == {"counterpart": "https://ex.com/b?x=1", "differs_in": "www"}
    assert canonical_variant("http://www.ex.com/a", "https://ex.com/a")["differs_in"] == "scheme and www"
    assert canonical_variant("https://ex.com:8443/a", "https://ex.com/a") is None
    assert canonical_variant("https://other.com/a", "https://ex.com/a") is None
    assert canonical_variant("https://ex.com/a", "https://ex.com/a") is None


def test_canonical_variant_noindex_conflict_and_two_canonicals():
    routes = {"/robots.txt": robots("User-agent: *\nAllow: /\n"),
              "/": page("Home", "/variant", "/upgrade", "/mixed", "/two", "/target", extra=f"<p>{TEXT}</p>"),
              # The www variant of this very address: IDX-4 names it, and the page stays in every content check.
              "/variant": doc("Variant", f"<p>variant {TEXT}</p>", head='<link rel="canonical" href="http://www.{host}/variant">'),
              # The https:// address of an http:// page: the better address, not reported.
              "/upgrade": doc("Upgrade", f"<p>upgrade {TEXT}</p>", head='<link rel="canonical" href="https://{host}/upgrade">'),
              "/mixed": doc("Mixed", f"<p>{TEXT}</p>", head='<meta name="robots" content="noindex"><link rel="canonical" href="/target">'),
              "/two": doc("Two", f"<p>{TEXT}</p>", head='<link rel="canonical" href="/target"><link rel="canonical" href="/other">'),
              "/target": doc("Target", f"<p>{TEXT}</p>")}
    with FakeServer(Site({k: v for k, v in routes.items()})) as server:
        host = server.base_url.split("://", 1)[1]
        for key in ("/variant", "/upgrade"):
            routes[key].body = routes[key].body.replace("{host}", host)
        run = Audit.__new__(Audit)
        run.base = server.base_url
        run.outcome = run_audit(server.base_url + "/", CrawlConfig(**{**FAST, "max_pages": 40}))
    run.by_id = {check.check_id: check for check in run.outcome.checks}
    idx4 = run.by_id["IDX-4"]
    [variant] = run.titled("IDX-4", "http:// or www variant")
    assert run.paths(variant) == {"/variant"} and variant.severity.value == "S3"
    assert variant.evidence["pages"][0]["judged_as"] == run.base + "/variant"
    [mixed] = run.titled("IDX-4", "noindex and declare a canonical")
    assert run.paths(mixed) == {"/mixed"} and mixed.severity.value == "S3"
    [conflict] = run.titled("IDX-4", "conflicting canonicals")
    assert run.paths(conflict) == {"/two"}
    # Two canonicals: neither is judged as the chosen one.
    assert not [f for f in idx4.findings if "canonicalized" in f.title and "/two" in run.paths(f)]
    assert any(row["url"].endswith("/two") for row in idx4.evidence["not_assessed"])
    assert not [f for f in idx4.findings + idx4.review_items if "/upgrade" in run.paths(f)]
    # The variant-canonical page is not silently dropped from the content checks.
    from maya_audit.structure_data import indexable_pages
    kept = {p.url.replace(run.base, "") for p in indexable_pages(run.outcome.result)}
    assert {"/variant", "/upgrade"} <= kept and "/mixed" not in kept
    assert any("no canonical" in o["metric"] for o in idx4.observations)


# -- B12: a temporary http -> https redirect ---------------------------------------------------------------------------

def _hosts(status: int) -> list[dict]:
    return [{"host": "ex.com", "role": "start",
             "tls": {"host": "ex.com", "port": 443, "valid": True, "days_left": 200, "not_after": "2027-05-01"},
             "http_redirect": {"checked": True, "http_url": "http://ex.com/", "status": status, "location": "https://ex.com/",
                               "redirects_to_https": True}}]


def test_a_302_from_http_to_https_is_a_temporary_redirect_finding():
    cfg = CrawlConfig()
    for status, expected in ((301, []), (308, []), (302, ["S4"]), (307, ["S4"])):
        result = SimpleNamespace(index=SimpleNamespace(hosts=_hosts(status), variant_note=None))
        check = idx2_tls(result, cfg)
        found = [f.severity.value for f in check.findings if "temporary redirect" in f.title]
        assert found == expected, (status, [f.title for f in check.findings])
        assert not [f for f in check.findings if f.title.startswith("No HTTP to HTTPS redirect")]


# -- B16: empty pages leave the crawl incomplete -----------------------------------------------------------------------

def test_an_empty_page_makes_the_crawl_incomplete_and_no_page_is_called_an_orphan():
    routes = {"/robots.txt": robots("User-agent: *\nAllow: /\n\nSitemap: {base}/sitemap.xml\n"),
              "/sitemap.xml": sitemap("/", "/hub", "/deep"),
              "/": page("Home", "/hub", extra=f"<p>{TEXT}</p>"),
              "/hub": Response(200, ""),  # its links would have led to /deep
              "/deep": doc("Deep", f"<p>{TEXT}</p>")}
    run = Audit(routes)
    int2 = int2_crawl_completeness(run.outcome.result, CrawlConfig(**FAST))
    assert int2.state == "incomplete" and "1 page(s) answered with an empty page" in int2.summary
    assert int2.evidence["empty_pages"]["count"] == 1
    assert not [f for f in run.by_id["IDX-7"].findings if "listed only in the sitemap" in f.title]


# -- B17: one server error not asked again ------------------------------------------------------------------------------

def test_a_single_server_error_beyond_the_refetch_cap_is_an_estimated_finding():
    routes = {"/robots.txt": robots("User-agent: *\nAllow: /\n"),
              "/": page("Home", "/broken", extra=f"<p>{TEXT}</p>"),
              "/broken": Response(500, "<html><title>Error</title></html>")}
    run = Audit(routes, max_refetches=0, prf_enabled=False)  # no refetch and no extra rounds: one request only
    assert not run.titled("IDX-1", "on every attempt")
    [finding] = run.titled("IDX-1", "on the one request made")
    assert finding.severity.value == "S3" and finding.confidence.value == "estimated"
    assert run.paths(finding) == {"/broken"} and finding.evidence["observation_strength"] == "single_observation"
    assert not [o for o in run.by_id["IDX-1"].observations if o.get("metric", "").startswith("failure not fetched again")]
