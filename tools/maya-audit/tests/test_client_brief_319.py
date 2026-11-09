"""DECISIONS 319: the client brief ("Müşteri özeti"). At most five pages for a business owner, Turkish and English, built
from the team report's data (current engine, selection, review.json, business type) and gated: no finding IDs, rule or
check names, unconfirmed items, vendor names (except the protection service that blocks crawlers) or unexplained
technical terms; never from an audit where `client_brief_allowed` is false.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from maya_audit import client_selection
from maya_audit.client_selection import CHAIN_GROUP, MERGE_GROUPS
from maya_audit_web.team_report import brief, build_data, texts
from test_team_report import RULES, synthetic, finished  # noqa: F401  (fixture)
from test_web_app import API, error, web  # noqa: F401  (fixture)

ROOT = Path(__file__).resolve().parents[1]
LANGS = ("tr", "en")
PLAIN = ("families", "rules", "groups", "page_types", "good")


def _all(x):
    if isinstance(x, dict):
        for v in x.values():
            yield from _all(v)
    elif isinstance(x, list):
        for v in x:
            yield from _all(v)
    elif isinstance(x, str):
        yield x


# ---------------------------------------------------------------- the text library

def test_both_languages_have_the_same_structure():
    tr, en = brief.library("tr"), brief.library("en")
    assert set(tr) == set(en)
    for section in (*PLAIN, "labels", "verdict", "health", "blocked"):
        assert set(tr[section]) == set(en[section]), section
    for section in ("families", "rules", "groups"):
        for key in tr[section]:
            assert set(tr[section][key]) == set(en[section][key]) == {"title", "what", "why"}, (section, key)
    assert len(tr["terms"]) == len(en["terms"])


def test_every_rule_family_merge_group_and_page_type_has_brief_words():
    families = {rule.split(".")[0] for _, rule in RULES} | {r.split(".")[0] for r in texts.library("tr")["rules"]}
    groups = {g["id"] for g in MERGE_GROUPS} | {CHAIN_GROUP["id"]}
    kinds = {t["id"] for f in (ROOT / "maya_audit" / "business_types" / "profiles").glob("*.json")
             for t in json.loads(f.read_text(encoding="utf-8")).get("page_types") or []}
    kinds |= {"home", "category", "product", "blog_article", "policy", "utility", "other"}  # Stage 3's page types
    for lang in LANGS:
        lib = brief.library(lang)
        assert sorted(families - set(lib["families"])) == [], lang
        assert sorted(groups - set(lib["groups"])) == [], lang
        assert sorted(kinds - set(lib["page_types"])) == [], lang
        for _, rule in RULES:  # every rule the engine can name resolves to words
            assert brief.entry_for(rule, None, lang), (lang, rule)


@pytest.mark.parametrize("lang", LANGS)
def test_library_texts_are_plain_no_digits_ids_or_vendor_names(lang):
    lib = brief.library(lang)
    problems = []
    for section in PLAIN:
        for value in _all(lib[section]):
            if re.search(r"\d", value):
                problems.append(f"digit: {value}")
            if any(p.search(value) for p in brief.ID_PATTERNS):
                problems.append(f"id: {value}")
            for vendor in brief.VENDORS + brief.PROTECTION:
                if re.search(rf"(?<![\w-]){re.escape(vendor)}(?![\w-])", value):
                    problems.append(f"vendor {vendor}: {value}")
            if lang == "en" and re.search(r"[ğışİŞĞ]", value):
                problems.append(f"Turkish letter: {value}")
            if lang == "tr" and re.search(r"\bURL", value):
                problems.append(f"URL in Turkish: {value}")
    assert problems == []


@pytest.mark.parametrize("lang", LANGS)
def test_every_library_text_with_a_technical_term_carries_its_explanation(lang):
    """A problem's words stand alone on its card, so each one that uses a term explains it there."""
    lib = brief.library(lang)
    missing = []
    for section in ("families", "rules", "groups"):
        for key, entry in lib[section].items():
            text = " ".join(entry.values())
            for t in lib["terms"]:
                if re.search(t["term"], text, re.I) and not re.search(t["explain"], text, re.I):
                    missing.append((section, key, t["term"]))
    for value in lib["good"].values():
        for t in lib["terms"]:
            if re.search(t["term"], value, re.I) and not re.search(t["explain"], value, re.I):
                missing.append(("good", value, t["term"]))
    assert missing == []


