"""DECISIONS 330-332. Speed with politeness kept (the site limit steps back up after fast answers; the audit's own
thread goes first; access and llms.txt's links to this site on lanes beside index, structure and rendering); every web
mode reads the Akıllı selection, plus "Özel sayı" and "Tam tarama sırası"; one Google key for Core Web Vitals and
PageSpeed. Offline: in-memory sites, a fake clock, a made-up key and recorded answers; nothing is requested."""
from __future__ import annotations

import json

import httpx
import pytest

from maya_audit import crux
from maya_audit.sitelimit import FAST_S, MAYA, STEP_UP_AFTER, SiteLimiter
from test_preview16_measure import KAFE, audit, clock, paced, site  # noqa: F401  (fixture)
from test_web_app import API, plan, web  # noqa: F401  (fixture)


# ---------------------------------------------------------------- 1: the site limit steps back up

def _slowed(limit=5):
    limiter = SiteLimiter(limit=limit)
    limiter.back_off("slow", "maya")
    limiter.back_off("slow", "maya")
    return limiter


def test_a_limit_lowered_for_slow_answers_steps_back_up_after_a_run_of_fast_ones():
    limiter = _slowed()
    assert limiter.limit == 1
    for _ in range(STEP_UP_AFTER - 1):
        assert limiter.answered(FAST_S / 2) is None
    assert limiter.answered(0.1) == 2 and limiter.limit == 2
    limiter.answered(0.2)
    limiter.answered(FAST_S + 0.5)  # one answer of a second or more starts the count again
    for _ in range(STEP_UP_AFTER - 1):
        limiter.answered(0.1)
    assert limiter.limit == 2
    limiter.answered(0.1)
    assert limiter.limit == 5  # back to the configured limit, never above it
    for _ in range(3 * STEP_UP_AFTER):
        limiter.answered(0.1)
    assert limiter.limit == 5
    summary = limiter.summary()
    assert [(s["from"], s["to"]) for s in summary["stepped_up"]] == [(1, 2), (2, 5)]
    assert [(s["from"], s["to"]) for s in summary["backed_off"]] == [(5, 2), (2, 1)]


@pytest.mark.parametrize("reason", ["429", "5xx", "no answer"])
def test_a_limit_lowered_for_a_429_a_5xx_or_no_answer_stays_down(reason):
    limiter = SiteLimiter(limit=5)
    limiter.back_off(reason, "maya")
    for _ in range(5 * STEP_UP_AFTER):
        limiter.answered(0.05)
    assert limiter.limit == 2 and limiter.summary()["stepped_up"] == []


def test_a_limit_of_one_from_the_start_never_goes_up():
    limiter = SiteLimiter(limit=1)  # a Crawl-delay or a rate-limited crawl (audit.site_limit_for)
    for _ in range(5 * STEP_UP_AFTER):
        limiter.answered(0.05)
    assert limiter.limit == 1


def test_a_bad_answer_resets_the_run():
    limiter = _slowed()
    for _ in range(STEP_UP_AFTER - 1):
        limiter.answered(0.1)
    limiter.answered(None, bad=True)
    limiter.answered(0.1)
    assert limiter.limit == 1


def test_lanes_leave_slot_0_to_the_audits_own_thread_while_it_waits():
    limiter = SiteLimiter(limit=1)
    assert limiter._candidates(MAYA, main=False) == [0]
    limiter._main_waiting = True
    assert limiter._candidates(MAYA, main=False) == [] and limiter._candidates(MAYA, main=True) == [0]
    wide = SiteLimiter(limit=5)
    wide._main_waiting = True
    assert 0 not in wide._candidates(MAYA, main=False) and len(wide._candidates(MAYA, main=False)) == 4


# ---------------------------------------------------------------- 1: access and llms.txt's links beside the own thread

def test_access_and_llms_links_run_on_lanes_with_the_same_requests(clock):  # noqa: F811
    outcome = audit(site(clock, pages=6, sitemap_only=12, llms=8), max_pages=8)
    result = outcome.result
    steps = {row["step"]: row for row in result.steps}
    assert steps["access"]["beside"] == ["index", "structure", "render"]
    assert steps["llms_links"]["beside"] == ["index", "structure", "render"]
    log = paced(result)
    llms = [r.url for r in log if r.purpose == "llms_link_check"]
    # every llms.txt link the crawl and the sitemap check did not read is asked once, never twice
    assert len(llms) == len(set(llms)) and llms
    entry = result.access.llms[0]["links"]
    assert entry["checked"] == 8 and entry["not_working"] == 0
    assert result.index.sitemap_check.llms_rows and not hasattr(result, "_llms_state")
    assert len(result.access.robots_samples) == 3  # the robots.txt samples still sent by the audit's own thread


# ---------------------------------------------------------------- 2: every mode reads the Akıllı selection

