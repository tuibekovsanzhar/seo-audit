"""The checklist's quick checks (DECISIONS 304): ten rules over data the crawl already reads, the page grouping of a page
reader's pages when Maya's crawler was blocked, and the key Product fields kept in report.json (schema 1.24).
Every site here is made up and held in memory; no socket is opened and nothing is paid for.
"""
import json
from types import SimpleNamespace

import httpx
import pytest

from maya_audit.analysis import analyze_html
from maya_audit.audit import run_audit
from maya_audit.checks import quick_rules
from maya_audit.config import CrawlConfig
from maya_audit.models import PageFetch
from maya_audit.report import build_report
from test_deadline_hosted_hardening import QUIET

SHOP = "https://quick-shop.test"
HTML = {"content-type": "text/html; charset=utf-8"}
TEXT = "<p>" + "Yeni sezon elbiseler ve zarif aksesuarlar her gün özenle hazırlanır ve kargoya verilir. " * 12 + "</p>"
MENU = ('<header><nav><a href="/">Ana Sayfa</a><a href="/collections">Koleksiyonlar</a><a href="/collections/elbise">Elbise</a>'
        '<a href="/collections/canta">Çanta</a><a href="/collections/bos">Outlet</a><a href="/collections/az">Parfüm</a>'
        '<a href="/blogs/news">Blog</a></nav></header>')
FOOTER = '<footer><a href="/policies/privacy-policy">Gizlilik</a></footer>'
GTIN_PRODUCT = ('{"@context": "https://schema.org", "@type": "Product", "name": "Kırmızı Elbise", "sku": "KE-1", '
                '"brand": {"@type": "Brand", "name": "Quick"}, "offers": {"@type": "Offer", "price": "1299.90", '
                '"priceCurrency": "TRY", "availability": "https://schema.org/InStock", "gtin13": "8690000000017"}}')
BARE_PRODUCT = ('{"@context": "https://schema.org", "@type": "Product", "name": "Mavi Elbise", "sku": "ME-1", '
                '"offers": {"@type": "AggregateOffer", "lowPrice": "999", "priceCurrency": "TRY", "offerCount": 2}}')
CRUMB = '<nav class="breadcrumbs"><a href="/">Ana Sayfa</a> / <a href="/collections/elbise">Elbise</a> / <span>Ürün</span></nav>'


def _doc(title, body, *, head="", og="website"):
    return (f'<!doctype html><html lang="tr"><head><title>{title}</title><meta property="og:type" content="{og}">'
            f'{head}</head><body>{MENU}<main><h1>{title}</h1>{TEXT}{body}</main>{FOOTER}</body></html>')


def _ld(block):
    return f'<script type="application/ld+json">{block}</script>'


