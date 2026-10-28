"""The country on the plan card is the country of the run, and the DataForSEO balance is known before anything is spent
(DECISIONS 179 and 180).

Every provider here is made up and in memory: DataForSEO is `Bank` below (a mock transport that also answers the free
account endpoint with a balance the test chooses), the sites are the demo sites, and Firecrawl is the in-memory one of
tests/test_firecrawl.py. No request leaves this computer, the balance endpoint included.
"""
import json

import httpx
import pytest

pytest.importorskip("fastapi")

from maya_audit import cli  # noqa: E402
from maya_audit.dataforseo import insights, panel, pricing  # noqa: E402
from maya_audit.dataforseo.cache import CACHE_NAME, Cache  # noqa: E402
from maya_audit.dataforseo.client import DataForSEOClient, NoCredit  # noqa: E402
from maya_audit.dataforseo.credentials import Credentials  # noqa: E402
from maya_audit.dataforseo.ledger import Ledger  # noqa: E402
from maya_audit_web import demo, paid, strings, wording  # noqa: E402
from test_firecrawl import Firecrawl  # noqa: E402
from test_web_app import API, CAFE, SECRETS, SHOP, Site, cloudflare, confirm, error, get, plan, start, web  # noqa: E402,F401
from test_web_firecrawl import PAGES, services  # noqa: E402

USER_DATA = pricing.USER_DATA
MARKET_PANELS = ("DFS-3", "DFS-4", "DFS-5", "DFS-6", "DFS-7")
NO_CREDIT = {"status_code": 40200, "status_message": "Payment Required.", "cost": 0, "result": None}


class Bank:
    """A made-up DataForSEO: records every request with its body, answers the account endpoint with `balance`
    (None: the account does not answer), and refuses paid requests for no credit from the `refuse_from`-th one on."""

    def __init__(self, balance=50.0, refuse_from=None, code=40200):
        self.balance, self.refuse_from, self.code = balance, refuse_from, code
        self.requests, self.bodies = [], []

    @property
    def paid(self):
        return [path for path in self.requests if path != USER_DATA]

    def __call__(self, request):
        path = request.url.path
        self.requests.append(path)
        if path == USER_DATA:
            if self.balance is None:
                return httpx.Response(503, text="unavailable")
            return httpx.Response(200, json={"status_code": 20000, "cost": 0, "tasks": [{"status_code": 20000, "cost": 0, "result": [
                {"login": SECRETS[0], "money": {"balance": self.balance, "total": 50}}]}]})
        self.bodies.append((path, json.loads(request.content or b"[{}]")[0]))
        if self.refuse_from is not None and len(self.paid) >= self.refuse_from:
            return httpx.Response(200, json={"status_code": 20000, "status_message": "Ok.", "cost": 0,
                                             "tasks": [{**NO_CREDIT, "status_code": self.code}]})
        return demo._backlinks(request)


@pytest.fixture
def automatic(monkeypatch):
    """The rule as it ships: a plan with paid data asks for the balance by itself. A made-up clock stands in for time."""
    clock = {"now": 1_800_000_000.0}
    monkeypatch.setattr(paid, "AUTOMATIC_BALANCE", True)
    monkeypatch.setattr(paid, "CLOCK", lambda: clock["now"])
    return clock


def in_turkish(client):
    client.put(f"{API}/session/language", json={"language": "tr"})


# -- B1: the country ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("typed", ["Turkey", "Türkiye", "TÜRKİYE", "turkiye", "TR", "tr", "Türkiye (TR)", "  türkiye  ", "TURKEY"])
def test_every_spelling_of_turkey_is_turkey(typed):
    assert insights.location_for(typed) == (2792, "tr", "Turkey", True)


@pytest.mark.parametrize("typed, expected", [
    ("Deutschland", (2276, "de", "Germany")), ("España", (2724, "es", "Spain")), ("ESPAÑA", (2724, "es", "Spain")), ("İtalya", (2380, "it", "Italy")),
    ("United Kingdom", (2826, "en", "United Kingdom")), ("UK", (2826, "en", "United Kingdom")), ("Birleşik Krallık", (2826, "en", "United Kingdom")),
    ("Germany (DE)", (2276, "de", "Germany")), ("U.S.A.", (2840, "en", "United States")), ("united states", (2840, "en", "United States")),
    ("France", (2250, "fr", "France")), ("NL", (2528, "nl", "Netherlands")), ("Canada", (2124, "en", "Canada")), ("australia", (2036, "en", "Australia")),
    ("United Arab Emirates", (2784, "ar", "United Arab Emirates"))])
def test_the_other_countries_survive_the_folding(typed, expected):
    assert insights.location_for(typed) == (*expected, True)
    # every name in the table is found under its own spelling
    assert all(insights.location_for(name) == (*place, True) for name, place in insights.LOCATIONS.items())


