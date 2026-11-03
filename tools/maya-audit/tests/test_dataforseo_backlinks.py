"""The backlinks and authority panel (DFS-1, DFS-2): the six acceptance tests, plus edge cases.

Everything here is offline. DataForSEO is an httpx mock transport that answers with the files in
tests/fixtures/dataforseo/, and the suite's network guard (tests/conftest.py) would fail any test
that tried to reach the real API. No test makes a paid call.
"""

import json
import os
import re
import subprocess
import sys

import httpx
import pytest

from maya_audit import cli
from maya_audit.dataforseo import Ledger, panel, pricing
from maya_audit.dataforseo import client as client_module
from maya_audit.dataforseo.ledger import LEDGER_NAME
from test_dataforseo import (BACKLINK_PATHS, ROOT, Api, fixture, home, make_client, run_cli,  # noqa: F401
                             use_credentials)
from test_deadline_hosted_hardening import _audit_site, _linked_site

SUMMARY, DOMAINS = pricing.BACKLINKS_SUMMARY, pricing.BACKLINKS_REFERRING_DOMAINS
MAX_PLANNED_USD = 0.06
TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(\+00:00|Z)?")


def run_plan(home, api, url="https://www.example-brand.com/", **options):
    """The shipped plan, price table and cache lifetimes against the mock API."""
    client = make_client(home, api, prices=None, cache_lifetimes=None, **options)
    try:
        return panel.run_checks(panel.audit_plan(url), client), client
    finally:
        client.close()


def by_id(section):
    return {check["check_id"]: check for check in section["checks"]}


# 1 ------------------------------------------------------------------------------------------------
def test_acceptance_1_the_panel_reports_counts_and_top_domains_traceable_to_the_fixture(home):
    section, _ = run_plan(home, Api())
    checks = by_id(section)
    summary_row = fixture(SUMMARY)["tasks"][0]["result"][0]
    domains_row = fixture(DOMAINS)["tasks"][0]["result"][0]

    measured = checks["DFS-1"]["evidence"]["data"]
    assert checks["DFS-1"]["status"] == "observed"
    assert measured["referring_domains"] == summary_row["referring_domains"] == 1536
    assert measured["backlinks"] == summary_row["backlinks"] == 18432
    assert measured["rank"] == summary_row["rank"]
    assert "1,536 referring domain(s) and 18,432 backlink(s)" in checks["DFS-1"]["summary"]

    listed = checks["DFS-2"]["evidence"]["data"]
    assert checks["DFS-2"]["status"] == "observed"
    assert listed["total_count"] == domains_row["total_count"] and listed["listed"] == 100
    assert [(d["domain"], d["rank"], d["backlinks"]) for d in listed["domains"]] == \
           [(i["domain"], i["rank"], i["backlinks"]) for i in domains_row["items"]]

    # Its own family, apart from the site checks, and never presented as a measurement of the site.
    assert {check["family"] for check in section["checks"]} == {"DFS"}
    assert {check["confidence"] for check in section["checks"]} == {"Estimated (third-party index)"}
    assert section["confidence"] == "Estimated (third-party index)" and section["status"] == "assessed"
    text = panel.render_text(section)
    assert "wikipedia.org" in text and "Estimated (third-party index)" in text and "more in the JSON report" in text


