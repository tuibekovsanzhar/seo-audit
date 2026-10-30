"""What DataForSEO may cost: the estimators against settled costs, the endpoint allow-list, and the three limits
(confirmation above $2 an audit, never more than $5 an audit, $20 a day; DECISIONS 192 and 193).

Every provider here is a mock transport answering made-up figures about made-up sites. Nothing can reach DataForSEO.
"""
import json

import httpx
import pytest

from maya_audit import cli
from maya_audit.dataforseo import (AuditCapReached, DataForSEOClient, EndpointNotAllowed, Ledger, insights, panel, pricing)
from maya_audit.dataforseo.cache import CACHE_NAME, Cache
from maya_audit.dataforseo.credentials import Credentials
from maya_audit.dataforseo.ledger import LEDGER_NAME

SITE = "https://www.made-up-shop.example/"
SERP = "/v3/serp/google/organic/live/advanced"
STEP = "/v3/test/step"

# What one real audit settled at, per request (its ledger, read 2026-10-13), in the order the plan sends them.
SETTLED = [("DFS-1", pricing.BACKLINKS_SUMMARY, 0.024036), ("DFS-2", pricing.BACKLINKS_REFERRING_DOMAINS, 0.0276),
           ("DFS-3", pricing.LABS_DOMAIN_OVERVIEW, 0.01212), ("DFS-4", pricing.LABS_RANKED_KEYWORDS, 0.024),
           ("DFS-5", pricing.LABS_RANKED_KEYWORDS, 0.018), ("DFS-6", pricing.LABS_COMPETITORS, 0.0144),
           ("DFS-7", pricing.LLM_MENTIONS_AGGREGATED, 0.101), ("DFS-8", pricing.LLM_MENTIONS_AGGREGATED, 0.101),
           ("DFS-9", pricing.LIGHTHOUSE, 0.005)]


class Api:
    """A made-up DataForSEO: records every path it is sent and charges what it is told to."""

    def __init__(self, cost=0.0):
        self.paths, self.cost = [], cost

    def __call__(self, request):
        assert request.url.host == "api.dataforseo.com"
        self.paths.append(request.url.path)
        task = {"status_code": 20000, "status_message": "Ok.", "cost": self.cost, "result": [{"rows": 1}]}
        return httpx.Response(200, json={"status_code": 20000, "status_message": "Ok.", "cost": self.cost, "tasks": [task]})


def client(tmp_path, api, **options):
    options.setdefault("audit_id", "made-up-audit")
    return DataForSEOClient(Credentials("made-up-login", "made-up-password"), Ledger(tmp_path / LEDGER_NAME), Cache(tmp_path / CACHE_NAME),
                            transport=httpx.MockTransport(api), **options)


def nine_calls():
    """Backlinks and the search data panels for one site with no key pages: the plan the settled costs came from."""
    return panel.audit_plan(SITE) + insights.audit_plan(SITE, country="Türkiye")


# -- The estimators ---------------------------------------------------------------------------------------------------
def test_each_estimate_is_within_a_fifth_of_what_the_same_request_settled_at_and_so_is_the_plan():
    plan = nine_calls()
    assert [(call.check_id, call.endpoint) for call in plan] == [(check, endpoint) for check, endpoint, _cost in SETTLED]
    for call, (check, _endpoint, settled) in zip(plan, SETTLED):
        estimate = pricing.estimate(call.endpoint, call.payload)
        assert abs(estimate - settled) <= 0.2 * settled, (check, estimate, settled)
    rows, total = panel.preview_rows(plan, None)
    assert total == pytest.approx(0.327156, abs=1e-6) and sum(cost for *_names, cost in SETTLED) == pytest.approx(0.327, abs=0.0005)
    assert abs(total - 0.327) <= 0.2 * 0.327
    # The business profile lookup was not part of that audit; its price is the listed one.
    assert pricing.estimate(pricing.BUSINESS_INFO, [{"keyword": "Made-Up Shop"}]) == pricing.BUSINESS_INFO_USD


