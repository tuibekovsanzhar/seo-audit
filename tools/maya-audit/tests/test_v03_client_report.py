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
    import math
    r = report([finding("A", "r.a", "S2", "verified", [SITE + "/a", SITE + "/en/a"]),
                finding("B", "r.b", "S3", "estimated", [SITE + "/a"]),
                finding("C", "r.c", "S4", "verified", [])])
    by = {g["finding_ids"][0]: g for g in cs.select(r)["groups"]}
    assert by["A"]["priority"] == round(40 * 1.0 * (1 + math.log1p(140 / 100)), 3)   # reach 1 + ln(1 + (80 + 60) / 100)
    assert by["B"]["priority"] == round(15 * 0.6 * (1 + math.log1p(0.8)), 3)
    assert by["C"]["reach"] == round(1 + math.log1p(1.0), 6)                            # no address: the homepage (100)
    assert cs.CONFIDENCE_WEIGHT == {"measured": 1.0, "estimated": 0.6, "inferred": 0.5, "unverified": 0.4}
    assert cs.SEVERITY_WEIGHT["S1"] == 100 and cs.SEVERITY_WEIGHT["S4"] == 5


def test_a_medium_is_never_below_a_low_and_ranking_never_changes_a_severity():
    many = [page(f"{SITE}/p{i}", 90) for i in range(200)]
    r = report([finding("L", "r.l", "S4", urls=[p["url"] for p in many]), finding("M", "r.m", "S3", urls=[SITE + "/a"]),
                finding("M2", "r.m2", "S3", "inferred", [SITE + "/a"], launch_gated=[]),
                finding("H", "r.h", "S2", "estimated", [SITE + "/en/a"])],
               pages=[page(SITE + "/", 100, "home", 1)] + many + [page(SITE + "/a", 80), page(SITE + "/en/a", 60)])
    sel = cs.select(r)
    low = next(g for g in sel["groups"] if g["finding_ids"] == ["L"])
    medium = next(g for g in sel["groups"] if g["finding_ids"] == ["M"])
    assert low["priority"] > medium["priority"]                      # a broad Low may score higher ...
    assert [g["finding_ids"][0] for g in sel["cards"]] == ["H", "M", "L"]  # ... but bands come first (DECISIONS 301)
    assert r["checks"][0]["findings"][0]["severity"] == "S4"         # nothing rewritten


def test_different_reach_never_gives_identical_scores():
    totals = [0, 10, 90, 100, 101, 500, 2000, 2050, 15000, 15090, 40000, 49000]
    reaches = [cs.reach_of(t) for t in totals]
    assert len(set(reaches)) == len(reaches) and reaches == sorted(reaches) and max(reaches) < cs.REACH_CAP
    scores = {cs._score(sev, "measured", x) for x in reaches for sev in ("S4",)}
    assert len(scores) == len(reaches)


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
    # DECISIONS 348: each source's reads come first
    assert [line["kind"] for line in sel["coverage"]["lines"]][:4] == ["sources", "page_cap", "time_budget", "reader"]


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
    # DECISIONS 312: "/en" (the homepage in English) is part of the homepage's row, not a row of its own.
    assert [p["url"] for p in sel["key_pages"][:2]] == [SITE + "/", SITE + "/a"]
    assert sel["key_pages"][0]["languages"] == [SITE + "/", SITE + "/en"]
    assert sel["key_pages"][0]["cards"] == [1] and sel["key_pages"][1]["cards"] == [1]


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
    assert list(sheets) == ["Nasıl okunur", "Özet", "Sayfa bazında", "Bulgu bazında",  # DECISIONS 322
                            "Kontrol listesi", "Kontrol listesi özeti",  # DECISIONS 342
                            "Bulgular", "Etkilenen adresler", "Kilit sayfalar", "Şablonlar", "Kapsam", "Yöntem",  # 315
                            "Düzeltme kaydı"]  # DECISIONS 363
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


# ---------------------------------------------------------------- DECISIONS 301

