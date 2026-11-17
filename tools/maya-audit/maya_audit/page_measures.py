"""One compact record of what was measured on each page that was read (DECISIONS 323).

The checks keep a sample of pages in their evidence (often the first 40), so a value per page is missing for the rest.
This record keeps the page's own measurements — status, HTML size, where the main content starts, headings and
their skipped levels, title and description, canonical, language, words, first response, cache, images, scripts,
tags, structured data — for every page whose content was read, Maya's own and a page reader's.

New audits store it as `crawl.page_measures` ({url: record}, schema 1.29), so a page read only through a page reader
(whose content the report does not otherwise keep) has its values too. For a report saved before it, `index()` works the
same records out from the saved page records (`crawl.pages[].analysis`, offline); a page read only through a page
reader in such a report has no saved record, and that is said, never guessed.

It never changes a finding, a severity or a confidence.
"""
from __future__ import annotations

from typing import Any

TEXT = 160  # the longest title or description kept, in characters


def _get(page: Any, key: str, default=None):
    return page.get(key, default) if isinstance(page, dict) else getattr(page, key, default)


def readable(page: Any) -> bool:
    """A page whose content was read: a 2xx answer with content (or a provider's document of unknown status)."""
    status, analysis = _get(page, "status"), _get(page, "analysis")
    if not isinstance(analysis, dict) or analysis.get("empty_response") or _get(page, "content_checks_eligible") is False:
        return False
    if _get(page, "error"):
        return False
    if status is None:
        return _get(page, "view") == "provider"
    return isinstance(status, int) and 200 <= status < 300


def _description(analysis: dict) -> str | None:
    for m in analysis.get("meta") or []:
        if isinstance(m, dict) and str(m.get("name") or "").lower() == "description":
            return str(m.get("content") or "")
    return None


def measure(page: Any) -> dict[str, Any]:
    """The page's measurements, from its page record (a `PageFetch` or its saved dict). Only what was measured: a
    value the record does not hold is left out, never written as 0."""
    a = _get(page, "analysis") or {}
    out: dict[str, Any] = {"status": _get(page, "status")}
    if _get(page, "view") and _get(page, "view") != "raw":
        out["view"] = _get(page, "view")
    if isinstance(_get(page, "body_bytes"), int):
        out["html_bytes"] = _get(page, "body_bytes")
        if _get(page, "body_truncated"):
            out["html_truncated"] = True
    if isinstance(a.get("main_offset_bytes"), int):
        out["main_offset_bytes"] = a["main_offset_bytes"]
    if isinstance(_get(page, "ttfb_ms"), (int, float)):
        out["ttfb_ms"] = round(_get(page, "ttfb_ms"), 1)
    headers = {str(k).lower(): v for k, v in (_get(page, "headers") or {}).items()}
    cache = next((f"{k}: {headers[k]}" for k in ("cf-cache-status", "x-cache", "x-vercel-cache", "akamai-cache-status")
                  if headers.get(k)), None) or (f"cache-control: {headers['cache-control']}" if headers.get("cache-control") else None)
    if cache:
        out["cache"] = cache[:80]
    if isinstance(a.get("title"), str):
        out["title"] = a["title"][:TEXT]
        out["title_chars"] = len(a["title"])
    desc = _description(a)
    if desc is not None:
        out["description"] = desc[:TEXT]
        out["description_chars"] = len(desc)
    canon = [c for c in a.get("canonicals") or [] if isinstance(c, str)]
    if canon:
        out["canonical"] = canon[0]
        if len(set(canon)) > 1:
            out["canonicals"] = len(set(canon))
    if isinstance(a.get("h1_elements"), list):
        out["h1_count"] = len(a["h1_elements"])
    counts = a.get("heading_counts") or {}
    jumps = [j for j in counts.get("skipped_level_jumps") or [] if isinstance(j, dict)]
    if isinstance(counts.get("skipped_level_jumps_total"), int) or jumps:
        out["heading_jumps"] = int(counts.get("skipped_level_jumps_total") or len(jumps))
        out["heading_jump_examples"] = list(dict.fromkeys(f"h{j.get('from')}→h{j.get('to')}" for j in jumps))[:4]
    if isinstance(a.get("html_lang"), str):
        out["html_lang"] = a["html_lang"]
    if isinstance(a.get("hreflang"), list):
        out["hreflang"] = len(a["hreflang"])
    if isinstance(a.get("visible_words"), int):
        out["words"] = a["visible_words"]
    if isinstance(a.get("main_region_chars"), int):
        out["main_chars"] = a["main_region_chars"]
    imgs = a.get("image_counts") or {}
    if imgs:
        out["images"] = sum(int((v or {}).get("total") or 0) for v in imgs.values() if isinstance(v, dict))
        out["images_missing_alt"] = sum(int((v or {}).get("missing_alt") or 0) for v in imgs.values() if isinstance(v, dict))
    # DECISIONS 354: an older report kept only the number of scripts; no list, no blocking-script count.
    scripts = [s for s in a.get("external_scripts") if isinstance(s, dict)] if isinstance(a.get("external_scripts"), list) else []
    if isinstance(a.get("external_scripts"), list):
        out["blocking_scripts"] = sum(1 for s in scripts if s.get("in_head") and not s.get("async") and not s.get("defer")
                                      and str(s.get("type") or "") in ("", "text/javascript"))
    tags = sorted({str(k) for v in (a.get("analytics_ids") or {}).values() if isinstance(v, dict) for k in v})
    if tags:
        out["analytics"] = tags[:6]
    types = (a.get("structured_data") or {}).get("types")
    if isinstance(types, list):
        out["schema_types"] = [str(t) for t in types][:8]
    for key in ("dead_link_total", "link_control_total"):
        if isinstance(a.get(key), int):
            out[key] = a[key]
    return out


def of_pages(pages) -> dict[str, dict]:
    """{url: record} for the pages whose content was read."""
    return {_get(p, "url"): measure(p) for p in pages or [] if isinstance(_get(p, "url"), str) and readable(p)}


def index(report: dict) -> dict[str, dict]:
    """{url: record} for a report: the stored `crawl.page_measures` (1.29), with any page it lacks worked out from the
    saved page records; for an older report, all from the saved page records."""
    crawl = report.get("crawl") or {}
    stored = crawl.get("page_measures")
    worked_out = of_pages(crawl.get("pages") or [])
    if isinstance(stored, dict):
        return {**worked_out, **{u: r for u, r in stored.items() if isinstance(r, dict)}}
    return worked_out
