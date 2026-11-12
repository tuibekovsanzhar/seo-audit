"""DECISIONS 343: technical issues from the SEO team's review (Efsa's enpara report) as global rules.

One hand-written site, offline (a loopback fake server), with each problem once:
  /eski-sayfa      302 -> /404?aspxerrorpath=/eski-sayfa, which answers 404 (rule 1);
  / and /anasayfa  the same page, both 200 and their own canonical (rule 2);
  /blog/kredi      BlogPosting with Product and AggregateRating (rule 3);
  /kampanya        a meta description with %%title%% left unfilled (rule 4, STR-13);
  /sss/hesaplar    /sss's title and H1, canonical to itself, hreflang to /sss (rule 5);
  /odemeler/fatura H1 "Ödemeler", the parent /odemeler's H1, its own title (rule 7);
and, on a site of its own, a sitemap of 30 addresses with a sample cap of 5: every one is asked (rule 6).
"""
from __future__ import annotations

import json

import pytest

from fakeserver import Response
from maya_audit import client_selection, final, page_rows, reassess_rules
from maya_audit.checks import team_rules
from maya_audit.config import SITEMAP_CHECK_ALL_UP_TO, CrawlConfig
from maya_audit.index_data import sitemap_check_cap
from test_m1_broken_links import audit
from test_review_fixes import TR
from test_firecrawl import no_lookups  # noqa: F401  (fixture)

NEW = ("idx1.error_redirect", "idx8.self_canonical_copies", "str3.product_on_article", "str1.sections_as_pages")
LINKS = ["/anasayfa", "/eski-sayfa", "/blog/kredi", "/kampanya", "/sss", "/sss/hesaplar", "/odemeler", "/odemeler/fatura"]


def html(title: str, h1: str, words: str, head: str = "", body: str = "") -> Response:
    nav = " ".join(f'<a href="{p}">{p}</a>' for p in LINKS)
    return Response(body=f'<!doctype html><html lang="tr"><head><title>{title}</title>{head}</head><body><header><nav>{nav}'
                         f'</nav></header><main><h1>{h1}</h1><p>{words} {TR}</p>{body}</main></body></html>')


def jsonld(value: dict) -> str:
    return f'<script type="application/ld+json">{json.dumps(value, ensure_ascii=False)}</script>'


def routes() -> dict:
    home = html("Bankanın güzeli", "Bankanın güzeli", "Ana sayfa metni.", '<link rel="canonical" href="/">')
    return {
        "/robots.txt": Response(body="User-agent: *\nAllow: /\n", content_type="text/plain"),
        "/sitemap.xml": Response(404, "", content_type="text/plain"),
        "/": home,
        "/anasayfa": html("Bankanın güzeli", "Bankanın güzeli", "Ana sayfa metni.", '<link rel="canonical" href="/anasayfa">'),
        "/eski-sayfa": Response(302, "", headers={"Location": "/404?aspxerrorpath=/eski-sayfa"}),
        "/404": Response(404, "<html><title>Bulunamadı</title><body>Sayfa yok</body></html>"),
        "/blog/kredi": html("Kredi nedir | Blog", "Kredi nedir?", "Kredi hakkında bir yazı.",
                            jsonld({"@context": "https://schema.org", "@type": "BlogPosting", "headline": "Kredi nedir?"})
                            + jsonld({"@context": "https://schema.org", "@type": "Product", "name": "Kredi",
                                      "aggregateRating": {"@type": "AggregateRating", "ratingValue": 4.8, "reviewCount": 120}})),
        "/kampanya": html("Kampanyalar", "Kampanyalar", "Kampanya listesi.",
                          '<meta name="description" content="%%title%% %%sep%% Banka">'),
        "/sss": html("Sıkça Sorulan Sorular | Banka", "Sıkça sorulan sorular", "Tüm sorular burada.",
                     '<link rel="canonical" href="/sss"><link rel="alternate" hreflang="tr" href="/sss">'),
        "/sss/hesaplar": html("Sıkça Sorulan Sorular | Banka", "Sıkça sorulan sorular", "Hesaplarla ilgili sorular.",
                              '<link rel="canonical" href="/sss/hesaplar"><link rel="alternate" hreflang="tr" href="/sss">'),
        "/odemeler": html("Ödemeler | Banka", "Ödemeler", "Ödeme çeşitleri."),
        "/odemeler/fatura": html("Fatura Ödemeleri | Banka", "Ödemeler", "Fatura ödemek için."),
    }


