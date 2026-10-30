"""team-preview-16, run 4 (DECISIONS 219 part 2): a gap for each host, the requests to other sites in a pool beside the
audited site's, and adaptive pacing on a fast, error-free site; INT-4 measures per host.

Every site is made up (demo-kafe.test, other-N.test) and answered by an httpx mock transport; nothing is requested.
Most tests run on a fake monotonic clock (a wait moves it at once). The one that shows two other sites asked at the same
time uses the real clock with gaps of 0.02 s: two requests meet in the mock transport, and nothing is timed.
"""

from __future__ import annotations

import threading
import time

import httpx
import pytest

from maya_audit.audit import run_audit
from maya_audit.checks.integrity import int4_crawler_identity
from maya_audit.config import CrawlConfig
from maya_audit.fetcher import Fetcher, gaps_by_host
from maya_audit.models import RequestRecord

KAFE = "https://demo-kafe.test"
HOST = "demo-kafe.test"


class FakeClock:
    """time.monotonic and time.sleep for one test: sleeping moves the clock, nothing waits. Locked: the other-site
    pool's threads move it too."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start
        self._lock = threading.Lock()

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.advance(max(0.0, seconds))

    def advance(self, seconds: float) -> None:
        with self._lock:
            self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    fake = FakeClock()
    monkeypatch.setattr(time, "monotonic", fake.monotonic)
    monkeypatch.setattr(time, "sleep", fake.sleep)
    return fake


def page(body: str = "", title: str = "Demo Kafe") -> str:
    words = " ".join(["kahve", "menü", "tatlı", "çay", "sabah", "kahvaltı"] * 40)
    return (f"<html lang='tr'><head><title>{title}</title><meta name='description' content='Demo Kafe'></head>"
            f"<body><main><h1>{title}</h1><p>{words}</p>{body}</main></body></html>")


def site(pages: int = 3, external: int = 0, robots: str = "User-agent: *\nAllow: /\n", answer=None, other=None):
    """A made-up cafe: a homepage linking `pages` pages and `external` other sites (one link each). `answer(request)`
    runs before each answer of the cafe, `other(request)` before each answer of another site (it may return one)."""
    paths = [f"/sayfa-{i}" for i in range(pages)]
    links = "".join(f'<a href="{p}">{p}</a>' for p in paths)
    links += "".join(f'<a href="https://other-{i}.test/sayfa">other {i}</a>' for i in range(external))
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, str(request.url)))
        if request.url.host != HOST:
            got = other(request) if other else None
            if got is not None:
                return got
            if request.url.path == "/robots.txt":
                return httpx.Response(200, text="User-agent: *\nAllow: /\n", headers={"content-type": "text/plain"})
            return httpx.Response(200, text="ok", headers={"content-type": "text/plain"})
        got = answer(request) if answer else None
        if got is not None:
            return got
        path = request.url.path
        if path == "/robots.txt":
            return httpx.Response(200, text=robots, headers={"content-type": "text/plain"})
        if path == "/":
            return httpx.Response(200, text=page(links), headers={"content-type": "text/html; charset=utf-8"})
        if path in paths:
            return httpx.Response(200, text=page(title=f"Demo Kafe {path}"), headers={"content-type": "text/html; charset=utf-8"})
        return httpx.Response(404, text="yok", headers={"content-type": "text/plain"})

    transport = httpx.MockTransport(handler)
    transport.seen = seen
    return transport


BASE = dict(request_delay_s=1.0, robots_samples=1, render_enabled=False, prf_enabled=False, refetch_delay_s=0.0,
            probe_retry_cooldown_s=0.0, time_limit_s=3600.0, sitemap_check_max=0, soft_404_probe=False)


def audit(transport, **options):
    return run_audit(KAFE + "/", CrawlConfig(**{**BASE, **options}), transport).result


def other_site_requests(result):
    return [(r.url, r.purpose) for r in result.requests if "other-" in r.url]


# -- (d) the other-site pool ----------------------------------------------------------------------------------------------

def test_other_sites_are_asked_at_the_same_time_while_the_audited_site_is_asked_one_request_at_a_time():
    """Real clock, gaps of 0.02 s. An other-site request waits (at most 10 s) for a second one to be in flight: it meets
    one only if two other sites are asked at the same time. The cafe's requests are counted while in flight."""
    lock = threading.Lock()
    state = {"other": 0, "met": threading.Event(), "site": 0, "site_max": 0}

    def other(request):
        if request.url.path == "/robots.txt":
            return None
        with lock:
            state["other"] += 1
            if state["other"] >= 2:
                state["met"].set()
        state["met"].wait(10)
        with lock:
            state["other"] -= 1
        return None

    def answer(request):
        with lock:
            state["site"] += 1
            state["site_max"] = max(state["site_max"], state["site"])
        time.sleep(0.005)
        with lock:
            state["site"] -= 1
        return None

    transport = site(pages=4, external=6, answer=answer, other=other)
    outcome = run_audit(KAFE + "/", CrawlConfig(**{**BASE, "request_delay_s": 0.02}), transport)
    result = outcome.result
    assert state["met"].is_set(), "no two requests to other sites were ever in flight together"
    assert state["site_max"] == 1, "the audited site was asked more than one request at a time"
    # Every other site was asked (robots.txt first, then its link), each counted by the pool's own row.
    asked = other_site_requests(result)
    assert {url for url, purpose in asked if purpose == "external_link_head"} == {f"https://other-{i}.test/sayfa" for i in range(6)}
    gate = next(g for g in outcome.gates if g.check_id == "INT-4")
    assert gate.state == "compliant", gate.summary
    by_host = {row["host"]: row for row in gate.evidence["politeness"]["by_host"]}
    assert by_host[HOST]["min_gap_ms"] + 25 >= by_host[HOST]["required_gap_ms"] == 20.0
    # The step timing table: the pool's row, and every request counted once over all the rows.
    rows = {row["step"]: row for row in result.steps}
    assert rows["other_sites"]["requests"] == len(asked)
    assert sum(row["requests"] for row in result.steps) == len(result.requests)
    # The pool (threads, locks) is not kept on the result: a saved snapshot pickles it.
    assert result._other_sites is None


