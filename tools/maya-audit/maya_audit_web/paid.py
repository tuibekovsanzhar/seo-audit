"""Paid data in the web app: what a plan may cost, the approval it needs, and why a request was refused.

The cost guard itself is `maya_audit.dataforseo`: price estimators, the ledger with its daily budget,
the cache, and the client that will not send without them. The web app and the command line use the
same ledger file under the same lock, so a dollar reserved by one is a dollar the other cannot spend.
This module decides only what the person is shown and what they must approve:

- a plan whose paid total is above the per-audit confirmation limit ($2 unless configured) needs an explicit
  confirmation of its exact maximum; below it the plan shows its cost and runs without asking, every call recorded in
  the ledger;
- one audit never spends more than the per-audit limit ($5 unless configured), whatever was confirmed: a plan above
  it says which checks would be left out, and the ledger refuses the request that would pass it;
- the plan shows what each DataForSEO API would cost, that the SERP API is not called, and the three limits;
- the daily allowance is the engine's ($20 unless configured), counted per UTC day as the ledger counts it;
- "today's allowance is used up", "the DataForSEO account has no credit", "the balance is unknown" and
  "credentials are not set" are four different things and are worded differently;
- the account's balance is asked for (a free request) when a plan with paid data is built, at most once in ten minutes,
  so a plan can warn before anything is spent elsewhere for a report without that data (DECISIONS 180).

Nothing here raises a limit, buys credit, or sends a paid request on its own initiative.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import httpx

from maya_audit import dataforseo as dfs
from maya_audit.dataforseo import insights, panel, pricing
from maya_audit.dataforseo.cache import Cache
from maya_audit.dataforseo.credentials import Credentials
from maya_audit.dataforseo.ledger import Ledger, LedgerCorrupt

from . import wording
from .strings import current_language, t, usd

# How long a fetched balance (or a failed attempt to fetch it) is reused before a plan with paid data asks again.
BALANCE_REUSE_S = 600
# Whether building a plan with paid data asks for the balance by itself. Tests of other things switch it off
# (tests/conftest.py), so their made-up provider is sent only what they are about.
AUTOMATIC_BALANCE = True
# The time, for the ten-minute reuse. Tests put a made-up clock here.
CLOCK: Callable[[], float] = time.time


def daily_cap() -> float:
    """What may be spent in a UTC day: the engine's own limit ($20 unless MAYA_AUDIT_DATAFORSEO_DAILY_USD says otherwise)."""
    return pricing.daily_budget()


def limits() -> dict[str, float]:
    """The three limits a plan card states: the total above which it asks, the most one audit may spend, and the day's."""
    return {"confirm_usd": pricing.approval_threshold(), "audit_cap_usd": pricing.audit_cap(), "daily_usd": daily_cap()}


# DataForSEO's own status codes for "the account cannot pay" and "the account may not use this API".
_NO_CREDIT_CODES = {"40200", "40210"}
_NO_SUBSCRIPTION_CODES = {"40204"}
# DataForSEO's "invalid field" and "not found" answers: the panel is not offered for this market or these settings.
_UNSUPPORTED_CODES = {"40501", "40503", "40400", "40402"}
_REFUSED = re.compile(r"DataForSEO refused \S+: (\d{5})")
_BALANCE_WAS = re.compile(r"the DataForSEO balance was \$(\d+(?:\.\d+)?) when the audit started")
_CAP_REACHED = re.compile(r"this audit reached its \$(\d+(?:\.\d+)?) DataForSEO limit")
PURPOSE = {f"DFS-{n}": f"paid.purpose.DFS-{min(n, 9) if n < 12 else 12}" for n in range(1, 13)}


@dataclass
class PaidServices:
    """Where paid calls go and how they are recorded. Tests and demo mode pass their own."""
    credentials: Callable[[], Credentials | None]
    stores: Callable[[], tuple[Ledger, Cache | None]]
    transport: httpx.BaseTransport | None = None
    # The calls one audit of a URL makes. Demo mode asks about a reserved name instead of the demo site.
    plan: Callable[[str], list[panel.PlannedCall]] = panel.audit_plan
    # The search data panels for a URL and the plan's options (country, brand, key pages, local business).
    search_plan: Callable[[str, dict[str, Any]], list[panel.PlannedCall]] = lambda url, options: insights.audit_plan(
        url, country=options.get("country"), brand=options.get("brand"), key_pages=options.get("key_pages") or (),
        local_business=bool(options.get("local_business")), home=options.get("home"))

    @classmethod
    def real(cls) -> "PaidServices":
        return cls(dfs.load_credentials, panel.open_stores)


