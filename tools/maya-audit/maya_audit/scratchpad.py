"""The crawl frontier, on disk, so a crawl can be resumed and can outgrow memory.

The pattern is OpenSEO's audit scratchpad (MIT, Ben Senescu, 2026), which keeps one SQLite
database per audit holding the URL queue and the seen-set. Their reasons were specific to
Cloudflare — Workflow step-output limits, Durable Object billing, chatty writes kept off Postgres.
Maya has none of those. What carries over is the shape: a frontier table keyed by URL, claimed one
row at a time, with status transitions that survive the process.

**Resumption is not free, and this module is where the cost is paid.** Maya's integrity gates
assert things that are only true of one continuous run: robots.txt was fetched before any other
request, every request used one user agent, the smallest gap was at least the configured delay.
A crawl assembled from several sessions can still say all of that — but per session, and only if
each session is recorded. So this holds a `sessions` table alongside the frontier, and the gates
read it. A resumed crawl that could not say which session a page came from would be a crawl whose
INT-4 evidence is a half-truth.

Two pieces of state must survive a resume or the resumed crawl is ruder than the one before it:

* the **robots.txt** the earlier session obeyed, hashed, so a changed policy is noticed rather
  than silently inherited;
* the **backoff delay** the earlier session ended on, so a site that rate-limited us yesterday is
  not met at full speed today.

Ordering is built for a crawl that stops at a page cap, so that the pages it does fetch stand for
the site: a redirect target first (the start URL's redirect leads to the real homepage), then the
start URL and key pages, then pages linked from the site's navigation, then everything else. Within
the last two groups a URL from a part of the site not fetched yet goes before another page of a part
already sampled (`section_key`), links go before sitemap-only URLs, and discovery order breaks ties.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import zlib
from dataclasses import dataclass
from typing import Any, Iterable

from .fetcher import utc_now
from .urls import is_pagination, section_key

MEMORY = ":memory:"

# Frontier states. "queued" is the only one `get_next_url` will claim.
QUEUED, CRAWLED, BLOCKED, RATE_LIMITED, FAILED, SKIPPED = (
    "queued", "crawled", "blocked", "rate_limited", "failed", "skipped")
TERMINAL = frozenset({CRAWLED, BLOCKED, RATE_LIMITED, FAILED, SKIPPED})

# Lower sorts first. A redirect target is followed before anything already waiting. Links found in a
# page's navigation (`FrontierUrl.nav`) rank between key pages and ordinary links. From ordinary links
# down, the section a URL belongs to is weighed before this number (see `get_next_url`).
# "rendered_link": a link that exists only in the rendered view of a page (maya_audit.render_discovery).
# "alternate" (live gap 3): a hreflang alternate or the canonical target the homepage or a key page names in its <head>.
# It ranks with key pages (strict order, after them by sequence), above navigation links: the site's other language
# versions are what a capped crawl must not miss. A URL already queued keeps the route it was found by ("sitemap" stays
# "sitemap", so IDX-7 and INT-2 still read it as sitemap-found); only its place in the queue moves up.
PRIORITY = {"redirect": 0, "start": 1, "key_page": 1, "alternate": 1, "link": 3, "rendered_link": 3, "sitemap": 4}
NAV_PRIORITY = 2
# Page 2, 3, ... of a list is fetched only when nothing else is waiting: it is page 1's template again, and three
# of ten slots went to `?sayfa=2..4` on a live run.
PAGINATION_PRIORITY = 5

SCHEMA = """
CREATE TABLE IF NOT EXISTS frontier (
    url         TEXT PRIMARY KEY,
    status      TEXT NOT NULL DEFAULT 'queued',
    depth       INTEGER,
    parent_url  TEXT,
    via         TEXT NOT NULL,
    priority    INTEGER NOT NULL,
    seq         INTEGER NOT NULL,
    session_no  INTEGER,
    updated_at  TEXT,
    section     TEXT,
    page_key    TEXT,
    locale      TEXT,
    boost       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS frontier_next_idx ON frontier (status, priority, seq);

CREATE TABLE IF NOT EXISTS sessions (
    session_no        INTEGER PRIMARY KEY,
    started_at        TEXT NOT NULL,
    finished_at       TEXT,
    user_agent        TEXT,
    robots_sha256     TEXT,
    requests          INTEGER,
    min_gap_ms        REAL,
    configured_delay_s REAL,
    final_delay_s     REAL,
    stop_reason       TEXT,
    stop_detail       TEXT
);

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);

