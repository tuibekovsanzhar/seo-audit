"""DECISIONS 368: İlginay's review of "Diğer bulgular" in an Ek, as global rules. A homepage with many headings is never
"too few" (product names marked as <h2> are said instead); headings are compared with the page's own language; a
canonical is said to name another page only when every reading agrees and one is final; each page's line names the
text, element and place; the Özet lists a problem only with a concrete example, and RG-24 names the ones left out.
Fake pages and reports only."""
from __future__ import annotations

import json

from maya_audit import client_appendix, example_rows, reassess_rules, text_gate, xlsx
from maya_audit import client_selection as cs
from maya_audit.language import heading_language

SITE = "https://shop.test"


def _report(checks, pages=(), render=None, firecrawl=None):
    return {"checks": checks, "crawl": {"pages": list(pages), "render": {"pages": render or {}}},
            "firecrawl": {"pages": firecrawl or []}}


def _check(check_id, *findings):
    return {"check_id": check_id, "status": "findings", "findings": list(findings), "evidence": {}}


def _finding(fid, check_id, rule, title, urls, evidence, severity="S3"):
    return {"id": fid, "check_id": check_id, "rule_id": rule, "title": title, "severity": severity,
            "confidence": "verified", "scope": {"kind": "page", "count": len(urls), "urls": list(urls)},
            "evidence": evidence, "engines": [], "how_to_fix": "", "expected": "", "notes": []}


def _cards_page(n_products=12):
    headings = [{"level": 1, "text": "Shop"}, {"level": 2, "text": "Weekly offers"}]
    lines = ["Shop", "Weekly offers", "See all"]
    for i in range(n_products):
        headings.append({"level": 2, "text": f"Product {i} 75CL"})
        lines += ["Region", f"Product {i} 75CL", f"AED {50 + i}.00", "10% Off"]
    return headings, lines


# ---------------------------------------------------------------------------------------------- (1) the outline

def test_a_homepage_with_many_headings_is_never_too_few_and_product_names_as_h2_are_said_instead():
    headings, lines = _cards_page()
    hidden = [{**h, "hidden": True} for h in headings]  # a dialog marked the page aria-hidden in one reading
    outline = _finding("STR-2-o", "STR-2", "str2.home_outline", "The homepage has 0 visible section heading(s) for 900 words",
                       [SITE + "/"], {"pages": [{"url": SITE + "/", "visible_h2_h3": []}], "minimum_subheadings": 3})
    r = _report([_check("STR-2", outline)], pages=[{"url": SITE + "/", "depth": 0, "status": 200,
                                                     "analysis": {"headings": hidden}}])
    saved = [json.dumps({"url": SITE + "/", "headings": headings, "main_text": "\n".join(lines)})]
    affected = {"STR-2-o": [SITE + "/"]}
    changes: list[str] = []
    reassess_rules._decisions_368(r, affected, changes, saved)
    rules = [f["rule_id"] for f in r["checks"][0]["findings"]]
    assert rules == ["str2.card_headings"]
    card = r["checks"][0]["findings"][0]
    assert card["title"] == "The homepage marks 12 product names as <h2> headings" and card["severity"] == "S4"
    page = card["evidence"]["pages"][0]
    assert page["section_headings"] == ["Weekly offers"] and page["examples"][0] == "Product 0 75CL"
    assert "13 H2 başlığın 12 tanesi ürün kartı adı: «Product 0 75CL»" in page["row"]["tr"]
    assert any("removed, the homepage has 13 <h2>/<h3> headings" in c for c in changes)


def test_a_few_product_headings_are_not_a_finding():
    headings, lines = _cards_page(n_products=3)
    assert example_rows.card_headings(headings, lines) and len(example_rows.card_headings(headings, lines)) == 3
    from maya_audit.checks.structure import card_headings_finding
    assert card_headings_finding(SITE + "/", headings, lines, set()) is None


# ---------------------------------------------------------------------------------------------- (2) heading language

def test_english_question_headings_are_english_on_an_english_page():
    for heading in ("How do I move up a tier?", "Do my points expire?", "How do I request a manual adjustment?"):
        assert heading_language(heading, declared="en") == "en"
    row = {"url": SITE + "/faqs", "declared": "en", "headings_language": "pt", "headings_count": 3,
           "headings": ["How do I move up a tier?", "Do my points expire?", "How do I request a manual adjustment?"]}
    f = _finding("STR-12-h", "STR-12", "str12.headings",
                 "1 page(s) have section headings in another language than they declare (declared English, headings in Portuguese)",
                 [SITE + "/faqs"], {"pages": [row]})
    r = _report([_check("STR-12", f)])
    affected = {"STR-12-h": [SITE + "/faqs"]}
    reassess_rules._decisions_368(r, affected, [], [])
    assert r["checks"][0]["findings"] == [] and "STR-12-h" not in affected