def test_an_unknown_or_missing_country_is_not_recognised():
    for typed in ("Atlantis", "", None, "(", "Türkiyee"):
        assert insights.location_for(typed) == (2840, "en", "United States", False)


@pytest.mark.parametrize("typed", ["TÜRKİYE", "Türkiye (TR)"])
def test_the_country_typed_on_the_card_is_the_market_of_every_request(web, typed):
    bank = Bank()
    client = web(provider=bank)
    american = plan(client, search_data=True, country="United States")
    made = plan(client, search_data=True, country=typed)
    assert made["search_data"]["market"] == "Turkey" and made["search_data"]["market_known"] and made["paid_options"]["country"] == typed
    assert made["fingerprint"] != american["fingerprint"] and made["can_start"] and made["cannot_start"] is None
    assert all("Turkey, tr" in row["title"] for row in made["paid"]["calls"] if row["check_id"] in MARKET_PANELS)
    audit = start(client, confirm(client, made))
    assert audit["state"] == "finished" and len(bank.bodies) == 7
    bodies = dict(zip([row["check_id"] for row in made["paid"]["calls"]], [body for _path, body in bank.bodies]))
    for check_id in MARKET_PANELS:
        assert bodies[check_id]["location_code"] == 2792 and bodies[check_id]["language_code"] == "tr", check_id
    assert bodies["DFS-8"]["location_code"] == 2840 and bodies["DFS-8"]["language_code"] == "en"  # ChatGPT: the one market there is
    section = get(client, audit, "/result")["dataforseo"]
    assert not any("default market" in check["title"] for check in section["checks"])
    assert sum("Turkey, tr" in check["title"] for check in section["checks"]) == 5


def test_a_changed_brand_is_a_changed_plan_and_a_plan_older_than_the_saved_country_does_not_run(web):
    client = web(provider=Bank())
    # "Demo Shop" is the address's own suggestion, not a typed name (DECISIONS 220): these tests type other names.
    first = plan(client, search_data=True, country="Türkiye", brand_name="Demo Shop Ltd")
    assert plan(client, search_data=True, country="Türkiye", brand_name="Demo Shop Co")["fingerprint"] != first["fingerprint"]
    assert first["paid_options"]["brand"] == "Demo Shop Ltd" and first["business"]["country_confirmed"] and first["business"]["suggested_from"] is None
    # The country saved for the site changed after the plan was made: the old plan is refused, the provider is asked nothing.
    client.put(f"{API}/projects/{SHOP}/profile", json={"brand_name": "Demo Shop Ltd", "countries": ["Germany"]})
    refused = error(client.post(f"{API}/audits", json={"plan_id": first["id"]}), 409, "plan_changed")
    assert "brand or country" in refused["message"] and refused["details"] == {"changed": "business"}
    error(client.post(f"{API}/plans/{first['id']}/confirm", json={"approved_max_usd": first["paid"]["total_usd"]}), 409, "plan_changed")
    # The same for the brand.
    client.put(f"{API}/projects/{SHOP}/profile", json={"brand_name": "Another Name", "countries": ["Türkiye"]})
    error(client.post(f"{API}/audits", json={"plan_id": first["id"]}), 409, "plan_changed")
    assert client.provider.requests == [] and client.site.requests == []
    # A plan made now takes what is saved, and runs.
    again = plan(client, search_data=True)
    assert again["paid_options"]["country"] == "Türkiye" and again["paid_options"]["brand"] == "Another Name" and again["search_data"]["market"] == "Turkey"
    assert start(client, confirm(client, again))["state"] == "finished"


def test_search_data_does_not_run_on_an_unknown_market_until_the_person_says_so(web):
    bank = Bank()
    client = web(provider=bank)
    for typed in ("Atlantis", ""):
        unknown = plan(client, search_data=True, country=typed)
        assert not unknown["can_start"] and unknown["cannot_start"]["code"] == "market_unknown" and unknown["search_data"]["market_unknown"]
        assert "Use United States figures" in unknown["cannot_start"]["message"] and (typed or "no country") in unknown["cannot_start"]["message"]
        assert not any(line["kind"] == "search" for line in unknown["search_data"]["markets"])  # no market is named while there is none
        refused = error(client.post(f"{API}/audits", json={"plan_id": unknown["id"]}), 409, "market_unknown")
        assert refused["message"] == unknown["cannot_start"]["message"]
    assert plan(client, search_data=True)["cannot_start"]["code"] == "market_unknown"  # the demo address suggests no country
    assert bank.requests == []
    # The tick: United States figures, said on the card, tied into the fingerprint, and said in the report.
    accepted = plan(client, search_data=True, country="Atlantis", market_default_accepted=True)
    assert accepted["can_start"] or accepted["needs_confirmation"]
    assert accepted["cannot_start"] is None and accepted["paid_options"]["market_default_accepted"] is True and accepted["fingerprint"] != unknown["fingerprint"]
    assert accepted["fingerprint"] != plan(client, search_data=True, country="United States")["fingerprint"]
    assert {"kind": "search", "text": "Search data market: United States, English."} in accepted["search_data"]["markets"]
    audit = start(client, confirm(client, accepted))
    section = get(client, audit, "/result")["dataforseo"]
    assert sum("United States, en; default market" in check["title"] for check in section["checks"]) == 5
    assert all(body["location_code"] == 2840 for _path, body in bank.bodies if "location_code" in body)
    # The tick means nothing for a country that is recognised, and a plan with backlinks only has no market to know.
    assert plan(client, search_data=True, country="Türkiye", market_default_accepted=True)["paid_options"]["market_default_accepted"] is False
    backlinks = plan(client, backlinks=True, country="")
    assert backlinks["cannot_start"] is None and (backlinks["can_start"] or backlinks["needs_confirmation"])
    assert backlinks["search_data"]["markets"] == [{"kind": "backlinks", "text": "Backlinks: no market (worldwide)."}]
    assert start(client, confirm(client, backlinks))["state"] == "finished"


