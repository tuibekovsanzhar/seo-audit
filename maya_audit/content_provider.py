"""Small contract for opt-in commercial HTML readers, not a bypass implementation.

Adapters own provider-specific pricing and transport. They must use the existing
locked Ledger/Cache, reserve before sending, enforce the confirmed ceiling and
daily budget, and retain ambiguous reservations without retrying paid calls.
The web/CLI entry point confirms a priced plan before constructing an adapter.
No provider is selected or enabled by importing this module.
"""
from dataclasses import dataclass
from typing import Any, Protocol


class ContentProviderError(RuntimeError):
    """Safe, credential-redacted provider failure."""


class ContentLoadError(ContentProviderError):
    """A no-document provider error: other URLs may be attempted, never this one again."""

    def diagnostic(self, url: str) -> dict[str, Any]:
        raise NotImplementedError


class ProviderLimitReached(ContentProviderError):
    """Stop collection but keep content already obtained."""


class ProviderStopped(ProviderLimitReached):
    """The audit was stopped or ran out of time: nothing was reserved or sent for this request. Content already
    obtained is kept, and the address is not recorded as a failed page."""


class ProviderRetentionRequired(ContentProviderError):
    """Stop until the user makes a separate data-retention decision."""


@dataclass(frozen=True)
class ProviderIdentity:
    id: str
    name: str

    def source(self, context: str) -> str:
        return f"Source: {self.name} ({context})"


@dataclass(frozen=True)
class ProviderConsent:
    enabled: bool = False
    owner_approved: bool = False

    def require(self, *, unblocking: bool) -> None:
        if not self.enabled:
            raise ContentProviderError("content provider is off for this audit")
        if unblocking and not self.owner_approved:
            raise ContentProviderError("the site owner has not approved bypassing bot protection for this audit")


class ContentPage(Protocol):
    url: str
    final_url: str
    status: int | None
    html: str
    content_type: str | None
    cached: bool
    fetched_at: str


class ContentProvider(Protocol):
    """A confirmed, guarded reader. The reader never calls an unguarded transport.

Unblocking adapters must require owner approval even on cache access. Successful
pages provide HTML, not invented HTTP evidence; only content checks consume them.
"""
    identity: ProviderIdentity
    consent: ProviderConsent
    calls: list[dict[str, Any]]
    requests_sent: int

    def scrape(self, url: str, *, wait_ms: int = 0) -> ContentPage: ...
    def close(self) -> None: ...
