"""team-preview-16, run 1: seven false alarms of the owner's real-site test (docs/FALSE-ALARMS.md FA-025 to FA-031;
DECISIONS 216, 217, 220 to 224; LG-84, LG-87 to LG-91).

- ACC-4 does not blame a firewall when the browser also got an empty or error page (FA-025).
- A redirect loop that ends once the site's own cookie is sent back is a cookie loop, not "never resolves" (FA-026).
- The brand guessed from the address is not a confirmed brand; the site's own spelling wins (FA-027).
- STR-5 does not count copyright years or branch names as other names (FA-028).
- noindex on a utility page (a QR menu, a print page) that the menu does not link is a note, not a Blocker (FA-029).
- A calculator's input grid or an empty table inside a form is not a table to mark up; a grid is named by its heading
  (FA-030).
- STR-9 guesses the language from the main text, and a page in two languages is mixed, not wrongly declared (FA-031).

Every site is made up and held in memory or in mock transports; nothing is fetched from the internet.
"""
import json

import httpx

from maya_audit.probes import BROWSER_NOT_REAL_REASON, BROWSER_USER_AGENT
from test_brand_and_launch_gate import no_lookups  # noqa: F401
from test_false_alarms import KAFE
from test_round2_empty_and_googlebot import GOOGLEBOT, by_title, ua_site


# -- FA-025: the browser also got an empty page (DECISIONS 216) ------------------------------------------------------------
def test_googlebot_500_where_the_browser_got_an_empty_page_is_not_a_firewall_finding(no_lookups):
    outcome = ua_site(browser_gets_empty=True)
    checks = [r for r in outcome.result.requests if r.purpose == "ua_check"]
    assert len(checks) <= 6 and {r.user_agent for r in checks} == {BROWSER_USER_AGENT, GOOGLEBOT}
    acc4 = outcome.by_id["ACC-4"]
    assert acc4.findings == [] and acc4.status == "not_assessed"
    pairs = outcome.result.access.ua_check["pairs"]
    assert pairs and all(p["outcome"] == "browser_not_real" and not p["assessed"] for p in pairs)
    assert all(p["reason"] == BROWSER_NOT_REAL_REASON for p in pairs)
    assert BROWSER_NOT_REAL_REASON == ("the browser also got an empty or error page: a server fault (see IDX-1), not a "
                                       "difference made for Googlebot")
    assert [u["reason"] for u in acc4.evidence["urls_not_assessed"]] == [BROWSER_NOT_REAL_REASON] * len(pairs)
    # No firewall fix anywhere; the error text Googlebot's user agent was shown is still IDX-1's finding.
    assert "WAF" not in str(acc4.findings)
    [shown] = by_title(outcome.by_id["IDX-1"], "server error message")
    assert "Googlebot" in shown.evidence["pages"][0]["seen_by"] and "u812345" not in str(shown.evidence)


def test_googlebot_500_where_the_browser_got_a_real_page_is_still_high(no_lookups):
    outcome = ua_site()
    [finding] = outcome.by_id["ACC-4"].findings
    assert finding.severity.value == "S3" and "Allow Googlebot in your WAF" in finding.how_to_fix
    assert not [p for p in outcome.result.access.ua_check["pairs"] if p.get("outcome") == "browser_not_real"]
    assert KAFE + "/bos/" not in outcome.result.access.ua_check["urls"]  # an empty page is not sampled


