"""The search data panels (DFS-3 onwards) and Core Web Vitals from CrUX.

DataForSEO and Google are mock transports answering in their documented shapes with made-up figures
(maya_audit_web.demo.search_data). Nothing here can reach either service.
"""
import json

import httpx
import pytest

from maya_audit import crux
from maya_audit.dataforseo import DataForSEOClient, Ledger, insights, panel, pricing
from maya_audit.dataforseo.cache import CACHE_NAME, Cache
from maya_audit.dataforseo.credentials import Credentials
from maya_audit.dataforseo.ledger import LEDGER_NAME
from maya_audit_web import demo

SITE = "https://www.demo-shop.example/"


class Api:
    def __init__(self, fail=()):
        self.bodies, self.fail = [], set(fail)

    def __call__(self, request):
        assert request.url.host == "api.dataforseo.com" and request.headers["authorization"].startswith("Basic ")
        payload = json.loads(request.content)
        self.bodies.append((request.url.path, payload))
        if request.url.path in self.fail:
            return httpx.Response(200, json={"status_code": 20000, "tasks": [{"status_code": 40204, "status_message": "Access denied. Visit Plans and Subscriptions to activate your subscription.", "cost": 0}]})
        cost, result = demo.search_data(request.url.path, payload)
        task = {"status_code": 20000, "status_message": "Ok.", "cost": cost, "result": [result]}
        return httpx.Response(200, json={"status_code": 20000, "status_message": "Ok.", "cost": cost, "tasks": [task]})


def client(tmp_path, api, approved=2.0):
    return DataForSEOClient(Credentials("login", "password-made-up"), Ledger(tmp_path / LEDGER_NAME), Cache(tmp_path / CACHE_NAME),
                            daily_budget=2.0, approved_usd=approved, approved_always_ask=True, transport=httpx.MockTransport(api))


def test_the_plan_names_every_call_its_market_and_an_upper_bound_price(tmp_path):
    plan = insights.audit_plan(SITE, country="Türkiye", brand="Demo Shop", key_pages=[SITE + "kettles", SITE + "teapots", SITE + "sets"], local_business=True)
    assert [call.check_id for call in plan] == ["DFS-3", "DFS-4", "DFS-5", "DFS-6", "DFS-7", "DFS-8", "DFS-9", "DFS-10", "DFS-11", "DFS-12"]
    assert all(call.target and not call.not_sent for call in plan)
    labs = [call for call in plan if "dataforseo_labs" in call.endpoint]
    assert all(call.payload[0]["target"] == "demo-shop.example" and call.payload[0]["location_code"] == 2792 and call.payload[0]["language_code"] == "tr" for call in labs)
    quick = plan[2].payload[0]
    assert quick["filters"] == [["ranked_serp_element.serp_item.rank_group", ">=", 4], "and", ["ranked_serp_element.serp_item.rank_group", "<=", 20]]
    assert plan[5].payload[0]["platform"] == "chat_gpt" and plan[5].payload[0]["location_code"] == 2840  # ChatGPT: United States only
    assert [call.payload[0]["url"] for call in plan[6:9]] == [SITE, SITE + "kettles", SITE + "teapots"]  # homepage and two key pages
    assert plan[9].payload == [{"keyword": "Demo Shop", "location_code": 2792, "language_code": "tr"}]
    rows, total = panel.preview_rows(plan, None)
    assert all(row["state"] == "paid" and row["estimate_usd"] > 0 for row in rows)
    assert total == pytest.approx(0.0121 + 0.024 + 0.018 + 0.0144 + 0.101 + 0.101 + 3 * 0.005 + 0.0054, abs=0.001)
    # No country this tool knows: the United States, said in the title. No brand: the profile lookup is not sent.
    vague = insights.audit_plan(SITE, country="Atlantis", local_business=True)
    assert "United States, en; default market" in vague[0].title and vague[0].payload[0]["location_code"] == 2840
    assert vague[-1].check_id == "DFS-12" and "names no brand" in vague[-1].not_sent
    assert all(call.not_sent for call in insights.audit_plan("http://127.0.0.1:8000/"))
    assert "DFS-12" not in [call.check_id for call in insights.audit_plan(SITE)]  # only for a business the plan says is local


