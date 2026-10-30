"""Optional check that the crawler's public information page is available.

The audit records this page's status for transparency. A live site crawl can
start without it, and an unavailable page does not block the site audit.
"""

from __future__ import annotations

from urllib.parse import urlsplit, urljoin
import time


from .fetcher import Fetcher, utc_now
from .urls import is_loopback_host

UNPUBLISHED_MARKER = "REPLACE-BEFORE-PUBLISHING"
RESERVED_SUFFIXES = (".invalid", ".example", ".test", ".localhost", ".local")


class BotInfoPageNotReady(ValueError):
    pass


def validate_bot_info_url(url: str | None, allow_loopback: bool = False) -> None:
    if not url:
        raise BotInfoPageNotReady(
            "no bot info URL configured: live crawls need a public page explaining Maya-Audit "
            "(pass --bot-info-url)"
        )
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if allow_loopback and is_loopback_host(host):
        return
    if parts.scheme != "https":
        raise BotInfoPageNotReady(f"bot info URL must use https: {url}")
    if not host or is_loopback_host(host) or host.endswith(RESERVED_SUFFIXES) or host in ("example.com", "example.org", "example.net"):
        raise BotInfoPageNotReady(f"bot info URL is not on a real public domain: {url}")


def check_bot_info_page(url: str | None, user_agent: str, product_token: str, timeout_s: float = 15.0, allow_loopback: bool = False, *, deadline_mono: float | None = None, stop_check=None) -> dict:
    """GET the info page and require 200, the product token, and no unpublished marker."""
    validate_bot_info_url(url, allow_loopback)
    checked_at = utc_now()
    fetcher = Fetcher(user_agent, timeout_s, 0, block_loopback=not allow_loopback)
    fetcher.deadline_mono = min(deadline_mono or float("inf"), time.monotonic() + timeout_s)
    fetcher.stop_check = stop_check
    try:
        current = url
        for _ in range(6):
            response = fetcher.get(current, "bot_info", 1024 * 1024)
            if response.error or response.truncated:
                raise BotInfoPageNotReady("bot info page unavailable, interrupted, unsafe, or over the size limit")
            if not (response.status and 300 <= response.status < 400 and response.headers.get("location")):
                break
            next_url = urljoin(current, response.headers["location"])
            if urlsplit(next_url).scheme != "https":
                raise BotInfoPageNotReady(f"bot info redirect must use https: {next_url}")
            current = next_url
        else:
            raise BotInfoPageNotReady(f"too many redirects from bot info URL: {url}")
    finally:
        fetcher.close()
    text = response.body.decode("utf-8", "replace")

    evidence = {
        "url": url,
        "final_url": current,
        "status": response.status,
        "checked_at": checked_at,
        "mentions_product_token": product_token in text,
        "contains_unpublished_marker": UNPUBLISHED_MARKER in text,
    }
    if response.status != 200:
        raise BotInfoPageNotReady(f"bot info page returned {response.status}: {url}")
    if not evidence["mentions_product_token"]:
        raise BotInfoPageNotReady(f"bot info page does not mention {product_token!r}: {url}")
    if evidence["contains_unpublished_marker"]:
        raise BotInfoPageNotReady(f"bot info page still contains the {UNPUBLISHED_MARKER} placeholder: {url}")
    return evidence
