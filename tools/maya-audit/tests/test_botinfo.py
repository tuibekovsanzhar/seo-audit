import os
import re

import httpx
import pytest

from fakeserver import FakeServer, Response, Site
from fakeserver.scenarios import page, robots
from maya_audit.botinfo import UNPUBLISHED_MARKER, BotInfoPageNotReady, check_bot_info_page
from maya_audit.config import CrawlConfig
from maya_audit.crawler import Crawler
from maya_audit.audit import run_audit

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOT_PAGE = open(os.path.join(ROOT, "site", "maya-audit-bot", "index.html"), encoding="utf-8").read()
UA = CrawlConfig().user_agent


def live_config(**overrides):
    return CrawlConfig(allowed_live_hosts=frozenset({"example.com"}), **overrides)


def _mock_public_site(requests):
    def respond(request):
        requests.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n", request=request)
        if request.url.path == "/":
            return httpx.Response(200, text="<html><head><title>Example</title></head><body><main><h1>Example page</h1><p>Public test content.</p></main></body></html>", headers={"content-type": "text/html"}, request=request)
        return httpx.Response(404, request=request)
    return httpx.MockTransport(respond)


def test_live_audit_starts_for_selected_host_without_allowlist_or_bot_page():
    requests = []
    config = CrawlConfig(max_pages=1, request_delay_s=0, robots_samples=1,
                         robots_sample_interval_s=0, render_enabled=False, prf_enabled=False,
                         probes_enabled=False)
    outcome = run_audit("https://example.com/", config, _mock_public_site(requests))
    assert outcome.result.bot_info_check["state"] == "not_configured"
    assert requests[:3] == ["https://example.com/robots.txt", "https://example.com/sitemap.xml",
                            "https://example.com/"]
    assert "https://example.com/" in requests
    assert all("maya-audit-bot" not in url for url in requests)


def test_missing_optional_bot_page_does_not_abort_selected_site(monkeypatch):
    import maya_audit.crawler as crawler_module

    requests = []
    def missing_page(*args, **kwargs):
        raise BotInfoPageNotReady("bot info page returned 404: https://maya.example/maya-audit-bot")
    monkeypatch.setattr(crawler_module, "check_bot_info_page", missing_page)
    config = CrawlConfig(bot_info_url="https://maya.example/maya-audit-bot", max_pages=1,
                         request_delay_s=0, robots_samples=1, robots_sample_interval_s=0,
                         render_enabled=False, prf_enabled=False, probes_enabled=False)
    outcome = run_audit("https://example.com/", config, _mock_public_site(requests))
    assert outcome.result.bot_info_check["state"] == "unavailable"
    assert outcome.result.bot_info_check["crawl_continued"] is True
    assert "https://example.com/" in requests


@pytest.mark.parametrize("url", ["https://maya-audit.invalid/bot", "http://maya.example.org/bot", "https://localhost/bot"])
def test_unusable_optional_bot_info_page_is_reported_and_site_crawl_continues(url):
    requests = []
    config = live_config(bot_info_url=url, max_pages=1, request_delay_s=0, render_enabled=False,
                         prf_enabled=False, probes_enabled=False)
    result = Crawler(config, _mock_public_site(requests)).run("https://example.com/")
    assert result.bot_info_check["state"] == "unavailable"
    assert "https://example.com/" in requests


def test_repo_bot_page_is_rejected_until_its_placeholder_is_replaced():
    assert UNPUBLISHED_MARKER in BOT_PAGE
    with FakeServer(Site({"/bot": Response(body=BOT_PAGE)})) as server:
        with pytest.raises(BotInfoPageNotReady, match=UNPUBLISHED_MARKER):
            check_bot_info_page(server.base_url + "/bot", UA, "Maya-Audit", allow_loopback=True)


def test_half_published_bot_page_is_still_refused():
    """Replacing the contact line but leaving the publishing checklist comment is not enough."""
    half = BOT_PAGE.replace(f"{UNPUBLISHED_MARKER}: add a real contact address", "Contact: crawler@maya.test")
    with FakeServer(Site({"/bot": Response(body=half)})) as server:
        with pytest.raises(BotInfoPageNotReady, match=UNPUBLISHED_MARKER):
            check_bot_info_page(server.base_url + "/bot", UA, "Maya-Audit", allow_loopback=True)


