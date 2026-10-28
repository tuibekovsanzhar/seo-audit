"""W2 rule regressions (review appendix B): hreflang beyond its shape (H23/B04), generic anchors, thin-content
exemptions and Turkish heuristics (H24/B07-B10), listings are not product pages (H27), required structured-data fields
(H31/B11), and the smaller wording and status fixes (B18, B19, B23, B24, STR-14 accessible names)."""

from __future__ import annotations

import pytest

from maya_audit.checks.structure import str9_language
from maya_audit.language import hreflang_code_problem
from maya_audit.structure_data import StructureData
from test_false_alarms import CFG, ROOT, TR, html, ld, site

LONG = " ".join([TR] * 6)


def hreflang(*pairs):
    return "".join(f'<link rel="alternate" hreflang="{code}" href="{ROOT}{href}">' for code, href in pairs)


def str9(pages_html):
    result, pages = site(pages_html)
    data = StructureData()
    for page in pages:   # every page is crawled, so the link check entry of a target is the crawl's own
        data.links[page.url] = {"source": "crawl", "status": 200, "hreflang": page.analysis["hreflang"]}
    return str9_language(result, CFG, pages, set(), data)


def titled(check, words):
    return [f for f in check.findings if words in f.title]


# -- H23 / B04 -------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("code", ["tr", "en-GB", "en-gb", "zh-Hant", "zh-Hant-TW", "es-419", "x-default", "fil-PH"])
def test_usable_hreflang_codes_pass(code):
    assert hreflang_code_problem(code) is None


@pytest.mark.parametrize("code, why", [("en-UK", "use GB"), ("eng-USA", "region of 2 letters"), ("zz-ZZ", "private"),
                                       ("tr-ZZ", "private"), ("english", "language of 2-3 letters"), ("en_GB", "not a")])
def test_wrong_hreflang_codes_say_why(code, why):
    assert why in hreflang_code_problem(code)


def test_en_uk_is_reported_with_the_right_region():
    pairs = (("tr", "/"), ("en-UK", "/en/"), ("x-default", "/"))
    check = str9({"/": html(f"<p>{LONG}</p>", head=hreflang(*pairs)),
                  "/en/": html(f"<p>{LONG}</p>", head=hreflang(*pairs))})
    [finding] = titled(check, "malformed hreflang codes")
    assert finding.severity.value == "Info" and "use GB" in str(finding.evidence)


def test_the_same_code_for_two_urls_is_s4():
    pairs = (("tr", "/"), ("tr", "/tr/"), ("x-default", "/"))
    check = str9({"/": html(f"<p>{LONG}</p>", head=hreflang(*pairs)),
                  "/tr/": html(f"<p>{LONG}</p>", head=hreflang(*pairs))})
    [finding] = titled(check, "same hreflang code")
    assert finding.severity.value == "S4" and finding.evidence["items"][0]["targets"] == [ROOT + "/", ROOT + "/tr/"]


@pytest.mark.parametrize("target_html, problem", [
    (html(f"<p>{LONG}</p>", title=""), "empty <title>"),
    (html(f"<p>{LONG}</p>", head='<meta name="robots" content="noindex">'), "noindex"),
    (html(f"<p>{LONG}</p>", head=f'<link rel="canonical" href="{ROOT}/">'), "canonical points to"),
])
def test_a_target_that_cannot_stand_for_its_language_is_s4(target_html, problem):
    pairs = (("tr", "/"), ("en", "/en/"), ("x-default", "/"))
    target_html = target_html.replace("</head>", hreflang(*pairs) + "</head>")
    check = str9({"/": html(f"<p>{LONG}</p>", head=hreflang(*pairs)), "/en/": target_html})
    [finding] = titled(check, "hreflang target page(s)")
    assert finding.severity.value == "S4" and ROOT + "/en/" in finding.scope["urls"]
    assert any(problem in p for row in finding.evidence["links"] for p in row["problems"])


