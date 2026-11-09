"""The local web app (API v1). Every audit here runs against in-memory sites and an in-memory DataForSEO.

Nothing in this file can reach a real website or a real provider: site requests go to `demo.site_transport`,
paid requests to `Provider`, and tests/conftest.py blocks any socket that is not loopback.
"""
import io
import json
import socket
import os
import re
import threading
import time
import zipfile
from pathlib import Path

import httpx
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from maya_audit.dataforseo.cache import CACHE_NAME, Cache  # noqa: E402
from maya_audit.dataforseo.credentials import Credentials  # noqa: E402
from maya_audit.dataforseo.ledger import LEDGER_NAME, BudgetExceeded, Ledger  # noqa: E402
from maya_audit_web import catalog, chat, comparison, demo, paid, pdf, strings, summary, wording  # noqa: E402
from maya_audit_web.app import create_app  # noqa: E402
from maya_audit_web.runner import Engine, WorkerAlreadyRunning  # noqa: E402
from maya_audit_web.store import MAX_EVENTS, Store  # noqa: E402

BASE = "http://127.0.0.1:8770"
API = "/api/v1"
SHOP, CAFE = "demo-shop.localhost", "demo-kafe.localhost"
PACKAGE = Path(strings.__file__).resolve().parent
SECRETS = ("made-up-login", "made-up-password")


class Site:
    """The demo sites, counting requests, optionally pausing at one so a test can act mid-crawl."""

    def __init__(self, pause_at=None, respond=None):
        self.requests, self.pause_at, self.custom = [], pause_at, respond
        self.reached, self.release = threading.Event(), threading.Event()
        self._inner = demo.site_transport(0.0)

    def transport(self):
        def respond(request):
            self.requests.append(str(request.url))
            if self.pause_at and len(self.requests) == self.pause_at:
                self.reached.set()
                self.release.wait(15)
            return self.custom(request) if self.custom else self._inner.handle_request(request)
        return httpx.MockTransport(respond)


class Provider:
    """A made-up DataForSEO that records every request it is sent."""

    def __init__(self, responder=None):
        self.requests, self.responder = [], responder

    def __call__(self, request):
        self.requests.append(request.url.path)
        return self.responder(request) if self.responder else demo._backlinks(request)


@pytest.fixture
def web(tmp_path):
    made = []

    def make(site=None, provider=None, credentials=True, folder=None, citations=False, heartbeat_s=10.0, firecrawl=None):
        site, provider = site or Site(), provider or Provider()
        home = folder or tmp_path / "web"
        services = paid.PaidServices(
            credentials=lambda: Credentials(*SECRETS) if credentials else None,
            stores=lambda: (Ledger(tmp_path / "paid" / LEDGER_NAME), Cache(tmp_path / "paid" / CACHE_NAME)),
            transport=httpx.MockTransport(provider), plan=demo.paid_services(tmp_path / "unused").plan,
            search_plan=demo.paid_services(tmp_path / "unused").search_plan)
        cited = str(demo.write_citations(tmp_path / "cited")) if citations else None
        engine = Engine(paid=services, transport_factory=site.transport, allow_loopback=True, overrides=demo.OVERRIDES,
                        overrides_for=(lambda url: {"citations_file": cited}) if cited else None,
                        **({"firecrawl": firecrawl} if firecrawl else {}))
        client = TestClient(create_app(home, engine=engine, port=8770, heartbeat_s=heartbeat_s), base_url=BASE)
        client.__enter__()
        made.append(client)
        client.get("/")  # the page sets the session cookie, as a browser would receive it
        client.headers["x-maya-token"] = client.get(f"{API}/session").json()["token"]
        client.site, client.provider, client.ledger = site, provider, Ledger(tmp_path / "paid" / LEDGER_NAME)
        return client

    def close(client):
        if client in made:
            made.remove(client)
            client.__exit__(None, None, None)

    make.close = close
    yield make
    for client in made:
        client.__exit__(None, None, None)


def plan(client, url=SHOP, expect=201, **options):
    response = client.post(f"{API}/plans", json={"url": url, **options})
    assert response.status_code == expect, response.text
    return response.json()


def confirm(client, made):
    if not made["paid"]["needs_confirmation"]:
        return made  # within the per-audit threshold: nothing to confirm
    response = client.post(f"{API}/plans/{made['id']}/confirm", json={"approved_max_usd": made["paid"]["total_usd"]})
    assert response.status_code == 200, response.text
    return response.json()


def start(client, made, wait=True):
    response = client.post(f"{API}/audits", json={"plan_id": made["id"], "message": f"audit {made['target']['host']}"})
    assert response.status_code == 201, response.text
    audit = response.json()
    if wait:
        client.app.state.runner.wait(audit["id"], 90)
    return client.get(f"{API}/audits/{audit['id']}").json()


def audit_of(client, url=SHOP, **options):
    return start(client, plan(client, url, **options))


def get(client, audit, path="", **params):
    response = client.get(f"{API}/audits/{audit['id']}{path}", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def error(response, status, code):
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == {"error"} and set(body["error"]) == {"code", "message", "details"}, body
    assert body["error"]["code"] == code, body
    return body["error"]


def sse(text):
    """Parse a finished event stream into (id, name, data) rows."""
    rows = []
    for block in text.split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line and not line.startswith(":"))
        if "event" in fields:
            rows.append((int(fields["id"]), fields["event"], json.loads(fields["data"])))
    return rows


# -- request safety --------------------------------------------------------------------------------

def test_the_server_binds_to_loopback_only_and_has_one_launcher():
    from maya_audit_web import __main__ as main_module
    assert main_module.HOST == "127.0.0.1"
    source = (PACKAGE / "__main__.py").read_text(encoding="utf-8")
    assert "--host" not in source and "0.0.0.0" not in source


@pytest.mark.parametrize("headers", [
    {"host": "evil.example"}, {"host": "127.0.0.1:9999"}, {"host": "rebind.example:8770"},
    {"origin": "https://evil.example"}, {"origin": "http://127.0.0.1:9999"}, {"origin": "null"},
    {"sec-fetch-site": "cross-site"}, {"sec-fetch-site": "same-site"},
])
def test_requests_from_another_host_or_site_are_refused(web, headers):
    client = web()
    code = "host_not_allowed" if "host" in headers else "cross_site_request"
    error(client.get(f"{API}/audits", headers=headers), 403, code)
    error(client.get("/", headers=headers), 403, code)
    error(client.post(f"{API}/plans", json={"url": SHOP}, headers=headers), 403, code)
    assert client.site.requests == []


def test_reads_need_the_session_cookie_and_changes_also_need_the_token_and_json(web):
    client = web()
    assert client.get(f"{API}/health").json() == {"status": "ok", "api_version": "1"}
    bare = TestClient(client.app, base_url=BASE)  # a local program that never opened the page: no Origin, no cookie
    for path in ("/session", "/audits", "/budget", "/settings", "/openapi.json", "/strings"):
        error(bare.get(API + path), 401, "not_authenticated")
    error(bare.post(f"{API}/plans", json={"url": SHOP}, headers={"x-maya-token": client.headers["x-maya-token"]}), 401, "not_authenticated")
    assert bare.get(f"{API}/health").status_code == 200
    good = {"url": SHOP}
    error(client.post(f"{API}/plans", json=good, headers={"x-maya-token": ""}), 403, "bad_action_token")
    error(client.post(f"{API}/plans", json=good, headers={"x-maya-token": "guess"}), 403, "bad_action_token")
    error(client.post(f"{API}/plans", data={"url": SHOP}), 415, "json_required")  # what an HTML form can send
    error(client.post(f"{API}/plans", content=json.dumps(good), headers={"content-type": "text/plain"}), 415, "json_required")
    error(client.post(f"{API}/plans", json={"url": "x" * 70_000}), 413, "request_too_large")
    error(client.patch(f"{API}/plans", json=good), 405, "method_not_allowed")
    error(client.options(f"{API}/plans", headers={"origin": BASE, "access-control-request-method": "POST"}), 405, "method_not_allowed")
    assert client.post(f"{API}/plans", json=good).status_code == 201
    cookie = client.get("/").headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert client.headers["x-maya-token"] not in cookie  # the token is never in a cookie or an address


def test_responses_carry_protective_headers_no_cross_origin_grant_and_one_error_shape(web):
    client = web()
    for path in ("/", f"{API}/session", "/static/app.js", f"{API}/health"):
        response = client.get(path)
        assert response.status_code == 200
        assert "default-src 'none'" in response.headers["content-security-policy"]
        assert "script-src 'self'" in response.headers["content-security-policy"]
        assert response.headers["x-content-type-options"] == "nosniff" and response.headers["x-frame-options"] == "DENY"
        assert not [name for name in response.headers if name.startswith("access-control-")]
    assert client.get(f"{API}/session").headers["cache-control"] == "no-store"
    error(client.get(f"{API}/nothing-here"), 404, "not_found")
    error(client.get(f"{API}/audits/{'0' * 32}"), 404, "audit_not_found")
    error(client.get(f"{API}/audits/not-an-id/summary"), 404, "audit_not_found")
    invalid = error(client.post(f"{API}/plans", json={"url": SHOP, "mode": "everything", "surprise": 1}), 422, "invalid_request")
    assert {row["field"] for row in invalid["details"]["fields"]} == {"mode", "surprise"}
    error(client.get(f"{API}/audits", params={"limit": 5000}), 422, "invalid_request")


def test_the_page_never_builds_markup_from_text():
    script = (PACKAGE / "static" / "app.js").read_text(encoding="utf-8")
    for unsafe in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "javascript:", "new Function"):
        assert unsafe not in script
    page = (PACKAGE / "static" / "index.html").read_text(encoding="utf-8")
    assert '<script src="/static/app.js"></script>' in page and "onclick=" not in page and "style=" not in page


@pytest.mark.usefixtures("confirm_every_paid_plan")
def test_the_api_describes_itself_and_exposes_no_secret_or_path(web, tmp_path):
    client = web()
    schema = client.get(f"{API}/openapi.json").json()
    paths = set(schema["paths"])
    for wanted in ("/health", "/plans", "/plans/{plan_id}", "/plans/{plan_id}/confirm", "/audits", "/audits/{audit_id}",
                   "/audits/{audit_id}/events", "/audits/{audit_id}/stop", "/audits/{audit_id}/resume-plan",
                   "/audits/{audit_id}/resume", "/audits/{audit_id}/result", "/audits/{audit_id}/findings",
                   "/audits/{audit_id}/evidence/{evidence_id}", "/audits/{audit_id}/downloads/{format}",
                   "/audits/{audit_id}/comparison", "/audits/{audit_id}/conversation", "/audits/{audit_id}/messages",
                   "/projects/{project_id}/profile", "/budget", "/settings"):
        assert API + wanted in paths, wanted
    shown = json.dumps([client.get(f"{API}/settings").json(), client.get(f"{API}/budget").json(),
                        client.get(f"{API}/health").json(), client.get(f"{API}/session").json()])
    assert str(tmp_path) not in shown and "/Users/" not in shown and not any(secret in shown for secret in SECRETS)
    assert client.get(f"{API}/settings").json()["paid"] == {"daily_cap_usd": 2.0, "credentials_configured": True}


# -- addresses and plans ---------------------------------------------------------------------------

def test_reading_an_address_out_of_a_message():
    assert chat.find_address("please audit example.com, thanks") == "example.com"
    assert chat.find_address("check https://www.example.com.tr/mağaza?x=1.") == "https://www.example.com.tr/mağaza?x=1"
    for question in ("is robots.txt blocking bots?", "what about sitemap.xml and index.html", "e.g. the json-ld", "me@example.com"):
        assert chat.find_address(question) is None
    assert chat.target_url("Example.COM/shop#top") == "https://example.com/shop"
    for private in ("http://127.0.0.1/", "localhost:8000", "http://10.0.0.5/", "http://169.254.169.254/latest", "http://[::1]/"):
        with pytest.raises(chat.BadTarget, match="private"):
            chat.target_url(private)
    for bad in ("http://user:secret@example.com/", "https://intranet/", "http://example.com:notaport/", "http://0x7f.1/",
                "http://2130706433/", "http://10.1/", "ftp://example.com/"):
        with pytest.raises(chat.BadTarget):
            chat.target_url(bad)


def test_a_plan_touches_no_network_and_says_what_it_does_not_know(web):
    client = web()
    made = plan(client, f"https://{SHOP}/", mode="standard", key_pages=["/about", "tr/urun-3", ""])
    assert client.site.requests == [] and client.provider.requests == []
    assert made["target"] == {"url": f"https://{SHOP}/", "host": SHOP, "domain": SHOP, "http_fallback": None, "note": None}
    assert (made["mode"], made["page_cap"]) == ("standard", 500) and made["key_pages"] == [f"https://{SHOP}/about", f"https://{SHOP}/tr/urun-3"]
    # DECISIONS 333: the details say the same time as the short line, and the audit's time limit
    assert made["duration"]["known"] and made["duration"]["label"].startswith(made["duration"]["typical"]["label"]) \
        and f"time limit of {made['time_limit_minutes']} minutes" in made["duration"]["label"] and made["time_limit_minutes"] > 0
    assert any("do not know how many pages" in line for line in made["limitations"])
    assert any("block" in line for line in made["limitations"]) and any("not proof" in line for line in made["limitations"])
    assert len(made["included"]) == 6 and len(made["unavailable"]) == 4 and made["rendering"]["policy"] == "off"
    cost = made["paid"]
    assert cost["requested"] is False and cost["needs_confirmation"] is False and made["can_start"] and not made["needs_confirmation"]
    assert cost["total_usd"] > 0 and [c["state"] for c in cost["calls"]] == ["paid", "paid"]  # the price is shown before it is chosen
    assert all(c["purpose"] and c["cache_age_s"] is None for c in cost["calls"])
    assert cost["provider_balance"] == {"known": False, "message": strings.t("paid.balance.unknown")}
    assert cost["budget"]["day_is"] == "UTC calendar day" and cost["budget"]["resets_at"].endswith("T00:00:00+00:00")
    assert client.get(f"{API}/plans/{made['id']}").json()["fingerprint"] == made["fingerprint"]
    error(client.post(f"{API}/plans", json={"url": "http://192.168.1.1/"}), 422, "private_address")
    error(client.post(f"{API}/plans", json={"url": "what should I fix first?"}), 422, "invalid_url")
    error(client.post(f"{API}/plans", json={"url": SHOP, "key_pages": ["https://other.example/x"]}), 422, "invalid_key_pages")
    error(client.post(f"{API}/plans", json={"url": SHOP, "key_pages": [f"/item/{n}" for n in range(30)]}), 422, "invalid_key_pages")
    assert client.site.requests == [] and client.provider.requests == []


def test_local_fake_sites_are_a_test_only_permission(tmp_path):
    """Without the test permission the app refuses loopback at the plan, and the engine is told to block it too."""
    from maya_audit_web.runner import crawl_config
    real = Engine(transport_factory=lambda: demo.site_transport(0.0))
    with TestClient(create_app(tmp_path / "real", engine=real, port=8770), base_url=BASE) as client:
        client.get("/")
        client.headers["x-maya-token"] = client.get(f"{API}/session").json()["token"]
        error(client.post(f"{API}/plans", json={"url": SHOP}), 422, "private_address")
        error(client.post(f"{API}/plans", json={"url": "http://127.0.0.1:8000/"}), 422, "private_address")
    job = {"url": "https://example.com/", "mode": "quick", "key_pages": []}
    assert crawl_config(real, job, tmp_path / "x.db", resume=False).block_loopback is True
    assert crawl_config(Engine(allow_loopback=True), job, tmp_path / "x.db", resume=False).block_loopback is False
    from maya_audit_web import __main__ as main_module
    assert "allow_loopback=True" not in (PACKAGE / "__main__.py").read_text(encoding="utf-8").split("else:")[1]  # only the demo branch sets it


# -- confirmation and spending ---------------------------------------------------------------------

