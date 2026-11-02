"""Firecrawl settings, prices and the key. This is the only file that holds them.

CHECK THESE AGAINST FIRECRAWL'S OWN DOCUMENTATION AND YOUR ACCOUNT before relying on them. They were read from
docs.firecrawl.dev on 2026-10-07 through a summarising reader, not from a live response, and no real request was
made while this was written:

- endpoint: POST https://api.firecrawl.dev/v2/scrape, `Authorization: Bearer <key>`
- `proxy`: "basic", "enhanced" or "auto" (the service's own default is "auto"; "stealth" is the older name for
  "enhanced"). Maya always sends the value explicitly, so the service never chooses.
- `zeroDataRetention: true` costs one extra credit per page and has to be enabled for the account by Firecrawl.
- a scrape is 1 credit per page; a request that returns no document is not charged.
- no price per credit in dollars is published: it depends on the account's plan.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ..dataforseo.cache import Cache
from ..dataforseo.credentials import REDACTED, data_dir, read_env_file
from ..dataforseo.ledger import Ledger

BASE_URL = "https://api.firecrawl.dev"
SCRAPE = "/v2/scrape"
KEY_VAR = "MAYA_AUDIT_FIRECRAWL_API_KEY"
ENV_FILE_VAR = "MAYA_AUDIT_ENV_FILE"
RATE_VAR = "MAYA_AUDIT_FIRECRAWL_USD_PER_CREDIT"
DAILY_VAR = "MAYA_AUDIT_FIRECRAWL_DAILY_CREDITS"
ZDR_VAR = "MAYA_AUDIT_FIRECRAWL_ZERO_DATA_RETENTION"
OFF_VAR = "MAYA_AUDIT_FIRECRAWL"
LEDGER_NAME = "firecrawl-ledger.jsonl"
CACHE_NAME = "firecrawl-cache.db"

CREDITS_PER_PAGE = 1
# A challenged site's sitemap asked for through the reader: at most this many documents, and only from this page cap up.
SITEMAP_REQUESTS = 2
SITEMAP_MIN_PAGE_CAP = 10
ZERO_DATA_RETENTION_EXTRA_CREDITS = 1
# What one credit costs in US dollars on this account's plan. None means "not set": plans and reports then show
# credits only and say the dollar amount is unknown. Set it here, or with MAYA_AUDIT_FIRECRAWL_USD_PER_CREDIT.
USD_PER_CREDIT: float | None = None
# Pages Firecrawl may read in one audit unless the person chooses otherwise.
DEFAULT_MAX_PAGES = 50
# Firecrawl requests in flight at once (DECISIONS 294; Owner, 2026-11-02: the plan is Standard, 25 concurrent browsers).
# The setting is 1 to 10; on a 429, a 5xx or a timeout it backs off to 2, then 1 (maya_audit.firecrawl.pace). Maya's
# own limit on the site (maya_audit.sitelimit) does not cap it (DECISIONS 295).
CONCURRENCY_VAR = "MAYA_AUDIT_FIRECRAWL_CONCURRENCY"
DEFAULT_CONCURRENCY = 5
MIN_CONCURRENCY, MAX_CONCURRENCY = 1, 10
# Firecrawl's own pace (DECISIONS 295; Owner, 2026-11-02): its requests come from Firecrawl's network, not this
# computer's, so they keep their own gap instead of Maya's polite one: request starts at least this many seconds apart.
# A robots.txt Crawl-delay is a floor. Each back-off step (Firecrawl's 429 or 5xx, the site's 429 or 5xx seen through
# Firecrawl, a timed-out call) doubles it, to at most four times the setting.
GAP_VAR = "MAYA_AUDIT_FIRECRAWL_GAP_S"
DEFAULT_GAP_S = 1.0
MIN_GAP_S, MAX_GAP_S = 0.2, 30.0
# This computer's setting may also be 0 (no gap): only for test machines, never offered in a plan.
# A page whose call timed out is asked for once more after this many seconds (DECISIONS 295, agent default).
RETRY_WAIT_S = 5.0
MAX_PAGES_LIMIT = 500
# Credits that may be spent or reserved in one UTC day (the ledger's day). Firecrawl reads every audit's pages, so this
# is a guard against a runaway, not a budget: ten Standard audits with zero data retention. MAYA_AUDIT_FIRECRAWL_DAILY_CREDITS changes it.
DAILY_CREDITS = 10000
# Maya's own copy of a page read through Firecrawl. One day, and only for the audit that made it (A16): a new audit,
# even on the same day, reads the site again and shows what the client fixed. A resumed audit that may spend nothing
# more can still re-use the copies its first run made (for a week).
CACHE_LIFETIME_S = 24 * 60 * 60
# The field of a cached answer that names the audit that paid for it (A16). Never sent to Firecrawl.
CACHE_AUDIT_FIELD = "_maya_audit_id"
RESUME_CACHE_LIFETIME_S = 7 * 24 * 60 * 60
PROXIES = ("basic", "enhanced", "auto")
# The only proxy used without the site owner's stated approval. The others exist to get past bot protection.
DEFAULT_PROXY = "basic"
TIMEOUT_S = 90.0
MAX_RESPONSE_BYTES = 12 * 1024 * 1024


@dataclass(frozen=True, repr=False)
class FirecrawlKey:
    value: str

    def __repr__(self) -> str:  # a stray print() or traceback must not show the key
        return "FirecrawlKey([redacted])"

    def authorization(self) -> str:
        return "Bearer " + self.value

    def redact(self, text: str) -> str:
        return text.replace(self.value, REDACTED) if len(self.value) >= 3 else text


def _environment(environ: Mapping[str, str] | None) -> tuple[Mapping[str, str], dict[str, str]]:
    environ = os.environ if environ is None else environ
    return environ, read_env_file(Path(environ.get(ENV_FILE_VAR) or ".env"))


def load_key(environ: Mapping[str, str] | None = None) -> FirecrawlKey | None:
    """The key from the environment, falling back to the .env file, exactly as the DataForSEO credentials are read."""
    environ, from_file = _environment(environ)
    value = environ.get(KEY_VAR) or from_file.get(KEY_VAR)
    return FirecrawlKey(value) if value else None


def usd_per_credit(environ: Mapping[str, str] | None = None) -> float | None:
    """The configured dollar price of one credit, or None when nobody has set it."""
    environ, from_file = _environment(environ)
    raw = environ.get(RATE_VAR) or from_file.get(RATE_VAR)
    if raw:
        try:
            value = float(raw)
            return value if 0 < value < 10 else None
        except ValueError:
            return None
    return USD_PER_CREDIT


def daily_credits(environ: Mapping[str, str] | None = None) -> int:
    environ, from_file = _environment(environ)
    raw = environ.get(DAILY_VAR) or from_file.get(DAILY_VAR)
    try:
        return max(0, int(raw)) if raw else DAILY_CREDITS
    except ValueError:
        return DAILY_CREDITS


_NO = {"0", "off", "false", "no"}


def zero_data_retention_wanted(environ: Mapping[str, str] | None = None) -> bool:
    """Zero data retention is asked for unless this computer's settings say "off" (an account without it refuses every request)."""
    environ, from_file = _environment(environ)
    return (environ.get(ZDR_VAR) or from_file.get(ZDR_VAR) or "on").strip().lower() not in _NO


