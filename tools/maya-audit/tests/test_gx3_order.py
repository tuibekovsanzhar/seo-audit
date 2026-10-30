"""Findings on the homepage or a key page come before others of the same severity, in every output (gx3, item 5)."""

from maya_audit.findings import Finding, Severity, page_importance, priority_key, scope_for
from maya_audit.models import Confidence


def _f(title, urls, severity=Severity.S3, tier=2):
    return Finding("STR-1", title, severity, Confidence.VERIFIED, "Documented", [], scope_for(urls), {}, "x", "y",
                   importance_tier=tier)


def test_the_homepage_counts_as_a_key_page_for_ordering_only():
    home = _f("home", ["https://e.com/"])
    assert home.importance_tier == 2 and page_importance(home) == 0
    assert page_importance(_f("deep", ["https://e.com/a", "https://e.com/?q=1"])) == 2
    assert page_importance({"importance_tier": 1, "scope": {"urls": ["https://e.com"]}}) == 0
    assert page_importance({"importance_tier": 0, "scope": {}}) == 0


def test_engine_order_puts_homepage_and_key_page_findings_first_within_a_severity():
    many = _f("many", [f"https://e.com/p{i}" for i in range(40)])
    key = _f("key", ["https://e.com/k"], tier=0)
    home = _f("home", ["https://e.com/"])
    s2 = _f("s2", ["https://e.com/z"], severity=Severity.S2)
    assert [f.title for f in sorted([many, key, home, s2], key=priority_key)] == ["s2", "key", "home", "many"]


def _row(rid, severity, importance, pages):
    return {"id": rid, "severity": severity, "confidence": "verified", "importance": importance, "pages_total": pages,
            "estimates": {"effort": "S"}}


def test_web_order_puts_importance_before_page_count_and_after_severity():
    from maya_audit_web.action_priority import ordered
    rows = [_row("many", "S3", 2, 40), _row("home", "S3", 0, 1), _row("s4home", "S4", 0, 1), _row("s2", "S2", 2, 1)]
    assert [r["id"] for r in ordered(rows)] == ["s2", "home", "many", "s4home"]

