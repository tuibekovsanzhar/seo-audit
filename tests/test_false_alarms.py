"""One test for every confirmed false alarm, and the healthy case beside each (docs/FALSE-ALARMS.md, DECISIONS 173-178,
186, 194-200).

Each alarm was found in the saved page copies or the saved report of a real audit. Each test builds a small made-up page
with the same pattern and nothing else of the site: every address is example.test and every name is invented. Next
to it stands the case that must not change, so a rule that stops a false alarm cannot quietly stop a real finding.
Nothing is requested: pages are made from HTML in memory. The alarms that came from what a site answers on a second
request (FA-016, FA-017, FA-020) run the whole audit over made-up sites in an in-memory transport: no socket is opened.
"""
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from maya_audit.analysis import analyze_html
from maya_audit.checks.render import account_page, login_target, rnd5_walls
from maya_audit import shared_elements
from maya_audit.checks.content_quality import str14_anchor_text
from maya_audit.checks.small_site import ADDRESS_ONLY, BASIC_PAGES, str19_links_to_nowhere, str21_basic_pages
from maya_audit.checks.structure import (str4_consistency, str5_entity, str7_alt, str8_semantic_tables, str9_language,
                                         str12_content_language)
from maya_audit.config import ACCOUNT_PATHS, MIN_FOREIGN_HEADINGS, SITEWIDE_SHARE, TEASER_SHARE, CrawlConfig
from maya_audit.html_links import extract_link_edges
from maya_audit.language import NOT_FOREIGN_IN, block_language, detect_language, heading_language, text_assessable, words_of
from maya_audit.models import StopReason, to_jsonable
from maya_audit.report import (PAGE_KINDS, detail_lines, detail_sentence, page_item, page_sentence, problem_summary,
                               problems_by_page_lines, title_with_details)
from maya_audit.structure_data import StructureData

ROOT = "https://shop.example.test"
CFG = CrawlConfig()
DOCS = Path(__file__).resolve().parent.parent / "docs"
TR = ("Bu sayfa hizmetlerimiz hakkında bilgi vermek için hazırlandı ve ekibimiz ile birlikte her müşteri için en uygun "
      "planı oluşturmak çok önemli bir adım olarak görülür. Süreç daha sonra birlikte değerlendirilir, ancak her "
      "durumda kişiye göre bir yaklaşım gerekir ve bu nedenle bizi arayabilirsiniz. ")


def html(body, *, title="Sayfa | Örnekmağaza", lang="tr", head="", header="", footer=""):
    return (f'<!doctype html><html lang="{lang}"><head><title>{title}</title>{head}</head><body>'
            f'<header><nav><a href="/">Ana Sayfa</a>{header}</nav></header><main>{body}</main><footer>{footer}</footer></body></html>')


def ld(*nodes):
    return "".join('<script type="application/ld+json">' + json.dumps({"@context": "https://schema.org", **node}) + "</script>" for node in nodes)


def site(pages_html):
    """(result, pages) as the checks see them, from made-up HTML by path. Nothing is fetched."""
    pages = [SimpleNamespace(url=ROOT + path, analysis=analyze_html(text, ROOT + path), body_truncated=False, status=200, headers={},
                             depth=0 if path == "/" else 1,
                             outlinks=[edge for edge in extract_link_edges(text, ROOT + path) if edge["target"].startswith(ROOT)])
             for path, text in pages_html.items()]
    return SimpleNamespace(origin=ROOT, start_url=ROOT + "/", pages=pages, stop_reason=StopReason.EXHAUSTED, not_fetched_urls=[]), pages


def path(url):
    return url.removeprefix(ROOT)


# -- FA-003: an account page that redirects to the login page (DECISIONS 173) ------------------------------------------
def redirects(*rows):
    pages = [SimpleNamespace(url=ROOT + source, status=status, redirect_location=target, analysis=None) for source, status, target in rows]
    return rnd5_walls(SimpleNamespace(origin=ROOT, start_url=ROOT + "/", pages=pages), CFG)


def test_an_account_page_redirecting_to_login_is_a_note():
    check = redirects(("/musteri-hesabi", 302, "http://shop.example.test/login?ReturnUrl=%2Fmusteri-hesabi"),
                      ("/Hesabım.aspx", 302, f"{ROOT}/uye-girisi"),          # Turkish letters, capitals and a file extension
                      ("/sepet", 302, f"{ROOT}/oturum?next=%2Fsepet"),        # no login word in the target: the return address says it
                      ("/checkout/step-1", 301, f"{ROOT}/giris-yap"))
    [note] = check.findings
    assert note.title == "4 account, cart or checkout page(s) send a signed-out visitor to the login page (expected)"
    assert note.severity.value == "Info" and note.confidence.value == "verified" and note.scope["count"] == 4
    assert note.evidence["pages"][0] == {"url": f"{ROOT}/musteri-hesabi", "status": 302,
                                         "location": "http://shop.example.test/login?ReturnUrl=%2Fmusteri-hesabi"}
    assert "still reported as a wall" in note.notes[0] and "Nothing to fix" in note.how_to_fix
    # A note makes no problem and no page row.
    summary = problem_summary(to_jsonable(check.findings), pages_checked=4)
    assert summary["problems"] == 0 and summary["notes"] == 1 and summary["by_page"] == []
    assert {"musteri-hesabi", "hesabim", "hesabım", "sepet", "checkout", "giris-yap", "wishlist", "adreslerim"} <= ACCOUNT_PATHS
    assert account_page(f"{ROOT}/HESABIM") and account_page(f"{ROOT}/tr/sepetim/") and not account_page(f"{ROOT}/blog/sepet-nedir-rehberi")


def test_a_content_page_redirecting_to_login_is_still_a_blocker_and_other_walls_are_unchanged():
    check = redirects(("/blog/kargo-rehberi", 302, f"{ROOT}/login?ReturnUrl=%2Fblog%2Fkargo-rehberi"),
                      ("/urunler/mavi-kazak", 302, f"{ROOT}/uyeler?returnUrl=/urunler/mavi-kazak"),  # only the return address names a login
                      ("/hakkimizda", 302, f"{ROOT}/giris-yap"),                                    # a Turkish login address
                      ("/sepet", 302, f"{ROOT}/age-verification"),                                  # an age wall, even on a cart page
                      ("/kategori/kazak?next=2", 301, f"{ROOT}/kategori/kazak/?next=2"),            # a page number is not a return address
                      ("/eski-sayfa", 301, f"{ROOT}/yeni-sayfa"))
    [wall] = check.findings
    assert wall.title == "4 page(s) redirect a cookie-less visitor to a login, consent, age, or country page"
    assert wall.severity.value == "S1" and wall.confidence.value == "verified"
    assert sorted(path(url) for url in wall.scope["urls"]) == ["/blog/kargo-rehberi", "/hakkimizda", "/sepet", "/urunler/mavi-kazak"]
    assert login_target(f"{ROOT}/login") and not login_target(f"{ROOT}/kategori/kazak/?next=2") and not login_target(f"{ROOT}/yeni-sayfa")


# -- FA-004, FA-005: a term or a common word is not a wrong language (DECISIONS 174) ------------------------------------
GLOSSARY = ["Proof of Work (PoW) Nedir?", "Chain of Custody (CoC) Nedir?", "Layer of Trust (LoT) Nasıl Çalışır?", "Staking Ödülleri Nelerdir?"]


def headings_check(headings, lang="tr"):
    body = "<h1>Sözlük</h1>" + "".join(f"<h2>{text}</h2><p>{TR}</p>" for text in headings)
    result, pages = site({"/": html(f"<h1>Ana sayfa</h1><p>{TR}</p>", lang=lang), "/sozluk/": html(body, lang=lang)})
    return str12_content_language(result, CFG, pages, set())


def test_a_turkish_glossary_heading_with_an_english_term_is_not_english():
    for heading in GLOSSARY:
        assert heading_language(heading, declared="tr") == "tr", heading
    # The term's own words are not counted: without the Turkish question word nothing is called at all.
    assert heading_language("Delegated Proof of Stake (DPoS)", declared="tr") is None
    assert heading_language("Bank of Example Hesabı Açma", declared="tr") == "tr"
    check = headings_check(GLOSSARY)
    assert [f.title for f in check.findings] == [] and check.status == "pass"


def test_et_in_a_turkish_heading_is_not_french():
    assert heading_language("Bizi Takip Et", declared="tr") is None            # no evidence either way: not called
    assert heading_language("Bizi Takip Et") == "fr"                           # what it was called without the page's language
    assert heading_language("En son haberler ve duyurular", declared="tr") == "tr"  # "en" and "son" are Turkish words here
    check = headings_check(["Bizi Takip Et", "Hemen Kayıt Ol", "Sepete Ekle ve Al", "En Çok Satanlar"])
    assert check.findings == []


def test_real_foreign_headings_are_still_called_and_reported():
    assert heading_language("Information for new patient") == "en" and heading_language("Information for new patient", declared="tr") == "en"
    assert heading_language("Tedavi süreci nasıl ilerler") == "tr" and heading_language("Tedavi süreci nasıl ilerler", declared="tr") == "tr"
    assert MIN_FOREIGN_HEADINGS == 3
    check = headings_check(["Information for new patient", "Welcome to our clinic", "How we work with you"])
    [finding] = check.findings
    assert finding.title == "1 page(s) have section headings in another language than they declare (declared Turkish, headings in English)"
    assert finding.confidence.value == "estimated" and "word lists (Estimated)" in finding.evidence["method"]
    assert any("Still a heuristic over word lists" in note for note in finding.notes)
    assert headings_check(["Information for new patient", "Welcome to our clinic"]).findings == []  # two are not enough


# -- FA-006, FA-007, FA-008: a price or a name "differs" only when it clearly does (DECISIONS 175) -----------------------
TEASER = ('<div class="slide"><a href="/blog/karsilastirma" class="card"><div class="name">Örnekmağaza ve rakibi: hangisi?</div>'
          "<div class=\"text\">Rakip altyapı aylık 29 USD'den başlayan bir yazılımdır.</div></a></div>")


def offers(kind, name, *prices, currency="TRY", listed=True):
    made = [{"@type": "Offer", "price": str(price), "priceCurrency": currency} for price in prices]
    return {"@type": kind, "name": name, "offers": made if listed or len(made) > 1 else made[0]}


def str4(pages_html):
    result, pages = site(pages_html)
    return str4_consistency(result, CFG, pages, set(), set())[0]


def price_rows(entry):
    return [row for row in entry.evidence["values"] if row["field"] == "price"]