def main_reader_on(environ: Mapping[str, str] | None = None) -> bool:
    """Firecrawl reads every audit's pages when a key is set, unless MAYA_AUDIT_FIRECRAWL=off."""
    environ, from_file = _environment(environ)
    return (environ.get(OFF_VAR) or from_file.get(OFF_VAR) or "on").strip().lower() not in _NO


def concurrency(environ: Mapping[str, str] | None = None) -> int:
    """Firecrawl requests in flight at once on this computer: MAYA_AUDIT_FIRECRAWL_CONCURRENCY, 1 to 10, else 5."""
    environ, from_file = _environment(environ)
    raw = environ.get(CONCURRENCY_VAR) or from_file.get(CONCURRENCY_VAR)
    try:
        value = int(raw) if raw else DEFAULT_CONCURRENCY
    except ValueError:
        return DEFAULT_CONCURRENCY
    return max(MIN_CONCURRENCY, min(MAX_CONCURRENCY, value))


def gap_s(environ: Mapping[str, str] | None = None) -> float:
    """Seconds between Firecrawl request starts on this computer: MAYA_AUDIT_FIRECRAWL_GAP_S, else 1. 0 (a test machine)
    is kept as 0; any other value is held to 0.2 to 30."""
    environ, from_file = _environment(environ)
    raw = environ.get(GAP_VAR) or from_file.get(GAP_VAR)
    try:
        value = float(raw) if raw else DEFAULT_GAP_S
    except ValueError:
        return DEFAULT_GAP_S
    if value == 0:
        return 0.0
    return max(MIN_GAP_S, min(MAX_GAP_S, value))


