"""Firecrawl's own pace on the audited site (DECISIONS 295; Owner, 2026-11-02).

Maya's crawler asks the site from this computer, so it keeps its polite gap (maya_audit.sitelimit). Firecrawl's requests
reach the site from Firecrawl's network, so they keep a pace of their own:

- at most `limit` requests in flight at once (the reader's concurrency setting, 1 to 10, default 5);
- request starts at least `gap_s` apart (the reader's gap setting, default 1 s; a robots.txt Crawl-delay is a floor and
  then one request at a time);
- backing off only on what Firecrawl reports for this site: its own 429 or 5xx, the site's 429 or 5xx seen through it,
  and a call that timed out. Each step lowers the limit (5 -> 2 -> 1) and doubles the gap, to at most four times the
  setting. Each step is recorded.

Nothing here sends a request: the reader's client takes a turn, sends, and gives it back. The clock and sleep are the
run clock's, so a test's fake clock moves this pace too.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable

from ..sitelimit import backed_off
from .. import clock as _clock

# The gap grows to at most this many times the setting.
MOST_WIDENING = 4.0


@dataclass
class Turn:
    index: int
    started_mono: float


@dataclass
class ReaderPace:
    limit: int
    gap_s: float
    now: Callable[[], float] = _clock.monotonic
    sleep: Callable[[float], None] = _clock.sleep
    # A robots.txt Crawl-delay, when the site set one: the gap never goes below it.
    crawl_delay_s: float = 0.0
    configured: int = field(init=False)
    configured_gap_s: float = field(init=False)
    max_in_flight: int = field(init=False, default=0)
    starts: int = field(init=False, default=0)
    steps: list[dict] = field(init=False, default_factory=list)

    def __post_init__(self) -> None:
        self.limit = max(1, int(self.limit))
        self.gap_s = max(0.0, float(self.gap_s))
        if self.crawl_delay_s > 0:
            self.limit, self.gap_s = 1, max(self.gap_s, float(self.crawl_delay_s))
        self.configured, self.configured_gap_s = self.limit, self.gap_s
        self._cond = threading.Condition()
        self._in_flight = 0
        self._last_start: float | None = None

    def acquire(self, *, should_stop: Callable[[], bool] | None = None, deadline_mono: float | None = None,
                step_s: float = 0.25) -> Turn | None:
        """Wait for a free place and the gap; None when `should_stop()` turned true or the deadline came first."""
        with self._cond:
            while True:
                if should_stop is not None and should_stop():
                    return None
                now = self.now()
                if deadline_mono is not None and now >= deadline_mono:
                    return None
                if self._in_flight >= self.limit:
                    self._cond.wait(step_s)  # until a request in flight gives its place back
                    continue
                ready = 0.0 if self._last_start is None else self._last_start + self.gap_s
                if ready <= now:
                    self._in_flight += 1
                    self._last_start = now
                    self.starts += 1
                    self.max_in_flight = max(self.max_in_flight, self._in_flight)
                    return Turn(self.starts, now)
                wait = min(ready - now, step_s)
                if deadline_mono is not None:
                    wait = min(wait, max(0.0, deadline_mono - now))
                self._cond.release()
                try:
                    self.sleep(max(0.001, wait))
                finally:
                    self._cond.acquire()

    def release(self, turn: Turn | None) -> None:
        if turn is None:
            return
        with self._cond:
            self._in_flight = max(0, self._in_flight - 1)
            self._cond.notify_all()

    def back_off(self, reason: str, after_answers: int | None = None) -> dict | None:
        """Fewer requests at once and a longer gap, recorded with why. None when both are already at their bottom."""
        with self._cond:
            lower = backed_off(self.limit) or self.limit
            wider = round(min(self.configured_gap_s * MOST_WIDENING, max(self.gap_s * 2, self.gap_s + 0.5)), 3) \
                if self.configured_gap_s > 0 else self.gap_s
            if lower == self.limit and wider <= self.gap_s:
                return None
            step = {"from": self.limit, "to": lower, "gap_from_s": self.gap_s, "gap_to_s": max(wider, self.gap_s),
                    "reason": reason, "after_answers": after_answers}
            self.steps.append(step)
            self.limit, self.gap_s = lower, max(wider, self.gap_s)
            self._cond.notify_all()
            return step

    def summary(self) -> dict:
        return {"configured": self.configured, "final": self.limit, "gap_s": self.configured_gap_s,
                "gap_final_s": self.gap_s, "crawl_delay_s": self.crawl_delay_s or None, "starts": self.starts,
                "max_in_flight": self.max_in_flight}