def test_ai_mentions_are_priced_at_one_row_for_each_target_asked_about():
    one = [{"target": [{"domain": "made-up-shop.example"}], "platform": "google"}]
    assert pricing.estimate(pricing.LLM_MENTIONS_AGGREGATED, one) == 0.101
    three = [{"target": [{"domain": "a.example"}, {"domain": "b.example"}, {"keyword": "made-up"}]}]
    assert pricing.estimate(pricing.LLM_MENTIONS_AGGREGATED, three) == pytest.approx(0.103)
    # Never less than one row: no target, an empty list, something that is not a list.
    for odd in ([{}], [{"target": []}], [{"target": "made-up-shop.example"}], None):
        assert pricing.estimate(pricing.LLM_MENTIONS_AGGREGATED, odd) == 0.101
    assert pricing.estimate(pricing.LLM_MENTIONS_AGGREGATED, one + one) == pytest.approx(0.202)  # two tasks, two requests
    assert not hasattr(pricing, "LLM_MAX_ROWS")


# -- The allow-list ---------------------------------------------------------------------------------------------------
def test_the_serp_api_is_refused_before_anything_is_sent_whoever_allows_it(tmp_path):
    api = Api()
    with pytest.raises(EndpointNotAllowed) as refused:
        client(tmp_path, api).request(SERP, [{"keyword": "made-up kettle"}])
    assert str(refused.value) == (f"DataForSEO endpoint {SERP} is not on Maya's list of allowed endpoints, so it is refused. "
                                  "No request was sent.")
    # Naming it in `allowed`, with a price of its own, changes nothing: the prefix rule cannot be overridden.
    own = client(tmp_path, api, allowed=frozenset({SERP}), prices={SERP: lambda payload: 0.002})
    with pytest.raises(EndpointNotAllowed):
        own.request(SERP, [{"keyword": "made-up kettle"}])
    # An endpoint that is merely not listed is refused the same way, also when a caller brings a price for it.
    with pytest.raises(EndpointNotAllowed):
        client(tmp_path, api, prices={STEP: lambda payload: 0.01}).request(STEP, [{}])
    assert api.paths == [] and not (tmp_path / LEDGER_NAME).exists()  # nothing sent, nothing reserved
    # Healthy: a listed endpoint is sent, and one a caller both prices and allows is sent too.
    client(tmp_path, api).request(pricing.BACKLINKS_SUMMARY, [{"target": "made-up-shop.example"}])
    client(tmp_path, api, prices={STEP: lambda payload: 0.01}, allowed=frozenset({STEP})).request(STEP, [{}])
    assert api.paths == [pricing.BACKLINKS_SUMMARY, STEP]


def test_the_allow_list_is_exactly_the_priced_endpoints_and_holds_no_serp_endpoint():
    assert pricing.ALLOWED_ENDPOINTS == frozenset(pricing.PRICE_ESTIMATORS) and pricing.FORBIDDEN_PREFIXES == ("/v3/serp/",)
    assert not [endpoint for endpoint in pricing.ALLOWED_ENDPOINTS if endpoint.startswith("/v3/serp/")]
    assert not pricing.allowed(SERP) and not pricing.allowed(SERP, frozenset({SERP})) and pricing.allowed(pricing.LIGHTHOUSE)
    # No plan Maya builds names one either.
    every = panel.audit_plan(SITE) + insights.audit_plan(SITE, country="Türkiye", brand="Made-Up Shop", local_business=True,
                                                         key_pages=[SITE + "kettles", SITE + "teapots"])
    assert all(pricing.allowed(call.endpoint) for call in every)
    assert {pricing.service_of(call.endpoint) for call in every} == {"Backlinks", "Labs", "AI Optimization", "OnPage (Lighthouse)", "Business Data"}
    assert pricing.service_of(SERP) == "SERP"


