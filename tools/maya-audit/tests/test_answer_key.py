"""Issues from Maya's own audit of a live hospital site (25 Sep - 2 Oct 2026) that the tool missed.

Each test rebuilds the page shape that carried the issue. Offline: fake server only.
"""

import json

import pytest

from fakeserver import FakeServer, Response, Site
from maya_audit.analysis import template_markers
from maya_audit.audit import run_audit
from maya_audit.checks.index import soft_404_verdict, tracking_parameters
from maya_audit.config import CrawlConfig
from maya_audit.report import render_markdown
from test_deadline_hosted_hardening import QUIET
from test_review_fixes import TR, audit, links, page, short

BLOG_OK = {"@context": "https://schema.org", "@type": "BlogPosting", "headline": "Çocuklarda Dikkat Eksikliği",
           "datePublished": "2026-07-05", "author": {"@type": "Person", "name": "Uzm. Psk. Ayşe Yılmaz"}}
BLOG_TEMPLATE = {"@context": "https://schema.org", "@type": "BlogPosting", "headline": "Çocuklarda Dikkat Eksikliği",
                 "datePublished": "{{publishDate}}", "image": "{{featured_image}}",
                 "author": {"@type": "Person", "name": "{{author_name}}", "jobTitle": "{{author_role}}"},
                 "reviewedBy": {"@type": "Person", "name": "{{reviewer_name}}"}}


def ld(data):
    return '<script type="application/ld+json">' + json.dumps(data, ensure_ascii=False) + "</script>"


# 2. Template markers --------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def template_site():
    routes = {
        # A second BlogPosting block and article:published_time, both still holding the template's slots.
        "/tr/cocuklarda-dikkat-eksikligi-belirtileri/": page(
            f"<h1>Çocuklarda Dikkat Eksikliği Belirtileri</h1><p>{TR}</p>",
            head=ld(BLOG_OK) + ld(BLOG_TEMPLATE) + '<meta property="article:published_time" content="{{publishDate}}">'
                 '<meta name="author" content="{{author_name}}">'),
        # A draft marker left in the FAQ answers.
        "/tr/cocuklarda-enkoprezis-diski-kacirma-nedir/": page(
            f"<h1>Enkoprezis</h1><p>{TR}</p><h2>Sık sorulan sorular</h2><p>Tedavi genellikle 6 ay sürer ‹teyit› ve "
            "düzenli takip gerekir.</p><p>Görülme sıklığı yüzde 1-3 arasındadır ‹teyit›.</p>"),
        # An image and a link whose address is a slot nobody filled.
        "/tr/beyin-ve-sinir-cerrahisi-hangi-hastaliklara-bakar/": page(
            f'<h1>Beyin ve Sinir Cerrahisi</h1><p>{TR}</p><img src="https://withmaya.ai/app/%7Binline_image_1%7D" '
            'alt="Karşılaştırma tablosu"><a href="https://withmaya.ai/app/{cta_link}">Randevu al</a>'),
        "/tr/baslik/": page(f"<h1>Başlık</h1><p>{TR}</p>", title="{{page_title}} - Hastane"),
        # Things that look similar and are fine.
        "/tr/temiz/": page(f"<h1>Temiz</h1><p>{TR}</p><p>Kaynak [[1]] ve fiyat {{}} değil; ‹ Önceki | Sonraki › "
                           "bağlantıları ve «alıntı» işaretleri sorun değildir. function() { return 1 }</p>",
                           head=ld(BLOG_OK)),
    }
    return audit(routes)


def found(outcome, where):
    finding = next((f for f in outcome.by_id["STR-13"].findings if f.evidence["where"] == where), None)
    return finding, [] if finding is None else [(row["url"].removeprefix(outcome.base), row["marker"], row["field"])
                                                for row in finding.evidence["found"]]


def test_str13_unfilled_slots_in_json_ld_are_reported_with_the_marker_and_the_field(template_site):
    finding, rows = found(template_site, "JSON-LD")
    page_ = "/tr/cocuklarda-dikkat-eksikligi-belirtileri/"
    assert sorted(rows) == sorted([
        (page_, "{{publishDate}}", "BlogPosting.datePublished"), (page_, "{{featured_image}}", "BlogPosting.image"),
        (page_, "{{author_name}}", "BlogPosting.author.name"), (page_, "{{author_role}}", "BlogPosting.author.jobTitle"),
        (page_, "{{reviewer_name}}", "BlogPosting.reviewedBy.name")])
    assert finding.severity.value == "S2" and finding.confidence.value == "verified"
    assert "{{publishDate}}" in finding.title and finding.evidence["found"][0]["sample"]


