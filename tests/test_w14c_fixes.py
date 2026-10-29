"""Fixes after the 2026-10-29 client PDFs (DECISIONS 284). Hand-written pages; offline, in memory."""
from __future__ import annotations

from maya_audit import verification
from maya_audit.checks.structure import str2_headings
from maya_audit.severity import apply as apply_severity
from test_false_alarms import CFG, TR, html, site


# ------------------------------------------------------------------ (3) a hidden homepage <h1> is at most Medium


def test_a_hidden_homepage_h1_is_medium_because_nothing_re_tests_it():
    assert "str2.home_hidden_h1" not in verification.RETESTS  # if a re-test is added, revisit the cap
    result, pages = site({"/": html('<h1 style="display:none">Örnekmağaza</h1>' + f"<p>{TR}</p>"),
                          "/a": html("<h1>A</h1>")})
    check = str2_headings(result, CFG, pages, set(), set())
    apply_severity([check], result)
    [hidden] = [f for f in check.findings if f.title == "The homepage's only <h1> is hidden"]
    assert hidden.severity.value == "S3"