# ---------------------------------------------------------------- what goes in

def _data(cards, todos=None, confirm=(), confirmations=None):
    todos = todos or [{"n": c["card"], "finding_ids": c["finding_ids"], "rule_id": c["rule_id"], "scope": "12 sayfa",
                       "owner": "Geliştirici", "effort": "Küçük", "when": "Bu ay",
                       "links": [{"href": f"https://www.shop.example/p{c['card']}", "text": f"/p{c['card']}"}]}
                      for c in cards]
    return {"meta": {"brand": "Shop", "domain": "shop.example", "date": "1 Kas 2026"}, "todos": todos, "_cards": cards,
            "_confirm_ids": list(confirm), "_confirmations": confirmations or {}, "key_pages": [], "lab": None,
            "field": None, "_selection_business": None, "_selection_not_found": []}


def _card(n, rule, severity="S3", confidence="measured", issue_type="issue", merge=None, tpl=None):
    return {"card": n, "finding_ids": [f"STR-2-{n:08x}"], "rule_id": rule, "severity": severity, "confidence": confidence,
            "issue_type": issue_type, "merge_group": merge, "placement": "card", "template_line": tpl}


REPORT = {"checks": [], "audit_status": {"content_coverage": {"pages_read": 40}}}


def test_only_measured_or_confirmed_issue_cards_reach_the_brief_at_most_five():
    cards = [_card(1, "str2.no_h1"), _card(2, "str7.placeholder", issue_type="warning"),
             _card(3, "str7.over_100kb", issue_type="opportunity"), _card(4, "str5.names", confidence="inferred"),
             _card(5, "str14.no_text", confidence="estimated"), _card(6, "idx6.tracking", severity="Info"),
             _card(7, "idx6.alias_links"), _card(8, "str16.shared"), _card(9, "str1.shared"), _card(10, "tseo1.heading_jumps"),
             _card(11, "str2.many_h1"), _card(12, "idx6.broken")]
    cards[11]["finding_ids"] = ["IDX-6-0000000c"]
    data = _data(cards, confirm=["IDX-6-0000000c"])
    got = brief.problems(data, REPORT, "tr")
    # no warning, opportunity, inferred, estimated (DECISIONS 329), Info; at most 5
    assert [p["card"] for p in got] == [1, 7, 8, 9, 10]
    assert [p["n"] for p in got] == [1, 2, 3, 4, 5]
    assert all(p["evidence"] == brief.library("tr")["labels"]["evidence"]["measured"] for p in got)
    assert got[0]["example"] == "shop.example/p1" and got[0]["scope"] == "Toplam: 12 sayfa"
    assert got[0]["who"] == "Geliştirici" and got[0]["effort"] == "Küçük"
    # A card waiting in "Teyit edin" never reaches a brief, whatever its place.
    only = _data([_card(1, "idx6.broken")], confirm=["STR-2-00000001"])
    assert brief.problems(only, REPORT, "tr") == []


def test_a_manual_confirmation_is_said_and_the_template_line_counts_pages():
    data = _data([_card(1, "str12.language", merge="language_mismatch", tpl={"template": "/c/*", "kind": "category", "pages": 43})],
                 confirmations={"STR-2-00000001": {"result": "confirmed", "by": "Owner"}})
    p = brief.problems(data, REPORT, "en")[0]
    assert p["evidence"] == "Measured and checked by hand"
    assert p["title"] == brief.library("en")["groups"]["language_mismatch"]["title"]
    assert p["template"].startswith("43 pages with this problem share one page template")


