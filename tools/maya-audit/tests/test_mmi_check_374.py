"""DECISIONS 374 (the owner's MMI Ek check): one judged value per page and metric everywhere (the median the finding was
judged on, with how it was measured; a single measurement named as one), an example and its rows only over their own
threshold, RG-25 / RG-26 in the text check, the robots tag outside <head> with where it sits and Googlebot's view,
and the GTIN example in plain words. Fake data only."""
from __future__ import annotations

from maya_audit import page_rows, text_gate
from maya_audit.example_rows import attach, googlebot_heads, robots_outside, site_example
from maya_audit.reassess_rules import _decisions_374

SITE = "https://shop.test"


def _page(url, totals, ttfbs):
    return {"url": SITE + url, "samples": [{"ttfb_ms": a, "total_ms": b} for a, b in zip(ttfbs, totals)],
            "median_total_ms": sorted(totals)[1], "median_ttfb_ms": sorted(ttfbs)[1]}


def _slow():
    pages = [_page("/", [720, 1714, 1844], [567, 962, 1003]), _page("/slow", [2415, 1829, 1434], [1690, 1143, 900]),
             _page("/fine", [700, 800, 900], [300, 400, 500])]
    return {"id": "PRF-1-s", "check_id": "PRF-1", "rule_id": "prf1.slow", "severity": "S4",
            "title": "3 page(s) take more than 1.5 s (median) to return their HTML",
            "scope": {"urls": [p["url"] for p in pages], "count": 3}, "evidence": {"pages": pages, "threshold_s": 1.5}}


def test_the_example_is_the_slowest_page_over_the_threshold_on_the_judged_value():
    assert site_example(_slow()) == ("/slow: HTML'in tamamı 1.829 ms (3 ölçümün ortancası; ölçümler: 2.415 ms, 1.829 ms, "
                                     "1.434 ms), eşik 1.500 ms")


def test_a_page_under_the_threshold_leaves_the_slow_finding_and_every_row_shows_the_judged_median():
    f = _slow()
    r = {"checks": [{"check_id": "PRF-1", "status": "findings", "findings": [f]}], "crawl": {}}
    affected = {"PRF-1-s": list(f["scope"]["urls"])}
    _decisions_374(r, affected, [])
    assert affected["PRF-1-s"] == [SITE + "/", SITE + "/slow"]
    attach(r)
    assert page_rows.measured(f, SITE + "/", "tr").startswith("HTML'in tamamı 1.714 ms (3 ölçümün ortancası")


def test_one_value_per_page_and_metric_and_no_example_under_its_threshold():
    record = {"version": "t", "decision": "PASS", "violations": [], "counts": {}, "hard": 0}
    made = [{"name": "Özet", "header": ["Kart", "Başlık", "Örnek"],
             "rows": [["3", "a", "/: ilk yanıt 962 ms (3 ölçümün ortancası), eşik 800 ms"],
                      ["10", "b", "/x: HTML'in tamamı 1.000 ms (3 ölçümün ortancası), eşik 1.500 ms"]]},
            {"name": "Bulgu bazında", "header": ["Sorun", "Sayfa", "Ölçülen değer"],
             "rows": [["a", {"text": SITE + "/", "location": SITE + "/"}, "ilk yanıt (tek ölçüm, tarama sırasında) 567 ms"],
                      ["a", SITE + "/", "ilk yanıt 962 ms (3 ölçümün ortancası), eşik 800 ms"]]}]
    out = text_gate.with_consistency(record, made, "tr")
    rules = [v["rule"] for v in out["violations"]]
    assert rules.count("RG-26") == 1 and "1.000 ms" in out["violations"][0]["message"]
    assert "RG-25" not in rules  # "(tek ölçüm)" is labelled apart: not the same metric
    made[1]["rows"].append(["a", SITE + "/", "ilk yanıt 1.003 ms (3 ölçümün ortancası), eşik 800 ms"])
    out = text_gate.with_consistency(record, made, "tr")
    assert [v["rule"] for v in out["violations"]].count("RG-25") == 1 and out["decision"] == "BLOCKED"


def test_the_robots_tag_outside_head_says_where_and_why_and_googlebots_view():
    analysis = {"outside_head": {"robots_content": ["index, follow"], "closed_early_by": None}}
    rec = robots_outside(SITE + "/a", analysis, "Next.js", None)
    assert rec["row"]["tr"] == ('<meta name="robots" content="index, follow">: <head> normal kapandıktan sonra gövdede '
                                "(Next.js meta etiketlerini gövdeye akıtıyor); Googlebot isteğiyle doğrulanmadı")
    early = robots_outside(SITE + "/b", {"outside_head": {"robots_content": ["noindex"], "closed_early_by": "<div#overlay>"}},
                           None, {"robots_head": [], "robots_outside_head": ["noindex"]})
    assert "<div#overlay> öğesinden sonra" in early["row"]["tr"] and "Googlebot olarak istendiğinde de <head> dışında" in early["row"]["tr"]


def test_a_tag_googlebot_gets_in_head_is_not_reported():
    ua = {"pairs": [{"url": SITE + "/a", "googlebot": {"robots_head": ["index, follow"], "robots_outside_head": []}}]}
    assert googlebot_heads(ua)[SITE + "/a"]["robots_head"] == ["index, follow"]
    f = {"id": "ACC-3-r", "check_id": "ACC-3", "rule_id": "acc3.robots_outside_head", "severity": "Info",
         "title": "2 page(s) carry a robots tag outside <head>: browsers ignore it; some crawlers may not",
         "scope": {"urls": [SITE + "/a", SITE + "/b"], "count": 2},
         "evidence": {"robots_tags_outside_head": {SITE + "/a": ["robots"], SITE + "/b": ["robots"]}}}
    pages = [{"url": SITE + u, "analysis": {"outside_head": {"robots_content": ["index, follow"]}}} for u in ("/a", "/b")]
    r = {"checks": [{"check_id": "ACC-3", "status": "findings", "findings": [f]}],
         "crawl": {"pages": pages, "access": {"ua_check": ua}}, "platform": {"name": "Next.js"}}
    affected = {"ACC-3-r": [SITE + "/a", SITE + "/b"]}
    _decisions_374(r, affected, [])
    assert r["checks"][0]["findings"] == []  # /a in <head> for Googlebot; /b streamed the same way


def test_the_gtin_example_says_what_is_missing():
    f = {"id": "STR-3-g", "check_id": "STR-3", "rule_id": "str3.product_no_identifier",
         "evidence": {"pages": [{"url": SITE + "/p", "sku": "41220", "brand": "The Macallan"}]}}
    r = {"checks": [{"check_id": "STR-3", "findings": [f]}], "crawl": {}}
    attach(r)
    assert page_rows.measured(f, SITE + "/p", "tr") == \
        "Product işaretlemesinde gtin (gtin8/12/13/14) ve mpn yok; var olanlar: sku «41220», brand «The Macallan»"
