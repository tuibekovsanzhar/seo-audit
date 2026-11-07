"""DECISIONS 320: no card's content ever stops the PDF (a long confirmation note shrinks and wraps like a title), the
client brief's "SEO" owner is the SEO / marketing team, and a 429 block names its service and says what was refused and
what loaded. Hand-made reports, made-up review files and a local Chromium only; nothing is requested."""
from __future__ import annotations

import json
import re

import pytest

from maya_audit import maya_blocked
from maya_audit_web.team_report import brief, render, texts
from test_client_brief_319 import REPORT, _card, _data
from test_team_report import SITE, built, synthetic

NOTE = {"en": "Checked every language version in a normal browser with a cleared cache on desktop and on mobile: the menu, the "
              "filter tabs, the size labels, the store stock labels and the homepage banner stay in Turkish on the English pages, "
              "and one category name is translated with the wrong word, so customers searching in English cannot find it",
        "tr": "Bütün dil sürümleri temiz önbellekle masaüstünde ve mobilde normal bir tarayıcıda kontrol edildi: İngilizce "
              "sayfalarda menü, filtre sekmeleri, beden etiketleri, mağaza stok etiketleri ve ana sayfa bannerı Türkçe kalıyor "
              "ve bir kategori adı yanlış kelimeyle çevrilmiş; İngilizce arayan müşteriler onu bulamıyor"}
BY = "Sanzhar Tuibekov and the whole content and SEO team of the agency"
# Every kind of card the to-do pages print: an evidence line, broken-link targets, a sitewide card with its own line,
# bot protection with its AI-crawler line, a 429 block with its two lines, and image weight; plus the three issue types.
RULES = [("STR-1", "str1.shared"), ("STR-2", "str2.no_h1"), ("STR-14", "str14.no_text"), ("RND-6", "rnd6.large"),
         ("STR-7", "str7.over_100kb"), ("STR-10", "str10.no_description"), ("IDX-1", "idx1.4xx.referenced"),
         ("ACC-9", "acc9.bot_protection"), ("STR-12", "str12.language")]
MANUAL = {"en": "Manual check:", "tr": "Elle kontrol:"}


def _pdf_text(path):
    from pypdf import PdfReader
    return " ".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)


def _confirmed(tmp_path, lang, rules=RULES):
    """A synthetic report whose every finding the owner confirmed with a long note, built through the real path."""
    report = synthetic(rules, "S3")
    art = tmp_path / "artifacts"
    art.mkdir()
    entries = [{"finding_id": c["findings"][0]["id"], "result": "confirmed", "by": BY, "date": "2026-11-07",
                "seen": "seen in a browser", "rule_id": c["findings"][0]["rule_id"], "note": NOTE[lang]} for c in report["checks"]]
    (art / "review.json").write_text(json.dumps({"version": 1, "entries": entries}), encoding="utf-8")
    return built(art, report, lang)


@pytest.mark.parametrize("lang", texts.LANGS)
def test_a_long_confirmation_note_on_every_card_type_still_prints_and_stays(tmp_path, lang):
    pytest.importorskip("playwright")
    data = _confirmed(tmp_path, lang)
    noted = [t for t in data["todos"] if t.get("sub_keep")]
    assert len(noted) >= 6 and all(t["sub_keep"].startswith(MANUAL[lang]) and NOTE[lang][:30] in t["sub_keep"] for t in noted)
    # The three issue types and the longest status a confirmed card has.
    labels = {"en": ["Issue", "Check", "Opportunity"], "tr": ["Sorun", "Kontrol edin", "Fırsat"]}[lang]
    for k, t in enumerate(data["todos"]):
        t["issue_type"], t["issue_type_label"] = ["issue", "warning", "opportunity"][k % 3], labels[k % 3]
    # The last page's "Teyit edin" list with the same long words.
    for c in data.get("confirm") or []:
        c["reason"] = NOTE[lang]
    result = render.produce(data, tmp_path / "r.html", tmp_path / "r.pdf")
    assert result["stop"] is None and result["overflow"] == [], result["lines"]
    text = _pdf_text(tmp_path / "r.pdf")
    # The note is the last line a card gives up: every noted card still prints it.
    assert text.count(MANUAL[lang]) >= len(noted), (text.count(MANUAL[lang]), len(noted))
    html = (tmp_path / "r.html").read_text(encoding="utf-8")
    assert len(re.findall(r'<div class="keep" data-slot="todos\[\d+\]\.sub\[\d+\]" data-fit=', html)) == len(noted)


