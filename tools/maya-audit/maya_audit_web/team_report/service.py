"""The team report in one call, for the web app (DECISIONS 307): report.json -> data -> checks -> HTML -> PDF and
the XLSX appendix, with no model in the loop. The same three steps the maya-audit-pro skill runs (build_data,
validate_data, render), in the same modules, so the two reports are the same.

When something blocks the report, `TeamReport.blocked` is true and `reasons` says why in plain words (the text
library's `blocked` section, in the report's language); `details` keeps the technical lines for the owner.
"""
from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from maya_audit_web.team_report import build_data, render, texts, validate_data


@dataclass
class TeamReport:
    lang: str
    data: dict | None = None
    pdf: bytes | None = None
    xlsx: bytes | None = None
    blocked: bool = False
    reasons: list[str] = field(default_factory=list)
    details: list[str] = field(default_factory=list)
    pages: int | None = None
    decision: str | None = None  # the release gate's: PASS or CONDITIONAL when a PDF was produced
    previews: list[bytes] = field(default_factory=list)
    text_check: dict | None = None  # the release gate's text check (DECISIONS 353)
    draft: bool = False  # the text check found a blocking problem: the PDF is a marked draft


def _plain(lang: str, key: str, path: str | None = None) -> str:
    words = texts.library(lang)["blocked"]
    sentence = words.get(key) or words["gate"]
    return f"{sentence} ({words['field']}: {path})" if path else sentence


def build(report_path: Path, lang: str, *, review_path: Path | None = None, affected_path: Path | None = None,
          audit_id: str | None = None, previews: bool = False) -> TeamReport:
    """The team report of one saved audit. Never raises for a report that cannot be published: it says why."""
    out = TeamReport(lang=lang)
    try:
        data, _ = build_data.build_from_files(report_path, lang, audit_id=audit_id, review=review_path,
                                              affected_path=affected_path)
    except build_data.BuildError as exc:
        out.blocked, out.reasons, out.details = True, [_plain(lang, "build")], [str(exc)]
        return out
    out.data = data
    checked = validate_data.check(data)
    out.decision = (checked["record"] or {}).get("decision")
    if checked["errors"]:
        out.blocked = True
        for e in checked["errors"]:
            reason = _plain(lang, e.get("rule") or e["kind"], None if e.get("rule") else e.get("path"))
            if reason not in out.reasons:
                out.reasons.append(reason)
            out.details.append(e["text"])
        return out
    with tempfile.TemporaryDirectory(prefix="maya-team-report-") as tmp:
        html = Path(tmp) / ("ekip-raporu.html" if lang == "tr" else "team-report.html")
        pdf = html.with_suffix(".pdf")
        try:
            result = render.produce(data, html, pdf, png=Path(tmp) / "png" if previews else None)
        except Exception as exc:  # no Chromium or no Playwright on this computer
            out.blocked, out.reasons, out.details = True, [_plain(lang, "browser")], [f"{type(exc).__name__}: {exc}"]
            return out
        if result["stop"] or not result["pdf"]:
            out.blocked = True
            out.details = [line for line in result["lines"] if line.startswith(("HATA", "TAŞMA", "  -"))] or result["lines"]
            for field_name in result["overflow"]:
                out.reasons.append(_plain(lang, "overflow", field_name))
            for line in result["problems"]:
                rule = next((r for r in texts.library(lang)["blocked"] if r.startswith("RG-") and f"{r}:" in line), None)
                reason = _plain(lang, rule or "pdf")
                if reason not in out.reasons:
                    out.reasons.append(reason)
            if not out.reasons:
                out.reasons.append(_plain(lang, "pdf"))
            return out
        out.text_check, out.draft = result.get("text_check"), bool(result.get("draft"))
        out.pdf = pdf.read_bytes()
        if result["appendix"]:
            out.xlsx = Path(result["appendix"]).read_bytes()
        out.pages = sum(1 for _ in _pages(pdf))
        if previews and result["previews"]:
            out.previews = [p.read_bytes() for p in sorted(Path(result["previews"]).glob("*.png"),
                                                           key=lambda p: int("".join(c for c in p.stem if c.isdigit()) or 0))]
    return out


def _pages(pdf: Path):
    try:
        from pypdf import PdfReader
        return PdfReader(str(pdf)).pages
    except ImportError:
        import fitz  # type: ignore
        return list(fitz.open(str(pdf)))


def appendix_files(report: dict, affected: dict | None, confirmations: dict | None, lang: str,
                   business: str | None = None, todos: list[dict] | None = None, artifacts=None,
                   text_check=render.NOT_GIVEN, previous: dict | None = None, pdf: bytes | None = None) -> dict:
    """DECISIONS 376: {"client": the Ek, "team": the team file (text check, fix log) or None, "record"}; `pdf`: the
    team report printed for this audit and language, for each card's page (D4)."""
    return render.appendix_files(report, affected, confirmations, lang, business, todos=todos,
                                 maya=render.maya_bundle(artifacts), text_check=text_check, previous=previous, pdf=pdf)[0]


def appendix(report: dict, affected: dict | None, confirmations: dict | None, lang: str,
             business: str | None = None, todos: list[dict] | None = None, artifacts=None,
             text_check=render.NOT_GIVEN, previous: dict | None = None) -> bytes:
    """The XLSX appendix alone (the web app's "Ek (XLSX)" button): the skill writes the same file. `todos`: the team
    report's cards in this language (DECISIONS 322); `artifacts`: the audit's folder, for its Maya data (DECISIONS 352);
    `text_check`: the text check of the team report's data, None when it could not run (DECISIONS 353)."""
    return render.appendix_bytes(report, affected, confirmations, lang, business, todos=todos,
                                 maya=render.maya_bundle(artifacts), text_check=text_check, previous=previous)[0]
