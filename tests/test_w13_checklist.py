"""DECISIONS 278 (T4, G1, G3): the validation note is made from the report by finding id, its counts hold only what was
matched and re-tested, and every report carries the release gate's decision. Made-up reports (shop.example.test)."""
import json

from maya_audit import release_gate
from maya_audit_web.comparison import main, validation_note

SITE = "https://shop.example.test"


def report():
    kept = {"id": "IDX-1-a", "check_id": "IDX-1", "rule_id": "idx1.4xx.referenced.linked", "severity": "S2",
            "scope": {"urls": [SITE + "/en"]}, "evidence": {"target_urls": [SITE + "/404"]},
            "verification": {"state": "confirmed", "subjects": [SITE + "/en"], "checked": [{"url": SITE + "/en"}]}}
    review = {"id": "IDX-5-b", "check_id": "IDX-5", "rule_id": "judgment.sitemap", "severity": "S3",
              "scope": {"urls": [SITE + "/old-campaign"]}, "evidence": {"x": 1}}
    return {"checks": [{"check_id": "IDX-1", "findings": [kept, review]}]}


SPEC = {"title": "Validation, shop.example.test",
        "items": [{"label": "placeholder links to the 404 page", "rule_id": "idx1.4xx.referenced.linked", "urls": ["/en"]},
                  # Same rule, but none of its addresses: a match by title would have called this "kept".
                  {"label": "sitemap URLs to 404", "rule_id": "idx1.4xx.referenced.linked", "urls": ["/old-campaign"]},
                  {"label": "sitemap review", "rule_id": "judgment.sitemap", "urls": ["/old-campaign"],
                   "manual_notes": "seen live, 302 then 404"},
                  {"label": "old false alarm", "rule_id": "str12.language", "urls": ["/tr"], "expected": "closed"}],
        "false_alarm_sweep": None}


def test_counts_only_matched_and_retested_items():
    note = validation_note(SPEC, report())
    assert "| placeholder links to the 404 page | kept | kept, re-tested and confirmed | IDX-1-a |" in note
    assert "| sitemap URLs to 404 | kept | not matched to any finding | — |" in note
    assert "| sitemap review | kept | kept, not re-tested | IDX-5-b |" in note and "seen live, 302 then 404" in note
    assert "| old false alarm | closed | closed |" in note
    assert ("Items to keep: 3. Kept, re-tested and confirmed: 1. Kept but not re-tested: 1. Not matched to any finding: 1."
            in note)
    assert "no false-alarm sweep was done; nothing is claimed." in note


def test_a_sweep_is_claimed_only_when_recorded():
    note = validation_note({**SPEC, "false_alarm_sweep": "every S2 finding and every PDF card title"}, report())
    assert "New false alarms: swept (every S2 finding and every PDF card title)." in note


def test_the_command_line_writes_the_note(tmp_path):
    (tmp_path / "report.json").write_text(json.dumps(report()), encoding="utf-8")
    (tmp_path / "report.affected-urls.json").write_text(json.dumps({"IDX-5-b": [SITE + "/old-campaign", SITE + "/x"]}),
                                                        encoding="utf-8")
    (tmp_path / "checklist.json").write_text(json.dumps(SPEC), encoding="utf-8")
    assert main(["--checklist", str(tmp_path / "checklist.json"), str(tmp_path / "report.json"),
                 "-o", str(tmp_path / "DOGRULAMA.md")]) == 0
    assert "| sitemap review | kept | kept, not re-tested | IDX-5-b |" in (tmp_path / "DOGRULAMA.md").read_text(encoding="utf-8")


def test_every_report_carries_the_release_gate_decision():
    """G1: the engine writes the gate's record last, without changing a finding."""
    from test_w13_head_family import audit
    outcome, built, base = audit()
    gate = built["release_gate"]
    assert gate["version"] == release_gate.VERSION and gate["decision"] in (release_gate.PASS, release_gate.CONDITIONAL,
                                                                          release_gate.BLOCKED)
    assert gate["decision"] == release_gate.decision(gate["violations"]) and gate["cards_checked"] is False
    assert [f["id"] for c in built["checks"] for f in c["findings"]] == [f.id for c in outcome.checks
                                                                        if not c.check_id.startswith("ANS") for f in c.findings]