@pytest.mark.parametrize("lang", texts.LANGS)
def test_a_card_with_more_than_it_can_hold_is_shrunk_then_counted_never_blocked(tmp_path, lang):
    pytest.importorskip("playwright")
    data = _confirmed(tmp_path, lang, RULES[:4])
    card = data["todos"][1]
    long_line = NOTE[lang].replace(",", "") + " " + NOTE[lang]
    card["sub"] = [card["sub_keep"]] + [f"{n} · {long_line}" for n in range(6)]
    card["status"] = card["status"] + " · " + BY + " · " + BY
    card["steps"] = "\n".join([NOTE[lang][:100]] * 4)
    card["verify"] = NOTE[lang][:150]
    result = render.produce(data, tmp_path / "r.html", tmp_path / "r.pdf")
    assert result["stop"] is None and result["overflow"] == [], result["lines"]
    assert any(s.startswith("kart: todos[1]") for s in result["shortened"]), result["shortened"]
    text = _pdf_text(tmp_path / "r.pdf")
    assert text.count(MANUAL[lang]) >= 4  # the note of every card, the overfull one too
    more = {"en": "more", "tr": "satır daha"}[lang]
    assert more in text


def test_the_overflow_check_still_reports_what_the_fitter_cannot_fix():
    # The fitter runs before the check; the check itself is unchanged (a page body over the footer still stops it).
    assert "gövde alt bilgiye taşıyor" in render.OVERFLOW_JS and "CARD_FIT_JS" in render.render.__code__.co_names


# ---------------------------------------------------------------- the brief's "SEO" owner

@pytest.mark.parametrize("lang,team,word", [("tr", "SEO", "SEO / pazarlama ekibi"), ("en", "SEO", "SEO / marketing team")])
def test_the_brief_names_the_seo_owner_as_the_seo_and_marketing_team(lang, team, word):
    data = _data([_card(1, "str2.no_h1"), _card(2, "str1.shared")])
    data["todos"][0]["owner"] = team
    data["todos"][1]["owner"] = "Developer" if lang == "en" else "Geliştirici"
    got = brief.problems(data, REPORT, lang)
    assert got[0]["who"] == word and got[0]["owner"] == "seo"
    assert got[1]["who"] == ("Developer" if lang == "en" else "Geliştirici")
    assert brief.check(brief.compose(data, REPORT, lang)) == []


# ---------------------------------------------------------------- 429: the service, what was refused, what loaded

def _crawl(*, files=True, start="https://www.shop.example/"):
    reqs = [{"purpose": "page", "url": start, "status": 429}]
    if files:
        reqs += [{"purpose": "robots", "url": "https://shop.example/robots.txt", "status": 301},
                 {"purpose": "robots", "url": "https://www.shop.example/robots.txt", "status": 200}]
        reqs += [{"purpose": "sitemap", "url": f"https://www.shop.example/sitemap_{i}.xml", "status": 200} for i in range(26)]
        reqs += [{"purpose": "llms", "url": "https://www.shop.example/llms.txt", "status": 200},
                 {"purpose": "external_link_head", "url": "https://other.example/robots.txt", "status": 200}]
    return {"start_url": start, "origin": start.rstrip("/"),
            "pages": [{"url": start, "status": 429, "discovered_via": "start"}], "requests": reqs}


def test_served_files_reads_the_request_log_on_the_sites_host():
    assert maya_blocked.served_files(_crawl()) == {"robots": True, "sitemaps": 26, "llms": True}
    assert maya_blocked.served_files(_crawl(files=False)) == {"robots": False, "sitemaps": 0, "llms": False}
    assert maya_blocked.served_files({}) == {"robots": False, "sitemaps": 0, "llms": False}


