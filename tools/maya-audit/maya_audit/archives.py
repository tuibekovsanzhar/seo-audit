"""Opt-in, bounded reads of existing public copies. Never request the audited host.

No browser, resources, Save Page Now, live fallback, or protection bypass. These
copies have their own checks; live crawl findings and access evidence stay intact.
"""
from __future__ import annotations

import gzip
import io
import json
import re
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Callable
from urllib.parse import urlsplit

import httpx

from .fetcher import utc_now
from .findings import check_id_key
from .models import StopReason, to_jsonable
from .urls import normalize_url

NAMES = {"wayback": "Wayback Machine", "common_crawl": "Common Crawl"}
NOTICE = "archived/indexed copy, date {date}; the live site may differ"
MAX_BODY = 2 * 1024 * 1024
MAX_WARC = 4 * 1024 * 1024
MAX_TOTAL = 20 * 1024 * 1024
MAX_PAGES = 50
# These questions can be answered from HTML alone. Excludes freshness and remote
# validation, including hreflang targets, image headers and sameAs destinations.
CHECKS = {"IDX-8", "TSEO-1", *(f"STR-{n}" for n in (1, 2, 3, 8, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 22, 23))}


class ArchiveError(ValueError):
    pass


class ArchiveStop(ArchiveError):
    """No further requests this run (rate limit, service failure, stop or budget)."""


@dataclass(frozen=True)
class Copy:
    url: str
    html: str
    date: str
    archive_url: str
    source: str


def capture_date(timestamp: str) -> str:
    if not re.fullmatch(r"\d{14}", timestamp):
        raise ArchiveError("Invalid capture timestamp")
    return datetime.strptime(timestamp, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc).isoformat()


def scoped(url: str, target: str) -> bool:
    try:
        p, t = urlsplit(url), urlsplit(target)
        return (p.scheme in ("http", "https") and not p.username and not p.password
                and p.port in (None, 80, 443) and bool(p.hostname)
                and p.hostname.removeprefix("www.") == (t.hostname or "").removeprefix("www."))
    except ValueError:
        return False


