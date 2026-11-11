"""Firecrawl in the web app. Every request here goes to an in-memory Firecrawl; no key, site or provider is real."""
import io
import json
import zipfile

import httpx
import pytest

pytest.importorskip("fastapi")

from maya_audit.dataforseo.cache import Cache  # noqa: E402
from maya_audit.dataforseo.ledger import Ledger  # noqa: E402
from maya_audit.firecrawl import settings  # noqa: E402
from maya_audit_web import demo, strings  # noqa: E402
from maya_audit_web.fc import FirecrawlServices  # noqa: E402
from test_firecrawl import KEY, ROBOTS_TEXT, TEXT, Firecrawl, doc  # noqa: E402
from test_web_app import API, SHOP, Site, cloudflare, confirm, error, get, plan, start, web  # noqa: E402,F401

ROOT = f"http://{SHOP}"
PAGES = {
    f"{ROOT}/robots.txt": ROBOTS_TEXT,
    f"{ROOT}/": doc("Solar Panels", "<h1>Welcome</h1>" + TEXT + '<a href="/about">About</a> <a href="/products">Products</a> '
                    '<a href="/private/accounts">Accounts</a>'),
    f"{ROOT}/about": doc("Solar Panels", "<h1>About</h1>" + TEXT),
    f"{ROOT}/products": doc("Products | Bank", "<h1>Products</h1>" + TEXT),
}
NO_ZDR = lambda body: httpx.Response(403, json={"success": False, "error": "Zero Data Retention is not enabled for this team."}) \
    if body.get("zeroDataRetention") else None  # noqa: E731


def services(tmp_path, api, key=True):
    folder = tmp_path / "fc"
    return FirecrawlServices(key=lambda: KEY if key else None,
                             stores=lambda: (Ledger(folder / settings.LEDGER_NAME), Cache(folder / settings.CACHE_NAME)),
                             transport=httpx.MockTransport(api))


def approve(client, made, **body):
    if not body and not (made.get("to_confirm") or {}).get("approved_max_credits"):
        return made  # the basic proxy of a normal run has nothing to confirm
    response = client.post(f"{API}/plans/{made['id']}/confirm", json=body or {"approved_max_credits": made["to_confirm"]["approved_max_credits"]})
    assert response.status_code == 200, response.text
    return response.json()


def outputs(client, audit):
    """Everything a person can see or download for one audit, as one text."""
    parts = [client.get(f"{API}/audits/{audit['id']}{path}").text for path in ("", "/summary", "/result", "/print?full=true", "/findings",
                                                                               "/downloads/markdown", "/events")]
    return "\n".join(parts)


def test_firecrawl_is_on_when_a_key_is_set_and_switched_off_for_one_audit_it_is_sent_nothing(web, tmp_path, monkeypatch):
    api = Firecrawl(PAGES)
    client = web(site=Site(respond=cloudflare), firecrawl=services(tmp_path, api))
    default = plan(client)
    assert default["firecrawl"]["requested"] and default["firecrawl"]["main_reader"] and default["to_confirm"] is None and default["can_start"]
    assert default["firecrawl"]["options"]["read_always"] is True and default["firecrawl"]["max_pages"] == 50  # the plan's own page cap
    assert plan(client, mode="standard")["firecrawl"]["max_pages"] == 500
    assert any("Firecrawl" in line and "on when its key is set" in line for line in default["optional"])
    monkeypatch.setenv("MAYA_AUDIT_FIRECRAWL", "off")  # switched off for the whole computer
    assert plan(client)["firecrawl"]["requested"] is False
    monkeypatch.delenv("MAYA_AUDIT_FIRECRAWL")
    monkeypatch.setenv("MAYA_AUDIT_FIRECRAWL_ZERO_DATA_RETENTION", "off")  # an account without zero data retention
    assert plan(client)["firecrawl"]["options"]["allow_without_zero_data_retention"] is True and plan(client)["firecrawl"]["credits_per_page"] == 1
    monkeypatch.delenv("MAYA_AUDIT_FIRECRAWL_ZERO_DATA_RETENTION")
    made = plan(client, firecrawl=False)
    reader = made["firecrawl"]
    assert reader["requested"] is False and reader["needs_confirmation"] is False and reader["available"] and made["to_confirm"] is None
    assert made["can_start"]
    audit = start(client, made)
    assert audit["state"] == "finished" and audit["firecrawl"] == {"requested": False, "state": "none", "options": None, "needs_decision": False, "continuing": False}
    assert api.bodies == []  # not one request
    assert "firecrawl" not in client.get(f"{API}/audits/{audit['id']}/result").json() and get(client, audit, "/summary")["firecrawl"] is None
    # Without a key the option cannot be switched on, and the plan says why.
    bare = web(folder=tmp_path / "bare", site=Site(respond=cloudflare), firecrawl=services(tmp_path, api, key=False))
    refused = plan(bare, firecrawl=True)
    assert refused["firecrawl"]["blocked"]["code"] == "firecrawl_key_not_configured" and not refused["can_start"]
    error(bare.post(f"{API}/audits", json={"plan_id": refused["id"]}), 409, "firecrawl_key_not_configured")
    keyless = plan(bare)  # nothing asked for: no key simply means Maya's own crawler reads the pages
    assert keyless["firecrawl"]["available"] is False and keyless["firecrawl"]["requested"] is False and keyless["can_start"] and api.bodies == []


