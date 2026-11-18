"""What is wrong on one page: each row of "Problems by page" speaks for that page, with that page's own numbers.

Every finding, page and site here is made up. Nothing is requested.
"""
import json
import re

import pytest

from maya_audit import schema
from maya_audit.report import (MORE_ON_PAGE, PAGE_KINDS, PAGE_RULES, headline, holes, page_form, page_item, page_sentence,
                               phrase, problem_summary, problems_by_page_lines, with_page_items)

SITE = "https://made-up-shop.example"


def finding(check_id, title, severity="S4", urls=(), evidence=None, *, kind=None, count=None, number=1):
    urls = [f"{SITE}{path}" for path in urls]
    return {"id": f"{check_id}-made-up-{number}", "check_id": check_id, "title": title, "severity": severity, "evidence": evidence or {},
            "scope": {"kind": kind or ("page" if len(urls) == 1 else "template"), "count": len(urls) if count is None else count, "urls": urls[:25]}}


def said(made, path):
    return page_sentence(page_item(made, f"{SITE}{path}"))


# -- the page's own number, never the site-wide count ---------------------------------------------------------------
def test_tseo1_a_long_title_is_said_with_that_pages_own_length():
    made = finding("TSEO-1", "31 page title(s) above the 60-character guidance band", urls=["/a", "/b"],
                   evidence={"items": [{"url": f"{SITE}/a", "title": "A made-up title", "characters": 78}, {"url": f"{SITE}/b", "characters": 61}]})
    item = page_item(made, f"{SITE}/a")
    assert item == {"finding_id": made["id"], "check_id": "TSEO-1", "severity": "S4", "kind": "title_long", "values": {"characters": 78, "limit": 60}}
    assert page_sentence(item) == "Title above the editorial guidance band (78 characters)" and said(made, "/b") == "Title above the editorial guidance band (61 characters)"
    row = problem_summary([made], pages_checked=2)["by_page"][0]
    assert row["url"] == f"{SITE}/a" and row["finding_ids"] == [made["id"]] and row["items"] == [item]  # same order as finding_ids
    lines = problems_by_page_lines(problem_summary([made], pages_checked=2), {made["id"]: made["title"]}, SITE)
    assert "| `/a` | 1 | Low | Title above the editorial guidance band (78 characters) |" in lines and "31 page title(s)" not in "\n".join(lines)


def test_a_page_beyond_the_cut_evidence_list_never_borrows_the_site_wide_count():
    pages = [f"/p{n}" for n in range(45)]
    rows = [{"url": f"{SITE}{path}", "characters": 70 + n} for n, path in enumerate(pages[:40])]  # the check keeps 40 rows
    made = finding("TSEO-1", "45 page title(s) above the 60-character guidance band", urls=pages, evidence={"items": rows, "item_count": 45})
    summary = problem_summary([made], {made["id"]: [f"{SITE}{path}" for path in pages]}, pages_checked=45)
    by_url = {row["url"]: row["items"][0] for row in summary["by_page"]}
    assert len(by_url) == 45 and page_sentence(by_url[f"{SITE}/p39"]) == "Title above the editorial guidance band (109 characters)"
    beyond = by_url[f"{SITE}/p40"]  # page 41: listed as affected, its length not in the report
    assert beyond["kind"] == "title_long" and beyond["values"] == {"limit": 60} and page_form(beyond) == "plain"
    assert page_sentence(beyond) == "Title above the editorial guidance band (over 60 characters)"
    table = "\n".join(problems_by_page_lines(summary, {made["id"]: made["title"]}, SITE, None))  # every page (the Markdown shows 25)
    assert "45 page title(s)" not in table and "| `/p44` | 1 | Low | Title above the editorial guidance band (over 60 characters) |" in table


def test_str19_links_without_an_address_say_the_pages_number_only_when_the_report_holds_it():
    title = "30 link(s) have no address a crawler can follow (they may still work for visitors through JavaScript)"
    by_link = {"links": [{"text": "Read more", "why": 'href="#"', "pages": 40, "example": f"{SITE}/a"}], "links_count": 30, "pages_count": 48}
    old = finding("STR-19", title, urls=["/a", "/b"], evidence=by_link)  # as saved before 1.10: no list by page
    assert page_item(old, f"{SITE}/a")["values"] == {}
    assert said(old, "/a") == "Has links with no address a crawler can follow (number on this page not recorded)"
    assert not any(character.isdigit() for character in said(old, "/a"))
    new = finding("STR-19", title, urls=["/a", "/b"], evidence={**by_link, "by_page": [{"url": f"{SITE}/a", "links": 3}, {"url": f"{SITE}/b", "links": 1}]})
    assert said(new, "/a") == "3 links have no address a crawler can follow" and said(new, "/b") == "1 link has no address a crawler can follow"


