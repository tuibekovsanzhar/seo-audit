"""Review G, worker gx2: the word-list rules read the same in German, French, Spanish and Arabic as in Turkish and
English (G09, G19-G24, item 11), and the structural signs come before the words."""

from __future__ import annotations

from datetime import date

import pytest

from maya_audit.analysis import analyze_html
from maya_audit.checks.structure import _video_placeholder, page_kind, placeholder_alt, price_tokens, visible_dates
from maya_audit.language import hreflang_code_problem
from maya_audit.page_words import fold
from test_false_alarms import ROOT, TR, html, ld, site

LONG = " ".join([TR] * 6)


def test_fold_takes_the_marks_off_latin_letters_too():
    assert fold("Über uns · À propos · Añadir · İletişim · Straße") == "uber uns · a propos · anadir · iletisim · strasse"


# -- G09 -------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("alt", ["Bild", "imagen", "Immagine", "صورة", "Foto"])
def test_placeholder_nouns_in_other_languages_are_placeholders_as_the_whole_alt(alt):
    assert placeholder_alt({"alt": alt}) == "a placeholder word"


@pytest.mark.parametrize("alt", ["Foto der Praxis", "Imagen del producto", "Bild: Wanderer im Gebirge"])
def test_a_placeholder_noun_inside_a_description_is_not_one(alt):
    assert placeholder_alt({"alt": alt}) is None


def test_alt_equal_to_title_is_not_a_placeholder_but_a_camera_name_still_is():
    assert placeholder_alt({"alt": "Diş Beyazlatma", "title": "Diş Beyazlatma"}) is None
    assert placeholder_alt({"alt": "IMG_2034", "title": "IMG_2034"}) == "a file name"


# -- G20 -------------------------------------------------------------------------------------------------------------
TODAY = date(2026, 10, 22)


def test_a_named_video_uploaded_today_with_a_thumbnail_is_not_a_default():
    node = {"@type": "VideoObject", "name": "Crue de la Saône", "thumbnailUrl": "https://x.test/t.jpg",
            "uploadDate": "2026-10-22"}
    assert _video_placeholder(node, TODAY) == []


def test_the_audit_day_counts_beside_a_default_name_or_a_missing_thumbnail():
    named = {"name": "Vidéo", "thumbnailUrl": "https://x.test/t.jpg", "uploadDate": "2026-10-22T08:00:00+00:00"}
    assert _video_placeholder(named, TODAY) == ['name is "Vidéo"', "uploadDate 2026-10-22T08:00:00+00:00 is the audit day"]
    bare = {"name": "Crue de la Saône", "uploadDate": "2026-10-22"}
    assert _video_placeholder(bare, TODAY) == ["uploadDate 2026-10-22 is the audit day"]


# -- G22 -------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text, day, kind", [
    ("Publié le 14 février 2026 par Claire", "2026-02-14", "published"),
    ("Veröffentlicht am 3. März 2026", "2026-03-03", "published"),
    ("Publicado el 14 de febrero de 2026", "2026-02-14", "published"),
    ("Mis à jour le 2 août 2025", "2025-08-02", "modified"),
    ("Aktualisiert am 1. Dezember 2024", "2024-12-01", "modified"),
    ("le 1er mars 2026", "2026-03-01", None),
])
def test_dates_and_labels_are_read_in_german_french_and_spanish(text, day, kind):
    found = {d["date"].isoformat(): d["kind"] for d in visible_dates(analyze_html(html(f"<p>{text}</p>"), ROOT + "/"))}
    assert found.get(day, "missing") == kind


# -- G23 -------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("title", ["Startseite", "Accueil", "Página de inicio", "Sin título", "الرئيسية"])
def test_placeholder_titles_in_other_languages_are_generic(title):
    from maya_audit.checks.structure import str1_titles
    from test_false_alarms import CFG
    result, pages = site({"/": html(f"<p>{LONG}</p>", title="Örnekmağaza | Ev"), "/a/": html(f"<p>{LONG}</p>", title=title)})
    findings = str1_titles(result, CFG, pages, set()).findings
    assert any(ROOT + "/a/" in str(f.evidence) and "generic" in str(f.evidence) for f in findings)


