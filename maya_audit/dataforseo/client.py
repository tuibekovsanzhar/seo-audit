"""The one place a DataForSEO request is sent from.

`DataForSEOClient.request` is the only function that talks to the API, and the cost guard is
inside it: allow-list, price check, approval limit, the audit's own limit, daily budget, ledger reservation, cache. A caller cannot
reach the network without passing all of them.
"""

from __future__ import annotations

import time
import math
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

import httpx

from ..network import PublicTransport
from ..urls import UnresolvedHostError, UnsafeTargetError
from . import pricing
from .cache import Cache
from .credentials import Credentials
from .ledger import Ledger

BASE_URL = "https://api.dataforseo.com"
OK = 20000  # DataForSEO's own status code for success, at the top level and on each task
TIMEOUT_S = 30.0
RETRIES_ON_5XX = 2
# A call that never left this computer (the address lookup failed, or no connection could be made) is tried once
# more: nothing was sent, so nothing can be charged twice. A call that was sent and got no answer is never repeated.
RETRIES_WHEN_NOT_SENT = 1
RETRY_WAIT_S = 2.0
NOT_REACHED = ("DataForSEO {endpoint} could not be reached: {why}, in {times} attempts. Nothing was sent and nothing was "
               "charged. This is a connection problem on this computer or network, not a problem with the site or the account: "
               "check the internet connection and run the audit again")
# Tests replace this with a mock transport. Nothing else should.
TRANSPORT: httpx.BaseTransport | None = None


class DataForSEOError(RuntimeError):
    """A DataForSEO request failed or was refused. The message never contains credentials."""


class NoCredentials(DataForSEOError):
    pass


class NoEstimator(DataForSEOError):
    pass


class EndpointNotAllowed(DataForSEOError):
    """The endpoint is not one Maya may call (pricing.ALLOWED_ENDPOINTS), or it belongs to an API Maya never calls
    (pricing.FORBIDDEN_PREFIXES: the SERP API). Refused before anything is priced, reserved or sent."""


class ApprovalRequired(DataForSEOError):
    pass


class NoCredit(DataForSEOError):
    """DataForSEO answered that the account cannot pay for this request. Asking for anything else paid in the same
    audit would be refused the same way, so the caller stops asking (panel.run_checks)."""

    def __init__(self, message: str, code: int) -> None:
        super().__init__(message)
        self.code = code


# DataForSEO's own status codes for "the account cannot pay": 40200 Payment Required, 40210 Insufficient Funds. Read
# from its documentation and from four saved refusals (40200); 40210 has not been seen (docs/LAUNCH-GATE.md).
NO_CREDIT_CODES = frozenset({40200, 40210})


class PossiblyBilled(DataForSEOError):
    """The request was sent and no answer came back: it may have been charged, and it is not retried."""


@dataclass
class DataForSEOResult:
    endpoint: str
    data: dict[str, Any]
    estimate: float
    cost: float
    cached: bool
    fetched_at: str  # when DataForSEO produced this data (UTC)

    @property
    def age_s(self) -> float:
        return max(0.0, (datetime.now(timezone.utc) - datetime.fromisoformat(self.fetched_at)).total_seconds())