def _shop(clean: bool = False) -> dict[str, str]:
    """A shop with one of each defect the quick checks report; `clean` is the same shop with each one fixed."""
    product_links = ('<a href="/products/kirmizi-elbise">Kırmızı</a>' if clean else
                     '<a href="/collections/elbise/products/kirmizi-elbise">Kırmızı</a>')
    next_page = '<a href="/collections/elbise?page=2">2</a>' if clean else ""
    crumb = CRUMB if clean else ""
    pages = {
        "/": _doc("Quick Shop", '<a href="/pages/kampanya">Kampanya</a><a href="/eski">Eski</a>'
                                + ("" if clean else '<a href="/pages/etbi%CC%87s">ETBİS</a><a href="/pages/123456">Duyuru</a>')),
        "/collections": _doc("Koleksiyonlar", "".join(f'<a href="/collections/{c}">{c}</a>' for c in ("elbise", "canta", "bos", "az"))),
        "/collections/elbise": _doc("Elbise", product_links + '<a href="/products/mavi-elbise">Mavi</a>'
                                    '<a href="/products/yesil-elbise">Yeşil</a>' + next_page,
                                    head='<link rel="next" href="/collections/elbise?page=2">', og="product.group"),
        "/collections/canta": _doc("Çanta", '<a href="/products/siyah-canta">Siyah</a><a href="/products/kirmizi-elbise">Kırmızı</a>'
                                            '<a href="/products/mavi-elbise">Mavi</a>', og="product.group"),
        "/collections/bos": _doc("Outlet", '<p>Bu koleksiyonda ürün yok.</p>' if not clean else
                                 '<a href="/products/siyah-canta">S</a><a href="/products/yesil-elbise">Y</a><a href="/products/mavi-elbise">M</a>',
                                 og="product.group"),
        "/collections/az": _doc("Parfüm", '<a href="/products/siyah-canta">Siyah</a>' if not clean else
                                '<a href="/products/siyah-canta">S</a><a href="/products/yesil-elbise">Y</a><a href="/products/mavi-elbise">M</a>',
                                og="product.group"),
        "/collections/elbise/products/kirmizi-elbise": _doc("Kırmızı Elbise", CRUMB, og="product",
                                                            head=f'<link rel="canonical" href="{SHOP}/products/kirmizi-elbise">' + _ld(GTIN_PRODUCT)),
        "/products/kirmizi-elbise": _doc("Kırmızı Elbise", CRUMB, og="product", head=_ld(GTIN_PRODUCT)),
        "/products/mavi-elbise": _doc("Mavi Elbise", crumb, og="product", head=_ld(GTIN_PRODUCT if clean else BARE_PRODUCT)),
        "/products/yesil-elbise": _doc("Yeşil Elbise", CRUMB, og="product", head=_ld(GTIN_PRODUCT)),
        "/products/siyah-canta": _doc("Siyah Çanta", crumb, og="product", head=_ld(GTIN_PRODUCT)),
        "/blogs/news": _doc("Blog", '<a href="/blogs/news/sezon-rehberi">Sezon rehberi</a><a href="/blogs/news/kumas-nedir">Kumaş nedir</a>'),
        "/blogs/news/sezon-rehberi": _doc("Sezon rehberi", '<p class="post-author">Ayşe Yılmaz</p>' if clean else "", og="article"),
        "/blogs/news/kumas-nedir": _doc("Kumaş nedir", "", og="article", head='<meta name="author" content="Ayşe Yılmaz">'),
        "/pages/kampanya": _doc("Kampanya", ""),
        "/pages/etbi%CC%87s": _doc("ETBİS", ""),
        "/pages/123456": _doc("Duyuru", ""),
        "/eski": _doc("Eski", "", head="" if clean else '<meta name="robots" content="noindex">'),
        "/policies/privacy-policy": _doc("Gizlilik", ""),
    }
    return pages


def _respond(pages):
    robots = f"User-agent: Googlebot\nDisallow: /eski\n\nUser-agent: *\nAllow: /\nSitemap: {SHOP}/sitemap.xml\n"
    sitemap = ('<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
               'xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">'
               f'<url><loc>{SHOP}/</loc><image:image><image:loc>{SHOP}/a.jpg</image:loc></image:image></url>'
               f'<url><loc>{SHOP}/pages/kampanya</loc></url></urlset>')

    def respond(request):
        path = request.url.raw_path.decode().split("?")[0]
        if path == "/robots.txt":
            return httpx.Response(200, text=robots, headers={"content-type": "text/plain"})
        if path == "/sitemap.xml":
            return httpx.Response(200, text=sitemap, headers={"content-type": "application/xml"})
        for key in (path, path.upper(), path.lower()):
            if key in pages:
                return httpx.Response(200, headers=HTML, text=pages[key])
        return httpx.Response(404, headers=HTML, text=_doc("Yok", ""))
    return respond


def _audit(clean=False):
    config = CrawlConfig(**{**QUIET, "max_pages": 40, "sitemap_check_max": 5})
    return run_audit(SHOP + "/", config, httpx.MockTransport(_respond(_shop(clean))))


@pytest.fixture(scope="module")
def shop():
    outcome = _audit()
    return outcome, {f.rule_id: f for c in outcome.checks for f in c.findings}