def test_each_panel_is_read_into_a_sentence_figures_and_a_table_with_source_and_date(tmp_path):
    api = Api()
    plan = insights.audit_plan(SITE, country="United States", brand="Demo Cafe", local_business=True)
    section = panel.run_checks(plan, client(tmp_path, api))
    by_id = {check["check_id"]: check for check in section["checks"]}
    assert section["panel"] == "Search data" and section["status"] == "assessed" and section["requests_sent"] == len(plan) == len(api.bodies)
    assert all(check["status"] == "observed" and check["evidence"]["source"].startswith("DataForSEO /v3/") and check["evidence"]["data_from"]
               and check["evidence"]["from_cache"] is False for check in section["checks"])
    assert "164 keyword(s) ranked in Google's top 100" in by_id["DFS-3"]["summary"] and by_id["DFS-3"]["evidence"]["data"]["metrics"]["Keywords in position 4–10"] == 31
    ranked = by_id["DFS-4"]["evidence"]["data"]
    assert ranked["table"]["columns"] == ["Keyword", "Searches a month", "Position", "Ranking page"] and ranked["table"]["rows"][0] == ["demo shop", 5400, 1, "https://demo-shop.example/"]
    wins = by_id["DFS-5"]
    assert "58 keyword(s) rank in positions 4 to 20" in wins["summary"] and all(4 <= row[2] <= 20 for row in wins["evidence"]["data"]["table"]["rows"])
    assert [row[0] for row in by_id["DFS-6"]["evidence"]["data"]["table"]["rows"]][:2] == ["demo-shop.example", "made-up-rival-one.example"]  # as DataForSEO lists them
    assert "38 AI answer(s) in DataForSEO's sample match this domain" in by_id["DFS-7"]["summary"] and "not every answer" in by_id["DFS-7"]["summary"]
    assert "wider than \"the brand is mentioned in the answer\"" in by_id["DFS-7"]["summary"] and by_id["DFS-7"]["status"] == "observed"
    assert by_id["DFS-8"]["summary"].startswith("Measured zero:") and "not proof of absence" in by_id["DFS-8"]["summary"]
    assert by_id["DFS-8"]["evidence"]["data"]["sample"] == "measured_zero" and "English only" in by_id["DFS-8"]["title"]
    lab = by_id["DFS-9"]
    assert "performance 62 of 100" in lab["summary"] and lab["evidence"]["data"]["past_good_threshold"] == ["Largest Contentful Paint", "Total Blocking Time"]
    assert "not what real visitors experienced" in lab["summary"]
    profile = by_id["DFS-12"]
    # Found by name only, and its website is another domain: shown, with nothing recommended.
    assert "rated 4.4 from 212 review(s)" in profile["summary"] and "Identity NOT confirmed" in profile["summary"]
    assert profile["evidence"]["data"]["identity_confirmed"] is False and profile["evidence"]["data"]["missing"] == []
    assert profile["evidence"]["data"]["missing_if_this_is_the_business"] == ["phone", "claimed by the owner"]
    assert section["cost_usd"] == pytest.approx(sum(call["cost_usd"] for call in section["calls"])) and 0 < section["cost_usd"] <= section["estimated_usd"]
    text, markdown = panel.render_text(section), panel.render_markdown(section)
    assert "DataForSEO: search data" in text and "made-up kettle reviews | 2,400 | 6 |" in text and "source: DataForSEO /v3/dataforseo_labs/google/ranked_keywords/live; data from" in text
    assert "## DataForSEO: search data" in markdown and "| made-up-rival-one.example | 61 | 14.2 | 2,300 | 9,100.0 |" in markdown
    assert "password-made-up" not in json.dumps(section) + text + markdown
    # A second audit inside the cache lifetime sends and pays nothing.
    again = panel.run_checks(plan, client(tmp_path, api))
    assert again["requests_sent"] == 0 and again["cost_usd"] == 0 and all(c["evidence"]["from_cache"] for c in again["checks"])


def test_a_missing_subscription_an_odd_answer_and_a_small_approval_are_each_not_assessed_never_zero(tmp_path):
    api = Api(fail={pricing.LLM_MENTIONS_AGGREGATED})
    section = panel.run_checks(insights.audit_plan(SITE), client(tmp_path, api))
    by_id = {check["check_id"]: check for check in section["checks"]}
    assert section["status"] == "partly_assessed" and by_id["DFS-7"]["status"] == by_id["DFS-8"]["status"] == "not_assessed"
    assert "40204" in by_id["DFS-7"]["summary"] and by_id["DFS-3"]["status"] == "observed"
    odd = lambda request: httpx.Response(200, json={"status_code": 20000, "tasks": [{"status_code": 20000, "cost": 0.005, "result": [{"categories": {}}]}]})  # noqa: E731
    lab = panel.run_checks([call for call in insights.audit_plan(SITE) if call.check_id == "DFS-9"], client(tmp_path / "odd", odd))
    assert lab["checks"][0]["status"] == "not_assessed" and "could not be read" in lab["checks"][0]["summary"]
    tight = panel.run_checks(insights.audit_plan(SITE), client(tmp_path / "tight", Api(), approved=0.03))
    assert [c["status"] for c in tight["checks"]][:3] == ["observed", "not_assessed", "not_assessed"] and "above the approved" in tight["checks"][1]["summary"]


