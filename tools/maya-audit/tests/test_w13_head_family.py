"""DECISIONS 278 (T8, T9): tags after a body element that ended <head> early are said once, under TSEO-1, and a canonical
there is "not judged", never "absent". Offline fake site, the real audit and report, the release gate on the result."""
from dataclasses import replace

from fakeserver import FakeServer, Response, Site
from maya_audit import release_gate
from maya_audit.audit import run_audit
from maya_audit.config import CrawlConfig
from maya_audit.report import build_report
from test_deadline_hosted_hardening import QUIET
from test_review_fixes import TR, links, page

WIDGET = '<div id="a11y-overlay"></div>'


def broken_head(base_path, title):
    # The widget is printed inside <head>; everything after it is read as body by browsers and by Google.
    return page(f"<h1>{title}</h1><p>{TR}</p>", head=(
        WIDGET + f'<link rel="canonical" href="{base_path}"><meta name="robots" content="index,follow">'
        f'<meta name="description" content="{title} sayfası"><meta property="og:title" content="{title}">'
        f'<meta property="og:description" content="{title} sayfası">'))


def audit():
    routes = {"/robots.txt": Response(body="User-agent: *\nAllow: /\n", content_type="text/plain"),
              "/": page(f"<h1>Ana sayfa</h1><p>{TR}</p>" + links(["/hesaplar/", "/kartlar/", "/temiz/"]),
                        head='<meta property="og:title" content="Ana sayfa"><meta name="description" content="Ana">'),
              "/hesaplar/": broken_head("/hesaplar/", "Hesaplar"),
              "/kartlar/": broken_head("/kartlar/", "Kartlar"),
              "/temiz/": page(f"<h1>Temiz</h1><p>{TR}</p>", head='<link rel="canonical" href="/temiz/">')}
    with FakeServer(Site(routes)) as fake:
        outcome = run_audit(fake.base_url + "/", replace(CrawlConfig(), **QUIET))
    report = build_report(outcome.result, outcome.gates, outcome.checks)
    return outcome, report, fake.base_url


def test_tags_after_early_head_close_are_one_finding():
    outcome, report, base = audit()
    broken = {base + "/hesaplar/", base + "/kartlar/"}
    by_check = {c.check_id: c for c in outcome.checks}
    [head] = [f for f in by_check["TSEO-1"].findings if "end <head> early" in f.title]
    assert set(head.scope["urls"]) == broken and head.severity.value == "S2"
    said = {(row["check_id"], row["element"]) for row in head.evidence["absorbed_from"]}
    assert {("STR-10", "og:title"), ("STR-10", "description"), ("ACC-3", "robots")} <= said
    for f in by_check["STR-10"].findings + by_check["ACC-3"].findings:
        # og:image is really missing on these pages (no tag at all): STR-10 still says so, correctly.
        if any(k in f.title for k in ("have no og:title", "have no og:description", "no meta description", "robots tag outside")):
            assert not broken & set(f.scope["urls"]), f.title
    assert head.dedup_key == "head_closed_early:div#a11y-overlay"
    assert [v for v in release_gate.check_report(report) if v["rule"] in ("RG-9", "RG-10")] == []  # said once, no gap


def test_canonical_after_early_close_is_not_assessed_not_absent():
    outcome, report, base = audit()
    [idx4] = [c for c in report["checks"] if c["check_id"] == "IDX-4"]
    [gap] = [p for p in idx4["coverage"]["not_assessed"] if p.get("element") == "canonical"]
    assert gap["count"] == 2 and set(gap["urls"]) == {base + "/hesaplar/", base + "/kartlar/"} and gap["reason"]
    assert idx4["status"] != "pass"  # a part was not assessed: partial, never a pass


def test_a_finding_that_still_says_absent_where_not_measured_is_caught():
    """If any check reports the canonical absent on such a page, the gate says it was never measured (RG-10)."""
    outcome, report, base = audit()
    report["checks"][0]["findings"].append({
        "id": "X-absent", "check_id": "X", "severity": "Info", "scope": {"urls": [base + "/hesaplar/"]}, "evidence": {"x": 1},
        "measurement": {"claims": [{"element": "canonical", "state": "absent", "urls": [base + "/hesaplar/"]}]}})
    out = [v for v in release_gate.check_report(report) if v["rule"] == "RG-10" and v.get("finding_id") == "X-absent"]
    assert out and "could not be measured" in out[0]["message"]