def test_the_card_names_the_market_of_each_panel_and_where_a_suggestion_comes_from_in_english_and_turkish(web):
    client = web(provider=Bank())
    made = plan(client, "https://www.maksimum-enerji.com.tr/", search_data=True, backlinks=True)
    assert made["business"]["country"] == "Türkiye" and made["business"]["suggested_from"] == "the address ending (.tr)" and not made["business"]["country_confirmed"]
    assert [line["text"] for line in made["search_data"]["markets"]] == [
        "Search data market: Turkey, Turkish.",
        "ChatGPT mentions: United States, English only (the one market DataForSEO offers).",
        "Backlinks: no market (worldwide).",
        "Suggested from the address ending (.tr): Turkey. Confirm or change it."]
    assert [line["kind"] for line in made["search_data"]["markets"]] == ["search", "chatgpt", "backlinks", "suggestion"]
    # Typed on the card or saved for the site, it is no longer a suggestion.
    assert [line["kind"] for line in plan(client, "https://www.maksimum-enerji.com.tr/", search_data=True, country="TR")["search_data"]["markets"]] == ["search", "chatgpt"]
    in_turkish(client)
    turkish = plan(client, "https://www.maksimum-enerji.com.tr/", search_data=True, backlinks=True)
    assert [line["text"] for line in turkish["search_data"]["markets"]] == [
        "Arama verisi pazarı: Türkiye, Türkçe.",
        "ChatGPT'de anılma: yalnızca Amerika Birleşik Devletleri, İngilizce (DataForSEO'nun sunduğu tek pazar).",
        "Geri bağlantılar: pazar yok (dünya geneli).",
        "Adres uzantısı (.tr) temel alınarak önerildi: Türkiye. Onaylayın veya değiştirin."]
    unknown = plan(client, search_data=True, country="Atlantis")
    assert unknown["search_data"]["market_default_label"] == "Amerika Birleşik Devletleri verilerini kullan" and "Atlantis" in unknown["cannot_start"]["message"]
    assert unknown["cannot_start"]["message"].startswith("Arama verisi için bir pazar gerekir")


def test_the_suggestion_comes_from_the_last_audits_homepage_language_and_no_page_is_fetched_for_it(web):
    client = web(provider=Bank())
    before = plan(client, CAFE, search_data=True)
    assert before["business"]["country"] == "" and before["business"]["suggested_from"] is None  # nothing to go on yet
    assert start(client, plan(client, CAFE))["state"] == "finished"  # the demo cafe's pages say lang="tr"
    fetched = len(client.site.requests)
    after = plan(client, CAFE, search_data=True, backlinks=True)
    assert after["business"]["country"] == "Türkiye" and after["business"]["suggested_from"] == "the last audit's homepage language (tr)"
    assert after["search_data"]["markets"][-1] == {"kind": "suggestion", "text": "Suggested from the last audit's homepage language (tr): Turkey. Confirm or change it."}
    assert after["search_data"]["market"] == "Turkey" and after["cannot_start"] is None
    assert len(client.site.requests) == fetched and client.provider.requests == []  # a plan asks the site and the provider nothing
    in_turkish(client)
    assert plan(client, CAFE, search_data=True)["search_data"]["markets"][-1]["text"] == "Son denetimdeki ana sayfa dili (tr) temel alınarak önerildi: Türkiye. Onaylayın veya değiştirin."


