"""After the live nihan Standard 500 audit of 2026-11-02 (DECISIONS 295): Firecrawl's own pace, a timed-out page asked
for once more, a Mac kept awake and its sleep said, RND-6 on Firecrawl's HTML when Maya was blocked, and the outcome
sentence when Maya was blocked by 429s but Firecrawl read the pages.

Every site, every Firecrawl and every clock here is made up; no socket is opened, nothing is paid for, and nothing is
started on this computer (caffeinate is replaced).
"""
import json
import os
import time as real_time
from dataclasses import replace

import httpx
import pytest

from maya_audit import keepawake
from maya_audit.audit import run_audit
from maya_audit.config import CrawlConfig
from maya_audit.firecrawl import Options, panel, reader, settings
from maya_audit.firecrawl.pace import ReaderPace
from maya_audit.report import build_report, duration_line, reader_gaps, run_outcome, sleep_note, timing
from maya_audit.runclock import RunClock, for_outcome
from maya_audit_web import summary, wording
from maya_audit_web.strings import set_language
from test_false_alarms import KAFE
from test_firecrawl import SITE, Firecrawl, blocked_audit, client_for, doc, no_lookups  # noqa: F401
from test_rate_limited_start import site as rate_limited_site, slept  # noqa: F401
from test_review_fixes import QUIET
from test_run_clock import FakeTime, clocked
from test_v03_speed import SlowFirecrawl, _pages, _site

MAIN = Options(read_always=True, max_pages=12)
CFG = CrawlConfig(**{**QUIET, "max_pages": 12})


@pytest.fixture
def no_retry_wait(monkeypatch):
    monkeypatch.setattr(settings, "RETRY_WAIT_S", 0)


def readable_audit(n=8):
    pages = _pages(n)
    return pages, run_audit(KAFE + "/", CFG, httpx.MockTransport(_site(pages)))


# -- 1. Firecrawl's own pace ----------------------------------------------------------------------------------------
def test_firecrawls_pace_spaces_starts_by_its_gap_and_never_has_more_in_flight_than_its_limit():
    time = FakeTime()
    pace = ReaderPace(2, 1.0, now=time.clock, sleep=time.sleep)
    first, second = pace.acquire(), pace.acquire()
    assert (first.started_mono, second.started_mono) == (1000.0, 1001.0) and round(sum(time.slept), 3) == 1.0
    asked = {"n": 0}

    def give_up():
        asked["n"] += 1
        return asked["n"] > 3
    assert pace.acquire(should_stop=give_up) is None  # two in flight already: a third waits, and gives up on a stop
    pace.release(first)
    third = pace.acquire()
    assert third.started_mono == 1002.0 and pace.max_in_flight == 2 and pace.starts == 3


def test_firecrawls_pace_backs_off_five_two_one_and_doubles_its_gap_to_at_most_four_times():
    pace = ReaderPace(5, 1.0)
    assert pace.back_off("429 from Firecrawl", 3) == {"from": 5, "to": 2, "gap_from_s": 1.0, "gap_to_s": 2.0,
                                                       "reason": "429 from Firecrawl", "after_answers": 3}
    assert pace.back_off("timeout")["gap_to_s"] == 4.0 and pace.limit == 1
    assert pace.back_off("5xx from the site") is None  # both at their bottom
    assert pace.summary()["gap_final_s"] == 4.0 and pace.summary()["final"] == 1


def test_a_crawl_delay_makes_firecrawl_read_one_at_a_time_with_the_delay_as_its_gap(tmp_path, no_lookups):
    from maya_audit.robots import policy_from_response
    pages, outcome = readable_audit(3)
    # The site's robots.txt as Maya read it, with a Crawl-delay (put in after the crawl, so Maya's own crawl did not wait).
    text = b"User-agent: *\nCrawl-delay: 3\nAllow: /\n"
    outcome.result.robots_policy_by_origin[KAFE] = policy_from_response(KAFE + "/robots.txt", 200, None, text, 500 * 1024, [])
    time = FakeTime(now=outcome.started_mono)
    client = client_for(tmp_path, Firecrawl(pages))
    client.clock = clocked(time)
    info = reader.apply(outcome, CFG, client, replace(MAIN, gap_s=1.0))
    assert info["concurrency"]["start"] == 1 and info["concurrency"]["gap_s"] == 3.0 and info["concurrency"]["crawl_delay_s"] == 3.0
    assert info["pages_read"] == 4 and round(sum(time.slept), 3) == 9.0  # three gaps of three seconds between four requests


