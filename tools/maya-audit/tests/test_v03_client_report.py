"""v0.3 stage 6 (DECISIONS 300): priority score, root-cause merge, "Teyit edin", own limits, the 10-page/15-card gate,
the XLSX appendix, findings seen only in Firecrawl's copy, internal search/cart pages, Shopify's lastmod steps."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from maya_audit import client_appendix, client_selection as cs, double_reading, release_gate, xlsx
from maya_audit.checks.access import indexable_utility_page, utility_indexable_findings

SITE = "https://shop.test"


def page(url, importance, page_type="category", rank=None, read=True):
    return {"url": url, "status": 200, "analysis": {"html_lang": "tr"} if url == SITE + "/" else {},
            "grouping": {"importance": importance, "page_type": page_type, "importance_rank": rank or 100 - importance,
                         "template_key": "/x/*", "read": read}}


def finding(fid, rule, severity="S4", confidence="verified", urls=(), check="STR-1", **extra):
    return {"id": fid, "check_id": check, "rule_id": rule, "title": f"{rule} title {fid}", "severity": severity,
            "confidence": confidence, "scope": {"kind": "template", "count": len(urls), "urls": list(urls)},
            "evidence": {"pages": [{"url": u} for u in urls]}, "how_to_fix": "Fix it.", **extra}


def report(findings, pages=None, **extra):
    pages = pages or [page(SITE + "/", 100, "home", 1), page(SITE + "/a", 80), page(SITE + "/en/a", 60),
                      page(SITE + "/cart", 20, "utility"), page(SITE + "/en", 90, "home", 2)]
    return {"schema_version": "1.23", "crawl": {"start_url": SITE + "/", "pages": pages, "page_grouping": {"method_version": 2}},
            "checks": [{"check_id": "X", "findings": findings}], "findings_in_priority_order": [f["id"] for f in findings],
            **extra}


# ---------------------------------------------------------------- priority

def test_priority_is_severity_times_confidence_times_reach_times_business():
    r = report([finding("A", "r.a", "S2", "verified", [SITE + "/a", SITE + "/en/a"]),
                finding("B", "r.b", "S3", "estimated", [SITE + "/a"]),
                finding("C", "r.c", "S4", "verified", [])])
    by = {g["finding_ids"][0]: g for g in cs.select(r)["groups"]}
    assert by["A"]["priority"] == round(40 * 1.0 * 1.4 * 1.0, 1)        # reach (80 + 60) / 100
    assert by["B"]["priority"] == round(15 * 0.6 * 0.8, 1)
    assert by["C"]["reach"] == 1.0 and by["C"]["priority"] == 5.0          # no address: the homepage
    assert cs.CONFIDENCE_WEIGHT == {"measured": 1.0, "estimated": 0.6, "inferred": 0.5, "unverified": 0.4}
    assert cs.SEVERITY_WEIGHT["S1"] == 100 and cs.SEVERITY_WEIGHT["S4"] == 5


def test_reach_is_capped_and_ranking_never_changes_a_severity():
    many = [page(f"{SITE}/p{i}", 90) for i in range(20)]
    r = report([finding("L", "r.l", "S4", urls=[p["url"] for p in many]), finding("M", "r.m", "S3", urls=[SITE + "/a"])],
               pages=[page(SITE + "/", 100, "home", 1)] + many + [page(SITE + "/a", 80)])
    sel = cs.select(r)
    low = next(g for g in sel["cards"] if g["finding_ids"] == ["L"])
    assert low["reach"] == cs.REACH_CAP and low["priority"] == 25.0
    assert [g["finding_ids"][0] for g in sel["cards"]] == ["L", "M"]  # a broad Low may outrank a narrow Medium
    assert low["severity"] == "S4" and r["checks"][0]["findings"][0]["severity"] == "S4"  # nothing rewritten


def test_unverified_check_weighs_point_four_whatever_its_engine_confidence():
    f = finding("A", "r.a", launch_gated=["LG-61"])
    assert cs.confidence_class(f) == "unverified" and cs.confirm_reason(f) == "unverified_check"


# ---------------------------------------------------------------- one card per root cause

def test_language_copies_of_one_rule_are_one_card_with_an_example_per_language():
    r = report([finding("TR", "shared.heading_jump", urls=[SITE + "/a", SITE + "/cart"]),
                finding("EN", "shared.heading_jump", urls=[SITE + "/en/a"])])
    sel = cs.select(r)
    assert len(sel["cards"]) == 1
    card = sel["cards"][0]
    assert card["finding_ids"] == ["TR", "EN"] and card["languages"] == ["en", "tr"]
    examples = {x["language"]: x["url"] for x in card["examples"]}
    assert examples == {"tr": SITE + "/a", "en": SITE + "/en/a"}  # the cart (a utility page) is never the example


def test_findings_that_differ_in_what_a_card_says_stay_apart():
    r = report([finding("A", "r.a", urls=[SITE + "/a"]), finding("B", "r.a", urls=[SITE + "/en/a"], intent={"kind": "x"}),
                finding("C", "r.a", urls=[SITE + "/a"], launch_gated=["LG-1"])])
    sel = cs.select(r)
    assert [g["finding_ids"] for g in sel["groups"]] == [["A"], ["B"], ["C"]]


# ---------------------------------------------------------------- placement

def test_low_confidence_firecrawl_only_and_spoofed_googlebot_go_to_confirm_first():
    fc = finding("FC", "str12.language", "S3", "estimated", [SITE + "/en/a"],
                 evidence={"reading": {"seen_in": "firecrawl_only"}})
    ua = finding("UA", "acc4.ua_check.status", "Info", "estimated", [SITE + "/a"], check="ACC-4",
                 evidence={"pairs": [{"outcome": "refused", "bot_status": 429}]})
    inf = finding("IN", "r.in", "S4", "inferred", [SITE + "/a"])
    note = finding("NO", "r.no", "Info", "inferred", [SITE + "/a"])
    sel = cs.select(report([fc, ua, inf, note, finding("OK", "r.ok", urls=[SITE + "/a"])]))
    place = {g["finding_ids"][0]: g["placement"] for g in sel["groups"]}
    assert place == {"FC": "confirm", "UA": "confirm", "IN": "confirm", "NO": "note", "OK": "card"}
    assert {g["finding_ids"][0]: g["confirm_reason"] for g in sel["confirm"]} == {
        "FC": "firecrawl_only", "UA": "spoofed_googlebot", "IN": "low_confidence"}


def test_the_owners_manual_check_moves_a_finding_to_a_card_or_out():
    fc = finding("FC", "str12.language", "S3", "estimated", [SITE + "/en/a"], evidence={"reading": {"seen_in": "firecrawl_only"}})
    confirmed = cs.select(report([fc]), confirmations={"str12.language": {"result": "confirmed"}})
    assert confirmed["cards"][0]["finding_ids"] == ["FC"] and confirmed["cards"][0]["confidence"] == "measured"
    rejected = cs.select(report([fc]), confirmations={"FC": {"result": "rejected"}})
    assert not rejected["cards"] and rejected["rejected"][0]["finding_ids"] == ["FC"]
    assert rejected["counts"]["findings"] == 1  # still in the appendix


def test_maya_own_limits_are_coverage_never_a_client_card():
    r = report([finding("R", "acc9.reader.site", "S4", urls=[SITE + "/a"], check="ACC-9")])
    r["crawl"].update(stop_reason="page_cap", config={"max_pages": 50}, deadline_hit=True)
    sel = cs.select(r)
    assert not sel["cards"] and sel["own_limits"][0]["finding_ids"] == ["R"]
    assert [line["kind"] for line in sel["coverage"]["lines"]][:3] == ["page_cap", "time_budget", "reader"]


def test_at_most_fifteen_cards_but_every_blocker_and_high_is_kept():
    lows = [finding(f"L{i}", f"r.l{i}", "S4", urls=[SITE + "/a"]) for i in range(20)]
    sel = cs.select(report(lows))
    assert len(sel["cards"]) == 15 and sel["counts"]["appendix_only"] == 5
    highs = [finding(f"H{i}", f"r.h{i}", "S2", urls=[SITE + "/a"]) for i in range(16)]
    sel = cs.select(report(highs + lows))
    assert len(sel["cards"]) == 16 and all(g["severity"] == "S2" for g in sel["cards"])
    assert [v["rule"] for v in release_gate.check_client_output({}, cards=len(sel["cards"]))] == ["RG-16"]


def test_key_pages_follow_importance_rank_and_name_their_cards():
    sel = cs.select(report([finding("A", "r.a", urls=[SITE + "/", SITE + "/a"])]))
    assert [p["url"] for p in sel["key_pages"][:2]] == [SITE + "/", SITE + "/en"]
    assert sel["key_pages"][0]["cards"] == [1] and sel["key_pages"][1]["cards"] == []


# ---------------------------------------------------------------- gate and appendix

def test_gate_blocks_a_client_pdf_over_ten_pages_or_an_appendix_missing_a_finding():
    r = report([finding("A", "r.a"), finding("B", "r.b")])
    assert [v["rule"] for v in release_gate.check_client_output(r, pages=11)] == ["RG-15"]
    assert release_gate.check_client_output(r, pages=10, cards=15, appendix_ids=["A", "B"]) == []
    missing = release_gate.check_client_output(r, appendix_ids=["A"])
    assert missing[0]["rule"] == "RG-17" and missing[0]["hard"] and missing[0]["finding_id"] == "B"
    assert release_gate.decision(missing) == release_gate.BLOCKED


def test_appendix_xlsx_lists_every_finding_and_address_without_empty_columns():
    r = report([finding("A", "r.a", urls=[SITE + "/a", SITE + "/en/a"]), finding("B", "r.b", "Info", urls=[SITE + "/a"])])
    data = client_appendix.build(cs.select(r), "tr")
    sheets = xlsx.read(data)
    assert list(sheets) == ["Bulgular", "Etkilenen adresler", "Kilit sayfalar", "Kapsam", "Yöntem"]
    assert client_appendix.finding_ids(data) == {"A", "B"}
    assert len(sheets["Etkilenen adresler"]) == 1 + 3
    header = sheets["Bulgular"][0]
    assert "Teyit nedeni" not in header and "Grubun ilk bulgusu" not in header  # empty in every row: left out
    assert all(any(row[i] for row in sheets["Bulgular"][1:]) for i in range(len(header)))


def test_xlsx_writer_keeps_text_numbers_and_turkish_letters():
    data = xlsx.workbook([{"name": "A/B: ç", "header": ["x", "y"], "rows": [["İğüş", 3.5], ["<&>", None]]}])
    assert xlsx.read(data) == {"A B  ç": [["x", "y"], ["İğüş", "3.5"], ["<&>"]]}


def test_card_platform_steps_must_match_the_reports_platform():
    r = report([finding("A", "idx5.stamped", check="IDX-5")], platform={"name": "WordPress"})
    out = release_gate.check_cards({"todos": [{"finding_ids": ["A"], "platform_steps": "Shopify"}]}, r)
    assert any(v["rule"] == "RG-11" and "Shopify" in v["message"] for v in out)
    assert cs.platform_steps("idx5.stamped", "Shopify", "tr")[0].startswith("Shopify site haritasını")
    assert cs.platform_steps("idx5.stamped", "WordPress", "tr") is None


# ---------------------------------------------------------------- seen only in Firecrawl's copy

def test_a_finding_with_no_counterpart_in_mayas_own_reading_is_marked_estimated():
    reader = [{"check_id": "TSEO-1", "findings": [
        {"id": "a", "rule_id": "shared.heading_jump", "confidence": "verified",
         "title": "Repeated block: heading “Cart 0 items” (H3) comes after an H1, skipping a level (on 80 page(s))"},
        {"id": "b", "rule_id": "tseo1.heading_jumps", "confidence": "verified", "title": "47 heading level jump(s) in the page structure"},
        {"id": "c", "rule_id": "shared.links_no_address", "confidence": "verified",
         "title": "Shared header/footer: 147 links have no address (“Türkçe”, “English” and 145 more) (on 88 page(s))"}]}]
    own = [{"check_id": "TSEO-1", "findings": [
        {"rule_id": "shared.heading_jump", "title": "Repeated block: heading “Secure Shopping” (H3) comes after an H1, skipping a level (on 71 page(s))"},
        {"rule_id": "tseo1.heading_jumps", "title": "214 heading level jump(s) in the page structure"},
        {"rule_id": "shared.links_no_address", "title": "Shared header/footer: 140 links have no address (“A”, “B” and 138 more) (on 90 page(s))"}]}]
    assert double_reading.mark(reader, own) == ["a"]
    a = reader[0]["findings"][0]
    assert a["confidence"] == "estimated" and a["evidence"]["reading"]["seen_in"] == "firecrawl_only"
    assert double_reading.NOTE in a["notes"]
    assert double_reading.mark(reader, own) == []  # said once
    assert cs.confirm_reason(a) == "firecrawl_only"


def test_marks_need_mayas_own_copies_of_a_site_firecrawl_read_beside_it():
    blocked = {"firecrawl": {"checks_from_firecrawl": ["STR-1"], "crawl_blocked": {"blocked": True}},
               "crawl": {"pages": [{"url": SITE, "analysis": {"title": "x"}}]}}
    assert not double_reading.applies(blocked)
    beside = {"firecrawl": {"checks_from_firecrawl": ["STR-1"], "crawl_blocked": {"blocked": False}},
              "crawl": {"pages": [{"url": SITE, "analysis": {"title": "x"}, "view": "raw"}]}}
    assert double_reading.applies(beside)


# ---------------------------------------------------------------- internal search and cart pages

def _page(url, meta=(), canonicals=None, status=200, headers=None):
    return SimpleNamespace(url=url, status=status, headers=headers or {},
                           analysis={"meta": list(meta), "canonicals": canonicals if canonicals is not None else [url]})


@pytest.mark.parametrize("url,meta,canonicals,expected", [
    (SITE + "/search", (), None, "search"),
    (SITE + "/en/cart", (), None, "cart"),
    (SITE + "/arama?q=x", (), None, "arama"),
    (SITE + "/search", ({"name": "robots", "content": "noindex"},), None, None),
    (SITE + "/cart", (), [SITE + "/"], None),                 # canonical elsewhere: not indexable as itself
    (SITE + "/search-tips/x", (), None, None),               # only the last segment decides
])
def test_an_indexable_search_or_cart_page(url, meta, canonicals, expected):
    assert indexable_utility_page(_page(url, meta, canonicals)) == expected


def test_search_and_cart_pages_without_noindex_are_one_low_finding():
    found = utility_indexable_findings([_page(SITE + "/search"), _page(SITE + "/cart"), _page(SITE + "/a")], set(), "UA")
    assert len(found) == 1
    f = found[0]
    assert f.rule_id == "acc3.utility_indexable" and f.severity.value == "S4" and f.scope["count"] == 2
    from maya_audit_web import wording
    assert wording.title("ACC-3", f.title, "tr")[1] and "noindex" in wording.fix(f.how_to_fix, "tr")[0]
    from maya_audit.judgments import qualify
    assert "owner decision" not in json.dumps(qualify({"check_id": "ACC-3", "rule_id": f.rule_id, "title": f.title,
                                                       "severity": "S4", "evidence": {}, "scope": f.scope}))