def test_spam_share_is_counted_with_one_threshold_and_stated_in_dfs1_and_the_markdown_table(home, monkeypatch):
    from maya_audit import config

    assert config.SPAM_SCORE_THRESHOLD == 50 and panel.SPAM_SCORE_THRESHOLD is config.SPAM_SCORE_THRESHOLD
    items = fixture(DOMAINS)["tasks"][0]["result"][0]["items"]
    # The shape of the first real audit: one clean domain, a few with no score, most at or above the threshold.
    for i, item in enumerate(items):
        item["backlinks_spam_score"] = 0 if i == 0 else None if i in (1, 2) else 49 if i < 13 else 50 if i == 13 else 70
    body = fixture(DOMAINS)
    body["tasks"][0]["result"][0].update(items=items[:75], total_count=75, items_count=75)

    def answer(request):
        return httpx.Response(200, json=body if request.url.path == DOMAINS else fixture(SUMMARY))

    section, _ = run_plan(home, Api(answer))
    checks = by_id(section)
    line = "62 of 75 referring domains look like spam (spam score ≥ 50)."
    assert checks["DFS-1"]["summary"].endswith(line)
    assert checks["DFS-1"]["evidence"]["data"]["spam_like_referring_domains"] == {
        "count": 62, "of": 75, "threshold": 50, "covers_every_referring_domain": True, "counted_from": "DFS-2", "summary": line}
    listed = checks["DFS-2"]["evidence"]["data"]
    assert (listed["spam_like"], listed["spam_score_threshold"], listed["without_spam_score"]) == (62, 50, 2)
    markdown = panel.render_markdown(section)
    assert line in markdown and "50 or more is counted here as" in markdown
    assert "| Referring domain | DataForSEO rank | Backlinks | First seen | Spam score |" in markdown
    assert "| wikipedia.org | 940 | 412 | 2020-01-10 | 0 |" in markdown          # clean
    assert "| github.com | 933 | 408 | 2021-02-11 | not reported |" in markdown   # no score is not called spam
    assert "| 49 |" in markdown and "| 50 ⚠ |" in markdown and "| 70 ⚠ |" in markdown
    text = panel.render_text(section)
    assert line in text and "spam score 70 ⚠" in text


def test_spam_share_says_when_it_covers_only_the_listed_domains_or_could_not_be_counted(home):
    section, _ = run_plan(home, Api())  # the fixture lists 100 of 1,536
    assert ("of 100 highest-ranked referring domains listed (1,536 in the index) look like spam (spam score ≥ 50)."
            in by_id(section)["DFS-1"]["summary"])
    assert by_id(section)["DFS-1"]["evidence"]["data"]["spam_like_referring_domains"]["covers_every_referring_domain"] is False

    def list_fails(request):
        if request.url.path == DOMAINS:
            return httpx.Response(200, json={"status_code": 20000, "cost": 0, "tasks": [{"status_code": 50000, "cost": 0}]})
        return httpx.Response(200, json=fixture(SUMMARY))

    section, _ = run_plan(home, Api(list_fails), url="https://other-brand.com/")
    assert "look like spam was not assessed" in by_id(section)["DFS-1"]["summary"]
    assert "spam_like_referring_domains" not in by_id(section)["DFS-1"]["evidence"]["data"]


# 2 ------------------------------------------------------------------------------------------------
def test_acceptance_2_the_planned_cost_is_shown_first_is_at_most_6_cents_and_the_ledger_matches_the_fixture(
        monkeypatch, capsys, home):
    use_credentials(monkeypatch)
    code, out, api = run_cli(monkeypatch, capsys, ["--dataforseo"])
    assert code == 0 and api.paths == BACKLINK_PATHS  # exactly two calls

    shown = float(re.search(r"Total for this audit: \$(\d+\.\d+)", out.out).group(1))
    planned = sum(pricing.estimate(call.endpoint, call.payload) for call in panel.audit_plan("https://www.example.com/"))
    assert shown == round(planned, 4) and 0 < planned <= MAX_PLANNED_USD
    # The plan is printed before the audit's own output, so before either call is made.
    assert out.out.index("Total for this audit") < out.out.index("Result      ") < out.out.index("DFS-1  Backlink profile summary")

    fixture_cost = sum(fixture(path)["cost"] for path in BACKLINK_PATHS)
    ledger = Ledger(home / LEDGER_NAME)
    rows = ledger.calls()
    assert [(row["endpoint"], row["cost"], row["status"]) for row in rows] == \
           [(path, fixture(path)["cost"], "settled") for path in BACKLINK_PATHS]
    assert ledger.spent_today() == pytest.approx(fixture_cost) == pytest.approx(0.04303)
    assert all(row["cost"] <= row["estimate"] for row in rows)  # the estimates really were upper bounds
    assert f"DataForSEO spend or reserved estimate for this audit: ${fixture_cost:.4f}" in out.out