def test_a_good_cluster_has_no_target_or_cluster_finding():
    pairs = (("tr", "/"), ("en", "/en/"), ("x-default", "/"))
    desc = '<meta name="description" content="Açıklama">'
    check = str9({"/": html(f"<p>{LONG}</p>", head=hreflang(*pairs) + desc),
                  "/en/": html(f"<p>{LONG}</p>", head=hreflang(*pairs) + desc)})
    assert not titled(check, "hreflang target page(s)") and not titled(check, "lack x-default")


def test_a_cluster_without_x_default_or_self_is_info():
    check = str9({"/": html(f"<p>{LONG}</p>", head=hreflang(("en", "/en/"))),
                  "/en/": html(f"<p>{LONG}</p>", head=hreflang(("tr", "/"), ("en", "/en/")))})
    [finding] = titled(check, "lack x-default")
    assert finding.severity.value == "Info"
    rows = {r["url"]: r["missing"] for r in finding.evidence["items"]}
    assert rows[ROOT + "/"] == ["x-default", "a link to this page itself"] and rows[ROOT + "/en/"] == ["x-default"]


def test_a_target_that_was_not_crawled_is_not_read_never_fine():
    result, pages = site({"/": html(f"<p>{LONG}</p>", head=hreflang(("tr", "/"), ("en", "/en/")))})
    data = StructureData()
    data.links[ROOT + "/en/"] = {"source": "fetched", "status": 200, "hreflang": [{"hreflang": "tr", "href": ROOT + "/"}]}
    check = str9_language(result, CFG, pages, set(), data)
    assert not titled(check, "hreflang target page(s)")
    assert check.evidence["hreflang_target_pages_not_read_count"] == 1


# -- H31 / B11 -------------------------------------------------------------------------------------------------------
def str3(head, started_at=None):
    from maya_audit.checks.structure import str3_structured_data
    result, pages = site({"/": html(f"<h1>Ana</h1><p>{TR}</p>"), "/v/": html(f"<h1>Video</h1><p>{TR}</p>", head=head)})
    result.started_at = started_at
    return str3_structured_data(result, CFG, pages, set())


def video(**fields):
    return ld({"@type": "VideoObject", **fields})


def test_a_video_named_video_and_dated_the_audit_day_is_reported():
    check = str3(video(name="Video", thumbnailUrl=ROOT + "/p.jpg", uploadDate="2026-10-21T08:00:00+00:00"),
                 started_at="2026-10-21T09:30:00+00:00")
    [finding] = [f for f in check.findings if "VideoObject" in f.title]
    assert finding.severity.value == "Info" and "uploadDate" in str(finding.evidence)
    assert len(finding.evidence["items"][0]["why"]) == 2


def test_a_real_video_is_not_a_placeholder():
    check = str3(video(name="Difüzör nasıl kullanılır", thumbnailUrl=ROOT + "/p.jpg", uploadDate="2025-03-01"),
                 started_at="2026-10-21T09:30:00+00:00")
    assert not [f for f in check.findings if "VideoObject" in f.title or "required" in f.title]


@pytest.mark.parametrize("node, missing", [
    ({"@type": "VideoObject", "name": "Tanıtım"}, ["thumbnailUrl", "uploadDate"]),
    ({"@type": "Restaurant", "name": "Kafe"}, ["address"]),
    ({"@type": "Event", "name": "Konser", "startDate": "2026-11-01"}, ["location"]),
    ({"@type": "Recipe", "name": "Kek"}, ["image"]),
    ({"@type": "JobPosting", "title": "Garson", "description": "x", "datePosted": "2026-10-01",
      "hiringOrganization": {"@type": "Organization", "name": "Kafe"}},
     ["jobLocation (or applicantLocationRequirements for a remote job)"]),
])
def test_more_types_have_their_required_properties_checked(node, missing):
    [finding] = [f for f in str3(ld(node)).findings if "required" in f.title]
    assert finding.evidence["items"][0]["missing"] == missing


def test_the_faq_note_gives_the_2023_restriction_not_a_2025_end():
    from maya_audit.checks import structure
    source = open(structure.__file__, encoding="utf-8").read()
    assert "Since August 2023 Google shows FAQ rich results only for authoritative government and health" in source
    assert "FAQ rich results in 2025" not in source