def test_a_teaser_price_is_not_the_pages_price():
    """A blog teaser that names a competitor's monthly price stands on five of eight pages. On a page whose markup says
    0 TRY ("Free") or 60000 TRY it was read as that page's price: High, "price differs"."""
    filler = {f"/sayfa-{n}": html(f"<h1>Sayfa {n}</h1><p>{TR}</p>" + (TEASER if n < 3 else "")) for n in range(6)}
    check = str4({
        "/": html(f"<h1>Örnekmağaza</h1><p>{TR}</p>"),
        "/akademi": html(f"<h1>Akademi</h1><p>Eğitimlerimiz ücretsiz. {TR}</p>" + TEASER, head=ld(offers("Course", "Örnek Akademi", 0))),
        "/etkinlik": html(f"<h1>Etkinlik</h1><p>{TR}</p>" + TEASER, head=ld(offers("Event", "Örnek Kamp", 60000))),
        **filler})
    assert check.findings == [] and TEASER_SHARE == 0.25 and SITEWIDE_SHARE == 0.6
    [item] = check.review_items
    assert item.title == "1 page(s): the markup price is not shown on the page, or the page's own price could not be told apart"
    [row] = price_rows(item)
    assert (path(row["url"]), row["schema_value"], row["schema_currency"], row["offer_parent"]) == (
        "/etkinlik", "60000", "TRY", {"type": ["Event"], "name": "Örnek Kamp"})
    assert row["outcome"] == "not_visible" and row["why_code"] == "not_own" and "not this page's own" in row["why_not_reliable"]
    [shown] = row["visible"]
    assert (shown["text"], shown["value"], shown["currency"], shown["where"]) == ("29 USD", "29", "USD", "link text (a teaser for another page)")
    assert "aylık 29 USD'den başlayan" in shown["context"] and len(shown["context"]) <= 100
    # Free: a markup price of 0 beside the word is a match, and makes neither a finding nor a review row.
    free = next(row for row in check.evidence["price_comparisons"] if path(row["url"]) == "/akademi")
    assert free["outcome"] == "match" and free["free_wording"] is True and free["visible"][0]["text"] == "ücretsiz"


def test_a_price_in_a_block_many_pages_repeat_is_not_the_pages_price_even_outside_a_link():
    promo = "<div class=\"promo\">Kampanya: yıllık paket 990 TL</div>"
    pages = {f"/sayfa-{n}": html(f"<h1>Sayfa {n}</h1><p>{TR}</p>" + (promo if n < 5 else "")) for n in range(11)}
    pages["/sayfa-0"] = html(f"<h1>Danışmanlık</h1><p>{TR}</p>" + promo, head=ld(offers("Service", "Danışmanlık", 4500)))
    check = str4(pages)
    assert check.findings == []
    [row] = price_rows(check.review_items[0])
    assert row["why_code"] == "not_own" and [shown["where"] for shown in row["visible"]] == ["a block repeated on at least 25% of the pages (and at least 5)"]
    # The same block on four pages is under the bar (five pages): there it is the page's own content, and a difference.
    few = {f"/sayfa-{n}": html(f"<h1>Sayfa {n}</h1><p>{TR}</p>" + (promo if n < 4 else "")) for n in range(11)}
    few["/sayfa-0"] = html(f"<h1>Danışmanlık</h1><p>{TR}</p>" + promo, head=ld(offers("Service", "Danışmanlık", 4500)))
    [finding] = str4(few).findings
    assert finding.severity.value == "S2" and price_rows(finding)[0]["visible"][0]["text"] == "990 TL"


def home_with(*testimonials):
    plans = [offers("Product", f"Örnekmağaza - {name}", price, listed=False) for name, price in (("BAŞLANGIÇ", 50000), ("PREMIUM", 95000), ("PREMIUM PLUS", 190000))]
    said = "".join(f'<div class="kazanc"><div>Aylık Kazanç</div><div>{amount} TL</div></div>' for amount in testimonials)
    return {"/": html(f"<h1>50.000 TL'den Başlayan Fiyatlar ile İlk Adımınızı Atın</h1><p>{TR}</p>{said}", head=ld(*plans)),
            "/hakkimizda": html(f"<h1>Hakkımızda</h1><p>{TR}</p>")}


def test_sibling_offers_beside_a_matched_price_are_review_items():
    """Three plans in the markup; the headline shows the first one's price, and a testimonial shows what a customer
    earns. The earning was set against the two other plans: High, "price differs"."""
    check = str4(home_with("189.039"))
    assert [f for f in check.findings if "price" in f.title] == []
    item = next(r for r in check.review_items if "could not be told apart" in r.title)
    rows = price_rows(item)
    assert [(row["schema_value"], row["schema_currency"], row["why_code"]) for row in rows] == [("95000", "TRY", "sibling"), ("190000", "TRY", "sibling")]
    assert [shown["text"] for shown in rows[0]["visible"] if shown["where"] == "main content"] == ["189.039 TL"]
    assert rows[0]["offer_parent"]["name"] == "Örnekmağaza - PREMIUM"
    matched = [row for row in check.evidence["price_comparisons"] if row["outcome"] == "match"]
    assert [(row["schema_value"], row["visible"][0]["text"]) for row in matched] == [("50000", "50.000 TL")]
    # Several testimonials: several prices of the page's own, and still nothing to set one offer against.
    several = str4(home_with("189.039", "155.580"))
    assert [f for f in several.findings if "price" in f.title] == []
    assert {row["why_code"] for row in price_rows(next(r for r in several.review_items if "could not be told apart" in r.title))} == {"several"}


def test_a_brand_prefix_or_an_absent_name_is_not_a_different_name():
    """"Örnekmağaza - PREMIUM PLUS" in the markup, "PREMIUM PLUS" on the page: the same name with the site's in front.
    And a homepage that lists three plans in its markup and names none of them shows no name; it does not show another."""
    plan = offers("Product", "Örnekmağaza - PREMIUM PLUS", 190000, listed=False)
    site_name = '<meta property="og:site_name" content="Örnekmağaza">'
    pages = home_with()
    pages["/paketler"] = html(f"<h1>Paketler</h1><h2>PREMIUM PLUS</h2><p>190.000 TL. {TR}</p>", head=site_name + ld(plan))
    check = str4(pages)
    assert [f.title for f in check.findings if "name" in f.title] == []
    item = next(r for r in check.review_items if "product name is not shown" in r.title)
    assert item.title == "1 page(s): structured-data product name is not shown on the page" and [path(u) for u in item.scope["urls"]] == ["/"]
    assert {row["why_not_reliable"] for row in item.evidence["values"]} == {"the product name is not shown on this page"}
    assert len(item.evidence["values"]) == 3 and {row["compared_as"] for row in item.evidence["values"]} == {"BAŞLANGIÇ", "PREMIUM", "PREMIUM PLUS"}
    assert "örnekmağaza" in check.evidence["site_names_left_out_of_product_names"]


def test_a_product_page_whose_h1_names_something_else_still_has_a_different_name():
    check = str4({"/": html(f"<h1>Örnekmağaza</h1><p>{TR}</p>"),
                  "/urun/kazak": html(f"<h1>Mavi Yün Kazak</h1><p>450 TL. {TR}</p>", head=ld(offers("Product", "Kırmızı Deri Ceket", 450, listed=False)))})
    [finding] = [f for f in check.findings if "name" in f.title]
    assert finding.title == "1 page(s): structured-data product name differs from the product name shown on the page"
    assert finding.severity.value == "S3" and finding.confidence.value == "estimated"


def test_a_single_differing_price_is_still_high_with_both_values_in_every_output():
    """Markup 89, the page shows only "$99": the approved case. The row, the page's line, the finding's own lines and
    the Turkish display all carry both values."""
    check = str4({"/": html(f"<h1>Örnek</h1><p>{TR}</p>", lang="en"),
                  "/pricing": html(f"<h1>Starter plan</h1><p>Starter is $99 per month. {TR}</p>", lang="en",
                                   head=ld(offers("Product", "Starter plan", 89, currency="USD", listed=False)))})
    [finding] = check.findings
    assert finding.title == "1 page(s): structured-data price differs from the price shown on the page"
    assert finding.severity.value == "S2" and finding.confidence.value == "verified" and check.review_items == []
    [row] = price_rows(finding)
    assert (row["schema_value"], row["schema_currency"], row["outcome"], row["distinct_prices_shown"]) == ("89", "USD", "conflict", 1)
    assert [(shown["text"], shown["value"], shown["where"]) for shown in row["visible"]] == [("$99", "99", "main content")]
    saved = to_jsonable(finding)
    item = page_item(saved, f"{ROOT}/pricing")
    assert item["kind"] == "markup_price_differs" and item["values"] == {"markup": "89", "currency": "USD", "shown": "$99"}
    assert page_sentence(item) == "Structured data says 89 USD; the page shows “$99”"
    assert [detail_sentence(line, ROOT) for line in detail_lines(saved)] == ["`/pricing`: Markup: 89 USD / Shown: “$99”"]
    summary = problem_summary([saved], pages_checked=2)
    assert "Structured data says 89 USD; the page shows “$99”" in "\n".join(problems_by_page_lines(summary, {saved["id"]: saved["title"]}, ROOT))
    # A report saved before the row held both sides says it plainly, and never with a hole.
    old = {**saved, "evidence": {"values": [{"url": f"{ROOT}/pricing", "field": "price", "outcome": "conflict", "schema_value": "89", "visible": ["$99"]}]}}
    assert page_sentence(page_item(old, f"{ROOT}/pricing")) == PAGE_KINDS["markup_price_differs"][1]
    assert [detail_sentence(line, ROOT) for line in detail_lines(old)] == ["`/pricing`: Markup: 89 / Shown: “$99”"]
    pytest.importorskip("fastapi")
    from maya_audit_web import pdf, practical, strings, summary as web_summary

    try:
        assert practical.page_line(item) == "Structured data says 89 USD; the page shows “$99”"
        assert web_summary.item(saved)["details"] == ["/pricing: Markup: 89 USD / Shown: “$99”"]
        assert "/pricing: Markup: 89 USD / Shown: “$99”" in pdf._issue(practical.issue(web_summary.item(saved)))
        strings.set_language("tr")
        assert practical.page_line(item) == "Yapılandırılmış veri 89 USD diyor; sayfada “$99” görünüyor"
        assert web_summary.item(saved)["details"] == ["/pricing: İşaretleme: 89 USD / Sayfada: “$99”"]
    finally:
        strings.set_language("en")


