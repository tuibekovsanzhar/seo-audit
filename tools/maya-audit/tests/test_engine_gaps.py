"""Engine gaps named by an external review: links built by JavaScript, click depth and inbound links,
anchor text, image files and formats, thin pages, and the caps on stored links.

Offline: fake server only. Tests that open a browser render pages served by the fake server.
"""

from types import SimpleNamespace

import pytest

from fakeserver import Response
from fakeserver.rnd_scenarios import FAST_RND
from maya_audit.analysis import analyze_html, image_formats
from maya_audit.checks.content_quality import generic_anchor
from maya_audit.html_links import extract_link_edges
from maya_audit.link_graph import build_link_graph
from maya_audit.render_discovery import clearly_more
from maya_audit.report import build_report, render_markdown
from test_review_fixes import TR, audit, links, page, short
from test_rnd_scenarios import _browser_available

LONG = f"<p>{TR}</p><p>{TR}</p><p>{TR}</p><p>{TR}</p>"  # about 200 words


def browser_or_skip():
    reason = _browser_available()
    if reason:
        pytest.skip(f"T1 rendering tests need a headless browser: {reason}")


# a. Render-assisted link discovery ---------------------------------------------------------------------
def test_clearly_more_needs_a_handful_of_new_links_and_a_real_share():
    assert clearly_more(0, 5) and clearly_more(2, 8) and clearly_more(10, 5)
    assert not clearly_more(0, 4)      # a widget's few links do not make a site JavaScript-built
    assert not clearly_more(40, 6)     # six more on a page that already has forty


JS_PATHS = [f"/urun-{n}/" for n in range(1, 9)]
JS_MENU = ("<div id='menu'></div><script>document.getElementById('menu').innerHTML = "
           + repr("".join(f'<a href="{path}">Ürün {n}</a>' for n, path in enumerate(JS_PATHS, 1))) + ";</script>")


def js_site():
    routes = {path: page(f"<h1>Ürün {n}</h1>{LONG}<p>Ürün {n} hakkında ayrıntılar.</p>") for n, path in enumerate(JS_PATHS, 1)}
    routes["/"] = page(f"<h1>Mağaza</h1>{LONG}<a href='/hakkimizda/'>Hakkımızda</a>" + JS_MENU)
    routes["/hakkimizda/"] = page(f"<h1>Hakkımızda</h1>{LONG}")
    return routes


def test_links_written_by_a_script_are_followed_and_the_report_says_so():
    browser_or_skip()
    outcome = audit(js_site(), sitemap=[], **{**FAST_RND, "render_enabled": True, "render_budget": 2, "render_settle_ms": 400})
    result = outcome.result
    discovery = result.render_discovery
    assert discovery["used"] and discovery["links_added"] == 8 and discovery["pages_rendered"] == 1
    [row] = discovery["pages"]
    assert (row["why"], row["raw_links"], row["links_only_after_rendering"]) == ("homepage", 2, 8)
    # Every product page was crawled, though no raw HTML links to it.
    by_url = {p.url.removeprefix(outcome.base): p for p in result.pages}
    assert set(JS_PATHS) <= set(by_url) and {by_url[path].discovered_via for path in JS_PATHS} == {"rendered_link"}
    rendered = [edge for edge in by_url["/"].outlinks if edge.get("rendered")]
    assert len(rendered) == 8 and rendered[0]["anchor"] == "Ürün 1"
    # The report says discovery used rendering: in INT-2, in IDX-7 and at the top of the links section.
    int2 = next(gate for gate in outcome.gates if gate.check_id == "INT-2")
    assert any("Link discovery used rendering: 8 link(s)" in caveat for caveat in int2.evidence["caveats"])
    assert "Link discovery used rendering: 8 link(s)" in render_markdown(result, outcome.gates, outcome.checks)
    assert build_report(result, outcome.gates, outcome.checks)["crawl"]["render_discovery"]["used"] is True
    idx7 = outcome.by_id["IDX-7"]
    assert idx7.evidence["links_known_only_from_a_rendered_view"] >= 8