def reported_cost(body: dict[str, Any]) -> float | None:
    """The `cost` DataForSEO reports for a response, including tasks that failed but were billed."""
    def valid(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0
    if valid(body.get("cost")):
        return float(body["cost"])
    costs = [t["cost"] for t in body.get("tasks") or [] if isinstance(t, dict) and valid(t.get("cost"))]
    return float(sum(costs)) if costs else None


def succeeded(body: dict[str, Any]) -> bool:
    tasks = body.get("tasks") or []
    return body.get("status_code") == OK and all(isinstance(t, dict) and t.get("status_code") == OK for t in tasks)


class DataForSEOClient:
    def __init__(self, credentials: Credentials | None, ledger: Ledger, cache: Cache | None, *,
                 prices: dict[str, pricing.Estimator] | None = None,
                 allowed: frozenset[str] | None = None,
                 cache_lifetimes: dict[str, int] | None = None,
                 always_ask: frozenset[str] | None = None,
                 daily_budget: float | None = None,
                 audit_cap: float | None = None,
                 approved_usd: float | None = None,
                 approved_always_ask: bool = False,
                 audit_id: str | None = None,
                 transport: httpx.BaseTransport | None = None,
                 deadline_mono: float | None = None, should_stop: Callable[[], bool] | None = None) -> None:
        self.deadline_mono = deadline_mono
        self.should_stop = should_stop
        self.credentials = credentials
        self.ledger = ledger
        self.cache = cache
        self.prices = pricing.PRICE_ESTIMATORS if prices is None else prices
        # The endpoints this client may call. A caller with its own price table names its endpoints here as well; the
        # forbidden prefixes are refused whatever this holds.
        self.allowed = pricing.ALLOWED_ENDPOINTS if allowed is None else frozenset(allowed)
        self.cache_lifetimes = pricing.CACHE_LIFETIME_S if cache_lifetimes is None else cache_lifetimes
        self.always_ask = pricing.ALWAYS_ASK if always_ask is None else always_ask
        # Read when the client is made, so the configured limits apply.
        self.daily_budget = pricing.daily_budget() if daily_budget is None else daily_budget
        self.audit_cap = pricing.audit_cap() if audit_cap is None else audit_cap
        self.approved_usd = pricing.approval_threshold() if approved_usd is None else approved_usd
        self.approved_always_ask = approved_always_ask
        self.audit_id = audit_id or uuid.uuid4().hex[:12]
        self.estimated_this_audit = 0.0
        self.requests_sent = 0
        # What was asked and what it cost, for the report. Never headers, never credentials.
        self.calls: list[dict[str, Any]] = []
        self._http = httpx.Client(base_url=BASE_URL, timeout=TIMEOUT_S, trust_env=False,
                                  transport=transport or TRANSPORT or PublicTransport(allow_loopback=False, before_connect=self._remaining_timeout))

    def _remaining_timeout(self) -> float:
        if self.should_stop is not None and self.should_stop():
            raise DataForSEOError("DataForSEO plan stopped on request; no further request sent")
        remaining = TIMEOUT_S if self.deadline_mono is None else self.deadline_mono - time.monotonic()
        if remaining <= 0:
            raise DataForSEOError("DataForSEO plan deadline reached; no further request sent")
        return min(TIMEOUT_S, remaining)

    def close(self) -> None:
        self._http.close()

    def _clean(self, text: str) -> str:
        return self.credentials.redact(text) if self.credentials else text

    def request(self, endpoint: str, payload: Any = None, *, target: str | None = None,
                refresh: bool = False) -> DataForSEOResult:
        """Send one request (POST with `payload`, GET without) — after every check has passed."""
        if not pricing.allowed(endpoint, self.allowed):
            raise EndpointNotAllowed(f"DataForSEO endpoint {endpoint} is not on Maya's list of allowed endpoints, so it is "
                                     "refused. No request was sent.")
        self._remaining_timeout()
        estimate = pricing.estimate(endpoint, payload, self.prices)
        if estimate is None:
            raise NoEstimator(f"DataForSEO endpoint {endpoint} has no price estimator in maya_audit/dataforseo/"
                              "pricing.py, so it is refused. No request was sent.")
        if self.credentials is None:
            raise NoCredentials("no credentials")

        lifetime = self.cache_lifetimes.get(endpoint, 0)
        if self.cache is not None and lifetime and not refresh:
            held = self.cache.get(endpoint, payload, lifetime)
            if held is not None:
                body, stored_at = held
                self.ledger.note("cache_hit", endpoint, target, self.audit_id, cache="hit")
                result = DataForSEOResult(endpoint, body, estimate, 0.0, True,
                                          datetime.fromtimestamp(stored_at, timezone.utc).isoformat(timespec="seconds"))
                self._record(result, target)
                return result

        call_id = None
        if estimate > 0:
            if endpoint in self.always_ask and not self.approved_always_ask:
                raise ApprovalRequired(f"DataForSEO endpoint {endpoint} always needs approval. No request was sent.")
            if round(self.estimated_this_audit + estimate, 6) > round(self.approved_usd, 6):
                raise ApprovalRequired(
                    f"this audit's DataForSEO calls would reach ${self.estimated_this_audit + estimate:.4f}, above the "
                    f"approved ${self.approved_usd:.2f}. No request was sent; approve more with --dfs-approve-up-to.")
            call_id = self.ledger.reserve(endpoint, target, self.audit_id, estimate, self.daily_budget,
                                          audit_cap=self.audit_cap)
            self.estimated_this_audit = round(self.estimated_this_audit + estimate, 6)

        try:
            body = self._send(endpoint, payload, call_id)
        except DataForSEOError:
            if call_id is not None:
                row = next(c for c in self.ledger.calls() if c["id"] == call_id)
                self.calls.append({"endpoint": endpoint, "target": target, "estimate_usd": estimate,
                                   "cost_usd": self.ledger._counted(row), "from_cache": False,
                                   "data_from": row["ts"], "billing_status": row["status"]})
            raise
        cost = reported_cost(body)
        if call_id is not None:
            # The real cost replaces the estimate, also when the task failed but was billed.
            self.ledger.settle(call_id, "settled", estimate if cost is None else cost,
                               None if cost is not None else "the response reported no cost; the estimate was kept")
        else:
            try:
                self.ledger.note("free", endpoint, target, self.audit_id, cost=cost or 0.0)
            except RuntimeError:
                pass  # a ledger that cannot be read stops paid calls; it does not stop a free one
        # One time for this answer: the report, the call record and the cache all give the same date (it was read twice
        # before, and a second could pass in between).
        arrived = datetime.now(timezone.utc).replace(microsecond=0)
        recorded = DataForSEOResult(endpoint, {}, estimate, estimate if cost is None else cost, False,
                                    arrived.isoformat(timespec="seconds"))
        self._record(recorded, target)
        self.calls[-1]["billing_status"] = "estimated" if cost is None else "reported"
        if not succeeded(body):
            failed = next((t for t in body.get("tasks") or [] if isinstance(t, dict) and t.get("status_code") != OK), body)
            refused = next((part.get("status_code") for part in (failed, body) if part.get("status_code") in NO_CREDIT_CODES), None)
            if refused is not None:
                # In plain words, with the provider's code kept. What the ledger recorded decides the last sentence.
                kept = ("Nothing was charged." if cost == 0 or (cost is None and not estimate) else
                        f"The answer reported no cost, so the estimate of ${estimate:.4f} stays counted against today's limit." if cost is None else
                        f"DataForSEO reported a cost of ${cost:.4f} for it, which stays counted.")
                raise NoCredit(f"the DataForSEO account has no credit for this request (provider code {refused}). {kept}", refused)
            raise DataForSEOError(self._clean(
                f"DataForSEO refused {endpoint}: {failed.get('status_code')} {failed.get('status_message')}"))
        body = self.credentials.redact_json(body)
        if self.cache is not None and lifetime:
            self.cache.put(endpoint, payload, body, stored_at=arrived.timestamp())
        result = DataForSEOResult(endpoint, body, estimate, estimate if cost is None else cost, False,
                                  arrived.isoformat(timespec="seconds"))
        return result

    def _record(self, result: DataForSEOResult, target: str | None) -> None:
        self.calls.append({"endpoint": result.endpoint, "target": target, "estimate_usd": result.estimate,
                           "cost_usd": result.cost, "from_cache": result.cached, "data_from": result.fetched_at})

    def _send(self, endpoint: str, payload: Any, call_id: str | None) -> dict[str, Any]:
        headers = {"Authorization": self.credentials.authorization()}
        attempt, unsent_left = 0, RETRIES_WHEN_NOT_SENT
        while True:
            counted = False
            try:
                timeout = self._remaining_timeout()
                self.requests_sent += 1
                counted = True
                end = time.monotonic() + timeout
                method = "GET" if payload is None else "POST"
                with self._http.stream(method, endpoint, headers=headers, timeout=timeout,
                                       **({} if payload is None else {"json": payload})) as incoming:
                    chunks, size = [], 0
                    for chunk in incoming.iter_bytes():
                        if time.monotonic() >= end or (self.should_stop is not None and self.should_stop()):
                            raise httpx.ReadTimeout("DataForSEO response interrupted")
                        size += len(chunk)
                        if size > 8 * 1024 * 1024:
                            raise httpx.ReadError("DataForSEO response exceeds size limit")
                        chunks.append(chunk)
                    response = httpx.Response(incoming.status_code, content=b"".join(chunks))
            except DataForSEOError:
                self.requests_sent -= int(counted)
                if call_id is not None:
                    self.ledger.settle(call_id, "failed", 0.0, "stopped before network connection")
                raise
            except UnresolvedHostError:
                # The address of DataForSEO's own server could not be looked up (DNS failed or timed out). Nothing was
                # connected to, so nothing was sent or charged, and asking once more cannot pay twice.
                self.requests_sent -= int(counted)
                if unsent_left > 0:
                    unsent_left -= 1
                    time.sleep(RETRY_WAIT_S)
                    continue
                if call_id is not None:
                    self.ledger.settle(call_id, "failed", 0.0, f"address lookup failed {RETRIES_WHEN_NOT_SENT + 1} times; no connection made")
                raise DataForSEOError(NOT_REACHED.format(endpoint=endpoint, why="its address could not be looked up (DNS)",
                                                         times=RETRIES_WHEN_NOT_SENT + 1)) from None
            except UnsafeTargetError:
                self.requests_sent -= int(counted)
                if call_id is not None:
                    self.ledger.settle(call_id, "failed", 0.0, "unsafe destination; no connection made")
                raise DataForSEOError("DataForSEO destination failed network safety checks; no request sent") from None
            except httpx.TimeoutException as exc:
                # Sent, no answer: DataForSEO may have done the work and charged for it. Asking again
                # could pay twice, so the reservation stays and the call is not repeated.
                if call_id is not None:
                    self.ledger.settle(call_id, "possibly_billed", None, f"timed out ({type(exc).__name__}); not retried")
                raise PossiblyBilled(f"DataForSEO {endpoint} timed out; it may have been billed and was not retried") from None
            except httpx.ConnectError as exc:
                # No connection was made, so nothing reached DataForSEO and nothing can have been charged: one more try.
                if unsent_left > 0:
                    self.requests_sent -= int(counted)
                    unsent_left -= 1
                    time.sleep(RETRY_WAIT_S)
                    continue
                if call_id is not None:
                    self.ledger.settle(call_id, "failed", 0.0, f"not sent ({type(exc).__name__}), {RETRIES_WHEN_NOT_SENT + 1} attempts")
                raise DataForSEOError(self._clean(NOT_REACHED.format(endpoint=endpoint, why=f"no connection could be made ({type(exc).__name__})",
                                                                     times=RETRIES_WHEN_NOT_SENT + 1))) from None
            except httpx.HTTPError as exc:
                if call_id is not None:
                    self.ledger.settle(call_id, "possibly_billed", None, f"delivery uncertain ({type(exc).__name__}); not retried")
                raise DataForSEOError(self._clean(f"DataForSEO {endpoint} could not be reached ({type(exc).__name__})")) from None
            if call_id is None and response.status_code >= 500 and attempt < RETRIES_ON_5XX:
                attempt += 1
                time.sleep(0.5 * attempt)
                continue
            break
        try:
            body = response.json()
            if not isinstance(body, dict):
                raise ValueError("not a JSON object")
        except ValueError:
            if call_id is not None:
                self.ledger.settle(call_id, "possibly_billed", None, f"HTTP {response.status_code}, no usable response; not retried")
            raise DataForSEOError(f"DataForSEO {endpoint} answered HTTP {response.status_code} with no usable response") from None
        return body