class Client:
    def __init__(self, user_agent: str, *, transport=None, should_stop: Callable[[], bool] = lambda: False,
                 sleep=time.sleep, clock=time.monotonic):
        self.http = httpx.Client(transport=transport, timeout=20, follow_redirects=False, trust_env=False,
                                 headers={"User-Agent": user_agent, "Accept-Encoding": "identity"})
        self.should_stop, self.sleep, self.clock = should_stop, sleep, clock
        self.last = None
        self.bytes = 0
        self.requests = 0
        self.deadline = clock() + 180

    def close(self):
        self.http.close()

    def get(self, url, *, params=None, headers=None, limit=MAX_BODY, partial=False):
        # Endpoint allowlist; never trust a replay redirect or CDX-supplied host.
        p = urlsplit(url)
        if p.scheme != "https" or p.netloc not in {"archive.org", "web.archive.org", "index.commoncrawl.org", "data.commoncrawl.org"}:
            raise ArchiveError("Archive endpoint is not allowed")
        if self.should_stop() or self.clock() >= self.deadline or self.bytes >= MAX_TOTAL:
            raise ArchiveStop("Archive collection stopped or reached its time/download limit")
        if self.last is not None:
            self.sleep(max(0, 1.0 - (self.clock() - self.last)))
        if self.should_stop():
            raise ArchiveStop("Archive collection stopped")
        self.last = self.clock()
        self.requests += 1
        try:
            with self.http.stream("GET", url, params=params, headers=headers) as r:
                if r.status_code == 429 or r.status_code >= 500:
                    raise ArchiveStop(f"Archive returned HTTP {r.status_code}; back off and retry later. "
                                      f"Retry-After: {r.headers.get('retry-after', 'not supplied')}")
                if r.status_code != (206 if partial else 200):
                    raise ArchiveError(f"Archive returned HTTP {r.status_code}; no redirect or live fallback followed")
                chunks, size = [], 0
                for chunk in r.iter_bytes(chunk_size=16384):
                    size += len(chunk)
                    self.bytes += len(chunk)
                    if size > limit or self.bytes > MAX_TOTAL or self.should_stop() or self.clock() >= self.deadline:
                        raise ArchiveStop("Archive response exceeded the download/time limit or collection was stopped")
                    chunks.append(chunk)
                return b"".join(chunks), dict(r.headers)
        except httpx.HTTPError as exc:
            raise ArchiveStop(f"Archive request failed ({type(exc).__name__}); retry later") from None

    def json(self, url, **kwargs):
        raw, _ = self.get(url, **kwargs)
        try:
            return json.loads(raw)
        except (ValueError, UnicodeError):
            raise ArchiveError("Archive returned invalid JSON") from None

    def wayback(self, target: str, seeds: list[str], cap: int, errors: list[str]) -> list[Copy]:
        candidates = list(dict.fromkeys([target, *seeds]))[:cap]
        # Bounded URL discovery, then Availability chooses the newest capture per
        # exact URL. CDX collapse alone would select the oldest capture, not latest.
        try:
            rows = self.json("https://web.archive.org/cdx/search/cdx", params={
                "url": target, "matchType": "host", "output": "json", "fl": "original",
                "filter": ["statuscode:200", "mimetype:text/html"], "collapse": "urlkey", "limit": cap * 4})
            for row in rows[1:]:
                if isinstance(row, list) and row and scoped(str(row[0]), target) and row[0] not in candidates:
                    candidates.append(row[0])
        except ArchiveStop:
            raise
        except (ArchiveError, TypeError, KeyError) as exc:
            errors.append(str(exc))  # known URLs can still have captures
        copies = []
        for url in candidates[:cap]:
            if not scoped(url, target):
                continue
            try:
                data = self.json("https://archive.org/wayback/available", params={"url": url})
                snap = data.get("archived_snapshots", {}).get("closest", {})
                if not snap.get("available") or str(snap.get("status")) != "200":
                    errors.append(f"No available capture: {url}")
                    continue
                stamp = str(snap.get("timestamp", ""))
                date = capture_date(stamp)
                replay = str(snap.get("url", ""))
                match = re.fullmatch(r"https?://web\.archive\.org/web/" + stamp + r"/(https?://.+)", replay)
                if not match or not scoped(match[1], target):
                    raise ArchiveError("Invalid or out-of-scope Wayback capture")
                original = match[1]
                if any(c.url == original for c in copies):
                    continue
                replay = f"https://web.archive.org/web/{stamp}id_/{original}"
                raw, headers = self.get(replay)
                if "html" not in headers.get("content-type", "").lower():
                    raise ArchiveError("Wayback capture is not HTML")
                copies.append(Copy(original, raw.decode("utf-8", "replace"), date, replay, "wayback"))
            except ArchiveStop as exc:
                errors.append(str(exc))
                break
            except (ArchiveError, TypeError, AttributeError, ValueError) as exc:
                errors.append(f"{url}: {exc}")
        return copies

    def common_crawl(self, target: str, seeds: list[str], cap: int, errors: list[str]) -> list[Copy]:
        collections = self.json("https://index.commoncrawl.org/collinfo.json")
        if not isinstance(collections, list):
            raise ArchiveError("Invalid Common Crawl collection list")
        # Search the newest collection only; disclose the limit. Exact lookups
        # choose latest per URL within that collection, not a random domain row.
        ids = sorted({row.get("id", "") for row in collections if isinstance(row, dict)
                      and re.fullmatch(r"CC-MAIN-\d{4}-\d{2}", row.get("id", ""))}, reverse=True)
        if not ids:
            raise ArchiveError("No Common Crawl index is available")
        endpoint = f"https://index.commoncrawl.org/{ids[0]}-index"
        errors.append(f"Coverage: newest Common Crawl collection only ({ids[0]}); older collections were not searched.")
        candidates = list(dict.fromkeys([target, *seeds]))[:cap]
        raw, _ = self.get(endpoint, params={"url": urlsplit(target).hostname, "matchType": "domain",
                       "output": "json", "filter": ["=status:200", "=mime:text/html"], "limit": cap * 4})
        for line in raw.splitlines():
            row = json.loads(line)
            url = row.get("url", "")
            if scoped(url, target) and url not in candidates:
                candidates.append(url)
        copies = []
        for url in candidates[:cap]:
            if not scoped(url, target):
                continue
            try:
                raw, _ = self.get(endpoint, params={"url": url, "matchType": "exact", "output": "json",
                              "filter": ["=status:200", "=mime:text/html"], "sort": "reverse", "limit": 1})
                if not raw.strip():
                    errors.append(f"No indexed capture: {url}")
                    continue
                row = json.loads(raw.splitlines()[0])
                if not scoped(row.get("url", ""), target) or normalize_url(row["url"]) != normalize_url(url):
                    raise ArchiveError("Common Crawl returned a different URL")
                date = capture_date(str(row.get("timestamp", "")))
                filename = str(row.get("filename", ""))
                if not re.fullmatch(r"crawl-data/CC-MAIN-\d{4}-\d{2}/[A-Za-z0-9_./-]+\.warc\.gz", filename) or ".." in filename:
                    raise ArchiveError("Invalid WARC path")
                offset, length = int(row["offset"]), int(row["length"])
                if offset < 0 or not 0 < length <= MAX_BODY:
                    raise ArchiveError("WARC record exceeds the small-download limit")
                location = "https://data.commoncrawl.org/" + filename
                raw, headers = self.get(location, headers={"Range": f"bytes={offset}-{offset + length - 1}"}, limit=length, partial=True)
                if len(raw) != length or not headers.get("content-range", "").startswith(f"bytes {offset}-{offset + length - 1}/"):
                    raise ArchiveError("WARC byte range does not match the requested record")
                html = warc_html(raw, row["url"], date)
                copies.append(Copy(row["url"], html, date, location + f"#bytes={offset}-{offset + length - 1}", "common_crawl"))
            except ArchiveStop as exc:
                errors.append(str(exc))
                break
            except (ArchiveError, ValueError, KeyError, TypeError, OSError) as exc:
                errors.append(f"{url}: {exc}")
        return copies


