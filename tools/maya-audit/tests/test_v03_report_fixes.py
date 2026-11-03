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
    sheets = client_appendix.sheets(cs.select(r), "en")
    header, row = sheets[0]["header"], sheets[0]["rows"][0]
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
    assert row["title"] == title and row["scope"] == "31 sayfa"                 # not the lead's "885 KB ... 1 sayfa"
    action = next(a for a in d["actions"] if a["ref"] == "RND-6-home")
    assert action["title"] == title
    first = d["priorities"][0]
    assert first["value"] == "31 sayfa" and first["finding_ids"] == ["RND-6-home", "RND-6-late"]


def test_the_evidence_sample_shows_the_measured_value_and_drops_columns_empty_in_every_row():
    b, _ = _builder(_html_weight_report())
    sample = b.build()["evidence_sample"]
    assert sample["columns"] == ["ADRES", "ÖLÇÜLEN", "SINIR"] and sample["rows"] == [["/", "885 KB", "500 KB"]]
    no_facts = {"columns": ["ADRES", "HTTP", "SONUÇ"], "rows": [["/a", "—", "—"], ["/b", "—", "—"]]}
    assert b._without_empty_columns(no_facts) == {"columns": ["ADRES"], "rows": [["/a"], ["/b"]]}