def test_firecrawl_keeps_its_own_gap_not_mayas_after_maya_was_rate_limited(tmp_path, slept, no_lookups):
    handler, _ = rate_limited_site([(429, 60), (429, 60)])
    outcome = run_audit("https://bank.test/", CrawlConfig(**{**QUIET, "max_pages": 10}), httpx.MockTransport(handler))
    outcome.pace_s = 60.0  # Maya's polite gap after the 429s
    api = Firecrawl(SITE)
    time = FakeTime(now=outcome.started_mono)
    client = client_for(tmp_path, api)
    client.clock = clocked(time, pace_s=60.0)
    info = reader.apply(outcome, CrawlConfig(**{**QUIET, "max_pages": 10}), client,
                        Options(read_always=True, max_pages=10, concurrency=1, gap_s=1.0))
    # One-second starts, never Maya's sixty: the waits add up to one second between each two requests.
    assert info["pages_read"] >= 3 and round(sum(time.slept), 3) == float(len(api.bodies) - 1)


# -- 2. a timed-out page is asked for once more ------------------------------------------------------------------------
def test_a_page_that_times_out_is_retried_once_then_skipped_and_the_reading_goes_on(tmp_path, no_lookups, no_retry_wait):
    pages, outcome = readable_audit(8)
    tries = {}

    def flaky(body):
        url = body["url"]
        tries[url] = tries.get(url, 0) + 1
        if url == f"{KAFE}/p1" and tries[url] == 1:
            raise httpx.ReadTimeout("made up: no answer in time")
        if url == f"{KAFE}/p2":
            raise httpx.ReadTimeout("made up: never answers")
        return None
    api = Firecrawl(pages, responder=flaky)
    client = client_for(tmp_path, api)
    client.clock = for_outcome(outcome)
    info = reader.apply(outcome, CFG, client, MAIN)
    section = panel.section(info)
    assert tries[f"{KAFE}/p1"] == 2 and tries[f"{KAFE}/p2"] == 2  # each asked for twice, no more
    assert section["pages_read"] == 8 and not section.get("stopped_because")  # the reading went on to every other page
    assert section["coverage"]["timeouts"] == {"timed_out": 2, "retried": 2, "read_on_retry": 1, "skipped": 1}
    rows = {row["url"]: row for row in section["pages"]}
    assert rows[f"{KAFE}/p1"]["outcome"] == "read" and rows[f"{KAFE}/p1"]["retried"] is True
    assert rows[f"{KAFE}/p2"]["outcome"] == "failed" and rows[f"{KAFE}/p2"]["cause"] == "timeout_or_no_answer"
    assert [step["reason"] for step in section["concurrency"]["backed_off"]] == ["timeout", "timeout"]
    assert "Firecrawl: 8 page(s) read, 2 retried after a timeout, 1 skipped" in reader_gaps(section)
    # Every call that timed out keeps its reservation: 4 timed out, possibly billed; the second try of p1 was charged.
    assert sum(1 for call in client.calls if call["billing_status"] == "possibly_billed") == 3
    set_language("tr")
    try:
        assert wording.reason("Firecrawl: 8 page(s) read, 2 retried after a timeout, 1 skipped")[0] == (
            "Firecrawl: 8 sayfa okundu, 2 sayfa zaman aşımından sonra yeniden istendi, 1 sayfa atlandı")
    finally:
        set_language("en")


