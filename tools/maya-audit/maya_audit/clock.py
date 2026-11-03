"""One clock for every wait of an audit (DECISIONS 299).

The polite gap between Maya's requests, a Retry-After, the site limit's gap, Firecrawl's own pace and back-off, the
timeout retry, scheduled requests and every deadline read the time and sleep through this module: `monotonic()` and
`sleep()` ask the clock in use, which is the system's unless a test put a `FakeClock` in place (`using`). A fake clock
moves when something sleeps and nothing waits, so a test of a paced audit takes the time of its work, not of its waits.

The headless browser (maya_audit.render) keeps the system clock: it waits for a real browser's events.
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from typing import Iterator


class SystemClock:
    """The time module, looked up at each call (a test that patches `time.monotonic` still moves it)."""

    def monotonic(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(max(0.0, seconds))


class FakeClock:
    """A clock that moves only when something sleeps: the sleep returns at once. Locked, since the site limit's and the
    reader's threads move it too. It starts at the system's monotonic time, so a deadline set before it was put in place
    still means something."""

    def __init__(self, start: float | None = None) -> None:
        self.now = time.monotonic() if start is None else float(start)
        self.slept = 0.0
        self.sleeps = 0
        self._lock = threading.Lock()

    def monotonic(self) -> float:
        with self._lock:
            return self.now

    def sleep(self, seconds: float) -> None:
        self.advance(seconds)
        time.sleep(0)  # let another thread run, as a real sleep would

    def advance(self, seconds: float) -> None:
        with self._lock:
            step = max(0.0, float(seconds))
            self.now += step
            self.slept += step
            self.sleeps += 1


_current: SystemClock | FakeClock = SystemClock()


def current() -> SystemClock | FakeClock:
    return _current


def monotonic() -> float:
    return _current.monotonic()


def sleep(seconds: float) -> None:
    _current.sleep(seconds)


@contextmanager
def using(clock: SystemClock | FakeClock) -> Iterator[SystemClock | FakeClock]:
    """Put `clock` in place for the block (process-wide: for tests, never while the web app runs audits)."""
    global _current
    before, _current = _current, clock
    try:
        yield clock
    finally:
        _current = before
