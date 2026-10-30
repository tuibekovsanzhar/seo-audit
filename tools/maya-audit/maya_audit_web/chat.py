"""What the assistant says back: reads a message, finds a website address in it, proposes a plan.

Rule-based throughout. A message with an address becomes a plan (never a running audit: starting is
a separate, explicit action). A message without one is a question about the conversation's latest
report, answered by `followups`.
"""

from __future__ import annotations

import ipaddress
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from maya_audit.urls import is_loopback_host, normalize_url

from .strings import t

_EXPLICIT = re.compile(r"https?://[^\s<>\"'`]+", re.IGNORECASE)
_BARE = re.compile(r"(?<![\w@./-])((?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24})(:\d{2,5})?(/[^\s<>\"'`]*)?",
                   re.IGNORECASE)
# "robots.txt" and "sitemap.xml" in a question are file names, not sites.
_FILE_ENDINGS = frozenset("txt xml json html htm php js css pdf md png jpg jpeg gif svg csv zip py".split())
_STANDARD = re.compile(r"\b(standard|500|full|deep|thorough|standart|tam)\b", re.IGNORECASE)
_TRAILING = ".,;:!?)]}>'\""


class BadTarget(ValueError):
    """The address cannot be audited. `key` names the sentence that says why."""

    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.key = key


def find_address(text: str) -> str | None:
    """The first thing in `text` that reads as a website address, or None."""
    explicit = _EXPLICIT.search(text)
    if explicit:
        return explicit.group(0).rstrip(_TRAILING)
    for match in _BARE.finditer(text):
        if match.group(1).rsplit(".", 1)[-1].lower() not in _FILE_ENDINGS:
            return match.group(0).rstrip(_TRAILING)
    return None


def target_url(address: str, *, allow_loopback: bool = False) -> str:
    """A normalised http(s) URL that may be audited, or BadTarget.

    Checks the form only; nothing is looked up here. The engine validates every address a name
    resolves to before each request.
    """
    raw = address.strip()
    if not re.match(r"^https?://", raw, re.IGNORECASE):
        raw = ("http://" if allow_loopback and is_loopback_host(urlsplit("//" + raw).hostname or "") else "https://") + raw
    try:
        parts = urlsplit(raw)
        host = (parts.hostname or "").lower()
        parts.port  # noqa: B018  raises on a port that is not a number
    except ValueError:
        raise BadTarget("chat.bad_url") from None
    if parts.scheme.lower() not in ("http", "https") or not host or parts.username or parts.password:
        raise BadTarget("chat.bad_url")
    if is_loopback_host(host):
        if not allow_loopback:
            raise BadTarget("chat.private_url")
    else:
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is not None and not address.is_global:
            raise BadTarget("chat.private_url")
        # A name must end in a real top-level label: "0x7f.1" and "10.1" are other spellings of an IP address.
        if address is None and not re.fullmatch(r"(?:[a-z0-9_-]+\.)+(?:[a-z]{2,}|xn--[a-z0-9-]+)", host.rstrip(".")):
            raise BadTarget("chat.bad_url")
    normalised = normalize_url(urlunsplit((parts.scheme.lower(), parts.netloc, parts.path or "/", parts.query, "")))
    if not normalised:
        raise BadTarget("chat.bad_url")
    return normalised


def https_first(address: str, *, allow_loopback: bool = False) -> tuple[str, str | None]:
    """(the URL to audit, the http:// URL to fall back to or None).

    An address typed with http://, or with no scheme, is audited over https://. Only if https:// does not answer
    at all is the http:// address tried. An address typed with https:// has no fallback: the person asked for it.
    Local test sites are left as typed.
    """
    url = target_url(address, allow_loopback=allow_loopback)
    parts = urlsplit(url)
    if is_loopback_host(parts.hostname or ""):
        return url, None
    typed_https = bool(re.match(r"^https://", address.strip(), re.IGNORECASE))
    secure = urlunsplit(("https", *parts[1:]))
    plain = urlunsplit(("http", *parts[1:]))
    return secure, None if typed_https else plain


def wants_standard(text: str, address: str) -> bool:
    return bool(_STANDARD.search(text.replace(address, " ")))


def key_page_urls(site_url: str, lines: list[str], limit: int) -> list[str]:
    """Important pages as full URLs on the audited site. ValueError carries the sentence for the first bad one."""
    host = urlsplit(site_url).hostname or ""
    out: list[str] = []
    for line in lines:
        value = str(line).strip()
        if not value:
            continue
        if not re.match(r"^https?://", value, re.IGNORECASE) and not value.startswith("/"):
            # "pricing" and "example.com/pricing" both mean a page; only the second names a host.
            value = "https://" + value if value.split("/", 1)[0].lower().removeprefix("www.") == host.removeprefix("www.") \
                else "/" + value
        url = normalize_url(value, site_url)
        if not url or (urlsplit(url).hostname or "").removeprefix("www.") != host.removeprefix("www."):
            raise ValueError(t("plan.key_pages.bad", host=host, value=value[:200]))
        if value.startswith("http") and urlsplit(url).scheme != urlsplit(site_url).scheme:
            url = urlunsplit(urlsplit(url)._replace(scheme=urlsplit(site_url).scheme))
        if url not in out:
            out.append(url)
    if len(out) > limit:
        raise ValueError(t("plan.key_pages.too_many", limit=limit))
    return out


def text_message(text: str, **extra: Any) -> dict[str, Any]:
    return {"text": text, **extra}
