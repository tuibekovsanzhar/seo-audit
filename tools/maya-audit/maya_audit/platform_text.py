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
