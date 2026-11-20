"""DECISIONS 373: Efsa's revision-compliance review. The version stamp in every Ek and PDF; rules not yet approved
shown as "Kontrol edin"; the fix log's three states (never "Düzeltildi" on empty evidence or a missing test); the note
importer; and İlginay's Nature's Garden follow-ups (text-less links, unrendered collections in "Kapsam", plain Turkish
table rows, a few 429s to Maya as Maya's own limit). Fake data only."""
from __future__ import annotations

import json

from maya_audit import client_appendix, fix_log, rule_approval, xlsx
from maya_audit import client_selection as cs
from maya_audit.version_stamp import line as version_line

from test_v03_client_report import SITE, finding, report


# ---------------------------------------------------------------- version stamp

def test_every_ek_says_its_engine_commit_and_build_time():
    label, text = version_line("tr")
    assert label == "Sürüm" and text.startswith("Maya Audit ") and " · commit " in text and text.endswith(" UTC")
    book = xlsx.read(client_appendix.build(cs.select(report([finding("A", "str1.shared", "S4", urls=[SITE + "/a"])])), "tr"))
    assert book["Yöntem"][-1][0].startswith("Sürüm: ")  # DECISIONS 375: the last row of "Yöntem", not "Kapsam"


# ---------------------------------------------------------------- unapproved rules

def test_a_questioned_rule_and_a_draft_sectors_check_are_kontrol_edin():
    assert rule_approval.unapproved("idx5.stamped") == "questioned"
    assert rule_approval.unapproved("str1.shared") is None
    assert rule_approval.draft_profile("havayolu") and not rule_approval.draft_profile("eticaret")
    assert rule_approval.unapproved("idx8.location_template", "IDX-8", "havayolu") == "draft_sector"
    assert rule_approval.unapproved("idx8.location_template", "IDX-8", "eticaret") is None
    sel = cs.select(report([finding("S", "idx5.stamped", "S4", urls=[SITE + "/sitemap.xml"], check="IDX-5"),
                            finding("T", "str1.shared", "S4", urls=[SITE + "/a"])]))
    kinds = {g["finding_ids"][0]: (g["issue_type"], g.get("unapproved")) for g in sel["groups"]}
    assert kinds["S"] == ("warning", "questioned") and kinds["T"][1] is None


# ---------------------------------------------------------------- fix log: three states

def _ctx(findings=(), checks=(), cards=(), book=None):
    return {"report": {"checks": [{"check_id": c, "status": "findings", "findings": [f for f in findings if f["check_id"] == c]}
                                  for c in checks]}, "cards": list(cards), "book": book or {}, "gate": "PASS"}


def test_fixed_needs_a_passing_test_real_evidence_and_holding_labels():
    item = {"check": {"no_problem": ["str2.hidden_h1"], "test": "tests/x.py", "labels": ["l1"]}}
    ctx = _ctx(checks=["STR-2"])
    assert fix_log.status_of(item, ctx, {"tests/x.py": True}, {"l1": True})[0] == fix_log.FIXED
    assert fix_log.status_of(item, ctx, {"tests/x.py": False}, {"l1": True})[0] == fix_log.OPEN
    assert fix_log.status_of(item, ctx, {"tests/x.py": True}, {"l1": False})[0] == fix_log.OPEN
    assert fix_log.status_of(item, ctx, {"tests/x.py": True}, {})[0] == fix_log.UNVERIFIED  # labels not run
    no_test = {"check": {"no_problem": ["str2.hidden_h1"]}}
    assert fix_log.status_of(no_test, ctx, {}, {}) == (fix_log.UNVERIFIED, "test bağlı değil")


def test_empty_evidence_and_a_check_never_assessed_are_not_fixed():
    item = {"check": {"sheet_has": {"sheet": "Özet", "regex": "x"}, "test": "tests/x.py"}}
    status, how = fix_log.status_of(item, _ctx(), {"tests/x.py": True})
    assert status == fix_log.UNVERIFIED and "kanıt yok" in how  # F10: no sheet is not a pass
    absent = {"check": {"no_card": ["str5.names"], "test": "tests/x.py"}}
    assert fix_log.status_of(absent, _ctx(), {"tests/x.py": True})[0] == fix_log.UNVERIFIED  # STR-5 not assessed
    assert fix_log.status_of(absent, _ctx(checks=["STR-5"]), {"tests/x.py": True})[0] == fix_log.FIXED
    assert set(fix_log.STATES) == {"Düzeltildi", "Hâlâ var", "Doğrulanmadı"}


def test_an_eks_fix_log_says_not_verified_here_for_another_brands_item(monkeypatch, tmp_path):
    status = tmp_path / "status.json"
    status.write_text(json.dumps({"rows": [{"no": 1, "durum": "Düzeltildi", "tarih": "2026-11-19", "commit": "x", "decisions": "373"},
                                           {"no": 2, "durum": "Düzeltildi", "tarih": "2026-11-19", "commit": "x", "decisions": "373"}]}))
    monkeypatch.setattr(fix_log, "STATUS_FILE", status)
    monkeypatch.setattr(fix_log, "items", lambda: [{"no": 1, "brand_key": "mmi", "genel": "a", "nasil": "x"},
                                                   {"no": 2, "brand_key": "enpara", "genel": "b", "nasil": "y"}])
    rows = {r[1]: r[2] for r in fix_log.ek_sheet("tr", "www.mmihomedelivery.ae")["rows"]}
    assert rows == {"a": "Düzeltildi", "b": "bu denetimde doğrulanmadı (genel durum: Düzeltildi)"}