def test_idx4_a_canonical_to_different_content_names_the_address_it_points_to():
    target = f"{SITE}/en/en/"
    made = finding("IDX-4", "1 page(s) are canonicalized to a URL with different content", "S2", ["/en/"], {"pages": [
        {"url": f"{SITE}/en/", "canonical": target, "resolved_via": [target, f"{SITE}/", f"{SITE}/tr/"], "value": 0.042}]})
    assert said(made, "/en/") == f"Canonical points to {target} (which ends at /tr/): different content"
    direct = finding("IDX-4", "1 page(s) are canonicalized to a URL with different content", "S2", ["/a"], {"pages": [
        {"url": f"{SITE}/a", "canonical": f"{SITE}/b", "resolved_via": [f"{SITE}/b"], "value": 0.1}]})
    assert said(direct, "/a") == f"Canonical points to {SITE}/b: different content"
    assert said(direct, "/not-in-the-list") == "Canonical points to a URL with different content"


# -- problems that are about several pages together -----------------------------------------------------------------
def test_str1_a_title_shared_by_four_pages_says_three_other_pages_on_each():
    group = [f"{SITE}/p{n}" for n in range(4)]
    made = finding("STR-1", "1 title(s) are shared by 4 different indexable pages", urls=[f"/p{n}" for n in range(4)],
                   evidence={"groups": [{"title": "Made-up Shop", "urls": group}]})
    assert [said(made, f"/p{n}") for n in range(4)] == ["Shares its title “Made-up Shop” with 3 other pages"] * 4
    pair = finding("IDX-8", "2 indexable pages share the title 'Made-up Shop'", urls=["/a", "/b"],
                   evidence={"title": "Made-up Shop", "urls": [f"{SITE}/a", f"{SITE}/b"]})
    assert said(pair, "/a") == "Shares its title “Made-up Shop” with 1 other page"
    shared = finding("STR-16", "1 meta description(s) are shared by 3 different indexable pages", urls=["/a", "/b", "/c"],
                     evidence={"groups": [{"description": "Made up.", "count": 3, "urls": [f"{SITE}/a", f"{SITE}/b", f"{SITE}/c"]}]})
    assert said(shared, "/c") == "Shares its meta description with 2 other pages"
    one_way = finding("STR-9", "1 page(s) have hreflang links that are not returned", urls=["/tr/"],
                      evidence={"links": [{"url": f"{SITE}/tr/", "hreflang": "en", "target": f"{SITE}/en/", "status": 200}]})
    assert said(one_way, "/tr/") == f"hreflang en to {SITE}/en/ is not returned"


