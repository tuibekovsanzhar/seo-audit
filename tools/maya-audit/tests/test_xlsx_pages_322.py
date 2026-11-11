"""DECISIONS 322: the XLSX appendix for teammates who are not technical ("Nasıl okunur", "Özet", "Sayfa bazında",
"Bulgu bazında"), clickable links and wrapped text, the web app's "Etkilenen sayfalar (N)", and certificate hosts
as plain host names. Offline: in-memory reports, the demo web app; no provider, no live site."""
from __future__ import annotations

import io
import json
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from maya_audit import client_appendix, client_selection as cs, page_rows, xlsx
from test_v03_client_report import SITE, finding, page, report

ROOT = Path(__file__).resolve().parents[1]
TR_SHEETS = ["Nasıl okunur", "Özet", "Sayfa bazında", "Bulgu bazında",
             "Bulgular", "Etkilenen adresler", "Kilit sayfalar", "Şablonlar", "Kapsam", "Yöntem"]
EN_SHEETS = ["How to read", "Summary", "By page", "By finding",
             "Findings", "Affected URLs", "Key pages", "Templates", "Coverage", "Method"]


def _report():
    """Two page problems (one measured on /a with its HTML size), a certificate on two hosts, an Info note."""
    heavy = finding("RND-6-a", "rnd6.large", "S3", urls=[SITE + "/a", SITE + "/en/a"], check="RND-6")
    heavy["evidence"] = {"pages": [{"url": SITE + "/a", "bytes": 1_460_000, "truncated_at_read_cap": False}],
                         "threshold_bytes": 1_000_000}
    jumps = finding("TSEO-1-j", "tseo1.heading_jumps", "S4", urls=[SITE + "/a", SITE + "/cart"], check="TSEO-1")
    jumps["evidence"] = {"items": [{"url": SITE + "/a", "jump_count": 2, "examples": []},
                                   {"url": SITE + "/cart", "jump_count": 1, "examples": []}]}
    cert = finding("IDX-2-c", "idx2.expires", "S2", urls=["https://shop.test/", "https://www.shop.test/"], check="IDX-2")
    cert["evidence"] = {"hosts": [{"host": "shop.test", "valid": True, "not_after": "2026-11-14T00:00:00+00:00", "days_left": 9.1},
                                  {"host": "www.shop.test", "valid": True, "not_after": "2026-11-14T00:00:00+00:00", "days_left": 9.1}]}
    note = finding("STR-2-n", "str2.many_h1", "Info", urls=[SITE + "/en"], check="STR-2")
    return report([cert, heavy, jumps, note])


def _sheets(lang="tr", todos=None, r=None):
    return {s["name"]: s for s in client_appendix.sheets(cs.select(r or _report()), lang, todos=todos)}


# ---------------------------------------------------------------- the four sheets

def test_the_reader_sheets_come_first_in_the_file_language():
    assert list(_sheets("tr")) == TR_SHEETS
    assert list(_sheets("en")) == EN_SHEETS
    book = xlsx.read(client_appendix.build(cs.select(_report()), "en"))
    assert book["By finding"][0][:7] == ["Problem", "Severity", "Issue type", "Page", "Read?", "Measured value", "What to do"]  # 323
    assert book["By finding"][0][-3:] == ["Finding ID", "Rule", "Check"]  # technical IDs at the end
    tr = xlsx.read(client_appendix.build(cs.select(_report()), "tr"))
    assert tr["Bulgu bazında"][0][:7] == ["Sorun", "Önem", "Sorun türü", "Sayfa", "Okundu mu?", "Ölçülen değer", "Ne yapılmalı"]
    assert tr["Sayfa bazında"][0] == ["Sayfa", "Okundu mu?", "Sayfa türü", "Önem puanı (0-100)", "Sorun sayısı", "En yüksek önem", "Sorunlar", "Kartlar"]