def _paths(finding):
    return sorted(u.removeprefix(SHOP) for u in finding.scope.get("_all_urls") or finding.scope["urls"])


# -- the rules on a made-up shop -------------------------------------------------------------------------------------

def test_links_to_an_alias_are_counted_and_a_canonical_that_differs_only_in_percent_case_is_not_one(shop):
    _, found = shop
    f = found["idx6.alias_links"]
    assert f.check_id == "IDX-6" and f.severity.value == "S4" and f.confidence.value == "verified"
    assert _paths(f) == ["/collections/elbise"] and f.evidence["link_count"] == 1
    assert f.evidence["targets"] == [{"url": SHOP + "/collections/elbise/products/kirmizi-elbise",
                                      "canonical": SHOP + "/products/kirmizi-elbise", "linked_from_pages": 1}]
    groups = {SHOP + "/a%CC%87": {"canonical": SHOP + "/a%cc%87"}}
    page = SimpleNamespace(url=SHOP + "/", outlinks=[{"target": SHOP + "/a%CC%87"}])
    assert quick_rules.alias_links([page], groups) == []


def test_empty_and_near_empty_collections_are_found_and_a_hub_or_a_full_one_is_not(shop):
    _, found = shop
    f = found["str15.empty_collections"]
    assert f.check_id == "STR-15" and f.confidence.value == "estimated" and "LG-102" in f.launch_gated
    # DECISIONS 371: only a collection with no product at all; /collections/az (1 product) is no finding
    assert _paths(f) == ["/collections/bos"]
    [row] = f.evidence["pages"]
    assert row["url"] == SHOP + "/collections/bos" and row["products_listed"] == 0 and row["empty"] is True
    assert row["row"]["tr"].startswith("HTML'de 0 ürün") and f.evidence["near_empty"] == 0
    assert f.notes == [quick_rules.EMPTY_COLLECTIONS_NOTE]


def test_an_address_with_a_combining_dot_is_reported_with_its_composed_form(shop):
    _, found = shop
    f = found["tseo1.url_decomposed"]
    assert f.check_id == "TSEO-1" and _paths(f) == ["/pages/etbi%CC%87s"]
    [row] = f.evidence["addresses"]
    assert row["fixed"] == SHOP + "/pages/etbis" and row["characters"] == ["U+0307"] and row["read"] is True
    # A Turkish letter written as itself (ı = %C4%B1) and a composed İ (%C4%B0) are not decomposed.
    assert quick_rules.decomposed_addresses([SHOP + "/kad%C4%B1n", SHOP + "/%C4%B0zmir"], set(), set()) == []


def test_noindex_behind_a_robots_rule_for_googlebot_is_found_when_maya_could_read_it(shop):
    _, found = shop
    f = found["acc3.robots_noindex"]
    assert f.check_id == "ACC-3" and _paths(f) == ["/eski"] and f.confidence.value == "verified"
    [row] = f.evidence["pages"]
    assert [b["bot"] for b in row["blocked_for"]] == ["Googlebot"] and "Disallow: /eski" in row["blocked_for"][0]["robots"]


def test_a_list_page_whose_next_page_is_only_in_link_rel_next_is_found(shop):
    _, found = shop
    f = found["idx7.pagination_unlinked"]
    assert f.check_id == "IDX-7" and _paths(f) == ["/collections/elbise"] and f.confidence.value == "verified"
    assert f.evidence["pages"][0]["next"] == SHOP + "/collections/elbise?page=2"
    # A page-2 address known from elsewhere, not linked from page 1, is the estimated form.
    page = PageFetch(url=SHOP + "/collections/x", discovered_via="link", depth=1, requested_at="", user_agent="", status=200,
                     error=None, elapsed_ms=0, content_type="text/html", body_bytes=1, body_truncated=False, headers={},
                     fetch_class=__import__("maya_audit.models", fromlist=["FetchClass"]).FetchClass.OK,
                     classification_confidence=__import__("maya_audit.models", fromlist=["Confidence"]).Confidence.VERIFIED,
                     classification_evidence=[], analysis={"title": "X"}, outlinks=[])
    [estimated] = quick_rules.pagination_unlinked([page], {page.url: {"page_type": "category"}}, [SHOP + "/collections/x?page=2"])
    assert estimated.confidence.value == "estimated" and estimated.evidence["pages"][0]["source"].startswith("a page-2 address")