@pytest.mark.usefixtures("confirm_every_paid_plan")
def test_a_plan_shows_firecrawl_credits_and_only_a_stronger_proxy_needs_its_exact_maximum_confirmed(web, tmp_path):
    api = Firecrawl(PAGES)
    client = web(site=Site(respond=cloudflare), firecrawl=services(tmp_path, api))
    made = plan(client, firecrawl=True)
    reader = made["firecrawl"]
    # 50 pages and robots.txt, two credits each with zero data retention; no dollar figure until a rate is configured.
    assert (reader["max_pages"], reader["max_credits"], reader["credits_per_page"], reader["max_usd"]) == (50, 106, 2, None)
    assert reader["options"]["proxy"] == "basic" and reader["options"]["allow_without_zero_data_retention"] is False
    assert "only credits are shown" in reader["cost_line"] and "106 credits" in reader["cost_line"]
    assert any("Maya's own crawler still makes the direct requests" in line for line in reader["lines"]) and any("robots.txt allows" in line for line in reader["lines"])
    assert any("Firecrawl reads the pages of this audit" in line for line in reader["lines"])
    # The basic proxy is the page reader of a normal run: nothing to confirm, the plan can start.
    assert not made["needs_confirmation"] and made["can_start"] and made["to_confirm"] is None
    error(client.post(f"{API}/plans/{made['id']}/confirm", json={"approved_max_credits": 106}), 409, "nothing_to_confirm")
    made = plan(client, firecrawl=True, firecrawl_proxy="enhanced", firecrawl_owner_approved=True)
    assert made["needs_confirmation"] and not made["can_start"]
    assert made["to_confirm"] == {"approved_max_usd": None, "approved_max_credits": 106, "label": "Confirm up to 106 Firecrawl credits"}
    error(client.post(f"{API}/audits", json={"plan_id": made["id"]}), 402, "confirmation_required")
    error(client.post(f"{API}/plans/{made['id']}/confirm", json={"approved_max_credits": 100}), 422, "credits_mismatch")
    error(client.post(f"{API}/plans/{made['id']}/confirm", json={"approved_max_usd": 1.0}), 422, "credits_mismatch")
    assert api.bodies == []
    confirmed = approve(client, made)
    assert confirmed["can_start"] and confirmed["confirmation"]["approved_max_credits"] == 106
    # A smaller page cap is a different plan with a smaller maximum; the cap cannot go past its limit.
    small = plan(client, firecrawl=True, firecrawl_max_pages=5)
    assert small["firecrawl"]["max_credits"] == 12 and small["fingerprint"] != made["fingerprint"]
    assert client.post(f"{API}/plans", json={"url": SHOP, "firecrawl": True, "firecrawl_max_pages": 501}).status_code == 422
    # A stronger proxy without the owner's approval is refused at the plan, before anything can be confirmed.
    pushy = plan(client, firecrawl=True, firecrawl_proxy="enhanced")
    assert pushy["firecrawl"]["blocked"]["code"] == "firecrawl_options" and "site owner has approved" in pushy["firecrawl"]["blocked"]["message"].replace("\n", " ") \
        or "owner" in pushy["firecrawl"]["blocked"]["message"]
    assert not pushy["can_start"] and pushy["to_confirm"] is None
    # With backlinks too, one confirmation carries both maximums, and each must be exact.
    both = plan(client, firecrawl=True, firecrawl_proxy="auto", firecrawl_owner_approved=True, backlinks=True)
    assert both["to_confirm"]["approved_max_usd"] == both["paid"]["total_usd"] > 0 and both["to_confirm"]["approved_max_credits"] == 106
    assert both["to_confirm"]["label"] == f"Confirm up to ${both['paid']['total_usd']:.2f} and 106 Firecrawl credits" or " and 106 Firecrawl credits" in both["to_confirm"]["label"]
    error(client.post(f"{API}/plans/{both['id']}/confirm", json={"approved_max_usd": both["paid"]["total_usd"]}), 422, "credits_mismatch")
    error(client.post(f"{API}/plans/{both['id']}/confirm", json={"approved_max_credits": 106}), 422, "amount_mismatch")
    assert approve(client, both, approved_max_usd=both["paid"]["total_usd"], approved_max_credits=106)["can_start"]
    assert api.bodies == [] and client.provider.requests == []