def test_acceptance_2b_every_planned_call_has_a_7_day_cache_and_a_repeat_audit_costs_nothing(home):
    assert all(pricing.CACHE_LIFETIME_S[path] == 7 * 24 * 60 * 60 for path in BACKLINK_PATHS)
    api = Api()
    first, _ = run_plan(home, api)
    second, _ = run_plan(home, api)
    assert api.paths == BACKLINK_PATHS  # the second audit sent nothing
    assert first["cost_usd"] == pytest.approx(0.04303) and second["cost_usd"] == 0 and second["requests_sent"] == 0
    assert all(check["evidence"]["from_cache"] for check in second["checks"])
    assert by_id(second)["DFS-1"]["evidence"]["data"] == by_id(first)["DFS-1"]["evidence"]["data"]
    lines, total = panel.preview(panel.audit_plan("https://www.example-brand.com/"), Ledger(home / LEDGER_NAME),
                                 make_client(home, api).cache, daily_budget=2.0)
    assert total == 0 and sum("(cached)" in line for line in lines) == 2


# 3 ------------------------------------------------------------------------------------------------
def crawl_part(report_path):
    """The report without the paid panel, and without the one figure that is a stopwatch reading of the whole job
    (it includes the panel's own time, and no two runs take the same time)."""
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report.pop("dataforseo", None)
    assert isinstance(report["audit_status"]["timing"].pop("all_phases_s"), float)
    return report


def test_acceptance_3_a_failed_backlink_call_marks_the_panel_not_assessed_and_changes_nothing_else(
        monkeypatch, capsys, tmp_path):
    use_credentials(monkeypatch)
    outcome = _audit_site(_linked_site(2))
    monkeypatch.setattr(cli, "run_audit", lambda *args, **kwargs: outcome)
    monkeypatch.setattr(client_module._clock, "sleep", lambda seconds: None)  # the one clock (DECISIONS 299)

    def audit(name, responder):
        api = Api(responder)
        monkeypatch.setattr(client_module, "TRANSPORT", api.transport)
        paths = [tmp_path / f"{name}.json", tmp_path / f"{name}.md"]
        code = cli.main(["crawl", "https://www.example.com/", "--dataforseo", "--dfs-refresh",
                         "--json", str(paths[0]), "--markdown", str(paths[1])])
        return code, capsys.readouterr().out, paths, api

    denied = {"status_code": 20000, "status_message": "Ok.", "cost": 0, "tasks": [
        {"status_code": 40204, "status_message": "Access denied. Visit Plans and Subscriptions to activate your "
                                                 "subscription and get access to this API.", "cost": 0, "result": None}]}
    good_code, good_out, good, _ = audit("good", None)
    bad_code, bad_out, bad, bad_api = audit("bad", lambda request: httpx.Response(200, json=denied))
    down_code, _, down, down_api = audit("down", lambda request: httpx.Response(503, text="unavailable"))

    for code, paths in ((bad_code, bad), (down_code, down)):
        section = json.loads(paths[0].read_text(encoding="utf-8"))["dataforseo"]
        # A refusal that reports its cost ($0) costs nothing. An HTTP 503 with no usable answer may have
        # been charged, so its reserved estimate stays counted; it is never retried.
        assert section["status"] == "not_assessed"
        assert section["cost_usd"] == (0 if paths is bad else pytest.approx(section["estimated_usd"]))
        assert all(check["status"] == "not_assessed" and "evidence" not in check for check in section["checks"])
        assert code == good_code == 0  # the audit's own verdict and exit code are untouched
        # Every crawl-based check, gate and page record is the same as in the audit whose calls worked.
        assert TIMESTAMP.sub("T", json.dumps(crawl_part(paths[0]), sort_keys=True)) == \
               TIMESTAMP.sub("T", json.dumps(crawl_part(good[0]), sort_keys=True))
        assert "NOT ASSESSED: no backlink data was obtained" in paths[1].read_text(encoding="utf-8")
    reasons = [check["summary"] for check in json.loads(bad[0].read_text(encoding="utf-8"))["dataforseo"]["checks"]]
    assert all("not assessed: DataForSEO refused" in reason and "40204" in reason for reason in reasons)
    assert "40204" in bad_out and "40204" in bad[1].read_text(encoding="utf-8")
    assert len(bad_api.paths) == 2 and len(down_api.paths) == 2  # a paid call that got a 5xx is not sent again
    # The site-check part of the terminal output is the same text, with only the panel differing.
    head = lambda out: TIMESTAMP.sub("T", out[out.index("Result      "):out.index("DataForSEO: backlinks")])
    assert head(bad_out) == head(good_out)


