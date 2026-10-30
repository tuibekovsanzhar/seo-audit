"""Firecrawl: the guarded client, the content reader for blocked sites, and the rendering fallback.

No request reaches Firecrawl: every test passes an in-memory transport, and tests/conftest.py refuses any
connection that is not loopback. No key is read from the user's files: conftest points the .env lookup at nothing.
"""
import json
import socket

import httpx
import pytest

from maya_audit.audit import run_audit
from maya_audit.config import CrawlConfig
from maya_audit.dataforseo.cache import Cache
from maya_audit.dataforseo.ledger import Ledger
from maya_audit.firecrawl import (ApprovalRequired, FirecrawlClient, FirecrawlError, FirecrawlKey, InsufficientCredits, NoKey,
                                  Options, PossiblyBilled, ZeroDataRetentionUnavailable, load_key, settings)
from maya_audit.firecrawl import panel, reader
from maya_audit.firecrawl.client import PageCapReached
from maya_audit.report import build_report, run_outcome
from test_review_fixes import QUIET

KEY = FirecrawlKey("fc-made-up-key-0000")
HTML = {"content-type": "text/html; charset=utf-8"}
ROBOTS_TEXT = "User-agent: *\nDisallow: /private/\n"


class Firecrawl:
    """A made-up Firecrawl: records every request body and answers from a table of pages."""

    def __init__(self, pages=None, responder=None):
        self.bodies, self.pages, self.responder = [], pages or {}, responder

    def __call__(self, request):
        assert request.url.host == "api.firecrawl.dev" and request.url.path == "/v2/scrape" and request.method == "POST"
        assert request.headers["authorization"] == KEY.authorization()
        body = json.loads(request.content)
        self.bodies.append(body)
        if self.responder:
            answer = self.responder(body)
            if answer is not None:
                return answer
        url = body["url"]
        if url not in self.pages:
            return httpx.Response(200, json={"success": True, "data": {"rawHtml": "<html><title>404</title></html>", "metadata": {"statusCode": 404, "url": url}}})
        return httpx.Response(200, json={"success": True, "data": {"rawHtml": self.pages[url], "metadata": {"statusCode": 200, "url": url, "contentType": "text/html"}}})

    @property
    def urls(self):
        return [body["url"] for body in self.bodies]


def client_for(tmp_path, api, **options):
    defaults = dict(approved_credits=1000, daily_credits=1000)
    return FirecrawlClient(KEY, Ledger(tmp_path / "fc" / settings.LEDGER_NAME), Cache(tmp_path / "fc" / settings.CACHE_NAME),
                           transport=httpx.MockTransport(api), **{**defaults, **options})


# -- the key and the settings ------------------------------------------------------------------------------------
def test_the_key_is_read_like_the_dataforseo_credentials_and_never_shown(tmp_path, monkeypatch):
    assert load_key() is None  # conftest: no real environment, no real .env
    env = tmp_path / ".env"
    env.write_text(f'# keys\nMAYA_AUDIT_FIRECRAWL_API_KEY="{KEY.value}"\nUNRELATED=1\n')
    monkeypatch.setenv("MAYA_AUDIT_ENV_FILE", str(env))
    assert load_key().value == KEY.value
    monkeypatch.setenv("MAYA_AUDIT_FIRECRAWL_API_KEY", "fc-from-the-environment")
    assert load_key().value == "fc-from-the-environment"  # a real environment variable wins over the file
    assert KEY.value not in repr(KEY) and KEY.value not in str(KEY) and KEY.redact(f"sent {KEY.value}") == "sent [redacted]"
    from maya_audit.config import SECRET_FIELDS
    assert "firecrawl_api_key" in SECRET_FIELDS


def test_defaults_are_basic_proxy_zero_data_retention_fifty_pages_and_no_dollar_rate(monkeypatch):
    options = Options()
    assert (options.proxy, options.max_pages, options.owner_approved_bypass, options.allow_without_zero_data_retention) == ("basic", 50, False, False)
    assert settings.USD_PER_CREDIT is None and settings.usd_per_credit() is None
    estimate = options.estimate(audit_page_cap=500)
    assert estimate == {"max_requests": 51, "max_pages": 50, "credits_per_page": 2, "max_credits": 102, "usd_per_credit": None, "max_usd": None}
    assert Options(max_pages=200).estimate(50)["max_pages"] == 50  # never more than the audit's own page cap
    monkeypatch.setenv("MAYA_AUDIT_FIRECRAWL_USD_PER_CREDIT", "0.001")
    assert Options().estimate(500)["max_usd"] == pytest.approx(0.102)
    monkeypatch.setenv("MAYA_AUDIT_FIRECRAWL_USD_PER_CREDIT", "not a number")
    assert settings.usd_per_credit() is None
    monkeypatch.setenv("MAYA_AUDIT_FIRECRAWL_DAILY_CREDITS", "40")
    assert settings.daily_credits() == 40


def test_stronger_proxies_need_the_owners_approval():
    assert Options(proxy="basic").problem() is None
    for proxy in ("enhanced", "auto"):
        assert "site owner has approved" in Options(proxy=proxy).problem()
        assert Options(proxy=proxy, owner_approved_bypass=True).problem() is None
    assert "must be one of" in Options(proxy="stealth", owner_approved_bypass=True).problem()  # the old name is not accepted silently
    assert "between 1 and 500" in Options(max_pages=0).problem() and "between 1 and 500" in Options(max_pages=501).problem()


