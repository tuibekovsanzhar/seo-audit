"""Robots directives from meta tags and X-Robots-Tag headers, shared by ACC-3 and IDX checks."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

COLON_DIRECTIVES = {"max-snippet", "max-image-preview", "max-video-preview", "unavailable_after"}
META_NAMES = ("robots", "googlebot", "bingbot")


_WEEKDAY = re.compile(r"(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*\.?", re.I)


def _parts(content: str) -> list[str]:
    """The comma-separated parts of a robots value, with an unavailable_after date kept whole: Google accepts RFC 822
    and RFC 850 dates, which carry a comma after the weekday ("unavailable_after: Wed, 03 Nov 2027 15:00:00 GMT")."""
    out: list[str] = []
    for part in content.split(","):
        if out and _WEEKDAY.fullmatch(out[-1].rsplit(":", 1)[-1].strip()) and "unavailable_after" in out[-1].lower():
            out[-1] = f"{out[-1]},{part}"
        else:
            out.append(part)
    return out


def unavailable_after(value: str | None) -> datetime | None:
    """The moment an unavailable_after directive names (ISO 8601, RFC 822 or RFC 850), in UTC; None if unreadable.
    A date with no time or zone is read as UTC midnight."""
    text = (value or "").strip()
    if not text:
        return None
    when = None
    try:
        when = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            when = parsedate_to_datetime(text)
        except (TypeError, ValueError, IndexError):
            for fmt in ("%A, %d-%b-%y %H:%M:%S %Z", "%d %b %Y %H:%M:%S %Z", "%d %B %Y"):
                try:
                    when = datetime.strptime(text, fmt)
                    break
                except ValueError:
                    continue
    if when is None:
        return None
    return when.replace(tzinfo=timezone.utc) if when.tzinfo is None else when.astimezone(timezone.utc)


def parse_directive_list(content: str, scope: str) -> list[tuple[str, str, str | None]]:
    """Parse "googlebot: noindex, max-snippet:20" into (scope, directive, value) tuples."""
    out = []
    for part in _parts(content):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            left, right = (x.strip() for x in part.split(":", 1))
            if left.lower() not in COLON_DIRECTIVES:
                scope, part = left.lower(), right
                if not part:
                    continue
                if ":" in part:
                    left, right = (x.strip() for x in part.split(":", 1))
                    out.append((scope, left.lower(), right))
                    continue
            else:
                out.append((scope, left.lower(), right))
                continue
        out.append((scope, part.lower(), None))
    return out


def directives_for(analysis: dict, headers: dict[str, str]) -> list[dict]:
    found = []
    for meta in analysis["meta"]:
        if meta["name"] in META_NAMES:
            scope = "*" if meta["name"] == "robots" else meta["name"]
            raw = f'<meta name="{meta["name"]}" content="{meta["content"]}">'
            for s, directive, value in parse_directive_list(meta["content"], scope):
                found.append({"scope": s, "directive": directive, "value": value, "source": "meta", "raw": raw})
    header = headers.get("x-robots-tag")
    if header:
        for s, directive, value in parse_directive_list(header, "*"):
            found.append({"scope": s, "directive": directive, "value": value, "source": "X-Robots-Tag",
                          "raw": f"X-Robots-Tag: {header}"})
    return found


def page_directives(page) -> list[dict]:
    """Directives on a fetched response. A non-HTML response (a PDF, an image) can only carry them in the
    X-Robots-Tag header, which is the one way to keep such a file out of an index."""
    return directives_for(page.analysis or {"meta": []}, page.headers)


def noindex_directives(analysis: dict | None, headers: dict[str, str]) -> list[str]:
    """Raw noindex declarations that apply to all bots, Googlebot, or Bingbot.

    A response with no HTML analysis (a PDF, an unparsed or empty body) can still carry X-Robots-Tag (B05)."""
    return [d["raw"] for d in directives_for(analysis or {"meta": []}, headers)
            if d["directive"] in ("noindex", "none") and d["scope"] in ("*", "googlebot", "bingbot")]
