"""Firecrawl: an optional, paid, third-party reader for pages Maya's own crawler was not allowed to read.

Nothing here runs unless an audit is started with Firecrawl switched on and its cost confirmed. Every request
goes through `FirecrawlClient.scrape`, which is where the page cap, the approved credits, the daily budget, the
ledger and the cache live. Maya's own crawler always runs first and stays the test of access: what Firecrawl reads
never changes an access, robots.txt, header, redirect or timing result.
"""

from .client import (ApprovalRequired, FirecrawlClient, FirecrawlError, FirecrawlPage, InsufficientCredits, NoKey,
                     PossiblyBilled, ProviderRateLimited, ZeroDataRetentionUnavailable)
from .settings import FirecrawlKey, Options, load_key, open_stores

__all__ = ["ApprovalRequired", "FirecrawlClient", "FirecrawlError", "FirecrawlKey", "FirecrawlPage", "InsufficientCredits",
           "NoKey", "Options", "PossiblyBilled", "ProviderRateLimited", "ZeroDataRetentionUnavailable", "load_key", "open_stores"]
