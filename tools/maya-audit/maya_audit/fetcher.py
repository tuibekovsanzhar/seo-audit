from __future__ import annotations

import ssl
import threading
import time
import zlib
from http.cookiejar import DefaultCookiePolicy
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlsplit

import httpx

from .models import RequestRecord
from .network import PublicTransport, BeforeConnectDeadline
from .urls import HostNotFoundError, LocalDnsError, UnresolvedHostError, UnsafeTargetError, validate_public_target

ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
# Requests that do not count toward adaptive pacing (DECISIONS 219 part 2): ACC-4's browser and Googlebot comparison,
# and what a rendering browser asks for inside one page.
NOT_PACED_PURPOSES = ("ua_check", "render_subresource")
# What the request log shows for a Cookie header Maya sent back (IDX-3, DECISIONS 217): never the value.
COOKIE_NOT_KEPT = "(the site's own cookie, sent back once; value not kept)"
# Only the encodings Maya decodes itself with a bound on the output (A6). httpx would otherwise also offer br and zstd
# when those libraries are installed, and decode each network chunk whole: a few hundred KB of gzip can expand to
# hundreds of MB before the body cap is looked at.
ACCEPT_ENCODING = "gzip, deflate"


class _BoundedDecoder:
    """Decodes a response body piece by piece, never producing more than asked for at once (A6).

    gzip and deflate (zlib-wrapped, or raw deflate as some servers send it, the way httpx falls back) are decoded here;
    no encoding or "identity" passes the bytes through. Any other encoding gets no decoder (`for_encoding` returns
    None) and the caller keeps httpx's own decoding: a server that sends br although Maya did not offer it."""

    def __init__(self, kind: str) -> None:
        self.kind = kind
        self._raw_deflate_tried = False
        self._d = (zlib.decompressobj(16 + zlib.MAX_WBITS) if kind == "gzip" else
                   zlib.decompressobj() if kind == "deflate" else None)

    @classmethod
    def for_encoding(cls, value: str | None) -> "_BoundedDecoder | None":
        coding = (value or "").strip().lower()
        if coding in ("", "identity"):
            return cls("identity")
        if coding in ("gzip", "x-gzip"):
            return cls("gzip")
        if coding == "deflate":
            return cls("deflate")
        return None

    def decode(self, data: bytes, limit: int) -> bytes:
        """At most `limit` bytes of output from `data`, after whatever input an earlier call left unread."""
        if self._d is None:
            return data
        data = self._d.unconsumed_tail + data
        try:
            return self._d.decompress(data, max(1, limit))
        except zlib.error as exc:
            if self.kind == "deflate" and not self._raw_deflate_tried:
                self._raw_deflate_tried = True
                self._d = zlib.decompressobj(-zlib.MAX_WBITS)
                try:
                    return self._d.decompress(data, max(1, limit))
                except zlib.error as again:
                    raise httpx.DecodingError(f"deflate: {again}") from None
            raise httpx.DecodingError(f"{self.kind}: {exc}") from None

    def flush(self, limit: int) -> bytes:
        """What is left once the network has sent everything, at most `limit` bytes."""
        if self._d is None:
            return b""
        try:
            out = self._d.decompress(self._d.unconsumed_tail, max(1, limit)) if self._d.unconsumed_tail else b""
            if limit - len(out) > 0:
                out += self._d.flush(limit - len(out))
            return out
        except zlib.error as exc:
            raise httpx.DecodingError(f"{self.kind}: {exc}") from None


def tls_verify(ca_bundle: str | None):
    """httpx `verify` value: default trust store, or an SSL context for a custom CA file."""
    return ssl.create_default_context(cafile=ca_bundle) if ca_bundle else True


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


