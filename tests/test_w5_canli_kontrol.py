"""The client-report skill's live-check script goes through the engine's guards (review E-R8 / H41).

It used to send plain `http.client` requests to any address, follow redirects anywhere, never read robots.txt, and
offer a Googlebot user agent. These tests run it against a loopback fake site only.
"""

import importlib.util
import json
from pathlib import Path

import pytest

from fakeserver import FakeServer, Response, Site
from fakeserver.scenarios import robots

SCRIPT = Path(__file__).resolve().parents[1] / ".agents/skills/maya-audit-rapor/scripts/canli_kontrol.py"


@pytest.fixture(scope="module")
def canli():
    spec = importlib.util.spec_from_file_location("canli_kontrol_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _site() -> Site:
    return Site({
        "/robots.txt": robots("User-agent: *\nDisallow: /private\n\nUser-agent: Maya-Audit\nDisallow: /maya-only\n"),
        "/": Response(body="<html><head><title>Ana sayfa</title><meta name='description' content='Kısa açıklama'>"
                           "</head><body><h1>Merhaba</h1><p>Metin</p></body></html>"),
        "/old": Response(301, headers={"Location": "/"}),
        "/to-private": Response(302, headers={"Location": "/private/page"}),
        "/private/page": Response(body="<title>secret</title>"),
        "/maya-only": Response(body="<title>x</title>"),
    })


def _paths(server) -> list[str]:
    return [request.path for request in server.requests]


def test_robots_is_read_first_and_a_browser_identity_is_used(canli):
    with FakeServer(_site()) as server:
        checker = canli.LiveChecker(allow_loopback=True, delay_s=0)
        try:
            chain, body = checker.fetch(server.base_url + "/old")
        finally:
            checker.close()
        assert [hop["status"] for hop in chain] == [301, 200]
        assert b"Merhaba" in body
        assert _paths(server) == ["/robots.txt", "/old", "/"]
        assert all("Googlebot" not in request.user_agent for request in server.requests)
        assert all(request.user_agent == canli.BROWSER_UA for request in server.requests)


def test_a_disallowed_url_is_never_requested_even_through_a_redirect(canli):
    with FakeServer(_site()) as server:
        checker = canli.LiveChecker(allow_loopback=True, delay_s=0)
        try:
            with pytest.raises(canli.RobotsSkip):
                checker.fetch(server.base_url + "/private/page")
            with pytest.raises(canli.RobotsSkip):
                checker.fetch(server.base_url + "/to-private")
            # A group for Maya's own token is obeyed too, although the identity sent is a browser's.
            with pytest.raises(canli.RobotsSkip):
                checker.fetch(server.base_url + "/maya-only")
        finally:
            checker.close()
        assert "/private/page" not in _paths(server) and "/maya-only" not in _paths(server)
        assert _paths(server).count("/robots.txt") == 1


def test_an_unreadable_robots_txt_stops_requests_to_that_site(canli):
    site = Site({"/robots.txt": robots("busy", status=503), "/": Response(body="<title>x</title>")})
    with FakeServer(site) as server:
        checker = canli.LiveChecker(allow_loopback=True, delay_s=0)
        try:
            with pytest.raises(canli.RobotsSkip):
                checker.fetch(server.base_url + "/")
        finally:
            checker.close()
        assert _paths(server) == ["/robots.txt"]


def test_the_default_refuses_loopback_and_private_addresses(canli, capsys):
    with FakeServer(_site()) as server:
        assert canli.main(["durum", server.base_url + "/", "http://10.0.0.1/", "http://192.168.1.1/"]) == 1
        assert server.requests == []
    out = capsys.readouterr().out
    assert out.count("REDDEDİLDİ") == 3
    assert "Sonuç: 0/3" in out


def test_there_is_no_googlebot_option(canli):
    with pytest.raises(SystemExit):
        canli.main(["durum", "http://example.com/", "--ua", "googlebot"])
    assert "googlebot" not in SCRIPT.read_text(encoding="utf-8").lower().replace("search-engine bot", "")


def test_bilgi_writes_page_facts_marked_untrusted(canli, tmp_path):
    with FakeServer(_site()) as server:
        cards = tmp_path / "cards.json"
        url = server.base_url + "/"
        cards.write_text(json.dumps({"cards": [{"where": {"examples": [url, server.base_url + "/private/page"]}}]}),
                         encoding="utf-8")
        checker = canli.LiveChecker(allow_loopback=True, delay_s=0)
        try:
            assert canli.main(["bilgi", str(cards)], checker=checker) == 0
        finally:
            checker.close()
        facts = json.loads(cards.read_text(encoding="utf-8"))["page_facts"]
        assert facts[url]["title"] == "Ana sayfa" and facts[url]["h1"] == "Merhaba"
        assert facts[url]["description"] == "Kısa açıklama" and facts[url]["untrusted"] is True
        assert server.base_url + "/private/page" not in facts
        assert "/private/page" not in _paths(server)