def test_the_lab_test_is_run_on_the_homepage_the_crawl_ended_on_not_on_a_typed_address_that_redirects(web, tmp_path):
    typed, final = "https://made-up-shop.example/", "https://www.made-up-shop.example/"
    plain = insights.audit_plan(typed, country="TR", key_pages=[typed + "pricing"])
    aimed = insights.audit_plan(typed, country="TR", key_pages=[typed + "pricing"], home=final)
    assert [call.target for call in plain if call.endpoint == pricing.LIGHTHOUSE] == [typed, typed + "pricing"]
    assert [call.target for call in aimed if call.endpoint == pricing.LIGHTHOUSE] == [final, typed + "pricing"]
    assert aimed[6].payload[0]["url"] == final and aimed[6].title == f"Lighthouse lab test (mobile): {final}"
    rows = [panel.preview_rows(calls, None)[1] for calls in (plain, aimed)]
    assert rows[0] == rows[1] and len(plain) == len(aimed)  # the same number of requests at the same price
    # The typed homepage given again as a key page is still one page, and another site's address is never taken.
    assert insights.lighthouse_pages(typed, [typed, typed + "pricing"], final) == [final, typed + "pricing"]
    assert insights.lighthouse_pages(typed, [], "https://elsewhere.example/") == [typed] and insights.lighthouse_pages(typed, [], None) == [typed]
    # In a run: the worker hands the crawl's own final homepage to the plan of calls.
    seen = []

    def searching(url, options):
        seen.append(options.get("home"))
        return demo.paid_services(tmp_path / "unused").search_plan(url, options)

    client = web(provider=Bank())
    client.app.state.engine.paid.search_plan = searching
    made = plan(client, search_data=True, country="Türkiye")
    assert seen and set(seen) == {None}  # pricing the plan knows no final homepage yet
    audit = start(client, confirm(client, made))
    home = get(client, audit, "/result")["crawl"]["pages"][0]["url"]
    assert audit["state"] == "finished" and seen[-1] == home and home.endswith(f"{SHOP}/")


def test_the_command_line_matches_the_country_the_same_way_and_refuses_one_it_does_not_know(capsys):
    def prepared(*extra):
        args = cli._parser().parse_args(["crawl", "https://made-up-shop.example/", "--dfs-search-data", "--dfs-dry-run", *extra])
        args.dfs_daily_budget = pricing.daily_budget()
        return cli._dfs_prepare(args)

    code, client, calls = prepared("--dfs-country", "Türkiye (TR)")
    assert code == 0 and client is None and calls[0].payload[0]["location_code"] == 2792 and calls[0].payload[0]["language_code"] == "tr"
    assert "Turkey, tr" in calls[0].title and not any("default market" in call.title for call in calls)
    capsys.readouterr()
    code, client, calls = prepared("--dfs-country", "Atlantis")
    said = capsys.readouterr()
    assert code == 2 and client is None and calls == [] and "DataForSEO plan" not in said.out
    assert "'Atlantis'" in said.err and "Türkiye" in said.err and "United Kingdom" in said.err and "--dfs-default-market" in said.err
    code, client, calls = prepared("--dfs-country", "Atlantis", "--dfs-default-market")
    assert code == 0 and all("United States, en; default market" in call.title for call in calls[:5])
    code, _client, calls = prepared()  # no country given: the documented default, said in every title
    assert code == 0 and "default market" in calls[0].title


# -- B2: the balance ---------------------------------------------------------------------------------------------------

def test_the_balance_is_fetched_by_itself_when_a_paid_plan_is_built_and_reused_for_ten_minutes(web, automatic):
    bank = Bank(balance=12.5)
    client = web(provider=bank)
    assert paid.BALANCE_REUSE_S == 600
    assert plan(client)["balance_warning"] is None and bank.requests == []  # nothing paid ticked: nobody is asked
    assert client.get(f"{API}/budget").json()["provider_balance"]["known"] is False and bank.requests == []
    made = plan(client, backlinks=True)
    assert bank.requests == [USER_DATA] and made["paid"]["provider_balance"]["balance_usd"] == 12.5 and made["balance_warning"] is None
    assert client.get(f"{API}/budget").json()["provider_balance"]["balance_usd"] == 12.5
    # It is the free call it is: on the ledger, costing nothing, and never a secret in what is shown.
    rows = client.ledger.calls()
    assert [(row["endpoint"], row["event"], row["estimate"], row["cost"]) for row in rows] == [(USER_DATA, "free", 0.0, 0.0)] and client.ledger.spent_today() == 0
    assert not any(secret in json.dumps(made) for secret in SECRETS)
    automatic["now"] += 599
    plan(client, backlinks=True), plan(client, search_data=True, country="TR")
    assert bank.requests == [USER_DATA]  # within ten minutes the answer is reused
    automatic["now"] += 2
    bank.balance = 3.0
    later = plan(client, search_data=True, country="TR")
    assert bank.requests == [USER_DATA, USER_DATA] and later["paid"]["provider_balance"]["balance_usd"] == 3.0
    # The button still asks at once, whatever the clock says.
    fresh = client.post(f"{API}/budget/provider-balance", json={}).json()
    assert fresh["known"] and fresh["balance_usd"] == 3.0 and len(bank.requests) == 3


