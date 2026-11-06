"""A blocked audit's result card: the block said once, the readable-pages counter, and reading the content through
Firecrawl afterwards without running the audit again. Every site and every Firecrawl here is in memory."""
import httpx
import pytest

pytest.importorskip("fastapi")

from maya_audit.findings import check_id_key  # noqa: E402
from maya_audit_web import demo, snapshot  # noqa: E402
from test_firecrawl import Firecrawl  # noqa: E402
from test_web_app import API, Site, audit_of, cloudflare, error, get, plan, start, web  # noqa: E402,F401
from test_web_firecrawl import NO_ZDR, PAGES, approve, services  # noqa: E402

WALL = {"success": True, "data": {"rawHtml": "<html><title>Just a moment...</title><body>Checking your browser</body></html>",
                                  "metadata": {"statusCode": 403}}}


def walled(for_proxies=("basic",)):
    """A Firecrawl whose robots.txt request works and whose pages come back as a challenge for the proxies named."""
    return lambda body: httpx.Response(200, json=WALL) if body["proxy"] in for_proxies and not body["url"].endswith("/robots.txt") else None


def read(client, audit, **body):
    return client.post(f"{API}/audits/{audit['id']}/firecrawl/read", json=body)


def finished(client, audit):
    return get(client, client.app.state.runner.wait(audit["id"], 60))


def test_a_blocked_audit_says_so_once_and_counts_readable_pages(web, tmp_path):
    client = web(site=Site(respond=cloudflare), firecrawl=services(tmp_path, Firecrawl(PAGES)))
    audit = start(client, plan(client, firecrawl=False))
    view = get(client, audit, "/summary")
    block, stat = view["blocked"], view["pages_stat"]
    assert block["blocked_requests"] >= 1 and stat["blocked"] and stat["value"] == 0 and stat["label"] == "Readable pages"
    assert block["blocked_requests"] == 1 and stat["line"] == "Readable pages: 0 (1 blocked request)" and stat["detail"] == "1 blocked request"
    assert set(block["sections"]) == {"who", "meaning", "next", "firecrawl", "status"}
    # The block's own finding stays a finding everywhere; on the card's top list it only points to the card.
    pointed = [row for row in view["top"] if row["in_block_card"]]
    assert [row["check_id"] for row in pointed] == ["ACC-9"] and view["block_pointer"]
    assert any(row["check_id"] == "ACC-9" for row in get(client, audit, "/findings", limit=100)["items"])
    assert view["technical"]["title"] == "Technical details" and [gate["check_id"] for gate in view["gates"]][0] == "INT-1"
    assert "Readable pages" in client.get(f"{API}/audits/{audit['id']}/print?full=true").text
    # An audit the site let in keeps the counter it always had.
    client.site.custom = None
    plain = get(client, start(client, plan(client, firecrawl=False)), "/summary")
    assert plain["blocked"] is None and plain["pages_stat"]["label"] == "Pages checked" and plain["firecrawl_offer"] is None
    assert plain["pages_stat"]["value"] == plain["counts"]["pages_checked"] and not any(row.get("in_block_card") for row in plain["top"])