def test_five_failures_in_a_row_stop_the_reading_and_the_coverage_line_says_so(tmp_path, no_lookups, no_retry_wait):
    pages, outcome = readable_audit(10)

    def down(body):
        if body["url"] != KAFE + "/":
            raise httpx.ReadTimeout("made up: Firecrawl stopped answering")
        return None
    api = Firecrawl(pages, responder=down)
    client = client_for(tmp_path, api)
    client.clock = for_outcome(outcome)
    info = reader.apply(outcome, CFG, client, MAIN)
    section = panel.section(info)
    assert section["stopped_because"] == "the last 5 pages asked for came back unreadable, so no more were requested"
    assert section["pages_read"] == 1 and len(api.bodies) <= 1 + 5 + 5  # stopped, not every page asked for twice
    timeouts = section["coverage"]["timeouts"]
    assert timeouts["skipped"] >= 3 and timeouts["read_on_retry"] == 0
    gaps = reader_gaps(section)
    assert any(gap.startswith("reading stopped early (the last 5 pages") for gap in gaps)
    assert any(gap.startswith("Firecrawl: 1 page(s) read, ") and gap.endswith(f"{timeouts['skipped']} skipped") for gap in gaps)


def test_firecrawls_own_408_is_a_timeout_asked_for_once_more_and_not_charged(tmp_path, no_lookups, no_retry_wait):
    pages, outcome = readable_audit(3)
    tries = {}

    def slow_engine(body):
        tries[body["url"]] = tries.get(body["url"], 0) + 1
        if body["url"] == f"{KAFE}/p0" and tries[body["url"]] == 1:
            return httpx.Response(408, json={"success": False, "error": "Scrape timed out"})
        return None
    client = client_for(tmp_path, Firecrawl(pages, responder=slow_engine))
    client.clock = for_outcome(outcome)
    info = reader.apply(outcome, CFG, client, MAIN)
    assert info["pages_read"] == 4 and info["coverage"]["timeouts"]["read_on_retry"] == 1
    assert [c["credits"] for c in client.calls if c["url"] == f"{KAFE}/p0"] == [0, 2]  # the 408 had no document: no charge


# -- 3. the Mac kept awake, and its sleep said -------------------------------------------------------------------------
class Launched:
    def __init__(self, args, **kwargs):
        self.args, self.ended = args, False
        Launched.last = self

    def terminate(self):
        self.ended = True

    def wait(self, timeout=None):
        return 0


def test_on_macos_an_audit_runs_under_caffeinate_for_this_process_and_ends_it(monkeypatch):
    monkeypatch.setattr(keepawake, "LAUNCH", Launched)
    monkeypatch.setattr(keepawake.sys, "platform", "darwin")
    Launched.last = None
    with keepawake.KeepAwake({}) as awake:
        assert awake.active and Launched.last.args[1:] == ["-i", "-w", str(os.getpid())]
        assert Launched.last.args[0].endswith("caffeinate")
    assert Launched.last.ended and not awake.active
    Launched.last = None
    with keepawake.KeepAwake({keepawake.VAR: "off"}):
        assert Launched.last is None  # switched off
    monkeypatch.setattr(keepawake.sys, "platform", "linux")
    with keepawake.KeepAwake({}) as awake:
        assert Launched.last is None and not awake.active  # nothing elsewhere


def test_a_computer_that_slept_is_said_in_the_timing_section_and_a_short_gap_is_not():
    time = FakeTime(now=5000.0)
    clock = RunClock(clock=time.clock, sleep=time.sleep, started_mono=5000.0 - 600, started_wall=real_time.time() - 3600)
    assert 2990 <= clock.slept_s() <= 3010  # an hour on the wall, ten minutes awake
    assert sleep_note(3000) == ("The computer slept for about 50 min during this audit; the durations count only the time "
                                "it was awake.")
    assert sleep_note(90) is None and sleep_note(None) is None
    outcome = blocked_audit()
    saved = timing(outcome.result, None, 600.0, 3000.0)
    assert saved["slept_s"] == 3000.0 and saved["slept_note"].startswith("The computer slept for about 50 min")
    assert timing(outcome.result, None, 600.0, 30.0)["slept_note"] is None
    assert duration_line(outcome.result, 600.0, 3000.0).endswith("about 50 min during this audit; the durations count only the time it was awake.")
    assert "slept" not in duration_line(outcome.result, 600.0, 30.0)
    report = build_report(outcome.result, outcome.gates, outcome.checks, all_phases_s=600.0, slept_s=3000.0)
    shown = summary.status_view(report)["duration_line"]
    assert shown.endswith("The computer slept for about 50 min during this audit; the durations count only the time it was awake.")