def test_the_balance_is_not_fetched_without_credentials_in_demo_mode_or_when_the_switch_is_off(web, automatic, tmp_path, monkeypatch):
    bank = Bank()
    without = web(provider=bank, credentials=False)
    made = plan(without, backlinks=True)
    assert bank.requests == [] and made["paid"]["blocked"]["code"] == "credentials_not_configured" and made["balance_warning"] is None
    assert without.post(f"{API}/budget/provider-balance", json={}).json()["code"] == "credentials_not_configured" and bank.requests == []
    # Demo mode: the made-up provider is asked for no balance, and no warning is ever shown.
    bank = Bank(balance=0.0)
    client = web(provider=bank, folder=tmp_path / "demo")
    client.app.state.engine.demo = True
    made = plan(client, backlinks=True)
    assert bank.requests == [] and made["balance_warning"] is None
    services = client.app.state.engine.paid
    assert paid.balance_for_plan(services, None, None, paid_wanted=True, demo=True) is None
    assert paid.balance_for_plan(services, None, None, paid_wanted=False, demo=False) is None and bank.requests == []
    assert paid.balance_warning({"requested": True, "available": True, "blocked": None, "total_usd": 1.0}, {"known": True, "balance_usd": 0.0}, demo=True) is None
    monkeypatch.setattr(paid, "AUTOMATIC_BALANCE", False)
    assert paid.balance_for_plan(services, None, None, paid_wanted=True, demo=False) is None and bank.requests == []


def test_an_account_that_does_not_answer_never_blocks_the_plan_and_is_not_asked_again_at_once(web, automatic):
    bank = Bank(balance=None)
    client = web(provider=bank)
    made = plan(client, backlinks=True)
    asked = len(bank.requests)
    assert asked >= 1 and set(bank.requests) == {USER_DATA} and made["paid"]["total_usd"] > 0
    assert made["balance_warning"]["level"] == "unknown" and [choice["id"] for choice in made["balance_warning"]["choices"]] == ["without_search_data", "run_anyway"]
    assert made["balance_warning"]["message"] == f"DataForSEO balance unknown (the account did not answer); this plan's maximum is ${strings.usd(made['paid']['total_usd'])}."
    plan(client, backlinks=True)
    assert len(bank.requests) == asked  # the failed attempt is reused for ten minutes too
    automatic["now"] += 601
    bank.balance = 40.0
    assert plan(client, backlinks=True)["balance_warning"] is None and len(bank.requests) == asked + 1


def test_the_card_says_zero_low_and_unknown_in_english_and_turkish_and_nothing_when_there_is_enough(web, automatic):
    bank = Bank(balance=0.0)
    client = web(provider=bank)
    zero = plan(client, search_data=True, country="TR")
    total = zero["paid"]["total_usd"]
    assert zero["balance_warning"] == {"level": "zero", "balance_usd": 0.0, "total_usd": total, "message": "DataForSEO balance $0.00 — search data will be empty.",
                                       "choices": [{"id": "without_search_data", "label": "Run without search data"}]}
    assert zero["can_start"] or zero["needs_confirmation"]  # the warning does not disable Start: Start asks
    automatic["now"] += 601
    bank.balance = 0.10
    low = plan(client, search_data=True, country="TR")["balance_warning"]
    assert low["level"] == "low" and low["message"] == f"DataForSEO balance $0.10 is below this plan's maximum of ${strings.usd(total)}: some panels may come back empty."
    assert low["choices"] == [{"id": "without_search_data", "label": "Run without search data"}, {"id": "run_anyway", "label": "Run anyway"}]
    in_turkish(client)
    turkish = plan(client, search_data=True, country="TR")["balance_warning"]
    comma = strings.usd(total).replace(".", ",")
    assert turkish["message"] == f"DataForSEO bakiyesi (0,10 $) bu planın en yüksek tutarının ({comma} $) altında: bazı paneller boş gelebilir."
    assert [choice["label"] for choice in turkish["choices"]] == ["Arama verisi olmadan çalıştır", "Yine de çalıştır"]
    assert strings.t("plan.balance.choice.cancel", "tr") == "Vazgeç" and strings.t("plan.balance.choice.cancel", "en") == "Cancel"
    automatic["now"] += 601
    bank.balance = 0
    assert plan(client, search_data=True, country="TR")["balance_warning"]["message"] == "DataForSEO bakiyesi 0,00 $ — arama verisi boş gelecek."
    automatic["now"] += 601
    bank.balance = None
    assert plan(client, search_data=True, country="TR")["balance_warning"]["message"] == f"DataForSEO bakiyesi bilinmiyor (hesap yanıt vermedi); bu planın en yüksek tutarı {comma} $."
    automatic["now"] += 601
    bank.balance = total  # exactly the plan's maximum is enough
    enough = plan(client, search_data=True, country="TR")
    assert enough["balance_warning"] is None and enough["paid"]["provider_balance"]["balance_usd"] == total
    # The page shows it above Start and asks once.
    script = open(strings.LOCALES.parent / "static" / "app.js", encoding="utf-8").read()
    for said in ("balance_warning", "balance_choice", "plan.balance.choice.cancel", "market_default_accepted", "plan.market.updating"):
        assert said in script, said


