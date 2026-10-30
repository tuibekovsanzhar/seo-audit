"""Review G06, worker gx2: the platform is the one most pages show (a more specific one beats what it is built on), and
more platforms and CDNs are recognised from what the crawler keeps."""

from __future__ import annotations

import pytest

from maya_audit.site_platform import recognise
from test_false_alarms import html, site


def platform_of(pages_html, headers=None):
    result, pages = site(pages_html)
    for page in pages:
        page.headers = headers or {}
    return recognise(result)


def script(src):
    return html("<p>x</p>", head=f'<script src="{src}"></script>')


def test_the_platform_on_most_pages_wins_over_one_embedded_wordpress_page():
    shop = script("/theme/9f2c/js/storefront/storefront.js")
    pages = {"/": shop, "/a": shop, "/b": shop, "/blog/": script("/blog/wp-content/themes/x/main.js")}
    found = platform_of(pages)
    assert found["name"] == "Shopware" and "3 of 4 pages read" in found["signals"][0]


def test_woocommerce_beats_wordpress_even_on_fewer_pages():
    wp = script("/wp-content/themes/x/main.js")
    pages = {"/": wp, "/a": wp, "/b": wp, "/shop/": script("/wp-content/plugins/woocommerce/assets/js/cart.js")}
    assert platform_of(pages)["name"] == "WooCommerce"


@pytest.mark.parametrize("page, name", [
    (script("/static/version1712/frontend/Magento/luma/en_US/mage/cookies.js"), "Magento"),
    (html("<p>x</p>", head='<meta name="generator" content="PrestaShop">'), "PrestaShop"),
    (script("/catalog/view/javascript/jquery/jquery.js"), "OpenCart"),
    (script("https://static1.squarespace.com/static/vta/x/scripts/site-bundle.js"), "Squarespace"),
    (html("<p>x</p>", head='<meta name="generator" content="Webflow">'), "Webflow"),
    (html("<p>x</p>", head='<meta name="generator" content="Drupal 10 (https://www.drupal.org)">'), "Drupal"),
    (script("/_next/static/chunks/main-1a2b.js"), "Next.js"),
])
def test_more_platforms_are_named(page, name):
    assert platform_of({"/": page})["name"] == name


@pytest.mark.parametrize("headers, cdn", [
    ({"server": "AkamaiGHost"}, "Akamai"), ({"x-cache": "Miss from cloudfront"}, "CloudFront"),
    ({"server": "Sucuri/Cloudproxy"}, "Sucuri"), ({"x-iinfo": "10-123-0 0NNN RT(1 2)"}, "Imperva"),
    ({"x-cdn": "Imperva"}, "Imperva"), ({"server": "Vercel"}, "Vercel"), ({"server": "Netlify"}, "Netlify"),
    ({"x-served-by": "cache-fra-etou8220123-FRA"}, "Fastly"),
])
def test_cdns_are_named_from_their_headers(headers, cdn):
    assert platform_of({"/": html("<p>x</p>")}, headers)["cdn"] == cdn


def test_a_bare_ticimax_word_does_not_name_ticimax():
    assert platform_of({"/": script("/js/ticimax-slider-clone.js")}) is None