@pytest.fixture(scope="module")
def site():
    outcome, base = audit(routes())
    sealed = final.seal(outcome)
    found = {f["rule_id"]: f for c in sealed.report["checks"] for f in c["findings"]}
    return sealed, found, base


def path_rows(finding: dict, base: str) -> dict:
    return {r["url"].removeprefix(base): r["row"]["tr"] for r in finding["evidence"]["pages"]}


# ---------------------------------------------------------------- the rules on the fake site


def test_a_missing_page_that_redirects_to_an_error_page(site):
    _, found, base = site
    f = found["idx1.error_redirect"]
    rows = path_rows(f, base)
    assert rows["/eski-sayfa"] == "302 → /404?aspxerrorpath=/eski-sayfa → 404 (404/410 yerine yönlendirme)"
    assert f["scope"]["urls"] == [base + "/eski-sayfa"]


def test_two_addresses_of_one_page_each_their_own_canonical(site):
    _, found, base = site
    rows = path_rows(found["idx8.self_canonical_copies"], base)
    assert set(rows) == {"/", "/anasayfa"}
    assert rows["/anasayfa"] == "/ ile aynı içerik, başlık ve H1; 200 ve kendini kanonik gösteriyor"
    fix = {r["url"].removeprefix(base): r.get("fix") for r in found["idx8.self_canonical_copies"]["evidence"]["pages"]}
    assert fix["/anasayfa"]["tr"] == "Bu adresi / adresine 301 ile yönlendirin."  # DECISIONS 344: the row's own step
    assert rows["/"].startswith("asıl adres önerisi")


def test_product_and_rating_markup_on_a_blog_post(site):
    _, found, base = site
    rows = path_rows(found["str3.product_on_article"], base)
    assert rows == {"/blog/kredi": "BlogPosting sayfasında AggregateRating, Product işaretlemesi"}


def test_an_unfilled_variable_in_a_meta_tag_is_str13s_with_its_own_card(site):
    _, found, base = site
    f = found["str13.markers_data"]
    assert "%%title%%" in f["title"] and "meta tag" in f["title"]
    assert f["scope"]["urls"] == [base + "/kampanya"]


def test_sub_pages_opening_a_part_of_their_parent_are_one_card(site):
    # DECISIONS 344: the parent's head with hreflang to it, and the section's name as H1, are one site-wide card
    _, found, base = site
    rows = path_rows(found["str1.sections_as_pages"], base)
    assert rows == {"/sss/hesaplar": 'üst sayfa /sss; hreflang üst sayfayı gösteriyor, başlık üst sayfayla aynı, H1 "Sıkça '
                                     'sorulan sorular" üst sayfanın H1\'i; sayfa başlığı "Sıkça Sorulan Sorular | Banka"',
                    "/odemeler/fatura": 'üst sayfa /odemeler; H1 "Ödemeler" üst sayfanın H1\'i; sayfa başlığı "Fatura Ödemeleri | Banka"'}
    assert found["str1.sections_as_pages"]["severity"] == "S3"


