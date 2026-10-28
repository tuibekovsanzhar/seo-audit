"""Phase 1C: a missing measurement is never a zero or a healthy reading, and each provider answer says what it is.

Every DataForSEO answer here is an offline fixture in the shapes its public documentation describes; no endpoint is called.
"""
import json

import httpx
import pytest

from maya_audit.dataforseo import DataForSEOClient, Ledger, insights, panel, pricing
from maya_audit.dataforseo.cache import CACHE_NAME, Cache
from maya_audit.dataforseo.credentials import Credentials
from maya_audit.dataforseo.ledger import LEDGER_NAME

SITE = "https://www.brand.example/"


def run(tmp_path, results, *, check_ids, task_status=20000, message="Ok.", top_status=20000, http=200, **plan):
    """Run the named checks of the shipped plan against one canned result per endpoint."""
    def api(request):
        by_endpoint = isinstance(results, dict) and any(str(key).startswith("/v3/") for key in results)
        result = results.get(request.url.path) if by_endpoint else results
        task = {"status_code": task_status, "status_message": message, "cost": 0.01 if task_status == 20000 else 0,
                "result": None if result is None else [result]}
        return httpx.Response(http, json={"status_code": top_status, "status_message": "Ok.", "tasks": [task]})
    client = DataForSEOClient(Credentials("login", "password-made-up"), Ledger(tmp_path / LEDGER_NAME), Cache(tmp_path / CACHE_NAME),
                              daily_budget=5.0, approved_usd=5.0, approved_always_ask=True, transport=httpx.MockTransport(api))
    calls = [c for c in insights.audit_plan(SITE, country="United States", **plan) if c.check_id in check_ids]
    section = panel.run_checks(calls, client)
    return {c["check_id"]: c for c in section["checks"]}, section


def mentions(platform):
    return {"total": {"platform": platform, "sources_domain": [{"key": "review.example", "mentions": 3, "ai_search_volume": 900}],
                      "search_results_domain": [{"key": "brand.example", "mentions": 2, "ai_search_volume": 500}]}, "items": None}


@pytest.mark.parametrize("platform, status, starts, sample", [
    ([{"key": "google", "mentions": 0, "ai_search_volume": 0}], "observed", "Measured zero:", "measured_zero"),
    ([], "observed", "DataForSEO returned an empty sample:", "empty"),
    ([{"key": "google", "mentions": 7, "ai_search_volume": 1200}], "observed", "7 AI answer(s) in DataForSEO's sample match this domain", "matches"),
    ([{"key": "google", "mentions": 7}], "partial", "7 AI answer(s)", "matches"),
])
def test_a_measured_zero_an_empty_sample_and_real_matches_are_three_different_answers(tmp_path, platform, status, starts, sample):
    checks, section = run(tmp_path, mentions(platform), check_ids=("DFS-7",))
    check = checks["DFS-7"]
    assert check["status"] == status and check["summary"].startswith(starts) and check["evidence"]["data"]["sample"] == sample
    assert "cited as a source of an AI answer, named in its text, or listed among the search results" in check["evidence"]["data"]["scope"]
    if status == "partial":
        assert check["evidence"]["data"]["missing_measurements"] == ["monthly volume of the questions"] and section["status"] == "partly_assessed"


@pytest.mark.parametrize("broken", [
    {"total": None}, {"total": {"platform": None}}, {"items": None},
    {"total": {"platform": [{"key": "google"}]}},                       # the row is there, the number is not
    {"total": {"platform": [{"key": "google", "mentions": None}]}},
    {"total": {"platform": [{"key": "google", "mentions": "12"}]}},     # text is not a count
    {"total": {"platform": [{"key": "google", "mentions": True}]}},
])
def test_a_missing_null_or_wrong_typed_mention_count_is_not_assessed_and_never_no_mention_found(tmp_path, broken):
    checks, section = run(tmp_path, broken, check_ids=("DFS-7",))
    check = checks["DFS-7"]
    assert check["status"] == "not_assessed" and "could not be read" in check["summary"] and section["status"] == "not_assessed"
    said = json.dumps(check)
    assert "Measured zero" not in said and "empty sample" not in said and "No mention" not in said
    assert check["evidence"]["cost_usd"] == 0.01  # what it cost is still shown


def lighthouse(score=0.91, **audits):
    return {"categories": {} if score is None else {"performance": {"score": score}, "seo": {"score": 0.9}},
            "audits": {key.replace("_", "-"): {"numericValue": value, "displayValue": str(value)} for key, value in audits.items()}}


