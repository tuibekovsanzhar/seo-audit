"""DataForSEO prices and spending limits. This is the only file that holds them.

CHECK THESE AGAINST YOUR OWN ACCOUNT before switching an endpoint on. DataForSEO prices differ
between accounts and change over time, and the two open-source tools this was modelled on disagree
with each other. `maya-audit dfs balance` prints whatever price information your account returns.

Each estimator returns a conservative UPPER BOUND in US dollars for one request, worked out from the
request's parameters. It is used to plan and to reserve budget before the call; the ledger is then
corrected to the `cost` DataForSEO reports. An endpoint with no estimator here is refused: the
client never guesses a price.
"""

from __future__ import annotations

from typing import Any, Callable

Estimator = Callable[[Any], float]

USER_DATA = "/v3/appendix/user_data"

BACKLINKS_SUMMARY = "/v3/backlinks/summary/live"
BACKLINKS_REFERRING_DOMAINS = "/v3/backlinks/referring_domains/live"

# Backlinks API: a fixed price per request plus a price per returned row. Checked on 2026-10-06
# against one account's own price list (`maya-audit dfs balance`) and against the `cost` of a real
# audit: both matched these figures exactly. Another account, or a later date, can differ, so
# `dfs balance` compares them again every time it is run.
BACKLINKS_REQUEST_USD = 0.024
BACKLINKS_ROW_USD = 0.000036
# Rows DataForSEO may return when a request sets no limit of its own (the API's maximum).
BACKLINKS_MAX_ROWS = 1000


def _backlinks_rows(payload: Any) -> float:
    """Upper bound for a Backlinks request that returns up to `limit` rows per task."""
    tasks = payload if isinstance(payload, list) and payload else [{}]
    total = 0.0
    for task in tasks:
        limit = task.get("limit") if isinstance(task, dict) else None
        rows = limit if isinstance(limit, int) and not isinstance(limit, bool) and limit > 0 else BACKLINKS_MAX_ROWS
        total += BACKLINKS_REQUEST_USD + rows * BACKLINKS_ROW_USD
    return total


def _backlinks_summary(payload: Any) -> float:
    """Upper bound for a Backlinks summary: one row per task."""
    tasks = payload if isinstance(payload, list) and payload else [{}]
    return len(tasks) * (BACKLINKS_REQUEST_USD + BACKLINKS_ROW_USD)


# -- Search data panels (added 2026-10-08). Endpoint names and prices were read from DataForSEO's public documentation
# and pricing pages on that day; none of these endpoints was called while this was written. `maya-audit dfs balance`
# compares them with the account's own price list.
LABS_DOMAIN_OVERVIEW = "/v3/dataforseo_labs/google/domain_rank_overview/live"
LABS_RANKED_KEYWORDS = "/v3/dataforseo_labs/google/ranked_keywords/live"
LABS_COMPETITORS = "/v3/dataforseo_labs/google/competitors_domain/live"
LLM_MENTIONS_AGGREGATED = "/v3/ai_optimization/llm_mentions/aggregated_metrics/live"
LIGHTHOUSE = "/v3/on_page/lighthouse/live/json"
BUSINESS_INFO = "/v3/business_data/google/my_business_info/live"

# DataForSEO Labs (Google), live: per task and per returned item.
LABS_REQUEST_USD = 0.012
LABS_ROW_USD = 0.00012
LABS_DEFAULT_ROWS = 100
# LLM Mentions: per request and per row; needs the account's AI Optimization subscription.
LLM_REQUEST_USD = 0.10
LLM_ROW_USD = 0.001
# One row is charged for each entry of the task's `target` list, not for the rows inside the answer: two real requests
# with one target each settled at $0.101 (2026-10-13). That is one audit's ledger, so it is watched (LAUNCH-GATE LG-71).
LIGHTHOUSE_USD = 0.005
BUSINESS_INFO_USD = 0.0054


def _per_task(payload: Any, price_of: Callable[[dict], float]) -> float:
    tasks = payload if isinstance(payload, list) and payload else [{}]
    return sum(price_of(task if isinstance(task, dict) else {}) for task in tasks)