# -- the other kinds a real audit showed ----------------------------------------------------------------------------
def test_each_made_up_finding_reads_as_that_pages_own_fact():
    page = f"{SITE}/a"
    cases = [
        (finding("IDX-6", "6 internal link(s) on 1 page(s) carry tracking parameters (utm_source=gemini, utm_source=chatgpt.com)", "S3", ["/a", "/b"], {
            "links": [{"source": page, "target": f"{SITE}/x?utm_source=gemini", "parameters": ["utm_source=gemini"]}] * 5
            + [{"source": f"{SITE}/b", "target": f"{SITE}/y?utm_source=chatgpt.com", "parameters": ["utm_source=chatgpt.com"]}], "links_count": 6}),
         "5 internal links tagged utm_source=gemini"),
        (finding("STR-11", "2 page(s) describe the same entity twice in structured data with a different dateModified", "S3", ["/a"], {
            "contradictions": [{"url": page, "field": "dateModified", "descriptions": [{"value": ["2026-10-09"]}, {"value": ["2026-06-24"]}]}]}),
         "Structured data gives one entity two dateModified values: 2026-10-09 and 2026-06-24"),
        (finding("STR-11", "2 page(s) describe the same entity twice in structured data with a different name", "S3", ["/a"], {
            "contradictions": [{"url": page, "field": "name", "descriptions": [{"value": ["made-up shop ltd"]}, {"value": ["made-up shop"]}]}]}),
         "Structured data gives one entity two name values: “made-up shop ltd” and “made-up shop”"),
        (finding("RND-3", "1 page(s) show more content only after a click or scroll", "S3", ["/a"], {
            "pages": [{"url": page, "words_before": 2333, "words_after": 2435}]}),
         "102 more words appear only after a click or scroll (2,333 → 2,435)"),
        (finding("TSEO-1", "47 heading level jump(s) in the page structure", urls=["/a"], evidence={
            "items": [{"url": page, "jump_count": 2, "examples": [{"from": 1, "to": 3}, {"from": 2, "to": 5}]}]}), "Heading jumps H1→H3, H2→H5"),
        (finding("TSEO-1", "47 heading level jump(s) in the page structure", urls=["/a"], evidence={
            "items": [{"url": page, "jump_count": 2, "examples": [{"from": 2, "to": 5}, {"from": 2, "to": 5}]}]}), "Heading jumps H2→H5 (2×)"),
        (finding("TSEO-1", "2 page title(s) below the 10-character guidance band", urls=["/a"], evidence={"items": [{"url": page, "title": "Shop", "characters": 4}]}),
         "Title below the editorial guidance band (4 characters)"),
        (finding("RND-7", "12 page(s) have less than 30% of their text in the main content", urls=["/a"], evidence={"pages": [{"url": page, "main_share": 0.164}]}),
         "Only 16% of the page's text is main content"),
        (finding("TSEO-1", "10 meta description(s) above the 160-character guidance band", urls=["/a"], evidence={"items": [{"url": page, "characters": 171}]}),
         "Meta description above the editorial guidance band (171 characters)"),
        (finding("TSEO-1", "6 meta description(s) below the 70-character guidance band", urls=["/a"], evidence={"items": [{"url": page, "characters": 57}]}),
         "Meta description below the editorial guidance band (57 characters)"),
        (finding("STR-9", "2 page(s) have hreflang links to URLs that do not return 200", urls=["/a"], evidence={
            "links": [{"url": page, "hreflang": "x-default", "target": f"{SITE}/", "status": 302, "location": f"{SITE}/tr/"}]}),
         f"hreflang x-default points to {SITE}/, which answers 302 (redirects to /tr/)"),
        (finding("ACC-3", "noindex via meta on 5 page(s)", "S1", ["/a"], {"directives": {page: ["noindex"]}}), "Robots instruction on this page: noindex via meta"),
        (finding("IDX-6", f"Link target returns 404, linked from 2 page(s): {SITE}/gone", "S3", ["/a"], {"target": f"{SITE}/gone", "target_status": 404}),
         f"Links to {SITE}/gone, which returns 404"),
        (finding("STR-1", "3 page(s) have no <title>", urls=["/a"], evidence={"pages": [page]}), "No <title>"),
        (finding("STR-2", "2 long page(s) (>600 words) have no subheadings", urls=["/a"], evidence={"pages": [{"url": page, "content_words": 1840}]}),
         "Long page with no subheadings (1,840 words)"),
    ]
    for made, sentence in cases:
        assert said(made, "/a") == sentence, made["title"]
    two = finding("STR-9", "1 page(s) have hreflang links to URLs that do not return 200", urls=["/a"], evidence={"links": [
        {"url": page, "hreflang": "en", "target": f"{SITE}/en/", "status": 404, "location": None},
        {"url": page, "hreflang": "de", "target": f"{SITE}/de/", "status": 404, "location": None}]})
    assert said(two, "/a") == f"hreflang en points to {SITE}/en/, which answers 404 (and 1 more on this page)"


def test_a_finding_with_no_rule_of_its_own_says_whose_figure_its_title_carries():
    made = finding("STR-21", "No FAQ page was found among the 12 page(s) of the site", urls=["/a", "/b", "/c"])
    item = page_item(made, f"{SITE}/a")
    assert item["kind"] == "affected" and item["values"] == {"title": made["title"], "count": 3}
    assert page_sentence(item) == "Also affected by: “No FAQ page was found among the 12 page(s) of the site” (site-wide: 3 pages)"
    alone = finding("STR-3", "The homepage has no Organization structured data", urls=["/"])
    assert said(alone, "/") == "No Organization structured data"  # a kind of its own since team-preview-12
    lone = finding("STR-21", "No FAQ page was found among the 1 page(s) of the site", urls=["/"])
    assert page_sentence(page_item(lone, f"{SITE}/")) == "Also affected by: “No FAQ page was found among the 1 page(s) of the site”"  # one page: no figure to explain
    # Evidence in a shape the rule does not know is not guessed at: no number is said.
    odd = finding("TSEO-1", "3 page title(s) above the 60-character guidance band", urls=["/a", "/b"], evidence={"items": "not a list of rows"})
    assert said(odd, "/a") == "Title above the editorial guidance band (over 60 characters)"
    broken = finding("IDX-3", "2 redirect chain(s) of 2 or more hops", urls=["/a"], evidence={"chains": [{"hops": "not a list"}, 7]})
    assert said(broken, "/a") in ("Starts a redirect chain of 2 or more hops", "Also affected by: “2 redirect chain(s) of 2 or more hops”")