def test_pages_of_a_javascript_built_site_are_not_called_orphans():
    browser_or_skip()
    options = {**FAST_RND, "render_enabled": True, "render_budget": 2, "render_settle_ms": 400}
    # /gizli-kampanya/ is in the sitemap and linked from nowhere that was rendered.
    routes = {**js_site(), "/gizli-kampanya/": page(f"<h1>Kampanya</h1>{LONG}")}
    listed = ["/"] + JS_PATHS + ["/gizli-kampanya/"]
    with_discovery = audit(routes, sitemap=listed, **options)
    idx7 = with_discovery.by_id["IDX-7"]
    assert not [f for f in idx7.findings if "no internal links" in f.title]
    assert idx7.evidence["orphans"].startswith("not assessed: this site writes links with JavaScript")
    assert idx7.evidence["unlinked_sitemap_pages_not_called_orphans"] == 1 and idx7.status == "partial"
    assert any(part["part"] == "orphan pages" for part in idx7.coverage["not_assessed"])
    # Without it, the same site looks like a homepage with nine orphans: the false alarm this prevents.
    without = audit(routes, sitemap=listed, **{**options, "render_discovery": False, "render_enabled": False})
    [orphans] = [f for f in without.by_id["IDX-7"].findings if "no internal links" in f.title]
    assert orphans.scope["count"] == 9
    assert without.result.render_discovery == {**without.result.render_discovery, "enabled": False, "used": False}


def test_a_page_that_gains_a_few_links_after_rendering_does_not_switch_discovery_on():
    browser_or_skip()
    paths = [f"/sayfa-{n}/" for n in range(1, 11)]
    widget = "<div id='w'></div><script>document.getElementById('w').innerHTML = '<a href=\"/ek-1/\">Ek 1</a><a href=\"/ek-2/\">Ek 2</a>';</script>"
    routes = {path: page(f"<h1>{path}</h1>{LONG}<p>{path} için metin.</p>") for path in paths}
    routes["/"] = page(f"<h1>Ana</h1>{LONG}" + links(paths) + widget)
    outcome = audit(routes, **{**FAST_RND, "render_enabled": True, "render_budget": 1, "render_settle_ms": 400})
    discovery = outcome.result.render_discovery
    assert discovery["pages_rendered"] == 1 and not discovery["used"] and discovery["links_added"] == 0
    assert discovery["pages"][0]["links_only_after_rendering"] == 2
    assert not any(p.url.endswith("/ek-1/") for p in outcome.result.pages)


# b. Click depth and inbound links ------------------------------------------------------------------------
def fetched(url, targets=(), status=200, location=None, via="link", rendered=()):
    edges = [{"target": t, "anchor": "x"} for t in targets] + [{"target": t, "anchor": "x", "rendered": True} for t in rendered]
    return SimpleNamespace(url=url, status=status, redirect_location=location, outlinks=edges, depth=0 if via == "start" else 9,
                           discovered_via=via)


def test_click_depth_is_the_shortest_path_and_passes_through_redirects():
    s = "https://s.example"
    pages = [fetched(f"{s}/", [f"{s}/a", f"{s}/eski"], via="start"),
             fetched(f"{s}/a", [f"{s}/b"]), fetched(f"{s}/b", [f"{s}/c", f"{s}/a"]), fetched(f"{s}/c", [f"{s}/d"]),
             fetched(f"{s}/d", [f"{s}/e"]), fetched(f"{s}/e", [f"{s}/f"]), fetched(f"{s}/f"),
             fetched(f"{s}/eski", status=301, location=f"{s}/yeni"), fetched(f"{s}/yeni", [f"{s}/d"]),
             fetched(f"{s}/yalniz", via="sitemap")]
    graph = build_link_graph(SimpleNamespace(pages=pages, start_url=f"{s}/", origin=s, render=None, render_discovery=None))
    depth = {url.removeprefix(s): n for url, n in graph.depth.items()}
    # /d is 4 clicks down the chain, and 2 through the redirect: the redirect itself is not a click.
    assert depth == {"/": 0, "/a": 1, "/yeni": 1, "/b": 2, "/d": 2, "/c": 3, "/e": 3, "/f": 4}
    assert "/yalniz" not in depth and graph.inbound_count(f"{s}/yalniz") == 0
    assert graph.inbound_count(f"{s}/d") == 2 and graph.inbound_count(f"{s}/a") == 2 and graph.inbound_count(f"{s}/yeni") == 1
    assert not graph.js_linked