def test_products_without_a_breadcrumb_or_a_content_link_to_a_category_are_found(shop):
    _, found = shop
    f = found["idx7.product_no_category"]
    assert f.check_id == "IDX-7" and f.confidence.value == "estimated" and "LG-102" in f.launch_gated
    # The menu links every collection on every page: that does not count. The breadcrumb does.
    assert _paths(f) == ["/products/mavi-elbise", "/products/siyah-canta"]


def test_slugs_that_are_ids_too_long_or_hold_symbols_are_unclear_and_word_slugs_are_not(shop):
    _, found = shop
    f = found["tseo1.url_slug_unclear"]
    assert _paths(f) == ["/pages/123456"] and f.evidence["by_reason"] == {"an id only": 1}
    assert quick_rules.slug_problem(SHOP + "/products/" + "uzun-" * 25) == "over 100 characters"
    assert quick_rules.slug_problem(SHOP + "/pages/yaz%20indirimi") == "spaces or symbols"
    assert quick_rules.slug_problem(SHOP + "/products/a1b2c3d4e5f6") == "an id only"
    for fine in ("/products/kad%C4%B1n-keten-g%C3%B6mlek", "/blogs/news/2024-yaz-rehberi", "/pages/etbi%CC%87s", "/"):
        assert quick_rules.slug_problem(SHOP + fine) is None, fine


def test_an_article_with_no_author_anywhere_is_found_and_a_meta_author_is_enough(shop):
    _, found = shop
    f = found["str3.article_no_author"]
    assert f.check_id == "STR-3" and _paths(f) == ["/blogs/news/sezon-rehberi"] and f.evidence["articles"] == 2


def test_product_markup_without_gtin_or_mpn_is_found_from_the_fields_kept_in_report_json(shop):
    outcome, found = shop
    f = found["str3.product_no_identifier"]
    assert f.check_id == "STR-3" and _paths(f) == ["/products/mavi-elbise"] and f.launch_gated == []
    assert f.evidence["pages"][0]["brand"] is None and f.evidence["product_pages_with_markup"] == 4
    report = build_report(outcome.result, outcome.gates, outcome.checks)
    assert report["schema_version"] == "1.33"
    pages = {p["url"]: p for p in report["crawl"]["pages"]}
    [kept] = pages[SHOP + "/products/kirmizi-elbise"]["analysis"]["structured_data"]["products"]
    assert kept == {"type": "Product", "gtin": {}, "mpn": None, "sku": "KE-1", "brand": "Quick",
                    "offers": [{"price": "1299.90", "priceCurrency": "TRY", "availability": "InStock", "gtin": "8690000000017"}],
                    "has_variant": 0, "variant_identifiers": 0, "in_list": False}
    [bare] = pages[SHOP + "/products/mavi-elbise"]["analysis"]["structured_data"]["products"]
    assert bare["offers"] == [{"price": "999", "priceCurrency": "TRY", "availability": None}]


def test_the_sitemap_records_its_image_and_video_entries(shop):
    outcome, _ = shop
    doc = next(d for d in outcome.result.sitemap_docs if d.kind == "urlset")
    assert (doc.image_entries, doc.video_entries) == (1, 0)


def test_a_clean_shop_gets_none_of_the_quick_checks_findings():
    outcome = _audit(clean=True)
    new = {"idx6.alias_links", "str15.empty_collections", "tseo1.url_decomposed", "acc3.robots_noindex",
           "idx7.pagination_unlinked", "idx7.product_no_category", "idx5.no_image_sitemap", "idx5.no_video_sitemap",
           "tseo1.url_slug_unclear", "str3.article_no_author", "str3.product_no_identifier"}
    assert {f.rule_id for c in outcome.checks for f in c.findings} & new == set()