@pytest.mark.usefixtures("confirm_every_paid_plan")
def test_every_paid_plan_needs_a_confirmation_of_its_exact_cost_and_a_double_click_buys_once(web):
    client = web()
    made = plan(client, backlinks=True)
    total = made["paid"]["total_usd"]
    assert 0 < total < 0.50 and made["needs_confirmation"] and not made["can_start"]  # far below the old CLI threshold; still asked
    refused = error(client.post(f"{API}/audits", json={"plan_id": made["id"]}), 402, "confirmation_required")
    assert "$0.0516" in refused["message"] and refused["details"]["total_usd"] == total
    for amount in (0, total + 0.01, 2.0):
        error(client.post(f"{API}/plans/{made['id']}/confirm", json={"approved_max_usd": amount}), 422, "amount_mismatch")
    error(client.post(f"{API}/plans/{made['id']}/confirm", json={"approved_max_usd": 50_000}), 422, "invalid_request")
    error(client.post(f"{API}/plans/{made['id']}/confirm", json={}), 422, "invalid_request")
    confirmed = confirm(client, made)
    assert confirmed["confirmation"]["approved_max_usd"] == total and confirmed["can_start"]
    assert confirm(client, made)["confirmation"] == confirmed["confirmation"]  # confirming twice records it once
    assert client.site.requests == [] and client.provider.requests == [] and client.ledger.calls() == []  # confirming starts nothing

    first = client.post(f"{API}/audits", json={"plan_id": made["id"]})
    second = client.post(f"{API}/audits", json={"plan_id": made["id"]})
    assert (first.status_code, second.status_code) == (201, 200) and first.json()["id"] == second.json()["id"]
    audit = client.app.state.runner.wait(first.json()["id"], 60)
    assert client.post(f"{API}/audits", json={"plan_id": made["id"]}).json()["id"] == audit["id"]  # also after it finished
    assert audit["state"] == "finished" and len(client.provider.requests) == 2 and client.get(f"{API}/audits").json()["total"] == 1
    view = get(client, audit, "/summary")
    assert view["backlinks"]["available"] and 0 < view["backlinks"]["cost_usd"] <= total
    assert view["backlinks"]["cost_usd"] == client.ledger.spent_today() and "spent or reserved" in view["backlinks"]["spent_line"]

    # The same figures again come from the cache: zero new cost, the data's age shown, nothing to confirm, nothing sent.
    again = plan(client, backlinks=True)
    assert again["paid"]["total_usd"] == 0 and not again["needs_confirmation"] and again["can_start"]
    assert [c["state"] for c in again["paid"]["calls"]] == ["cached", "cached"] and all(c["cache_age_s"] is not None for c in again["paid"]["calls"])
    error(client.post(f"{API}/plans/{again['id']}/confirm", json={"approved_max_usd": 0}), 409, "nothing_to_confirm")
    start(client, again)
    assert len(client.provider.requests) == 2


@pytest.mark.usefixtures("confirm_every_paid_plan")
def test_changed_options_or_an_old_plan_need_a_fresh_plan_and_confirmation(web):
    client = web()
    made = confirm(client, plan(client, backlinks=True))
    other = plan(client, backlinks=True, mode="standard")
    assert other["id"] != made["id"] and other["fingerprint"] != made["fingerprint"] and other["confirmation"] is None
    error(client.post(f"{API}/audits", json={"plan_id": other["id"]}), 402, "confirmation_required")  # one consent, one plan
    client.app.state.store._run("UPDATE plans SET expires_at = '2020-01-01T00:00:00+00:00' WHERE id = ?", (made["id"],))
    assert client.get(f"{API}/plans/{made['id']}").json()["expired"]
    error(client.post(f"{API}/audits", json={"plan_id": made["id"]}), 410, "plan_expired")
    error(client.post(f"{API}/plans/{other['id']}/confirm", json={"approved_max_usd": 1.0}), 422, "amount_mismatch")
    client.app.state.store._run("UPDATE plans SET expires_at = '2020-01-01T00:00:00+00:00' WHERE id = ?", (other["id"],))
    error(client.post(f"{API}/plans/{other['id']}/confirm", json={"approved_max_usd": other["paid"]["total_usd"]}), 410, "plan_expired")
    assert client.site.requests == [] and client.provider.requests == []


@pytest.mark.usefixtures("confirm_every_paid_plan")
def test_a_zero_cost_plan_does_not_turn_into_a_paid_one_when_the_cache_goes(web, tmp_path):
    client = web()
    start(client, confirm(client, plan(client, backlinks=True)))
    free = plan(client, backlinks=True)
    assert free["paid"]["total_usd"] == 0 and len(client.provider.requests) == 2
    os.remove(tmp_path / "paid" / CACHE_NAME)  # the saved figures are gone after the plan was shown
    changed = error(client.post(f"{API}/audits", json={"plan_id": free["id"]}), 409, "plan_changed")
    assert changed["details"]["new_total_usd"] > 0 and len(client.provider.requests) == 2
    fresh = plan(client, backlinks=True)
    assert fresh["needs_confirmation"] and fresh["paid"]["total_usd"] > 0


@pytest.mark.usefixtures("confirm_every_paid_plan")
def test_the_daily_cap_is_two_dollars_shared_with_the_command_line_and_cannot_be_set(web, tmp_path):
    assert paid.daily_cap() == 2.00  # as configured for this test; the request cannot change it
    client = web()
    error(client.post(f"{API}/plans", json={"url": SHOP, "backlinks": True, "daily_cap_usd": 50}), 422, "invalid_request")
    captured = {}
    real = paid.dfs.DataForSEOClient

    class Spy(real):
        def __init__(self, *args, **kwargs):
            captured.update(kwargs)
            super().__init__(*args, **kwargs)
    paid.dfs.DataForSEOClient = Spy
    try:
        made = confirm(client, plan(client, backlinks=True))
        start(client, made)
    finally:
        paid.dfs.DataForSEOClient = real
    assert captured["daily_budget"] == 2.00 and captured["approved_usd"] == made["paid"]["total_usd"]
    assert captured["approved_always_ask"] is True

    # The command line writes to the same ledger file: what it reserves, the web app can no longer spend.
    client.ledger.reserve("/v3/backlinks/summary/live", "cli.example", "from-the-cli", 1.94, 2.00)
    budget = client.get(f"{API}/budget").json()
    assert budget["spent_today_usd"] == pytest.approx(1.94 + captured_cost(client), abs=1e-6) and budget["remaining_today_usd"] < 0.06
    assert plan(client, CAFE, backlinks=True)["paid"]["budget"]["spent_today_usd"] == budget["spent_today_usd"]


def captured_cost(client):
    return sum(row["cost"] or 0 for row in client.ledger.calls() if row["audit_id"] != "from-the-cli")


def test_budget_reservations_are_atomic_between_concurrent_callers(tmp_path):
    """Two callers (say the CLI and the web app) each try to reserve the last of today's allowance: one gets it."""
    ledger_path = tmp_path / LEDGER_NAME
    Ledger(ledger_path).reserve("/v3/backlinks/summary/live", "a.example", "earlier", 1.90, 2.00)
    results, gate = [], threading.Barrier(8)

    def reserve(n):
        gate.wait()
        try:
            Ledger(ledger_path).reserve("/v3/backlinks/summary/live", f"{n}.example", f"caller-{n}", 0.06, 2.00)
            results.append("reserved")
        except BudgetExceeded:
            results.append("refused")
    threads = [threading.Thread(target=reserve, args=(n,)) for n in range(8)]
    [thread.start() for thread in threads]
    [thread.join() for thread in threads]
    assert sorted(results) == ["refused"] * 7 + ["reserved"] and Ledger(ledger_path).spent_today() == 1.96


@pytest.mark.usefixtures("confirm_every_paid_plan")
def test_daily_limit_account_credit_unknown_balance_and_missing_credentials_are_four_different_things(web, tmp_path):
    def no_credit(request):
        return httpx.Response(200, json={"status_code": 20000, "status_message": "Ok.", "cost": 0, "tasks": [
            {"status_code": 40210, "status_message": "Insufficient Funds.", "cost": 0, "result": None}]})
    client = web(provider=Provider(no_credit))
    audit = start(client, confirm(client, plan(client, backlinks=True)))
    assert audit["state"] == "finished" and audit["outcome"]["code"] == "INCOMPLETE"  # the technical audit is untouched
    view = get(client, audit, "/summary")["backlinks"]
    assert not view["available"] and view["cost_usd"] == 0 and [c["refusal"]["code"] for c in view["checks"]] == ["provider_credits_insufficient", "not_requested_no_credit"]
    assert client.provider.requests == ["/v3/backlinks/summary/live"]  # refused for no credit once: the second call was not sent (DECISIONS 180)
    message = view["checks"][0]["summary"]
    assert message.startswith("DataForSEO account credits are insufficient") and "not Maya's daily limit" in message and "never buys credit" in message
    assert all(c["data"] is None for c in view["checks"])  # unavailable, not "zero backlinks"

    client.ledger.reserve("/v3/backlinks/summary/live", "earlier.example", "earlier", 1.98, 2.00)
    capped = plan(client, backlinks=True)
    assert capped["paid"]["blocked"]["code"] == "daily_limit_reached" and not capped["needs_confirmation"] and not capped["can_start"]
    limit = capped["paid"]["blocked"]["message"]
    assert limit.startswith("Daily spending limit reached") and "midnight UTC" in limit and "without backlinks" in limit
    assert "credit" not in limit.lower() and "buy" not in limit.lower()
    before = len(client.provider.requests)
    error(client.post(f"{API}/plans/{capped['id']}/confirm", json={"approved_max_usd": capped["paid"]["total_usd"]}), 409, "daily_limit_reached")
    error(client.post(f"{API}/audits", json={"plan_id": capped["id"]}), 409, "daily_limit_reached")
    assert len(client.provider.requests) == before and client.ledger.spent_today() == 1.98
    assert start(client, plan(client))["state"] == "finished"  # without backlinks it still runs

    budget = client.get(f"{API}/budget").json()
    assert budget["provider_balance"]["known"] is False and "unknown" in budget["provider_balance"]["message"]
    assert len(client.provider.requests) == before  # reading the budget asks nobody


def test_the_balance_is_fetched_when_a_paid_plan_is_built_or_on_request_through_the_engines_client(web, monkeypatch):
    """The rule since DECISIONS 180 (it was "only on request"): one free request by itself when a plan with paid data is
    built, reused for ten minutes; never for a plan with nothing paid, and never without credentials. More in
    tests/test_market_and_balance.py."""
    monkeypatch.setattr(paid, "AUTOMATIC_BALANCE", True)  # the rule as it ships (tests/conftest.py switches it off for the other tests)

    def respond(request):
        if request.url.path == "/v3/appendix/user_data":
            return httpx.Response(200, json={"status_code": 20000, "cost": 0, "tasks": [{"status_code": 20000, "cost": 0, "result": [
                {"login": SECRETS[0], "money": {"balance": 12.5, "total": 50}}]}]})
        return demo._backlinks(request)
    client = web(provider=Provider(respond))
    assert client.get(f"{API}/budget").json()["provider_balance"]["known"] is False and client.provider.requests == []  # reading the budget asks nobody
    assert plan(client)["paid"]["provider_balance"]["known"] is False and client.provider.requests == []  # nor does a plan with nothing paid
    made = plan(client, backlinks=True)
    assert client.provider.requests == ["/v3/appendix/user_data"] and made["paid"]["provider_balance"]["balance_usd"] == 12.5 and made["balance_warning"] is None
    plan(client, backlinks=True)
    assert client.provider.requests == ["/v3/appendix/user_data"]  # reused: a second plan inside ten minutes asks nobody
    fresh = client.post(f"{API}/budget/provider-balance", json={}).json()  # the button asks at once
    assert fresh["known"] and fresh["balance_usd"] == 12.5 and client.provider.requests == ["/v3/appendix/user_data"] * 2
    assert client.get(f"{API}/budget").json()["provider_balance"]["balance_usd"] == 12.5 and client.ledger.spent_today() == 0
    assert {row["event"] for row in client.ledger.calls()} == {"free"}  # recorded as the free calls they are
    assert not any(secret in json.dumps([fresh, made, client.get(f"{API}/budget").json()]) for secret in SECRETS)
    without = web(credentials=False, folder=client.app.state.store.folder.parent / "none")
    assert without.post(f"{API}/budget/provider-balance", json={}).json()["code"] == "credentials_not_configured"
    made = plan(without, backlinks=True)
    assert made["paid"]["blocked"]["code"] == "credentials_not_configured" and made["paid"]["blocked"]["message"].startswith("Credentials are not configured")
    error(without.post(f"{API}/audits", json={"plan_id": made["id"]}), 409, "credentials_not_configured")
    assert without.provider.requests == [] and without.site.requests == []


