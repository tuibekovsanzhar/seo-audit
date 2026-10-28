"""Firecrawl in the web app: where its requests go, and what a plan shows before any of them is made.

The guard itself is `maya_audit.firecrawl` (page cap, approved credits, daily budget, ledger, cache, no retry,
zero data retention). This module only connects it: the key and stores for real use, stand-ins for tests and the
demonstration, and the plan section a person confirms. Firecrawl is off unless the person switches it on for
that audit, and nothing is sent until its maximum is confirmed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import httpx

from maya_audit import firecrawl as engine
from maya_audit.dataforseo.cache import Cache
from maya_audit.dataforseo.ledger import Ledger
from maya_audit.firecrawl import panel, reader, settings
from maya_audit.findings import check_id_key
from maya_audit.firecrawl.settings import FirecrawlKey, Options

from . import wording
from .strings import t

STATES = ("none", "pending", "attempted", "done", "needs_decision")


@dataclass
class FirecrawlServices:
    """Where Firecrawl requests go and how they are recorded. Tests and demo mode pass their own."""
    key: Callable[[], FirecrawlKey | None]
    stores: Callable[[], tuple[Ledger, Cache | None]]
    transport: httpx.BaseTransport | None = None
    # Whether the local browser can render pages; when it cannot, the rendering fallback is offered.
    browser_available: Callable[[], bool] = lambda: True

    @classmethod
    def real(cls) -> "FirecrawlServices":
        from . import pdf

        return cls(engine.load_key, engine.open_stores, browser_available=pdf.available)


def options_from(requested: dict[str, Any]) -> Options:
    return Options(read_blocked=True, read_always=bool(requested.get("read_always")), render_fallback=bool(requested.get("render_fallback")),
                   sitemap_discovery=bool(requested.get("sitemap_discovery", True)),
                   max_pages=int(requested.get("max_pages") or settings.DEFAULT_MAX_PAGES),
                   proxy=requested.get("proxy") or settings.DEFAULT_PROXY,
                   owner_approved_bypass=bool(requested.get("owner_approved_bypass")),
                   allow_without_zero_data_retention=bool(requested.get("allow_without_zero_data_retention")))


def plan(services: FirecrawlServices, requested: dict[str, Any] | None, audit_page_cap: int, rendering_wanted: bool) -> dict[str, Any]:
    """The Firecrawl part of a plan. Sends nothing. With `requested` None it shows what switching it on would cost."""
    options = options_from(requested or {})
    configured = services.key() is not None
    wanted = requested is not None
    # The spending record is opened only when Firecrawl could be used at all: a computer without a key gets no new file.
    ledger = services.stores()[0] if configured and wanted else _NothingSpent()
    shown = panel.plan(options, audit_page_cap, ledger, configured)
    # Asked only once Firecrawl is switched on: finding out means starting the local browser, which a plain plan never does.
    offer_render = wanted and rendering_wanted and not services.browser_available()
    return {**shown, "requested": wanted, "needs_confirmation": wanted and shown["needs_confirmation"], "main_reader": wanted and options.read_always,
            "blocked": shown["blocked"] if wanted else None, "available": configured,
            "spent_today_credits": shown["spent_today_credits"] if wanted else None,
            "render_fallback_offered": offer_render, "proxies": list(settings.PROXIES), "max_pages_limit": settings.MAX_PAGES_LIMIT,
            "lines": [t("fc.plan.always" if options.read_always else "fc.plan.when"), t("fc.plan.first"), t("fc.plan.robots"), t("fc.plan.zdr") if not options.allow_without_zero_data_retention
                      else t("fc.plan.no_zdr"), t("fc.plan.proxy." + ("basic" if options.proxy == "basic" else "approved"), proxy=options.proxy)],
            "cost_line": cost_line(shown)}


class _NothingSpent:
    def spent_today(self) -> float:
        return 0.0


def cost_line(shown: dict[str, Any]) -> str:
    if shown["max_usd"] is None:
        return t("fc.cost.credits", credits=shown["max_credits"], pages=shown["max_pages"], per_page=shown["credits_per_page"])
    return t("fc.cost.usd", credits=shown["max_credits"], pages=shown["max_pages"], per_page=shown["credits_per_page"],
             usd=f"{shown['max_usd']:.4f}")


def open_client(services: FirecrawlServices, options: Options, *, approved_credits: float, audit_id: str,
                should_stop: Callable[[], bool] | None = None, clock=None) -> engine.FirecrawlClient:
    ledger, cache = services.stores()
    return engine.FirecrawlClient(services.key(), ledger, cache, approved_credits=approved_credits, max_pages=options.max_pages,
                                  proxy=options.proxy, owner_approved_bypass=options.owner_approved_bypass,
                                allow_without_zero_data_retention=options.allow_without_zero_data_retention,
                                  audit_id=audit_id, transport=services.transport, should_stop=should_stop, clock=clock)


STRONGER = tuple(name for name in settings.PROXIES if name != settings.DEFAULT_PROXY)


def confirm_text(shown: dict[str, Any]) -> str:
    """The amount on a button: credits, and dollars when a price per credit is configured."""
    if shown["max_usd"] is None:
        return t("fc.amount.credits", credits=shown["max_credits"])
    return t("fc.amount.usd", credits=shown["max_credits"], usd=f"{shown['max_usd']:.2f}" if shown["max_usd"] >= 0.1 else f"{shown['max_usd']:.4f}")


def offer_kind(section: dict[str, Any] | None, state: dict[str, Any], crawl_blocked: bool) -> str | None:
    """What a finished, blocked audit may still do with Firecrawl: nothing (None), switch it on, accept storage after
    zero data retention was refused, or retry with a stronger proxy after basic was turned away as well."""
    status = state.get("state", "none")
    if status in ("none", "") and not section:
        return "not_requested" if crawl_blocked else None
    if status == "needs_decision" and (section or {}).get("needs_decision") == "zero_data_retention":
        return "zero_data_retention"
    if status == "done" and section and reader.also_blocked(section):
        return "also_blocked" if section.get("proxy") == settings.DEFAULT_PROXY else "stronger_blocked"
    return None


def continuation_options(kind: str, state: dict[str, Any], proxy: str, owner_approved: bool) -> dict[str, Any]:
    """The options a continuation would run with. The person's ticks arrive as arguments; nothing is assumed for them."""
    kept = state.get("options") or {}
    waived = bool(kept.get("allow_without_zero_data_retention")) or kind == "zero_data_retention"
    return {"read_always": True, "render_fallback": False, "max_pages": int(kept.get("max_pages") or settings.DEFAULT_MAX_PAGES),
            "proxy": proxy, "owner_approved_bypass": bool(owner_approved), "allow_without_zero_data_retention": waived}


