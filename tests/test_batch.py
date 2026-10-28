"""`maya-audit batch`: several brands one after another, a report each, and a summary.

Offline. The sites are fake servers on loopback, audited by the real `run_audit` (only the timing
settings are shortened); DataForSEO is the mock transport with the fixtures. Nothing here can reach
a real site or the real API (tests/conftest.py blocks every non-loopback connection).
"""

import csv
import json
from dataclasses import replace

import httpx
import pytest

from fakeserver import FakeServer
from maya_audit import audit as audit_module
from maya_audit import cli
from maya_audit.crawler import ConcurrentCrawlError
from maya_audit.dataforseo import Ledger, pricing
from maya_audit.dataforseo import client as client_module
from maya_audit.dataforseo.ledger import LEDGER_NAME
from test_dataforseo import BACKLINK_PATHS, PAID, Api, home, use_credentials  # noqa: F401
from test_deadline_hosted_hardening import QUIET, _linked_site

PER_BRAND = 0.051636


class Sites:
    """Public-looking brand URLs, each served by a fake site on loopback through the real audit."""

    def __init__(self, monkeypatch):
        self.servers, self.routes, self.audited, self.configs = [], {}, [], {}
        monkeypatch.setattr(cli, "run_audit", self.run_audit)

    def add(self, url, site=None, error=None):
        if site is not None:
            server = FakeServer(site)
            server.__enter__()
            self.servers.append(server)
            self.routes[url] = server
        else:
            self.routes[url] = error
        return url

    def run_audit(self, url, config):
        self.audited.append(url)
        self.configs[url] = config
        target = self.routes[url]
        if isinstance(target, Exception):
            raise target
        return audit_module.run_audit(target.base_url + "/", replace(config, **QUIET))

    def close(self):
        for server in self.servers:
            server.__exit__(None, None, None)


@pytest.fixture
def sites(monkeypatch):
    sites = Sites(monkeypatch)
    yield sites
    sites.close()


def brands_file(tmp_path, rows, header="name,url"):
    path = tmp_path / "brands.csv"
    path.write_text(header + "\n" + "\n".join(f"{name},{url}" for name, url in rows) + "\n", encoding="utf-8")
    return str(path)


def summary(out):
    with open(out / "summary.csv", encoding="utf-8", newline="") as fh:
        return {row["name"]: row for row in csv.DictReader(fh)}


def use_api(monkeypatch, api=None):
    api = api or Api()
    monkeypatch.setattr(client_module, "TRANSPORT", api.transport)
    return api