def test_every_rule_names_a_kind_in_the_table_and_every_kind_has_its_words():
    for kind, (text, plain) in PAGE_KINDS.items():
        assert text and (plain is not None or not holes(text)), kind  # a sentence that needs a value has a form without it
    empty = {"id": "X-1", "check_id": "X-1", "title": "", "severity": "S4", "evidence": {}, "scope": {"kind": "template", "count": 2, "urls": []}}
    for check_id, pattern, rule in PAGE_RULES:
        match = re.search(pattern, _TITLES[pattern])
        assert match, pattern
        kind, values = rule({**empty, "check_id": check_id, "title": _TITLES[pattern]}, f"{SITE}/a", match)
        assert kind in PAGE_KINDS, (check_id, pattern)
        page_sentence({"kind": kind, "values": {k: v for k, v in values.items() if v is not None}})  # words even with nothing known


# One real title per rule, as the checks write them (numbers made up).
_TITLES = {
    r"return a server error \(5xx\)": "2 URL(s) return a server error (5xx) on every attempt",
    r"fail at the connection level": "2 URL(s) fail at the connection level on every attempt",
    r"time out on every attempt": "2 URL(s) time out on every attempt (10s limit)",
    r"return a client error \(4xx\)": "2 URL(s) return a client error (4xx), linked internally",
    r"redirect loop": "1 redirect loop(s): the URL never resolves",
    r"intermittently redirect to themselves": "2 URL(s) intermittently redirect to themselves; the page loads on another try",
    r"redirected to themselves once|verification is incomplete": "1 URL(s) have observed redirect cycles; verification is incomplete",
    r"loop (for visitors without cookies|in Maya)": "1 URL(s) loop in Maya's cookie-less checks; with the cookie the site sets, the page loads",
    r"redirect chain": "2 redirect chain(s) of 2 or more hops",
    r"redirect from https:// to an http:// address": "1 page(s) redirect from https:// to an http:// address, which this audit did not follow",
    r"canonicalized to a URL with different content": "1 page(s) are canonicalized to a URL with different content",
    r"canonical that is broken, noindexed, or an error": "2 page(s) declare a canonical that is broken, noindexed, or an error",
    r"declare conflicting canonicals": "2 page(s) declare conflicting canonicals",
    r"^Link target returns ": "Link target returns 404, linked from 2 page(s): https://made-up-shop.example/gone",
    r"carry tracking parameters": "4 internal link(s) on 2 page(s) carry tracking parameters (utm_source=x)",
    r"point to another site": "3 link(s) on 2 page(s) point to another site (other.example) at a path that exists on this one",
    r"listed only in the sitemap": "2 page(s) are listed only in the sitemap, with no internal links to them",
    r"have identical visible text": "2 indexable pages have identical visible text",
    r"share the title": "2 indexable pages share the title 'Made-up'",
    r"nearly identical main content": "3 indexable pages have nearly identical main content (estimate)",
    r"copies or near-copies of each other": "2 groups of indexable pages that are copies or near-copies of each other (4 pages)",
    r"^(?P<label>.+) on \d+ page\(s\)$": "nosnippet via meta on 2 page(s)",
    r"\(median\) to return their HTML": "2 page(s) take more than 3 s (median) to return their HTML",
    r"time out on some attempts": "2 URL(s) time out on some attempts but not others",
    r"failed on some attempts": "2 URL(s) failed on some attempts and worked on others",
    r"^Main content is missing from the raw HTML": "Main content is missing from the raw HTML of 2 page(s): it appears only after JavaScript runs",
    r"^Part of the content": "Part of the content (30%–70% present) is missing from the raw HTML of 2 page(s)",
    r"may be client-rendered": "2 page(s) that were not rendered may be client-rendered (raw-HTML heuristics)",
    r"show more content only after a click or scroll": "1 page(s) show more content only after a click or scroll",
    r"may hide content behind interaction": "2 page(s) that were not rendered may hide content behind interaction (raw-HTML heuristics)",
    r"have HTML larger than": "2 page(s) have HTML larger than 2000 KB",
    r"start their main content more than": "2 page(s) start their main content more than 500 KB into the HTML",
    r"less than (?P<limit>\d+)% of their text in the main content": "12 page(s) have less than 30% of their text in the main content",
    r"have no <title>": "2 page(s) have no <title>",
    r"title\(s\) are shared by": "1 title(s) are shared by 4 different indexable pages",
    r"begin with the same \d+ characters": "2 page title(s) begin with the same 50 characters as another page's, so they look alike where a title is cut short",
    r"have a generic title": "2 page(s) have a generic title",
    r"have no <h1>": "2 page(s) have no <h1>",
    r"The homepage has no <h1>": "The homepage has no <h1>",
    r"The homepage has no Organization structured data": "The homepage has no Organization structured data",
    r"have no subheadings": "2 long page(s) (>600 words) have no subheadings",
    r"JSON-LD that does not parse": "2 page(s) have JSON-LD that does not parse",
    r"structured data that returns an error": "2 page(s) name a URL in their structured data that returns an error",
    r"structured-data price differs from": "2 page(s): structured-data price differs from the price shown on the page",
    r"structured-data (?P<field>.+?) differs from": "2 page(s): structured-data rating differs from the rating shown on the page",
    r"brand @id\(s\) carry a different name": "1 brand @id(s) carry a different name on different pages",
    r"carry a future date": "2 page(s) carry a future date",
    r"date signals more than (?P<limit>\d+) days apart": "2 page(s) have date signals more than 30 days apart",
    r"^(?P<total>\d+) of \d+ sampled image file\(s\) do not load": "2 of 20 sampled image file(s) do not load",
    r"^(?P<total>\d+) likely meaningful image\(s\)": "4 likely meaningful image(s) on 2 page(s): 3 with no alt text, 1 with an empty alt",
    r"pricing or spec comparisons as <div> grids": "2 page(s) lay out pricing or spec comparisons as <div> grids instead of <table>",
    r"contain an empty <table> element": "2 page(s) contain an empty <table> element",
    r"hreflang links to URLs that do not return 200": "2 page(s) have hreflang links to URLs that do not return 200",
    r"hreflang links that are not returned": "2 page(s) have hreflang links that are not returned",
    r"<html lang> that does not match": "2 page(s) declare a <html lang> that does not match the content language",
    r"og:image that returns 404/410": "2 page(s) have an og:image that returns 404/410",
    r"same entity twice in structured data with a different (?P<field>.+)$": "2 page(s) describe the same entity twice in structured data with a different name",
    r"mostly in another language than they declare": "2 page(s) are mostly in another language than they declare (en)",
    r"section headings in another language": "2 page(s) have section headings in another language than they declare (en)",
    r"placeholder or template text": "2 page(s) contain placeholder or template text",
    r"template markers": "2 page(s) have unfilled template markers in visible text: {{name}}",
    r"only with generic text": "3 link(s) on 2 page(s) name their target only with generic text: “click here”",
    r"have no text at all": "3 link(s) on 2 page(s) have no text at all",
    r"meta description\(s\) are shared by": "1 meta description(s) are shared by 3 different indexable pages",
    r"have no address a crawler can follow": "2 link(s) have no address a crawler can follow (they may still work for visitors through JavaScript)",
    r"carry their message in video or animation": "2 page(s) carry their message in video or animation, with fewer than 80 words of text",
    r"page title\(s\) above the (?P<limit>\d+)-character": "3 page title(s) above the 60-character guidance band",
    r"page title\(s\) below the (?P<limit>\d+)-character": "3 page title(s) below the 10-character guidance band",
    r"meta description\(s\) above the (?P<limit>\d+)-character": "3 meta description(s) above the 160-character guidance band",
    r"meta description\(s\) below the (?P<limit>\d+)-character": "3 meta description(s) below the 70-character guidance band",
    r"heading level jump\(s\)": "4 heading level jump(s) in the page structure",
}