# -- The limits -------------------------------------------------------------------------------------------------------
def test_the_defaults_are_two_five_and_twenty_and_each_variable_changes_its_own(monkeypatch, tmp_path):
    assert (pricing.APPROVAL_THRESHOLD_USD, pricing.AUDIT_CAP_USD, pricing.DAILY_BUDGET_USD) == (2.00, 5.00, 20.00)
    assert (pricing.approval_threshold(), pricing.audit_cap(), pricing.daily_budget()) == (2.00, 5.00, 20.00)
    monkeypatch.setenv("MAYA_AUDIT_DATAFORSEO_CONFIRM_ABOVE_USD", "1.25")
    assert (pricing.approval_threshold(), pricing.audit_cap(), pricing.daily_budget()) == (1.25, 5.00, 20.00)
    monkeypatch.setenv("MAYA_AUDIT_DATAFORSEO_AUDIT_CAP_USD", "8")
    assert (pricing.approval_threshold(), pricing.audit_cap(), pricing.daily_budget()) == (1.25, 8.00, 20.00)
    monkeypatch.setenv("MAYA_AUDIT_DATAFORSEO_DAILY_USD", "40")
    assert (pricing.approval_threshold(), pricing.audit_cap(), pricing.daily_budget()) == (1.25, 8.00, 40.00)
    # A value that is not a sensible amount falls back to the default, each on its own.
    for bad in ("abc", "-1", "1000000", "$3"):
        for name in ("MAYA_AUDIT_DATAFORSEO_CONFIRM_ABOVE_USD", "MAYA_AUDIT_DATAFORSEO_AUDIT_CAP_USD", "MAYA_AUDIT_DATAFORSEO_DAILY_USD"):
            monkeypatch.setenv(name, bad)
        assert (pricing.approval_threshold(), pricing.audit_cap(), pricing.daily_budget()) == (2.00, 5.00, 20.00), bad
    # Asking only above an amount the audit can never reach would mean never asking: it is treated as the limit.
    monkeypatch.setenv("MAYA_AUDIT_DATAFORSEO_CONFIRM_ABOVE_USD", "9")
    monkeypatch.setenv("MAYA_AUDIT_DATAFORSEO_AUDIT_CAP_USD", "4")
    assert pricing.approval_threshold() == 4.00 and pricing.audit_cap() == 4.00
    monkeypatch.delenv("MAYA_AUDIT_DATAFORSEO_AUDIT_CAP_USD")
    assert pricing.approval_threshold() == 5.00
    # The environment wins over the env file; the file is read when the environment says nothing.
    for name in ("MAYA_AUDIT_DATAFORSEO_CONFIRM_ABOVE_USD", "MAYA_AUDIT_DATAFORSEO_DAILY_USD"):
        monkeypatch.delenv(name)
    made_up = tmp_path / "made-up.env"
    made_up.write_text("MAYA_AUDIT_DATAFORSEO_CONFIRM_ABOVE_USD=0.75\nMAYA_AUDIT_DATAFORSEO_AUDIT_CAP_USD=3\n", encoding="utf-8")
    monkeypatch.setenv("MAYA_AUDIT_ENV_FILE", str(made_up))
    assert (pricing.approval_threshold(), pricing.audit_cap(), pricing.daily_budget()) == (0.75, 3.00, 20.00)
    monkeypatch.setenv("MAYA_AUDIT_DATAFORSEO_AUDIT_CAP_USD", "6")
    assert pricing.audit_cap() == 6.00
    # A client made with no limits of its own takes the configured ones.
    made = client(tmp_path, Api())
    assert (made.approved_usd, made.audit_cap, made.daily_budget) == (0.75, 6.00, 20.00)
    # The constants stay the defaults a test can lower.
    monkeypatch.delenv("MAYA_AUDIT_ENV_FILE")
    monkeypatch.delenv("MAYA_AUDIT_DATAFORSEO_AUDIT_CAP_USD")
    monkeypatch.chdir(tmp_path)  # no .env here
    monkeypatch.setattr(pricing, "APPROVAL_THRESHOLD_USD", 0.0)
    monkeypatch.setattr(pricing, "AUDIT_CAP_USD", 1.5)
    assert (pricing.approval_threshold(), pricing.audit_cap()) == (0.0, 1.5)