def test_a_review_item_about_a_price_carries_both_values_in_both_languages():
    check = str4(home_with("189.039"))
    saved = to_jsonable(next(r for r in check.review_items if "could not be told apart" in r.title))
    lines = [detail_sentence(line, ROOT) for line in detail_lines(saved)]
    assert lines[0].startswith("`/`: Markup: 95000 TRY / Shown: “189.039 TL”") and "could not be paired" in lines[0] and len(lines) == 2
    pytest.importorskip("fastapi")
    from maya_audit_web import strings, summary as web_summary, wording

    english, turkish = strings.STRINGS["en"], strings.STRINGS["tr"]
    assert [key for key in english if key.startswith("detail.") and (key not in turkish or "{" in strings.t(key, "tr", markup="1", shown="2", why="3", name="4", sources="5", value="6", more=7, source="8", pages=9, url="10", status=11, location="12"))] == []
    try:
        row = web_summary.review_item(saved)
        assert row["details"][0].startswith("/: Markup: 95000 TRY / Shown: “189.039 TL” (another offer on the page matches") and not row["untranslated"]
        strings.set_language("tr")
        row = web_summary.review_item(saved)
        assert row["title_shown"] == "1 sayfada işaretlemedeki fiyat sayfada gösterilmiyor veya sayfanın kendi fiyatı ayırt edilemedi"
        assert row["details"][0].startswith("/: İşaretleme: 95000 TRY / Sayfada: “189.039 TL” (sayfadaki başka bir teklif") and not row["untranslated"]
        assert wording.MARKS["tr"] not in row["why_shown"] + row["action_shown"]
    finally:
        strings.set_language("en")


def test_a_price_of_zero_beside_the_word_free_matches():
    for word in ("Ücretsiz", "ÜCRETSİZ katılım", "Bedava", "Free entry", "Bu etkinlikte ücret alınmaz"):
        check = str4({"/": html(f"<h1>Örnek</h1><p>{TR}</p>"),
                      "/etkinlik": html(f"<h1>Buluşma</h1><p>{word}. {TR}</p>", head=ld(offers("Event", "Buluşma", 0)))})
        assert check.findings == [] and check.review_items == [] and check.status == "pass", word
    # Without the word a price of 0 is simply not on the page: a person looks; nothing is called different.
    silent = str4({"/": html(f"<h1>Örnek</h1><p>{TR}</p>"), "/etkinlik": html(f"<h1>Buluşma</h1><p>{TR}</p>", head=ld(offers("Event", "Buluşma", 0)))})
    assert silent.findings == [] and [row["why_code"] for row in price_rows(silent.review_items[0])] == ["no_price"]


# -- FA-009: og:site_name holding the page title; the names are listed (DECISIONS 176) -----------------------------------
def brand_site(product_brands=()):
    def page_of(n, site_name):
        products = ld(*[{"@type": "Product", "name": f"Ürün {n}", "brand": {"@type": "Brand", "name": brand}} for brand in product_brands])
        return html(f"<h1>Sayfa {n}</h1><p>{TR}</p>", title=f"Sayfa {n} | Ornek", head=f'<meta property="og:site_name" content="{site_name}">' + products)

    pages = {f"/urun-{n}": page_of(n, "ORNEK SHOP") for n in range(40)}
    for name in ("KVKK", "Gizlilik", "Hakkımızda", "İletişim", "Kampanya", "İade", "Sorular"):
        slug = "/" + name.lower().replace("ı", "i").replace("i̇", "i")
        pages[slug] = html(f"<h1>{name}</h1><p>{TR}</p>", title=f"{name} | Ornekk", head=f'<meta property="og:site_name" content="{name} | Ornekk">')
    organization = ld({"@type": "Organization", "name": "ornek.example.test", "url": ROOT + "/"})
    pages["/"] = html(f"<h1>Ornek</h1><p>{TR}</p>", title="Ornek", head=organization + '<meta property="og:site_name" content="ORNEK SHOP">')
    result, made = site(pages)
    return str5_entity(result, CFG, made, set(), StructureData())


def test_og_site_name_holding_the_title_is_one_line_not_n_names():
    """Seven static pages carry their own title in og:site_name ("KVKK | Ornekk"). Read as names of the brand they made
    seven of "13 different ways"; they are one defect, said once, with the pages and the values."""
    check = brand_site()
    names, pasted = check.findings
    assert names.title == "The brand is named 3 different ways" and names.scope["kind"] == "sitewide"
    assert pasted.title == "og:site_name holds the page title on 7 page(s)" and pasted.severity.value == "S4" and pasted.confidence.value == "verified"
    assert pasted.scope["count"] == 7 and {"url": f"{ROOT}/kvkk", "og_site_name": "KVKK | Ornekk", "title": "KVKK | Ornekk"} in pasted.evidence["pages"]
    assert not [value for value in names.evidence["observed_values"] if "|" in value]
    # Each name with every page it was seen on and what gave it, counted before the lists are cut.
    by_name = {variant["name"]: variant for variant in names.evidence["variants"]}
    # ("Ornekk", the misspelt suffix of the seven titles, was a "name" only through those og:site_name values: a title
    # segment counts as a name when it is the commonest one or shares a word with another source, and it is neither.)
    assert set(by_name) == {"ORNEK SHOP", "Ornek", "ornek.example.test"}
    assert (by_name["ORNEK SHOP"]["pages"], by_name["ORNEK SHOP"]["by_source"], len(by_name["ORNEK SHOP"]["seen_as"])) == (41, {"og:site_name": 41}, 10)
    assert by_name["Ornek"]["by_source"] == {"title suffix/prefix": 40} and by_name["Ornek"]["pages"] == 40
    assert check.evidence["og_site_name_holding_the_title"] == 7 and check.evidence["name_sources_count"] == 43
    saved = to_jsonable(names)
    lines = [detail_sentence(line) for line in detail_lines(saved)]
    assert lines == ["“ORNEK SHOP”: og:site_name (41 pages)", "“Ornek”: title suffix (40 pages)", "“ornek.example.test”: Organization name (1 page)"]
    assert title_with_details(saved) == "The brand is named 3 different ways: " + "; ".join(lines)
    summary = problem_summary(to_jsonable(check.findings), pages_checked=48)
    whole_site = problems_by_page_lines(summary, {saved["id"]: title_with_details(saved), pasted.id: pasted.title}, ROOT)[4]
    assert whole_site.startswith("| Whole site | 1 |") and "“Ornek”: title suffix (40 pages)" in whole_site
    assert detail_sentence(detail_lines(to_jsonable(pasted))[0], ROOT).endswith("og:site_name is “" + pasted.evidence["pages"][0]["og_site_name"] + "”")
    pytest.importorskip("fastapi")
    from maya_audit_web import pdf, practical, strings, summary as web_summary, wording

    try:
        row = web_summary.item(saved)
        assert row["details"] == lines and row["names_line"] == "; ".join(lines)
        table = practical.by_page(summary, [row, web_summary.item(to_jsonable(pasted))])
        assert table["rows"][0]["whole_site"] and table["rows"][0]["lines"] == ["The brand is named 3 different ways: " + "; ".join(lines)]
        assert "“Ornek”: title suffix (40 pages)" in pdf._by_page(table, ROOT) and "“Ornek”: title suffix (40 pages)" in pdf._issue(practical.issue(row))
        assert wording.title("STR-5", pasted.title, "en") == ("og:site_name holds the page title on 7 pages", True)
        assert wording.title("STR-5", pasted.title, "tr") == ("og:site_name 7 sayfada sayfa başlığını içeriyor", True)
        strings.set_language("tr")
        assert web_summary.item(saved)["details"][:2] == ["“ORNEK SHOP”: og:site_name (41 sayfa)", "“Ornek”: başlık eki (40 sayfa)"]
        assert not web_summary.item(to_jsonable(pasted))["untranslated"] and web_summary.item(to_jsonable(pasted))["notes_untranslated"] == 0
    finally:
        strings.set_language("en")


def test_product_brands_add_no_names_of_the_site():
    """A shop sells Nike and Adidas. They are brands of products, not names of the shop: STR-5 never reads Product.brand."""
    plain, with_brands = brand_site(), brand_site(product_brands=("Nike", "Adidas"))
    assert [f.title for f in with_brands.findings] == [f.title for f in plain.findings]
    assert with_brands.findings[0].evidence["observed_values"] == plain.findings[0].evidence["observed_values"]
    assert "Nike" not in json.dumps(to_jsonable(with_brands.findings), ensure_ascii=False) and "not read" in with_brands.evidence["product_brands"]


def test_a_homepage_titled_with_the_brand_alone_keeps_its_site_name():
    result, pages = site({"/": html(f"<h1>Ornek Analiz</h1><p>{TR}</p>", title="Ornek Analiz", head='<meta property="og:site_name" content="Ornek Analiz">'),
                          "/fiyat": html(f"<h1>Fiyat</h1><p>{TR}</p>", title="Fiyat | Ornek Analiz", head='<meta property="og:site_name" content="Ornek Analiz">')})
    check = str5_entity(result, CFG, pages, set(), StructureData())
    assert check.findings == [] and check.evidence["og_site_name_holding_the_title"] == 0


# -- FA-010, FA-011: a cookie-settings opener and a show/hide toggle are controls (DECISIONS 177) ------------------------
def links_check(footer, body="", pages=6):
    result, made = site({f"/sayfa-{n}": html(f"<h1>Sayfa {n}</h1><p>{TR}</p>{body}", footer=footer) for n in range(pages)})
    return str19_links_to_nowhere(result, CFG, made, set())


def test_a_cookie_settings_link_is_a_control():
    for footer in ('<a href="#" class="js-open-cookie-settings">Çerez Ayarları</a>',     # by its class and by its label
                   '<a href="#" class="ot-sdk-show-settings">Tercihler</a>',              # by its class alone
                   '<a href="#">Çerez Tercihleri</a>', '<a href="#">Manage cookies</a>',  # by its label alone
                   f'<a href="{ROOT}/sayfa-0#" class="js-open-cookie-settings">Çerez Ayarları</a>'):
        check = links_check(footer)
        [note] = check.findings
        assert note.title == '1 control group(s) use anchors; interaction and accessibility require review', footer
        assert note.severity.value == "Info" and note.evidence["seo_problem"] is False
        # On every page of the site, and still only part of the one accessibility note: no shared "no address" problem.
        assert not [f for f in check.findings if "shared_element" in f.evidence or f.severity.value != "Info"]
    marked = links_check('<a href="#" class="js-open-cookie-settings">Çerez Ayarları</a>').findings[0].evidence["controls"][0]
    assert marked["control_because"] == 'class="js-open-cookie-settings"' and marked["pages"] == 6


def test_a_show_hide_toggle_is_a_control():
    toggle = '<span class="toc_toggle"><a href="#" class="toc_toggle_label" data-label="göster">gizle</a></span>'
    for body in (toggle, '<a href="#">Göster</a>', '<a href="#">Daha fazla göster</a>', '<a href="#">Show less</a>', '<a href="#" class="js-toggle-filters">Filtreler</a>'):
        check = links_check("", body)
        assert [f.severity.value for f in check.findings] == ["Info"] and "control group(s) use anchors" in check.findings[0].title, body
    assert links_check("", toggle).findings[0].evidence["controls"][0]["control_because"] == 'class="toc_toggle_label"'