def test_idx7_reports_pages_more_than_four_clicks_deep_and_the_most_and_least_linked_pages():
    chain = [f"/k{n}/" for n in range(1, 7)]
    routes = {path: page(f"<h1>Kat {n}</h1>{LONG}<p>Kat {n}.</p>" + (links([chain[n]]) if n < len(chain) else "") + links(["/merkez/"]))
              for n, path in enumerate(chain, 1)}
    routes["/merkez/"] = page(f"<h1>Merkez</h1>{LONG}")
    routes["/"] = page(f"<h1>Ana</h1>{LONG}" + links([chain[0], "/merkez/"]))
    outcome = audit(routes, sitemap=[])
    idx7 = outcome.by_id["IDX-7"]
    [deep] = [f for f in idx7.findings if "clicks from the homepage" in f.title]
    assert deep.title == "2 page(s) are 5+ clicks from the homepage" and deep.severity.value == "Info"
    assert [(row["url"].removeprefix(outcome.base), row["depth"]) for row in deep.evidence["pages"]] == [("/k6/", 6), ("/k5/", 5)]
    [graph] = [o for o in idx7.observations if "most_linked" in o]
    top = graph["most_linked"][0]
    assert (top["url"].removeprefix(outcome.base), top["inbound_links"], top["click_depth"]) == ("/merkez/", 7, 1)
    assert graph["least_linked"][0]["inbound_links"] == 1
    assert graph["pages_by_click_depth"] == {"0": 1, "1": 2, "2": 1, "3": 1, "4": 1, "5": 1, "6": 1}
    rows = {row["url"].removeprefix(outcome.base): row for row in idx7.evidence["link_graph"]["pages"]}
    assert rows["/k3/"] == {"url": outcome.base + "/k3/", "click_depth": 3, "inbound_links": 1}
    markdown = render_markdown(outcome.result, outcome.gates, outcome.checks)
    assert "## Internal links" in markdown and "| `/merkez/` | 7 | 1 |" in markdown and "**Least linked pages**" in markdown


# c. Anchor text ---------------------------------------------------------------------------------------
@pytest.mark.parametrize("text, phrase", [
    ("Devamı", "devamı"), ("Devamını Oku »", "devamını oku"), ("BURAYA TIKLAYIN", "buraya tıklayın"), ("Tıklayın!", "tıklayın"),
    ("Detaylar →", "detaylar"), ("Click here", "click here"), ("Read more...", "read more"), ("İNCELE", "incele"),
    ("Şizofreni tedavisi", None), ("Devamı: şizofreni tedavisi", None), ("Detaylı bilgi için bölüm sayfası", None), ("", None)])
def test_generic_anchor(text, phrase):
    assert generic_anchor(text) == phrase


