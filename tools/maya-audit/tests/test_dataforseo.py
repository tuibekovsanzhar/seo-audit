"""DataForSEO foundation: credentials, the guarded client, the ledger and the cache.

Everything here is offline. Requests go to an httpx mock transport; the suite's network guard
(tests/conftest.py) would fail any test that tried to reach the real API.
"""

import base64
import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from maya_audit import cli
from maya_audit.config import SECRET_FIELDS
from maya_audit.dataforseo import (BudgetExceeded, Credentials, DataForSEOClient, DataForSEOError, EndpointNotAllowed, Ledger,
                                   LedgerCorrupt, NoEstimator, PossiblyBilled, load_credentials, panel, pricing)
from maya_audit.dataforseo import client as client_module
from maya_audit.dataforseo.cache import CACHE_NAME, Cache, cache_key
from maya_audit.dataforseo.ledger import LEDGER_NAME
from test_deadline_hosted_hardening import _audit_site, _linked_site

ROOT = Path(__file__).resolve().parent.parent
LOGIN, PASSWORD = "MARKER-LOGIN-7f3a@example.test", "MARKER-PASSWORD-91c2e"
CREDENTIALS = Credentials(LOGIN, PASSWORD)
PAID = "/v3/test/paid"
PRICES = {pricing.USER_DATA: lambda payload: 0.0, PAID: lambda payload: 0.05}
LIFETIMES = {PAID: 7 * pricing.DAY}
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "dataforseo"
BACKLINK_FIXTURES = {pricing.BACKLINKS_SUMMARY: "backlinks_summary.json",
                     pricing.BACKLINKS_REFERRING_DOMAINS: "backlinks_referring_domains.json"}
BACKLINK_PATHS = list(BACKLINK_FIXTURES)
SUMMARY_PRICE = (0.024, 0.000036)  # what the mock account lists for the backlink summary; a test raises it
FORBIDDEN = [LOGIN, PASSWORD, base64.b64encode(f"{LOGIN}:{PASSWORD}".encode()).decode(),
             base64.b64encode(LOGIN.encode()).decode(), base64.b64encode(PASSWORD.encode()).decode()]


def ok_body(cost=0.05, **extra):
    return {"status_code": 20000, "status_message": "Ok.", "cost": cost,
            "tasks": [{"status_code": 20000, "status_message": "Ok.", "cost": cost, "result": [extra or {"rows": 1}]}]}


def fixture(endpoint):
    return json.loads((FIXTURES / BACKLINK_FIXTURES[endpoint]).read_text(encoding="utf-8"))


def user_data_body():
    # The real endpoint names the account in its answer, so the mock does too.
    # Same shape as the real answer: hundreds of zero limits, a nested price table, daily statistics.
    listed = lambda request, result: {"live": {level: [{"cost_type": "per_result", "cost": result},
                                                        {"cost_type": "per_request", "cost": request}]
                                               for level in ("priority_low", "priority_normal", "priority_high")}}
    return ok_body(0, login=LOGIN, timezone="Europe/Berlin", backlinks_subscription_expiry_date="2050-01-01 00:00:00 +00:00",
                   money={"total": 50.0, "balance": 41.5,
                          "limits": {"day": {"total": 10, "serp": {"live": {"regular": 0}}, "backlinks": {"summary": {"live": 0}}}},
                          "statistics": {"day": {"total": 0.140736, "total_backlinks": 0, "value": "2026-10-06"}}},
                   price={"backlinks": {"summary": listed(*SUMMARY_PRICE), "referring_domains": listed(0.024, 0.000036)},
                          "serp": {"google": {"organic": listed(0.002, 0)}}})


class Api:
    """A mock DataForSEO: counts requests and records which paths were called."""

    def __init__(self, responder=None):
        self.paths, self.responder = [], responder

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.paths.append(request.url.path)
        assert request.url.host == "api.dataforseo.com"
        assert request.headers["authorization"] == CREDENTIALS.authorization()
        if self.responder:
            return self.responder(request)
        if request.url.path in BACKLINK_FIXTURES:
            return httpx.Response(200, json=fixture(request.url.path))
        return httpx.Response(200, json=user_data_body() if request.url.path == pricing.USER_DATA else ok_body())

    @property
    def transport(self):
        return httpx.MockTransport(self)


@pytest.fixture
def home():
    return Path(os.environ["MAYA_AUDIT_HOME"])