def steps(count):
    return [panel.PlannedCall(f"DFS-{number}", f"Made-up step {number}", STEP, [{"n": number}], "made-up-shop.example") for number in range(1, count + 1)]


def step_client(tmp_path, api, usd, **options):
    return client(tmp_path, api, prices={STEP: lambda payload: usd}, allowed=frozenset({STEP}), cache_lifetimes={}, **options)


def test_a_six_dollar_plan_confirmed_at_six_dollars_stops_at_five_and_the_run_finishes(tmp_path):
    api = Api(cost=0.75)
    paid = step_client(tmp_path, api, 0.75, approved_usd=6.00, approved_always_ask=True, daily_budget=20.00)
    plan = steps(8)  # eight requests of $0.75: $6.00
    assert panel.preview_rows(plan, None, prices=paid.prices)[1] == 6.00 and paid.audit_cap == 5.00
    section = panel.run_checks(plan, paid)
    paid.close()
    # Six were sent ($4.50). The seventh would make $5.25, so it and the eighth were not requested.
    assert len(api.paths) == 6 and section["requests_sent"] == 6 and section["cost_usd"] == pytest.approx(4.50)
    assert [check["status"] for check in section["checks"]] == ["not_assessed"] * 8  # the made-up answers have no reader; the last two were never asked
    assert [check["summary"] for check in section["checks"][6:]] == ["not requested: this audit reached its $5.00 DataForSEO limit. No request was sent."] * 2
    assert all("not requested" not in check["summary"] for check in section["checks"][:6])
    assert section["stopped"] == {"code": "audit_cap_reached", "after": "DFS-6", "not_requested": ["DFS-7", "DFS-8"]}
    assert section["note"] == ("This audit reached its $5.00 DataForSEO limit after DFS-6, so the remaining 2 request(s) were not sent: "
                               "DFS-7, DFS-8. Nothing was charged for them.")
    assert section["note"] in panel.render_text(section) and f"- **Note:** {section['note']}" in panel.render_markdown(section)
    # The ledger holds six settled calls and nothing for the two left out.
    ledger = Ledger(tmp_path / LEDGER_NAME)
    assert [row["status"] for row in ledger.calls()] == ["settled"] * 6 and ledger.spent_today() == pytest.approx(4.50)
    json.dumps(section)  # the section is a report section: it must be writable


def test_the_limit_is_the_audits_own_across_sessions_and_other_audits_are_not_counted(tmp_path):
    api = Api(cost=2.00)
    first = step_client(tmp_path, api, 2.00, approved_usd=6.00, daily_budget=20.00, audit_id="resumed-audit")
    first.request(STEP, [{"n": 1}])
    first.request(STEP, [{"n": 2}])  # $4.00 so far
    first.close()
    # A second session of the same audit (a resume: same audit id, a new client with its own approval).
    again = step_client(tmp_path, api, 2.00, approved_usd=6.00, daily_budget=20.00, audit_id="resumed-audit")
    with pytest.raises(AuditCapReached, match=r"reached its \$5\.00 DataForSEO limit.*No request was sent") as stopped:
        again.request(STEP, [{"n": 3}])
    assert stopped.value.cap == 5.00 and stopped.value.spent == pytest.approx(4.00) and len(api.paths) == 2
    again.close()
    # Another audit has its own limit: the first audit's spend is not counted against it. The day's limit still counts both.
    other = step_client(tmp_path, api, 2.00, approved_usd=6.00, daily_budget=20.00, audit_id="another-audit")
    other.request(STEP, [{"n": 1}])
    assert len(api.paths) == 3 and Ledger(tmp_path / LEDGER_NAME).spent_today() == pytest.approx(6.00)
    other.close()
    # A reservation that was never settled counts at its estimate, as it does for the day.
    ledger = Ledger(tmp_path / "unsettled" / LEDGER_NAME)
    ledger.reserve(STEP, None, "hanging-audit", 4.00, 20.00, audit_cap=5.00)
    with pytest.raises(AuditCapReached):
        ledger.reserve(STEP, None, "hanging-audit", 1.50, 20.00, audit_cap=5.00)
    ledger.reserve(STEP, None, "hanging-audit", 1.00, 20.00, audit_cap=5.00)  # exactly the limit is allowed
    assert len(ledger.calls()) == 2


