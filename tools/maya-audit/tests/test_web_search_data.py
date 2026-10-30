"""The web app's search data panels, Core Web Vitals and archived copies. Every provider is made up and in memory."""
import httpx
import pytest

pytest.importorskip("fastapi")

from maya_audit_web import demo  # noqa: E402
from test_web_app import API, Site, cloudflare, confirm, error, get, plan, start, web  # noqa: E402,F401


@pytest.mark.usefixtures("confirm_every_paid_plan")
def test_search_data_is_priced_confirmed_run_once_and_shown_with_source_and_date(web):
    client = web()
    plain = plan(client)
    assert [row["check_id"] for row in plain["paid"]["calls"]] == ["DFS-1", "DFS-2"] and not plain["paid"]["requested"]  # shown, not chosen
    assert plain["search_data"]["requested"] is False and plain["paid_options"]["search_data"] is False
    made = plan(client, search_data=True, market_default_accepted=True, local_business=True)
    ids = [row["check_id"] for row in made["paid"]["calls"]]
    assert ids == ["DFS-3", "DFS-4", "DFS-5", "DFS-6", "DFS-7", "DFS-8", "DFS-9", "DFS-12"]  # the panels only: backlinks were not asked for
    assert all(row["purpose"] and row["estimate_usd"] > 0 for row in made["paid"]["calls"]) and made["fingerprint"] != plain["fingerprint"]
    assert made["needs_confirmation"] and not made["can_start"] and made["paid"]["total_usd"] == pytest.approx(0.2809, abs=0.01)
    error(client.post(f"{API}/audits", json={"plan_id": made["id"]}), 402, "confirmation_required")
    assert client.provider.requests == []
    both = plan(client, search_data=True, market_default_accepted=True, backlinks=True)
    assert [row["check_id"] for row in both["paid"]["calls"]][:2] == ["DFS-1", "DFS-2"] and both["paid"]["total_usd"] > made["paid"]["total_usd"] - 0.01

    audit = start(client, confirm(client, made))
    assert audit["state"] == "finished" and len(client.provider.requests) == 8
    report = get(client, audit, "/result")
    section = report["dataforseo"]
    assert section["panel"] == "Search data" and section["status"] == "assessed" and 0 < section["cost_usd"] <= made["paid"]["total_usd"]
    assert client.ledger.spent_today() == pytest.approx(section["cost_usd"])
    view = get(client, audit, "/summary")["backlinks"]
    by_id = {check["check_id"]: check for check in view["checks"]}
    assert by_id["DFS-5"]["data"]["provider_table"]["rows"] and by_id["DFS-5"]["data_from"] and by_id["DFS-5"]["endpoint"].endswith("/ranked_keywords/live")
    original = by_id['DFS-5']['data']['provider_table']['rows']
    assert any(row[0]=='made-up kettle reviews' for row in original)
    assert len(by_id['DFS-5']['data']['keyword_assessments'])==len(original)
    assert all(row[-1] in ('branded','relevant','related_organization') for row in by_id['DFS-5']['data']['table']['rows'])
    assert "rated 4.4 from 212 review(s)" in by_id["DFS-12"]["summary"]
    markdown = client.get(f"{API}/audits/{audit['id']}/downloads/markdown").text
    assert "## DataForSEO: search data" in markdown and "made-up kettle reviews" in markdown
    printed = client.get(f"{API}/audits/{audit['id']}/print?full=true").text
    assert "made-up kettle reviews" in printed and "Quick wins" in printed
    # The same plan again inside the cache lifetime costs nothing and needs no confirmation.
    again = plan(client, search_data=True, market_default_accepted=True, local_business=True)
    assert again["paid"]["total_usd"] == 0 and not again["needs_confirmation"] and all(row["state"] == "cached" for row in again["paid"]["calls"])


def test_core_web_vitals_are_shown_when_a_key_is_set_and_said_to_be_unavailable_when_not(web):
    client = web()
    audit = start(client, plan(client))
    view = get(client, audit, "/summary")
    assert view["crux"]["status"] == "not_available" and view["crux"]["summary"] == "Core Web Vitals not available (no API key)"
    assert "crux" not in get(client, audit, "/result") and "no API key" in plan(client)["search_data"]["core_web_vitals"]
    engine = client.app.state.runner.engine
    engine.crux_key, engine.crux_transport = (lambda: "made-up-google-key"), demo.CRUX_TRANSPORT
    audit = start(client, plan(client, key_pages=["/about"]))
    report = get(client, audit, "/result")
    assert report["crux"]["status"] == "assessed" and report["crux"]["data_until"] == "2026-10-01"
    view = get(client, audit, "/summary")
    assert "Largest Contentful Paint (LCP) 2.9 s (needs improvement)" in view["crux"]["summary"]
    everything = client.get(f"{API}/audits/{audit['id']}/downloads/markdown").text + client.get(f"{API}/audits/{audit['id']}/result").text
    assert "## Core Web Vitals (real visitors)" in everything and "made-up-google-key" not in everything