# -- H24 / B07-B10 ---------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("anchor, phrase", [("CLICK HERE", "click here"), ("Click Here »", "click here"),
                                            ("click here", "click here"), ("Devamını Oku »", "devamını oku")])
def test_generic_anchors_match_in_any_case(anchor, phrase):
    from maya_audit.checks.content_quality import generic_anchor
    assert generic_anchor(anchor) == phrase


def short(url, title="Sayfa"):
    from types import SimpleNamespace
    return SimpleNamespace(url=ROOT + url, analysis={"title": title})


@pytest.mark.parametrize("url", ["/research/ai-study", "/girisimcilik/", "/blog/odeme-yontemleri-rehberi",
                                 "/urun/sepetli-bisiklet", "/urun-4041", "/uyelik-avantajlari"])
def test_a_word_inside_a_longer_word_or_an_article_does_not_exempt_a_short_page(url):
    from maya_audit.checks.content_quality import thin_exempt
    assert thin_exempt(short(url)) is None


@pytest.mark.parametrize("url, title", [("/odeme", "Sayfa"), ("/sepet/", "Sayfa"), ("/iletisim-bilgileri", "Sayfa"),
                                        ("/p/12", "PRIVACY POLICY"), ("/bize-ulasin", "Sayfa"), ("/x", "Giriş Yap")])
def test_a_contact_legal_or_cart_page_is_still_exempt(url, title):
    from maya_audit.checks.content_quality import thin_exempt
    assert thin_exempt(short(url, title))


def test_a_short_page_built_around_a_form_is_left_out_of_thin_content():
    from maya_audit.checks.content_quality import str15_thin_content
    form = '<form><input name="ad"><button type="submit">Gönder</button></form>'
    result, pages = site({"/": html(f"<p>{LONG}</p>"), "/teklif-al/": html(f"<p>Kısa bir metin.</p>{form}"),
                          "/a/": html(f"<p>{LONG}</p>"), "/b/": html(f"<p>{LONG}</p>")})
    check = str15_thin_content(result, CFG, pages, set(), set())
    assert check.evidence["short_pages_left_out"].get("page with a form") == 1
    assert not [f for f in check.findings if ROOT + "/teklif-al/" in f.scope["urls"]]


def test_a_form_on_every_page_exempts_no_short_page():
    from maya_audit.checks.content_quality import str15_thin_content
    form = '<form><input name="eposta"><button type="submit">Abone ol</button></form>'
    result, pages = site({"/": html(f"<p>{LONG}</p>", footer=form), "/kisa/": html("<p>Kısa bir metin.</p>", footer=form),
                          "/a/": html(f"<p>{LONG}</p>", footer=form)})
    check = str15_thin_content(result, CFG, pages, set(), set())
    assert "page with a form" not in check.evidence["short_pages_left_out"]
    assert [f for f in check.findings if ROOT + "/kisa/" in f.scope["urls"]]


@pytest.mark.parametrize("title", ["Anasayfa", "Ana Sayfa", "Başlıksız", "BAŞLIKSIZ"])
def test_turkish_placeholder_titles_are_generic(title):
    from maya_audit.checks.structure import str1_titles
    result, pages = site({"/": html(f"<p>{LONG}</p>", title="Örnekmağaza | Ev"), "/a/": html(f"<p>{LONG}</p>", title=title)})
    findings = str1_titles(result, CFG, pages, set()).findings
    assert any(ROOT + "/a/" in str(f.evidence) and "generic" in str(f.evidence) for f in findings)