# -- the web layer: the same words in English, its own in Turkish ---------------------------------------------------
def test_the_web_english_is_the_engines_word_for_word_and_turkish_has_every_sentence():
    pytest.importorskip("fastapi")
    from maya_audit_web import strings

    english, turkish = strings.STRINGS["en"], strings.STRINGS["tr"]
    expected = {"bypage.more": MORE_ON_PAGE}
    for kind, (text, plain) in PAGE_KINDS.items():
        expected[f"bypage.{kind}"] = text
        if plain is not None:
            expected[f"bypage.{kind}.plain"] = plain
    assert {key: value for key, value in english.items() if key.startswith("bypage.")} == expected
    assert [key for key in expected if key not in turkish or not turkish[key].strip()] == []
    assert [key for key in expected if sorted(holes(english[key])) != sorted(holes(turkish[key]))] == []
    assert english["practical.by_page.col.titles"] == "What is wrong on this page" and turkish["practical.by_page.col.titles"] == "Bu sayfadaki sorun"


def test_the_card_and_the_printed_table_say_what_is_wrong_on_each_page_in_the_readers_language():
    pytest.importorskip("fastapi")
    from maya_audit_web import pdf, practical, strings

    long_titles = finding("TSEO-1", "31 page title(s) above the 60-character guidance band", urls=["/a", "/b"], number=1,
                          evidence={"items": [{"url": f"{SITE}/a", "characters": 78}]})
    revealed = finding("RND-3", "1 page(s) show more content only after a click or scroll", "S3", ["/a"], number=2,
                       evidence={"pages": [{"url": f"{SITE}/a", "words_before": 2333, "words_after": 2435}]})
    no_rule = finding("STR-21", "No FAQ page was found among the 12 page(s) of the site", urls=["/a", "/b"], number=3)
    findings = [revealed, long_titles, no_rule]
    summary = problem_summary(findings, pages_checked=2)
    rows = [{"id": f["id"], "title": f["title"]} for f in findings]
    table = practical.by_page(summary, rows)
    first, second = table["rows"]
    assert first["url"] == f"{SITE}/a" and first["lines"] == [page_sentence(item) for item in summary["by_page"][0]["items"]] == [
        "102 more words appear only after a click or scroll (2,333 → 2,435)", "Title above the editorial guidance band (78 characters)",
        "Also affected by: “No FAQ page was found among the 12 page(s) of the site” (site-wide: 2 pages)"]
    assert second["lines"][0] == "Title above the editorial guidance band (over 60 characters)" and first["titles"][1] == long_titles["title"]  # the titles stay in the data
    html = pdf._by_page(table, SITE)
    assert "<th>What is wrong on this page</th>" in html and "Title above the editorial guidance band (78 characters)" in html and "31 page title(s)" not in html
    strings.set_language("tr")
    try:
        turkish = practical.by_page(summary, rows)
        assert turkish["columns"][3] == "Bu sayfadaki sorun"
        assert turkish["rows"][0]["lines"][:2] == ["102 kelime daha yalnızca tıklama veya kaydırmadan sonra görünüyor (2.333 → 2.435)", "Başlık editoryal öneri aralığının üstünde (78 karakter)"]
        assert turkish["rows"][1]["lines"][0] == "Başlık editoryal öneri aralığının üstünde (60 karakterden fazla)"
    finally:
        strings.set_language("en")


