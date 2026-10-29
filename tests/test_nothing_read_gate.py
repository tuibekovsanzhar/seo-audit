"""DECISIONS 287: a report that read no page is not delivered as a result (release gate RG-14, hard)."""
from __future__ import annotations

from maya_audit import release_gate


def report(pages_read):
    return {"checks": [], "audit_status": {"content_coverage": {"pages_read": pages_read, "level": "none" if not pages_read else "partial"}}}


def test_zero_pages_read_blocks_delivery_with_its_reason():
    record = release_gate.run(report(0))
    assert record["decision"] == release_gate.BLOCKED
    [v] = [v for v in record["violations"] if v["rule"] == "RG-14"]
    assert v["hard"] and v["message"].startswith("site content could not be read")


def test_one_page_read_is_not_blocked_by_it():
    assert not [v for v in release_gate.check_report(report(1)) if v["rule"] == "RG-14"]


def test_a_report_without_a_coverage_record_is_not_judged_on_it():
    """Older reports have no content_coverage; RG-14 says nothing rather than guessing."""
    assert not [v for v in release_gate.check_report({"checks": []}) if v["rule"] == "RG-14"]


def test_the_summary_table_counts_it():
    assert "Site content could not be read" in release_gate.summary_table(release_gate.run(report(0)))