def test_each_brand_gets_its_reports_and_a_brand_that_fails_mid_batch_does_not_stop_the_rest(
        monkeypatch, capsys, tmp_path, sites, home):
    api = use_api(monkeypatch)
    rows = [("Alpha", sites.add("https://www.alpha.example/", _linked_site(2))),
            ("Broken Brand", sites.add("https://broken.example/", error=RuntimeError("the site fell over half way"))),
            ("Busy", sites.add("https://busy.example/", error=ConcurrentCrawlError("an audit of busy.example is already running on this host"))),
            ("No Address", "not-a-url"),
            ("Big Site", sites.add("https://big.example/", _linked_site(6))),
            ("Omega & Co", sites.add("https://omega.example/", _linked_site(1)))]
    out = tmp_path / "batch"
    code = cli.main(["batch", brands_file(tmp_path, rows), "--out", str(out), "--max-pages", "3", "--delay", "0"])
    printed = capsys.readouterr().out

    assert code == 1  # not every brand has a usable report
    assert sites.audited == [url for _, url in rows if url != "not-a-url"]  # in order, one at a time, all attempted
    assert all(config.max_pages == 3 for config in sites.configs.values())  # the batch's page cap reached every audit
    table = summary(out)
    assert list(table) == [name for name, _ in rows]
    assert [table[name]["exit_code"] for name, _ in rows] == ["0", "2", "2", "2", "3", "0"]

    # A brand that worked: both reports, and the summary row is the report's own numbers.
    alpha = json.loads((out / "Alpha.json").read_text(encoding="utf-8"))
    assert (out / "Alpha.md").read_text(encoding="utf-8").startswith("# Maya Audit: http://127.0.0.1")
    assert table["Alpha"]["result"].startswith("completed: ") and table["Alpha"]["error"] == ""
    assert int(table["Alpha"]["pages_checked"]) == len(alpha["crawl"]["pages"]) == 3 and table["Alpha"]["redirects"] == "0"
    assert alpha["page_counts"] == {"pages_checked": 3, "redirects": 0}
    assert int(table["Alpha"]["pages_discovered"]) == len(alpha["crawl"]["discovered_urls"])
    severities = [finding["severity"] for check in alpha["checks"] for finding in check["findings"]]
    for severity in ("S1", "S2", "S3", "S4", "Info"):
        assert int(table["Alpha"][f"findings_{severity}"]) == severities.count(severity)
    assert int(table["Alpha"]["findings_total"]) == len(severities)
    not_assessed = [c for c in alpha["checks"] + alpha["answer_engine_panel"] if c["status"] == "not_assessed"]
    assert int(table["Alpha"]["checks_not_assessed"]) == len(not_assessed) > 0
    int3 = next(gate for gate in alpha["gates"] if gate["check_id"] == "INT-3")["evidence"]
    assert table["Alpha"]["render_mode"] == int3["rendering_mode"] and table["Alpha"]["pages_rendered"] == "0"
    assert float(table["Alpha"]["duration_s"]) >= 0  # one decimal place; a loopback audit can round to 0.0
    assert (table["Alpha"]["json"], table["Alpha"]["markdown"]) == ("Alpha.json", "Alpha.md")

    # The page cap: a usable report, flagged as incomplete.
    assert table["Big Site"]["pages_checked"] == "3" and int(table["Big Site"]["pages_discovered"]) == 7
    assert table["Big Site"]["result"].startswith("incomplete: ") and (out / "Big-Site.md").exists()
    assert (out / "Omega-Co.json").exists()  # the name is made safe for a file name

    # The failures: recorded with their error, no report files, and the brands after them still ran.
    assert table["Broken Brand"]["error"] == "RuntimeError: the site fell over half way"
    assert "ConcurrentCrawlError: an audit of busy.example is already running" in table["Busy"]["error"]
    assert "not a web address" in table["No Address"]["error"]
    for failed in ("Broken-Brand", "Busy", "No-Address"):
        assert not (out / f"{failed}.json").exists() and not (out / f"{failed}.md").exists()
    assert table["Broken Brand"]["pages_checked"] == "" and table["Broken Brand"]["result"] == "error: no audit was produced"

    text = (out / "summary.md").read_text(encoding="utf-8")
    assert "**Reports produced:** 3 of 6" in text and "| Alpha | https://www.alpha.example/ | 0 completed |" in text
    assert "- **Broken Brand** (exit 2): RuntimeError: the site fell over half way" in text
    assert "- **Big Site** (exit 3): incomplete" in text and "3 = incomplete" in text
    assert "[4/6] No Address" in printed and "3 of 6 brand(s) have a usable report" in printed

    # Without --dataforseo nothing about DataForSEO happens, as for a single audit.
    assert api.paths == [] and list(home.iterdir()) == []
    assert "dataforseo" not in alpha and table["Alpha"]["dfs_status"] == "" and table["Alpha"]["dfs_cost_usd"] == ""
    assert "DataForSEO" not in printed + (out / "Alpha.md").read_text(encoding="utf-8") and "DataForSEO spend" not in text