@pytest.mark.parametrize("lang", ["tr", "en"])
def test_how_to_read_is_ten_lines_without_a_filter(lang):  # six, "Okundu mu?" (323), P0-P3 (324), links + Quick Look (337)
    how = _sheets(lang)[client_appendix.READ[lang]["how"]]
    assert len(how["rows"]) == 10 and how["frozen"] is False and how["filter"] is False
    assert all(len(row) == 1 and 40 < len(row[0]) < 260 for row in how["rows"])


def test_by_finding_has_one_row_per_finding_and_page_with_the_value_measured_there():
    rows = xlsx.read(client_appendix.build(cs.select(_report()), "tr"))["Bulgu bazında"]
    head, body = rows[0], rows[1:]
    col = {name: head.index(name) for name in head}
    pairs = {(r[col["Bulgu kimliği"]], r[col["Sayfa"]]) for r in body}
    assert pairs == {("IDX-2-c", "shop.test"), ("IDX-2-c", "www.shop.test"), ("RND-6-a", SITE + "/a"),
                     ("RND-6-a", SITE + "/en/a"), ("TSEO-1-j", SITE + "/a"), ("TSEO-1-j", SITE + "/cart"),
                     ("STR-2-n", SITE + "/en")}
    value = {(r[col["Bulgu kimliği"]], r[col["Sayfa"]]): r[col["Ölçülen değer"]] for r in body}
    assert value[("RND-6-a", SITE + "/a")] == "HTML 1.460 KB; sınır 1.000 KB"
    assert value[("TSEO-1-j", SITE + "/cart")] == "1 başlık düzeyi atlaması"
    # a page outside the evidence's sample with no HTML size kept: "—", never the page's generic status (DECISIONS 324)
    assert value[("RND-6-a", SITE + "/en/a")] == "—"
    assert value[("IDX-2-c", "shop.test")].startswith("sertifika 2026-11-14 tarihinde bitiyor; denetimde 9 gün")
    # ordered by severity: the High certificate first, the Info note last
    assert [r[col["Önem"]] for r in body][0] == "Yüksek" and body[-1][col["Önem"]] == "Bilgi"


def test_by_page_lists_pages_with_problems_by_importance_then_severity():
    rows = xlsx.read(client_appendix.build(cs.select(_report()), "en"))["By page"]
    body = rows[1:]
    assert [r[0] for r in body] == [SITE + "/a", SITE + "/en/a", SITE + "/cart"]  # importance 80, 60, 20
    first = dict(zip(rows[0], body[0]))
    assert first["Read?"] == "Yes"
    assert first["Problems"] == "2" and first["Highest severity"] == "Medium" and first["Page type"] == "category"
    # hosts are not pages, and an Info note is not a problem: neither has a row here
    assert not any("www.shop.test" in r[0] or r[0] == SITE + "/en" for r in body)


def test_by_page_puts_pages_without_importance_last():
    r = _report()
    r["checks"][0]["findings"][1]["scope"]["urls"].append(SITE + "/never-read")
    body = xlsx.read(client_appendix.build(cs.select(r), "en"))["By page"][1:]
    assert body[-1][0] == SITE + "/never-read" and body[-1][1] == "No, not read" and body[-1][3] == ""