def test_a_challenged_site_is_read_through_firecrawl_with_no_block_headline_and_direct_results_stand(web, tmp_path):
    api = Firecrawl(PAGES)
    client = web(site=Site(respond=cloudflare), firecrawl=services(tmp_path, api))
    plain = start(client, plan(client, firecrawl=False))
    assert plain["outcome"]["code"] == "DEGRADED"
    before = client.get(f"{API}/audits/{plain['id']}/result").json()
    audit = start(client, plan(client))  # no flag and no confirmation: the key is set
    assert audit["state"] == "finished" and audit["outcome"]["code"] == "COMPLETED" and audit["outcome"]["reason"].startswith("We read 3 page(s) through Firecrawl")
    assert "direct crawler was challenged" in audit["outcome"]["reason"] and "Genuine AI-crawler access was not measured" in audit["outcome"]["reason"]
    assert audit["firecrawl"]["state"] == "done" and audit["firecrawl"]["requested"]
    report = client.get(f"{API}/audits/{audit['id']}/result").json()
    assert report["schema_version"] == "1.32"

    def access(rep):
        return {c["check_id"]: (c["status"], c["summary"], [f["title"] for f in c["findings"]]) for c in rep["checks"]
                if c["check_id"].split("-")[0] in ("ACC", "PRF") or c["check_id"] in ("IDX-1", "IDX-2", "IDX-3", "IDX-4")}
    now = access(report)
    acc9 = now.pop("ACC-9")
    assert {k: v for k, v in access(before).items() if k != "ACC-9"} == now and access(before)["ACC-9"][0] == "findings"
    assert acc9[2] == ["Maya's crawler blocked by bot protection (Cloudflare): 1 of 1 page request(s) got its block page. "
                       "AI crawlers (GPTBot, ClaudeBot, PerplexityBot, Google-Extended) may be blocked the same way"]
    [finding] = next(c for c in report["checks"] if c["check_id"] == "ACC-9")["findings"]  # DECISIONS 317: a finding, not a note
    assert finding["severity"] == "S3" and finding["evidence"]["pages_blocked_or_challenged"] == 1
    assert [(g["check_id"], g["state"]) for g in report["gates"]] == [(g["check_id"], g["state"]) for g in before["gates"]]
    assert [p["status"] for p in report["crawl"]["pages"]] == [403]

    section = report["firecrawl"]
    assert section["used"] and section["pages_read"] == 3 and section["skipped_by_robots"] == 0 and section["proxy"] == "basic"
    assert section["zero_data_retention"]["status"] == "applied" and section["owner_approved_bypass"] is False
    assert section["credits"]["used_or_reserved"] == 10 and section["usd"]["used_or_reserved"] is None
    assert f"{ROOT}/robots.txt" not in api.urls and f"{ROOT}/private/accounts" in api.urls and len(api.bodies) == 5
    # The homepage first, then the sitemap (Maya's own crawler could not read one): asked once, and this site has none.
    assert api.urls[:2] == [f"{ROOT}/", f"{ROOT}/sitemap.xml"] and section["sitemap"]["addresses_found"] == 0
    assert section["sitemap"]["documents"] == [{"url": f"{ROOT}/sitemap.xml", "outcome": "not_found", "status": 404}]
    assert section["robots"]["source"] == "Maya's own crawler" and section["robots"]["mode"] == "allow_all"
    assert all(body["proxy"] == "basic" and body["zeroDataRetention"] is True and body["storeInCache"] is False for body in api.bodies)

    view = get(client, audit, "/summary")
    assert view["blocked"] is None and view["firecrawl_offer"] is None and view["block_pointer"] is None  # no "site blocked" headline
    assert view["firecrawl"]["used"] and view["firecrawl"]["main_reader"] and "AI crawlers may not see this content" not in json.dumps(view)
    assert view["pages_stat"] == {**view["pages_stat"], "value": 3, "label": "Pages read", "detail": "via Firecrawl", "line": "Pages read: 3 (via Firecrawl)"}
    assert view["summary_line"].startswith("3 pages checked.") and view["outcome"]["code"] == "COMPLETED" and view["first_action_withheld"] is None
    assert view["counts"]["by_severity"]["S3"] == sum(1 for row in view["top"] if row["severity"] == "S3")
    # DECISIONS 317: Cloudflare's block of Maya's crawler is a problem to fix (its AI-crawler warning), not a note.
    assert [row["title"][:40] for row in view["top"] if row["check_id"] == "ACC-9" and row["requires_fix"]] == ["Maya's crawler blocked by bot protection"]
    [gap] = [g for g in view["coverage"]["gaps"] if g.get("blocked")]
    assert gap["part"] == "Needs Maya’s own direct requests" and "read through Firecrawl" in gap["reason"]
    assert view["firecrawl"]["decision"] is None and any("Pages read through Firecrawl: 3" in line for line in view["firecrawl"]["lines"])
    rows = get(client, audit, "/findings", limit=100)["items"]
    sourced = [row for row in rows if row["source"]]
    assert sourced and all(row["source"]["label"] == "Source: Firecrawl" for row in sourced)
    assert all(row["check_id"].split("-")[0] in ("STR", "TSEO", "IDX") for row in sourced)
    assert all(row["source"] is None for row in rows if row["check_id"].startswith(("ACC", "PRF")))
    [note] = [row for row in rows if row["check_id"] == "ACC-9"]
    assert note["severity"] == "S3" and note["title"].startswith("Maya's crawler blocked by bot protection (Cloudflare): 1 of 1 page request(s)")

    printed = client.get(f"{API}/audits/{audit['id']}/print?full=true").text
    assert "Source: Firecrawl" in printed and "AI crawlers may not see this content" not in printed and "The site blocked this audit" not in printed
    assert "Read through Firecrawl" in printed and "3 (via Firecrawl)" in printed and "could not read the site properly" not in printed
    assert "robots.txt returned 403; RFC 9309: unavailable, crawling allowed" in printed
    markdown = client.get(f"{API}/audits/{audit['id']}/downloads/markdown").text
    assert "## Firecrawl (third-party page reader)" in markdown and "Source: Firecrawl." in markdown
    assert "**Pages read:** 3 (via Firecrawl)" in markdown and "**Result:** COMPLETED" in markdown
    assert "Robots policy" in markdown and "robots.txt returned 403" in markdown
    everything = outputs(client, audit) + json.dumps(client.get(f"{API}/plans/{audit['plan_id']}").json())
    assert KEY.value not in everything and "Bearer" not in everything
    # What Firecrawl read is saved apart from the evidence of Maya's own crawl, and both are in the download.
    with zipfile.ZipFile(io.BytesIO(client.get(f"{API}/audits/{audit['id']}/downloads/evidence").content)) as archive:
        names = archive.namelist()
        read = json.loads(archive.read("evidence-firecrawl/index.json"))["pages"]
    assert sorted(entry["url"] for entry in read) == [f"{ROOT}/", f"{ROOT}/about", f"{ROOT}/products"]
    assert "evidence/index.json" in names and sum(name.startswith("evidence-firecrawl/") for name in names) == 4
    # A plain audit of the same site, before and after, carries none of this.
    assert "firecrawl" not in before and "Source: Firecrawl" not in client.get(f"{API}/audits/{plain['id']}/print?full=true").text