# -- FA-026: a redirect loop that ends once the site's own cookie is sent back (DECISIONS 217) -----------------------------
def cookie_site(cookie_opens=True):
    """/ticari answers 301 to itself with Set-Cookie (two headers, one with a dated Expires), and the page once the
    cookie comes back; with `cookie_opens` False it loops whatever is sent."""
    from maya_audit.audit import run_audit
    from maya_audit.config import CrawlConfig
    from test_false_alarms import QUIET, answer

    sent_cookies = []

    def respond(request):
        path = request.url.path
        if path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n", headers={"content-type": "text/plain"})
        if path == "/sitemap.xml":
            return httpx.Response(404, text="none")
        if path == "/ticari":
            cookie = request.headers.get("cookie")
            sent_cookies.append(cookie)
            if cookie_opens and cookie and "seen=1" in cookie and "lang=tr" in cookie:
                return answer(title="Ticari | Demo Kart")
            return httpx.Response(301, headers=[("location", "/ticari"), ("set-cookie", "seen=1; Path=/; HttpOnly"),
                                                ("set-cookie", "lang=tr; Expires=Wed, 21 Oct 2026 07:28:00 GMT; Path=/")])
        if path == "/":
            return answer('<a href="/ticari">Ticari</a>', title="Demo Kart")
        return answer(title="Yok", status=404)

    outcome = run_audit("https://demo-kart.test/", CrawlConfig(**{**QUIET, "max_pages": 10}), httpx.MockTransport(respond))
    outcome.by_id = {c.check_id: c for c in outcome.checks}
    outcome.sent_cookies = sent_cookies
    return outcome


def test_a_loop_that_loads_with_the_sites_own_cookie_is_a_cookie_loop_not_a_blocker(no_lookups):
    from maya_audit.fetcher import COOKIE_NOT_KEPT
    from maya_audit.report import build_report
    import json

    outcome = cookie_site()
    idx3 = outcome.by_id["IDX-3"]
    [finding] = idx3.findings
    assert finding.title == ("1 URL(s) loop in Maya's cookie-less checks; with the cookie the site sets, "
                             "the page loads")
    assert (finding.severity.value, finding.confidence.value) == ("S3", "verified")
    assert finding.scope["urls"] == ["https://demo-kart.test/ticari"]
    assert finding.how_to_fix.startswith("Compare the logged cookie-less and cookie-enabled requests")
    assert finding.notes[0].startswith("Maya observed different outcomes with and without the site")
    assert not [f for check in outcome.checks for f in check.findings if f.severity.value == "S1"]
    walk = finding.evidence["cookie_walks"]["https://demo-kart.test/ticari"]
    assert walk["outcome"] == "resolves" and [h["set_cookie"] for h in walk["hops"]] == [True, False]
    assert [h["cookie_sent"] for h in walk["hops"]] == [False, True]
    # The three cookie-less re-checks stay; one cookie walk of at most 10 hops, with Maya's own user agent.
    requests = outcome.result.requests
    cookie_requests = [r for r in requests if r.purpose == "redirect_recheck_cookies"]
    assert len([r for r in requests if r.purpose == "redirect_recheck" and r.url.endswith("/ticari")]) == 3
    assert 1 <= len(cookie_requests) <= 10 and {r.user_agent for r in cookie_requests} == {outcome.result.user_agent}
    # Only the cookies the site set, both of them (the dated one not split at its comma); no value is kept or written.
    assert "seen=1; lang=tr" in outcome.sent_cookies
    assert [r.extra_headers.get("Cookie") for r in cookie_requests] == [None, COOKIE_NOT_KEPT]
    int4 = next(gate for gate in outcome.gates if gate.check_id == "INT-4")
    assert int4.state == "compliant", int4.summary
    written = json.dumps(build_report(outcome.result, outcome.gates, outcome.checks), default=str)
    assert "seen=1" not in written and "lang=tr" not in written


def test_a_loop_that_loops_with_the_cookie_too_stays_a_blocker(no_lookups):
    outcome = cookie_site(cookie_opens=False)
    [loop] = outcome.by_id["IDX-3"].findings
    assert loop.title == "1 redirect loop(s) observed in the tested native client" and loop.severity.value == "S1"
    walk = loop.evidence["cookie_walks"]["https://demo-kart.test/ticari"]
    assert walk["outcome"] == "loops" and len(walk["hops"]) <= 10


# -- FA-027: the brand guessed from the address, posted back unchanged, was "typed" and "confirmed" (DECISIONS 220) -------
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