@dataclass
class RawResponse:
    url: str
    status: int | None
    headers: dict[str, str]
    body: bytes
    truncated: bool
    elapsed_ms: float
    error: str | None
    started_at: str
    # Request sent -> response headers received, including connection setup when a new connection was opened.
    ttfb_ms: float | None = None
    # Each Set-Cookie header as the site sent it, one item per header (never comma-joined: a cookie's date has a
    # comma). Held in memory only, for IDX-3's one cookie re-walk (DECISIONS 217); never stored or written.
    set_cookies: list[str] = field(default_factory=list)
    # Bytes that came over the network for this answer (as sent, compressed if it was): beside `body` this tells a
    # "200 with 0 bytes" from a body that was lost in decoding (A10). None when the request failed.
    wire_bytes: int | None = None


class Fetcher:
    """Sequential, polite HTTP GETs with a single user agent and a request log.

    Redirects are never followed automatically: every hop is its own logged
    request so redirect chains, robots.txt checks, and INT-4 stay auditable.
    """

    def __init__(
        self,
        user_agent: str,
        timeout_s: float,
        delay_s: float,
        transport: httpx.BaseTransport | None = None,
        ca_bundle: str | None = None,
        block_loopback: bool = False,
    ) -> None:
        self.user_agent = user_agent
        self.delay_s = delay_s
        self.timeout_s = timeout_s
        self.deadline_mono: float | None = None
        # A stop request (maya_audit.progress) is honoured like the deadline: once seen, no further request
        # is sent, and every collector reports what it could not ask for as not checked.
        self.stop_check = None
        self.stopped = False
        # Every request refused for the time limit, from any thread; `own_deadline_hits` only the audit's own thread's,
        # which is what a step's collector is judged on (a worker of the other-site pool, DECISIONS 219, is not).
        self.deadline_hits = 0
        self.own_deadline_hits = 0
        self._hits_lock = threading.Lock()
        self.block_loopback = block_loopback
        # MockTransport is used only by deterministic unit tests. It never opens a socket.
        self._mock_transport = isinstance(transport, httpx.MockTransport)
        self.log: list[RequestRecord] = []
        # The renderer fetches a page's sub-resources from a few worker threads; the log stays ordered.
        self._log_lock = threading.Lock()
        self._last_request = 0.0
        # Per-host gaps (DECISIONS 219 part 2; `configure_pacing`). Off by default: one gap for every host, as before.
        self.per_host = False
        self.site_host: str | None = None
        self._last_by_host: dict[str, float] = {}
        self._gap_by_host: dict[str, float] = {}
        self._host_locks: dict[str, threading.Lock] = {}
        self._hosts_guard = threading.Lock()
        self._pace_lock = threading.Lock()
        # Adaptive pacing of the audited site (only with per-host gaps): see `_pace_after`.
        self.adaptive = False
        self.min_delay_s = 0.5
        self.crawl_delay_floor_s = 0.0
        self.pacing_clean_answers = 20
        self.pacing_factor = 0.75
        self.pacing_clean_ttfb_ms = 1500.0
        self.pacing_reset_ttfb_ms = 2000.0
        self._clean_in_a_row = 0
        self._site_requests = 0
        self._pace_base_s = delay_s
        self.narrowings: list[dict[str, float]] = []
        self.narrowing_stopped: dict | None = None
        # Seconds spent waiting (the gap between requests, Retry-After, the performance rounds' pauses, a robots.txt
        # sample not yet due): the "Of which waiting" of the step timing table (DECISIONS 219).
        self.waited_s = 0.0
        # The step timing table (`crawl.steps`): one row per step, {step, started_at, seconds, requests, waiting_s}.
        self.steps: list[dict] = []
        self._step: dict | None = None
        # Requests sent outside the other-site pool (a step's "Requests"); the pool has its own row.
        self.own_requests = 0
        self.pool_seqs: list[int] = []
        # Requests that must wait until a moment (ACC-1's robots.txt samples, DECISIONS 12 and 219): each is sent
        # before the next request of the audit's own thread once it has come due, never by an idle wait; what is
        # still not due when Maya's last step ends is waited for then (`finish_due`).
        self._due: list[dict] = []
        self._sending_due = False
        self._owner = threading.get_ident()
        # Marks the threads of the other-site pool (maya_audit.other_sites): their requests, waiting and refusals for
        # the time limit are the pool's own row of the step timing table, not the step running on the audit's thread.
        self._local = threading.local()
        # After the crawl, the audited site's requests share one limit with the page reader (maya_audit.sitelimit,
        # DECISIONS 294): set by run_audit, None before (the crawl itself is sequential, as always).
        self.site_limiter = None
        # Seconds above which an answer from the audited site counts as slow for the shared limit's back-off.
        self.slow_answer_s = 2.0
        self._client = httpx.Client(
            follow_redirects=False,
            timeout=timeout_s,
            headers={"User-Agent": user_agent, "Accept": ACCEPT},
            trust_env=False,
            transport=transport or PublicTransport(allow_loopback=not block_loopback, verify=tls_verify(ca_bundle),
                                                   before_connect=self.remaining_timeout),
            verify=tls_verify(ca_bundle),
        )
        # Every widening of the request gap, so INT-4 can report that Maya backed off and by how much.
        self.delay_widenings: list[dict[str, float]] = []
        self.base_delay_s = delay_s
        # Never store cookies: every request is a fresh, cookie-less client, as
        # the public bot info page promises (and as spec RND-5 assumes). The one exception is IDX-3's cookie re-walk
        # (DECISIONS 217): it sends a site's own cookie back by hand for that walk only (`get(cookie=...)`).
        self._client.cookies.jar.set_policy(DefaultCookiePolicy(allowed_domains=[]))

    def close(self) -> None:
        self._client.close()

    # -- per-host gaps and adaptive pacing (DECISIONS 219 part 2) -----------------------------------------------------

    def configure_pacing(self, cfg) -> None:
        """Turn on per-host gaps and the audited site's adaptive pacing, from a CrawlConfig with `adaptive_pacing`."""
        self.per_host = True
        self.adaptive = True
        self.min_delay_s = cfg.min_request_delay_s
        self.pacing_clean_answers = max(1, cfg.pacing_clean_answers)
        self.pacing_factor = cfg.pacing_factor
        self.pacing_clean_ttfb_ms = cfg.pacing_clean_ttfb_ms
        self.pacing_reset_ttfb_ms = cfg.pacing_reset_ttfb_ms
        self.slow_answer_s = cfg.pacing_reset_ttfb_ms / 1000

    @property
    def in_pool(self) -> bool:
        """Whether the calling thread is a worker of the other-site pool."""
        return bool(getattr(self._local, "pool", False))

    def mark_pool_thread(self) -> None:
        self._local.pool = True

    @property
    def thread_requests(self) -> int:
        """Requests the calling thread has sent (a pool worker's count of its robots.txt reads)."""
        return getattr(self._local, "sent", 0)

    def hit_deadline(self) -> None:
        """Count one request refused for the time limit (locked: the other-site pool counts from its threads)."""
        with self._hits_lock:
            self.deadline_hits += 1
            if not self.in_pool:
                self.own_deadline_hits += 1

    def set_host_gap(self, host: str, seconds: float) -> None:
        """The gap kept between requests to another site's `host` (the configured delay, or its Crawl-delay)."""
        with self._hosts_guard:
            self._gap_by_host[host.lower()] = max(0.0, seconds)

    def gap_for(self, host: str | None) -> float:
        """The gap kept before a request to `host`: the audited site's (adaptive) gap, or that host's own."""
        if not self.per_host or host is None or host == self.site_host:
            return self.delay_s
        with self._hosts_guard:
            return self._gap_by_host.get(host, self.base_delay_s)

    def _host_lock(self, host: str):
        with self._hosts_guard:
            return self._host_locks.setdefault(host, threading.Lock())

    @property
    def floor_s(self) -> float:
        """The smallest gap adaptive pacing may use on the audited site: the floor, never below a Crawl-delay."""
        return max(self.min_delay_s, self.crawl_delay_floor_s)

    def _pace_after(self, host: str | None, purpose: str, status: int | None, error: str | None,
                    ttfb_ms: float | None, empty: bool = False) -> None:
        """After an answer from the audited site: count it toward narrowing the gap, or put the gap back for good.

        `empty`: a 2xx that sent no page (IDX-1's empty response). It is neutral (A9): it neither counts toward
        narrowing nor stops it, it only starts the count of clean answers again. A server that answers fast because it
        sends nothing is no sign that it can take more requests."""
        if not self.adaptive or host is None or host != self.site_host or purpose in NOT_PACED_PURPOSES:
            return
        if error == "audit_deadline_skipped":
            return
        self._site_requests += 1
        bad = (status == 429 or (status is not None and status >= 500) or error is not None or status is None
               or (ttfb_ms is not None and ttfb_ms > self.pacing_reset_ttfb_ms))
        if bad:
            if self.narrowing_stopped is None:
                self.narrowing_stopped = {"after_requests": self._site_requests, "status": status, "error": error,
                                          "ttfb_ms": ttfb_ms}
                if self.narrowings:
                    self.delay_s = max(self.delay_s, self._pace_base_s)
            self._clean_in_a_row = 0
            return
        if self.narrowing_stopped is not None:
            return
        if empty:
            self._clean_in_a_row = 0
            return
        clean = (status is not None and (200 <= status < 400 or status in (404, 410))
                 and ttfb_ms is not None and ttfb_ms <= self.pacing_clean_ttfb_ms)
        if not clean:
            self._clean_in_a_row = 0
            return
        self._clean_in_a_row += 1
        if self._clean_in_a_row < self.pacing_clean_answers:
            return
        self._clean_in_a_row = 0
        floor = self.floor_s
        if self.delay_s <= floor:
            return
        if not self.narrowings:
            self._pace_base_s = self.delay_s  # what a reset goes back to: the configured gap (or a Crawl-delay)
        previous = self.delay_s
        self.delay_s = max(floor, round(self.delay_s * self.pacing_factor, 3))
        self.narrowings.append({"from_s": round(previous, 3), "to_s": round(self.delay_s, 3),
                                "after_requests": self._site_requests})

    def widen_delay(self, factor: float, ceiling: float) -> float | None:
        """Increase the gap between every later request. Returns the new delay, or None if capped.

        Only ever widens. INT-4 asserts the smallest observed gap is at least the configured delay,
        so a gap that only grows can never break that invariant — which is why backoff is safe to
        apply inside a politeness-audited crawl without weakening what the audit proves.
        """
        if self.delay_s >= ceiling:
            return None
        previous = self.delay_s
        self.delay_s = min(ceiling, self.delay_s * factor)
        self.delay_widenings.append({"from_s": round(previous, 3), "to_s": round(self.delay_s, 3)})
        return self.delay_s

    # -- the step timing table ---------------------------------------------------------------------------------------

    def begin_step(self, name: str) -> None:
        """Close the step running now and start `name`. Its row counts the requests and the waiting until the next."""
        now = time.monotonic()
        self.end_step(now)
        self._step = {"step": name, "started_at": utc_now(), "_t": now, "_requests": self.own_requests,
                      "_waited": self.waited_s}

    def end_step(self, now: float | None = None) -> None:
        step, self._step = self._step, None
        if step is None:
            return
        now = time.monotonic() if now is None else now
        self.steps.append({"step": step["step"], "started_at": step["started_at"], "seconds": round(max(0.0, now - step["_t"]), 1),
                           "requests": self.own_requests - step["_requests"],
                           "waiting_s": round(max(0.0, self.waited_s - step["_waited"]), 1)})

    # -- requests that wait for a moment ------------------------------------------------------------------------------

    def schedule(self, due_mono: float, send) -> None:
        """Send `send()` (which makes its own requests through this fetcher) once the monotonic time `due_mono` has
        come: before the next request of the audit's own thread, or at `finish_due`."""
        self._due.append({"due": due_mono, "send": send})
        self._due.sort(key=lambda item: item["due"])

    @property
    def due_waiting(self) -> int:
        return len(self._due)

    def _send(self, item: dict) -> None:
        self._sending_due = True
        try:
            item["send"]()
        finally:
            self._sending_due = False

    def send_due(self, purpose: str = "") -> None:
        """Send what has come due. Not from a rendering's own requests, from another thread or from inside a send."""
        if (not self._due or self._sending_due or purpose in ("render", "render_subresource")
                or threading.get_ident() != self._owner):
            return
        while self._due and self._due[0]["due"] <= time.monotonic():
            if self.deadline_mono is not None and time.monotonic() >= self.deadline_mono:
                return
            self._send(self._due.pop(0))

    def finish_due(self) -> bool:
        """At the end of Maya's own steps: wait for what is still not due, then send it. False when the time limit or a
        stop came first (what was left is then not sent)."""
        while self._due:
            wait = self._due[0]["due"] - time.monotonic()
            if wait > 0 and not self.sleep(wait):
                self._due.clear()
                return False
            if self.poll_stop() or (self.deadline_mono is not None and time.monotonic() >= self.deadline_mono):
                self._due.clear()
                return False
            self._send(self._due.pop(0))
        return True

    def wait_politely(self, host: str | None = None) -> None:
        """Wait out the gap before the next request: since the last request of all, or with per-host gaps since the
        last request to `host` (the audited site's when `host` is not given)."""
        if not self.per_host:
            wait = self._last_request + self.delay_s - time.monotonic()
        else:
            host = (host or self.site_host or "").lower() or None
            with self._hosts_guard:
                last = self._last_by_host.get(host) if host else None
            wait = (last + self.gap_for(host) - time.monotonic()) if last is not None else 0.0
        if wait > 0:
            self.sleep(wait)

    def poll_stop(self) -> bool:
        """Whether a stop was requested. The first time it is, the deadline moves to now."""
        if not self.stopped and self.stop_check is not None and self.stop_check():
            self.stopped = True
            self.deadline_mono = time.monotonic()
        return self.stopped

    def sleep(self, seconds: float) -> bool:
        """Sleep without crossing the audit-wide deadline; return False when time ran out."""
        self.poll_stop()
        remaining = (self.deadline_mono - time.monotonic()) if self.deadline_mono is not None else seconds
        if remaining <= 0:
            self.hit_deadline()
            return False
        began = time.monotonic()
        wake = began + min(max(seconds, 0.0), remaining)
        while (left := wake - time.monotonic()) > 0:
            time.sleep(min(left, 0.5) if self.stop_check is not None else left)  # in slices, to hear a stop request
            if self.poll_stop():
                break
        # A pool worker's waiting is not a step's "Of which waiting"; the other-site pool's row is measured from its
        # requests (maya_audit.other_sites).
        if not self.in_pool:
            self.waited_s += max(0.0, time.monotonic() - began)
        if self.deadline_mono is not None and time.monotonic() >= self.deadline_mono:
            self.hit_deadline()
            return False
        return True

    def record_external(self, url: str, purpose: str, started_at: str, status: int | None, error: str | None) -> None:
        """Log a request made outside httpx (e.g. by the headless browser) so INT-4 audits it."""
        now = time.monotonic()
        with self._log_lock:
            self.log.append(RequestRecord(seq=len(self.log) + 1, url=url, purpose=purpose, user_agent=self.user_agent,
                                          started_at=started_at, status=status, error=error, elapsed_ms=0.0,
                                          started_mono=now, ended_mono=now))
            self._last_request = now
            if not self.in_pool:
                self.own_requests += 1
            host = (urlsplit(url).hostname or "").lower()
            if host:
                with self._hosts_guard:
                    self._last_by_host[host] = now

    def remaining_timeout(self, timeout_s: float | None = None) -> float:
        self.poll_stop()
        remaining = self.deadline_mono - time.monotonic() if self.deadline_mono is not None else self.timeout_s
        if remaining <= 0:
            self.hit_deadline()
            raise httpx.TimeoutException("overall audit deadline reached")
        return min(timeout_s or self.timeout_s, remaining)

    def request_budget(self, url: str, timeout_s: float | None = None) -> float:
        """Shared preflight for collector requests outside the page request log."""
        self.remaining_timeout(timeout_s)
        if not self._mock_transport:
            validate_public_target(url, allow_loopback=not self.block_loopback)
        return self.remaining_timeout(timeout_s)

    def api_request(self, client: httpx.Client, method: str, url: str, **kwargs) -> httpx.Response:
        """Bound API response size and elapsed time; never follow API redirects."""
        budget = self.request_budget(url)
        end = time.monotonic() + budget
        with client.stream(method, url, timeout=budget, follow_redirects=False, **kwargs) as response:
            chunks, size = [], 0
            for chunk in response.iter_bytes():
                self.poll_stop()
                if self.stopped or time.monotonic() >= end:
                    self.hit_deadline()
                    raise httpx.TimeoutException("overall audit deadline reached")
                size += len(chunk)
                if size > 8 * 1024 * 1024:
                    raise ValueError("API response exceeds 8 MiB limit")
                chunks.append(chunk)
            return httpx.Response(response.status_code, headers={k: v for k, v in response.headers.items() if k not in ("content-encoding", "content-length")},
                                  content=b"".join(chunks), request=response.request)

    def get(
        self,
        url: str,
        purpose: str,
        max_bytes: int,
        user_agent: str | None = None,
        extra_headers: dict[str, str] | None = None,
        method: str = "GET",
        cookie: str | None = None,
    ) -> RawResponse:
        """One request, GET unless `method` says otherwise ("HEAD" for a link to another site, DECISIONS 211). The
        request log records the purpose, not the method: a purpose names the method when it is not GET.

        `cookie` is sent as the Cookie header (IDX-3's cookie re-walk, DECISIONS 217). Its value is never logged: the
        request log says only that the site's own cookie was sent back."""
        # A request that cannot start before the global deadline is not a network
        # attempt: do not manufacture a timeout row (INT-4 counts real attempts).
        self.poll_stop()
        if self.deadline_mono is not None and time.monotonic() >= self.deadline_mono:
            self.hit_deadline()
            return RawResponse(url, None, {}, b"", False, 0.0, "audit_deadline_skipped", utc_now(), None)
        paced = purpose != "render_subresource"
        host = (urlsplit(url).hostname or "").lower() or None
        if paced:
            self.send_due(purpose)
        limiter = self.site_limiter
        if paced and limiter is not None and host is not None and host == self.site_host:
            # The audited site after the crawl: one shared limit with the page reader (DECISIONS 294). The audit's own
            # thread always takes slot 0, so its requests keep the gap after its own last one; other threads (the
            # sitemap check's workers) take any free slot. Starts stay at least the gap apart.
            from .sitelimit import MAYA, bad_answer

            slot = limiter.acquire(MAYA, main=threading.get_ident() == self._owner and not self.in_pool,
                                   should_stop=self.poll_stop, deadline_mono=self.deadline_mono)
            if slot is None:
                self.hit_deadline()
                return RawResponse(url, None, {}, b"", False, 0.0, "audit_deadline_skipped", utc_now(), None)
            if not self.in_pool:
                self.waited_s += slot.waited_s
            try:
                response = self._request(url, purpose, max_bytes, user_agent, extra_headers, method, cookie, host, slot.index,
                                         slot.started_mono)
            finally:
                limiter.release(slot)
            reason = bad_answer(response.status, response.error,
                                None if response.ttfb_ms is None else response.ttfb_ms / 1000, self.slow_answer_s)
            if reason is not None:
                limiter.back_off(reason, "maya")
        else:
            # With per-host gaps, the wait and the request to one host hold that host's lock: two threads never ask one
            # host at once, and each keeps the gap after the other's request (DECISIONS 219 part 2).
            with (self._host_lock(host) if paced and self.per_host and host else nullcontext()):
                if paced:
                    self.wait_politely(host)
                response = self._request(url, purpose, max_bytes, user_agent, extra_headers, method, cookie, host)
        if paced:
            from .classify import empty_response
            # A HEAD answer never has a body, so it is never "empty" here.
            empty = method != "HEAD" and empty_response(response.status, response.headers.get("content-type"),
                                                       response.body, response.truncated)
            with self._pace_lock:  # the sitemap check's workers answer from several threads (DECISIONS 294)
                self._pace_after(host, purpose, response.status, response.error, response.ttfb_ms, empty)
        return response

    def _request(self, url: str, purpose: str, max_bytes: int, user_agent: str | None,
                 extra_headers: dict[str, str] | None, method: str, cookie: str | None, host: str | None,
                 slot: int | None = None, slot_started: float | None = None) -> RawResponse:
        started_at = utc_now()
        # A request through the shared site limit starts when the limit let it (the spacing the limit kept is the spacing
        # the log shows, whatever the threads did in between).
        start = time.monotonic() if slot_started is None else slot_started
        status: int | None = None
        headers: dict[str, str] = {}
        chunks: list[bytes] = []
        truncated = False
        error: str | None = None
        ttfb_ms: float | None = None
        set_cookies: list[str] = []
        wire_bytes: int | None = None
        try:
            if self.deadline_mono is not None and time.monotonic() >= self.deadline_mono:
                self.hit_deadline()
                return RawResponse(url, None, {}, b"", False, 0.0, "audit_deadline_skipped", started_at, None)
            if not self._mock_transport:
                validate_public_target(url, allow_loopback=not self.block_loopback)
            headers_out = {"Accept-Encoding": ACCEPT_ENCODING, **dict(extra_headers or {})}
            if user_agent:
                headers_out["User-Agent"] = user_agent
            if cookie:
                headers_out["Cookie"] = cookie
            remaining = (self.deadline_mono - time.monotonic()) if self.deadline_mono is not None else self.timeout_s
            if remaining <= 0:
                self.hit_deadline()
                return RawResponse(url, None, {}, b"", False, 0.0, "audit_deadline_skipped", started_at, None)
            request_timeout = httpx.Timeout(min(self.timeout_s, remaining))
            with self._client.stream(method, url, headers=headers_out or None,
                                     timeout=request_timeout) as response:
                status = response.status_code
                ttfb_ms = round((time.monotonic() - start) * 1000, 1)
                for key, value in response.headers.multi_items():
                    key = key.lower()
                    headers[key] = f"{headers[key]}, {value}" if key in headers else value
                    if key == "set-cookie":
                        set_cookies.append(value)
                total = 0
                # Decoded here with a bound on each step's output (A6); an encoding Maya did not offer falls back to
                # httpx's decoding of whole network chunks, as before.
                decoder = _BoundedDecoder.for_encoding(response.headers.get("content-encoding"))
                if response.is_stream_consumed:  # an answer already held in memory (a test transport): decoded already
                    decoder = None
                pieces = response.iter_raw() if decoder is not None else response.iter_bytes()
                for piece in pieces:
                    self.poll_stop()
                    if self.stopped or (self.deadline_mono is not None and time.monotonic() >= self.deadline_mono):
                        self.hit_deadline()
                        raise httpx.ReadTimeout("overall audit deadline reached")
                    if time.monotonic() - start > self.timeout_s:
                        raise httpx.ReadTimeout("total response deadline exceeded")
                    chunk = decoder.decode(piece, max_bytes - total + 1) if decoder is not None else piece
                    total += len(chunk)
                    if total > max_bytes:
                        chunks.append(chunk[: max_bytes - (total - len(chunk))])
                        truncated = True
                        break
                    chunks.append(chunk)
                else:
                    if decoder is not None:
                        tail = decoder.flush(max_bytes - total + 1)
                        total += len(tail)
                        if total > max_bytes:
                            tail, truncated = tail[: max_bytes - (total - len(tail))], True
                        chunks.append(tail)
                wire_bytes = response.num_bytes_downloaded
        except BeforeConnectDeadline:
            return RawResponse(url, None, {}, b"", False, 0.0, "audit_deadline_skipped", started_at, None)
        except httpx.TimeoutException as exc:
            error = f"timeout ({type(exc).__name__})"
        except LocalDnsError as exc:
            error = f"local_dns_failure ({exc})"  # this computer's network; says nothing about the site
        except HostNotFoundError as exc:
            error = f"host_not_found ({exc})"
        except UnresolvedHostError as exc:
            error = f"unresolved_host ({exc})"
        except UnsafeTargetError as exc:
            error = f"unsafe_target ({exc})"
        except (httpx.InvalidURL, UnicodeError) as exc:
            # Not an HTTPError: a URL httpx cannot send (control character, bad IDN). One bad link, not a dead crawl.
            # After UnsafeTargetError, a ValueError subclass; idna.IDNAError is a UnicodeError.
            error = f"invalid_url ({type(exc).__name__})"
        except httpx.ConnectError as exc:
            error = f"connect_error ({exc})"
        except (httpx.RemoteProtocolError, httpx.ReadError) as exc:
            error = f"connection_dropped ({type(exc).__name__})"
        except httpx.HTTPError as exc:
            error = f"http_error ({type(exc).__name__}: {exc})"

        if error is not None:
            status, headers, chunks, ttfb_ms, set_cookies, wire_bytes = None, {}, [], None, [], None

        ended = time.monotonic()
        elapsed_ms = round((ended - start) * 1000, 1)
        with self._log_lock:
            self._last_request = ended
            if host:
                with self._hosts_guard:
                    self._last_by_host[host] = ended
            if not self.in_pool:
                self.own_requests += 1
            else:
                self.pool_seqs.append(len(self.log) + 1)
            self._local.sent = getattr(self._local, "sent", 0) + 1
            self.log.append(
                RequestRecord(
                    seq=len(self.log) + 1,
                    url=url,
                    purpose=purpose,
                    user_agent=user_agent or self.user_agent,
                    started_at=started_at,
                    status=status,
                    error=error,
                    elapsed_ms=elapsed_ms,
                    # The cookie's value is not kept, only that one was sent (DECISIONS 217).
                    extra_headers={**dict(extra_headers or {}), **({"Cookie": COOKIE_NOT_KEPT} if cookie else {})},
                    ttfb_ms=ttfb_ms,
                    started_mono=start,
                    ended_mono=ended,
                    slot=slot,
                )
            )
        return RawResponse(url, status, headers, b"".join(chunks), truncated, elapsed_ms, error, started_at, ttfb_ms,
                           set_cookies, wire_bytes)