def sitemap_only(n: int, cap: int) -> dict:
    """A homepage and n sitemap addresses no page links to (each 404), read with a page cap of 1."""
    from dataclasses import replace
    from fakeserver import FakeServer, Site
    from maya_audit.audit import run_audit
    from test_deadline_hosted_hardening import QUIET
    state = {}
    r = {"/robots.txt": Response(body="User-agent: *\nAllow: /\n", content_type="text/plain"),
         "/": html("Ana sayfa", "Ana sayfa", "Tek sayfa."),
         "/sitemap.xml": lambda site, req: Response(
             body='<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                  + "".join(f"<url><loc>{state['base']}/liste/{i}</loc></url>" for i in range(n)) + "</urlset>",
             content_type="application/xml")}
    with FakeServer(Site(r)) as fake:
        state["base"] = fake.base_url
        outcome = run_audit(fake.base_url + "/", replace(CrawlConfig(), **{**QUIET, "sitemap_check_max": cap, "max_pages": 1}))
    return final.seal(outcome).report["crawl"]["index"]["sitemap_check"]


def test_a_sitemap_of_up_to_1000_addresses_is_checked_whole():
    check = sitemap_only(30, 5)
    assert check["listed"] == 30 and check["cap"] == 30 and not check["sampled"] and len(check["rows"]) == 30
    assert all(row.get("status") == 404 for row in check["rows"])  # every 404 entry found, not a sample of 5
    assert sitemap_check_cap(CrawlConfig(sitemap_check_max=5), SITEMAP_CHECK_ALL_UP_TO) == SITEMAP_CHECK_ALL_UP_TO
    assert sitemap_check_cap(CrawlConfig(sitemap_check_max=5), SITEMAP_CHECK_ALL_UP_TO + 1) == 5
    assert sitemap_check_cap(CrawlConfig(sitemap_check_max=0), 10) == 0  # switched off stays off
    assert sitemap_check_cap(CrawlConfig(sitemap_check_max=5, fast_check=True), 30) == 5


def test_the_ek_lists_every_page_with_its_evidence(site):
    sealed, found, base = site
    sel = client_selection.select(sealed.report, sealed.affected, {})
    rows = page_rows.finding_rows(sel, sealed.affected, "tr")
    for rule in NEW:
        mine = [r for r in rows if r["rule_id"] == rule]
        expected = path_rows(found[rule], base)
        assert {r["url"].removeprefix(base): r["value"] for r in mine} == expected, rule


# ---------------------------------------------------------------- saved reports and the probe


def test_a_saved_report_of_the_current_schema_gets_the_rules_offline(site):
    sealed, found, _ = site
    old = json.loads(json.dumps(sealed.report))
    for c in old["checks"]:
        c["findings"] = [f for f in c["findings"] if f.get("rule_id") not in NEW]
    affected = {k: v for k, v in sealed.affected.items() if k not in {found[r]["id"] for r in NEW}}
    new, changes = reassess_rules.saved_data(old, affected)
    again = {f["rule_id"] for c in new["checks"] for f in c["findings"]}
    assert set(NEW) <= again and sum("DECISIONS 343" in c for c in changes) == len(NEW)
    new2, aff2, _ = reassess_rules.apply(old, affected)
    assert set(NEW) <= {f["rule_id"] for c in new2["checks"] for f in c["findings"]}


def test_the_missing_page_probe_alone_makes_the_finding():
    probe = {"sent": True, "url": "https://b.test/maya-audit-no-such-page-1", "status": 302,
             "redirect_location": "https://b.test/404?aspxerrorpath=/maya-audit-no-such-page-1"}
    [f] = team_rules.error_redirects([], [], probe)
    assert f.rule_id == "idx1.error_redirect" and f.evidence["pages"][0]["row"]["en"].startswith("Maya's made-up address: 302 → /404?")
    assert team_rules.error_redirects([], [], {**probe, "redirect_location": "https://b.test/yeni-sayfa"}) == []


@pytest.mark.parametrize("url,error", [("https://b.test/404?aspxerrorpath=/x", True), ("https://b.test/hata", True),
                                       ("https://b.test/sayfa-bulunamadi", True), ("https://b.test/error.aspx", True),
                                       ("https://b.test/hatali-odeme-iadesi", False), ("https://b.test/urunler/404-ml", False)])
def test_what_counts_as_an_error_page(url, error):
    assert team_rules.error_page(url) is error