from maya_audit import brand  # noqa: E402
from maya_audit.dataforseo import insights  # noqa: E402
from test_brand_and_launch_gate import keyword_section, page, table  # noqa: E402
from test_false_alarms import audited  # noqa: E402
from test_web_app import web  # noqa: E402,F401

LEZZETLI = "https://lezzetliyemekevi.test"
STATIC = Path(__file__).resolve().parent.parent / "maya_audit_web" / "static"


def lezzetli_site(site_name=True):
    """Five pages, each with og:site_name "Lezzetli Yemek Evi" (or none); the address is the name glued into one word."""
    head = '<meta property="og:site_name" content="Lezzetli Yemek Evi">' if site_name else ""
    links = "".join(f'<a href="/tarif-{n}">Tarif {n}</a>' for n in range(1, 5))
    routes = {"/": page("Ana Sayfa", f"<h2>Yemek tarifleri</h2>{links}", head=head)}
    routes.update({f"/tarif-{n}": page(f"Tarif {n}", "<h2>Yemek tarifleri</h2>", head=head) for n in range(1, 5)})
    return audited(routes, start=LEZZETLI + "/", sitemap=("/",), max_pages=10)


def test_a_typed_glued_name_takes_the_sites_spelling_and_a_search_for_its_start_is_a_brand_search(no_lookups, tmp_path):
    outcome = lezzetli_site()
    assert brand.resolve(outcome.result) == {"name": "Lezzetli Yemek Evi", "source": "site", "confirmed": False,
                                             "found_in": "og_site_name", "pages": 5}
    # The name typed glued into one word is the site's own name: the site's spelling, still typed and confirmed.
    assert brand.resolve(outcome.result, "Lezzetliyemekevi") == {"name": "Lezzetli Yemek Evi", "source": "typed",
                                                                 "confirmed": True, "found_in": None, "pages": None}
    assert brand.same_name("LEZZETLİ yemek evi", "lezzetliyemekevi") and not brand.same_name("Lezzetli", "Lezzetli Yemek")
    # Healthy: a name typed by hand that is not the site's stays as typed.
    assert brand.resolve(outcome.result, "Demo Kafe") == {"name": "Demo Kafe", "source": "typed", "confirmed": True,
                                                          "found_in": None, "pages": None}
    site_section = keyword_section(tmp_path / "site", LEZZETLI + "/", ("lezzetli yemek", 900, 1), ("ucuz uçak bileti", 700, 30))
    insights.apply_relevance(site_section, brand=None, domain="lezzetliyemekevi.test", texts=["Yemek tarifleri"],
                             brand_info=brand.resolve(outcome.result))
    # Generic partial names no longer establish our brand. Full names/confirmed aliases still do.
    assert table(site_section)["evidence"]["data"]["keyword_assessments"][0]["category"] == "ambiguous"
    # A one-word brand (no site name to respell it): a search written as its start, of two or more words, names it.
    glued = brand.resolve(lezzetli_site(site_name=False).result, "Lezzetliyemekevi")
    assert glued["name"] == "Lezzetliyemekevi"
    section = keyword_section(tmp_path, LEZZETLI + "/", ("lezzetli yemek", 900, 1), ("lezzetli yemek evi menü", 300, 1),
                              ("yemek tarifleri", 5000, 8), ("ucuz uçak bileti", 700, 30))
    insights.apply_relevance(section, brand=None, domain="lezzetliyemekevi.test", texts=["Yemek tarifleri"], brand_info=glued)
    data = table(section)["evidence"]["data"]
    kept = {row[0]: row[-1] for row in data["table"]["rows"]}
    assert kept["lezzetli yemek evi menü"] == "branded"
    assert next(a for a in data['keyword_assessments'] if a['keyword']=='lezzetli yemek')['category']=='ambiguous'
    assert kept.get("yemek tarifleri") != "branded" and not data["unrelated"]["rows"]
    assert next(a for a in data['keyword_assessments'] if a['keyword']=='ucuz uçak bileti')['uncertain']
    assert insights.classify_keyword("adile sultan ev", {"adilesultanevyemekleri"}, set(), False, glued="adilesultanevyemekleri") == "branded"
    assert insights.classify_keyword("adile", {"adilesultanevyemekleri"}, set(), False, glued="adilesultanevyemekleri") != "branded"