def test_start_at_a_zero_balance_asks_once_and_running_without_search_data_sends_dataforseo_nothing(web, automatic, tmp_path):
    bank, reader = Bank(balance=0.0), Firecrawl(PAGES)
    client = web(site=Site(respond=cloudflare), provider=bank, firecrawl=services(tmp_path, reader))
    made = plan(client, search_data=True, backlinks=True, country="Türkiye")
    assert made["balance_warning"]["level"] == "zero" and made["firecrawl"]["requested"] and bank.requests == [USER_DATA]
    asked = error(client.post(f"{API}/audits", json={"plan_id": made["id"]}), 409, "balance_decision_required")
    assert asked["message"] == "DataForSEO balance $0.00 — search data will be empty." and asked["details"]["choices"] == ["without_search_data"]
    assert asked["details"]["level"] == "zero" and asked["details"]["balance_usd"] == 0.0
    error(client.post(f"{API}/audits", json={"plan_id": made["id"], "balance_choice": "run_anyway"}), 422, "balance_choice_not_offered")
    error(client.post(f"{API}/audits", json={"plan_id": made["id"], "balance_choice": "whatever"}), 422, "invalid_request")
    assert reader.bodies == [] and client.site.requests == []  # nothing has run, nothing was spent anywhere
    response = client.post(f"{API}/audits", json={"plan_id": made["id"], "balance_choice": "without_search_data"})
    assert response.status_code == 201, response.text
    client.app.state.runner.wait(response.json()["id"], 90)
    audit = client.get(f"{API}/audits/{response.json()['id']}").json()
    assert audit["state"] == "finished" and audit["paid"] == {"requested": True, "state": "skipped", "approved_max_usd": 0.0, "skipped": True}
    assert bank.requests == [USER_DATA] and bank.bodies == [] and client.ledger.spent_today() == 0  # DataForSEO was sent no request for data
    assert [row["event"] for row in client.ledger.calls()] == ["free"]  # the balance request, and no reservation
    step = next(row for row in audit["timeline"] if row["step"] == "backlinks")
    assert step["status"] == "skipped" and "DataForSEO balance" in step["reason"]
    # The Firecrawl reading is as it would have been.
    report = get(client, audit, "/result")
    assert report["firecrawl"]["used"] and report["firecrawl"]["pages_read"] == 3 and reader.bodies
    # The report's DataForSEO section says why, check by check, in English; the page says it in the reader's language.
    section = report["dataforseo"]
    reason = "the DataForSEO balance was $0.00 when the audit started"
    assert section["note"] == f"Search data was not requested: {reason}." and section["status"] == "not_assessed"
    assert section["stopped"] == {"code": "balance_at_start", "after": None, "not_requested": [check["check_id"] for check in section["checks"]]}
    assert len(section["checks"]) == 9 and {check["summary"] for check in section["checks"]} == {f"not requested: {reason}. No request was sent."}
    assert section["requests_sent"] == 0 and section["cost_usd"] == 0 and section["calls"] == []
    view = get(client, audit, "/summary")["backlinks"]
    assert view["note_shown"] == section["note"] and not view["available"] and {check["refusal"]["code"] for check in view["checks"]} == {"not_requested_balance"}
    assert view["checks"][0]["summary"] == "Search data was not requested: the DataForSEO balance was $0.00 when the audit started."
    markdown = client.get(f"{API}/audits/{audit['id']}/downloads/markdown").text
    assert f"- **Note:** {section['note']}" in markdown and section["note"] in client.get(f"{API}/audits/{audit['id']}/print?full=true").text
    in_turkish(client)
    turkish = get(client, audit, "/summary")["backlinks"]
    assert turkish["note_shown"] == "Arama verisi istenmedi: denetim başladığında DataForSEO bakiyesi 0,00 $ idi."
    assert turkish["checks"][0]["summary"] == "Arama verisi istenmedi: denetim başladığında DataForSEO bakiyesi 0,00 $ idi."
    # The same plan started twice is the same audit, whatever the second click says.
    assert client.post(f"{API}/audits", json={"plan_id": made["id"]}).json()["id"] == audit["id"]