def test_str13_unfilled_slots_in_meta_tags_and_the_title(template_site):
    finding, rows = found(template_site, "meta tag")
    assert sorted(rows) == [("/tr/cocuklarda-dikkat-eksikligi-belirtileri/", "{{author_name}}", 'name="author"'),
                            ("/tr/cocuklarda-dikkat-eksikligi-belirtileri/", "{{publishDate}}", 'property="article:published_time"')]
    assert finding.severity.value == "S2"
    finding, rows = found(template_site, "title")
    assert rows == [("/tr/baslik/", "{{page_title}}", "<title>")] and "in the title" in finding.title


def test_str13_a_draft_marker_in_visible_text(template_site):
    finding, rows = found(template_site, "visible text")
    assert rows == [("/tr/cocuklarda-enkoprezis-diski-kacirma-nedir/", "‹teyit›", None)]
    assert finding.severity.value == "S3"
    assert finding.evidence["found"][0]["sample"].startswith("Tedavi genellikle 6 ay sürer ‹teyit›")
    assert "browser" in " ".join(finding.notes)


def test_str13_an_unresolved_slot_in_an_image_or_link_address(template_site):
    finding, rows = found(template_site, "link or image URL")
    assert sorted(rows) == [("/tr/beyin-ve-sinir-cerrahisi-hangi-hastaliklara-bakar/", "%7Binline_image_1%7D", "<img src>"),
                            ("/tr/beyin-ve-sinir-cerrahisi-hangi-hastaliklara-bakar/", "{cta_link}", "<a href>")]
    values = [row["sample"] for row in finding.evidence["found"]]
    assert "https://withmaya.ai/app/%7Binline_image_1%7D" in values and finding.severity.value == "S2"


def test_str13_leaves_footnotes_pagination_arrows_quotes_and_code_alone(template_site):
    reported = {url for f in template_site.by_id["STR-13"].findings for url in short(template_site, f.scope["urls"])}
    assert "/tr/temiz/" not in reported and "/" not in reported
    assert template_site.by_id["STR-13"].evidence["places_checked"] == [
        "JSON-LD", "meta tag", "title", "link or image URL", "visible text"]
    markdown = render_markdown(template_site.result, template_site.gates, template_site.checks)
    assert "unfilled template markers in JSON-LD: {{publishDate}}" in markdown


@pytest.mark.parametrize("text, markers", [
    ("{{publishDate}}", ["{{publishDate}}"]), ("by {{ author.name | title }} on", ["{{ author.name | title }}"]),
    ("{% include 'cta' %}", ["{% include 'cta' %}"]), ("[[cta_button]]", ["[[cta_button]]"]), ("‹teyit›", ["‹teyit›"]),
    ("‹kaynak ekle›", ["‹kaynak ekle›"]), ("Hello ${user.name}", ["${user.name}"]),
    ("https://x.example/app/%7Binline_image_1%7D", ["%7Binline_image_1%7D"]),
    ("https://x.example/a/{slug}/b", ["{slug}"]),
    ("[[1]] [[2]]", []), ("‹ Önceki", []), ("Sonraki ›", []), ("‹ 1 2 3 ›", []), ("{ a: 1 }", []), ("{}", []),
    ("price {10}", []), ("a {b} c", []), ("JSON {\"a\": \"b\"}", []),
])
def test_template_markers(text, markers):
    assert template_markers(text) == markers


def test_str13_a_json_ld_block_that_does_not_parse_because_of_its_slots_is_still_read():
    broken = '<script type="application/ld+json">{"@type": "BlogPosting", "wordCount": {{word_count}}, "name": "x"}</script>'
    outcome = audit({"/tr/bozuk/": page(f"<h1>Bozuk</h1><p>{TR}</p>", head=broken)})
    finding, rows = found(outcome, "JSON-LD")
    assert rows == [("/tr/bozuk/", "{{word_count}}", "block 1 (the block does not parse, or the marker is in a key)")]


