"""The SQLite frontier, and what resuming a crawl is allowed to claim.

The frontier tests pin traversal order and the seen-set, because both were in-memory semantics that
a table can quietly get wrong. The resume tests pin the things that make a resumed crawl honest:
robots is re-fetched, the backoff delay is inherited, and the INT gates say the audit was assembled
from more than one session rather than implying one continuous run.
"""

import pytest

from fakeserver import FakeServer, SCENARIOS
from maya_audit.audit import run_audit
from maya_audit.config import CrawlConfig
from maya_audit.scratchpad import (BLOCKED, CRAWLED, MEMORY, QUEUED, RATE_LIMITED, FrontierUrl,
                                   Scratchpad, robots_fingerprint)

FAST = {"request_delay_s": 0.0, "robots_sample_interval_s": 0.05, "refetch_delay_s": 0.0,
        "prf_round_gap_s": 0.0, "render_enabled": False, "probes_enabled": False}


def drain(pad):
    out = []
    while (claimed := pad.get_next_url()) is not None:
        out.append(claimed.url)
        pad.mark_status(claimed.url, CRAWLED)
    return out


def test_traversal_order_matches_the_queues_it_replaced():
    """Redirects jump the queue, links follow in discovery order, sitemap URLs come last."""
    pad = Scratchpad(MEMORY)
    pad.add_urls([FrontierUrl("http://s/", 0, "start", None)])
    pad.add_urls([FrontierUrl("http://s/sm", None, "sitemap", None)])
    pad.add_urls([FrontierUrl("http://s/a", 1, "link", "http://s/"),
                  FrontierUrl("http://s/b", 1, "link", "http://s/")])
    pad.add_urls([FrontierUrl("http://s/r", 1, "redirect", "http://s/a")])
    assert drain(pad) == ["http://s/r", "http://s/", "http://s/a", "http://s/b", "http://s/sm"]


def test_link_discovery_upgrades_a_queued_sitemap_url():
    pad = Scratchpad(MEMORY)
    pad.add_urls([FrontierUrl("http://s/a", None, "sitemap", None)])
    pad.add_urls([FrontierUrl("http://s/a", 1, "link", "http://s/")])
    assert pad.get_next_url() == FrontierUrl("http://s/a", 1, "link", "http://s/")
    pad.close()


def test_the_primary_key_is_the_seen_set():
    """A URL already crawled must never be re-queued by a later link to it."""
    pad = Scratchpad(MEMORY)
    pad.add_urls([FrontierUrl("http://s/a", 0, "start", None)])
    pad.mark_status("http://s/a", CRAWLED)
    assert pad.add_urls([FrontierUrl("http://s/a", 5, "link", "http://s/b")]) == 0
    assert pad.counts() == {CRAWLED: 1}
    assert pad.get_next_url() is None


def test_a_claim_is_not_a_completion():
    """A process killed mid-fetch must leave the URL claimable, not silently lost."""
    pad = Scratchpad(MEMORY)
    pad.add_urls([FrontierUrl("http://s/a", 0, "start", None)])
    claimed = pad.get_next_url()
    assert claimed.url == "http://s/a"
    assert pad.counts() == {QUEUED: 1}  # still queued: the fetch has not resolved
    reopened = Scratchpad(pad.path) if pad.path != MEMORY else pad
    assert reopened.urls_with_status(QUEUED) == ["http://s/a"]


def test_every_outcome_is_recorded(tmp_path):
    pad = Scratchpad(str(tmp_path / "f.db"))
    for i, status in enumerate((CRAWLED, BLOCKED, RATE_LIMITED)):
        pad.add_urls([FrontierUrl(f"http://s/{i}", 0, "link", None)])
        pad.mark_status(f"http://s/{i}", status)
    assert pad.counts() == {CRAWLED: 1, BLOCKED: 1, RATE_LIMITED: 1}


def test_an_unknown_status_is_refused():
    pad = Scratchpad(MEMORY)
    pad.add_urls([FrontierUrl("http://s/a", 0, "start", None)])
    with pytest.raises(ValueError, match="unknown frontier status"):
        pad.mark_status("http://s/a", "probably_fine")