def test_a_link_to_content_with_no_address_is_still_reported_whatever_its_class():
    # Rejected as over-matching: "cookie" anywhere in a class, any js- class, and btn / button.
    for footer in ('<a href="#" class="footer-cookie-link">Cookie policy</a>', '<a href="#" class="js-track btn button">Kampanya koşulları</a>',
                   '<a href="#">Show all products in this category</a>'):
        problems = [f for f in links_check(footer).findings if f.severity.value != "Info"]
        assert len(problems) == 1 and "has no address" in problems[0].title, footer
    # On four pages of ten it stays a per-page finding with its own title.
    result, made = site({f"/sayfa-{n}": html(f"<h1>Sayfa {n}</h1><p>{TR}</p>", footer='<a href="#" class="footer-cookie-link">Cookie policy</a>' if n < 4 else "")
                         for n in range(10)})
    [problem] = str19_links_to_nowhere(result, CFG, made, set()).findings
    assert problem.title.startswith("4 link(s) have no address a crawler can follow") and problem.scope["count"] == 4


# -- FA-012: a flag beside its code, a deliberate empty alt (DECISIONS 178) ------------------------------------------------
FLAGS = "".join(f'<tr><td class="country"><img src="https://cdn.example.test/country/{code}.svg" width="300" height="150"> {code} </td><td>Veri</td></tr>'
                for code in ("AU", "TR", "DE", "FR", "GB", "US", "JP", "CA"))
CAPTIONED = ('<div class="kart"><div class="kart-gorsel"><img src="/img/guvenli-yatirim.svg" alt="" width="400" height="300"></div>'
             '<div class="kart-baslik">Güvenli Yatırım</div></div>')


def images_check(body):
    result, pages = site({"/": html(f"<h1>Ana</h1><p>{TR}</p>"), "/takvim/": html(f"<h1>Takvim</h1><p>{TR}</p>{body}")})
    return str7_alt(result, CFG, pages, set(), set())


def test_a_flag_beside_its_code_is_decorative_and_counted_once():
    """A table of figures with a country flag beside each country code, and illustrations with a deliberate alt="" over
    their captions: "218 likely meaningful images have missing or empty alt text"."""
    check = images_check(f"<table>{FLAGS}</table>{CAPTIONED}")
    assert [f for f in check.findings if "meaningful" in f.title] == []
    [other] = [f for f in check.findings if "other image(s)" in f.title]
    assert other.title == "8 other image(s) on 1 page(s) have no alt attribute" and other.severity.value == "Info"
    [row] = other.evidence["images"]                                    # eight flags, one row
    assert (row["count"], row["src_pattern"], row["alt_state"]) == (8, "https://cdn.example.test/country/*.svg", "missing")
    assert row["why"] == "beside its own label (the text next to it says what it shows)"
    assert check.evidence["empty_alt_not_assessed_count"] == 1          # the captioned illustration: not called either way
    # With alt="" the flags are simply decorative: nothing is listed at all.
    assert [f for f in images_check("<table>" + FLAGS.replace('width="300"', 'alt="" width="300"') + "</table>").findings if "image(s) on" in f.title] == []
    # 300x150 is the size a browser gives an unsized image, not the image's own: alone it makes nothing "large".
    unsized = images_check('<div class="gorsel"><img src="/img/desen.svg" width="300" height="150"></div>')
    assert [f.title for f in unsized.findings if "image(s) on" in f.title] == ["1 other image(s) on 1 page(s) have no alt attribute"]
    analysis = analyze_html(html(f"<table>{FLAGS}</table>{CAPTIONED}"))
    assert [image["beside_label"] for image in analysis["images"]] == [True] * 8 + [False]


def test_a_large_photo_without_alt_in_an_article_is_still_meaningful():
    check = images_check('<article><p>Ekibimiz</p><a href="/team"><img src="/img/ekip-toplantisi.jpg" width="800" height="500"></a>'
                         '<figure><img src="/img/satis-egrisi.png" alt=""><figcaption>Grafik: Aylık satışlar</figcaption></figure></article>')
    [finding] = [f for f in check.findings if "meaningful" in f.title]
    assert finding.title == "2 likely meaningful image(s) on 1 page(s): 1 with no alt text, 1 with an empty alt" and finding.severity.value == "S4"
    assert (finding.evidence["no_alt"], finding.evidence["empty_alt"]) == (1, 1)
    assert {row["src"]: (row["alt_state"], row["why"]) for row in finding.evidence["images"]} == {
        "/img/ekip-toplantisi.jpg": ("missing", "image-only link without an accessible name"), "/img/satis-egrisi.png": ("empty", "informative caption: Grafik: Aylık satışlar")}
    saved = to_jsonable(finding)
    assert page_sentence(page_item(saved, f"{ROOT}/takvim/")) == "2 likely meaningful images have missing or empty alt text"
    pytest.importorskip("fastapi")
    from maya_audit_web import catalog, practical, wording

    assert wording.title("STR-7", finding.title, "en") == ("2 likely meaningful images on 1 page: 1 with no alt text, 1 with an empty alt", True)
    assert wording.title("STR-7", finding.title, "tr") == ("1 sayfada muhtemelen anlamlı 2 görsel: 1 tanesinde alt metni yok, 1 tanesinde alt boş", True)
    assert wording.title("STR-7", "3 likely meaningful image(s) on 2 page(s) have missing or empty alt text", "tr")[1]  # a report saved before
    assert "Alt text" in catalog.note("STR-7", finding.title)["why"] and 'actual image' in practical.example_for(finding.title)


# -- FA-014: the tiles of an embedded map (DECISIONS 186) ------------------------------------------------------------------
MAP = ("".join(f'<img src="https://maps.googleapis.com/maps/vt?pb=!1m5!1m4!1i15!2i{19500 + n}!3i12345!4i256" alt="" width="256" height="256">'
               for n in range(24))
       + '<img src="https://maps.gstatic.com/mapfiles/transparent.png" alt="" width="256" height="256">'
       + '<img src="https://maps.gstatic.com/mapfiles/api-3/images/spotlight-poi3.png" alt="" width="200" height="200">')


def test_map_tiles_are_not_meaningful_images():
    """A contact page with an embedded map: 24 tiles, a pin and a transparent overlay, each with alt="": "52 likely
    meaningful image(s) on 2 page(s)", because "map" in the host and the folder counted as a file-name hint."""
    check = images_check(f'<div class="harita">{MAP}</div>')
    assert [f for f in check.findings if "image(s) on" in f.title and "layout shift" not in f.title] == [] and check.evidence["map_images_left_out_count"] == 26
    assert check.evidence["empty_alt_not_assessed_count"] == 0
    # Without an alt attribute a map image is an Info row, one for the 24 tiles, and never "meaningful".
    bare = images_check(f'<div class="harita">{MAP.replace(chr(32) + "alt=" + chr(34) * 2, "")}</div>')
    assert [f for f in bare.findings if "meaningful" in f.title] == [] and bare.evidence["map_images_left_out_count"] == 0
    [other] = [f for f in bare.findings if "other image(s)" in f.title]
    assert other.title == "26 other image(s) on 1 page(s) have no alt attribute"
    assert {row["why"] for row in other.evidence["images"]} == {"a map tile or map control (decorative)"}
    assert sorted(row.get("count", 1) for row in other.evidence["images"]) == [1, 1, 24]
    # The hint is a whole word of the file name: not a part of a word, not the folder, not the host, not a data: address.
    from maya_audit.checks.structure import map_host, name_hint

    for name in ("fon-header-map-mobil.jpg", "/img/chart_2024.png", "screenshot2.png", "https://cdn.example.test/a/salesChart.png?v=2",
                 "/img/Site%20Map.png", "/img/photos.jpg"):
        assert name_hint(name), name
    for name in ("roadmap.png", "sitemap-icon.svg", "vegetable.jpg", "/products/logo.png", "https://maps.example.test/maps/vt?pb=1",
                 "data:image/svg+xml;base64,bWFwIGNoYXJ0IG1hcA==", "data:image/svg+xml,%3Csvg%20id='map'%3E%3C/svg%3E"):
        assert not name_hint(name), name
    assert map_host("https://a.tile.openstreetmap.org/7/63/42.png") and map_host("//maps.gstatic.com/mapfiles/transparent.png")
    assert not map_host("https://maps.gstatic.com.example.test/x.png") and not map_host("/maps.googleapis.com/x.png")
    plain = images_check('<div class="gorsel"><img src="/img/roadmap.png" alt=""><img src="/img/vegetable.jpg" alt="">'
                         '<img src="data:image/svg+xml,%3Csvg%20id=%27map%27%3E%3C/svg%3E" alt=""></div>')
    assert [f for f in plain.findings if "image(s) on" in f.title and "layout shift" not in f.title] == [] and plain.evidence["empty_alt_not_assessed_count"] == 3
    assert plain.evidence["map_images_left_out_count"] == 0


def test_explicit_chart_context_retains_informative_images():
    check = images_check('<figure><img src="/img/sales-chart_2024.png" alt=""><figcaption>Chart of revenue</figcaption></figure>'
                         '<figure><img src="/img/aylik.png" alt=""><figcaption>Grafik: Aylık satışlar</figcaption></figure>')
    [finding] = [f for f in check.findings if "meaningful" in f.title]
    assert finding.title == "2 likely meaningful image(s) on 1 page(s): 0 with no alt text, 2 with an empty alt"
    assert {row["src"]: row["why"] for row in finding.evidence["images"]} == {
        "/img/sales-chart_2024.png": "informative caption: Chart of revenue", "/img/aylik.png": "informative caption: Grafik: Aylık satışlar"}
    assert any("file name and figure wrappers do not prove purpose." in note for note in finding.notes)
    pytest.importorskip("fastapi")
    from maya_audit_web import wording

    assert all(wording.note(note, "tr")[1] for note in finding.notes)


# -- FA-015: a Turkish page called Portuguese (DECISIONS 194) -------------------------------------------------------------
ALLERGENS = "tavuk süt gluten yumurta hardal kereviz soya susam balık fıstık badem ceviz kabuklu yumuşakça sülfit".split()
DISHES = ("Izgara tavuk şiş", "Fırın sütlaç", "Mercimek çorbası", "Kıymalı pide", "Susamlı simit", "Cevizli baklava", "Balık buğulama")
# An allergen table as its text reads: the allergens across the top, then each dish with an "o" under four of them (89 x 4 = 356).
ALLERGEN_TABLE = "Alerjen tablosu " + " ".join(ALLERGENS) + " " + " ".join(f"{DISHES[n % len(DISHES)]} {n + 1} o o o o" for n in range(89))
CAMPAIGN_WORDS = "detaylı bilgi süresi fırsatı taksit peşin kampanya indirim kupon geçerlidir alışveriş sepette kargo bedava ürünlerde".split()
# A campaign list as its text reads: a marketplace's name with a suffix after an apostrophe, and shop addresses.
CAMPAIGNS = " ".join(
    [f"Trendyol'da {CAMPAIGN_WORDS[n % 15]} {CAMPAIGN_WORDS[(n + 3) % 15]} {CAMPAIGN_WORDS[(n + 7) % 15]}" for n in range(873)]
    + [f"Örnekpazar’de {CAMPAIGN_WORDS[(n + 1) % 15]} {CAMPAIGN_WORDS[(n + 5) % 15]}" for n in range(506)]
    + [f"www.ornekmagaza-{n}.com adresinde {CAMPAIGN_WORDS[n % 15]} https://kampanya.example.test/de/{n} bilgi@ornekmagaza.com" for n in range(308)])
