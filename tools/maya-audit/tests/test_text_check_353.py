"""DECISIONS 353: the finding catalogue (export and import), the release gate's text checks (RG-18 to RG-23, the
"Kontrol raporu" sheet, the draft mark) and the optional second reader. Made-up cards and reports; no network."""
from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

import pytest

from maya_audit import client_selection, text_gate, xlsx
from maya_audit_web import finding_catalogue as fc
from maya_audit_web.team_report import llm_review

SITE = "https://shop.test"


def finding(fid, rule="idx6.broken", title="3 internal link(s) on 2 page(s) point to pages that fail", evidence=None, urls=()):
    return {"id": fid, "rule_id": rule, "check_id": rule.split(".")[0].upper().replace("IDX", "IDX-").replace("STR", "STR-"),
            "title": title, "severity": "S3", "evidence": evidence or {"links": 3, "pages": 2},
            "scope": {"urls": list(urls)}}


def report(*findings, platform=None):
    r = {"checks": [{"check_id": "IDX-6", "findings": list(findings)}]}
    if platform:
        r["platform"] = {"name": platform}
    return r


def card(n=1, fid="F1", title="Bozuk bağlantıları düzeltin", steps="Bağlantıları bulun\nDoğru adrese verin", **more):
    return {"n": n, "finding_ids": [fid], "title": title, "steps": steps, "why": "Ziyaretçi hata sayfasına düşer.",
            "verify": "Bağlantıyı açın; sayfa açılmalı.", "scope": "2 sayfa", "all_urls": [f"{SITE}/a", f"{SITE}/b"],
            "rule_id": "idx6.broken", **more}


def data(*cards, notes=(), **more):
    return {"lang": "tr", "todos": list(cards), "notes_more": list(notes), "_facts": [], **more}


def rules_of(found):
    return sorted({(v["rule"], v["hard"]) for v in found})


# ---------------------------------------------------------------- RG-18 placeholders and numbers

def test_a_clean_card_passes():
    record = text_gate.run(data(card()), report(finding("F1")))
    assert record["decision"] == "PASS" and record["violations"] == []


def test_a_placeholder_left_in_a_text_blocks():
    found = text_gate.check(data(card(title="{count} bağlantıyı düzeltin")), report(finding("F1")))
    assert ("RG-18", True) in rules_of(found)
    found = text_gate.check(data(card(), assessment={"headline": "Önce [[bağlantılar]] None"}), report(finding("F1")))
    assert any(v["rule"] == "RG-18" and v["where"].startswith("assessment") for v in found)


def test_a_number_the_findings_do_not_hold_blocks_and_one_they_hold_passes():
    found = text_gate.check(data(card(title="7 bozuk bağlantıyı düzeltin")), report(finding("F1")))
    assert ("RG-18", True) in rules_of(found) and "'7'" in found[0]["message"]
    assert text_gate.check(data(card(title="3 bozuk bağlantıyı düzeltin")), report(finding("F1"))) == []
    # A heading tag, a status class or a size is code, not a count.
    assert text_gate.check(data(card(steps="<h2> başlık ekleyin\n4xx yanıtları ve 100 KB üstünü bulun")), report(finding("F1"))) == []


# ---------------------------------------------------------------- RG-19 platform

def test_platform_advice_only_on_that_platform():
    shopify = card(steps="Shopify yönetiminde bağlantıyı düzeltin\nTemayı kaydedin")
    assert ("RG-19", True) in rules_of(text_gate.check(data(shopify), report(finding("F1"))))
    assert ("RG-19", True) in rules_of(text_gate.check(data(shopify), report(finding("F1"), platform="Ticimax")))
    assert text_gate.check(data(shopify), report(finding("F1"), platform="Shopify")) == []
    # WooCommerce is built on WordPress; evidence that names the platform lets the card say it.
    woo = card(steps="WordPress eklentisini güncelleyin\nTemayı kaydedin")
    assert text_gate.check(data(woo), report(finding("F1"), platform="WooCommerce")) == []
    named = finding("F1", evidence={"links": 3, "pages": 2, "generator": "Shopify"})
    assert text_gate.check(data(shopify), report(named)) == []


# ---------------------------------------------------------------- RG-20 menu and sign-in links