def offer(services: FirecrawlServices, section: dict[str, Any] | None, state: dict[str, Any], audit_page_cap: int,
          crawl_blocked: bool, offline: bool) -> dict[str, Any] | None:
    """The Firecrawl choice on a blocked audit's result card. Sends nothing and opens no spending record unless a key is set."""
    kind = offer_kind(section, state, crawl_blocked)
    if kind is None:
        return None
    if kind == "stronger_blocked":
        return {"kind": kind, "title": t("fc.offer.stronger_blocked.title", proxy=section.get("proxy")), "lines": [t("fc.offer.stronger_blocked.body")],
                "available": False, "choices": [], "consent": {"storage": False, "owner": False}, "blocked": None, "offline": offline}
    configured = services.key() is not None
    proxies = STRONGER if kind == "also_blocked" else (state.get("options") or {}).get("proxy") and [state["options"]["proxy"]] or [settings.DEFAULT_PROXY]
    choices, blocked, storage = [], None, False
    for proxy in proxies:
        # Priced as it would run once the ticks are made; the request itself is refused without them.
        wanted = continuation_options(kind, state, proxy, proxy != settings.DEFAULT_PROXY)
        shown = plan(services, wanted, audit_page_cap, False)
        storage = wanted["allow_without_zero_data_retention"]
        blocked = blocked or shown["blocked"]
        choices.append({"proxy": proxy, "proxy_label": t("fc.proxy." + proxy), "max_credits": shown["max_credits"], "max_usd": shown["max_usd"],
                        "max_pages": shown["max_pages"], "credits_per_page": shown["credits_per_page"], "cost_line": cost_line(shown),
                        "label": t("fc.offer." + kind + ".confirm", amount=confirm_text(shown), proxy=proxy)})
    lines = {"not_requested": [t("fc.offer.not_requested.body"), t("fc.plan.robots"), t("fc.plan.zdr"), t("fc.plan.proxy.basic")],
             "zero_data_retention": [t("fc.zdr.unavailable"), t("fc.offer.zdr.body")],
             "also_blocked": [t("fc.offer.also_blocked.body"), t("fc.offer.also_blocked.never_auto")]}[kind]
    return {"kind": kind, "title": t("fc.offer." + kind + ".title"), "lines": lines, "available": configured,
            "unavailable_reason": None if configured else t("fc.unavailable"), "choices": choices, "blocked": blocked if configured else None,
            "consent": {"storage": storage, "storage_label": t("fc.zdr.accept"), "storage_warning": t("fc.zdr.warning"),
                        "owner": kind == "also_blocked", "owner_label": t("fc.owner"), "owner_help": t("fc.offer.owner.help")},
            "offline": offline, "offline_note": t("fc.offer.offline") if offline else t("fc.offer.repeats"),
            "waiting": t("fc.offer.waiting")}