PORTUGUESE = ("Os nossos produtos são feitos com muito cuidado para que você tenha uma experiência melhor em cada compra. Não há "
              "mais dúvidas: a equipa responde por telefone ou por correio, mas é preciso dizer o número do pedido. Uma parte dos "
              "artigos chega em dois dias, com um desconto que não se repete, para os clientes das cidades mais distantes. ")
ENGLISH = ("This page is about the services that we offer and the people who work with you from the first day. You can read what "
           "is included, how long it takes and what it will cost, and you will find our address at the end of the page. ")


def lang_check(pages_html):
    result, pages = site(pages_html)
    return str9_language(result, CFG, pages, set(), StructureData())


def test_a_turkish_allergen_table_and_a_campaign_list_are_not_portuguese():
    """A menu's allergen table, an "o" under each allergen (356 of them), and a campaign page with "…'da" 873 times,
    "…'de" 506 times and 308 ".com" addresses: "<html lang> says Turkish, but the text reads as Portuguese"."""
    assert ALLERGEN_TABLE.split().count("o") == 356 and CAMPAIGNS.count("Trendyol'da") == 873 and CAMPAIGNS.count("’de ") == 506
    assert CAMPAIGNS.count(".com") >= 308
    assert detect_language(ALLERGEN_TABLE)["language"] == "pt"              # what it is called without the page's language
    table = detect_language(ALLERGEN_TABLE, declared="tr")
    assert table["language"] != "pt" and "pt" not in table["hits"] and "o" in NOT_FOREIGN_IN["tr"]
    for declared in (None, "tr"):
        campaign = detect_language(CAMPAIGNS, declared=declared)
        assert campaign["language"] not in ("pt", "it", "nl") and not {"pt", "it", "nl"} & set(campaign["hits"]), (declared, campaign)
    # Addresses are taken out before words are counted, and a word with an apostrophe counts by the part before it.
    assert words_of("Trendyol'da ve Örnekpazar’de: www.ornek.com, https://ornek.example.test/de/ bilgi@ornek.com") == ["Trendyol", "ve", "Örnekpazar"]
    assert block_language("Trendyol'da detaylı bilgi için www.ornek.com adresine bakın, kampanya süresi yakında doluyor") == "tr"
    assert set("a e no na il van at as can para es un sus der den dem hat sur te er u".split()) <= NOT_FOREIGN_IN["tr"]
    check = lang_check({"/": html(f"<h1>Ana</h1><p>{TR}</p>"), "/alerjenler/": html(f"<h1>Alerjenler</h1><p>{ALLERGEN_TABLE}</p>"),
                        "/kampanyalar/": html(f"<h1>Kampanyalar</h1><p>{CAMPAIGNS}</p>")})
    assert [f.title for f in check.findings if "does not match" in f.title] == []
    assert text_assessable({"html_lang": "tr", "_visible_text": ALLERGEN_TABLE}, {"pt"})[0] is False


def test_a_portuguese_page_declared_turkish_is_still_called_portuguese_and_english_is_english():
    assert detect_language(PORTUGUESE * 2, declared="tr")["language"] == "pt" and detect_language(PORTUGUESE * 2)["language"] == "pt"
    for declared in (None, "en", "tr"):
        assert detect_language(ENGLISH * 2, declared=declared)["language"] == "en", declared
    assert detect_language(TR * 2, declared="tr")["language"] == "tr" and detect_language(TR * 2, declared="en")["language"] == "tr"
    # Three paragraphs: STR-9 judges a page from 150 words of main text (DECISIONS 224).
    check = lang_check({"/": html(f"<h1>Ana</h1><p>{TR}</p>"), "/pt/": html(f"<h1>Produtos</h1><p>{PORTUGUESE * 3}</p>")})
    [finding] = [f for f in check.findings if "does not match" in f.title]
    assert finding.title == "1 page(s) declare a <html lang> that does not match the content language"
    assert [(path(row["url"]), row["declared"], row["detected"]) for row in finding.evidence["pages"]] == [("/pt/", "tr", "pt")]
    assert page_sentence(page_item(to_jsonable(finding), f"{ROOT}/pt/")) == "<html lang> says Turkish, but the text reads as Portuguese"


# -- FA-018: an About page under another name, a Contact page that was linked and not read (DECISIONS 197) ---------------
def basic_check(pages_html, **crawl):
    result, pages = site(pages_html)
    for name, value in crawl.items():
        setattr(result, name, value)
    return str21_basic_pages(result, CFG, pages, set())


BASICS = {"/": html(f"<h1>Ana</h1><p>{TR}</p>"), "/urunler/": html(f"<h1>Ürünler</h1><p>{TR}</p>"), "/iletisim/": html(f"<h1>İletişim</h1><p>{TR}</p>"),
          "/sss/": html(f"<h1>Sorular</h1><p>{TR}</p>")}


def test_an_about_page_called_hikayemiz_is_found():
    """A site whose About page is /hikayemiz/ ("our story"): "No About page was found among the pages of the site"."""
    check = basic_check({**BASICS, "/hikayemiz/": html(f"<h1>Nasıl başladık</h1><p>{TR}</p>", title="Nasıl başladık | Örnekmağaza")})
    assert check.findings == [] and check.status == "pass" and [path(url) for url in check.evidence["found"]["About"]] == ["/hikayemiz/"]
    assert {"hikayemiz", "bizim-hikayemiz", "tarihce", "tarihcemiz", "bizi-taniyin", "ekibimiz", "vizyon-misyon", "misyon-vizyon",
            "sirket-profili"} == set(ADDRESS_ONLY["About"])
    assert {"iletisim-bilgileri", "bize-yazin"} <= set(BASIC_PAGES["Contact"]) and {"sik-sorulan-sorular", "merak-edilenler"} <= set(BASIC_PAGES["FAQ"])
    for address in ("/Tarihçemiz/", "/kurumsal-bilgi/bizi-taniyin", "/tr/vizyon-misyon.html"):  # compared the Turkish way
        assert basic_check({**BASICS, address: html(f"<h1>Biz</h1><p>{TR}</p>")}).findings == [], address
    # These words mark the About page in an address only: a blog post titled with one of them is not it.
    post = basic_check({**BASICS, "/blog/yazi-3/": html(f"<h1>Hikayemiz: bir fırının ilk yılı</h1><p>{TR}</p>", title="Hikayemiz | Blog")})
    assert [f.title for f in post.findings] == ["No About page was found among the 5 page(s) of the site"]


def test_a_contact_page_linked_from_the_footer_and_not_read_is_not_called_missing():
    """A site read whole, except the page its footer links as "Bize Ulaşın" (robots.txt disallows it): "No Contact page
    was found among the pages of the site"."""
    footer = '<ul class="alt-menu"><li><a href="/bize-ulasin">Bize Ulaşın</a></li><li><a href="/urunler/">Ürünler</a></li></ul>'
    pages = {address: html(f"<h1>{address}</h1><p>{TR}</p>", footer=footer) for address in ("/", "/urunler/", "/hakkimizda/", "/sss/")}
    check = basic_check(pages)
    assert check.findings == [] and check.status == "pass"
    assert check.summary == ("No basic page is missing among the 4 page(s) read. "
                             "Contact: linked from the footer (/bize-ulasin), not among the pages read.")
    assert check.evidence["linked_from_footer_not_read"] == {"Contact": {"url": f"{ROOT}/bize-ulasin", "anchor": "Bize Ulaşın", "linked_from": f"{ROOT}/"}}
    assert check.evidence["found"]["Contact"] == []
    # With another kind really missing, the finding names that one only, and the summary still says where Contact is.
    del pages["/sss/"]
    check = basic_check(pages)
    [finding] = check.findings
    assert finding.title == "No FAQ page was found among the 3 page(s) of the site" and finding.evidence["not_found"] == ["FAQ"]
    assert check.summary == "1 finding: not found: FAQ. Contact: linked from the footer (/bize-ulasin), not among the pages read."
    # By its address alone (an icon link), and a footer link to a page that was read is that page.
    icon = {address: html(f"<h1>{address}</h1><p>{TR}</p>", footer='<a href="/iletisim-bilgileri/"><img src="/i/zarf.svg" alt="zarf"></a>')
            for address in ("/", "/urunler/", "/hakkimizda/", "/sss/")}
    assert "Contact: linked from the footer (/iletisim-bilgileri/)" in basic_check(icon).summary
    read = basic_check({**{address: html(f"<h1>{address}</h1><p>{TR}</p>", footer='<a href="/s/7/">Bize Ulaşın</a>')
                           for address in ("/", "/urunler/", "/hakkimizda/", "/sss/")}, "/s/7/": html(f"<h1>Şubemiz</h1><p>{TR}</p>")})
    assert [path(url) for url in read.evidence["found"]["Contact"]] == ["/s/7/"] and "linked_from_footer_not_read" not in read.evidence
    edges = extract_link_edges(html("<p>x</p>", footer=footer, header='<a href="/sepet">Sepet</a>'), ROOT + "/")
    assert {path(edge["target"]): edge.get("footer", False) for edge in edges} == {"/": False, "/sepet": False, "/bize-ulasin": True, "/urunler/": True}
    pytest.importorskip("fastapi")
    from maya_audit_web import wording

    assert wording.line(check.summary, "tr", check_id="STR-21") == (
        "1 bulgu: bulunamadı: SSS. İletişim: alt bilgiden bağlantı verilmiş (/bize-ulasin), okunan sayfalar arasında değil.", True)