def test_the_address_suggestion_posted_or_saved_unchanged_is_not_a_confirmed_brand(web):
    from test_web_app import API, SHOP, plan, start

    client = web()
    # The card's suggestion for demo-shop is "Demo Shop"; posted back unchanged it is not the run's brand.
    posted = plan(client, brand_name="Demo Shop")
    assert posted["business"]["brand_name"] == "Demo Shop" and posted["business"]["brand_confirmed"] is False
    assert posted["paid_options"]["brand"] is None
    report = json.loads((client.app.state.runner.artifacts(start(client, posted)["id"]) / "report.json").read_text(encoding="utf-8"))
    assert report["brand"]["source"] == "site" and report["brand"]["confirmed"] is False
    # Saved in the profile (spaces and case aside), it is treated as no value.
    client.put(f"{API}/projects/{SHOP}/profile", json={"brand_name": "demoshop"})
    saved = plan(client)
    assert saved["business"]["brand_confirmed"] is False and saved["paid_options"]["brand"] is None
    assert saved["business"]["brand_name"] == "Demo Shop"
    # Healthy: a name typed by hand is typed and confirmed.
    typed = plan(client, brand_name="Demo Dükkan")
    assert typed["business"]["brand_confirmed"] is True and typed["paid_options"]["brand"] == "Demo Dükkan"
    # The card sends the brand only when it was edited, and never saves an unedited suggestion.
    script = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "if (brandEdited()) body.brand_name = brandInput.value.trim(); else delete body.brand_name;" in script
    assert "brandName !== undefined ? brandName : (saved.brand_name || \"\")" in script


# -- FA-028: copyright years and branch names counted as other names of the brand (DECISIONS 221) ------------------------
from maya_audit.checks.structure import _norm, str5_entity  # noqa: E402
from maya_audit.structure_data import StructureData  # noqa: E402
from test_false_alarms import CFG, ROOT, html, ld, site  # noqa: E402


def kafe_names(home_org=None, footer="© 2023-2025 Demo Kafe. Tüm hakları saklıdır.", menu_org=None):
    def branch(name, slug):
        return html("<h1>Şube</h1><p>Adres</p>", title=f"{name} | Demo Kafe",
                    head=ld({"@type": "Organization", "name": name, "url": ROOT + slug}) + '<meta property="og:site_name" content="Demo Kafe">')
    head = '<meta property="og:site_name" content="Demo Kafe">'
    home_head = head + (ld({"@type": "Organization", "name": home_org, "url": ROOT + "/"}) if home_org else "")
    pages = {"/": html("<h1>Demo Kafe</h1><p>Kahve</p>", title="Demo Kafe", head=home_head, footer=footer),
             "/menu": html("<h1>Menü</h1><p>Kahve</p>", title="Menü | Demo Kafe", head=head + (ld({"@type":"Organization", "name":menu_org, "url":ROOT+"/menu"}) if menu_org else "")),
             "/sube/kadikoy": branch("Demo Kafe Kadıköy Şube", "/sube/kadikoy"),
             "/sube/moda": branch("Demo Kafe Kadıköy Şube", "/sube/moda")}
    result, made = site(pages)
    return str5_entity(result, CFG, made, set(), StructureData())