-- Every fetched page as the crawler recorded it (compressed JSON), so a resumed crawl reports on all its
-- sessions' pages, not only the last session's. `skipped` holds the robots.txt decisions the same way.
CREATE TABLE IF NOT EXISTS pages (
    url         TEXT PRIMARY KEY,
    n           INTEGER NOT NULL,
    session_no  INTEGER NOT NULL,
    record      BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS skipped (url TEXT PRIMARY KEY, n INTEGER NOT NULL, record TEXT NOT NULL);

-- How many URLs of each section have been fetched, so the next pick can prefer a section not sampled yet.
CREATE TABLE IF NOT EXISTS section_fetches (section TEXT PRIMARY KEY, n INTEGER NOT NULL);

-- DECISIONS 316: how many versions of each page (its address without the locale folder) have been fetched, so a
-- capped crawl reads one version of a page before a second, and a third only when nothing else is waiting.
CREATE TABLE IF NOT EXISTS page_copies (page_key TEXT PRIMARY KEY, n INTEGER NOT NULL);
"""


@dataclass(frozen=True)
class FrontierUrl:
    url: str
    depth: int | None
    via: str
    parent_url: str | None
    nav: bool = False  # found in a page's navigation (<nav>, <header>, role="navigation")


def robots_fingerprint(body: str | bytes | None) -> str | None:
    """A hash of the robots.txt a session obeyed, so a later session can notice it changed."""
    if body is None:
        return None
    raw = body.encode("utf-8", "replace") if isinstance(body, str) else body
    return hashlib.sha256(raw).hexdigest()


class Scratchpad:
    """One crawl's frontier. Defaults to an in-memory database, which is the old behaviour."""

    @classmethod
    def read_only(cls, path: str) -> "Scratchpad":
        """Open an existing frontier to look at it, without starting a session.

        Inspecting a frontier used to insert a session row, so merely reading one inflated INT-2's
        "assembled from N sessions" and put an empty row in INT-4's per-session table. Found on the
        first live resume test, where a read between two crawls produced a phantom third session.
        """
        return cls(path, resume=True, _open_session=False)

    def __init__(self, path: str = MEMORY, resume: bool = False, _open_session: bool = True, binding: dict | None = None) -> None:
        if resume and binding is not None:
            from pathlib import Path
            if path == MEMORY or not Path(path).is_file():
                raise ValueError("Resume needs an existing crawl database; start a new audit instead.")
        self.path = path
        self.resumed = False
        # isolation_level=None: transactions are opened explicitly, so a claim is one atomic
        # BEGIN IMMEDIATE .. COMMIT rather than whatever the driver decides to wrap.
        self._db = sqlite3.connect(path, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL" if path != MEMORY else "PRAGMA journal_mode=MEMORY")
        self._db.execute("PRAGMA synchronous=NORMAL")
        if self._db.execute("SELECT 1 FROM sqlite_master WHERE name = 'frontier'").fetchone():
            columns = {row["name"] for row in self._db.execute("PRAGMA table_info(frontier)")}
            for name, kind in (("section", "TEXT"), ("page_key", "TEXT"), ("locale", "TEXT"),
                               ("boost", "INTEGER NOT NULL DEFAULT 0")):
                if name not in columns:  # a frontier from before sections (or before DECISIONS 316)
                    self._db.execute(f"ALTER TABLE frontier ADD COLUMN {name} {kind}")
        self._db.executescript(SCHEMA)
        existing = self._db.execute("SELECT COUNT(*) AS n FROM sessions").fetchone()["n"]
        if existing and not resume:
            raise ValueError(
                f"{path} already holds a crawl of {existing} session(s). Pass --resume to continue it, "
                f"or point --db-path somewhere else. Refusing to overwrite a frontier silently.")
        self.resumed = bool(existing) and resume
        if binding is not None:
            try:
                self.bind(binding)
            except ValueError:
                self._db.close()
                raise
        self.session_no = existing + 1 if _open_session else existing
        if _open_session:
            self._db.execute("INSERT INTO sessions (session_no, started_at) VALUES (?, ?)",
                             (self.session_no, utc_now()))
        self._seq = self._db.execute("SELECT COALESCE(MAX(seq), 0) AS s FROM frontier").fetchone()["s"]
        # DECISIONS 316: the site's locale folders, its main version and the business type's key page types.
        saved = self.get_meta("locales") or {}
        self.locale_folders: frozenset[str] = frozenset(saved.get("folders") or [])
        self.main_locale: str | None = saved.get("main")
        self._boost = None

    def set_locales(self, folders, main: str | None, boost=None) -> None:
        """The site's locale folders (`locales.detect`), its main version ("" for the root) and a test for the business
        type's key page types; set before the URLs are queued. URLs already waiting are keyed again."""
        self.locale_folders = frozenset(folders or ())
        self.main_locale = main
        self._boost = boost
        self.set_meta("locales", {"folders": sorted(self.locale_folders), "main": main})
        rows = [(*self._keys(r["url"]), r["url"]) for r in self._db.execute("SELECT url FROM frontier WHERE status = ?", (QUEUED,))]
        if rows:
            with self._transaction():
                self._db.executemany("UPDATE frontier SET section = ?, page_key = ?, locale = ?, boost = ? WHERE url = ?", rows)

    def set_main_locale(self, main: str | None) -> None:
        """The version the homepage landed on: its pages go first among copies of the same page."""
        if main != self.main_locale:
            self.main_locale = main
            self.set_meta("locales", {"folders": sorted(self.locale_folders), "main": main})

    def _keys(self, url: str) -> tuple[str, str, str, int]:
        """(section, page key, locale folder, boost) of one URL."""
        from .locales import locale_of, page_key, section_url
        folders = self.locale_folders
        from .locales import HOME_KEY
        key = page_key(url, folders)
        boost = 1 if key == HOME_KEY else 0  # the homepage is a key page of every business type
        if self._boost is not None and not boost:
            try:
                boost = 1 if self._boost(url) else 0
            except Exception:  # noqa: BLE001  a hint only
                boost = 0
        return (section_key(section_url(url, folders)) if folders else section_key(url),
                key, locale_of(url, folders), boost)

    def bind(self, binding: dict) -> None:
        """Refuse mixed-target/settings evidence before creating a resume session."""
        binding = json.loads(json.dumps(binding, sort_keys=True))
        saved = self.get_meta("resume_binding")
        if self.resumed and saved is None:
            raise ValueError("This older crawl has no target/settings binding; start a new audit.")
        if saved is not None and saved != binding:
            raise ValueError("Resume target or audit settings differ from the saved crawl; start a new audit.")
        if saved is None:
            self.set_meta("resume_binding", binding)

    # -- frontier ------------------------------------------------------------

    def add_urls(self, urls: Iterable[FrontierUrl]) -> int:
        """Queue URLs not already known. Returns how many were new or moved up.

        The URL primary key *is* the seen-set: a URL already crawled, failed or skipped keeps the row
        it has, so re-adding a URL can never resurrect one already visited. A URL still waiting moves
        up when it is found again by a stronger route (a sitemap URL that a page links to, a link that
        turns out to be in the navigation), and jumps the queue when it is a redirect target: the
        start URL's redirect leads to the real homepage, which a sitemap has usually listed already.
        """
        rows = []
        for item in urls:
            self._seq += 1
            seq = -self._seq if item.via == "redirect" else self._seq
            priority = NAV_PRIORITY if item.nav and item.via in ("link", "rendered_link") else PRIORITY.get(item.via, 1)
            if item.via in ("link", "rendered_link", "sitemap") and is_pagination(item.url):
                priority = PAGINATION_PRIORITY
            rows.append((item.url, QUEUED, item.depth, item.parent_url, item.via, priority, seq, utc_now(),
                         *self._keys(item.url)))
        if not rows:
            return 0
        with self._transaction():
            before = self._db.total_changes
            self._db.executemany(
                "INSERT INTO frontier (url, status, depth, parent_url, via, priority, seq, updated_at, section, page_key, "
                "locale, boost) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(url) DO UPDATE SET depth=excluded.depth, parent_url=excluded.parent_url, "
                "via=CASE WHEN excluded.via='alternate' THEN frontier.via ELSE excluded.via END, "
                "priority=excluded.priority, updated_at=excluded.updated_at, "
                "seq=CASE WHEN excluded.via='redirect' THEN excluded.seq ELSE frontier.seq END "
                "WHERE frontier.status=? AND excluded.priority < frontier.priority",
                [(*row, QUEUED) for row in rows])
            return self._db.total_changes - before

    def get_next_url(self) -> FrontierUrl | None:
        """Claim the next queued URL atomically, or None when the frontier is empty.

        The claim marks the row with this session number so an interrupted crawl leaves evidence of
        what it was working on. Status stays `queued` until the fetch resolves: a process killed
        mid-fetch leaves the URL claimable again rather than silently lost.
        """
        with self._transaction():
            # Redirect targets, the start URL and key pages go strictly in priority order. After them come
            # navigation links, then the rest; inside each of those two groups a section with fewer pages
            # fetched so far goes first, so a capped crawl samples the site instead of one long list.
            # DECISIONS 316: a page already read in COPIES versions (other country/language folders) waits until
            # nothing else does (the start URL, key pages and redirect targets excepted); among the rest a page not read
            # in any version goes before a second version; within a section round the business type's key page types
            # and then the main version go first.
            from .locales import COPIES, HOME_COPIES, HOME_KEY
            row = self._db.execute(
                "SELECT f.url, f.depth, f.via, f.parent_url, f.priority FROM frontier f "
                "LEFT JOIN section_fetches s ON s.section = f.section "
                "LEFT JOIN page_copies c ON c.page_key = f.page_key WHERE f.status = ? "
                "ORDER BY f.priority >= ?, "
                "CASE WHEN f.via IN ('start', 'key_page', 'redirect') THEN 0 "
                "WHEN COALESCE(c.n, 0) >= (CASE WHEN f.page_key = ? THEN ? ELSE ? END) THEN 1 ELSE 0 END, "
                "MIN(f.priority, ?), CASE WHEN f.priority < ? OR f.page_key IS ? THEN 0 ELSE MIN(COALESCE(c.n, 0), 1) END, "
                "CASE WHEN f.priority < ? THEN 0 ELSE COALESCE(s.n, 0) END, "
                "CASE WHEN f.priority < ? THEN 0 ELSE 1 - COALESCE(f.boost, 0) END, "
                "CASE WHEN f.locale IS ? THEN 0 ELSE 1 END, f.priority, f.seq LIMIT 1",
                (QUEUED, PAGINATION_PRIORITY, HOME_KEY if self.locale_folders else None, HOME_COPIES, COPIES, PRIORITY["link"],
                 NAV_PRIORITY, HOME_KEY if self.locale_folders else None, NAV_PRIORITY, NAV_PRIORITY,
                 self.main_locale if self.locale_folders else None)).fetchone()
            if row is None:
                return None
            self._db.execute("UPDATE frontier SET session_no = ?, updated_at = ? WHERE url = ?",
                             (self.session_no, utc_now(), row["url"]))
            return FrontierUrl(row["url"], row["depth"], row["via"], row["parent_url"], row["priority"] == NAV_PRIORITY)

    def mark_status(self, url: str, status: str) -> None:
        if status not in TERMINAL and status != QUEUED:
            raise ValueError(f"unknown frontier status {status!r}")
        with self._transaction():
            before = self._db.execute("SELECT status, section, page_key FROM frontier WHERE url = ?", (url,)).fetchone()
            self._db.execute("UPDATE frontier SET status = ?, session_no = ?, updated_at = ? WHERE url = ?",
                             (status, self.session_no, utc_now(), url))
            # A URL that was actually requested counts towards its section; one skipped for robots.txt does not.
            if before is not None and before["status"] == QUEUED and status not in (QUEUED, SKIPPED):
                self._db.execute("INSERT INTO section_fetches (section, n) VALUES (?, 1) "
                                 "ON CONFLICT(section) DO UPDATE SET n = n + 1", (before["section"] or "",))
                if before["page_key"] is not None:
                    self._db.execute("INSERT INTO page_copies (page_key, n) VALUES (?, 1) "
                                     "ON CONFLICT(page_key) DO UPDATE SET n = n + 1", (before["page_key"],))

    def counts(self) -> dict[str, int]:
        return {r["status"]: r["n"] for r in
                self._db.execute("SELECT status, COUNT(*) AS n FROM frontier GROUP BY status")}

    def urls_with_status(self, status: str) -> list[str]:
        return [r["url"] for r in self._db.execute(
            "SELECT url FROM frontier WHERE status = ? ORDER BY priority, seq", (status,))]

    def all_urls(self) -> list[str]:
        return [r["url"] for r in self._db.execute("SELECT url FROM frontier ORDER BY url")]

    def known(self, url: str) -> bool:
        return self._db.execute("SELECT 1 FROM frontier WHERE url = ?", (url,)).fetchone() is not None

    # -- page records ---------------------------------------------------------

    @property
    def on_disk(self) -> bool:
        return self.path != MEMORY

    def save_page(self, record: dict[str, Any]) -> None:
        """Keep one fetched page (a JSON-ready dict, working data included). On disk only: a crawl held in
        memory cannot be resumed, so it has no use for a second copy of every page."""
        if not self.on_disk:
            return
        blob = zlib.compress(json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), 3)
        with self._transaction():
            n = self._db.execute("SELECT COALESCE(MAX(n), 0) + 1 AS n FROM pages").fetchone()["n"]
            self._db.execute("INSERT OR REPLACE INTO pages (url, n, session_no, record) VALUES (?, ?, ?, ?)",
                             (record["url"], n, self.session_no, blob))

    def saved_pages(self, before_session: int | None = None) -> list[dict[str, Any]]:
        """Page records in the order they were fetched; with `before_session`, only earlier sessions' pages."""
        rows = self._db.execute("SELECT record FROM pages WHERE session_no < ? ORDER BY n",
                                (before_session if before_session is not None else self.session_no + 1,))
        return [json.loads(zlib.decompress(row["record"]).decode("utf-8")) for row in rows]

    def saved_page_count(self) -> int:
        return self._db.execute("SELECT COUNT(*) AS n FROM pages").fetchone()["n"]

    def save_skipped(self, record: dict[str, Any]) -> None:
        if not self.on_disk:
            return
        with self._transaction():
            n = self._db.execute("SELECT COALESCE(MAX(n), 0) + 1 AS n FROM skipped").fetchone()["n"]
            self._db.execute("INSERT OR REPLACE INTO skipped (url, n, record) VALUES (?, ?, ?)",
                             (record["url"], n, json.dumps(record, ensure_ascii=False)))

    def saved_skipped(self) -> list[dict[str, Any]]:
        return [json.loads(row["record"]) for row in self._db.execute("SELECT record FROM skipped ORDER BY n")]

    def requeue_unsaved(self) -> list[str]:
        """Queue again every URL marked as fetched that has no page record, and return them.

        A process killed between a fetch and the write of its record leaves such a URL. Left alone, the
        resumed report would be missing a page it claims to have crawled."""
        if not self.on_disk:
            return []
        lost = [row["url"] for row in self._db.execute(
            "SELECT url FROM frontier WHERE status IN (?, ?, ?, ?) AND url NOT IN (SELECT url FROM pages)",
            (CRAWLED, BLOCKED, RATE_LIMITED, FAILED))]
        with self._transaction():
            self._db.executemany("UPDATE frontier SET status = ? WHERE url = ?", [(QUEUED, url) for url in lost])
        return lost

    # -- state that must survive a resume ------------------------------------

    def set_meta(self, key: str, value: Any) -> None:
        with self._transaction():
            self._db.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                             (key, json.dumps(value)))

    def get_meta(self, key: str, default: Any = None) -> Any:
        row = self._db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return default if row is None else json.loads(row["value"])

    def finish_session(self, **fields: Any) -> None:
        allowed = ("user_agent", "robots_sha256", "requests", "min_gap_ms", "configured_delay_s",
                   "final_delay_s", "stop_reason", "stop_detail")
        unknown = set(fields) - set(allowed)
        if unknown:
            raise ValueError(f"unknown session field(s): {', '.join(sorted(unknown))}")
        sets = ", ".join(f"{k} = ?" for k in fields)
        with self._transaction():
            self._db.execute(
                f"UPDATE sessions SET finished_at = ?{', ' + sets if sets else ''} WHERE session_no = ?",
                (utc_now(), *fields.values(), self.session_no))

    def sessions(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self._db.execute("SELECT * FROM sessions ORDER BY session_no")]

    def robots_changed_since_last_session(self, fingerprint: str | None) -> str | None:
        """The previous session's robots hash, when it differs from this one's. Else None.

        A resumed crawl inherits a queue built under the earlier robots.txt. If the file has changed,
        URLs queued then may now be disallowed, so INT-4 says so rather than letting the audit imply
        one policy governed the whole crawl.
        """
        if fingerprint is None:
            return None
        row = self._db.execute(
            "SELECT robots_sha256 FROM sessions WHERE session_no < ? AND robots_sha256 IS NOT NULL "
            "ORDER BY session_no DESC LIMIT 1", (self.session_no,)).fetchone()
        previous = row["robots_sha256"] if row else None
        return previous if previous and previous != fingerprint else None

    # -- plumbing ------------------------------------------------------------

    def _transaction(self):
        return _Transaction(self._db)

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> "Scratchpad":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


class _Transaction:
    """BEGIN IMMEDIATE .. COMMIT, so a claim cannot interleave with another writer."""

    def __init__(self, db: sqlite3.Connection) -> None:
        self._db = db

    def __enter__(self) -> sqlite3.Connection:
        self._db.execute("BEGIN IMMEDIATE")
        return self._db

    def __exit__(self, exc_type: Any, *_: Any) -> None:
        self._db.execute("ROLLBACK" if exc_type else "COMMIT")
