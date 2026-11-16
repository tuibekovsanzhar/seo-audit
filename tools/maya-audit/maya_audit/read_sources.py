"""Who read the pages, per source (DECISIONS 348): Maya's own crawler and the page reader (Firecrawl), each with the
pages it read, the block pages it got and its 429 answers, so a person sees which one failed.

From report.json only (live and saved audits alike); sends no request. A source that was not used says so, and a count
is never guessed: an answer of a kind the record does not say is counted as "other".
"""
from __future__ import annotations

from typing import Any


def _maya(crawl: dict) -> dict[str, Any]:
    from .client_selection import not_a_page
    asked = read = blocked = limited = other = 0
    for p in crawl.get("pages") or []:
        if not isinstance(p, dict):
            continue
        status, kind = p.get("status"), p.get("fetch_class")
        if isinstance(status, int) and 300 <= status < 400:
            continue  # a redirect is the site's answer on the way to a page, not a page asked for
        if not_a_page(p.get("url"), p.get("content_type")) and kind == "ok":
            continue  # a sitemap or feed file: not a page (DECISIONS 347)
        asked += 1
        if status == 429 or kind == "rate_limited":
            limited += 1
        elif kind == "blocked":
            blocked += 1
        elif kind == "ok" and isinstance(status, int) and 200 <= status < 300 and p.get("content_checks_eligible") is not False:
            read += 1
        else:
            other += 1
    return {"used": True, "asked": asked, "read": read, "blocked": blocked, "rate_limited": limited, "other": other,
            "stopped": crawl.get("stop_reason") if crawl.get("stop_reason") in ("rate_limit", "blocked", "time_limit") else None,
            "stop_detail": crawl.get("stop_detail") if crawl.get("stop_reason") in ("rate_limit", "blocked") else None}


def _reader(section: dict) -> dict[str, Any]:
    if not section or not section.get("enabled"):
        return {"used": False}
    asked = read = blocked = limited = other = 0
    for row in section.get("pages") or []:
        if not isinstance(row, dict):
            continue
        outcome = row.get("outcome")
        if outcome in ("skipped_without_request", "unsupported_resource", "redirected", "redirected_out_of_scope"):
            continue
        asked += 1
        reason = str(row.get("reason") or "")
        if row.get("status") == 429 or "HTTP 429" in reason or "rate limit" in reason.lower():
            limited += 1
        elif outcome == "blocked":
            blocked += 1
        elif outcome in ("read", "rendered"):
            read += 1
        else:
            other += 1
    coverage = section.get("coverage") or {}
    return {"used": bool(section.get("used") or asked), "asked": asked, "read": read, "blocked": blocked,
            "rate_limited": limited, "other": other, "not_requested": coverage.get("known_urls_not_requested"),
            "stopped_because": section.get("stopped_because") or (None if asked else section.get("reason"))}


def summary(report: dict) -> dict[str, Any] | None:
    """{"maya": {...}, "reader": {...}}: each source's requests and answers; None when no page was asked for."""
    crawl = report.get("crawl") or {}
    maya = _maya(crawl)
    reader = _reader(report.get("firecrawl") or {})
    if not maya["asked"] and not reader.get("asked"):
        return None
    return {"maya": maya, "reader": reader}


WORDS = {
    "tr": {"maya": "Maya'nın doğrudan tarayıcısı: {asked} sayfa isteği, {read} okundu, {blocked} engel sayfası, {limited} × 429",
           "stopped": {"rate_limit": "hız sınırında durdu", "blocked": "engellendiği için durdu", "time_limit": "süre sınırında durdu"},
           "reader": "Firecrawl: {asked} sayfa isteği, {read} okundu, {blocked} engel sayfası, {limited} × 429",
           "not_used": "Firecrawl: kullanılmadı",
           "other": "{n} başka yanıt", "not_requested": "{n} bilinen adres istenmedi"},
    "en": {"maya": "Maya's direct crawler: {asked} page requests, {read} read, {blocked} block pages, {limited} × 429",
           "stopped": {"rate_limit": "stopped by a rate limit", "blocked": "stopped by a block", "time_limit": "stopped by the time limit"},
           "reader": "Firecrawl: {asked} page requests, {read} read, {blocked} block pages, {limited} × 429",
           "not_used": "Firecrawl: not used",
           "other": "{n} other answers", "not_requested": "{n} known addresses not requested"},
}


def lines(info: dict | None, lang: str = "tr") -> list[str]:
    """Two sentences, one per source, in the report's language."""
    if not info:
        return []
    W = WORDS[lang]
    m, r = info["maya"], info["reader"]
    first = W["maya"].format(asked=m["asked"], read=m["read"], blocked=m["blocked"], limited=m["rate_limited"])
    extra = [W["other"].format(n=m["other"])] if m["other"] else []
    if m.get("stopped"):
        extra.append(W["stopped"][m["stopped"]])
    out = [first + (f" ({'; '.join(extra)})" if extra else "") + "."]
    if not r.get("used"):
        out.append(W["not_used"] + ".")
        return out
    second = W["reader"].format(asked=r["asked"], read=r["read"], blocked=r["blocked"], limited=r["rate_limited"])
    extra = [W["other"].format(n=r["other"])] if r["other"] else []
    if r.get("not_requested"):
        extra.append(W["not_requested"].format(n=r["not_requested"]))
    out.append(second + (f" ({'; '.join(extra)})" if extra else "") + ".")
    return out


def numbers(info: dict | None) -> list[int]:
    """Every number the two sentences print (the team report's validator checks each against the report)."""
    if not info:
        return []
    out = []
    for key in ("maya", "reader"):
        src = info[key]
        out += [src.get(k) for k in ("asked", "read", "blocked", "rate_limited", "other", "not_requested")
                if isinstance(src.get(k), int)]
    return out
