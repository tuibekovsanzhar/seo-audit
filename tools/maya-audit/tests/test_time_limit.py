"""What an audit that runs out of time still delivers, and how it says what it lost.

The first real 40-page run hit its 300 s limit after rendering, and every structure check came back
"not assessed". These tests make the clock run out at a chosen step (no sleeping) and check that the
checks which only read the fetched pages still run, that nothing unsent is reported as broken, and
that the report names what was cut.
"""

import time

import pytest

from fakeserver import FakeServer, Response, Site
from maya_audit import audit as audit_module
from maya_audit import cli
from maya_audit.audit import run_audit
from maya_audit.config import CrawlConfig, default_time_limit_s, estimated_duration_s
from maya_audit.report import build_report, render_markdown, render_text
from test_deadline_hosted_hardening import QUIET

BODY = " ".join(f"kelime{i}" for i in range(120))


def page(body, head=""):
    return Response(body=f'<!doctype html><html lang="tr"><head><title>Sayfa başlığı</title>{head}</head><body>'
                         f"<main>{body}</main></body></html>")


def run(monkeypatch, expire_in, **options):
    """Audit a small site; the time limit 'runs out' the moment the named collector is reached."""
    original = getattr(audit_module, expire_in)

    def expiring(fetcher, *args, **kwargs):
        fetcher.deadline_mono = time.monotonic() - 1
        return original(fetcher, *args, **kwargs)

    monkeypatch.setattr(audit_module, expire_in, expiring)
    hreflang = '<link rel="alternate" hreflang="en" href="/en/kontrol-edilmeyen">'
    routes = {"/robots.txt": Response(body="User-agent: *\nAllow: /\n", content_type="text/plain"),
              "/": page(f'<h1>Ana</h1><p>{BODY}</p><a href="/basliksiz">x</a>'),
              # no <h1>: a finding that needs no extra request. The hreflang link is on this page, not the homepage:
              # the homepage's alternates are read by the crawl itself (crawl order, live gap 3), and this target must
              # stay unrequested.
              "/basliksiz": page(f"<p>{BODY} farklı</p>", head=hreflang),
              "/en/kontrol-edilmeyen": page("<h1>EN</h1>")}
    with FakeServer(Site(routes)) as server:
        outcome = run_audit(server.base_url + "/", CrawlConfig(**{**QUIET, "time_limit_s": 600, **options}))
        outcome.requests_seen = [r.route_path for r in server.requests]
    outcome.by_id = {check.check_id: check for check in outcome.checks}
    return outcome


STRUCTURE = [*(f"STR-{n}" for n in range(1, 13)), "TSEO-1"]


def test_running_out_of_time_while_rendering_no_longer_costs_the_structure_checks(monkeypatch):
    outcome = run(monkeypatch, "collect_render_data", render_enabled=True)
    assert outcome.result.deadline_hit
    # Structure data is collected before rendering now, so it was complete when the clock ran out.
    ran = [check_id for check_id in STRUCTURE if outcome.by_id[check_id].status != "not_assessed"]
    assert len(ran) == 12 and "structure" not in outcome.result.collector_errors  # all but STR-4: no structured data here
    assert "render" in outcome.result.collector_errors
    assert any("no <h1>" in f.title for f in outcome.by_id["STR-2"].findings)
    # Rendering was cut, so the render checks fall back to the raw HTML instead of vanishing.
    assert outcome.result.render.pages == {} and "deadline" in outcome.result.render.reason
    assert outcome.by_id["RND-4"].status != "not_assessed" and outcome.by_id["RND-7"].status != "not_assessed"
    # The performance rounds never started: said, not guessed.
    assert "deadline" in outcome.result.perf.skipped_reason