def make_client(home, api, credentials=CREDENTIALS, **options):
    options.setdefault("prices", PRICES)
    # A client with its own price table names the endpoints it may call as well; the shipped table has the shipped list.
    options.setdefault("allowed", None if options["prices"] is None else frozenset(options["prices"]))
    options.setdefault("cache_lifetimes", LIFETIMES)
    return DataForSEOClient(credentials, Ledger(home / LEDGER_NAME), Cache(home / CACHE_NAME),
                            transport=api.transport, **options)


def use_credentials(monkeypatch):
    monkeypatch.setenv("MAYA_AUDIT_DATAFORSEO_LOGIN", LOGIN)
    monkeypatch.setenv("MAYA_AUDIT_DATAFORSEO_PASSWORD", PASSWORD)


def run_cli(monkeypatch, capsys, argv, api=None, url="https://www.example.com/"):
    """The real CLI with a quick local audit behind it and the mock API in front of DataForSEO.

    `url` is only what the DataForSEO plan is built from: the audit itself is the local fake site.
    """
    api = api or Api()
    monkeypatch.setattr(client_module, "TRANSPORT", api.transport)
    monkeypatch.setattr(cli, "run_audit", lambda *args, **kwargs: _audit_site(_linked_site(2)))
    code = cli.main(["crawl", url, *argv])
    return code, capsys.readouterr(), api


# 1 ------------------------------------------------------------------------------------------------
def test_01_without_credentials_every_check_is_not_assessed_and_nothing_is_sent(monkeypatch, capsys, tmp_path):
    report = tmp_path / "r.json"
    code, out, api = run_cli(monkeypatch, capsys, ["--dataforseo", "--json", str(report)])
    section = json.loads(report.read_text(encoding="utf-8"))["dataforseo"]
    assert section["checks"] and all(c["status"] == "not_assessed" for c in section["checks"])
    assert all(c["summary"] == "not assessed: no credentials" for c in section["checks"])
    assert api.paths == [] and section["requests_sent"] == 0
    assert "not assessed: no credentials" in out.out
    assert code == 0  # the crawl itself completed; DataForSEO does not change the audit's exit code


# 2 ------------------------------------------------------------------------------------------------
def test_02_credentials_never_reach_any_output_ledger_or_cache(monkeypatch, capsys, tmp_path, home):
    use_credentials(monkeypatch)
    report, markdown = tmp_path / "r.json", tmp_path / "r.md"
    code, out, api = run_cli(monkeypatch, capsys, ["--dataforseo", "--json", str(report), "--markdown", str(markdown)])
    assert api.paths == BACKLINK_PATHS
    assert json.loads(report.read_text(encoding="utf-8"))["dataforseo"]["checks"][0]["status"] == "observed"

    # A paid, cached call whose response echoes the account name, and one that fails with it in the message.
    echo = Api(lambda request: httpx.Response(200, json=ok_body(0.05, account=LOGIN, note=f"key {PASSWORD}")))
    client = make_client(home, echo)
    assert "[redacted]" in json.dumps(client.request(PAID, [{"target": "example.com"}], target="example.com").data)
    refused = Api(lambda request: httpx.Response(200, json={
        "status_code": 40100, "status_message": f"not authorised: {LOGIN}", "cost": 0, "tasks": []}))
    with pytest.raises(DataForSEOError) as failure:
        make_client(home, refused).request(PAID, [{"target": "other.com"}])
    assert cli.main(["dfs", "balance"]) == 0
    balance = capsys.readouterr()

    everything = {"terminal": out.out + out.err + balance.out + balance.err, "json": report.read_text(encoding="utf-8"),
                  "markdown": markdown.read_text(encoding="utf-8"), "error": str(failure.value), "repr": repr(CREDENTIALS),
                  "calls": json.dumps(client.calls)}
    for path in home.iterdir():
        everything[path.name] = path.read_bytes().decode("utf-8", errors="replace")
    assert {LEDGER_NAME, CACHE_NAME} <= set(everything)
    for where, text in everything.items():
        for secret in FORBIDDEN:
            assert secret not in text, f"a credential form leaked into {where}"
    assert "dataforseo_login" in SECRET_FIELDS and "dataforseo_password" in SECRET_FIELDS