def test_headings_in_another_language_than_the_page_are_kept_with_examples():
    row = {"url": SITE + "/a", "declared": "en", "headings_language": "de", "headings_count": 3,
           "headings": ["Antworten auf die häufigsten Fragen", "Unterschied zu den anderen Angeboten",
                        "Alles zu den Kosten auf einen Blick", "Antworten auf die häufigsten Fragen"]}
    f = _finding("STR-12-h", "STR-12", "str12.headings",
                 "1 page(s) have section headings in another language than they declare (declared English, headings in German)",
                 [SITE + "/a"], {"pages": [row]})
    r = _report([_check("STR-12", f)])
    reassess_rules._decisions_368(r, {"STR-12-h": [SITE + "/a"]}, [], [])
    kept = r["checks"][0]["findings"][0]["evidence"]["pages"][0]
    assert kept["row"]["tr"].startswith("sayfanın dili İngilizce (<html lang>); başlıklar Almanca: «Antworten auf die häufigsten")


# ---------------------------------------------------------------------------------------------- (3) canonical readings

def test_canonical_readings_say_whether_they_agree_and_which_is_final():
    v = example_rows.canonical_versions
    assert v([SITE + "/"], {"canonicals": [SITE + "/x"], "settled": True}, None)["verdict"] == "differ"
    assert v([SITE + "/"], {"canonicals": [SITE], "settled": False}, None)["verdict"] == "not_final"
    assert v([SITE + "/"], {"canonicals": [SITE], "settled": False}, {"canonicals": [SITE + "/"]})["verdict"] == "agree"
    assert v([SITE + "/"], None, None)["verdict"] == "raw_only"
    line = example_rows.canonical_row(v([SITE + "/"], {"canonicals": [SITE + "/x"], "settled": False,
                                                        "read_at": "2026-11-16T12:48:06+00:00"}, None))["tr"]
    assert line == ("ham HTML: https://shop.test/; tarayıcıda işlenmiş: https://shop.test/x "
                    "(2026-11-16, sayfa yüklenmesi bitmeden okundu)")


def test_a_canonical_read_before_the_page_finished_loading_is_not_said_and_differing_readings_are_their_own_finding():
    rows = [{"url": SITE + "/about", "canonical": SITE + "/"}, {"url": SITE + "/help", "canonical": SITE + "/"}]
    f = _finding("IDX-4-d", "IDX-4", "idx4.different", "2 page(s) are canonicalized to a URL with different content",
                 [r["url"] for r in rows], {"pages": rows})
    pages = [{"url": SITE + "/about", "analysis": {"canonicals": [SITE + "/"]}},
             {"url": SITE + "/help", "analysis": {"canonicals": [SITE + "/"]}}]
    render = {SITE + "/about": {"ok": True, "network_idle": False, "started_at": "2026-11-16T12:00:00+00:00",
                                "rendered": {"canonicals": [SITE + "/"]}},
              SITE + "/help": {"ok": True, "network_idle": True, "rendered": {"canonicals": [SITE + "/help"]}}}
    r = _report([_check("IDX-4", f)], pages=pages, render=render)
    affected = {"IDX-4-d": [r_["url"] for r_ in rows]}
    reassess_rules._decisions_368(r, affected, [], [])
    findings = r["checks"][0]["findings"]
    assert [x["rule_id"] for x in findings] == ["idx4.versions_differ"]
    assert findings[0]["scope"]["urls"] == [SITE + "/help"] and findings[0]["severity"] == "S3"
    assert "tarayıcıda işlenmiş: https://shop.test/help" in findings[0]["evidence"]["pages"][0]["row"]["tr"]
    assert r["checks"][0]["evidence"]["not_assessed"][0]["url"] == SITE + "/about"


# ---------------------------------------------------------------------------------------------- (4) each page's line

