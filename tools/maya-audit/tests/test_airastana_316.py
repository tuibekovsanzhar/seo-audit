"""Fixes found on the airastana.com audit (DECISIONS 316): one page limit for both readers, one version of each page
across country/language folders, Imperva's block page recognised (live and in saved data), the airline business type,
the same four summary tiles, a plain sitemap line, "Teyit edin" explained, the headline's grammar and one Turkish
instruction form. Fake sites, a made-up Firecrawl and hand-made reports only; nothing is requested."""
from __future__ import annotations

import json
import re
from pathlib import Path

import httpx

from maya_audit import business_types as bt, client_selection as cs, locales
from maya_audit.audit import run_audit
from maya_audit.classify import classify_fetch, identify_blocker
from maya_audit.config import CrawlConfig
from maya_audit.firecrawl import Options, reader
from maya_audit.analysis import analyze_html
from maya_audit.models import FetchClass, to_jsonable
from maya_audit.reassess_rules import apply as reassess, saved_block_page
from maya_audit.report import build_report
from maya_audit.scratchpad import CRAWLED, FrontierUrl, Scratchpad
from test_deadline_hosted_hardening import QUIET
from test_firecrawl import Firecrawl, client_for, no_lookups  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
HTML = {"content-type": "text/html; charset=utf-8"}
FOLDERS = ["global-en", "global-ru", "kaz-kk", "uk-ru", "jp-ja"]
PAGES = ["information/about-us", "information/baggage-allowance", "check-in/online", "information/fares-and-fare-rules",
         "mmb/booking-details", "information/airports"]
AIR = "https://air.test"
TEXT = "<p>" + "Our flights connect the region with daily departures and helpful service. " * 12 + "</p>"
INCAPSULA = ('<html style="height:100%"><head><META NAME="ROBOTS" CONTENT="NOINDEX, NOFOLLOW"><meta name="format-detection" '
             'content="telephone=no"></head><body style="margin:0px;height:100%"><iframe id="main-iframe" '
             'src="/_Incapsula_Resource?SWUDNSAI=31&xinfo=4" frameborder=0 width="100%" height="100%">Request unsuccessful. '
             'Incapsula incident ID: 656000250164420567-126085675619452533</iframe></body></html>')


def _doc(title, lang="en"):
    return (f'<!doctype html><html lang="{lang}"><head><title>{title}</title></head><body><main><h1>{title}</h1>{TEXT}'
            "</main></body></html>")