def test_removing_a_menu_or_sign_in_link_is_refused():
    menu = card(link_rows=[{"suggested": "remove", "position": "menu", "href": "/eski", "links_to": f"{SITE}/eski"}])
    assert ("RG-20", True) in rules_of(text_gate.check(data(menu), report(finding("F1"))))
    login = card(link_rows=[{"suggested": "remove", "position": "body", "href": "/giris", "links_to": f"{SITE}/giris"}])
    assert ("RG-20", True) in rules_of(text_gate.check(data(login), report(finding("F1"))))
    body = card(link_rows=[{"suggested": "remove", "position": "body", "href": "/eski", "links_to": f"{SITE}/eski"}])
    assert text_gate.check(data(body), report(finding("F1"))) == []
    said = card(steps="Menüdeki bağlantıyı kaldırın\nSite haritasını güncelleyin")
    assert ("RG-20", True) in rules_of(text_gate.check(data(said), report(finding("F1"))))
    kept = card(steps="Menüdeki bağlantıyı kaldırmayın\nSon adrese verin")
    assert text_gate.check(data(kept), report(finding("F1"))) == []
    entry = card(rule_id="idx6.links_to_entry_redirect", steps="Bu bağlantıyı kaldırın\nSon adrese verin")
    assert ("RG-20", True) in rules_of(text_gate.check(data(entry), report(finding("F1", rule="idx6.links_to_entry_redirect"))))


# ---------------------------------------------------------------- RG-21 English

def test_english_in_a_turkish_card_blocks_and_quoted_site_text_does_not():
    marked = card(title="Fix the broken links (İngilizce)")
    assert ("RG-21", True) in rules_of(text_gate.check(data(marked), report(finding("F1"))))
    soft = data(card(), own_limits=["Cloudflare rate-limited the crawler on 1 of 2 requests and the pages were read"])
    assert ("RG-21", False) in rules_of(text_gate.check(soft, report(finding("F1"))))
    quoted = card(why="Bağlantı metni «Shop the new collection for the season» olarak görünüyor.")
    assert text_gate.check(data(quoted), report(finding("F1"))) == []
    english_report = {**data(card(title="Fix the links to the pages that fail")), "lang": "en"}
    assert text_gate.check(english_report, report(finding("F1"))) == []


def test_untranslated_appendix_sentences_are_listed_soft():
    record = text_gate.run(data(card()), report(finding("F1")))
    more = text_gate.with_untranslated(record, [("IDX-6", "Some new sentence (İngilizce)"), ("IDX-6", "Some new sentence (İngilizce)")])
    assert more["counts"]["RG-21"] == 1 and more["decision"] == "CONDITIONAL"


# ---------------------------------------------------------------- RG-22 duplicates, RG-23 phrases

def test_two_cards_saying_the_same_thing_about_the_same_pages_block():
    twice = data(card(1), card(2, fid="F2", title="Bağlantıları onarın"))
    found = text_gate.check(twice, report(finding("F1"), finding("F2")))
    assert ("RG-22", True) in rules_of(found) and "kart 1 ile kart 2" in found[0]["message"]
    other_pages = card(2, fid="F2", all_urls=[f"{SITE}/c"])
    assert text_gate.check(data(card(1), other_pages), report(finding("F1"), finding("F2"))) == []


def test_banned_phrases_are_whole_words_from_the_teams_file(tmp_path):
    filler = card(why="Bu düzeltme kritik öneme sahiptir.")
    assert ("RG-23", False) in rules_of(text_gate.check(data(filler), report(finding("F1"))))
    word_inside = card(steps="Videoyu birkaç cümleyle özetleyin\nMetni sayfaya ekleyin")
    assert text_gate.check(data(word_inside), report(finding("F1"))) == []
    own = tmp_path / "phrases.json"
    own.write_text(json.dumps({"phrases": [{"text": "ZİYARETÇİ", "lang": "tr", "block": True}]}), encoding="utf-8")
    found = text_gate.check(data(card()), report(finding("F1")), banned=text_gate.phrases(own))
    assert ("RG-23", True) in rules_of(found)  # "Ziyaretçi" in why, Turkish İ folded


def test_the_shipped_phrase_file_is_valid_and_holds_the_teams_examples():
    texts = {p["text"] for p in text_gate.phrases()}
    assert {"kritik öneme sahiptir", "ayrıca belirtmek gerekir ki"} <= texts


# ---------------------------------------------------------------- the sheet and the draft mark

