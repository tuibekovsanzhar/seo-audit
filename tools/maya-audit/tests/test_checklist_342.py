"""DECISIONS 342: the SEO team's 165-item checklist, visibly checked in every audit (İlginay, enpara fee70191).

Every item has one result (Geçti / Sorun / Veri eksik / İnceleme gerekli / Uygulanmaz), one line of evidence, the Maya
rule or card behind it and, for Veri eksik, the missing data source; the Ek has the rows and the totals, the team
report one page. The decisions are tested on hand-made selections; the sheets and the page on the fake site of
DECISIONS 339 (tests/test_head_card_339.py).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from maya_audit import checklist, client_appendix, client_selection, final, xlsx
from maya_audit_web.runner import REPORT_JSON
from maya_audit_web.team_report import build_data, render
from test_head_card_339 import routes
from test_m1_broken_links import audit
from test_firecrawl import no_lookups  # noqa: F401  (fixture)

ROOT = Path(__file__).resolve().parents[1]


def item(iid: str) -> dict:
    return next(i for i in checklist.items() if i["id"] == iid)


def selection(groups=(), checks=None, connected=None, site=None, crux=None, lab=False) -> dict:
    base_site = {"business": {"id": "bankacilik", "label": {"tr": "Bankacılık", "en": "Banking"}},
                 "page_types": {"other": 10, "category": 2}, "pages_read": 12, "found": 40, "sitemaps": 1,
                 "types_seen": ["Organization"], "start": "https://b.test/", "cap": 50, "stop": "done", "not_read": 0}
    return {"groups": list(groups), "cards": [], "_checklist_facts": {
        "checks": checks or {}, "connected": {**{k: False for k in ("gsc", "ga4", "pagespeed", "merchant", "manual",
                                                                    "bing", "gbp", "logs", "dataforseo", "crm", "indexnow")},
                                              **(connected or {})},
        "site": {**base_site, **(site or {})}, "crux": crux or {"status": None, "metrics": []}, "lab": lab}}


def group(rule: str, check: str, severity="S3", placement="card", card=1, fid="F-1") -> dict:
    lead = {"id": fid, "rule_id": rule, "check_id": check, "title": f"{rule} title", "severity": severity}
    return {"lead": lead, "members": [lead], "severity": severity, "placement": placement, "card": card,
            "finding_ids": [fid], "check_id": check}


# ---------------------------------------------------------------- the item list


def test_the_list_holds_the_165_items_in_20_groups_with_known_checks_and_rules():
    items = checklist.items()
    assert len(items) == 165 and len({i["id"] for i in items}) == 165
    assert [i["id"] for i in items] == [f"SEO-{n:03d}" for n in range(1, 166)]
    assert len(checklist.groups_in_order()) == 20
    catalogue = json.loads((ROOT / "maya_audit" / "rule_ids.json").read_text(encoding="utf-8"))["rules"]
    rules = {k for rows in catalogue.values() for k, _ in rows}
    rules |= set(json.loads((ROOT / "maya_audit" / "issue_types.json").read_text(encoding="utf-8"))["rules"])
    for it in items:
        assert it["method"] in ("full", "partial", "review", "manual", "data", "missing"), it["id"]
        assert set(it["checks"]) <= set(catalogue), it["id"]
        for prefix in it["rules"]:
            assert any(r.startswith(prefix) for r in rules), (it["id"], prefix)
        assert it["rest"] is None or it["rest"] == "review" or set(it["rest"]) <= set(checklist.WORDS["tr"]["source"])
        assert set(it["needs"]) <= set(checklist.WORDS["tr"]["source"]), it["id"]


def test_english_rows_use_english_names_and_words():
    import re
    rows = checklist.rows(selection(), "en")
    assert rows[10]["item"] == "Key URL HTTP status" and rows[10]["group"] == "02 · Host, security and HTTP behaviour"
    assert not any(re.search("[ğüşıöçİĞÜŞÖÇ]", " ".join(str(v) for v in r.values())) for r in rows)
    assert len(checklist.totals(rows)["groups"]) == 20


def test_every_condition_has_its_reason_in_both_languages():
    whens = {i["when"] for i in checklist.items() if i["when"]}
    for lang in ("tr", "en"):
        assert whens <= set(checklist.WORDS[lang]["when"])
        assert set(checklist.WORDS[lang]["result"]) == set(checklist.RESULTS)


# ---------------------------------------------------------------- the decisions


def test_an_item_for_shops_does_not_apply_to_a_bank_and_says_why():
    row = checklist.judge(item("SEO-097"), selection())
    assert (row["result"], row["evidence"]) == ("na", "Ürün sayfası okunmadı; iş türü: Bankacılık.")
    assert checklist.judge(item("SEO-097"), selection(site={"page_types": {"product": 4}}))["result"] != "na"


def test_a_problem_on_a_card_is_an_issue_naming_the_card_and_the_rule():
    sel = selection([group("str2.no_h1", "STR-2", card=4, fid="F-9")], checks={"STR-2": {"status": "findings"}})
    row = checklist.judge(item("SEO-065"), sel, cards={"F-9": 6}, todos_by_n={6: "H1 ekleyin"})
    assert (row["result"], row["evidence"], row["ref"]) == ("issue", "H1 ekleyin", "Kart 6 · str2.no_h1")
    row = checklist.judge(item("SEO-065"), sel)  # no team report: the finding's own title, its rule
    assert (row["result"], row["ref"]) == ("issue", "str2.no_h1") and row["evidence"] == "str2.no_h1 title"


def test_a_problem_under_confirm_first_needs_review_and_info_or_rejected_count_for_nothing():
    checks = {"STR-9": {"status": "findings"}}
    sel = selection([group("str9.no_return", "STR-9", placement="confirm", card=None)], checks=checks,
                    site={"languages": True})
    row = checklist.judge(item("SEO-144"), sel)
    assert row["result"] == "review" and row["evidence"].startswith("Teyit edin listesinde: ")
    for g in (group("str9.no_return", "STR-9", severity="Info", placement="note"),
              group("str9.no_return", "STR-9", placement="rejected")):
        assert checklist.judge(item("SEO-144"), selection([g], checks=checks, site={"languages": True}))["result"] == "pass"


def test_missing_data_names_its_source():
    row = checklist.judge(item("SEO-001"), selection())
    assert (row["result"], row["missing_sources"]) == ("missing_data", ["manual"])
    row = checklist.judge(item("SEO-004"), selection())
    assert (row["result"], row["missing_sources"]) == ("missing_data", ["gsc", "ga4"])
    assert row["evidence"] == "Search Console ve GA4 bağlı değil; bu madde bu veriyle değerlendirilir."
    row = checklist.judge(item("SEO-023"), selection(checks={"IDX-9": {"status": "not_assessed"}}))
    assert (row["result"], row["missing_sources"]) == ("missing_data", ["gsc"])
    row = checklist.judge(item("SEO-023"), selection(checks={"IDX-9": {"status": "pass"}}, connected={"gsc": True}))
    assert row["result"] == "pass"  # Google's own canonical, read once Search Console is connected


def test_a_check_that_could_not_run_is_missing_data_with_its_source():
    row = checklist.judge(item("SEO-018"), selection(checks={"PRF-1": {"status": "not_assessed"}}))
    assert (row["result"], row["evidence"]) == ("missing_data", "PRF-1 bu denetimde çalışmadı.")
    row = checklist.judge(item("SEO-129"), selection(checks={"RND-1": {"status": "not_assessed"},
                                                              "RND-2": {"status": "not_assessed"}}))
    assert row["missing_sources"] == ["render"]


def test_a_clean_full_item_passes_a_partial_one_names_what_is_left():
    checks = {"IDX-3": {"status": "pass"}, "IDX-1": {"status": "pass"}}
    row = checklist.judge(item("SEO-014"), selection(checks=checks))
    assert (row["result"], row["evidence"]) == ("pass", "IDX-3: sorun bulunmadı (12 sayfa okundu).")
    row = checklist.judge(item("SEO-015"), selection(checks=checks))
    assert row["result"] == "review" and "uzman incelemesi" in row["evidence"]
    row = checklist.judge(item("SEO-013"), selection(checks=checks))
    assert (row["result"], row["missing_sources"]) == ("missing_data", ["gsc"])


def test_core_web_vitals_come_from_the_field_data():
    crux = {"status": "assessed", "form_factor": "PHONE", "metrics": [
        {"metric": "interaction_to_next_paint", "label": "Interaction to Next Paint (INP)", "shown": "323 ms",
         "rating": "needs improvement"},
        {"metric": "largest_contentful_paint", "label": "Largest Contentful Paint (LCP)", "shown": "1.4 s", "rating": "good"}]}
    sel = selection(crux=crux, connected={"pagespeed": True})
    row = checklist.judge(item("SEO-112"), sel)
    assert (row["result"], row["evidence"], row["ref"]) == ("issue", "INP p75 323 ms (iyileştirilmeli).", "PRF-3 · CrUX")
    assert checklist.judge(item("SEO-111"), sel)["result"] == "pass"
    assert checklist.judge(item("SEO-113"), sel)["result"] == "missing_data"  # no CLS value
    row = checklist.judge(item("SEO-114"), sel)
    assert row["result"] == "missing_data" and row["missing_sources"] == ["pagespeed"]
    assert checklist.judge(item("SEO-112"), selection())["missing_sources"] == ["pagespeed"]


def test_totals_add_up_per_result_and_per_group():
    rows = checklist.rows(selection())
    t = checklist.totals(rows)
    assert t["n"] == 165 == sum(t["all"].values()) == sum(g["n"] for g in t["groups"])
    assert all(sum(g["counts"].values()) == g["n"] for g in t["groups"])
    assert [g["group"] for g in t["groups"]] == checklist.groups_in_order()


# ---------------------------------------------------------------- the Ek and the team report


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    outcome, _ = audit(routes())
    sealed = final.seal(outcome)
    folder = tmp_path_factory.mktemp("audit") / "artifacts"
    folder.mkdir(parents=True)
    (folder / REPORT_JSON).write_text(json.dumps(sealed.report), encoding="utf-8")
    data = build_data.build_from_files(folder / REPORT_JSON, "tr")[0]
    return sealed, data


def test_the_ek_has_every_item_and_the_totals(site):
    sealed, data = site
    content, _ = render.appendix_bytes(sealed.report, sealed.affected, {}, "tr", todos=data["todos"])
    book = xlsx.read(content)
    names = list(book)
    # DECISIONS 376: the team's order: the checklist's totals, then the checklist, after the technical sheets
    assert names.index("Kontrol listesi") == names.index("Kontrol listesi özeti") + 1 > names.index("Bulgular")
    rows = book["Kontrol listesi"]
    assert rows[0] == ["ID", "Grup", "Kontrol maddesi", "Öncelik", "Sonuç", "Kanıt", "Maya kuralı / kart", "Eksik veri kaynağı",
                       "Nasıl kontrol edilir", "Gereken veri / neden uzman", "Otomatikleştirme önerisi"]  # DECISIONS 365
    assert rows[1][0] == "Nasıl kontrol edilir"  # the counts of each way on the first three rows
    rows = [rows[0]] + rows[4:]
    assert [r[0] for r in rows[1:]] == [f"SEO-{n:03d}" for n in range(1, 166)]
    labels = set(checklist.WORDS["tr"]["result"].values())
    assert all(r[4] in labels and r[5] for r in rows[1:])
    assert all(len(r) > 7 and r[7] for r in rows[1:] if r[4] == "Veri eksik")
    head = next(r for r in rows if r[0] == "SEO-132")  # the early-closed head of the fake site, with its card
    card = next(t for t in data["todos"] if t.get("rule_id", "").startswith("tseo1.head_closed"))
    assert head[4] == "Sorun" and head[6].startswith(f"Kart {card['n']} · tseo1.head_closed")
    totals = book["Kontrol listesi özeti"]
    assert totals[0] == ["Grup", "Madde", "Geçti", "Sorun", "Veri eksik", "İnceleme gerekli", "Uygulanmaz",
                         "Otomatik", "Veri gerekir", "Uzman incelemesi"]
    assert totals[1][:2] == ["Toplam", "165"] and sum(int(x) for x in totals[1][2:7]) == 165 == sum(int(x) for x in totals[1][7:])
    assert len(totals) == 22 and sum(int(r[1]) for r in totals[2:]) == 165
    assert client_appendix.finding_ids(content)  # the findings sheet is still found


def test_the_team_report_page_has_the_totals_groups_sources_and_issues(site):
    _, data = site
    c = data["checklist"]
    assert c["n"] == 165 and sum(r["n"] for r in c["results"]) == 165 and len(c["groups"]) == 20
    assert [r["label"] for r in c["results"]] == ["Geçti", "Sorun", "Veri eksik", "İnceleme gerekli", "Uygulanmaz"]
    assert any(s["label"] == "Search Console" for s in c["sources"])
    assert any(i["id"] == "SEO-132" for i in c["issues"])
    html = render.page_checklist(data, render.LABELS["tr"])
    assert "Eksik veri kaynakları" in html and "SEO-132" in html and html.count("<tr>") == 21


def test_the_checklist_page_is_outside_the_ten_page_limit(site):
    _, data = site
    pages = [p for p in render.build_html(data).split('<section class="page">')[1:]]
    assert "SEO kontrol listesi" in pages[-1]
    assert render.build_html({**data, "checklist": None}).count('<section class="page">') == len(pages) - 1
