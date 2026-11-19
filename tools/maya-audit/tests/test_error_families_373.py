"""DECISIONS 373 (Efsa, A2): each decision is tested against its error family, not only the variant the expert saw:
other forms of the same error and a healthy counter-example that must still be reported. Families: the brand name,
link lists, the hidden <h1>, the heading language. Fake sites, a mock transport and a local headless browser only."""
from __future__ import annotations

import json

import httpx
import pytest

from maya_audit.audit import run_audit
from maya_audit.config import CrawlConfig
from maya_audit.language import heading_language
from maya_audit.models import to_jsonable
from maya_audit.report import build_report
from test_deadline_hosted_hardening import QUIET
from test_firecrawl import no_lookups  # noqa: F401

HTML = {"content-type": "text/html; charset=utf-8"}
TEXT = "<p>" + "Fresh snacks and dried fruit delivered to your door, with weekly offers and recipes. " * 8 + "</p>"


def site(routes: dict[str, str], start="https://shop.test"):
    def respond(request):
        path = request.url.path
        if path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        if path in routes:
            body = routes[path]
            if body.startswith("REDIRECT "):
                return httpx.Response(301, headers={"location": start + body.split(" ", 1)[1]})
            return httpx.Response(200, headers=HTML, text=body)
        return httpx.Response(404, headers=HTML, text="<h1>yok</h1>")
    config = CrawlConfig(**{**QUIET, "max_pages": 30, "sitemap_check_max": 0})
    outcome = run_audit(start + "/", config, httpx.MockTransport(respond))
    report = json.loads(json.dumps(to_jsonable(build_report(outcome.result, outcome.gates, outcome.checks))))
    return report, {f.get("rule_id"): f for c in report["checks"] for f in c.get("findings") or []}


def org(name):
    return ('<script type="application/ld+json">{"@context":"https://schema.org","@type":"Organization","name":"'
            + name + '","url":"https://shop.test/"}</script>')


def page(title, body, head="", lang="en"):
    return (f'<!doctype html><html lang="{lang}"><head><meta charset=utf-8><title>{title}</title>{head}</head>'
            f"<body><main>{body}{TEXT}</main></body></html>")


# ---------------------------------------------------------------- the brand name

def test_product_section_language_version_and_sub_brand_titles_are_not_brand_names(no_lookups):  # noqa: F811
    links = "".join(f'<a href="{p}">{p}</a>' for p in ("/p/almond", "/p/cashew", "/kampanyalar", "/kampanyalar/a", "/en",
                                                       "/business", "/business/a"))
    routes = {
        "/": page("Nature Shop", "<h1>Nature Shop</h1>" + links, org("Nature Shop")),
        # a product name before the brand (MMI)
        "/p/almond": page("Almond Mix | Almond Mix Nature Shop", "<h1>Almond Mix</h1>", org("Nature Shop")),
        "/p/cashew": page("Cashew Mix | Cashew Mix Nature Shop", "<h1>Cashew Mix</h1>", org("Nature Shop")),
        # a section name before the brand
        "/kampanyalar": page("Kampanyalar | Nature Shop", "<h1>Kampanyalar</h1>", org("Nature Shop")),
        "/kampanyalar/a": page("Kampanyalar - Nature Shop", "<h1>A</h1>", org("Nature Shop")),
        # a language version whose Organization name is its page title (Enpara)
        "/en": page("Homepage", "<h1>Home</h1>", org("Homepage")),
        # a sub-brand
        "/business": page("Nature Shop Business", "<h1>Business</h1>", org("Nature Shop Business")),
        "/business/a": page("Offers | Nature Shop Business", "<h1>Offers</h1>", org("Nature Shop Business")),
    }
    report, found = site(routes)
    names = found.get("str5.names")
    shown = json.dumps((names or {}).get("evidence", {}).get("variants") or [], ensure_ascii=False)
    for wrong in ("Almond Mix Nature Shop", "Cashew Mix Nature Shop", "Kampanyalar", "Homepage"):
        assert wrong not in shown, wrong


def test_a_brand_really_written_two_ways_is_still_reported(no_lookups):  # noqa: F811
    links = "".join(f'<a href="/{i}">{i}</a>' for i in range(4))
    routes = {"/": page("Home | Acme Market", "<h1>Acme Market</h1>" + links, org("Acme Market"))}
    routes.update({f"/{i}": page(f"Page {i} | ACME Foods Ltd", f"<h1>P{i}</h1>", org("ACME Foods Ltd")) for i in range(2)})
    routes.update({f"/{i}": page(f"Sayfa {i} | Akme Gıda", f"<h1>S{i}</h1>", org("Akme Gıda")) for i in range(2, 4)})
    _, found = site(routes)
    assert "str5.names" in found  # the healthy counter-example: a real second name


