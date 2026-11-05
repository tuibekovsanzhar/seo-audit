"""One version per running app (DECISIONS 314).

The page's script and stylesheet are read once, when the app starts, and served from memory with that start's version
token, so a page always comes with the text table, headline builder and engine of the process that serves it. Before,
the script was read from disk on every request while the Python side stayed as it was at start: after an update
without a restart the new script asked the old process for text keys it did not have, and the page showed raw keys
("result.business.chip"), the old headline and an old engine commit.

`code_fingerprint` hashes the code and text files on disk; the page compares it with the one the process started with
and says "restart" when they differ (`/api/v1/version`).
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
ROOT = PACKAGE.parent
STATIC = PACKAGE / "static"
SERVED = ("app.js", "app.css")  # the files the page loads from /static
CHECK_EVERY_S = 20.0  # the code on disk is hashed again at most this often


def code_fingerprint(roots: tuple[Path, ...] = (ROOT / "maya_audit", PACKAGE)) -> str:
    """A hash of every code and text file the app runs on (Python, JSON, the page's files)."""
    h = hashlib.sha256()
    for root in roots:
        for path in sorted(p for p in root.rglob("*") if p.is_file() and p.suffix in (".py", ".json", ".js", ".css", ".html")
                           and "__pycache__" not in p.parts):
            h.update(path.relative_to(ROOT).as_posix().encode())
            h.update(path.read_bytes())
    return h.hexdigest()[:16]


@dataclass
class Snapshot:
    """The page's files and the code fingerprint as they were when this process started."""
    files: dict[str, bytes]
    index: bytes
    code: str
    build: str
    started_at: float = field(default_factory=time.time)
    _disk: tuple[float, str] | None = None

    @classmethod
    def take(cls, static: Path = STATIC) -> "Snapshot":
        files = {name: (static / name).read_bytes() for name in SERVED}
        code = code_fingerprint()
        build = hashlib.sha256(code.encode() + b"".join(files[n] for n in SERVED)).hexdigest()[:12]
        index = (static / "index.html").read_bytes()
        for name in SERVED:
            index = index.replace(f'"/static/{name}"'.encode(), f'"/static/{name}?v={build}"'.encode())
        return cls(files=files, index=index, code=code, build=build)

    def on_disk(self) -> str:
        now = time.monotonic()
        if self._disk is None or now - self._disk[0] >= CHECK_EVERY_S:
            self._disk = (now, code_fingerprint())
        return self._disk[1]

    def status(self) -> dict:
        disk = self.on_disk()
        return {"build": self.build, "code": self.code, "code_on_disk": disk, "restart_needed": disk != self.code}