def test_copyright_years_and_branch_names_are_not_other_names_of_the_brand():
    from maya_audit_web import wording

    check = kafe_names()
    assert not [f for f in check.findings if f.title.startswith("The brand is named")]
    footer = next(s for s in check.evidence["name_sources"] if s["source"] == "footer legal name")
    assert footer["value"] == "Demo Kafe"
    assert check.evidence["branches_not_counted"] == ["Demo Kafe Kadıköy Şube"]
    assert check.summary.endswith("Branch names are not counted as other names: Demo Kafe Kadıköy Şube.")
    turkish, ok = wording.line(check.summary, "tr", "STR-5")
    assert ok and turkish.endswith("Şube adları başka ad sayılmadı: Demo Kafe Kadıköy Şube.")
    # A capital dotted İ is one letter: "İçerenköy" is not split into "i çerenköy".
    assert _norm("Ataşehir-İçerenköy") == "ataşehir içerenköy"
    other = kafe_names(footer="Copyright © 2024, Demo Kafe").evidence["name_sources"]
    assert next(s["value"] for s in other if s["source"] == "footer legal name") == "Demo Kafe"


def test_three_different_names_are_still_reported_and_a_branch_name_on_the_homepage_counts():
    # A third independent own-entity label still conflicts; a copyright holder alone does not.
    check = kafe_names(home_org="Demo Kafe Kadıköy Şube", footer="© 2024 Rights Holder Ltd", menu_org="Kafe Demo Kahve Evi")
    [names] = [f for f in check.findings if f.title.startswith("The brand is named")]
    assert names.title == "The brand is named 3 different ways"
    assert {v["name"] for v in names.evidence["variants"]} == {"Demo Kafe", "Demo Kafe Kadıköy Şube", "Kafe Demo Kahve Evi"}
    assert names.evidence["branches_not_counted"] == []


# -- FA-029: noindex on a QR-menu page was a Blocker because the sitemap listed it (DECISIONS 222) -------------------------
from test_false_alarms import HTML_TYPE, TR  # noqa: E402

NOINDEX = '<meta name="robots" content="noindex">'


def kafe_page(title, body="", head="", nav=""):
    return httpx.Response(200, headers=HTML_TYPE, text=(
        f'<!doctype html><html lang="tr"><head><title>{title}</title>{head}</head><body><header><nav><a href="/">Ana Sayfa</a>'
        f'{nav}</nav></header><main><h1>{title}</h1><p>{TR}</p>{body}</main></body></html>'))


def noindexed(path, in_menu=False):
    nav = f'<a href="{path}">Sayfa</a>' if in_menu else ""
    routes = {"/": kafe_page("Demo Kafe", '<a href="/menu">Menü</a>', nav=nav), "/menu": kafe_page("Menü | Demo Kafe", nav=nav),
              path: kafe_page("Sayfa | Demo Kafe", head=NOINDEX, nav=nav)}
    outcome = audited(routes, sitemap=("/", "/menu", path))
    return [f for f in outcome.by_id["ACC-3"].findings if "noindex" in f.title]


def test_noindex_on_a_qr_menu_page_listed_in_the_sitemap_is_a_note_and_in_the_menu_a_blocker(no_lookups):
    from maya_audit_web import wording

    [note] = noindexed("/qr-menu/")
    assert note.title == ("noindex via meta on 1 utility page(s) (such as a QR menu or a print page): check that this is "
                          "intended")
    assert note.severity.value == "S3" and note.scope["urls"] == [KAFE + "/qr-menu/"]
    assert note.how_to_fix.startswith("If this page should appear in search and AI answers, remove the noindex.")
    assert wording.title("ACC-3", note.title, "tr") == (
        "1 yardımcı sayfada (QR menü veya yazdırma sayfası gibi) meta ile noindex: bunun bilerek yapıldığını kontrol edin", True)
    assert wording.title("ACC-3", note.title, "en")[0].startswith("noindex via meta on 1 utility page (such as")
    # The same page linked from the main menu is put forward by the site: a Blocker, as before.
    [blocker] = noindexed("/qr-menu/", in_menu=True)
    assert blocker.title == "noindex via meta on 1 page(s)" and blocker.severity.value == "S1"


