"""v0.3 stage 3, page grouping (DECISIONS 297): template key, page type, internal link score, click depth and importance
for every page read, stored on the page record (schema 1.23) and never used for a finding or a severity.
Every site here is made up and held in memory; no socket is opened and nothing is paid for.
"""
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx

from maya_audit.audit import run_audit
from maya_audit.config import CrawlConfig
from maya_audit.models import PageFetch, page_from_record, to_jsonable
from maya_audit.page_groups import annotate, click_depths, layout_fingerprint, pagerank, url_patterns
from maya_audit.report import build_report
from test_deadline_hosted_hardening import QUIET

SHOP = "https://demo-shop.test"
HTML = {"content-type": "text/html; charset=utf-8"}
TEXT = "<p>" + "Yeni sezon elbiseler ve zarif aksesuarlar her gün özenle hazırlanır. " * 12 + "</p>"
MENU = ('<header><nav><a href="/">Ana Sayfa</a><a href="/collections/elbise">Elbise</a>'
        '<a href="/collections/canta">Çanta</a><a href="/search">Ara</a><a href="/cart">Sepet</a></nav></header>')
FOOTER = '<footer><a href="/policies/privacy-policy">Gizlilik Politikası</a><a href="/blogs/news">Blog</a></footer>'


def _doc(title, body, *, head="", og="website", lang="tr", menu=MENU):
    return (f'<!doctype html><html lang="{lang}"><head><title>{title}</title><meta property="og:type" content="{og}">'
            f'{head}</head><body>{menu}<main><h1>{title}</h1>{TEXT}{body}</main>{FOOTER}</body></html>')


def _shop() -> dict[str, str]:
    canonical = f'<link rel="canonical" href="{SHOP}/products/kirmizi-elbise">'
    return {
        "/": _doc("Demo Shop", '<a href="/blogs/news/sezon-rehberi">Sezon rehberi</a>',
                  head=f'<link rel="alternate" hreflang="en" href="{SHOP}/en">'
                       f'<link rel="alternate" hreflang="tr" href="{SHOP}/">'),
        # Reached only through the homepage's hreflang: the language switcher is a form, not a link.
        "/en": _doc("Demo Shop EN", '<a href="/en/collections/elbise">Dresses</a>', lang="en", menu=""),
        "/en/collections/elbise": _doc("Dresses", "", lang="en", menu=""),
        "/collections/elbise": _doc("Elbise", '<a href="/collections/elbise/products/kirmizi-elbise">Kırmızı</a>'
                                              '<a href="/products/mavi-elbise">Mavi</a>'
                                              '<a href="/products/yesil-elbise">Yeşil</a>', og="product.group"),
        "/collections/canta": _doc("Çanta", '<a href="/products/siyah-canta">Siyah çanta</a>'
                                            '<a href="/products/kirmizi-elbise">Kırmızı elbise</a>', og="product.group"),
        "/collections/elbise/products/kirmizi-elbise": _doc("Kırmızı Elbise", "", og="product", head=canonical),
        "/products/kirmizi-elbise": _doc("Kırmızı Elbise", "", og="product"),
        "/products/mavi-elbise": _doc("Mavi Elbise", "", og="product"),
        "/products/yesil-elbise": _doc("Yeşil Elbise", "", og="product"),
        "/products/siyah-canta": _doc("Siyah Çanta", "", og="product"),
        "/blogs/news": _doc("Blog", '<a href="/blogs/news/sezon-rehberi">Sezon rehberi</a>'
                                    '<a href="/blogs/news/kumas-nedir">Kumaş nedir</a>'),
        "/blogs/news/sezon-rehberi": _doc("Sezon rehberi", "", og="article"),
        "/blogs/news/kumas-nedir": _doc("Kumaş nedir", "", og="article"),
        "/policies/privacy-policy": _doc("Gizlilik Politikası", ""),
        "/search": _doc("Arama", ""),
        "/cart": _doc("Sepet", ""),
        # In the sitemap only: no page read links to it.
        "/pages/eski-kampanya": _doc("Eski kampanya", ""),
    }