def budget(services: PaidServices) -> dict[str, Any]:
    """Today's local allowance, from the ledger. Reads a file; asks nobody."""
    now = datetime.now(timezone.utc)
    reset = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    out: dict[str, Any] = {"daily_cap_usd": daily_cap(), "day": now.date().isoformat(), "day_is": "UTC calendar day",
                           "resets_at": reset.isoformat(timespec="seconds"), "spent_today_usd": None,
                           "remaining_today_usd": None, "ledger_readable": True,
                           "credentials_configured": services.credentials() is not None}
    try:
        spent = services.stores()[0].spent_today()
    except (LedgerCorrupt, RuntimeError, OSError):
        out["ledger_readable"] = False
        return out
    out.update(spent_today_usd=spent, remaining_today_usd=round(max(0.0, daily_cap() - spent), 6))
    return out


def calls(services: PaidServices, url: str, options: dict[str, Any] | None) -> list[panel.PlannedCall]:
    """Every DataForSEO call the plan's options ask for: backlinks, the search data panels, or both."""
    options = options if options is not None else {"backlinks": True}
    planned = list(services.plan(url)) if options.get("backlinks") else []
    return planned + (list(services.search_plan(url, options)) if options.get("search_data") else [])


def fingerprint(url: str, mode: str, key_pages: list[str], backlinks: bool, rows: list[dict[str, Any]], total: float,
                firecrawl: dict[str, Any] | None = None, extras: dict[str, Any] | None = None,
                market: list[Any] | None = None) -> str:
    """What a confirmation is tied to: the target, the settings, and every priced request with its price.

    `firecrawl` is that part of the plan when it was switched on: its options and its maximum in credits.
    `market` is [location code, language, brand, whether the country was recognised, whether the United States was
    accepted instead]: a changed market is a changed plan.
    """
    priced = [[row["endpoint"], row["target"], row["state"], round(row["estimate_usd"], 6)] for row in rows] if backlinks else []
    parts: list[Any] = [url, mode, sorted(key_pages), bool(backlinks), priced, round(total, 6) if backlinks else 0.0]
    if firecrawl and firecrawl.get("requested"):
        # Requests at once (DECISIONS 294) change neither what is read nor what it costs: left out, so a plan confirmed
        # before the setting existed keeps its fingerprint.
        shown = {k: v for k, v in (firecrawl["options"] or {}).items() if k != "concurrency"}
        parts.append(["firecrawl", shown, firecrawl["max_credits"], firecrawl["max_usd"]])
    if extras and any(extras.values()):
        parts.append(["extras", {key: value for key, value in sorted(extras.items()) if value}])
    if market is not None:
        parts.append(["market", *market])
    basis = json.dumps(parts, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def price(url: str, services: PaidServices, *, requested: bool, options: dict[str, Any] | None = None) -> dict[str, Any]:
    """What the paid DataForSEO calls of this plan would cost for `url` right now. Sends nothing."""
    today = budget(services)
    held = limits()
    out: dict[str, Any] = {"requested": requested, "available": today["credentials_configured"], "calls": [],
                           "total_usd": 0.0, "needs_confirmation": False, "blocked": None, "budget": today,
                           # What each DataForSEO API would cost, and the limits, shown on the plan before Start.
                           "by_service": [], "serp_api_calls": 0, "limits": held, "over_audit_cap": None}
    if not out["available"]:
        out["blocked"] = {"code": "credentials_not_configured", "message": t("paid.refused.no_credentials")}
        return out
    if not today["ledger_readable"]:
        out["blocked"] = {"code": "ledger_unreadable", "message": t("paid.refused.ledger")}
        return out
    _ledger, cache = services.stores()
    rows, total = panel.preview_rows(calls(services, url, options), cache)
    moment = time.time()
    for row in rows:
        row["purpose"] = t(PURPOSE.get(row["check_id"], "paid.purpose.other"))
        row["cache_age_s"] = round(max(0.0, moment - row["cached_at"])) if row.get("cached_at") else None
        row.pop("cached_at", None)
    out.update(calls=rows, total_usd=total, by_service=panel.by_service(rows), serp_api_calls=panel.serp_api_calls(rows))
    left_out = panel.left_out_by_cap(rows, held["audit_cap_usd"])
    if left_out:
        # A warning, not a refusal: requests go in the order shown until the limit, and the plan says what is left out.
        out["over_audit_cap"] = {"cap_usd": held["audit_cap_usd"], "total_usd": total, "left_out": left_out, "message": t(
            "paid.over_cap", total=_money(total), cap=_money(held["audit_cap_usd"]), left_out=", ".join(left_out))}
    if any(row["state"] == "refused" for row in rows):
        out["blocked"] = {"code": "no_price", "message": t("paid.refused.no_price")}
    elif total > today["remaining_today_usd"]:
        out["blocked"] = {"code": "daily_limit_reached", "message": t(
            "paid.refused.daily_allowance_plan", total=usd(total), remaining=usd(today["remaining_today_usd"]),
            cap=usd(daily_cap()))}
    else:
        # A plan within the per-audit threshold runs without asking; above it the exact total is confirmed first.
        out["needs_confirmation"] = requested and total > held["confirm_usd"]
    return out


def open_client(services: PaidServices, *, approved_usd: float, audit_id: str,
                should_stop: Callable[[], bool] | None = None, deadline_mono: float | None = None) -> dfs.DataForSEOClient:
    ledger, cache = services.stores()
    return dfs.DataForSEOClient(services.credentials(), ledger, cache, daily_budget=daily_cap(), audit_cap=pricing.audit_cap(),
                                approved_usd=approved_usd, approved_always_ask=True, audit_id=audit_id,
                                transport=services.transport, should_stop=should_stop, deadline_mono=deadline_mono)


def _stamp() -> str:
    return datetime.fromtimestamp(CLOCK(), timezone.utc).isoformat(timespec="seconds")


def refresh_balance(services: PaidServices) -> dict[str, Any]:
    """Ask DataForSEO's free account endpoint for the balance: because a person pressed the button, or because a plan
    with paid data is being built (`balance_for_plan`). One free request through the engine's client; never a paid one."""
    if services.credentials() is None:
        return {"known": False, "code": "credentials_not_configured", "message": t("paid.refused.no_credentials")}
    client = open_client(services, approved_usd=0.0, audit_id="balance")
    try:
        balance = panel.account_balance(client)
    except RuntimeError as exc:
        creds = services.credentials()
        detail = creds.redact(str(exc)) if creds else str(exc)
        return {"known": False, "code": "balance_unavailable", "message": t("paid.balance.failed", detail=detail[:200]), "checked_at": _stamp()}
    finally:
        client.close()
    if balance is None:
        return {"known": False, "code": "balance_unavailable", "message": t("paid.balance.unknown"), "checked_at": _stamp()}
    return {"known": True, "balance_usd": balance, "checked_at": _stamp()}


def _age_s(record: dict[str, Any] | None) -> float | None:
    try:
        return CLOCK() - datetime.fromisoformat(record["checked_at"]).timestamp()
    except (KeyError, TypeError, ValueError):
        return None


def latest_balance(known: dict[str, Any] | None, failed: dict[str, Any] | None) -> dict[str, Any] | None:
    """The more recent of the last balance that was read and the last attempt that got no answer."""
    ages = [(age, record) for record in (known, failed) if record and (age := _age_s(record)) is not None]
    return min(ages, key=lambda pair: pair[0])[1] if ages else None


def balance_for_plan(services: PaidServices, known: dict[str, Any] | None, failed: dict[str, Any] | None, *,
                     paid_wanted: bool, demo: bool) -> dict[str, Any] | None:
    """The balance to fetch now for a plan being built, or None when nothing is to be fetched.

    Fetched only when the plan asks for paid data, this is not demo mode, credentials are set, and the last answer (or
    the last failed attempt) is older than ten minutes. A failure is an answer of its own ("unknown"): it never stops
    the plan."""
    if not (AUTOMATIC_BALANCE and paid_wanted and not demo and services.credentials() is not None):
        return None
    last = latest_balance(known, failed)
    if last is not None and 0 <= (_age_s(last) or 0) < BALANCE_REUSE_S:
        return None
    try:
        return refresh_balance(services)
    except Exception as exc:  # noqa: BLE001  whatever went wrong, the plan is still made: the balance is "unknown"
        return {"known": False, "code": "balance_unavailable", "message": t("paid.balance.failed", detail=type(exc).__name__), "checked_at": _stamp()}


def _money(amount: float) -> str:
    """A dollar amount for a sentence, with the decimal comma Turkish uses ("0,00 $")."""
    return usd(amount).replace(".", ",") if current_language() == "tr" else usd(amount)


def balance_warning(cost: dict[str, Any], last: dict[str, Any] | None, *, demo: bool = False) -> dict[str, Any] | None:
    """What the plan card says above Start when the account may not be able to pay for this plan, and the choices it
    offers. None when the balance covers the plan, when nothing here costs anything, or when it was never asked for."""
    total = cost.get("total_usd") or 0.0
    if demo or not cost.get("requested") or not cost.get("available") or cost.get("blocked") or total <= 0 or last is None:
        return None
    without, anyway = {"id": "without_search_data", "label": t("plan.balance.choice.without")}, {"id": "run_anyway", "label": t("plan.balance.choice.anyway")}
    if not last.get("known"):
        return {"level": "unknown", "balance_usd": None, "total_usd": total, "choices": [without, anyway],
                "message": t("plan.balance.unknown", total=_money(total))}
    balance = float(last.get("balance_usd") or 0.0)
    if balance <= 0:
        return {"level": "zero", "balance_usd": balance, "total_usd": total, "choices": [without], "message": t("plan.balance.zero")}
    if balance < total:
        return {"level": "low", "balance_usd": balance, "total_usd": total, "choices": [without, anyway],
                "message": t("plan.balance.low", balance=_money(balance), total=_money(total))}
    return None


def refusal(summary: str, spent_today: float | None = None) -> dict[str, str]:
    """Turn one "not assessed" reason from the backlink panel into a stable code and a plain sentence."""
    number = _REFUSED.search(summary)
    if "daily budget reached" in summary:
        code, message = "daily_limit_reached", t("paid.refused.daily_allowance", cap=usd(daily_cap()),
                                                 spent=usd(spent_today) if spent_today is not None else "?")
    elif (number and number.group(1) in _NO_CREDIT_CODES) or "has no credit for this request" in summary:
        code, message = "provider_credits_insufficient", t("paid.refused.account_credits")
    elif panel.RAN_OUT in summary:
        code, message = "not_requested_no_credit", t("paid.refused.not_requested_no_credit")
    elif (reached := _CAP_REACHED.search(summary)):
        code, message = "audit_cap_reached", t("paid.refused.audit_cap", cap=_money(float(reached.group(1))))
    elif summary.startswith("not requested: the DataForSEO balance was"):
        amount = _BALANCE_WAS.search(summary)
        code, message = "not_requested_balance", (t("paid.refused.balance_at_start", balance=_money(float(amount.group(1)))) if amount
                                                  else t("paid.refused.balance_unknown_at_start"))
    elif number and number.group(1) in _NO_SUBSCRIPTION_CODES:
        code, message = "provider_subscription_missing", t("paid.refused.subscription")
    elif number and number.group(1) in _UNSUPPORTED_CODES:
        code, message = "unsupported_request", t("paid.refused.unsupported", detail=summary.removeprefix("not assessed: ")[:200])
    elif "Nothing was sent and nothing was charged" in summary:
        code, message = "provider_unreachable", t("paid.refused.unreachable")
    elif "no credentials" in summary:
        code, message = "credentials_not_configured", t("paid.refused.no_credentials")
    elif "above the approved" in summary or "always needs approval" in summary:
        code, message = "confirmation_required", t("paid.refused.approval")
    elif "may have been billed" in summary or "no usable response" in summary or "delivery uncertain" in summary:
        code, message = "possibly_billed", t("paid.refused.possibly_billed")
    elif "stopped on request" in summary or "deadline reached" in summary:
        code, message = "stopped", t("paid.refused.stopped")
    else:
        code, message = "provider_error", t("paid.refused.other", detail=summary.removeprefix("not assessed: ")[:300])
    return {"code": code, "message": message}


_WORD_CELLS = {"Relevance": ("branded", "relevant", "related_organization"), "Claimed by the owner": ("yes", "no")}


def _named(text: Any) -> Any:
    intent = {'Keyword intent evidence (listed sample only)': 'title', 'Supported dimensions': 'dimensions',
              'Reason': 'reason', 'Evidence references': 'references'}
    if text == 'related_organization':
        return t('paid.keyword.related_organization')
    if text in intent:
        return t('paid.intent.' + intent[text])
    if isinstance(text, str) and all(w.strip() in ('brand_identity', 'related_organization', 'service_relevance', 'local_relevance', 'editorial_relevance', 'unrelated_intent', 'uncertain') for w in text.split(',')):
        return ', '.join(t('paid.intent.' + w.strip()) for w in text.split(','))
    return (t("paid.keyword.related_organization") if text == "related_organization" else
            wording.label(text)[0] if isinstance(text, str) else text)


def shown_data(data: Any) -> dict[str, Any] | None:
    """How a data panel's own words are shown: `labels` maps each figure's name, column name, table title and each cell
    that is this tool's own word (the relevance group, yes or no) to the reader's language; `notes` holds the note under
    each side table. The tables themselves are not copied: the provider's cells are shown as they came."""
    if not isinstance(data, dict):
        return None
    labels: dict[str, str] = {}
    notes: dict[str, str] = {}

    def name(text: Any) -> None:
        if isinstance(text, str) and text not in labels:
            labels[text] = _named(text)

    for label, value in (data.get("metrics") or {}).items() if isinstance(data.get("metrics"), dict) else ():
        name(label)
        if label in _WORD_CELLS and value in _WORD_CELLS[label]:
            name(value)
    for key in ("table", "unrelated", "ambiguous", "intent_dimensions", "editorial_opportunities"):
        table = data.get(key)
        if not isinstance(table, dict) or "columns" not in table:
            continue
        for column in table["columns"]:
            name(column)
            for word in _WORD_CELLS.get(column, ()):
                name(word)
        name(table.get("title"))
        if key == 'intent_dimensions':
            notes[key] = t('paid.intent.note')
            for row in table['rows']:
                name(row[1])
        elif table.get("note"):
            notes[key] = wording.line(table["note"])[0]
    return {"labels": labels, "notes": notes, "word_columns": sorted(set(_WORD_CELLS) | ({"Supported dimensions"} if data.get("intent_dimensions") else set()))}


def describe(dfs_panel: dict[str, Any], services: PaidServices) -> dict[str, Any]:
    """The backlink section for the results page: figures, cost, and a worded reason for every refusal.

    A panel that could not run is "unavailable", with why. It is never shown as zero backlinks.
    """
    from maya_audit.dataforseo.insights import qualify_section
    dfs_panel = qualify_section(dfs_panel)
    spent = budget(services)["spent_today_usd"]
    checks = []
    billing = {call["endpoint"]: call.get("billing_status") for call in dfs_panel.get("calls") or []}
    for check in dfs_panel["checks"]:
        row = {"check_id": check["check_id"], "title": check["title"], "target": check.get("target"), "status": check["status"], "endpoint": check.get("endpoint"),
               "summary": check["summary"], "refusal": None, "data": (check.get("evidence") or {}).get("data"),
               "from_cache": (check.get("evidence") or {}).get("from_cache"),
               "data_from": (check.get("evidence") or {}).get("data_from")}
        if check['check_id'] in ('DFS-4', 'DFS-5'):
            from maya_audit.dataforseo.insights import qualified_opportunity_data
            row['data'] = qualified_opportunity_data(row['data'])
        if check["status"] == "not_assessed":
            row["refusal"] = refusal(check["summary"], spent)
            # The ledger's own verdict outranks the wording: a call it holds as possibly billed is shown as that.
            if billing.get(check.get("endpoint")) == "possibly_billed":
                row["refusal"] = {"code": "possibly_billed", "message": t("paid.refused.possibly_billed")}
            row["summary"] = row["refusal"]["message"]
        # What a person reads: the title, the sentence, and the figures' names and column names in the reader's
        # language. The provider's own cells (keywords, domains, addresses, numbers) are shown as they came.
        title, title_ok = wording.label(check["title"], check_id=check["check_id"])
        said, said_ok = (row["summary"], True) if row["refusal"] else wording.line(check["summary"], check_id=check["check_id"])
        row.update(title_shown=title, summary_shown=said, data_shown=shown_data(row["data"]), untranslated=not (title_ok and said_ok))
        checks.append(row)
    note = dfs_panel.get("note")
    note_shown = wording.line(note)[0] if note else None
    if note and _BALANCE_WAS.search(note):  # the amount written as the plan card writes it in this language
        note_shown = t("paid.refused.balance_at_start", balance=_money(float(_BALANCE_WAS.search(note).group(1))))
    return {"target": dfs_panel["target"], "status": dfs_panel["status"], "panel": dfs_panel.get("panel"),
            "available": dfs_panel["status"] != "not_assessed", "checks": checks,
            # One sentence for the whole panel when requests were left out because of the account's balance.
            "note": note, "note_shown": note_shown, "stopped": dfs_panel.get("stopped"),
            "cost_usd": dfs_panel["cost_usd"], "estimated_usd": dfs_panel["estimated_usd"],
            "requests_sent": dfs_panel["requests_sent"],
            "calls": [{"endpoint": c["endpoint"], "cost_usd": c["cost_usd"], "from_cache": c["from_cache"],
                       "billing_status": c.get("billing_status")} for c in dfs_panel.get("calls") or []],
            "spent_line": t("paid.spent", cost=usd(dfs_panel["cost_usd"]), estimate=usd(dfs_panel["estimated_usd"]))}
