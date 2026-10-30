"""Fixes from the review of the first real five-brand batch (2026-10-06).

Each test rebuilds, on the fake server, the shape of page that produced a wrong or embarrassing
result on a live site, and keeps a case next to it where the finding is real and must still appear.
Offline: fake server and fixtures only.
"""

import csv
import json

import pytest

from fakeserver import FakeServer, Response, Site
from maya_audit import cli
from maya_audit.audit import run_audit
from maya_audit.checks.access import private_path_segment
from maya_audit.checks.render import PAYWALL_TR, WALL_SIGNATURES_TR, decorative_canvas, tracking_iframe
from maya_audit.checks.structure import declared_language, language_share, placeholder_hits
from maya_audit.config import SPAM_SCORE_THRESHOLD, CrawlConfig  # noqa: F401
from maya_audit.language import block_language, turkish_fold
from maya_audit.report import build_report, render_markdown, render_text
from test_deadline_hosted_hardening import QUIET

TR = ("Bu sayfa hastanemizin sunduğu hizmetler hakkında bilgi vermek için hazırlandı ve uzman kadromuz ile birlikte "
      "her hasta için en uygun tedavi planını oluşturmak çok önemli bir adım olarak görülür. Tedavi süreci daha sonra "
      "hasta ve ailesi ile birlikte değerlendirilir, ancak her durumda kişiye göre bir yaklaşım gerekir ve bu nedenle "
      "randevu almak için bizi arayabilirsiniz. ")
EN = ("Welcome to Riverside General Hospital, where our team of doctors and nurses is here for you and your family. "
      "We have been caring for the people of this city for more than thirty years, and we are proud of the trust that "
      "our patients have placed in us. This is the place to describe your services and what you can do for the visitor. ")
DE = ("Dies ist eine Seite über unsere Arbeit und die Menschen, die mit uns zusammen an einem Ziel arbeiten. Wir sind "
      "für Sie da und freuen uns auf Ihren Besuch, denn das ist nicht nur ein Beruf, sondern auch eine Aufgabe, die "
      "wir mit dem ganzen Team gerne erfüllen. Sie werden bei uns von den besten Ärzten nach dem Stand der Zeit betreut. ")
MENU = '<a href="/">Ana Sayfa</a>'


def page(body, lang="tr", head="", title="Sayfa", nav=MENU, footer="Tüm hakları saklıdır"):
    return Response(body=f'<!doctype html><html lang="{lang}"><head><title>{title}</title>{head}</head><body>'
                         f'<header><nav>{nav}</nav></header><main>{body}</main><footer>{footer}</footer></body></html>')


def links(paths):
    return " ".join(f'<a href="{path}">{path.strip("/") or "ana"}</a>' for path in paths)