def test_merge_table_puts_every_html_size_finding_on_one_card_with_the_worst_pages():
    rows = [finding("H1", "rnd6.home_large", "S3", urls=[SITE + "/"], check="RND-6",
                    evidence={"pages": [{"url": SITE + "/", "bytes": 885_000}]}),
            finding("H2", "rnd6.large", "S4", urls=[SITE + "/a", SITE + "/en/a"], check="RND-6",
                    evidence={"pages": [{"url": SITE + "/a", "bytes": 1_300_000}, {"url": SITE + "/en/a", "bytes": 1_100_000}]}),
            finding("H3", "rnd6.late", "S4", urls=[SITE + "/a"], check="RND-6",
                    evidence={"pages": [{"url": SITE + "/a", "main_offset_bytes": 700_000}]})]
    sel = cs.select(report(rows))
    [card] = sel["cards"]
    assert card["finding_ids"] == ["H1", "H2", "H3"] and card["severity"] == "S3" and card["merge_group"] == "html_weight"
    assert [x["url"] for x in card["examples"]] == [SITE + "/a", SITE + "/en/a", SITE + "/"]  # largest first
    assert set(sel["by_finding"]) == {"H1", "H2", "H3"}                                     # all in the appendix
    table = {g["id"]: g["rules"] for g in cs.merge_table()}
    assert "rnd6.late" in table["html_weight"] and len({r for rules in table.values() for r in rules}) == sum(map(len, table.values()))


def test_review_file_confirms_a_finding_which_then_competes_for_the_cards(tmp_path):
    from maya_audit import manual_review
    fc = finding("FC", "str12.language", "S3", "estimated", [SITE + "/en/a"], check="STR-12",
                 evidence={"reading": {"seen_in": "firecrawl_only"}})
    path = manual_review.path_for(tmp_path / "artifacts" / "report.json")
    assert path.name == "review.json"
    manual_review.record(path, manual_review.entry("FC", "rejected", by="A", seen="first look"))
    manual_review.record(path, manual_review.entry("FC", "confirmed", by="Owner", seen="menu and titles in Turkish",
                                                   note="“Üst Giyim” is translated as “Outerwear”", when="2026-11-03"))
    review = manual_review.load(path)
    assert [e["result"] for e in review["entries"]] == ["confirmed"] and review["replaced"][0]["result"] == "rejected"
    sel = cs.select(report([fc]), confirmations=manual_review.confirmations(review))
    [card] = sel["cards"]
    assert card["confidence"] == "measured" and card["manual"]["note"].endswith("“Outerwear”")
    with pytest.raises(ValueError):
        manual_review.entry("FC", "maybe", by="x", seen="y")
    with pytest.raises(ValueError):
        manual_review.entry("FC", "confirmed", by=" ", seen="y")  # who checked is required
    assert "seen" not in manual_review.entry("FC", "confirmed", by="x", seen="")  # what was seen is optional (DECISIONS 310)


def _record(url, menu, titles, lang, alt=None):
    return {"url": url, "status": 200,
            "outlinks": [{"target": SITE + "/c", "anchor": m, "nav": True} for m in menu]
                        + [{"target": SITE + "/products/" + str(i), "anchor": t} for i, t in enumerate(titles)],
            "analysis": {"html_lang": lang, "hreflang": [{"hreflang": "tr", "href": alt}] if alt else [],
                         "buttons": [{"text": "Add to cart"}], "breadcrumbs": [], "images": [], "h1_elements": []}}


def test_language_finding_names_the_regions_in_the_other_language_and_advises_on_them():
    from maya_audit import language_regions
    tr = _record(SITE + "/kaban", ["Kaban", "Mont", "Ferace"], ["Deri Tüylü Kaban", "Yün Kaban"], "tr")
    en = _record(SITE + "/en/kaban", ["Coats", "Mont", "Ferace"], ["Deri Tüylü Kaban", "Yün Kaban"], "en", alt=SITE + "/kaban")
    r = {"crawl": {"pages": [tr, en]}, "brand": {"name": "Shop"}, "platform": {"name": "Shopify"},
         "checks": [{"check_id": "STR-12", "findings": [finding("L", "str12.language", "S3", "estimated", [en["url"]], check="STR-12",
                    evidence={"pages": [{"url": en["url"], "declared": "en", "main_content_language": "tr", "foreign_share": 0.9}]})]}]}
    assert language_regions.attach(r) == ["L"] and language_regions.attach(r) == []
    found = r["checks"][0]["findings"][0]["evidence"]["regions"]
    regions = {t["region"]: t for t in found["regions"]}
    assert regions["menu"]["foreign"] == 2 and regions["menu"]["in_other_language"]       # "Mont", "Ferace": identical
    assert regions["titles"]["foreign"] == 2 and "buttons" not in regions                   # "Add to cart" is English
    assert found["pages_compared_with_other_version"] == 1
    steps = language_regions.advice(found, "Shopify", "tr")
    assert steps[0].startswith("Shopify'da Translate & Adapt") and any("Menü" in x for x in steps)
    assert "WPML" in language_regions.advice(found, "WordPress", "en")[0]
    assert language_regions.line(found, {"menu": "menu", "titles": "titles", "body": "body"}).startswith("menu 67%")