def test_a_site_that_lets_mayas_crawler_in_is_read_through_firecrawl_too_and_falls_back_page_by_page(web, tmp_path):
    api = Firecrawl(PAGES)  # a reader that knows none of this site's pages: every answer is a 404
    client = web(firecrawl=services(tmp_path, api))
    audit = start(client, plan(client, firecrawl_max_pages=5))
    report = client.get(f"{API}/audits/{audit['id']}/result").json()
    section = report["firecrawl"]
    own = {page["url"] for page in report["crawl"]["pages"] if page["status"] == 200}
    assert audit["state"] == "finished" and api.bodies and set(api.urls) <= own and len(api.urls) == len(set(api.urls))
    assert not [url for url in api.urls if url.endswith("/robots.txt")]  # robots.txt is Maya's own request
    assert section["used"] and section["crawl_blocked"]["blocked"] is False and section["purpose"] == "main page reader"
    through = section["pages_read"]
    assert 1 <= through < len(own) and section["credits"]["used_or_reserved"] == 2 * len(api.bodies)
    view = get(client, audit, "/summary")
    assert view["blocked"] is None and view["firecrawl_offer"] is None and audit["outcome"]["code"] in ("COMPLETED", "INCOMPLETE")
    # Pages the reader could not read keep Maya's own reading, and the counter says who read what.
    assert view["pages_stat"]["label"] == "Pages read" and view["pages_stat"]["value"] == len(own)
    assert view["pages_stat"]["detail"] == f"{through} via Firecrawl, {len(own) - through} by Maya’s own crawler"
    rows = get(client, audit, "/findings", limit=100)["items"]
    assert all(row["source"] is None for row in rows if row["check_id"].startswith(("ACC", "PRF", "RND")))
    assert all(row["source"]["label"] == "Source: Firecrawl" for row in rows if row["source"])