def test_a_fully_read_site_with_no_about_page_and_no_footer_link_still_says_so():
    footer = '<a href="/urunler/">Ürünler</a>'
    check = basic_check({address: html(f"<h1>{address}</h1><p>{TR}</p>", footer=footer) for address in ("/", "/urunler/", "/iletisim/", "/sss/")})
    [finding] = check.findings
    assert finding.title == "No About page was found among the 4 page(s) of the site" and finding.severity.value == "Info"
    assert check.summary == "1 finding: not found: About." and "linked_from_footer_not_read" not in check.evidence
    # A link in the menu is not a footer link, and an unfinished crawl is still "not assessed".
    menu = basic_check({address: html(f"<h1>{address}</h1><p>{TR}</p>", header='<a href="/hakkimizda/">Hakkımızda</a>')
                        for address in ("/", "/urunler/", "/iletisim/", "/sss/")})
    assert [f.title for f in menu.findings] == ["No About page was found among the 4 page(s) of the site"]
    cut = basic_check({address: html(f"<h1>{address}</h1><p>{TR}</p>") for address in ("/", "/urunler/")}, stop_reason=StopReason.PAGE_CAP)
    assert cut.status == "not_assessed" and cut.findings == [] and "may exist" in cut.summary


# -- FA-019: a related-posts block called "Shared header/footer" and "the whole site" (DECISIONS 198) --------------------
RELATED = ('<div class="post-4711 post-related"><a href="/blog/yazi-0/"><img src="/kapak/0.jpg" alt=""></a>'
           '<a href="/blog/yazi-1/"><img src="/kapak/1.jpg" alt=""></a></div>')
HEART = '<a href="/hesabim#/favoriler"><svg width="20" height="20"><path d="M0 0"/></svg></a>'


def no_text_check(pages_html):
    result, pages = site(pages_html)
    return str14_anchor_text(result, CFG, pages, set())


def test_a_related_posts_block_is_named_by_its_block_and_is_not_the_whole_site():
    """Six blog posts with picture links in a "related posts" block, on a site of 46 pages: "Shared header/footer: link
    to … has no text (on 4 page(s))", "Affects the whole site"."""
    posts = {f"/blog/yazi-{n}/": html(f"<h1>Yazı {n}</h1><p>{TR}</p>{RELATED}") for n in range(6)}
    others = {f"/urun-{n}/": html(f"<h1>Ürün {n}</h1><p>{TR}</p>") for n in range(40)}
    check = no_text_check({**posts, **others})
    [finding] = check.findings                                         # the two picture links of the block are one finding
    assert finding.title == "“div.post-related” block: 2 link(s) have no text (on 6 page(s) of /blog/)" and "Shared header/footer" not in finding.title
    assert finding.scope["kind"] == "template" and finding.scope["count"] == 6 and finding.severity.value == "S4"
    assert finding.evidence["shared_element"] == {"type": "links", "href": "/blog/yazi-0/", "hrefs": ["/blog/yazi-0/", "/blog/yazi-1/"], "links": 2,
                                                  "block": "div.post-related", "where": "repeated", "kind": "link_no_text", "pages": 6, "section": "blog"}
    saved = to_jsonable(check.findings)
    summary = problem_summary(saved, {f.id: f.scope["_all_urls"] for f in check.findings}, pages_checked=46)
    # One grouped line that names the block and the section: no line on any of the six pages' rows, and no "whole site".
    assert summary["by_page"] == [] and summary["whole_site"]["problems"] == 1 and summary["whole_site"]["finding_ids"] == [saved[0]["id"]]
    [listed] = summary["whole_site"]["shared_elements"]
    assert (listed["kind"], listed["pages"], listed["element"]["block"], listed["element"]["section"]) == ("link_no_text", 6, "div.post-related", "blog")
    markdown = "\n".join(problems_by_page_lines(summary, {saved[0]["id"]: saved[0]["title"]}, ROOT))
    assert "| Whole site or one section | 1 | Low | “div.post-related” block: 2 link(s) have no text (on 6 page(s) of /blog/) |" in markdown
    assert "| Whole site |" not in markdown and "Also affected by" not in markdown and "/blog/yazi-0/`" not in markdown
    # Four of a section's six pages was enough for "the whole site" (decision 183): it is still one finding, about those pages.
    four = no_text_check({**{address: text if n < 4 else html(f"<h1>Yazı {n}</h1><p>{TR}</p>") for n, (address, text) in enumerate(posts.items())}, **others})
    assert [(f.title, f.scope["kind"]) for f in four.findings] == [("“div.post-related” block: 2 link(s) have no text (on 4 page(s) of /blog/)", "template")]
    # In no block the markup names: "Repeated block", by the link's address.
    bare = no_text_check({**{address: html(f'<h1>Yazı</h1><p>{TR}</p><a href="/blog/yazi-0/"><img src="/kapak/0.jpg" alt=""></a>') for address in posts}, **others})
    assert [f.title for f in bare.findings] == ["Repeated block: link to /blog/yazi-0/ has no text (on 6 page(s) of /blog/)"]
    split = shared_elements.split({ROOT + address: {"k"} for address in posts}, [ROOT + address for address in [*posts, *others]])
    assert split == {"k"} and split.sections == {"k": ["blog"]} and split.section("k", [ROOT + address for address in posts]) == "blog"
    assert shared_elements.label("footer", "div.x") == "Shared header/footer" and shared_elements.label("aside", "div.x") == "“div.x” block"
    assert shared_elements.label(None) == shared_elements.label("repeated") == "Repeated block"
    pytest.importorskip("fastapi")
    from maya_audit_web import strings, summary as web_summary, wording

    row = web_summary.item(saved[0])
    assert row["affects"] == strings.t("result.affects.section", count=6, section="blog") == "Affects 6 pages of /blog/"
    assert row["affects"] != strings.t("result.affects.sitewide") and "whole site" not in row["affects"]
    from maya_audit_web import practical

    table = practical.by_page(summary, [row])
    assert [(line["label"], line["problems"], line["lines"]) for line in table["rows"]] == [
        ("Whole site or one section", 1, ["“div.post-related” block: 2 links have no text (on 6 pages of /blog/) · div.post-related → /blog/yazi-0/, /blog/yazi-1/"])]
    assert row["title_shown"] == "“div.post-related” block: 2 links have no text (on 6 pages of /blog/) · div.post-related → /blog/yazi-0/, /blog/yazi-1/"
    assert wording.title("STR-14", finding.title, "tr") == ("“div.post-related” bloğu: 2 bağlantının metni yok (6 sayfada /blog/ bölümünde)", True)
    assert wording.title("STR-14", bare.findings[0].title, "tr") == ("Tekrarlanan blok: /blog/yazi-0/ bağlantısının metni yok (6 sayfada /blog/ bölümünde)", True)


def test_a_header_icon_link_on_every_page_is_still_shared_header_footer_and_site_wide():
    check = no_text_check({f"/sayfa-{n}/": html(f"<h1>Sayfa {n}</h1><p>{TR}</p>", header=HEART) for n in range(50)})
    [finding] = check.findings
    assert finding.title == "Shared header/footer: link to /hesabim#/favoriler has no text (on 50 page(s))"
    assert finding.scope["kind"] == "sitewide" and finding.scope["count"] == 50 and "section" not in finding.evidence["shared_element"]
    summary = problem_summary(to_jsonable(check.findings), pages_checked=50)
    assert summary["whole_site"]["problems"] == 1 and summary["by_page"] == [] and summary["whole_site"]["shared_elements"][0]["kind"] == "link_no_text"
    pytest.importorskip("fastapi")
    from maya_audit_web import strings, summary as web_summary, wording

    assert web_summary.item(to_jsonable(finding))["affects"] == strings.t("result.affects.sitewide") == "Affects the whole site"
    assert wording.title("STR-14", finding.title, "tr") == ("Ortak üst/alt bölüm: /hesabim#/favoriler bağlantısının metni yok (50 sayfada)", True)


# -- FA-013: a collapsed copy of a real table (DECISIONS 178) --------------------------------------------------------------
TABLE = ('<table><tr><th scope="col">İşlem</th><th scope="col">Bizde</th><th scope="col">Piyasada</th></tr>'
         "<tr><td>Alım Satım Komisyonu</td><td>Ücretsiz</td><td>Ücretli</td></tr><tr><td>Canlı Veri</td><td>Ücretsiz</td><td>30 TL</td></tr>"
         "<tr><td>Hesap İşletimi</td><td>Ücretsiz</td><td>25 TL</td></tr></table>")


def grid(toggle=""):
    rows = "".join(f'<div class="satir"><div class="bas"><h4{toggle}>{label}</h4></div><div class="govde"><span>Bizde</span><span>{price}</span></div></div>'
                   for label, price in (("Alım Satım Komisyonu", "Ücretsiz"), ("Canlı Veri", "30 TL"), ("Hesap İşletimi", "25 TL")))
    return f'<div class="kart-govde">{rows}</div>'


def tables_check(body, at="/ucretler/"):
    result, pages = site({"/": html(f"<h1>Ana</h1><p>{TR}</p>"), at: html(f"<h1>Ücretler</h1><p>{TR}</p>{body}")})
    return str8_semantic_tables(result, CFG, pages, set(), set())


def test_a_collapsed_copy_of_a_real_table_is_not_reported():
    """A fee page with real tables (<th scope="col">) and, in an accordion, the same rows again as <div>s:
    "lay out pricing or spec comparisons as <div> grids instead of <table>"."""
    toggle = grid(' data-toggle="collapse" data-target="#tablo"')
    folded = f'<div id="acc" class="accordion-page"><div class="card">{toggle}</div></div>'
    check = tables_check(TABLE + folded)
    assert check.findings == [] and check.evidence["grids_left_out_count"] == 1 and check.evidence["real_tables"] == 1
    assert check.evidence["grids_left_out"][0]["why"] == "inside a collapse or accordion"
    for wrapper in ('<div class="collapse" id="x">{}</div>', '<div data-bs-toggle="collapse">{}</div>', '<section aria-expanded="false">{}</section>'):
        assert tables_check(wrapper.format(grid())).findings == [], wrapper
    # Not folded away, but the same rows as the real table beside it: a second view of the table, not a missing one.
    copy = tables_check(TABLE + grid())
    assert copy.findings == [] and copy.evidence["grids_left_out"][0]["why"] == "3 of 3 row labels are in a real <table> with header cells on this page"
    analysis = analyze_html(html(TABLE + folded))
    assert analysis["tables"][0]["row_labels"] == ["İşlem", "Alım Satım Komisyonu", "Canlı Veri", "Hesap İşletimi"]
    assert analysis["div_grids"][0]["in_collapse"] is True and analysis["div_grids"][0]["row_labels"][0] == "Alım Satım Komisyonu"


def test_a_pricing_page_with_only_a_div_grid_is_still_reported():
    for body in (grid(), grid() + "<table><tr><td>Not</td><td>KDV dahildir</td></tr></table>"):  # a table without headers, about something else
        check = tables_check(body)
        [finding] = check.findings
        assert finding.title == "1 page(s) lay out pricing or spec comparisons as <div> grids instead of <table>" and finding.severity.value == "S4"
        assert check.evidence["grids_left_out_count"] == 0 and finding.evidence["grids"][0]["in_collapse"] is False


