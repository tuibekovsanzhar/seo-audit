"""PRF-1..PRF-3 against local fake websites and fake PageSpeed Insights / CrUX APIs."""

import json

import httpx

import pytest

from fakeserver import FakeServer
from fakeserver.prf_scenarios import FAST_PRF, crux_api, prf_site, psi_api
from maya_audit.audit import run_audit
from maya_audit.checks.perf import nearest_rank
from maya_audit.config import CrawlConfig
from maya_audit.report import build_report


def paths(item):
    return sorted(u.split("//", 1)[1].split("/", 1)[1] or "/" for u in item.scope["urls"])


def only(findings, text):
    [match] = [f for f in findings if text in f.title]
    return match


@pytest.fixture(scope="module")
def mixed():
    from fakeserver.prf_scenarios import PRF_SCENARIOS

    scenario = PRF_SCENARIOS["prf_mixed"]
    with FakeServer(scenario.build()) as site:
        options = {**scenario.config, "key_pages": tuple(site.base_url + p for p in scenario.config["key_pages"])}
        outcome = run_audit(site.base_url + "/", CrawlConfig(**options))
        return outcome, list(site.requests), site.base_url


def _checks(outcome):
    return {c.check_id: c for c in outcome.checks}


def test_response_time_uses_the_median_of_repeated_samples(mixed):
    outcome, requests, base = mixed
    prf1 = _checks(outcome)["PRF-1"]
    slow = only(prf1.findings, "(median)")
    assert paths(slow) == ["slow"] and slow.severity.value == "S4" and slow.confidence.value == "estimated"
    row = slow.evidence["pages"][0]
    assert row["successful_samples"] == 3 and row["median_total_ms"] > 300
    assert [s["source"] for s in row["samples"]] == ["crawl", "prf_round_2", "prf_round_3"]
    assert all(s["ttfb_ms"] is not None and s["ttfb_ms"] <= s["total_ms"] for s in row["samples"])
    assert "not recorded" in slow.evidence["egress_region"]
    measured = {r["url"].rsplit("/", 1)[-1]: r for r in prf1.evidence["measured"]}
    assert measured["slow-once"]["p90_total_ms"] > 300 and measured["slow-once"]["median_total_ms"] < 300  # one slow sample
    too_few = {r["url"].rsplit("/", 1)[-1] for r in prf1.evidence["not_enough_samples"]}
    assert too_few == {"flaky", "always-500", "fails-twice"}  # flaky: 2 of 3 succeeded; fails-twice: 2 of 4
    why = {i["url"].rsplit("/", 1)[-1] or "/": i["why"] for i in outcome.result.perf.sample}
    assert why["slow"] == why["slow-once"] == why["flaky"] == "user-marked key page"
    assert why["/"] == "homepage" and why["a"].startswith("template /blog/")
    assert why["always-500"] == why["hang-once"] == why["fails-twice"] == "failed during the crawl"
    assert "b" not in why  # one page per template, and only 1 template slot in this run


def test_intermittent_timeout_is_prf1_and_persistent_failure_is_idx1(mixed):
    outcome, requests, base = mixed
    checks = _checks(outcome)
    timeout = only(checks["PRF-1"].findings, "time out on some attempts")
    assert paths(timeout) == ["hang-once"] and timeout.confidence.value == "verified"
    idx1 = checks["IDX-1"]
    [persistent] = idx1.findings
    assert paths(persistent) == ["always-500"]
    assert len(persistent.evidence["pages"][0]["attempts"]) == 4  # crawl, refetch, two PRF rounds: all 500
    intermittent = {o["url"].rsplit("/", 1)[-1] for o in idx1.observations if "intermittent" in o["metric"]}
    # fails-twice failed on the crawl AND the refetch; only the PRF rounds show it works, so it is not an IDX-1 S1.
    assert intermittent == {"hang-once", "reset-once", "fails-twice"}