def test_run_anyway_at_a_low_or_unknown_balance_sends_the_requests_as_before(web, automatic):
    bank = Bank(balance=0.01)
    client = web(provider=bank)
    made = confirm(client, plan(client, backlinks=True))
    assert made["balance_warning"]["level"] == "low"
    error(client.post(f"{API}/audits", json={"plan_id": made["id"]}), 409, "balance_decision_required")
    response = client.post(f"{API}/audits", json={"plan_id": made["id"], "balance_choice": "run_anyway"})
    assert response.status_code == 201, response.text
    client.app.state.runner.wait(response.json()["id"], 90)
    audit = client.get(f"{API}/audits/{response.json()['id']}").json()
    section = get(client, audit, "/result")["dataforseo"]
    assert audit["paid"]["state"] == "done" and bank.paid == [pricing.BACKLINKS_SUMMARY, pricing.BACKLINKS_REFERRING_DOMAINS]
    assert section["status"] == "assessed" and "note" not in section and "stopped" not in section and section["cost_usd"] > 0
    # Unknown: the same two choices, and "run without" works there too.
    automatic["now"] += 601
    bank.balance = None
    assert plan(client, CAFE, backlinks=True)["balance_warning"] is None  # every figure of this plan is saved already: nothing to pay, nothing to warn about
    unknown = confirm(client, plan(client, CAFE, backlinks=True, search_data=True, country="TR"))
    assert unknown["balance_warning"]["level"] == "unknown"
    response = client.post(f"{API}/audits", json={"plan_id": unknown["id"], "balance_choice": "without_search_data"})
    client.app.state.runner.wait(response.json()["id"], 90)
    section = client.get(f"{API}/audits/{response.json()['id']}/result").json()["dataforseo"]
    # What Maya's own cache already holds costs nothing and is still shown; nothing new was asked for.
    assert len(bank.paid) == 2 and section["note"] == "Search data was not requested: the DataForSEO balance was unknown when the audit started."
    checks = {check["check_id"]: check for check in section["checks"]}
    assert checks["DFS-1"]["status"] == "observed" and checks["DFS-1"]["evidence"]["from_cache"] and checks["DFS-2"]["evidence"]["from_cache"]
    assert section["stopped"]["not_requested"] == ["DFS-3", "DFS-4", "DFS-5", "DFS-6", "DFS-7", "DFS-8", "DFS-9"] and section["cost_usd"] == 0
    assert checks["DFS-3"]["summary"] == "not requested: the DataForSEO balance was unknown when the audit started. No request was sent."


def engine_client(tmp_path, bank):
    return DataForSEOClient(Credentials(*SECRETS), Ledger(tmp_path / "ledger.jsonl"), Cache(tmp_path / "cache.sqlite"), daily_budget=100.0,
                            approved_usd=10.0, approved_always_ask=True, audit_id="made-up", transport=httpx.MockTransport(bank))


@pytest.mark.parametrize("code", [40200, 40210])
def test_a_first_refusal_for_no_credit_stops_the_run_after_one_request(tmp_path, code):
    bank = Bank(refuse_from=1, code=code)
    client = engine_client(tmp_path, bank)
    calls = insights.audit_plan("https://made-up-shop.example/", country="Türkiye")
    with pytest.raises(NoCredit) as refused:
        client.request(calls[0].endpoint, calls[0].payload, target=calls[0].target)
    assert refused.value.code == code and len(bank.requests) == 1
    bank.requests.clear()
    client = engine_client(tmp_path / "again", bank)
    section = panel.run_checks(calls, client)
    client.close()
    assert len(bank.requests) == 1 and section["requests_sent"] == 1 and section["cost_usd"] == 0 and section["status"] == "not_assessed"
    first, rest = section["checks"][0], section["checks"][1:]
    assert first["summary"] == f"not assessed: the DataForSEO account has no credit for this request (provider code {code}). Nothing was charged."
    assert "Payment Required" not in json.dumps(section) and "Insufficient Funds" not in json.dumps(section)
    assert len(rest) == 6 and {check["summary"] for check in rest} == {
        "not requested: the DataForSEO account balance ran out earlier in this audit. No request was sent."}
    assert all(check["status"] == "not_assessed" and "evidence" not in check for check in section["checks"])
    assert section["stopped"] == {"code": "provider_credits_insufficient", "after": "DFS-3", "not_requested": [check["check_id"] for check in rest]}
    assert section["note"] == "DataForSEO refused a request because the account has no credit, so the remaining 6 were not sent. Nothing was charged for them."
    # The ledger: one reservation, settled at what the provider reported (nothing), and no second try.
    rows = Ledger(tmp_path / "again" / "ledger.jsonl").calls()
    assert len(rows) == 1 and rows[0]["status"] == "settled" and Ledger(tmp_path / "again" / "ledger.jsonl").spent_today() == 0
    assert section["note"] in panel.render_text(section) and f"- **Note:** {section['note']}" in panel.render_markdown(section)
    # Shown in the reader's language.
    for language, starts in (("en", "DataForSEO refused a request"), ("tr", "DataForSEO, hesapta kredi olmadığı için")):
        shown, translated = wording.line(section["note"], language)
        assert translated and shown.startswith(starts) and "6" in shown