def test_the_new_prices_are_listed_estimated_and_cached():
    for endpoint in (pricing.LABS_DOMAIN_OVERVIEW, pricing.LABS_RANKED_KEYWORDS, pricing.LABS_COMPETITORS, pricing.LLM_MENTIONS_AGGREGATED,
                     pricing.LIGHTHOUSE, pricing.BUSINESS_INFO):
        assert endpoint in pricing.PRICE_ESTIMATORS and endpoint in pricing.LISTED_PRICES and pricing.CACHE_LIFETIME_S[endpoint] >= pricing.DAY
    assert pricing.estimate(pricing.LABS_RANKED_KEYWORDS, [{"limit": 100}]) == 0.024 and pricing.estimate(pricing.LABS_RANKED_KEYWORDS, [{}]) == 0.024
    assert pricing.estimate(pricing.LLM_MENTIONS_AGGREGATED, [{}]) == 0.101 and pricing.estimate(pricing.LIGHTHOUSE, [{}]) == 0.005


# -- Core Web Vitals (CrUX) ---------------------------------------------------------------------------------------
RECORD = {"record": {"key": {"origin": "https://shop.test", "formFactor": "PHONE"}, "metrics": {
    "largest_contentful_paint": {"percentiles": {"p75": 3100}}, "interaction_to_next_paint": {"percentiles": {"p75": 180}},
    "cumulative_layout_shift": {"percentiles": {"p75": "0.31"}}, "first_contentful_paint": {"percentiles": {"p75": 1900}}},
    "collectionPeriod": {"firstDate": {"year": 2026, "month": 9, "day": 8}, "lastDate": {"year": 2026, "month": 10, "day": 5}}}}


def test_without_a_key_core_web_vitals_are_said_to_be_not_available_and_nothing_is_sent():
    assert crux.load_key() is None
    section = crux.collect("https://shop.test/", transport=httpx.MockTransport(lambda r: pytest.fail("no request without a key")))
    assert section["status"] == "not_available" and section["summary"] == "Core Web Vitals not available (no API key)"


def test_core_web_vitals_are_read_rated_and_dated_and_the_key_is_never_shown(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("MAYA_AUDIT_CRUX_API_KEY=made-up-google-key-123\n")
    monkeypatch.setenv("MAYA_AUDIT_ENV_FILE", str(env))
    seen = []

    def google(request):
        seen.append(request)
        assert request.url.host == "chromeuxreport.googleapis.com" and request.headers.get("x-goog-api-key") == "made-up-google-key-123" and "key" not in request.url.params
        assert json.loads(request.content) == {"origin": "https://shop.test", "formFactor": "PHONE"}
        return httpx.Response(200, json=RECORD)

    section = crux.collect("https://shop.test/some/page", transport=httpx.MockTransport(google))
    rated = {row["metric"]: (row["shown"], row["rating"]) for row in section["metrics"]}
    assert len(seen) == 1 and section["status"] == "assessed" and section["passes_core_web_vitals"] is False and section["data_until"] == "2026-10-05"
    assert rated == {"largest_contentful_paint": ("3.1 s", "needs improvement"), "interaction_to_next_paint": ("180 ms", "good"),
                     "cumulative_layout_shift": ("0.31", "poor"), "first_contentful_paint": ("1.9 s", None)}
    assert "Largest Contentful Paint (LCP) 3.1 s (needs improvement)" in section["summary"]
    text = "\n".join(crux.lines(section)) + crux.markdown(section) + json.dumps(section)
    assert "made-up-google-key-123" not in text and "real Chrome visitors on phones" in text and "data up to 2026-10-05" in text
    from maya_audit import schema
    assert set(section) <= set(schema.CRUX_KEYS)

    few = crux.collect("https://shop.test/", transport=httpx.MockTransport(lambda r: httpx.Response(404, json={"error": {"message": "chrome ux report data not found"}})))
    assert few["status"] == "not_available" and "too few real Chrome visits" in few["summary"]
    bad = crux.collect("https://shop.test/", transport=httpx.MockTransport(lambda r: httpx.Response(400, json={"error": {"message": "API key not valid: made-up-google-key-123"}})))
    assert bad["status"] == "not_available" and "HTTP 400" in bad["summary"] and "made-up-google-key-123" not in json.dumps(bad)

    def down(request):
        raise httpx.ConnectError("no route")
    assert "could not be reached" in crux.collect("https://shop.test/", transport=httpx.MockTransport(down))["summary"]
