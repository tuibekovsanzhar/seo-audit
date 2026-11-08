"""DECISIONS 323: "Okundu mu?" in the appendix's page sheets (pages read first, addresses never read after them), and a
measured value for every page read: `crawl.page_measures` (schema 1.29) in new audits, Maya's pages and a page
reader's; worked out from the saved page records for older audits. Offline: mock transports and a fake reader."""
from __future__ import annotations

import json

import httpx

from maya_audit import client_appendix, client_selection as cs, page_measures, page_rows, xlsx
from maya_audit.audit import run_audit
from maya_audit.config import CrawlConfig
from maya_audit.models import to_jsonable
from maya_audit.report import build_report
from maya_audit.schema import SCHEMA_VERSION, frozen_path
from test_blocked_reader_317 import S, URLS, _read, _site
from test_deadline_hosted_hardening import QUIET
from test_firecrawl import no_lookups  # noqa: F401  (fixture)
from test_v03_client_report import SITE, finding, page, report


def _page(url, words=120, title="T", jumps=0):
    p = page(url, 50)
    p.update({"body_bytes": 1_460_000, "ttfb_ms": 210.4, "headers": {"cf-cache-status": "DYNAMIC"}, "view": "raw",
              "content_checks_eligible": True})
    p["analysis"] = {"title": title, "meta": [{"name": "description", "content": "A description"}],
                     "canonicals": [url], "h1_elements": [{"text": "H"}], "html_lang": "tr", "visible_words": words,
                     "main_offset_bytes": 820_000, "heading_counts": {"skipped_level_jumps_total": jumps,
                                                                      "skipped_level_jumps": [{"from": 1, "to": 3}] * jumps},
                     "structured_data": {"types": ["Product"]}, "image_counts": {"main_content": {"total": 4, "missing_alt": 1}}}
    return p


# ---------------------------------------------------------------- 1: "Okundu mu?" and the order

def _mixed():
    """One finding on two read pages (importance 80 and 60) and on two addresses never read."""
    f = finding("RND-6-l", "rnd6.large", "S4", urls=[SITE + "/never-b", SITE + "/en/a", SITE + "/never-a", SITE + "/a"], check="RND-6")
    f["evidence"] = {"pages": [], "threshold_bytes": 1_000_000}
    pages = [page(SITE + "/", 100, "home", 1), _page(SITE + "/a"), _page(SITE + "/en/a")]
    pages[1]["grouping"]["importance"], pages[2]["grouping"]["importance"] = 80, 60
    return report([f], pages=pages)


def test_both_page_sheets_say_whether_a_page_was_read_and_put_the_read_pages_first():
    book = xlsx.read(client_appendix.build(cs.select(_mixed()), "tr"))
    by_page, found = book["Sayfa bazında"], book["Bulgu bazında"]
    assert by_page[0][:2] == ["Sayfa", "Okundu mu?"] and found[0][3:5] == ["Sayfa", "Okundu mu?"]
    assert [(r[0], r[1]) for r in by_page[1:]] == [(SITE + "/a", "Evet"), (SITE + "/en/a", "Evet"),
                                                  (SITE + "/never-a", "Hayır, okunmadı"), (SITE + "/never-b", "Hayır, okunmadı")]
    assert [r[4] for r in found[1:]] == ["Evet", "Evet", "Hayır, okunmadı", "Hayır, okunmadı"]
    en = xlsx.read(client_appendix.build(cs.select(_mixed()), "en"))["By page"]
    assert en[0][1] == "Read?" and {r[1] for r in en[1:]} == {"Yes", "No, not read"}


def test_within_a_card_the_read_rows_come_first_so_its_link_still_lands_on_its_first_row():
    r = _mixed()
    other = finding("TSEO-1-j", "tseo1.heading_jumps", "S3", urls=[SITE + "/never-c", SITE + "/a"], check="TSEO-1")
    other["evidence"] = {"items": []}
    r["checks"][0]["findings"].insert(0, other)
    rows = page_rows.finding_rows(cs.select(r), None, "en")
    cards = [x["card"] for x in rows]
    assert cards == sorted(cards)  # each card's rows are together
    for n in set(cards):
        reads = [x["read"] for x in rows if x["card"] == n]
        assert reads == sorted(reads, key=lambda v: v is False)  # read first, then never read


def test_how_to_read_explains_the_column_in_one_line():
    for lang, word in (("tr", "Okundu mu?"), ("en", "Read?")):
        lines = client_appendix.READ[lang]["lines"]
        assert len(lines) == 7 and sum(word in line for line in lines) == 1


def test_hosts_and_the_whole_site_are_not_pages():
    f = finding("IDX-2-c", "idx2.expires", "S2", urls=["https://shop.test/"], check="IDX-2")
    f["evidence"] = {"hosts": [{"host": "shop.test", "valid": True, "not_after": "2026-11-14", "days_left": 9}]}
    rows = page_rows.finding_rows(cs.select(report([f, finding("S", "r.s", "S4")])), None, "tr")
    assert {page_rows.read_word(x["read"], "tr") for x in rows} == {"—"}


# ---------------------------------------------------------------- 2: a value for every page read