def warc_html(raw: bytes, url: str, date: str) -> str:
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as fh:
        record = fh.read(MAX_WARC + 1)
    if len(record) > MAX_WARC:
        raise ArchiveError("Decompressed WARC record is too large")
    head, sep, payload = record.partition(b"\r\n\r\n")
    if not sep or not head.startswith(b"WARC/1."):
        raise ArchiveError("Invalid WARC record")
    fields = {k.lower(): v.strip() for line in head.decode("utf-8", "replace").splitlines()[1:]
              for k, _, v in [line.partition(":")]}
    if fields.get("warc-type") != "response" or fields.get("warc-target-uri") != url:
        raise ArchiveError("WARC record does not contain the indexed response")
    if fields.get("warc-date", "").replace("Z", "+00:00") != date:
        raise ArchiveError("WARC capture date does not match its index")
    http, sep, body = payload.partition(b"\r\n\r\n")
    lines = http.decode("latin1").splitlines()
    fields = {k.lower(): v.strip() for line in lines[1:] for k, _, v in [line.partition(":")]}
    if not sep or not re.match(r"HTTP/\S+ 200\b", lines[0]) or "html" not in fields.get("content-type", ""):
        raise ArchiveError("Archived response is not successful HTML")
    if fields.get("content-encoding", "identity") != "identity" or fields.get("transfer-encoding"):
        raise ArchiveError("Encoded archived HTTP body is unsupported; no partial content was checked")
    charset = re.search(r"charset=[\"']?([\w-]+)", fields.get("content-type", ""))
    try:
        return body.decode(charset[1] if charset else "utf-8", "replace")
    except LookupError:
        raise ArchiveError("Unsupported archived HTML charset") from None


def analyze(copies, result, cfg):
    """Reuse engine checks on an isolated historical view, never replace live checks."""
    from types import SimpleNamespace
    from .firecrawl.reader import _page_from
    from .checks.structure import run_structure_checks
    from .checks.index import idx8_duplicates
    from .coverage import settle_all
    pages, kept = [], []
    for c in copies:
        fetched = SimpleNamespace(html=c.html, status=200, fetched_at=c.date, content_type="text/html")
        page, state = _page_from(c.url, fetched, result.origin, cfg, "archive", 0, NAMES[c.source])
        if state == "read":
            pages.append(page)
            kept.append(c)
    view = replace(result, pages=pages, structure=None, render=None, access=None, index=None, perf=None,
                   not_fetched_urls=[], requests=[], collector_errors={}, stop_reason=StopReason.PAGE_CAP,
                   stop_detail="Archive sample only; live coverage is unknown")
    checks = [c for c in run_structure_checks(view, cfg, []) + settle_all([idx8_duplicates(view, cfg)], view) if c.check_id in CHECKS] if pages else []
    source = kept[0].source if kept else None
    provenance = [{"url": c.url, "date": c.date, "archive_url": c.archive_url,
                   "label": f"Source: {NAMES[c.source]}; " + NOTICE.format(date=c.date)} for c in kept]
    for check in checks:
        check.evidence["source"] = {"reader": source, "copies": provenance}
        check.summary = f"Source: {NAMES[source]}; archived content only. " + check.summary
        for item in [*check.findings, *check.review_items]:
            selected = [p for p in provenance if p["url"] in item.scope.get("urls", [])] or provenance
            item.evidence["source"] = {"reader": source, "copies": selected}
            item.id = source + ":" + item.id
            if hasattr(item, "notes"):
                item.notes.insert(0, " | ".join(p["label"] for p in selected))
    return to_jsonable(checks), [{**meta, "title": p.analysis.get("title"),
                                "text_sample": "\n".join(p.analysis.get("_content_blocks") or [])[:2000]} for meta, p in zip(provenance, pages)]


