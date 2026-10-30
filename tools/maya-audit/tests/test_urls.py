import pytest

from maya_audit.config import CrawlConfig
from maya_audit.crawler import Crawler
from maya_audit.urls import (UnsafeTargetError, detect_templates, host_allowed, is_allowed_origin_move,
                             normalize_url, validate_public_target)


def test_normalize():
    assert normalize_url("HTTPS://Example.COM:443/a#frag") == "https://example.com/a"
    assert normalize_url("../b?x=1", "http://example.com/a/c") == "http://example.com/b?x=1"
    assert normalize_url("http://example.com") == "http://example.com/"
    assert normalize_url("mailto:hi@example.com") is None
    assert normalize_url("http://example.com:8080/") == "http://example.com:8080/"


def test_live_host_guard():
    assert host_allowed("http://127.0.0.1:9000/", frozenset())
    assert host_allowed("http://localhost/", frozenset())
    assert not host_allowed("https://example.com/", frozenset())
    assert host_allowed("https://www.example.com/", frozenset({"example.com"}))


def test_crawler_can_audit_the_selected_host_without_a_separate_allowlist():
    import httpx

    requests = []
    def respond(request):
        requests.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /", request=request)
        return httpx.Response(200, text="<html><title>Example</title><body><h1>Example</h1></body></html>",
                              headers={"content-type": "text/html"}, request=request)
    # render_discovery off: this test lists the crawl's own requests, without the homepage render.
    result = Crawler(CrawlConfig(max_pages=1, request_delay_s=0, bot_info_url=None, render_discovery=False),
                     httpx.MockTransport(respond)).run("https://example.com/")
    assert result.pages[0].status == 200
    # Sitemap discovery is a deliberate request between robots.txt and page fetches.
    assert requests == ["https://example.com/robots.txt", "https://example.com/sitemap.xml",
                        "https://example.com/"]


def test_origin_moves():
    assert is_allowed_origin_move("http://example.com/", "https://example.com/")
    assert is_allowed_origin_move("https://example.com/", "https://www.example.com/")
    assert not is_allowed_origin_move("https://example.com/", "https://other.com/")
    assert not is_allowed_origin_move("https://example.com/", "http://example.com/")


def test_private_dns_target_is_rejected(monkeypatch):
    import socket

    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs:
                        [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 443))])
    with pytest.raises(UnsafeTargetError, match="non-public destination"):
        validate_public_target("https://internal.example/")


def test_templates_are_grouped():
    urls = [f"https://e.com/blog/post-{i}" for i in range(3)] + ["https://e.com/docs/a", "https://e.com/docs/b", "https://e.com/about"]
    groups = detect_templates(urls)
    assert len(groups["/blog/{id}"]) == 3
    assert len(groups["/docs/{slug}"]) == 2
    assert groups["/about"] == ["https://e.com/about"]


def test_registrable_domain_decides_where_a_www_variant_is_meaningful():
    """Found by the first live crawl: www.<host> is not an address for a host that is already a subdomain."""
    from maya_audit.index_data import www_variant
    from maya_audit.urls import is_registrable_domain

    assert is_registrable_domain("example.com") and is_registrable_domain("enpara.com")
    assert is_registrable_domain("example.com.tr") and is_registrable_domain("example.co.uk")
    assert not is_registrable_domain("blog.example.com")
    assert not is_registrable_domain("tuibekovsanzhar.github.io")  # *.github.io cannot cover www.<user>.github.io
    assert not is_registrable_domain("127.0.0.1")

    assert www_variant("example.com") == "www.example.com"
    assert www_variant("www.enpara.com") == "enpara.com"
    assert www_variant("tuibekovsanzhar.github.io") is None  # no phantom S1 for a host nobody types
    assert www_variant("acme.netlify.app") is None
    assert www_variant("localhost") == "www.localhost"  # loopback test servers still exercise the check