# -- the client ------------------------------------------------------------------------------------------------------
def test_every_request_names_basic_proxy_asks_for_zero_data_retention_and_turns_firecrawls_cache_off(tmp_path):
    api = Firecrawl({"https://shop.test/": "<html><title>Shop</title></html>"})
    client = client_for(tmp_path, api)
    page = client.scrape("https://shop.test/")
    [body] = api.bodies
    assert body["proxy"] == "basic" and body["zeroDataRetention"] is True
    assert body["storeInCache"] is False and body["maxAge"] == 0 and body["formats"] == ["rawHtml"] and body["onlyMainContent"] is False
    assert body["skipTlsVerification"] is False
    assert (page.status, page.cached, page.credits, page.proxy, page.zero_data_retention) == (200, False, 2, "basic", True)
    [call] = client.calls
    assert call == {**call, "url": "https://shop.test/", "credits": 2, "billing_status": "charged", "from_cache": False}
    assert client.ledger.spent_today() == 2 and KEY.value not in json.dumps(client.calls) and "Shop" not in json.dumps(client.calls)
    enhanced = client_for(tmp_path / "e", Firecrawl(), proxy="enhanced", owner_approved_bypass=True)
    enhanced.scrape("https://shop.test/x")
    assert enhanced.consent.owner_approved
    with pytest.raises(ValueError):
        client_for(tmp_path / "bad", Firecrawl(), proxy="stealth")


def test_a_page_is_served_from_mayas_own_cache_for_one_day_at_no_cost_and_a_resume_keeps_its_copies_longer(tmp_path, monkeypatch):
    api = Firecrawl({"https://shop.test/": "<html><title>Shop</title></html>"})
    first = client_for(tmp_path, api, audit_id="audit-one")
    first.scrape("https://shop.test/")
    again = client_for(tmp_path, api, audit_id="audit-one")  # the same audit (its pages are re-read within the run)
    page = again.scrape("https://shop.test/")
    assert page.cached and page.credits == 0 and len(api.bodies) == 1 and again.requests_sent == 0
    assert again.ledger.spent_today() == 2 and again.calls[0]["billing_status"] == "cache"
    # A new audit reads the site again, even the same day (A16, W1): it shows what was just fixed.
    other = client_for(tmp_path, api, audit_id="audit-two")
    assert not other.scrape("https://shop.test/").cached and len(api.bodies) == 2
    assert settings.CACHE_LIFETIME_S == 24 * 3600 and settings.RESUME_CACHE_LIFETIME_S == 7 * 24 * 3600
    import time as clock
    real = clock.time
    monkeypatch.setattr(clock, "time", lambda: real() + 2 * 24 * 3600)  # two days later
    resumed = client_for(tmp_path, api, approved_credits=0)  # a resumed audit: nothing to spend, its own copies still serve
    assert resumed.scrape("https://shop.test/").cached and len(api.bodies) == 2
    # A resumed command-line crawl has a new audit id and credits left, and still reads its earlier copies (A16).
    assert client_for(tmp_path, api, resumed=True, audit_id="cli-resume").scrape("https://shop.test/").cached
    fresh = client_for(tmp_path, api)  # a new audit reads the site again, so the client's fixes show
    assert not fresh.scrape("https://shop.test/").cached and len(api.bodies) == 3


def test_the_page_cap_the_confirmed_credits_and_the_daily_budget_each_stop_requests(tmp_path):
    api = Firecrawl()
    capped = client_for(tmp_path / "cap", api, max_pages=2)
    for n in range(3):  # two pages, and one more for robots.txt
        capped.scrape(f"https://shop.test/{n}")
    with pytest.raises(PageCapReached, match="request allowance of 3.*2 plus one bootstrap reserve"):  # total including the existing reserve; threshold unchanged
        capped.scrape("https://shop.test/3")
    sent = len(api.bodies)
    approved = client_for(tmp_path / "approved", api, approved_credits=4)
    approved.scrape("https://shop.test/a")
    approved.scrape("https://shop.test/b")
    with pytest.raises(ApprovalRequired, match="above the 4 confirmed"):
        approved.scrape("https://shop.test/c")
    daily = client_for(tmp_path / "daily", api, daily_credits=3)
    daily.scrape("https://shop.test/a")
    with pytest.raises(FirecrawlError, match="Firecrawl daily budget reached"):
        daily.scrape("https://shop.test/b")
    assert len(api.bodies) == sent + 3 and daily.ledger.spent_today() == 2
    with pytest.raises(NoKey):
        FirecrawlClient(None, Ledger(tmp_path / "k" / "l.jsonl"), None, approved_credits=10, transport=httpx.MockTransport(api)).scrape("https://shop.test/")
    stopped = client_for(tmp_path / "stopped", api, should_stop=lambda: True)
    with pytest.raises(FirecrawlError, match="stopped on request"):
        stopped.scrape("https://shop.test/")
    assert len(api.bodies) == sent + 3