def test_the_protection_service_is_named_only_on_its_own_problem():
    report = {"checks": [{"check_id": "ACC-9", "findings": [{"id": "ACC-9-00000001", "rule_id": "acc9.bot_protection",
                                                             "evidence": {"blocked_by": [{"name": "Imperva"}]}}]}],
              "audit_status": {"content_coverage": {"pages_read": 40}}}
    card = _card(1, "acc9.bot_protection")
    card["finding_ids"] = ["ACC-9-00000001"]
    b = brief.compose(_data([card]), report, "tr")
    assert b["problems"][0]["what"].startswith("Sitenizin Imperva adlı koruma hizmeti")
    assert b["_allowed_vendors"] == ["Imperva"] and brief.check(b) == []
    b["problems"][0]["why"] += " Cloudflare"  # another service, never allowed
    assert [x["kind"] for x in brief.check(b)] == ["vendors"]


def test_good_things_need_a_clean_pass_and_no_contradicting_finding():
    checks = [{"check_id": "IDX-2", "status": "pass", "findings": []},
              {"check_id": "ACC-2", "status": "pass", "findings": []},
              {"check_id": "ACC-9", "status": "findings", "findings": [{"id": "ACC-9-1"}]},
              {"check_id": "IDX-5", "status": "pass", "findings": [{"id": "IDX-5-1"}]},  # pass with a finding: not said
              {"check_id": "IDX-6", "status": "pass", "findings": []}]
    good = brief._good({"checks": checks}, "tr")
    lib = brief.library("tr")["good"]
    assert good == [lib["IDX-2"], lib["IDX-6"]]  # ACC-2 contradicted by ACC-9's block


def test_the_plan_starts_the_most_important_problem_in_the_first_thirty_days():
    cards = [_card(1, "rnd6.large"), _card(2, "str2.no_h1"), _card(3, "str16.shared")]
    data = _data(cards)
    data["todos"][0].update(effort="Orta")  # month, medium effort: 60 days by its own rule
    data["todos"][2].update(when="Daha sonra")
    b = brief.compose(data, REPORT, "tr")
    assert b["plan"]["d30"][0].startswith("1. sorun") and b["plan"]["d30"][1].startswith("2. sorun")
    assert b["plan"]["d60"] == [brief.library("tr")["labels"]["plan_60_empty"]]
    assert b["plan"]["d90"][0].startswith("3. sorun") and b["plan"]["d90"][-1] == brief.library("tr")["labels"]["plan_recheck"]


def test_key_pages_keep_one_row_per_type_and_say_site_wide_problems_apart():
    pages = [{"path": "/", "type": "Ana sayfa", "kind_id": "home", "cards": "01, 02"}]
    pages += [{"path": f"/t{i}/", "type": "Tedavi", "kind_id": "treatment", "cards": "02"} for i in range(9)]
    pages += [{"path": "/ekip/", "type": "Doktor ve ekip", "kind_id": "doctors", "cards": "09"}]
    cards = [_card(1, "idx2.expires"), _card(2, "str2.no_h1")]
    data = _data(cards)
    data["key_pages"] = pages
    b = brief.compose(data, REPORT, "tr")
    rows = b["key_pages"]
    assert len(rows) == brief.KEY_PAGES_SHOWN and rows[-1]["path"] == "/ekip/"  # the doctors' page kept its place
    assert rows[0]["state"] == "2. sorun"  # the certificate (problem 1) is the site's: said once, under the table
    assert rows[-1]["state"] == "Ekip raporundaki diğer düzeltmeler"
    assert b["sitewide_note"].endswith(": 1. sorun.")
    en = brief.compose(data, REPORT, "en")
    assert en["key_pages"][0]["state"] == "Problem 2"
    data["key_pages"][0]["cards"] = "01, 02, 07"  # a card the brief does not show (a note, a low problem)
    assert brief.compose(data, REPORT, "en")["key_pages"][0]["state"] == "Problem 2 and other fixes"


# ---------------------------------------------------------------- the gate

def _clean(lang="tr"):
    return brief.compose(_data([_card(1, "str2.no_h1"), _card(2, "idx6.tracking")]), REPORT, lang)