def test_reopening_without_resume_refuses_rather_than_overwriting(tmp_path):
    """Silently starting a fresh crawl over a saved frontier would destroy the thing --resume needs."""
    path = str(tmp_path / "f.db")
    first = Scratchpad(path)
    first.add_urls([FrontierUrl("http://s/a", 0, "start", None)])
    first.close()
    with pytest.raises(ValueError, match="already holds a crawl"):
        Scratchpad(path)
    resumed = Scratchpad(path, resume=True)
    assert resumed.resumed and resumed.session_no == 2
    assert resumed.urls_with_status(QUEUED) == ["http://s/a"]


def test_a_changed_robots_between_sessions_is_detectable(tmp_path):
    path = str(tmp_path / "f.db")
    first = Scratchpad(path)
    first.finish_session(robots_sha256=robots_fingerprint("User-agent: *\nAllow: /\n"))
    first.close()
    second = Scratchpad(path, resume=True)
    same = robots_fingerprint("User-agent: *\nAllow: /\n")
    changed = robots_fingerprint("User-agent: *\nDisallow: /\n")
    assert second.robots_changed_since_last_session(same) is None
    assert second.robots_changed_since_last_session(changed) is not None


def test_meta_survives_a_session(tmp_path):
    path = str(tmp_path / "f.db")
    first = Scratchpad(path)
    first.set_meta("final_delay_s", 4.0)
    first.close()
    assert Scratchpad(path, resume=True).get_meta("final_delay_s") == 4.0


# -- the crawler on top of it -------------------------------------------------

def run_on(scenario, tmp_path, name="f.db", **overrides):
    with FakeServer(SCENARIOS[scenario].build()) as site:
        config = CrawlConfig(**{**FAST, **overrides}, db_path=str(tmp_path / name))
        return run_audit(site.base_url + "/", config), site.base_url


def test_a_normal_crawl_records_one_session(tmp_path):
    outcome, _ = run_on("healthy", tmp_path)
    assert len(outcome.result.sessions) == 1
    politeness = next(g for g in outcome.gates if g.check_id == "INT-4").evidence["politeness"]
    assert politeness["sessions"]["count"] == 1
    assert "assembled_from" not in politeness["sessions"]
    int2 = next(g for g in outcome.gates if g.check_id == "INT-2")
    assert int2.evidence["session_windows"] is None


def test_a_resumed_crawl_says_so_in_both_gates(tmp_path):
    """The whole point of the resume design: the gates must not imply one continuous run."""
    db = str(tmp_path / "r.db")
    with FakeServer(SCENARIOS["healthy"].build()) as site:
        run_audit(site.base_url + "/", CrawlConfig(**FAST, db_path=db, max_pages=1))
        second = run_audit(site.base_url + "/", CrawlConfig(**FAST, db_path=db, resume=True))
    assert len(second.result.sessions) == 2
    politeness = next(g for g in second.gates if g.check_id == "INT-4").evidence["politeness"]["sessions"]
    assert politeness["count"] == 2 and politeness["this_session"] == 2
    assert len(politeness["assembled_from"]) == 2
    assert "judged per session" in politeness["note"]
    int2 = next(g for g in second.gates if g.check_id == "INT-2")
    assert "assembled from 2 sessions" in int2.summary
    assert len(int2.evidence["session_windows"]) == 2


def test_a_resumed_crawl_does_not_refetch_what_the_first_one_fetched(tmp_path):
    db = str(tmp_path / "r.db")
    with FakeServer(SCENARIOS["healthy"].build()) as site:
        first = run_audit(site.base_url + "/", CrawlConfig(**FAST, db_path=db, max_pages=1))
        second = run_audit(site.base_url + "/", CrawlConfig(**FAST, db_path=db, resume=True))
    already = {p.url for p in first.result.pages}
    assert already and not already & {r.url for r in second.result.requests if r.purpose == "page"}
    # ... and the resumed report still covers them: they are read back from the crawl database.
    assert already < {p.url for p in second.result.pages}