def _respond(pages):
    sitemap = ('<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
               + "".join(f"<url><loc>{SHOP}{p}</loc></url>" for p in ("/", "/pages/eski-kampanya")) + "</urlset>")

    def respond(request):
        path = request.url.path
        if path == "/robots.txt":
            return httpx.Response(200, text=f"User-agent: *\nAllow: /\nSitemap: {SHOP}/sitemap.xml\n",
                                  headers={"content-type": "text/plain"})
        if path == "/sitemap.xml":
            return httpx.Response(200, text=sitemap, headers={"content-type": "application/xml"})
        if path in pages:
            return httpx.Response(200, headers=HTML, text=pages[path])
        return httpx.Response(404, headers=HTML, text=_doc("Yok", ""))
    return respond


def _audit(pages=None):
    pages = pages or _shop()
    # Stage 3's own importance (DECISIONS 297): the business type "Diğer" keeps it exactly (DECISIONS 311).
    config = CrawlConfig(**{**QUIET, "max_pages": 40, "sitemap_check_max": 5, "business_type": "diger"})
    return run_audit(SHOP + "/", config, httpx.MockTransport(_respond(pages)))


def _by_path(result):
    return {p.url.removeprefix(SHOP) or "/": p.grouping for p in result.pages if p.grouping}


# -- unit rules ----------------------------------------------------------------------------------------------------

def test_url_patterns_keep_the_section_and_language_folder_and_turn_slugs_into_a_star():
    urls = [f"{SHOP}/", f"{SHOP}/en", f"{SHOP}/products/a", f"{SHOP}/products/b", f"{SHOP}/en/products/a",
            f"{SHOP}/collections/x", f"{SHOP}/collections/y", f"{SHOP}/collections/x/products/a",
            f"{SHOP}/collections/y/products/b", f"{SHOP}/pages/about", f"{SHOP}/blogs/news/p1", f"{SHOP}/blogs/news/p2",
            f"{SHOP}/blogs/news", f"{SHOP}/search", f"{SHOP}/orders/123456?x=1"]
    got = {u.removeprefix(SHOP): p for u, p in url_patterns(urls).items()}
    assert got["/"] == "/" and got["/en"] == "/en" and got["/search"] == "/search"
    assert got["/products/a"] == got["/products/b"] == "/products/*"
    assert got["/en/products/a"] == "/en/products/*"  # one product under /en is still a product slot: a known folder
    assert got["/collections/x"] == "/collections/*" and got["/collections/x/products/a"] == "/collections/*/products/*"
    assert got["/pages/about"] == "/pages/*"  # a known folder, even with one child
    assert got["/blogs/news"] == "/blogs/*" and got["/blogs/news/p1"] == "/blogs/*/*"  # Shopify: a store may have several blogs
    assert got["/orders/123456?x=1"] == "/orders/*"  # an id; the query is not part of the pattern


def test_the_layout_fingerprint_ignores_page_text_and_the_language_folder_of_form_targets():
    a = {"og": {"og:type": ["product"]}, "structured_data": {"types": ["Product", "FAQPage", "Answer"]},
         "main_region_types": ["main"], "breadcrumbs": [{"x": 1}], "form_actions": ["/cart/add", "/search"]}
    b = {**a, "structured_data": {"types": ["Product"]}, "form_actions": ["/en/cart/add", "/en/search"]}
    c = {**a, "og": {"og:type": ["website"]}}
    assert layout_fingerprint(a) == layout_fingerprint(b) != layout_fingerprint(c)


def test_pagerank_rewards_links_from_important_pages_and_click_depth_follows_the_homepages_hreflang():
    graph = {"h": {"a": 1.0, "b": 1.0}, "a": {"c": 1.0, "h": 1.0}, "b": {"h": 1.0}, "c": {"h": 1.0}, "d": {"c": 1.0},
             "e": {"h": 1.0}, "x": {}}
    rank = pagerank(graph)
    assert abs(sum(rank.values()) - 1) < 1e-9 and rank["h"] == max(rank.values())
    assert rank["c"] > rank["d"]  # c is linked from a (linked from the homepage); d from nothing
    depth, via = click_depths(graph, "h", {"e"})
    assert depth == {"h": 0, "a": 1, "b": 1, "c": 2, "e": 1} and via == {"e"}
    assert "d" not in depth and "x" not in depth  # not reached: no depth at all, never 0