def test_firecrawl_can_be_switched_on_afterwards_and_the_website_is_not_asked_again(web, tmp_path, monkeypatch):
    api = Firecrawl(PAGES)
    client = web(site=Site(respond=cloudflare), firecrawl=services(tmp_path, api))
    audit = start(client, plan(client, firecrawl=False))
    offer = get(client, audit, "/summary")["firecrawl_offer"]
    assert offer["kind"] == "not_requested" and offer["available"] and offer["offline"] and offer["consent"] == {
        **offer["consent"], "storage": False, "owner": False}
    choice, = offer["choices"]
    assert choice["proxy"] == "basic" and choice["max_credits"] == 106 and choice["label"] == "Read content via Firecrawl: confirm up to 106 credits"
    assert "website is asked for nothing more" in offer["offline_note"] and api.bodies == []
    monkeypatch.setenv("MAYA_AUDIT_FIRECRAWL_USD_PER_CREDIT", "0.001")
    priced = get(client, audit, "/summary")["firecrawl_offer"]["choices"][0]
    assert priced["label"].endswith("confirm up to 106 credits (about $0.11)") and priced["max_usd"] == 0.106

    error(read(client, audit, proxy="basic", approved_max_credits=5), 402, "confirmation_required")
    error(read(client, audit, proxy="enhanced", owner_approved_bypass=True, approved_max_credits=106), 422, "firecrawl_options")
    assert api.bodies == [] and get(client, audit)["firecrawl"]["state"] == "none"
    before_site, before = len(client.site.requests), client.get(f"{API}/audits/{audit['id']}/result").json()
    before_view = get(client, audit, "/summary")
    going = read(client, audit, proxy="basic", approved_max_credits=106)
    assert going.status_code == 200 and going.json()["state"] in ("queued", "running", "finished"), going.text
    done = finished(client, audit)
    assert done["state"] == "finished" and done["firecrawl"]["state"] == "done" and done["firecrawl"]["continuing"] is False
    assert len(client.site.requests) == before_site  # the saved result was reused: not one new request to the website
    assert done["sessions"] == audit["sessions"] and [step["status"] for step in done["timeline"]] == [step["status"] for step in audit["timeline"]]
    after = client.get(f"{API}/audits/{audit['id']}/result").json()
    assert after["crawl"]["requests"] == before["crawl"]["requests"] and after["gates"] == before["gates"]
    access = lambda report: [c for c in report["checks"] if c["check_id"].startswith(("ACC", "PRF"))]
    assert {k: v for k, v in enumerate(access(after)) if v["check_id"] != "ACC-9"} == {k: v for k, v in enumerate(access(before)) if v["check_id"] != "ACC-9"}
    # The one change: the reader's pages recorded beside it; Cloudflare's block stays a problem (DECISIONS 317).
    assert next(c for c in after["checks"] if c["check_id"] == "ACC-9")["findings"][0]["evidence"]["read_through"]["pages_read"] == 3
    section = after["firecrawl"]
    assert section["used"] and section["pages_read"] == 3 and section["proxy"] == "basic" and all(body["zeroDataRetention"] for body in api.bodies)
    view = get(client, audit, "/summary")
    assert view["firecrawl_offer"] is None and view["firecrawl"]["used"] and view["firecrawl"]["attempts"][0]["result"] == "read"
    assert view["pages_stat"]["value"] == 3 and view["pages_stat"]["line"] == "Pages read: 3 (via Firecrawl)"
    assert "could not run" in before_view["blocked"]["lines"][3] and "need to read pages" in before_view["blocked"]["lines"][3]
    assert view["blocked"] is None and done["outcome"]["code"] == "COMPLETED"  # read after all: the headline goes
    assert view["first_action"] is not None and view["firecrawl"]["checks"] == sorted(view["firecrawl"]["checks"], key=check_id_key)
    assert view["firecrawl"]["checks"].index("STR-2") < view["firecrawl"]["checks"].index("STR-10")
    assert view["summary_line"].startswith("3 pages checked.")
    assert view["first_action_withheld"] is None
    assert after["crawl"]["pages"][0]["status"] == 403  # the record of Maya's own request stays
    assert view["counts"]["pages_checked"] == view["method"]["pages_checked"] == 3
    assert "**Pages read:** 3 (via Firecrawl)" in client.get(f"{API}/audits/{audit['id']}/downloads/markdown").text
    printed = client.get(f"{API}/audits/{audit['id']}/print?full=true").text
    assert "on 3 pages" in printed and "pages checked." not in printed and "3 (via Firecrawl)" in printed and "The site blocked this audit" not in printed
    assert all("read through Firecrawl" in g["reason"] for g in view["coverage"]["gaps"] if g.get("blocked"))
    error(read(client, audit, proxy="basic", approved_max_credits=106), 409, "firecrawl_not_offered")


def test_accepting_storage_after_a_refusal_continues_without_running_the_audit_again(web, tmp_path):
    api = Firecrawl(PAGES, responder=NO_ZDR)
    client = web(site=Site(respond=cloudflare), firecrawl=services(tmp_path, api))
    audit = start(client, approve(client, plan(client, firecrawl=True, firecrawl_max_pages=5)))
    offer = get(client, audit, "/summary")["firecrawl_offer"]
    assert offer["kind"] == "zero_data_retention" and offer["consent"]["storage"] and not offer["consent"]["owner"]
    assert "may be stored by Firecrawl" in offer["consent"]["storage_label"] and offer["choices"][0]["max_credits"] == 6
    assert offer["choices"][0]["label"] == "Continue without zero data retention: confirm up to 6 credits"
    error(read(client, audit, proxy="basic", approved_max_credits=6), 422, "storage_not_accepted")
    before = len(client.site.requests)
    assert read(client, audit, proxy="basic", accept_content_may_be_stored=True, approved_max_credits=6).status_code == 200
    done = finished(client, audit)
    assert done["firecrawl"]["state"] == "done" and len(client.site.requests) == before
    section = client.get(f"{API}/audits/{audit['id']}/result").json()["firecrawl"]
    assert section["used"] and section["zero_data_retention"]["status"] == "waived by the user for this audit"
    assert [a["result"] for a in get(client, audit, "/summary")["firecrawl"]["attempts"]] == ["needs_decision", "read"]


