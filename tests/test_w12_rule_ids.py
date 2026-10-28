"""DECISIONS 269: the rule id table is generated from the web package's title frames and stays in step with them."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from maya_audit.findings import Finding, Severity  # noqa: E402
from maya_audit.models import Confidence  # noqa: E402
from maya_audit.rules import assign, rule_id  # noqa: E402
import rule_catalog  # noqa: E402


def test_the_generated_table_is_current():
    saved = json.loads((ROOT / "maya_audit" / "rule_ids.json").read_text(encoding="utf-8"))
    assert saved == rule_catalog.build(), "run: python scripts/rule_catalog.py"


def test_a_finding_gets_its_rule_id_and_a_reworded_saved_title_is_reassigned():
    f = Finding("STR-2", "The homepage's only <h1> is hidden", Severity.S2, Confidence.VERIFIED, "Hypothesis", [],
                {"urls": []}, {}, "", "")
    assert f.rule_id == "str2.home_hidden_h1"
    saved = {"findings": [{"check_id": "STR-1", "title": "14 page(s) have no <title>"}], "review_items": []}
    assign([saved])
    assert saved["findings"][0]["rule_id"] == rule_id("STR-1", "14 page(s) have no <title>") is not None


# -- the title matching that groups and labels findings never goes silent (DECISIONS 269) ----------------------------

def _samples() -> dict[str, list[str]]:
    """Every title frame of every check written out with sample values: a number for {n#}, 5% for {p%}, x otherwise."""
    import re
    from maya_audit_web import wording
    hole = re.compile(r"\{(\w+)([#~%*]?)(?::[^{}]*)?\}|\[\[\w+:(.*?)\]\]")

    def sample(frame: str) -> str:
        return hole.sub(lambda m: m.group(3) if m.group(3) is not None else {"#": "2", "%": "5%"}.get(m.group(2), "x"), frame)
    return {check: [sample(frame) for _, frame, _ in rows] for check, rows in wording._TITLES.items()}


def test_every_launch_gate_title_pattern_still_matches_a_title_the_engine_writes():
    import re
    from maya_audit.launch_gate import LABELS
    samples = _samples()
    every = [s for rows in samples.values() for s in rows]
    dead = [(row.check_id, row.pattern) for row in LABELS if row.pattern
            and not any(re.search(row.pattern, s) for s in (samples.get(row.check_id, []) if row.check_id else every))]
    assert dead == [], "a reworded title left these launch-gate rows matching nothing"


def test_every_root_cause_title_pattern_still_matches_a_title_the_engine_writes():
    from maya_audit import root_cause
    every = [s for rows in _samples().values() for s in rows]
    patterns = [value for name, value in vars(root_cause).items() if name.isupper() and hasattr(value, "search")]
    assert patterns and [p.pattern for p in patterns if not any(p.search(s) for s in every)] == []