def test_lighthouse_calls_a_metric_good_only_when_it_was_measured(tmp_path):
    healthy, section = run(tmp_path / "a", lighthouse(largest_contentful_paint=1800, cumulative_layout_shift=0.02, total_blocking_time=90), check_ids=("DFS-9",))
    assert healthy["DFS-9"]["status"] == "observed" and "the three main lab metrics are within Google's \"good\" thresholds" in healthy["DFS-9"]["summary"]
    poor, _ = run(tmp_path / "b", lighthouse(largest_contentful_paint=5200, cumulative_layout_shift=0.31, total_blocking_time=90), check_ids=("DFS-9",))
    assert poor["DFS-9"]["evidence"]["data"]["past_good_threshold"] == ["Largest Contentful Paint", "Cumulative Layout Shift"]
    assert "within the threshold: Total Blocking Time" in poor["DFS-9"]["summary"]
    # A score with no timings: the old code said "the three main lab metrics are within Google's good thresholds".
    bare, section = run(tmp_path / "c", lighthouse(), check_ids=("DFS-9",))
    check = bare["DFS-9"]
    assert check["status"] == "partial" and section["status"] == "partly_assessed" and "within Google's" not in check["summary"]
    assert "not measured in this answer, so not judged: Largest Contentful Paint, Cumulative Layout Shift, Total Blocking Time" in check["summary"]
    assert check["evidence"]["data"]["past_good_threshold"] == [] and check["evidence"]["data"]["within_good_threshold"] == []
    half, _ = run(tmp_path / "d", lighthouse(largest_contentful_paint=1800), check_ids=("DFS-9",))
    assert half["DFS-9"]["status"] == "partial" and "within the threshold: Largest Contentful Paint" in half["DFS-9"]["summary"]
    assert half["DFS-9"]["evidence"]["data"]["missing_measurements"] == ["Cumulative Layout Shift", "Total Blocking Time"]
    timings_only, _ = run(tmp_path / "e", lighthouse(None, largest_contentful_paint=1800, cumulative_layout_shift=0.02, total_blocking_time=90), check_ids=("DFS-9",))
    assert "no performance score was reported" in timings_only["DFS-9"]["summary"] and timings_only["DFS-9"]["status"] == "partial"
    nothing, _ = run(tmp_path / "f", {"categories": {}, "audits": {}}, check_ids=("DFS-9",))
    assert nothing["DFS-9"]["status"] == "not_assessed"
    for check in (healthy["DFS-9"], poor["DFS-9"], check):
        assert "not what real visitors experienced" in check["summary"] and "Interaction to Next Paint" not in json.dumps(check)


def test_rankings_tell_an_empty_sample_from_an_unreadable_answer(tmp_path):
    empty, _ = run(tmp_path / "a", {"total_count": 0, "items": []}, check_ids=("DFS-3", "DFS-4", "DFS-6"))
    assert empty["DFS-3"]["status"] == "observed" and "empty sample" in empty["DFS-3"]["summary"] and "not a measurement that the site ranks for nothing" in empty["DFS-3"]["summary"]
    assert empty["DFS-4"]["evidence"]["data"]["listed"] == 0 and empty["DFS-6"]["evidence"]["data"]["listed"] == 0
    null_items, _ = run(tmp_path / "b", {"total_count": 0, "items": None}, check_ids=("DFS-4",))
    assert null_items["DFS-4"]["status"] == "observed"  # the provider says the total is zero
    unreadable, _ = run(tmp_path / "c", {"items": None}, check_ids=("DFS-3", "DFS-4", "DFS-6"))
    assert {c["status"] for c in unreadable.values()} == {"not_assessed"}
    no_count, _ = run(tmp_path / "d", {"items": [{"metrics": {"organic": {"etv": 12.0}}}]}, check_ids=("DFS-3",))
    assert no_count["DFS-3"]["status"] == "not_assessed" and "no count of ranked keywords" in no_count["DFS-3"]["summary"]
    part, _ = run(tmp_path / "e", {"items": [{"metrics": {"organic": {"count": 12, "pos_1": 1}}}]}, check_ids=("DFS-3",))
    assert part["DFS-3"]["status"] == "partial" and "Not reported by the provider: estimated organic visits" in part["DFS-3"]["summary"]
    odd, _ = run(tmp_path / "f", {"total_count": 3, "items": [{"keyword_data": {"keyword": "kettle", "keyword_info": {"search_volume": "many"}},
                                                                 "ranked_serp_element": {"serp_item": {"rank_group": None}}}]}, check_ids=("DFS-4",))
    assert odd["DFS-4"]["evidence"]["data"]["table"]["rows"] == [["kettle", None, None, None]]  # shown as not reported, never as 0


