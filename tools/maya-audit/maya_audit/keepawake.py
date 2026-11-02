"""Keep the computer awake while an audit runs (DECISIONS 295; Owner, 2026-11-02).

A Mac that goes to sleep in the middle of an audit stops it: requests in flight time out, and the audit's own clock
(which stops while the computer sleeps) no longer matches the time on the wall. On macOS, while an audit runs,
`caffeinate -i -w <this process>` keeps the system from idle sleep; it ends when the audit ends, and by itself if this
process dies. The display may still turn off, and closing the lid still sleeps the Mac: that is the owner's choice.

Elsewhere nothing is started. `MAYA_AUDIT_KEEP_AWAKE=off` switches it off (the test suite does).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from typing import Any, Callable

VAR = "MAYA_AUDIT_KEEP_AWAKE"
_NO = {"0", "off", "false", "no"}
# Tests replace this to see what would be started. Nothing else should.
LAUNCH: Callable[..., Any] = subprocess.Popen


def wanted(environ=None) -> bool:
    environ = os.environ if environ is None else environ
    return sys.platform == "darwin" and (environ.get(VAR) or "on").strip().lower() not in _NO


class KeepAwake:
    """`with KeepAwake():` around an audit. Never fails the audit: if caffeinate cannot start, the audit runs as before."""

    def __init__(self, environ=None) -> None:
        self.environ = environ
        self.process = None
        self.reason: str | None = None

    def __enter__(self) -> "KeepAwake":
        if not wanted(self.environ):
            self.reason = "not macOS, or switched off"
            return self
        tool = shutil.which("caffeinate") or "/usr/bin/caffeinate"
        try:
            self.process = LAUNCH([tool, "-i", "-w", str(os.getpid())], stdin=subprocess.DEVNULL,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (OSError, ValueError) as exc:
            self.reason = f"caffeinate could not start ({type(exc).__name__})"
        return self

    def __exit__(self, *exc_info) -> None:
        process, self.process = self.process, None
        if process is None:
            return
        try:
            process.terminate()
            process.wait(timeout=5)
        except Exception:  # an ended process, or one that will end with this one (-w): nothing to do
            pass

    @property
    def active(self) -> bool:
        return self.process is not None
