"""DECISIONS 351: the follow-up on the bank's audit.

(1) a link to a sign-in or application entry that redirects is "keep it" (Kontrol edin, at most P3), never "remove it";
    "Bağlantı yerleri" gives a link to a redirect its final address, and a menu link is mended, never removed;
(2) the alias-links card gives Shopify's step only on a Shopify site, and its links are listed in "Bağlantı yerleri";
(3) a CMS edit or preview address (?efl--edit=1, ?preview=) is its clean page: folded into it by the crawl, never a page
    read or typed, and said in Kapsam.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from fakeserver import Response
from maya_audit import client_selection, final, link_places, priority_levels, reassess_rules
from maya_audit.checks import quick_rules
from maya_audit.checks.stage8_rules import _entry, links_to_redirect
from maya_audit.urls import edit_preview, without_edit_preview
from test_m1_broken_links import audit
from test_review_fixes import TR
from test_firecrawl import no_lookups  # noqa: F401  (fixture)


def page(url, outlinks=(), status=200):
    return SimpleNamespace(url=url, status=status, redirect_location=None, analysis={"og": {}}, outlinks=list(outlinks))


def edge(target, anchor, nav=False, footer=False):
    return {"target": target, "anchors": [anchor], "anchor": anchor, "nav": nav, "footer": footer}


# ---------------------------------------------------------------- 1. sign-in and application entries


@pytest.mark.parametrize("url,final_url,entry", [
    ("https://b.test/internet/MainPageEnter.aspx?src=HizliKrediBasvuru", "https://loanapp.b.test/?amount=1", True),
    ("https://b.test/giris", "https://b.test/internet-subesi/login", True),
    ("https://b.test/kredi", "https://apply.b.test/", True),          # an application host
    ("https://b.test/eski-kampanya", "https://b.test/kampanyalar", False),
    ("https://b.test/eski", "https://news.other.test/x", False),      # another host, not an entry
])
def test_what_an_entry_link_is(url, final_url, entry):
    walk = {"hops": [{"url": url, "status": 301, "target": final_url}], "final": final_url}
    assert _entry(url, walk) is entry


def test_a_menu_link_to_an_application_entry_is_a_check_not_a_card_to_remove():
    entry_url = "https://b.test/internet/Enter.aspx?src=KrediBasvuru&site=megamenu"
    pages = [page(f"https://b.test/p{i}", [edge(entry_url, "Kredi", nav=True)]) for i in range(6)]
    moved = SimpleNamespace(url=entry_url, status=301, redirect_location="https://loanapp.b.test/?amount=50000",
                            analysis=None, outlinks=[])
    [f] = links_to_redirect(pages + [moved], pages)
    assert f.rule_id == "idx6.links_to_entry_redirect" and f.severity.value == "S4"
    assert "never remove" in f.how_to_fix and f.evidence["template_link"]["where"] == "menu"
    assert all("Keep the link" in r["fix"]["en"] for r in f.evidence["pages"])


def test_an_entry_card_is_at_most_p3():
    ctx = priority_levels.Context({"https://b.test/": {"page_type": "home", "importance": 100}}, {}, {"https://b.test/"})
    member = {"id": "IDX-6-x", "severity": "S2", "rule_id": "idx6.links_to_entry_redirect", "scope": {"urls": ["https://b.test/"]}}
    label = priority_levels.label({"members": [member], "finding_ids": ["IDX-6-x"], "severity": "S2"}, ctx, None, None)
    assert label["level"] == "P3"


def report_with(findings, pages):
    return {"crawl": {"pages": pages}, "checks": [{"check_id": "IDX-6", "findings": findings}]}


def test_a_link_to_a_redirect_is_given_its_final_address_never_removed():
    target = "https://b.test/internet/Enter.aspx"
    pages = [{"url": "https://b.test/", "status": 200, "outlinks": [edge(target, "Kredi", nav=True)]},
             {"url": target, "status": 301, "redirect_location": "https://loanapp.b.test/"}]
    f = {"id": "IDX-6-e", "rule_id": "idx6.links_to_entry_redirect", "evidence": {"targets": [{"url": target}]}}
    [row] = link_places.places(report_with([f], pages))["IDX-6-e"]
    assert row["suggested"] == "https://loanapp.b.test/" and row["position"] == "menu"


def test_a_broken_menu_link_is_mended_not_removed():
    pages = [{"url": "https://b.test/", "status": 200, "outlinks": [edge("https://b.test/yok", "Yok", nav=True)]},
             {"url": "https://b.test/yok", "status": 404}]
    f = {"id": "IDX-1-a", "rule_id": "idx1.4xx.referenced", "evidence": {"link_sources": [
        {"source": "https://b.test/", "links_to": "https://b.test/yok", "anchor": "Yok", "position": "menu"}]}}
    [row] = link_places.places({"crawl": {"pages": pages}, "checks": [{"check_id": "IDX-1", "findings": [f]}]})["IDX-1-a"]
    assert row["suggested"] == "fix_nav"


# ---------------------------------------------------------------- 2. the alias-links card


def test_shopifys_step_only_on_a_shopify_site():
    assert quick_rules.alias_fix(None, ["https://b.test/?efl--edit=1"]) == quick_rules.ALIAS_LINKS_FIX
    assert "Shopify" not in quick_rules.ALIAS_LINKS_FIX
    assert quick_rules.alias_fix("Shopify", []) == quick_rules.ALIAS_LINKS_FIX_SHOPIFY
    assert quick_rules.alias_fix(None, ["https://s.test/collections/a/products/b"]) == quick_rules.ALIAS_LINKS_FIX_SHOPIFY


def test_a_saved_alias_card_loses_the_shopify_step_on_another_site():
    f = {"id": "IDX-6-a", "rule_id": "idx6.alias_links", "how_to_fix": quick_rules.ALIAS_LINKS_FIX_SHOPIFY,
         "evidence": {"targets": [{"url": "https://b.test/?efl--edit=1", "canonical": "https://b.test/"}]}}
    changes: list[str] = []
    reassess_rules._decisions_351(report_with([f], []), changes)
    assert f["how_to_fix"] == quick_rules.ALIAS_LINKS_FIX and "DECISIONS 351" in changes[0]


def test_the_alias_links_are_listed_with_text_place_href_and_canonical():
    target = "https://b.test/?efl--edit=1"
    pages = [{"url": f"https://b.test/p{i}", "status": 200,
              "outlinks": [{**edge(target, "Çerez Ayarları", footer=True), "href": "/?efl--edit=1"}]} for i in range(2)]
    f = {"id": "IDX-6-a", "rule_id": "idx6.alias_links",
         "evidence": {"targets": [{"url": target, "canonical": "https://b.test/", "linked_from_pages": 2}]}}
    rows = link_places.places(report_with([f], pages))["IDX-6-a"]
    assert len(rows) == 2 and {(r["link_text"], r["position"], r["href"], r["suggested"]) for r in rows} == {
        ("Çerez Ayarları", "footer", "/?efl--edit=1", "https://b.test/")}


# ---------------------------------------------------------------- 3. CMS edit and preview addresses


@pytest.mark.parametrize("url,edit,clean", [
    ("https://b.test/?efl--edit=1", True, "https://b.test/"),
    ("https://b.test/x?preview=true&id=3", True, "https://b.test/x?id=3"),
    ("https://b.test/x?preview_theme_id=12", True, "https://b.test/x"),
    ("https://b.test/x?editor=1", False, None), ("https://b.test/x?page=2", False, None)])
def test_what_an_edit_or_preview_address_is(url, edit, clean):
    assert edit_preview(url) is edit
    if clean:
        assert without_edit_preview(url) == clean


def html(title, body=""):
    return Response(body=f'<!doctype html><html lang="tr"><head><title>{title}</title></head><body><main><h1>{title}</h1>'
                         f'<p>{TR}</p>{body}</main><footer><a href="/?efl--edit=1">Çerez Ayarları</a> '
                         f'<a href="/hakkimizda?preview=true">Hakkımızda</a></footer></body></html>')


def test_the_crawl_folds_edit_addresses_into_their_clean_page(no_lookups):  # noqa: F811
    routes = {"/robots.txt": Response(body="User-agent: *\nAllow: /\n", content_type="text/plain"),
              "/sitemap.xml": Response(404, "", content_type="text/plain"),
              "/": html("Banka", '<a href="/hakkimizda">Hakkımızda</a>'), "/hakkimizda": html("Hakkımızda")}
    outcome, base = audit(routes, max_pages=10)
    asked = [p.url for p in outcome.result.pages]
    assert not [u for u in asked if edit_preview(u)] and base + "/hakkimizda" in asked
    sealed = final.seal(outcome)
    [alias] = [f for c in sealed.report["checks"] for f in c["findings"] if f["rule_id"] == "idx6.alias_links"]
    assert {t["url"].removeprefix(base): t["canonical"].removeprefix(base) for t in alias["evidence"]["targets"]} == {
        "/?efl--edit=1": "/", "/hakkimizda?preview=true": "/hakkimizda"}
    line = client_selection.edit_pages_line(sealed.report)
    assert line["read"] == 0 and line["linked"] == 2


def test_a_saved_edit_address_is_not_a_page_read_and_kapsam_says_so():
    pages = [{"url": "https://b.test/", "status": 200, "content_checks_eligible": True, "outlinks": []},
             {"url": "https://b.test/?efl--edit=1", "status": 200, "content_checks_eligible": True, "outlinks": []}]
    report = {"crawl": {"pages": pages}}
    assert client_selection.pages_read(report) == {"https://b.test/"}
    line = client_selection.edit_pages_line(report)
    assert (line["read"], line["linked"], line["examples"]) == (1, 0, ["https://b.test/?efl--edit=1"])
    from maya_audit.client_appendix import coverage_text
    assert coverage_text(line, "tr").startswith("CMS düzenleme/önizleme adresleri ayrı sayfa sayılmadı: 1 okunan")