# -- the whole audit -----------------------------------------------------------------------------------------------

def test_a_made_up_shop_gets_templates_types_depths_and_importance_on_every_page_read():
    outcome = _audit()
    g = _by_path(outcome.result)
    types = {path: row.get("page_type") for path, row in g.items()}
    assert types["/"] == types["/en"] == "home"
    assert types["/collections/elbise"] == types["/collections/canta"] == "category"
    assert types["/products/mavi-elbise"] == types["/collections/elbise/products/kirmizi-elbise"] == "product"
    assert types["/blogs/news/sezon-rehberi"] == "blog_article" and types["/blogs/news"] == "category"
    assert types["/policies/privacy-policy"] == "policy"
    assert types["/search"] == types["/cart"] == "utility"
    assert g["/products/mavi-elbise"]["template_key"] == "/products/*"
    assert g["/collections/elbise/products/kirmizi-elbise"]["url_pattern"] == "/collections/*/products/*"
    assert g["/en/collections/elbise"]["url_pattern"] == "/en/collections/*"
    # Click depth: links, and the homepage's hreflang as one step; a page only the sitemap names has none.
    assert g["/"]["click_depth"] == 0 and g["/collections/elbise"]["click_depth"] == 1
    assert g["/products/mavi-elbise"]["click_depth"] == 2
    assert g["/en"]["click_depth"] == 1 and g["/en"]["click_depth_basis"] == "links and the homepage's hreflang"
    assert g["/en/collections/elbise"]["click_depth"] == 2
    orphan = g["/pages/eski-kampanya"]
    assert orphan["click_depth"] is None and orphan["click_depth_basis"].startswith("not reached")
    assert orphan["importance_parts"]["click_depth"] == 0
    # Importance: the homepage first; the menu's categories above a product and the footer's policy page.
    imp = {path: row["importance"] for path, row in g.items()}
    assert imp["/"] == max(imp.values())
    assert imp["/collections/elbise"] > imp["/products/mavi-elbise"] > imp["/pages/eski-kampanya"]
    assert imp["/collections/elbise"] > imp["/policies/privacy-policy"]
    # Capped at 20: a duplicate whose canonical names another page, and a cart or search page however well linked.
    dup = g["/collections/elbise/products/kirmizi-elbise"]
    assert dup["importance"] <= 20 and dup["importance_parts"]["capped"] == "not indexable"
    assert g["/search"]["importance"] <= 20 and g["/search"]["importance_parts"]["capped"] == "utility page"
    assert g["/search"]["internal_link_score"] > g["/products/mavi-elbise"]["internal_link_score"]  # linked, but capped
    # A link to the duplicate counts for the page its canonical names, when that page was read.
    # /collections/elbise links to the duplicate, /collections/canta to the page itself: two pages link to it.
    assert g["/products/kirmizi-elbise"]["inlinks"] == 2 and g["/collections/elbise/products/kirmizi-elbise"]["inlinks"] == 0
    summary = outcome.result.page_grouping
    assert summary["confidence"] == "Estimated" and summary["page_types"]["product"] == 5
    assert summary["pages_scored"] == sum(1 for row in g.values() if "importance" in row)
    assert summary["not_reached_from_homepage"] == 1 and summary["reached_through_hreflang"] == 2
    assert dup["click_depth"] == 2  # click depth follows the link as clicked, not the canonical


def test_the_grouping_is_written_per_page_in_report_json_under_schema_1_23():
    outcome = _audit()
    report = build_report(outcome.result, outcome.gates, outcome.checks)
    assert report["schema_version"] == "1.29"
    pages = {p["url"]: p for p in report["crawl"]["pages"]}
    home = pages[SHOP + "/"]["grouping"]
    assert home["page_type"] == "home" and home["importance"] >= 80 and home["template_key"] == "/"
    assert set(home) >= {"template_key", "url_pattern", "layout", "page_type", "page_type_basis", "internal_link_score",
                         "inlinks", "click_depth", "click_depth_basis", "importance", "importance_parts"}
    missing = pages[SHOP + "/nowhere"]["grouping"] if SHOP + "/nowhere" in pages else {"not_scored": "x"}
    assert "importance" not in missing
    assert report["crawl"]["page_grouping"]["method_version"] == 2
    json.dumps(report)  # plain JSON


