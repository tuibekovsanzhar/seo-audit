"""DECISIONS 324: the team's sector audit method in Maya Audit. Homepage weights by the sector's rank; P0-P3 on the cards
(impact from severity, effort a neutral 3, the team's thresholds, automatic P0 for an indexing blocker, a person's P0
marks in review.json); plain words in the brief; the "Sektör audit" XLSX in the team's five-sheet format with formulas
and dropdowns; the "Ölçülen değer" of a finding with no value of its own. Offline: in-memory reports, the demo web app."""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from maya_audit import business_types as bt
from maya_audit import client_appendix, client_selection as cs, manual_review, page_rows, priority_levels as pl
from maya_audit import sector_audit, xlsx
from test_v03_client_report import SITE, finding, page, report
from test_team_report import built, synthetic, finished  # noqa: F401  (fixture)
from test_web_app import API, web  # noqa: F401  (fixture)

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------- profiles

def test_homepage_weight_follows_the_sector_rank():
    home = {pid: bt.weight(bt.profile(pid), "home") for pid in ("eticaret", "saglik", "ev_hizmetleri", "restoran",
                                                                  "bankacilik", "kart", "havayolu")}
    assert home == {"eticaret": 70, "saglik": 55, "ev_hizmetleri": 55, "restoran": 55, "bankacilik": 100,
                    "kart": 85, "havayolu": 85}  # ranked: the rank's weight; added where the list has none: 85
    assert not hasattr(bt, "HOME_MIN") and bt.FORMULA == {"page_type": 0.5, "internal_link_score": 0.35, "click_depth": 0.15}


def test_travel_profile_is_named_as_in_the_team_file():
    assert bt.label("seyahat", "tr") == "Seyahat / rezervasyon (tur, otel)"
    assert bt.label("seyahat", "en") == "Travel / booking (tours, hotels)"
    assert sector_audit.sector_of("seyahat") == "Seyahat / rezervasyon"


# ---------------------------------------------------------------- P0-P3

def _ctx(types: dict[str, str], profile="eticaret"):
    """A context of pages read with their business page types."""
    importance = {u: {"business_page_type": t, "page_type": "other", "importance": 50} for u, t in types.items()}
    return pl.Context(importance, {"business_type": {"id": profile}}, set(types))


CATEGORY = {f"{SITE}/c{i}": "category" for i in range(10)}
PAGES = {**CATEGORY, SITE + "/": "home", f"{SITE}/p1": "product", f"{SITE}/p2": "product"}


def _group(*members, placement=None):
    return {"members": list(members), "finding_ids": [m["id"] for m in members], "placement": placement}


def test_p_level_formula_thresholds_and_bands():
    ctx = _ctx(PAGES)
    high = pl.label(_group(finding("H", "str1.shared", "S2", urls=list(CATEGORY))), ctx, None, {})
    assert high["score"] == round(20 * 4 * 1.0 * 5 * 1 / 3, 1) == 133.3 and high["level"] == "P1"
    assert high["basis"]["page_type"] == "category" and high["basis"]["spread"] == 5
    low_everywhere = pl.label(_group(finding("L", "str1.shared", "S4", urls=list(PAGES))), ctx, None, {})
    assert low_everywhere["level"] == "P2" and low_everywhere["score"] <= 33.4  # a Low card is never above P2
    one = pl.label(_group(finding("O", "str1.shared", "S3", urls=[f"{SITE}/c1"])), ctx, None, {})
    assert one["basis"]["spread"] == 1 and one["level"] == "P3"
    site = pl.label(_group(finding("S", "idx2.expires", "S2", urls=[])), ctx, None, {})
    assert site["basis"]["page_type"] is None and site["score"] == 133.3  # no address: the whole site
    assert pl.label(_group(finding("I", "str2.many_h1", "Info", urls=[SITE + "/"])), ctx, None, {})["level"] is None
    assert [pl.spread(n, 100) for n in (1, 10, 11, 30, 31, 70, 71)] == [1, 2, 3, 3, 4, 4, 5]
    assert [pl.level(s) for s in (160, 159.9, 80, 79.9, 30, 29.9, 0.1, 0)] == ["P0", "P1", "P1", "P2", "P2", "P3", "P3", None]


