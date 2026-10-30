"""P4 (kör nokta planı, 22 Oct): what a reader of the menu and the outline meets, for any site.

Live, on a Ticimax shop: the Turkish pages' menu icons carry alt="My Cart", "Sign up / Login", "Favorites"; the
homepage's questions sit in <span>s, not headings; a category lives at /ciceksi-kukular, linked as "Çiçeksi Kokular".
Each rule is an observation (as P3), with tests of what it must find and what it must not."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from fakeserver import FakeServer
from fakeserver.scenarios import robots
from fakeserver.server import Response, Site
from maya_audit.analysis import analyze_html
from maya_audit.audit import run_audit
from maya_audit.checks.content_quality import slug_typos
from maya_audit.checks.structure import chrome_language_mismatch, questions_not_headings
from maya_audit.config import CrawlConfig

FAST = {"request_delay_s": 0.0, "robots_sample_interval_s": 0.05, "probe_retry_cooldown_s": 0.0, "refetch_delay_s": 0.0,
        "render_enabled": False, "prf_round_gap_s": 0.0, "image_checks_max": 0, "check_external_links": False}
ALLOW = robots("User-agent: *\nAllow: /\n")
TR_TEXT = "<p>" + "Bu sayfa ev kokuları ve difüzörler için bir rehber olarak hazırlandı ve çok daha fazlası var. " * 12 + "</p>"
EN_TEXT = "<p>" + "This page is a guide to home fragrance and the diffusers that you can use in your room. " * 12 + "</p>"
ANSWER = "<p>This is the answer to the question, with enough words in it.</p>"


def page_of(html: str, lang: str = "tr", url: str = "https://s.test/", outlinks=()) -> SimpleNamespace:
    analysis = analyze_html(f'<html lang="{lang}"><body>{html}</body></html>')
    return SimpleNamespace(url=url, analysis=analysis, outlinks=list(outlinks))


# -- questions written as plain text -------------------------------------------------------------------------------
def test_questions_in_spans_are_not_headings():
    html = "<main>" + "".join(f"<div><span>Question {k}?</span>{ANSWER}</div>" for k in range(4)) + "</main>"
    assert len(questions_not_headings(analyze_html(html))) == 4


@pytest.mark.parametrize("wrap", ["<h3>{q}</h3>", "<details><summary>{q}</summary></details>", "<dl><dt>{q}</dt></dl>",
                                  "<button>{q}</button>"])
def test_questions_marked_up_as_headings_toggles_or_terms_are_fine(wrap):
    html = "<main>" + "".join(wrap.format(q=f"Question {k}?") + ANSWER for k in range(4)) + "</main>"
    assert questions_not_headings(analyze_html(html)) == []


# -- slug typos -----------------------------------------------------------------------------------------------------
def pages_linked(*pairs) -> list:
    home = SimpleNamespace(url="https://s.test/", analysis={"title": "Shop", "h1_elements": []},
                           outlinks=[{"target": f"https://s.test{path}", "anchors": [anchor]} for path, anchor in pairs])
    return [home] + [SimpleNamespace(url=f"https://s.test{path}", analysis={"title": "", "h1_elements": []}, outlinks=[])
                     for path, _ in pairs]


def test_an_address_word_one_letter_off_its_link_text_is_observed():
    [row] = slug_typos(pages_linked(("/ciceksi-kukular", "Çiçeksi Kokular")))
    assert (row["address_word"], row["page_name_word"]) == ("kukular", "kokular")


@pytest.mark.parametrize("path,anchor", [
    ("/kokulari", "Kokular"),          # an ending, not a typo
    ("/difuzoru", "Difüzör"),
    ("/sets", "Set"),
    ("/difuzor-8", "Difüzör"),
    ("/arjavo", "Arjava"),             # only the last letter differs
    ("/lumora", "Our story"),          # a coined word with nothing near it
    ("/ciceksi-kokular", "Çiçeksi Kokular"),
])
def test_what_is_not_an_address_typo(path, anchor):
    assert slug_typos(pages_linked((path, anchor))) == []


# -- a menu in another language -------------------------------------------------------------------------------------
TR_MENU = ('<header><a href="/checkout" title="My Cart"><img alt="My Cart" src="/i/cart.svg">Sepetim</a>'
           '<a href="/UyeGiris" title="Sign up / Login"><img alt="Sign up / Login" src="/i/user.svg"></a>'
           '<a href="/fav"><img alt="Favorites" src="/i/fav.svg">Favorilerim</a></header>')


def test_english_icon_names_in_a_turkish_menu_are_observed():
    row = chrome_language_mismatch(page_of(TR_MENU + f"<main>{TR_TEXT}</main>"))
    assert row and row["page_language"] == "tr" and set(row["labels"]) >= {"my cart", "favorites"}


@pytest.mark.parametrize("html,lang", [
    (TR_MENU + f"<main>{EN_TEXT}</main>", "en"),                                                   # an English page
    ('<header><a href="/shop">Shop</a><a href="/login">Login</a><a href="/news">Newsletter</a>'
     '<a href="/blog">Blog</a></header><main><p>' + "Dies ist der Text der Seite, und wir haben mehr. " * 15 + "</p></main>", "de"),
    ('<header><a href="/en/">English</a><a href="/de/">Deutsch</a><a href="/sepet">Sepetim</a></header>'
     f"<main>{TR_TEXT}</main>", "tr"),                                                             # a language switcher
    ('<header><a href="/cart">My Cart</a></header>' + f"<main>{TR_TEXT}</main>", "tr"),           # one label only
])
def test_what_is_not_a_menu_in_another_language(html, lang):
    assert chrome_language_mismatch(page_of(html, lang)) is None


# -- end to end: the observations are written --------------------------------------------------------------------------
def test_the_three_observations_reach_the_report():
    qa = "".join(f"<div><span>Soru numarası {k} nedir?</span><p>Bu sorunun cevabı burada, yeterince kelimeyle.</p></div>"
                 for k in range(4))
    home = Response(body=f'<!doctype html><html lang="tr"><head><title>Mağaza</title></head><body>{TR_MENU}<main>'
                         f'<h1>Mağaza</h1>{TR_TEXT}{qa}<a href="/ciceksi-kukular">Çiçeksi Kokular</a></main></body></html>')
    site = Site({"/robots.txt": ALLOW, "/": home,
                 "/ciceksi-kukular": Response(body=f'<html lang="tr"><head><title>Çiçeksi</title></head><body><main>'
                                                   f'<h1>Çiçeksi</h1>{TR_TEXT}</main></body></html>')})
    with FakeServer(site) as server:
        outcome = run_audit(server.base_url + "/", CrawlConfig(**{**FAST, "max_pages": 5}))
    metrics = {c.check_id: {o["metric"] for o in c.observations} for c in outcome.checks}
    assert "pages whose question-and-answer block writes its questions as plain text" in metrics["STR-2"]
    assert "addresses whose words look misspelled against the page's own name" in metrics["STR-14"]
    assert "pages whose header, menu or footer labels are in another language than the page" in metrics["STR-9"]