def audit(routes, sitemap=None, robots="User-agent: *\nAllow: /\n", start="/", **options):
    """Run the real audit over a fake site. `sitemap` is a list of paths; the homepage links to every route."""
    paths = [path for path in routes if path != "/"]
    routes = dict(routes)
    home = routes.pop("/", None)
    site = {"/robots.txt": Response(body=robots, content_type="text/plain"), **routes}
    with FakeServer(Site(site)) as server:
        if home is None:
            home = page(f"<h1>Ana sayfa</h1><p>{TR}</p>" + links(paths))
        site["/"] = home
        listed = sitemap if sitemap is not None else ["/"] + paths
        site["/sitemap.xml"] = Response(content_type="application/xml", body=(
            '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            + "".join(f"<url><loc>{server.base_url}{path}</loc></url>" for path in listed) + "</urlset>"))
        outcome = run_audit(server.base_url + start, CrawlConfig(**{**QUIET, **options}))
        outcome.base = server.base_url
    outcome.by_id = {check.check_id: check for check in outcome.checks}
    return outcome


def short(outcome, urls):
    return sorted(url.removeprefix(outcome.base) for url in urls)


# 3. ACC-2 ------------------------------------------------------------------------------------------
PRIVATE = ["/checkout", "/sepet", "/odeme/adim-1", "/hesabim", "/uye-girisi", "/arama", "/cdn-cgi/l/email-protection"]
ROBOTS = ("User-agent: *\n" + "".join(f"Disallow: /{name}\n" for name in
          ("checkout", "sepet", "odeme", "hesabim", "uye-girisi", "arama", "cdn-cgi/", "blog/", "kampanyalar", "arsiv/")))


@pytest.fixture(scope="module")
def robots_site():
    blocked = PRIVATE + ["/blog/yazi-bir", "/kampanyalar", "/arsiv/eski-sayfa"]
    home = page(f"<h1>Mağaza</h1><p>{TR}</p>" + links(blocked + ["/urunler"]),
                nav=MENU + ' <a href="/kampanyalar">Kampanyalar</a> <a href="/sepet">Sepetim</a>')
    # The sitemap puts the blog forward; the navigation puts /kampanyalar forward; nothing puts /arsiv/ forward.
    return audit({"/": home, "/urunler": page(f"<h1>Ürünler</h1><p>{TR}</p>")}, sitemap=["/", "/urunler", "/blog/yazi-bir"],
                 robots=ROBOTS)


def acc2_search(outcome):
    found = {}
    for finding in outcome.by_id["ACC-2"].findings:
        if " search bot(s) " in finding.title:
            for url in short(outcome, finding.scope["urls"]):
                found[url] = finding
    return found


def test_acc2_blocking_private_or_technical_paths_is_info_not_s1(robots_site):
    found = acc2_search(robots_site)
    for path in PRIVATE:
        finding = found[path]
        assert finding.severity.value == "Info", path
        assert finding.intent == {"kind": "private_or_technical_path", "severity_otherwise": "S1"}
        assert finding.evidence["path_kind"]["kind"] == "private_or_technical"
        assert "private or technical" in " ".join(finding.notes)
    assert found["/sepet"].evidence["path_kind"]["matched_segments"] == ["sepet"]  # in the navigation, still Info
    assert not [f for f in robots_site.by_id["ACC-2"].findings
                if f.severity.value in ("S1", "S2") and set(short(robots_site, f.scope["urls"])) & set(PRIVATE)]
    text = render_text(robots_site.result, robots_site.gates, robots_site.checks)
    assert "private_or_technical_path; would otherwise be S1" in text


def test_acc2_is_still_s1_when_the_blocked_path_holds_pages_meant_to_be_found(robots_site):
    found = acc2_search(robots_site)
    blog, campaign, archive = found["/blog/yazi-bir"], found["/kampanyalar"], found["/arsiv/eski-sayfa"]
    assert blog.severity.value == "S1" and campaign.severity.value == "S1"
    why = lambda finding: set(finding.evidence["path_kind"]["why"].values())
    assert why(blog) == {"listed in the sitemap"} and why(campaign) == {"linked from the navigation"}
    # A real page that neither the sitemap nor the navigation puts forward: reported, but not as S1.
    assert archive.severity.value == "S3" and archive.evidence["path_kind"]["kind"] == "not_put_forward"
    assert "S3 rather than S1" in " ".join(archive.notes)


def test_acc2_a_private_looking_path_listed_in_the_sitemap_or_a_sitewide_rule_stays_s1():
    outcome = audit({"/urunler": page(f"<p>{TR}</p>" + links(["/search/populer"]))}, sitemap=["/", "/urunler", "/search/populer"],
                    robots="User-agent: *\nDisallow: /search\n\nUser-agent: OAI-SearchBot\nDisallow: /\n")
    found = acc2_search(outcome)
    assert found["/search/populer"].severity.value == "S1"  # the site lists it in its own sitemap
    sitewide = next(f for f in outcome.by_id["ACC-2"].findings if "sitewide" in f.title and "OAI-SearchBot" in f.title)
    assert sitewide.severity.value == "S1"


@pytest.mark.parametrize("url, pattern, segment", [
    ("https://s/checkout", "/checkout", "checkout"), ("https://s/tr/sepet/", "", "sepet"),
    ("https://s/Hesabim/siparislerim", "", "hesabim"), ("https://s/wp-login.php", "", "wp-login"),
    ("https://s/x", "/cdn-cgi/", "cdn-cgi"), ("https://s/urunler/sepet-canta", "", None),
    ("https://s/blog/login-sorunlari-nasil-cozulur", "/blog/", None), ("https://s/", "/", None),
])
def test_private_path_segment(url, pattern, segment):
    assert private_path_segment(url, pattern) == segment


# 4. RND-4 ------------------------------------------------------------------------------------------
GTM = ('<noscript><iframe src="https://www.googletagmanager.com/ns.html?id=GTM-T5WQJHT" height="0" width="0" '
       'style="display:none;visibility:hidden"></iframe></noscript>')
TRACKERS = (GTM + '<iframe src="https://sgtm.marka.example/ns.html?id=GTM-PHHQNH"></iframe>'
            '<iframe src="https://www.facebook.com/tr?id=123&ev=PageView" width="1" height="1"></iframe>'
            '<iframe src="https://vars.hotjar.com/box-abc.html" title="hotjar"></iframe>'
            '<iframe src="https://www.google.com/recaptcha/api2/anchor?k=x"></iframe>'
            '<iframe src="https://widget.marka.example/chat" hidden></iframe>'
            '<canvas aria-hidden="true"></canvas><canvas id="particles-js"></canvas>'
            '<canvas class="hero-bg-animation"></canvas><canvas role="presentation"></canvas>')


def test_rnd4_ignores_tracking_iframes_and_decorative_canvases():
    outcome = audit({"/yazi": page(f"<h1>Yazı</h1><p>{TR}</p>" + TRACKERS)})
    rnd4 = outcome.by_id["RND-4"]
    assert rnd4.findings == [] and rnd4.status == "pass"
    assert rnd4.evidence["ignored_tracking_iframes_count"] == 6 and rnd4.evidence["ignored_decorative_canvases_count"] == 4
    reasons = {row["iframe_src"].split("/")[2]: row["why"] for row in rnd4.evidence["ignored_tracking_iframes"]}
    assert "noscript" in reasons["www.googletagmanager.com"] and "tag-manager" in reasons["sgtm.marka.example"]
    assert "hotjar.com" in reasons["vars.hotjar.com"] and "hidden" in reasons["widget.marka.example"]
    assert "6 tracking, consent or hidden iframe(s) and 4 decorative canvas(es)" in rnd4.summary


def test_rnd4_still_flags_real_content_in_an_iframe_or_a_canvas():
    body = (f"<h1>Fiyatlar</h1><p>{TR}</p>" + TRACKERS
            + '<iframe src="https://tablo.example/embed/fiyat-listesi" title="Fiyat listesi"></iframe>'
              '<canvas id="satis-grafigi" width="600" height="300"></canvas>'
              '<canvas id="yillik-grafik" aria-label="2025 satışları: 120, 140, 180"></canvas>')
    outcome = audit({"/fiyatlar": page(body)})
    findings = {("iframe" if "iframe" in f.title else "canvas"): f for f in outcome.by_id["RND-4"].findings}
    assert set(findings) == {"iframe", "canvas"}
    assert [item["iframe_src"] for item in findings["iframe"].evidence["items"]] == ["https://tablo.example/embed/fiyat-listesi"]
    assert [item["canvas"] for item in findings["canvas"].evidence["items"]] == ["satis-grafigi"]
    assert outcome.by_id["RND-4"].evidence["ignored_tracking_iframes_count"] == 6


@pytest.mark.parametrize("frame, ignored", [
    ({"src": "https://www.googletagmanager.com/ns.html?id=GTM-X"}, True),
    ({"src": "//connect.facebook.net/x"}, True), ({"src": "https://static.hotjar.com/c"}, True),
    ({"src": "https://www.youtube.com/embed/abc"}, False), ({"src": "https://maps.google.com/maps?q=x"}, False),
    ({"src": "/kendi/icerik.html"}, False), ({"src": "/kendi/icerik.html", "in_noscript": True}, True),
    ({"src": "https://notfacebook.com.evil.example/x"}, False),
])
def test_tracking_iframe(frame, ignored):
    assert bool(tracking_iframe(frame)) is ignored


def test_decorative_canvas():
    assert decorative_canvas({"hint": "confetti-canvas"}) and decorative_canvas({"hidden": True})
    assert decorative_canvas({"hint": "sales-chart"}) is None and decorative_canvas({"hint": None}) is None


# 5. Pages and redirects ----------------------------------------------------------------------------
def test_reports_count_pages_checked_and_redirects_separately(monkeypatch, capsys, tmp_path):
    routes = {"/": Response(302, "", headers={"Location": "/tr/"}),
              "/tr/": page(f"<h1>Ana</h1><p>{TR}</p>" + links([f"/tr/sayfa-{name}/" for name in "abcdef"])),
              **{f"/tr/sayfa-{name}/": page(f"<h1>{name}</h1><p>{TR}</p>") for name in "abcdef"}}
    outcome = audit(routes, sitemap=["/tr/"], max_pages=3)
    assert len(outcome.result.pages) == 4  # three pages and the redirect that led to the homepage
    assert "**Pages checked:** 3 pages + 1 redirect, of " in render_markdown(outcome.result, outcome.gates, outcome.checks)
    assert "3 pages + 1 redirect checked, " in render_text(outcome.result, outcome.gates, outcome.checks)
    assert build_report(outcome.result, outcome.gates, outcome.checks)["page_counts"] == {"pages_checked": 3, "redirects": 1}

    brands = tmp_path / "brands.csv"
    brands.write_text("name,url\nMarka,https://marka.example/\n", encoding="utf-8")
    monkeypatch.setattr(cli, "run_audit", lambda url, config: outcome)
    assert cli.main(["batch", str(brands), "--out", str(tmp_path / "out"), "--max-pages", "3"]) == 0
    with open(tmp_path / "out" / "summary.csv", encoding="utf-8", newline="") as fh:
        [row] = list(csv.DictReader(fh))
    assert (row["pages_checked"], row["redirects"]) == ("3", "1") and "pages_fetched" not in row
    assert "| 3 pages + 1 redirect (of " in (tmp_path / "out" / "summary.md").read_text(encoding="utf-8")
    assert json.loads((tmp_path / "out" / "marka.json").read_text(encoding="utf-8"))["page_counts"]["redirects"] == 1


# 6. IDX-8 ------------------------------------------------------------------------------------------
def unique(seed, n=60):
    return " ".join(f"{seed}kelime{i}" for i in range(n))


def furniture():
    """A big menu and footer written as plain <div>s, the way the site that showed this problem builds them."""
    menu = "".join(f"<p>Menü başlığı {i}: e-ticaret paketleri, entegrasyonlar, destek ve eğitim içerikleri burada</p>" for i in range(150))
    return f'<div class="ust-menu">{menu}</div>', f'<div class="alt-bilgi">{menu.replace("Menü", "Alt")}</div>'


def div_page(body, title):
    top, bottom = furniture()
    return Response(body=f'<!doctype html><html lang="tr"><head><title>{title}</title></head><body>{top}'
                         f'<div class="icerik"><h1>{title}</h1>{body}</div>{bottom}</body></html>')


def test_idx8_pages_that_share_only_their_menu_and_footer_are_not_near_duplicates():
    names = ["demo", "hakkimizda", "entegrasyon", "iletisim", "kariyer"]
    twin = f"<p>{unique('ortak', 200)}</p>"
    routes = {f"/{name}": div_page(f"<p>{unique(name)}</p>", name.title()) for name in names}
    routes["/urun-siyah"] = div_page(twin + "<p>Renk: siyah</p>", "Ürün siyah")
    routes["/urun-beyaz"] = div_page(twin + "<p>Renk: beyaz</p>", "Ürün beyaz")
    routes["/"] = div_page("<p>" + unique("ana") + "</p>" + links(list(routes)), "Ana")
    outcome = audit(routes)
    idx8 = outcome.by_id["IDX-8"]
    near = [f for f in idx8.findings if "nearly identical" in f.title]
    assert [short(outcome, f.scope["urls"]) for f in near] == [["/urun-beyaz", "/urun-siyah"]]  # the real pair only
    assert "main content only" in near[0].evidence["compared"] and idx8.evidence["site_wide_text_blocks_removed"] >= 300

    # The same pages compared on their whole visible text are the false alarm this fixes.
    from maya_audit.analysis import sketch_similarity
    by_path = {p.url.removeprefix(outcome.base): p.analysis for p in outcome.result.pages if p.analysis}
    assert sketch_similarity(by_path["/demo"]["text_sketch"], by_path["/hakkimizda"]["text_sketch"]) >= 0.8


def test_idx8_a_page_with_almost_no_content_of_its_own_is_not_compared_and_that_is_said():
    routes = {f"/{name}": div_page(f"<p>{unique(name)}</p>", name) for name in ("bir", "iki", "uc")}
    routes["/bos-a"], routes["/bos-b"] = div_page("<p>Yakında</p>", "Boş A"), div_page("<p>Çok yakında</p>", "Boş B")
    outcome = audit(routes)
    idx8 = outcome.by_id["IDX-8"]
    assert not [f for f in idx8.findings if "nearly identical" in f.title]
    assert short(outcome, idx8.evidence["too_little_main_content_to_compare"]) == ["/bos-a", "/bos-b"]
    assert "2 page(s) have fewer than 30 words of their own" in idx8.summary


def test_a_title_two_pages_share_is_one_finding_by_str1_and_identical_text_is_still_idx8s():
    """"2 indexable pages share the title …" (IDX-8) beside "1 title(s) are shared by 2 different indexable pages"
    (STR-1): two problems for one fact (decision 187)."""
    routes = {f"/{name}": div_page(f"<p>{unique(name)}</p>", name.title()) for name in ("demo", "hakkimizda", "iletisim")}
    routes["/kazak"], routes["/hirka"] = div_page(f"<p>{unique('kazak')}</p>", "Made-up Shop"), div_page(f"<p>{unique('hirka')}</p>", "Made-up Shop")
    same = div_page(f"<p>{unique('ayni')}</p>", "Kopya")
    routes["/kopya-a"], routes["/kopya-b"] = same, same
    routes["/"] = div_page("<p>" + unique("ana") + "</p>" + links(list(routes)), "Ana")
    outcome = audit(routes)
    idx8 = outcome.by_id["IDX-8"]
    assert not [f for f in idx8.findings if "share the title" in f.title]
    titles = [f for f in outcome.by_id["STR-1"].findings if "title(s) are shared" in f.title]
    assert len(titles) == 1 and ["/hirka", "/kazak"] in [short(outcome, group["urls"]) for group in titles[0].evidence["groups"]]
    assert [group["title"] for group in titles[0].evidence["groups"] if short(outcome, group["urls"]) == ["/hirka", "/kazak"]] == ["Made-up Shop"]
    # Healthy: the same text at two addresses is still IDX-8's finding; the title the two copies share is said on their
    # group's line, and STR-1 keeps its other group (decision 225).
    [identical] = idx8.findings
    assert identical.title == "1 group of indexable pages that are copies or near-copies of each other (2 pages)"
    assert short(outcome, identical.scope["urls"]) == ["/kopya-a", "/kopya-b"]
    assert [g["signals"] for g in identical.evidence["duplicate_groups"]] == [["same_text", "same_title"]]
    assert [short(outcome, group["urls"]) for group in titles[0].evidence["groups"]] == [["/hirka", "/kazak"]]


def test_idx8_near_duplicates_that_look_like_variants_of_one_product_get_variant_advice():
    """adilehanim, 2026-10-12: "/bol-cevizli-dag-cezerye/" and "/bol-findikli-dag-cezerye/" were told to "Consolidate
    near-identical pages", which is wrong advice for two flavours of one product (decision 190)."""
    pytest.importorskip("fastapi")
    from maya_audit_web import wording
    twin, other = f"<p>{unique('ortak', 200)}</p>", f"<p>{unique('kurum', 200)}</p>"
    routes = {f"/{name}": div_page(f"<p>{unique(name)}</p>", name.title()) for name in ("demo", "hakkimizda", "iletisim")}
    routes["/bol-cevizli-dag-tatli/"] = div_page(twin + "<p>Cevizli</p>", "CEVİZLİ DAĞ TATLI | Made-up Shop")
    routes["/bol-findikli-dag-tatli/"] = div_page(twin + "<p>Fındıklı</p>", "FINDIKLI DAĞ TATLI | Made-up Shop")
    routes["/about/"], routes["/contact-us/"] = div_page(other + "<p>About</p>", "About | Made-up Shop"), div_page(other + "<p>Contact</p>", "Contact us | Made-up Shop")
    routes["/"] = div_page("<p>" + unique("ana") + "</p>" + links(list(routes)), "Ana")
    outcome = audit(routes)
    # The two groups are one IDX-8 finding (decision 225); the variant advice stays on the variants' own line.
    from maya_audit.models import to_jsonable
    from maya_audit.report import detail_lines, detail_sentence

    [merged] = outcome.by_id["IDX-8"].findings
    assert merged.title == "2 groups of indexable pages that are copies or near-copies of each other (4 pages)"
    assert merged.severity.value == "S4" and merged.expected == "each indexable URL has distinct content"
    assert merged.notes[-1] == "These pages look like variants of one product: their addresses and titles differ by a word or two."
    near = {tuple(short(outcome, g["urls"])): g for g in merged.evidence["duplicate_groups"]}
    variants, plain = near[("/bol-cevizli-dag-tatli/", "/bol-findikli-dag-tatli/")], near[("/about/", "/contact-us/")]
    assert variants["variant_like"] is True and plain["variant_like"] is False
    [pair] = variants["pairs"]
    assert pair["differs_in"] == {"url": {"a": ["cevizli"], "b": ["findikli"]}, "title": {"a": ["cevizli"], "b": ["findikli"]}}
    lines = {detail_sentence(line).split(":")[0]: detail_sentence(line) for line in detail_lines(to_jsonable(merged))}
    assert lines["/bol-cevizli-dag-tatli/, /bol-findikli-dag-tatli/"].endswith(
        "These look like variants of one product: add what sets each apart (ingredients, weight, use), or create a parent product page.")
    # Healthy: two unrelated pages with nearly the same text get no variant advice.
    assert lines["/about/, /contact-us/"] == "/about/, /contact-us/: nearly the same main content"
    assert all(wording.note(note, "tr")[1] for note in merged.notes)


def test_what_makes_two_pages_look_like_variants():
    from maya_audit.checks.index import variant_difference
    site = "https://shop.example.test"
    def like(a, title_a, b, title_b):
        return variant_difference(site + a, title_a, site + b, title_b)
    # The saved group that needs three words in the address: "bol", "antep", "fistikli" beside "narli".
    assert like("/bol-antep-fistikli-dag-tatli/", "ANTEP FISTIKLI DAĞ TATLI | Made-up", "/narli-dag-tatli/", "NARLI DAĞ TATLI | Made-up") == {
        "url": {"a": ["bol", "antep", "fistikli"], "b": ["narli"]}, "title": {"a": ["antep", "fistikli"], "b": ["narli"]}}
    assert like("/en/dag-tatli-with-plenty-walnut/", "Dag Tatli With Plenty Walnut - Made-up", "/en/dag-tatli-with-plenty-hazelnut/", "Dag Tatli With Plenty Hazelnut - Made-up")
    same_titles = ("Dağ Tatlı Cevizli | Made-up", "Dağ Tatlı Fındıklı | Made-up")
    assert like("/urun/dag-tatli-cevizli/", same_titles[0], "/urun/dag-tatli-findikli/", same_titles[1])
    assert like("/urun/dag-tatli-cevizli/", same_titles[0], "/blog/dag-tatli-findikli/", same_titles[1]) is None      # another folder
    assert like("/urun/dag-tatli-cevizli/", same_titles[0], "/urun/tatli/dag-tatli-findikli/", same_titles[1]) is None  # another depth
    assert like("/dag-tatli-cevizli/", "Dağ Tatlı | Made-up", "/dag-tatli-findikli/", "Dağ Tatlı | Made-up") is None      # the same title
    assert like("/dag-tatli-a-b-c-d/", same_titles[0], "/dag-tatli-findikli/", same_titles[1]) is None                   # four words apart
    assert like("/cevizli/", same_titles[0], "/findikli/", same_titles[1]) is None                                       # no shared word in the address
    assert like("/dag-tatli-cevizli/", "Marka | Cevizli", "/dag-tatli-findikli/", "Marka | Fındıklı") is None        # titles share one word only
    assert like("/", "Ana | Made-up", "/dag-tatli/", "Dağ Tatlı | Made-up") is None


# 7. STR-4 ------------------------------------------------------------------------------------------
BANNER = '<div class="ust-bant">Mağazanı hemen aç: aylık 29 USD</div>'


def product(*prices, currency="TRY"):
    offers = [{"@type": "Offer", "price": price, "priceCurrency": currency} for price in prices]
    return ('<script type="application/ld+json">' + json.dumps(
        {"@context": "https://schema.org", "@type": "Product", "name": "Paket", "offers": offers}) + "</script>")


@pytest.fixture(scope="module")
def price_site():
    routes = {
        "/": page(BANNER + f"<h1>Paket</h1><p>50.000 TL'den başlayan fiyatlar ile e-ticarete başla.</p><p>{TR}</p>"
                  + links(["/akademi", "/etkinlik", "/paketler", "/hakkimizda", "/baslangic"]), head=product("95000", "190000")),
        "/akademi": page(BANNER + f"<h1>Paket</h1><p>{TR}</p>", head=product("0", "60000", "250")),
        "/etkinlik": page(BANNER + f"<h1>Paket</h1><p>Ücretsiz etkinlik. {TR}</p>", head=product("0")),
        "/paketler": page(BANNER + f"<h1>Paket</h1><p>Paket fiyatı 95.000 TL. {TR}</p>", head=product("95000")),
        "/baslangic": page(BANNER + f"<h1>Paket</h1><p>{TR}</p>", head=product("29", currency="USD")),
        "/hakkimizda": page(BANNER + f"<h1>Hakkımızda</h1><p>{TR}</p>"),
    }
    return audit(routes)


def test_str4_a_price_shown_on_most_pages_is_not_taken_for_a_pages_own_price(price_site):
    price = [f for f in price_site.by_id["STR-4"].findings if "price differs" in f.title]
    assert [short(price_site, f.scope["urls"]) for f in price] == [["/"]]  # not /akademi, not /etkinlik
    rows = price_site.by_id["STR-4"].evidence
    assert "/akademi" not in json.dumps([f.evidence for f in price])


def test_str4_the_homepage_price_conflict_is_still_flagged(price_site):
    [finding] = [f for f in price_site.by_id["STR-4"].findings if "price differs" in f.title]
    assert finding.severity.value == "S2" and finding.confidence.value == "verified"
    values = finding.evidence["values"]
    assert [row["schema_value"] for row in values] == ["95000", "190000"]
    for row in values:
        # Both sides are in the row: the markup price with its currency, and the page's own price with its place.
        assert row["schema_currency"] == "TRY" and row["offer_parent"] == {"type": ["Product"], "name": "Paket"}
        assert [(shown["text"], shown["currency"]) for shown in row["visible"] if shown["where"] == "main content"] == [("50.000 TL", "TRY")]
        assert row["site_wide_prices_ignored"] == ["29 USD"] and row["distinct_prices_shown"] == 1


def test_str4_a_markup_price_equal_to_the_site_wide_price_still_matches(price_site):
    from maya_audit.checks.structure import _compare_page, sitewide_prices
    from maya_audit.main_content import blocks_on_most_pages

    pages = [p for p in price_site.result.pages if p.analysis]
    sitewide, shared = sitewide_prices(pages), blocks_on_most_pages(pages)
    assert sitewide == {"29 usd"}
    by_path = {p.url.removeprefix(price_site.base): p for p in pages}
    outcome = lambda path: [(row["schema_value"], row["outcome"]) for row in
                            _compare_page(by_path[path], by_path[path].analysis["_visible_text"], False, sitewide, shared)
                            if row["field"] == "price"]
    assert outcome("/baslangic") == [("29", "match")] and outcome("/paketler") == [("95000", "match")]
    assert outcome("/akademi") == [("0", "not_visible"), ("60000", "not_visible"), ("250", "not_visible")]
    # Without the site-wide rule these were the false alarms. Since 2026-10-11 the banner's "29 USD" is not taken for
    # the price of an offer in TRY either (DECISIONS 175), so they are "not shown" with or without that rule.
    alone = [r for r in _compare_page(by_path["/akademi"], by_path["/akademi"].analysis["_visible_text"], False) if r["field"] == "price"]
    assert {r["outcome"] for r in alone} == {"not_visible"} and {r["why_code"] for r in alone} == {"not_own"}
    assert [shown["where"] for shown in alone[0]["visible"]] == ["another currency than the markup"]


# 8. STR-7 ------------------------------------------------------------------------------------------
def test_str7_reads_a_lazy_loaded_images_real_address_and_still_reports_its_missing_alt():
    body = (f"<h1>SEO</h1><p>{TR}</p>"
            '<figure><img src="" data-src="/gorsel/seo-paneli.jpg" width="650" height="600"><figcaption>Diagram of audit steps</figcaption></figure>'
            '<img src="data:image/gif;base64,R0lGODlhAQABAAAAACw=" data-srcset="/gorsel/rapor-800.jpg 800w, /gorsel/rapor-1600.jpg 1600w" '
            'width="400" height="300" alt="">'
            '<img class="lazyload" data-original="/gorsel/grafik.png" width="500" height="400" alt="Aylık satış grafiği">'
            '<figure><img src="/gorsel/ekip.jpg" loading="lazy" width="500" height="400"><figcaption>Diagram of team responsibilities</figcaption></figure>'
            '<img width="650" height="600">')
    outcome = audit({"/seo": page(body)})
    str7 = outcome.by_id["STR-7"]
    [finding] = [f for f in str7.findings if "meaningful" in f.title]
    rows = {row["src"]: row for row in finding.evidence["images"]}
    # Never an empty src. The image with a deliberate alt="" is no longer called meaningful for its size alone
    # (DECISIONS 178): it is counted among the empty-alt images that could not be classified.
    assert set(rows) == {"/gorsel/seo-paneli.jpg", "/gorsel/ekip.jpg"}
    assert rows["/gorsel/seo-paneli.jpg"]["alt_state"] == "missing" and rows["/gorsel/seo-paneli.jpg"]["lazy_loaded"] is True
    assert rows["/gorsel/ekip.jpg"]["lazy_loaded"] is True and str7.evidence["empty_alt_not_assessed_count"] == 1
    assert finding.title == "2 likely meaningful image(s) on 1 page(s): 2 with no alt text, 0 with an empty alt"
    assert str7.evidence["images_with_no_source_skipped"] == 1  # the <img> with no address at all shows nothing
    assert "/gorsel/grafik.png" not in json.dumps(finding.evidence)  # it has alt text


# 9. RND-5 ------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def wall_site():
    menu = MENU + ' <a href="/giris">Giriş Yap</a> <a href="/uyelik">Üye Ol</a> <a href="/abonelik">Abone Ol</a>'
    routes = {
        "/haber": page(f"<h1>Haber</h1><p>{TR * 8}</p><p>Bu haberin devamını okumak için abone olun.</p>", nav=menu),
        "/ozel": page("<h1>Üyelere özel</h1><p>Bu içeriği görüntülemek için lütfen giriş yapın.</p>", nav=menu),
        "/yas": page("<h1>ŞARAP</h1><p>18 YAŞINDAN BÜYÜK MÜSÜNÜZ? YAŞINIZI DOĞRULAYIN.</p>", nav=menu),
        "/normal": page(f"<h1>Normal</h1><p>{TR * 2}</p>", nav=menu),
        "/kisa": page("<h1>İletişim</h1><p>Bize ulaşın.</p>", nav=menu),
        "/de": page(f"<h1>Über uns</h1><p>{DE * 2}</p>", lang="de", nav='<a href="/">Start</a>', footer="Alle Rechte"),
        "/en-wall": page("<h1>Members</h1><p>Please sign in to continue.</p>", lang="en", nav='<a href="/">Home</a>', footer="All rights"),
    }
    return audit(routes)


def test_rnd5_finds_turkish_walls_and_paywalls_and_keeps_the_english_ones(wall_site):
    rnd5 = wall_site.by_id["RND-5"]
    walls = {page_["url"].removeprefix(wall_site.base): page_["signatures"]
             for f in rnd5.findings if "wall" in f.title and "paywall" not in f.title for page_ in f.evidence["pages"]}
    assert walls == {"/ozel": ["login"], "/yas": ["age gate"], "/en-wall": ["login"]}
    paywalls = {page_["url"].removeprefix(wall_site.base): page_["snippet"]
                for f in rnd5.findings if "paywalled" in f.title for page_ in f.evidence["pages"]}
    assert paywalls == {"/haber": "devamını okumak için"}


def test_rnd5_now_runs_on_turkish_pages_and_menu_labels_alone_are_not_a_wall(wall_site):
    rnd5 = wall_site.by_id["RND-5"]
    assert rnd5.status != "not_assessed" and rnd5.evidence["text_signatures_language"] == "English and Turkish"
    not_assessed = short(wall_site, [row["url"] for row in rnd5.evidence["text_signatures_not_assessed"]])
    assert not_assessed == ["/de"]  # German is still said to be not assessed, not passed
    flagged = {url for f in rnd5.findings for url in short(wall_site, f.scope["urls"])}
    # "Giriş Yap", "Üye Ol" and "Abone Ol" are in every page's menu, including a 3-word contact page.
    assert "/normal" not in flagged and "/kisa" not in flagged and "/" not in flagged


@pytest.mark.parametrize("text, name", [
    ("Devam etmek için giriş yapın", "login"), ("LÜTFEN GİRİŞ YAPINIZ", "login"),
    ("Bu sayfa sadece üyelerimize açıktır", "login"), ("Tüm çerezleri kabul et", "cookie consent"),
    ("Sitemizde çerezler kullanılmaktadır", "cookie consent"), ("Bu hizmet ülkenizde kullanılamıyor", "geo block"),
    ("Giriş Yap", None), ("Üye Ol", None), ("Abone ol, fırsatları kaçırma", None), ("Çerezli kurabiye tarifi", None),
])
def test_turkish_wall_signatures(text, name):
    matched = [key for key, rx in WALL_SIGNATURES_TR.items() if rx.search(turkish_fold(text))]
    assert matched == ([name] if name else [])


@pytest.mark.parametrize("text, hit", [
    ("Haberin devamını okumak için tıklayın", True), ("Bu içerik abonelere özel", True),
    ("Yazının devamı için abone olun", True), ("Bültenimize abone ol", False), ("Devamı yarın", False),
])
def test_turkish_paywall_signatures(text, hit):
    assert bool(PAYWALL_TR.search(turkish_fold(text))) is hit


# 10. STR-12 ----------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def language_site():
    tr_nav = MENU + ' <a href="/tr/hizmetler/">Hizmetler</a>'
    hreflang = '<link rel="alternate" hreflang="tr" href="{base}/urun"><link rel="alternate" hreflang="en" href="{base}/en/product">'
    routes = {
        # The live case: a Turkish service page whose body is another hospital's English template text.
        "/tr/hizmetler/uyku/": page(f"<h1>Uyku Bozuklukları</h1><p>{EN}</p><p>{EN.replace('Riverside', 'Lakeside')}</p>", nav=tr_nav),
        "/tr/hizmetler/kaygi/": page(f"<h1>Kaygı</h1><p>{TR}</p><p>{TR}</p>", nav=tr_nav),
        "/tr/blog/alinti/": page(f"<h1>Alıntı</h1><p>{TR}</p><p>{TR}</p><p>{TR}</p><blockquote>The only way out is "
                                 f"through, and that is the truth of it for all of us.</blockquote>", nav=tr_nav),
        "/en/about/": page(f"<h1>About</h1><p>{EN}</p><p>{EN}</p>", lang="tr", nav=tr_nav),   # the template ships lang="tr"
        "/tr/taslak/": page(f"<h1>Taslak</h1><p>{TR}</p><p>Lorem ipsum dolor sit amet, consectetur adipiscing elit.</p>", nav=tr_nav),
        "/tr/kurumsal/": page(f"<h1>Kurumsal</h1><p>{TR}</p><p>ŞİRKET ADINIZ burada yer alacak.</p>", nav=tr_nav),
        "/urun": Response(body='<!doctype html><html><head><title>Ürün</title>HREFLANG</head><body><main><h1>Ürün</h1>'
                               f'<p>{EN}</p><p>{EN}</p></main></body></html>'),
        "/dilsiz": Response(body=f"<!doctype html><html><head><title>X</title></head><body><main><p>{EN}</p></main></body></html>"),
        "/tr/kisa/": page("<h1>Kısa</h1><p>Yakında.</p>", nav=tr_nav),
    }
    with_base = dict(routes)

    def fill(site, request):
        base = "http://" + request.headers.get("host", "")
        return Response(body=routes["/urun"].body.replace("HREFLANG", hreflang.format(base=base)))

    with_base["/urun"] = fill
    return audit(with_base)


def test_str12_a_turkish_page_whose_body_is_english_placeholder_text_is_reported(language_site):
    str12 = language_site.by_id["STR-12"]
    [finding] = [f for f in str12.findings if "another language" in f.title]
    assert "declared Turkish, written mostly in English" in finding.title
    assert finding.severity.value == "S3" and finding.confidence.value == "estimated"
    rows = {row["url"].removeprefix(language_site.base): row for row in finding.evidence["pages"]}
    assert set(rows) == {"/tr/hizmetler/uyku/", "/urun"}
    uyku = rows["/tr/hizmetler/uyku/"]
    assert uyku["declared"] == "tr" and uyku["main_content_language"] == "en" and uyku["foreign_share"] == 1.0
    assert uyku["declared_by"] == {"url_folder": "tr", "hreflang_for_this_url": None, "html_lang": "tr"}
    assert uyku["samples"][0].startswith("Welcome to Riverside General Hospital")  # a short sample to read
    assert len(uyku["samples"][0]) <= 200 and uyku["words"]["foreign"] > 100 and uyku["words"]["declared"] == 0
    # Declared by the page's own hreflang entry when there is no language folder and no <html lang>.
    assert rows["/urun"]["declared_by"] == {"url_folder": None, "hreflang_for_this_url": "tr", "html_lang": None}
    markdown = render_markdown(language_site.result, language_site.gates, language_site.checks)
    assert "mostly in another language than they declare" in markdown


def test_str12_does_not_report_matching_pages_a_quotation_or_a_page_filed_under_its_real_language(language_site):
    str12 = language_site.by_id["STR-12"]
    reported = {url for f in str12.findings if "another language" in f.title for url in short(language_site, f.scope["urls"])}
    assert not reported & {"/tr/hizmetler/kaygi/", "/tr/blog/alinti/", "/en/about/", "/"}
    not_assessed = {row["url"].removeprefix(language_site.base): row["reason"] for row in str12.evidence["language_not_assessed"]}
    assert "declares no language" in not_assessed["/dilsiz"] and "words of main content" in not_assessed["/tr/kisa/"]
    assert str12.coverage["not_assessed"]  # said, not silently passed


def test_str12_reports_placeholder_and_template_text(language_site):
    [finding] = [f for f in language_site.by_id["STR-12"].findings if "placeholder" in f.title]
    assert finding.severity.value == "S2" and finding.confidence.value == "verified"
    rows = {row["url"].removeprefix(language_site.base): row["found"] for row in finding.evidence["pages"]}
    assert set(rows) == {"/tr/taslak/", "/tr/kurumsal/"}
    assert {hit["phrase"] for hit in rows["/tr/taslak/"]} == {"lorem ipsum", "dolor sit amet", "consectetur adipiscing"}
    assert rows["/tr/kurumsal/"] == [{"phrase": "şirket adınız", "sample": "ŞİRKET ADINIZ burada yer alacak."}]
    assert "describe your services" not in json.dumps(rows)  # only the listed phrases, each with its passage
    assert any("Lorem ipsum dolor sit amet" in hit["sample"] for hit in rows["/tr/taslak/"])


def test_str12_is_a_registered_check_everywhere_checks_are_listed():
    from maya_audit.coverage import PAGE_DEPENDENT, RULES

    assert "STR-12" in PAGE_DEPENDENT and "STR-12" in RULES
    outcome = audit({"/tr/a/": page(f"<p>{TR}</p>")})
    ids = [check.check_id for check in outcome.checks]
    assert ids.index("STR-12") == ids.index("STR-11") + 1 and len([i for i in ids if i.startswith("STR-")]) == 23  # STR-16 to STR-23 added 2026-10-07
    assert outcome.by_id["STR-12"].status in ("pass", "partial")


@pytest.mark.parametrize("text, language", [
    (TR, "tr"), (EN, "en"), (DE, "de"), ("Hemen ara", None), ("Riverside General Hospital 2024", None),
    ("Şirketimiz müşterilerine güvenli alışveriş imkânı sağlamaktadır", "tr"),
])
def test_block_language(text, language):
    assert block_language(text) == language


def test_language_share_and_placeholder_helpers():
    share = language_share([TR, EN, EN, "Tamam"], "tr")
    assert share["foreign_languages"] == {"en": 2 * len(EN.split())} and 0.6 < share["share"] < 0.75
    assert share["words"]["unclassified"] == 1 and len(share["samples"]) == 2
    assert language_share(["Kısa"], "tr")["share"] is None
    assert placeholder_hits(["Hello World! Welcome to WordPress."]) and not placeholder_hits([TR, EN.split(".")[0]])


# 7 again: the real homepage shape ------------------------------------------------------------------
def test_str4_the_homepage_headline_price_counts_even_when_most_pages_repeat_the_amount_in_a_banner():
    """magazanolsun.com, 2026-10-06: markup 95000 / 190000, headline "50.000 TL'den Başlayan Fiyatlar ...".

    Every page carries two banners, one with "29 USD" and one that repeats "50.000 TL". Ignoring a price
    because of its amount alone would hide the homepage's own headline; it is ignored only inside the banner.
    """
    banners = ('<div class="ust-bant">Mağazanı hemen aç: aylık 29 USD</div>'
               "<div class=\"kampanya\">Kampanya: 50.000 TL'den başlayan paketler</div>")
    markup = ('<script type="application/ld+json">' + json.dumps({"@context": "https://schema.org", "@graph": [
        {"@type": "Product", "name": "Mağazanolsun - PREMIUM", "offers": {
            "@type": "Offer", "price": "95000", "priceCurrency": "TRY", "availability": "https://schema.org/InStock"}},
        {"@type": "Product", "name": "Mağazanolsun - PREMIUM PLUS", "offers": {
            "@type": "Offer", "price": "190000", "priceCurrency": "TRY", "availability": "https://schema.org/InStock"}}]})
        + "</script>")
    others = ["/nasil-calisir", "/paketler", "/basari-hikayeleri", "/basinda-biz", "/isletme", "/ornek-sayfalar"]
    routes = {"/": page(banners + "<h1>50.000 TL'den Başlayan Fiyatlar ile Yeni Nesil E-ticarete İlk Adımınızı Atın</h1>"
                        + f"<p>{TR}</p>" + links(others), head=markup, title="Mağazanolsun | Yeni Nesil E-Ticaret"),
              "/etkinlik-sayfasi": page(banners + f"<h1>Etkinlik</h1><p>{TR}</p>", head=product("0")),
              **{path: page(banners + f"<h1>{path}</h1><p>{TR}</p>") for path in others}}
    outcome = audit(routes)
    str4 = outcome.by_id["STR-4"]
    assert set(str4.evidence["site_wide_prices"]) == {"29 usd", "50.000 tl"}  # both amounts are on every page
    [finding] = [f for f in str4.findings if "price differs" in f.title]
    assert short(outcome, finding.scope["urls"]) == ["/"] and finding.severity.value == "S2"
    assert [(row["schema_value"], [shown["text"] for shown in row["visible"] if shown["where"] == "main content"],
             row["site_wide_prices_ignored"]) for row in finding.evidence["values"]] == [
        ("95000", ["50.000 TL"], ["29 USD"]), ("190000", ["50.000 TL"], ["29 USD"])]
    # The event page shows only the banners: its price of 0 is "not shown", and that is recorded where it can be read.
    rows = {(row["url"].removeprefix(outcome.base), row["schema_value"]): row for row in str4.evidence["price_comparisons"]}
    assert rows[("/etkinlik-sayfasi", "0")]["outcome"] == "not_visible"
    assert rows[("/etkinlik-sayfasi", "0")]["site_wide_prices_ignored"] == ["29 USD", "50.000 TL"]
    assert rows[("/", "95000")]["outcome"] == "conflict" and str4.evidence["price_comparisons_count"] == 3


# 8 again: placeholder phrases in names ---------------------------------------------------------------
def test_str12_a_page_or_menu_entry_named_like_a_placeholder_is_not_placeholder_text():
    nav = MENU + ' <a href="/ornek-sayfalar">Örnek Sayfalar</a> <a href="/sample-text">Sample text</a>'
    routes = {
        # magazanolsun.com/ornek-sayfalar: a real page whose title, heading and menu label say "Örnek Sayfalar".
        "/ornek-sayfalar": page(f"<h1>Örnek Sayfalar</h1><h2>Örnek metin şablonları</h2><p>{TR}</p>"
                                '<a href="/x">Lorem ipsum eklentisi</a><button>Your text here</button>',
                                title="Örnek Sayfalar", nav=nav),
        "/gercek-taslak": page(f"<h1>Hizmetlerimiz</h1><p>{TR}</p><p>Buraya metin gelecek, içerik eklenecek.</p>", nav=nav),
    }
    outcome = audit(routes)
    [finding] = [f for f in outcome.by_id["STR-12"].findings if "placeholder" in f.title]
    rows = {row["url"].removeprefix(outcome.base): row["found"] for row in finding.evidence["pages"]}
    assert set(rows) == {"/gercek-taslak"}  # headings, link labels and buttons are names, not leftover text
    assert {hit["phrase"] for hit in rows["/gercek-taslak"]} == {"buraya metin", "içerik eklenecek"}


def test_placeholder_list_no_longer_holds_phrases_that_are_also_ordinary_page_names():
    from maya_audit.config import PLACEHOLDER_TEXT

    assert not {"örnek sayfa", "sample page", "hello world!"} & set(PLACEHOLDER_TEXT)
    assert {"lorem ipsum", "your company name", "şirket adınız", "içerik eklenecek"} <= set(PLACEHOLDER_TEXT)


def test_company_name_in_privacy_prose_is_not_a_template_slot():
    assert not placeholder_hits(["This may include your company name and job title."])
    assert not placeholder_hits(["Please enter your business name to register."])
    assert placeholder_hits(["Copyright [Your Company Name]. All rights reserved."])
    assert placeholder_hits(["Your company name"])
    assert placeholder_hits(["Lorem ipsum dolor sit amet."])