def test_a_refusal_of_zero_data_retention_stops_everything_and_is_never_retried_without_it(tmp_path):
    api = Firecrawl(responder=lambda body: httpx.Response(403, json={"success": False, "error": "Zero Data Retention is not enabled for this team. Contact help@firecrawl.dev"})
                    if body.get("zeroDataRetention") else None)
    client = client_for(tmp_path, api)
    with pytest.raises(ZeroDataRetentionUnavailable, match="zero data retention not available"):
        client.scrape("https://shop.test/")
    with pytest.raises(ZeroDataRetentionUnavailable):
        client.scrape("https://shop.test/other")  # nothing further is sent
    assert len(api.bodies) == 1 and all(body["zeroDataRetention"] is True for body in api.bodies)
    assert client.ledger.spent_today() == 0 and client.calls[0]["billing_status"] == "failed"
    # Only a client the person explicitly allowed for that audit leaves it out, and it costs one credit less.
    waived = client_for(tmp_path / "waived", api, allow_without_zero_data_retention=True)
    page = waived.scrape("https://shop.test/")
    assert "zeroDataRetention" not in api.bodies[-1] and page.zero_data_retention is False and page.credits == 1


@pytest.mark.parametrize("answer,error,billing,spent", [
    (lambda body: httpx.Response(402, json={"success": False, "error": "Insufficient credits"}), InsufficientCredits, "failed", 0),
    (lambda body: httpx.Response(429, json={"success": False, "error": "Rate limit exceeded"}), FirecrawlError, "failed", 0),
    (lambda body: httpx.Response(401, json={"success": False, "error": "Unauthorized: Invalid token"}), FirecrawlError, "failed", 0),
    (lambda body: httpx.Response(500, json={"success": False, "error": "All scraping engines failed"}), FirecrawlError, "failed", 0),
    (lambda body: httpx.Response(200, text="not json"), PossiblyBilled, "possibly_billed", 2),
    (lambda body: httpx.Response(200, json={"success": True, "data": {"markdown": "x"}}), PossiblyBilled, "possibly_billed", 2),
])
def test_failures_are_accounted_and_nothing_is_sent_twice(tmp_path, answer, error, billing, spent):
    api = Firecrawl(responder=answer)
    client = client_for(tmp_path, api)
    with pytest.raises(error) as raised:
        client.scrape("https://shop.test/")
    assert len(api.bodies) == 1 and client.calls[0]["billing_status"] == billing and client.ledger.spent_today() == spent
    assert KEY.value not in str(raised.value)
    if error is InsufficientCredits:
        assert "not Maya's own daily budget" in str(raised.value)


def test_a_timeout_keeps_its_reservation_and_a_refused_connection_costs_nothing(tmp_path):
    def timeout(request):
        raise httpx.ReadTimeout("made up")

    def refused(request):
        raise httpx.ConnectError("made up")
    slow = FirecrawlClient(KEY, Ledger(tmp_path / "a" / "l.jsonl"), None, approved_credits=10, daily_credits=10, transport=httpx.MockTransport(timeout))
    with pytest.raises(PossiblyBilled, match="may have been charged and was not retried"):
        slow.scrape("https://shop.test/")
    assert slow.ledger.spent_today() == 2
    down = FirecrawlClient(KEY, Ledger(tmp_path / "b" / "l.jsonl"), None, approved_credits=10, daily_credits=10, transport=httpx.MockTransport(refused))
    with pytest.raises(FirecrawlError, match="could not be reached"):
        down.scrape("https://shop.test/")
    assert down.ledger.spent_today() == 0


# -- the content reader for a blocked site -------------------------------------------------------------------------
@pytest.fixture
def no_lookups(monkeypatch):
    real = socket.getaddrinfo
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, *a, **k: (_ for _ in ()).throw(socket.gaierror(8, "not known"))
                        if str(host).endswith(".test") else real(host, *a, **k))


def challenged(request):
    return httpx.Response(403, headers={**HTML, "server": "cloudflare", "cf-mitigated": "challenge", "cf-ray": "a1-FRA"},
                          text="<html><title>Just a moment...</title><body>Checking your browser</body></html>")


def doc(title, body, head=""):
    return (f'<!doctype html><html lang="en"><head><title>{title}</title>{head}</head><body><header><nav><a href="/">Home</a></nav></header>'
            f"<main>{body}</main></body></html>")


TEXT = "<p>" + "Maximum builds solar panels for homes and small businesses across the country. " * 12 + "</p>"
SITE = {
    "https://bank.test/robots.txt": f"<html><body><pre>{ROBOTS_TEXT}</pre></body></html>",
    "https://bank.test/": doc("Solar Panels", "<h1>Welcome</h1>" + TEXT + '<a href="/about">About</a> <a href="/products">Products</a> '
                              '<a href="/private/accounts">Accounts</a> <a href="https://other.example/x">Partner</a> <a href="#">More</a>'),
    "https://bank.test/about": doc("Solar Panels", "<h1>About</h1>" + TEXT + '<a href="/contact">Contact</a>'),
    "https://bank.test/products": doc("Products | Bank", "<h1>Products</h1>" + TEXT),
    "https://bank.test/contact": doc("Contact | Bank", "<h1>Contact</h1><p>Call us.</p>"),
}


def blocked_audit(transport=challenged, missing_policy=False, **options):
    outcome = run_audit("https://bank.test/", CrawlConfig(**{**QUIET, "max_pages": 10, **options}), httpx.MockTransport(transport))
    if missing_policy:
        outcome.result.robots_policy_by_origin.clear()
    outcome.by_id = lambda: {check.check_id: check for check in outcome.checks}
    return outcome