def test_automatic_p0_for_an_indexing_blocker():
    ctx = _ctx(PAGES)
    broad = pl.label(_group(finding("N", "acc3.noindex", "S3", urls=list(CATEGORY)[:4])), ctx, None, {})
    assert broad["level"] == "P0" and "4/10" in broad["auto_p0"]  # 40% of the first page type
    home = pl.label(_group(finding("N2", "acc3.noindex", "S4", urls=[SITE + "/"])), ctx, None, {})
    assert home["level"] == "P0" and "ana sayfa" in home["auto_p0"]
    narrow = pl.label(_group(finding("N3", "acc3.noindex", "S3", urls=list(CATEGORY)[:1])), ctx, None, {})
    assert narrow["auto_p0"] is None and narrow["level"] != "P0"  # one page of ten is not "a broad part"
    robots = pl.label(_group(finding("R", "acc2.blocks.sitewide", "S1", urls=[])), ctx, None, {})
    assert robots["level"] == "P0"


def test_no_automatic_p0_while_waiting_or_for_maya_blocked():
    ctx = _ctx(PAGES)
    waiting = pl.label(_group(finding("W", "acc3.noindex", "S3", urls=list(CATEGORY)), placement="confirm"), ctx, None, {})
    assert waiting["auto_p0"] is None and waiting["level"] == "P1"
    blocked = pl.label(_group(finding("B", "acc9.bot_protection", "S3", urls=list(CATEGORY))), ctx, None, {})
    assert blocked["auto_p0"] is None  # Maya's crawler blocked says nothing of Google


def test_manual_p0_set_and_removed_in_the_review_file(tmp_path):
    path = tmp_path / "review.json"
    manual_review.record(path, manual_review.entry("X-1", "confirmed", by="Ayşe"))
    manual_review.record_p0(path, manual_review.p0_entry("L", "set", by="Ayşe", when="2026-11-08"))
    manual_review.record_p0(path, manual_review.p0_entry("N", "removed", by="Ayşe", when="2026-11-08"))
    review = manual_review.load(path)
    assert [e["finding_id"] for e in review["entries"]] == ["X-1"] and len(review["p0"]) == 2
    conf = manual_review.confirmations(review)
    ctx = _ctx(PAGES)
    low = pl.label(_group(finding("L", "str1.shared", "S4", urls=[f"{SITE}/c1"])), ctx, None, conf)
    assert low["level"] == "P0" and "elle P0" in low["reason"] and low["manual"]["by"] == "Ayşe"
    auto = pl.label(_group(finding("N", "acc3.noindex", "S3", urls=list(CATEGORY))), ctx, None, conf)
    assert auto["level"] == "P1" and "kaldırıldı" in auto["reason"]
    assert manual_review.undo_p0(path, ["L"]) == ["L"]
    assert [e["finding_id"] for e in manual_review.load(path)["p0"]] == ["N"]
    manual_review.undo(path, ["X-1"])  # undoing a check keeps the P0 marks
    assert manual_review.load(path)["p0"][0]["finding_id"] == "N"


def test_p_levels_never_change_order_severity_or_score(monkeypatch):
    r = report([finding("A", "acc3.noindex", "S3", urls=[SITE + "/", SITE + "/a"]),
                finding("B", "str1.shared", "S4", urls=[SITE + "/a", SITE + "/en/a"]),
                finding("C", "idx2.expires", "S2", urls=[])])
    with_levels = cs.select(r)
    monkeypatch.setattr(pl, "annotate", lambda *a, **k: None)
    without = cs.select(r)
    key = lambda s: [(g["finding_ids"], g["severity"], g["priority"], g["placement"], g.get("card")) for g in s["groups"]]  # noqa: E731
    assert key(with_levels) == key(without)
    assert {g["finding_ids"][0]: g["p_level"]["level"] for g in with_levels["groups"]}["A"] == "P0"  # noindex on the homepage