def test_reliability(mixed):
    outcome, requests, base = mixed
    prf2 = _checks(outcome)["PRF-2"]
    flaky = only(prf2.findings, "some attempts")
    assert paths(flaky) == ["fails-twice", "flaky", "reset-once"]  # the timeout-only URL is PRF-1's
    rows = {r["url"].rsplit("/", 1)[-1]: r for r in flaky.evidence["pages"]}
    assert (rows["flaky"]["failures"], rows["flaky"]["attempts"]) == (1, 3)
    rate = only(prf2.findings, "of fetches failed")
    assert rate.scope["kind"] == "sitewide" and rate.evidence["failures"] == 5
    assert prf2.evidence["urls_failing_every_attempt_left_to_IDX-1"] == [base + "/always-500"]
    assert prf2.evidence["blocked_or_rate_limited_attempts_not_counted"] == 1  # the challenge page
    # Seen from the server: 3 fetches of each sampled page, 4 of the ones that failed in the crawl, 1 of the challenge.
    # /blog/b: the crawl, and the browser and Googlebot pair of ACC-4's small check, which since DECISIONS 216 takes
    # the largest template's second page where it took an empty page.
    counts = {}
    for r in requests:
        counts[r.route_path] = counts.get(r.route_path, 0) + 1
    assert (counts["/slow"], counts["/flaky"], counts["/always-500"], counts["/hang-once"], counts["/blocked"],
            counts["/blog/b"]) == (3, 3, 4, 4, 1, 3)
    assert [r.url.rsplit("/", 2)[-2:] for r in outcome.result.requests if r.purpose == "ua_check" and r.url.endswith("/blog/b")] == [["blog", "b"]] * 2
    assert {g.check_id: g.state for g in outcome.gates}["INT-4"] == "compliant"


def test_healthy_site_rate_not_judged_below_minimum(run_audit_scenario):
    run = run_audit_scenario("prf_healthy")
    assert run.checks["PRF-1"].status == "pass" and run.checks["PRF-2"].status == "pass"
    [obs] = run.checks["PRF-2"].observations
    assert obs["attempts"] == 9 and obs["minimum_attempts"] == 20


def test_no_extra_requests_after_rate_limiting(run_audit_scenario):
    run = run_audit_scenario("rate_limited")
    assert run.result.perf.skipped_reason.startswith("the crawl stopped because the site rate-limited")
    assert not [r for r in run.result.requests if r.purpose == "prf_sample"]
    assert run.checks["PRF-1"].status == "not_assessed" and run.checks["PRF-2"].status == "not_assessed"
    paths_seen = [r.path for r in run.requests]
    assert {p for p in paths_seen if paths_seen.count(p) > 1} == {"/robots.txt"}  # only ACC-1's robots samples repeat


def test_no_prf_flag_leaves_prf_not_assessed(run_audit_scenario):
    run = run_audit_scenario("prf_healthy", prf_enabled=False)
    assert run.checks["PRF-1"].status == "not_assessed" and "--no-prf" in run.checks["PRF-1"].summary
    assert run.checks["PRF-2"].status == "not_assessed"


def test_nearest_rank_percentile():
    assert nearest_rank([100, 300, 200], 90) == 300
    assert nearest_rank(list(range(1, 11)), 90) == 9


def run_pagespeed(verified: bool, api_mock=None, *, first_lookup_timeout=False):
    token = "owner-token" if verified else None
    with FakeServer(prf_site(token)) as site, FakeServer(psi_api()) as psi, FakeServer(crux_api(lambda: site.base_url)) as crux:
        config = CrawlConfig(**{**FAST_PRF, "prf_enabled": False}, key_pages=(site.base_url + "/", site.base_url + "/slow"),
                             pagespeed_enabled=True, google_api_key="psi-test-key-123", probes_enabled=False,
                             psi_endpoint=psi.base_url + "/pagespeedonline/v5/runPagespeed",
                             crux_endpoint=crux.base_url + "/v1/records:queryRecord", site_verification_token=token)
        if api_mock is not None:
            # Ownership/request-count contract: deterministic API responses, real loopback site.
            # The verified-site integration above still uses actual loopback API servers.
            from fakeserver.server import RequestSeen
            from maya_audit import perf_data
            import time
            def response(request):
                server = crux if str(request.url).startswith(crux.base_url + '/') else psi
                assert str(request.url).startswith(server.base_url + '/')
                seen = RequestSeen(len(server.requests)+1, request.url.raw_path.decode(),
                                   request.headers.get('user-agent',''), time.time(),
                                   headers={k.lower(): v for k, v in request.headers.items()},
                                   method=request.method, body=request.content)
                server.requests.append(seen)
                if first_lookup_timeout and server is crux and len(crux.requests)==1:
                    raise httpx.ReadTimeout('controlled missing URL lookup', request=request)
                reply = server.site.resolve(seen)
                return httpx.Response(reply.status, content=reply.body,
                                      headers={'content-type':reply.content_type}, request=request)
            api_mock.setattr(perf_data, 'PublicTransport', lambda **kw: httpx.MockTransport(response))
        outcome = run_audit(site.base_url + "/", config)
        return outcome, list(psi.requests), list(crux.requests), site.base_url