@pytest.mark.parametrize("lang", LANGS)
def test_a_clean_brief_passes_the_gate(lang):
    assert brief.check(_clean(lang), pages=4) == []


@pytest.mark.parametrize("change, kind", [
    (lambda b: b["problems"][0].update(why=b["problems"][0]["why"] + " (STR-2-00000001)"), "ids"),
    (lambda b: b["problems"][0].update(why=b["problems"][0]["why"] + " idx6.tracking"), "ids"),
    (lambda b: b["health"].append("ACC-9"), "ids"),
    (lambda b: b["good"].append("Shopify temanız hızlı."), "vendors"),
    (lambda b: b["good"].append("Firecrawl ile okunan sayfalar."), "vendors"),
    (lambda b: b["good"].append("Sayfalarınızın hreflang etiketleri doğru."), "terms"),
    (lambda b: b["good"].append("noindex yok."), "terms"),
    (lambda b: b["problems"][0].update(_confidence="inferred"), "unconfirmed"),
    (lambda b: b.update(_confirm_ids=list(b["problems"][0]["_finding_ids"])), "unconfirmed"),
])
def test_the_gate_blocks_ids_vendors_terms_and_unconfirmed_items(change, kind):
    b = _clean()
    change(b)
    assert [x["kind"] for x in brief.check(b)] == [kind]


def test_more_than_five_pages_is_blocked_and_the_pdf_text_is_checked_too():
    b = _clean()
    assert [x["kind"] for x in brief.check(b, pages=6)] == ["pages"]
    assert [x["kind"] for x in brief.check(b, pages=4, pdf_text="STR-12-c792bc34")] == ["ids"]
    assert brief._reason("tr", "pages", pages="6") == "Müşteri özeti 6 sayfa tuttu; en çok 5 sayfa olabilir."


def test_page_count_never_passes_five():
    b = _clean()
    b["problems"] = b["problems"] * 3  # 6 problems would be 2 problem pages: never more than MAX_PROBLEMS are taken
    assert brief.MAX_PROBLEMS == 5 and brief.page_count({"problems": b["problems"][:brief.MAX_PROBLEMS]}) == 5


# ---------------------------------------------------------------- the whole path

def _report_file(tmp_path, n):
    report = synthetic([("STR-2", "str2.no_h1")] * n, "S3")
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    return path


@pytest.mark.parametrize("lang", LANGS)
def test_a_low_coverage_audit_gets_no_brief_and_says_why(tmp_path, lang):
    out = brief.build(_report_file(tmp_path, 3), lang)  # 4 pages read: under 10
    assert out.blocked and out.pdf is None and out.content is None
    assert out.reasons == [brief.library(lang)["blocked"]["low_coverage"].replace("{read}", "4")]
    assert out.details == ["client_brief_allowed: low_coverage"]


def test_a_brief_is_built_from_the_team_reports_data(tmp_path):
    out = brief.build(_report_file(tmp_path, 12), "tr", render_pdf=False)
    assert not out.blocked, out.reasons
    b = out.content
    assert b["problems"] and all(p["severity"] in brief.SEVERITIES for p in b["problems"])
    assert brief.page_count(b) <= brief.MAX_PAGES
    html = out.html
    assert html.count('<section class="page">') == brief.page_count(b)
    assert "MÜŞTERİ ÖZETİ" in html and not any(p.search(html) for p in brief.ID_PATTERNS)
    # The team report's selection is the brief's: card order, confidence and the "Teyit edin" list.
    data, _ = build_data.build_from_files(tmp_path / "report.json", "tr")
    assert [c["finding_ids"][0] for c in data["_cards"]][:len(b["problems"])] == [p["_finding_ids"][0] for p in b["problems"]]


