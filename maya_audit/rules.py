"""Stable rule ids for findings (DECISIONS 269).

Every finding title the engine writes matches one frame in `maya_audit_web/wording.py`; that frame's key
("str2.home_hidden_h1") is the finding's rule id. The table is generated into `rule_ids.json` (the engine does not import
the web package) and locked to the frames by `tests/test_w12_rule_ids.py`. Code that must know what a finding is reads
`rule_id` instead of matching its English title, which can be reworded.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

_FILE = Path(__file__).with_name("rule_ids.json")


@lru_cache(maxsize=1)
def _table() -> dict[str, list[tuple[str, re.Pattern]]]:
    data = json.loads(_FILE.read_text(encoding="utf-8"))["rules"]
    return {check: [(key, re.compile(pattern)) for key, pattern in rows] for check, rows in data.items()}


def rule_id(check_id: str, title: str) -> str | None:
    """The key of the first frame of `check_id` that matches the whole title, or None (a title with no frame)."""
    for key, regex in _table().get(check_id, ()):
        if regex.fullmatch(title or ""):
            return key
    return None


def assign(checks) -> None:
    """Set `rule_id` on every finding and review item of native or saved (dict) checks; idempotent."""
    for check in checks:
        for item in [*(_get(check, "findings") or []), *(_get(check, "review_items") or [])]:
            key = rule_id(_get(item, "check_id"), _get(item, "title"))
            if isinstance(item, dict):
                item["rule_id"] = key
            elif hasattr(item, "rule_id"):
                item.rule_id = key


def _get(value, name):
    return value.get(name) if isinstance(value, dict) else getattr(value, name, None)