def test_a_healthy_site_with_one_site_wide_problem_shows_only_the_whole_site_with_its_own_title():
    pytest.importorskip("fastapi")
    from maya_audit_web import pdf, practical

    soft = finding("IDX-1", "A page that does not exist redirects (301) to the homepage (soft 404)", "S3", ["/"], kind="sitewide")
    note = finding("STR-10", "3 page(s) have no og:image", "Info", ["/a", "/b", "/c"], number=2)
    summary = problem_summary([soft, note], pages_checked=3)
    assert summary["by_page"] == [] and summary["whole_site"] == {"problems": 1, "worst_severity": "S3", "finding_ids": [soft["id"]], "shared_elements": []}
    assert headline(summary) == "1 problem across assessed scope; 3 pages read for content (1 medium) + 1 note"
    table = practical.by_page(summary, [{"id": soft["id"], "title": soft["title"]}, {"id": note["id"], "title": note["title"]}])
    assert [(row["whole_site"], row["label"], row["titles"], row["lines"]) for row in table["rows"]] == [(True, "Whole site", [soft["title"]], [soft["title"]])]
    lines = problems_by_page_lines(summary, {soft["id"]: soft["title"]}, SITE)
    assert lines[4] == f"| Whole site | 1 | Medium | {soft['title']} |" and lines[5] == ""
    assert soft["title"] in pdf._by_page(table, SITE) and "Also affected" not in pdf._by_page(table, SITE)