# 3 ------------------------------------------------------------------------------------------------
def test_03_an_endpoint_without_a_price_estimator_is_refused_before_any_request(home):
    api = Api()
    # An endpoint that may be called and has no price is refused for that reason (the allow-list is tested in
    # tests/test_cost_limits.py; since DECISIONS 193 it is asked first, so each refusal below names its own reason).
    unpriced = "/v3/backlinks/backlinks/live"
    with pytest.raises(NoEstimator, match="no price estimator"):
        make_client(home, api, allowed=frozenset({unpriced})).request(unpriced, [{"target": "example.com"}])
    with pytest.raises(NoEstimator):  # also with the shipped price table, not just the test one
        make_client(home, api, prices=None, allowed=frozenset({unpriced})).request(unpriced, [{"target": "example.com"}])
    with pytest.raises(EndpointNotAllowed, match="not on Maya's list of allowed endpoints"):
        make_client(home, api).request("/v3/serp/google/organic/live/advanced", [{"keyword": "example"}])
    with pytest.raises(EndpointNotAllowed):  # the shipped list does not hold it either
        make_client(home, api, prices=None).request(unpriced, [{"target": "example.com"}])
    assert api.paths == []
    assert not (home / LEDGER_NAME).exists()
    # The shipped price table switches on the free account check, the two backlink calls and the six search-data endpoints, nothing else.
    assert set(pricing.PRICE_ESTIMATORS) == {pricing.USER_DATA, *BACKLINK_PATHS, pricing.LABS_DOMAIN_OVERVIEW, pricing.LABS_RANKED_KEYWORDS,
                                             pricing.LABS_COMPETITORS, pricing.LLM_MENTIONS_AGGREGATED, pricing.LIGHTHOUSE, pricing.BUSINESS_INFO}
    assert pricing.PRICE_ESTIMATORS[pricing.USER_DATA](None) == 0


# 4 ------------------------------------------------------------------------------------------------
def test_04_a_call_that_would_pass_the_daily_budget_is_blocked_unsent(home):
    ledger = Ledger(home / LEDGER_NAME)
    ledger.settle(ledger.reserve(PAID, "earlier.com", "a1", 0.08, daily_budget=0.10), "settled", 0.08)
    api = Api()
    with pytest.raises(BudgetExceeded, match="No request was sent"):
        make_client(home, api, daily_budget=0.10).request(PAID, [{"target": "example.com"}])
    assert api.paths == []
    assert ledger.spent_today() == 0.08 and len(ledger.calls()) == 1


# 5 ------------------------------------------------------------------------------------------------
def test_05_two_processes_racing_for_the_last_of_the_budget_exactly_one_proceeds(home):
    code = ("import sys, time; from maya_audit.dataforseo.ledger import Ledger, BudgetExceeded\n"
            "while time.time() < float(sys.argv[2]): pass\n"
            "try:\n    Ledger(sys.argv[1]).reserve('/v3/test/paid', 'example.com', sys.argv[3], 0.06, 0.10); print('PROCEEDED')\n"
            "except BudgetExceeded:\n    print('BLOCKED')\n")
    import time

    start = str(time.time() + 1.5)  # both children wait for the same instant, then race
    children = [subprocess.Popen([sys.executable, "-c", code, str(home / LEDGER_NAME), start, name],
                                 stdout=subprocess.PIPE, text=True, cwd=ROOT) for name in ("one", "two")]
    results = sorted(child.communicate(timeout=30)[0].strip() for child in children)
    assert results == ["BLOCKED", "PROCEEDED"]
    assert Ledger(home / LEDGER_NAME).spent_today() == 0.06


# 6 ------------------------------------------------------------------------------------------------
def test_06_the_ledger_records_the_cost_dataforseo_reports_not_the_estimate(home):
    api = Api(lambda request: httpx.Response(200, json=ok_body(0.0241)))
    client = make_client(home, api)
    result = client.request(PAID, [{"target": "example.com"}], target="example.com")
    [row] = client.ledger.calls()
    assert row["estimate"] == 0.05 and row["cost"] == 0.0241 and row["status"] == "settled"
    assert row["endpoint"] == PAID and row["target"] == "example.com" and row["audit_id"] == client.audit_id
    assert result.cost == 0.0241 and client.ledger.spent_today() == 0.0241