def test_one_source_for_every_count():
    rows = [finding("A", "r.a", "S2", urls=[SITE + "/a"]), finding("B", "r.b", "S4", urls=[SITE + "/a"]),
            finding("C", "r.c", "Info", urls=[SITE + "/a"]), finding("D", "r.d", "S4", "inferred", [SITE + "/en/a"])]
    sel = cs.select(report(rows))
    c = sel["counts"]
    assert c["by_severity"] == {"S1": 0, "S2": 1, "S3": 0, "S4": 2, "Info": 1}
    assert c["problems"] == 3 and c["findings"] == 4 == sum(c["by_severity"].values())
    data = client_appendix.build(sel, "en")
    assert len(xlsx.read(data)["Findings"]) - 1 == c["findings"]


# ---------------------------------------------------------------- every output prints the same numbers (DECISIONS 301 (5))

from test_report_agreement import demo_app  # noqa: E402,F401  (fixture)


@pytest.mark.parametrize("site_name", ["SHOP", "BANK"])
def test_web_pdf_pro_pdf_xlsx_and_markdown_print_the_same_counts(demo_app, site_name, tmp_path):  # noqa: F811
    import re
    import subprocess
    import sys
    from pathlib import Path
    from html import unescape
    from maya_audit_web import demo
    from test_report_agreement import audit
    one = audit(demo_app, getattr(demo, site_name))
    base = f"/api/v1/audits/{one['id']}"
    folder = demo_app.app.state.runner.artifacts(one["id"])
    report = json.loads((folder / "report.json").read_text(encoding="utf-8"))
    affected = json.loads((folder / "affected-urls.json").read_text(encoding="utf-8")) if (folder / "affected-urls.json").exists() else None
    sel = cs.select(report, affected)
    c = sel["counts"]
    # Web concise print: the severity tiles and the summary line.
    text = re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", demo_app.get(base + "/print?lang=en").text)))
    for level, name in (("S1", "Blocker"), ("S2", "High"), ("S3", "Medium"), ("S4", "Low"), ("Info", "Note")):
        assert re.search(rf"\b{c['by_severity'][level]} {name}", text), (level, text[:600])
    assert f"{c['findings']} finding" in text and f"{c['cards']} card" in text
    # XLSX appendix: one row per finding, by severity.
    sheets = xlsx.read(demo_app.get(base + "/downloads/xlsx?lang=en").content)
    rows = sheets["Findings"][1:]
    assert len(rows) == c["findings"]
    for level, name in cs.SEVERITY_NAME.items():
        assert sum(1 for r in rows if r[3] == name) == c["by_severity"][level]
    # Markdown: "N problems across assessed scope ... + M notes".
    md = demo_app.get(base + "/downloads/markdown").text
    head = re.search(r"\*\*(\d+) problems? across assessed scope.*?\+ (\d+) notes?\*\*", md)
    assert head, md[:400]
    assert (int(head.group(1)), int(head.group(2))) == (c["problems"], c["by_severity"]["Info"])
    # Pro report data: the KPI and the coverage box.
    skill = Path(__file__).resolve().parents[1] / ".agents" / "skills" / "maya-audit-pro" / "scripts" / "build_data.py"
    out = tmp_path / "data.json"
    run = subprocess.run([sys.executable, str(skill), str(folder / "report.json"), "--lang", "en", "-o", str(out),
                          "--maya-src", str(Path(__file__).resolve().parents[1])], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["kpis"][0]["value"] == str(c["problems"])
    assert data["appendix"]["counts"]["findings"] == c["findings"]
    rows = {row["label"]: row["value"] for row in data["coverage"]["rows"]}
    assert rows["Additional notes"] == str(c["by_severity"]["Info"])
    # The pro report as printed (DECISIONS 305): the parts not assessed are one number on page 1 (coverage box), page 3
    # (provenance line) and the last page (own limits). The PDF is printed from this HTML (render.py).
    for slot in data["_slots"]:
        parts = re.findall(r"[^.\[\]]+", slot["path"])
        holder = data
        for part in parts[:-1]:
            holder = holder[int(part)] if part.isdigit() else holder[part]
        key = int(parts[-1]) if parts[-1].isdigit() else parts[-1]
        if isinstance(holder[key], str) and "⟪" in holder[key]:
            holder[key] = "Check the page"
    out.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    html = tmp_path / "pro.html"
    run = subprocess.run([sys.executable, str(skill.with_name("render.py")), str(out), "-o", str(html)], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    printed = re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", html.read_text(encoding="utf-8"))))
    n = c["not_assessed"]
    assert rows["Unassessed scope items"] == str(n)
    assert f"Unassessed scope items {n}" in printed and f"{n} scope items unassessed" in printed
    assert (f"{n} parts not assessed" in printed) == bool(n)
    assert sorted(int(x) for x in re.findall(r"(\d+) (?:scope items unassessed|parts not assessed)", printed)) == [n] * (1 + bool(n))


def test_web_review_buttons_write_the_audits_review_file_and_the_card_says_so(demo_app):  # noqa: F811
    from maya_audit import manual_review
    from maya_audit_web import demo
    from test_report_agreement import audit
    one = audit(demo_app, demo.SHOP)
    base = f"/api/v1/audits/{one['id']}"
    view = demo_app.get(base + "/summary").json()
    # The appendix's button is in the team report's section, in its chosen language (DECISIONS 308).
    assert [d["format"] for d in view["downloads"]][:2] == ["pdf", "markdown"] and view["team_report"]["xlsx"].endswith("/downloads/xlsx")
    folder = demo_app.app.state.runner.artifacts(one["id"])
    report = json.loads((folder / "report.json").read_text(encoding="utf-8"))
    target = next(f for c in report["checks"] for f in c.get("findings") or [] if f["severity"] in ("S2", "S3", "S4"))
    token = {"x-maya-token": demo_app.headers.get("x-maya-token", "")}
    bad = demo_app.post(base + "/review", json={"finding_id": "NOPE-1", "result": "confirmed", "by": "A", "seen": "B"}, headers=token)
    assert bad.status_code == 404
    ok = demo_app.post(base + "/review", json={"finding_id": target["id"], "result": "confirmed", "by": "Owner",
                                              "seen": "seen in a browser", "note": "checked on the live page"}, headers=token)
    assert ok.status_code == 200, ok.text
    entries = manual_review.load(folder / "review.json")["entries"]
    assert entries[-1]["finding_id"] == target["id"] and entries[-1]["by"] == "Owner"
    assert any(target["id"] in r["finding_ids"] for r in ok.json()["reviewed"])
    printed = demo_app.get(base + "/print?lang=en").text
    if f'{target["id"]}' in printed:  # on a card: the card says who confirmed it, and the note
        assert "confirmed by manual check (Owner," in printed and "checked on the live page" in printed
    assert json.loads((folder / "report.json").read_text(encoding="utf-8")) == report  # the report itself is never changed


def test_no_dom_call_in_the_web_page_can_print_null():
    """A raw replaceChildren/append turns a null child into the text "null" ("nullnull" under the "Confirm first"
    list, 2 Nov nihan Quick 50). Optional children go through el(), add() or fill(), which drop null, undefined and
    false; a raw call may only take what is always a node."""
    import re
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / "maya_audit_web" / "static" / "app.js").read_text(encoding="utf-8")
    helpers = re.compile(r"^function (el|add|fill)\(")
    offending = []
    for number, line in enumerate(source.splitlines(), 1):
        if helpers.match(line.strip()) or "child instanceof Node" in line:
            continue
        for call in re.finditer(r"\.(replaceChildren|append|prepend)\(", line):
            rest = line[call.end():]
            if re.search(r"\?[^:]*:\s*null\b|\bnull\s*[,)]", rest):
                offending.append((number, line.strip()[:120]))
    assert offending == []


def test_key_pages_say_why_they_are_empty_when_no_page_could_be_scored():
    blocked = {"schema_version": "1.22", "crawl": {"start_url": SITE + "/", "pages": [{"url": SITE + "/", "status": 429}]},
               "firecrawl": {"crawl_blocked": {"blocked": True}, "pages": [{"url": SITE + "/", "outcome": "read"}]},
               "checks": [{"check_id": "X", "findings": [finding("A", "r.a", urls=[SITE + "/"])]}]}
    sel = cs.select(blocked)
    assert sel["key_pages"] == [] and sel["key_pages_reason"] == "reader_only"
    rows = xlsx.read(client_appendix.build(sel, "en"))["Key pages"]
    assert len(rows) == 2 and "saved copies keep no links" in " ".join(rows[1])
    nothing = {"crawl": {"start_url": SITE + "/", "pages": []}, "checks": []}
    assert cs.select(nothing)["key_pages_reason"] == "no_pages"
    assert cs.select(report([finding("A", "r.a", urls=[SITE + "/a"])]))["key_pages_reason"] is None