# ---------------------------------------------------------------- outputs

def test_xlsx_shows_the_p_level():
    r = report([finding("A", "acc3.noindex", "S3", urls=[SITE + "/"]), finding("B", "str1.shared", "S4", urls=[SITE + "/a"])])
    book = xlsx.read(client_appendix.build(cs.select(r), "tr"))
    head = book["Özet"][0]
    assert head[:5] == ["Kart", "Başlık", "Önem", "Sorun türü", "Öncelik (P0-P3)"]
    levels = {row[0]: row[head.index("Öncelik (P0-P3)")] for row in book["Özet"][3:] if len(row) > 4}
    assert "P0" in levels.values()
    fhead = book["Bulgular"][0]
    assert "Öncelik (P0-P3)" in fhead
    assert any("P0-P3" in line[0] for line in book["Nasıl okunur"][1:])
    assert any(row[0] == "Öncelik (P0-P3)" for row in book["Yöntem"])


def test_brief_says_the_level_in_plain_words():
    from maya_audit_web.team_report import brief
    from test_client_brief_319 import REPORT, _card, _data
    data = _data([_card(1, "str2.no_h1"), _card(2, "idx6.tracking")])
    data["todos"][0]["p_level"], data["todos"][1]["p_level"] = "P0", "P2"
    b = brief.compose(data, REPORT, "tr")
    assert [p["urgency"] for p in b["problems"]] == ["Acil", "Planlı"]
    html = brief.build_html(b)
    assert "Acil" in html and not any(code in html for code in (">P0<", ">P1<", ">P2<", ">P3<"))
    assert brief.library("tr")["labels"]["severity"]["S1"] == "Çok yüksek önem"  # "Acil" now means P0 only
    assert brief.check(b, pages=4) == []
    b["problems"][0]["why"] += " (P0)"
    assert [x["kind"] for x in brief.check(b)] == ["ids"]  # a code never reaches the client
    assert pl.word("P1", "en") == "Priority" and pl.word(None) is None


def test_team_report_and_web_cards_show_the_chip(tmp_path, finished):  # noqa: F811
    from maya_audit_web.team_report import render
    data = built(tmp_path, synthetic([("ACC-3", "acc3.noindex"), ("STR-1", "str1.shared")], "S3"), "tr")
    assert all("p_level" in t for t in data["todos"]) and any(t["p_level"] for t in data["todos"])
    assert 'class="plevel' in render.build_html(data)
    client, audit, _ = finished
    view = client.get(f"{API}/audits/{audit['id']}/overview?lang=tr").json()
    assert view["available"] and all("p_level" in f and "p_level_reason" in f for f in view["fixes"])
    script = (ROOT / "maya_audit_web" / "static" / "app.js").read_text(encoding="utf-8")
    assert 'class: "plevel "' in script and "p0Block(auditId, data, redraw)" in script


def test_web_p0_mark_and_undo(finished):  # noqa: F811
    client, audit, _ = finished
    base = f"{API}/audits/{audit['id']}/review"
    rows = client.get(base).json()["p0"]
    assert rows and all({"card", "finding_id", "level", "reason", "manual"} <= set(r) for r in rows)
    target = next((r for r in rows if r["level"] != "P0"), rows[0])
    action = "set" if target["level"] != "P0" else "removed"
    missing = client.post(base + "/p0", json={"finding_id": target["finding_id"], "action": action})
    assert missing.status_code == 422  # who marked it is required
    saved = client.post(base + "/p0", json={"finding_id": target["finding_id"], "action": action, "by": "Test"}).json()
    row = next(r for r in saved["p0"] if r["finding_id"] == target["finding_id"])
    assert row["manual"]["action"] == action and (row["level"] == "P0") == (action == "set")
    undone = client.delete(f"{base}/p0/{target['finding_id']}").json()
    assert next(r for r in undone["p0"] if r["finding_id"] == target["finding_id"])["manual"] is None
    assert client.delete(f"{base}/p0/{target['finding_id']}").status_code == 404