def test_firecrawl_reads_a_blocked_sites_content_and_never_touches_access_results(tmp_path, no_lookups):
    outcome = blocked_audit(missing_policy=True)
    cfg = CrawlConfig(**{**QUIET, "max_pages": 10})
    before = {check.check_id: (check.status, check.summary, len(check.findings)) for check in outcome.checks}
    gates_before = [(g.check_id, g.state, g.summary) for g in outcome.gates]
    assert before["STR-1"][0] == "not_assessed" and before["ACC-9"][0] == "findings"
    api = Firecrawl(SITE)
    client = client_for(tmp_path, api)
    info = reader.apply(outcome, cfg, client, Options())
    after = outcome.by_id()

    # Maya's crawler stays the access test: its verdict, its gates and every access check are exactly as they were.
    assert run_outcome(outcome.result, outcome.gates)[1] == "DEGRADED" and [(g.check_id, g.state, g.summary) for g in outcome.gates] == gates_before
    untouched = [cid for cid in before if cid not in reader.CONTENT_CHECKS]
    assert {"ACC-1", "ACC-2", "ACC-9", "IDX-1", "IDX-2", "IDX-3", "IDX-4", "PRF-1", "PRF-2", "RND-1"} <= set(untouched)
    assert all((after[cid].status, after[cid].summary, len(after[cid].findings)) == before[cid] for cid in untouched)
    assert [p.url for p in outcome.result.pages] == ["https://bank.test/"] and outcome.result.pages[0].status == 403  # crawl record unchanged
    assert set(info["checks_from_firecrawl"]) == set(reader.CONTENT_CHECKS) and not set(info["checks_from_firecrawl"]) & set(untouched)

    # robots.txt was refused to Maya, so it was read through Firecrawl first, and its rules were obeyed.
    assert api.urls[0] == "https://bank.test/robots.txt" and info["robots"]["mode"] == "parsed"
    assert set(api.urls[1:]) == {"https://bank.test/", "https://bank.test/about", "https://bank.test/products", "https://bank.test/contact"}
    assert "https://bank.test/private/accounts" not in api.urls and info["skipped_by_robots"] == 1
    assert not [url for url in api.urls if "other.example" in url]  # only the audited site
    assert info["used"] and info["pages_read"] == 4 and info["purpose"] == "content reader for a blocked site"
    assert info["proxy"] == "basic" and info["owner_approved_bypass"] is False and info["zero_data_retention"]["status"] == "applied"
    assert info["credits"] == {"per_page": 2, "estimated_max": 22, "used_or_reserved": 10} and info["usd"]["used_or_reserved"] is None
    assert "only credits are shown" in info["usd"]["note"] and "AI crawlers may not see this content" in info["notice"]

    # The content checks now have results, each labelled with where its pages came from.
    titles = after["STR-1"]
    assert titles.status == "findings" and titles.summary.startswith("Source: Firecrawl (Maya's crawler was blocked). ")
    [shared] = [f for f in titles.findings if "shared" in f.title]
    assert shared.notes[0].startswith("Source: Firecrawl (Maya's crawler was blocked). AI crawlers may not see this content")
    assert shared.evidence["source"] == {"reader": "firecrawl", "why": "Maya's crawler was blocked"}
    assert sorted(shared.scope["urls"]) == ["https://bank.test/", "https://bank.test/about"]
    assert after["STR-19"].findings and after["STR-18"].findings  # the new small-site checks run on these pages too
    labelled = [check for check in outcome.checks if check.check_id in reader.CONTENT_CHECKS]
    assert all(check.summary.startswith("Source: Firecrawl") and check.evidence["source"]["reader"] == "firecrawl" for check in labelled)
    assert all(f.notes[0].startswith("Source: Firecrawl") for check in labelled for f in check.findings)

    report = build_report(outcome.result, outcome.gates, outcome.checks)
    text = json.dumps(report) + json.dumps({k: v for k, v in info.items() if k != "view_pages"})
    assert KEY.value not in text and "view_pages" in info and len(info["view_pages"]) == 4
    assert report["crawl"]["pages"][0]["status"] == 403 and len(report["crawl"]["pages"]) == 1


def test_firecrawl_is_not_used_when_mayas_crawler_read_the_site(tmp_path, no_lookups):
    def open_site(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS_TEXT, headers={"content-type": "text/plain"})
        return httpx.Response(200, headers=HTML, text=SITE.get(str(request.url), doc("x", "<h1>x</h1>"))) if str(request.url) in SITE else httpx.Response(404, headers=HTML, text="x")
    outcome = blocked_audit(open_site)
    before = [(c.check_id, c.status, c.summary) for c in outcome.checks]
    api = Firecrawl(SITE)
    info = reader.apply(outcome, CrawlConfig(**{**QUIET, "max_pages": 10}), client_for(tmp_path, api), Options())
    assert api.bodies == [] and info["used"] is False and "Firecrawl was not used" in info["reason"]
    assert [(c.check_id, c.status, c.summary) for c in outcome.checks] == before and info["credits"]["used_or_reserved"] == 0