def test_language_versions_are_not_second_addresses():
    from types import SimpleNamespace as P
    a = {"text_sha256": "x", "title": "T", "h1_elements": [{"text": "H"}], "canonicals": [],
         "hreflang": [{"hreflang": "en", "href": "https://b.test/en"}]}
    pages = [P(url="https://b.test/", status=200, analysis=a, outlinks=[]),
             P(url="https://b.test/en", status=200, analysis={**a, "hreflang": [{"hreflang": "tr", "href": "https://b.test/"}]}, outlinks=[])]
    assert team_rules.self_canonical_copies(pages) == []


# ---------------------------------------------------------------- the team report and the checklist


def test_each_rule_has_its_own_card_title(site, tmp_path):
    from maya_audit_web.runner import REPORT_JSON
    from maya_audit_web.team_report import build_data
    sealed, _, _ = site
    folder = tmp_path / "artifacts"
    folder.mkdir()
    (folder / REPORT_JSON).write_text(json.dumps(sealed.report), encoding="utf-8")
    data = build_data.build_from_files(folder / REPORT_JSON, "tr")[0]
    titles = {t["title"] for t in data["todos"] + (data.get("notes_more") or [])}
    for title in ("Olmayan adreslerde 302 yerine doğrudan 404/410 döndürün", "Aynı sayfanın ikinci adreslerini asıl adrese 301'leyin",
                  "Blog yazılarındaki Product işaretlemesini kaldırın",
                  "Sayfa içindeki başlıklar/sorular ayrı adres oluşturuyor"):
        assert title in titles, title
    # A new check's finding waits under "Teyit edin" here (one page); as a card it carries the review's title.
    from maya_audit_web.team_report import texts
    assert texts.library("tr")["rules"]["str13.markers_data"]["title"] == "JSON-LD'deki doldurulmamış şablon değişkenini düzeltin"
    assert texts.library("en")["rules"]["str13.markers_data"]["title"] == "Fix the unfilled template variable in the JSON-LD"


@pytest.mark.parametrize("item,rule,check", [("SEO-013", "idx1.error_redirect", "IDX-1"),
                                             ("SEO-041", "idx8.self_canonical_copies", "IDX-8"),
                                             ("SEO-049", "idx8.self_canonical_copies", "IDX-8"),
                                             ("SEO-101", "str13.markers_data", "STR-13"),
                                             ("SEO-106", "str3.product_on_article", "STR-3"),
                                             ("SEO-145", "str1.sections_as_pages", "STR-1"),
                                             ("SEO-065", "str1.sections_as_pages", "STR-1")])
def test_the_checklist_items_each_rule_covers(item, rule, check):
    from maya_audit import checklist
    from test_checklist_342 import group, selection
    it = next(i for i in checklist.items() if i["id"] == item)
    row = checklist.judge(it, selection([group(rule, check, card=3, fid="F-1")], checks={check: {"status": "findings"}},
                                        site={"languages": True, "page_types": {"blog_article": 3, "category": 2}}))
    assert (row["result"], row["ref"]) == ("issue", rule), row


def test_second_addresses_are_alias_forms_of_one_address_only():
    from types import SimpleNamespace as P
    a = {"text_sha256": "x", "title": "T", "h1_elements": [{"text": "H"}], "canonicals": []}

    def found(*urls):
        pages = [P(url=u, status=200, analysis=dict(a), outlinks=[]) for u in urls]
        return {r["url"] for f in team_rules.self_canonical_copies(pages) for r in f.evidence["pages"]}
    assert found("https://b.test/sss", "https://b.test/sss/default.aspx") == {"https://b.test/sss", "https://b.test/sss/default.aspx"}
    assert found("https://b.test/form", "https://b.test/form?sw=1") == {"https://b.test/form", "https://b.test/form?sw=1"}
    assert found("https://b.test/iletisim", "https://b.test/iletisim/") == set()  # idx8.two_addresses reports these
    assert found("https://b.test/ucretler", "https://b.test/ucretler/para-transferleri") == set()  # two pages, one text