def test_with_dataforseo_the_batch_plan_is_shown_first_and_each_brand_goes_through_the_cost_guard(
        monkeypatch, capsys, tmp_path, sites, home):
    use_credentials(monkeypatch)
    api = use_api(monkeypatch)
    rows = [("Alpha", sites.add("https://www.alpha-brand.com/", _linked_site(1))),
            ("Broken", sites.add("https://broken-brand.com/", error=RuntimeError("boom"))),
            ("Alpha Shop", sites.add("https://shop.alpha-brand.com/", _linked_site(1))),   # same registrable domain
            ("Marka", sites.add("https://www.marka.com.tr/", _linked_site(1)))]
    out = tmp_path / "batch"
    code = cli.main(["batch", brands_file(tmp_path, rows), "--out", str(out), "--dataforseo", "--delay", "0"])
    printed = capsys.readouterr().out
    assert code == 1

    # The whole batch's plan and total come before the first brand is touched.
    assert f"Total for the batch: ${4 * PER_BRAND:.4f}" in printed and "Fits today's remaining budget: yes" in printed
    assert printed.index("Total for the batch") < printed.index("[1/4] Alpha")
    assert "alpha-brand.com" in printed and "marka.com.tr" in printed

    # Two paid calls for each new domain; the failed brand bought nothing; the shared domain came from the cache.
    assert api.paths == BACKLINK_PATHS * 2
    ledger = Ledger(home / LEDGER_NAME)
    paid = [row for row in ledger.calls() if row["event"] == "reserve"]
    assert [row["target"] for row in paid] == ["alpha-brand.com"] * 2 + ["marka.com.tr"] * 2
    assert len({row["audit_id"] for row in paid}) == 2  # each brand is its own audit in the ledger
    assert ledger.spent_today() == pytest.approx(2 * 0.04303)

    table = summary(out)
    assert (table["Alpha"]["dfs_status"], table["Alpha"]["dfs_cost_usd"], table["Alpha"]["dfs_from_cache"]) == ("assessed", "0.043030", "no")
    assert (table["Alpha Shop"]["dfs_cost_usd"], table["Alpha Shop"]["dfs_from_cache"]) == ("0.000000", "yes")
    assert (table["Marka"]["dfs_cost_usd"], table["Marka"]["dfs_from_cache"]) == ("0.043030", "no")
    assert (table["Broken"]["exit_code"], table["Broken"]["dfs_status"], table["Broken"]["dfs_cost_usd"]) == ("2", "", "")
    section = json.loads((out / "Marka.json").read_text(encoding="utf-8"))["dataforseo"]
    assert section["target"] == "marka.com.tr" and section["status"] == "assessed"
    assert "## DataForSEO: backlinks and authority" in (out / "Alpha-Shop.md").read_text(encoding="utf-8")
    text = (out / "summary.md").read_text(encoding="utf-8")
    assert "**DataForSEO spend for the batch:** $0.0861" in text and "assessed, $0.0000 (from cache)" in text


def test_a_dataforseo_failure_for_one_brand_is_in_its_row_and_changes_no_exit_code(monkeypatch, capsys, tmp_path, sites):
    use_credentials(monkeypatch)
    monkeypatch.setattr(client_module.time, "sleep", lambda seconds: None)

    def responder(request):
        if b"down-brand.com" in request.content:
            return httpx.Response(503, text="unavailable")
        from test_dataforseo import fixture
        return httpx.Response(200, json=fixture(request.url.path))

    use_api(monkeypatch, Api(responder))
    rows = [("Down", sites.add("https://down-brand.com/", _linked_site(1))), ("Fine", sites.add("https://fine-brand.com/", _linked_site(1)))]
    out = tmp_path / "batch"
    assert cli.main(["batch", brands_file(tmp_path, rows), "--out", str(out), "--dataforseo", "--delay", "0"]) == 0
    table = summary(out)
    assert table["Down"]["exit_code"] == "0" and table["Down"]["dfs_status"].startswith("not_assessed (not assessed: DataForSEO")
    # The two unanswered paid calls keep their reserved estimates: they may have been charged.
    assert table["Down"]["dfs_cost_usd"] == "0.051636" and table["Fine"]["dfs_status"] == "assessed"


@pytest.mark.usefixtures("small_cli_limits")
def test_dry_run_prints_the_total_for_the_whole_batch_and_sends_crawls_and_writes_nothing(
        monkeypatch, capsys, tmp_path, sites, home):
    use_credentials(monkeypatch)
    api = use_api(monkeypatch)
    rows = [("Alpha", sites.add("https://www.alpha-brand.com/", _linked_site(1))),
            ("Marka", sites.add("https://magaza.marka.com.tr/", _linked_site(1))),
            ("Local", "http://127.0.0.1:8000/")]
    out = tmp_path / "batch"
    assert cli.main(["batch", brands_file(tmp_path, rows), "--out", str(out), "--dfs-dry-run"]) == 0
    printed = capsys.readouterr().out
    assert "DataForSEO plan for the batch: 3 brand(s)" in printed
    assert f"Total for the batch: ${2 * PER_BRAND:.4f}" in printed  # the loopback brand is never sent to a paid endpoint
    assert "Alpha: $0.0516" in printed and "Marka: $0.0516" in printed and "Local: $0.0000" in printed
    assert "marka.com.tr" in printed and "not sent: not a public domain" in printed
    assert "$2.0000 left" in printed and "Fits today's remaining budget: yes" in printed
    assert "no DataForSEO request was sent, no site was crawled and no file was written" in printed
    assert api.paths == [] and sites.audited == [] and not out.exists()
    assert not (home / LEDGER_NAME).exists()