def gaps_by_host(records) -> tuple[dict[str, list[float]], str]:
    """The gaps, in ms, between one request to a host and the next request to that same host (DECISIONS 219 part 2),
    and the clock they were measured on. Resource requests inside one rendering are left out (a burst by nature).
    Requests to different hosts may overlap (the other-site pool); politeness is a matter between Maya and one host."""
    by_host: dict[str, list] = {}
    for record in records:
        if record.purpose == "render_subresource":
            continue
        by_host.setdefault((urlsplit(record.url).hostname or "").lower(), []).append(record)
    clock = "monotonic"
    out: dict[str, list[float]] = {}
    for host, rows in by_host.items():
        if all(r.started_mono is not None and r.ended_mono is not None for r in rows):
            rows = sorted(rows, key=lambda r: (r.started_mono, r.seq))
            # Each slot of the shared site limit (DECISIONS 294) is one sequence: the gap from the end of its last request
            # to its next start. A request with no slot (the crawl, another host) is slot 0, the audit's own thread.
            gaps: list[float] = []
            by_slot: dict[int, list] = {}
            for record in rows:
                by_slot.setdefault(getattr(record, "slot", None) or 0, []).append(record)
            for sequence in by_slot.values():
                gaps += [max(0.0, (b.started_mono - a.ended_mono) * 1000) for a, b in zip(sequence, sequence[1:])]
            if len(by_slot) > 1:
                # Requests overlapped: their starts are also at least the gap apart, whoever sent them.
                gaps += [max(0.0, (b.started_mono - a.started_mono) * 1000) for a, b in zip(rows, rows[1:])]
            out[host] = gaps
            continue
        clock = "wall clock (monotonic stamps missing)"  # a report from before monotonic stamps existed
        gaps = []
        for a, b in zip(rows, rows[1:]):
            end = datetime.fromisoformat(a.started_at).timestamp() + a.elapsed_ms / 1000
            gaps.append(max(0.0, (datetime.fromisoformat(b.started_at).timestamp() - end) * 1000))
        out[host] = gaps
    return out, clock