# ---------------------------------------------------------------- link lists: each kind names its link

def test_broken_redirecting_textless_and_parameterised_links_each_name_their_link(no_lookups):  # noqa: F811
    from maya_audit import final, link_places
    from maya_audit.example_rows import attach
    body = ('<h1>Links</h1><a href="/gone">Old offer</a> <a href="/old">Recipes</a> '
            '<a href="/p/1"><img src="/i.png" alt=""></a></main><footer>'
            '<a href="https://social.test/shop?igsh=abc123">instagram</a></footer><main>')
    routes = {"/": page("Shop", body), "/old": "REDIRECT /recipes", "/recipes": page("Recipes", "<h1>Recipes</h1>"),
              "/p/1": page("Product", "<h1>Product</h1>")}
    report, found = site(routes)
    attach(report)
    places = link_places.places(report)
    broken = [r for rows in places.values() for r in rows if r.get("links_to", "").endswith("/gone")]
    assert broken and broken[0]["link_text"] == "Old offer" and broken[0]["source"] == "https://shop.test/"
    params = places.get("IDX-6") or []
    assert params and params[0]["link_text"] == "instagram" and params[0]["parameters"] == ["igsh=abc123"]
    textless = found["str14.no_text"]["evidence"]["links"][0]
    assert textless["row"]["tr"].endswith("→ /p/1") and "görselin alt metni" in textless["row"]["tr"]
    moved = final.broken_link_cards(report)
    assert any("/old" in json.dumps(rows) for rows in moved.values()) or "idx6.links_to_redirect" in found


def test_a_page_whose_links_are_fine_has_no_link_rows(no_lookups):  # noqa: F811
    from maya_audit import link_places
    routes = {"/": page("Shop", '<h1>Shop</h1><a href="/a">About us</a>'), "/a": page("About", "<h1>About</h1>")}
    report, found = site(routes)
    assert not [r for rows in link_places.places(report).values() for r in rows]
    assert "str14.no_text" not in found


# ---------------------------------------------------------------- the hidden <h1>, in a real browser

CASES = {
    "sr_only": ('<h1 style="position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)">Recipes</h1>', True),
    "responsive_duplicate": ('<h1 style="display:none">Recipes</h1><h1>Recipes</h1>', True),
    "pop_up": ('<div aria-hidden="true"><h1>Recipes</h1></div><div role="dialog" aria-modal="true" '
               'style="position:fixed;top:0;width:300px;height:200px">Sign up</div>', True),
    "transparent": ('<h1 style="opacity:0">Recipes</h1>', True),
    "display_none": ('<div style="display:none"><h1>Recipes</h1></div>', False),  # the healthy counter-example
}


@pytest.mark.parametrize("case", list(CASES))
def test_an_h1_is_hidden_only_when_no_one_reads_it(case):
    from maya_audit.render import H1_VISIBILITY_JS
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page_ = browser.new_page()
            page_.set_content(f"<html><body>{CASES[case][0]}<p>text</p></body></html>")
            seen = page_.evaluate(H1_VISIBILITY_JS)
            browser.close()
    except Exception as exc:  # noqa: BLE001
        pytest.fail(f"a local headless browser is needed for this test (python -m playwright install chromium): {exc}")
    read = any(v["visible"] or v.get("accessible", True) for v in seen)
    assert read is CASES[case][1], (case, seen)


# ---------------------------------------------------------------- the heading language

@pytest.mark.parametrize("heading", ["Our Story", "Shop Now", "Free Shipping", "Best Sellers", "New In"])
def test_short_english_headings_are_never_called_foreign_on_a_turkish_page(heading):
    assert heading_language(heading, declared="tr") is None


@pytest.mark.parametrize("heading", ["Non-Candy Halloween Treats to Hand Out This Year", "How do I move up a tier?",
                                     "Do my points expire?"])
def test_english_headings_with_english_words_are_english(heading):
    assert heading_language(heading, declared="en") == "en"


def test_a_real_foreign_heading_is_still_called():
    assert heading_language("Unterschied zu den anderen Angeboten", declared="en") == "de"
    assert heading_language("Information for new patient", declared="tr") == "en"