@pytest.mark.usefixtures("small_cli_limits")
def test_a_batch_whose_plan_does_not_fit_todays_remaining_budget_does_not_start(monkeypatch, capsys, tmp_path, sites, home):
    use_credentials(monkeypatch)
    api = use_api(monkeypatch)
    ledger = Ledger(home / LEDGER_NAME)
    ledger.settle(ledger.reserve(PAID, "earlier.com", "a1", 1.95, daily_budget=2.0), "settled", 1.95)
    rows = [("Alpha", sites.add("https://www.alpha-brand.com/", _linked_site(1))), ("Beta", sites.add("https://beta-brand.com/", _linked_site(1)))]
    out, brands = tmp_path / "batch", brands_file(tmp_path, rows)

    assert cli.main(["batch", brands, "--out", str(out), "--dataforseo"]) == 2
    io = capsys.readouterr()
    assert "Fits today's remaining budget: NO" in io.out and "$0.0500 left" in io.out
    assert "totals $0.1033 and only $0.0500 of today's $2.00 budget is left" in io.err and "Nothing was sent" in io.err
    assert api.paths == [] and sites.audited == [] and not out.exists()

    # The dry run says the same and still exits 0; a larger budget lets the batch run.
    assert cli.main(["batch", brands, "--out", str(out), "--dfs-dry-run"]) == 0
    assert "Fits today's remaining budget: NO" in capsys.readouterr().out
    assert cli.main(["batch", brands, "--out", str(out), "--dataforseo", "--dfs-daily-budget", "3", "--delay", "0"]) == 0
    assert api.paths == BACKLINK_PATHS * 2

    # Once running, the ledger still refuses a call that would pass the budget. Here something else spends
    # the rest of today's budget while the brand is being crawled: its panel is "not assessed", and nothing is sent.
    def spend_meanwhile(url, config, audit=sites.run_audit):
        ledger.settle(ledger.reserve(PAID, "elsewhere.com", "other", 0.95, daily_budget=3.0), "settled", 0.95)
        return audit(url, config)

    monkeypatch.setattr(cli, "run_audit", spend_meanwhile)
    (tmp_path / "more").mkdir()
    more = brands_file(tmp_path / "more", [("Gamma", sites.add("https://gamma-brand.com/", _linked_site(1)))])
    out2 = tmp_path / "batch2"
    assert cli.main(["batch", more, "--out", str(out2), "--dataforseo", "--dfs-daily-budget", "3", "--delay", "0"]) == 0
    status = summary(out2)["Gamma"]["dfs_status"]
    assert status.startswith("not_assessed") and "daily budget reached" in status and "No request was sent" in status
    assert api.paths == BACKLINK_PATHS * 2 and summary(out2)["Gamma"]["exit_code"] == "0"


@pytest.mark.usefixtures("small_cli_limits")
def test_a_batch_total_above_the_threshold_needs_approval(monkeypatch, capsys, tmp_path, sites):
    use_credentials(monkeypatch)
    api = use_api(monkeypatch)
    rows = [(f"Brand{i}", sites.add(f"https://brand-{i}.com/", error=RuntimeError("not reached"))) for i in range(10)]
    out, brands = tmp_path / "batch", brands_file(tmp_path, rows)
    assert cli.main(["batch", brands, "--out", str(out), "--dataforseo"]) == 2
    err = capsys.readouterr().err
    assert "totals $0.5164, above the $0.50 approved" in err and "--dfs-approve-up-to 0.52" in err
    assert api.paths == [] and sites.audited == []
    assert cli.main(["batch", brands, "--out", str(out), "--dataforseo", "--dfs-approve-up-to", "0.52"]) == 1
    assert len(sites.audited) == 10 and api.paths == []  # approved and started; these brands all fail before any call