# 4. Tracking parameters on internal links -------------------------------------------------------------
def test_idx6_internal_links_carrying_tracking_parameters_are_reported():
    tagged = ["/tr/yatakli-servis/?utm_source=gemini", "/tr/yatakli-servis/psikiyatri/?utm_source=gemini&utm_medium=ai",
              "/tr/rehber/?gclid=abc123"]
    body = (f"<h1>Yataklı Psikiyatri Servisi</h1><p>{TR}</p>" + links(tagged)
            + '<a href="/tr/arama/?q=uyku&page=2">Arama</a><a href="https://baska.example/?utm_source=x">Dış</a>')
    outcome = audit({"/tr/psikiyatri-servisi/": page(body), "/tr/yatakli-servis/": page(f"<h1>Y</h1><p>{TR}</p>"),
                     "/tr/yatakli-servis/psikiyatri/": page(f"<h1>P</h1><p>{TR}</p>"), "/tr/rehber/": page(f"<h1>R</h1><p>{TR}</p>")},
                    sitemap=["/", "/tr/psikiyatri-servisi/"])
    idx6 = outcome.by_id["IDX-6"]
    [finding] = [f for f in idx6.findings if "tracking parameters" in f.title]
    assert finding.severity.value == "S3" and finding.confidence.value == "verified"
    assert "3 internal link(s) on 1 page(s) carry tracking parameters (utm_source=gemini, utm_medium=ai, gclid=abc123)" in finding.title
    rows = {row["target"].removeprefix(outcome.base): row for row in finding.evidence["links"]}
    assert set(rows) == set(tagged)  # not the search link, not the link to another site
    assert rows[tagged[1]]["parameters"] == ["utm_source=gemini", "utm_medium=ai"]
    assert rows[tagged[0]]["source"].endswith("/tr/psikiyatri-servisi/") and rows[tagged[0]]["anchor"]
    assert "3 internal link(s) carry tracking parameters" in idx6.summary and idx6.title.startswith("Internal links")


def test_idx6_says_so_when_no_internal_link_is_tagged():
    outcome = audit({"/tr/a/": page(f"<p>{TR}</p>")})
    idx6 = outcome.by_id["IDX-6"]
    assert not idx6.findings and "No internal link carries tracking parameters" in idx6.summary


def test_tracking_parameters():
    assert tracking_parameters("https://s/a?utm_source=gemini&id=4&UTM_Campaign=x&fbclid=1") == [
        "utm_source=gemini", "UTM_Campaign=x", "fbclid=1"]
    assert tracking_parameters("https://s/a?page=2&sort=utm") == [] and tracking_parameters("https://s/a") == []


# 5. Soft 404 ------------------------------------------------------------------------------------------
def soft_site(answer, robots="User-agent: *\nAllow: /\n", **options):
    """A site whose answer for any unknown path is `answer`; returns the audit and what the server saw."""
    routes = {"/robots.txt": Response(body=robots, content_type="text/plain"),
              "/": page(f"<h1>Ana</h1><p>{TR}</p>" + links(["/tr/sayfa/"])), "/tr/sayfa/": page(f"<h1>S</h1><p>{TR}</p>"),
              "/sitemap.xml": Response(404, "", content_type="text/plain")}
    with FakeServer(Site(routes, fallback=answer)) as server:
        outcome = run_audit(server.base_url + "/", CrawlConfig(**{**QUIET, **options}))
        seen = [(r.seq, r.route_path, r.at, r.user_agent) for r in server.requests]
        outcome.base = server.base_url
    outcome.by_id = {check.check_id: check for check in outcome.checks}
    return outcome, seen


def probes(seen):
    return [row for row in seen if row[1].startswith("/maya-audit-no-such-page-")]