def test_every_anchor_text_for_a_target_is_kept_and_a_link_without_any_name_is_counted():
    html = ('<nav><a href="/a">Ana</a></nav><a href="/a">Hizmetler</a><a href="/a"></a>'
            '<a href="/b"><img src="x.png" alt="Logo"></a><a href="/c"><img src="y.png"></a><a href="/c">  </a>'
            '<a href="/d" aria-label="Kapat"><svg></svg></a><a href="/e" title="İletişim"><i class="icon"></i></a>')
    edges = {edge["target"].removeprefix("http://s"): edge for edge in extract_link_edges(html, "http://s/")}
    assert edges["/a"] == {"target": "http://s/a", "anchor": "Ana", "anchors": ["Ana", "Hizmetler"], "links": 3, "empty": 1, "nav": True,
                           "href": "/a",  # DECISIONS 337: the first link's address as written
                           "hrefs": ["/a"], "where": None, "anchor_counts":{'Ana':1,'Hizmetler':1,'':1}}  # distinct texts and DOM occurrences remain separate
    assert edges["/b"]["anchors"] == ["Logo"] and edges["/b"]["empty"] == 0          # named by the image's alt
    assert edges["/c"] == {"target": "http://s/c", "anchor": "", "anchors": [], "links": 2, "empty": 2, "href": "/c", "hrefs": ["/c"], "where": None, "anchor_counts":{'':2}}
    assert edges["/d"]["anchors"] == ["Kapat"] and edges["/e"]["anchors"] == ["İletişim"]
    many = "".join(f'<a href="/x">metin {n}</a>' for n in range(30))
    [edge] = extract_link_edges(many, "http://s/", max_anchors=4)
    assert edge["anchors"] == ["metin 0", "metin 1", "metin 2", "metin 3"] and edge["links"] == 30


def test_str14_reports_generic_and_empty_anchor_text_but_not_a_card_whose_title_names_the_target():
    targets = ["/sizofreni/", "/kaygi/", "/uyku/", "/depresyon/", "/bagimlilik/", "/logo-hedef/", "/ikon/"]
    body = (f"<h1>Bölümler</h1>{LONG}"
            '<a href="/sizofreni/">Devamı »</a>'                                             # generic only
            '<a href="/kaygi/">Buraya tıklayın</a>'                                           # generic only
            '<a href="/uyku/">Read more</a><a href="/uyku/">Detaylar</a>'                      # two generic texts
            '<h3><a href="/depresyon/">Depresyon tedavisi</a></h3><a href="/depresyon/">Devamı</a>'  # the title names it
            '<a href="/bagimlilik/"></a>'                                                     # nothing at all
            '<a href="/logo-hedef/"><img src="/l.png" alt="Bağımlılık merkezi"></a>'             # named by its image
            '<a href="/ikon/" aria-label="Uyku laboratuvarı"><i class="i"></i></a>')            # named by its label
    routes = {path: page(f"<h1>{path}</h1>{LONG}<p>{path} sayfası.</p>") for path in targets}
    routes["/bolumler/"] = page(body)
    outcome = audit(routes, image_checks_max=0)
    check = outcome.by_id["STR-14"]
    generic = next(f for f in check.findings if "generic text" in f.title)
    empty = next(f for f in check.findings if "no text at all" in f.title)
    assert generic.severity.value == "S4" and generic.confidence.value == "verified"
    assert sorted(row["target"].removeprefix(outcome.base) for row in generic.evidence["links"]) == ["/kaygi/", "/sizofreni/", "/uyku/"]
    assert generic.evidence["phrases"] == {"devamı": 1, "buraya tıklayın": 1, "read more": 1, "detaylar": 1}
    assert short(outcome, generic.scope["urls"]) == ["/bolumler/"]
    assert [row["target"].removeprefix(outcome.base) for row in empty.evidence["links"]] == ["/bagimlilik/"]
    [counts] = check.observations
    assert counts["links_with_generic_text_only"] == 4 and counts["links_with_no_text"] == 1


def test_str14_passes_a_site_with_descriptive_links():
    outcome = audit({"/tr/a/": page(f"<h1>A</h1>{LONG}"), "/tr/b/": page(f"<h1>B</h1>{LONG}<p>B.</p>")})
    assert outcome.by_id["STR-14"].status in ("pass", "partial") and not outcome.by_id["STR-14"].findings


# d. Images --------------------------------------------------------------------------------------------
PNG = Response(body="\x89PNG....", content_type="image/png")