def test_06b_a_task_that_failed_but_was_billed_is_still_recorded_at_its_cost(home):
    billed = {"status_code": 20000, "cost": 0.03, "tasks": [{"status_code": 40501, "status_message": "Invalid Field", "cost": 0.03}]}
    client = make_client(home, Api(lambda request: httpx.Response(200, json=billed)))
    with pytest.raises(DataForSEOError, match="40501"):
        client.request(PAID, [{"target": "example.com"}])
    assert client.ledger.calls()[0]["cost"] == 0.03
    assert client.cache.get(PAID, [{"target": "example.com"}], LIFETIMES[PAID]) is None  # failures are not cached


# 7 ------------------------------------------------------------------------------------------------
def test_07_a_timeout_is_sent_once_never_retried_and_left_as_possibly_billed(home):
    def time_out(request):
        raise httpx.ReadTimeout("no answer", request=request)

    api = Api(time_out)
    client = make_client(home, api)
    with pytest.raises(PossiblyBilled):
        client.request(PAID, [{"target": "example.com"}])
    assert len(api.paths) == 1
    [row] = client.ledger.calls()
    assert row["status"] == "possibly_billed" and row["cost"] is None and "not retried" in row["note"]
    assert client.ledger.spent_today() == 0.05  # still counted, at the estimate


def test_07b_a_paid_server_error_is_not_retried(home, monkeypatch):
    monkeypatch.setattr(client_module._clock, "sleep", lambda seconds: None)  # the one clock (DECISIONS 299)
    api = Api(lambda request: httpx.Response(503, text="unavailable"))
    with pytest.raises(DataForSEOError):
        make_client(home, api).request(PAID, [{"target": "example.com"}])
    assert len(api.paths) == 1


# 8 ------------------------------------------------------------------------------------------------
def test_08_a_repeat_call_is_served_from_cache_for_nothing_and_refresh_asks_again(home):
    api = Api()
    client = make_client(home, api)
    payload = [{"target": "example.com", "limit": 100}]
    first = client.request(PAID, payload, target="example.com")
    second = client.request(PAID, [{"limit": 100, "target": "example.com"}], target="example.com")  # same parameters
    assert len(api.paths) == 1
    assert (first.cached, second.cached, second.cost) == (False, True, 0.0)
    assert second.data == first.data and second.fetched_at <= first.fetched_at
    hit = client.ledger.calls()[-1]
    assert (hit["event"], hit["cache"], hit["cost"], hit["estimate"]) == ("cache_hit", "hit", 0.0, 0.0)
    client.request(PAID, payload, target="example.com", refresh=True)
    assert len(api.paths) == 2
    assert cache_key(PAID, payload).startswith(PAID + "#") and len(cache_key(PAID, payload)) == len(PAID) + 65


# 9 ------------------------------------------------------------------------------------------------
def test_09_a_corrupt_ledger_stops_paid_calls_and_is_left_untouched(home):
    ledger_path = home / LEDGER_NAME
    damaged = '{"id": "a", "event": "reserve", "ts": "2026-10-01T00:00:00+00:00", "estimate": 0.05}\n{"id": "b", "eve'
    ledger_path.write_text(damaged, encoding="utf-8")
    api = Api()
    with pytest.raises(LedgerCorrupt, match="corrupt at line 2.*Paid calls are stopped"):
        make_client(home, api).request(PAID, [{"target": "example.com"}])
    assert api.paths == []
    assert ledger_path.read_text(encoding="utf-8") == damaged


# 10 -----------------------------------------------------------------------------------------------
@pytest.mark.usefixtures("small_cli_limits")
def test_10_dry_run_prints_the_plan_and_total_sends_nothing_and_exits_0(monkeypatch, capsys):
    use_credentials(monkeypatch)
    api = Api()
    monkeypatch.setattr(client_module, "TRANSPORT", api.transport)
    monkeypatch.setattr(cli, "run_audit", lambda *args, **kwargs: pytest.fail("a dry run must not crawl"))
    assert cli.main(["crawl", "https://www.example.com.tr/", "--dfs-dry-run"]) == 0
    out = capsys.readouterr().out
    assert "DataForSEO plan" in out and all(path in out for path in BACKLINK_PATHS) and "example.com.tr" in out
    assert "Total for this audit: $0.0516" in out and "$2.00 daily budget" in out and "$0.50 per audit" in out
    assert "no DataForSEO request was sent" in out
    assert api.paths == []