def test_the_same_links_are_asked_every_run_and_pacing_off_asks_them_in_turn_in_the_queue_order(clock):
    def run(**options):
        return audit(site(pages=3, external=8), **options)

    first, second, off = run(), run(), run(adaptive_pacing=False)
    assert sorted(other_site_requests(first)) == sorted(other_site_requests(second)) == sorted(other_site_requests(off))
    assert first.structure.other_site_links.keys() == off.structure.other_site_links.keys()
    assert {u: e["verdict"] for u, e in first.structure.other_site_links.items()} == \
           {u: e["verdict"] for u, e in off.structure.other_site_links.items()}
    # Pacing off: today's order. No pool row, and the other sites' requests sit inside the structure step, in turn.
    assert "other_sites" not in {row["step"] for row in off.steps}
    assert off.backoff["narrowed"] == [] and off.backoff["adaptive_pacing"] is False
    heads = [url for url, purpose in other_site_requests(off) if purpose == "external_link_head"]
    assert heads == [f"https://other-{i}.test/sayfa" for i in range(8)]
    assert [p for _, p in other_site_requests(off)] == ["robots", "external_link_head"] * 8


def test_the_cap_is_fixed_when_the_queue_is_built(clock):
    # 3 pages read: a cap of 20 + 4 = 24 requests, robots.txt included: 12 other sites, 2 requests each.
    result = audit(site(pages=3, external=20), external_sites_max=25)
    heads = [url for url, purpose in other_site_requests(result) if purpose == "external_link_head"]
    held = result.structure.external
    assert held["requests"] <= held["cap"] == 24 and len(heads) == 12
    # The first 12 in the queue's order, whichever answered first.
    assert set(heads) == {f"https://other-{i}.test/sayfa" for i in range(12)}
    assert result.structure.other_site_links_not_checked.get("cap") == 8


