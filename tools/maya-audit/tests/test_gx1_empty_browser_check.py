"""IDX-1 empty pages, corroborated by a second client (first review C1/C2; live Adile run: 57 URLs empty to Maya's own
user agent, read fine by another reader). Before two empty answers to Maya's client are called empty pages (S1/S2), at
most three of them are asked once more with a browser user agent."""

from __future__ import annotations

from fakeserver import FakeServer
from fakeserver.scenarios import page, robots, sitemap
from maya_audit.audit import run_audit
from maya_audit.config import EMPTY_BROWSER_CHECK_URLS, CrawlConfig
from maya_audit.index_data import EMPTY_CHECK_PURPOSE
from maya_audit.probes import BROWSER_USER_AGENT
from fakeserver.server import Response, Site

FAST = {"request_delay_s": 0.0, "robots_sample_interval_s": 0.05, "probe_retry_cooldown_s": 0.0, "refetch_delay_s": 0.0,
        "render_enabled": False, "prf_round_gap_s": 0.0, "max_pages": 30}
TEXT = ("Kettles boil water quickly and switch themselves off. This page describes one kettle, its capacity, its "
        "warranty and how to descale it so it lasts for years. ") * 4
EMPTY = [f"/urun/{n}" for n in range(1, 6)]


def site(browser_gets_content: bool, disallow: str = "") -> Site:
    def product(site, request):
        if browser_gets_content and request.user_agent == BROWSER_USER_AGENT:
            return Response(body=f"<!doctype html><html><head><title>Kettle</title></head><body><p>{TEXT}</p></body></html>")
        return Response(200, "")

    routes = {"/robots.txt": robots(f"User-agent: *\nAllow: /\n{disallow}\nSitemap: {{base}}/sitemap.xml\n"),
              "/sitemap.xml": sitemap("/", *EMPTY),
              "/": page("Home", *EMPTY, extra=f"<p>{TEXT}</p>"),
              **{path: product for path in EMPTY}}
    return Site(routes)


def int4(outcome) -> str:
    return next(g.state for g in outcome.gates if g.check_id == "INT-4")


def audit(**kwargs):
    with FakeServer(site(**kwargs)) as server:
        outcome = run_audit(server.base_url + "/", CrawlConfig(**FAST))
        requests = list(server.requests)
    checks = {c.check_id: c for c in outcome.checks}
    empties = [f for f in checks["IDX-1"].findings if "empty page" in f.title]
    asked = [r for r in requests if r.user_agent == BROWSER_USER_AGENT and r.path.startswith("/urun/")]
    return outcome, empties, asked


def test_content_to_a_browser_makes_it_a_bot_specific_s3_not_empty_pages():
    outcome, empties, asked = audit(browser_gets_content=True)
    [finding] = empties
    assert "automated clients only" in finding.title and finding.severity.value == "S3"
    assert len(finding.scope["_all_urls"]) == len(EMPTY)
    check = finding.evidence["browser_check"]
    assert check["purpose"] == EMPTY_CHECK_PURPOSE and check["answers"][0]["content"]
    # At most three browser requests, each tagged, and INT-4 stays compliant.
    assert 1 <= len(asked) <= EMPTY_BROWSER_CHECK_URLS
    assert all(r.headers.get("x-maya-probe") == "ua-differential" for r in asked)
    assert int4(outcome) == "compliant"


def test_empty_to_a_browser_too_keeps_the_empty_page_verdict():
    outcome, empties, asked = audit(browser_gets_content=False)
    assert [f.severity.value for f in empties] == ["S2"] and "automated clients only" not in empties[0].title
    assert empties[0].evidence["browser_check"]["verdict"] == "a browser got an empty page too"
    assert len(asked) == EMPTY_BROWSER_CHECK_URLS and int4(outcome) == "compliant"


def test_not_asked_as_a_browser_stays_s3():
    # With requests under other user agents switched off, two empty answers to Maya's client are not confirmed.
    with FakeServer(site(browser_gets_content=True)) as server:
        outcome = run_audit(server.base_url + "/", CrawlConfig(**{**FAST, "probes_enabled": False}))
        asked = [r for r in server.requests if r.user_agent == BROWSER_USER_AGENT]
    idx1 = next(c for c in outcome.checks if c.check_id == "IDX-1")
    [finding] = [f for f in idx1.findings if "empty page" in f.title]
    assert finding.severity.value == "S3" and asked == []
    assert finding.evidence["observation_strength"] == "repeated_empty_same_client_only"
    assert "switched off" in finding.evidence["browser_check"]["reason"]


def test_a_mixed_browser_sample_puts_each_page_where_its_own_answer_says():
    """One page a browser reads, one it gets empty too, one not asked: three different verdicts."""
    from types import SimpleNamespace as NS

    from maya_audit.checks.index import _empty_pages
    from maya_audit.models import FetchClass

    base = "https://cafe.example"
    urls = [base + p for p in ("/a", "/b", "/c")]
    pages = [NS(url=u, depth=1, status=200, body_bytes=0, content_type="text/html", requested_at="2026-10-19T01:00:00Z",
                analysis={"empty_response": True}, fetch_class=FetchClass.OK) for u in urls]
    again = {"status": 200, "body_bytes": 0, "empty_response": True, "requested_at": "2026-10-19T01:01:00Z"}
    answers = [{"url": urls[0], "sent": True, "status": 200, "empty_response": False, "content": True},
               {"url": urls[1], "sent": True, "status": 200, "empty_response": True, "content": False}]
    data = NS(refetches=[{"url": u, "refetch": again} for u in urls], sitemap_check=NS(rows=[], llms_rows=[]),
              empty_browser_check={"answers": answers, "cap": 3})
    result = NS(pages=pages, start_url=base + "/", origin=base)
    findings = _empty_pages(result, CrawlConfig(), data, set(), [])
    where = {u.rsplit("/", 1)[-1]: (f.severity.value, "automated clients only" in f.title, f.evidence["observation_strength"])
             for f in findings for u in f.scope["_all_urls"]}
    assert where == {"a": ("S3", True, "repeated_empty_to_maya_content_to_a_browser"),
                     "b": ("S2", False, "repeated_empty"),
                     "c": ("S3", False, "repeated_empty_mixed_browser_sample")}
    assert all("_state" not in row for f in findings for row in f.evidence["pages"])