def test_turkish_dates_and_labels_are_read():
    from maya_audit.analysis import analyze_html
    from maya_audit.checks.structure import visible_dates
    page = html("<p>Yayın tarihi: 3 Mart 2026 · Son güncelleme 12 Ekim 2026</p><p>Published March 3, 2026</p>"
                "<p>MAYIS: 5 MAYIS 2025, 1 Şubat 2024, 9 Aralik 2023</p>")
    found = {d["date"].isoformat(): d["kind"] for d in visible_dates(analyze_html(page, ROOT + "/"))}
    assert found["2026-03-03"] == "published" and found["2026-10-12"] == "modified"
    assert {"2025-05-05", "2024-02-01", "2023-12-09"} <= set(found)


@pytest.mark.parametrize("path", ["/menumuz/", "/urunlerimiz/", "/sube/"])
def test_basic_page_stems_take_a_turkish_suffix(path):
    from maya_audit.checks.small_site import basic_pages_found
    _, pages = site({"/": html(f"<p>{LONG}</p>"), path: html(f"<p>{LONG}</p>")})
    assert ROOT + path in [u for urls in basic_pages_found(pages).values() for u in urls]


def test_capital_dotted_i_counts_as_turkish():
    from maya_audit.language import detect_language
    text = " ".join(["BU İŞ İÇİN DE BİR ŞEY VAR VE BİZ İLE ÇOK DAHA İYİ OLDU"] * 8)
    guess = detect_language(text, min_words=20)
    assert guess["language"] == "tr" and guess["hits"]["tr"] >= 40


# -- H27 -------------------------------------------------------------------------------------------------------------
def offer_page(price, extra="", head=""):
    return html(f"<h1>Ürün</h1><p>{TR}</p><p>Fiyat: {price}</p>{extra}", head=head)


def maybe_urls(pages_html):
    from maya_audit.checks.structure import product_template
    result, pages = site(pages_html)
    found = product_template(pages, ROOT + "/")
    return {row["url"].removeprefix(ROOT) for row in found["maybe"]}, set(found["listings"])


def test_a_page_with_one_price_and_no_buy_button_is_still_a_maybe():
    maybe, listings = maybe_urls({"/": html(f"<p>{LONG}</p>"), "/hizmet-paketi/": offer_page("1.250 TL")})
    assert maybe == {"/hizmet-paketi/"} and not listings


def test_a_category_listing_with_item_list_markup_is_not_a_maybe_product():
    item_list = ld({"@type": "ItemList", "itemListElement": [{"@type": "ListItem", "position": 1, "url": ROOT + "/a/"}]})
    maybe, listings = maybe_urls({"/": html(f"<p>{LONG}</p>"), "/kokular/": offer_page("1.250 TL", head=item_list)})
    assert maybe == set() and listings == {ROOT + "/kokular/"}


def test_a_page_linking_to_several_priced_pages_is_a_listing():
    cards = "".join(f'<a href="/u{i}/">Ürün {i}</a>' for i in range(4))
    pages = {"/": html(f"<p>{LONG}</p>"), "/liste/": offer_page("1.250 TL", extra=cards)}
    pages.update({f"/u{i}/": offer_page(f"{100 + i} TL") for i in range(4)})
    maybe, listings = maybe_urls(pages)
    assert "/liste/" not in maybe and ROOT + "/liste/" in listings and "/u1/" in maybe


# -- B18 -------------------------------------------------------------------------------------------------------------
def test_no_news_or_job_page_is_not_applicable_not_a_pass():
    from maya_audit.checks.small_site import str22_news_link_lists, str23_job_postings
    result, pages = site({"/": html(f"<p>{LONG}</p>"), "/menu/": html(f"<p>{LONG}</p>")})
    assert str22_news_link_lists(result, CFG, pages, set()).status == "not_applicable"
    assert str23_job_postings(result, CFG, pages, set()).status == "not_applicable"


# -- B19 -------------------------------------------------------------------------------------------------------------
def test_a_first_heading_of_h3_is_a_skipped_level():
    from maya_audit.analysis import analyze_html
    counts = analyze_html(html("<h3>Başlık</h3><h4>Alt</h4><h2>İki</h2><h4>Dört</h4>"), ROOT + "/")["heading_counts"]
    jumps = [(j["from"], j["to"]) for j in counts["skipped_level_jumps"]]
    assert jumps[:1] == [(1, 3)] and counts["skipped_level_jumps"][0]["first_heading"] and (2, 4) in jumps