def test_noindex_on_an_ordinary_page_listed_in_the_sitemap_is_one_s3_finding(no_lookups):
    # H26 / CR-33 (W1): the owner's intent is not known from the sitemap alone, so the noindex is S3. Review G16: that
    # the sitemap lists it is the same fact, said in that one finding (it was a second, S2 finding above the directive).
    # A key page or a page the menu links stays S1 (DECISIONS 222).
    [noindex] = noindexed("/hakkimizda/")
    assert noindex.title == "noindex via meta on 1 page(s) the sitemap lists: check that this is intended"
    assert noindex.severity.value == "S3" and noindex.evidence["listed_in_sitemaps"]
    assert "sitemap" in noindex.how_to_fix


# -- FA-030: a calculator's input grid and the empty table it fills were "tables to mark up" (DECISIONS 223) -------------
from maya_audit.analysis import analyze_html  # noqa: E402
from maya_audit.checks.structure import CALCULATOR_LEFT_OUT, str8_semantic_tables  # noqa: E402
from maya_audit.models import to_jsonable  # noqa: E402
from maya_audit.report import page_item, page_sentence  # noqa: E402

CALCULATOR = ('<h2>Faiz hesapla</h2><section id="birikim" class="hesap"><div class="hesap__form">'
              + "".join(f'<div class="satir"><span>{label}</span><span>{value}</span><input type="range" min="0" max="9"></div>'
                        for label, value in (("Hesap açılış tutarı", "10.000 TL"), ("Vade", "32 gün"), ("Faiz oranı", "%45")))
              + "</div></section>")
PRICES = ('<h2>Paket fiyatları</h2><div class="paket-liste">'
          + "".join(f'<div class="paket"><span>{name}</span><span>{price}</span><span>Aylık</span></div>'
                    for name, price in (("Başlangıç", "90 TL"), ("Standart", "150 TL"), ("Kurumsal", "400 TL"))) + "</div>")


def str8_on(body, path="/hesapla/"):
    result, pages = site({"/": html(f"<h1>Demo Banka</h1><p>{TR}</p>"), path: html(f"<h1>Demo Banka</h1><p>{TR}</p>{body}")})
    return str8_semantic_tables(result, CFG, pages, set(), set())


def test_a_calculators_grid_and_an_empty_table_in_a_form_are_left_out():
    check = str8_on(CALCULATOR)
    assert check.findings == []
    [left] = check.evidence["grids_left_out"]
    assert left["why"] == CALCULATOR_LEFT_OUT == "a calculator or form: its rows are input fields, not a table of facts"
    form = str8_on('<form action="/taksit"><label>Tutar <input name="t"></label><table class="sonuc"></table></form>')
    assert form.findings == [] and form.evidence["empty_tables"] == 0
    assert [row["why"] for row in form.evidence["grids_left_out"]] == [CALCULATOR_LEFT_OUT]
    # An empty table in the block of a calculator written with <output> and no <form>.
    block = str8_on('<div class="taksit"><div class="alanlar"><select><option>3</option></select><output>0</output></div>'
                    '<table class="plan"></table></div>')
    assert block.findings == [] and block.evidence["grids_left_out"][0]["why"] == CALCULATOR_LEFT_OUT


