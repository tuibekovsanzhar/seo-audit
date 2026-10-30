"""Progress events, stopping on request, and a resume that reports on every session's pages.

What a job runner (the web interface) needs from the engine. Offline: fake server only.
"""

import sqlite3

import pytest

from fakeserver import FakeServer, Response, Site
from maya_audit.audit import run_audit
from maya_audit.config import CrawlConfig
from maya_audit.models import StopReason, page_from_record, page_record
from maya_audit.progress import PHASES, Hooks
from maya_audit.report import EXIT_INCOMPLETE, build_report, render_markdown, run_outcome
from maya_audit.scratchpad import CRAWLED, QUEUED, FrontierUrl, Scratchpad
from test_deadline_hosted_hardening import QUIET
from test_review_fixes import TR, links, page

PATHS = [f"/tr/bolum-{n}/" for n in range(1, 9)]


def site():
    routes = {path: page(f"<h1>Bölüm {n}</h1><p>{TR}</p><p>Bölüm {n} için ayrıntılı bilgi bu sayfada yer alır.</p>"
                         + (f"<p>Yazar {{{{author_name}}}} tarafından yazıldı.</p>" if n == 7 else ""))
              for n, path in enumerate(PATHS, 1)}
    routes["/"] = page(f"<h1>Ana sayfa</h1><p>{TR}</p>" + links(PATHS))
    routes["/robots.txt"] = Response(body="User-agent: *\nAllow: /\n", content_type="text/plain")
    return Site(routes)


def run(server, hooks=None, **options):
    return run_audit(server.base_url + "/", CrawlConfig(**{**QUIET, **options}), hooks=hooks)


def findings(outcome, base):
    """What the site checks found, without the things that differ between two runs (ids, times, the port)."""
    return sorted((f.check_id, f.title, f.severity.value, tuple(sorted(u.removeprefix(base) for u in f.scope["urls"])))
                  for c in outcome.checks if c.check_id[:3] in ("ACC", "IDX", "STR", "TSE") for f in c.findings)


class Recorder:
    """Collects progress events and asks for a stop once `when(event)` is true."""

    def __init__(self, when=None):
        self.events, self.when, self.stop = [], when, False

    def on_progress(self, event):
        self.events.append(event)
        if self.when and self.when(event):
            self.stop = True

    def hooks(self):
        return Hooks(on_progress=self.on_progress, should_stop=lambda: self.stop)


# Progress ---------------------------------------------------------------------------------------------
def test_an_audit_reports_its_phases_in_order_and_its_page_counts():
    seen = Recorder()
    with FakeServer(site()) as server:
        outcome = run(server, seen.hooks())
    phases = list(dict.fromkeys(event["phase"] for event in seen.events))
    assert phases == [p for p in PHASES if p in phases]  # in the documented order
    assert phases[0] == "starting" and phases[-1] == "done"
    assert {"crawl", "access", "index", "structure", "render", "performance", "checks"} <= set(phases)
    crawl = [event for event in seen.events if event["phase"] == "crawl"]
    counts = [event["pages_fetched"] for event in crawl]
    assert counts == sorted(counts) and counts[-1] == 9 == len(outcome.result.pages)
    assert all(event["max_pages"] == CrawlConfig().max_pages for event in crawl)
    assert crawl[-1]["pages_discovered"] == 9 and crawl[0]["url"] == server.base_url + "/"
    assert all(event["elapsed_s"] >= 0 for event in seen.events)
    assert seen.events[-1]["stopped"] is False and seen.events[-1]["stop_reason"] == "exhausted"


def test_hooks_do_not_change_what_an_audit_finds_and_a_failing_listener_does_not_fail_it():
    def broken(event):
        raise RuntimeError("listener bug")

    with FakeServer(site()) as server:
        plain = run(server)
        watched = run(server, Hooks(on_progress=broken, should_stop=lambda: False))
        assert findings(plain, server.base_url) == findings(watched, server.base_url) != []
    assert watched.result.stopped is False and "audit_stopped" not in watched.result.collector_errors


# Stop -------------------------------------------------------------------------------------------------
def test_a_stop_during_the_crawl_ends_it_and_the_fetched_pages_are_still_checked(tmp_path):
    seen = Recorder(lambda event: event["phase"] == "crawl" and event["pages_fetched"] >= 3)
    with FakeServer(site()) as server:
        outcome = run(server, seen.hooks(), db_path=str(tmp_path / "crawl.db"))
    result = outcome.result
    assert result.stop_reason == StopReason.STOPPED and result.stopped and not result.deadline_hit
    assert len(result.pages) == 3 and len(result.not_fetched_urls) == 6
    code, word, sentence = run_outcome(result, outcome.gates)
    assert (code, word) == (EXIT_INCOMPLETE, "INCOMPLETE") and "stopped on request and can be resumed" in sentence
    by_id = {check.check_id: check for check in outcome.checks}
    # The checks that read the fetched pages ran. Those that need requests of their own were cut, as at the time limit.
    assert by_id["STR-1"].status != "not_assessed" and by_id["STR-13"].status != "not_assessed"
    assert by_id["IDX-4"].status == "not_assessed" and "deadline" in by_id["IDX-4"].summary
    markdown = render_markdown(result, outcome.gates, outcome.checks)
    assert "The audit was stopped on request before it finished." in markdown
    assert "reached its time limit" not in markdown
    int2 = next(gate for gate in outcome.gates if gate.check_id == "INT-2")
    assert "Resume" in (int2.how_to_fix or "")
    report = build_report(result, outcome.gates, outcome.checks)
    assert report["crawl"]["stopped"] is True and report["crawl"]["stop_reason"] == "stopped"