# -- FA-021: a <div> grid on a page that has real tables; an empty <table> (DECISIONS 200) --------------------------------
REAL_TABLE = ('<table class="besin"><tr><th>Besin</th><th>100 g</th></tr>'
              + "".join(f"<tr><td>Değer {n}</td><td>{n} g</td></tr>" for n in range(1, 11)) + "</table>")
PRICE_GRID = ('<section id="paketler" class="fiyat"><div class="paket-liste">'
              + "".join(f'<div class="paket"><span>{name}</span><span>{price}</span><span>Aylık</span></div>'
                        for name, price in (("Başlangıç", "90 TL"), ("Standart", "150 TL"), ("Kurumsal", "400 TL"))) + "</div></section>")


def test_a_page_with_a_real_table_is_not_told_to_use_one_and_its_empty_table_is_reported():
    """A product page with an 11-row nutrition table (with <th>), an empty <table> a script fills, and a price list
    laid out in <div>s: "1 page(s) lay out pricing or spec comparisons as <div> grids instead of <table>", with nothing
    saying which grid."""
    check = tables_check(REAL_TABLE + '<table id="stok"></table>' + PRICE_GRID, at="/urun/kuru-kayisi/")
    [finding] = check.findings
    assert finding.title == "1 page(s) contain an empty <table> element" and finding.severity.value == "S4" and finding.confidence.value == "verified"
    assert finding.how_to_fix == "Remove the empty <table>, or put the rows it was meant to hold into it."
    assert finding.notes == ["Empty in the HTML the server sent; a script may fill it."]
    assert finding.evidence["pages"] == [{"url": f"{ROOT}/urun/kuru-kayisi/", "tables": 1}] and check.evidence["empty_tables"] == 1
    [left] = check.evidence["grids_left_out"]
    assert left["why"] == "the page has a real <table> with header cells and 11 rows" and left["selector"] == "main > section#paketler.fiyat > div.paket-liste"
    saved = to_jsonable(finding)
    assert page_item(saved, f"{ROOT}/urun/kuru-kayisi/")["kind"] == "table_empty"
    assert page_sentence(page_item(saved, f"{ROOT}/urun/kuru-kayisi/")) == "Contains 1 empty <table> element"
    # A page in the RND-1 gap (its content appears only after JavaScript) is skipped: its table may be filled by then.
    result, pages = site({"/": html(f"<h1>Ana</h1><p>{TR}</p>"), "/stok/": html(f'<h1>Stok</h1><p>{TR}</p><table id="stok"></table>')})
    assert str8_semantic_tables(result, CFG, pages, set(), {f"{ROOT}/stok/"}).findings == []
    assert [f.title for f in str8_semantic_tables(result, CFG, pages, set(), set()).findings] == ["1 page(s) contain an empty <table> element"]
    # A table with a header row and nothing under it is not "a real table" that excuses a grid.
    headed = tables_check("<table><tr><th>Paket</th><th>Fiyat</th></tr></table>" + PRICE_GRID)
    assert [f.title for f in headed.findings] == ["1 page(s) lay out pricing or spec comparisons as <div> grids instead of <table>"]
    pytest.importorskip("fastapi")
    from maya_audit_web import catalog, strings, wording

    assert wording.title("STR-8", finding.title, "en") == ("1 page contains an empty <table> element", True)
    assert wording.title("STR-8", finding.title, "tr") == ("1 sayfada boş bir <table> öğesi var", True)
    assert wording.fix(finding.how_to_fix, "tr") == ("Boş <table> öğesini kaldırın ya da içermesi gereken satırları içine koyun.", True)
    assert wording.note(finding.notes[0], "tr")[1] and wording.expected(finding.expected, "tr")[1]
    assert "empty table" in catalog.note("STR-8", finding.title)["why"].lower()
    assert strings.t("bypage.table_empty", tables=1) == "Contains 1 empty <table> element"


def test_a_div_grid_finding_says_where_the_grid_is_and_what_its_first_row_holds():
    check = tables_check(PRICE_GRID, at="/paketler/")                  # a pricing page with only a <div> grid: still reported
    [finding] = check.findings
    assert finding.title == "1 page(s) lay out pricing or spec comparisons as <div> grids instead of <table>" and finding.severity.value == "S4"
    [grid_row] = finding.evidence["grids"]
    assert grid_row["selector"] == "main > section#paketler.fiyat > div.paket-liste" and grid_row["first_row"] == "Başlangıç | 90 TL | Aylık"
    assert check.evidence["grids_left_out_count"] == 0 and check.evidence["empty_tables"] == 0
    saved = to_jsonable(finding)
    # Named by the heading it sits under since DECISIONS 223; the selector stays in the evidence.
    line = "<div> grid under “Ücretler”; first row: “Başlangıç | 90 TL | Aylık”"
    assert page_sentence(page_item(saved, f"{ROOT}/paketler/")) == line
    # A report saved before the heading was kept keeps its line with the selector.
    before = {**saved, "evidence": {"grids": [{key: value for key, value in saved["evidence"]["grids"][0].items() if key not in ("heading", "label")}]}}
    assert page_sentence(page_item(before, f"{ROOT}/paketler/")) == (
        "<div> grid at main > section#paketler.fiyat > div.paket-liste; first row: “Başlangıç | 90 TL | Aylık”")
    markdown = "\n".join(problems_by_page_lines(problem_summary([saved], pages_checked=2), {saved["id"]: saved["title"]}, ROOT))
    assert line.replace("|", "\\|") in markdown                         # a Markdown table writes | as \|
    # A report saved before the selector was kept says it the way it always did.
    old = {**saved, "evidence": {"grids": [{key: value for key, value in saved["evidence"]["grids"][0].items()
                                            if key not in ("selector", "first_row", "heading", "label")}]}}
    assert page_sentence(page_item(old, f"{ROOT}/paketler/")) == "Lays out a pricing or spec comparison as <div> grids instead of <table>"
    pytest.importorskip("fastapi")
    from maya_audit_web import strings

    values = page_item(saved, f"{ROOT}/paketler/")["values"]
    strings.set_language("tr")
    try:
        assert strings.t("bypage.div_grid_heading", **values) == "“Ücretler” başlığı altında <div> ızgarası; ilk satır: “Başlangıç | 90 TL | Aylık”"
        assert strings.t("bypage.div_grid", **page_item(before, f"{ROOT}/paketler/")["values"]) == (
            "main > section#paketler.fiyat > div.paket-liste konumundaki <div> ızgarası; ilk satır: “Başlangıç | 90 TL | Aylık”")
    finally:
        strings.set_language("en")


# -- made-up sites that answer requests, for the alarms that depend on a second request ----------------------------------
import httpx  # noqa: E402

from maya_audit.audit import run_audit  # noqa: E402
from maya_audit.checks.index import idx3_redirects  # noqa: E402
from test_blocked_and_small_sites import no_lookups  # noqa: E402,F401
from test_deadline_hosted_hardening import QUIET  # noqa: E402

KAFE = "https://demo-kafe.test"
HTML_TYPE = {"content-type": "text/html; charset=utf-8"}


def answer(body="", *, title="Sayfa | Demo Kafe", status=200):
    return httpx.Response(status, headers=HTML_TYPE, text=f'<!doctype html><html lang="tr"><head><title>{title}</title></head><body>'
                                                         f'<header><nav><a href="/">Ana Sayfa</a></nav></header><main><h1>{title}</h1><p>{TR}</p>{body}</main></body></html>')


def to_itself(path):
    return httpx.Response(301, headers={"location": path})


