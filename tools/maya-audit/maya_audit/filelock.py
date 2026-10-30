"""One exclusive lock on an open file, on macOS and Linux (fcntl) and on Windows (msvcrt) (DECISIONS 231).

Which one is chosen when a lock is taken, not when this module is imported: fcntl where Python has it, msvcrt
where it does not (Windows). On Windows the first byte of the file is locked, whatever the file holds (Windows
lets a byte past the end of a file be locked), so every caller locks the same region.

Used for the three locks that keep two processes apart: the web app's worker (one worker per data folder), the
DataForSEO ledger (one paid call is reserved at a time) and the per-site crawl lock. Nothing else.
"""

from __future__ import annotations

import importlib
from typing import IO


def _fcntl():
    """The fcntl module, or None where Python has none (Windows)."""
    try:
        return importlib.import_module("fcntl")
    except ImportError:
        return None


def lock(f: IO, blocking: bool) -> None:
    """Take an exclusive lock on `f`. Blocking: wait until it is free. Not blocking: raise OSError when another
    process holds it."""
    fcntl = _fcntl()
    if fcntl is not None:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        return
    import msvcrt

    f.seek(0)
    if not blocking:
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        return
    while True:
        try:
            # LK_LOCK itself tries for about ten seconds, once a second, and then gives up with an OSError: it is
            # asked again until the lock is had, as fcntl's blocking lock waits.
            msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
            return
        except OSError:
            continue


def unlock(f: IO) -> None:
    """Release the lock `lock` took on `f`."""
    fcntl = _fcntl()
    if fcntl is not None:
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        return
    import msvcrt

    f.seek(0)
    msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