def test_running_out_of_time_before_the_structure_step_still_runs_every_check_that_needs_no_request(monkeypatch):
    outcome = run(monkeypatch, "collect_index_data")
    after_limit = outcome.requests_seen[outcome.requests_seen.index("/basliksiz") + 1:]
    assert "/en/kontrol-edilmeyen" not in after_limit  # nothing was requested once the time was up

    ran = [check_id for check_id in STRUCTURE if outcome.by_id[check_id].status != "not_assessed"]
    assert len(ran) == 12, ran
    assert any("no <h1>" in f.title for f in outcome.by_id["STR-2"].findings)

    # The hreflang target was never requested. It is "not checked", never "does not return 200".
    str9 = outcome.by_id["STR-9"]
    assert not any("do not return 200" in f.title for f in str9.findings)
    entry = next(iter(outcome.result.structure.links.values()))
    assert entry["source"] == "not_fetched" and "time limit" in entry["reason"]
    assert outcome.result.structure.cut_by_time_limit == 1 and outcome.result.structure.same_origin_requests == 0
    assert str9.evidence["hreflang_targets_not_assessed_count"] == 1 and str9.coverage["not_assessed"]


def test_the_report_says_which_checks_the_time_limit_cut_and_why(monkeypatch):
    outcome = run(monkeypatch, "collect_index_data")
    report = build_report(outcome.result, outcome.gates, outcome.checks)
    cuts = {row["collector"]: row for row in report["time_limit_cuts"]}
    # DECISIONS 328: the sitemap check (DECISIONS 206) starts right after the crawl, beside the other steps, so here it
    # ended before the time ran out (at the index step) and is not cut; before, it was the last step and was cut too.
    assert set(cuts) == {"structure", "render", "performance"}
    assert outcome.result._sitemap_check is not None and "sitemap_check" not in outcome.result.collector_errors
    assert cuts["performance"]["checks_not_run"] == ["PRF-1", "PRF-2"] and cuts["performance"]["checks_run_on_fetched_pages_only"] == []
    # STR-4 and RND-2 are "not assessed" for reasons of their own (no structured data, no declared facts): not blamed on the clock.
    assert cuts["structure"]["checks_not_run"] == [] and cuts["render"]["checks_not_run"] == []
    assert "STR-2" in cuts["structure"]["checks_run_on_fetched_pages_only"] and "TSEO-1" in cuts["structure"]["checks_run_on_fetched_pages_only"]
    assert "before this data collection started" in cuts["performance"]["reason"]

    markdown = render_markdown(outcome.result, outcome.gates, outcome.checks)
    section = markdown.split("## Cut short by the time limit")[1].split("## ")[0]
    assert "reached its time limit of 600 seconds" in section and "larger --time-limit" in section
    assert "Not run (performance data: overall audit deadline reached before this data collection started): PRF-1, PRF-2." in section
    assert "Run on the pages already fetched, without their extra requests (structure data:" in section and "STR-2" in section
    assert "without rendering (render data:" in section
    assert markdown.index("## Cut short by the time limit") < markdown.index("## What to fix first")
    text = render_text(outcome.result, outcome.gates, outcome.checks)
    assert "Time limit  The audit reached its time limit of 600 seconds" in text and "Time limit  Not run (performance data" in text


def test_a_run_inside_its_time_limit_has_no_such_section():
    with FakeServer(Site({"/robots.txt": Response(body="User-agent: *\nAllow: /\n", content_type="text/plain"),
                          "/": page(f"<h1>Ana</h1><p>{BODY}</p>")})) as server:
        outcome = run_audit(server.base_url + "/", CrawlConfig(**QUIET))
    assert build_report(outcome.result, outcome.gates, outcome.checks)["time_limit_cuts"] == []
    assert "time limit" not in render_markdown(outcome.result, outcome.gates, outcome.checks).split("## What to fix first")[0].lower()