def audited(routes, start=KAFE + "/", sitemap=("/",), robots=None, **options):
    """The whole audit over made-up sites held in memory. `routes` maps a path of the audited site, or a (host, path)
    of another site, to a response or to a function of how many times that address has been asked for (1, 2, ...).
    `outcome.asked` lists every (host, path) requested, in order; no socket is opened."""
    asked, counts = [], {}
    own = httpx.URL(start).host
    robots = {own: "User-agent: *\nAllow: /\n", **(robots or {})}

    def respond(request):
        host, path = request.url.host, request.url.path
        asked.append((host, path))
        counts[(host, path)] = counts.get((host, path), 0) + 1
        if path == "/robots.txt":
            return (httpx.Response(200, text=robots[host], headers={"content-type": "text/plain"}) if host in robots
                    else httpx.Response(404, text="none"))
        if host == own and path == "/sitemap.xml":
            return httpx.Response(200, headers={"content-type": "application/xml"}, text=(
                '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                + "".join(f"<url><loc>https://{own}{listed}</loc></url>" for listed in sitemap) + "</urlset>"))
        route = routes.get(path if host == own else (host, path))
        if route is None:
            return answer(title="Bulunamadı", status=404)
        return route(counts[(host, path)]) if callable(route) else route

    outcome = run_audit(start, CrawlConfig(**{**QUIET, "max_pages": 10, **options}), httpx.MockTransport(respond))
    outcome.by_id = {check.check_id: check for check in outcome.checks}
    outcome.asked = asked
    outcome.rechecks = [request.url.removeprefix(KAFE) for request in outcome.result.requests if request.purpose == "redirect_recheck"]
    outcome.int4 = next(gate for gate in outcome.gates if gate.check_id == "INT-4")  # one user agent, robots.txt obeyed, paced
    return outcome


# -- FA-016: a URL that sometimes redirects to itself was "a redirect loop: the URL never resolves" (DECISIONS 195) --------
def test_a_url_that_redirects_to_itself_on_every_second_request_is_intermittent_not_a_loop(no_lookups):
    flaky = lambda n: to_itself("/kampanyalar") if n % 2 else answer(title="Kampanyalar | Demo Kafe")  # noqa: E731
    outcome = audited({"/": answer('<a href="/kampanyalar">Kampanyalar</a>'), "/kampanyalar": flaky})
    crawl = next(p for p in outcome.result.pages if p.url == KAFE + "/kampanyalar")
    assert crawl.status == 301 and crawl.redirect_location == KAFE + "/kampanyalar"  # what the crawl alone saw: a self-redirect
    [finding] = outcome.by_id["IDX-3"].findings
    assert finding.title == "1 URL(s) intermittently redirect to themselves; the page loads on another try"
    assert (finding.severity.value, finding.confidence.value) == ("S3", "verified") and finding.scope["urls"] == [KAFE + "/kampanyalar"]
    assert finding.how_to_fix == "Compare the successful and cyclic requests at the recorded times. Identify the cause before changing configuration; then repeat the same client checks."
    attempts = finding.evidence["rechecks"][KAFE + "/kampanyalar"]
    assert [a["outcome"] for a in attempts] == ["resolves", "loops", "resolves"] and attempts[0]["hops"][0]["status"] == 200
    assert not [f for check in outcome.checks for f in check.findings if f.severity.value == "S1"]
    assert outcome.rechecks.count("/kampanyalar") == 3 and outcome.int4.state == "compliant" and not outcome.int4.evidence["requests_to_disallowed_urls"]


def test_a_homepage_that_answered_in_the_crawl_and_redirects_to_itself_on_a_recheck_is_included(no_lookups):
    home = lambda n: to_itself("/") if n % 2 == 0 else answer(title="Demo Kafe | Ana Sayfa")  # noqa: E731
    outcome = audited({"/": home})
    assert next(p for p in outcome.result.pages if p.url == KAFE + "/").status == 200  # the crawl has the page, not the redirect
    [finding] = outcome.by_id["IDX-3"].findings
    assert finding.title.startswith("1 URL(s) intermittently redirect to themselves") and finding.scope["urls"] == [KAFE + "/"]
    assert [a["outcome"] for a in finding.evidence["rechecks"][KAFE + "/"]] == ["loops", "resolves", "loops"]
    assert outcome.by_id["IDX-3"].evidence["homepage_rechecks"] == ["loops", "resolves", "loops"]


def test_a_url_that_redirects_to_itself_every_time_is_still_a_blocker_and_a_site_without_redirects_is_asked_only_for_its_homepage(no_lookups):
    outcome = audited({"/": answer('<a href="/dongu">Döngü</a>'), "/dongu": to_itself("/dongu")})
    [loop] = outcome.by_id["IDX-3"].findings
    assert loop.title == "1 redirect loop(s) observed in the tested native client" and (loop.severity.value, loop.confidence.value) == ("S1", "verified")
    assert [a["outcome"] for a in loop.evidence["rechecks"][KAFE + "/dongu"]] == ["loops", "loops", "loops"] and loop.evidence["attempts_per_url"] == 4
    assert outcome.rechecks == ["/dongu"] * 3 + ["/"] * 3

    # Without the re-checks (a crawl that was cut, a page Maya's own crawler did not read) one response is never a
    # blocker: it is said as seen once, Medium and Inferred.
    outcome.result.index.redirect_rechecks = {}
    [once] = idx3_redirects(outcome.result, CrawlConfig(**QUIET)).findings
    assert once.title == "1 URL(s) have observed redirect cycles; verification is incomplete"
    assert (once.severity.value, once.confidence.value) == ("S3", "inferred") and once.evidence["not_rechecked_because"]

    # A healthy site: no redirect, so the only extra requests are the homepage's three, and nothing is reported.
    healthy = audited({"/": answer('<a href="/menu">Menü</a>'), "/menu": answer(title="Menü | Demo Kafe")})
    assert healthy.rechecks == ["/", "/", "/"] and healthy.by_id["IDX-3"].findings == [] and healthy.by_id["IDX-3"].status == "pass"
    assert healthy.by_id["IDX-3"].evidence["recheck_requests"] == 3


# -- FA-017: a working link to another site was "most likely leads nowhere" (DECISIONS 196) -------------------------------
OTHER = "other-shop.test"
LINKED = ('<a href="/hakkimizda">Hakkımızda</a> <a href="https://other-shop.test/hakkimizda">Grup şirketimiz</a>')


def other_site(status=200, robots=None, **options):
    routes = {"/": answer(LINKED), "/hakkimizda": answer(title="Hakkımızda | Demo Kafe"),
              (OTHER, "/hakkimizda"): answer(title="Hakkımızda | Diğer Mağaza", status=status)}
    outcome = audited(routes, sitemap=("/", "/hakkimizda"), robots={OTHER: robots or "User-agent: *\nAllow: /\n"}, **options)
    outcome.other = [path for host, path in outcome.asked if host == OTHER]
    outcome.links = [f for f in outcome.by_id["IDX-6"].findings if "another site" in f.title]
    return outcome


def test_a_link_to_another_site_that_answers_with_a_page_is_not_reported(no_lookups):
    outcome = other_site(200)
    assert outcome.other == ["/robots.txt", "/hakkimizda"]  # the other site's robots.txt first, then the address, once
    assert outcome.links == [] and outcome.by_id["IDX-6"].status == "pass"
    evidence = outcome.by_id["IDX-6"].evidence
    assert evidence["links_to_another_site_at_one_of_this_sites_paths"] == 1 and evidence["other_site_requests"] == 1
    assert evidence["of_which_the_other_address_answers_with_a_page_or_a_redirect"] == 1
    assert "nowhere" not in json.dumps(to_jsonable(outcome.by_id["IDX-6"]))
    # Links to other sites are checked by default now (DECISIONS 211); the address IDX-6 asked is not asked again.
    assert outcome.int4.state == "compliant" and outcome.result.config["check_external_links"] is True


def test_a_link_to_another_site_that_answers_404_is_reported_with_the_status(no_lookups):
    outcome = other_site(404)
    [dead] = outcome.links
    assert dead.title == ("1 link(s) on 1 page(s) point to another site (other-shop.test) at a path that exists on this one, "
                          "and the other address returns 404")
    assert (dead.severity.value, dead.confidence.value) == ("S3", "verified") and dead.evidence["other_address_status"] == 404
    assert dead.evidence["links"][0]["same_path_on_this_site"] == KAFE + "/hakkimizda" and "nowhere" not in dead.how_to_fix
    assert outcome.other == ["/robots.txt", "/hakkimizda"]


def test_a_link_the_other_sites_robots_txt_disallows_is_a_note_and_the_page_is_not_requested(no_lookups):
    outcome = other_site(404, robots="User-agent: *\nDisallow: /\n")
    [note] = outcome.links
    assert note.title == ("1 link(s) on 1 page(s) point to another site (other-shop.test) at a path that exists on this one; "
                          "the other address could not be checked")
    assert (note.severity.value, note.confidence.value) == ("Info", "inferred") and "robots.txt" in note.evidence["why_not_checked"][0]
    assert outcome.other == ["/robots.txt"]  # the page itself was never asked for


def test_a_link_to_a_brand_family_domain_sends_no_request_and_an_internal_link_to_a_404_page_is_reported_as_before(no_lookups):
    outcome = other_site(404, brand_family_domains=("other-shop.test",))
    assert outcome.other == [] and outcome.links == []  # not even its robots.txt
    assert outcome.by_id["IDX-6"].evidence["links_to_brand_family_domains_not_checked"] == 1
    # A subdomain of a family domain is family too; a domain that only ends with the same letters is not.
    from maya_audit.urls import clean_hostname, in_domain_family
    assert in_domain_family("blog.other-shop.test", ("other-shop.test",)) and not in_domain_family("another-shop.test", ("other-shop.test",))
    assert clean_hostname(" Other-Shop.Test. ") == "other-shop.test"
    assert [clean_hostname(text) for text in ("https://other-shop.test", "other-shop.test/yol", "<b>x</b>.test", "10.0.0.1", "tek", "")] == [None] * 6

    # Healthy: a link to a page of this site that answers 404 is still reported, once: under IDX-1's 4xx finding, with the
    # link as its row (review H10).
    broken = audited({"/": answer('<a href="/eski-menu">Eski menü</a>')})
    assert not broken.by_id["IDX-6"].findings
    [finding] = [f for f in broken.by_id["IDX-1"].findings if "client error (4xx)" in f.title]
    assert finding.title == "1 URL(s) return a client error (4xx), linked internally or listed in the sitemap; linked from 1 page(s)"
    assert finding.evidence["broken_links"][0]["target"] == f"{KAFE}/eski-menu"
    assert (finding.severity.value, finding.confidence.value) == ("S2", "verified")


# -- FA-020: the homepage looked for at the address that failed, or read twice with two answers (DECISIONS 199) -----------
def test_a_start_address_that_answers_404_does_not_hide_the_homepage_that_was_read(no_lookups):
    from maya_audit.access_data import homepage_url

    outcome = audited({"/": answer(title="Demo Kafe | Ana Sayfa")}, start=KAFE + "/menu-yok")
    assert next(p for p in outcome.result.pages if p.url == KAFE + "/menu-yok").status == 404
    assert homepage_url(outcome.result) == KAFE + "/"
    check = outcome.by_id["STR-18"]
    assert check.status == "pass" and check.summary == "The homepage title names the brand ('Demo Kafe | Ana Sayfa')."


def test_two_reads_of_the_homepage_that_disagree_are_said_so_and_a_homepage_without_a_title_keeps_its_sentence(no_lookups):
    home = lambda n: to_itself("/") if n == 1 else answer(title="Demo Kafe | Ana Sayfa")  # noqa: E731
    outcome = audited({"/": home}, sitemap=())
    assert [(p.url, p.status) for p in outcome.result.pages] == [(KAFE + "/", 301)]  # the crawl has only the redirect
    check = outcome.by_id["STR-18"]
    assert check.status == "not_assessed"
    assert check.summary == "Two reads of the homepage disagreed: one answered 301, another 200. The title was not judged."
    assert check.evidence["statuses_seen"][:2] == [301, 200]

    # Healthy: a homepage that was read and has no title keeps the sentence it had.
    bare = httpx.Response(200, headers=HTML_TYPE, text=f"<!doctype html><html lang=\"tr\"><head></head><body><main><h1>Demo Kafe</h1><p>{TR}</p></main></body></html>")
    untitled = audited({"/": bare}).by_id["STR-18"]
    assert untitled.status == "not_assessed"
    assert untitled.summary == "The homepage was not read as an indexable page with a title (a missing title is STR-1's finding)."


# -- the list and the tests cannot drift apart -----------------------------------------------------------------------------
def test_every_false_alarm_entry_names_a_test_that_exists():
    text = (DOCS / "FALSE-ALARMS.md").read_text(encoding="utf-8")
    entries = re.split(r"^## (FA-\d{3})\s*$", text, flags=re.MULTILINE)[1:]
    by_entry = dict(zip(entries[::2], entries[1::2]))
    # In order, never twice, and with no number missing.
    numbers = [int(entry[3:]) for entry in by_entry]
    assert numbers == list(range(1, len(numbers) + 1)) and len(by_entry) >= 24
    defined = {name: file.name for file in sorted(Path(__file__).resolve().parent.glob("test_*.py"))
               for name in re.findall(r"^def (test_\w+)\(", file.read_text(encoding="utf-8"), flags=re.MULTILINE)}
    for entry, body in by_entry.items():
        for field in ("Date", "Site", "Report said", "Page really had", "Cause", "Rule now", "Test"):
            assert f"- **{field}:**" in body, (entry, field)
        named = re.search(r"- \*\*Test:\*\* `(test_\w+)` \(`tests/(test_\w+\.py)`\)", body)
        assert named, f"{entry} names no test"
        assert defined.get(named.group(1)) == named.group(2), f"{entry}: {named.group(1)} is not a test in tests/{named.group(2)}"