def credits_per_page(zero_data_retention: bool = True) -> int:
    return CREDITS_PER_PAGE + (ZERO_DATA_RETENTION_EXTRA_CREDITS if zero_data_retention else 0)


def open_stores() -> tuple[Ledger, Cache]:
    """Firecrawl's own ledger (amounts are credits) and cache, beside DataForSEO's in ~/.maya-audit."""
    home = data_dir()
    return Ledger(home / LEDGER_NAME), Cache(home / CACHE_NAME)


@dataclass(frozen=True)
class Options:
    """What one audit may do with Firecrawl. All of it is chosen by the person, per audit, and written to the report."""
    read_blocked: bool = True          # read page content when Maya's own crawler was blocked
    read_always: bool = False          # the main page reader: read every audit's pages, blocked or not
    # How the reader chooses and finds pages (maya_audit.firecrawl.reading). Each can be switched off to measure it.
    spread_by_section: bool = True     # the crawler's order: key pages, navigation, the least-read section first
    sitemap_discovery: bool = False    # ask the reader for the sitemap when Maya's own crawler could not read one (on in the app and CLI)
    stop_after_unreadable: int = 5     # stop asking after this many unreadable answers in a row (0: never)
    render_fallback: bool = False      # render the sampled pages when the local browser cannot start
    max_pages: int = DEFAULT_MAX_PAGES
    proxy: str = DEFAULT_PROXY
    owner_approved_bypass: bool = False   # "The site owner has approved bypassing bot protection"
    allow_without_zero_data_retention: bool = False  # explicit, per audit, after Firecrawl refused it
    concurrency: int = DEFAULT_CONCURRENCY  # requests in flight at once, 1 to 10 (DECISIONS 294)
    # Seconds between request starts, Firecrawl's own pace (DECISIONS 295). None: this computer's setting (`gap_s()`).
    gap_s: float | None = None

    def problem(self) -> str | None:
        """Why these options may not be used, or None."""
        if self.proxy not in PROXIES:
            return f"proxy must be one of {', '.join(PROXIES)}"
        if self.proxy != DEFAULT_PROXY and not self.owner_approved_bypass:
            return (f'the "{self.proxy}" proxy is for getting past bot protection and may be used only when the site '
                    "owner has approved that for this audit")
        if not 1 <= self.max_pages <= MAX_PAGES_LIMIT:
            return f"the Firecrawl page cap must be between 1 and {MAX_PAGES_LIMIT}"
        if not MIN_CONCURRENCY <= self.concurrency <= MAX_CONCURRENCY:
            return f"Firecrawl requests at once must be between {MIN_CONCURRENCY} and {MAX_CONCURRENCY}"
        if self.gap_s is not None and not MIN_GAP_S <= self.gap_s <= MAX_GAP_S:
            return f"the gap between Firecrawl requests must be between {MIN_GAP_S:g} and {MAX_GAP_S:g} seconds"
        return None

    def estimate(self, audit_page_cap: int) -> dict[str, Any]:
        """The most this audit could spend: every allowed page, plus robots.txt and the sitemap documents the reader may
        be asked for, at the price with zero data retention."""
        pages = min(self.max_pages, audit_page_cap) + 1  # + robots.txt, when Maya could not read it either
        extra = SITEMAP_REQUESTS if self.sitemap_discovery and min(self.max_pages, audit_page_cap) >= SITEMAP_MIN_PAGE_CAP else 0
        credits = (pages + extra) * credits_per_page(not self.allow_without_zero_data_retention)
        rate = usd_per_credit()
        return {"max_requests": pages + extra, "max_pages": pages - 1, "credits_per_page": credits_per_page(not self.allow_without_zero_data_retention),
                "max_credits": credits, "usd_per_credit": rate, "max_usd": None if rate is None else round(credits * rate, 4)}

    def as_dict(self) -> dict[str, Any]:
        return {"read_blocked": self.read_blocked, "read_always": self.read_always, "spread_by_section": self.spread_by_section,
                "sitemap_discovery": self.sitemap_discovery, "stop_after_unreadable": self.stop_after_unreadable, "render_fallback": self.render_fallback, "max_pages": self.max_pages,
                "proxy": self.proxy, "owner_approved_bypass": self.owner_approved_bypass,
                "allow_without_zero_data_retention": self.allow_without_zero_data_retention, "concurrency": self.concurrency,
                "gap_s": self.gap_s}