def test_the_kontrol_raporu_sheet_is_the_team_files_and_never_the_clients():
    from maya_audit import client_appendix
    record = text_gate.run(data(card(title="{x} düzeltin")), report(finding("F1")))
    sheet = text_gate.sheet(record, "tr")
    assert sheet["name"] == "Kontrol raporu" and sheet["rows"][0][1].startswith("Taslak")
    assert any(r[0] == "RG-18" and r[2] == "Evet" for r in sheet["rows"])
    assert text_gate.sheet(None, "tr")["rows"][0][1].startswith("Kontrol çalışmadı")
    assert text_gate.sheet(text_gate.run(data(card()), report(finding("F1"))), "tr")["rows"][-1][1] == "Sorun bulunmadı"
    made = []
    original = client_appendix.sheets
    client_appendix.sheets = lambda *a, **k: [{"name": "Özet", "header": ["a"], "rows": [], "widths": [10]}]
    try:
        files = client_appendix.build_files({}, "tr", None, text_check=lambda: record)
    finally:
        client_appendix.sheets = original
    # DECISIONS 376: the text check is the team's: first sheet of the team file, never in the client Ek, whose cover
    # says it is a draft when the check blocks
    assert list(xlsx.read(files["team"]))[0] == "Kontrol raporu" and "Kontrol raporu" not in xlsx.read(files["client"])
    assert xlsx.read(files["client"], band=True)["Kapak"][1][0].startswith("TASLAK")


def test_a_blocked_team_report_says_draft_on_every_page():
    from maya_audit_web.team_report import render
    d = {"lang": "tr", "meta": {"audit_id": "abc", "engine_version": "0.2.8", "date": "17 Kas 2026"}, "_draft": True}
    L = render.LABELS["tr"]
    assert "TASLAK · " in render.footer(d, L, 1, 2)
    assert "TASLAK" not in render.footer({**d, "_draft": False}, L, 1, 2)
    assert "position:fixed" in text_gate.draft_mark("tr")


# ---------------------------------------------------------------- the catalogue

def saved_home(tmp_path) -> Path:
    folder = tmp_path / "home" / "audits" / "a1" / "current-engine"
    folder.mkdir(parents=True)
    r = {"checks": [{"check_id": "STR-7", "title": "Images: alt text, uploaded files, formats",
                     "findings": [{"id": "S1", "rule_id": "str7.alt_missing", "check_id": "STR-7", "severity": "S4",
                                   "title": "4 likely meaningful image(s) on 2 page(s) have missing or empty alt text",
                                   "evidence": {"images": [], "source": "x"}}]}]}
    (folder / "report.json").write_text(json.dumps(r), encoding="utf-8")
    return tmp_path / "home"


def test_the_catalogue_lists_every_rule_group_note_and_checklist_item(tmp_path):
    home = saved_home(tmp_path)
    out = tmp_path / "katalog.xlsx"
    counts = fc.export(out, home)
    book = xlsx.read(out.read_bytes())
    rows = book[fc.SHEET]
    head, body = rows[0], rows[1:]
    keys = {r[0] for r in body}
    rule_ids = {rule for rows_ in json.loads((fc.ROOT / "maya_audit" / "rule_ids.json").read_text())["rules"].values() for rule, _ in rows_}
    assert {f"rule:{r}" for r in rule_ids} <= keys
    assert {f"group:{g['id']}" for g in client_selection.MERGE_GROUPS} <= keys and "group:redirect_chain" in keys
    assert any(k.startswith("note:") for k in keys) and any(k.startswith("checklist:SEO-") for k in keys)
    assert any("|platform:Shopify" in k for k in keys)
    at = {h: i for i, h in enumerate(head)}
    alt = next(r for r in body if r[0] == "rule:str7.alt_missing")
    assert alt[at["Kaç denetimde"]] == "1/1" and "218" not in alt[at["Örnek cümle (gerçek)"]]
    assert alt[at["Örnek cümle (gerçek)"]].startswith("2 sayfadaki") and "S4×1" in alt[at["Önem (kayıtlı denetimlerde)"]]
    assert "images" in alt[at["Yer tutucular"]] and alt[at["Sorun türü"]] in ("Sorun", "Kontrol edin", "Fırsat")
    for name in fc.NEW:
        assert all((r[at[name]] if at[name] < len(r) else "") == "" for r in body)
    assert counts["audits"] == 1 and "Yasaklı ifadeler" in book


@pytest.fixture
def sources(tmp_path, monkeypatch):
    copies = {}
    for name, path in fc.FILES.items():
        copies[name] = tmp_path / "src" / path.name.replace(".json", f"-{name}.json")
        copies[name].parent.mkdir(exist_ok=True)
        shutil.copy(path, copies[name])
    monkeypatch.setattr(fc, "FILES", copies)
    monkeypatch.setattr(fc, "ROOT", tmp_path)
    return copies


def edited(tmp_path, changes: dict[str, dict[str, str]]) -> Path:
    head = ["Anahtar", "Tür", *fc.NEW]
    body = [[key, "x", *(cells.get(n, "") for n in fc.NEW)] for key, cells in changes.items()]
    path = tmp_path / "edited.xlsx"
    path.write_bytes(xlsx.workbook([{"name": fc.SHEET, "header": head, "rows": body, "widths": [10] * len(head)}]))
    return path