# ---------------------------------------------------------------- the sector audit workbook

def test_sector_method_resource_has_the_team_rows():
    m = sector_audit.method()
    base = [r for r in m["sec"] if not r["draft"]]
    assert len(m["core"]) == 44 and len(base) == 174 and sum(1 for t in m["page_types"] if not t["draft"]) == 58
    assert len([s for s in m["sectors"] if not s["draft"]]) == 12
    drafts = [r for r in m["sec"] if r["draft"]]
    assert len(drafts) == 33 and {r["sector"] for r in drafts} == {"Havayolu (taslak)", "Restoran / kafe (taslak)"}
    assert m["draft_note"] == "taslak — İlginay/Efsa onayı bekliyor"
    for row in m["core"] + m["sec"]:
        assert row["status"] in sector_audit.STATUS and isinstance(row["rules"], list) and isinstance(row["needs"], list)
    for t in m["page_types"]:  # every page type is one of its profile's
        assert t["type_id"] in {pt["id"] for pt in bt.profile(t["profile"])["page_types"]}
    counts = {}
    for row in m["core"] + base:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    assert counts == {"A": 74, "K": 116, "G": 7, "P": 14, "M-M": 6, "M-S": 1}  # the Step 1 mapping
    toml = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"sector_method.json"' in toml


def _sector_report():
    pages = [page(SITE + "/", 100, "home", 1), page(SITE + "/kategori/a", 90, "category"),
             page(SITE + "/kategori/b", 85, "category"), page(SITE + "/urun/x", 70, "product")]
    for p in pages:
        p["grouping"]["business_page_type"] = {"home": "home", "category": "category", "product": "product"}[p["grouping"]["page_type"]]
    r = report([finding("T-1", "str1.shared", "S3", urls=[SITE + "/kategori/a", SITE + "/kategori/b"], check="STR-1"),
                finding("H-1", "str2.no_h1", "S4", urls=[SITE + "/urun/x"], check="STR-2")], pages=pages)
    r["crawl"]["business_type"] = {"id": "eticaret", "chosen_by": "person"}
    r["checks"] += [{"check_id": c, "status": s, "findings": []} for c, s in
                    (("ACC-1", "pass"), ("ACC-2", "pass"), ("ACC-3", "pass"), ("IDX-1", "pass"), ("IDX-4", "pass"),
                     ("IDX-7", "pass"), ("STR-9", "not_applicable"), ("STR-1", "findings"), ("STR-2", "findings"))]
    r["audit_status"] = {"content_coverage": {"pages_read": 40, "level": "complete"}}
    return r