def test_summary_has_the_pdf_cards_each_linked_to_its_first_row():
    todos = [{"n": 1, "title": "Renew the TLS certificate", "severity": "S2", "issue_type": "issue", "owner": "Developer",
              "effort": "Small", "finding_ids": ["IDX-2-c"], "all_urls": []},
             {"n": 2, "title": "Make heavy pages lighter", "severity": "S3", "issue_type": "issue", "owner": "Developer",
              "effort": "Medium", "finding_ids": ["RND-6-a"], "all_urls": []},
             {"n": 3, "title": "Small fixes", "severity": "Info", "owner": "Developer", "effort": "Small",
              "finding_ids": ["STR-2"], "topics": [{"topic": "questions", "ids": ["STR-2"]}], "all_urls": []}]
    data = client_appendix.build(cs.select(_report()), "en", todos=todos)
    book, links = xlsx.read(data), xlsx.links(data)
    summary = book["Summary"]
    assert [r[:3] for r in summary[1:]] == [["1", "Renew the TLS certificate", "High"], ["2", "Make heavy pages lighter", "Medium"],
                                           ["3", "Small fixes", "Info"]]
    assert [r[7] for r in summary[1:]] == ["2", "2", "0"]  # addresses (after "Priority (P0-P3)", DECISIONS 324)
    found = book["By finding"]
    card = found[0].index("Card")
    for n, ref in ((1, "I2"), (2, "I3")):
        target = links["Summary"][ref]
        m = re.fullmatch(r"#'By finding'!A(\d+)", target)
        assert m, target
        row = int(m.group(1))
        assert found[row - 1][card] == str(n) and all(r[card] != str(n) for r in found[1:row - 1])
    assert "I4" not in links["Summary"]  # card 3 names checks' observations, no finding row: no link
    assert all(r[card] != "3" for r in found[1:])  # a check id on a note card never takes a finding


def test_summary_without_the_team_report_uses_the_selection_cards_in_the_file_language():
    sel = cs.select(_report())
    names = [r[1] for r in xlsx.read(client_appendix.build(sel, "tr", title=lambda c, t: "TR:" + t))["Özet"][1:]]
    assert names and all(n.startswith("TR:") or n in {g["title"]["tr"] for g in cs.MERGE_GROUPS} for n in names)


def test_addresses_are_clickable_and_hosts_are_plain_names():
    data = client_appendix.build(cs.select(_report()), "tr")
    book, links = xlsx.read(data), xlsx.links(data)
    found = book["Bulgu bazında"]
    page_col = found[0].index("Sayfa")
    letter = "ABCDEFGHIJKLM"[page_col]
    for i, row in enumerate(found[1:], 2):
        ref = f"{letter}{i}"
        if row[page_col].startswith("https://"):
            assert links["Bulgu bazında"][ref] == row[page_col]
        else:
            # shown as the plain host name, still opening the host's root when clicked
            assert row[page_col] in ("shop.test", "www.shop.test")
            assert links["Bulgu bazında"][ref] == f"https://{row[page_col]}/"
    assert all(v.startswith(SITE) for v in links["Sayfa bazında"].values()) and links["Sayfa bazında"]
    # DECISIONS 322 (7): the technical address sheet shows a certificate's hosts as host names too
    urls = book["Etkilenen adresler"]
    assert [r[3] for r in urls[1:] if r[0] == "IDX-2-c"] == ["shop.test", "www.shop.test"]


def test_rg17_still_reads_the_technical_findings_sheet():
    r = _report()
    data = client_appendix.build(cs.select(r), "tr")
    assert client_appendix.finding_ids(data, "tr") == {"IDX-2-c", "RND-6-a", "TSEO-1-j", "STR-2-n"}
    assert client_appendix.finding_ids(client_appendix.build(cs.select(r), "en"), "en") == {"IDX-2-c", "RND-6-a", "TSEO-1-j", "STR-2-n"}


def test_empty_reader_sheets_say_why():
    sheets = _sheets("tr", r=report([]))
    for key in ("summary", "by_page", "by_finding"):
        sheet = sheets[client_appendix.READ["tr"][key]]
        assert sheet["header"] == ["Not"] and sheet["rows"] == [[client_appendix.READ["tr"]["empty"][key]]]


def test_maya_limits_and_rejected_findings_stay_out_of_the_reader_sheets():
    r = _report()
    sel = cs.select(r, None, {"RND-6-a": {"result": "rejected", "by": "Owner", "date": "2026-11-07"}})
    rows = page_rows.finding_rows(sel, None, "en")
    assert "RND-6-a" not in {x["finding_id"] for x in rows}
    assert "RND-6-a" in client_appendix.finding_ids(client_appendix.build(sel, "en"), "en")  # still in the appendix


# ---------------------------------------------------------------- measured values