def _llm_mentions(payload: Any) -> float:
    def one(task: dict) -> float:
        targets = task.get("target")
        rows = max(1, len(targets)) if isinstance(targets, list) else 1
        return LLM_REQUEST_USD + rows * LLM_ROW_USD
    return _per_task(payload, one)


def _labs(payload: Any) -> float:
    def one(task: dict) -> float:
        limit = task.get("limit")
        rows = limit if isinstance(limit, int) and not isinstance(limit, bool) and limit > 0 else LABS_DEFAULT_ROWS
        return LABS_REQUEST_USD + rows * LABS_ROW_USD
    return _per_task(payload, one)


# endpoint path -> (per request, per row) behind its estimator. `maya-audit dfs balance` sets these
# beside the prices the account lists and says so when the account's are higher.
LISTED_PRICES: dict[str, tuple[float, float]] = {
    BACKLINKS_SUMMARY: (BACKLINKS_REQUEST_USD, BACKLINKS_ROW_USD),
    BACKLINKS_REFERRING_DOMAINS: (BACKLINKS_REQUEST_USD, BACKLINKS_ROW_USD),
    LABS_DOMAIN_OVERVIEW: (LABS_REQUEST_USD, LABS_ROW_USD),
    LABS_RANKED_KEYWORDS: (LABS_REQUEST_USD, LABS_ROW_USD),
    LABS_COMPETITORS: (LABS_REQUEST_USD, LABS_ROW_USD),
    LLM_MENTIONS_AGGREGATED: (LLM_REQUEST_USD, LLM_ROW_USD),
    LIGHTHOUSE: (LIGHTHOUSE_USD, 0.0),
    BUSINESS_INFO: (BUSINESS_INFO_USD, 0.0),
}

# endpoint path -> upper-bound price of one request. Paid endpoints are added here, one at a time,
# when the panel that uses them is built.
PRICE_ESTIMATORS: dict[str, Estimator] = {
    USER_DATA: lambda payload: 0.0,  # account details and balance; DataForSEO does not charge for it
    BACKLINKS_SUMMARY: _backlinks_summary,
    BACKLINKS_REFERRING_DOMAINS: _backlinks_rows,
    LABS_DOMAIN_OVERVIEW: _labs,
    LABS_RANKED_KEYWORDS: _labs,
    LABS_COMPETITORS: _labs,
    LLM_MENTIONS_AGGREGATED: _llm_mentions,
    LIGHTHOUSE: lambda payload: _per_task(payload, lambda task: LIGHTHOUSE_USD),
    BUSINESS_INFO: lambda payload: _per_task(payload, lambda task: BUSINESS_INFO_USD),
}

# Endpoints that need explicit approval on every audit, whatever they cost (live LLM answers and
# backlink row dumps belong here when they are added).
ALWAYS_ASK: frozenset[str] = frozenset()

# The only DataForSEO endpoints Maya may call: exactly the ones priced above. `DataForSEOClient.request` refuses any
# other path before anything is reserved or sent, also when a caller brings its own price table (DECISIONS 193).
ALLOWED_ENDPOINTS: frozenset[str] = frozenset(PRICE_ESTIMATORS)
# Never called, whoever asks and whatever list they pass: Maya does not use the SERP API.
FORBIDDEN_PREFIXES: tuple[str, ...] = ("/v3/serp/",)

# What a plan card and the dry run call each API, from the endpoint's path. SERP is listed so it can be shown as zero.
SERVICES: tuple[tuple[str, str], ...] = (
    ("/v3/backlinks/", "Backlinks"), ("/v3/dataforseo_labs/", "Labs"), ("/v3/ai_optimization/", "AI Optimization"),
    ("/v3/on_page/", "OnPage (Lighthouse)"), ("/v3/business_data/", "Business Data"), ("/v3/serp/", "SERP"))
SERP_SERVICE = "SERP"


def service_of(endpoint: str) -> str:
    """The DataForSEO API an endpoint belongs to, by its path. A path of no listed API is named by its first part."""
    for prefix, name in SERVICES:
        if endpoint.startswith(prefix):
            return name
    parts = endpoint.strip("/").split("/")
    return parts[1] if len(parts) > 1 else endpoint