def test_the_grouping_never_changes_a_finding_or_a_severity():
    outcome = _audit()
    before = json.dumps(to_jsonable(outcome.checks), sort_keys=True, default=str)
    for p in outcome.result.pages:
        p.grouping = None
    annotate(outcome.result)  # again, from nothing
    assert json.dumps(to_jsonable(outcome.checks), sort_keys=True, default=str) == before
    # And the grouping is the same each time (idempotent; finalization runs it again after a page reader).
    first = {p.url: p.grouping for p in outcome.result.pages}
    annotate(outcome.result)
    assert {p.url: p.grouping for p in outcome.result.pages} == first


def test_a_page_not_read_is_not_scored_and_says_why_never_a_zero():
    outcome = _audit({**_shop(), "/": _shop()["/"].replace("</main>", '<a href="/eski">Eski</a></main>'),
                      "/eski": None})
    g = {p.url.removeprefix(SHOP): p.grouping for p in outcome.result.pages}
    assert g["/eski"] == {"not_scored": "not a readable HTML page"}


def test_og_type_article_on_every_page_is_a_site_default_not_an_article():
    """WordPress sets og:type=article on every page (adile): only pages in an article folder, or with its posts'
    layout, are articles; /hikayemiz is not."""
    def wp(title, body="", folder_post=False):
        main_type = "article" if folder_post else "div"
        return (f'<!doctype html><html lang="tr"><head><title>{title}</title><meta property="og:type" content="article">'
                f'</head><body><header><nav><a href="/">Ana Sayfa</a><a href="/hikayemiz">Hikayemiz</a>'
                f'<a href="/iletisim">İletişim</a><a href="/blog">Blog</a></nav></header><main><{main_type}><h1>{title}</h1>'
                f'{TEXT}{body}</{main_type}></main></body></html>')
    pages = {"/": wp("Ev"), "/hikayemiz": wp("Hikayemiz"), "/iletisim": wp("İletişim"), "/kvkk": wp("KVKK"),
             "/blog": wp("Blog", '<a href="/blog/a">A</a><a href="/blog/b">B</a><a href="/blog/c">C</a>'),
             "/blog/a": wp("A", folder_post=True), "/blog/b": wp("B", folder_post=True), "/blog/c": wp("C", folder_post=True)}
    pages["/"] = pages["/"].replace("</main>", '<a href="/kvkk">KVKK</a></main>')
    outcome = _audit(pages)
    g = _by_path(outcome.result)
    assert g["/hikayemiz"]["page_type"] == "other" and "site default" in g["/hikayemiz"]["page_type_basis"]
    assert g["/blog/a"]["page_type"] == "blog_article" and g["/blog"]["page_type"] == "category"
    assert g["/kvkk"]["page_type"] == "policy"
    # Flat pages that share a layout are one template.
    assert g["/hikayemiz"]["template_key"] == g["/iletisim"]["template_key"] == f"/* ~ {g['/iletisim']['layout']}"