def view(section: dict[str, Any] | None, state: dict[str, Any]) -> dict[str, Any] | None:
    """The Firecrawl part of the results page: the report's section in sentences, and any decision that is waiting."""
    if not section:
        return None
    waiting = section.get("needs_decision") == "zero_data_retention" and state.get("state") == "needs_decision"
    options = options_from({**(state.get("options") or {}), "allow_without_zero_data_retention": True})
    lines = panel.summary_lines(section)
    said = [wording.line(text) for text in lines]
    return {"used": bool(section.get("used")), "purpose": section.get("purpose"), "notice": section.get("notice"),
            # `lines` and `notice` are the report's own English; a person reads `lines_shown` and `notice_shown`.
            "notice_shown": wording.line(section.get("notice"))[0], "lines_shown": [text for text, _ in said],
            "untranslated": sum(1 for _, ok in said if not ok),
            "lines": lines, "proxy": section.get("proxy"), "main_reader": section.get("purpose") == reader.MAIN_PURPOSE,
            "owner_approved_bypass": bool(section.get("owner_approved_bypass")),
            "zero_data_retention": section.get("zero_data_retention"), "pages_read": section.get("pages_read"),
            "checks": sorted(section.get("checks_from_firecrawl") or [], key=check_id_key), "credits": section.get("credits"), "usd": section.get("usd"),
            "also_blocked": reader.also_blocked(section), "reason": section.get("reason"),
            "attempts": state.get("attempts") or [], "spent_line": spent_line(state.get("attempts") or []),
            "decision": None if not waiting else {
                "kind": "zero_data_retention", "message": t("fc.zdr.unavailable"), "warning": t("fc.zdr.warning"),
                "approve_credits": options.estimate(state.get("audit_page_cap") or settings.DEFAULT_MAX_PAGES)["max_credits"]}}


def spent_line(attempts: list[dict[str, Any]]) -> str | None:
    """Credits used by every Firecrawl attempt on this audit together, when there was more than one."""
    if len(attempts) < 2:
        return None
    return t("fc.attempts", count=len(attempts), credits=f"{sum(float(a.get('credits') or 0) for a in attempts):g}")
