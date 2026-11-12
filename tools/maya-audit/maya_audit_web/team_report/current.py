"""A saved audit re-evaluated with the current engine before its team report is built (DECISIONS 308).

A saved report keeps the findings and severities the engine of its day wrote. The team report (the web app's "Ekip
raporu" and the maya-audit-pro skill, which share `build_data.build_from_files`) is built from a derived copy instead:
the same steps as `tools/reassess_saved.py` (`maya_audit.reassess_rules.apply`: the reassessment rules, the checks that
can run on saved data, the Product fields from the saved JSON-LD), on a copy, with no request. What the current engine
does at selection time (reach from pages read and percent-escape case, DECISIONS 305) then applies to that copy as to
any report.

- The original report.json and affected-urls.json are never written. The copy lives in a folder of its own:
  `<audit>/current-engine/` beside the audit's `artifacts/` (the web app's history), or `<report>.current-engine/`
  beside a report anywhere else, with `meta.json` saying what it was made from.
- The copy is made again only when its source or the engine changed: the key is the source files' size and modified
  time and the engine's fingerprint (a hash of the `maya_audit` package's own files), so every engine change counts.
- A report written by an engine of the current schema with no offline record is already current: it is used as is,
  unless its saved data adds what DECISIONS 309 reads from it (the platform a page reader's copies hide, the RND-6
  label); then the copy holds only those additions (`reassess_rules.saved_data`).
- The owner's manual checks stay in the audit's one review file (`artifacts/review.json`), which both paths read.
"""
from __future__ import annotations

import hashlib
import json
import os
import socket
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

FOLDER = "current-engine"
META = "meta.json"
_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


@dataclass
class Current:
    report_path: Path        # the report the team report is built from (the derived copy, or the source when current)
    affected_path: Path | None
    source_path: Path        # the saved report.json, never written
    reassessed: bool
    engine: dict = field(default_factory=dict)  # version, schema, commit, fingerprint, processed_at
    changes: list[str] = field(default_factory=list)


@lru_cache(maxsize=1)
def fingerprint() -> str:
    """A hash of the engine's own files (maya_audit/**/*.py and *.json) and, DECISIONS 314, the text libraries the
    reports are written with (the team report's texts and labels, the web app's translations): any change to a rule
    or a sentence makes the derived copy again."""
    base = Path(__file__).resolve().parents[2]
    roots = [base / "maya_audit", base / "maya_audit_web" / "team_report" / "texts",
             base / "maya_audit_web" / "team_report" / "refs", base / "maya_audit_web" / "locales"]
    h = hashlib.sha256()
    for root in roots:
        for path in sorted(p for p in root.rglob("*") if p.suffix in (".py", ".json") and "__pycache__" not in p.parts):
            h.update(path.relative_to(base).as_posix().encode())
            h.update(path.read_bytes())
    return h.hexdigest()[:16]


def engine() -> dict:
    from maya_audit import __version__
    from maya_audit.report import source_provenance
    from maya_audit.schema import SCHEMA_VERSION
    commit = str(source_provenance().get("source_commit") or "")
    return {"version": __version__, "schema": SCHEMA_VERSION,
            "commit": commit[:7] if len(commit) >= 7 and all(c in "0123456789abcdef" for c in commit) else None,
            "fingerprint": fingerprint()}


def folder_for(source: Path) -> Path:
    source = Path(source).resolve()
    if source.parent.name == "artifacts":
        return source.parent.parent / FOLDER
    return source.with_name(source.stem + "." + FOLDER)


def _stamp(path: Path | None) -> list | None:
    if path is None or not path.is_file():
        return None
    st = path.stat()
    return [st.st_size, st.st_mtime_ns]


def _lock(folder: Path) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(str(folder), threading.Lock())


def _is_current(report: dict, fp: str) -> bool:
    from maya_audit.schema import SCHEMA_VERSION, version_key
    analysis = (report.get("generation") or {}).get("analysis")
    if isinstance(analysis, dict):  # an offline re-evaluation: current only when this engine made it
        return (analysis.get("engine") or {}).get("fingerprint") == fp
    return version_key(str(report.get("schema_version") or "1.0")) >= version_key(SCHEMA_VERSION)


def _saved_jsonld(folder: Path) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for path in sorted((folder / "evidence").glob("*.json")):
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        blocks = saved.get("json_ld_blocks") if isinstance(saved, dict) else None
        if isinstance(saved, dict) and isinstance(saved.get("url"), str) and isinstance(blocks, list):
            out[saved["url"]] = [b for b in blocks if isinstance(b, str)]
    return out


def _saved_texts(folder: Path) -> list[str]:
    """The saved page copies (Maya's and the page reader's) as text, for what DECISIONS 309 reads from them."""
    out = []
    for sub in ("evidence", "evidence-firecrawl"):
        for path in sorted((folder / sub).glob("*.json")):
            if path.name == "index.json":
                continue
            try:
                out.append(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError):
                continue
    return out


def read_of(report: dict) -> dict | None:
    """DECISIONS 316: the pages read as the summary, the PDF and the history list count them (`content_coverage`), kept
    in the small meta file so the history list can say the same number without reading report.json."""
    cov = (report.get("audit_status") or {}).get("content_coverage") or {}
    by = cov.get("read_by") or {}
    if not isinstance(cov.get("pages_read"), int):
        return None
    return {"pages_read": cov["pages_read"], "maya": int(by.get("maya_only") or 0) + int(by.get("both") or 0),
            "firecrawl": int(by.get("firecrawl") or 0)}