@pytest.mark.usefixtures("small_cli_limits")
def test_10b_a_plan_above_the_threshold_needs_approval_when_there_is_no_terminal(monkeypatch, capsys, home):
    use_credentials(monkeypatch)
    costly = [panel.PlannedCall("DFS-9", "Costly", PAID, [{"n": i}], "example.com") for i in range(11)]  # $0.55
    monkeypatch.setattr(panel, "audit_plan", lambda url: costly)
    monkeypatch.setattr(pricing, "PRICE_ESTIMATORS", PRICES)
    monkeypatch.setattr(pricing, "ALLOWED_ENDPOINTS", frozenset(PRICES))
    code, out, api = run_cli(monkeypatch, capsys, ["--dataforseo"])
    assert code == 2 and "--dfs-approve-up-to 0.55" in out.err and api.paths == []
    code, out, api = run_cli(monkeypatch, capsys, ["--dataforseo", "--dfs-approve-up-to", "0.60"])
    assert code == 0 and len(api.paths) == 11
    # The client enforces the same limit itself: an unapproved eleventh call is refused, not sent.
    quiet = Api()
    limited = make_client(home, quiet, cache_lifetimes={})
    for i in range(10):
        limited.request(PAID, [{"m": i}])
    with pytest.raises(DataForSEOError, match="above the approved"):
        limited.request(PAID, [{"m": 10}])
    assert len(quiet.paths) == 10


# 11 -----------------------------------------------------------------------------------------------
def test_11_env_file_is_git_ignored():
    assert ".env" in (ROOT / ".gitignore").read_text(encoding="utf-8").split()
    inside = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=ROOT, capture_output=True, text=True)
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        # An unzipped copy has no Git history, so Git cannot be asked. The .gitignore line itself was checked above.
        pytest.skip("this folder is not a Git repository, so `git check-ignore` cannot run")
    assert subprocess.run(["git", "check-ignore", "-q", ".env"], cwd=ROOT).returncode == 0
    assert subprocess.run(["git", "check-ignore", "-q", ".maya-audit/dataforseo-ledger.jsonl"], cwd=ROOT).returncode == 0


def test_11b_credentials_come_from_the_environment_or_the_env_file_only(monkeypatch, tmp_path):
    assert load_credentials() is None
    env_file = tmp_path / ".env"
    env_file.write_text(f'# DataForSEO\nMAYA_AUDIT_DATAFORSEO_LOGIN={LOGIN}\nexport MAYA_AUDIT_DATAFORSEO_PASSWORD="{PASSWORD}"\n'
                        "UNRELATED_SECRET=x\n", encoding="utf-8")
    monkeypatch.setenv("MAYA_AUDIT_ENV_FILE", str(env_file))
    assert load_credentials() == CREDENTIALS
    assert "UNRELATED_SECRET" not in os.environ and "MAYA_AUDIT_DATAFORSEO_PASSWORD" not in os.environ
    monkeypatch.setenv("MAYA_AUDIT_DATAFORSEO_PASSWORD", "from-the-environment")
    assert load_credentials().password == "from-the-environment"  # a real variable wins over the file
    options = [action.option_strings for action in cli.argparse.ArgumentParser()._actions]
    assert not any("password" in flag or "login" in flag for flags in options for flag in flags)


# 12 -----------------------------------------------------------------------------------------------
def test_12_dfs_balance_calls_only_user_data_and_prints_balance_and_prices(monkeypatch, capsys):
    api = Api()
    monkeypatch.setattr(client_module, "TRANSPORT", api.transport)
    assert cli.main(["dfs", "balance"]) == 2  # no credentials: says so, sends nothing
    assert "MAYA_AUDIT_DATAFORSEO_LOGIN" in capsys.readouterr().err and api.paths == []
    use_credentials(monkeypatch)
    assert cli.main(["dfs", "balance"]) == 0
    out = capsys.readouterr().out
    assert api.paths == [pricing.USER_DATA]
    assert "Balance:         $41.5000" in out and "Total deposited: $50.0000" in out
    assert "login [redacted]" in out and LOGIN not in out and PASSWORD not in out
    # The real answer is thousands of lines of zero limits and prices; the report keeps what matters.
    assert len(out.splitlines()) < 22 and "not reported" not in out  # one line per paid endpoint Maya uses
    assert "Spending limits set on the account: day/total = 10" in out
    assert "Spent today, as DataForSEO counts it: $0.1407 (its day 2026-10-06, account time zone Europe/Berlin)" in out
    assert "Spent today through Maya Audit:       $0.0000" in out
    assert "Backlinks subscription until: 2050-01-01" in out
    for path in BACKLINK_PATHS:
        assert (f"{path}: account $0.024 a request + $3.6e-05 a result; Maya estimates $0.024 + $3.6e-05: "
                "covered by Maya's estimate") in out
    assert "serp" not in out
    assert cli.main(["dfs", "balance", "--all-prices"]) == 0 and '"serp"' in capsys.readouterr().out


