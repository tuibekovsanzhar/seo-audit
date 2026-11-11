"""DECISIONS 278 (T3, T11 and the broken-link cases): a broken internal link names the page to edit, keeps the error
address apart, and its second look re-tests the claim where it is (the source still links, the target still fails).
Offline fake site, the real audit and report, the release gate on the result."""
from dataclasses import replace

from fakeserver import FakeServer, Response, Site
from maya_audit import release_gate
from maya_audit.audit import run_audit
from maya_audit.config import CrawlConfig
from maya_audit.report import build_report
from test_deadline_hosted_hardening import QUIET
from test_review_fixes import TR, links, page

PLACEHOLDER = "/{shop_link_en}"


def audit(**cfg):
    routes = {"/robots.txt": Response(body="User-agent: *\nAllow: /\nSitemap: /sitemap.xml\n", content_type="text/plain"),
              "/sitemap.xml": Response(body="<?xml version='1.0'?><urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>"
                                            "<url><loc>{base}/</loc></url><url><loc>{base}/eski-kampanya</loc></url></urlset>",
                                       content_type="application/xml"),
              "/": page(f"<h1>Ana sayfa</h1><p>{TR}</p>" + links(["/en", "/hakkimizda"])),
              "/en": page(f"<h1>English</h1><p>{TR}</p><a href=\"{PLACEHOLDER}\">{{shop}}</a>"),
              PLACEHOLDER: Response(302, "", headers={"Location": "/404?from=" + PLACEHOLDER}),
              "/404": Response(404, "<html><title>Bulunamadı</title><body>Yok</body></html>"),
              "/eski-kampanya": Response(302, "", headers={"Location": "/404"}),
              "/hakkimizda": page(f"<h1>Hakkımızda</h1><p>{TR}</p>")}
    site = Site(routes)
    with FakeServer(site) as fake:
        site.routes["/sitemap.xml"] = Response(body=routes["/sitemap.xml"].body.replace("{base}", fake.base_url),
                                               content_type="application/xml")
        outcome = run_audit(fake.base_url + "/", replace(CrawlConfig(), **{**QUIET, "verification_enabled": True, **cfg}))
    return outcome, build_report(outcome.result, outcome.gates, outcome.checks), fake.base_url


def broken(outcome, rule="idx1.4xx.referenced"):
    [f] = [f for c in outcome.checks for f in c.findings if (f.rule_id or "").startswith(rule)]
    return f


def test_error_page_target_is_not_confirmed_but_the_source_is_retested():
    outcome, report, base = audit()
    f = broken(outcome)
    assert f.severity.value == "S2"  # the severity stays the engine's
    # The page to edit is the page whose link fails, never the error page. The sitemap entry that ends at the error is
    # its own finding since DECISIONS 337, with the same severity.
    assert f.scope["urls"] == [base + "/en"]
    assert f.evidence["target_urls"] == [f.evidence["link_sources"][0]["target"]]
    [row] = f.evidence["link_sources"]
    assert row["source"] == base + "/en" and row["links_to"] == base + PLACEHOLDER
    v = f.verification
    assert v["state"] == "confirmed" and v["subjects"] == [base + "/en"]
    assert v["checked"][0]["url"] == base + "/en" and v["checked"][0]["link_present"] is True
    assert 400 <= v["checked"][0]["target_status"] < 500
    entry = broken(outcome, "idx1.4xx.sitemap_only")
    assert entry.severity.value == "S2" and entry.scope["urls"] == entry.evidence["sitemap_only"] == [base + "/eski-kampanya"]
    assert entry.evidence["target_urls"] == [base + "/404"]  # where the entry ends: the error page, apart from the entry
    assert entry.verification["state"] == "confirmed" and entry.verification["subjects"] == [base + "/eski-kampanya"]
    assert [x for x in release_gate.check_report(report) if x["rule"] == "RG-4"] == []


def test_a_sitemap_url_that_redirects_to_the_error_page_is_not_found():
    outcome, report, base = audit()
    [idx5] = [c for c in outcome.checks if c.check_id == "IDX-5"]
    rows = [r for f in idx5.findings for r in (f.evidence.get("bad_urls") or []) if r["url"] == base + "/eski-kampanya"]
    if not rows:  # the crawl read it itself: IDX-1 then reports it beside the sitemap row
        rows = [r for f in idx5.findings for r in (f.evidence.get("sitemap_decisions") or []) if r.get("url") == base + "/eski-kampanya"]
    assert rows, "the listed address that ends in a 404 is reported"
    assert rows[0].get("kind") in ("not_found", None) and rows[0].get("kind") != "redirect"


def test_every_high_finding_has_a_verification_state():
    """T11: every High finding leaves the audit with a state; one no second look reached says why."""
    outcome, report, base = audit()
    highs = [f for c in report["checks"] for f in c["findings"] if f["severity"] in ("S1", "S2")]
    assert highs and all((f.get("verification") or {}).get("state") in release_gate.STATES for f in highs)
    untested = [f for f in highs if f["verification"]["state"] == "not_retested"]
    assert all(f["verification"]["reason"] for f in untested)
    assert [x for x in release_gate.check_report(report) if x["rule"] == "RG-5"] == []


def test_switched_off_still_says_not_retested():
    outcome, report, base = audit(verification_enabled=False)
    highs = [f for c in report["checks"] for f in c["findings"] if f["severity"] in ("S1", "S2")]
    assert highs and {f["verification"]["state"] for f in highs} == {"not_retested"}
    # The re-testable one says the stage was off; the others that their rule has no re-test. Both are true.
    links = [f for f in highs if f["rule_id"].startswith("idx1.4xx")]  # the link and the sitemap entry (DECISIONS 337)
    assert len(links) == 2 and all(f["verification"]["reason"].startswith("switched off") for f in links)
    assert all(f["verification"]["reason"] == "no re-test for this rule" for f in highs if f not in links)