# -- image and video sitemaps ----------------------------------------------------------------------------------------

def _image_pages(n):
    return [SimpleNamespace(url=f"{SHOP}/p{i}", analysis={"images": [{"src": f"/img/{i}-{j}.jpg", "in_chrome": False} for j in range(10)],
                                                         "media": [{"tag": "video"}] if i < 12 else []}) for i in range(n)]


def test_many_images_and_videos_without_sitemap_entries_are_found_only_when_the_counts_are_known():
    urlset = {"url": SHOP + "/sitemap.xml", "kind": "urlset", "error": None, "image_entries": 0, "video_entries": 0}
    made, why = quick_rules.media_sitemaps(_image_pages(25), [urlset])
    assert why is None and [f.rule_id for f in made] == ["idx5.no_image_sitemap", "idx5.no_video_sitemap"]
    assert made[0].title == "The sitemap lists no images although the pages read show 250 different images"
    assert quick_rules.media_sitemaps(_image_pages(25), [{**urlset, "image_entries": 40, "video_entries": 3}]) == ([], None)
    assert quick_rules.media_sitemaps(_image_pages(5), [urlset]) == ([], None)  # not many: nothing to say
    old = {k: v for k, v in urlset.items() if k not in ("image_entries", "video_entries")}
    assert quick_rules.media_sitemaps(_image_pages(25), [old])[1].startswith("the sitemap records hold no image")


# -- Product fields --------------------------------------------------------------------------------------------------

def test_product_fields_read_identifiers_from_the_product_its_offers_and_its_variants():
    group = ('{"@context": "https://schema.org", "@graph": [{"@type": "ProductGroup", "name": "G", "brand": "Quick", '
             '"hasVariant": [{"@type": "Product", "sku": "V1", "mpn": "M-1"}, {"@type": "Product", "sku": "V2"}]}, '
             '{"@type": "ItemList", "itemListElement": [{"@type": "ListItem", "item": {"@type": "Product", "name": "L"}}]}]}')
    analysis = analyze_html(f"<html><head>{_ld(group)}</head><body></body></html>", SHOP + "/products/g")
    group_row, listed = analysis["structured_data"]["products"]
    assert group_row["type"] == "ProductGroup" and group_row["has_variant"] == 2 and group_row["variant_identifiers"] == 1
    assert group_row["brand"] == "Quick" and quick_rules._has_identifier(group_row) and listed["in_list"] is True
    plain = analyze_html("<html><body><p>No markup</p></body></html>", SHOP + "/")
    assert "products" not in plain["structured_data"] and plain["author_signals"] == []


# -- the page reader's grouping (Maya's crawler blocked) -------------------------------------------------------------

def test_pages_read_through_firecrawl_get_importance_when_mayas_crawler_was_blocked(tmp_path, monkeypatch):
    import socket
    from maya_audit.client_selection import grouping, key_pages
    from maya_audit.firecrawl import reader
    from maya_audit.firecrawl.settings import Options
    from test_firecrawl import SITE, Firecrawl, blocked_audit, client_for
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: (_ for _ in ()).throw(socket.gaierror(8, "not known")))
    outcome = blocked_audit(missing_policy=True)
    reader.apply(outcome, CrawlConfig(**{**QUIET, "max_pages": 10}), client_for(tmp_path, Firecrawl(SITE)), Options())
    kept = outcome.result.reader_page_grouping
    assert kept["reader"] == "Firecrawl" and kept["pages_scored"] == 4
    assert set(kept["pages"]) == {"https://bank.test/", "https://bank.test/about", "https://bank.test/products", "https://bank.test/contact"}
    assert kept["pages"]["https://bank.test/"]["page_type"] == "home" and kept["pages"]["https://bank.test/"]["importance_rank"] == 1
    # Maya's own record (a 403) is still not scored; the report keeps the reader's grouping beside it.
    report = build_report(outcome.result, outcome.gates, outcome.checks)
    assert report["crawl"]["reader_page_grouping"]["pages"]["https://bank.test/about"]["importance"] > 0
    importance, summary = grouping(report)
    assert set(importance) == set(kept["pages"]) and summary["reader"] == "Firecrawl" and "pages" not in summary
    assert [row["url"] for row in key_pages(report, [], importance)][0] == "https://bank.test/"
    json.dumps(report)