def test_a_title_with_combining_accents_is_counted_as_read():
    from maya_audit.technical_seo import run_traditional_seo_quality_check
    decomposed = "é" * 31   # 31 letters a reader sees, 62 code points before NFC
    result, pages = site({"/": html(f"<p>{LONG}</p>", title=decomposed)})
    check = run_traditional_seo_quality_check(result, pages, set(), set())
    assert len(decomposed) == 62 and not [f for f in check.findings if "above" in f.title.lower() and "title" in f.title.lower()]
    assert [f for f in run_traditional_seo_quality_check(*site({"/": html(f"<p>{LONG}</p>", title="e" * 62)}), set(), set()).findings
            if "title" in f.title.lower()]


# -- B23 / B24 / STR-14 accessible names -----------------------------------------------------------------------------
def test_the_auto_stamp_title_says_within_a_day():
    from maya_audit.checks import structure
    source = open(structure.__file__, encoding="utf-8").read()
    assert "a date within ±1 day of the audit" in source


@pytest.mark.parametrize("link, named", [
    ('<a href="/b/" aria-label="Sepet"><i class="icon"></i></a>', True),
    ('<span id="l1">Sepet</span><a href="/b/" aria-labelledby="l1"><i class="icon"></i></a>', True),
    ('<a href="/b/" title="Sepet"><i class="icon"></i></a>', True),
    ('<a href="/b/"><img src="/s.png" alt="Sepet"></a>', True),
    ('<a href="/b/"><i class="icon"></i></a>', False),
])
def test_a_link_named_by_aria_title_or_image_alt_is_not_nameless(link, named):
    from maya_audit.checks.content_quality import str14_anchor_text
    result, pages = site({"/": html(f"<p>{LONG}</p>{link}"), "/b/": html(f"<p>{LONG}</p>")})
    nameless = [f for f in str14_anchor_text(result, CFG, pages, set()).findings if "no text" in f.title]
    assert bool(nameless) is not named


def test_one_named_block_is_one_finding_whatever_pages_it_is_on():
    from maya_audit.checks.content_quality import str14_anchor_text
    def block(i):   # the same "related posts" block; which posts it lists differs from page to page
        links = ['<a href="/y/"><i></i></a>'] + (['<a href="/x0/"><i></i></a>'] if i < 6 else [])
        return '<div class="post-related">' + "".join(links + (['<a href="/x1/"><i></i></a>'] if i >= 2 else [])) + "</div>"
    pages_html = {"/": html(f"<p>{LONG}</p>")}
    pages_html.update({f"/p{i}/": html(f"<p>{LONG} {i}</p>" + block(i)) for i in range(8)})
    result, pages = site(pages_html)
    findings = [f for f in str14_anchor_text(result, CFG, pages, set()).findings if "post-related" in f.title]
    assert len(findings) == 1, [f.title for f in findings]


def test_an_unread_hreflang_target_keeps_str9_from_a_clean_pass():
    from maya_audit.coverage import settle
    pairs = (("tr", "/"), ("en", "https://other.example/en/"), ("x-default", "/"))
    head = "".join(f'<link rel="alternate" hreflang="{c}" href="{h if h.startswith("http") else ROOT + h}">' for c, h in pairs)
    result, pages = site({"/": html(f"<p>{LONG}</p>", head=head)})
    data = StructureData()
    data.links["https://other.example/en/"] = {"source": "fetched", "status": 200,
                                                "hreflang": [{"hreflang": "tr", "href": ROOT + "/"}]}
    check = str9_language(result, CFG, pages, set(), data)
    settle(check)
    assert check.status != "pass" and "not read" in check.summary


def test_the_new_auto_stamp_title_reads_in_turkish():
    from maya_audit_web import wording
    text, translated = wording.title("STR-6", "Last-Modified header looks auto-stamped: 4 of 4 pages carry a date within ±1 day of the audit", "tr")
    assert translated and "bir gün" in text