def test_idx1_a_missing_page_that_redirects_to_the_homepage_is_a_soft_404():
    outcome, seen = soft_site(Response(301, "", headers={"Location": "/"}))
    idx1 = outcome.by_id["IDX-1"]
    [finding] = [f for f in idx1.findings if "soft 404" in f.title]
    assert finding.title == "A page that does not exist redirects (301) to the homepage (soft 404)"
    assert finding.severity.value == "S3" and finding.confidence.value == "verified"
    probe = finding.evidence["probe"]
    assert probe["status"] == 301 and probe["final_url"] == outcome.base + "/" and probe["redirect_location"] == outcome.base + "/"
    assert "not followed" in probe["final_url_note"] and "curl" in finding.evidence["reproduce"]
    # One request only, to a clearly random path, with Maya's own user agent.
    [sent] = probes(seen)
    assert len(sent[1]) == len("/maya-audit-no-such-page-") + 16 and sent[3].startswith("Maya-Audit")
    assert probe["url"] == outcome.base + sent[1]
    assert "Missing-page test: a made-up address redirects (301) to the homepage" in idx1.summary


def test_idx1_a_missing_page_that_answers_200_is_a_soft_404_and_one_that_answers_404_is_fine():
    outcome, seen = soft_site(page("<h1>Aradığınız sayfa bulunamadı</h1>", title="Sayfa bulunamadı"))
    [finding] = [f for f in outcome.by_id["IDX-1"].findings if "soft 404" in f.title]
    assert "answers 200, as if the page existed" in finding.title
    assert finding.evidence["probe"]["title"] == "Sayfa bulunamadı" and finding.evidence["probe"]["final_url"].endswith(probes(seen)[0][1])

    outcome, seen = soft_site(Response(404, "<html><title>Yok</title></html>"))
    idx1 = outcome.by_id["IDX-1"]
    assert not [f for f in idx1.findings if "soft 404" in f.title] and len(probes(seen)) == 1
    assert idx1.evidence["soft_404_probe"]["status"] == 404 and idx1.evidence["soft_404_probe"]["assessed"] is True
    assert "answers 404, as it should" in idx1.summary


def test_idx1_the_probe_obeys_robots_txt_the_delay_and_the_off_switch():
    outcome, seen = soft_site(Response(301, "", headers={"Location": "/"}),
                              robots="User-agent: *\nDisallow: /maya-audit-no-such-page-\n")
    probe = outcome.by_id["IDX-1"].evidence["soft_404_probe"]
    assert probes(seen) == [] and probe["sent"] is False and "robots.txt disallows" in probe["reason"]
    assert not [f for f in outcome.by_id["IDX-1"].findings if "soft 404" in f.title]
    assert any("soft 404" in part["part"] for part in outcome.by_id["IDX-1"].coverage["not_assessed"])  # said, not passed

    outcome, seen = soft_site(Response(301, "", headers={"Location": "/"}), soft_404_probe=False)
    assert probes(seen) == [] and "switched off" in outcome.by_id["IDX-1"].evidence["soft_404_probe"]["reason"]

    # Politeness: the probe waits its turn like every other request to the site.
    outcome, seen = soft_site(Response(404, "x"), request_delay_s=0.3)
    at = {row[1]: row[2] for row in seen}
    [sent] = probes(seen)
    before = max(t for path, t in at.items() if t < sent[2])
    assert sent[2] - before >= 0.28


def test_idx1_a_redirect_somewhere_else_is_recorded_but_not_called_a_soft_404():
    outcome, seen = soft_site(Response(302, "", headers={"Location": "/tr/hata/"}))
    idx1 = outcome.by_id["IDX-1"]
    assert not [f for f in idx1.findings if "soft 404" in f.title]
    probe = idx1.evidence["soft_404_probe"]
    assert probe["assessed"] is False and probe["final_url"] == outcome.base + "/tr/hata/" and "not followed" in probe["verdict"]
    assert len(probes(seen)) == 1


def test_soft_404_verdict_treats_the_language_homepage_as_the_homepage():
    from types import SimpleNamespace

    home = SimpleNamespace(depth=0, status=200, url="https://s.example/tr/")
    result = SimpleNamespace(pages=[home], start_url="https://s.example/", origin="https://s.example")
    probe = {"sent": True, "status": 301, "redirect_location": "https://s.example/tr/"}
    assert soft_404_verdict(probe, result)["kind"] == "redirect_to_homepage"
    assert soft_404_verdict({**probe, "redirect_location": "https://s.example/"}, result)["soft_404"] is True
    assert soft_404_verdict({"sent": True, "status": 503, "redirect_location": None}, result)["assessed"] is False