# ---------------------------------------------------------------- note import

def test_the_note_words_give_the_verdict_and_an_unclear_note_is_asked():
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("import_notes", Path(__file__).resolve().parents[1] / "tools" / "import_notes.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.classify("DOĞRU") == "correct" and mod.classify("Doğru.") == "correct"
    assert mod.classify("YANLIŞ, SAYFALARDA BAŞLIK VAR") == "wrong" and mod.classify("Hatalı bulgu") == "wrong"
    assert mod.classify("HANGİ BAĞLANTILARDA METİN YOK") == "incomplete" and mod.classify("nerede?") == "incomplete"
    assert mod.classify("DOĞRU AMA FARKLI SAYFALARDA DA OLABİLİR") is None  # asked, never guessed
    assert mod.classify("Robots'ta parametre bilerek eklenmiş") is None


# ---------------------------------------------------------------- Nature's Garden follow-ups

def test_a_few_429s_to_maya_are_its_own_limit_and_many_are_the_sites():
    few = {"rule_id": "acc9.rate_limited_429", "evidence": {"pages_blocked_or_challenged": 1, "pages_requested": 7}}
    many = {"rule_id": "acc9.rate_limited_429", "evidence": {"pages_blocked_or_challenged": 40, "pages_requested": 60}}
    assert cs.own_limit(few) and not cs.own_limit(many)


def test_an_unrendered_empty_collection_goes_to_coverage_not_to_findings():
    from maya_audit.reassess_rules import _decisions_373
    rows = [{"url": SITE + "/collections/a", "products_listed": 0, "rendered_products": None},
            {"url": SITE + "/collections/b", "products_listed": 0, "rendered_products": 0}]
    f = {"id": "STR-15-e", "check_id": "STR-15", "rule_id": "str15.empty_collections", "severity": "S4",
         "title": "2 indexable collection or category page(s) list no product or almost none",
         "scope": {"urls": [r["url"] for r in rows], "count": 2}, "evidence": {"pages": rows}}
    r = {"checks": [{"check_id": "STR-15", "status": "findings", "findings": [f]}]}
    affected = {"STR-15-e": [x["url"] for x in rows]}
    _decisions_373(r, affected, [])
    assert affected["STR-15-e"] == [SITE + "/collections/b"]
    [gap] = r["checks"][0]["coverage"]["not_assessed"]
    assert gap["part"] == "collection pages with no product in their HTML" and gap["count"] == 1


def test_textless_links_and_tables_say_the_element_and_its_content():
    from maya_audit import page_rows
    from maya_audit.example_rows import attach
    links = {"id": "STR-14-n", "check_id": "STR-14", "rule_id": "str14.no_text", "evidence": {"links": [
        {"source": SITE + "/blog", "target": SITE + "/products/mix", "block": "div.article"}]}}
    tables = {"id": "STR-8-t", "check_id": "STR-8", "rule_id": "str8.headers", "evidence": {"tables": [
        {"url": SITE + "/p", "element": "table.nl-table [table 1]", "rows": 14, "columns": 2,
         "sample_rows": [["Total Fat 9g", "12%"]]}]}}
    r = {"checks": [{"check_id": "X", "findings": [links, tables]}], "crawl": {}}
    attach(r)
    assert page_rows.measured(links, SITE + "/blog", "tr") == \
        "<a> (div.article): görünür metni, içindeki görselin alt metni, aria-label ve title yok → /products/mix"
    assert page_rows.measured(tables, SITE + "/p", "tr") == \
        "tablo «table.nl-table [table 1]» (14 satır, 2 sütun): başlık hücresi (<th>) yok; ilk satır: «Total Fat 9g», «12%»"


def test_a_saved_reading_without_styled_titles_does_not_claim_no_subheadings():
    from maya_audit.reassess_rules import _decisions_373
    f = {"id": "STR-2-s", "check_id": "STR-2", "rule_id": "str2.no_subheadings", "severity": "S4",
         "title": "2 long page(s) (>800 words) have no subheadings", "scope": {"urls": [SITE + "/a", SITE + "/b"], "count": 2},
         "evidence": {"pages": [{"url": SITE + "/a", "content_words": 900}, {"url": SITE + "/b", "content_words": 950,
                                                                              "styled_headings": 0}]}}
    r = {"checks": [{"check_id": "STR-2", "status": "findings", "findings": [f]}]}
    affected = {"STR-2-s": [SITE + "/a", SITE + "/b"]}
    _decisions_373(r, affected, [])
    assert affected["STR-2-s"] == [SITE + "/b"]
