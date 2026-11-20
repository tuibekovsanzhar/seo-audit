"""DECISIONS 373 (Efsa, A6): which code made a file, so a note on a file can be matched to the code that wrote it.
DECISIONS 375: the stamp is for the team, not the client: no PDF shows it; the Ek says it in one short line, the last
row of "Yöntem" ("Sürüm: 0.2.8 · commit abc1234"), and in the file's document properties with the build time."""
from __future__ import annotations

from datetime import datetime, timezone

WORDS = {"tr": {"label": "Sürüm", "line": "Maya Audit {version} · commit {commit} · oluşturuldu {built} UTC",
                "none": "kaydedilmedi"},
         "en": {"label": "Version", "line": "Maya Audit {version} · commit {commit} · built {built} UTC",
                "none": "not recorded"}}


def engine(now: datetime | None = None) -> dict:
    """{"version", "commit" (7 characters, or None), "built"}: the engine building the file now."""
    from . import __version__
    from .report import source_provenance
    commit = str(source_provenance().get("source_commit") or "")
    ok = len(commit) >= 7 and all(c in "0123456789abcdef" for c in commit[:7])
    when = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return {"version": __version__, "commit": commit[:7] if ok else None, "built": when.strftime("%Y-%m-%d %H:%M")}


def line(lang: str = "tr", now: datetime | None = None) -> tuple[str, str]:
    """(label, text) for a file's version line."""
    w = WORDS["tr" if lang == "tr" else "en"]
    e = engine(now)
    return w["label"], w["line"].format(version=e["version"], commit=e["commit"] or w["none"], built=e["built"])


def short(lang: str = "tr") -> str:
    """The Ek's one line: "Sürüm: 0.2.8 · commit abc1234" (DECISIONS 375)."""
    w = WORDS["tr" if lang == "tr" else "en"]
    e = engine()
    return f"{w['label']}: {e['version']} · commit {e['commit'] or w['none']}"


def properties(now: datetime | None = None) -> dict:
    """The xlsx document properties (DECISIONS 375): who made the file, the engine version, commit and build time."""
    e = engine(now)
    return {"creator": "Maya Audit", "version": e["version"],
            "description": f"Maya Audit {e['version']} · commit {e['commit'] or 'not recorded'} · built {e['built']} UTC",
            "created": (now or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