# 6. Headings in another language ----------------------------------------------------------------------
THEME = ("<h3>Get Directions</h3><h2>Neuro Therapy Unit</h2><h3>Enhancing the patient and family experience</h3>"
         "<h3>Patients supported by dedicated team of experts</h3><h3>Information for new patient</h3>"
         "<h2>Available Doctors Under Food &amp; Nutrition</h2><h3>Prof. Dr. Kültegin Ögel</h3>"
         "<h3>Ask Any Question If You Have</h3>")


def test_str12_reports_theme_headings_left_in_another_language_even_when_the_body_is_turkish():
    """The two live pages still showing another hospital's theme: Turkish title and text, English section headings."""
    routes = {
        "/tr/tibbi-bolumlerimiz/yeme-bozukluklari/": page(f"<h1>Yeme Bozuklukları</h1><p>{TR}</p><p>{TR}</p>" + THEME),
        "/tr/tibbi-bolumlerimiz/kaygi/": page(f"<h1>Kaygı Bozuklukları</h1><h2>Tedavi süreci nasıl ilerler</h2><p>{TR}</p>"
                                              "<h2>Check-up Merkezi</h2><h2>Online Randevu</h2><h3>Google Search Console</h3>"),
        "/en/medical-units/sleep/": page("<h1>Sleep Laboratory</h1><h2>What to expect from the test</h2>"
                                         "<h2>Information for new patients</h2><h2>How to book a visit with us</h2>"
                                         "<p>We are here for you and your family, and this is the place for the tests "
                                         "that you need. The team will be with you from the first day of your visit, "
                                         "and all of the results are shared with your doctor on the same day.</p>", lang="en"),
    }
    outcome = audit(routes)
    [finding] = [f for f in outcome.by_id["STR-12"].findings if "section headings" in f.title]
    assert "declared Turkish, headings in English" in finding.title
    assert finding.severity.value == "S3" and finding.confidence.value == "estimated"
    [row] = finding.evidence["pages"]
    assert row["url"].endswith("/tr/tibbi-bolumlerimiz/yeme-bozukluklari/") and row["headings_count"] == 4
    assert row["headings"] == ["Enhancing the patient and family experience", "Patients supported by dedicated team of experts",
                               "Information for new patient", "Ask Any Question If You Have"]
    # Not also reported as "mostly in another language": its body is Turkish.
    assert not [f for f in outcome.by_id["STR-12"].findings if "mostly in another language" in f.title]


def test_heading_language():
    from maya_audit.language import heading_language

    assert heading_language("Information for new patient") == "en"
    assert heading_language("Tedavi süreci nasıl ilerler") == "tr"
    assert heading_language("Neuro Therapy Unit") is None and heading_language("Check-up Merkezi") is None
    assert heading_language("Hasta ve Family Rehberi için the") is None  # evidence for two languages: not called


# 3. Links that should be internal ---------------------------------------------------------------------
def test_idx6_a_link_to_another_site_at_the_path_of_one_of_this_sites_pages_is_reported():
    body = (f"<h1>Psikolog Gözüyle Şizofreni</h1><p>{TR}</p>"
            '<a href="https://withmaya.ai/tr/tibbi-bolumlerimiz/sizofreni/">Şizofreni tedavisi</a> '
            '<a href="https://withmaya.ai/tr/randevu">Randevu alın</a> '
            '<a href="https://withmaya.ai/app/dashboard">Araç</a> '
            '<a href="https://www.saglik.gov.tr/tr/randevu-sistemi">Bakanlık</a> <a href="https://withmaya.ai/">Maya</a>')
    outcome = audit({"/tr/psikolog-gozuyle-sizofreni/": page(body),
                     "/tr/tibbi-bolumlerimiz/sizofreni/": page(f"<h1>Şizofreni</h1><p>{TR}</p>"),
                     "/tr/randevu/": page(f"<h1>Randevu</h1><p>{TR}</p>")})
    idx6 = outcome.by_id["IDX-6"]
    [finding] = [f for f in idx6.findings if "another site" in f.title]
    # Since DECISIONS 196 the other address is asked once; this test reaches no public name, so it could not be checked.
    assert finding.title == ("2 link(s) on 1 page(s) point to another site (withmaya.ai) at a path that exists on this one; "
                             "the other address could not be checked")
    assert finding.severity.value == "Info" and finding.confidence.value == "inferred"
    rows = {row["target"]: row for row in finding.evidence["links"]}
    assert set(rows) == {"https://withmaya.ai/tr/tibbi-bolumlerimiz/sizofreni/", "https://withmaya.ai/tr/randevu"}
    assert rows["https://withmaya.ai/tr/randevu"]["same_path_on_this_site"].endswith("/tr/randevu/")  # slash and case aside
    assert rows["https://withmaya.ai/tr/randevu"]["anchor"] == "Randevu alın"
    assert idx6.evidence["external_links_seen"] == 5
    # Only the other site's robots.txt was asked for (and could not be reached): never the page itself.
    assert {r.url for r in outcome.result.requests if "withmaya.ai" in r.url} == {"https://withmaya.ai/robots.txt"}