def test_pagespeed_lab_and_field_on_verified_site():
    outcome, psi_requests, crux_requests, base = run_pagespeed(verified=True)
    prf3 = _checks(outcome)["PRF-3"]
    assert len(psi_requests) == 6  # 3 runs x 2 key pages
    assert {r.query["strategy"] for r in psi_requests} == {"mobile"}
    home = next(o for o in prf3.observations if o["url"] == base + "/")
    lab = next(v for k, v in home.items() if k.startswith("lab"))
    assert lab["LCP (ms)"] == {"median": 2500.0, "runs": 3}
    field = next(v for k, v in home.items() if k.startswith("field"))
    assert field["scope"] == "url" and field["p75"]["INP p75 (ms)"] == 120
    poor = {f.title.split("real-user ")[1].split(" in")[0]: f for f in prf3.findings}
    assert set(poor) == {"LCP p75 (ms)", "CLS p75"}  # /slow falls back to origin data: LCP 4600, CLS "0.31"
    assert all(f.severity.value == "Info" and f.cost_tier == "T2" for f in prf3.findings)
    assert poor["CLS p75"].evidence["values"][0]["scope"] == "origin"
    report = json.dumps(build_report(outcome.result, outcome.gates, outcome.checks))
    assert "psi-test-key-123" not in report  # key redacted everywhere
    assert '"categories"' not in report  # Lighthouse category scores are not read or shown; numeric timestamps vary
    prf1 = _checks(outcome)["PRF-1"]
    assert prf1.evidence["crux_field_ttfb_p75"][0]["ttfb_p75_ms"] == 600


def test_pagespeed_lab_runs_need_ownership(monkeypatch):
    outcome, psi_requests, crux_requests, base = run_pagespeed(verified=False, api_mock=monkeypatch)
    assert psi_requests == []  # Google's servers were never asked to load an unverified site
    assert len(crux_requests) == 3  # "/" by URL; "/slow" by URL (404) then origin
    prf3 = _checks(outcome)["PRF-3"]
    lab = next(v for k, v in prf3.observations[0].items() if k.startswith("lab"))
    assert lab["assessed"] is False and "ownership-verified" in lab["reason"]


def test_pagespeed_without_key_is_not_assessed(run_audit_scenario):
    run = run_audit_scenario("prf_healthy", pagespeed_enabled=True)
    assert run.checks["PRF-3"].status == "not_assessed" and "MAYA_AUDIT_GOOGLE_API_KEY" in run.checks["PRF-3"].summary


def test_unowned_pagespeed_lookup_failure_keeps_origin_scope_and_no_lab_run(monkeypatch):
    outcome, psi_requests, crux_requests, base = run_pagespeed(
        verified=False, api_mock=monkeypatch, first_lookup_timeout=True)
    assert psi_requests == [] and len(crux_requests)==4
    urls=outcome.result.perf.lab_field['urls']
    home=next(row for row in urls if row['url']==base+'/')
    assert home['lab']['assessed'] is False
    assert home['field']['scope']=='origin'
    assert home['field']['earlier_attempts'][0]['scope']=='url'
    assert home['field']['earlier_attempts'][0]['error']=='ReadTimeout'
