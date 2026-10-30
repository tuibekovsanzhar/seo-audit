"""INT-1..INT-4 against the local fake websites.

Every test also checks the server's own request log, which is independent of
Maya's: robots.txt must be the first request, and paths the site forbids must
never arrive.
"""

import pytest

from maya_audit.models import Confidence, FetchClass, StopReason


def assert_server_side_compliance(run):
    assert run.server_paths[0] == "/robots.txt"
    forbidden = [p for p in run.server_paths if any(p.startswith(f) for f in run.scenario.must_not_request)]
    assert forbidden == []
    int4 = run.gates["INT-4"]
    assert int4.state == "compliant", int4.summary
    assert int4.evidence["user_agents_used"] == [run.config.user_agent]


def test_healthy_site(run_scenario):
    run = run_scenario("healthy")
    assert_server_side_compliance(run)

    int1 = run.gates["INT-1"]
    assert (int1.state, int1.confidence) == ("ok", Confidence.VERIFIED)

    int2 = run.gates["INT-2"]
    assert int2.state == "complete"
    assert run.result.stop_reason == StopReason.EXHAUSTED
    assert int2.evidence["sitemap_urls_listed"] == 3
    # Sitemap-last: the orphan is fetched, and marked as found only via the sitemap.
    assert int2.evidence["fetched_only_via_sitemap"] == [run.result.origin + "/landing-orphan"]
    assert run.page("/landing-orphan").depth is None
    assert int2.evidence["caveats"]  # one robots-skipped URL

    int3 = run.gates["INT-3"]
    assert int3.state == "disclosure"
    assert int3.evidence["rendered_pages"] == []
    assert all(p.view == "raw" for p in run.result.pages)
    assert [k["rendered"] for k in int3.evidence["key_pages"]] == [False, False]

    int4 = run.gates["INT-4"]
    [skip] = int4.evidence["skipped_by_robots"]
    assert skip["url"].endswith("/private/admin")
    assert skip["rule"] == {"directive": "disallow", "pattern": "/private/", "line": 2}


def test_cloudflare_challenge(run_scenario):
    run = run_scenario("cloudflare_challenge")
    assert_server_side_compliance(run)

    int1 = run.gates["INT-1"]
    assert (int1.state, int1.confidence) == ("degraded", Confidence.VERIFIED)
    start = int1.evidence["start_url"]
    assert start["fetch_class"] == "blocked"
    assert "header cf-mitigated: challenge" in start["evidence"]
    assert start["reproduce"].startswith("curl -i -A ")
    assert not run.page("/").content_checks_eligible
    assert "allowlist" in int1.how_to_fix

    int2 = run.gates["INT-2"]
    assert int2.state == "incomplete"  # the queue ran dry only because the start page was unreadable


def test_forbidden_mix_is_degraded_but_only_estimated(run_scenario):
    run = run_scenario("forbidden_mix")
    assert_server_side_compliance(run)

    int1 = run.gates["INT-1"]
    assert int1.state == "degraded"
    assert int1.confidence == Confidence.ESTIMATED
    assert int1.evidence["blocked_or_rate_limited"] == "2/6 (33.3%)"
    assert int1.evidence["blocked_or_rate_limited_verified_only"] == "1/6 (16.7%)"

    members, pricing, docs_a = run.page("/members"), run.page("/pricing"), run.page("/docs/a")
    assert (members.fetch_class, members.classification_confidence) == (FetchClass.BLOCKED, Confidence.VERIFIED)
    assert (pricing.fetch_class, pricing.classification_confidence) == (FetchClass.BLOCKED, Confidence.ESTIMATED)
    assert docs_a.fetch_class == FetchClass.OK  # injected challenge script alone is not a block


def test_rate_limit_stops_the_crawl_early(run_scenario):
    run = run_scenario("rate_limited")
    assert_server_side_compliance(run)
    assert run.result.stop_reason == StopReason.RATE_LIMIT
    assert "120s" in run.result.stop_detail

    int2 = run.gates["INT-2"]
    assert int2.state == "incomplete"
    assert int2.evidence["not_fetched"]["count"] == 3
    # No request after the one that asked for a 120 s wait.
    assert run.server_paths[-1] == "/p3"

    int1 = run.gates["INT-1"]
    assert int1.state == "degraded" and int1.evidence["by_fetch_class"] == {"ok": 3, "rate_limited": 1}


def test_transient_429_is_retried_once(run_scenario):
    run = run_scenario("rate_limited_transient")
    assert_server_side_compliance(run)
    flaky = run.page("/flaky")
    assert flaky.fetch_class == FetchClass.OK and flaky.retried_after_429
    assert run.server_paths.count("/flaky") == 2
    assert run.gates["INT-2"].state == "complete"