def test_idx6_ordinary_links_to_other_sites_are_not_reported():
    body = (f"<h1>Kaynaklar</h1><p>{TR}</p>" '<a href="https://baska.example/">Ana sayfa</a> '
            '<a href="https://baska.example/hakkinda">Hakkında</a> <a href="https://baska.example/tr/">TR</a>')
    outcome = audit({"/tr/kaynaklar/": page(body), "/tr/iletisim/": page(f"<h1>İletişim</h1><p>{TR}</p>")})
    idx6 = outcome.by_id["IDX-6"]
    # Another site's homepage, a path this site does not have, and a bare language folder this site has no page at.
    assert idx6.findings == [] and idx6.evidence["links_to_another_site_at_one_of_this_sites_paths"] == 0
    assert idx6.evidence["external_links_seen"] == 3


# 9. Pagination ----------------------------------------------------------------------------------------
@pytest.mark.parametrize("url, paginated", [
    ("https://s/basinda-biz?sayfa=2", True), ("https://s/blog?page=3", True), ("https://s/blog/page/4/", True),
    ("https://s/urunler?kategori=5&p=2", True), ("https://s/haberler/sayfa/2", True),
    ("https://s/basinda-biz", False), ("https://s/blog?page=abc", False), ("https://s/urun?id=2", False),
    ("https://s/page/hakkimizda", False), ("https://s/arama?q=sayfa", False),
])
def test_is_pagination(url, paginated):
    from maya_audit.urls import is_pagination

    assert is_pagination(url) is paginated


def test_a_capped_crawl_does_not_spend_its_pages_on_page_2_3_4_of_a_list():
    """magazanolsun.com, v2 batch: /basinda-biz?sayfa=2, 3 and 4 took three of ten slots."""
    pager = links([f"/basinda-biz?sayfa={n}" for n in (2, 3, 4, 5)])
    sections = [f"/bolum-{name}" for name in ("bir", "iki", "uc", "dort", "bes", "alti")]
    routes = {"/": page(f"<h1>Ana</h1><p>{TR}</p>", nav='<a href="/">Ana</a> <a href="/basinda-biz">Basında Biz</a>'),
              "/basinda-biz": page(f"<h1>Basında Biz</h1><p>{TR}</p>" + pager + links(sections)),
              **{f"/basinda-biz?sayfa={n}": page(f"<h1>Basında Biz</h1><p>{TR} {n}</p>" + pager) for n in (2, 3, 4, 5)},
              **{path: page(f"<h1>{path}</h1><p>{TR}</p>") for path in sections}}
    outcome = audit(routes, sitemap=["/"], max_pages=6)
    fetched = [p.url.removeprefix(outcome.base) for p in outcome.result.pages]
    assert fetched[:2] == ["/", "/basinda-biz"] and not [path for path in fetched if "sayfa=" in path]
    assert len([path for path in fetched if path.startswith("/bolum-")]) == 4

    everything = audit(routes, sitemap=["/"], max_pages=50)
    all_fetched = [p.url.removeprefix(everything.base) for p in everything.result.pages]
    assert sorted(path for path in all_fetched if "sayfa=" in path) == [f"/basinda-biz?sayfa={n}" for n in (2, 3, 4, 5)]
    assert max(all_fetched.index(path) for path in sections) < min(all_fetched.index(p) for p in all_fetched if "sayfa=" in p)