def test_the_owner_approval_is_per_audit_recorded_and_the_only_way_to_a_stronger_proxy(web, tmp_path):
    api = Firecrawl(PAGES)
    client = web(site=Site(respond=cloudflare), firecrawl=services(tmp_path, api))
    made = plan(client, firecrawl=True, firecrawl_proxy="enhanced", firecrawl_owner_approved=True, firecrawl_max_pages=10)
    assert made["firecrawl"]["blocked"] is None and any("site owner approved bypassing bot protection" in line for line in made["firecrawl"]["lines"])
    audit = start(client, approve(client, made))
    section = client.get(f"{API}/audits/{audit['id']}/result").json()["firecrawl"]
    assert all(body["proxy"] == "enhanced" for body in api.bodies) and section["proxy"] == "enhanced" and section["owner_approved_bypass"] is True
    view = get(client, audit, "/summary")["firecrawl"]
    assert view["owner_approved_bypass"] and any("the site owner approved bypassing bot protection" in line for line in view["lines"])
    assert "the site owner approved bypassing bot protection" in client.get(f"{API}/audits/{audit['id']}/print?full=true").text
    # The next audit starts from the default again: the tick does not carry over.
    assert plan(client, firecrawl=True)["firecrawl"]["options"] == {**made["firecrawl"]["options"], "proxy": "basic",
                                                                     "owner_approved_bypass": False, "max_pages": 50}