@pytest.mark.parametrize("failure", ["server_error", "timeout"])
def test_a_failed_paid_call_is_counted_never_retried_and_leaves_the_audit_whole(web, failure):
    def respond(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("made up")
        return httpx.Response(503, text="unavailable")
    client = web(provider=Provider(respond))
    made = confirm(client, plan(client, backlinks=True))
    audit = start(client, made)
    assert audit["state"] == "finished" and audit["paid"]["state"] == "done" and len(client.provider.requests) == 2  # one per call, no retry
    view = get(client, audit, "/summary")
    assert view["counts"]["pages_checked"] == 49 and view["top"]  # pages read: the demo's one error page is not one (289)
    backlinks = view["backlinks"]
    assert not backlinks["available"] and {c["refusal"]["code"] for c in backlinks["checks"]} == {"possibly_billed"}
    assert backlinks["cost_usd"] == pytest.approx(made["paid"]["total_usd"]) == client.ledger.spent_today()
    assert {c["billing_status"] for c in backlinks["calls"]} == {"possibly_billed"}
    assert "may still have been charged" in backlinks["checks"][0]["summary"]


@pytest.mark.usefixtures("confirm_every_paid_plan")
def test_refusal_reasons_are_read_from_the_engines_own_messages(tmp_path):
    """The wording comes from maya_audit.dataforseo; if it changes there, this says so."""
    from maya_audit.dataforseo import panel

    def refusal_for(responder=None, approved=1.0, reserve=0.0, credentials=True, stop=False):
        ledger = Ledger(tmp_path / f"ledger-{len(list(tmp_path.iterdir()))}" / LEDGER_NAME)
        if reserve:
            ledger.reserve("/v3/backlinks/summary/live", "x.example", "x", reserve, 2.0)
        services = paid.PaidServices(lambda: Credentials("a-login", "a-password") if credentials else None,
                                     lambda: (ledger, None), httpx.MockTransport(responder or demo._backlinks))
        client = paid.open_client(services, approved_usd=approved, audit_id="t", should_stop=(lambda: True) if stop else None)
        try:
            result = panel.run_checks(panel.audit_plan("https://www.example.com/")[:1], client)
        finally:
            client.close()
        refusal = paid.describe(result, services)["checks"][0]["refusal"]
        return refusal and refusal["code"]

    def code(number):
        return lambda r: httpx.Response(200, json={"status_code": 20000, "cost": 0, "tasks": [
            {"status_code": number, "status_message": "refused", "cost": 0, "result": None}]})

    def timeout(request):
        raise httpx.ReadTimeout("made up")

    def dropped(request):
        raise httpx.ReadError("made up")

    assert refusal_for() is None
    assert refusal_for(reserve=1.99) == "daily_limit_reached"
    assert refusal_for(code(40200)) == refusal_for(code(40210)) == "provider_credits_insufficient"
    assert refusal_for(code(40204)) == "provider_subscription_missing"
    assert refusal_for(credentials=False) == "credentials_not_configured"
    assert refusal_for(approved=0.001) == "confirmation_required"
    assert refusal_for(timeout) == refusal_for(dropped) == refusal_for(lambda r: httpx.Response(503, text="down")) == "possibly_billed"
    assert refusal_for(stop=True) == "stopped"
    assert refusal_for(code(50000)) == "provider_error"


# -- jobs: queue, progress, stop, resume, restart --------------------------------------------------

def test_one_audit_runs_at_a_time_and_the_rest_wait_in_a_bounded_queue(web):
    site = Site(pause_at=8)
    client = web(site=site)
    first = start(client, plan(client), wait=False)
    assert site.reached.wait(10)
    waiting = [start(client, plan(client, CAFE), wait=False) for _ in range(5)]
    assert get(client, first)["state"] == "running" and {get(client, a)["state"] for a in waiting} == {"queued"}
    assert all(step["status"] in ("pending", "skipped") for step in get(client, waiting[0])["timeline"])
    error(client.post(f"{API}/audits", json={"plan_id": plan(client, CAFE)["id"]}), 429, "queue_full")
    seen = len(site.requests)
    stopped = client.post(f"{API}/audits/{waiting[0]['id']}/stop", json={}).json()
    assert stopped["state"] == "stopped" and len(site.requests) == seen  # stopped before it started: nothing requested
    error(client.delete(f"{API}/audits/{first['id']}"), 409, "audit_running")
    site.release.set()
    for audit in waiting[1:]:
        assert client.app.state.runner.wait(audit["id"], 60)["state"] == "finished"
    assert get(client, first)["state"] == "finished" and get(client, waiting[0])["state"] == "stopped"
    order = [row["id"] for row in client.get(f"{API}/audits", params={"status": "finished", "limit": 100}).json()["audits"]]
    assert set(order) == {first["id"], *(a["id"] for a in waiting[1:])}


def test_progress_comes_from_the_engine_with_real_counters_and_marks_skipped_steps(web):
    client = web()
    audit = audit_of(client)
    assert audit["state"] == "finished" and audit["outcome"]["code"] == "INCOMPLETE" and audit["outcome"]["crawl_stop"] == "page_cap"
    steps = {step["step"]: step for step in audit["timeline"]}
    assert list(steps) == ["access", "sitemap", "crawling", "rendering", "checks", "backlinks", "report"]
    assert {name: s["status"] for name, s in steps.items()} == {
        "access": "done", "sitemap": "done", "crawling": "done", "rendering": "skipped", "checks": "done",
        "backlinks": "skipped", "report": "done"}
    assert steps["rendering"]["reason"] and steps["backlinks"]["reason"] == strings.t("step.skipped.backlinks")
    report = client.get(f"{API}/audits/{audit['id']}/result").json()
    counters = audit["counters"]
    assert counters["pages_checked"] == report["page_counts"]["pages_checked"] == 50 and counters["page_cap"] == 50
    assert counters["redirects"] == report["page_counts"]["redirects"] and counters["requests_sent"] == len(report["crawl"]["requests"])
    assert "not the size of the site" in counters["page_cap_note"] and audit["eta"] == {"kind": "none", "label": None}
    assert audit["elapsed_s"] is not None and audit["current_url"] is None


def test_events_are_ordered_versioned_bounded_and_replayable(web):
    client = web()
    audit = audit_of(client, mode="standard")
    rows = sse(client.get(f"{API}/audits/{audit['id']}/events", headers={"last-event-id": "0"}).text)
    names = [name for _, name, _ in rows]
    assert names[0] == "snapshot" and names[-1] == "end" and rows[0][2]["audit"]["id"] == audit["id"]
    stored = rows[1:-1]
    ids = [event_id for event_id, _, _ in stored]
    assert ids == sorted(ids) and len(set(ids)) == len(ids) and all(data["v"] == 1 and data["ts"] for _, _, data in stored)
    assert {"state", "step", "progress", "log", "done"} <= set(names)
    assert [d["step"] for _, n, d in stored if n == "step"][:3] == ["access", "sitemap", "crawling"]
    done = [d for _, n, d in stored if n == "done"][0]
    assert done == {**done, "state": "finished", "outcome": "INCOMPLETE", "pages_checked": 500}
    progress = [d for _, n, d in stored if n == "progress"]
    assert progress and progress == sorted(progress, key=lambda d: d["pages_checked"]) and progress[-1]["page_cap"] == 500
    # Routine progress never carries page bodies or the report: every event is small, and their number is capped.
    assert max(len(json.dumps(d)) for _, _, d in stored) < 2000 and len(stored) <= MAX_EVENTS
    assert "<html" not in json.dumps(stored).lower() and "Walnut desk organiser" not in json.dumps(stored)
    # Reconnecting after event N gives a fresh snapshot, then only what came after N.
    middle = ids[len(ids) // 2]
    again = sse(client.get(f"{API}/audits/{audit['id']}/events", headers={"last-event-id": str(middle)}).text)
    assert again[0][1] == "snapshot" and [i for i, _, _ in again[1:-1]] == [i for i in ids if i > middle]
    fresh = sse(client.get(f"{API}/audits/{audit['id']}/events").text)  # no Last-Event-ID: the snapshot is enough
    assert [name for _, name, _ in fresh] == ["snapshot", "end"] and fresh[0][0] == ids[-1]
    error(client.get(f"{API}/audits/{'0' * 32}/events"), 404, "audit_not_found")


def test_a_live_stream_sends_a_snapshot_and_heartbeats_while_the_site_is_slow(web):
    site = Site(pause_at=6)
    client = web(site=site, heartbeat_s=0.25)
    audit = start(client, plan(client), wait=False)
    assert site.reached.wait(10)
    stream = client.app.state.stream(audit["id"], None)
    seen = []
    for chunk in stream:
        seen.append(chunk)
        if chunk.startswith(": heartbeat") or len(seen) > 400:
            break
    assert seen[0] == "retry: 2000\n\n" and "event: snapshot" in seen[1] and seen[-1] == ": heartbeat\n\n"
    live = get(client, audit)
    assert live["state"] == "running" and live["eta"]["kind"] in ("calculating", "estimate", "unknown", "waiting")
    assert live["counters"]["pages_checked"] < 50 and live["timeline"][2]["status"] in ("active", "pending")
    site.release.set()
    rest = list(stream)
    assert "event: end" in rest[-1] and client.app.state.runner.wait(audit["id"], 60)["state"] == "finished"


@pytest.mark.usefixtures("confirm_every_paid_plan")
def test_stop_keeps_what_was_read_and_resume_needs_its_own_approval_before_it_spends(web):
    site = Site(pause_at=14)
    client = web(site=site)
    audit = start(client, confirm(client, plan(client, backlinks=True)), wait=False)
    assert site.reached.wait(10)
    stopping = client.post(f"{API}/audits/{audit['id']}/stop", json={}).json()
    assert stopping["state"] == "stopping" and not stopping["can_stop"] and "nothing new is started" in stopping["note"]
    error(client.post(f"{API}/audits/{audit['id']}/stop", json={}), 409, "audit_not_running")
    site.release.set()
    stopped = get(client, client.app.state.runner.wait(audit["id"], 30))
    assert stopped["state"] == "stopped" and stopped["can_resume"] and 0 < stopped["counters"]["pages_checked"] < 50
    # The job's lifecycle is "stopped"; the audit's own outcome is the engine's, and it is not "complete".
    assert stopped["outcome"]["code"] == "INCOMPLETE" and stopped["outcome"]["crawl_stop"] == "stopped" and "stopped on request" in stopped["outcome"]["reason"]
    assert client.provider.requests == [] and client.ledger.calls() == []  # nothing is paid for on a stopped audit
    partial = get(client, audit, "/summary")
    assert partial["outcome"]["resumable"] and not partial["outcome"]["complete"]
    assert partial["backlinks"]["available"] is False and "not been requested yet" in partial["backlinks"]["unavailable_reason"]
    seen_before = set(site.requests)

    preview = client.post(f"{API}/audits/{audit['id']}/resume-plan", json={}).json()
    assert preview["resumable"] and preview["pages_saved"] == stopped["counters"]["pages_checked"]
    assert preview["pages_left"] == 50 - preview["pages_saved"] and preview["continues_from_saved_crawl"]
    assert preview["paid"]["pending"] and preview["paid"]["needs_confirmation"] and preview["paid"]["total_usd"] > 0
    assert len(site.requests) == len(seen_before) and client.provider.requests == []  # a resume plan requests nothing
    error(client.post(f"{API}/audits/{audit['id']}/resume", json={}), 402, "confirmation_required")
    error(client.post(f"{API}/audits/{audit['id']}/resume", json={"approved_max_usd": 1.5}), 402, "confirmation_required")
    assert get(client, audit)["state"] == "stopped" and client.provider.requests == []

    resumed = client.post(f"{API}/audits/{audit['id']}/resume", json={"approved_max_usd": preview["paid"]["total_usd"]})
    assert resumed.status_code == 200 and resumed.json()["state"] in ("queued", "running")
    done = get(client, client.app.state.runner.wait(audit["id"], 60))
    assert done["state"] == "finished" and done["sessions"] == 2 and done["counters"]["pages_checked"] == 50
    report = client.get(f"{API}/audits/{audit['id']}/result").json()
    assert report["page_counts"]["pages_checked"] == 50 and len(report["crawl"]["sessions"]) == 2
    # Earlier pages are not read again: the second sitting's page requests fit in what was left of the limit
    # (a few more are redirect hops; the checks after the crawl fetch a small sample of their own under other purposes).
    second_sitting = [r for r in report["crawl"]["requests"] if r["purpose"] == "page"]
    assert 0 < len(second_sitting) <= preview["pages_left"] + report["page_counts"]["redirects"] + 1
    view = get(client, audit, "/summary")
    assert "2 sittings" in view["coverage"]["resumed_note"] and view["backlinks"]["available"] and len(client.provider.requests) == 2
    error(client.post(f"{API}/audits/{audit['id']}/resume", json={}), 409, "audit_not_resumable")
    after = client.post(f"{API}/audits/{audit['id']}/resume-plan", json={}).json()
    assert not after["resumable"] and after["paid"]["note"] == strings.t("paid.resume.done")


@pytest.mark.parametrize("pause_at", [1, 2, 3])
def test_a_stop_before_the_first_page_was_read_loses_nothing_on_resume(web, pause_at):
    # Stopped while robots.txt (1), the sitemap (2) or the homepage itself (3) was being requested.
    site = Site(pause_at=pause_at, respond=cloudflare)
    client = web(site=site)
    audit = start(client, plan(client), wait=False)
    assert site.reached.wait(15)
    client.post(f"{API}/audits/{audit['id']}/stop", json={})
    site.release.set()
    assert get(client, client.app.state.runner.wait(audit["id"], 30))["state"] == "stopped"
    assert client.post(f"{API}/audits/{audit['id']}/resume", json={}).status_code == 200
    done = get(client, client.app.state.runner.wait(audit["id"], 60))
    report = client.get(f"{API}/audits/{audit['id']}/result").json()
    # The homepage is fetched in the second sitting and judged for what it is: blocked, not skipped and not a lost request.
    assert [(p["status"], p["fetch_class"], p["discovered_via"]) for p in report["crawl"]["pages"]] == [(403, "blocked", "start")]
    assert done["outcome"]["code"] == "DEGRADED" and get(client, audit, "/summary")["blocked"]["name"] == "Cloudflare"


@pytest.mark.usefixtures("confirm_every_paid_plan")
def test_a_restart_marks_unfinished_audits_interrupted_and_restarts_nothing(web, tmp_path):
    folder = tmp_path / "durable"
    site = Site(pause_at=10)
    client = web(site=site, folder=folder)
    audit = start(client, confirm(client, plan(client, backlinks=True)), wait=False)
    queued = start(client, plan(client, CAFE), wait=False)
    assert site.reached.wait(10)
    with pytest.raises(WorkerAlreadyRunning):  # a second copy of the app on the same folder is refused, not doubled
        create_app(folder, engine=client.app.state.engine, port=8770)
    site.release.set()
    web.close(client)  # shutdown asks the running audit to stop politely
    store = Store(folder)
    assert store.audit(audit["id"])["state"] == "stopped" and 0 < store.audit(audit["id"])["progress"]["pages_checked"] < 50
    # Put the rows back the way a crash (no polite stop) leaves them.
    store.update_audit(audit["id"], state="running", finished_at=None)
    store.update_audit(queued["id"], state="queued", finished_at=None)
    store.close()

    second_site = Site()
    second = web(site=second_site, folder=folder)
    assert second.get(f"{API}/settings").json()["audits_recovered_at_startup"] == 2
    time.sleep(0.8)  # long enough for a worker to have picked something up, had it been going to
    for row in (audit, queued):
        seen = get(second, row)
        assert seen["state"] == "interrupted" and seen["can_resume"] and "Nothing restarts by itself" in seen["state_note"]
    assert second_site.requests == [] and second.provider.requests == []
    preview = second.post(f"{API}/audits/{audit['id']}/resume-plan", json={}).json()
    assert preview["resumable"] and preview["paid"]["needs_confirmation"]
    assert second.post(f"{API}/audits/{audit['id']}/resume", json={"approved_max_usd": preview["paid"]["total_usd"]}).status_code == 200
    done = get(second, second.app.state.runner.wait(audit["id"], 60))
    assert done["state"] == "finished" and done["counters"]["pages_checked"] == 50 and done["has_report"]
    assert len(second.provider.requests) == 2


def test_an_interrupted_paid_request_is_not_sent_again(web, tmp_path):
    folder = tmp_path / "paid-crash"
    client = web(folder=folder)
    audit = audit_of(client)
    web.close(client)
    store = Store(folder)  # as if the app died after marking the paid step begun and before any answer was saved
    store._run("UPDATE audits SET backlinks = 1, paid_state = 'attempted', state = 'running' WHERE id = ?", (audit["id"],))
    store.close()
    second = web(folder=folder)
    preview = second.post(f"{API}/audits/{audit['id']}/resume-plan", json={}).json()
    assert preview["resumable"] and not preview["paid"]["needs_confirmation"] and "may have been charged" in preview["paid"]["note"]
    assert second.post(f"{API}/audits/{audit['id']}/resume", json={}).status_code == 200
    done = get(second, second.app.state.runner.wait(audit["id"], 60))
    view = get(second, done, "/summary")
    assert done["state"] == "finished" and second.provider.requests == []
    assert view["backlinks"]["available"] is False and "was not sent again" in view["backlinks"]["unavailable_reason"]


def test_resume_refuses_settings_that_no_longer_match_the_saved_crawl(web):
    site = Site(pause_at=12)
    client = web(site=site)
    audit = start(client, plan(client), wait=False)
    assert site.reached.wait(10)
    client.post(f"{API}/audits/{audit['id']}/stop", json={})
    site.release.set()
    client.app.state.runner.wait(audit["id"], 30)
    seen = len(site.requests)
    client.app.state.store._run("UPDATE audits SET key_pages = ? WHERE id = ?", (json.dumps([f"http://{SHOP}/about"]), audit["id"]))
    assert client.post(f"{API}/audits/{audit['id']}/resume", json={}).status_code == 200
    failed = get(client, client.app.state.runner.wait(audit["id"], 30))
    assert failed["state"] == "failed" and failed["error"]["code"] == "resume_mismatch" and "differ from the saved crawl" in failed["error"]["message"]
    assert len(site.requests) == seen and not failed["can_resume"]  # refused before any request


def test_complete_incomplete_and_degraded_are_the_engines_outcomes_not_the_jobs(web):
    client = web()
    complete = audit_of(client, CAFE)
    assert (complete["state"], complete["outcome"]["code"]) == ("finished", "COMPLETED") and get(client, complete, "/summary")["outcome"]["complete"]
    incomplete = audit_of(client, SHOP)
    view = get(client, incomplete, "/summary")
    assert (incomplete["state"], incomplete["outcome"]["code"]) == ("finished", "INCOMPLETE") and not view["outcome"]["complete"]
    assert view["outcome"]["note"] == strings.t("result.partial_note") and view["coverage"]["not_fetched"] > 0

    def blocked(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n", headers={"content-type": "text/plain"})
        return httpx.Response(403, text="<html><title>Just a moment...</title><body>Checking your browser. cf-chl</body></html>",
                              headers={"content-type": "text/html", "server": "cloudflare", "cf-mitigated": "challenge"})
    walled = web(site=Site(respond=blocked), folder=client.app.state.store.folder.parent / "blocked")
    degraded = audit_of(walled, SHOP)
    assert degraded["state"] == "finished" and degraded["outcome"]["code"] == "DEGRADED"  # a report was written; the audit is not fine
    seen = get(walled, degraded, "/summary")
    assert seen["outcome"]["label"] == "The site could not be read properly" and not seen["outcome"]["complete"]
    assert any(gate["check_id"] == "INT-1" and gate["state"] != "ok" for gate in seen["gates"])
    assert seen["counts"]["not_checked"] > 0 and seen["counts"]["problems"] <= 2  # nothing is passed off as clean

    def broken(request):
        raise RuntimeError("secret path /Users/someone/private and a page dump")
    crashed = web(site=Site(respond=broken), folder=client.app.state.store.folder.parent / "crash")
    failed = audit_of(crashed, SHOP)
    assert failed["state"] in ("failed", "finished")
    assert "/Users/someone" not in json.dumps(failed) and "page dump" not in json.dumps(failed)


# -- results ---------------------------------------------------------------------------------------

@pytest.fixture
def standard(web):
    client = web(citations=True)
    # DECISIONS 331: read in the crawl's own order ("Tam tarama sırası"), as these 500-page scenarios were written for
    made = confirm(client, plan(client, mode="standard", crawl_order=True, backlinks=True, key_pages=["/tr/", "/tr/urun-7", "/app", "/item/13"]))
    audit = start(client, made)
    return client, audit, client.get(f"{API}/audits/{audit['id']}/result").json()


def test_a_500_page_audit_of_english_and_turkish_pages_is_shown_from_its_report(standard):
    client, audit, report = standard
    assert audit["state"] == "finished" and report["page_counts"]["pages_checked"] == 500 and report["schema_version"] == "1.31"
    view = get(client, audit, "/summary")
    counts = view["counts"]
    # Severity counts are the report's own findings, counted; nothing is added or re-judged.
    by_severity = {}
    for check in report["checks"]:
        for finding in check["findings"]:
            by_severity[finding["severity"]] = by_severity.get(finding["severity"], 0) + 1
    assert counts["by_severity"] == {level: by_severity.get(level, 0) for level in ("S1", "S2", "S3", "S4", "Info")}
    assert counts["problems"] + counts["notes"] == counts["findings_total"] == len(report["findings_in_priority_order"])
    assert [row["id"] for row in view["top"]] == report["findings_in_priority_order"][:5] and view["more_findings"] == counts["findings_total"] - 5
    # The demo's sitemap-listed noindex page is S3 plus a separate S2 sitemap conflict since H26 (intent unknown), so the
    # first action is the worst finding the report puts first, whatever its level.
    first = next(f for c in report["checks"] for f in c["findings"] if f["id"] == report["findings_in_priority_order"][0])
    assert view["first_action"]["id"] == first["id"] and view["first_action"]["severity"] == first["severity"] in ("S1", "S2")
    # The answer-engine panel has findings of its own here; they stay in their panel and out of the site counts.
    ans = [c for c in report["answer_engine_panel"] if c["findings"]]
    assert ans and view["answers"]["assessed"] and sum(c["findings"] for c in view["answers"]["checks"]) == sum(len(c["findings"]) for c in ans)
    assert not any(row["check_id"].startswith("ANS") for row in get(client, audit, "/findings", limit=100)["items"])
    assert "not a visibility score" in view["answers"]["note"]
    assert view["rendering"] == {**view["rendering"], "available": False, "mode": "raw_html_only"} and view["rendering"]["reason"]
    assert view["coverage"]["not_fetched"] == len(report["crawl"]["not_fetched_urls"]) > 0 and "not proof about every page" in view["coverage"]["sampled_note"]
    assert any(gap["whole_check"] for gap in view["coverage"]["gaps"]) and any(not gap["whole_check"] for gap in view["coverage"]["gaps"])
    # No brand was typed: the cover shows the site's own name, read from its page titles, and says so (DECISIONS 201).
    assert view["backlinks"]["available"] and view["brand"] == {"name": "Demo Shop", "confirmed": False, "country": None,
                                                                "label": strings.t("result.brand.from_site", source=strings.t("result.brand.source.title"))}
    assert report["brand"] == {"name": "Demo Shop", "source": "site", "confirmed": False, "found_in": "title", "pages": report["brand"]["pages"]}
    # The results card stays small however large the report (here several MB) is. It holds, for each page with a problem,
    # what is wrong on that page (schema 1.10: `problem_summary.by_page[].items` and `practical.by_page.rows[].lines`).
    # Every check, gate and coverage gap also carries its title and sentence as the reader is shown them (`*_shown`).
    assert len(json.dumps(view)) < 215_000
    assert len(json.dumps(report)) > 1_000_000
    titles = " ".join(row["title"] for row in get(client, audit, "/findings", limit=100)["items"])
    assert "noindex" in titles and "meta description(s) are shared" in titles and "title(s) are shared" in titles
    # Text from the site is carried as text. A shared title is STR-1's finding only (DECISIONS 187): its title holds a
    # count, and the site's own words are in its evidence and in the line of each page that shares the title.
    shared = next(f for c in report["checks"] if c["check_id"] == "STR-1" for f in c["findings"] if "title(s) are shared" in f["title"])
    assert '<script>alert("maya")</script>' in json.dumps(shared["evidence"], ensure_ascii=False).replace('\\"', '"')
    assert not [f for c in report["checks"] if c["check_id"] == "IDX-8" for f in c["findings"] if "share the title" in f["title"]]
    lines = [line for row in view["practical"]["by_page"]["rows"] for line in row["lines"]]
    assert any('<script>alert("maya")</script>' in line for line in lines), lines[:5]
    evidence_index = json.loads((client.app.state.runner.artifacts(audit["id"]) / "evidence" / "index.json").read_text(encoding="utf-8"))
    turkish = next(n for n, row in enumerate(evidence_index["pages"], 1) if "urun-7" in row["url"])
    assert "Ceviz masa düzenleyici 7" in json.dumps(get(client, audit, f"/evidence/page-{turkish}")["record"], ensure_ascii=False)
    saved = report["evidence_saved"]
    assert saved["folder"] == "evidence" and saved["pages"] == 500 and saved["not_saved"] == report["page_counts"]["redirects"]


def test_findings_are_filtered_and_paged_and_every_affected_page_is_reachable(standard):
    client, audit, report = standard
    everything = get(client, audit, "/findings", limit=100)
    assert everything["total"] == everything["all_findings"] == len(report["findings_in_priority_order"])
    assert [row["id"] for row in everything["items"]] == report["findings_in_priority_order"]
    pages = [get(client, audit, "/findings", limit=7, offset=offset)["items"] for offset in range(0, everything["total"], 7)]
    assert [row["id"] for page in pages for row in page] == report["findings_in_priority_order"]
    critical = get(client, audit, "/findings", severity="S1,S2")
    assert critical["total"] and {row["severity"] for row in critical["items"]} <= {"S1", "S2"}
    assert {row["area"] for row in get(client, audit, "/findings", area="STR", limit=100)["items"]} == {"STR"}
    assert all("noindex" in row["title"].lower() + row["fix"].lower() for row in get(client, audit, "/findings", q="noindex")["items"])
    assert {row["check_id"] for row in get(client, audit, "/findings", check_id="str-16")["items"]} == {"STR-16"}
    error(client.get(f"{API}/audits/{audit['id']}/findings", params={"severity": "S9"}), 422, "invalid_request")
    by_id = {f["id"]: f for check in report["checks"] for f in check["findings"]}
    for row in everything["items"]:  # each row repeats the report's own decisions
        source = by_id[row["id"]]
        assert (row["severity"], row["confidence"], row["title"], row["fix"]) == (
            source["severity"], source["confidence"], source["title"], source["how_to_fix"])
        assert row["estimates"]["owner"] in catalog.OWNERS and row["estimates"]["effort"] in catalog.EFFORTS and "estimates" in row["estimates"]["label"]
    # A finding with more pages than the report keeps (25): all of them can be paged through and searched.
    big = max(everything["items"], key=lambda row: row["pages_total"])
    assert big["pages_total"] > 25 and len(by_id[big["id"]]["scope"]["urls"]) == 25
    collected, offset = [], 0
    while True:
        chunk = get(client, audit, f"/findings/{big['id']}/pages", limit=40, offset=offset)
        collected += chunk["pages"]
        offset += 40
        if offset >= chunk["total"]:
            break
    assert chunk["complete"] and chunk["all_pages"] == big["pages_total"] == len(collected) == len(set(collected))
    assert collected[:25] == by_id[big["id"]]["scope"]["urls"]
    needle = collected[-1].rsplit("/", 1)[-1]
    assert collected[-1] in get(client, audit, f"/findings/{big['id']}/pages", q=needle)["pages"]
    error(client.get(f"{API}/audits/{audit['id']}/findings/nope/pages"), 404, "finding_not_found")


def test_the_action_plan_groups_by_severity_and_labels_its_advice_as_estimates(standard):
    client, audit, report = standard
    everyone = get(client, audit, "/action-plan")
    groups = {group["id"]: group for group in everyone["groups"]}
    assert list(groups) == ["fix_now", "fix_next", "improve_later"] and everyone["total"] == len(report["findings_in_priority_order"])
    assert {row["severity"] for row in groups["fix_now"]["items"]} <= {"S1", "S2"} and groups["fix_now"]["items"]
    assert {row["severity"] for row in groups["fix_next"]["items"]} <= {"S3"}
    assert {row["severity"] for row in groups["improve_later"]["items"]} <= {"S4", "Info"}
    notes = [row for row in groups["improve_later"]["items"] if row["severity"] == "Info"]
    assert notes and not any(row["requires_fix"] for row in notes)  # an observation is never made a mandatory fix
    assert "estimates, not measurements" in everyone["estimates_note"]
    for row in groups["fix_now"]["items"]:
        assert row["what"] and row["why"] and row["fix"] and row["pages_total"] >= 1 and row["confidence_label"] and row["sample_pages"]
        assert not re.search(r"\b(will|guarantee\w*) (rank|improve|increase)", row["why"], re.I)
    per_role = {role: get(client, audit, "/action-plan", role=role) for role in catalog.OWNERS}
    assert sum(plan_["total"] for plan_ in per_role.values()) == everyone["total"]
    assert all(row["estimates"]["owner"] == "developer" for g in per_role["developer"]["groups"] for row in g["items"])
    assert catalog.known() >= {check["check_id"] for check in report["checks"]}  # every check has its own plain note


def test_evidence_is_served_only_from_the_audits_own_registered_files(standard, tmp_path):
    client, audit, report = standard
    finding_id = report["findings_in_priority_order"][0]
    shown = get(client, audit, f"/evidence/{finding_id}")
    assert shown["kind"] == "finding" and shown["record"]["id"] == finding_id and "evidence" in shown["record"]
    page = get(client, audit, "/evidence/page-1")
    assert page["kind"] == "page" and page["url"].startswith(f"http://{SHOP}")
    for bad in ("page-0", "page-9999", "page-1x", "..%2F..%2Freport.json", "index.json", "%2e%2e", "page-1%00", "crawl.db"):
        assert client.get(f"{API}/audits/{audit['id']}/evidence/{bad}").status_code == 404, bad
    for bad_id in ("..", "%2e%2e%2f%2e%2e", "x" * 32, audit["id"].upper()):
        assert client.get(f"{API}/audits/{bad_id}/summary").status_code == 404
    for name in ("crawl.db", "report.json", "..%2Fstate%2Fcrawl.db", "json%00", "web-v1.db"):
        assert client.get(f"{API}/audits/{audit['id']}/downloads/{name}").status_code == 404

    # A file inside the evidence folder swapped for a link to somewhere else is not followed.
    folder = client.app.state.runner.artifacts(audit["id"]) / "evidence"
    index = json.loads((folder / "index.json").read_text(encoding="utf-8"))
    outside = tmp_path / "outside-secret.json"
    outside.write_text('{"secret": "must not leave"}')
    victim = folder / index["pages"][1]["file"]
    victim.unlink()
    victim.symlink_to(outside)
    error(client.get(f"{API}/audits/{audit['id']}/evidence/page-2"), 404, "evidence_not_found")
    archive = zipfile.ZipFile(io.BytesIO(client.get(f"{API}/audits/{audit['id']}/downloads/evidence").content))
    names = archive.namelist()
    assert f"evidence/{victim.name}" not in names and "evidence/index.json" in names and "affected-urls.json" in names
    assert len(names) == len(index["pages"]) - 1 + 2 and all(not name.startswith(("/", "..")) for name in names)
    assert b"must not leave" not in b"".join(archive.read(name) for name in names)


def test_downloads_are_named_safely_and_carry_no_secret_or_local_path(standard, tmp_path):
    client, audit, report = standard
    for fmt, extension in (("json", "json"), ("markdown", "md")):
        response = client.get(f"{API}/audits/{audit['id']}/downloads/{fmt}")
        assert response.status_code == 200
        assert re.fullmatch(rf'attachment; filename="maya-audit-demo-shop\.localhost-\d{{4}}-\d\d-\d\d\.{extension}"', response.headers["content-disposition"])
    assert client.get(f"{API}/audits/{audit['id']}/downloads/json").json() == report
    markdown = client.get(f"{API}/audits/{audit['id']}/downloads/markdown").text
    events = client.get(f"{API}/audits/{audit['id']}/events", headers={"last-event-id": "0"}).text
    everything = json.dumps(report) + markdown + events + json.dumps(get(client, audit, "/summary")) + json.dumps(get(client, audit, "/conversation"))
    # find() rather than "in": on a failure pytest would otherwise try to diff several megabytes of text.
    for label, text in (("report", json.dumps(report)), ("markdown", markdown), ("events", events)):
        assert text.find(str(tmp_path)) == -1, (label, text[max(0, text.find(str(tmp_path)) - 150):text.find(str(tmp_path)) + 60])
    assert [needle for needle in (*SECRETS, "Authorization", str(tmp_path), str(Path.home())) if everything.find(needle) != -1] == []
    if os.name != "nt":  # POSIX permission bits; Windows protects the profile folder with ACLs instead (docs/WEB-APP.md)
        mode = (client.app.state.runner.artifacts(audit["id"]) / "report.json").stat().st_mode & 0o777
        assert mode == 0o600 and (client.app.state.store.folder / "web-v1.db").stat().st_mode & 0o777 == 0o600


def test_pdf_markdown_and_json_agree_and_the_pdf_has_a_cover_page_numbers_turkish_and_long_addresses(standard):
    client, audit, report = standard
    client.put(f"{API}/projects/{SHOP}/profile", json={"brand_name": "Çağdaş Ceviz Atölyesi İŞ", "countries": ["Türkiye"], "key_pages": []})
    view = get(client, audit, "/summary")
    assert view["brand"] == {"name": "Çağdaş Ceviz Atölyesi İŞ", "confirmed": True, "label": None, "country": "Türkiye"}
    printable = client.get(f"{API}/audits/{audit['id']}/print?full=true")
    html = printable.text
    assert "<script" not in html and "&lt;script&gt;alert(&quot;maya&quot;)" in html  # a page title holding HTML stays text
    assert "script-src" not in printable.headers["content-security-policy"] and "<link" not in html and "<img" not in html and "src=" not in html
    for needle in ("Çağdaş Ceviz Atölyesi İŞ", "Türkiye", "Executive summary", view["headline"], view["practical"]["executive"]["problems_title"], "Problems by page", "By severity", "Top opportunities", "First five actions", "Scorecard by area",
                   "Action plan: what to do when", "This week", "Findings by area", "Every page", "What else we checked", "Technical appendix", "Sources and dates",
                   "What could not be checked",
                   "AI answer citations", "backlinks (third-party data", "How this audit was done", "Suggested owner and effort (estimates)"):
        assert needle in html, needle
    markdown = client.get(f"{API}/audits/{audit['id']}/downloads/markdown").text
    from html import escape
    for finding_id in report["findings_in_priority_order"][:12]:
        check_id, title = next((f["check_id"], f["title"]) for c in report["checks"] for f in c["findings"] if f["id"] == finding_id)
        # The three formats name the same findings: the report and the Markdown in the engine's own words, the printed
        # page in the words shown to the reader ("5 pages", not "5 page(s)").
        shown = wording.title(check_id, title)[0]
        # IDX-6's broken targets are one Markdown card with a table of targets (review CR-02); each stays its own finding.
        named = title in markdown or (check_id == "IDX-6" and "internal link targets return" in markdown)
        assert escape(shown, quote=True) in html and named and "(s)" not in shown
    assert "500 (limit 500)" in html and "500 page" in markdown

    response = client.get(f"{API}/audits/{audit['id']}/downloads/pdf?full=true")
    if response.status_code == 503:
        error(response, 503, "pdf_unavailable")
        pytest.skip("headless Chromium is not available here, so the PDF itself was not produced or inspected")
    assert response.content.startswith(b"%PDF-") and response.headers["content-disposition"].endswith('.pdf"')
    pypdf = pytest.importorskip("pypdf")
    reader = pypdf.PdfReader(io.BytesIO(response.content))
    count = len(reader.pages)
    text = [page.extract_text() for page in reader.pages]
    # Stopped by the page limit only: a partial audit, with its figures (DECISIONS 226).
    assert count > 5 and "Çağdaş Ceviz Atölyesi İŞ" in text[0] and "Partial audit: 500 of 610 pages read (page limit)" in text[0]
    assert "Executive summary" in text[1] and "Top opportunities" in text[1] and "problems across assessed scope" in text[1].replace("\n", " ")  # the executive summary is the page after the cover
    assert all(f"{n} / {count}" in text[n - 1] for n in (1, 2, count))  # page numbers on every page
    joined = "".join(text).replace("\n", "")
    assert "How this audit was done" in joined and "http://demo-shop.localhost/item/11" in joined
    assert "<script>alert(" in joined.replace(" ", "")  # shown as characters, on paper too


# -- questions, comparison, profile ----------------------------------------------------------------

def test_follow_up_answers_are_deterministic_use_ids_and_refuse_what_the_report_cannot_support(standard):
    client, audit, report = standard

    def ask(question):
        messages = client.post(f"{API}/audits/{audit['id']}/messages", json={"text": question}).json()["messages"]
        assert [m["role"] for m in messages] == ["user", "assistant"] and messages[1]["kind"] == "answer"
        return messages[1]["body"]

    for question in ("What is my ranking on Google?", "how often is the brand mentioned in ChatGPT", "sentiment?",
                     "give me a visibility score", "how much traffic will I get", "sıralama nedir"):
        answer = ask(question)
        assert answer["intent"] == "not_measured" and "does not measure" in answer["text"] and answer["items"] == [] and answer["suggestions"]
    order = report["findings_in_priority_order"]
    plan_answer = ask("Show the action plan")
    assert plan_answer["intent"] == "plan" and plan_answer["card"] == {"type": "action_plan", "role": None} and plan_answer["finding_ids"] == [order[0]]
    assert ask("action plan for the developers")["card"] == {"type": "action_plan", "role": "developer"}
    assert ask("what should the content team do?")["card"]["role"] == "content"
    critical = ask("Only critical issues")
    assert critical["intent"] == "critical" and critical["finding_ids"] == order[:len(critical["finding_ids"])] and critical["finding_ids"]
    assert all(("Blocker" in line or "High" in line) for line in critical["items"])
    top = ask("Explain the top issue")
    assert top["intent"] == "top" and top["finding_ids"] == [order[0]] and order[0].rsplit("-", 1)[0] in top["text"]
    assert any("Confidence" in line for line in top["items"]) and any("estimates" in line for line in top["items"])
    assert any("http://demo-shop.localhost/" in line for line in top["items"])  # the top finding names its own pages
    check = ask("explain IDX-4")
    assert check["intent"] == "check" and check["text"].startswith("IDX-4 Canonical signals")
    assert ask("explain STR-99")["text"] == strings.t("follow.check.unknown", check="STR-99")
    assert ask("which pages are affected by ACC-3?")["items"][0].startswith("http://demo-shop.localhost/item/")
    assert ask("what could not be checked?")["intent"] == "coverage"
    assert ask("is robots.txt blocking AI crawlers?")["intent"] == "area:ACC"  # a file name, not a new site to audit
    assert ask("only medium issues")["intent"] == "severity"
    assert "spent or reserved" in ask("how much did the backlinks cost")["text"]
    unknown = ask("tell me about the weather in Istanbul")
    assert unknown["intent"] == "unknown" and unknown["suggestions"] and "I can only answer from this audit's report" in unknown["text"]
    assert ask("Compare with last audit")["text"] == strings.t("follow.compare.none")
    assert ask("Show the action plan") == plan_answer  # the same question, the same answer
    spoken = json.dumps([plan_answer, critical, top, check, unknown])
    assert not re.findall(r"\d+(?:\.\d+)?\s?%", spoken)  # no invented percentages
    conversation = get(client, audit, "/conversation")["messages"]
    assert [m["kind"] for m in conversation[:3]] == ["text", "plan", "audit"] and conversation[1]["plan"]["id"] == audit["plan_id"]
    assert len(conversation) > 20 and all(m["id"] < n["id"] for m, n in zip(conversation, conversation[1:]))
    error(client.post(f"{API}/audits/{audit['id']}/messages", json={"text": ""}), 422, "invalid_request")


def test_the_results_adapter_has_no_field_for_what_the_audit_does_not_measure():
    keys = set(re.findall(r'"([a-z_]+)":', (PACKAGE / "summary.py").read_text(encoding="utf-8") + (PACKAGE / "comparison.py").read_text(encoding="utf-8")))
    assert not keys & {"visibility", "visibility_score", "mention_rate", "sentiment", "ranking", "rank", "score", "resolved", "fixed"}


def test_comparison_does_not_call_a_problem_gone_when_its_pages_were_not_read_again(standard):
    client, older, _ = standard
    error(client.get(f"{API}/audits/{older['id']}/comparison"), 404, "no_previous_audit")
    # Quick 50 after Standard 500: most of the earlier pages are not read this time (both in crawl order, DECISIONS 331)
    newer = audit_of(client, SHOP, crawl_order=True)
    result = get(client, newer, "/comparison")
    assert result["compared_with"] == older["id"] and not result["same_conditions"] and result["caution"]
    assert {"pages", "scope", "key_pages", "source"} <= {d["code"] for d in result["differences"]}
    assert "500" in next(d["message"] for d in result["differences"] if d["code"] == "scope")
    counts = result["counts"]
    assert counts["cannot_tell"] > 0 and counts["still_reported"] > 0 and sum(counts.values()) >= counts["still_reported"]
    assert all("was read" in row["why"] or "did not run" in row["why"] for row in result["cannot_tell"])
    assert all(row["pages_read_again"] >= 1 or row["pages_named"] == 0 for row in result["no_longer_reported"])
    assert "matched by check and by title" in result["matching"] and "fixed" not in json.dumps(result).lower()
    asked = client.post(f"{API}/audits/{newer['id']}/messages", json={"text": "Compare with last audit"}).json()["messages"][1]["body"]
    assert asked["card"] == {"type": "comparison"} and asked["text"] == result["summary_line"] and result["caution"] in asked["items"]
    assert get(client, newer, "/summary")["has_previous"] and not get(client, older, "/summary")["has_previous"]
    other_site = audit_of(client, CAFE)
    error(client.get(f"{API}/audits/{newer['id']}/comparison", params={"with": other_site["id"]}), 409, "not_comparable")
    assert get(client, newer, "/comparison", **{"with": older["id"]})["counts"] == counts


def test_comparison_matching_and_verdicts_on_small_reports():
    def report(findings, pages, statuses=None, cap=50):
        checks = {}
        for check_id, title, urls in findings:
            checks.setdefault(check_id, []).append({"id": f"{check_id}-{len(title)}{len(urls)}", "check_id": check_id, "title": title,
                                                    "severity": "S2", "scope": {"kind": "page", "count": len(urls), "urls": urls}})
        for check_id, status in (statuses or {}).items():
            checks.setdefault(check_id, [])
        return {"schema_version": "1.1", "findings_in_priority_order": [], "page_counts": {"pages_checked": len(pages), "redirects": 0},
                "gates": [], "answer_engine_panel": [],
                "checks": [{"check_id": c, "title": c, "status": (statuses or {}).get(c, "findings" if f else "pass"), "summary": "", "findings": f,
                            "coverage": {}} for c, f in checks.items()],
                "crawl": {"start_url": "https://x.example/", "started_at": "t", "pages": [{"url": u, "status": 200} for u in pages],
                          "config": {"max_pages": cap}, "requests": [], "stop_reason": "exhausted"}}
    a, b, c = "https://x.example/a", "https://x.example/b", "https://x.example/c"
    old = report([("STR-1", "3 page(s) have no <title>", [a, b, c]), ("IDX-1", "2 URL(s) return 404", [a, b]),
                  ("IDX-4", "1 canonical loop", [c]), ("RND-1", "1 page(s) need JavaScript", [a])], [a, b, c])
    new = report([("STR-1", "1 page(s) have no <title>", [a]), ("ACC-2", "GPTBot is blocked", [a])], [a, b],
                 statuses={"IDX-1": "pass", "IDX-4": "pass", "RND-1": "not_assessed"})
    result = comparison.compare(new, old)
    assert [(r["check_id"], r["pages_before"], r["pages"]) for r in result["still_reported"]] == [("STR-1", 3, 1)]  # matched despite the count
    assert [r["check_id"] for r in result["no_longer_reported"]] == ["IDX-1"] and result["no_longer_reported"][0]["pages_read_again"] == 2
    assert {r["check_id"] for r in result["cannot_tell"]} == {"IDX-4", "RND-1"}  # its page was not read; the check did not run
    assert [r["check_id"] for r in result["first_seen"]] == ["ACC-2"] and result["new"] == []  # the earlier audit never ran ACC-2
    same = comparison.compare(old, old)
    assert same["same_conditions"] and same["counts"] == {"still_reported": 4, "no_longer_reported": 0, "cannot_tell": 0, "new": 0, "first_seen": 0,
                                                   "worse": 0, "better": 0}
    with pytest.raises(summary.UnreadableReport):
        comparison.compare({**new, "schema_version": "2.0"}, old)


def test_an_unsupported_report_version_is_refused_not_guessed_at(web):
    client = web()
    audit = audit_of(client, CAFE)
    path = client.app.state.runner.artifacts(audit["id"]) / "report.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps({**report, "schema_version": "2.0"}))
    for route in ("/summary", "/findings", "/action-plan", "/result", "/downloads/pdf", "/print?full=true"):
        refused = error(client.get(f"{API}/audits/{audit['id']}{route}"), 409, "report_version_unsupported")
        assert "schema 2.0" in refused["message"]
    path.write_text("{ not json")
    error(client.get(f"{API}/audits/{audit['id']}/summary"), 409, "report_unreadable")
    assert get(client, audit)["state"] == "finished"


def test_the_business_profile_is_saved_validated_and_never_changes_findings(web):
    client = web()
    empty = client.get(f"{API}/projects/{SHOP}/profile").json()
    assert empty["confirmed"] is False and empty["brand_name"] == "" and empty["key_pages"] == []
    before = audit_of(client)
    findings_before, counts_before = get(client, before, "/findings", limit=100)["items"], get(client, before, "/summary")["counts"]
    saved = client.put(f"{API}/projects/{SHOP}/profile", json={
        "brand_name": "  Demo Shop Ltd ", "industry": "Furniture", "goals": ["more enquiries", " "], "countries": ["TR", "DE"],
        "languages": ["tr", "en"], "key_pages": ["/about", "tr/"]}).json()
    assert saved["confirmed"] and saved["brand_name"] == "Demo Shop Ltd" and saved["goals"] == ["more enquiries"]
    assert saved["key_pages"] == [f"http://{SHOP}/about", f"http://{SHOP}/tr/"]
    assert client.get(f"{API}/projects/{SHOP}/profile").json() == saved
    error(client.put(f"{API}/projects/{SHOP}/profile", json={"key_pages": ["https://elsewhere.example/"]}), 422, "invalid_key_pages")
    error(client.put(f"{API}/projects/{SHOP}/profile", json={"brand_name": "x" * 500}), 422, "invalid_request")
    error(client.put(f"{API}/projects/{SHOP}/profile", json={"severity_override": "Info"}), 422, "invalid_request")
    error(client.get(f"{API}/projects/..%2F..%2Fetc/profile"), 404, "not_found")
    error(client.get(f"{API}/projects/nodot/profile"), 404, "project_not_found")
    after = get(client, before, "/summary")
    assert after["brand"]["name"] == "Demo Shop Ltd" and after["brand"]["confirmed"]
    assert get(client, before, "/findings", limit=100)["items"] == findings_before and after["counts"] == counts_before


def test_history_is_searched_filtered_paged_kept_on_disk_and_deleted_with_its_files(web, tmp_path):
    folder = tmp_path / "history"
    client = web(folder=folder)
    shop, cafe = audit_of(client), audit_of(client, CAFE)
    listed = client.get(f"{API}/audits").json()
    assert listed["total"] == 2 and [a["id"] for a in listed["audits"]] == [cafe["id"], shop["id"]]
    assert listed["audits"][0] == {**listed["audits"][0], "host": CAFE, "state": "finished", "outcome": "COMPLETED", "pages_checked": 12}
    assert [a["id"] for a in client.get(f"{API}/audits", params={"q": "kafe"}).json()["audits"]] == [cafe["id"]]
    assert [a["id"] for a in client.get(f"{API}/audits", params={"domain": SHOP}).json()["audits"]] == [shop["id"]]
    assert client.get(f"{API}/audits", params={"q": "100%_nothing"}).json()["total"] == 0
    assert client.get(f"{API}/audits", params={"status": "failed"}).json()["audits"] == []
    assert [a["id"] for a in client.get(f"{API}/audits", params={"limit": 1, "offset": 1}).json()["audits"]] == [shop["id"]]
    client.post(f"{API}/audits/{shop['id']}/messages", json={"text": "what about the weather"})
    assert [a["id"] for a in client.get(f"{API}/audits", params={"q": "weather"}).json()["audits"]] == [shop["id"]]
    audit_folder = folder / "audits" / shop["id"]
    assert (audit_folder / "artifacts" / "report.json").is_file() and (audit_folder / "state" / "crawl.db").is_file()
    assert not list(folder.glob("**/dataforseo-ledger.jsonl"))  # the spending ledger is not among an audit's files
    web.close(client)
    again = web(folder=folder)  # history is on disk, not in the process
    assert get(again, shop, "/summary")["counts"]["pages_checked"] == 49  # pages read (DECISIONS 289)
    assert again.delete(f"{API}/audits/{shop['id']}").json() == {"deleted": shop["id"]}
    assert not audit_folder.exists() and again.get(f"{API}/audits").json()["total"] == 1
    error(again.get(f"{API}/audits/{shop['id']}"), 404, "audit_not_found")


def test_history_and_reports_live_outside_the_repository(monkeypatch, tmp_path):
    from maya_audit_web.store import data_home
    monkeypatch.setenv("MAYA_AUDIT_HOME", str(tmp_path / "home"))
    assert data_home() == tmp_path / "home" / "web"
    monkeypatch.delenv("MAYA_AUDIT_HOME")
    assert data_home() == Path.home() / ".maya-audit" / "web"
    assert Path(__file__).resolve().parents[1] not in data_home().parents


@pytest.mark.timing
@pytest.mark.slow
def test_the_api_stays_responsive_while_a_500_page_audit_runs(web):
    site = Site()
    site._inner = demo.site_transport(0.004)
    client = web(site=site)
    audit = start(client, plan(client, mode="standard"), wait=False)
    slowest, polls, deadline = 0.0, 0, time.monotonic() + 90
    while get(client, audit)["active"] and time.monotonic() < deadline:
        for path in (f"{API}/health", f"{API}/audits", f"{API}/audits/{audit['id']}", f"{API}/budget"):
            begun = time.monotonic()
            assert client.get(path).status_code == 200
            slowest = max(slowest, time.monotonic() - begun)
        polls += 1
    done = get(client, audit)
    assert done["state"] == "finished" and done["counters"]["pages_checked"] == 500 and polls > 3
    # Wall-clock bound: 1.5 s held on a developer Mac, a shared CI runner took 1.96 s once. 3 s still catches a
    # request that waits for the audit (that took the whole audit, many seconds).
    assert slowest < 3.0, f"slowest request while the audit ran: {slowest:.2f}s"
    store = client.app.state.store
    assert store._one("SELECT COUNT(*) AS n FROM events WHERE audit_id = ?", (audit["id"],))["n"] <= MAX_EVENTS
    assert len(json.dumps(done)) < 6000 and len(json.dumps(store.audit(audit["id"])["progress"])) < 2000


# -- demo mode, strings ----------------------------------------------------------------------------

def test_demo_mode_is_labelled_accepts_only_its_own_sites_and_keeps_its_own_ledger(tmp_path, monkeypatch):
    from maya_audit_web import __main__ as main_module
    monkeypatch.setenv("MAYA_AUDIT_HOME", str(tmp_path / "home"))
    app, folder = main_module.build(True, 8770)
    assert folder == tmp_path / "home" / "web" / "demo"
    with TestClient(app, base_url=BASE) as client:
        client.get("/")
        assert client.get(f"{API}/settings").json()["language"] == "tr"  # Turkish unless the reader chose (DECISIONS 310)
        client.cookies.set("maya_language", "en")
        client.headers["x-maya-token"] = client.get(f"{API}/session").json()["token"]
        settings = client.get(f"{API}/settings").json()
        assert settings["demo"] and {s["address"] for s in settings["demo_sites"]} == set(demo.SITES)
        refused = error(client.post(f"{API}/plans", json={"url": "example.com"}), 422, "demo_sites_only")
        assert SHOP in refused["message"]
        made = plan(client, SHOP, backlinks=True, mode="standard", crawl_order=True)  # DECISIONS 331
        assert made["paid"]["calls"][0]["target"] == "demo-shop.example" and {k: v for k, v in made["duration"].items() if k != "typical"} == {"known": False, "label": strings.t("plan.duration.demo")}
        audit = start(client, confirm(client, made))
        view = get(client, audit, "/summary")
        assert view["demo"] and view["counts"]["pages_checked"] == 500 and view["backlinks"]["available"]
        assert view["answers"]["assessed"] and view["coverage"]["gaps"] and view["counts"]["by_severity"]["S2"] >= 1  # every kind of state to look at (no S1 since H26)
        assert strings.t("app.demo_banner") in client.get(f"{API}/audits/{audit['id']}/print?full=true").text
        cafe = audit_of(client, CAFE)
        assert cafe["outcome"]["code"] == "COMPLETED" and get(client, cafe, "/summary")["counts"]["pages_checked"] == 12
    assert (folder / "paid" / LEDGER_NAME).is_file() and not (tmp_path / "home" / LEDGER_NAME).exists()  # the real ledger was never opened


def test_every_sentence_the_app_uses_is_in_the_one_catalog():
    used = set()
    for path in [*PACKAGE.glob("*.py"), PACKAGE / "static" / "app.js"]:
        text = path.read_text(encoding="utf-8")
        used |= set(re.findall(r'\b[tT]\(\s*f?"([a-z][a-zA-Z_.0-9-]+)"', text))
        used |= set(re.findall(r'"((?:result|follow|plan|paid|job|phase|nav|chat|step|eta|compare|pdf|owner|effort|profile|resume|'
                               r'error|word|option|chip|help|welcome|composer|theme|log)\.[a-zA-Z_.0-9-]+)"', text))
    table = strings.STRINGS["en"]
    prefixes = sorted(key for key in used if key.endswith("."))
    missing = sorted(key for key in used if not key.endswith(".") and key not in table)
    assert not missing, missing
    for prefix in prefixes:
        assert any(key.startswith(prefix) for key in table), prefix
    from maya_audit.progress import PHASES
    from maya_audit_web.runner import PHASE_STEP, STEPS
    groups = (("result.severity.", ("S1", "S2", "S3", "S4", "Info")), ("job.state.", ("queued", "running", "stopping", "stopped", "interrupted", "finished", "failed")),
              ("result.outcome.", ("COMPLETED", "INCOMPLETE", "DEGRADED")), ("step.", STEPS), ("phase.", [p for p in (*PHASES, "backlinks", "report") if p != "done"]),
              ("step.status.", ("pending", "active", "done", "skipped", "unavailable", "not_reached")),
              ("result.status.", ("pass", "partial", "findings", "needs_review", "observed", "not_assessed")),
              ("result.confidence.", ("verified", "inferred", "estimated", "not_assessed")), ("result.group.", ("fix_now", "fix_next", "improve_later")),
              ("owner.", catalog.OWNERS), ("effort.", catalog.EFFORTS), ("result.download.", ("pdf", "markdown", "json", "evidence")),
              ("compare.section.", ("still_reported", "no_longer_reported", "new", "first_seen", "cannot_tell")),
              ("compare.diff.", ("target", "pages", "scope", "rendering", "key_pages", "source")))
    for group, members in groups:
        assert all(group + member in table for member in members), group
    assert set(PHASE_STEP) >= set(PHASES) - {"done"} and set(PHASE_STEP.values()) == set(STEPS)
    assert strings.t("paid.total", total="0.05") == "Maximum for this audit: $0.05" and strings.t("no.such.key") == "no.such.key"
    # No user-facing sentence is written in the page or the script itself: the page has ids, the script has keys.
    page = re.sub(r"<title>.*?</title>|>Maya Audit<|>M<|Skip to the message box", "", (PACKAGE / "static" / "index.html").read_text(encoding="utf-8"))
    assert not re.findall(r">\s*[A-Za-z][^<>{}]{3,}<", page)


# -- blocked sites, addresses, brand ------------------------------------------------------------------

def cloudflare(request):
    return httpx.Response(403, headers={"content-type": "text/html", "server": "cloudflare", "cf-mitigated": "challenge", "cf-ray": "a1-FRA"},
                          text="<html><title>Just a moment...</title><body>Checking your browser</body></html>")


def test_a_blocked_audit_leads_with_who_blocked_it_and_what_to_do(web):
    client = web(site=Site(respond=cloudflare))
    audit = audit_of(client)
    assert audit["state"] == "finished" and audit["outcome"]["code"] == "DEGRADED"
    view = get(client, audit, "/summary")
    lead = view["blocked"]
    assert lead["headline"] == "The site blocked this audit: Cloudflare (bot challenge)" and lead["name"] == "Cloudflare"
    assert (lead["pages_read"], lead["pages_requested"]) == (0, 1) and "could read 0 of the 1 page it requested" in lead["lines"][0]
    assert any("banks, large retailers" in line for line in lead["lines"]) and any("does not try to get past" in line for line in lead["lines"])
    assert any("AI search and assistant crawlers" in line and "not tested" in line for line in lead["lines"])
    steps = " ".join(lead["next_steps"])
    assert "allow the user agent “Maya-Audit”" in steps and "Verify ownership" in steps and "try again later" in steps
    # With nothing read there is no "first action", and the access finding is the one thing reported.
    assert view["first_action"] is None and view["pages_read"] == 0
    assert view["top"][0]["check_id"] == "ACC-9" and "may be blocked the same way" in view["top"][0]["title"]  # DECISIONS 317
    assert view["first_action_withheld"] == strings.t("result.first_action.withheld", read=0, needed=3)
    assert "Only Maya's own crawler was measured" in view["top"][0]["why"]
    # One line for everything the block made impossible, not one per check.
    gaps = view["coverage"]["gaps"]
    [same_cause] = [gap for gap in gaps if gap.get("blocked")]
    assert same_cause["part"] == "Blocked by Cloudflare (bot challenge)" and len(same_cause["checks"]) > 25
    assert same_cause["checks_label"] == f"{len(same_cause['checks'])} checks" and "one cause" in same_cause["reason"]
    assert not [gap for gap in gaps if "No indexable HTML pages" in (gap["reason"] or "") or "could read none" in (gap["reason"] or "")]
    assert len(gaps) < 15 and view["counts"]["not_checked"] == len(gaps)
    others = {check for gap in gaps if not gap.get("blocked") for check in gap["checks"]}
    assert {"ACC-4", "ACC-5", "IDX-9"} <= others  # unavailable for reasons of their own: still listed separately
    printable = client.get(f"{API}/audits/{audit['id']}/print?full=true").text
    assert printable.index("The site blocked this audit: Cloudflare") < printable.index("Action plan") and "What to do next" in printable
    assert "First action" not in printable and "No problems were found" not in printable
    # Every request carried Maya's own user agent: nothing was retried in disguise.
    report = client.get(f"{API}/audits/{audit['id']}/result").json()
    assert {r["user_agent"] for r in report["crawl"]["requests"]} == {report["crawl"]["user_agent"]}
    coverage_answer = client.post(f"{API}/audits/{audit['id']}/messages", json={"text": "what could not be checked?"}).json()["messages"][1]["body"]
    assert any(item.startswith(f"{len(same_cause['checks'])} checks: Blocked by Cloudflare") for item in coverage_answer["items"])


def test_a_report_saved_before_the_blocker_was_recorded_is_still_explained():
    """The shape of a real saved report from before this change: INT-1 without `blocked_by`, no ACC-9."""
    page = {"url": "https://bank.example/", "status": 403, "fetch_class": "blocked", "discovered_via": "start", "redirect_location": None}
    impaired = {**page, "error": None, "confidence": "verified", "evidence": ["header cf-mitigated: challenge", "status 403"],
                "headers": {"server": "cloudflare", "cf-mitigated": "challenge", "cf-ray": "x-FRA"}}
    report = {"schema_version": "1.1", "findings_in_priority_order": [], "page_counts": {"pages_checked": 1, "redirects": 0},
              "gates": [{"check_id": "INT-1", "title": "Fetch classification per page", "state": "degraded", "summary": "degraded",
                         "evidence": {"pages_fetched": 1, "impaired_pages": [impaired]}}],
              "checks": [{"check_id": f"STR-{n}", "title": f"Check {n}", "status": "not_assessed", "summary": "No indexable HTML pages.",
                          "findings": [], "review_items": [], "coverage": {"not_assessed": []}} for n in range(1, 16)],
              "answer_engine_panel": [],
              "crawl": {"start_url": "https://bank.example/", "origin": "https://bank.example", "user_agent": "Maya-Audit/0.2",
                        "product_token": "Maya-Audit", "pages": [page], "requests": [], "config": {"max_pages": 50}}}
    view = summary.build(report, outcome="DEGRADED", reason="blocked")
    assert view["blocked"]["who"] == "Cloudflare (bot challenge)" and view["first_action"] is None
    [gap] = view["coverage"]["gaps"]
    assert gap["blocked"] and gap["checks_label"] == "15 checks"
    plain = json.loads(json.dumps(report).replace('"server": "cloudflare", "cf-mitigated": "challenge", "cf-ray": "x-FRA"', '"server": "nginx"')
                       .replace("header cf-mitigated: challenge", "status 403 (access denied)"))
    assert summary.build(plain, outcome="DEGRADED", reason="blocked")["blocked"]["who"] == "the site or its firewall (HTTP 403, access denied)"
    fine = {**report, "gates": [{**report["gates"][0], "state": "ok", "evidence": {"pages_fetched": 1, "impaired_pages": []}}]}
    assert summary.build(fine, outcome="COMPLETED", reason="")["blocked"] is None


def test_few_pages_read_means_no_first_action_and_enough_pages_means_one(web):
    def two_pages(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n", headers={"content-type": "text/plain"})
        if request.url.path in ("/", "/b"):
            return httpx.Response(200, headers={"content-type": "text/html"}, text='<html lang="en"><head><meta name="robots" content="noindex">'
                                  '<title>T</title></head><body><main><h1>T</h1><a href="/b">b</a></main></body></html>')
        return httpx.Response(404, headers={"content-type": "text/html"}, text="<html><title>404</title></html>")
    client = web(site=Site(respond=two_pages))
    view = get(client, audit_of(client), "/summary")
    assert view["pages_read"] == 2 and view["counts"]["problems"] >= 1 and view["blocked"] is None
    assert view["first_action"] is None and "Only 2 pages could be read" in view["first_action_withheld"]
    assert view["top"]  # the findings are still all there; only the "start here" is withheld
    enough = web(folder=client.app.state.store.folder.parent / "enough")
    full = get(enough, audit_of(enough), "/summary")
    assert full["pages_read"] >= 3 and full["first_action"] and full["first_action_withheld"] is None


def test_https_is_tried_first_and_http_only_when_https_does_not_answer(web, monkeypatch):
    real = socket.getaddrinfo
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, *a, **k: (_ for _ in ()).throw(socket.gaierror(8, "not known"))
                        if str(host).endswith(".test") else real(host, *a, **k))

    def page_for(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n", headers={"content-type": "text/plain"})
        if request.url.path == "/":
            return httpx.Response(200, headers={"content-type": "text/html"}, text='<html lang="en"><title>Old Shop</title><main><h1>Old Shop</h1></main></html>')
        return httpx.Response(404, headers={"content-type": "text/html"}, text="<html><title>404</title></html>")

    def http_only(request):
        if request.url.scheme == "https":
            raise httpx.ConnectError("connection refused")
        return page_for(request)
    client = web(site=Site(respond=http_only))
    typed = plan(client, "http://old-shop.test/")
    assert typed["target"]["url"] == "https://old-shop.test/" and typed["target"]["http_fallback"] == "http://old-shop.test/"
    assert typed["target"]["note"] == strings.t("plan.https_first.typed_http")
    bare = plan(client, "old-shop.test")
    assert bare["target"]["url"] == "https://old-shop.test/" and bare["target"]["note"] == strings.t("plan.https_first")
    explicit = plan(client, "https://old-shop.test/")
    assert explicit["target"]["http_fallback"] is None and explicit["target"]["note"] is None
    assert client.site.requests == []

    audit = start(client, typed)
    assert audit["url"] == "http://old-shop.test/" and audit["state"] == "finished"
    assert audit["address_note"] == "https://old-shop.test/ did not answer at all, so http://old-shop.test/ was audited instead."
    schemes = [url.split(":")[0] for url in client.site.requests]
    assert schemes[0] == "https" and "http" in schemes and schemes.index("http") > 0  # https was asked first
    report = client.get(f"{API}/audits/{audit['id']}/result").json()
    assert report["crawl"]["start_url"] == "http://old-shop.test/" and report["page_counts"]["pages_checked"] == 1

    no_fallback = start(client, explicit)  # typed with https://: the person asked for exactly that
    assert no_fallback["url"] == "https://old-shop.test/" and no_fallback["address_note"] is None

    answering = web(site=Site(respond=page_for), folder=client.app.state.store.folder.parent / "https-ok")
    secure = start(answering, plan(answering, "http://old-shop.test/"))
    assert secure["url"] == "https://old-shop.test/" and secure["address_note"] is None  # https answered: no fallback
    assert [url for url in answering.site.requests if url.startswith("http://") and "robots.txt" not in url
            and url != "http://old-shop.test/"] == []  # the only http:// requests are IDX-2's own redirect check
    report = answering.get(f"{API}/audits/{secure['id']}/result").json()
    assert report["crawl"]["start_url"] == "https://old-shop.test/"


def test_a_start_address_that_redirects_to_another_site_is_said_and_the_other_site_offered(web, monkeypatch):
    real = socket.getaddrinfo
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, *a, **k: (_ for _ in ()).throw(socket.gaierror(8, "not known"))
                        if str(host).endswith(".test") else real(host, *a, **k))

    def moved(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n", headers={"content-type": "text/plain"})
        if request.url.host == "old-brand.test":
            return httpx.Response(301, headers={"location": "https://www.new-brand.test/"})
        return httpx.Response(200, headers={"content-type": "text/html"}, text="<html><title>New</title><main><h1>New</h1></main></html>")
    client = web(site=Site(respond=moved))
    audit = start(client, plan(client, "https://old-brand.test/"))
    view = get(client, audit, "/summary")
    assert view["redirected"] == {"from": "https://old-brand.test/", "to": "https://www.new-brand.test/", "to_host": "www.new-brand.test",
                                  "message": strings.t("redirect.message", start="https://old-brand.test/", target="https://www.new-brand.test/"),
                                  "offer": "Audit www.new-brand.test instead?"}
    assert not [url for url in client.site.requests if "new-brand.test" in url]  # the audit stayed where it was sent
    assert "sends visitors on to another site" in client.get(f"{API}/audits/{audit['id']}/print?full=true").text
    offered = plan(client, view["redirected"]["to"])
    assert offered["target"]["host"] == "www.new-brand.test"

    def same_site(request):
        if request.url.host == "brand.test" and request.url.path == "/":
            return httpx.Response(301, headers={"location": "https://www.brand.test/"})
        return moved(request)
    own = web(site=Site(respond=same_site), folder=client.app.state.store.folder.parent / "www")
    assert get(own, start(own, plan(own, "https://brand.test/")), "/summary")["redirected"] is None  # www of the same name is the same site


def test_the_plan_suggests_brand_and_country_and_the_report_uses_what_was_confirmed(web, monkeypatch):
    client = web()
    made = plan(client, "https://www.maksimum-enerji.com.tr/")
    assert made["business"] == {"brand_name": "Maksimum Enerji", "country": "Türkiye", "brand_confirmed": False, "country_confirmed": False,
                                "suggested_from": "the address ending (.tr)", "note": strings.t("plan.business.suggested")}
    assert plan(client, "https://acme.io/")["business"]["country"] == ""  # no guess where the address does not say
    client.put(f"{API}/projects/maksimum-enerji.com.tr/profile", json={"brand_name": "Maksimum", "countries": ["Türkiye", "Germany"]})
    again = plan(client, "www.maksimum-enerji.com.tr")
    assert again["business"] == {"brand_name": "Maksimum", "country": "Türkiye", "brand_confirmed": True, "country_confirmed": True,
                                 "suggested_from": None, "note": strings.t("plan.business.confirmed")}
    assert again["fingerprint"] == made["fingerprint"]  # the brand never changes what is audited
    audit = audit_of(client)
    client.put(f"{API}/projects/{SHOP}/profile", json={"brand_name": "Demo Shop Ltd", "countries": ["Türkiye"]})
    brand = get(client, audit, "/summary")["brand"]
    assert brand == {"name": "Demo Shop Ltd", "confirmed": True, "label": None, "country": "Türkiye"}
    cover = client.get(f"{API}/audits/{audit['id']}/print?full=true").text
    assert "<h1 class=\"wrap\">Demo Shop Ltd</h1>" in cover and "<td>Country</td><td class=\"wrap\">Türkiye</td>" in cover
    script = (PACKAGE / "static" / "app.js").read_text(encoding="utf-8")
    assert "plan.business.brand" in script and "plan.business.country" in script and "saveBusiness" in script


# -- explanations ------------------------------------------------------------------------------------

def engine_finding_titles():
    """Every finding title the engine can write, as (check id, a sample title), read from the engine's own source:
    the checks package and the technical SEO check beside it. A number or a name put in at run time is written as 3
    ("3%" for a percentage, "'3'" for a quoted value)."""
    import maya_audit.checks as checks_package
    import maya_audit.technical_seo as technical_seo
    folder = Path(checks_package.__file__).parent

    def sample(found):
        spec = found.group(0)[1:-1]
        return "3%" if spec.endswith("%") else "'3'" if spec.endswith("!r") else "3"

    found = []
    for path in [*sorted(folder.glob("*.py")), Path(technical_seo.__file__)]:
        source = path.read_text(encoding="utf-8")
        for match in re.finditer(r'(?:Finding|_finding|_note|ReviewItem)\(\s*(?:check_id=)?"((?:ACC|IDX|RND|STR|PRF|TSEO)-\d+)",\s*(?:title=)?f?"((?:[^"\\]|\\.)*)"', source):
            check_id, template = match.group(1), match.group(2)
            rest = source[match.end():match.end() + 400]
            more = re.match(r'\s*\n?\s*f?"((?:[^"\\]|\\.)*)"', rest)  # a title continued on the next line
            title = template + (more.group(1) if more else "")
            found.append((check_id, re.sub(r"\{[^{}]*\}", sample, title).replace("\\\"", '"')))
    return found


# Titles built from a label chosen at run time. Each label is checked to be in the engine's source, so a rename shows up here.
LABELLED = {"STR-19": ("have no address a crawler can follow (they may still work for visitors through JavaScript)",
                       "in the footer look like links but have no address"),
            "RND-4": ("embed content in an iframe; essential content and accessibility are not established", "draw content on a <canvas> with no text equivalent",
                      "show banner-shaped images with no alt text in main content")}

# The same for every check whose title is put together at run time: check id -> ((pieces of the engine's source the
# title is made of, a title as the engine writes it), ...). `engine_title_samples` checks each piece is still in the
# source, and leaves out the sample that holds only a 3 where the label goes (`ONLY_A_LABEL`).
BUILT_TITLES = {
    "ACC-2": ((("blocks {role} bot(s)", '"sitewide" if pattern.strip()'), "robots.txt line 4 (Disallow: /) blocks search bot(s) GPTBot, OAI-SearchBot sitewide"),
              (("blocks {role} bot(s)", "sampled URL(s)"), "robots.txt line 7 (Disallow: /private/) blocks training bot(s) GPTBot on 2 sampled URL(s)"),
              (("blocks {role} bot(s)",), "robots.txt line 9 (Disallow: /app/) blocks live bot(s) ChatGPT-User on 1 sampled URL(s)"),
              (("Policy mismatch: declared policy blocks {role} bots",), "Policy mismatch: declared policy blocks training bots, but robots.txt allows GPTBot, CCBot on at least one sampled URL")),
    "ACC-3": ((('f"noindex via {where}"',), "noindex via meta robots on 5 page(s)"),
              (("(page intent should be reviewed)",), "noindex via X-Robots-Tag (googlebot) (page intent should be reviewed) on 1 page(s)"),
              (('f"nosnippet via {where}"',), "nosnippet via meta robots on 2 page(s)"),
              (('f"max-snippet:0 via {where}"',), "max-snippet:0 via meta robots on 1 page(s)"),
              (('f"max-snippet below {cfg.min_max_snippet} via {where}"',), "max-snippet below 50 via meta robots on 3 page(s)"),
              (('f"noarchive via {where}"',), "noarchive via meta robots (bingbot) on 2 page(s)"),
              (('f"nocache via {where}"',), "nocache via X-Robots-Tag on 1 page(s)"),
              (('"main content inside data-nosnippet"',), "main content inside data-nosnippet on 4 page(s)"),
              # A utility page's noindex (DECISIONS 222).
              (("utility page(s) (such as a QR menu or a print page): check that this ",),
               "noindex via meta robots on 1 utility page(s) (such as a QR menu or a print page): check that this is intended"),
              # noindex on a page only the sitemap lists, and the sitemap listing it (H26, W1); unavailable_after (B06).
              (("{label} on {n} page(s) the sitemap lists: check that this is intended",),
               "noindex via meta on 2 page(s) the sitemap lists: check that this is intended"),
              (("The sitemap lists {n} page(s) that carry noindex",), "The sitemap lists 2 page(s) that carry noindex"),
              (('f"unavailable_after (date passed) via {where}"', "(page intent should be reviewed)"),
               "unavailable_after (date passed) via X-Robots-Tag (page intent should be reviewed) on 1 page(s)"),
              (('f"unavailable_after (date passed) via {where}"',), "unavailable_after (date passed) via meta on 1 page(s)"),
              (('f"unavailable_after (date passed) via {where}"', "the sitemap lists: check that this is intended"),
               "unavailable_after (date passed) via meta on 1 page(s) the sitemap lists: check that this is intended"),
              (('f"unavailable_after {value} via {where}"',), "unavailable_after 2030-01-01 via meta on 1 page(s)")),
    "ACC-4": ((("were {outcome.replace('_', ' ')} on", "(seen once, not retried)"), "Requests with search bot user agents were blocked on 3 URL(s): GPTBot, ClaudeBot (seen once, not retried)"),
              (("were {outcome.replace('_', ' ')} on",), "Requests with live bot user agents were rate limited on 1 URL(s): ChatGPT-User"),
              (("were {outcome.replace('_', ' ')} on",), "Requests with training bot user agents were challenged on 2 URL(s): CCBot"),
              (("were {outcome.replace('_', ' ')} on",), "Requests with search bot user agents were degraded on 2 URL(s): PerplexityBot"),
              (("were redirected somewhere a browser was not sent",), "Requests with search bot user agents were redirected somewhere a browser was not sent on 2 URL(s): Bingbot"),
              (("received different content than a browser",), "Requests with live bot user agents received different content than a browser on 1 URL(s): Claude-User"),
              # Ownership not verified: a browser against Googlebot's user agent (DECISIONS 205).
              (("A request with Googlebot's user agent got {status} on ", "URL(s) where a browser got {browser}"),
               "A request with Googlebot's user agent got 500 on 3 of 3 URL(s) where a browser got 200"),
              (("A request with Googlebot's user agent got {status} on ",), "A request with Googlebot's user agent got 403 on 1 of 2 URL(s) where a browser got 200"),
              (("sent Googlebot's user agent a page of very different size than a browser's",),
               "1 of 3 URL(s) sent Googlebot's user agent a page of very different size than a browser's"),
              # An empty page to Googlebot's user agent (A21) and a CDN challenge to it (A22), W1.
              (("sent Googlebot's user agent an empty page where a browser got the page",),
               "1 of 3 URL(s) sent Googlebot's user agent an empty page where a browser got the page"),
              (("challenged Googlebot's user agent from Maya's address: the real Googlebot ",),
               "2 of 3 URL(s) challenged Googlebot's user agent from Maya's address: the real Googlebot may be on a verified-bot allowlist")),
    "ACC-6": ((("Training{f' ({training})' if training else ''}", "· Live fetch", '"allowed"', "partly blocked ("),
               "OpenAI: Training (GPTBot): blocked · Search (OAI-SearchBot): allowed · Live fetch (ChatGPT-User): partly blocked (2/5 sampled URLs)"),
              (('"no token"',), "Common Crawl: Training (CCBot): blocked · Search: no token · Live fetch: no token")),
    "ACC-9": ((("The site blocks or challenges automated visitors: {who}", '"bot challenge": "a bot challenge"'),
               "The site blocks or challenges automated visitors: Cloudflare (bot challenge) answered 5 of 6 page request(s). AI crawlers may be affected too"),
              (("the site or its firewall (HTTP {top['status']}, access denied)",),
               "The site blocks or challenges automated visitors: the site or its firewall (HTTP 403, access denied) answered 1 of 1 page request(s). AI crawlers may be affected too"),
              (("the site's rate limiting (HTTP 429)",),
               "The site blocks or challenges automated visitors: the site's rate limiting (HTTP 429) answered 9 of 30 page request(s). AI crawlers may be affected too"),
              # The same finding once the pages were read through Firecrawl (maya_audit/firecrawl/reader.py).
              (("Maya's direct crawler{counted}. {pages_read} page(s) were read through Firecrawl instead.", 'f" on {hit} of {asked} request(s)"', '"challenged"'),
               "Cloudflare challenged Maya's direct crawler on 1 of 1 request(s). 3 page(s) were read through Firecrawl instead. Genuine AI-crawler access was not measured."),
              (('"rate-limited" if top.get("kind") == "rate limit"',),
               "Akamai rate-limited Maya's direct crawler. 12 page(s) were read through Firecrawl instead. Genuine AI-crawler access was not measured."),
              (('"The site\'s bot protection"',),
               "The site's bot protection challenged Maya's direct crawler on 2 of 2 request(s). 1 page(s) were read through Firecrawl instead. Genuine AI-crawler access was not measured."),
              (('"The site\'s bot protection"',),
               "The site's bot protection rate-limited Maya's direct crawler. 4 page(s) were read through Firecrawl instead. Genuine AI-crawler access was not measured.")),
    # The answer-engine panel: shown apart from the site findings, worded by the same table.
    "ANS-1": ((("Cited URL fails a site check ({', '.join(view['failures'])}): {url}",), "Cited URL fails a site check (http_404, noindex): https://made-up.example/old-pricing"),),
    "ANS-2": ((("answer(s) state {label} that the cited page contradicts", '"a price or plan"'), "2 answer(s) state a price or plan that the cited page contradicts"),
              (('"a fact"',), "1 answer(s) state a fact that the cited page contradicts"),
              (("answer claim(s) state something the cited page does not show",), "3 answer claim(s) state something the cited page does not show")),
    "ANS-4": ((("cited {engines_seen[engine]} domain-mentions on this topic and none from this site",), "perplexity cited 41 domain-mentions on this topic and none from this site"),),
    "IDX-1": ((("return a client error (4xx), {label}", "linked internally or listed in the sitemap"), "3 URL(s) return a client error (4xx), linked internally or listed in the sitemap"),
              (("not referenced by any crawled page or the sitemap",), "1 URL(s) return a client error (4xx), not referenced by any crawled page or the sitemap"),
              # IDX-6's findings for the same dead URLs said under IDX-1 (maya_audit.root_cause, review H10).
              (('IDX6_SUFFIX = "; linked from {pages} page(s)"',),
               "3 URL(s) return a client error (4xx), linked internally or listed in the sitemap; linked from 4 page(s)"),
              (("A page that does not exist {answer} (soft 404)", "redirects ({probe['status']}) to the homepage"), "A page that does not exist redirects (301) to the homepage (soft 404)"),
              (("answers 200, as if the page existed",), "A page that does not exist answers 200, as if the page existed (soft 404)"),
              # Empty to Maya twice, content to a browser user agent (first review C1/C2).
              (("answer with an empty page to automated clients only (under {limit} bytes); a browser gets",),
               "5 page(s) answer with an empty page to automated clients only (under 512 bytes); a browser gets content")),
    "IDX-2": ((("No HTTP to HTTPS redirect on {', '.join(row['host'] for row in wrong)}",), "No HTTP to HTTPS redirect on example.com, www.example.com"),),
    # IDX-1's empty or failing pages said in IDX-5's share title, and in ACC-8's links title (DECISIONS 215).
    "IDX-5": ((("word-like queries; intended paths are unassessed",), "2 sitemap URL(s) use word-like queries; intended paths are unassessed"),
              (("contain unescaped spaces or corrupted encoding",), "1 sitemap URL(s) contain unescaped spaces or corrupted encoding"),
              # Its first number is the URLs left in the finding (review CR-28).
              (("{rest} of {assessed} sitemap URL(s){checked} are not live, indexable pages besides the {same} empty or failing ",
                "page(s) reported under IDX-1 ({share} with them){tail}"),
               "57 of 245 sitemap URL(s) are not live, indexable pages besides the 66 empty or failing page(s) reported under IDX-1 (50% with them)"),
              (("{rest} of {assessed} sitemap URL(s){checked} are not live, indexable pages besides the {same} empty or failing ",
                "the sitemap lists {len(listed)}"),
               "57 of 245 sitemap URL(s) checked are not live, indexable pages besides the 66 empty or failing page(s) reported under IDX-1 "
               "(50% with them); the sitemap lists 282")),
    "ACC-8": ((("; {same} of them lead to the empty pages reported under IDX-1", "lead to pages that do not work"),
               "49 of 141 link(s) in llms.txt lead to pages that do not work (empty page, redirect); 48 of them lead to the empty pages "
               "reported under IDX-1"),),
    "IDX-3": ((("redirect from https:// to an http:// address", "which this audit did not follow"), "2 page(s) redirect from https:// to an http:// address, which this audit did not follow"),
              (('"redirect to another host"',), "1 page(s) redirect to another host, which this audit did not follow")),
    "IDX-4": ((("are canonicalized to a URL with different content",), "1 page(s) are canonicalized to a URL with different content"),
              (("are canonicalized to a URL with the same content",), "3 page(s) are canonicalized to a URL with the same content")),
    "IDX-9": ((("Google reports the page excluded by noindex", "key page(s))"), "Google reports the page excluded by noindex (2 key page(s))"),
              (("Google reports: {isr.get('coverageState')}",), "Google reports: Crawled - currently not indexed (1 key page(s))"),
              (("Google reports the page blocked by robots.txt",), "Google reports the page blocked by robots.txt (1 key page(s))"),
              (("Google chose a different canonical than the page declares",), "Google chose a different canonical than the page declares (3 key page(s))")),
    "PRF-3": ((("in Google's 'poor' range", '"LCP p75 (ms)"'), "2 URL(s) have real-user LCP p75 (ms) in Google's 'poor' range"),
              ((" (whole-origin data for some)", '"CLS p75"'), "1 URL(s) have real-user CLS p75 in Google's 'poor' range (whole-origin data for some)")),
    "RND-2": ((("declared critical fact(s) {label}", '"appear only after JavaScript runs"'), "2 declared critical fact(s) appear only after JavaScript runs"),
              (("exist only inside markup (script data or attributes), not as visible text",),
               "1 declared critical fact(s) exist only inside markup (script data or attributes), not as visible text")),
    "RND-4": ((("embed content in an iframe; essential content and accessibility are not established",), "3 page(s) embed content in an iframe; essential content and accessibility are not established"),
              (("draw content on a <canvas> with no text equivalent",), "1 page(s) draw content on a <canvas> with no text equivalent"),
              (("show banner-shaped images with no alt text in main content", "(may contain text)"), "2 page(s) show banner-shaped images with no alt text in main content (may contain text)")),
    "RND-5": ((("redirect a cookie-less visitor to a login, consent, age, or country page",), "4 page(s) redirect a cookie-less visitor to a login, consent, age, or country page"),
              (("serve a short page that looks like a consent, login, age, or geo wall instead of the content",),
               "1 page(s) serve a short page that looks like a consent, login, age, or geo wall instead of the content"),
              (("look paywalled but have no isAccessibleForFree structured data",), "2 page(s) look paywalled but have no isAccessibleForFree structured data")),
    # RND-6 on Firecrawl's rendered copies (DECISIONS 299): the title as written, then what was measured.
    "RND-6": ((("have HTML larger than", " (rendered HTML via Firecrawl, not comparable with raw size)"),
               "12 page(s) have HTML larger than 1000 KB (rendered HTML via Firecrawl, not comparable with raw size)"),
              (("The homepage's HTML is", " (rendered HTML via Firecrawl, not comparable with raw size)"),
               "The homepage's HTML is 1400 KB, above 900 KB (rendered HTML via Firecrawl, not comparable with raw size)"),
              (("start their main content more than", " (rendered HTML via Firecrawl, not comparable with raw size)"),
               "30 page(s) start their main content more than 500 KB into the HTML (rendered HTML via Firecrawl, not comparable with raw size)")),
    "STR-4": ((("structured-data {field} differs from the {field} shown on the page", '"price"'), "2 page(s): structured-data price differs from the price shown on the page"),
              (('"product name"',), "1 page(s): structured-data product name differs from the product name shown on the page"),
              (("structured-data {field} is not shown on the page", '"author"'), "4 page(s): structured-data author is not shown on the page"),
              (('"currency"', '"availability"', '"rating"', '"date"'), "1 page(s): structured-data availability differs from the availability shown on the page")),
    "STR-6": ((("looks auto-stamped", '"Last-Modified header"', "the audit day"), "Last-Modified header looks auto-stamped: 48 of 48 pages carry the audit day"),
              (('"sitemap <lastmod>"',), "sitemap <lastmod> looks auto-stamped: 20 of 21 pages carry the audit day"),
              (('"schema dateModified"', "one identical date ("), "schema dateModified looks auto-stamped: 30 of 31 pages carry one identical date (2026-01-05)")),
    "STR-9": ((('"have no <html lang>"',), "3 page(s) have no <html lang>"), (('"have a malformed <html lang> value"',), "1 page(s) have a malformed <html lang> value"),
              (('"have malformed hreflang codes"',), "2 page(s) have malformed hreflang codes"), (('"use relative hreflang URLs"',), "5 page(s) use relative hreflang URLs")),
    "STR-10": ((("have no {tag}", '"meta description"'), "12 page(s) have no meta description"),
               (('"og:title", "og:description", "og:image"',), "19 page(s) have no og:image"),
               (("have an empty {tag}",), "4 page(s) have an empty og:title")),
    # A problem one shared element causes on most pages: one site-wide finding that names the element
    # (maya_audit/shared_elements.py, `TITLES`).
    "STR-7": ((("Shared header/footer: image {src} has no alt text (on {pages} page(s))", '"image_no_alt"'),
               "Shared header/footer: image /media/free-delivery-banner.jpg has no alt text (on 31 page(s))"),),
    "STR-14": ((("Shared header/footer: link to {href} has no text (on {pages} page(s))", '"link_no_text"'),
                "Shared header/footer: link to /account#/favourites has no text (on 50 page(s))"),
               (("Shared header/footer: link “{text}” to {href} has only generic text (on {pages} page(s))", '"link_generic"'),
                "Shared header/footer: link “click here” to /cookie-notice/ has only generic text (on 49 page(s))"),
               # Nameless links in one block the markup names, and an element only one section's pages carry (DECISIONS 198).
               (("“{block}” block: {links} link(s) have no text (on {pages} page(s))", "BLOCK_LINKS_TITLE", 'f"(on {len(urls)} page(s) of /{section}/)"'),
                "“div.post-related” block: 3 link(s) have no text (on 6 page(s) of /blog/)"),
               (('REPEATED_LABEL = "Repeated block"',), "Repeated block: link to /media/photo.jpg has no text (on 31 page(s))"),
               (("Shared template: links to {pattern} have no text (on {pages} page(s)), for example {href}", '"link_no_text_pattern"'),
                "Shared template: links to /media/products/…/*.png have no text (on 36 page(s)), for example /media/products/2026/04/walnut-tray.png")),
    "STR-12": ((("are mostly in another language than they declare ({label})", "written mostly in"),
                "2 page(s) are mostly in another language than they declare (declared English, written mostly in Turkish; declared German, written mostly in English)"),
               (("have section headings in another language than they declare ({label})", "headings in {NAMES.get(m, m)}"),
                "1 page(s) have section headings in another language than they declare (declared Turkish, headings in English)")),
    "STR-13": ((("have unfilled template markers in {where if where != 'title' else 'the title'}", '"JSON-LD"', '"meta tag"', '"link or image URL"', '"visible text"'),
                "3 page(s) have unfilled template markers in the title: {{page_title}}, [[brand]]"),
               ((" and {len(markers) - 6} more",), "9 page(s) have unfilled template markers in visible text: {{a}}, {{b}}, {{c}}, {{d}}, {{e}}, {{f}} and 2 more"),
               (('"JSON-LD"',), "1 page(s) have unfilled template markers in JSON-LD: {{price}}"),
               (('"meta tag"',), "1 page(s) have unfilled template markers in meta tag: {{description}}"),
               (('"link or image URL"',), "2 page(s) have unfilled template markers in link or image URL: {{image_url}}"),
               (("have template markers in the {RAW_ONLY}", "raw HTML only (filled in by the browser)"),
                "4 page(s) have template markers in the raw HTML only (filled in by the browser): {{ title }}")),
    "STR-19": ((("link(s) have no address a crawler can follow (they may still work for visitors through JavaScript)",),
                "30 link(s) have no address a crawler can follow (they may still work for visitors through JavaScript)"),
               (("in the footer look like links but have no address",), "6 link(s) on 12 page(s) in the footer look like links but have no address"),
               (("Shared header/footer: link “{text}” has no address (on {pages} page(s))", '"link_no_address"'),
                "Shared header/footer: link “Cookie settings” has no address (on 47 page(s))"),
               (("Shared header/footer: {links} links have no address ({texts}) (on {pages} page(s))", '"links_no_address"'),
                "Shared header/footer: 7 links have no address (“Departments”, “Diagnosis”, “Treatment”, “Our team” and 3 more) (on 26 page(s))"),
               (("Shared header/footer: {links} links have no address ({texts}) (on {pages} page(s))", "TEXTS_NAMED"),
                "Shared header/footer: 2 links have no address (“Departments”, “Diagnosis”) (on 26 page(s))")),
    "STR-21": ((("No {' / '.join(missing)} page was found among", '"About"', '"Product or service"', '"Contact"', '"FAQ"'),
                "No About / Product or service / Contact / FAQ page was found among the 12 page(s) of the site"),),
    "TSEO-1": ((('"page title(s) below the 10-character guidance band"',), "2 page title(s) below the 10-character guidance band"),
               (('"page title(s) above the 60-character guidance band"',), "31 page title(s) above the 60-character guidance band"),
               (('"meta description(s) below the 70-character guidance band"',), "6 meta description(s) below the 70-character guidance band"),
               (('"meta description(s) above the 160-character guidance band"',), "10 meta description(s) above the 160-character guidance band"),
               (('"heading level jump(s) in the page structure"',), "47 heading level jump(s) in the page structure"),
               (("heading “{text}” (H{to}) comes after an H{before}, skipping a level (on {pages} page(s))", '"heading_jump" if len(before) == 1'),
                "Shared header/footer: heading “Newsletter” (H4) comes after an H2, skipping a level (on 9 page(s))"),
               (("heading “{text}” (H{to}) comes after a higher-level heading, skipping levels (on {pages} page(s))", '"heading_jump_varied"'),
                "Shared header/footer: heading “Support line” (H5) comes after a higher-level heading, skipping levels (on 37 page(s))")),
}
# What `engine_finding_titles` reads where the title is a label put in at run time: only the frame, with a 3 for the label.
ONLY_A_LABEL = {("ACC-2", "robots.txt line 3 (Disallow: 3) blocks 3 bot(s) 3 "), ("ACC-3", "3 on 3 page(s)"),
                ("ACC-4", "Requests with 3 bot user agents 3 on 3 URL(s): 3"), ("IDX-1", "3 URL(s) return a client error (4xx), 3"),
                ("IDX-1", "A page that does not exist 3 (soft 404)"), ("IDX-3", "3 page(s) 3, which this audit did not follow"),
                ("IDX-9", "3 (3 key page(s))"), ("RND-2", "3 declared critical fact(s) 3"), ("RND-4", "3 page(s) 3"), ("RND-5", "3 page(s) 3"),
                ("STR-9", "3 page(s) 3"), ("STR-10", "3 page(s) have no 3"), ("STR-10", "3 page(s) have an empty 3"), ("TSEO-1", "3 3")}


QUALIFIED_TITLE_SAMPLES = [('IDX-6','1 external destination(s) have mixed HEAD/GET evidence; review request context'), ('IDX-6', '1 external destination(s) have HEAD errors; GET navigation is unverified'), ('IDX-1', '2 URL(s) returned repeated empty GET responses in the tested client'), ('IDX-1', '1 URL(s) returned an empty response; persistence is unconfirmed'), ('IDX-5', '3 sitemap URL observation(s) require differentiated review (9 checked)'), ('IDX-5', '3 sitemap URL observation(s) require differentiated review (9 checked); 1 already have IDX-1 retrieval evidence'), ('STR-14', '2 generic-text link occurrence(s) recorded; purpose requires contextual review'), ('STR-2', 'The homepage has no meaningful <h1> text'), ('STR-2', '2 page(s) have no meaningful <h1> text')]


# A qualified title assembled from supported component/text/target evidence (owner fix4).
QUALIFIED_TITLE_SAMPLES += [('STR-14','2 generic-text link occurrence(s) recorded; purpose requires contextual review — div.related; Read more; https://cafe.example/story/1')]

def engine_title_samples():
    """Every finding title the engine can write, as (check id, sample): those read straight from its source, and for
    a title put together at run time a title as the engine writes it (`BUILT_TITLES`, each piece checked against the source)."""
    import maya_audit.checks as checks_package
    import maya_audit.technical_seo as technical_seo
    import maya_audit.index_data as index_data
    import maya_audit.language as language_names
    import maya_audit.firecrawl.reader as firecrawl_reader
    import maya_audit.shared_elements as shared_elements
    import maya_audit.page_words as page_words  # STR-21's basic-page kinds live there (DECISIONS 229)
    sources = "".join(path.read_text(encoding="utf-8") for path in [*Path(checks_package.__file__).parent.glob("*.py"), Path(technical_seo.__file__),
                                                                     Path(language_names.__file__), Path(index_data.__file__), Path(firecrawl_reader.__file__),
                                                                     Path(shared_elements.__file__), Path(page_words.__file__)])
    read = engine_finding_titles()
    assert ONLY_A_LABEL <= set(read), ONLY_A_LABEL - set(read)  # a frame that changed shows up here
    samples = [row for row in read if row not in ONLY_A_LABEL]
    for check_id, rows in BUILT_TITLES.items():
        for pieces, title in rows:
            for piece in pieces:
                assert piece in sources, f"{check_id}: the engine's source no longer holds {piece!r}"
            samples.append((check_id, title))
    return list(samples) + QUALIFIED_TITLE_SAMPLES


def test_every_kind_of_finding_has_its_own_matching_explanation():
    titles = engine_finding_titles()
    # Preserve the existing TSEO scope and include all new shared qualification frames.
    # The original source-title matching and exhaustive unused-note assertions stay intact.
    titles.extend((check, title) for check, title in engine_title_samples()
                  if check == "TSEO-1" or (check, title) in QUALIFIED_TITLE_SAMPLES)
    assert len(titles) > 100 and {check for check, _ in titles} >= {"ACC-1", "ACC-9", "IDX-2", "RND-4", "STR-7", "STR-19", "STR-23", "PRF-2"}
    import maya_audit.checks as checks_package
    sources = "".join(path.read_text(encoding="utf-8") for path in Path(checks_package.__file__).parent.glob("*.py"))
    for check_id, labels in LABELLED.items():
        for label in labels:
            assert label in sources, label
            titles.append((check_id, f"3 page(s) {label}"))
    titles = [(check, title) for check, title in titles if not (check in LABELLED and title in ("3 page(s) 3", "3 link(s) on 3 page(s) 3"))]
    used = set()
    for check_id, title in titles:
        assert catalog.has_own_note(check_id, title), f"{check_id} has no explanation of its own for: {title}"
        specific = [pattern for pattern in catalog.matches(check_id, title) if pattern != "."]
        assert len(specific) <= 1, f"{check_id}: more than one explanation matches {title!r}: {specific}"
        used.update((check_id, pattern) for pattern in catalog.matches(check_id, title)[:1])
    unused = [(check, pattern) for check, variants in catalog._BY_TITLE.items() for pattern, *_ in variants
              if (check, pattern) not in used and pattern != "."]
    # A note nothing in today's source needs is there for reports saved by an earlier engine, and says so (`SAVED_ONLY`).
    assert set(unused) == catalog.SAVED_ONLY, f"explanations that match no finding the engine writes: {sorted(set(unused) - catalog.SAVED_ONLY)}"
    for check_id in {check for check, _ in titles}:
        assert check_id in catalog.known(), check_id
    for values in [*catalog._NOTES.values(), *[v[1:] for variants in catalog._BY_TITLE.values() for v in variants]]:
        owner, effort, why = values
        assert owner in catalog.OWNERS and effort in catalog.EFFORTS and len(why) > 40
        assert not re.search(r"\b(will|guarantee\w*) (rank|improve|increase|boost)", why, re.I)


def test_explanations_are_about_the_finding_they_sit_under():
    """The mismatches that were seen, and their neighbours."""
    def why(check, title):
        return catalog.note(check, title)["why"].lower()
    redirect = why("IDX-2", "No HTTP to HTTPS redirect on example.com, www.example.com")
    assert "redirect" in redirect and "http://" in redirect and "certificate" not in redirect
    assert why("IDX-2", "No HTTP to HTTPS redirect on example.com (http:// answered 200 without redirecting to https://)") == redirect  # a report saved before
    assert "certificate" in why("IDX-2", "TLS certificate is not valid on example.com: certificate has expired")
    assert "expires" in why("IDX-2", "TLS certificate on example.com expires in 7 day(s) (2026-10-14)")
    assert "byte sizes" in why("STR-7", "24% of 84 content image(s) are offered in WebP or AVIF") and "not guaranteed" in why("STR-7", "24% of 84 content image(s) are offered in WebP or AVIF")
    assert "alt text" in why("STR-7", "12 likely meaningful image(s) on 4 page(s) have missing or empty alt text")
    assert "tracking" in why("IDX-6", "4 internal link(s) on 2 page(s) carry tracking parameters (utm_source)")
    assert "broken link" in why("IDX-6", "Link target returns 404, linked from 1 page(s): https://example.com/x")
    assert "same title" in why("IDX-8", "33 indexable pages share the title 'Sale'") and "same content" in why("IDX-8", "4 indexable pages have identical visible text")
    assert "sitemap" in why("IDX-5", "No usable XML sitemap on a site with 80 discovered URLs") and "future" in why("IDX-5", "2 sitemap <lastmod> value(s) are in the future")
    assert "json" in why("STR-3", "2 page(s) have JSON-LD that does not parse") or "parse" in why("STR-3", "2 page(s) have JSON-LD that does not parse")
    assert "who is behind" in why("STR-3", "The homepage has no Organization structured data")
    assert "javascript" in why("RND-1", "Main content is missing from the raw HTML of 3 page(s): it appears only after JavaScript runs")
    assert "soft" not in why("IDX-1", "3 URL(s) return a server error (5xx) on every attempt") and "missing address" in why("IDX-1", "A page that does not exist answers 200 (soft 404)")
