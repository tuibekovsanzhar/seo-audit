"""DECISIONS 373 (Efsa, A6): which code made a file. Every Ek (the first row of "Kapsam") and every PDF (its provenance
lines) says the engine version, the commit and when the file was built, so a note on a file can be matched to the
code that wrote it."""
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