def test_the_offline_tool_reads_a_saved_report_and_leaves_it_unchanged(tmp_path):
    outcome = _audit()
    report = build_report(outcome.result, outcome.gates, outcome.checks)
    for page in report["crawl"]["pages"]:  # as a 1.22 report: no grouping saved
        page.pop("grouping", None)
    report["crawl"].pop("page_grouping", None)
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    before = path.read_bytes()
    out = tmp_path / "groups.json"
    tool = Path(__file__).resolve().parents[1] / "tools" / "page_groups_saved.py"
    run = subprocess.run([sys.executable, str(tool), str(path), "--top", "5", "--json", str(out)],
                         capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    assert "page types:" in run.stdout and SHOP + "/" in run.stdout
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved["pages"][SHOP + "/"]["page_type"] == "home" and path.read_bytes() == before
    # The same grouping as the engine's own (the saved page records hold what it needs).
    pages = [page_from_record(r) for r in report["crawl"]["pages"]]
    again = SimpleNamespace(pages=pages, start_url=SHOP + "/", origin=SHOP, discovered_urls=report["crawl"]["discovered_urls"],
                            sitemap_urls=report["crawl"]["sitemap_urls"], page_grouping=None)
    annotate(again)
    assert {p.url: p.grouping for p in again.pages} == saved["pages"]
    assert isinstance(pages[0], PageFetch)


# -- stage 3b (DECISIONS 298) ----------------------------------------------------------------------------------------

def _bare(url):
    return SimpleNamespace(url=url, outlinks=[], analysis={"og": {}, "title": "", "structured_data": {"types": []}})


def test_str3_page_kind_takes_a_product_inside_a_collection_for_a_product_not_a_listing():
    from maya_audit.checks.structure import page_kind
    home = SHOP + "/"
    for path in ("/collections/elbise/products/kirmizi", "/en/collections/elbise/products/kirmizi",
                 "/kategori/elbise/urun/kirmizi"):
        kind, basis = page_kind(_bare(SHOP + path), home)
        assert kind == "product" and basis.startswith("path /"), path
    for path in ("/collections/elbise", "/collections/products/kirmizi", "/collections/elbise/products",
                 "/collections/elbise/products/kirmizi/yorumlar"):
        assert page_kind(_bare(SHOP + path), home)[0] == "category", path


def test_a_canonical_that_was_not_read_is_scored_from_the_links_to_its_aliases():
    outcome = _audit()
    result = outcome.result
    # As on nihan: the duplicate under the collection was read, the /products/ page it names was not.
    result.pages = [p for p in result.pages if p.url != SHOP + "/products/kirmizi-elbise"]
    summary = annotate(result)
    canonical = SHOP + "/products/kirmizi-elbise"
    assert summary["aliases"] == 1 and summary["canonical_pages_scored"] == 1
    row = summary["canonical_pages"][canonical]
    assert row["read"] is False and row["indexable"] is None and row["page_type"] == "product"
    assert row["template_key"] == "/products/*" and row["aliases"] == 1 and "not read" in row["basis"]
    # Both links count for it: /collections/elbise links to the alias, /collections/canta to the address itself.
    assert row["inlinks"] == 2 and row["importance_parts"]["capped"] is False
    assert row["click_depth"] == 2 and row["click_depth_basis"] == "links"  # /collections/canta links to it
    alias = _by_path(result)["/collections/elbise/products/kirmizi-elbise"]
    assert alias["canonical"] == canonical and alias["canonical_importance"] == row["importance"]
    assert alias["importance"] <= 20 < row["importance"]
    # Ranked with the pages read.
    ranks = sorted([g["importance_rank"] for g in _by_path(result).values() if "importance_rank" in g]
                   + [row["importance_rank"]])
    assert ranks == list(range(1, len(ranks) + 1))
    # Linked only through its alias: as deep as the alias, and it says so.
    result.pages = [p for p in result.pages if p.url != SHOP + "/collections/canta"]
    alone = annotate(result)["canonical_pages"][canonical]
    assert alone["click_depth"] == 2 and alone["click_depth_basis"] == (
        f"through its alias {SHOP}/collections/elbise/products/kirmizi-elbise")
    assert alone["inlinks"] == 1


def test_a_canonical_not_read_that_names_another_item_is_not_followed():
    """Every page canonical to one address (a known CMS mistake) does not make that address a page of the site."""
    pages = _shop()
    pages["/collections/elbise/products/kirmizi-elbise"] = pages["/collections/elbise/products/kirmizi-elbise"].replace(
        "/products/kirmizi-elbise", "/products/baska")
    outcome = _audit(pages)
    assert SHOP + "/products/baska" not in outcome.result.page_grouping["canonical_pages"]


def test_a_policy_page_linked_only_from_footers_is_capped_at_35_and_one_in_the_menu_is_not():
    outcome = _audit()
    footer_only = _by_path(outcome.result)["/policies/privacy-policy"]
    assert footer_only["importance"] <= 35
    assert footer_only["importance_parts"]["capped"] == "policy page linked only from footers or sitewide blocks"
    menu = MENU.replace("</nav>", '<a href="/policies/privacy-policy">Gizlilik</a></nav>')
    pages = {path: html.replace(MENU, menu) for path, html in _shop().items()}
    in_menu = _by_path(_audit(pages).result)["/policies/privacy-policy"]
    assert in_menu["importance_parts"]["capped"] is False
    # The same link in the content of every page (a cookie banner) is a sitewide block: still capped.
    banner = {path: html.replace("</main>", '<p>Çerezler: <a href="/policies/privacy-policy">politika</a></p></main>')
              for path, html in _shop().items()}
    assert _by_path(_audit(banner).result)["/policies/privacy-policy"]["importance_parts"]["capped"] \
        == "policy page linked only from footers or sitewide blocks"


def test_ties_are_broken_by_products_listed_then_sitemap_order_never_by_address():
    menu = ('<header><nav><a href="/">Ev</a><a href="/collections/armut">Armut</a><a href="/collections/zeytin">Zeytin</a>'
            '<a href="/collections/incir">İncir</a></nav></header>')
    pages = {"/": _doc("Ev", "", menu=menu),
             # Equal links in: zeytin lists three products, armut and incir two each.
             "/collections/zeytin": _doc("Zeytin", '<a href="/products/z1">1</a><a href="/products/z2">2</a>'
                                                   '<a href="/products/z3?variant=7">3</a><a href="/products/z3">3</a>', menu=menu),
             # And one other page each, so that every category links to as many pages (the same link score).
             "/collections/armut": _doc("Armut", '<a href="/products/a1">1</a><a href="/products/a2">2</a>'
                                                 '<a href="/pages/hakkimizda">Biz</a>', menu=menu),
             "/collections/incir": _doc("İncir", '<a href="/products/i1">1</a><a href="/products/i2">2</a>'
                                                 '<a href="/pages/hakkimizda">Biz</a>', menu=menu),
             "/pages/hakkimizda": _doc("Biz", "", menu=menu)}
    for slug in ("z1", "z2", "z3", "a1", "a2", "i1", "i2"):
        pages[f"/products/{slug}"] = _doc(slug, "", og="product", menu=menu)
    order = ["/", "/collections/incir", "/collections/armut"]  # incir before armut in the sitemap
    sitemap = ('<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
               + "".join(f"<url><loc>{SHOP}{p}</loc></url>" for p in order) + "</urlset>")
    base = _respond(pages)

    def respond(request):
        if request.url.path == "/sitemap.xml":
            return httpx.Response(200, text=sitemap, headers={"content-type": "application/xml"})
        return base(request)
    config = CrawlConfig(**{**QUIET, "max_pages": 40, "sitemap_check_max": 5, "business_type": "diger"})
    g = _by_path(run_audit(SHOP + "/", config, httpx.MockTransport(respond)).result)
    cats = {path: g[path] for path in ("/collections/zeytin", "/collections/armut", "/collections/incir")}
    assert len({row["importance"] for row in cats.values()}) == 1  # a tie
    assert cats["/collections/zeytin"]["tie_break"]["products_listed"] == 3  # one product, whatever its ?variant=
    ranked = sorted(cats, key=lambda path: cats[path]["importance_rank"])
    assert ranked == ["/collections/zeytin", "/collections/incir", "/collections/armut"]  # not alphabetical


def test_blog_articles_are_flagged_citable_content_and_the_flag_changes_no_score():
    outcome = _audit()
    g = _by_path(outcome.result)
    assert g["/blogs/news/sezon-rehberi"]["citable_content"] is True
    assert g["/products/mavi-elbise"]["citable_content"] is False and g["/blogs/news"]["citable_content"] is False
    article = g["/blogs/news/sezon-rehberi"]
    parts = article["importance_parts"]
    assert article["importance"] == round(0.5 * parts["internal_link_score"] + 0.25 * parts["click_depth"]
                                          + 0.25 * parts["page_type"])
    assert outcome.result.page_grouping["citable_content_pages"] == 2
