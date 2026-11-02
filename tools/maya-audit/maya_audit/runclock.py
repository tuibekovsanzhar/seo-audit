"""One clock for a whole audit: the crawl, rendering, a page reader, paid data panels, archives and the report.

`run_audit` stops its own work at the audit's time limit. Everything that runs after it (Firecrawl, DataForSEO, the
archives, Core Web Vitals) used to carry on regardless, with timeouts of its own. A `RunClock` is the same deadline
and the same stop request, handed to each of them:

- nothing new is started, reserved or sent once the deadline has passed or a stop was asked for;
- a request that is sent may wait no longer than the time that is left;
- requests that reach the audited site through a reader keep the pace Maya's own crawler kept (the configured
  delay, a robots.txt Crawl-delay, and any widening after a rate limit).

A request already on its way cannot be recalled: it ends by its own timeout, and if no answer was read it is
recorded as possibly billed, exactly as before. Writing the report is not bounded by the clock: it makes no
request and must always be able to save what was learned.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

# A request with less than this left would almost certainly be cut off after it was sent (and possibly billed).
MIN_REQUEST_S = 5.0
STOPPED = "the audit was stopped on request"
OUT_OF_TIME = "the audit's time limit was reached"


@dataclass
class RunClock:
    deadline_mono: float | None = None
    should_stop: Callable[[], bool] | None = None
    # Seconds between requests that reach the audited site, as Maya's own crawler ended up pacing them.
    pace_s: float = 0.0
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep
    started_mono: float = field(default_factory=time.monotonic)
    _last_site_request: float | None = None
    # The audited site's one limit, shared with Maya's own later steps (maya_audit.sitelimit, DECISIONS 294). With it, a
    # reader's request takes a slot (`take_turn`) and gives it back (`give_back`); the pace is the limit's.
    site_limiter: object | None = None
    # What one request needs to be worth starting: MIN_REQUEST_S until the reader has measured its own calls, then
    # what it measured (DECISIONS 294).
    needs_s: float = MIN_REQUEST_S

    def remaining(self) -> float | None:
        return None if self.deadline_mono is None else self.deadline_mono - self.clock()

    def why_not(self, needs_s: float = 0.0) -> str | None:
        """Why no new request may start now, or None when one may. Checked before anything is reserved or sent."""
        if self.should_stop is not None and self.should_stop():
            return STOPPED
        left = self.remaining()
        if left is not None and left <= needs_s:
            return OUT_OF_TIME
        return None

    def timeout(self, most_s: float) -> float:
        """How long one request may take: its own limit, or the time left when that is less."""
        left = self.remaining()
        return most_s if left is None else max(0.0, min(most_s, left))

    def wait_for_turn(self) -> str | None:
        """Wait until the audited site may be asked again; returns why not to ask at all, if a stop or the deadline
        arrived while waiting. The wait is taken in short steps so a stop is noticed."""
        if self._last_site_request is not None and self.pace_s > 0:
            until = self._last_site_request + self.pace_s
            while self.clock() < until:
                blocked = self.why_not()
                if blocked:
                    return blocked
                self.sleep(min(0.5, max(0.0, until - self.clock())))
        return self.why_not(self.needs_s if self.deadline_mono is not None else 0.0)

    def site_was_asked(self) -> None:
        self._last_site_request = self.clock()

    def take_turn(self):
        """(slot, None) when a request may be sent now, or (None, why not). Without a site limit, the old single pace:
        the slot is None and the wait is `wait_for_turn`'s."""
        limiter = self.site_limiter
        if limiter is None:
            return None, self.wait_for_turn()
        from .sitelimit import READER

        needs = self.needs_s if self.deadline_mono is not None else 0.0
        slot = limiter.acquire(READER, should_stop=self.should_stop,
                               deadline_mono=None if self.deadline_mono is None else self.deadline_mono - needs)
        if slot is None:
            return None, self.why_not(needs) or OUT_OF_TIME
        why = self.why_not(needs)
        if why:
            limiter.release(slot)
            return None, why
        return slot, None

    def give_back(self, slot) -> None:
        if slot is not None and self.site_limiter is not None:
            self.site_limiter.release(slot)

    def elapsed_s(self) -> float:
        return round(self.clock() - self.started_mono, 3)


# What one page through a reader is assumed to take, beside the pace: an assumption, not a measurement. The coverage
# benchmark (scripts/coverage_benchmark.py) shows what it buys against fast and slow readers. Change it for one
# computer with MAYA_AUDIT_READER_SECONDS_PER_PAGE, or for one audit with --reader-seconds-per-page.
READER_SECONDS_PER_PAGE = 8.0
READER_SECONDS_VAR = "MAYA_AUDIT_READER_SECONDS_PER_PAGE"


def reader_seconds_per_page(environ=None) -> float:
    import os

    raw = (os.environ if environ is None else environ).get(READER_SECONDS_VAR)
    try:
        value = float(raw) if raw else READER_SECONDS_PER_PAGE
    except ValueError:
        return READER_SECONDS_PER_PAGE
    return value if 1.0 <= value <= 120.0 else READER_SECONDS_PER_PAGE


def reader_allowance_s(pages: int, delay_s: float, per_page_s: float | None = None, at_once: int = 1) -> float:
    """Time set aside, up front, for a page reader to read the audit's pages. It is added to the audit's time limit and
    kept for the reader: Maya's own crawl cannot use it up.

    One request at a time: per page, the pace plus an assumed answer time. With `at_once` requests in flight (DECISIONS
    294): per page, the assumed answer time shared by the requests in flight, never less than the pace (starts stay the
    gap apart). The assumed time is only the plan: while reading, the reader measures its own calls and uses those."""
    per_page = reader_seconds_per_page() if per_page_s is None else per_page_s
    if at_once <= 1:
        return round(max(0, pages) * (max(0.0, delay_s) + per_page), 1)
    return round(max(0, pages) * max(max(0.0, delay_s), per_page / at_once), 1)


def for_outcome(outcome, should_stop: Callable[[], bool] | None = None) -> RunClock:
    """The clock for the steps that follow `run_audit`: its deadline, its pace, and when it started."""
    clock = RunClock(deadline_mono=getattr(outcome, "deadline_mono", None), should_stop=should_stop,
                     pace_s=float(getattr(outcome, "pace_s", 0.0) or 0.0),
                     # The audit's one limit on the site (DECISIONS 294): a reader after the audit uses it too.
                     site_limiter=getattr(outcome, "site_limiter", None))
    if getattr(outcome, "started_mono", None) is not None:
        clock.started_mono = outcome.started_mono
    return clock


NO_LIMIT = RunClock()
