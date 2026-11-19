"""DECISIONS 361: advice for one platform (Shopify, WordPress, WooCommerce, ikas, Ticimax, …) is shown only on a site the
audit recognised as that platform (`site_platform.recognise`; WooCommerce runs on WordPress). One filter, used wherever
an advice text is shown: a card's lines, the appendix's "Ne yapılmalı" and the engine's fix sentences. A sentence, a
";" clause or a step line that names another platform is left out; the rest of the text stays as written. The release
gate's RG-19 blocks any that is still shown (`maya_audit.text_gate`)."""
from __future__ import annotations

import re

from .text_gate import BUILT_ON, _PLATFORM

_SENTENCE = re.compile(r"(?<=[.;!?])\s+")


def own(platform: str | None) -> set[str]:
    """The platform names advice may use on this site (lower-case)."""
    return {(platform or "").lower(), BUILT_ON.get(platform or "", "").lower()} - {""}


def other_platform(text: str | None, platform: str | None) -> str | None:
    """The first platform the text names that is not this site's, or None."""
    mine = own(platform)
    for hit in _PLATFORM.finditer(text or ""):
        if hit.group(1).lower() not in mine:
            return hit.group(1)
    return None


def for_platform(text: str | None, platform: str | None) -> str | None:
    """`text` without the sentences, ";" clauses and lines that name another platform than the site's. Lines are kept
    as lines; a text left with nothing keeps its first part only when that names no other platform (else "")."""
    if not text or not other_platform(text, platform):
        return text
    lines = []
    for line in str(text).split("\n"):
        if not other_platform(line, platform):
            lines.append(line)
            continue
        parts = [p for p in _SENTENCE.split(line) if p.strip() and not other_platform(p, platform)]
        if parts:
            kept = " ".join(parts).strip()
            lines.append(kept[:-1] + "." if kept.endswith(";") else kept)
    return "\n".join(lines).strip()


def lines_for(lines, platform: str | None) -> list[str]:
    return [line for line in lines or [] if not other_platform(line, platform)]


def advice_by_platform() -> dict[str, list[str]]:
    """DECISIONS 365: {platform: the rules (and note topics) whose advice has a line for it}, read from the advice texts
    themselves (the cards' steps and texts, the rule actions), so the list never goes stale. A line naming a platform is
    shown only on that platform (`for_platform`); every other site gets the rule's general advice."""
    import json
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    found: dict[str, set[str]] = {}

    def scan(key: str, value) -> None:
        for hit in _PLATFORM.finditer(json.dumps(value, ensure_ascii=False)):
            name = next((p for p in PLATFORM_NAMES if p.lower() == hit.group(1).lower()), hit.group(1))
            found.setdefault(name, set()).add(key)
    actions = json.loads((root / "maya_audit" / "rule_actions.json").read_text(encoding="utf-8"))
    for rule, entry in (actions.get("actions") or actions).items():
        scan(rule, entry)
    for lang in ("tr", "en"):
        texts = json.loads((root / "maya_audit_web" / "team_report" / "texts" / f"{lang}.json").read_text(encoding="utf-8"))
        for rule, entry in (texts.get("rules") or {}).items():
            scan(rule, entry)
        for topic, entry in (texts.get("notes") or {}).items():
            scan(f"not: {topic}", entry)
    return {p: sorted(v) for p, v in sorted(found.items())}


from .text_gate import PLATFORMS as PLATFORM_NAMES  # noqa: E402
