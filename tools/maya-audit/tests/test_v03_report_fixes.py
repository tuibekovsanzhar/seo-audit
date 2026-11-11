"""DECISIONS 305: percent-escape case is one address; reach counts only pages that were read; one count of the parts not
assessed; a merged card's title and whole scope in the summary, findings table and action plan; evidence tables print
the measured value and no empty column. Made-up reports only; no socket, nothing paid."""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace

from maya_audit import client_appendix, client_selection as cs
from maya_audit.urls import normalize_url, upper_escapes
from test_v03_client_report import SITE, finding, page, report

SKILL = Path(__file__).resolve().parents[1] / ".agents" / "skills" / "maya-audit-pro"


# ---------------------------------------------------------------- 1. one address whatever the escapes' case

def test_percent_escapes_are_upper_case_so_one_page_is_one_address():
    assert normalize_url("/pages/etbi%cc%87s", SITE + "/") == normalize_url(SITE + "/pages/etbi%CC%87s") == SITE + "/pages/etbi%CC%87s"
    assert normalize_url(SITE + "/a?q=%c4%b1&x=1") == SITE + "/a?q=%C4%B1&x=1"
    assert upper_escapes("/a%2fb/c") == "/a%2Fb/c" and upper_escapes("/plain-ascii") == "/plain-ascii"


def test_a_canonical_that_differs_only_in_escape_case_names_the_page_itself():
    from maya_audit.index_data import canonical_elsewhere
    from maya_audit.page_groups import canonical_aliases

    def made(url, canonical):
        return SimpleNamespace(url=url, headers={}, status=200, analysis={"canonicals": [canonical], "meta": []},
                               redirect_location=None)
    # A page saved by an earlier engine, its own address with lower-case escapes, its canonical upper-case.
    old = made(SITE + "/pages/etbi%cc%87s", SITE + "/pages/etbi%CC%87s")
    new = made(SITE + "/pages/etbi%CC%87s", "/pages/etbi%cc%87s")
    other = made(SITE + "/collections/x/products/y", SITE + "/products/y")
    assert not canonical_elsewhere(old) and not canonical_elsewhere(new) and canonical_elsewhere(other)
    nodes = {p.url for p in (old, new, other)}
    assert canonical_aliases([old, new, other], nodes, SITE) == {other.url: SITE + "/products/y"}


# ---------------------------------------------------------------- 2. reach: pages read only

def test_addresses_that_were_never_read_add_nothing_to_reach_and_are_counted_apart():
    unread = [f"{SITE}/sitemap-only/{i}" for i in range(1500)]
    r = report([finding("WIDE", "r.wide", urls=[SITE + "/a"] + unread),
                finding("READ", "r.read", urls=[SITE + "/a"]),
                finding("GONE", "r.gone", urls=unread[:10]),
                finding("FILE", "r.file", urls=[SITE + "/sitemap.xml"], check="IDX-5"),
                finding("NONE", "r.none", urls=[])])
    by = {g["finding_ids"][0]: g for g in cs.select(r)["groups"]}
    assert by["WIDE"]["reach"] == by["READ"]["reach"] == round(1 + math.log1p(80 / 100), 6)   # /a alone (80)
    assert (by["WIDE"]["pages_counted"], by["WIDE"]["addresses_not_read"]) == (1, 1500)
    assert by["GONE"]["reach"] == 1.0 and by["GONE"]["addresses_not_read"] == 10               # nothing read: the minimum
    home = round(1 + math.log1p(100 / 100), 6)
    assert by["FILE"]["reach"] == by["NONE"]["reach"] == home                                   # a file, no address: the homepage
    # A canonical scored only from its aliases (`read: False`) was not read either.
    r2 = report([finding("C", "r.c", urls=[SITE + "/canon"])],
                pages=[page(SITE + "/", 100, "home", 1), page(SITE + "/canon", 70, "product", read=False)])
    assert cs.select(r2)["groups"][0]["addresses_not_read"] == 1


def test_the_appendix_lists_pages_read_and_addresses_not_read_per_finding():
    r = report([finding("WIDE", "r.wide", urls=[SITE + "/a", SITE + "/never"])])
    sheets = {s["name"]: s for s in client_appendix.sheets(cs.select(r), "en")}
    header, row = sheets["Findings"]["header"], sheets["Findings"]["rows"][0]
    assert row[header.index("Pages read (reach)")] == 1 and row[header.index("Not read")] == 1


# ---------------------------------------------------------------- 3a. one count of the parts not assessed