def _air_site():
    """/ -> 301 /global-en; the sitemap lists the same 6 pages in 5 country-language folders (airastana's shape)."""
    urls = [f"{AIR}/{f}/{p}" for p in PAGES for f in FOLDERS]  # grouped by page, as airastana's sitemap is

    def respond(request):
        path = request.url.path
        if path == "/robots.txt":
            return httpx.Response(200, text=f"User-agent: *\nAllow: /\nSitemap: {AIR}/sitemap.xml\n")
        if path == "/sitemap.xml":
            return httpx.Response(200, headers={"content-type": "application/xml"}, text=(
                '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                + "".join(f"<url><loc>{u}</loc></url>" for u in urls) + "</urlset>"))
        if path == "/":
            return httpx.Response(301, headers={"location": AIR + "/global-en"})
        if path == "/global-en" or str(request.url) in urls:
            return httpx.Response(200, headers=HTML, text=_doc(path))
        return httpx.Response(404, headers=HTML, text=_doc("Not found"))
    return respond


def _air_report(max_pages=10):
    config = CrawlConfig(**{**QUIET, "max_pages": max_pages, "sitemap_check_max": 0, "business_type": "auto"})
    outcome = run_audit(AIR + "/", config, httpx.MockTransport(_air_site()))
    return outcome, json.loads(json.dumps(to_jsonable(build_report(outcome.result, outcome.gates, outcome.checks))))


# ---------------------------------------------------------------- 2: country/language folders

def test_country_language_folders_are_found_on_the_sites_own_evidence():
    urls = [f"{AIR}/{f}/{p}" for f in FOLDERS for p in PAGES]
    info = locales.detect(urls, start_url=AIR + "/global-en")
    assert info["folders"] == sorted(FOLDERS) and info["main"] == "global-en" and info["versions"] == 5
    assert locales.page_key(AIR + "/uk-ru/information/about-us", info["folders"]) == "/information/about-us"
    # A pair-shaped or two-letter folder with nothing mirroring it is not a locale (/how-to/, /tv/).
    plain = locales.detect(["https://x.test/how-to/a", "https://x.test/how-to/b", "https://x.test/tv/a", "https://x.test/a"],
                           start_url="https://x.test/")
    assert plain["folders"] == []
    # The root is a version only when the homepage lives there (moodist's root links are old /tr/ addresses).
    mirrored = ["https://m.test/tr/a/", "https://m.test/tr/b/", "https://m.test/en/a/", "https://m.test/en/b/",
                "https://m.test/a/", "https://m.test/b/"]
    assert locales.detect(mirrored, start_url="https://m.test/tr/")["root_is_version"] is False
    assert locales.detect(mirrored, start_url="https://m.test/")["root_is_version"] is True


def test_the_frontier_reads_one_version_of_each_page_before_a_second_and_the_main_version_first():
    pad = Scratchpad()
    pad.set_locales(FOLDERS, "global-en")
    pad.add_urls([FrontierUrl(f"{AIR}/{f}/{p}", None, "sitemap", None) for p in PAGES for f in reversed(FOLDERS)])
    order = []
    while (item := pad.get_next_url()) is not None:
        order.append(item.url)
        pad.mark_status(item.url, CRAWLED)
    keys = [locales.page_key(u, FOLDERS) for u in order]
    # The first six are six different pages, each its main version (/global-en), before any second version.
    assert len(set(keys[:6])) == 6 and all("/global-en/" in u for u in order[:6])
    # A third version of a page comes only after every page has two.
    assert all(keys[:12].count(k) == 2 for k in set(keys[:12]))


def test_a_capped_crawl_of_a_site_with_country_folders_reads_different_pages():
    outcome, r = _air_report(max_pages=10)
    read = [p["url"] for p in r["crawl"]["pages"] if p["status"] == 200 and p["url"] != AIR + "/global-en"]
    keys = [locales.page_key(u, FOLDERS) for u in read]
    assert len(read) == 9 and len(set(keys)) == len(PAGES)              # every page before a second copy
    assert max(keys.count(k) for k in keys) <= locales.COPIES             # never more than two copies of one page
    assert all("/global-en/" in u for u in read[:len(PAGES)])             # the main version first
    assert r["crawl"]["locales"]["folders"] == sorted(FOLDERS) and r["crawl"]["locales"]["main"] == "global-en"
    assert r["schema_version"] == "1.28"
    line = locales.line(locales.summary(r["crawl"]["locales"], cs.pages_read(r)), "en")
    assert line == "5 country/language versions found; at most 2 versions of a page were read."


def test_the_homepage_may_be_read_in_up_to_four_versions_for_the_per_locale_checks():
    s = locales.summary({"versions": 4, "folders": ["tr", "en", "ru", "ar"], "main": "tr"},
                        ["https://m.test/tr/", "https://m.test/en/", "https://m.test/ru/", "https://m.test/ar/", "https://m.test/tr/a"])
    assert s["most_versions_of_one_page"] == 1 and s["homepage_versions"] == 4
    assert locales.line(s, "tr") == "4 ülke/dil sürümü bulundu; her sayfanın bir sürümü okundu (ana sayfa 4 sürümde)."
    assert locales.HOME_COPIES == 4 and locales.COPIES == 2


# ---------------------------------------------------------------- 1: one page limit for both readers

def _small_site():
    pages = {f"https://bank.test/p{i}": _doc(f"P{i}") for i in range(1, 7)}
    pages["https://bank.test/"] = _doc("Home").replace("</main>", "".join(f'<a href="/p{i}">P{i}</a>' for i in range(1, 7)) + "</main>")

    def respond(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n", headers={"content-type": "text/plain"})
        url = str(request.url)
        return httpx.Response(200, headers=HTML, text=pages[url]) if url in pages else httpx.Response(404, headers=HTML, text="x")
    return respond, pages


def test_pages_read_by_maya_and_the_page_reader_together_never_pass_the_plans_limit(tmp_path, no_lookups):
    respond, pages = _small_site()
    cfg = CrawlConfig(**{**QUIET, "max_pages": 3})
    outcome = run_audit("https://bank.test/", cfg, httpx.MockTransport(respond))
    own = {p.url for p in outcome.result.pages if p.status == 200}
    assert len(own) == 3
    api = Firecrawl(pages)
    info = reader.apply(outcome, cfg, client_for(tmp_path, api), Options(read_always=True, max_pages=3))
    read = {row["url"] for row in info["pages"] if row["outcome"] == "read"}
    assert read <= own and len(own | read) <= 3                          # before: 3 + 3 different pages = 6 read
    from maya_audit.report import read_counts
    counts = read_counts(to_jsonable(outcome.result), to_jsonable(info))
    assert counts["pages"] <= 3 and info["coverage"]["not_requested_because"] in (None, "page_cap")


# ---------------------------------------------------------------- Imperva's block page

def test_impervas_block_page_served_with_200_is_a_block_not_a_noindex_page():
    c = classify_fetch(200, {"x-iinfo": "53-25903242-0 pNNN"}, INCAPSULA.encode(), None)
    assert c.fetch_class == FetchClass.BLOCKED
    assert identify_blocker(200, {"x-iinfo": "1"}, c.evidence, "blocked")["name"] == "Imperva"
    # A normal page that only carries Imperva's injected script is the site's own page.
    normal = '<html><head><title>Home</title><script src="/_Incapsula_Resource?SWJIYLWA=abc"></script></head><body>Hi</body></html>'
    assert classify_fetch(200, {"x-iinfo": "1"}, normal.encode(), None).fetch_class == FetchClass.OK


def _block_record(url):
    return {"url": url, "status": 200, "fetch_class": "ok", "classification_confidence": "verified", "body_bytes": 1166,
            "elapsed_ms": 120.0, "content_type": "text/html", "body_truncated": False,
            "content_checks_eligible": True, "discovered_via": "sitemap", "depth": None, "requested_at": "t", "user_agent": "Maya",
            "classification_evidence": ["status 200"], "headers": {"x-iinfo": "1"}, "error": None,
            "analysis": json.loads(json.dumps(analyze_html(INCAPSULA))),
            "grouping": {"importance": 20, "page_type": "other", "importance_rank": 2, "read": True}}


def _saved_blocked_report():
    site = "https://air.test"
    maya = [f"{site}/global-en/information/about-us", f"{site}/global-ru/information/about-us", f"{site}/kaz-kk/mmb/x"]
    reader_read = [f"{site}/global-en/information/about-us", f"{site}/global-en/check-in/online"]
    acc3 = {"id": "ACC-3-a", "check_id": "ACC-3", "rule_id": "acc3.sitemap_noindex", "severity": "S3", "confidence": "verified",
            "title": "noindex via meta on 3 page(s) the sitemap lists", "scope": {"urls": maya}, "evidence": {}}
    idx5 = {"id": "IDX-5-a", "check_id": "IDX-5", "rule_id": "idx5.unsuitable", "severity": "S3", "confidence": "estimated",
            "title": "5 sitemap URL observation(s) require differentiated review (5 checked)", "scope": {"urls": maya},
            "evidence": {"sitemap_decisions": [{"url": u, "attempts": [{"url": u, "body_bytes": 1166, "noindex": [
                '<meta name="robots" content="NOINDEX, NOFOLLOW">'], "fetch_class": "ok"}]} for u in maya] + [
                {"url": f"{site}/uk-ru/x", "attempts": [{"url": f"{site}/uk-ru/x", "body_bytes": 1050, "noindex": [
                    '<meta name="robots" content="NOINDEX, NOFOLLOW">'], "fetch_class": "ok"}]}]}}
    heading = {"id": "TSEO-1-a", "check_id": "TSEO-1", "rule_id": "tseo1.heading_jumps", "severity": "S4", "confidence": "estimated",
               "title": "2 heading level jump(s)", "scope": {"urls": reader_read},
               "evidence": {"reading": {"seen_in": "firecrawl_only", "note": "x"}},
               "notes": ["Seen only in Firecrawl's copy of the pages, not in Maya's own reading of the same pages: confirm it in "
                         "a normal browser before acting on it."]}
    acc9 = {"check_id": "ACC-9", "status": "pass", "summary": "None of the 3 page(s) requested answered", "findings": []}
    return {
        "schema_version": "1.26",
        "crawl": {"start_url": site + "/", "origin": site, "user_agent": "Maya-Audit/0.2", "product_token": "Maya-Audit",
                  "config": {"max_pages": 50}, "pages": [_block_record(u) for u in maya],
                  "sitemap_urls": [f"{site}/{f}/{p}" for f in FOLDERS for p in PAGES], "discovered_urls": [], "requests": []},
        "firecrawl": {"used": True, "pages_read": 2, "purpose": "main page reader", "checks_from_firecrawl": ["TSEO-1"],
                      "pages": [{"url": u, "outcome": "read"} for u in reader_read]},
        "audit_status": {"direct_access": {"state": "readable", "note": "let in"}, "vendor_crawler_evidence": {"state": "not_measured", "note": "x"},
                         "content_coverage": {"level": "partial", "pages_read": 4}},
        "checks": [{"check_id": "ACC-3", "findings": [acc3]}, {"check_id": "IDX-5", "findings": [idx5]},
                   {"check_id": "TSEO-1", "findings": [heading]}, acc9],
        "findings_in_priority_order": ["ACC-3-a", "IDX-5-a", "TSEO-1-a"], "problem_summary": {"pages_checked": 4},
    }


def test_a_saved_audit_with_impervas_block_page_drops_what_was_measured_only_on_it():
    r = _saved_blocked_report()
    assert saved_block_page(r["crawl"]["pages"][0]) == "Imperva"
    new, aff, record = reassess(r, {})
    ids = {f["id"] for c in new["checks"] for f in c.get("findings") or []}
    assert "ACC-3-a" not in ids and "IDX-5-a" not in ids and "TSEO-1-a" in ids     # the reader's own finding stays
    assert any("Imperva's block page" in c for c in record["changes"])
    assert all(p["fetch_class"] == "blocked" and p["content_checks_eligible"] is False for p in new["crawl"]["pages"])
    cov = new["audit_status"]["content_coverage"]
    assert cov["pages_read"] == 2 and cov["read_by"]["maya_only"] == 0           # the block pages are not pages read
    assert new["audit_status"]["direct_access"]["state"] == "challenged"
    acc9 = next(c for c in new["checks"] if c["check_id"] == "ACC-9")
    assert acc9["findings"] and "Imperva" in acc9["findings"][0]["title"]
    # "Seen only in Firecrawl's copy" compared it with a block page: there was nothing to compare, the mark is taken off.
    heading = next(f for c in new["checks"] for f in c.get("findings") or [] if f["id"] == "TSEO-1-a")
    assert "reading" not in heading["evidence"] and not heading["notes"]
    assert new["crawl"]["locales"]["versions"] == 5
    # The key pages are the reader's pages, typed for the business type; importance not computed (no links).
    rows = cs.reader_key_pages(new, [], {"id": "havayolu"})
    assert [k["business_page_type"] for k in rows][:1] == ["checkin"] and rows[0]["importance_unknown"]["reason"] == "reader_only"


def test_moodist_and_nihan_shaped_reports_have_no_block_page():
    for record in ({"fetch_class": "ok", "analysis": {"visible_words": 900, "iframes": []}},
                   {"fetch_class": "ok", "analysis": {"visible_words": 4, "iframes": [{"src": "https://www.youtube.com/embed/x"}]}}):
        assert saved_block_page(record) is None


# ---------------------------------------------------------------- 3: the airline variant

def test_airastana_shaped_addresses_suggest_havayolu_and_tur_in_a_country_folder_is_not_a_tour():
    urls = [f"https://airastana.com/{f}/{p}" for f in ["global-en", "tur-en", "tur-tr", "kaz-kk", "uk-ru"]
            for p in ["information/baggage-allowance", "check-in/online", "mmb/booking-details", "information/about-us",
                      "information/fares-and-fare-rules", "information/hotels-in-almaty", "information/airports",
                      "information/contact-us", "information/news", "information/careers", "information/media",
                      "information/privacy-notice"]]
    folders = locales.detect(urls)["folders"]
    assert "tur-en" in folders
    s = bt.suggest(None, None, None, urls, folders)
    assert s["id"] == "havayolu" and s["scores"]["havayolu"] > s["scores"]["seyahat"]
    assert bt.label("havayolu", "tr") == "Havayolu" and bt.label("seyahat", "tr") == "Tur / otel"
    groups = {c["id"]: c["group_label"] for c in bt.choices("tr")}
    assert groups["havayolu"] == groups["seyahat"] == "Seyahat / rezervasyon"
    tours = ["https://tatil.test/turlar/kapadokya-turu", "https://tatil.test/oteller/antalya", "https://tatil.test/otel/x",
             "https://tatil.test/tur/y", "https://tatil.test/hakkimizda"]
    assert bt.suggest(None, None, None, tours)["id"] == "seyahat"


def test_iata_style_routes_count_only_when_the_airports_form_a_network():
    assert bt.iata_routes([["flights", "ala ist"], ["flights", "ist ayt"], ["flights", "ayt ala"]]) == ["ala-ist", "ist-ayt", "ayt-ala"]
    assert bt.iata_routes([["big sale"], ["new car"], ["top ten"]]) == []
    profile = bt.profile("havayolu")
    assert [t["id"] for t in profile["page_types"] if t.get("rank")] == [
        "routes", "flight_search", "fares", "baggage", "checkin", "terms_help"]


def test_signals_table_lists_the_airline_profile():
    md = (ROOT / "docs" / "business-types" / "signals.md").read_text(encoding="utf-8")
    assert "## Havayolu" in md and "## Tur / otel" in md and "Bagaj" in md


# ---------------------------------------------------------------- 4, 5, 6: the summary

def test_the_summary_keeps_four_tiles_and_says_a_striking_sitemap_result_on_its_card(tmp_path):
    from maya_audit_web.team_report import build_data
    src = tmp_path / "report.json"
    idx5 = {"id": "IDX-5-x", "check_id": "IDX-5", "rule_id": "idx5.unsuitable", "severity": "S3", "confidence": "estimated",
            "title": "149 of 149 sitemap URL(s) checked (100%) are not live, indexable pages; the sitemap lists 3580",
            "scope": {"urls": []}, "how_to_fix": "Fix it.",
            "evidence": {"breakdown": {"not_live": {"redirect": 149, "not_found": 0, "server_error": 0, "empty": 0, "noindex": 0},
                                       "canonical_elsewhere": 0, "disallowed": 0, "noindex_reported_under_acc3": 0},
                         "bad_urls": [{"url": f"https://s.test/p{i}", "kind": "redirect", "location": f"https://s.test/uk-ru/p{i}"}
                                      for i in range(149)]}}
    from test_v03_client_report import page, report
    r = report([idx5], pages=[page("https://s.test/", 100, "home", 1), page("https://s.test/a", 80)])
    r["crawl"]["locales"] = {"folders": ["uk-ru", "global-en"], "main": "global-en", "versions": 2}
    r["audit_status"] = {"content_coverage": {"pages_read": 2, "known_urls_not_read": 0}}
    src.write_text(json.dumps(r))
    for lang, label, line in (("en", "Pages with Medium+ issues", "All 149 checked sitemap addresses redirect to a country/language version."),
                              ("tr", "Orta ve üstü sorunlu sayfa", "Kontrol edilen 149 sitemap adresinin tamamı bir ülke/dil sürümüne yönleniyor.")):
        data, _ = build_data.build_from_files(src, lang, reassess=False)
        assert len(data["kpis"]) == 4 and data["kpis"][2]["label"] == label
        assert not any("sitemap" in k["label"].lower() for k in data["kpis"])
        card = next(t for t in data["todos"] if "IDX-5-x" in t["finding_ids"])
        assert card["sitemap_line"] == line and card["sub"][0] == line


def test_headlines_read_naturally_in_both_languages():
    from maya_audit_web.team_report import texts as T
    assert T.headline(["S3"], ["Certificate expiry"], "en", counts={"S3": 4, "S4": 3}) == (
        "There are 4 medium and 3 low-severity issues; start with the certificate expiry.")
    assert T.headline(["S3"], ["Sertifika süresi", "Başlık düzeyleri"], "tr", counts={"S3": 4, "S4": 3}) == (
        "4 orta ve 3 düşük önemde sorun var; öncelik: sertifika süresi ve başlık düzeyleri.")
    assert T.headline(["S2"], ["Canonical redirect loop"], "en", counts={"S2": 1, "S3": 7, "S4": 12}).endswith(
        "start with the canonical redirect loop.")


def test_turkish_instructions_use_one_form():
    for rel in ("maya_audit_web/team_report/texts/tr.json", "maya_audit_web/locales/findings/tr.json",
                "maya_audit_web/locales/tr.json", "maya_audit/client_reporting/advice.py"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert not re.search(r"\w+(malısınız|melisiniz)\b", text), rel
        assert "Bilinçli dışlamayı" not in text, rel
    findings = (ROOT / "maya_audit_web/locales/findings/tr.json").read_text(encoding="utf-8")
    assert "Bilerek dizin dışında tutulan sayfalara dokunmayın" in findings


def test_the_waiting_tile_says_what_it_holds():
    from maya_audit_web import strings
    assert strings.t("overview.waiting.split", "en", problems=2, notes=1) == (
        "2 issues (among the recorded issues) and 1 note; below, under “Check these first”")
    assert strings.t("overview.waiting.split", "tr", problems=2, notes=1).startswith("2 sorun (kayıtlı sorunların içinde) ve 1 not")


def test_the_history_list_takes_the_derived_copys_count(tmp_path):
    from maya_audit_web.team_report.current import read_of
    assert read_of({"audit_status": {"content_coverage": {"pages_read": 13, "read_by": {"maya_only": 0, "both": 0, "firecrawl": 13}}}}) == {
        "pages_read": 13, "maya": 0, "firecrawl": 13}
    assert read_of({}) is None


def test_the_evidence_index_says_which_saved_pages_were_readable(tmp_path):
    from maya_audit.evidence_store import save_evidence
    outcome, _ = _air_report(max_pages=3)
    save_evidence(outcome.result, outcome.result.config if hasattr(outcome.result.config, "key_pages") else CrawlConfig(**QUIET),
                  tmp_path / "ev", mode="all")
    index = json.loads((tmp_path / "ev" / "index.json").read_text(encoding="utf-8"))
    assert index["pages"] and all(row["fetch_class"] == "ok" for row in index["pages"] if row["status"] == 200)
