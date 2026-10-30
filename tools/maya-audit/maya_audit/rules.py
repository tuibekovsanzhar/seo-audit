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


class EngineDataMissing(RuntimeError):
    """A data file the engine needs is missing, unreadable or empty: an installation fault, never "no rules" or "no
    actions" (DECISIONS 279). Reinstall the package; a wheel must carry the file (tests/test_distribution_contract.py)."""


def engine_data(name: str, key: str) -> dict:
    """The non-empty `key` object of the package data file `name`, or EngineDataMissing saying which file and why."""
    path = Path(__file__).with_name(name)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))[key]
    except FileNotFoundError:
        raise EngineDataMissing(f"maya_audit/{name} is missing from this installation; reinstall maya-audit") from None
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise EngineDataMissing(f"maya_audit/{name} cannot be read ({type(exc).__name__}); reinstall maya-audit") from None
    if not isinstance(data, dict) or not data:
        raise EngineDataMissing(f"maya_audit/{name} has no {key!r} entries; reinstall maya-audit")
    return data


@lru_cache(maxsize=1)
def _table() -> dict[str, list[tuple[str, re.Pattern]]]:
    data = engine_data(_FILE.name, "rules")
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
