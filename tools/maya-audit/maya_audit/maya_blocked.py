"""Maya's own crawler blocked by 429s on pages while the site's files are served (DECISIONS 288).

nihan.com.tr (a Shopify store behind Cloudflare) answered every page request from Maya's crawler with 429 and
`Retry-After: 60`, also after the one wait (286), while robots.txt, 26 sitemap files and llms.txt came back 200 in the
same minutes. That is a rule against this crawler on pages, not "too many requests": the report says so instead of
"rate limited", and the Firecrawl reader may go on past the homepage only when the site owner approved bypassing bot
protection for the audit.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

LABEL = "blocked for Maya's crawler (429 on pages)"
SITE_FILES = ("robots", "robots_sample", "sitemap", "llms")


def _get(value: Any, name: str):
    return value.get(name) if isinstance(value, dict) else getattr(value, name, None)


def holds(result: Any) -> bool:
    """Every page Maya asked for answered 429, the start page among them, nothing was read, and a site file (robots.txt,
    a sitemap, llms.txt) on the same host was served with 200."""
    pages = [p for p in _get(result, "pages") or [] if not (isinstance(_get(p, "status"), int) and 300 <= _get(p, "status") < 400)]
    if not pages or any(_get(p, "status") != 429 for p in pages):
        return False
    start = next((p for p in pages if _get(p, "discovered_via") == "start"), None)
    if start is None:
        return False
    host = (urlsplit(_get(start, "url") or "").hostname or "").lower()
    return any(_get(r, "purpose") in SITE_FILES and _get(r, "status") == 200
               and (urlsplit(_get(r, "url") or "").hostname or "").lower() == host for r in _get(result, "requests") or [])


def served_files(result: Any) -> dict:
    """DECISIONS 320: which site files the site served (200, on the start page's host, "www." aside) while pages were
    refused: {"robots": bool, "sitemaps": int, "llms": bool}. Read from the crawl's request log, so a saved report says it
    too; the report's words name what loaded, never more than the log shows."""
    def bare(url):
        host = (urlsplit(url or "").hostname or "").lower()
        return host[4:] if host.startswith("www.") else host
    start = next((p for p in _get(result, "pages") or [] if _get(p, "discovered_via") == "start"), None)
    host = bare(_get(start, "url") if start is not None else _get(result, "start_url"))
    ok = [r for r in _get(result, "requests") or [] if _get(r, "status") == 200 and bare(_get(r, "url")) == host]
    sitemaps = {_get(r, "url") for r in ok if _get(r, "purpose") == "sitemap"}
    return {"robots": any(_get(r, "purpose") in ("robots", "robots_sample") for r in ok), "sitemaps": len(sitemaps),
            "llms": any(_get(r, "purpose") == "llms" for r in ok)}


def label(result: Any) -> None:
    """Name it in the crawl's stop detail, once, so every output says the same."""
    detail = _get(result, "stop_detail") or ""
    if holds(result) and not detail.startswith(LABEL):
        result.stop_detail = f"{LABEL}: {detail}" if detail else LABEL