def test_each_page_line_names_the_text_the_element_and_the_place():
    link = _finding("STR-19-l", "STR-19", "shared.link_no_address", "x", [SITE + "/a"],
                    {"shared_element": {"text": "Gift Cards", "why": "empty href", "component": "div.menu"},
                     "by_page": [{"url": SITE + "/a", "links": 1}]}, "S4")
    slug = _finding("TSEO-1-s", "TSEO-1", "tseo1.url_slug_unclear", "x", [SITE + "/blog/12345"],
                    {"pages": [{"url": SITE + "/blog/12345", "why": "id only"}]}, "S4")
    generic = _finding("STR-14-g", "STR-14", "judgment.generic.identity", "x", [SITE + "/"],
                       {"links": [{"source": SITE + "/", "target": SITE + "/shop/wine", "anchor": "See all", "in_navigation": False}]}, "S4")
    shown = _finding("RND-3-r", "RND-3", "rnd3.revealed", "x", [SITE + "/faq"],
                     {"pages": [{"url": SITE + "/faq", "clicked": [{"tag": "button", "text": "Who can order?"}],
                                 "new_text_sample": "adults only"}]})
    late = _finding("RND-1-p", "RND-1", "rnd1.partial", "x", [SITE + "/p"],
                    {"pages": [{"url": SITE + "/p", "content_delta": {"missing_text_blocks": [
                        {"text": "Delivery and returns"}, {"text": "Free delivery over 200"}, {"text": "Order now"}]}}]})
    render = {SITE + "/p": {"rendered": {"headings": [{"level": 2, "text": "Delivery and returns"}],
                                         "buttons": [{"text": "Order now"}]}}}
    r = _report([_check("X", link, slug, generic, shown, late)],
                pages=[{"url": SITE + "/blog/12345", "analysis": {"title": "Linen shirt care guide | Shop"}}], render=render)
    example_rows.attach(r)
    rows = {f["id"]: f["evidence"] for f in r["checks"][0]["findings"]}
    assert rows["STR-19-l"]["by_page"][0]["row"]["tr"] == "«Gift Cards» bağlantısı: <a> href boş; her sayfada tekrarlanan alanda (div.menu)"
    assert rows["TSEO-1-s"]["pages"][0]["row"]["tr"] == ("kısa ad «12345» (5 karakter, yalnızca bir kimlik/numara); "
                                                         "öneri: «linen-shirt-care-guide-shop»")
    assert rows["STR-14-g"]["links"][0]["row"]["tr"] == "hedefi söylemeyen bağlantı metni: «See all» → /shop/wine (içerikte)"
    assert rows["RND-3-r"]["pages"][0]["row"]["tr"] == ("tıklanan: «Who can order?» (<button>); "
                                                        "sonra görünen kelimeler (örnek): «adults only»")
    assert rows["RND-1-p"]["pages"][0]["row"]["tr"] == (
        "JavaScript'le gelen metin: «Delivery and returns» (başlık H2); «Free delivery over 200» (metin, bölüm "
        "«Delivery and returns»); «Order now» (düğme, bölüm «Delivery and returns»)")


def test_a_slug_suggestion_keeps_the_address_words_without_stopwords():
    assert example_rows.slug_suggestion("the-elves-ultimate-events-guide-part-2-abu-dhabi-grand-prix") == \
        "elves-ultimate-events-guide-abu-dhabi"
    assert example_rows.slug_suggestion("4711") is None


# ---------------------------------------------------------------------------------------------- (5) the Özet

def test_the_summary_lists_a_problem_only_with_a_concrete_example_and_rg24_names_the_others():
    from test_v03_client_report import finding, report
    shown = finding("A", "shared.link_no_address", "S4", urls=[SITE + "/a"], check="STR-19")
    shown["evidence"] = {"by_page": [{"url": SITE + "/a", "links": 1,
                                      "row": {"tr": "«Gift Cards» bağlantısı: <a> href boş", "en": "x"}}]}
    bare = finding("B", "str3.article_no_author", "S4", urls=[SITE + "/b"], check="STR-3")
    bare["evidence"] = {"articles": 4, "without_author": 1}
    sel = cs.select(report([shown, bare]))
    record = {"version": "t", "decision": "PASS", "violations": [], "counts": {}, "hard": 0}
    files = client_appendix.build_files(sel, "tr", todos=[{"n": None, "appendix_only": True, "finding_ids": []}],
                                        text_check=record)
    book = {**xlsx.read(files["client"]), **xlsx.read(files["team"])}  # DECISIONS 376: "Kontrol raporu" is the team's
    summary = book["Özet"]
    assert summary[0][-1] == "Örnek"
    others = next(i for i, r in enumerate(summary) if str(r[1]).startswith("Diğer bulgular"))
    assert summary[others][1].endswith("; ölçülen değeri olmayan 1 bulgu yalnız «Bulgular» sayfasında")
    listed = summary[others + 1:]
    assert len(listed) == 1 and listed[0][-1] == "/a: «Gift Cards» bağlantısı: <a> href boş"
    rg = [r for r in book["Kontrol raporu"] if r[0] == "RG-24"]
    assert len(rg) == 1 and rg[0][2] == "Hayır" and "örnek ya da ölçülen değer yok" in rg[0][5]
    assert text_gate.with_no_example(record, [], "tr") is record
