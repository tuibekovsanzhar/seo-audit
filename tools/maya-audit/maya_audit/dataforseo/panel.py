"""What an audit asks DataForSEO for, the cost preview shown before it does, and the report section.

DataForSEO results are their own family ("DFS"), kept apart from the site checks: they come from a
third-party index, not from the crawl, and a failure here never changes a crawl-based check.

The panel today is backlinks and authority: a backlink summary (DFS-1) and the top referring
domains (DFS-2), both asked about the registrable domain of the audited site.
"""

from __future__ import annotations

import ipaddress
import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from ..config import SPAM_SCORE_THRESHOLD
from ..urls import is_loopback_host, registrable_domain
from . import pricing
from .cache import CACHE_NAME, Cache
from .client import DataForSEOClient, DataForSEOError, NoCredentials, NoCredit
from .credentials import LOGIN_VAR, PASSWORD_VAR, Credentials, data_dir
from .ledger import LEDGER_NAME, AuditCapReached, Ledger, LedgerCorrupt

NO_CREDENTIALS = "not assessed: no credentials"
CONFIDENCE = "Estimated (third-party index)"
REFERRING_DOMAINS_LIMIT = 100
# Rows of the referring-domain list shown in the text and Markdown reports; the JSON report keeps all of them.
SHOWN_DOMAINS = 20
# Rows of the "unrelated searches" list shown; the JSON report keeps all of them.
SHOWN_UNRELATED = 10


@dataclass(frozen=True)
class PlannedCall:
    check_id: str
    title: str
    endpoint: str
    payload: Any
    target: str | None
    not_sent: str | None = None  # why this call is left out, when the target cannot be looked up
    context: Any = None  # what the reader of the answer needs beyond the answer itself (the audited domain, say)


def target_domain(url: str) -> str:
    """The registrable domain of the audited site: what DataForSEO is asked about."""
    return registrable_domain(urlsplit(url).hostname or "")


def _is_public_domain(host: str) -> bool:
    if not host or "." not in host or is_loopback_host(host):
        return False
    try:
        ipaddress.ip_address(host)
        return False
    except ValueError:
        return True


def audit_plan(url: str) -> list[PlannedCall]:
    """Every DataForSEO call one audit of `url` makes: two, both about the site's registrable domain."""
    target = target_domain(url)
    not_sent = None if _is_public_domain(target) else (
        f"{target or url!r} is not a public domain name, so a backlink index has nothing to look up. No request was sent.")
    return [
        PlannedCall("DFS-1", "Backlink profile summary", pricing.BACKLINKS_SUMMARY,
                    [{"target": target, "include_subdomains": True}], target, not_sent),
        PlannedCall("DFS-2", f"Top {REFERRING_DOMAINS_LIMIT} referring domains", pricing.BACKLINKS_REFERRING_DOMAINS,
                    [{"target": target, "include_subdomains": True, "limit": REFERRING_DOMAINS_LIMIT,
                      "order_by": ["rank,desc"]}], target, not_sent),
    ]


def open_stores() -> tuple[Ledger, Cache]:
    home = data_dir()
    return Ledger(home / LEDGER_NAME), Cache(home / CACHE_NAME)


def preview_rows(plan: list[PlannedCall], cache: Cache | None, *, refresh: bool = False,
                 prices: dict | None = None) -> tuple[list[dict[str, Any]], float]:
    """The plan as rows, and its total. `state` is paid, cached, not_sent or refused (no price estimator).

    The one place a plan is priced before it runs: the terminal preview and the web app both read these rows.
    """
    rows, total = [], 0.0
    for call in plan:
        estimate = pricing.estimate(call.endpoint, call.payload, prices)
        lifetime = pricing.CACHE_LIFETIME_S.get(call.endpoint, 0)
        held = cache.get(call.endpoint, call.payload, lifetime) if (
            cache and lifetime and not refresh and not call.not_sent) else None
        state = "not_sent" if call.not_sent else "refused" if estimate is None else "cached" if held else "paid"
        if state == "paid":
            total += estimate
        rows.append({"check_id": call.check_id, "title": call.title, "endpoint": call.endpoint, "target": call.target,
                     "state": state, "estimate_usd": estimate if state == "paid" else 0.0,
                     # When the saved answer was fetched (seconds since 1970, UTC), for "cached" rows.
                     "cached_at": held[1] if held else None})
    return rows, round(total, 6)