def test_a_zero_data_retention_refusal_stops_and_waits_for_an_explicit_decision(web, tmp_path):
    api = Firecrawl(PAGES, responder=NO_ZDR)
    client = web(site=Site(respond=cloudflare), firecrawl=services(tmp_path, api))
    audit = start(client, approve(client, plan(client, firecrawl=True, firecrawl_max_pages=5)))
    assert audit["state"] == "finished" and audit["firecrawl"]["state"] == "needs_decision" and audit["firecrawl"]["needs_decision"]
    assert len(api.bodies) == 1 and api.bodies[0]["zeroDataRetention"] is True  # one refusal, no retry without it
    report = client.get(f"{API}/audits/{audit['id']}/result").json()
    assert report["firecrawl"]["used"] is False and report["firecrawl"]["zero_data_retention"]["status"] == "not available"
    assert report["firecrawl"]["needs_decision"] == "zero_data_retention" and report["firecrawl"]["credits"]["used_or_reserved"] == 0
    view = get(client, audit, "/summary")["firecrawl"]
    decision = view["decision"]
    assert decision["message"].startswith("Zero data retention not available") and "may be stored by Firecrawl" in decision["warning"]
    assert decision["approve_credits"] == 6  # one credit a page without it: five pages and robots.txt
    assert all(row["source"] is None for row in get(client, audit, "/findings", limit=100)["items"])
    assert "Zero data retention not available" in client.get(f"{API}/audits/{audit['id']}/print?full=true").text

    path = f"{API}/audits/{audit['id']}/firecrawl/without-zero-data-retention"
    error(client.post(path, json={"accept_content_may_be_stored": False, "approved_max_credits": 6}), 422, "storage_not_accepted")
    error(client.post(path, json={"accept_content_may_be_stored": True, "approved_max_credits": 12}), 402, "confirmation_required")
    assert client.post(path, json={"approved_max_credits": 6}).status_code == 422 and len(api.bodies) == 1
    assert get(client, audit)["firecrawl"]["state"] == "needs_decision"

    again = client.post(path, json={"accept_content_may_be_stored": True, "approved_max_credits": 6})
    assert again.status_code == 200 and again.json()["state"] in ("queued", "running"), again.text
    done = get(client, client.app.state.runner.wait(audit["id"], 60))
    assert done["state"] == "finished" and done["firecrawl"]["state"] == "done" and done["firecrawl"]["options"]["allow_without_zero_data_retention"]
    assert len(api.bodies) == 5 and all("zeroDataRetention" not in body for body in api.bodies[1:])
    section = client.get(f"{API}/audits/{audit['id']}/result").json()["firecrawl"]
    assert section["used"] and section["pages_read"] == 3 and section["zero_data_retention"] == {
        "requested": True, "applied": False, "status": "waived by the user for this audit"}
    assert section["credits"]["used_or_reserved"] == 4
    assert get(client, audit, "/summary")["firecrawl"]["decision"] is None
    error(client.post(path, json={"accept_content_may_be_stored": True, "approved_max_credits": 6}), 409, "no_decision_waiting")
    # The waiver was for that audit only: a new plan asks for zero data retention again.
    assert plan(client, firecrawl=True)["firecrawl"]["options"]["allow_without_zero_data_retention"] is False


def test_a_resume_reads_through_firecrawl_once_and_a_finished_audit_spends_nothing_more(web, tmp_path):
    api = Firecrawl(PAGES)
    site = Site(pause_at=2, respond=cloudflare)  # stopped while the sitemap is being asked for
    client = web(site=site, firecrawl=services(tmp_path, api))
    audit = start(client, approve(client, plan(client, firecrawl=True, firecrawl_max_pages=5)), wait=False)
    assert site.reached.wait(15)
    client.post(f"{API}/audits/{audit['id']}/stop", json={})
    site.release.set()
    stopped = get(client, client.app.state.runner.wait(audit["id"], 30))
    assert stopped["state"] == "stopped" and stopped["firecrawl"]["state"] == "pending" and api.bodies == []
    preview = client.post(f"{API}/audits/{audit['id']}/resume-plan", json={}).json()
    assert preview["firecrawl"]["pending"] and not preview["firecrawl"]["needs_confirmation"] and preview["firecrawl"]["max_credits"] == 12
    assert api.bodies == [] and get(client, audit)["state"] == "stopped"
    assert client.post(f"{API}/audits/{audit['id']}/resume", json={}).status_code == 200  # the basic proxy is not asked about again
    done = get(client, client.app.state.runner.wait(audit["id"], 60))
    assert done["state"] == "finished" and done["firecrawl"]["state"] == "done" and len(api.bodies) == 4
    after = client.post(f"{API}/audits/{audit['id']}/resume-plan", json={}).json()
    assert after["firecrawl"]["pending"] is False and after["firecrawl"]["note"] == strings.t("fc.resume.done")


