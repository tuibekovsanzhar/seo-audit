"""Declared bot policy and path-level intent markings (spec §1.7, §2.5)."""

from __future__ import annotations

from dataclasses import dataclass

from .robots import _matches, _normalize_octets
from .urls import request_target

# Spec §2.5 guardrail 3: only choices are markable, not defects.
MARKABLE_CHECKS = frozenset({"ACC-2", "ACC-3", "ACC-4", "ACC-7", "IDX-4", "IDX-7", "RND-5"})


@dataclass(frozen=True)
class DeclaredPolicy:
    """Onboarding answers (spec §8 Q2, F5). Bot-level only; never path-level."""

    training_bots: str | None = None  # "allow" | "block" | None (not declared)
    search_bots: str = "allow"  # search bots default to allowed


@dataclass(frozen=True)
class IntentMarking:
    """ "This condition, on this page or path pattern, is intended." """

    id: str
    check_id: str
    condition: str  # e.g. "noindex", "disallow", "challenged", "crawl-delay"
    scope: str  # absolute URL (exact page) or robots.txt-style path pattern
    token: str | None = None  # optional bot token (ACC checks only)
    marked_by: str = "unknown"
    marked_at: str = ""
    note: str = ""

    def __post_init__(self) -> None:
        if self.check_id not in MARKABLE_CHECKS:
            raise ValueError(f"{self.check_id} is not markable: its condition is a defect, not a choice (spec §2.5)")
        if self.token and not self.check_id.startswith("ACC-"):
            raise ValueError("bot-token scoping is only allowed on ACC checks")

    @property
    def is_exact(self) -> bool:
        return self.scope.lower().startswith(("http://", "https://"))


def find_marking(
    markings: tuple[IntentMarking, ...],
    check_id: str,
    condition: str,
    url: str,
    token: str | None,
    key_urls: set[str],
) -> tuple[IntentMarking | None, IntentMarking | None]:
    """Return (matching marking, pattern marking that was blocked by the key-page guardrail)."""
    target = _normalize_octets(request_target(url))
    blocked: IntentMarking | None = None
    for marking in markings:
        if marking.check_id != check_id or marking.condition != condition:
            continue
        if marking.token and (token is None or marking.token.lower() != token.lower()):
            continue
        if marking.is_exact:
            if marking.scope == url:
                return marking, None
            continue
        if _matches(marking.scope, target):
            if url in key_urls:  # guardrail 1: patterns never silently cover key pages
                blocked = blocked or marking
                continue
            return marking, None
    return None, blocked


def split_by_intent(
    markings: tuple[IntentMarking, ...],
    check_id: str,
    condition: str,
    items: list[tuple[str, str | None]],
    key_urls: set[str],
) -> tuple[list[tuple[str, str | None]], dict[str, list[tuple[str, str | None]]], list[dict]]:
    """Split (url, token) items into unmarked ones and ones covered by each marking."""
    unmarked: list[tuple[str, str | None]] = []
    covered: dict[str, list[tuple[str, str | None]]] = {}
    excluded: list[dict] = []
    for url, token in items:
        marking, blocked = find_marking(markings, check_id, condition, url, token, key_urls)
        if marking:
            covered.setdefault(marking.id, []).append((url, token))
        else:
            unmarked.append((url, token))
            if blocked:
                excluded.append({"url": url, "marking": blocked.id, "reason": "key page: pattern markings never cover key pages"})
    return unmarked, covered, excluded


def marking_by_id(markings: tuple[IntentMarking, ...], marking_id: str) -> IntentMarking:
    return next(m for m in markings if m.id == marking_id)