# -- 4. RND-6 on Firecrawl's HTML when Maya was blocked -------------------------------------------------------------------
def test_when_maya_was_blocked_the_html_weight_check_is_measured_on_firecrawls_html(tmp_path, no_lookups):
    heavy = dict(SITE)
    # 600 KB of inline script before the main content: a heavy homepage whose main content starts late.
    heavy["https://bank.test/"] = SITE["https://bank.test/"].replace("<body>", "<body><script>" + "x" * 600_000 + "</script>", 1)
    outcome = blocked_audit()
    assert outcome.by_id()["RND-6"].findings == []  # Maya got a challenge page: nothing to weigh
    info = reader.apply(outcome, CrawlConfig(**{**QUIET, "max_pages": 10}), client_for(tmp_path, Firecrawl(heavy)),
                        Options(read_always=True, max_pages=10))
    rnd6 = outcome.by_id()["RND-6"]
    assert "RND-6" in info["checks_from_firecrawl"] and rnd6.summary.startswith("Source: Firecrawl. ")
    assert rnd6.evidence["source"]["reader"] == "firecrawl" and rnd6.evidence["pages_measured"] == info["pages_read"]
    titles = [f.title for f in rnd6.findings]
    assert any(t.startswith("The homepage's HTML is 6") for t in titles)
    assert any("start their main content more than 500 KB" in t for t in titles)


def test_when_maya_read_the_site_its_own_html_weight_check_stands(tmp_path, no_lookups):
    pages, outcome = readable_audit(3)
    before = outcome.by_id()["RND-6"] if hasattr(outcome, "by_id") else next(c for c in outcome.checks if c.check_id == "RND-6")
    client = client_for(tmp_path, Firecrawl(pages))
    client.clock = for_outcome(outcome)
    info = reader.apply(outcome, CFG, client, MAIN)
    after = next(c for c in outcome.checks if c.check_id == "RND-6")
    assert "RND-6" not in info["checks_from_firecrawl"] and after is before and not after.summary.startswith("Source:")
    # The healthy reading: nothing timed out, nothing backed off, every page read.
    assert info["coverage"]["timeouts"] == {"timed_out": 0, "retried": 0, "read_on_retry": 0, "skipped": 0}
    assert info["concurrency"]["backed_off"] == [] and info["pages_read"] == 4
    assert not [row for row in info["pages"] if row.get("retried")]
    assert run_outcome(outcome.result, outcome.gates, panel.section(info))[1] == "COMPLETED"


# -- 5. the outcome sentence when Maya was blocked and Firecrawl read the pages --------------------------------------------
def test_blocked_by_429_with_pages_read_through_firecrawl_is_not_called_unreadable(tmp_path, slept, no_lookups):
    handler, _ = rate_limited_site([(429, 60), (429, 60)])
    outcome = run_audit("https://bank.test/", CrawlConfig(**{**QUIET, "max_pages": 10}), httpx.MockTransport(handler))
    info = reader.apply(outcome, CrawlConfig(**{**QUIET, "max_pages": 10}), client_for(tmp_path, Firecrawl(SITE)),
                        Options(read_always=True, max_pages=10))
    section = panel.section(info)
    code, word, sentence = run_outcome(outcome.result, outcome.gates, section)
    n = section["pages_read"]
    assert (code, word) == (1, "DEGRADED") and n >= 3
    assert sentence.startswith(f"Maya's crawler was blocked (429 on pages); {n} page(s) were read through Firecrawl")
    assert "could not read" not in sentence and sentence.endswith("Findings cover only the pages read.")
    assert summary.outcome_label("DEGRADED", sentence) == f"Maya's crawler was blocked (429 on pages); read through Firecrawl: {n} pages"
    assert wording.outcome(sentence)[0].startswith(f"Maya's crawler was blocked (429 on pages); {n} pages were read through Firecrawl")
    set_language("tr")
    try:
        translated, known = wording.outcome(sentence)
        assert known and translated.startswith(f"Maya'nın tarayıcısı engellendi (sayfalarda 429); {n} sayfa Firecrawl aracılığıyla okundu")
        assert summary.outcome_label("DEGRADED", sentence) == f"Maya'nın tarayıcısı engellendi (sayfalarda 429); Firecrawl ile okunan: {n} sayfa"
    finally:
        set_language("en")