def test_a_stop_is_heard_while_the_audit_waits_between_requests(tmp_path):
    import threading
    import time

    seen = Recorder()
    timer = threading.Timer(1.0, lambda: setattr(seen, "stop", True))
    started = time.monotonic()
    with FakeServer(site()) as server:
        timer.start()
        # 30 seconds between requests: after robots.txt the audit is waiting when the stop request arrives.
        outcome = run(server, seen.hooks(), request_delay_s=30.0, time_limit_s=600)
    assert outcome.result.stop_reason == StopReason.STOPPED and outcome.result.stopped
    assert len(outcome.result.pages) == 0 and time.monotonic() - started < 15


def test_a_stop_after_the_crawl_cuts_the_slow_collection_short(tmp_path):
    seen = Recorder(lambda event: event["phase"] == "performance")
    with FakeServer(site()) as server:
        outcome = run(server, seen.hooks(), db_path=str(tmp_path / "crawl.db"))
    result = outcome.result
    assert result.stop_reason == StopReason.EXHAUSTED and len(result.pages) == 9  # the crawl itself had finished
    assert result.stopped and result.collector_errors["audit_stopped"] == "the audit was stopped on request"
    assert run_outcome(result, outcome.gates)[1] == "INCOMPLETE"


# Resume -----------------------------------------------------------------------------------------------
def test_a_stopped_audit_resumed_reports_what_an_uninterrupted_one_does(tmp_path):
    db = str(tmp_path / "crawl.db")
    seen = Recorder(lambda event: event["phase"] == "crawl" and event["pages_fetched"] >= 4)
    with FakeServer(site()) as server:
        whole = run(server)
        first = run(server, seen.hooks(), db_path=db)
        before = len(server.requests)
        watch = Recorder()
        second = run(server, watch.hooks(), db_path=db, resume=True)
        asked_again = {seen.path for seen in server.requests[before:]}
        base = server.base_url
    assert len(first.result.pages) == 4 and first.result.stopped
    assert not second.result.stopped and second.result.stop_reason == StopReason.EXHAUSTED
    assert sorted(p.url for p in second.result.pages) == sorted(p.url for p in whole.result.pages)
    # The earlier session's pages come from the crawl database, in the order they were fetched.
    assert [p.url for p in second.result.pages[:4]] == [p.url for p in first.result.pages]
    assert findings(second, base) == findings(whole, base) != []
    assert any(f.check_id == "STR-13" for c in second.checks for f in c.findings)  # needs a page's text
    assert len(second.result.sessions) == 2 and second.result.not_fetched_urls == []
    # Progress counts the whole crawl, not only this session.
    crawl = [event for event in watch.events if event["phase"] == "crawl"]
    assert crawl[0]["pages_fetched"] == 5 and crawl[-1]["pages_fetched"] == 9
    # Only the five missing pages were requested as pages again (other requests are the checks' own).
    assert run_outcome(second.result, second.gates)[1] != "DEGRADED"
    first_paths = {p.url.removeprefix(base) for p in first.result.pages}
    page_requests = [r.url.removeprefix(base) for r in second.result.requests if r.purpose == "page"]
    assert len(page_requests) == 5 and not first_paths & set(page_requests) and asked_again


def test_resuming_after_a_stop_in_the_collection_fetches_no_page_and_finishes_the_checks(tmp_path):
    db = str(tmp_path / "crawl.db")
    seen = Recorder(lambda event: event["phase"] == "access")
    with FakeServer(site()) as server:
        first = run(server, seen.hooks(), db_path=db)
        second = run(server, db_path=db, resume=True)
        base = server.base_url
        whole = run(server)
    assert first.result.stopped and len(first.result.pages) == 9
    assert [r for r in second.result.requests if r.purpose == "page"] == []
    assert not second.result.stopped and len(second.result.pages) == 9
    assert findings(second, base) == findings(whole, base)


def test_a_page_fetched_but_never_saved_is_fetched_again_on_resume(tmp_path):
    """The process died between the fetch and the write of the page record."""
    db = str(tmp_path / "crawl.db")
    with FakeServer(site()) as server:
        run(server, db_path=db, max_pages=5)
        lost = server.base_url + PATHS[0]
        with sqlite3.connect(db) as raw:
            assert raw.execute("SELECT status FROM frontier WHERE url = ?", (lost,)).fetchone()[0] == CRAWLED
            raw.execute("DELETE FROM pages WHERE url = ?", (lost,))
        second = run(server, db_path=db, resume=True)
    assert [r.url for r in second.result.requests if r.purpose == "page"].count(lost) == 1
    assert len(second.result.pages) == 9 and len({p.url for p in second.result.pages}) == 9


def test_page_records_round_trip_with_their_working_data(tmp_path):
    with FakeServer(site()) as server:
        outcome = run(server, max_pages=2)
    original = outcome.result.pages[0]
    assert original.analysis["_visible_text"] and original.outlinks
    copy = page_from_record(page_record(original))
    assert copy == original and copy.fetch_class is original.fetch_class
    pad = Scratchpad(str(tmp_path / "p.db"))
    pad.add_urls([FrontierUrl(original.url, 0, "start", None)])
    pad.save_page(page_record(original))
    assert pad.saved_page_count() == 1 and page_from_record(pad.saved_pages()[0]) == original
    assert page_from_record({**page_record(original), "a_field_from_a_later_version": 1}) == original


def test_a_crawl_held_in_memory_saves_no_page_records():
    pad = Scratchpad()
    pad.save_page({"url": "http://s/"})
    assert pad.saved_page_count() == 0 and pad.requeue_unsaved() == []
    assert pad.urls_with_status(QUEUED) == []