def allowed(endpoint: str, allow: frozenset[str] | None = None) -> bool:
    """Whether Maya may call this endpoint. A forbidden prefix is refused whatever `allow` holds."""
    if any(endpoint.startswith(prefix) for prefix in FORBIDDEN_PREFIXES):
        return False
    return endpoint in (ALLOWED_ENDPOINTS if allow is None else allow)


# The three spending limits (owner, 2026-10-14; DECISIONS 192). Every call is still priced first, reserved and recorded.
# An audit whose planned DataForSEO total is above this needs approval (a yes on the terminal or --dfs-approve-up-to;
# the Confirm button in the web app). At or below it the audit runs without asking: a normal audit with backlinks
# and the search data panels is about $0.33.
APPROVAL_THRESHOLD_USD = 2.00
APPROVAL_THRESHOLD_VAR = "MAYA_AUDIT_DATAFORSEO_CONFIRM_ABOVE_USD"
# One audit never spends more than this, whatever was confirmed: the request that would pass it is not sent, nor any
# after it (ledger.Ledger.reserve). A resumed audit keeps its audit id, so the limit covers every session of it.
AUDIT_CAP_USD = 5.00
AUDIT_CAP_VAR = "MAYA_AUDIT_DATAFORSEO_AUDIT_CAP_USD"
# Paid calls stop for the day (UTC) once spend plus the next estimate would pass this. A guard against a runaway,
# not a target. MAYA_AUDIT_DATAFORSEO_DAILY_USD (environment or .env) or --dfs-daily-budget changes it.
DAILY_BUDGET_USD = 20.00
DAILY_BUDGET_VAR = "MAYA_AUDIT_DATAFORSEO_DAILY_USD"


def _limit(variable: str, default: float, environ: Any = None) -> float:
    """A limit in US dollars: the configured one (environment, then the .env file) when it is a sensible number,
    otherwise the default."""
    import os
    from pathlib import Path

    from .credentials import read_env_file

    environ = os.environ if environ is None else environ
    raw = environ.get(variable) or read_env_file(Path(environ.get("MAYA_AUDIT_ENV_FILE") or ".env")).get(variable)
    try:
        value = float(raw) if raw else default
    except ValueError:
        return default
    return value if 0 <= value <= 10_000 else default


def daily_budget(environ: Any = None) -> float:
    """Today's limit in US dollars: the configured one when it is a sensible number, otherwise the default."""
    return _limit(DAILY_BUDGET_VAR, DAILY_BUDGET_USD, environ)


def audit_cap(environ: Any = None) -> float:
    """The most one audit may spend, in US dollars: the configured amount when it is a sensible number, else the default."""
    return _limit(AUDIT_CAP_VAR, AUDIT_CAP_USD, environ)


def approval_threshold(environ: Any = None) -> float:
    """The plan total above which an audit asks first. Never above the per-audit limit: a plan the limit would cut short
    is always confirmed."""
    return min(_limit(APPROVAL_THRESHOLD_VAR, APPROVAL_THRESHOLD_USD, environ), audit_cap(environ))


# How long a successful response is reused, in seconds. An endpoint that is not listed is never cached.
DAY = 24 * 60 * 60
CACHE_LIFETIME_S: dict[str, int] = {
    # USER_DATA is deliberately absent: a balance must be current, and the response names the account.
    BACKLINKS_SUMMARY: 7 * DAY,
    BACKLINKS_REFERRING_DOMAINS: 7 * DAY,
    LABS_DOMAIN_OVERVIEW: 7 * DAY,
    LABS_RANKED_KEYWORDS: 7 * DAY,
    LABS_COMPETITORS: 7 * DAY,
    LLM_MENTIONS_AGGREGATED: 7 * DAY,
    LIGHTHOUSE: DAY,          # a speed test is about the page as it is now
    BUSINESS_INFO: 7 * DAY,
}


def estimate(endpoint: str, payload: Any, prices: dict[str, Estimator] | None = None) -> float | None:
    """Upper-bound price of this request, or None when the endpoint has no estimator."""
    estimator = (PRICE_ESTIMATORS if prices is None else prices).get(endpoint)
    return None if estimator is None else round(float(estimator(payload)), 6)