def _write(path: Path, value) -> None:
    tmp = path.with_name(path.name + ".part")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _no_network(*args, **kwargs):
    raise RuntimeError("the current-engine re-evaluation makes no network request")


def current(source: Path, affected_path: Path | None = None, *, folder: Path | None = None) -> Current:
    """The report a team report is built from: the derived copy made with the current engine (made now when missing or
    out of date), or the source itself when it is already current. Never writes the source."""
    source = Path(source).resolve()
    if affected_path is None and (source.parent / "affected-urls.json").is_file():
        affected_path = source.parent / "affected-urls.json"
    eng = engine()
    folder = Path(folder).resolve() if folder else folder_for(source)
    from maya_audit import crux as _crux
    key = {"source": str(source), "report": _stamp(source), "affected": _stamp(affected_path), "fingerprint": eng["fingerprint"],
           # DECISIONS 334: Core Web Vitals fetched again for this saved audit (`artifacts/crux.json`)
           "crux": _stamp(source.parent / _crux.SAVED_FILE)}
    with _lock(folder):
        meta_path = folder / META
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else None
        except ValueError:
            meta = None
        if isinstance(meta, dict) and meta.get("key") == key:
            if not meta.get("reassessed"):
                return Current(source, affected_path, source, False, meta.get("engine") or eng)
            aff = folder / "affected-urls.json"
            return Current(folder / "report.json", aff if aff.is_file() else None, source, True, meta.get("engine") or eng,
                           list(meta.get("changes") or []))
        report = json.loads(source.read_text(encoding="utf-8"))
        affected = json.loads(affected_path.read_text(encoding="utf-8")) if affected_path and affected_path.is_file() else None
        again = _crux.saved_beside(source.parent)  # DECISIONS 334
        crux_change = []
        if again and again != report.get("crux"):
            report = {**report, "crux": again}
            crux_change = [f"Core Web Vitals fetched again from Google on {again.get('fetched_at', '')[:10]} "
                           f"({again.get('status')}, {again.get('origin') or '—'}) (DECISIONS 334)"]
        texts = _saved_texts(source.parent)
        from maya_audit.reassess_rules import apply, saved_data
        audit_id = source.parent.parent.name if source.parent.name == "artifacts" else None
        if _is_current(report, eng["fingerprint"]):
            # Written by an engine of the current schema: only what DECISIONS 309 reads from the saved data (the
            # platform a page reader's copies hide, the RND-6 label) can still change; without it, used as is.
            new, changes = saved_data(report, affected, texts)
            changes = crux_change + changes
            if not changes:
                folder.mkdir(parents=True, exist_ok=True)
                _write(meta_path, {"key": key, "reassessed": False, "engine": eng, "read": read_of(new)})
                return Current(source, affected_path, source, False, eng)
            record = {"kind": "saved-data additions", "rules": "DECISIONS 309, 321, 329, 334, 337, 338, 340 and 343", "source_audit_id": audit_id,
                      "processed_at": datetime.now(timezone.utc).isoformat(), "requests": 0, "changes": changes,
                      "unchanged": "every other finding, observation, time and count is the source report's"}
            aff = affected
        else:
            saved = socket.socket.connect, socket.create_connection, socket.getaddrinfo
            socket.socket.connect = _no_network  # type: ignore[method-assign]
            socket.create_connection = _no_network  # type: ignore[assignment]
            socket.getaddrinfo = _no_network  # type: ignore[assignment]
            try:
                new, aff, record = apply(report, affected, source_audit_id=audit_id, jsonld_by_url=_saved_jsonld(source.parent),
                                         saved_texts=texts)
                record["changes"] = crux_change + list(record.get("changes") or [])
            finally:
                socket.socket.connect, socket.create_connection, socket.getaddrinfo = saved
        eng = {**eng, "processed_at": record["processed_at"]}
        record["engine"] = eng
        new.setdefault("generation", {})["analysis"] = record
        folder.mkdir(parents=True, exist_ok=True)
        _write(folder / "report.json", new)
        if affected is not None:
            _write(folder / "affected-urls.json", aff)
        elif (folder / "affected-urls.json").exists():
            (folder / "affected-urls.json").unlink()
        _write(meta_path, {"key": key, "reassessed": True, "engine": eng, "changes": record["changes"], "read": read_of(new),
                           "made_at": datetime.now(timezone.utc).isoformat()})
        return Current(folder / "report.json", folder / "affected-urls.json" if affected is not None else None, source,
                       True, eng, list(record["changes"]))


def line_of(eng: dict | None, lang: str) -> str | None:
    """'Güncel motorla yeniden değerlendirildi (Maya Audit 0.2.8 · şema 1.24 · 5749501, 4 Kas 2026)' for a report the
    current engine re-evaluated (its `generation.analysis.engine`), else None. The same line in the PDF and the web app."""
    if not isinstance(eng, dict) or not eng.get("version"):
        return None
    from maya_audit_web.team_report.build_data import REFS, date_short, load
    L = load(REFS / "etiketler.json")[lang]
    return L["prov_reassessed_line"].format(version=eng["version"], schema=eng.get("schema") or "—",
                                            commit=f" · {eng['commit']}" if eng.get("commit") else "",
                                            date=date_short(eng.get("processed_at"), L) if eng.get("processed_at") else "—")


def line(cur: Current, lang: str) -> str | None:
    return line_of(cur.engine, lang) if cur.reassessed else None