def test_page_caps_and_the_selection_by_mode():
    from maya_audit_web.runner import page_cap, sampled
    assert [page_cap({"mode": m}) for m in ("single", "quick", "smart", "standard")] == [1, 50, 150, 500]
    assert page_cap({"mode": "custom", "page_cap": 300}) == 300
    assert page_cap({"mode": "custom", "document": {"page_cap": 750}}) == 750
    assert page_cap({"mode": "custom", "config": {"max_pages": 1200}}) == 1200
    assert all(sampled({"mode": m}) for m in ("quick", "smart", "standard", "custom"))
    assert not sampled({"mode": "single"}) and not sampled({"mode": "standard", "crawl_order": True})
    assert not sampled({"mode": "quick", "document": {"crawl_order": True}})


def test_a_custom_plan_needs_its_count_and_says_how_pages_are_chosen(web):  # noqa: F811
    from maya_audit_web.strings import t
    client = web()
    missing = client.post(f"{API}/plans", json={"url": "demo-shop.localhost", "mode": "custom"})
    assert missing.status_code == 422 and missing.json()["error"]["code"] == "page_count_required"
    assert client.post(f"{API}/plans", json={"url": "demo-shop.localhost", "mode": "custom", "page_count": 24}).status_code == 422
    assert client.post(f"{API}/plans", json={"url": "demo-shop.localhost", "mode": "custom", "page_count": 2001}).status_code == 422
    made = plan(client, mode="custom", page_count=300)
    assert made["page_cap"] == 300 and made["mode_label"] == t("plan.mode.custom", cap=300)
    assert made["selection_line"] == t("plan.selection.sampled") and made["crawl_order"] is False
    other = plan(client, mode="custom", page_count=400)
    assert other["fingerprint"] != made["fingerprint"] and other["page_cap"] == 400
    ordered = plan(client, mode="custom", page_count=300, crawl_order=True)
    assert ordered["selection_line"] == t("plan.selection.order") and ordered["fingerprint"] != made["fingerprint"]
    assert plan(client, mode="single")["selection_line"] is None
    custom = next(m for m in client.get(f"{API}/settings").json()["modes"] if m["id"] == "custom")
    assert (custom["min"], custom["max"], custom["page_cap"]) == (25, 2000, None)
    assert made["duration"]["typical"]["high_minutes"] >= made["duration"]["typical"]["low_minutes"] >= 1


def test_a_custom_audit_reads_its_count_with_the_selection(web):  # noqa: F811
    from test_web_app import start
    client = web()
    audit = start(client, plan(client, mode="custom", page_count=30))
    assert audit["state"] == "finished" and audit["counters"]["page_cap"] == 30
    sampling = client.get(f"{API}/audits/{audit['id']}/result").json()["crawl"]["sampling"]
    assert sampling["mode"] == "smart" and sampling["budget"] == 30


def test_the_firecrawl_credit_estimate_on_the_plan(web, tmp_path):  # noqa: F811
    from test_web_app import Site, cloudflare
    from test_web_firecrawl import Firecrawl, PAGES, services
    client = web(site=Site(respond=cloudflare), firecrawl=services(tmp_path, Firecrawl(PAGES)))
    smart = plan(client, mode="smart")
    reader = smart["firecrawl"]
    assert reader["max_credits"] > smart["credits_expected"] > 0  # usually a quarter of the pages, never the cap
    full = plan(client, mode="smart", firecrawl_full_read=True)
    # read in full: every page and robots.txt (the maximum also covers the sitemap requests the reader may make)
    assert full["credits_expected"] == (full["page_cap"] + 1) * full["firecrawl"]["credits_per_page"] <= full["firecrawl"]["max_credits"]
    assert plan(client, mode="quick", firecrawl=False)["credits_expected"] is None


def test_the_web_screens_show_the_new_modes():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    script = (root / "maya_audit_web" / "static" / "app.js").read_text(encoding="utf-8")
    assert 'state.draft.mode !== "custom"' in script and 'T("new.crawl_order")' in script
    assert "current.selection_line" in script and 'T("plan.cost.credits.expected"' in script
    from maya_audit_web.strings import t
    assert [t(f"new.mode.{m}", "tr") for m in ("quick", "smart", "standard", "custom")] == [
        "Hızlı ~50", "Akıllı ~150 (önerilen)", "Derin ~500", "Özel sayı"]
    assert t("new.crawl_order", "tr") == "Tam tarama sırası (gelişmiş)"


# ---------------------------------------------------------------- 3: one Google key

CRUX_ANSWER = {"record": {"key": {"origin": "https://demo-shop.localhost"}, "metrics": {
    "largest_contentful_paint": {"percentiles": {"p75": 2100}},
    "interaction_to_next_paint": {"percentiles": {"p75": 180}},
    "cumulative_layout_shift": {"percentiles": {"p75": "0.05"}}},
    "collectionPeriod": {"lastDate": {"year": 2026, "month": 11, "day": 7}}}}