def test_the_page_readers_key_page_types_are_never_not_found(monkeypatch):
    """airastana: key pages typed from the page reader's addresses ("routes") are not "not found" (DECISIONS 319)."""
    report = synthetic([("STR-2", "str2.no_h1")] * 12, "S3")
    business = {"id": "havayolu", "label": {"tr": "Havayolu", "en": "Airline"},
                "not_found": [{"type": "routes", "label": {"tr": "R", "en": "R"}, "rank": 1},
                              {"type": "fares", "label": {"tr": "F", "en": "F"}, "rank": 3}]}
    monkeypatch.setattr(client_selection, "grouping", lambda r, b=None: ({}, {"business_type": business}))
    monkeypatch.setattr(client_selection, "reader_key_pages",
                        lambda r, rows, b, limit=10: [{"url": "https://shop.example/r", "business_page_type": "routes",
                                                       "cards": [], "rank": 1}])
    sel = client_selection.select(report, None, {})
    assert [n["type"] for n in sel["key_pages_not_found"]] == ["fares"]


def test_the_results_page_offers_a_working_client_brief(finished):
    client, audit, _ = finished
    view = client.get(f"{API}/audits/{audit['id']}").json()
    team = (view.get("team_report") or client.get(f"{API}/audits/{audit['id']}/summary").json().get("team_report"))
    assert team["brief"] == f"/api/v1/audits/{audit['id']}/client-brief"
    script = (ROOT / "maya_audit_web" / "static" / "app.js").read_text(encoding="utf-8")
    assert 'team.brief + "?lang=" + asked' in script and "download.brief.soon" not in script
    tr = json.loads((ROOT / "maya_audit_web" / "locales" / "tr.json").read_text(encoding="utf-8"))
    assert tr["download.brief.title"] == "Müşteri özeti (PDF)" and "download.brief.soon" not in tr


def test_a_blocked_brief_says_why_through_the_routes(finished):
    client, audit, folder = finished
    from maya_audit_web.runner import REPORT_JSON
    path = folder / REPORT_JSON
    report = json.loads(path.read_text(encoding="utf-8"))
    report["audit_status"]["content_coverage"]["pages_read"] = 2
    path.write_text(json.dumps(report), encoding="utf-8")
    for lang in LANGS:
        body = error(client.get(f"{API}/audits/{audit['id']}/client-brief", params={"lang": lang}), 422, "client_brief_blocked")
        assert body["message"] == brief.library(lang)["blocked"]["title"]
        assert body["details"]["reasons"] and "{" not in body["details"]["reasons"][0]
        error(client.get(f"{API}/audits/{audit['id']}/downloads/brief", params={"lang": lang}), 422, "client_brief_blocked")


@pytest.mark.slow
def test_each_language_prints_a_brief_of_at_most_five_pages_through_the_routes(finished):
    pytest.importorskip("playwright")
    pypdf = pytest.importorskip("pypdf")
    import io
    client, audit, _ = finished
    base = f"{API}/audits/{audit['id']}"
    for lang in LANGS:
        prepared = client.get(f"{base}/client-brief", params={"lang": lang})
        if prepared.status_code == 422:  # the demo site may be too small for a brief: then it must say so plainly
            reasons = prepared.json()["error"]["details"]["reasons"]
            assert reasons and all("{" not in r for r in reasons)
            continue
        assert prepared.status_code == 200, prepared.text
        body = prepared.json()
        pdf = client.get(body["pdf"]["url"])
        assert pdf.status_code == 200 and pdf.headers["x-maya-language"] == lang
        assert pdf.headers["content-disposition"].endswith('-musteri-ozeti-tr.pdf"' if lang == "tr" else '-client-brief-en.pdf"')
        reader = pypdf.PdfReader(io.BytesIO(pdf.content))
        assert 4 <= len(reader.pages) <= 5 == brief.MAX_PAGES
        text = "\n".join(p.extract_text() or "" for p in reader.pages)
        assert not any(p.search(text) for p in brief.ID_PATTERNS)
        flat = re.sub(r"\s", "", text)  # pypdf splits some Turkish letters with spaces
        assert ("CLIENTBRIEF" in flat) == (lang == "en") and ("Sonrakiad" in flat) == (lang == "tr")