def test_a_thirty_three_cent_plan_runs_fully_with_nothing_stopped(tmp_path):
    from maya_audit_web import demo

    def provider(request):
        cost, result = demo.search_data(request.url.path, json.loads(request.content)) or (0.0245, {"rows": 1})
        task = {"status_code": 20000, "status_message": "Ok.", "cost": cost, "result": [result]}
        return httpx.Response(200, json={"status_code": 20000, "status_message": "Ok.", "cost": cost, "tasks": [task]})

    sent = []
    plan = nine_calls()
    paid = client(tmp_path, lambda request: (sent.append(request.url.path), provider(request))[1])
    assert paid.approved_usd == 2.00  # nothing was approved by hand: the plan is under the confirmation limit
    section = panel.run_checks(plan, paid)
    paid.close()
    assert len(sent) == 9 and section["requests_sent"] == 9 and "stopped" not in section and "note" not in section
    assert section["estimated_usd"] == pytest.approx(0.327156, abs=1e-6) and 0 < section["cost_usd"] < 0.40
    assert all("not requested" not in check["summary"] for check in section["checks"])


# -- The plan card and the dry run ------------------------------------------------------------------------------------
def test_the_dry_run_names_each_service_says_serp_is_zero_and_states_the_limits(monkeypatch, capsys):
    monkeypatch.setattr(cli, "run_audit", lambda *args, **kwargs: pytest.fail("a dry run must not crawl"))
    assert cli.main(["crawl", SITE, "--dfs-dry-run", "--dataforseo", "--dfs-search-data", "--dfs-country", "Türkiye"]) == 0
    out = capsys.readouterr().out
    for line in ("  Backlinks: 2 paid requests, $0.0516", "  Labs: 4 paid requests, $0.0685", "  AI Optimization: 2 paid requests, $0.2020",
                 "  OnPage (Lighthouse): 1 paid request, $0.0050", "  SERP API calls: 0. Maya never calls the SERP API.",
                 "  Total for this audit: $0.3272",
                 "  Limits: confirmation above $2.00 per audit; never more than $5.00 per audit; $20.00 per day."):
        assert line in out, line
    assert "above the $5.00 limit for one audit" not in out and "/v3/serp/" not in out


def test_a_plan_above_the_limit_says_what_would_be_left_out_and_is_not_refused():
    rows = [{"check_id": f"DFS-{n}", "endpoint": STEP, "state": state, "estimate_usd": usd}
            for n, (state, usd) in enumerate([("paid", 3.0), ("cached", 0.0), ("paid", 1.5), ("paid", 1.0), ("not_sent", 0.0), ("paid", 0.25)], 1)]
    # $3.00, then $4.50; the next would make $5.50, so it and every paid request after it are left out.
    assert panel.left_out_by_cap(rows, 5.00) == ["DFS-4", "DFS-6"] and panel.left_out_by_cap(rows, 5.75) == []
    assert panel.by_service(rows) == [{"service": "test", "requests": 4, "usd": 5.75}] and panel.serp_api_calls(rows) == 0
    assert panel.serp_api_calls([{"endpoint": SERP}]) == 1  # counted from the plan, not written as a constant


pytest.importorskip("fastapi")
from maya_audit_web import paid as web_paid  # noqa: E402
from maya_audit_web.strings import t  # noqa: E402
from test_web_app import API, PACKAGE, confirm, error, get, plan, start, web  # noqa: E402,F401


