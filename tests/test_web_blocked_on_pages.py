"""DECISIONS 288 (changed 2026-10-30): Maya's crawler blocked by 429 on pages while robots.txt is served. Firecrawl, with
the basic proxy, reads on as the page reader; the report says so plainly, keeps ACC-9's AI-crawler warning, is not a
draft for that alone, and the web page names the block instead of "rate limit" or "try again later". Offline: a fake
site, a fake Firecrawl, the 60-second wait recorded rather than slept."""
from __future__ import annotations

import json

import httpx
import pytest

pytest.importorskip("fastapi")

from maya_audit.fetcher import Fetcher  # noqa: E402
from test_firecrawl import Firecrawl  # noqa: E402
from test_web_app import API, SHOP, Site, get, plan, start, web  # noqa: E402,F401
from test_web_firecrawl import PAGES, ROOT, services  # noqa: E402

ROBOTS = "User-agent: *\nDisallow: /private/\n"


def blocked_on_pages(request):
    if request.url.path == "/robots.txt":
        return httpx.Response(200, text=ROBOTS, headers={"content-type": "text/plain"})
    if request.url.path.endswith(".xml"):
        return httpx.Response(404, headers={"content-type": "text/html"}, text="<title>x</title>")
    return httpx.Response(429, headers={"content-type": "text/html", "server": "cloudflare", "cf-ray": "a5-IST",
                                        "retry-after": "60"}, text="<html><title>Too many requests</title></html>")


@pytest.fixture
def no_waits(monkeypatch):
    monkeypatch.setattr(Fetcher, "sleep", lambda self, seconds: True)


def run(web, tmp_path, **options):
    api = Firecrawl(PAGES)
    client = web(site=Site(respond=blocked_on_pages), firecrawl=services(tmp_path, api))
    return client, api, start(client, plan(client, **options))


def every_text(client, audit, language="en"):
    report = client.get(f"{API}/audits/{audit['id']}/result").json()
    shown = json.dumps(get(client, audit, "/summary"), ensure_ascii=False)
    printed = client.get(f"{API}/audits/{audit['id']}/print?full=true&lang={language}").text
    return report, shown, printed


def test_firecrawl_reads_on_with_the_basic_proxy_and_the_report_says_so(web, tmp_path, no_waits):
    client, api, audit = run(web, tmp_path)
    report, shown, printed = every_text(client, audit)
    reader = report["firecrawl"]
    assert reader["used"] and reader["purpose"] == "main page reader" and reader["pages_read"] >= 2
    assert {body["proxy"] for body in api.bodies} == {"basic"} and not reader["owner_approved_bypass"]
    assert f"{ROOT}/private/accounts" not in api.urls  # robots.txt disallows it: never asked for
    fallback = reader["crawl_blocked"]["homepage_fallback"]
    assert fallback["continued"] is True and fallback["maya_blocked"] == "blocked for Maya's crawler (429 on pages)"
    note = report["audit_status"]["direct_access"]["note"]
    assert note.startswith("Maya's own crawler was blocked (429 on pages)") and f"{reader['pages_read']} page(s) read through Firecrawl" in note
    # ACC-9 keeps its own finding and the AI-crawler warning.
    [acc9] = [f for c in report["checks"] if c["check_id"] == "ACC-9" for f in c["findings"]]
    assert acc9["rule_id"] == "acc9.blocked_429" and acc9["title"].endswith("AI crawlers may get the same treatment")
    # Using Firecrawl does not make it a draft: the gate judges it as usual.
    assert report["release_gate"]["decision"] in ("PASS", "CONDITIONAL")
    assert not [v for v in report["release_gate"]["violations"] if v["rule"] == "RG-14"]
    assert client.get(f"{API}/audits/{audit['id']}/downloads/markdown").status_code == 200


def test_the_web_page_names_the_block_in_both_languages(web, tmp_path, no_waits):
    client, _, audit = run(web, tmp_path)
    for language, says, never in (
            ("en", "Blocked for Maya's crawler (429 on pages)", ('"Rate-limited"', "Cloudflare (rate limit)", "try again later", "rate-limited Maya's crawler")),
            ("tr", "Maya'nın tarayıcısı engellendi (sayfalarda 429)", ('"hız sınırına takıldı"', "Cloudflare (hız sınırı)", "daha sonra yeniden deneyin", "(İngilizce)"))):
        assert client.put(f"{API}/session/language", json={"language": language}).status_code == 200
        _, shown, printed = every_text(client, audit, language)
        assert says in shown, language
        # The heading, badge, reader line and steps the owner named; the stop code `rate_limit` stays a code.
        for phrase in never:
            assert phrase not in shown and phrase not in printed, (language, phrase)
    client.put(f"{API}/session/language", json={"language": "en"})


def test_the_stealth_proxy_still_needs_the_owners_tick(web, tmp_path):
    """The plan refuses a non-basic proxy without the owner's approval: nothing reads past protection on its own."""
    client = web(site=Site(respond=blocked_on_pages), firecrawl=services(tmp_path, Firecrawl(PAGES)))
    made = plan(client, firecrawl_proxy="enhanced")
    assert made["firecrawl"]["blocked"]["code"] == "firecrawl_options" and "owner" in made["firecrawl"]["blocked"]["message"]