@pytest.mark.parametrize("task_status, message, code", [
    (40204, "Access denied. Visit Plans and Subscriptions to activate your subscription and get access to this API.", "provider_subscription_missing"),
    (40200, "Payment Required.", "provider_credits_insufficient"),
    (40501, "Invalid Field: 'location_code'.", "unsupported_request"),
    (50000, "Internal Error.", "provider_error"),
])
def test_a_refusal_is_named_for_what_it_is_and_only_a_low_balance_says_to_add_credit(tmp_path, task_status, message, code):
    from maya_audit_web import paid
    checks, section = run(tmp_path, None, check_ids=("DFS-7",), task_status=task_status, message=message)
    check = checks["DFS-7"]
    assert check["status"] == "not_assessed" and str(task_status) in check["summary"]
    refusal = paid.refusal(check["summary"])
    assert refusal["code"] == code
    assert ("add credit" in refusal["message"]) == (code == "provider_credits_insufficient")  # only a low balance is fixed by adding credit
    local = paid.refusal("not assessed: DataForSEO daily budget reached: $99.9000 already spent or reserved today (UTC)")
    assert local["code"] == "daily_limit_reached" and "credit" not in local["message"].lower()


def test_a_profile_found_by_name_is_the_business_only_when_its_website_is_the_audited_domain(tmp_path):
    profile = {"type": "google_business_info", "title": "Maximum", "category": "Gym", "address": "1 Other Street", "phone": None,
               "url": "https://maximum-gym.example/", "rating": {"value": 4.1, "votes_count": 88}, "is_claimed": False}
    other, _ = run(tmp_path / "a", {"items": [profile]}, check_ids=("DFS-12",), brand="Maximum", local_business=True)
    data = other["DFS-12"]["evidence"]["data"]
    assert data["identity_confirmed"] is False and data["missing"] == [] and "Identity NOT confirmed" in other["DFS-12"]["summary"]
    assert "another business may share the name" in other["DFS-12"]["summary"] and "Missing on the profile" not in other["DFS-12"]["summary"]
    ours = {**profile, "title": "Brand", "url": "https://www.brand.example/contact"}
    mine, _ = run(tmp_path / "b", {"items": [profile, ours]}, check_ids=("DFS-12",), brand="Brand", local_business=True)
    data = mine["DFS-12"]["evidence"]["data"]
    assert data["identity_confirmed"] is True and data["metrics"]["Name"] == "Brand" and data["missing"] == ["phone", "claimed by the owner"]
    assert "Identity confirmed: the profile's website is the audited domain" in mine["DFS-12"]["summary"]
    none, _ = run(tmp_path / "c", {"items": []}, check_ids=("DFS-12",), brand="Brand", local_business=True)
    assert none["DFS-12"]["evidence"]["data"]["found"] is False and none["DFS-12"]["status"] == "observed"
    from maya_audit_web import practical
    view = lambda checks: {"checks": [{"check_id": c["check_id"], "status": c["status"], "data": c["evidence"]["data"]} for c in checks.values()]}  # noqa: E731
    assert not [line for line in practical.opportunities(view(other), None, []) if "Business Profile" in line]  # nothing advised for a stranger's profile
    assert [line for line in practical.opportunities(view(mine), None, []) if "Business Profile is missing: phone" in line]


def test_the_market_and_the_chatgpt_limit_are_said_before_anything_is_paid():
    known = insights.audit_plan(SITE, country="Türkiye")
    assert "(Turkey, tr)" in known[0].title and known[4].payload[0]["platform"] == "google" and known[4].payload[0]["location_code"] == 2792
    chatgpt = known[5]
    assert chatgpt.payload[0]["location_code"] == 2840 and chatgpt.payload[0]["language_code"] == "en"
    assert "United States, English only" in chatgpt.title and "whatever the audit's market" in chatgpt.title and "Turkey" not in chatgpt.title
    unknown = insights.audit_plan(SITE, country="Atlantis")
    assert all("default market" in call.title for call in unknown[:5]) and insights.location_for("Atlantis")[3] is False
    assert insights.market_warning("Atlantis") and "United States" in insights.market_warning("Atlantis") and insights.market_warning("Türkiye") is None
    assert insights.market_warning("") and "no country" in insights.market_warning("").lower()
    assert known[4].payload[0]["target"] == [{"domain": "brand.example", "search_scope": ["any"]}]  # the paid request itself is unchanged