def image_site():
    def photos(prefix, n, extension):
        return "".join(f'<img src="/img/{prefix}-{i}.{extension}" alt="Fotoğraf {i}" width="400" height="300">' for i in range(n))

    routes = {
        "/galeri/": page(f"<h1>Galeri</h1>{LONG}" + photos("g", 6, "jpg")
                         + '<img src="/img/kayip.jpg" alt="Kayıp" width="400" height="300">'
                         + '<img src="/img/hata.png" alt="Hata sayfası" width="400" height="300">'
                         + '<img src="https://cdn.another.example/x.jpg" alt="Başka site" width="400" height="300">'
                         + '<figure><img src="/img/alt-yok-1.jpg" width="400" height="300"><figcaption>Grafik: Aylık talep</figcaption></figure>'),
        "/ekip/": page(f"<h1>Ekip</h1>{LONG}<p>Ekip.</p>" + photos("e", 5, "png")
                       + '<picture><source srcset="/img/yeni.avif" type="image/avif"><img src="/img/yeni.jpg" alt="Yeni" width="400" height="300"></picture>'
                       + '<figure><img src="/img/alt-yok-2.jpg" width="400" height="300"><figcaption>Grafik: Aylık talep</figcaption></figure>',
                       nav='<a href="/">Ana</a><img src="/img/logo.png">'),
    }
    for name in [f"g-{i}.jpg" for i in range(6)] + [f"e-{i}.png" for i in range(5)] + ["yeni.jpg", "alt-yok-1.jpg", "alt-yok-2.jpg", "logo.png"]:
        routes[f"/img/{name}"] = PNG
    routes["/img/hata.png"] = Response(body="<html><body>Bulunamadı</body></html>")   # a 200 that is not an image
    return routes                                                                    # /img/kayip.jpg is not served: 404


@pytest.fixture(scope="module")
def images():
    return audit(image_site())


def test_str7_reports_missing_alt_on_every_page_not_only_the_logo(images):
    missing = next(f for f in images.by_id["STR-7"].findings if "likely meaningful" in f.title)
    assert short(images, missing.scope["urls"]) == ["/ekip/", "/galeri/"]
    assert sorted(row["src"] for row in missing.evidence["images"]) == ["/img/alt-yok-1.jpg", "/img/alt-yok-2.jpg"]
    assert "logo" not in str(missing.evidence) and "header, navigation and footer" in images.by_id["STR-7"].evidence["scope"]


def test_str7_reports_image_files_that_do_not_load(images):
    check = images.by_id["STR-7"]
    broken = next(f for f in check.findings if "do not load" in f.title)
    assert broken.severity.value == "S3" and broken.confidence.value == "verified"
    problems = {row["image"].removeprefix(images.base): row["problem"] for row in broken.evidence["images"]}
    assert problems == {"/img/kayip.jpg": "HTTP 404", "/img/hata.png": "answers with text/html, not an image"}
    assert short(images, broken.scope["urls"]) == ["/galeri/"]
    # An image on another site is not requested unless external link checks are on, and the report says so.
    assert check.evidence["image_files_requested"] == 16 and check.evidence["distinct_content_images"] == 17
    assert list(check.evidence["image_files_not_requested"].values()) == [1]
    assert any(part["part"] == "image files not requested" for part in check.coverage["not_assessed"])
    requests = [r for r in images.result.requests if r.purpose == "image_status"]
    assert len(requests) == 16 and not any("another.example" in r.url for r in requests)


def test_str7_reports_the_share_of_images_in_webp_or_avif_as_info(images):
    check = images.by_id["STR-7"]
    formats = next(f for f in check.findings if "WebP or AVIF" in f.title)
    assert formats.severity.value == "Info" and formats.title == "1 of 17 image occurrence(s) reference WebP or AVIF in markup; delivery assessed separately"
    assessment = formats.evidence['format_assessment']
    assert assessment['markup_modern_occurrences'] == 1  # AVIF picture reference, not observed delivery
    share = next(o for o in check.observations if "format references" in o["metric"])
    assert (share['occurrences'], share['markup_modern_occurrences']) == (17, 1)
    assert assessment['response_resources_assessed'] <= 16