def test_the_plan_document_has_services_no_serp_calls_and_the_limits(web):
    client = web()
    cost = plan(client, backlinks=True, search_data=True, market_default_accepted=True)["paid"]
    paid_rows = [row for row in cost["calls"] if row["state"] == "paid"]
    assert cost["serp_api_calls"] == 0 and len(paid_rows) == 9
    assert [(entry["service"], entry["requests"]) for entry in cost["by_service"]] == [
        ("Backlinks", 2), ("Labs", 4), ("AI Optimization", 2), ("OnPage (Lighthouse)", 1)]
    assert sum(entry["requests"] for entry in cost["by_service"]) == len(paid_rows)
    assert sum(entry["usd"] for entry in cost["by_service"]) == pytest.approx(cost["total_usd"]) and cost["total_usd"] == pytest.approx(0.327156, abs=1e-6)
    assert cost["limits"] == {"confirm_usd": 2.00, "audit_cap_usd": 5.00, "daily_usd": 20.00} and cost["over_audit_cap"] is None
    assert not cost["needs_confirmation"] and cost["blocked"] is None
    # A plan with no paid data says the same about the limits and holds no service.
    plain = plan(client, backlinks=False)["paid"]
    assert plain["serp_api_calls"] == 0 and plain["limits"] == cost["limits"]
    # Once the answers are saved, the services are still named, with nothing to pay.
    start(client, plan(client, backlinks=True))
    saved = plan(client, backlinks=True)["paid"]
    assert saved["by_service"] == [{"service": "Backlinks", "requests": 0, "usd": 0.0}] and saved["total_usd"] == 0


def test_a_dollar_fifty_plan_needs_no_confirmation_and_a_two_fifty_plan_does(web, monkeypatch):
    client = web()
    made_up = [panel.PlannedCall("DFS-1", "Made-up panel", pricing.BACKLINKS_SUMMARY, [{"target": "made-up-shop.example"}], "made-up-shop.example")]
    monkeypatch.setattr(client.app.state.engine.paid, "plan", lambda url: made_up)
    for usd, asks in ((1.50, False), (2.00, False), (2.50, True)):
        monkeypatch.setitem(pricing.PRICE_ESTIMATORS, pricing.BACKLINKS_SUMMARY, lambda payload, usd=usd: usd)
        made = plan(client, backlinks=True)
        assert made["paid"]["total_usd"] == usd and made["paid"]["needs_confirmation"] is asks and made["needs_confirmation"] is asks, usd
        assert made["can_start"] is (not asks) and made["paid"]["over_audit_cap"] is None
        if asks:
            error(client.post(f"{API}/audits", json={"plan_id": made["id"]}), 402, "confirmation_required")
            assert confirm(client, made)["can_start"]
    assert client.provider.requests == []


def test_a_plan_above_five_dollars_warns_on_the_card_runs_to_the_limit_and_the_report_says_what_was_left_out(web, monkeypatch):
    from maya_audit_web import demo
    from test_web_app import Provider

    def two_dollars(request):  # the made-up provider charges what the plan estimated: $2.00 a request
        body = json.loads(demo._backlinks(request).content)
        body["cost"] = body["tasks"][0]["cost"] = 2.00
        return httpx.Response(200, json=body)

    client = web(provider=Provider(two_dollars))
    made_up = [panel.PlannedCall(f"DFS-{number}", f"Made-up panel {number}", pricing.BACKLINKS_SUMMARY, [{"target": f"made-up-{number}.example"}],
                                 f"made-up-{number}.example") for number in (1, 3, 4)]  # three summaries; no made-up referring-domain list
    monkeypatch.setattr(client.app.state.engine.paid, "plan", lambda url: made_up)
    monkeypatch.setitem(pricing.PRICE_ESTIMATORS, pricing.BACKLINKS_SUMMARY, lambda payload: 2.00)
    made = plan(client, backlinks=True)
    cost = made["paid"]
    assert cost["total_usd"] == 6.00 and cost["needs_confirmation"] and cost["blocked"] is None  # a warning, not a refusal
    assert cost["over_audit_cap"] == {"cap_usd": 5.00, "total_usd": 6.00, "left_out": ["DFS-4"], "message":
                                      "This plan is estimated at $6.00, above the $5.00 limit for one audit. Requests are sent in the order "
                                      "shown until the limit is reached; left out: DFS-4."}
    audit = start(client, confirm(client, made))
    assert audit["state"] == "finished", audit.get("error")
    assert len(client.provider.requests) == 2  # the audit itself finished; the third was never sent
    assert client.ledger.spent_today() == pytest.approx(4.00)
    section = get(client, audit, "/result")["dataforseo"]
    assert section["stopped"] == {"code": "audit_cap_reached", "after": "DFS-3", "not_requested": ["DFS-4"]}
    view = get(client, audit, "/summary")["backlinks"]
    assert section["note"] == ("This audit reached its $5.00 DataForSEO limit after DFS-3, so the remaining 1 request(s) were not sent: "
                               "DFS-4. Nothing was charged for them.")
    assert view["stopped"]["code"] == "audit_cap_reached" and view["note"] == section["note"]
    assert view["note_shown"] == "This audit reached its $5.00 DataForSEO limit after DFS-3, so the remaining 1 request was not sent: DFS-4. Nothing was charged for them."
    last = view["checks"][-1]
    assert last["refusal"] == {"code": "audit_cap_reached", "message":
                               "Not requested: this audit reached its $5.00 DataForSEO limit. Nothing was sent or charged for it."}