def _report_429(rule="acc9.blocked_429", service="Cloudflare", files=True, refused=()):
    report = synthetic([("ACC-9", rule)], "S3")
    f = report["checks"][0]["findings"][0]
    f.update(title=f"Maya's crawler blocked (429 on pages): {service or 'the site'} answered 1 of 1 page request(s) with 429",
             evidence={"blocked_by": [{"name": service, "kind": "rate limit", "status": 429, "responses": 2}] if service else [],
                       "pages_requested": 1, "pages_read": 0, "pages_blocked_or_challenged": 1, "start_url_blocked": True,
                       "robots_or_sitemap_also_refused": list(refused)},
             scope={"kind": "sitewide", "count": 1, "urls": [SITE + "/"]})
    crawl = _crawl(files=files, start=SITE + "/")
    for r in crawl["requests"]:
        r["url"] = r["url"].replace("https://www.shop.example", SITE).replace("https://shop.example", SITE)
    report["crawl"].update(start_url=SITE + "/", requests=crawl["requests"])
    return report


LINE = {"en": "Cloudflare refused 1 of 1 page request with 429 (too many requests); robots.txt, 26 sitemap files and llms.txt loaded.",
        "tr": "Cloudflare, 1 sayfa isteğinden 1 tanesini 429 (çok fazla istek) yanıtıyla reddetti; robots.txt, 26 site haritası "
              "dosyası ve llms.txt yüklendi."}


@pytest.mark.parametrize("lang", texts.LANGS)
def test_the_429_card_names_the_service_and_what_was_refused_and_what_loaded(tmp_path, lang):
    card = built(tmp_path, _report_429(), lang)["todos"][0]
    assert card["sub"][0] == LINE[lang]
    assert "Cloudflare" in card["sub"][1]  # the existing "check the rules in Cloudflare" line stays


@pytest.mark.parametrize("lang", texts.LANGS)
def test_an_unnamed_429_block_with_nothing_loaded_says_the_firewall_and_what_was_refused(tmp_path, lang):
    card = built(tmp_path, _report_429(rule="acc9.rate_limited_429", service=None, files=False,
                                       refused=[SITE + "/robots.txt"]), lang)["todos"][0]
    want = {"en": "The site's firewall refused 1 of 1 page request with 429 (too many requests); robots.txt and the sitemap "
                  "were refused too.",
            "tr": "Sitenin güvenlik duvarı, 1 sayfa isteğinden 1 tanesini 429 (çok fazla istek) yanıtıyla reddetti; robots.txt ve "
                  "site haritası da reddedildi."}
    assert card["sub"][0] == want[lang]


@pytest.mark.parametrize("lang", texts.LANGS)
@pytest.mark.parametrize("rule", ["acc9.blocked_429", "acc9.rate_limited_429"])
def test_the_brief_names_the_429_service_and_the_files_that_loaded_and_passes_its_gate(lang, rule):
    report = _report_429(rule=rule)
    f = report["checks"][0]["findings"][0]
    data = _data([{**_card(1, rule), "finding_ids": [f["id"]]}])
    [p] = brief.problems(data, report, lang)
    loaded = {"en": ("Your Cloudflare protection service", "the file that tells crawlers which pages they may read (robots.txt) "
                     "and the file that gives Google the list of your pages (the sitemap) loaded normally"),
              "tr": ("Sitenizin Cloudflare adlı koruma hizmeti", "tarayıcılara hangi sayfaları okuyabileceklerini söyleyen dosya "
                     "(robots.txt) ile Google'a sayfalarınızın listesini veren dosya (site haritası) ise normal açıldı")}[lang]
    assert p["what"].startswith(loaded[0]) and loaded[1] in p["what"], p["what"]
    assert brief.check(brief.compose(data, report, lang)) == []


@pytest.mark.parametrize("lang", texts.LANGS)
def test_the_brief_says_no_service_and_no_files_when_the_evidence_has_none(lang):
    report = _report_429(service=None, files=False)
    f = report["checks"][0]["findings"][0]
    data = _data([{**_card(1, "acc9.blocked_429"), "finding_ids": [f["id"]]}])
    [p] = brief.problems(data, report, lang)
    assert "Cloudflare" not in p["what"] and "robots" not in p["what"] and "[[" not in p["what"] and "{" not in p["what"]
    assert p["what"].endswith("."), p["what"]
    assert brief.check(brief.compose(data, report, lang)) == []