def test_basic_being_blocked_too_is_said_and_a_stronger_proxy_needs_the_owner_tick_and_a_new_confirmation(web, tmp_path):
    api = Firecrawl(PAGES, responder=walled(("basic",)))
    client = web(site=Site(respond=cloudflare), firecrawl=services(tmp_path, api))
    audit = start(client, approve(client, plan(client, firecrawl=True, firecrawl_max_pages=5)))
    assert {body["proxy"] for body in api.bodies} == {"basic"}  # nothing escalated by itself
    view = get(client, audit, "/summary")
    assert view["firecrawl"]["also_blocked"] and view["firecrawl"]["used"] is False
    assert view["firecrawl"]["lines"][0].startswith("Firecrawl basic was also blocked: 1 page(s) tried")
    offer = view["firecrawl_offer"]
    assert offer["kind"] == "also_blocked" and offer["title"] == "Firecrawl basic was also blocked" and offer["consent"]["owner"]
    assert [choice["proxy"] for choice in offer["choices"]] == ["enhanced", "auto"] and "never automatically" in " ".join(offer["lines"])
    assert offer["choices"][0]["label"] == "Retry with the enhanced proxy: confirm up to 12 credits"
    for path in ("/print?full=true", "/downloads/markdown?draft=true"):
        text = client.get(f"{API}/audits/{audit['id']}{path}").text
        assert "Firecrawl basic was also blocked" in text and "never switched on automatically" in text

    sent = len(api.bodies)
    error(read(client, audit, proxy="enhanced", approved_max_credits=12), 422, "owner_approval_required")
    error(read(client, audit, proxy="basic", approved_max_credits=12), 422, "firecrawl_options")
    error(read(client, audit, proxy="enhanced", owner_approved_bypass=True, approved_max_credits=11), 402, "confirmation_required")
    assert len(api.bodies) == sent
    before = len(client.site.requests)
    assert read(client, audit, proxy="enhanced", owner_approved_bypass=True, approved_max_credits=12).status_code == 200
    done = finished(client, audit)
    assert done["firecrawl"]["options"]["proxy"] == "enhanced" and len(client.site.requests) == before
    assert {body["proxy"] for body in api.bodies[sent:]} == {"enhanced"}
    section = client.get(f"{API}/audits/{audit['id']}/result").json()["firecrawl"]
    assert section["used"] and section["proxy"] == "enhanced" and section["owner_approved_bypass"] is True and section["pages_read"] == 3
    view = get(client, audit, "/summary")
    assert [a["result"] for a in view["firecrawl"]["attempts"]] == ["also_blocked", "read"] and view["firecrawl"]["attempts"][1]["owner_approved_bypass"]
    assert view["firecrawl"]["spent_line"].startswith("2 Firecrawl attempts") and view["firecrawl_offer"] is None
    assert "the site owner approved bypassing bot protection" in client.get(f"{API}/audits/{audit['id']}/print?full=true").text


def test_a_stronger_proxy_that_is_blocked_too_ends_the_offers(web, tmp_path):
    api = Firecrawl(PAGES, responder=walled(("basic", "enhanced", "auto")))
    client = web(site=Site(respond=cloudflare), firecrawl=services(tmp_path, api))
    audit = start(client, approve(client, plan(client, firecrawl=True, firecrawl_max_pages=5)))
    assert read(client, audit, proxy="auto", owner_approved_bypass=True, approved_max_credits=12).status_code == 200
    finished(client, audit)
    view = get(client, audit, "/summary")
    assert view["firecrawl_offer"]["kind"] == "stronger_blocked" and view["firecrawl_offer"]["choices"] == []
    assert view["firecrawl_offer"]["title"] == "Firecrawl auto was also blocked" and view["firecrawl"]["lines"][0].startswith("Firecrawl auto was also blocked")
    error(read(client, audit, proxy="enhanced", owner_approved_bypass=True, approved_max_credits=12), 409, "firecrawl_not_offered")