def test_the_import_writes_only_the_edited_texts_and_checks_placeholders(tmp_path, sources):
    before = {n: p.read_text(encoding="utf-8") for n, p in sources.items()}
    path = edited(tmp_path, {
        "rule:str7.alt_missing": {"Yeni başlık": "Anlam taşıyan görsellere alt metin ekleyin",
                                  "Yeni öneri": "- Alt metni olmayan görselleri bulun\n- Her birine ne gösterdiğini yazın",
                                  "Yeni bulgu cümlesi": "{pages} sayfada {images} görselin alt metni yok", "Not": "kısalt"},
        "rule:idx6.links_to_entry_redirect": {"Yeni bulgu cümlesi": "{count} bağlantı girişe gidiyor"},
        "group:html_weight": {"Yeni açıklama": "HTML 3 kat ağırsa tarayıcı geç okur."},
        "rule:idx1.4xx.referenced": {"Yeni öneri": "- Bağlantıları bulun\n- Düzeltin"},
        "rule:nope.nothing": {"Yeni başlık": "x"},
    })
    changes, refused, notes = fc.plan(fc.read_edits(path))
    reasons = {r["key"]: r["why"] for r in refused}
    assert "yer tutucular değişmiş" in reasons["rule:idx6.links_to_entry_redirect"]
    assert "rakam" in reasons["group:html_weight"]
    assert "3 adım olmalı" in reasons["rule:idx1.4xx.referenced"]  # a conditional step keeps its place
    assert reasons["rule:nope.nothing"] == "bilinmeyen kural" and notes == [{"key": "rule:str7.alt_missing", "note": "kısalt"}]
    written = fc.apply(changes)
    texts = json.loads(sources["texts"].read_text(encoding="utf-8"))
    assert texts["rules"]["str7.alt_missing"]["title"] == "Anlam taşıyan görsellere alt metin ekleyin"
    assert texts["rules"]["str7.alt_missing"]["steps"] == ["Alt metni olmayan görselleri bulun", "Her birine ne gösterdiğini yazın"]
    assert json.loads(sources["findings"].read_text(encoding="utf-8"))["titles"]["str7.alt_missing"].startswith("{pages} sayfada")
    assert sources["groups"].read_text(encoding="utf-8") == before["groups"]  # a refused row changes nothing
    assert sources["actions"].read_text(encoding="utf-8") == before["actions"] and len(written) == 2
    # Untouched rules are byte for byte as they were.
    old, new = json.loads(before["texts"]), texts
    assert {k: v for k, v in old["rules"].items() if k != "str7.alt_missing"} == {k: v for k, v in new["rules"].items() if k != "str7.alt_missing"}
    report_text = fc.diff_report(changes, refused, notes, applied=True)
    assert "eski:" in report_text and "Reddedilen satırlar" in report_text


def test_the_import_writes_the_approved_title_where_it_is_shown(tmp_path, sources):
    path = edited(tmp_path, {"rule:idx8.copies": {"Yeni başlık": "Kopya sayfaları birleştirin"},
                             "rule:idx5.stamped|platform:Shopify": {"Yeni öneri": "- Uygulamaların lastmod'u değiştirmesini durdurun\n- Site haritasını yeniden açın"},
                             "checklist:SEO-001": {"Yeni başlık": "Yetki envanteri"}})
    changes, refused, _ = fc.plan(fc.read_edits(path))
    assert refused == []
    fc.apply(changes)
    actions = json.loads(sources["actions"].read_text(encoding="utf-8"))["actions"]
    assert actions["idx8.copies"]["tr"] == "Kopya sayfaları birleştirin"
    assert actions["idx5.stamped"]["steps_by_platform"]["Shopify"]["tr"][0].startswith("Uygulamaların")
    items = json.loads(sources["checklist"].read_text(encoding="utf-8"))["items"]
    assert next(i for i in items if i["id"] == "SEO-001")["item"] == "Yetki envanteri"