@pytest.mark.parametrize("rule,evidence,url,want", [
    ("str12.language", {"pages": [{"url": SITE + "/en/a", "declared": "en", "main_content_language": "tr", "foreign_share": 0.98}]},
     SITE + "/en/a", "declared en, content tr; 98% of the content in another language"),
    ("str16.shared", {"groups": [{"description": "Same words", "count": 3, "urls": [SITE + "/a", SITE + "/b", SITE + "/c"]}]},
     SITE + "/b", 'same description on 3 pages: "Same words"'),
    ("idx6.tracking", {"links": [{"source": SITE + "/a", "target": SITE + "/b?utm_source=x", "parameters": ["utm_source"]}]},
     SITE + "/a", "tracking parameter in a link: utm_source"),
    ("idx6.links_to_redirect", {"targets": [{"url": SITE + "/old", "final": SITE + "/new", "linked_from": [SITE + "/a"]}]},
     SITE + "/a", f"link to a redirecting address: {SITE}/old → {SITE}/new"),
    ("rnd7.no_region", {"pages": [SITE + "/a"]}, SITE + "/a", "seen on this page (see Problem)"),
    ("tseo1.url_decomposed", {"addresses": []}, SITE + "/collections/i%CC%87pek",
     f"decomposed letter: U+0307; correct spelling: {SITE}/collections/ipek"),
    ("rnd6.large", {"pages": [{"url": SITE + "/z", "bytes": 1}]}, SITE + "/a", page_rows.WORDS["en"]["not_kept"]),
])
def test_the_value_measured_on_a_page_comes_from_its_own_evidence(rule, evidence, url, want):
    f = {"id": "X-1-a", "check_id": rule.split(".")[0].upper().replace("RND6", "RND-6"), "rule_id": rule, "evidence": evidence,
         "scope": {"urls": [url]}}
    assert page_rows.measured(f, url, "en") == want


def test_page_sizes_say_html_only_for_html_checks():
    f = {"check_id": "ACC-8", "rule_id": "acc8.present", "evidence": {"url": SITE + "/llms.txt", "bytes": 6000}}
    assert page_rows.measured(f, SITE + "/llms.txt", "tr") == "boyut 6 KB"


# ---------------------------------------------------------------- the file opens cleanly

def test_the_file_is_well_formed_with_frozen_headers_filters_wrapping_and_external_links():
    data = client_appendix.build(cs.select(_report()), "tr")
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = z.namelist()
        for name in names:
            if name.endswith((".xml", ".rels")):
                ET.fromstring(z.read(name))  # every part parses
        types = z.read("[Content_Types].xml").decode()
        sheets = [n for n in names if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n)]
        assert len(sheets) == len(TR_SHEETS) and all(f"/{n}" in types for n in sheets)
        how, found = z.read("xl/worksheets/sheet1.xml").decode(), z.read("xl/worksheets/sheet4.xml").decode()
        assert 'state="frozen"' not in how and "<autoFilter" not in how
        assert 'state="frozen"' in found and "<autoFilter" in found and "<hyperlinks>" in found
        assert found.index("<autoFilter") < found.index("<hyperlinks>")  # the schema's order
        rels = z.read("xl/worksheets/_rels/sheet4.xml.rels").decode()
        assert 'TargetMode="External"' in rels and SITE + "/a" in rels
        styles = z.read("xl/styles.xml").decode()
        assert 'wrapText="1"' in styles and "<u/>" in styles
        assert ' s="2"' in found and ' s="3"' in found  # wrapped text and link cells


def test_links_skip_addresses_excel_cannot_take():
    long = SITE + "/" + "a" * 2100
    data = xlsx.workbook([{"name": "S", "header": ["u"], "rows": [[{"text": long, "link": long}],
                                                                  [{"text": "x", "link": "javascript:alert(1)"}],
                                                                  [{"text": "ok", "link": SITE + "/ok"}]]}])
    assert xlsx.links(data)["S"] == {"A4": SITE + "/ok"}
    assert xlsx.read(data)["S"][1][0] == long  # still shown as text