def test_publish_ready_page_matches_the_template_and_passes():
    """The file handed off for publishing is generated from the template, and the crawler accepts it."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("prepare", os.path.join(ROOT, "scripts", "prepare_bot_page.py"))
    prepare = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prepare)

    published = open(os.path.join(ROOT, "site", "maya-audit-bot", "published", "index.html"), encoding="utf-8").read()
    assert published == prepare.build(BOT_PAGE, prepare.DEFAULT_CONTACT, prepare.DEFAULT_NOTE)  # no drift
    assert UNPUBLISHED_MARKER not in published and "<!--" not in published
    with FakeServer(Site({"/bot": Response(body=published)})) as server:
        evidence = check_bot_info_page(server.base_url + "/bot", UA, "Maya-Audit", allow_loopback=True)
    assert evidence["status"] == 200 and evidence["mentions_product_token"]
    assert not evidence["contains_unpublished_marker"]


def test_page_for_maya_own_domain_drops_the_test_deployment_note():
    """The copy handed over for withmaya.ai is the same page without the test-host disclosure.

    `published/` is served from a test deployment and says so. On Maya's own domain that sentence
    would be false, so the handover copy is generated with no note — and pinned here so the two
    cannot drift apart or quietly swap places (LG-02).
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location("prepare", os.path.join(ROOT, "scripts", "prepare_bot_page.py"))
    prepare = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prepare)

    handover = open(os.path.join(ROOT, "site", "maya-audit-bot", "for-withmaya.ai", "index.html"), encoding="utf-8").read()
    assert handover == prepare.build(BOT_PAGE, prepare.DEFAULT_CONTACT, None)
    assert "test deployment" not in handover
    assert UNPUBLISHED_MARKER not in handover and "<!--" not in handover
    assert "@" in prepare.DEFAULT_CONTACT and prepare.DEFAULT_CONTACT.endswith("withmaya.ai")
    with FakeServer(Site({"/maya-audit-bot": Response(body=handover)})) as server:
        evidence = check_bot_info_page(server.base_url + "/maya-audit-bot", UA, "Maya-Audit", allow_loopback=True)
    assert evidence["status"] == 200 and evidence["mentions_product_token"]
    assert not evidence["contains_unpublished_marker"]


def test_published_bot_page_passes_with_evidence():
    published = re.sub(r"<!--.*?-->", "", BOT_PAGE, flags=re.S).replace(
        f"{UNPUBLISHED_MARKER}: add a real contact address", "Contact: crawler@maya.test"
    )
    with FakeServer(Site({"/bot": Response(body=published)})) as server:
        evidence = check_bot_info_page(server.base_url + "/bot", UA, "Maya-Audit", allow_loopback=True)
        assert evidence["status"] == 200
        assert evidence["mentions_product_token"] and not evidence["contains_unpublished_marker"]
        assert server.requests[0].user_agent == UA


@pytest.mark.parametrize("response", [Response(status=404, body="Maya-Audit"), Response(body="<html>some other bot</html>")])
def test_missing_or_unrelated_bot_page_is_refused(response):
    with FakeServer(Site({"/bot": response})) as server:
        with pytest.raises(BotInfoPageNotReady):
            check_bot_info_page(server.base_url + "/bot", UA, "Maya-Audit", allow_loopback=True)


def test_crawler_never_sends_cookies_back():
    site = Site({
        "/robots.txt": robots("User-agent: *\nAllow: /\n"),
        "/": Response(body=page("Home", "/next").body, headers={"Set-Cookie": "session=abc123; Path=/"}),
        "/next": page("Next"),
    })
    with FakeServer(site) as server:
        Crawler(CrawlConfig(request_delay_s=0)).run(server.base_url + "/")
        cookies = {r.path: r.cookie for r in server.requests}
    assert "/next" in cookies
    assert all(value is None for value in cookies.values())
