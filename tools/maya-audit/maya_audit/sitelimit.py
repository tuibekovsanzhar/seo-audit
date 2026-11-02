"""One limit on requests to the audited site, shared by Maya's own requests and the page reader (DECISIONS 294).

After Maya's crawl, the page reader (Firecrawl) reads pages while Maya runs its own later steps. Both reach the same
site, so both go through one `SiteLimiter`:

- at most `limit` requests are in flight at once (default 5, from 1 to 10);
- request starts are spaced by the polite gap (the crawler's current delay: the configured one, a Crawl-delay, or the
  narrower or wider gap adaptive pacing set), counting Maya's and the reader's starts together, so the site never sees
  a higher request rate than one crawler alone (docs/BOT.md: "about one request a second");
- each slot also keeps the gap between the end of its own last request and its next start, so slot 0 (Maya's own
  thread) is exactly the sequential crawler it was;
- while Maya's own steps run, the reader never uses slot 0, and a request of Maya's that waits goes before the
  reader's: Maya's own steps are never held up behind a full limit of reader requests.

On a 429, a 5xx, a failed connection or a slow answer the limit steps down to 2, then to 1, and stays there; each step
is recorded. Nothing here sends a request: callers ask for a slot, send, and give it back.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable

DEFAULT_LIMIT = 5
MIN_LIMIT, MAX_LIMIT = 1, 10
# The steps a limit backs off through: from whatever it is to 2, then to 1.
LADDER = (2, 1)
MAYA, READER = "maya", "reader"


def backed_off(current: int) -> int | None:
    """The next, lower limit on the ladder, or None when it is already at the bottom."""
    for step in LADDER:
        if step < current:
            return step
    return None


def clamp(value) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return DEFAULT_LIMIT
    return max(MIN_LIMIT, min(MAX_LIMIT, number))


@dataclass
class Slot:
    index: int
    who: str
    waited_s: float
    started_mono: float


@dataclass
class SiteLimiter:
    limit: int = DEFAULT_LIMIT
    gap: Callable[[], float] = lambda: 0.0
    # None: `time.monotonic()` and `time.sleep()` looked up at each call, so a test's fake clock (which patches the time
    # module) moves this limit the same as the fetcher.
    clock: Callable[[], float] | None = None
    # Whether Maya's own steps are still running: slot 0 is then Maya's alone.
    maya_active: bool = True
    configured: int = field(init=False)
    max_in_flight: int = field(init=False, default=0)
    starts: int = field(init=False, default=0)
    steps: list[dict] = field(init=False, default_factory=list)
    # Starts by who asked, for the report.
    by_who: dict[str, int] = field(init=False, default_factory=dict)

    def __post_init__(self) -> None:
        self.limit = clamp(self.limit)
        self.configured = self.limit
        self._cond = threading.Condition()
        self._busy: set[int] = set()
        self._last_end: dict[int, float] = {}
        self._last_start: float | None = None
        self._maya_waiting = 0
        # When Maya's own thread waits for slot 0: the moment it may start. A reader may start before it only when that
        # leaves Maya's start where it was (the reader's start plus the gap is not later than it).
        self._main_ready: float | None = None

    # -- asking for a slot ----------------------------------------------------------------------------------------------

    def _now(self) -> float:
        return self.clock() if self.clock is not None else time.monotonic()

    def _candidates(self, who: str, main: bool) -> list[int]:
        if main:
            return [0] if 0 not in self._busy else []
        slots = [i for i in range(self.limit) if i not in self._busy]
        if who == READER and self.maya_active:
            slots = [i for i in slots if i != 0]
        return slots

    def _ready_at(self, index: int, gap: float) -> float:
        ready = 0.0
        if self._last_start is not None:
            ready = self._last_start + gap
        end = self._last_end.get(index)
        if end is not None:
            ready = max(ready, end + gap)
        return ready

    def acquire(self, who: str = MAYA, *, main: bool = False, should_stop: Callable[[], bool] | None = None,
                deadline_mono: float | None = None, sleep_step: float = 0.25) -> Slot | None:
        """Wait for a slot and the polite gap; None when `should_stop()` turned true or the deadline came first.

        `main` is Maya's own thread: it always takes slot 0, so its requests keep the gap after its own last one."""
        began = self._now()
        with self._cond:
            # Maya's requests that compete with the reader for the shared slots (the sitemap check's workers) go first.
            # Maya's own thread has slot 0 to itself, so it only asks that the reader does not push its start later.
            competing = who == MAYA and not main
            if competing:
                self._maya_waiting += 1
            try:
                while True:
                    if should_stop is not None and should_stop():
                        return None
                    now = self._now()
                    if deadline_mono is not None and now >= deadline_mono:
                        return None
                    slots = self._candidates(who, main)
                    gap = max(0.0, float(self.gap() or 0.0))
                    # A reader waits while a request of Maya's is waiting for a shared slot (Maya's own steps go first),
                    # and while starting now would move the start of Maya's own waiting request later.
                    if who == READER and (self._maya_waiting or (self._main_ready is not None and now + gap > self._main_ready + 1e-9)):
                        slots = []
                    if slots:
                        index = min(slots, key=lambda i: (self._ready_at(i, gap), i))
                        ready = self._ready_at(index, gap)
                        if main:
                            self._main_ready = ready
                        if ready <= now:
                            if main:
                                self._main_ready = None
                            self._busy.add(index)
                            self._last_start = now
                            self.starts += 1
                            self.by_who[who] = self.by_who.get(who, 0) + 1
                            self.max_in_flight = max(self.max_in_flight, len(self._busy))
                            return Slot(index, who, round(max(0.0, now - began), 3), now)
                        # Waiting for the gap: a sleep (the time module's, which a fake clock moves), without the lock.
                        wait = min(ready - now, sleep_step)
                        if deadline_mono is not None:
                            wait = min(wait, max(0.0, deadline_mono - now))
                        self._cond.release()
                        try:
                            time.sleep(max(0.001, wait))
                        finally:
                            self._cond.acquire()
                        continue
                    # Waiting for a free slot: until another request gives one back.
                    self._cond.wait(sleep_step)
            finally:
                if competing:
                    self._maya_waiting -= 1
                if main:
                    self._main_ready = None
                if competing or main:
                    self._cond.notify_all()

    def seed(self, started_mono: float | None, ended_mono: float | None) -> None:
        """The last request to the site before this limit existed (the crawl's), sent from the audit's own thread: the
        first request through the limit keeps the gap after it too."""
        with self._cond:
            if started_mono is not None:
                self._last_start = started_mono
            if ended_mono is not None:
                self._last_end[0] = ended_mono

    def release(self, slot: Slot | None) -> None:
        if slot is None:
            return
        with self._cond:
            self._busy.discard(slot.index)
            self._last_end[slot.index] = self._now()
            self._cond.notify_all()

    # -- backing off ----------------------------------------------------------------------------------------------------

    def back_off(self, reason: str, who: str, after: int | None = None) -> int | None:
        """Step the limit down (to 2, then 1) and record why. None when it is already 1."""
        with self._cond:
            lower = backed_off(self.limit)
            if lower is None:
                return None
            self.steps.append({"from": self.limit, "to": lower, "reason": reason, "seen_by": who,
                               "after_starts": self.starts if after is None else after})
            self.limit = lower
            self._cond.notify_all()
            return lower

    def maya_done(self) -> None:
        """Maya's own steps have ended: the reader may use every slot."""
        with self._cond:
            self.maya_active = False
            self._cond.notify_all()

    @property
    def in_flight(self) -> int:
        with self._cond:
            return len(self._busy)

    def summary(self) -> dict:
        """What the report keeps: the limit asked for, the limit at the end, every step down, the most in flight at once
        (Maya's and the reader's requests together) and how many requests each started."""
        return {"configured": self.configured, "final": self.limit, "backed_off": list(self.steps),
                "max_in_flight": self.max_in_flight, "starts": dict(self.by_who),
                "rule": "at most this many requests to the audited site at once, Maya's and the page reader's together; "
                        "request starts at least the polite gap apart"}


def bad_answer(status: int | None, error: str | None, seconds: float | None, slow_s: float) -> str | None:
    """Why an answer should make the limit back off ("429", "5xx", "no answer", "slow"), or None when it is fine."""
    if error == "audit_deadline_skipped":
        return None
    if status == 429:
        return "429"
    if status is not None and status >= 500:
        return "5xx"
    if error is not None or status is None:
        return "no answer"
    if seconds is not None and seconds > slow_s:
        return "slow"
    return None
