"""DECISIONS 373 (Efsa, A8): rules not yet approved show as "Kontrol edin", not "Sorun".

Two kinds: a rule the SEO team questioned (`rule_approval.json`, "questioned"), and the checks of a draft sector profile
(`sector_method.json`, sectors marked draft: "taslak — İlginay/Efsa onayı bekliyor") on an audit of that profile.
A rule moved to "approved" counts as approved again."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

FILE = Path(__file__).with_name("rule_approval.json")
SECTORS = Path(__file__).with_name("sector_method.json")


@lru_cache(maxsize=1)
def _data() -> dict:
    return json.loads(FILE.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _draft_rules() -> dict[str, frozenset]:
    """{draft profile id: the rule ids, rule prefixes and check ids its draft checks use}."""
    data = json.loads(SECTORS.read_text(encoding="utf-8"))
    drafts = {s.get("profile") for s in data.get("sectors") or [] if s.get("draft") and s.get("profile")}
    out: dict[str, set] = {p: set() for p in drafts}
    for row in data.get("sec") or []:
        if row.get("draft") and row.get("profile") in out:
            out[row["profile"]].update(r for r in row.get("rules") or [] if r)
    return {p: frozenset(v) for p, v in out.items()}


def questioned(rule_id: str | None) -> dict | None:
    """The team's question on a rule, while it is not approved."""
    data = _data()
    rule = rule_id or ""
    if rule in (data.get("approved") or {}):
        return None
    return (data.get("questioned") or {}).get(rule)


def draft_profile(profile: str | None) -> bool:
    return bool(profile) and profile in _draft_rules()


def unapproved(rule_id: str | None, check_id: str | None = None, profile: str | None = None) -> str | None:
    """Why a finding's rule is not approved ("questioned", "draft_sector"), or None."""
    if questioned(rule_id):
        return "questioned"
    rules = _draft_rules().get(profile or "")
    if rules and rule_id not in (_data().get("approved") or {}):
        rule = rule_id or ""
        if check_id in rules or rule in rules or any(r.endswith(".") and rule.startswith(r) for r in rules):
            return "draft_sector"
    return None