def test_without_a_key_or_a_block_nothing_is_offered_and_an_older_audit_repeats_its_last_steps(web, tmp_path):
    api = Firecrawl(PAGES)
    client = web(site=Site(respond=cloudflare), firecrawl=services(tmp_path, api))
    audit = start(client, plan(client, firecrawl=False))
    folder = client.app.state.runner.state_folder(audit["id"])
    assert snapshot.exists(folder)
    snapshot.remove(folder)  # as an audit saved before this version
    offer = get(client, audit, "/summary")["firecrawl_offer"]
    assert offer["offline"] is False and "requested from the website once more" in offer["offline_note"]
    before = len(client.site.requests)
    assert read(client, audit, proxy="basic", approved_max_credits=106).status_code == 200
    done = finished(client, audit)
    assert done["firecrawl"]["state"] == "done" and len(client.site.requests) > before
    assert client.get(f"{API}/audits/{audit['id']}/result").json()["firecrawl"]["used"]

    open_site = web(folder=tmp_path / "open", firecrawl=services(tmp_path / "2", Firecrawl(PAGES)))
    fine = start(open_site, plan(open_site, firecrawl=False))
    assert get(open_site, fine, "/summary")["firecrawl_offer"] is None and not snapshot.exists(open_site.app.state.runner.state_folder(fine["id"]))
    error(read(open_site, fine, proxy="basic", approved_max_credits=106), 409, "firecrawl_not_offered")

    keyless = web(folder=tmp_path / "keyless", site=Site(respond=cloudflare), firecrawl=services(tmp_path / "3", Firecrawl(PAGES), key=False))
    blocked = start(keyless, plan(keyless))
    offer = get(keyless, blocked, "/summary")["firecrawl_offer"]
    assert offer["available"] is False and "key is not set" in offer["unavailable_reason"]
    error(read(keyless, blocked, proxy="basic", approved_max_credits=106), 409, "firecrawl_key_not_configured")
    assert not (tmp_path / "3" / "fc").exists()  # a computer without a key gets no spending record


def test_the_demo_shows_both_awkward_cases_with_a_made_up_firecrawl(web, tmp_path):
    client = web(firecrawl=demo.firecrawl_services(tmp_path / "demo-fc"))
    vault = start(client, approve(client, plan(client, demo.VAULT, firecrawl=True, firecrawl_max_pages=5)))
    offer = get(client, vault, "/summary")["firecrawl_offer"]
    assert offer["kind"] == "zero_data_retention"
    assert read(client, vault, proxy="basic", accept_content_may_be_stored=True, approved_max_credits=offer["choices"][0]["max_credits"]).status_code == 200
    finished(client, vault)
    assert get(client, vault, "/summary")["firecrawl"]["used"]
    fortress = start(client, approve(client, plan(client, demo.FORTRESS, firecrawl=True, firecrawl_max_pages=5)))
    offer = get(client, fortress, "/summary")["firecrawl_offer"]
    assert offer["kind"] == "also_blocked"
    assert read(client, fortress, proxy="enhanced", owner_approved_bypass=True, approved_max_credits=offer["choices"][0]["max_credits"]).status_code == 200
    finished(client, fortress)
    view = get(client, fortress, "/summary")
    assert view["firecrawl"]["used"] and view["firecrawl"]["proxy"] == "enhanced" and view["firecrawl_offer"] is None


def test_reader_check_ids_are_numeric_and_rendering_does_not_double_count():
    from maya_audit.findings import check_id_key
    from maya_audit_web.summary import pages_read
    assert sorted(["STR-11", "STR-2", "STR-1", "STR-10"], key=check_id_key) == ["STR-1", "STR-2", "STR-10", "STR-11"]
    report = {"crawl": {"pages": [{"url": "https://example.test/", "status": 200, "fetch_class": "ok"}]},
              "firecrawl": {"used": True, "pages": [{"url": "https://example.test/", "outcome": "read"}]}}
    assert pages_read(report) == 1
    report["firecrawl"] = {"used": True, "rendered": [{"url": "https://example.test/", "outcome": "rendered"}]}
    assert pages_read(report) == 1


def test_blocked_header_wraps_without_overlapping_badge(web, tmp_path):
    from pathlib import Path
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    from maya_audit_web.strings import table
    try:  # a development install without the browser download skips this, as the rendering tests do
        with sync_playwright() as pw:
            pw.chromium.launch().close()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"headless Chromium unavailable: {exc}")
    client = web(site=Site(respond=cloudflare), firecrawl=services(tmp_path, Firecrawl(PAGES, walled(("basic",)))))
    audit = start(client, plan(client, firecrawl_max_pages=5))
    view = get(client, audit, "/summary")
    assert view["blocked"] and view["firecrawl_offer"]["kind"] == "also_blocked"  # only now is the site called blocked
    static = Path(__file__).parents[1] / "maya_audit_web" / "static"
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.route("**/*", lambda route: route.abort())
        page.set_content("<main id='result'></main>")
        page.add_style_tag(content=(static / "app.css").read_text(encoding="utf-8"))
        page.add_script_tag(content=(static / "app.js").read_text(encoding="utf-8").removesuffix("boot();\n"))
        page.evaluate("values => { state.strings = values; }", table("en"))
        page.evaluate("view => document.querySelector('#result').append(blockCard(view, {}))", view)
        for width in (375, 1100):
            page.set_viewport_size({"width": width, "height": 900})
            badge = page.locator(".status-line .state").bounding_box()
            count = page.locator(".status-line strong").bounding_box()
            assert count["y"] >= badge["y"] + badge["height"]
            assert "Readable pages: 0" in page.locator(".status-line").inner_text()
            assert "[object Object]" not in page.locator(".status-line").inner_text()
        browser.close()
