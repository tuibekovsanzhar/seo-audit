"""The Firecrawl plan shown before anything is spent, and the report section written afterwards."""

from __future__ import annotations

from typing import Any

from ..dataforseo.ledger import Ledger, LedgerCorrupt
from . import settings
from .settings import Options

# The keys of the report's `firecrawl` section (docs/REPORT-SCHEMA.md).
SECTION_KEYS = ("source", "enabled", "used", "purpose", "reason", "notice", "options", "proxy", "owner_approved_bypass",
                "zero_data_retention", "page_cap", "crawl_blocked", "robots", "pages", "rendered", "pages_read",
                "skipped_by_robots", "pages_blocked_for_firecrawl_too", "checks_from_firecrawl", "needs_decision",
                "stopped_because", "errors", "calls", "requests_sent", "credits", "usd", "coverage", "sitemap", "unsupported_resources")


ENHANCED_NEEDS_APPROVAL = ("The enhanced proxy tries to get past bot protection. It is used only when you tick that the site owner "
                           "has approved bypassing bot protection for this audit; it is never switched on automatically.")
STRONGER_ALSO_BLOCKED = ("This was with the site owner's approval to bypass bot protection. Ask the site owner to allow the "
                         "audit's user agent instead.")


def section(info: dict[str, Any]) -> dict[str, Any]:
    """The part of `reader.apply`'s result that goes into the report: no page objects, nothing outside the documented keys."""
    return {key: info[key] for key in SECTION_KEYS if key in info}


def plan(options: Options, audit_page_cap: int, ledger: Ledger, key_configured: bool, daily: float | None = None) -> dict[str, Any]:
    """What using Firecrawl for one audit could cost at most, and what is left of today's budget. Sends nothing."""
    estimate = options.estimate(audit_page_cap)
    daily = settings.daily_credits() if daily is None else daily
    try:
        spent = ledger.spent_today()
    except (LedgerCorrupt, RuntimeError, OSError):
        spent = None
    remaining = None if spent is None else round(max(0.0, daily - spent), 6)
    blocked = None
    if not key_configured:
        blocked = {"code": "firecrawl_key_not_configured", "message": "The Firecrawl key is not set on this computer, so Firecrawl cannot be used."}
    elif options.problem():
        blocked = {"code": "firecrawl_options", "message": options.problem()}
    elif spent is None:
        blocked = {"code": "firecrawl_ledger_unreadable", "message": "The Firecrawl spending record cannot be read, so its requests are stopped."}
    elif estimate["max_credits"] > remaining:
        blocked = {"code": "firecrawl_daily_limit_reached", "message": (
            f"Firecrawl daily limit reached: this audit could use up to {estimate['max_credits']} credits and only {remaining:g} of "
            f"today's {daily:g} are left. It resets at midnight UTC. Lower the Firecrawl page cap or run without Firecrawl.")}
    return {**estimate, "options": options.as_dict(), "key_configured": key_configured, "daily_credits": daily,
            "spent_today_credits": spent, "remaining_today_credits": remaining, "blocked": blocked,
            # The basic proxy is the page reader of a normal run: recorded and guarded, not asked about.
            "needs_confirmation": blocked is None and not (options.read_always and options.proxy == settings.DEFAULT_PROXY),
            "when_used": [w for w, on in (("to read the pages of every audit", options.read_blocked and options.read_always),
                                          ("only if Maya's own crawler is blocked", options.read_blocked and not options.read_always),
                                          ("only if the local browser cannot start", options.render_fallback)) if on]}


def plan_lines(shown: dict[str, Any]) -> list[str]:
    usd = "unknown (no dollar price per credit is configured)" if shown["max_usd"] is None else f"${shown['max_usd']:.4f}"
    options = shown["options"]
    lines = ["Firecrawl plan (a third-party reader; estimates are upper bounds; nothing has been sent)",
             f"  Used:                 {'; '.join(shown['when_used']) or 'never'}",
             f"  Pages at most:        {shown['max_pages']} (+1 request for robots.txt if Maya could not read it)",
             f"  Proxy:                {options['proxy']}" + (" (the site owner approved bypassing bot protection)" if options["owner_approved_bypass"] else ""),
             f"  Zero data retention:  {'NOT requested (waived for this audit: page content may be stored by Firecrawl)' if options['allow_without_zero_data_retention'] else 'requested on every page'}",
             f"  Credits at most:      {shown['max_credits']} ({shown['credits_per_page']} per page)",
             f"  In US dollars:        {usd}"]
    if shown["spent_today_credits"] is not None:
        lines.append(f"  Today (UTC):          {shown['spent_today_credits']:g} credits spent or reserved of {shown['daily_credits']:g}")
    if shown["blocked"]:
        lines.append(f"  Cannot be used:       {shown['blocked']['message']}")
    return lines