@pytest.mark.parametrize("content, message", [
    ("brand,website\nAlpha,https://alpha.example/\n", "needs a header row with the columns name and url"),
    ("name,url\n", "lists no brands"),
    ("name,url\nAlpha,https://a.example/\nalpha,https://b.example/\n", "would overwrite the reports of line 2"),
    ("name,url\n///,https://a.example/\n", "cannot be used as a file name"),
])
def test_a_brands_file_that_cannot_be_used_stops_the_batch_before_anything_runs(capsys, tmp_path, sites, content, message):
    path = tmp_path / "brands.csv"
    path.write_text(content, encoding="utf-8")
    assert cli.main(["batch", str(path), "--out", str(tmp_path / "out")]) == 2
    assert message in capsys.readouterr().err and sites.audited == [] and not (tmp_path / "out").exists()
    assert cli.main(["batch", str(tmp_path / "missing.csv"), "--out", str(tmp_path / "out")]) == 2


def test_existing_reports_are_not_overwritten_unless_asked_and_the_csv_may_have_extra_columns_and_a_bom(
        capsys, tmp_path, sites):
    url = sites.add("https://alpha.example/", _linked_site(1))
    path = tmp_path / "brands.csv"
    path.write_text(f"﻿Name, URL ,owner\n Alpha , {url} ,someone\n\n", encoding="utf-8")
    out = tmp_path / "batch"
    assert cli.main(["batch", str(path), "--out", str(out), "--delay", "0"]) == 0
    assert summary(out)["Alpha"]["url"] == url
    assert cli.main(["batch", str(path), "--out", str(out), "--delay", "0"]) == 2
    assert "already holds Alpha.json" in capsys.readouterr().err and len(sites.audited) == 1
    assert cli.main(["batch", str(path), "--out", str(out), "--delay", "0", "--overwrite"]) == 0


def test_a_batch_reads_pages_through_firecrawl_when_a_key_is_set_and_no_firecrawl_switches_it_off(monkeypatch, capsys, tmp_path, sites, home):
    from maya_audit.firecrawl import client as firecrawl_client
    from test_firecrawl import KEY, Firecrawl, doc

    page = lambda body: httpx.Response(200, json={"success": True, "data": {  # noqa: E731
        "rawHtml": doc("A page", "<h1>A page</h1><p>Read through the made-up reader.</p>"), "metadata": {"statusCode": 200, "url": body["url"]}}})
    api = Firecrawl(responder=page)
    env = tmp_path / ".env"
    env.write_text(f"MAYA_AUDIT_FIRECRAWL_API_KEY={KEY.value}\n")
    monkeypatch.setenv("MAYA_AUDIT_ENV_FILE", str(env))
    monkeypatch.setattr(firecrawl_client, "TRANSPORT", httpx.MockTransport(api))
    rows = [("Alpha", sites.add("https://www.alpha.example/", _linked_site(2)))]
    out = tmp_path / "batch"
    assert cli.main(["batch", brands_file(tmp_path, rows), "--out", str(out), "--max-pages", "3", "--delay", "0"]) == 0
    report = json.loads((out / "alpha.json").read_text(encoding="utf-8"))
    section = report["firecrawl"]
    assert api.bodies and section["used"] and section["purpose"] == "main page reader" and section["pages_read"] == len(api.bodies)
    assert all(body["proxy"] == "basic" and body["maxAge"] == 0 for body in api.bodies)
    assert "## Firecrawl (third-party page reader)" in (out / "alpha.md").read_text(encoding="utf-8") and KEY.value not in json.dumps(report)
    sent = len(api.bodies)
    assert cli.main(["batch", brands_file(tmp_path, rows), "--out", str(tmp_path / "plain"), "--max-pages", "3", "--delay", "0", "--no-firecrawl"]) == 0
    assert len(api.bodies) == sent and "firecrawl" not in json.loads((tmp_path / "plain" / "alpha.json").read_text(encoding="utf-8"))