def test_a_price_grid_without_controls_is_reported_and_named_by_its_heading():
    from maya_audit_web import strings

    check = str8_on(PRICES, path="/paketler/")
    [finding] = check.findings
    [grid] = finding.evidence["grids"]
    assert grid["heading"] == "Paket fiyatları" and grid["has_controls"] is False and " > " in grid["selector"]
    line = page_sentence(page_item(to_jsonable(finding), ROOT + "/paketler/"))
    assert line == "<div> grid under “Paket fiyatları”; first row: “Başlangıç | 90 TL | Aylık”"
    strings.set_language("tr")
    try:
        assert strings.t("bypage.div_grid_heading", **page_item(to_jsonable(finding), ROOT + "/paketler/")["values"]) == (
            "“Paket fiyatları” başlığı altında <div> ızgarası; ilk satır: “Başlangıç | 90 TL | Aylık”")
    finally:
        strings.set_language("en")
    # With no heading before it, a short name of its own, never the whole path.
    bare = analyze_html('<html><body><div class="wrap"><div class="paket-liste">' + PRICES.split('<div class="paket-liste">')[1]
                        + "</div></body></html>", ROOT + "/")
    [grid] = bare["div_grids"]
    assert grid["heading"] is None and grid["label"] == "div.paket-liste"
    item = page_item({"check_id": "STR-8", "title": "1 page(s) lay out pricing or spec comparisons as <div> grids instead of <table>", "id": "x",
                      "evidence": {"grids": [{"url": ROOT + "/", **grid}]}, "scope": {"urls": [ROOT + "/"]}}, ROOT + "/")
    assert page_sentence(item) == "<div> grid at div.paket-liste; first row: “Başlangıç | 90 TL | Aylık”"


# -- FA-031: a bilingual form page was "a <html lang> that does not match the content language" (DECISIONS 224) ----------
from maya_audit.checks.structure import str9_language  # noqa: E402

NOTICE_EN = ("Please read this notice before you fill in the form. The data that you give us is used only for this "
             "application and it will not be shared with anyone. You can ask us to delete it at any time, and we will "
             "answer within thirty days. ")
NOTICE_TR = ("Formu doldurmadan önce bu metni okuyun. Bize verdiğiniz bilgiler yalnızca bu başvuru için kullanılır ve "
             "başka bir kişi ile paylaşılmaz. ")
ENGLISH_PAGE = ("Our branch opens at nine and closes at six. You can open an account with your passport, and we will "
                "send your card to the address that you give us. The fee for the card is shown on this page. ")


def lang_of(body, lang="tr"):
    result, pages = site({"/": html(f"<h1>Demo Banka</h1><p>{TR}</p>"), "/form/": html(f"<h1>Başvuru</h1>{body}", lang=lang)})
    check = str9_language(result, CFG, pages, set(), StructureData())
    mismatch = [f for f in check.findings if "does not match the content language" in f.title]
    return check, mismatch, {row["url"]: row for row in check.evidence["lang_mismatch_not_assessed"]}


def test_a_bilingual_notice_is_mixed_language_and_a_short_page_is_not_judged():
    from maya_audit_web import wording

    check, mismatch, not_assessed = lang_of(f"<p>{NOTICE_EN * 4}</p><p>{NOTICE_TR * 2}</p>")
    row = not_assessed[ROOT + "/form/"]
    assert mismatch == [] and row["detected"] == "en"
    assert row["stopword_hits"]["en"] >= 2 * row["stopword_hits"]["tr"] and row["stopword_hits"]["tr"] >= 8
    assert row["reason"] == (f"the page holds the declared language too ({row['stopword_hits']['tr']} of its common words): "
                             "mixed languages, not a wrong declaration")
    assert wording.line(row["reason"], "tr")[0].startswith("sayfada beyan edilen dil de var (yaygın kelimelerinden ")
    _, mismatch, not_assessed = lang_of("<p>" + " ".join(ENGLISH_PAGE.split()[:60]) + "</p>")
    assert mismatch == [] and not_assessed[ROOT + "/form/"]["reason"].startswith("too little main text (")
    assert not_assessed[ROOT + "/form/"]["reason"].endswith(" words, need 150)")
    assert wording.line("too little main text (61 words, need 150)", "tr") == ("ana metin çok az (61 kelime, en az 150 gerekir)", True)


def test_a_long_english_page_declared_turkish_is_still_reported():
    _, [mismatch], _ = lang_of(f"<p>{ENGLISH_PAGE * 8}</p>")
    [row] = mismatch.evidence["pages"]
    assert (row["declared"], row["detected"]) == ("tr", "en") and row["main_words"] >= 150