def _money(info: dict[str, Any]) -> str:
    credits, usd = info["credits"], info["usd"]
    dollars = "" if usd["used_or_reserved"] is None else f" (${usd['used_or_reserved']:.4f})"
    return (f"{credits['used_or_reserved']:g} credit(s) spent or reserved{dollars}, of at most {credits['estimated_max']}; "
            f"{info['requests_sent']} request(s) sent")


from ..findings import check_id_key


def summary_lines(info: dict[str, Any]) -> list[str]:
    """The section as plain sentences, used by the text and Markdown reports and the web page."""
    zdr = info["zero_data_retention"]["status"]
    lines = []
    if info.get("used"):
        lines.append(f"Used as: {info['purpose']}. Proxy: {info['proxy']}"
                     + (" (the site owner approved bypassing bot protection)." if info["owner_approved_bypass"] else "."))
        if "pages_read" in info:
            lines.append(f"Pages read through Firecrawl: {info['pages_read']} (cap {info['page_cap']}); {info.get('skipped_by_robots', 0)} "
                         "left out because robots.txt disallows them.")
        found = info.get("sitemap")
        if found:
            read = [doc for doc in found.get("documents") or [] if doc.get("outcome") in ("read", "index")]
            lines.append(f"Sitemap through Firecrawl (Maya's own crawler could not read one): {found.get('addresses_found', 0)} address(es) found in "
                         f"{len(read)} of {len(found.get('documents') or [])} document(s) asked for." + (f" {found['note']}." if found.get("note") else ""))
        cover = info.get("coverage") or {}
        if not found and cover.get("sitemap_addresses_known"):
            # The reading queue was seeded with what Maya's own crawl read from the sitemap: said, so that "0 found by
            # the reader" (`sitemap_addresses_found`) is not read as "the sitemap was ignored".
            lines.append(f"Sitemap: {cover['sitemap_addresses_known']} address(es) known from Maya's own crawl; the reader was not asked "
                         "for the sitemap.")
        if cover.get("causes"):
            lines.append("Asked for and not read: " + ", ".join(f"{count} {name.replace('_', ' ')}" for name, count in sorted(cover["causes"].items())) + ".")
        lines.append(f"Checks that rest on Firecrawl's reading: {', '.join(sorted(info['checks_from_firecrawl'], key=check_id_key))}.")
        if info.get("notice"):
            lines.append(info["notice"])
    else:
        from .reader import also_blocked

        reason = info.get("reason") or "its conditions did not arise"
        if also_blocked(info):
            lines.append(reason[:1].upper() + reason[1:] + ".")
            lines.append(ENHANCED_NEEDS_APPROVAL if info.get("proxy") == settings.DEFAULT_PROXY else STRONGER_ALSO_BLOCKED)
        else:
            lines.append(f"Not used: {reason}.")
    for error in info.get("errors") or []:
        lines.append(f"{error['meaning']} — {error['url']} (HTTP {error['http_status']}).")
        lines.append("Provider error: " + error["message"])
        lines.append("Engines tried: " + (", ".join(error["engines_tried"]) or "not supplied by Firecrawl") + ".")
        lines.append(error["note"])
    robots = info.get("robots") or {}
    if robots.get("reason"):
        lines.append(f"Robots policy ({robots.get('source', 'unknown')}): {robots['reason']}.")
    lines.append(f"Zero data retention: {zdr}.")
    if info.get("needs_decision") == "zero_data_retention":
        lines.append("To proceed without it, the audit must be run again with an explicit confirmation that page content may be stored by Firecrawl.")
    if info.get('unsupported_resources'):
        skipped = info['unsupported_resources']
        lines.append(f"Unsupported non-page resources: {len(skipped)}; excluded from unreadable-page failure streaks.")
        lines.extend(f"Skipped resource: {row['url']} ({row['kind']}; {row['outcome']})." for row in skipped[:40])
    if info.get("stopped_because"):
        from ..report import provider_reason  # H19: the provider's own text stays under "Provider error" and in the JSON
        lines.append(f"Stopped early: {provider_reason(info['stopped_because'])}")
    lines.append(f"Cost: {_money(info)}." + (f" {info['usd']['note'].capitalize()}." if info["usd"].get("note") else ""))
    return lines


def render_text(info: dict[str, Any]) -> str:
    return "\n".join(["=" * 78, "Firecrawl (a third-party page reader; Maya's own crawler remains the access test)", "=" * 78, "",
                      *summary_lines(info), ""])


def render_markdown(info: dict[str, Any]) -> str:
    return "\n".join(["", "## Firecrawl (third-party page reader)", "",
                      "Maya's own crawler ran first and its access results stand. What follows describes only what was read "
                      "through Firecrawl.", "", *(f"- {line}" for line in summary_lines(info)), ""])