def test_the_demo_has_a_made_up_firecrawl_for_its_blocked_bank(web, tmp_path):
    client = web(firecrawl=demo.firecrawl_services(tmp_path / "demo-fc"))
    audit = start(client, plan(client, demo.BANK))
    section = client.get(f"{API}/audits/{audit['id']}/result").json()["firecrawl"]
    assert audit["outcome"]["code"] == "COMPLETED" and section["used"] and section["pages_read"] == 4 and section["skipped_by_robots"] == 0
    view = get(client, audit, "/summary")
    assert view["blocked"] is None and view["firecrawl"]["used"] and view["pages_stat"]["line"] == "Pages read: 4 (via Firecrawl)"
    # An open demo site is read through the made-up Firecrawl as well, page for page.
    shop = start(client, plan(client, demo.SHOP_URL if hasattr(demo, "SHOP_URL") else SHOP))
    shop_view = get(client, shop, "/summary")
    assert shop_view["firecrawl"]["used"] and shop_view["pages_stat"]["label"] == "Pages read" and "via Firecrawl" in shop_view["pages_stat"]["detail"]
    assert any(row["source"] for row in get(client, audit, "/findings", limit=100)["items"])


def test_engine_error_is_complete_in_results_and_downloads_and_not_called_a_block(web, tmp_path):
    from test_content_provider import ENGINE_ERROR, engine_failure
    api = Firecrawl(responder=engine_failure)
    client = web(site=Site(respond=cloudflare), firecrawl=services(tmp_path, api))
    audit = start(client, approve(client, plan(client, firecrawl=True)))
    report = get(client, audit, "/result")
    assert report["firecrawl"]["errors"][0]["message"] == ENGINE_ERROR
    assert report["firecrawl"]["errors"][0]["engines_tried"] == ["pdf", "document", "image"]
    view = get(client, audit, "/summary")
    assert view["firecrawl"]["also_blocked"] is False and view["firecrawl_offer"] is None
    assert report["firecrawl"]["credits"]["used_or_reserved"] == 0
    for path in ("/summary", "/print?full=true", "/downloads/markdown?draft=true"):
        text = client.get(f"{API}/audits/{audit['id']}{path}").text
        assert ENGINE_ERROR in text and "Firecrawl could not load the page as a website" in text
    assert all(b["proxy"] == "basic" for b in api.bodies)


def test_the_result_page_of_a_challenged_site_read_through_firecrawl_has_no_block_card(web, tmp_path):
    from pathlib import Path
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    try:  # a development install without the browser download skips this, as the rendering tests do
        with sync_playwright() as pw:
            pw.chromium.launch().close()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"headless Chromium unavailable: {exc}")
    client = web(site=Site(respond=cloudflare), firecrawl=services(tmp_path, Firecrawl(PAGES)))
    view = get(client, start(client, plan(client)), "/summary")
    static = Path(__file__).parents[1] / "maya_audit_web" / "static"
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        problems = []
        page.on("pageerror", lambda exc: problems.append(str(exc)))
        page.route("**/*", lambda route: route.abort())
        page.set_content("<main id='result'></main>")
        page.add_script_tag(content=(static / "app.js").read_text(encoding="utf-8").removesuffix("boot();\n"))
        page.evaluate("values => { state.strings = values; }", strings.table("en"))
        # DECISIONS 310: the former page is the folded "Technical details"; opened here to read it.
        page.evaluate("view => { const out = resultView(view, {}); document.querySelector('#result').append(out); out.openTechnical(); }", view)
        page.wait_for_timeout(300)
        text = page.locator(".tech-details").inner_text()
        browser.close()
    # In the technical details the headline still comes first and the outcome follows it.
    assert problems == [] and "Pages read" in text and "via Firecrawl" in text and view["headline"] in text
    assert text.index(view["headline"]) < text.index("Audit complete")
    assert "By severity" in text and view["top_title"] in text and "Problems by page (" in text
    assert "The site blocked this audit" not in text and "Readable pages" not in text and "[object Object]" not in text
    assert "Maya's direct crawler was challenged" in text and "Genuine AI-crawler access was not measured" in text
    assert "What Firecrawl did, and what it cost" in text and "AI crawlers may not see this content" not in text