def test_an_audit_maya_read_itself_has_no_reader_grouping():
    outcome = _audit(clean=True)
    assert outcome.result.reader_page_grouping is None and outcome.result.page_grouping["pages_scored"] > 10


# -- offline, on a saved report --------------------------------------------------------------------------------------

def test_a_saved_report_gets_the_quick_checks_offline_with_product_fields_from_its_saved_json_ld(shop, tmp_path):
    from maya_audit.reassess_rules import apply
    outcome, _ = shop
    report = build_report(outcome.result, outcome.gates, outcome.checks)
    # A report saved before 1.24: no quick-check findings, no Product fields, no author signals, no sitemap media counts.
    rules = {"idx6.alias_links", "str15.empty_collections", "tseo1.url_decomposed", "acc3.robots_noindex", "idx7.pagination_unlinked",
             "idx7.product_no_category", "tseo1.url_slug_unclear", "str3.article_no_author", "str3.product_no_identifier"}
    for check in report["checks"]:
        check["findings"] = [f for f in check["findings"] if f.get("rule_id") not in rules]
    for page in report["crawl"]["pages"]:
        (page.get("analysis") or {}).get("structured_data", {}).pop("products", None)
        (page.get("analysis") or {}).pop("author_signals", None)
    for doc in report["crawl"]["sitemap_docs"]:
        doc.pop("image_entries"), doc.pop("video_entries")
    saved = json.dumps(report, sort_keys=True)
    jsonld = {SHOP + "/products/mavi-elbise": [BARE_PRODUCT], SHOP + "/products/kirmizi-elbise": [GTIN_PRODUCT, "{not json"]}
    new, affected, record = apply(report, {}, jsonld_by_url=jsonld)
    assert json.dumps(report, sort_keys=True) == saved  # the source is never changed
    added = {f["rule_id"]: f for c in new["checks"] for f in c["findings"] if f.get("rule_id") in rules}
    # robots.txt's text is not in a saved report: SEO-031 is said to be not assessed, never "no finding".
    assert set(added) == rules - {"acc3.robots_noindex"}
    assert [u.removeprefix(SHOP) for u in affected[added["str3.product_no_identifier"]["id"]]] == ["/products/mavi-elbise"]
    assert added["str15.empty_collections"]["launch_gated"] == ["LG-44", "LG-102"]
    assert "Read from a saved report" in added["str3.article_no_author"]["notes"][-1]
    missing = {row["rule"].split(" ")[0] for row in record["not_assessed_offline"]}
    assert {"SEO-031", "SEO-036"} <= missing and "SEO-097" not in missing
    assert any("Product fields read from the saved JSON-LD of 2 page(s)" in c for c in record["changes"])
    again, _, second = apply(new, affected, jsonld_by_url=jsonld)  # applied twice: nothing is added twice
    assert sum(len(c["findings"]) for c in again["checks"]) == sum(len(c["findings"]) for c in new["checks"])
    assert not [c for c in second["changes"] if "added:" in c]


def test_the_offline_tool_reads_json_ld_from_the_audits_evidence_copies(tmp_path):
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("reassess_saved", Path(__file__).resolve().parents[1] / "tools" / "reassess_saved.py")
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    (tmp_path / "evidence").mkdir()
    (tmp_path / "evidence" / "001-home.json").write_text(json.dumps({"url": SHOP + "/", "json_ld_blocks": [BARE_PRODUCT]}))
    (tmp_path / "evidence" / "002-broken.json").write_text("{not json")
    assert tool._saved_jsonld(tmp_path) == {SHOP + "/": [BARE_PRODUCT]}
    assert tool._saved_jsonld(tmp_path / "nowhere") == {}
