"""The one place a Firecrawl request is sent from.

`FirecrawlClient.scrape` is the only function that talks to the API, and the guard is inside it: page cap,
approved credits, daily budget, ledger reservation, cache. A caller cannot reach the network without passing all
of them. Nothing is retried: a request with no usable answer keeps its reservation, because it may have been charged.

Every request names its proxy and asks for zero data retention, and tells Firecrawl not to keep the page in its own
cache. If Firecrawl refuses zero data retention, the client stops and says so. It never sends the request again
without it; only a client built with `allow_without_zero_data_retention=True` (the person's explicit choice for
that audit) leaves it out.
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

import httpx

from ..content_provider import (ContentLoadError, ContentProviderError, ProviderConsent, ProviderIdentity,
                                ProviderLimitReached, ProviderRetentionRequired, ProviderStopped)
from ..runclock import RunClock
from ..dataforseo.cache import Cache
from ..dataforseo.ledger import BudgetExceeded, Ledger
from ..network import PublicTransport
from ..urls import UnsafeTargetError
from . import settings
from .settings import FirecrawlKey

# Tests replace this with a mock transport. Nothing else should.
TRANSPORT: httpx.BaseTransport | None = None
_ZDR = re.compile(r"zero.?data.?retention|\bzdr\b", re.IGNORECASE)


class FirecrawlError(ContentProviderError):
    """A Firecrawl request failed or was refused. The message never contains the key."""


class WebsiteLoadError(ContentLoadError, FirecrawlError):
    """A provider-side failure, not evidence that the target blocked a browser."""

    def __init__(self, status: int, message: str):
        self.status = status
        self.provider_message = message
        match = re.search(r"Engines tried:\s*\[([^]]*)\]", message, re.IGNORECASE)
        self.engines = [e.strip().strip("\"'") for e in match.group(1).split(",") if e.strip()] if match else []
        self.engine_selection = bool(self.engines) and set(self.engines) <= {"pdf", "document", "image"}
        super().__init__(f"Firecrawl could not load the page as a website (HTTP {status}): {message}")

    def diagnostic(self, url: str) -> dict[str, Any]:
        return {"url": url, "http_status": self.status, "message": self.provider_message,
                "engines_tried": self.engines,
                "kind": "engine_selection" if self.engine_selection else "provider_load_failure",
                "meaning": "Firecrawl could not load the page as a website",
                "note": ("Only file engines were listed; possible request configuration or provider routing problem. "
                         "This does not prove the site blocked Firecrawl." if self.engine_selection else
                         "No website document was returned. This alone does not prove a bot-protection block.")}


class NoKey(FirecrawlError):
    pass


class ApprovalRequired(FirecrawlError):
    pass


class PageCapReached(ProviderLimitReached, FirecrawlError):
    pass


class Stopped(ProviderStopped, FirecrawlError):
    """A stop or the audit's deadline arrived before this request: nothing was reserved or sent."""


class InsufficientCredits(FirecrawlError):
    """Firecrawl said the account has no credit (HTTP 402). Not Maya's own daily budget."""


class PossiblyBilled(FirecrawlError):
    """The request was sent and no usable answer came back: it may have been charged, and it is not retried."""


class ZeroDataRetentionUnavailable(ProviderRetentionRequired, FirecrawlError):
    """Firecrawl refused a request that asked for zero data retention. Nothing was retried without it."""


@dataclass
class FirecrawlPage:
    url: str
    final_url: str
    status: int | None
    html: str
    content_type: str | None
    cached: bool
    credits: int
    fetched_at: str
    proxy: str
    zero_data_retention: bool