def test_sector_durum_rules(monkeypatch):
    r = _sector_report()
    monkeypatch.setattr(cs, "low_coverage", lambda report: None)
    sel = cs.select(r, None, {}, business="eticaret")
    res = sector_audit.evaluate(r, sel, None, "eticaret")
    assert res["sector"] == "E-ticaret / perakende" and res["rows"] == 44 + 18
    core = {row["id"]: row for row in res["core"]}
    assert core["CORE-001"]["durum"] == "Uygun"                                   # automatic, ran, nothing found
    assert core["CORE-012"]["durum"] == "Uygulanamaz"                             # hreflang on a one-language site
    assert core["CORE-023"]["durum"] == "Hatalı" and core["CORE-023"]["spread"]   # a Medium issue (STR-1)
    assert core["CORE-024"]["durum"] == "Kısmen Uygun"                            # only a Low (STR-2)
    assert core["CORE-028"]["durum"] == "Kontrol Edilmedi" and "Search Console" in core["CORE-028"]["reason"]
    assert core["CORE-006"]["durum"] == "Kontrol Edilmedi" and "Otomatik kısım temiz" in core["CORE-006"]["reason"]
    sec = {row["id"]: row for row in res["sec"]}
    assert sec["SEC-003"]["durum"] == "Uygun"                                     # category indexing: pages read, clean
    assert sec["SEC-002"]["durum"] == "Hatalı" and sec["SEC-002"]["example"].startswith(SITE + "/kategori/")
    assert sec["SEC-012"]["durum"] == "Kontrol Edilmedi" and "bulunamadı" in sec["SEC-012"]["reason"]  # no store page
    assert sec["SEC-019"]["durum"] == "Kontrol Edilmedi" and "bu sektör değil" in sec["SEC-019"]["reason"]
    # waiting in "Teyit edin": not a fault yet
    monkeypatch.setattr(cs, "confirm_reason", lambda f, c=None: "inferred" if f.get("id") == "T-1" else None)
    waiting = sector_audit.evaluate(r, cs.select(r, None, {}, business="eticaret"), None, "eticaret")
    assert {row["id"]: row for row in waiting["core"]}["CORE-023"]["reason"].startswith("Teyit bekliyor")
    # a low-coverage audit writes no "Uygun"
    monkeypatch.undo()
    monkeypatch.setattr(cs, "low_coverage", lambda report: {"pages_read": 2})
    low = sector_audit.evaluate(r, cs.select(r, None, {}, business="eticaret"), None, "eticaret")
    assert all(row["durum"] != "Uygun" for row in low["core"] + low["sec"])


def test_sector_xlsx_has_the_five_sheets_formulas_and_dropdowns(monkeypatch):
    r = _sector_report()
    monkeypatch.setattr(cs, "low_coverage", lambda report: None)
    data = sector_audit.build(r, cs.select(r, None, {}, business="eticaret"), None, "eticaret")
    book = xlsx.read(data)
    assert list(book) == ["Metodoloji", "Sektör Önceliği", "Ortak SEO Kontrolleri", "Sektörel SEO Kontrolleri", "Audit Özeti"]
    assert book["Metodoloji"][21][:2] == ["1", "1"] and book["Metodoloji"][26][:2] == ["6", "0.3"]  # A22:B27 for VLOOKUP
    assert book["Ortak SEO Kontrolleri"][0][:16] == sector_audit.method()["headers"]["core"]
    assert book["Sektörel SEO Kontrolleri"][0][:20] == sector_audit.method()["headers"]["sec"]
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        wbx = z.read("xl/workbook.xml").decode()
        core = z.read("xl/worksheets/sheet3.xml").decode()
        sec = z.read("xl/worksheets/sheet4.xml").decode()
        summary = z.read("xl/worksheets/sheet5.xml").decode()
    assert 'fullCalcOnLoad="1"' in wbx
    assert '<f>IF(OR(J2="Kontrol Edilmedi",J2="Uygulanamaz",H2="",I2=""),"",IF(J2="Uygun",0,ROUND(20*G2*H2*IF(J2="Hatalı",1,0.5)/I2,1)))</f>' in core.replace("&quot;", '"')
    assert 'sqref="J2:J45"' in core and "Kontrol Edilmedi,Hatalı,Kısmen Uygun,Uygun,Uygulanamaz" in core
    assert 'sqref="N2:N208"' in sec and "VLOOKUP(C2,Metodoloji!$A$22:$B$27,2,FALSE)" in sec
    assert "COUNTIFS(&apos;Sektörel SEO Kontrolleri&apos;!$B$2:$B$208" in summary or "COUNTIFS('Sektörel SEO Kontrolleri'!$B$2:$B$208" in summary
    rows = book["Ortak SEO Kontrolleri"]
    head = rows[0]
    row = next(x for x in rows if x[0] == "CORE-023")
    assert row[head.index("Durum")] == "Hatalı" and row[head.index("Öncelik Skoru")] != "" and row[head.index("Öncelik")].startswith("P")
    assert head[-4:] == ["Maya: Durum nedeni", "Maya kapsamı", "Maya kuralları", "Not"]
    drafts = [x for x in book["Sektörel SEO Kontrolleri"][1:] if x[0].startswith("SEC-T")]
    assert len(drafts) == 33 and all(x[-1] == "taslak — İlginay/Efsa onayı bekliyor" for x in drafts)
    eticaret = next(x for x in book["Audit Özeti"] if x and x[0] == "E-ticaret / perakende")
    assert eticaret[1:3] == ["6", "18"]