def test_a_refusal_on_the_second_request_keeps_the_first_panel_and_leaves_the_rest_unasked(web):
    bank = Bank(refuse_from=2)
    client = web(provider=bank)
    audit = start(client, confirm(client, plan(client, search_data=True, country="Türkiye")))
    assert audit["state"] == "finished" and audit["paid"]["state"] == "done" and len(bank.paid) == 2  # the second was refused; five were never sent
    section = get(client, audit, "/result")["dataforseo"]
    checks = {check["check_id"]: check for check in section["checks"]}
    assert checks["DFS-3"]["status"] == "observed" and checks["DFS-3"]["evidence"]["data"]["metrics"] and section["status"] == "partly_assessed"
    assert checks["DFS-4"]["summary"].startswith("not assessed: the DataForSEO account has no credit for this request (provider code 40200).")
    assert section["stopped"] == {"code": "provider_credits_insufficient", "after": "DFS-4", "not_requested": ["DFS-5", "DFS-6", "DFS-7", "DFS-8", "DFS-9"]}
    assert section["note"].startswith("DataForSEO refused a request because the account has no credit, so the remaining 5 were not sent.")
    assert section["requests_sent"] == 2 and section["cost_usd"] == pytest.approx(client.ledger.spent_today()) and section["cost_usd"] > 0  # the first panel's own cost
    assert [row["status"] for row in client.ledger.calls()] == ["settled", "settled"]
    view = get(client, audit, "/summary")["backlinks"]
    codes = [check["refusal"]["code"] if check["refusal"] else None for check in view["checks"]]
    assert codes == [None, "provider_credits_insufficient", *["not_requested_no_credit"] * 5] and view["available"]
    assert view["checks"][1]["summary"].startswith("DataForSEO account credits are insufficient")
    assert view["checks"][2]["summary"] == "Not requested: the DataForSEO account balance ran out earlier in this audit. No request was sent."
    assert view["note"] == section["note"] and view["stopped"]["after"] == "DFS-4"
    in_turkish(client)
    turkish = get(client, audit, "/summary")["backlinks"]
    assert turkish["note_shown"].startswith("DataForSEO, hesapta kredi olmadığı için bir isteği reddetti; bu nedenle kalan 5 istek gönderilmedi.")
    assert turkish["checks"][2]["summary"] == "İstenmedi: DataForSEO hesap bakiyesi bu denetimde daha önce tükendi. İstek gönderilmedi."
    assert turkish["checks"][1]["summary"].startswith("DataForSEO hesap kredisi yetersiz")
    printed = client.get(f"{API}/audits/{audit['id']}/print?full=true&lang=tr").text
    assert "kalan 5 istek gönderilmedi" in printed and "Payment Required" not in printed


def test_what_the_cache_holds_is_still_shown_after_the_account_ran_out(tmp_path):
    calls = insights.audit_plan("https://made-up-shop.example/", country="Türkiye")
    funded = Bank()
    client = engine_client(tmp_path, funded)
    client.request(calls[3].endpoint, calls[3].payload, target=calls[3].target)  # DFS-6 was fetched on an earlier day
    client.close()
    broke = Bank(refuse_from=1)
    client = engine_client(tmp_path, broke)
    section = panel.run_checks(calls, client)
    client.close()
    checks = {check["check_id"]: check for check in section["checks"]}
    assert len(broke.requests) == 1 and checks["DFS-6"]["status"] == "observed" and checks["DFS-6"]["evidence"]["from_cache"] is True
    assert section["stopped"]["not_requested"] == ["DFS-4", "DFS-5", "DFS-7", "DFS-8", "DFS-9"] and "remaining 5 were not sent" in section["note"]


def test_a_funded_account_runs_every_panel_exactly_as_before(web, automatic, monkeypatch, tmp_path):
    def run(client):
        made = plan(client, search_data=True, market_default_accepted=True, local_business=True)
        audit = start(client, confirm(client, made))
        return made, audit, get(client, audit, "/result")["dataforseo"]

    bank = Bank(balance=50.0)
    made, audit, section = run(web(provider=bank))
    assert made["balance_warning"] is None and audit["paid"] == {"requested": True, "state": "done", "approved_max_usd": made["paid"]["total_usd"], "skipped": False}
    assert bank.requests[0] == USER_DATA and len(bank.paid) == 8 and bank.requests.count(USER_DATA) == 1
    assert section["status"] == "assessed" and section["requests_sent"] == 8 and "note" not in section and "stopped" not in section
    # The same audit with the automatic balance switched off (the rule before this change): the same requests, the same report text.
    monkeypatch.setattr(paid, "AUTOMATIC_BALANCE", False)
    old = Bank()
    for saved in (tmp_path / "paid").glob(CACHE_NAME + "*"):  # the first run's answers are forgotten, so the second asks again
        saved.unlink()
    _made, _audit, before = run(web(provider=old, folder=tmp_path / "second"))
    assert old.requests == bank.paid

    def text(found):
        return [(check["check_id"], check["title"], check["status"], check["summary"]) for check in found["checks"]]

    assert text(before) == text(section) and before["requests_sent"] == section["requests_sent"] and before["cost_usd"] == section["cost_usd"]
