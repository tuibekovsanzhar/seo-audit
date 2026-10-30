"""PRF-1's CDN cache rule and HSTS advice, read the same way for every CDN (review G05, G14; gx3)."""

from types import SimpleNamespace

import pytest

from maya_audit.checks import perf


def _page(url, headers, status=200):
    return SimpleNamespace(url=url, headers=headers, status=status, ttfb_ms=800.0, content_type="text/html", view="raw")


def _pages(headers, n=3):
    return [_page(f"https://e.com/{i}", headers) for i in range(n)]


@pytest.mark.parametrize("headers, cdn", [
    ({"x-cache": "TCP_MISS from a1.deploy.akamaitechnologies.com", "server": "AkamaiGHost"}, "Akamai"),
    ({"x-cache": "Miss from cloudfront", "via": "1.1 abc.cloudfront.net (CloudFront)"}, "CloudFront"),
    ({"x-cache": "MISS", "x-served-by": "cache-fra-1"}, "Fastly"),
    ({"x-vercel-cache": "MISS", "x-vercel-id": "fra1::abc"}, "Vercel"),
    ({"cache-status": "Netlify Edge; fwd=miss", "x-nf-request-id": "01H"}, "Netlify"),
    ({"cache-status": "ExampleCDN; fwd=uri-miss"}, "ExampleCDN"),
    ({"cf-cache-status": "DYNAMIC", "server": "cloudflare"}, "Cloudflare"),
])
def test_each_cdn_that_went_to_the_origin_on_private_html_is_one_info_finding(headers, cdn):
    [finding] = perf._cdn_cache_findings(_pages({**headers, "cache-control": "private, no-store"}), set(), None)
    assert finding.severity.value == "Info" and finding.evidence["cdn"] == {cdn: 3}


def test_the_last_hop_of_x_cache_decides_miss_then_hit_is_a_hit():
    headers = {"x-cache": "MISS, HIT", "x-served-by": "cache-fra-1, cache-par-2", "cache-control": "private"}
    assert perf.cache_state(headers) == "hit"
    assert perf._cdn_cache_findings(_pages(headers), set(), None) == []


def test_no_cache_alone_means_revalidate_not_uncacheable():
    headers = {"cf-cache-status": "DYNAMIC", "cache-control": "no-cache, max-age=0"}
    assert perf._cdn_cache_findings(_pages(headers), set(), None) == []


def test_a_cache_age_above_zero_is_a_copy_served_from_the_cache():
    assert perf.cache_state({"x-cache": "MISS", "age": "41"}) == "hit"


def test_without_a_named_cdn_private_html_is_an_observation_only():
    pages = _pages({"cache-control": "private, max-age=0", "server": "nginx", "x-cache": "MISS"})
    assert perf.cdn_name(pages[0].headers) is None
    assert perf._cdn_cache_findings(pages, set(), None) == []
    seen = perf.cache_observation(pages)
    assert seen["cdn"] == {"none named": 3} and seen["cache_control"] == {"private, max-age=0": 3}


def test_one_page_served_from_the_edge_among_a_few_is_not_nearly_every_page():
    pages = _pages({"cf-cache-status": "DYNAMIC", "cache-control": "private"}, n=4)
    pages.append(_page("https://e.com/hit", {"cf-cache-status": "HIT", "cache-control": "private"}))
    assert perf._cdn_cache_findings(pages, set(), None) == []
    assert perf._cdn_cache_findings(pages, set(), None, share=0.8)


def _hsts(headers):
    page = SimpleNamespace(url="https://e.com/", status=200, headers=headers, view="raw", depth=0,
                           reproduce=lambda: "curl -i https://e.com/")
    result = SimpleNamespace(pages=[page], origin="https://e.com", start_url="https://e.com/")
    return perf._hsts_findings(result)


def test_hsts_advice_names_no_vendor_menu_and_adds_one_cdn_sentence_only_behind_a_cdn():
    [plain] = _hsts({"server": "nginx"})
    assert "Cloudflare" not in plain.how_to_fix and perf.HSTS_CDN not in plain.how_to_fix
    assert plain.scope["kind"] == "sitewide" and plain.severity.value == "Info"
    [behind] = _hsts({"server": "AkamaiGHost"})
    assert behind.how_to_fix == perf.HSTS_FIX + " " + perf.HSTS_CDN and "Akamai" not in behind.how_to_fix


def test_the_new_fix_sentences_have_turkish_wording():
    from maya_audit_web import wording
    for text in (perf.CACHE_FIX, perf.HSTS_FIX, perf.HSTS_FIX + " " + perf.HSTS_CDN):
        shown, ok = wording.fix(text, "tr")
        assert ok and shown != text