def test_acceptance_3b_one_failed_call_leaves_the_other_reported_and_the_panel_partly_assessed(home):
    def summary_fails(request):
        if request.url.path == SUMMARY:
            return httpx.Response(200, json={"status_code": 20000, "cost": 0, "tasks": [
                {"status_code": 50000, "status_message": "Internal Error.", "cost": 0}]})
        return httpx.Response(200, json=fixture(DOMAINS))

    section, _ = run_plan(home, Api(summary_fails))
    checks = by_id(section)
    assert section["status"] == "partly_assessed"
    assert checks["DFS-1"]["status"] == "not_assessed" and "50000" in checks["DFS-1"]["summary"]
    assert checks["DFS-2"]["status"] == "observed" and checks["DFS-2"]["evidence"]["data"]["listed"] == 100
    assert "PARTLY ASSESSED" in panel.render_markdown(section)


def test_acceptance_3c_an_answer_in_an_unexpected_shape_is_not_assessed_and_its_cost_is_still_shown(home):
    empty = {"status_code": 20000, "cost": 0.02003, "tasks": [{"status_code": 20000, "cost": 0.02003, "result": None}]}
    section, client = run_plan(home, Api(lambda request: httpx.Response(200, json=empty)))
    assert section["status"] == "not_assessed"
    for check in section["checks"]:
        assert check["status"] == "not_assessed" and "without a result" in check["summary"]
        assert check["evidence"]["cost_usd"] == 0.02003 and "data" not in check["evidence"]
    assert client.ledger.spent_today() == pytest.approx(0.04006)


# 4 ------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("url, expected", [
    ("https://www.withmaya.ai/", "withmaya.ai"),                 # www.
    ("https://WWW.Example.com/pricing?x=1", "example.com"),
    ("https://blog.example.com/post", "example.com"),            # a subdomain
    ("https://shop.eu.example.co.uk/", "example.co.uk"),
    ("https://marka.com.tr/", "marka.com.tr"),                   # .com.tr
    ("https://www.marka.com.tr/urunler", "marka.com.tr"),
    ("https://magaza.marka.com.tr:8443/", "marka.com.tr"),
])
def test_acceptance_4_the_target_sent_to_the_api_is_the_registrable_domain(home, url, expected):
    sent = []

    def record(request):
        sent.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json=fixture(request.url.path))

    section, client = run_plan(home, Api(record), url=url)
    assert [path for path, _ in sent] == BACKLINK_PATHS
    assert all(len(body) == 1 and body[0]["target"] == expected for _, body in sent)
    assert sent[1][1][0]["limit"] == 100 and sent[1][1][0]["order_by"] == ["rank,desc"]
    assert section["target"] == expected and {row["target"] for row in client.ledger.calls()} == {expected}