def test_the_image_sample_is_capped_and_spread_over_the_pages():
    outcome = audit(image_site(), image_checks_max=4)
    check = outcome.by_id["STR-7"]
    requested = [r.url.removeprefix(outcome.base) for r in outcome.result.requests if r.purpose == "image_status"]
    assert len(requested) == 4 and {path.split("-")[0] for path in requested} == {"/img/g", "/img/e"}  # two from each page
    [beyond] = [part for part in check.coverage["not_assessed"] if part["part"] == "image files beyond the sample"]
    assert beyond["count"] == 13


def test_image_formats_reads_addresses_srcsets_and_types():
    assert image_formats("/a.webp 1x, /a@2x.WEBP 2x") == ["webp", "webp"] and image_formats("/a.jpeg?v=3") == ["jpg"]
    assert image_formats("/photo", "image/avif") == ["avif"] and image_formats("/a.webpage") == []
    html = '<main><img srcset="/a.webp 1x" src="/a.png"><img data-src="/b.jpg" src="data:image/gif;base64,AA"></main>'
    assert [img["formats"] for img in analyze_html(html)["images"]] == [["png", "webp"], ["jpg"]]


# e. Thin content ----------------------------------------------------------------------------------------
def test_str15_reports_short_content_pages_but_not_contact_or_legal_pages():
    short_text = "<p>Bu hizmet hakkında yakında daha fazla bilgi eklenecek.</p>"
    routes = {
        "/hizmetler/emdr/": page("<h1>EMDR</h1>" + short_text),
        "/hizmetler/terapi/": page(f"<h1>Terapi</h1>{LONG}"),
        "/iletisim/": page("<h1>İletişim</h1><p>Adres: Örnek Sokak 5. Telefon: 0212 000 00 00.</p>"),
        "/belge/": page("<h1>Belge</h1><p>Kısa bir açıklama.</p>", title="Gizlilik Politikası"),
        "/blog/?sayfa=2": page("<h1>Blog</h1><p>İkinci sayfa.</p>"),
    }
    outcome = audit(routes, image_checks_max=0)
    check = outcome.by_id["STR-15"]
    [finding] = check.findings
    assert finding.severity.value == "Info" and finding.title == "1 content page(s) have fewer than 150 words of their own text"
    [row] = finding.evidence["pages"]
    assert row["url"].removeprefix(outcome.base) == "/hizmetler/emdr/" and row["main_content_words"] < 20
    assert check.evidence["short_pages_left_out"] == {"contact, legal, account or cart page": 2, "page 2, 3, ... of a list": 1, "homepage": 1}
    words = {row["url"].removeprefix(outcome.base): row["main_content_words"] for row in check.evidence["pages"]}
    assert words["/hizmetler/terapi/"] > 150 and set(words) == {"/", *routes}
    [stats] = check.observations
    assert stats["pages"] == 6 and stats["below_150_words"] == 5 and stats["longest"] == words["/hizmetler/terapi/"]


# f. Caps on stored links --------------------------------------------------------------------------------
def test_the_cap_on_stored_links_is_configurable_and_does_not_limit_the_crawl():
    paths = [f"/s{n}/" for n in range(1, 13)]
    routes = {path: page(f"<h1>{path}</h1>{LONG}<p>{path}.</p>") for path in paths}
    routes["/"] = page(f"<h1>Ana</h1>{LONG}" + links(paths)
                       + "".join(f'<a href="https://other{n}.example/">dış {n}</a>' for n in range(6)))
    outcome = audit(routes, sitemap=[], max_outlinks_per_page=5, max_external_links_per_page=2, image_checks_max=0)
    home = next(p for p in outcome.result.pages if p.url == outcome.base + "/")
    assert len(home.outlinks) == 5 and len(home.external_links) == 2 and home.links_found >= 18
    assert len(outcome.result.pages) == 13  # every link was followed, whatever the report keeps
    config = outcome.result.config
    assert (config["max_outlinks_per_page"], config["max_external_links_per_page"], config["max_anchor_texts_per_target"]) == (5, 2, 20)
    default = audit({"/a/": page(f"<h1>A</h1>{LONG}")}).result.config
    assert (default["max_outlinks_per_page"], default["max_external_links_per_page"]) == (1000, 300)