@pytest.mark.parametrize("name", ["robots_block", "robots_503"])
def test_robots_disallow_stops_everything(run_scenario, name):
    run = run_scenario(name)
    assert_server_side_compliance(run)
    assert run.server_paths == ["/robots.txt"]
    assert run.result.stop_reason == StopReason.ROBOTS_DISALLOWED
    assert run.gates["INT-1"].state == "not_assessed"
    assert run.gates["INT-1"].confidence == Confidence.NOT_ASSESSED
    assert run.gates["INT-2"].state == "incomplete"
    mode = run.gates["INT-4"].evidence["robots"][0]["mode"]
    assert mode == ("parsed" if name == "robots_block" else "disallow_all")


def test_specific_robots_group_for_maya(run_scenario):
    run = run_scenario("robots_maya_group")
    assert_server_side_compliance(run)
    assert "/public" in run.server_paths
    int4 = run.gates["INT-4"]
    assert int4.evidence["robots"][0]["matched_group_kind"] == "specific"
    [skip] = int4.evidence["skipped_by_robots"]
    assert skip["rule"]["line"] == 6  # "Disallow: /private/" under "User-agent: Maya-Audit" (line 5)
    assert run.gates["INT-2"].state == "complete"


def test_page_cap_stops_the_crawl_early(run_scenario):
    run = run_scenario("page_cap")
    assert_server_side_compliance(run)
    assert run.result.stop_reason == StopReason.PAGE_CAP
    int2 = run.gates["INT-2"]
    assert int2.state == "incomplete"
    assert int2.evidence["pages_counted_toward_cap"] == 10
    assert int2.evidence["not_fetched"]["count"] == 21
    assert "Raise the page cap" in int2.how_to_fix


def test_transport_errors(run_scenario):
    run = run_scenario("transport_errors")
    assert_server_side_compliance(run)
    slow, drop = run.page("/slow"), run.page("/drop")
    assert slow.fetch_class == FetchClass.ERROR and slow.error.startswith("timeout")
    assert drop.fetch_class == FetchClass.ERROR and drop.error.startswith("connection_dropped")
    int1 = run.gates["INT-1"]
    assert int1.state == "ok"  # transport errors are not blocks
    assert int1.evidence["content_checks_suppressed_on"] == 2
    assert run.gates["INT-2"].state == "incomplete"


def test_time_limit_stops_the_crawl_early(run_scenario):
    run = run_scenario("time_limit")
    assert_server_side_compliance(run)
    assert run.result.stop_reason == StopReason.TIME_LIMIT
    assert run.gates["INT-2"].state == "incomplete"
    assert run.gates["INT-2"].evidence["not_fetched"]["count"] > 0


def test_start_redirect_is_followed_and_not_counted_as_a_page(run_scenario):
    run = run_scenario("start_redirect")
    assert_server_side_compliance(run)
    root = run.page("/")
    assert root.status == 301 and root.redirect_location == run.result.origin + "/home"
    int2 = run.gates["INT-2"]
    assert int2.evidence["redirect_responses"] == 1
    assert int2.evidence["pages_counted_toward_cap"] == 2
    assert int2.state == "complete"


def test_int4_flags_a_request_to_a_disallowed_url(run_scenario):
    """The compliance audit must catch a violation, not just report success."""
    from dataclasses import replace

    from maya_audit.checks.integrity import int4_crawler_identity

    run = run_scenario("healthy")
    bad = replace(run.result.requests[-1], seq=999, url=run.result.origin + "/private/admin")
    tampered = replace(run.result, requests=[*run.result.requests, bad])
    gate = int4_crawler_identity(tampered, run.config)
    assert gate.state == "violation"
    assert gate.evidence["requests_to_disallowed_urls"][0]["url"].endswith("/private/admin")


def test_sitemap_discovery_cannot_starve_the_page_crawl(run_scenario):
    """One real site had 50 sitemap documents listing 8,133 URLs: fetching them used the whole time
    limit and the crawl fetched a single page. Discovery gets a share of the budget and discloses it."""
    starved = run_scenario("healthy", sitemap_time_share=0.0)
    assert starved.result.sitemap_docs == []          # discovery yielded immediately
    assert len(starved.result.pages) > 1              # the crawl still ran
    note = starved.result.sitemap_notes[0]
    assert "stopped after 0 document(s)" in note and "partial" in note
    assert note in starved.gates["INT-2"].evidence["caveats"]  # disclosed, not silent

    normal = run_scenario("healthy")
    assert normal.result.sitemap_docs and not normal.result.sitemap_notes


def test_key_pages_are_always_crawled(run_scenario):
    """Marking a page key must guarantee it is audited. The first client audit set five key pages and
    four were never fetched: they were outside the page cap, and key pages only affected sampling."""
    # /landing-orphan is sitemap-only, and sitemap URLs are fetched last, so a 3-page cap never reaches it.
    without = run_scenario("healthy", max_pages=3)
    assert not any(p.url.endswith("/landing-orphan") for p in without.result.pages)

    run = run_scenario("healthy", max_pages=3, key_pages=("/landing-orphan",))
    page = next((p for p in run.result.pages if p.url.endswith("/landing-orphan")), None)
    assert page is not None and page.discovered_via == "key_page" and page.status == 200
    assert run.gates["INT-4"].state == "compliant"  # still robots-checked and paced like any other fetch