# ---------------------------------------------------------------- certificate bands (DECISIONS 322 (7))

@pytest.mark.parametrize("days,want", [(30, "S3"), (14, "S2"), (7, "S1"), (30.4, None)])
def test_certificate_bands_are_inclusive_in_the_engine(days, want):
    from maya_audit.checks.index import expiry_severity
    from maya_audit.config import CrawlConfig
    inside = days <= CrawlConfig.tls_expiry_warning_days
    assert (expiry_severity(days).value if inside else None) == want


def test_brief_counts_a_14_day_certificate_as_high():
    from maya_audit_web.team_report import brief
    r = {"checks": [{"check_id": "IDX-2", "findings": [{"rule_id": "idx2.expires", "evidence": {"hosts": [{"days_left": 14}]}}]}]}
    assert brief.worst_severity([], {}, r) == "S2"
    r["checks"][0]["findings"][0]["evidence"]["hosts"][0]["days_left"] = 14.5
    assert brief.worst_severity([], {}, r) == "none"


# ---------------------------------------------------------------- the web app

from test_web_app import API, audit_of, error, web  # noqa: E402,F401  (fixture)


@pytest.fixture
def finished(web):  # noqa: F811
    client = web()
    audit = audit_of(client)
    assert audit["state"] == "finished"
    return client, audit


def test_each_problem_card_offers_its_affected_pages_with_the_full_list(finished):
    client, audit = finished
    overview = client.get(f"{API}/audits/{audit['id']}/overview", params={"lang": "tr"}).json()
    assert overview["available"] and overview["fixes"]
    for fix in overview["fixes"]:
        assert isinstance(fix["pages"], int)
        body = client.get(f"{API}/audits/{audit['id']}/cards/{fix['n']}/pages", params={"lang": "tr"}).json()
        assert body["n"] == fix["n"] and body["count"] == fix["pages"] == len(body["rows"])
        assert body["columns"]["address"] == "Adres" and body["columns"]["value"] == "Ölçülen değer"
        for row in body["rows"]:
            assert row["address"] and row["finding_ids"] and isinstance(row["value"], str)
    en = client.get(f"{API}/audits/{audit['id']}/cards/{overview['fixes'][0]['n']}/pages", params={"lang": "en"}).json()
    assert en["columns"]["address"] == "Address"
    error(client.get(f"{API}/audits/{audit['id']}/cards/999/pages"), 404, "card_not_found")


def test_the_web_appendix_has_the_reader_sheets_and_the_pdf_cards(finished):
    client, audit = finished
    book = xlsx.read(client.get(f"{API}/audits/{audit['id']}/downloads/xlsx", params={"lang": "tr"}).content)
    assert list(book)[:4] == TR_SHEETS[:4]
    overview = client.get(f"{API}/audits/{audit['id']}/overview", params={"lang": "tr"}).json()
    titles = [row[1] for row in book["Özet"][1:]]
    assert [f["title"] for f in overview["fixes"]] == titles[:len(overview["fixes"])]


def test_the_results_page_has_the_pages_button_search_and_csv():
    script = (ROOT / "maya_audit_web" / "static" / "app.js").read_text(encoding="utf-8")
    assert 'T("cards.pages", { count: f.pages })' in script and "cardPages(view.audit.id, f.n, lang)" in script
    assert 'type: "search"' in script and 'T("cards.csv")' in script and "text/csv;charset=utf-8" in script
    tr = json.loads((ROOT / "maya_audit_web" / "locales" / "tr.json").read_text(encoding="utf-8"))
    from maya_audit_web.strings import STRINGS
    keys = [k for k in STRINGS["en"] if k.startswith("cards.")]
    assert len(keys) >= 13 and all(k in tr for k in keys)
    assert tr["cards.pages"] == "Etkilenen sayfalar ({count})" and tr["cards.csv"] == "CSV indir"
