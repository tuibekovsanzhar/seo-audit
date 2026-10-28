"""docs/FIXTURE-MATRIX.md is generated; this keeps it current and keeps every check named by at least one test."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import fixture_matrix  # noqa: E402


def test_the_matrix_file_matches_the_tests():
    assert fixture_matrix.OUT.read_text(encoding="utf-8") == fixture_matrix.render(), \
        "run: .venv/bin/python scripts/fixture_matrix.py"


def test_every_check_is_named_by_a_test_and_the_new_checks_have_both_sides():
    found = fixture_matrix.tests_by_check()
    assert [check for check in fixture_matrix.known_checks() if not (found[check]["finds"] or found[check]["quiet"])] == []
    for check in ("STR-16", "STR-17"):
        assert found[check]["finds"] and len(found[check]["quiet"]) >= 2, check


def test_the_matrix_lists_the_checks_a_real_audit_reports():
    from maya_audit.audit import run_audit
    from maya_audit.config import CrawlConfig
    from maya_audit_web import demo
    outcome = run_audit("http://demo-kafe.localhost/", CrawlConfig(max_pages=5, **demo.OVERRIDES), demo.site_transport(0))
    reported = {c.check_id for c in outcome.checks} | {g.check_id for g in outcome.gates}
    assert reported == set(fixture_matrix.known_checks())