def test_politeness_is_measured_on_the_monotonic_clock(run_scenario):
    """Found on the first live crawl of a real site: INT-4 mixed a wall-clock start with a monotonic
    duration, so a clock adjustment mid-run reported a politeness violation that never happened."""
    from datetime import datetime, timedelta

    from maya_audit.checks.integrity import int4_crawler_identity

    run = run_scenario("healthy", request_delay_s=0.2)
    assert run.gates["INT-4"].state == "compliant"

    # NTP steps the wall clock back 600ms halfway through. The fetcher paced correctly regardless.
    records = run.result.requests
    for record in records[len(records) // 2:]:
        record.started_at = (datetime.fromisoformat(record.started_at) - timedelta(milliseconds=600)).isoformat()

    gate = int4_crawler_identity(run.result, run.config)
    assert gate.state == "compliant", gate.summary
    assert gate.evidence["politeness"]["measured_on"] == "monotonic"

    # Without monotonic stamps (an older report) the wall-clock fallback is used, and says so.
    for record in records:
        record.started_mono = record.ended_mono = None
    fallback = int4_crawler_identity(run.result, run.config)
    assert fallback.evidence["politeness"]["measured_on"].startswith("wall clock")
    assert fallback.state == "violation"  # the false positive the live run hit


def test_rate_limit_widens_the_gap_for_the_rest_of_the_crawl(run_audit_scenario):
    """A site that says "slow down" is telling us about the whole crawl, not about one URL.

    Ported from OpenSEO's crawl throttle: the interval grows on a refusal and is never narrowed
    again. Pausing and then resuming at a pace the site has already refused is how a polite crawler
    becomes a rude one.
    """
    run = run_audit_scenario("rate_limited_then_recovers", request_delay_s=0.01,
                             rate_limit_backoff_factor=2.0, max_request_delay_s=1.0)
    backoff = run.result.backoff
    assert backoff["configured_delay_s"] == 0.01
    # Two refusals, so two doublings, and the final delay is the widened one.
    assert [w["to_s"] for w in backoff["widenings"]] == [0.02, 0.04]
    assert backoff["final_delay_s"] == 0.04
    assert len(backoff["notes"]) == 2
    assert "widened to" in backoff["notes"][0]


def test_the_widened_gap_is_reported_by_int4(run_audit_scenario):
    """Politeness is what INT-4 audits, so a backoff it cannot see is a backoff nobody can check."""
    run = run_audit_scenario("rate_limited_then_recovers", request_delay_s=0.01,
                             rate_limit_backoff_factor=2.0, max_request_delay_s=1.0)
    politeness = run.gates["INT-4"].evidence["politeness"]
    assert politeness["configured_delay_s"] == 0.01
    assert politeness["final_delay_s"] == 0.04
    assert len(politeness["widened_after_rate_limit"]) == 2
    # Widening only ever increases the gap, so the gate's own invariant still holds.
    assert run.gates["INT-4"].state == "compliant"
    assert politeness["min_observed_gap_ms"] + politeness["tolerance_ms"] >= politeness["required_gap_ms"]


def test_backoff_stops_at_the_ceiling(run_audit_scenario):
    """Backoff must not be able to stall a crawl indefinitely."""
    run = run_audit_scenario("rate_limited_then_recovers", request_delay_s=0.01,
                             rate_limit_backoff_factor=10.0, max_request_delay_s=0.05)
    widenings = run.result.backoff["widenings"]
    assert [w["to_s"] for w in widenings] == [0.05]  # capped on the first refusal, then no more
    assert run.result.backoff["final_delay_s"] == 0.05


def test_a_clean_crawl_records_no_widening(run_audit_scenario):
    run = run_audit_scenario("healthy")
    backoff = run.result.backoff
    assert backoff["widenings"] == [] and backoff["notes"] == []
    assert backoff["final_delay_s"] == backoff["configured_delay_s"]


def test_a_politely_relentless_site_stops_the_crawl_on_the_cooldown_budget(run_audit_scenario):
    """Each refusal is short enough to honour, so only the cumulative budget can end this.

    Without it a site that refuses every page with a one-second Retry-After would be retried until
    the page cap or time limit ran out, which is a long time to keep asking a server that has said
    no to every single request.
    """
    run = run_audit_scenario("rate_limited_slow_drip", request_delay_s=0.0,
                             rate_limit_stop_after=99, max_total_cooldown_s=1.5)
    assert run.result.stop_reason.value == "rate_limit"
    assert "waiting out rate limits" in run.result.stop_detail
    assert "over the 2s allowed" in run.result.stop_detail
    assert run.result.backoff["total_cooldown_s"] >= 1.5