def test_sector_xlsx_web_download(finished):  # noqa: F811
    client, audit, _ = finished
    team = client.get(f"{API}/audits/{audit['id']}").json().get("team_report") or \
        client.get(f"{API}/audits/{audit['id']}/summary").json()["team_report"]
    assert team["sector"] == f"/api/v1/audits/{audit['id']}/downloads/sector"
    got = client.get(team["sector"])
    assert got.status_code == 200 and "X-Maya-Release-Gate" in got.headers
    disposition = got.headers["content-disposition"]
    assert "-sektor-audit" in disposition and disposition.rstrip('"').endswith(".xlsx")
    assert list(xlsx.read(got.content))[-1] == "Audit Özeti"
    tr = json.loads((ROOT / "maya_audit_web" / "locales" / "tr.json").read_text(encoding="utf-8"))
    assert tr["download.sector.title"] == "Sektör audit (XLSX)"


# ---------------------------------------------------------------- "Ölçülen değer"

@pytest.mark.parametrize("rule,check,evidence,want", [
    ("idx7.product_no_category", "IDX-7", {"products": 3}, "breadcrumb yok; içerikte kategori bağlantısı yok"),
    # DECISIONS 370: the bots blocked somewhere on the site are not this page's value
    ("acc6.scope", "ACC-6", {"blocked_tokens": ["GPTBot", "OAI-SearchBot"]}, "—"),
    ("acc4.ua_check.status", "ACC-4", {"pairs": [{"url": SITE + "/a", "browser": {"status": 200}, "googlebot": {"status": 429}}]},
     "tarayıcı 200, Googlebot 429"),
    ("str11.two_values", "STR-11", {"contradictions": [{"url": SITE + "/a", "field": "dateModified",
                                                        "descriptions": [{"value": ["2026-10-19"]}, {"value": ["2026-06-10"]}]}]},
     "dateModified: 2026-10-19 / 2026-06-10"),
    ("str5.names", "STR-5", {"variants": [{"name": "Özel Moodist", "pages": 5, "seen_as": [{"url": SITE + "/a"}]},
                                          {"name": "Moodist", "pages": 9, "seen_as": [{"url": SITE + "/b"}]}]},
     "marka adı: Özel Moodist"),
])
def test_measured_value_is_the_findings_own_field_or_a_dash(rule, check, evidence, want):
    record = {"status": 200, "html_bytes": 900_000}  # a page read: its status and size are not this finding's value
    f = {"id": "X", "rule_id": rule, "check_id": check, "evidence": evidence}
    assert page_rows.measured(f, SITE + "/a", "tr", page=record, read=True) == want
    other = {"id": "Y", "rule_id": "zz.none", "check_id": "ZZ-1", "evidence": {}}
    assert page_rows.measured(other, SITE + "/a", "tr", page=record, read=True) == "—"
    status = {"id": "Z", "rule_id": "idx1.4xx.referenced", "check_id": "IDX-1", "evidence": {}}
    assert page_rows.measured(status, SITE + "/a", "tr", page={"status": 404}, read=True) == "HTTP 404"