def test_the_new_sentences_are_filled_in_both_languages_and_the_page_shows_them():
    from maya_audit_web import wording

    for language, word in (("en", "paid requests"), ("tr", "ücretli istek")):
        row = t("paid.by_service.row", language, service="Labs", requests=4, usd="0.07")
        assert row.startswith("Labs: 4 ") and word in row and "0.07" in row and "{" not in row
        for key, values in (("paid.title.auto", {"limit": "2.00"}), ("paid.serp_zero", {}), ("paid.limits", {"confirm": "2.00", "cap": "5.00", "daily": "20.00"}),
                            ("paid.over_cap", {"total": "6.00", "cap": "5.00", "left_out": "DFS-7, DFS-8"}), ("paid.refused.audit_cap", {"cap": "5.00"})):
            said = t(key, language, **values)
            assert said != key and "{" not in said and "…" not in said and all(str(value) in said for value in values.values()), (language, key)
    assert t("paid.by_service.row", "en", service="OnPage (Lighthouse)", requests=1, usd="0.0050") == "OnPage (Lighthouse): 1 paid request, $0.0050"
    assert t("paid.serp_zero", "en") == "SERP API calls: 0. Maya never calls the SERP API." and "SERP API" in t("paid.serp_zero", "tr")
    # The engine's own sentences about the limit are worded for a Turkish reader too.
    for said, starts in (("not requested: this audit reached its $5.00 DataForSEO limit. No request was sent.", "istenmedi: bu denetim 5.00 $"),
                         ("This audit reached its $5.00 DataForSEO limit after DFS-6, so the remaining 2 request(s) were not sent: DFS-7, DFS-8. "
                          "Nothing was charged for them.", "Bu denetim DFS-6 sonrasında 5.00 $"),
                         ("This audit reached its $5.00 DataForSEO limit before its first request, so the remaining 3 request(s) were not sent: "
                          "DFS-1, DFS-2, DFS-3. Nothing was charged for them.", "Bu denetim ilk isteğinden önce 5.00 $")):
        shown, translated = wording.line(said, "tr")
        assert translated and shown.startswith(starts) and "{" not in shown, said
        assert wording.line(said, "en") == (said.replace("request(s)", "requests"), True)
    # The page prints one line per service with the amount in its own element, the SERP line and the limits, as nodes.
    script = (PACKAGE / "static" / "app.js").read_text(encoding="utf-8")
    for needed in ('T("paid.by_service.row"', 'el("strong", { text: money(service.usd) })', 'T("paid.serp_zero")', 'T("paid.limits"', "cost.over_audit_cap.message"):
        assert needed in script, needed
    assert web_paid.refusal("not requested: this audit reached its $5.00 DataForSEO limit. No request was sent.")["code"] == "audit_cap_reached"