# Tests replace this with a mock transport. Nothing else should.
TRANSPORT = None


def collect(result, cfg, *, wayback=False, common_crawl=False, transport=None, should_stop=lambda: False, sleep=time.sleep, clock=None):
    enabled = [name for name, on in (("wayback", wayback), ("common_crawl", common_crawl)) if on]
    if not enabled:
        return None
    if clock is not None:  # the audit's own deadline and stop request (maya_audit.runclock)
        asked = should_stop
        should_stop = lambda: bool(asked()) or clock.why_not() is not None  # noqa: E731
    transport = transport or TRANSPORT
    cap = min(MAX_PAGES, cfg.max_pages)
    section = {"enabled": enabled, "cost_usd": 0, "page_cap": cap, "sources": [], "notice": "Historical content only; live access findings are unchanged."}
    client = Client(cfg.user_agent, transport=transport, should_stop=should_stop, sleep=sleep)
    try:
        for n, name in enumerate(enabled):
            errors = []
            source_cap = cap // len(enabled) + (1 if n < cap % len(enabled) else 0)
            copies = []
            if source_cap and not result.stopped:
                try:
                    copies = getattr(client, name)(result.start_url, list(cfg.key_pages), source_cap, errors)
                except (ArchiveError, ValueError, TypeError, AttributeError) as exc:
                    errors.append(str(exc))
            checks, pages = analyze(copies, result, cfg)
            section["sources"].append({"id": name, "name": NAMES[name], "pages": pages, "checks": checks,
                                        "pages_read": len(pages), "notes": errors,
                                        "status": "assessed" if pages else "not_assessed"})
        section.update(requests_sent=client.requests, downloaded_bytes=client.bytes, fetched_at=utc_now())
    finally:
        client.close()
    return section


def lines(section, samples=True):
    out = ["Archived content (free)", section["notice"]]
    for source in section["sources"]:
        out += [f"{source['name']}: {source['pages_read']} archived page(s) read.", *source["notes"]]
        for page in source["pages"]:
            out += [f"{page['url']} — {page['label']}", str(page.get("title") or ""), *([page["text_sample"]] if samples else [])]
        for check in sorted(source["checks"], key=lambda c: check_id_key(c["check_id"])):
            out += [f"{check['check_id']}: {check['status']} — {check['summary']}"]
            for finding in check["findings"]:
                out += [f"[{finding['severity']}] {finding['title']}", *finding["notes"], finding["how_to_fix"]]
    return out


def view(section):
    """The section for a results page: sources, pages with their date labels, and what the content checks found."""
    sources = [{"id": s["id"], "name": s["name"], "pages_read": s["pages_read"], "status": s["status"], "notes": s["notes"],
                "pages": [{"url": p["url"], "label": p["label"], "title": p.get("title"), "archive_url": p["archive_url"]} for p in s["pages"]],
                "findings": [{"check_id": c["check_id"], "severity": f["severity"], "title": f["title"], "how_to_fix": f["how_to_fix"]}
                             for c in sorted(s["checks"], key=lambda c: check_id_key(c["check_id"])) for f in c["findings"]]}
               for s in section["sources"]]
    return {"notice": section["notice"], "pages_read": sum(s["pages_read"] for s in sources), "sources": sources,
            "requests_sent": section.get("requests_sent"), "fetched_at": section.get("fetched_at")}


def markdown(section):
    return "\n\n## Archived content\n\n" + "\n\n".join(line.replace("<", "&lt;").replace(">", "&gt;") for line in lines(section)) + "\n"