@pytest.mark.parametrize("status", [401, 403, 404, 410, 451])
@pytest.mark.parametrize("missing_policy", [False, True])
def test_4xx_robots_challenge_allows_content_without_changing_access(tmp_path, no_lookups, status, missing_policy):
    def target(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(status, text="<html>challenge</html>")
        return challenged(request)
    outcome = blocked_audit(target, missing_policy=missing_policy)
    before = [(c.check_id, c.summary) for c in outcome.checks if c.check_id.startswith("ACC-")]
    api = Firecrawl(SITE, responder=lambda body: httpx.Response(200, json={"success": True, "data": {
        "rawHtml": "<html>challenge</html>", "metadata": {"statusCode": status}}})
        if body["url"].endswith("/robots.txt") else None)
    info = reader.apply(outcome, CrawlConfig(**QUIET), client_for(tmp_path, api), Options())
    assert info["used"] and info["robots"]["mode"] == "allow_all"
    assert info["robots"]["status"] == status
    assert ("https://bank.test/robots.txt" in api.urls) == missing_policy
    assert before == [(c.check_id, c.summary) for c in outcome.checks if c.check_id.startswith("ACC-")]
    assert any("Robots policy" in line for line in panel.summary_lines(info))


@pytest.mark.parametrize("status", [429, 500, 503, None])
@pytest.mark.parametrize("missing_policy", [False, True])
def test_unreachable_or_rate_limited_robots_stops_firecrawl(tmp_path, no_lookups, status, missing_policy):
    from maya_audit.robots import policy_from_response
    outcome = blocked_audit(missing_policy=missing_policy)
    if not missing_policy:
        outcome.result.robots_policy_by_origin[outcome.result.origin] = policy_from_response(
            outcome.result.origin + "/robots.txt", status, None, b"", 500, [])
    api = Firecrawl(responder=lambda body: httpx.Response(200, json={"success": True, "data": {
        "rawHtml": "error", "metadata": {"statusCode": status}}}))
    info = reader.apply(outcome, CrawlConfig(**QUIET), client_for(tmp_path, api), Options())
    # No status at all is "no answer reached this computer": not a rule of the site's, so the reader asks for robots.txt
    # itself. Its answer has no status either, so the rules stay unknown and no page is requested.
    assert not info["used"] and info["robots"]["mode"] == ("not_checked" if status is None else "disallow_all")
    assert api.urls == (["https://bank.test/robots.txt"] if missing_policy or status is None else [])
    assert "no page was requested" in info["reason"]
    if status == 429:
        assert "back off and retry later" in info["reason"]


def test_a_site_without_robots_txt_is_read_and_firecrawl_being_blocked_too_is_said(tmp_path, no_lookups):
    outcome = blocked_audit(missing_policy=True)
    wall = "<html><title>Just a moment...</title><body>challenge</body></html>"
    api = Firecrawl({"https://bank.test/": wall}, responder=lambda body: httpx.Response(
        200, json={"success": True, "data": {"rawHtml": "not found", "metadata": {"statusCode": 404}}}) if body["url"].endswith("/robots.txt") else None)
    info = reader.apply(outcome, CrawlConfig(**{**QUIET, "max_pages": 10}), client_for(tmp_path, api), Options())
    assert info["robots"]["mode"] == "allow_all" and info["used"] is False
    assert info["reason"] == "Firecrawl basic was also blocked: 1 page(s) tried, 1 came back as a challenge or block page"
    assert info["pages_blocked_for_firecrawl_too"] == 1 and reader.also_blocked(info)
    assert info["pages"][0]["outcome"] == "blocked" and api.bodies[1]["proxy"] == "basic"  # and it did not escalate by itself
    lines = panel.summary_lines(info)
    assert lines[0].startswith("Firecrawl basic was also blocked") and "never switched on automatically" in lines[1]
    assert not any(line.startswith("Not used") for line in lines)


def test_no_document_from_firecrawl_counts_as_blocked_too_but_an_account_refusal_does_not(tmp_path, no_lookups):
    no_robots = lambda body: httpx.Response(200, json={"success": True, "data": {"rawHtml": "", "metadata": {"statusCode": 404}}}) \
        if body["url"].endswith("/robots.txt") else None
    failing = lambda body: no_robots(body) or httpx.Response(500, json={"success": False, "error": "All scraping engines failed"})
    info = reader.apply(blocked_audit(missing_policy=True), CrawlConfig(**{**QUIET, "max_pages": 10}), client_for(tmp_path, Firecrawl(responder=failing)), Options())
    assert info["used"] is False and not reader.also_blocked(info) and info["pages"][0]["outcome"] == "failed"
    assert "could not load the page as a website" in info["reason"]
    assert info["errors"][0]["kind"] == "provider_load_failure"
    assert info["credits"]["used_or_reserved"] == 2  # robots.txt was answered; the failed page cost nothing
    broke = lambda body: no_robots(body) or httpx.Response(402, json={"success": False, "error": "Insufficient credits"})
    info2 = reader.apply(blocked_audit(missing_policy=True), CrawlConfig(**{**QUIET, "max_pages": 10}), client_for(tmp_path / "2", Firecrawl(responder=broke)), Options())
    assert not reader.also_blocked(info2) and info2["reason"] == "Firecrawl could not read the site either"
    assert panel.summary_lines(info2)[0].startswith("Not used: ")


def test_reading_stops_after_the_first_three_unreadable_pages_instead_of_paying_for_every_address(tmp_path, no_lookups):
    def site(request):  # Maya may read robots.txt and the sitemap; every page is challenged
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\nSitemap: https://bank.test/sitemap.xml\n", headers={"content-type": "text/plain"})
        if request.url.path == "/sitemap.xml":
            urls = "".join(f"<url><loc>https://bank.test/p{n}</loc></url>" for n in range(8))
            return httpx.Response(200, text=f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>', headers={"content-type": "application/xml"})
        return challenged(request)
    outcome = blocked_audit(site)
    wall = lambda body: httpx.Response(200, json={"success": True, "data": {"rawHtml": "<html><title>Just a moment...</title></html>", "metadata": {"statusCode": 403}}})
    api = Firecrawl(responder=wall)
    info = reader.apply(outcome, CrawlConfig(**{**QUIET, "max_pages": 10}), client_for(tmp_path, api), Options())
    assert len(api.urls) == 3 and info["used"] is False and reader.also_blocked(info)
    assert "the first 3 pages asked for came back unreadable" in info["stopped_because"]
    assert info["reason"].startswith("Firecrawl basic was also blocked: 3 page(s) tried, 3 came back as a challenge")


def test_the_page_cap_and_the_owner_approval_are_obeyed_and_recorded(tmp_path, no_lookups):
    outcome = blocked_audit(missing_policy=True)
    api = Firecrawl(SITE)
    info = reader.apply(outcome, CrawlConfig(**{**QUIET, "max_pages": 10}), client_for(tmp_path, api, max_pages=2), Options(max_pages=2))
    assert info["pages_read"] == 2 and len(api.urls) == 3 and info["page_cap"] == 2  # robots.txt and two pages
    approved = Options(proxy="enhanced", owner_approved_bypass=True)
    api2 = Firecrawl(SITE)
    info2 = reader.apply(blocked_audit(missing_policy=True), CrawlConfig(**{**QUIET, "max_pages": 10}), client_for(tmp_path / "2", api2, proxy="enhanced", owner_approved_bypass=True), approved)
    assert {body["proxy"] for body in api2.bodies} == {"enhanced"} and info2["proxy"] == "enhanced" and info2["owner_approved_bypass"] is True
    assert info2["options"]["owner_approved_bypass"] is True


def test_a_zero_data_retention_refusal_leaves_the_audit_as_it_was_and_asks_for_a_decision(tmp_path, no_lookups):
    outcome = blocked_audit(missing_policy=True)
    before = [(c.check_id, c.status, c.summary) for c in outcome.checks]
    api = Firecrawl(SITE, responder=lambda body: httpx.Response(400, json={"success": False, "error": "zeroDataRetention is not enabled for your team"})
                    if body.get("zeroDataRetention") else None)
    info = reader.apply(outcome, CrawlConfig(**{**QUIET, "max_pages": 10}), client_for(tmp_path, api), Options())
    assert len(api.bodies) == 1 and info["used"] is False and info["needs_decision"] == "zero_data_retention"
    assert info["zero_data_retention"] == {"requested": True, "applied": False, "status": "not available"}
    assert "zero data retention not available" in info["reason"] and [(c.check_id, c.status, c.summary) for c in outcome.checks] == before
    assert info["credits"]["used_or_reserved"] == 0
    # With the person's explicit choice for this audit, it proceeds without it, and the report says so.
    waived = Options(allow_without_zero_data_retention=True)
    info2 = reader.apply(blocked_audit(missing_policy=True), CrawlConfig(**{**QUIET, "max_pages": 10}),
                         client_for(tmp_path / "w", api, allow_without_zero_data_retention=True), waived)
    assert info2["used"] and info2["zero_data_retention"] == {"requested": True, "applied": False, "status": "waived by the user for this audit"}
    assert info2["credits"]["per_page"] == 1 and all("zeroDataRetention" not in body for body in api.bodies[1:])


# -- the rendering fallback --------------------------------------------------------------------------------------------
def test_firecrawl_renders_the_sample_when_the_local_browser_cannot_start(tmp_path, no_lookups, monkeypatch):
    shell = '<!doctype html><html lang="en"><head><title>App</title></head><body><div id="root"></div><script src="/app.js"></script></body></html>'

    def site(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n", headers={"content-type": "text/plain"})
        return httpx.Response(200, headers=HTML, text=shell) if request.url.path == "/" else httpx.Response(404, headers=HTML, text="x")
    import maya_audit.render as render_module
    monkeypatch.setattr(render_module, "collect_render_data", None, raising=False)
    cfg = CrawlConfig(**{**QUIET, "max_pages": 5, "render_enabled": True})
    import maya_audit.audit as audit_module
    monkeypatch.setattr(audit_module, "collect_render_data", lambda fetcher, crawl, config, keys: render_module.RenderData(
        "raw_html_only", "Chromium could not start (made up for this test)"))
    outcome = run_audit("https://app.test/", cfg, httpx.MockTransport(site))
    by_id = {c.check_id: c for c in outcome.checks}
    assert not [f for f in by_id["RND-1"].findings if "appears only after JavaScript" in f.title]
    rendered = doc("App", "<h1>Orders</h1>" + TEXT)
    api = Firecrawl({"https://app.test/": rendered})
    info = reader.apply(outcome, cfg, client_for(tmp_path, api), Options(read_blocked=False, render_fallback=True))
    assert api.urls == ["https://app.test/"] and api.bodies[0]["waitFor"] == 1500 and api.bodies[0]["proxy"] == "basic"
    assert info["used"] and info["purpose"] == "rendering fallback" and info["rendered"][0]["outcome"] == "rendered"
    rnd1 = next(c for c in outcome.checks if c.check_id == "RND-1")
    [finding] = [f for f in rnd1.findings if "Main content is missing from the raw HTML" in f.title]
    assert finding.notes[0].startswith("Source: Firecrawl rendered these pages (the local browser could not start)")
    assert rnd1.summary.startswith("Source: Firecrawl rendered these pages") and outcome.result.render.browser == "Firecrawl (basic proxy)"
    assert set(info["checks_from_firecrawl"]) == {f"RND-{n}" for n in range(1, 8)}
    assert next(c for c in outcome.checks if c.check_id == "ACC-9").status == "pass"  # nothing else moved

    working = run_audit("https://app.test/", CrawlConfig(**{**QUIET, "max_pages": 5}), httpx.MockTransport(site))  # rendering switched off by choice
    api2 = Firecrawl({"https://app.test/": rendered})
    info2 = reader.apply(working, CrawlConfig(**{**QUIET, "max_pages": 5}), client_for(tmp_path / "2", api2), Options(read_blocked=False, render_fallback=True))
    assert api2.bodies == [] and info2["used"] is False


# -- the command line ----------------------------------------------------------------------------------------------------
def client_ledger(tmp_path):
    """Credits the command line recorded in its ledger (conftest gives every test its own ~/.maya-audit)."""
    import os
    from pathlib import Path
    return Ledger(Path(os.environ["MAYA_AUDIT_HOME"]) / settings.LEDGER_NAME).spent_today()


def cli_run(monkeypatch, tmp_path, argv, api=None, site=challenged, key=True):
    from maya_audit import cli
    from maya_audit.firecrawl import client as client_module
    env = tmp_path / ".env"
    env.write_text(f"MAYA_AUDIT_FIRECRAWL_API_KEY={KEY.value}\n" if key else "")
    monkeypatch.setenv("MAYA_AUDIT_ENV_FILE", str(env))
    monkeypatch.setattr(client_module, "TRANSPORT", httpx.MockTransport(api or Firecrawl(SITE)))
    monkeypatch.setattr(cli, "run_audit", lambda url, cfg: run_audit(url, CrawlConfig(**{**QUIET, "max_pages": cfg.max_pages}), httpx.MockTransport(site)))
    return cli.main(["crawl", "https://bank.test/", "--max-pages", "10", *argv])


def test_cli_dry_run_prints_the_plan_and_sends_and_crawls_nothing(monkeypatch, tmp_path, capsys):
    api = Firecrawl(SITE)
    monkeypatch.setattr("maya_audit.cli.run_audit", lambda *a, **k: pytest.fail("a dry run must not crawl"))
    from maya_audit import cli
    from maya_audit.firecrawl import client as client_module
    monkeypatch.setattr(client_module, "TRANSPORT", httpx.MockTransport(api))
    assert cli.main(["crawl", "https://bank.test/", "--firecrawl-dry-run", "--firecrawl-max-pages", "20"]) == 0
    out = capsys.readouterr().out
    assert "Pages at most:        20" in out and "Credits at most:      46 (2 per page)" in out and "Proxy:                basic" in out
    assert "Zero data retention:  requested on every page" in out and "unknown (no dollar price per credit is configured)" in out
    assert "Dry run: no Firecrawl request was sent and the site was not crawled." in out and api.bodies == []


def test_cli_needs_a_confirmation_for_every_use_and_refuses_stronger_proxies_without_approval(monkeypatch, tmp_path, capsys, no_lookups):
    api = Firecrawl(SITE)
    # A stronger proxy is still confirmed, to the exact number; the basic proxy of a normal run is not asked about.
    assert cli_run(monkeypatch, tmp_path, ["--firecrawl", "--firecrawl-proxy", "enhanced", "--firecrawl-owner-approved"], api) == 2
    assert "needs a confirmation of its cost. Pass --firecrawl-approve-up-to 26" in capsys.readouterr().err
    assert cli_run(monkeypatch, tmp_path, ["--firecrawl", "--firecrawl-approve-up-to", "5"], api) == 2
    assert "could use 26 credits, above the 5 confirmed" in capsys.readouterr().err
    assert cli_run(monkeypatch, tmp_path, ["--firecrawl", "--firecrawl-proxy", "enhanced", "--firecrawl-approve-up-to", "26"], api) == 2
    assert "only when the site owner has approved" in capsys.readouterr().err
    assert cli_run(monkeypatch, tmp_path, ["--firecrawl", "--firecrawl-approve-up-to", "26"], api, key=False) == 2
    assert "Firecrawl key is not set" in capsys.readouterr().err
    assert api.bodies == []


def test_cli_reads_a_blocked_site_through_firecrawl_and_labels_every_output(monkeypatch, tmp_path, capsys, no_lookups):
    api = Firecrawl(SITE)
    json_path, md_path = tmp_path / "r.json", tmp_path / "r.md"
    code = cli_run(monkeypatch, tmp_path, ["--json", str(json_path), "--markdown", str(md_path)], api)  # a key is set: no flag, no confirmation
    assert code == 0  # read through Firecrawl: the challenge of Maya's own crawler is a note, not a failed audit
    out = capsys.readouterr().out
    assert "Firecrawl (a third-party page reader; Maya's own crawler remains the access test)" in out
    assert "Pages read through Firecrawl: 4 (cap 10)" in out and "AI crawlers may not see this content" not in out
    assert "to read the pages of every audit" in out
    assert "Pages read  4 (via Firecrawl)" in out and "Result      COMPLETED" in out and "Credits at most:      26 (2 per page)" in out
    report = json.loads(json_path.read_text(encoding="utf-8"))
    section = report["firecrawl"]
    from maya_audit.findings import check_id_key
    assert section["checks_from_firecrawl"] == sorted(section["checks_from_firecrawl"], key=check_id_key)
    assert section["checks_from_firecrawl"].index("STR-2") < section["checks_from_firecrawl"].index("STR-10")
    assert "**Pages read:** 4 (via Firecrawl)" in md_path.read_text(encoding="utf-8") and client_ledger(tmp_path) == 12  # five pages and the sitemap, asked for once the homepage was read
    assert report["schema_version"] == "1.20" and section["used"] and section["proxy"] == "basic" and section["pages_read"] == 4
    assert section["zero_data_retention"]["status"] == "applied" and section["owner_approved_bypass"] is False
    from maya_audit import schema
    assert set(section) <= set(schema.FIRECRAWL_KEYS) and "view_pages" not in section
    str1 = next(c for c in report["checks"] if c["check_id"] == "STR-1")
    assert str1["summary"].startswith("Source: Firecrawl. ") and str1["findings"][0]["notes"][0] == "Source: Firecrawl."
    [note] = next(c for c in report["checks"] if c["check_id"] == "ACC-9")["findings"]
    assert note["severity"] == "Info" and note["title"].startswith("Cloudflare challenged Maya's direct crawler on 1 of 1 request(s).")
    assert report["crawl"]["pages"][0]["status"] == 403 and section["purpose"] == "main page reader"
    markdown = md_path.read_text(encoding="utf-8")
    assert "## Firecrawl (third-party page reader)" in markdown and "Source: Firecrawl." in markdown and "was blocked)" not in markdown
    assert KEY.value not in out + json_path.read_text(encoding="utf-8") + markdown
    assert all(body["proxy"] == "basic" and body["zeroDataRetention"] is True for body in api.bodies)


def test_cli_owner_approval_and_the_zero_data_retention_waiver_are_explicit_flags_and_recorded(monkeypatch, tmp_path, capsys, no_lookups):
    api = Firecrawl(SITE)
    json_path = tmp_path / "r.json"
    assert cli_run(monkeypatch, tmp_path, ["--firecrawl", "--firecrawl-proxy", "auto", "--firecrawl-owner-approved", "--firecrawl-allow-without-zdr",
                                           "--firecrawl-approve-up-to", "13", "--json", str(json_path)], api) == 0
    out = capsys.readouterr().out
    assert "Proxy:                auto (the site owner approved bypassing bot protection)" in out
    assert "NOT requested (waived for this audit: page content may be stored by Firecrawl)" in out and "Credits at most:      13 (1 per page)" in out
    section = json.loads(json_path.read_text(encoding="utf-8"))["firecrawl"]
    assert section["proxy"] == "auto" and section["owner_approved_bypass"] is True
    assert section["zero_data_retention"]["status"] == "waived by the user for this audit"
    assert all(body["proxy"] == "auto" and "zeroDataRetention" not in body for body in api.bodies)


def test_cli_without_firecrawl_flags_never_touches_it(monkeypatch, tmp_path, capsys, no_lookups):
    api = Firecrawl(SITE)
    json_path = tmp_path / "r.json"
    for argv, key in ((["--no-firecrawl"], True), ([], False)):  # switched off for this audit, or no key on this computer
        assert cli_run(monkeypatch, tmp_path, [*argv, "--json", str(json_path), "--overwrite"], api, key=key) == 1
        assert api.bodies == [] and "firecrawl" not in json.loads(json_path.read_text(encoding="utf-8")) and "Firecrawl" not in capsys.readouterr().out
    monkeypatch.setenv("MAYA_AUDIT_FIRECRAWL", "off")  # or switched off for the computer
    assert cli_run(monkeypatch, tmp_path, ["--json", str(json_path), "--overwrite"], api) == 1 and api.bodies == []


@pytest.mark.parametrize("status", [429, 503])
def test_maya_stops_pages_and_reports_robots_policy(no_lookups, status):
    paths = []
    def target(request):
        paths.append(request.url.path)
        return httpx.Response(status, text="try later")
    outcome = blocked_audit(target)
    assert set(paths) == {"/robots.txt"}
    assert not outcome.result.pages
    assert outcome.result.stop_reason.value == ("rate_limit" if status == 429 else "robots_disallowed")
    check = outcome.by_id()["ACC-1"]
    assert check.evidence["applied_policy"]["status"] == status
    assert "Applied policy:" in check.summary


def test_maya_robots_redirect_policy_is_reused_by_firecrawl(tmp_path, no_lookups):
    def target(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(302, headers={"location": "/rules.txt"})
        if request.url.path == "/rules.txt":
            return httpx.Response(200, text=ROBOTS_TEXT)
        return challenged(request)
    outcome = blocked_audit(target)
    assert outcome.result.robots[0]["redirect_hops"] == ["https://bank.test/rules.txt"]
    api = Firecrawl(SITE)
    info = reader.apply(outcome, CrawlConfig(**QUIET), client_for(tmp_path, api), Options())
    assert info["used"] and info["robots"]["mode"] == "parsed"
    assert info["robots"]["source"] == "Maya's own crawler"
    assert "https://bank.test/robots.txt" not in api.urls
    assert "https://bank.test/private/accounts" not in api.urls
    assert info["skipped_by_robots"] == 1