def test_blocked_by_429_with_nothing_read_keeps_could_not_read(tmp_path, slept, no_lookups):
    handler, _ = rate_limited_site([(429, 60), (429, 60)])
    outcome = run_audit("https://bank.test/", CrawlConfig(**{**QUIET, "max_pages": 10}), httpx.MockTransport(handler))
    refused = Firecrawl({}, responder=lambda body: httpx.Response(200, json={"success": True, "data": {
        "rawHtml": "<html><title>Just a moment...</title><body>Checking your browser</body></html>",
        "metadata": {"statusCode": 403, "url": body["url"]}}}))
    info = reader.apply(outcome, CrawlConfig(**{**QUIET, "max_pages": 10}), client_for(tmp_path, refused), Options(read_always=True, max_pages=10))
    code, word, sentence = run_outcome(outcome.result, outcome.gates, panel.section(info))
    assert (code, word) == (1, "DEGRADED") and sentence.startswith("The audit could not read the site properly")
    assert summary.outcome_label("DEGRADED", sentence) == "The site could not be read properly"


def test_the_progress_box_shows_both_paces(tmp_path, no_lookups):
    pages, outcome = readable_audit(3)
    seen = []
    client = client_for(tmp_path, Firecrawl(pages))
    client.clock = for_outcome(outcome)
    reader.apply(outcome, CFG, client, replace(MAIN, gap_s=0.2), progress=seen.append)
    assert seen and seen[-1]["at_once"] == 5 and seen[-1]["gap_s"] == 0.2
    from maya_audit_web.strings import t
    assert t("job.pace.firecrawl", read=3, cap=12, at_once=5, gap=1) == "Firecrawl: 3 of up to 12 pages read (5 at a time, starts at least 1 s apart)"
    assert t("job.pace.maya", gap=2) == "one request every 2 s"
    events = []
    from maya_audit.progress import Hooks
    run_audit(KAFE + "/", CFG, httpx.MockTransport(_site(pages)), Hooks(on_progress=events.append))
    assert any(e.get("phase") == "crawl" and e.get("delay_s") == 0 for e in events)  # Maya's own gap in each crawl event


def test_the_gap_setting_is_this_computers_unless_a_plan_or_the_command_line_says(monkeypatch, tmp_path):
    from maya_audit import cli
    env = tmp_path / "none.env"
    assert settings.gap_s({"MAYA_AUDIT_ENV_FILE": str(env)}) == 1.0
    assert settings.gap_s({"MAYA_AUDIT_ENV_FILE": str(env), settings.GAP_VAR: "2.5"}) == 2.5
    assert settings.gap_s({"MAYA_AUDIT_ENV_FILE": str(env), settings.GAP_VAR: "99"}) == 30.0
    assert Options(gap_s=0.1).problem() and Options(gap_s=1.0).problem() is None and Options().gap_s is None
    with pytest.raises(SystemExit):
        cli._parser().parse_args(["crawl", KAFE + "/", "--firecrawl-gap", "0"])
    assert cli._parser().parse_args(["crawl", KAFE + "/", "--firecrawl-gap", "2"]).firecrawl_gap == 2.0
    from maya_audit_web import fc, paid
    assert fc.options_from({"gap_s": 2.0}).gap_s == 2.0 and fc.options_from({}).gap_s is None

    def shown(gap):
        return {"requested": True, "options": {**Options(read_always=True).as_dict(), "gap_s": gap}, "max_credits": 102, "max_usd": None}
    assert paid.fingerprint(KAFE, "quick", [], False, [], 0.0, shown(None)) == paid.fingerprint(KAFE, "quick", [], False, [], 0.0, shown(3.0))


def test_the_report_schema_is_1_22_with_the_timeout_counts():
    from maya_audit import schema
    assert schema.SCHEMA_VERSION == "1.22" and "timeouts" in schema.FIRECRAWL_COVERAGE_KEYS
    assert json.loads(schema.frozen_path().read_text(encoding="utf-8"))["schema_version"] == "1.22"