@pytest.mark.parametrize("env,file,want", [
    ({"MAYA_AUDIT_CRUX_API_KEY": "made-up-crux"}, "", "made-up-crux"),
    ({"MAYA_AUDIT_GOOGLE_API_KEY": "made-up-google"}, "", "made-up-google"),
    ({}, "MAYA_AUDIT_GOOGLE_API_KEY=made-up-file\n", "made-up-file"),
    ({"MAYA_AUDIT_GOOGLE_API_KEY": "made-up-google"}, "MAYA_AUDIT_CRUX_API_KEY=made-up-crux-file\n", "made-up-crux-file"),
    ({}, "", None),
])
def test_core_web_vitals_take_either_google_key_name(tmp_path, env, file, want):
    path = tmp_path / "test.env"
    path.write_text(file, encoding="utf-8")
    assert crux.load_key({**env, "MAYA_AUDIT_ENV_FILE": str(path)}) == want


def test_pagespeed_takes_either_name_too(tmp_path):
    path = tmp_path / "test.env"
    path.write_text("MAYA_AUDIT_CRUX_API_KEY=made-up-crux\n", encoding="utf-8")
    assert crux.google_key({"MAYA_AUDIT_ENV_FILE": str(path)}) == "made-up-crux"
    assert crux.google_key({"MAYA_AUDIT_ENV_FILE": str(path), "MAYA_AUDIT_GOOGLE_API_KEY": "made-up-google"}) == "made-up-google"


def test_a_recorded_answer_fills_core_web_vitals_and_never_shows_the_key():
    seen = []

    def answer(request):
        seen.append(request)
        return httpx.Response(200, json=CRUX_ANSWER)
    section = crux.collect("https://demo-shop.localhost/", "made-up-google", transport=httpx.MockTransport(answer))
    assert section["status"] == "assessed" and section["passes_core_web_vitals"]
    assert [m["rating"] for m in section["metrics"]] == ["good", "good", "good"]
    assert seen[0].headers["x-goog-api-key"] == "made-up-google" and "made-up-google" not in str(seen[0].url)
    assert "made-up-google" not in json.dumps(section)
    refused = crux.collect("https://demo-shop.localhost/", "made-up-google",
                           transport=httpx.MockTransport(lambda r: httpx.Response(403, json={"error": {"message": "key made-up-google not enabled"}})))
    assert refused["status"] == "not_available" and "made-up-google" not in json.dumps(refused)
    assert "Chrome UX Report API is enabled" in refused["summary"]


# ---------------------------------------------------------------- DECISIONS 333: what the plan says

def test_the_plan_shows_core_web_vitals_when_the_key_is_set(web, monkeypatch):  # noqa: F811
    from maya_audit_web.strings import t
    client = web()
    assert plan(client)["search_data"]["core_web_vitals"] == t("crux.plan.off")
    monkeypatch.setenv("MAYA_AUDIT_CRUX_API_KEY", "made-up-crux")
    made = plan(client)
    assert made["search_data"]["core_web_vitals"] == t("crux.plan.on")
    assert t("plan.unavailable.pagespeed") not in made["unavailable"]
    from pathlib import Path
    script = (Path(__file__).resolve().parents[1] / "maya_audit_web" / "static" / "app.js").read_text(encoding="utf-8")
    assert '[T("plan.label.cwv"), plan.search_data.core_web_vitals]' in script  # a row of the plan's details


def test_paid_data_that_was_not_chosen_is_not_a_cost_on_the_plan(web):  # noqa: F811
    client = web()
    made = plan(client)  # backlinks and search data off
    assert made["paid"]["requested"] is False and made["paid"]["total_usd"] > 0  # the backlink price, for the details
    from pathlib import Path
    script = (Path(__file__).resolve().parents[1] / "maya_audit_web" / "static" / "app.js").read_text(encoding="utf-8")
    assert "current.paid && current.paid.requested && current.paid.total_usd ? T(\"plan.cost.short\"" in script


@pytest.mark.parametrize("mode", ["quick", "smart", "standard"])
def test_the_plans_two_time_lines_say_the_same_time(web, mode):  # noqa: F811
    client = web(provider=None)
    made = plan(client, mode=mode)
    usual = made["duration"]["typical"]
    assert made["duration"]["label"].startswith(usual["label"])  # the details start with the short line's time
    assert f"{made['time_limit_minutes']}" in made["duration"]["label"]
    import re
    up_to = made["duration"]["up_to_minutes"]
    assert up_to == made["time_limit_minutes"] or not re.search(rf"(?<!\d){up_to} minutes", made["duration"]["label"])