@pytest.mark.parametrize("url", ["http://127.0.0.1:8000/", "http://localhost/", "https://203.0.113.9/", "http://intranet/"])
def test_acceptance_4b_a_site_that_is_not_a_public_domain_is_never_sent_to_a_paid_endpoint(home, url):
    api = Api()
    section, client = run_plan(home, api, url=url)
    assert api.paths == [] and client.ledger.calls() == [] and section["cost_usd"] == 0
    assert section["status"] == "not_assessed"
    assert all("not a public domain name" in check["summary"] for check in section["checks"])
    lines, total = panel.preview(panel.audit_plan(url), client.ledger, client.cache, daily_budget=2.0)
    assert total == 0 and sum("not sent" in line for line in lines) == 2


# 5 ------------------------------------------------------------------------------------------------
def test_acceptance_5_the_markdown_report_states_the_source_its_date_and_whether_it_came_from_cache(
        monkeypatch, capsys, tmp_path, home):
    use_credentials(monkeypatch)
    first, second = tmp_path / "first.md", tmp_path / "second.md"
    api = Api()
    run_cli(monkeypatch, capsys, ["--dataforseo", "--markdown", str(first)], api)
    run_cli(monkeypatch, capsys, ["--dataforseo", "--markdown", str(second)], api)
    assert api.paths == BACKLINK_PATHS  # the second report was built from the cache

    fresh = first.read_text(encoding="utf-8").split("## DataForSEO: backlinks and authority")[1]
    cached = second.read_text(encoding="utf-8").split("## DataForSEO: backlinks and authority")[1]
    for text, origin in ((fresh, "fetched for this audit"), (cached, "served from Maya's local cache")):
        for path in BACKLINK_PATHS:
            line = next(l for l in text.splitlines() if l.startswith("**Source:**") and path in l)
            assert f"DataForSEO {path}" in line and origin in line
            assert re.search(r"data from \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00", line)
        assert "- **Target domain:** example.com" in text
        assert "- **Confidence:** Estimated (third-party index)" in text
        assert "| Referring domains | 1,536 |" in text and "| wikipedia.org | 940 | 412 |" in text
    assert "cost $0.0200" in fresh and "cost $0.0230" in fresh and "cost $0.0000" in cached
    # The cached report gives the date the data was fetched, not the date of the second audit.
    dates = lambda text: re.findall(r"data from (\S+);", text)
    assert dates(cached) == dates(fresh)


# 6 ------------------------------------------------------------------------------------------------
def test_acceptance_6_without_the_flag_no_request_is_made_and_the_output_is_what_it_was(
        monkeypatch, capsys, tmp_path, home):
    use_credentials(monkeypatch)  # credentials being present must make no difference
    outcome = _audit_site(_linked_site(2))
    monkeypatch.setattr(cli, "run_audit", lambda *args, **kwargs: outcome)
    api = Api()
    monkeypatch.setattr(client_module, "TRANSPORT", api.transport)

    def audit(name, *flags):
        paths = [tmp_path / f"{name}.json", tmp_path / f"{name}.md"]
        code = cli.main(["crawl", "https://www.example.com/", *flags, "--json", str(paths[0]), "--markdown", str(paths[1])])
        out = capsys.readouterr().out
        return code, TIMESTAMP.sub("T", out.replace(name, "NAME")), paths

    plain_code, plain_out, plain = audit("run-a")
    assert api.paths == [] and list(home.iterdir()) == []  # no request, no ledger, no cache
    again_code, again_out, again = audit("run-b")
    with_code, with_out, with_flag = audit("run-c", "--dataforseo")
    assert api.paths == BACKLINK_PATHS

    # Stable from run to run apart from timestamps ...
    assert plain_out == again_out and plain_code == again_code == with_code
    stopwatch = re.compile(r'"all_phases_s": [0-9.]+')  # the whole job's time: a measurement of the run, like a timestamp
    for a, b in zip(plain, again):
        assert stopwatch.sub("S", TIMESTAMP.sub("T", a.read_text(encoding="utf-8"))) == stopwatch.sub("S", TIMESTAMP.sub("T", b.read_text(encoding="utf-8")))
    # ... free of anything DataForSEO ...
    for text in (plain_out, plain[0].read_text(encoding="utf-8"), plain[1].read_text(encoding="utf-8")):
        assert "dataforseo" not in text.lower() and "DFS-" not in text
    # ... and exactly what the flag adds to: the panel is appended, nothing before it moves.
    assert TIMESTAMP.sub("T", with_flag[1].read_text(encoding="utf-8")).startswith(TIMESTAMP.sub("T", plain[1].read_text(encoding="utf-8")))
    assert TIMESTAMP.sub("T", json.dumps(crawl_part(with_flag[0]), sort_keys=True)) == \
           TIMESTAMP.sub("T", json.dumps(crawl_part(plain[0]), sort_keys=True))
    site_part = plain_out[plain_out.index("Result      "):plain_out.index("evidence report written")]
    assert site_part in with_out