def test_12b_dfs_balance_says_so_when_the_account_charges_more_than_the_estimator(monkeypatch, capsys):
    use_credentials(monkeypatch)
    monkeypatch.setattr(client_module, "TRANSPORT", Api().transport)
    monkeypatch.setitem(globals(), "SUMMARY_PRICE", (0.03, 0.000036))
    assert cli.main(["dfs", "balance"]) == 0
    out = capsys.readouterr().out
    assert f"{pricing.BACKLINKS_SUMMARY}: account $0.03 a request" in out and out.count("ABOVE MAYA'S ESTIMATE") == 1
    assert out.count("covered by Maya's estimate") == 1


def test_12c_the_shipped_estimators_are_built_from_the_prices_dfs_balance_compares(monkeypatch):
    assert set(pricing.LISTED_PRICES) == set(pricing.PRICE_ESTIMATORS) - {pricing.USER_DATA}
    request_usd, row_usd = pricing.LISTED_PRICES[pricing.BACKLINKS_REFERRING_DOMAINS]
    assert pricing.estimate(pricing.BACKLINKS_SUMMARY, [{"target": "example.com"}]) == round(request_usd + row_usd, 6)
    assert pricing.estimate(pricing.BACKLINKS_REFERRING_DOMAINS, [{"limit": 100}]) == round(request_usd + 100 * row_usd, 6)
    # The first real audit, 2026-10-06: a summary cost $0.024036, and 75 referring-domain rows cost $0.0267.
    assert round(request_usd + row_usd, 6) == 0.024036 and round(request_usd + 75 * row_usd, 6) == 0.0267


# Without --dataforseo ---------------------------------------------------------------------------------
def test_without_the_flag_nothing_about_dataforseo_happens(monkeypatch, capsys, tmp_path, home):
    use_credentials(monkeypatch)
    report = tmp_path / "r.json"
    code, out, api = run_cli(monkeypatch, capsys, ["--json", str(report)])
    assert api.paths == [] and list(home.iterdir()) == []
    assert "dataforseo" not in json.loads(report.read_text(encoding="utf-8")) and "DataForSEO" not in out.out
    assert "dataforseo" not in json.dumps(json.loads(report.read_text(encoding="utf-8"))["crawl"]["config"]).lower()


def test_the_shipped_limits_are_two_and_five_dollars_an_audit_and_twenty_a_day_and_the_day_is_configurable(monkeypatch, tmp_path, capsys):
    assert pricing.APPROVAL_THRESHOLD_USD == 2.00 and pricing.AUDIT_CAP_USD == 5.00 and pricing.DAILY_BUDGET_USD == 20.00
    assert pricing.daily_budget() == 20.00
    monkeypatch.setenv("MAYA_AUDIT_DATAFORSEO_DAILY_USD", "12.5")
    assert pricing.daily_budget() == 12.5
    env = tmp_path / ".env"
    env.write_text("MAYA_AUDIT_DATAFORSEO_DAILY_USD=7\n")
    monkeypatch.delenv("MAYA_AUDIT_DATAFORSEO_DAILY_USD")
    monkeypatch.setenv("MAYA_AUDIT_ENV_FILE", str(env))
    assert pricing.daily_budget() == 7.0
    for bad in ("-1", "abc", "1000000"):
        monkeypatch.setenv("MAYA_AUDIT_DATAFORSEO_DAILY_USD", bad)
        assert pricing.daily_budget() == 20.00
    monkeypatch.delenv("MAYA_AUDIT_DATAFORSEO_DAILY_USD")
    # The command line shows the three limits in its plan, and --dfs-daily-budget still overrides the configured day.
    assert cli.main(["crawl", "https://example.com/", "--dfs-dry-run", "--dfs-search-data"]) == 0
    out = capsys.readouterr().out
    assert "of a $7.00 daily budget" in out
    assert "Limits: confirmation above $2.00 per audit; never more than $5.00 per audit; $7.00 per day." in out
    assert cli.main(["crawl", "https://example.com/", "--dfs-dry-run", "--dfs-daily-budget", "3"]) == 0
    assert "of a $3.00 daily budget" in capsys.readouterr().out