def test_every_read_page_has_a_value_when_the_evidence_kept_only_a_sample():
    rows = page_rows.finding_rows(cs.select(_mixed()), None, "tr")
    values = {x["url"]: x["value"] for x in rows}
    assert values[SITE + "/a"] == values[SITE + "/en/a"] == "HTML 1.460 KB; sınır 1.000 KB"
    assert values[SITE + "/never-a"] == page_rows.WORDS["tr"]["not_read"]  # not read: said, never "not kept"
    assert not any(v == page_rows.WORDS["tr"]["not_kept"] for v in values.values())


def test_the_value_matches_the_kind_of_finding():
    rec = page_measures.measure(_page(SITE + "/a", jumps=2, title="A long title"))
    say = lambda rule, check: "; ".join(page_rows.from_page({"rule_id": rule, "check_id": check, "evidence": {}}, rec, "en"))  # noqa: E731
    assert say("rnd6.late", "RND-6") == "main content starts after 820 KB"
    assert say("tseo1.heading_jumps", "TSEO-1") == "2 heading level jump(s) (h1→h3)"
    assert say("tseo1.title_long", "TSEO-1") == 'title "A long title" (12 characters)'
    assert say("str16.shared", "STR-16") == 'description 13 characters: "A description"'
    assert say("str2.no_h1", "STR-2") == "1 main heading(s) (h1)"
    assert say("idx6.alias_links", "IDX-6") == f"canonical: {SITE}/a; HTTP 200"
    assert say("prf1.not_cached", "PRF-1") == "first response 210 ms; cache: cf-cache-status: DYNAMIC"
    assert say("str9.lang_mismatch", "STR-9") == "<html lang> tr; 120 words"
    assert say("str3.expected_type", "STR-3") == "structured data: Product"
    assert say("str7.no_alt", "STR-7") == "4 image(s); 1 image(s) without alt text"
    assert say("acc3.utility_indexable", "ACC-3") == "HTTP 200; HTML 1,460 KB"  # no value of its own: status and size


def test_the_findings_own_evidence_wins_over_the_page_record():
    f = {"rule_id": "str12.language", "check_id": "STR-12",
         "evidence": {"pages": [{"url": SITE + "/a", "declared": "en", "main_content_language": "tr"}]}}
    rec = page_measures.measure(_page(SITE + "/a"))
    assert page_rows.measured(f, SITE + "/a", "en", rec, True) == "declared en, content tr"
    assert page_rows.measured(f, SITE + "/b", "en", rec, True) == "<html lang> tr; 120 words"


def test_a_measure_holds_only_what_was_measured():
    bare = {"url": SITE + "/x", "status": 200, "analysis": {"title": "X"}, "content_checks_eligible": True}
    rec = page_measures.measure(bare)
    assert rec == {"status": 200, "title": "X", "title_chars": 1}  # no zero for what was not measured
    assert page_measures.of_pages([bare, {"url": SITE + "/blocked", "status": 403, "analysis": {}},
                                   {"url": SITE + "/empty", "status": 200, "analysis": {"empty_response": True}}]) == {SITE + "/x": rec}


def test_an_old_report_gets_the_records_from_its_saved_pages_and_a_new_one_keeps_its_own():
    old = _mixed()
    assert set(page_measures.index(old)) == {SITE + "/", SITE + "/a", SITE + "/en/a"}
    new = _mixed()
    new["crawl"]["page_measures"] = {SITE + "/reader-only": {"status": 200, "html_bytes": 5000}}
    assert set(page_measures.index(new)) == {SITE + "/", SITE + "/a", SITE + "/en/a", SITE + "/reader-only"}
    assert SITE + "/reader-only" in cs.read_set(new)


def test_a_new_audit_stores_a_record_for_every_page_maya_read(no_lookups):
    transport, _ = _site(blocked=lambda url: False)
    outcome = run_audit(S + "/", CrawlConfig(**{**QUIET, "max_pages": 8}), httpx.MockTransport(transport))
    rep = json.loads(json.dumps(to_jsonable(build_report(outcome.result, outcome.gates, outcome.checks))))
    assert rep["schema_version"] == SCHEMA_VERSION == "1.29"
    stored = rep["crawl"]["page_measures"]
    assert set(stored) == cs.pages_read(rep) and len(stored) >= 5
    assert all(isinstance(r.get("html_bytes"), int) and r.get("title") for r in stored.values())


def test_pages_read_only_through_the_reader_keep_their_records(tmp_path, no_lookups):
    transport, pages = _site()  # Maya's crawler gets a block page everywhere
    outcome, info = _read(tmp_path, transport, pages)
    stored = outcome.result.page_measures or {}
    read = {p["url"] for p in info.get("pages") or [] if p.get("outcome") == "read"} or set(stored)
    assert stored and read <= set(stored) and set(stored) <= set(URLS) | {S + "/"}
    assert all(r.get("view") == "provider" or r.get("status") == 200 for r in stored.values())


def test_the_frozen_schema_adds_page_measures_and_nothing_else():
    from maya_audit.schema import differences
    old = json.loads(frozen_path("1.28").read_text(encoding="utf-8"))
    new = json.loads(frozen_path("1.29").read_text(encoding="utf-8"))
    assert differences(old, new) == ["crawl: added ['page_measures']", "schema_version: '1.28' -> '1.29'"]