def test_acceptance_6b_without_the_flag_the_dataforseo_code_is_not_even_loaded(tmp_path):
    code = ("import sys\nfrom maya_audit import cli\n"
            "cli.main(['crawl', 'http://127.0.0.1:9/', '--time-limit', '0', '--no-render', '--no-prf'])\n"
            # Firecrawl is looked for on every run and reads its key with DataForSEO's .env reader and store classes.
            # Importing that package brings its client and price list along; the panel and its checks stay unloaded,
            # and (below) no spending record is opened.
            "shared = {'maya_audit.dataforseo', 'maya_audit.dataforseo.credentials', 'maya_audit.dataforseo.cache',"
            " 'maya_audit.dataforseo.ledger', 'maya_audit.dataforseo.client', 'maya_audit.dataforseo.pricing'}\n"
            "loaded = sorted(m for m in sys.modules if m.startswith('maya_audit.dataforseo') and m not in shared)\n"
            "print('LOADED', loaded)\n")
    # Replacing env must retain private home/cache/lock locations, without
    # inheriting credentials. Dropping the isolated bytecode cache can stall
    # dependency imports in a cloud-backed working folder before the CLI runs.
    child_tmp = tmp_path / "tmp"
    child_tmp.mkdir()
    done = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=120,
                          env={"PATH": "/usr/bin:/bin", "MAYA_AUDIT_HOME": str(tmp_path / "home"),
                               "MAYA_AUDIT_ENV_FILE": str(tmp_path / "none.env"),
                               "HOME": str(tmp_path), "TMPDIR": str(child_tmp),
                               "XDG_CACHE_HOME": str(tmp_path / "cache"),
                               "XDG_CONFIG_HOME": str(tmp_path / "config"),
                               "PYTHONPYCACHEPREFIX": os.environ.get("PYTHONPYCACHEPREFIX", str(tmp_path / "pycache"))})
    assert "LOADED []" in done.stdout, done.stdout[-2000:] + done.stderr[-2000:]
    assert not (tmp_path / "home").exists()



def test_a_cached_answer_gives_the_same_date_as_the_fresh_one_even_when_a_second_passes_while_it_is_stored(
        monkeypatch, capsys, tmp_path, home):
    # The date was read twice, once for the report and once when the answer was stored, so a cached report could be one
    # second later than the fresh one (an intermittent failure of acceptance test 5). The store now takes the answer's time.
    import time as real_time
    from types import SimpleNamespace
    from maya_audit.dataforseo import cache as cache_module
    use_credentials(monkeypatch)
    # The cache's own clock runs two seconds ahead, as if storing the answer took that long.
    monkeypatch.setattr(cache_module, "time", SimpleNamespace(time=lambda: real_time.time() + 2))
    first, second = tmp_path / "first.md", tmp_path / "second.md"
    api = Api()
    run_cli(monkeypatch, capsys, ["--dataforseo", "--markdown", str(first)], api)
    run_cli(monkeypatch, capsys, ["--dataforseo", "--markdown", str(second)], api)
    assert api.paths == BACKLINK_PATHS  # the second report was built from the cache
    dates = lambda path: re.findall(r"data from (\S+);", path.read_text(encoding="utf-8"))
    assert dates(first) and dates(second) == dates(first)