class FirecrawlClient:
    identity = ProviderIdentity("firecrawl", "Firecrawl")

    def __init__(self, key: FirecrawlKey | None, ledger: Ledger, cache: Cache | None, *, approved_credits: float,
                 max_pages: int = settings.DEFAULT_MAX_PAGES, daily_credits: float | None = None,
                 proxy: str = settings.DEFAULT_PROXY, allow_without_zero_data_retention: bool = False,
                 owner_approved_bypass: bool = False,
                 audit_id: str | None = None, transport: httpx.BaseTransport | None = None,
                 should_stop: Callable[[], bool] | None = None, clock: RunClock | None = None, resumed: bool = False) -> None:
        if proxy not in settings.PROXIES:
            raise ValueError(f"unknown Firecrawl proxy {proxy!r}")
        self.key, self.ledger, self.cache = key, ledger, cache
        self.approved_credits = approved_credits
        self.max_pages = max_pages
        self.daily_credits = settings.daily_credits() if daily_credits is None else daily_credits
        self.proxy = proxy
        self.consent = ProviderConsent(enabled=True, owner_approved=owner_approved_bypass)
        self.zero_data_retention = not allow_without_zero_data_retention
        self.audit_id = audit_id or uuid.uuid4().hex[:12]
        # A resumed crawl (the command line's --resume, whose audit id is new each run) may read the copies any earlier
        # run made, as one with no credits left always could (A16).
        self.resumed = resumed
        self.should_stop = should_stop
        # The audit's deadline, stop request and pace (maya_audit.runclock). A caller may set it after the crawl.
        self.clock = clock or RunClock(should_stop=should_stop)
        self.reserved_this_audit = 0.0
        self.requests_sent = 0
        self.zdr_refused = False
        # What was asked and what it cost, for the report. Never headers, never the key, never page content.
        self.calls: list[dict[str, Any]] = []
        self._http = httpx.Client(base_url=settings.BASE_URL, timeout=settings.TIMEOUT_S, trust_env=False,
                                  transport=transport or TRANSPORT or PublicTransport(allow_loopback=False))

    def close(self) -> None:
        self._http.close()

    def _clean(self, text: str) -> str:
        return self.key.redact(text) if self.key else text

    def body_for(self, url: str, *, wait_ms: int = 0) -> dict[str, Any]:
        """The request body. One place, so every request carries the same safety settings."""
        body: dict[str, Any] = {
            "url": url, "formats": ["rawHtml"], "onlyMainContent": False,
            "proxy": self.proxy,              # always sent: the service's own default would escalate by itself
            "storeInCache": False, "maxAge": 0,  # Firecrawl's cache off: neither stored there nor served from there
            "skipTlsVerification": False, "blockAds": True, "removeBase64Images": True,
            # blockAds=False filters out browser engines in Firecrawl's public engine selector.
            "parsers": [], "mobile": False,  # HTML reader: no paid PDF/OCR parsing or mobile emulation
            "timeout": int(settings.TIMEOUT_S * 1000) - 5000,
        }
        if self.zero_data_retention:
            body["zeroDataRetention"] = True
        if wait_ms:
            body["waitFor"] = wait_ms
        return body

    def scrape(self, url: str, *, wait_ms: int = 0) -> FirecrawlPage:
        """Read one page through Firecrawl, after every check has passed. Raises FirecrawlError; never retries."""
        try:
            self.consent.require(unblocking=self.proxy != settings.DEFAULT_PROXY)
        except ContentProviderError as exc:
            raise ApprovalRequired(str(exc)) from None
        blocked = self.clock.why_not() or ("the audit was stopped on request" if self.should_stop is not None and self.should_stop() else None)
        if blocked:
            raise Stopped(f"{blocked}; no further Firecrawl request was sent")
        if self.zdr_refused:
            raise ZeroDataRetentionUnavailable("zero data retention not available; no further request was sent")
        if self.key is None:
            raise NoKey("no Firecrawl key")
        payload = self.body_for(url, wait_ms=wait_ms)
        # The key leaves out the timeout: a cached page is the same page.
        cache_payload = {k: v for k, v in payload.items() if k != "timeout"}
        estimate = settings.credits_per_page(self.zero_data_retention)
        if self.cache is not None:
            # A client with no credits to spend is a resumed audit: it may only re-read what its first run saved.
            lifetime = settings.RESUME_CACHE_LIFETIME_S if self.approved_credits <= 0 or self.resumed else settings.CACHE_LIFETIME_S
            held = self.cache.get(settings.SCRAPE, cache_payload, lifetime)
            # A copy is read back only by the audit that made it, or by a resumed audit (A16): a new audit, even the
            # same day, reads the site again and so shows what the owner has just fixed.
            if (held is not None and self.approved_credits > 0 and not self.resumed
                    and held[0].get(settings.CACHE_AUDIT_FIELD) != self.audit_id):
                held = None
            if held is not None:
                body, stored_at = held
                self.ledger.note("cache_hit", settings.SCRAPE, url, self.audit_id, cache="hit")
                page = self._page(url, body, cached=True, credits=0,
                                  at=datetime.fromtimestamp(stored_at, timezone.utc).isoformat(timespec="seconds"))
                self._record(page, estimate, "cache")
                return page
        # A request to the provider is a request to the audited site at one remove: it waits its turn like Maya's own,
        # and it is not started with too little time left to read the answer (it could be billed and thrown away).
        blocked = self.clock.wait_for_turn()
        if blocked:
            raise Stopped(f"{blocked}; no further Firecrawl request was sent")
        if self.requests_sent >= self.max_pages + 1:  # + robots.txt
            # What is counted, and paid for, is requests: one that leads to a page already read still counts.
            raise PageCapReached(f"the Firecrawl request allowance of {self.max_pages + 1} for this audit is used "
                                 f"({self.max_pages} plus one bootstrap reserve). No request was sent.")
        if round(self.reserved_this_audit + estimate, 6) > round(self.approved_credits, 6):
            raise ApprovalRequired(f"this audit's Firecrawl requests would reach {self.reserved_this_audit + estimate:g} credits, "
                                   f"above the {self.approved_credits:g} confirmed. No request was sent.")
        try:
            call_id = self.ledger.reserve(settings.SCRAPE, url, self.audit_id, estimate, self.daily_credits)
        except BudgetExceeded as exc:
            raise FirecrawlError(str(exc).replace("DataForSEO daily budget", "Firecrawl daily budget").replace("$", "")
                                 + " (amounts are credits)") from None
        self.reserved_this_audit = round(self.reserved_this_audit + estimate, 6)
        limit = self.clock.timeout(settings.TIMEOUT_S)
        payload["timeout"] = max(1000, int(limit * 1000) - 5000)  # the provider's own limit, inside ours
        self.clock.site_was_asked()
        body = self._send(url, payload, call_id, estimate, limit)
        self.ledger.settle(call_id, "settled", float(estimate))
        if self.cache is not None:
            self.cache.put(settings.SCRAPE, cache_payload, {**body, settings.CACHE_AUDIT_FIELD: self.audit_id})
        page = self._page(url, body, cached=False, credits=estimate, at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
        self._record(page, estimate, "charged")
        return page

    def _page(self, url: str, body: dict[str, Any], *, cached: bool, credits: int, at: str) -> FirecrawlPage:
        data = body.get("data") if isinstance(body.get("data"), dict) else {}
        meta = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
        status = meta.get("statusCode") if isinstance(meta.get("statusCode"), int) else None
        html = data.get("rawHtml") if isinstance(data.get("rawHtml"), str) else ""
        return FirecrawlPage(url=url, final_url=str(meta.get("url") or meta.get("sourceURL") or url), status=status, html=html,
                             content_type=meta.get("contentType") if isinstance(meta.get("contentType"), str) else None,
                             cached=cached, credits=credits, fetched_at=at, proxy=self.proxy,
                             zero_data_retention=self.zero_data_retention)

    def _record(self, page: FirecrawlPage, estimate: int, billing: str) -> None:
        self.calls.append({"url": page.url, "status": page.status, "bytes": len(page.html.encode("utf-8", "ignore")),
                           "from_cache": page.cached, "credits": page.credits, "estimate_credits": estimate,
                           "billing_status": billing, "data_from": page.fetched_at})

    def _failed(self, url: str, estimate: int, credits: float, billing: str) -> None:
        self.calls.append({"url": url, "status": None, "bytes": 0, "from_cache": False, "credits": credits,
                           "estimate_credits": estimate, "billing_status": billing,
                           "data_from": datetime.now(timezone.utc).isoformat(timespec="seconds")})

    def _send(self, url: str, payload: dict[str, Any], call_id: str, estimate: int, limit: float | None = None) -> dict[str, Any]:
        headers = {"Authorization": self.key.authorization()}
        limit = settings.TIMEOUT_S if limit is None else limit
        end = time.monotonic() + limit
        try:
            self.requests_sent += 1
            with self._http.stream("POST", settings.SCRAPE, headers=headers, json=payload, timeout=limit) as incoming:
                chunks, size = [], 0
                for chunk in incoming.iter_bytes():
                    if time.monotonic() >= end:
                        raise httpx.ReadTimeout("Firecrawl response took too long")
                    size += len(chunk)
                    if size > settings.MAX_RESPONSE_BYTES:
                        raise httpx.ReadError("Firecrawl response exceeds the size limit")
                    chunks.append(chunk)
                response = httpx.Response(incoming.status_code, content=b"".join(chunks))
        except UnsafeTargetError:
            self.requests_sent -= 1
            self.ledger.settle(call_id, "failed", 0.0, "unsafe destination; no connection made")
            self._failed(url, estimate, 0, "failed")
            raise FirecrawlError("the Firecrawl address failed network safety checks; no request was sent") from None
        except httpx.ConnectError as exc:
            self.ledger.settle(call_id, "failed", 0.0, f"not sent ({type(exc).__name__})")
            self._failed(url, estimate, 0, "failed")
            raise FirecrawlError(f"Firecrawl could not be reached ({type(exc).__name__})") from None
        except httpx.HTTPError as exc:
            # Sent, no usable answer: it may have done the work and charged for it. The reservation stays.
            self.ledger.settle(call_id, "possibly_billed", None, f"no answer ({type(exc).__name__}); not retried")
            self._failed(url, estimate, estimate, "possibly_billed")
            raise PossiblyBilled(f"Firecrawl did not answer ({type(exc).__name__}); it may have been charged and was not retried") from None
        try:
            body = response.json()
            if not isinstance(body, dict):
                raise ValueError("not a JSON object")
        except ValueError:
            if response.status_code < 400:
                self.ledger.settle(call_id, "possibly_billed", None, f"HTTP {response.status_code}, no usable response; not retried")
                self._failed(url, estimate, estimate, "possibly_billed")
                raise PossiblyBilled(f"Firecrawl answered HTTP {response.status_code} with no usable response; it may have been charged") from None
            body = {"error": response.text}
        if response.status_code >= 400 or body.get("success") is False:
            # Firecrawl returned no document: by its own billing rules this is not charged.
            message = self._clean(str(body.get("error") or body.get("message") or body.get("code") or ""))
            self.ledger.settle(call_id, "failed", 0.0, f"HTTP {response.status_code}: {message[:120]}")
            self._failed(url, estimate, 0, "failed")
            self.reserved_this_audit = round(self.reserved_this_audit - estimate, 6)
            if self.zero_data_retention and _ZDR.search(message):
                self.zdr_refused = True
                raise ZeroDataRetentionUnavailable(
                    "zero data retention not available: Firecrawl refused the request that asked for it "
                    f"(HTTP {response.status_code}). Nothing was sent without it.")
            if response.status_code == 402:
                raise InsufficientCredits("Firecrawl account credits are insufficient (HTTP 402). This is not Maya's own daily budget.")
            if response.status_code in (401, 403):
                raise FirecrawlError(f"Firecrawl refused the key or the request (HTTP {response.status_code}): {message}")
            if response.status_code == 429:
                raise FirecrawlError("Firecrawl's own rate limit was reached (HTTP 429); the request was not repeated")
            if response.status_code >= 500 or "all scraping engines failed" in message.lower():
                raise WebsiteLoadError(response.status_code, message)
            raise FirecrawlError(f"Firecrawl returned no document (HTTP {response.status_code}): {message}")
        if not isinstance((body.get("data") or {}).get("rawHtml"), str):
            self.ledger.settle(call_id, "possibly_billed", None, "answer without rawHtml; not retried")
            self._failed(url, estimate, estimate, "possibly_billed")
            raise PossiblyBilled("Firecrawl answered without the page's HTML; it may have been charged and was not retried")
        return body