# -- G19 -------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("code, meant", [("jp", "ja"), ("cn", "zh"), ("gr-GR", "el"), ("dk", "da")])
def test_a_country_code_in_the_language_place_is_malformed(code, meant):
    assert f"use {meant}" in hreflang_code_problem(code)


@pytest.mark.parametrize("code", ["uk", "se", "ja", "en-us", "EN-GB", "ar-AE"])
def test_real_language_codes_and_lower_case_regions_pass(code):
    assert hreflang_code_problem(code) is None


# -- G21 / G24 -------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("button", ["In den Warenkorb", "Ajouter au panier", "Añadir al carrito", "Add to bag",
                                    "Aggiungi al carrello"])
def test_buy_buttons_in_other_languages_make_a_product_page_beside_a_price(button):
    from maya_audit.checks.small_site import shop_pages
    _, pages = site({"/": html(f"<p>{LONG}</p>"),
                     "/p/a": html(f"<p>{LONG}</p><p>89,95 €</p><button>{button}</button>")})
    assert ROOT + "/p/a" in shop_pages(pages)


def test_a_form_that_posts_to_the_checkout_is_a_buy_control_in_any_language():
    from maya_audit.checks.structure import _buy_control
    _, pages = site({"/": html('<form action="/checkout/line-item/add" method="post"><button>OK</button></form>')})
    assert _buy_control(pages[0]) == "/checkout/line-item/add"


@pytest.mark.parametrize("path, kind", [("/kontakt", "Contact"), ("/ueber-uns", "About"), ("/a-propos", "About"),
                                        ("/quienes-somos", "About"), ("/preguntas-frecuentes", "FAQ")])
def test_basic_pages_in_other_languages_are_found_by_address(path, kind):
    from maya_audit.checks.small_site import basic_pages_found
    _, pages = site({"/": html(f"<p>{LONG}</p>"), path: html(f"<p>{LONG}</p>", title="Seite")})
    assert ROOT + path in basic_pages_found(pages)[kind]


def test_a_contact_page_type_is_a_contact_page_whatever_its_address():
    from maya_audit.checks.small_site import basic_pages_found
    page = html(f"<p>{LONG}</p>", head=ld({"@context": "https://schema.org", "@type": "ContactPage"}), title="Yaz bize")
    _, pages = site({"/": html(f"<p>{LONG}</p>"), "/x9": page})
    assert ROOT + "/x9" in basic_pages_found(pages)["Contact"]


@pytest.mark.parametrize("path", ["/menu-settings/", "/sube-yonetimi-api/"])
def test_a_stem_is_matched_on_the_whole_segment_only(path):
    from maya_audit.checks.small_site import basic_pages_found
    _, pages = site({"/": html(f"<p>{LONG}</p>"), path: html(f"<p>{LONG}</p>", title="Ayarlar")})
    assert ROOT + path not in [u for urls in basic_pages_found(pages).values() for u in urls]


# -- item 11 ---------------------------------------------------------------------------------------------------------
def test_a_number_before_a_dollar_sign_followed_by_a_price_is_not_a_price():
    assert [t["text"] for t in price_tokens("No. 1 $28.00")] == ["$28.00"]
    assert [t["text"] for t in price_tokens("28,00 € 30,00 €")] == ["28,00 €", "30,00 €"]
    assert [t["text"] for t in price_tokens("49 TL")] == ["49 TL"]


@pytest.mark.parametrize("path", ["/actualites/tramway", "/noticias/presupuesto", "/nachrichten/stadtrat"])
def test_news_folders_in_other_languages_are_article_pages(path):
    _, pages = site({"/": html(f"<p>{LONG}</p>"), path: html(f"<p>{LONG}</p>")})
    page = next(p for p in pages if p.url == ROOT + path)
    assert page_kind(page, ROOT + "/")[0] == "article"
