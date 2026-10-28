"""DECISIONS 270-271: the rule catalogue (action titles and steps) and the structured evidence (facts)."""
import json
import re
from pathlib import Path

from maya_audit.facts import EXTRACTORS, attach

ROOT = Path(__file__).resolve().parents[1]
ACTIONS = json.loads((ROOT / "maya_audit" / "rule_actions.json").read_text(encoding="utf-8"))["actions"]
RULES = {key for rows in json.loads((ROOT / "maya_audit" / "rule_ids.json").read_text(encoding="utf-8"))["rules"].values()
         for key, _ in rows}


def test_every_catalogue_entry_names_a_real_rule_and_has_both_languages():
    assert set(ACTIONS) <= RULES
    for key, entry in ACTIONS.items():
        for lang in ("tr", "en"):
            assert entry.get(lang), (key, lang)
            lines = (entry.get("steps") or {}).get(lang) or []
            assert 1 <= len(lines) <= 4 and all(len(line) <= 75 for line in lines), (key, lang)


def test_catalogue_text_holds_no_number_a_report_would_have_to_prove():
    # Tag names (<h1>) are not numbers; anything else a report states comes from report.json.
    def numbers(text):
        return re.findall(r"\d+", re.sub(r"</?h\d>|<h\d>/<h\d>", "", text))
    for key, entry in ACTIONS.items():
        for text in [entry["tr"], entry["en"], *sum((entry.get("steps") or {}).values(), [])]:
            assert numbers(text) == [], (key, text)


def test_every_fact_extractor_is_a_real_rule_and_facts_are_attached_to_saved_findings():
    assert set(EXTRACTORS) <= RULES
    saved = {"findings": [{"rule_id": "rnd6.home_large", "evidence": {"pages": [{"url": "https://x.test/", "bytes": 651927}],
                                                                       "threshold_bytes": 500000}}]}
    attach([saved])
    assert saved["findings"][0]["evidence"]["facts"] == [{"url": "https://x.test/", "observed": "651 KB", "expected": "500 KB"}]


def test_an_unexpected_evidence_shape_gives_no_facts_rather_than_a_wrong_one():
    saved = {"findings": [{"rule_id": "str7.heavy", "evidence": {"images": "not a list of rows"}}]}
    attach([saved])
    assert "facts" not in saved["findings"][0]["evidence"]
