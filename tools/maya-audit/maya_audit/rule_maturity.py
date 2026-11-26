"""DECISIONS 378 (owner, accuracy first): how far the SEO team trusts each rule.

Three levels, from the team's card reviews (`rule_maturity.json`, made by `scripts/rule_maturity.py`) and their explicit
decisions (`rule_approval.json`):

- ``approved``: the team approved the rule in `rule_approval.json`, or its cards were found correct at least
  APPROVE_MIN_CORRECT times on at least APPROVE_MIN_BRANDS brands and its latest verdict is correct (or wording only).
- ``disputed``: the team questioned it in `rule_approval.json`, or its latest reviewed card was wrong.
- ``unreviewed``: everything else (never reviewed, or reviewed without proof either way).

An explicit approval beats everything. `client_selection.confirm_reason` sends a finding of a disputed rule (and, under
the strict policy, of an unreviewed one) to "Teyit edin": nothing is deleted and no severity changes.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from . import rule_approval

FILE = Path(__file__).with_name("rule_maturity.json")
LEVELS = ("approved", "disputed", "unreviewed")
POLICIES = ("card", "confirm")
# Agent defaults until the owner confirms them (DECISIONS 378)
APPROVE_MIN_CORRECT = 3
APPROVE_MIN_BRANDS = 2


@lru_cache(maxsize=1)
def _register() -> dict:
    return json.loads(FILE.read_text(encoding="utf-8")).get("rules") or {}


def stats(rule_id: str | None) -> dict | None:
    """The rule's row in the review register, or None when no reviewed card carried it."""
    return _register().get(rule_id or "")


def level(rule_id: str | None) -> str:
    rule = rule_id or ""
    data = rule_approval._data()
    if rule and rule in (data.get("approved") or {}):
        return "approved"
    if rule and rule in (data.get("questioned") or {}):
        return "disputed"
    row = stats(rule)
    if not row:
        return "unreviewed"
    latest = (row.get("latest") or {}).get("verdict")
    if latest == "wrong":
        return "disputed"
    if (row.get("correct", 0) >= APPROVE_MIN_CORRECT and len(row.get("brands_correct") or []) >= APPROVE_MIN_BRANDS
            and latest in ("correct", "wording")):
        return "approved"
    return "unreviewed"


def policy() -> str:
    """What a finding of a never-approved rule becomes: "card" (today's behaviour) or "confirm" ("Teyit edin")."""
    value = (rule_approval._data().get("policy") or {}).get("unreviewed", "card")
    if value not in POLICIES:
        raise ValueError(f"{rule_approval.FILE.name}: policy.unreviewed must be one of {POLICIES}, not {value!r}")
    return value