# -- saved reports and the schema -----------------------------------------------------------------------------------
def test_a_saved_1_9_report_without_items_gets_them_derived_and_its_file_is_not_changed(tmp_path):
    pytest.importorskip("fastapi")
    from maya_audit_web import summary as web_summary

    made = finding("TSEO-1", "2 page title(s) above the 60-character guidance band", urls=["/a", "/b"],
                   evidence={"items": [{"url": f"{SITE}/a", "characters": 78}, {"url": f"{SITE}/b", "characters": 64}]})
    new = problem_summary([made], pages_checked=2)
    as_saved = {**new, "by_page": [{key: value for key, value in row.items() if key != "items"} for row in new["by_page"]]}  # schema 1.9
    report = {"schema_version": "1.9", "checks": [{"check_id": "TSEO-1", "findings": [made]}], "findings_in_priority_order": [made["id"]],
              "problem_summary": as_saved}
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    before = path.read_bytes()
    loaded = json.loads(before)
    derived = web_summary.problems_of(loaded, None, 2)
    # A report saved before 1.11 also gets `page_checks`, counted from its own checks (the one check here is a page check that ran).
    assert derived == {**new, "page_checks": {"total": 1, "could_run": 1, "limited": False}}
    assert [page_sentence(row["items"][0]) for row in derived["by_page"]] == ["Title above the editorial guidance band (78 characters)", "Title above the editorial guidance band (64 characters)"]
    assert all("items" not in row for row in loaded["problem_summary"]["by_page"]) and path.read_bytes() == before  # neither the file nor what was read from it
    assert with_page_items(new, [made]) is new  # a 1.10 report is passed through as it is
    gone = with_page_items(as_saved, [])  # a finding the report no longer holds: the default, never a guess
    assert gone["by_page"][0]["items"][0]["kind"] == "affected"


def test_schema_1_16_is_frozen_and_adds_without_breaking_older_1_x_reports():
    assert schema.SCHEMA_VERSION == "1.33"
    frozen = json.loads(schema.frozen_path().read_text(encoding="utf-8"))
    assert schema.frozen_path().name == "report-schema-1.33.json" and schema.differences(frozen, schema.shape()) == []
    # 1.13 is kept, 1.14 only adds to it (the start address that failed; the audit's brand and where it came from), and a
    # 1.13 report is still read.
    thirteenth = json.loads(schema.frozen_path("1.13").read_text(encoding="utf-8"))
    assert schema.differences({k: v for k, v in thirteenth.items() if k != "schema_version"}, {k: v for k, v in frozen.items() if k != "schema_version"}) == [
        # team-preview-16, run 3 (DECISIONS 219): the step timing table and what the time limit cut.
        "brand: added", "crawl: added ['host_moves', 'steps', 'skipped_for_time', 'verification', 'page_grouping', 'reader_page_grouping', 'business_type', 'redirects', 'locales', 'page_measures', 'sampling']",
        # 1.31 (DECISIONS 334): why Core Web Vitals are missing, every request, the homepage's record.
        "crux: added ['reason_code', 'attempts', 'origins_asked', 'homepage', 'fetched_for_saved_audit']", "finding: added ['rule_id', 'verification', 'page_types', 'measurement', 'remediation', 'dedup_key']", "firecrawl: added ['unsupported_resources', 'concurrency']",
        # 1.21 (DECISIONS 294): the reader's measured pace and the shared site limit's slot of each request.
        # 1.22 (DECISIONS 295): the timeout counts. 1.23 (DECISIONS 297): the page grouping (page, crawl).
        # 1.28 (DECISIONS 317): how the one page limit was shared. 1.29 (DECISIONS 323): crawl.page_measures.
        # 1.30 (DECISIONS 327): crawl.sampling. 1.33 (DECISIONS 358): crawl.host_moves.
        "firecrawl_coverage: added ['seconds_per_page_measured', 'call_seconds_measured', 'seconds_per_page_assumed', 'skipped_for_time', 'ran_beside_maya', 'page_limit', 'timeouts']",
        "page: added ['wire_bytes', 'grouping']", "problem_start_address: added", "problem_summary: added ['start_address']", "report.optional: added ['platform']", "report.required: added ['generation', 'brand', 'release_gate']",
        "request: added ['slot']", "review_item: added ['rule_id']",
        # 1.24 (DECISIONS 304): the page reader's page grouping; the sitemap's image and video counts. 1.25 (DECISIONS
        # 311): the business type (crawl).
        "sitemap_doc: added ['image_entries', 'video_entries', 'new_urls']",  # 1.32 (DECISIONS 337): new_urls  # 1.18, DECISIONS 269; 1.19 adds `verification` (DECISIONS 272); 1.20 the contract fields and `release_gate` (278)
        "vocabulary.brand_found_in: added", "vocabulary.brand_source: added", "vocabulary.check_status: added ['not_applicable']", "vocabulary.not_requested_because: added ['provider_timeout', 'provider_error']"]
    assert frozen["brand"] == ["name", "source", "confirmed", "found_in", "pages"]
    assert frozen["problem_start_address"] == ["entered", "status", "audited_from"] and schema.unsupported_reason({"schema_version": "1.13"}) is None
    assert frozen["problem_page"] == ["url", "problems", "worst_severity", "finding_ids", "items"]
    assert frozen["problem_page_item"] == ["finding_id", "check_id", "severity", "kind", "values"]
    assert frozen["problem_page_checks"] == ["total", "could_run", "limited"] and "page_checks" in frozen["problem_summary"]

    def changes(before, after):
        return schema.differences({k: v for k, v in before.items() if k != "schema_version"}, {k: v for k, v in after.items() if k != "schema_version"})

    tenth = json.loads(schema.frozen_path("1.10").read_text(encoding="utf-8"))  # the 1.10 copy is kept, and 1.11 only adds to it
    added = changes(tenth, frozen)  # 1.11 grows with its batch: what is checked is that nothing is removed, and that these are in
    assert added and all(": added" in line for line in added)
    assert {"problem_page_checks: added", "problem_summary: added ['files', 'page_checks', 'single_page', 'start_address']", "problem_whole_site: added ['shared_elements']",
            "problem_shared_element: added", "content_coverage: added", "read_by: added", "firecrawl_coverage: added"} <= set(added)
    assert frozen["read_by"] == ["maya_only", "firecrawl_only", "both", "firecrawl", "total"] and "request_allowance_used" in frozen["vocabulary"]["not_requested_because"]
    old = json.loads(schema.frozen_path("1.9").read_text(encoding="utf-8"))  # the 1.9 copy is kept, and 1.10 only added to it
    assert changes(old, tenth) == ["problem_page: added ['items']", "problem_page_item: added"]
    assert "1.10" < "1.9"  # as text the order is wrong, which is why versions are compared as numbers
    assert schema.version_key("1.10") > schema.version_key("1.9") > schema.version_key("1.8")
    assert sorted(["1.9", "1.10", "1.2"], key=schema.version_key) == ["1.2", "1.9", "1.10"] and schema.version_key("not a version") == ()
    assert schema.version_key("1.11") > schema.version_key("1.10") and schema.unsupported_reason({"schema_version": "1.11"}) is None
    assert schema.unsupported_reason({"schema_version": "1.10"}) is None and schema.unsupported_reason({"schema_version": "1.9"}) is None
    assert "reads 1.x" in schema.unsupported_reason({"schema_version": "10.1"})