def by_service(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The plan's rows added up per DataForSEO API, in the order the plan first names each: how many requests would be
    paid for, and their estimate. A service whose answers are all saved already is listed with 0 paid requests."""
    found: dict[str, dict[str, Any]] = {}
    for row in rows:
        entry = found.setdefault(pricing.service_of(row["endpoint"]), {"requests": 0, "usd": 0.0})
        if row["state"] == "paid":
            entry["requests"] += 1
            entry["usd"] += row["estimate_usd"]
    return [{"service": name, "requests": entry["requests"], "usd": round(entry["usd"], 6)} for name, entry in found.items()]


def serp_api_calls(rows: list[dict[str, Any]]) -> int:
    """How many of the plan's calls go to the SERP API. Counted, not assumed: the client refuses every one, so a plan
    never holds any (DECISIONS 193)."""
    return sum(pricing.service_of(row["endpoint"]) == pricing.SERP_SERVICE for row in rows)


def left_out_by_cap(rows: list[dict[str, Any]], cap: float) -> list[str]:
    """The checks a plan above the per-audit limit would not get: requests go in the order shown, and the one that
    would pass the limit is not sent, nor any paid request after it. Empty when the plan fits."""
    running, reached, left = 0.0, False, []
    for row in rows:
        if row["state"] != "paid":
            continue
        reached = reached or round(running + row["estimate_usd"], 6) > round(cap, 6)
        if reached:
            left.append(row["check_id"])
        else:
            running += row["estimate_usd"]
    return left


def _requests(count: int) -> str:
    return f"{count} paid request" + ("" if count == 1 else "s")


_PREVIEW_COST = {"not_sent": "$0.0000 (not sent: not a public domain)", "refused": "REFUSED (no price estimator)",
                 "cached": "$0.0000 (cached)"}


def preview(plan: list[PlannedCall], ledger: Ledger, cache: Cache | None, *, daily_budget: float,
            refresh: bool = False, prices: dict | None = None) -> tuple[list[str], float]:
    """The plan as text, and its total: each call, its upper-bound estimate, today's spend, the limits."""
    lines = ["DataForSEO plan (estimates are upper bounds; nothing has been sent)"]
    rows, total = preview_rows(plan, cache, refresh=refresh, prices=prices)
    for row in rows:
        cost = _PREVIEW_COST.get(row["state"]) or f"${row['estimate_usd']:.4f}"
        lines.append(f"  {row['check_id']:6} {row['endpoint']:42} {row['target'] or '-':24} {cost}")
    try:
        spent = f"${ledger.spent_today():.4f}"
    except LedgerCorrupt as exc:
        spent = f"unknown ({exc})"
    cap = pricing.audit_cap()
    lines += [f"  {entry['service']}: {_requests(entry['requests'])}, ${entry['usd']:.4f}" for entry in by_service(rows)]
    lines += [f"  SERP API calls: {serp_api_calls(rows)}. Maya never calls the SERP API.",
              f"  Total for this audit: ${total:.4f}",
              f"  Spent or reserved today (UTC): {spent} of a ${daily_budget:.2f} daily budget",
              f"  Limits: confirmation above ${pricing.approval_threshold():.2f} per audit; never more than ${cap:.2f} per audit; "
              f"${daily_budget:.2f} per day."]
    left = left_out_by_cap(rows, cap)
    if left:
        lines.append(f"  This plan is estimated at ${total:.2f}, above the ${cap:.2f} limit for one audit. Requests are sent in the "
                     f"order shown until the limit is reached; left out: {', '.join(left)}.")
    return lines, total


def _first_result(data: dict[str, Any]) -> dict[str, Any]:
    result = ((data.get("tasks") or [{}])[0] or {}).get("result") or []
    if not result or not isinstance(result[0], dict):
        raise ValueError("DataForSEO answered without a result for this domain")
    return result[0]


def _summary(data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    row = _first_result(data)
    keys = ("referring_domains", "referring_main_domains", "referring_domains_nofollow", "backlinks", "rank",
            "backlinks_spam_score", "broken_backlinks", "referring_ips", "referring_subnets", "first_seen")
    metrics = {key: row.get(key) for key in keys}
    return (f"{_count(metrics['referring_domains'])} referring domain(s) and {_count(metrics['backlinks'])} "
            f"backlink(s) in DataForSEO's index; DataForSEO rank {_count(metrics['rank'])}."), metrics


def _referring_domains(data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    row = _first_result(data)
    domains = [{"domain": item.get("domain"), "rank": item.get("rank"), "backlinks": item.get("backlinks"),
                "first_seen": item.get("first_seen"), "spam_score": item.get("backlinks_spam_score")}
               for item in row.get("items") or [] if isinstance(item, dict) and item.get("domain")]
    total = row.get("total_count")
    scored = [d for d in domains if isinstance(d["spam_score"], (int, float)) and not isinstance(d["spam_score"], bool)]
    spam = sum(d["spam_score"] >= SPAM_SCORE_THRESHOLD for d in scored)
    return (f"{len(domains)} referring domain(s) listed, highest DataForSEO rank first, of {_count(total)} in the index. "
            f"{spam} of the {len(domains)} listed look like spam (spam score ≥ {SPAM_SCORE_THRESHOLD})."
            ), {"total_count": total, "listed": len(domains), "order": "DataForSEO rank, highest first",
                "spam_score_threshold": SPAM_SCORE_THRESHOLD, "spam_like": spam, "without_spam_score": len(domains) - len(scored),
                "domains": domains}


def _add_spam_line(checks: list[dict[str, Any]]) -> None:
    """Put the share of spam-looking referring domains, counted from DFS-2's list, into DFS-1's summary."""
    by_id = {check["check_id"]: check for check in checks}
    summary, listing = by_id.get("DFS-1"), by_id.get("DFS-2")
    if not summary or summary["status"] != "observed":
        return
    if not listing or listing["status"] != "observed":
        summary["summary"] += " How many referring domains look like spam was not assessed: the referring-domain list was not obtained."
        return
    data = listing["evidence"]["data"]
    total = data["total_count"]
    all_listed = not isinstance(total, int) or data["listed"] >= total
    of = "referring domains" if all_listed else f"highest-ranked referring domains listed ({_count(total)} in the index)"
    line = f"{data['spam_like']} of {data['listed']} {of} look like spam (spam score ≥ {data['spam_score_threshold']})."
    summary["summary"] += " " + line
    summary["evidence"]["data"]["spam_like_referring_domains"] = {
        "count": data["spam_like"], "of": data["listed"], "threshold": data["spam_score_threshold"],
        "covers_every_referring_domain": all_listed, "counted_from": "DFS-2", "summary": line}


# endpoint -> how its response becomes a one-line summary and the data kept in the report
_READERS = {pricing.BACKLINKS_SUMMARY: _summary, pricing.BACKLINKS_REFERRING_DOMAINS: _referring_domains}


NO_CREDIT_CODE = "provider_credits_insufficient"
BALANCE_AT_START_CODE = "balance_at_start"
AUDIT_CAP_CODE = "audit_cap_reached"
RAN_OUT = "the DataForSEO account balance ran out earlier in this audit"


def balance_reason(balance_usd: float | None) -> str:
    """Why an audit did not ask for paid data at all: what the account's balance was when it started."""
    return ("the DataForSEO balance was unknown when the audit started" if balance_usd is None else
            f"the DataForSEO balance was ${balance_usd:.2f} when the audit started")


def cap_reason(cap_usd: float) -> str:
    """Why a request was left out once one audit's own DataForSEO limit was reached."""
    return f"this audit reached its ${cap_usd:.2f} DataForSEO limit"


def _held(client: DataForSEOClient, call: PlannedCall, refresh: bool) -> bool:
    """Whether Maya's own cache holds this answer, so asking for it sends nothing and costs nothing."""
    lifetime = client.cache_lifetimes.get(call.endpoint, 0)
    return bool(client.cache is not None and lifetime and not refresh and client.cache.get(call.endpoint, call.payload, lifetime) is not None)


def run_checks(plan: list[PlannedCall], client: DataForSEOClient, *, refresh: bool = False,
               not_requested: str | None = None) -> dict[str, Any]:
    """Run the plan. Every failure becomes a "not assessed" check with its reason; none is raised.

    When DataForSEO answers that the account has no credit, nothing more is sent in this run: the same refusal would
    come back for every paid request. What Maya's own cache holds is still shown (it costs nothing), and each check
    left out says so. `not_requested` is the same stop decided before the first request (the person chose to run
    without paid data because of the balance): only cached answers are read.

    The audit's own limit (pricing.audit_cap) stops the run the same way: the request that would pass it is not sent,
    nor any after it, whatever total was confirmed. The audit itself goes on."""
    from . import insights

    checks = []
    stopped_after: str | None = None
    cap_usd: float | None = None
    last_asked: str | None = None
    left_out: list[str] = []
    why_left_out = not_requested
    for call in plan:
        check = {"check_id": call.check_id, "title": call.title, "family": "DFS", "endpoint": call.endpoint,
                 "target": call.target, "confidence": CONFIDENCE}
        if call.not_sent:
            check.update(status="not_assessed", summary=f"not assessed: {call.not_sent}")
            checks.append(check)
            continue
        if why_left_out is not None and not _held(client, call, refresh):
            check.update(status="not_assessed", summary=f"not requested: {why_left_out}. No request was sent.")
            left_out.append(call.check_id)
            checks.append(check)
            continue
        try:
            result = client.request(call.endpoint, call.payload, target=call.target, refresh=refresh)
        except AuditCapReached as exc:
            cap_usd, stopped_after, why_left_out = exc.cap, last_asked, cap_reason(exc.cap)
            check.update(status="not_assessed", summary=f"not requested: {why_left_out}. No request was sent.")
            left_out.append(call.check_id)
        except NoCredentials:
            check.update(status="not_assessed", summary=NO_CREDENTIALS,
                         fix=f"Set {LOGIN_VAR} and {PASSWORD_VAR} in the environment or in a git-ignored .env file.")
        except NoCredit as exc:
            check.update(status="not_assessed", summary=f"not assessed: {exc}")
            stopped_after, why_left_out = call.check_id, RAN_OUT
        except (DataForSEOError, RuntimeError) as exc:  # includes a blocked budget and a corrupt ledger
            check.update(status="not_assessed", summary=f"not assessed: {exc}")
        else:
            evidence = {"source": "DataForSEO " + call.endpoint, "data_from": result.fetched_at,
                        "from_cache": result.cached, "cost_usd": result.cost}
            try:
                summary, data = (_READERS.get(call.endpoint) or insights.reader_for(call))(result.data)
            except (ValueError, KeyError, TypeError, AttributeError) as exc:
                check.update(status="not_assessed", evidence=evidence,
                             summary=f"not assessed: the DataForSEO response could not be read ({exc})")
            else:
                # Measurements only: there is no pass condition for a backlink count. An answer that holds some of the
                # measurements and not others is "partial": what is there is shown, what is not is named, and neither a
                # zero nor a healthy reading is made up for the missing part.
                missing = data.get("missing_measurements") if isinstance(data, dict) else None
                check.update(status="partial" if missing else "observed", summary=summary, evidence={**evidence, "data": data})
        if cap_usd is None:
            last_asked = call.check_id
        checks.append(check)
    _add_spam_line(checks)
    assessed = sum(check["status"] != "not_assessed" for check in checks)
    out = {"source": "DataForSEO (third-party data, not measured by the crawl)", "audit_id": client.audit_id,
           "panel": "Backlinks and authority" if all(call.check_id in ("DFS-1", "DFS-2") for call in plan) else "Search data",
           "confidence": CONFIDENCE,
           "target": next((call.target for call in plan if call.target), None),
           "status": ("assessed" if assessed == len(checks) and not any(check["status"] == "partial" for check in checks)
                      else "partly_assessed" if assessed else "not_assessed"),
           "checks": checks, "calls": client.calls, "requests_sent": client.requests_sent,
           "estimated_usd": round(sum(c["estimate_usd"] for c in client.calls if not c["from_cache"]), 6),
           "cost_usd": round(sum(c["cost_usd"] for c in client.calls), 6)}
    if not_requested is not None:
        out["stopped"] = {"code": BALANCE_AT_START_CODE, "after": None, "not_requested": left_out}
        out["note"] = f"Search data was not requested: {not_requested}."
    elif cap_usd is not None:
        out["stopped"] = {"code": AUDIT_CAP_CODE, "after": stopped_after, "not_requested": left_out}
        where = f"after {stopped_after}" if stopped_after else "before its first request"
        out["note"] = (f"This audit reached its ${cap_usd:.2f} DataForSEO limit {where}, so the remaining {len(left_out)} "
                       f"request(s) were not sent: {', '.join(left_out)}. Nothing was charged for them.")
    elif stopped_after is not None and left_out:
        out["stopped"] = {"code": NO_CREDIT_CODE, "after": stopped_after, "not_requested": left_out}
        out["note"] = (f"DataForSEO refused a request because the account has no credit, so the remaining {len(left_out)} "
                       "were not sent. Nothing was charged for them.")
    return out


_STATUS_LINE = {"assessed": "assessed", "partly_assessed": "PARTLY ASSESSED: at least one call failed, see below",
                "not_assessed": "NOT ASSESSED: no backlink data was obtained, see the reason below"}
_METRIC_LABELS = (("referring_domains", "Referring domains"), ("referring_main_domains", "Referring main domains"),
                  ("referring_domains_nofollow", "Referring domains (nofollow only)"), ("backlinks", "Backlinks"),
                  ("rank", "DataForSEO rank (its own score, not Google's)"),
                  ("backlinks_spam_score", "Backlink spam score"), ("broken_backlinks", "Broken backlinks"),
                  ("referring_ips", "Referring IPs"), ("referring_subnets", "Referring subnets"),
                  ("first_seen", "First seen by DataForSEO"))


def _count(value: Any) -> str:
    if isinstance(value, bool) or value is None:
        return "not reported"
    return f"{value:,}" if isinstance(value, (int, float)) else str(value)


def _spam(score: Any) -> str:
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        return "not reported"
    return f"{score} ⚠" if score >= SPAM_SCORE_THRESHOLD else str(score)


def _provenance(evidence: dict[str, Any]) -> str:
    cache = "served from Maya's local cache" if evidence["from_cache"] else "fetched for this audit"
    return f"{evidence['source']}; data from {evidence['data_from']}; {cache}; cost ${evidence['cost_usd']:.4f}"


def render_text(panel: dict[str, Any]) -> str:
    lines = ["=" * 78, f"DataForSEO: {panel['panel'].lower()} (third-party data; separate from the site checks above)",
             "=" * 78, "", f"Target domain: {panel['target'] or 'none'}", f"Confidence:    {panel['confidence']}",
             f"Panel:         {_STATUS_LINE[panel['status']]}", *([f"Note:          {panel['note']}"] if panel.get("note") else []), ""]
    for check in panel["checks"]:
        lines += [f"{check['check_id']}  {check['title']}", f"      status: {check['status'].upper()}",
                  f"      {check['summary']}"]
        evidence = check.get("evidence") or {}
        data = evidence.get("data") or {}
        for key, label in _METRIC_LABELS:
            if key in data:
                lines.append(f"      {label + ':':48} {_count(data[key])}")
        domains = data.get("domains") or []
        for row in domains[:SHOWN_DOMAINS]:
            lines.append(f"      {str(row['domain']):40} rank {_count(row['rank']):>6}   backlinks {_count(row['backlinks']):>6}"
                         f"   spam score {_spam(row['spam_score'])}")
        if len(domains) > SHOWN_DOMAINS:
            lines.append(f"      ... and {len(domains) - SHOWN_DOMAINS} more in the JSON report")
        for label, value in (data.get("metrics") or {}).items():
            lines.append(f"      {label + ':':48} {_count(value)}")
        table = data.get("table") or {}
        if table.get("rows"):
            lines.append("      " + " | ".join(table["columns"]))
            lines += ["      " + " | ".join(_count(cell) for cell in row) for row in table["rows"][:SHOWN_DOMAINS]]
            if len(table["rows"]) > SHOWN_DOMAINS:
                lines.append(f"      ... and {len(table['rows']) - SHOWN_DOMAINS} more in the JSON report")
        for aside in (data.get("ambiguous") or {}, data.get("unrelated") or {}, data.get("editorial_opportunities") or {}):
            if not aside.get("rows"):
                continue
            lines += [f"      {aside['title']}: {len(aside['rows'])}", "      " + aside["note"]]
            lines += ["      " + " | ".join(_count(cell) for cell in row) for row in aside["rows"][:SHOWN_UNRELATED]]
            if len(aside["rows"]) > SHOWN_UNRELATED:
                lines.append(f"      ... and {len(aside['rows']) - SHOWN_UNRELATED} more in the JSON report")
        if evidence:
            lines.append(f"      source: {_provenance(evidence)}")
        lines.append("")
    lines.append(f"DataForSEO spend or reserved estimate for this audit: ${panel['cost_usd']:.4f} "
                 f"(estimated up to ${panel['estimated_usd']:.4f}); {panel['requests_sent']} request(s) sent")
    return "\n".join(lines) + "\n"


def render_markdown(panel: dict[str, Any]) -> str:
    lines = ["", f"## DataForSEO: {panel['panel'].lower()} (third-party data)", "",
             "These results come from DataForSEO's own indexes, not from Maya's crawl, and are reported separately "
             "from the site checks. They are estimates: another index would give different numbers.", "",
             f"- **Target domain:** {panel['target'] or 'none'}", f"- **Confidence:** {panel['confidence']}",
             f"- **Panel:** {_STATUS_LINE[panel['status']]}", *([f"- **Note:** {panel['note']}"] if panel.get("note") else []), ""]
    for check in panel["checks"]:
        lines += [f"### {check['check_id']} {check['title']}", "", f"**Status:** {check['status']}. {check['summary']}", ""]
        evidence = check.get("evidence") or {}
        data = evidence.get("data") or {}
        if evidence:
            lines += [f"**Source:** {_provenance(evidence)}", ""]
        metrics = [(label, data[key]) for key, label in _METRIC_LABELS if key in data]
        if metrics:
            lines += ["| Measure | Value |", "|---|---|", *(f"| {label} | {_count(value)} |" for label, value in metrics), ""]
        domains = data.get("domains") or []
        if domains:
            lines += [f"Spam score is DataForSEO's own 0-100 measure; {data['spam_score_threshold']} or more is counted "
                      "here as \"looks like spam\" and marked with ⚠.", "",
                      "| Referring domain | DataForSEO rank | Backlinks | First seen | Spam score |", "|---|---|---|---|---|"]
            lines += [f"| {row['domain']} | {_count(row['rank'])} | {_count(row['backlinks'])} | "
                      f"{str(row['first_seen'] or 'not reported')[:10]} | {_spam(row['spam_score'])} |"
                      for row in domains[:SHOWN_DOMAINS]]
            if len(domains) > SHOWN_DOMAINS:
                lines.append(f"\n{len(domains) - SHOWN_DOMAINS} more are in the JSON report.")
            lines.append("")
        extra = list((data.get("metrics") or {}).items())
        if extra:
            lines += ["| Measure | Value |", "|---|---|", *(f"| {label} | {_count(value)} |" for label, value in extra), ""]
        table = data.get("table") or {}
        if table.get("rows"):
            cell = lambda value: _count(value).replace("|", "\\|")  # noqa: E731
            lines += ["| " + " | ".join(table["columns"]) + " |", "|" + "---|" * len(table["columns"])]
            lines += ["| " + " | ".join(cell(value) for value in row) + " |" for row in table["rows"][:SHOWN_DOMAINS]]
            if len(table["rows"]) > SHOWN_DOMAINS:
                lines.append(f"\n{len(table['rows']) - SHOWN_DOMAINS} more are in the JSON report.")
            lines.append("")
        for aside in (data.get("ambiguous") or {}, data.get("unrelated") or {}, data.get("editorial_opportunities") or {}):
            if not aside.get("rows"):
                continue
            cell = lambda value: _count(value).replace("|", "\\|")  # noqa: E731
            lines += [f"**{aside['title']}: {len(aside['rows'])}.** {aside['note']}", "",
                      "| " + " | ".join(aside["columns"]) + " |", "|" + "---|" * len(aside["columns"])]
            lines += ["| " + " | ".join(cell(value) for value in row) + " |" for row in aside["rows"][:SHOWN_UNRELATED]]
            if len(aside["rows"]) > SHOWN_UNRELATED:
                lines.append(f"\n{len(aside['rows']) - SHOWN_UNRELATED} more are in the JSON report.")
            lines.append("")
    lines += [f"**DataForSEO spend or reserved estimate for this audit:** ${panel['cost_usd']:.4f} "
              f"(estimated up to ${panel['estimated_usd']:.4f}), {panel['requests_sent']} request(s) sent", ""]
    return "\n".join(lines)


def _nonzero(value: Any, path: tuple[str, ...] = ()) -> list[tuple[str, Any]]:
    """The entries of a nested table that are set, as ("day/total", 100) pairs. DataForSEO lists hundreds of zeros."""
    if isinstance(value, dict):
        return [found for key, inner in value.items() for found in _nonzero(inner, path + (str(key),))]
    return [("/".join(path), value)] if value else []


def account_price(prices: Any, endpoint: str) -> tuple[float | None, float | None]:
    """(per request, per result) the account lists for `endpoint`: the dearest of its priority levels.

    The account's price table is nested by the endpoint's path, each leaf a list like
    [{"cost_type": "per_request", "cost": 0.024}, {"cost_type": "per_result", "cost": 0.000036}].
    """
    node = prices
    for part in endpoint.strip("/").split("/")[1:]:  # drop the leading "v3"
        node = node.get(part) if isinstance(node, dict) else None
    found: dict[str, float] = {}
    for rows in (node.values() if isinstance(node, dict) else [node]):
        for row in rows if isinstance(rows, list) else []:
            if isinstance(row, dict) and isinstance(row.get("cost"), (int, float)):
                kind = str(row.get("cost_type"))
                found[kind] = max(found.get(kind, 0.0), float(row["cost"]))
    return found.get("per_request"), found.get("per_result")


def price_check(prices: Any) -> list[str]:
    """Each paid endpoint Maya uses: the account's listed price beside the estimator's, and whether it is covered."""
    lines = []
    for endpoint, (request_usd, row_usd) in pricing.LISTED_PRICES.items():
        per_request, per_result = account_price(prices, endpoint)
        if per_request is None and per_result is None:
            lines.append(f"    {endpoint}: the account lists no price; Maya estimates ${request_usd} a request + ${row_usd} a row")
            continue
        covered = (per_request or 0.0) <= request_usd and (per_result or 0.0) <= row_usd
        verdict = "covered by Maya's estimate" if covered else (
            "ABOVE MAYA'S ESTIMATE: raise it in maya_audit/dataforseo/pricing.py before the next paid audit")
        lines.append(f"    {endpoint}: account ${per_request or 0:g} a request + ${per_result or 0:g} a result; "
                     f"Maya estimates ${request_usd:g} + ${row_usd:g}: {verdict}")
    return lines


def account_balance(client: DataForSEOClient) -> float | None:
    """The account's balance in US dollars from the free account endpoint, or None when it is not reported."""
    result = client.request(pricing.USER_DATA)
    account = (((result.data.get("tasks") or [{}])[0].get("result") or [{}])[0]) or {}
    balance = (account.get("money") or {}).get("balance")
    return float(balance) if isinstance(balance, (int, float)) and not isinstance(balance, bool) else None


def balance_report(credentials: Credentials, ledger: Ledger, *, all_prices: bool = False) -> list[str]:
    """Ask the free account endpoint, and only that one, for the balance, today's spend and the prices Maya relies on."""
    client = DataForSEOClient(credentials, ledger, None, audit_id="balance")
    try:
        result = client.request(pricing.USER_DATA)
    finally:
        client.close()
    tasks = result.data.get("tasks") or [{}]
    account = ((tasks[0].get("result") or [{}])[0]) or {}
    money = account.get("money") or {}
    day = (money.get("statistics") or {}).get("day") or {}
    lines = [f"DataForSEO account (login {credentials.redact(str(account.get('login', 'not reported')))})",
             f"  Balance:         {_usd(money.get('balance'))}",
             f"  Total deposited: {_usd(money.get('total'))}",
             f"  Spent today, as DataForSEO counts it: {_usd(day.get('total'))} "
             f"(its day {day.get('value', 'not reported')}, account time zone {account.get('timezone', 'not reported')})"]
    try:
        lines.append(f"  Spent today through Maya Audit:       {_usd(ledger.spent_today())} (this machine's ledger, UTC day). "
                     "A larger DataForSEO figure means something else used the account today.")
    except LedgerCorrupt as exc:
        lines.append(f"  Spent today through Maya Audit:       unknown ({exc})")
    limits = _nonzero(money.get("limits"))
    lines.append("  Spending limits set on the account: " + (", ".join(f"{path} = {value}" for path, value in limits) or "none"))
    for key in sorted(k for k in account if k.endswith("_subscription_expiry_date")):
        lines.append(f"  {key.removesuffix('_subscription_expiry_date').replace('_', ' ').capitalize()} subscription until: "
                     f"{str(account[key])[:10] or 'not reported'}")
    prices = next((account[key] for key in ("price", "prices", "pricing") if account.get(key)), None)
    if prices:
        lines += ["  Prices the account lists for the paid endpoints Maya uses:", *price_check(prices)]
        if all_prices:
            lines += ["  Every price the account lists:",
                      *("    " + line for line in json.dumps(prices, indent=2, sort_keys=True).splitlines())]
    else:
        lines.append("  This endpoint returned no price information for the account.")
    lines.append(f"  Cost of this request: ${result.cost:.4f}")
    return [credentials.redact(line) for line in lines]


def _usd(value: Any) -> str:
    return f"${value:,.4f}" if isinstance(value, (int, float)) else "not reported"
