"""DECISIONS 350: the review of a bank's Smart ~150 audit (Bankacılık) as global rules.

(1) a product page carrying the bank's place markup (BankOrCreditUnion, PostalAddress) beside its loan offer is not a
    store/location page; with a business profile the Ek's page types are the profile's;
(2) a card whose pages all carry one template link names that link, where it sits and the address to give it;
(3) the block-pages line says the reader's new pages apart from Maya's pages it read again.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from maya_audit import client_selection, page_groups, page_rows, reassess_rules
from maya_audit.checks.stage8_rules import links_to_redirect, template_link
from maya_audit.client_appendix import block_pages_text


def page(url, types=(), iframes=(), headings=(), outlinks=(), status=200):
    a = {"structured_data": {"types": list(types)}, "iframes": [{"src": s} for s in iframes],
         "headings": [{"text": h} for h in headings], "og": {}}
    return SimpleNamespace(url=url, analysis=a, outlinks=list(outlinks), status=status, redirect_location=None)


# ---------------------------------------------------------------- 1. store/location only for one place


@pytest.mark.parametrize("types,iframes,headings,place", [
    (["BankOrCreditUnion", "PostalAddress", "LoanOrCredit", "Offer", "FAQPage"], [], [], False),   # a loan page
    (["BankOrCreditUnion", "PostalAddress", "ContactPoint"], [], [], False),     # an address alone: any organisation
    (["Store", "PostalAddress", "GeoCoordinates", "OpeningHoursSpecification"], [], [], True),   # a store page
    (["BankOrCreditUnion", "GeoCoordinates", "OpeningHoursSpecification"], [], [], True),        # a branch page
    (["WebPage"], ["https://www.google.com/maps/embed?pb=1"], ["Şube çalışma saatleri"], True),  # map + hours
    (["Service"], ["https://www.google.com/maps/embed?pb=1"], ["Çalışma saatleri"], False),     # a service page
])
def test_a_location_page_is_mainly_one_place(types, iframes, headings, place):
    assert (page_groups.location_reason(page("https://b.test/x", types, iframes, headings)) is not None) is place


def test_place_markup_on_most_pages_is_the_sites_own_not_a_location():
    p = page("https://b.test/sube", ["BankOrCreditUnion", "GeoCoordinates"])
    assert page_groups.location_reason(p) is not None
    assert page_groups.location_reason(p, frozenset({"BankOrCreditUnion"})) is None


def test_the_ek_uses_the_profiles_page_types_when_one_applies():
    rec = {"page_type": "other", "business_page_type": "products"}
    assert page_rows.page_kind_of(rec) == "products"
    assert page_rows.page_kind_of({"page_type": "blog_article", "business_page_type": "other"}) == "blog_article"
    generic = {"other": "diğer", "home": "ana sayfa"}
    assert page_rows.type_word("products", "tr", "bankacilik", generic) not in ("", "products")
    assert page_rows.type_word("other", "tr", "bankacilik", generic) == "diğer"
    assert page_rows.type_word(None, "tr", "bankacilik", generic) == ""


# ---------------------------------------------------------------- 2. one template link, named


def edge(target, anchor, nav=False, footer=False):
    return {"target": target, "anchors": [anchor], "nav": nav, "footer": footer}


def test_a_menu_link_to_a_redirect_on_every_page_is_named_with_its_final_address():
    apply_link = "https://b.test/internet/Enter.aspx?site=megamenu"
    pages = [page(f"https://b.test/p{i}", outlinks=[edge(apply_link, "Kredi", nav=True)]) for i in range(6)]
    moved = SimpleNamespace(url=apply_link, status=301, redirect_location="https://app.b.test/?amount=1", analysis=None,
                            outlinks=[])
    [f] = links_to_redirect(pages + [moved], pages)
    tl = f.evidence["template_link"]
    assert tl == {"url": apply_link, "final": "https://app.b.test/?amount=1", "kind": "redirect", "pages": 6,
                  "anchor": "Kredi", "where": "menu"}


def test_a_link_on_few_pages_is_not_a_template_link():
    target = "https://b.test/old"
    pages = [page(f"https://b.test/p{i}", outlinks=[edge(target, "Eski")] if i < 2 else []) for i in range(6)]
    moved = SimpleNamespace(url=target, status=301, redirect_location="https://b.test/new", analysis=None, outlinks=[])
    [f] = links_to_redirect(pages + [moved], pages)
    assert "template_link" not in f.evidence


def test_the_footer_place_of_a_template_link():
    target = "https://b.test/?edit=1"
    pages = [page(f"https://b.test/p{i}", outlinks=[edge(target, "Çerez Ayarları", footer=True)]) for i in range(5)]
    tl = template_link(pages, target, {p.url for p in pages}, "https://b.test/", "canonical")
    assert tl["where"] == "footer" and tl["anchor"] == "Çerez Ayarları" and tl["pages"] == 5


def test_a_saved_alias_links_card_gets_its_template_link_offline(monkeypatch):
    import maya_audit.models as models
    target = "https://b.test/?edit=1"
    recs = [{"url": f"https://b.test/p{i}", "status": 200, "outlinks": [edge(target, "Çerez Ayarları", footer=True)]}
            for i in range(5)]
    finding = {"id": "IDX-6-a", "rule_id": "idx6.alias_links", "evidence": {
        "page_count": 5, "targets": [{"url": target, "canonical": "https://b.test/", "linked_from_pages": 5}]}}
    report = {"crawl": {"pages": recs}, "checks": [{"check_id": "IDX-6", "findings": [finding]}]}
    monkeypatch.setattr(models, "page_from_record", lambda rec: SimpleNamespace(url=rec["url"], outlinks=rec["outlinks"]))
    changes: list[str] = []
    reassess_rules._decisions_350(report, changes)
    tl = finding["evidence"]["template_link"]
    assert (tl["where"], tl["anchor"], tl["final"]) == ("footer", "Çerez Ayarları", "https://b.test/")
    assert "DECISIONS 350" in changes[0]


# ---------------------------------------------------------------- 3. the reader's new pages apart


def test_the_block_line_says_new_pages_apart_from_pages_read_again():
    line = {"kind": "block_pages", "blocked": 1, "allowed": 2, "read": 91, "new": 0, "plan": 150}
    assert block_pages_text(line, "tr") == (
        "Engel sayfaları sayfa sınırına sayılmadı: Maya'nın tarayıcısı 1 istekte engel sayfası ya da 429 aldı; sayfa "
        "okuyucu Maya'nın okumadığı en çok 2 yeni sayfa okuyabilirdi, 0 yeni sayfa okudu (ayrıca Maya'nın okuduğu 91 "
        "sayfayı yeniden okudu).")
    assert block_pages_text(line, "en").endswith("could read up to 2 new pages Maya had not read and read 0 (and read 91 "
                                                 "of Maya's pages again).")


def test_the_block_line_counts_the_readers_new_pages_from_the_report():
    maya = [{"url": f"https://b.test/p{i}", "status": 200} for i in range(3)]
    rows = [{"url": "https://b.test/p0", "outcome": "read"}, {"url": "https://b.test/new", "outcome": "read"}]
    report = {"crawl": {"pages": maya}, "firecrawl": {"used": True, "pages_read": 2, "pages": rows, "coverage": {
        "page_limit": {"plan": 5, "maya_pages_read": 3, "block_answers": 1, "reader_new_pages_allowed": 2}}}}
    line = client_selection.block_pages_line(report)
    assert (line["new"], line["read"], line["allowed"]) == (1, 2, 2)