def test_parts_not_assessed_are_counted_once_without_the_unread_restatements():
    r = report([finding("A", "r.a", urls=[SITE + "/a"])])
    r["checks"] = [
        {"check_id": "STR-1", "status": "partial", "findings": [], "coverage": {"not_assessed": [
            {"part": "pages found but not read", "reason": "this check ran on the 5 page(s) that were read"},
            {"part": "og:image URLs", "reason": "not fetched"}]}},
        {"check_id": "STR-2", "status": "partial", "findings": r["checks"][0]["findings"], "coverage": {"not_assessed": [
            {"part": "og:image URLs", "reason": "not fetched"},
            {"part": "addresses found but not fetched by the crawl", "reason": "x"}]}},
        {"check_id": "IDX-9", "status": "not_assessed", "title": "Google index status", "summary": "Needs Search Console.",
         "findings": []}]
    r["answer_engine_panel"] = [{"check_id": "ANS-1", "status": "not_assessed", "title": "Cited URLs", "summary": "No data."}]
    sel = cs.select(r)
    lines = [line for line in sel["coverage"]["lines"] if line["kind"] == "not_assessed"]
    assert [(line["part"], line["checks"]) for line in lines] == [
        ("og:image URLs", ["STR-1", "STR-2"]), ("Google index status", ["IDX-9"]), ("Cited URLs", ["ANS-1"])]
    assert sel["counts"]["not_assessed"] == 3


# ---------------------------------------------------------------- 3b, 3c. the pro report

def _builder(r, lang="tr"):
    sys.path.insert(0, str(SKILL / "scripts"))
    import build_data as build
    import render
    catalog = json.loads((build.REFS / "sahip_efor.json").read_text(encoding="utf-8"))
    sel = cs.select(r)
    w = build.Wording(lang, str(SKILL.parents[2]))  # the engine's own wording, as --maya-src loads it
    return build.Builder(r, lang, render.LABELS[lang], catalog, w, None, "test", selection=sel), sel


def _html_weight_report():
    many = [page(f"{SITE}/c{i}", 70) for i in range(30)]
    home_large = finding("RND-6-home", "rnd6.home_large", "S3", urls=[SITE + "/"], check="RND-6",
                         title="The homepage's HTML is 885 KB, above 500 KB",
                         evidence={"pages": [{"url": SITE + "/", "bytes": 885000}], "threshold_bytes": 500000})
    late = finding("RND-6-late", "rnd6.late", "S4", urls=[p["url"] for p in many], check="RND-6",
                   title="30 page(s): the main content starts after the first 500 KB of HTML")
    return report([home_large, late], pages=[page(SITE + "/", 100, "home", 1)] + many)


def test_a_merged_card_is_named_and_counted_as_the_card_in_the_summary_the_table_and_the_action_plan():
    b, sel = _builder(_html_weight_report())
    [card] = [g for g in sel["cards"] if g["merge_group"] == "html_weight"]
    assert card["finding_ids"] == ["RND-6-home", "RND-6-late"]
    d = b.build()
    title = cs.MERGE_BY_RULE["rnd6.home_large"]["title"]["tr"]
    row = next(f for f in d["findings"] if f["id"] == "RND-6-home")
    # The table names what is wrong (DECISIONS 306), the card's whole scope; the action plan says what to do.
    assert row["title"] == cs.MERGE_BY_RULE["rnd6.home_large"]["finding"]["tr"] and row["scope"] == "1 sayfa (+30 sayfa: Düşük)"  # DECISIONS 339: each severity's pages
    action = next(a for a in d["actions"] if a["ref"] == "RND-6-home")
    assert action["title"] == title
    first = d["priorities"][0]
    assert first["value"] == "1 sayfa (+30 sayfa: Düşük)" and first["finding_ids"] == ["RND-6-home", "RND-6-late"]


def test_the_evidence_sample_shows_the_measured_value_and_drops_columns_empty_in_every_row():
    b, _ = _builder(_html_weight_report())
    sample = b.build()["evidence_sample"]
    assert sample["columns"] == ["ADRES", "ÖLÇÜLEN", "SINIR"] and sample["rows"] == [["/", "885 KB", "500 KB"]]
    no_facts = {"columns": ["ADRES", "HTTP", "SONUÇ"], "rows": [["/a", "—", "—"], ["/b", "—", "—"]]}
    assert b._without_empty_columns(no_facts) == {"columns": ["ADRES"], "rows": [["/a"], ["/b"]]}


# ---------------------------------------------------------------- DECISIONS 306: client-report polish

