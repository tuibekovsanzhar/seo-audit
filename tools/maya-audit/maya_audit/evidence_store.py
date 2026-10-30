"""Per-page verification evidence, saved beside an audit so findings can be checked without crawling again.

The JSON report keeps counts and samples; it does not keep what a page said. Checking a finding later
("was `{{publishDate}}` really in the JSON-LD?", "is the body still in English?") then means fetching
the site again, by which time it may have changed. With `--save-evidence`, each chosen page gets one
small JSON file holding what the checks read: title, meta tags (name and property, so og:* and
article:*), headings, the JSON-LD blocks as written, and the page's main text.

Sizes are capped per page and per audit. The folder holds the audited site's content, so it belongs
under `output/`, which is git-ignored.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .config import (EVIDENCE_MAX_JSONLD_CHARS, EVIDENCE_MAX_PAGES, EVIDENCE_MAX_TEXT_CHARS, EVIDENCE_MAX_TOTAL_BYTES,
                     CrawlConfig)
from .models import CrawlResult
from .urls import normalize_url

MODES = ("key", "all", "none")


def _slug(url: str) -> str:
    parts = urlsplit(url)
    text = re.sub(r"[^A-Za-z0-9]+", "-", (parts.path + ("-" + parts.query if parts.query else "")).strip("/"))
    return (text.strip("-") or "home")[:80]


def _trim(text: str, limit: int) -> tuple[str, bool]:
    return (text, False) if len(text) <= limit else (text[:limit], True)


def page_evidence(page) -> dict[str, Any]:
    """What the checks read on one page, in a form a person can read back."""
    a = page.analysis or {}
    text, text_cut = _trim("\n".join(a.get("_content_blocks") or a.get("_text_blocks") or []), EVIDENCE_MAX_TEXT_CHARS)
    blocks, used, jsonld_cut = [], 0, False
    for raw in a.get("_jsonld_raw") or []:
        if used + len(raw) > EVIDENCE_MAX_JSONLD_CHARS:
            jsonld_cut = True
            raw = raw[: max(0, EVIDENCE_MAX_JSONLD_CHARS - used)]
        if raw:
            blocks.append(raw)
            used += len(raw)
    return {
        "url": page.url, "status": page.status, "requested_at": page.requested_at, "discovered_via": page.discovered_via,
        "redirect_location": page.redirect_location, "content_type": page.content_type,
        "title": a.get("title"), "html_lang": a.get("html_lang"), "canonicals": a.get("canonicals") or [],
        "meta": a.get("meta") or [], "meta_properties": a.get("meta_properties") or [],
        "headings": a.get("headings") or [],
        "json_ld_blocks": blocks, "json_ld_truncated": jsonld_cut,
        "main_text": text, "main_text_truncated": text_cut,
        "main_text_is": "text outside <header>, <nav>, <footer> and <aside> (inside <main>/<article> when the page has one), "
                        "one text node per line",
        "template_urls": a.get("template_urls") or [],
    }


def chosen_pages(result: CrawlResult, cfg: CrawlConfig, mode: str) -> list:
    """The pages to save: every fetched page ("all"), or the key pages and wherever they redirected to ("key")."""
    if mode == "none":
        return []
    if mode == "all":
        return list(result.pages)
    keys = {u for u in (normalize_url(k, result.origin) for k in cfg.key_pages) if u}
    landed = {p.redirect_location for p in result.pages if p.url in keys and p.redirect_location}
    return [p for p in result.pages if p.url in keys or p.url in landed]


def save_evidence(result: CrawlResult, cfg: CrawlConfig, folder: str | Path, mode: str = "key") -> dict[str, Any]:
    """Write one file per chosen page plus index.json. Returns the index (also when nothing was chosen)."""
    pages = chosen_pages(result, cfg, mode)
    index: dict[str, Any] = {
        # The folder's name, never its place on this computer: index.json travels with the evidence (D-07).
        "audit_started_at": result.started_at, "origin": result.origin, "mode": mode, "folder": Path(folder).name,
        "limits": {"pages": EVIDENCE_MAX_PAGES, "total_bytes": EVIDENCE_MAX_TOTAL_BYTES,
                   "main_text_chars_per_page": EVIDENCE_MAX_TEXT_CHARS, "json_ld_chars_per_page": EVIDENCE_MAX_JSONLD_CHARS},
        "pages": [], "not_saved": [], "total_bytes": 0,
    }
    if not pages:
        index["note"] = ("nothing to save: no key pages were given (--key-page), and --save-evidence is 'key'"
                         if mode == "key" else "nothing to save")
        return index
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    for number, page in enumerate(pages, 1):
        if len(index["pages"]) >= EVIDENCE_MAX_PAGES:
            index["not_saved"].append({"url": page.url, "reason": f"page limit of {EVIDENCE_MAX_PAGES} reached"})
            continue
        body = json.dumps(page_evidence(page), ensure_ascii=False, indent=1).encode("utf-8")
        if index["total_bytes"] + len(body) > EVIDENCE_MAX_TOTAL_BYTES:
            index["not_saved"].append({"url": page.url, "reason": f"size limit of {EVIDENCE_MAX_TOTAL_BYTES} bytes reached"})
            continue
        name = f"{number:03d}-{_slug(page.url)}.json"
        (folder / name).write_bytes(body)
        index["pages"].append({"file": name, "url": page.url, "status": page.status, "bytes": len(body)})
        index["total_bytes"] += len(body)
    (folder / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    return index


def default_folder(result_origin_or_url: str, json_path: str | None) -> Path:
    """Next to the JSON report when there is one, else output/evidence/<host>/ (output/ is git-ignored)."""
    if json_path:
        path = Path(json_path).expanduser()
        return path.with_name(path.stem + "-evidence")
    host = re.sub(r"[^A-Za-z0-9.-]+", "-", urlsplit(result_origin_or_url).hostname or "site")
    return Path("output") / "evidence" / host


def shown_folder(folder: str | Path, json_path: str | None = None) -> str:
    """The evidence folder as a report that may be passed on names it (D-07): relative to the JSON report's own folder
    when it lies inside it (the default "<json name>-evidence"), else only its name. Never an absolute local path."""
    folder = Path(folder).expanduser()
    if json_path:
        base = Path(json_path).expanduser().resolve().parent
        try:
            return folder.resolve().relative_to(base).as_posix()
        except ValueError:
            pass
    return folder.name


def folder_in_use(folder: Path) -> bool:
    return folder.is_file() or (folder.is_dir() and any(folder.iterdir()))