def test_a_file_saved_by_excel_with_shared_strings_is_read(tmp_path):
    sheet = ('<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
             '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>'
             '<row r="2"><c r="A2" t="s"><v>2</v></c><c r="B2" t="inlineStr"><is><r><t>Yeni </t></r><r><t>metin</t></r></is></c></row>'
             '</sheetData></worksheet>')
    shared = ('<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><si><t>Anahtar</t></si>'
              '<si><r><t>Yeni </t></r><r><t>başlık</t></r></si><si><t>rule:x</t></si></sst>')
    book = ('<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
            '<sheet name="Bulgular" sheetId="1" r:id="rId7"/></sheets></workbook>')
    rels = ('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId7" Type="worksheet" Target="worksheets/data.xml"/></Relationships>')
    path = tmp_path / "excel.xlsx"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("xl/workbook.xml", book)
        z.writestr("xl/_rels/workbook.xml.rels", rels)
        z.writestr("xl/worksheets/data.xml", sheet)
        z.writestr("xl/sharedStrings.xml", shared)
    assert xlsx.read_any(path.read_bytes())["Bulgular"] == [["Anahtar", "Yeni başlık"], ["rule:x", "Yeni metin"]]


def test_the_merged_cards_texts_come_from_their_data_file():
    data_ = json.loads((fc.ROOT / "maya_audit" / "merge_group_texts.json").read_text(encoding="utf-8"))["groups"]
    for g in (*client_selection.MERGE_GROUPS, client_selection.CHAIN_GROUP):
        assert g["title"] == data_[g["id"]]["title"] and g["fix"]["tr"] == data_[g["id"]]["fix"]["tr"]
    source = (fc.ROOT / "maya_audit" / "client_selection.py").read_text(encoding="utf-8")
    assert "Sayfa HTML'ini hafifletin" not in source


# ---------------------------------------------------------------- the second reader

class FakeClient:
    def __init__(self, answer=None, stop="end_turn"):
        self.calls, self.answer, self.stop = [], answer, stop
        self.beta = self
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        block = type("B", (), {"type": "text", "text": json.dumps(self.answer)})()
        return type("R", (), {"content": [block], "stop_reason": self.stop})()


def test_the_second_reader_is_off_by_default_and_needs_a_key(monkeypatch):
    fake = FakeClient({"suggestions": []})
    assert llm_review.review(data(card()), report(finding("F1")), client=fake, environ={})["state"] == "off"
    assert fake.calls == []
    no_key = llm_review.review(data(card()), report(finding("F1")), environ={"MAYA_AUDIT_LLM_REVIEW": "1",
                                                                             "MAYA_AUDIT_ENV_FILE": "/nonexistent/.env"})
    assert no_key["state"] == "no_key"


def test_the_second_reader_only_suggests():
    d = data(card())
    before = json.dumps(d, sort_keys=True)
    fake = FakeClient({"suggestions": [{"card": 1, "field": "why", "kind": "unnatural", "problem": "çeviri gibi",
                                        "suggestion": "Ziyaretçi hata sayfası görür."},
                                       {"card": 99, "field": "x", "kind": "unclear", "problem": "?", "suggestion": "?"}]})
    result = llm_review.review(d, report(finding("F1")), client=fake, force=True)
    assert result["state"] == "done" and len(result["suggestions"]) == 1
    sent = fake.calls[0]
    assert sent["model"] == "claude-opus-5-5" and sent["fallbacks"] == "default"
    assert "Bozuk bağlantıları düzeltin" in sent["messages"][0]["content"]
    record = llm_review.attach(text_gate.run(d, report(finding("F1"))), result)
    assert record["decision"] == "PASS" and json.dumps(d, sort_keys=True) == before
    rows = text_gate.sheet_rows(record, "tr")
    assert any(r[0] == "LLM" and r[2] == "Hayır" and "Ziyaretçi" in r[6] for r in rows)
    refused = llm_review.review(d, report(finding("F1")), client=FakeClient({}, stop="refusal"), force=True)
    assert refused["state"] == "error" and refused["suggestions"] == []


# ---------------------------------------------------------------- the web app

def test_the_web_appendix_carries_the_check_and_says_its_decision(web):  # noqa: F811
    from test_web_app import API, audit_of
    client = web()
    audit = audit_of(client)
    ek = client.get(f"{API}/audits/{audit['id']}/downloads/xlsx", params={"lang": "tr"})
    assert ek.status_code == 200
    assert ek.headers["X-Maya-Text-Check"] in ("PASS", "CONDITIONAL", "BLOCKED", "NOT_RUN")
    book = xlsx.read(ek.content)
    assert "Kontrol raporu" not in book  # DECISIONS 376: in the team file
    team = client.get(f"{API}/audits/{audit['id']}/downloads/teamfile", params={"lang": "tr"})
    assert team.status_code == 200 and list(xlsx.read(team.content))[0] == "Kontrol raporu"
    if ek.headers["X-Maya-Text-Check"] == "BLOCKED":
        assert "-draft" in ek.headers["Content-Disposition"]


from test_web_app import web  # noqa: E402,F401  (fixture)