def test_another_sites_crawl_delay_is_kept_between_its_own_requests(clock):
    def other(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nCrawl-delay: 5\n", headers={"content-type": "text/plain"})
        if request.method == "HEAD":
            return httpx.Response(405)
        return None

    result = audit(site(pages=3, external=1, other=other))
    rows = [r for r in result.requests if "other-0" in r.url]
    assert [r.purpose for r in rows] == ["robots", "external_link_head", "external_link_status"]
    gaps, _ = gaps_by_host(rows)
    assert min(gaps["other-0.test"]) >= 5000 - 1
    assert result.backoff["host_gaps_s"] == {"other-0.test": 5.0}


def test_the_time_limit_during_the_pool_leaves_what_was_not_sent_not_checked_time_limit(clock):
    def other(request):
        clock.advance(40.0)  # another site that takes 40 s to answer
        return None

    result = audit(site(pages=3, external=8, other=other), time_limit_s=200.0)
    unchecked = result.structure.other_site_links_not_checked
    assert unchecked.get("time_limit", 0) >= 1
    assert "other_site_links" in result.skipped_for_time
    sent = {url for url, purpose in other_site_requests(result) if purpose == "external_link_head"}
    for url in result.structure.other_site_links:
        assert url in sent


# -- (e) adaptive pacing --------------------------------------------------------------------------------------------------

def fetcher(clock, statuses=None, ttfb_s=0.2):
    """A fetcher with adaptive pacing on, for the cafe; each answer takes `ttfb_s` of the fake clock."""
    answers = list(statuses or [])

    def handler(request):
        clock.advance(ttfb_s)
        status = answers.pop(0) if answers else 200
        return httpx.Response(status, text="ok")

    f = Fetcher("Maya-Audit/0.2", 15.0, 1.0, httpx.MockTransport(handler))
    f.configure_pacing(CrawlConfig())
    f.site_host = HOST
    return f


def test_twenty_clean_answers_in_a_row_narrow_the_gap_down_to_the_floor(clock):
    f = fetcher(clock)
    for n in range(19):
        f.get(f"{KAFE}/s/{n}", "page", 1000)
    for n in range(5):  # ACC-4's comparison requests do not count
        f.get(f"{KAFE}/u/{n}", "ua_check", 1000)
    assert f.narrowings == [] and f.delay_s == 1.0
    f.get(f"{KAFE}/s/19", "page", 1000)
    assert f.narrowings == [{"from_s": 1.0, "to_s": 0.75, "after_requests": 20}] and f.delay_s == 0.75
    for n in range(60):
        f.get(f"{KAFE}/t/{n}", "page", 1000)
    assert f.delay_s == 0.5 and [n["to_s"] for n in f.narrowings] == [0.75, 0.562, 0.5]
    # Never below the floor between two requests to the cafe.
    gaps, _ = gaps_by_host(f.log)
    assert min(gaps[HOST]) >= 500 - 1


def test_a_503_puts_the_gap_back_and_stops_the_narrowing_for_the_rest_of_the_audit(clock):
    f = fetcher(clock, statuses=[200] * 20 + [503])
    for n in range(21):
        f.get(f"{KAFE}/s/{n}", "page", 1000)
    assert f.delay_s == 1.0 and f.narrowing_stopped["status"] == 503 and f.narrowings[0]["to_s"] == 0.75
    for n in range(40):
        f.get(f"{KAFE}/t/{n}", "page", 1000)
    assert f.delay_s == 1.0 and len(f.narrowings) == 1


def test_a_slow_first_byte_breaks_the_run_and_one_over_2_s_stops_the_narrowing(clock):
    f = fetcher(clock, ttfb_s=1.8)  # neither clean (over 1.5 s) nor too slow (2 s): no narrowing, no reset
    for n in range(25):
        f.get(f"{KAFE}/s/{n}", "page", 1000)
    assert f.narrowings == [] and f.narrowing_stopped is None
    g = fetcher(clock, ttfb_s=2.5)
    g.get(f"{KAFE}/s/0", "page", 1000)
    assert g.narrowing_stopped["ttfb_ms"] > 2000


def test_another_sites_answers_never_narrow_the_audited_sites_gap(clock):
    f = fetcher(clock)
    for n in range(30):
        f.get(f"https://other-0.test/{n}", "external_link_head", 0, method="HEAD")
    assert f.narrowings == []


def test_crawl_delay_2_is_never_narrowed(clock):
    def answer(request):
        clock.advance(0.1)
        return None

    result = audit(site(pages=30, robots="User-agent: *\nCrawl-delay: 2\nAllow: /\n", answer=answer), max_pages=31)
    assert result.backoff["narrowed"] == [] and result.backoff["floor_s"] == 2.0 and result.backoff["final_delay_s"] == 2.0
    gaps, _ = gaps_by_host(result.requests)
    assert min(gaps[HOST]) >= 2000 - 1


def test_a_fast_site_is_audited_at_the_narrowed_gap_and_int4_judges_it_on_the_floor_in_use(clock):
    def answer(request):
        clock.advance(0.1)
        return None

    outcome = run_audit(KAFE + "/", CrawlConfig(**{**BASE, "max_pages": 41}), site(pages=40, answer=answer))
    result = outcome.result
    assert result.backoff["narrowed"][0] == {"from_s": 1.0, "to_s": 0.75, "after_requests": 20}
    gate = next(g for g in outcome.gates if g.check_id == "INT-4")
    politeness = gate.evidence["politeness"]
    assert gate.state == "compliant", gate.summary
    assert politeness["required_gap_ms"] == min(n["to_s"] for n in politeness["narrowed"]) * 1000
    assert politeness["floor_s"] == 0.5 and politeness["adaptive_pacing"] is True
    assert politeness["by_host"][0]["host"] == HOST


# -- INT-4 per host --------------------------------------------------------------------------------------------------------

def record(seq, url, start, end, purpose="page"):
    return RequestRecord(seq=seq, url=url, purpose=purpose, user_agent="Maya-Audit/0.2", started_at="2026-10-15T10:00:00+00:00",
                         status=200, error=None, elapsed_ms=(end - start) * 1000, started_mono=start, ended_mono=end)


def test_int4_measures_gaps_per_host_overlapping_other_sites_are_compliant_and_a_short_gap_names_its_host():
    from types import SimpleNamespace

    from maya_audit.robots import RobotsPolicy

    allow = RobotsPolicy(url="", mode="allow_all", reason="test", status=404, error=None, bytes_read=0, truncated=False,
                         redirect_hops=[], robots=None)

    def result_with(records):
        return SimpleNamespace(requests=records, robots_policy_by_origin={KAFE: allow, "https://other-0.test": allow},
                               robots=[], backoff={"site_host": HOST, "narrowed": [], "host_gaps_s": {}, "final_delay_s": 1.0, "widenings": []}, sessions=[],
                               skipped_robots=[], pages=[], access=None, bot_info_check=None, deadline_hit=False,
                               origin=KAFE)

    cfg = CrawlConfig(request_delay_s=1.0)
    ok = [record(1, f"{KAFE}/robots.txt", 0.0, 0.1, "robots"), record(2, "https://other-0.test/robots.txt", 0.1, 0.2, "robots"),
          record(3, f"{KAFE}/", 1.1, 1.2), record(4, "https://other-0.test/a", 1.2, 1.3, "external_link_head")]
    gate = int4_crawler_identity(result_with(ok), cfg)
    assert gate.state == "compliant", gate.summary
    short = ok + [record(5, f"{KAFE}/b", 1.5, 1.6)]
    gate = int4_crawler_identity(result_with(short), cfg)
    assert gate.state == "violation" and "smallest gap between requests to demo-kafe.test was 300.0ms" in gate.summary


# -- the IDX-8 title for one group ------------------------------------------------------------------------------------------

def test_the_merged_idx8_title_says_one_group_and_many_groups():
    from maya_audit.checks.index import idx8_merged
    from maya_audit_web import strings, wording

    one = idx8_merged([{"urls": ["/a", "/b"]}], ["/a", "/b"], near=False, variant=False, evidence={}, launch_gated=[],
                      importance_tier=0)
    two = idx8_merged([{"urls": ["/a", "/b"]}, {"urls": ["/c", "/d"]}], ["/a", "/b", "/c", "/d"], near=False, variant=False,
                      evidence={}, launch_gated=[], importance_tier=0)
    assert one.title == "1 group of indexable pages that are copies or near-copies of each other (2 pages)"
    assert two.title == "2 groups of indexable pages that are copies or near-copies of each other (4 pages)"
    assert wording.title("IDX-8", one.title, "en")[0] == one.title
    strings.set_language("tr")
    try:
        assert wording.title("IDX-8", one.title)[0] == ("Dizine eklenebilir sayfalardan birbirinin kopyası veya neredeyse "
                                                         "kopyası olan 1 grup (2 sayfa)")
    finally:
        strings.set_language("en")