# -- one page, many pages: the web layer's own sentences ------------------------------------------------------------
def test_a_count_is_said_as_one_thing_or_as_many_and_turkish_is_unchanged():
    pytest.importorskip("fastapi")
    from maya_audit_web.strings import STRINGS, t

    assert t("result.affects.pages", count=1) == "Affects 1 page" and t("result.affects.pages", count=3) == "Affects 3 pages"
    assert t("result.affects.pages", count=0) == "Affects 0 pages" and t("result.affects.pages", count=1234) == "Affects 1,234 pages"
    assert t("result.affects.pages", "tr", count=1) == "1 sayfayı etkiler" and t("result.affects.pages", "tr", count=3) == "3 sayfayı etkiler"
    assert t("result.summary_line", pages=1, gaps=1) == "1 page checked. 1 part could not be checked."
    assert t("result.summary_line", pages=50, gaps=29) == "50 pages checked. 29 parts could not be checked."
    assert t("practical.by_page.not_listed", title="X", count=1) == "“X” also affects 1 more page not listed here."
    assert t("follow.summary", outcome="Audit complete", pages=1, s1=1, s2=0, s3=2, s4=0, review=1, gaps=2) == (
        "Audit complete. 1 page checked. 1 blocker, 0 high, 2 medium, 0 low; 1 item needs a person to look; 2 parts could not be checked.")
    assert t("status.spend.firecrawl", credits="1", estimate="6", possibly=0, cached=2, zdr="on", usd="") .startswith(
        "Firecrawl: 1 credit used or reserved, of at most 6; 0 requests possibly billed;")  # a number handed over as text is still one
    assert t("result.affects.pages") == "Affects …"  # a missing value is written "…": the template's braces are never shown (DECISIONS 169)
    assert phrase("{n:page|pages}, {m:.}, {k:,}", n=2.0, m=2435, k=2435) == "2 pages, 2.435, 2,435"
    assert [key for key, text in STRINGS["en"].items() if "(s)" in text] == []  # no "page(s)" left in this layer's own sentences
    # Turkish does not change the noun after a number: its sentences keep the plain placeholder.
    assert [key for key, text in STRINGS["tr"].items() if re.search(r"\{\w+:[^{}]*\|", text)] == []