def test_a_resumed_crawl_inherits_the_previous_session_s_backoff(tmp_path):
    """Resuming at full speed against a site that rate-limited us would undo the backoff it earned."""
    db = str(tmp_path / "r.db")
    with FakeServer(SCENARIOS["rate_limited_then_recovers"].build()) as site:
        first = run_audit(site.base_url + "/", CrawlConfig(
            **{**FAST, "request_delay_s": 0.01}, db_path=db, max_pages=3,
            rate_limit_backoff_factor=2.0, max_request_delay_s=1.0))
        widened = first.result.backoff["final_delay_s"]
        assert widened > 0.01, "the scenario should have rate-limited us"
        second = run_audit(site.base_url + "/", CrawlConfig(
            **{**FAST, "request_delay_s": 0.01}, db_path=db, resume=True,
            rate_limit_backoff_factor=2.0, max_request_delay_s=1.0))
    # The second session starts at the pace the first one ended on, not at the configured delay.
    assert second.result.backoff["final_delay_s"] >= widened


def test_the_session_row_counts_every_request_the_session_made(tmp_path):
    """Found by the first live run: the session closed before the collection pass.

    `post_crawl` (ACC/IDX/RND/STR/PRF/ANS collection) made 441 of 455 requests on a real 10-page
    crawl. A session row recorded before it ran reported 14, so INT-4's per-session politeness
    figures on a resumed crawl would have been computed over a fraction of each session.
    """
    outcome, _ = run_on("healthy", tmp_path)
    session = outcome.result.sessions[-1]
    assert session["requests"] == len(outcome.result.requests)
    assert session["finished_at"]
    # And the gate's own request tally agrees with the row it lists.
    int4 = next(g for g in outcome.gates if g.check_id == "INT-4")
    assert session["requests"] == sum(int4.evidence["requests_by_purpose"].values())


def test_the_session_gap_matches_what_int4_measures(tmp_path):
    """Also found live: counting render subresources put 0.0 ms in a row INT-4 called compliant.

    Those are a burst inside one page render, not a pacing failure. INT-4 excludes them; the session
    row has to exclude them too, or the per-session table contradicts the gate that owns politeness.
    """
    outcome, _ = run_on("healthy", tmp_path, request_delay_s=0.05)
    session = outcome.result.sessions[-1]
    politeness = next(g for g in outcome.gates if g.check_id == "INT-4").evidence["politeness"]
    assert session["min_gap_ms"] == politeness["min_observed_gap_ms"]


def test_reading_a_frontier_does_not_open_a_session(tmp_path):
    """Found on the first live resume test: an inspection between two crawls became session 2.

    The gates then reported "assembled from 3 sessions" for two crawls, with an empty row in
    INT-4's per-session table.
    """
    path = str(tmp_path / "f.db")
    first = Scratchpad(path)
    first.add_urls([FrontierUrl("http://s/a", 0, "start", None)])
    first.finish_session(requests=1)
    first.close()

    for _ in range(3):
        reader = Scratchpad.read_only(path)
        assert reader.counts() == {QUEUED: 1}
        reader.close()
    assert len(Scratchpad.read_only(path).sessions()) == 1  # still one, after four reads


def test_an_unfinished_session_is_reported_but_not_counted(tmp_path):
    """A killed crawl leaves a row with no figures; it must not pad the assembled-from count."""
    db = str(tmp_path / "r.db")
    with FakeServer(SCENARIOS["healthy"].build()) as site:
        run_audit(site.base_url + "/", CrawlConfig(**FAST, db_path=db, max_pages=1))
        abandoned = Scratchpad(db, resume=True)      # opens a session, never finishes it
        abandoned.close()
        second = run_audit(site.base_url + "/", CrawlConfig(**FAST, db_path=db, resume=True))
    politeness = next(g for g in second.gates if g.check_id == "INT-4").evidence["politeness"]["sessions"]
    assert politeness["count"] == 2                       # two real crawls, not three
    assert politeness["sessions_that_never_finished"] == [2]
    int2 = next(g for g in second.gates if g.check_id == "INT-2")
    assert "assembled from 2 sessions" in int2.summary