def test_a_fix_that_renames_addresses_is_at_least_medium_effort_and_never_a_quick_win():
    from maya_audit.recommendation_catalog import RENAMES_ADDRESSES, note
    assert note("TSEO-1", "1689 address(es) contain a decomposed character (a letter followed by a combining mark)")["effort"] == "M"
    assert note("TSEO-1", "3 page address(es) have an unclear slug (an id only, over 100 characters, or spaces and symbols)")["effort"] == "M"
    r = report([finding("TSEO-1-d", "tseo1.url_decomposed", "S4", urls=[SITE + "/a"], check="TSEO-1",
                        title="1 address(es) contain a decomposed character (a letter followed by a combining mark)",
                        how_to_fix="x", evidence={}),
                finding("STR-2-h", "str2.no_h1", "S4", urls=[SITE + "/en/a"], check="STR-2", title="1 page(s) have no <h1>")])
    b, _ = _builder(r)
    d = b.build()
    rename = next(t for t in d["todos"] if t.get("rule_id") in RENAMES_ADDRESSES)
    assert rename["effort"] == "Orta" and rename["n"] not in d.get("quick_wins", (d.get("client") or {}).get("quick_wins", []))
    import json as _json
    tr = _json.loads((SKILL.parents[2] / "maya_audit" / "rule_actions.json").read_text(encoding="utf-8"))["actions"]
    assert "handle" in tr["tseo1.url_decomposed"]["steps"]["tr"][0] and "kısa ad" in tr["tseo1.url_decomposed"]["steps"]["tr"][0]


def test_the_confirm_list_speaks_to_the_client_and_keeps_the_technical_reason_in_the_appendix():
    import json as _json
    from maya_audit_web import strings
    labels = _json.loads((SKILL.parents[2] / "maya_audit_web" / "team_report" / "refs" / "etiketler.json").read_text(encoding="utf-8"))
    for lang in ("tr", "en"):
        shown = list(labels[lang]["confirm_reasons"].values()) + [strings.t(f"c6.reason.{k}", lang) for k in cs.CONFIRM_REASONS]
        for text in shown:
            assert "Firecrawl" not in text and "gerçek sitelerde" not in text and "real sites" not in text, text
    assert labels["tr"]["confirm_reasons"]["firecrawl_only"] == "Doğrulama bekliyor: farklı okuma yolunda görüldü"
    assert labels["tr"]["confirm_reasons"]["unverified_check"] == "Doğrulama bekliyor: kontrol yeni"
    tr_web = _json.loads((SKILL.parents[2] / "maya_audit_web" / "locales" / "tr.json").read_text(encoding="utf-8"))
    assert all("Firecrawl" not in tr_web[f"c6.reason.{k}"] for k in cs.CONFIRM_REASONS)
    assert client_appendix.WORDS["tr"]["reason"]["firecrawl_only"] == "yalnız Firecrawl kopyasında görüldü"  # the XLSX keeps it


def test_a_turkish_appendix_holds_no_english_sentence_of_the_engine():
    from maya_audit_web import wording
    titles = ["1 page(s) have no <h1>", "3 link(s) on 3 page(s) have no text at all"]
    fixes = ["Add one <h1> that names the page's topic."]
    r = report([finding("STR-2-h", "str2.no_h1", "S4", urls=[SITE + "/a"], check="STR-2", title=titles[0], how_to_fix=fixes[0]),
                finding("STR-14-t", "str14.no_text", "S4", urls=[SITE + "/en/a"], check="STR-14", title=titles[1],
                        how_to_fix=fixes[0])])
    parts = [("pages left out of this comparison",
              "a shared description on these pages could not be judged fairly (4 language version of a page already counted)"),
             ("og:image URLs",
              "not fetched (another origin with external link checks off, a cap, or robots.txt) or the status was inconclusive")]
    r["checks"].append({"check_id": "STR-10", "status": "partial", "findings": [],
                        "coverage": {"not_assessed": [{"part": p, "reason": why} for p, why in parts]}})
    sheets = client_appendix.sheets(cs.select(r), "tr", None,
                                    title=lambda c, t: wording.title(c, t, "tr")[0], fix=lambda t: wording.fix(t, "tr")[0],
                                    label=lambda t: wording.label(t, "tr")[0], line=lambda t: wording.line(t, "tr")[0])
    cells = [c for s in sheets for row in s["rows"] for c in row if isinstance(c, str)]
    english = set(titles) | set(fixes) | {p for p, _ in parts} | {why for _, why in parts} | set(client_appendix.WORDS["en"]["page_type"].values()) - {"category", "product"}
    assert not [c for c in cells if any(e in c for e in english)]
    assert not [c for c in cells if "(İngilizce)" in c]
    assert client_appendix._manual("confirmed · Owner · 2026-11-03 · seen", client_appendix.WORDS["tr"]).startswith("teyit edildi · Owner")
    key_pages = next(s for s in sheets if s["name"] == "Kilit sayfalar")
    # DECISIONS 312: the homepage's language versions are one row, "ana sayfa (N dil)".
    import re
    assert {re.sub(r"^ana sayfa \(\d+ dil\)$", "ana sayfa", row[2]) for row in key_pages["rows"]} <= set(
        client_appendix.WORDS["tr"]["page_type"].values())


def test_the_saved_copy_row_is_not_printed_when_no_page_came_from_a_saved_copy():
    b, _ = _builder(_html_weight_report())
    labels = [row["label"] for row in b.build()["coverage"]["rows"]]
    assert "Kayıtlı kopyadan okunan sayfa" not in labels and "Değerlendirilmeyen kapsam" in labels