def test_archived_copies_are_read_only_when_asked_for_and_nothing_else_could_read_the_site(web):
    asked = []

    def archive(request):
        asked.append(request.url.host)
        return demo._no_archives(request)

    client = web(site=Site(respond=cloudflare))
    client.app.state.runner.engine.archives_transport = httpx.MockTransport(archive)
    audit = start(client, plan(client))
    assert asked == [] and get(client, audit, "/summary")["archives"] is None  # off unless the plan asks
    made = plan(client, archives=True)
    assert made["archives"] is True and made["fingerprint"] != plan(client)["fingerprint"]
    audit = start(client, made)
    view = get(client, audit, "/summary")
    assert asked and set(asked) <= {"web.archive.org", "archive.org", "index.commoncrawl.org", "data.commoncrawl.org"}
    assert view["blocked"] and view["archives"]["pages_read"] == 0 and [s["id"] for s in view["archives"]["sources"]] == ["wayback", "common_crawl"]
    assert "## Archived content" in client.get(f"{API}/audits/{audit['id']}/downloads/markdown?draft=true").text
    # A site that could be read is never looked up in the archives.
    asked.clear()
    client.site.custom = None
    fine = start(client, plan(client, archives=True))
    assert asked == [] and "archives" not in get(client, fine, "/result")


def test_by_default_a_normal_paid_audit_runs_without_asking_is_recorded_and_only_a_large_total_is_confirmed(web, monkeypatch):
    from maya_audit.dataforseo import pricing
    from maya_audit_web import paid

    assert pricing.APPROVAL_THRESHOLD_USD == 2.00 and pricing.AUDIT_CAP_USD == 5.00 and pricing.DAILY_BUDGET_USD == 20.00
    assert paid.daily_cap() == 20.00 and paid.limits() == {"confirm_usd": 2.00, "audit_cap_usd": 5.00, "daily_usd": 20.00}
    client = web()
    # The daily limit is configurable, and still stops a plan that does not fit what is left of the day.
    monkeypatch.setenv("MAYA_AUDIT_DATAFORSEO_DAILY_USD", "0.10")
    small_day = plan(client, search_data=True, market_default_accepted=True, backlinks=True, local_business=True)
    assert paid.daily_cap() == 0.10 and small_day["paid"]["blocked"]["code"] == "daily_limit_reached" and not small_day["can_start"]
    monkeypatch.setenv("MAYA_AUDIT_DATAFORSEO_DAILY_USD", "not a number")
    assert paid.daily_cap() == 20.00
    monkeypatch.delenv("MAYA_AUDIT_DATAFORSEO_DAILY_USD")
    # Above the per-audit threshold the exact total is still confirmed before anything is sent.
    monkeypatch.setattr(pricing, "APPROVAL_THRESHOLD_USD", 0.25)
    large = plan(client, search_data=True, market_default_accepted=True, backlinks=True, local_business=True)
    assert large["needs_confirmation"] and not large["can_start"] and large["to_confirm"]["approved_max_usd"] == large["paid"]["total_usd"]
    error(client.post(f"{API}/audits", json={"plan_id": large["id"]}), 402, "confirmation_required")
    monkeypatch.setattr(pricing, "APPROVAL_THRESHOLD_USD", 2.00)
    assert client.provider.requests == []

    made = plan(client, search_data=True, market_default_accepted=True, backlinks=True, local_business=True)
    cost = made["paid"]
    # About thirty-three cents: priced and shown on the plan, under the $2 threshold, so nothing to confirm and it can start.
    assert 0.25 < cost["total_usd"] < 0.45 and cost["requested"] and not cost["needs_confirmation"] and cost["blocked"] is None
    assert made["to_confirm"] is None and made["can_start"] and cost["budget"]["daily_cap_usd"] == 20.00
    error(client.post(f"{API}/plans/{made['id']}/confirm", json={"approved_max_usd": cost["total_usd"]}), 409, "nothing_to_confirm")
    audit = start(client, made)
    section = get(client, audit, "/result")["dataforseo"]
    assert audit["state"] == "finished" and section["status"] == "assessed" and len(client.provider.requests) == 10
    # Everything is in the ledger, to the cent DataForSEO reported, and never more than the plan showed.
    assert client.ledger.spent_today() == pytest.approx(section["cost_usd"]) and 0 < section["cost_usd"] <= cost["total_usd"]
    assert get(client, audit)["paid"]["approved_max_usd"] == pytest.approx(cost["total_usd"])

