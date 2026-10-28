"""Archived copies (Wayback Machine, Common Crawl): a free, opt-in fallback for a site nothing else could read.

Both archives are mock transports built from their documented response shapes. Neither was called while this was
written, and no test can reach them (tests/conftest.py refuses every non-loopback connection).
"""
import gzip
import json

import httpx
import pytest

from maya_audit import archives
from maya_audit.config import CrawlConfig
from test_firecrawl import SITE, blocked_audit, no_lookups  # noqa: F401
from test_review_fixes import QUIET

CFG = CrawlConfig(**{**QUIET, "max_pages": 10})
STAMP = "20260901120000"
HOME, ABOUT = "https://bank.test/", "https://bank.test/about"


class Wayback:
    def __init__(self, pages, fail=None):
        self.pages, self.fail, self.requests = pages, fail, []

    def __call__(self, request):
        self.requests.append(request)
        assert request.headers["user-agent"].startswith("Maya-Audit") and request.url.host != "bank.test"
        if self.fail:
            return httpx.Response(self.fail)
        if request.url.host == "web.archive.org" and request.url.path == "/cdx/search/cdx":
            return httpx.Response(200, json=[["original"], *[[url] for url in self.pages], ["https://elsewhere.example/x"]])
        if request.url.host == "archive.org":
            url = request.url.params["url"]
            if url not in self.pages:
                return httpx.Response(200, json={"archived_snapshots": {}})
            return httpx.Response(200, json={"archived_snapshots": {"closest": {
                "available": True, "status": "200", "timestamp": STAMP, "url": f"http://web.archive.org/web/{STAMP}/{url}"}}})
        original = str(request.url).split("id_/", 1)[1]
        return httpx.Response(200, text=self.pages[original], headers={"content-type": "text/html; charset=utf-8"})


def collect(outcome, api, **which):
    return archives.collect(outcome.result, CFG, transport=httpx.MockTransport(api), sleep=lambda s: None, **(which or {"wayback": True}))


def test_archives_are_off_unless_asked_for():
    assert archives.collect(None, CFG) is None


def test_wayback_copies_are_read_labelled_with_their_date_and_never_touch_the_live_results(no_lookups):
    outcome = blocked_audit()
    before = [(c.check_id, c.status, c.summary) for c in outcome.checks]
    api = Wayback({HOME: SITE[HOME], ABOUT: SITE[ABOUT]})
    section = collect(outcome, api)
    assert [(c.check_id, c.status, c.summary) for c in outcome.checks] == before  # a separate section: live results stand
    [source] = section["sources"]
    assert section["cost_usd"] == 0 and source["id"] == "wayback" and source["pages_read"] == 2 and source["status"] == "assessed"
    assert {page["url"] for page in source["pages"]} == {HOME, ABOUT}
    assert all(page["date"] == "2026-09-01T12:00:00+00:00" and "archived/indexed copy, date 2026-09-01" in page["label"]
               and "the live site may differ" in page["label"] and page["archive_url"].startswith("https://web.archive.org/web/") for page in source["pages"])
    assert {check["check_id"] for check in source["checks"]} <= archives.CHECKS and source["checks"]
    assert all(check["summary"].startswith("Source: Wayback Machine; archived content only.") for check in source["checks"])
    findings = [f for check in source["checks"] for f in check["findings"]]
    assert findings and all(f["id"].startswith("wayback:") and "archived/indexed copy" in f["notes"][0] for f in findings)
    assert not [r for r in api.requests if r.url.host not in ("archive.org", "web.archive.org")]
    assert section["requests_sent"] == len(api.requests) and "Historical content only" in section["notice"]
    text = "\n".join(archives.lines(section))
    assert "Wayback Machine: 2 archived page(s) read." in text and "the live site may differ" in text
    assert "## Archived content" in archives.markdown(section)
    view = archives.view(section)
    assert view["pages_read"] == 2 and view["sources"][0]["pages"][0]["label"] and "text_sample" not in json.dumps(view)


@pytest.mark.parametrize("status", [429, 503])
def test_a_rate_limit_or_failure_at_the_archive_stops_and_is_said(no_lookups, status):
    api = Wayback({HOME: SITE[HOME]}, fail=status)
    section = collect(blocked_audit(), api)
    [source] = section["sources"]
    assert source["pages_read"] == 0 and source["status"] == "not_assessed" and len(api.requests) == 1
    assert any(f"HTTP {status}" in note and "retry later" in note for note in source["notes"])


def warc(url, html, date="2026-08-15T08:30:00Z"):
    http = b"HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n\r\n" + html.encode()
    head = f"WARC/1.0\r\nWARC-Type: response\r\nWARC-Target-URI: {url}\r\nWARC-Date: {date}\r\nContent-Length: {len(http)}".encode()
    return gzip.compress(head + b"\r\n\r\n" + http)


def test_common_crawl_reads_the_latest_record_of_the_newest_collection_by_byte_range(no_lookups):
    record = warc(HOME, SITE[HOME])
    row = {"url": HOME, "timestamp": "20260815083000", "status": "200", "mime": "text/html",
           "filename": "crawl-data/CC-MAIN-2026-33/segments/1/warc/a.warc.gz", "offset": "100", "length": str(len(record))}
    seen = []

    def api(request):
        seen.append(request)
        assert request.headers["user-agent"].startswith("Maya-Audit")
        if request.url.path == "/collinfo.json":
            return httpx.Response(200, json=[{"id": "CC-MAIN-2026-20"}, {"id": "CC-MAIN-2026-33"}])
        if request.url.host == "index.commoncrawl.org":
            assert request.url.path == "/CC-MAIN-2026-33-index"
            return httpx.Response(200, text=json.dumps(row) + "\n" if request.url.params["url"] in (HOME, "bank.test") else "")
        assert request.url.host == "data.commoncrawl.org" and request.headers["range"] == f"bytes=100-{100 + len(record) - 1}"
        return httpx.Response(206, content=record, headers={"content-range": f"bytes 100-{100 + len(record) - 1}/999999"})

    section = collect(blocked_audit(), api, common_crawl=True)
    [source] = section["sources"]
    assert source["id"] == "common_crawl" and source["pages_read"] == 1 and source["pages"][0]["date"] == "2026-08-15T08:30:00+00:00"
    assert any("newest Common Crawl collection only (CC-MAIN-2026-33)" in note for note in source["notes"])
    assert source["checks"] and all("Source: Common Crawl" in check["summary"] for check in source["checks"])
    assert not [r for r in seen if r.url.host == "bank.test"]


def test_only_the_archives_own_addresses_are_ever_requested():
    client = archives.Client("Maya-Audit/0.2", transport=httpx.MockTransport(lambda r: pytest.fail("no request expected")), sleep=lambda s: None)
    for url in ("http://web.archive.org/x", "https://bank.test/", "https://web.archive.org.evil.example/"):
        with pytest.raises(archives.ArchiveError):
            client.get(url)
    assert not archives.scoped("https://user:pw@bank.test/", HOME) and not archives.scoped("https://other.test/", HOME)
    assert archives.scoped("https://www.bank.test/about", HOME)