def test_the_crawl_stops_at_its_share_of_the_time_limit_so_the_checks_have_time_left():
    # The default share is 1.0 since DECISIONS 219 (page reading is never cut for the checks); a smaller share set in
    # the configuration still works as before.
    pages = {f"/p{i}": Response(body=f"<html><body><h1>{i}</h1></body></html>", delay_s=0.25) for i in range(12)}
    links = "".join(f'<a href="{path}">{path}</a>' for path in pages)
    routes = {"/robots.txt": Response(body="User-agent: *\nAllow: /\n", content_type="text/plain"),
              "/": Response(body=f"<html><body><h1>Ana</h1>{links}</body></html>"), **pages}
    with FakeServer(Site(routes)) as server:
        started = time.monotonic()
        outcome = run_audit(server.base_url + "/", CrawlConfig(**{**QUIET, "time_limit_s": 2.0, "crawl_time_share": 0.6}))
    assert outcome.result.stop_reason.value == "time_limit"
    assert "used its share (60%) of the 2s time limit" in outcome.result.stop_detail
    assert 2 <= len(outcome.result.pages) <= 9 and outcome.result.not_fetched_urls
    # The checks ran in the time that was kept back, and the whole audit stayed within the limit.
    assert outcome.result.access is not None and outcome.result.structure is not None
    assert time.monotonic() - started < 4


def test_the_default_time_limit_grows_with_the_page_cap_and_key_pages():
    assert default_time_limit_s(10) == 360 and default_time_limit_s(1) == 300
    assert default_time_limit_s(40, 12) == 660 > estimated_duration_s(40, 12)
    assert default_time_limit_s(10, render=False, prf=False) == 300
    # The five live 10-page runs took 170-217 s; the estimate must cover them.
    assert estimated_duration_s(10) >= 217


def test_the_cli_uses_the_scaled_default_and_warns_when_a_given_limit_looks_too_short(monkeypatch, capsys):
    seen = {}

    def fake(url, config):
        seen["limit"] = config.time_limit_s
        raise cli.HostNotAllowed("stop here")

    monkeypatch.setattr(cli, "run_audit", fake)
    keys = [flag for i in range(12) for flag in ("--key-page", f"/k{i}")]
    assert cli.main(["crawl", "https://example.com/", "--max-pages", "40", *keys]) == 2
    # 518 s for the pages, plus (1 + 0.3) s for each of the sitemap check's 100 light requests (DECISIONS 206; 100 in
    # Quick since DECISIONS 294) and for each of the at most 20 + 40 requests to other sites (DECISIONS 211).
    assert seen["limit"] == 930 and "warning" not in capsys.readouterr().err
    assert cli.main(["crawl", "https://example.com/", "--max-pages", "40", *keys, "--time-limit", "300"]) == 2
    err = capsys.readouterr().err
    assert seen["limit"] == 300
    assert "warning: --time-limit 300 is below the estimated 726 s for 40 pages and 12 key pages" in err and "use 930 s" in err
    assert cli.main(["crawl", "https://example.com/", "--max-pages", "10", "--time-limit", "600"]) == 2
    assert "warning" not in capsys.readouterr().err


def test_a_collector_interrupted_mid_way_without_a_safe_fallback_is_still_dropped_whole_and_named(monkeypatch):
    original = audit_module.collect_index_data

    def interrupted(fetcher, *args, **kwargs):
        fetcher.deadline_mono = time.monotonic() - 1
        fetcher.get("http://127.0.0.1:9/never-sent", "page", 10)  # refused unsent: the collector was cut mid-way
        return original(fetcher, *args, **kwargs)

    monkeypatch.setattr(audit_module, "collect_index_data", interrupted)
    with FakeServer(Site({"/robots.txt": Response(body="User-agent: *\nAllow: /\n", content_type="text/plain"),
                          "/": page(f"<h1>Ana</h1><p>{BODY}</p>")})) as server:
        outcome = run_audit(server.base_url + "/", CrawlConfig(**{**QUIET, "time_limit_s": 600}))
    assert outcome.result.index is None
    cut = next(row for row in build_report(outcome.result, outcome.gates, outcome.checks)["time_limit_cuts"]
               if row["collector"] == "index")
    assert cut["checks_not_run"] == [f"IDX-{n}" for n in range(1, 11)] and "results are incomplete" in cut["reason"]
    assert "Not run (index data:" in render_markdown(outcome.result, outcome.gates, outcome.checks)
