"""No sentence reaches a reader with an unfilled hole (DECISIONS 169).

Seen on 2026-10-11 in "Problems by page": `{headings:section heading is|section headings are} in {language}, but the
page is declared as {declared}`. The sentence had a value named `language`, and the function that fills sentences took
it for the interface language. This file looks for a hole left open in everything a reader is shown: the Markdown
report, the display strings of the JSON report, the results card (/summary), the practical report (/practical) and the
printed page, in English and in Turkish.

Every site, reader and report here is made up. Nothing is requested.
"""
import json
import logging
import re
import string
from html import unescape

import httpx
import pytest

pytest.importorskip("fastapi")

from maya_audit.report import PAGE_KINDS, PAGE_RULES, page_form, page_item, page_sentence, problem_summary, problems_by_page_lines  # noqa: E402
from maya_audit_web import demo, pdf, practical, strings  # noqa: E402
from maya_audit_web.strings import t  # noqa: E402
from test_firecrawl import Firecrawl  # noqa: E402
from test_page_wording import _TITLES, SITE, finding  # noqa: E402
from test_web_app import API, Site, cloudflare, get, plan, start, web  # noqa: E402,F401
from test_web_firecrawl import PAGES, services  # noqa: E402

# A hole as the sentence tables write one: {name} or {name:form}. Not "${name}" (script text), not "{{name}}" (a
# site's own template marker, which STR-13 quotes).
HOLE = re.compile(r"(?<![{$])\{[A-Za-z_]\w*(?::[^{}\n]*)?\}(?!\})")

# -- what may hold braces on purpose (the whole allow-list; nothing else is passed over) -----------------------------
# 1. Text in backticks or in a code block: an address, a tag or a pattern quoted as written.
CODE = re.compile(r"```.*?```|`[^`\n]*`|<pre\b.*?</pre>|<code\b.*?</code>|<style\b.*?</style>|<script\b.*?</script>", re.DOTALL | re.IGNORECASE)
# 2. The fix examples (`practical.EXAMPLES` and their Turkish forms), which show markup and JSON-LD as a person would
#    type it: fields named `example` in a payload, and the same texts wherever the printed page shows them.
EXAMPLE_KEYS = frozenset({"example"})
# 3. A URL pattern's label: "/blog/{slug}", "/products/{id}".
URL_PATTERN = re.compile(r"(?<=[/=])\{[a-z_]+\}")
# 4. In the JSON report and in payloads: everything under `evidence` (what a check recorded, including the site's own
#    text) and under `crawl` (the pages as fetched).
SITE_TEXT_KEYS = frozenset({"evidence", "crawl"})
# 5. STR-13 quotes the site's own unfilled template markers in its titles and notes ("{inline_image_1}"): those exact
#    markers, taken from the report's STR-13 findings, and no other.


def site_markers(report: dict) -> set[str]:
    found: set[str] = set()
    for check in report.get("checks") or []:
        if check.get("check_id") == "STR-13":
            found.update(HOLE.findall(json.dumps(check, ensure_ascii=False)))
    return found


def example_texts() -> list[str]:
    from maya_audit_web import wording

    return [text for _, text in practical.EXAMPLES] + list((wording.TABLES.get("tr") or {}).get("examples", {}).values())


def open_holes(text: str, allowed: set[str] = frozenset()) -> list[str]:
    """Holes left open in one piece of display text, after the allow-list."""
    text = unescape(text)
    for example in example_texts():
        text = text.replace(example, " ")
    text = URL_PATTERN.sub(" ", CODE.sub(" ", text))
    return [hole for hole in HOLE.findall(text) if hole not in allowed]


def strings_of(node, skip: frozenset[str] = SITE_TEXT_KEYS | EXAMPLE_KEYS):
    if isinstance(node, dict):
        for key, value in node.items():
            if key not in skip:
                yield from strings_of(value, skip)
    elif isinstance(node, list):
        for value in node:
            yield from strings_of(value, skip)
    elif isinstance(node, str):
        yield node


def assert_no_open_hole(client, audit) -> dict:
    """Every output of one audit, in both languages. Returns the saved report."""
    report = get(client, audit, "/result")
    allowed = site_markers(report)
    found = {}
    markdown = client.get(f"{API}/audits/{audit['id']}/downloads/markdown?draft=true").text
    found["report.md"] = open_holes(markdown, allowed)
    found["report.json"] = [hole for text in strings_of(report) for hole in open_holes(text, allowed)]
    for language in ("en", "tr"):
        assert client.put(f"{API}/session/language", json={"language": language}).status_code == 200
        for name in ("/summary", "/practical"):
            found[f"{name} ({language})"] = [hole for text in strings_of(get(client, audit, name)) for hole in open_holes(text, allowed)]
        found[f"print ({language})"] = open_holes(client.get(f"{API}/audits/{audit['id']}/print?full=true&lang={language}").text, allowed)
    client.put(f"{API}/session/language", json={"language": "en"})
    assert {name: holes for name, holes in found.items() if holes} == {}
    assert len(markdown) > 500 and report["checks"]
    return report


# -- the regular expression and the allow-list themselves -------------------------------------------------------------
def test_the_search_finds_an_open_hole_and_passes_over_only_what_the_allow_list_names():
    leaked = "{headings:section heading is|section headings are} in {language}, but the page is declared as {declared}"
    assert open_holes(leaked) == ["{headings:section heading is|section headings are}", "{language}", "{declared}"]
    assert open_holes("Affects {count:page|pages}") == ["{count:page|pages}"] and open_holes("3 pages, no hole") == []
    assert open_holes("<td>{title}</td>") == ["{title}"] and open_holes("&#123;title&#125;") == ["{title}"]  # also when escaped in HTML
    # Allowed: code, a URL pattern, a site's own double-brace marker, an example, and a STR-13 marker named in the report.
    assert open_holes("Pattern `/blog/{slug}` and <code>{id}</code>") == [] and open_holes("Template /products/{id} has 40 pages") == []
    assert open_holes("unfilled template markers in visible text: {{name}}") == [] and open_holes("costs ${amount}") == []
    assert open_holes(practical.EXAMPLES[13][1]) == [] and '"@type":"Organization"' in practical.EXAMPLES[13][1]
    marker = {"checks": [{"check_id": "STR-13", "findings": [{"title": "2 page(s) have unfilled template markers in visible text: {inline_image_1}"}]}]}
    assert site_markers(marker) == {"{inline_image_1}"} and open_holes("markers: {inline_image_1}", site_markers(marker)) == []
    assert open_holes("markers: {inline_image_1} and {language}", site_markers(marker)) == ["{language}"]
    # Under `evidence` and `crawl` the site's own text is kept as it is; everywhere else it is looked at.
    assert list(strings_of({"title": "a {hole}", "evidence": {"text": "{site_text}"}, "crawl": {"pages": ["{x}"]}, "example": "{…}"})) == ["a {hole}"]


# -- the sentence that leaked, and the function that fills sentences --------------------------------------------------
def test_a_value_named_language_is_a_value_and_a_language_is_named_in_the_readers_language():
    item = {"finding_id": "STR-12-made-up", "check_id": "STR-12", "severity": "S3", "kind": "headings_language",
            "values": {"headings": 3, "language": "en", "declared": "tr"}}
    # The function itself: positional key and language, so `language=` is one of the sentence's values.
    assert t("bypage.headings_language", headings=3, language="en", declared="tr") == "3 section headings are in en, but the page is declared as tr"
    assert t("bypage.headings_language", "tr", headings=3, language="en", declared="tr") == "3 bölüm başlığı en dilinde, ancak sayfa tr olarak bildirilmiş"
    with pytest.raises(TypeError):
        t(key="bypage.headings_language")  # `key` is no longer a keyword of the function: it can be a value's name
    assert t("bypage.affected.plain", title="X", key="k", values="v", language="en") == "Also affected by: “X”"
    # As the reader sees it: the language by its name, in the reader's language. The report keeps the code.
    assert practical.page_line(item) == "3 section headings are in English, but the page is declared as Turkish"
    assert page_sentence(item) == "3 section headings are in English, but the page is declared as Turkish"  # the engine's Markdown
    one = {**item, "values": {"headings": 1, "language": "de", "declared": "en-GB"}}
    assert practical.page_line(one) == "1 section heading is in German, but the page is declared as en-GB"  # an unknown code is shown as it is
    mismatch = {**item, "kind": "language_mismatch", "values": {"declared": "tr", "language": "en"}}
    html_lang = {**item, "check_id": "STR-9", "kind": "lang_mismatch", "values": {"declared": "en", "detected": "tr"}}
    assert practical.page_line(mismatch) == "Declared as Turkish, but the main content is mostly English"
    assert practical.page_line(html_lang) == "<html lang> says English, but the text reads as Turkish"
    strings.set_language("tr")
    try:
        assert practical.page_line(item) == "3 bölüm başlığı İngilizce dilinde, ancak sayfa Türkçe olarak bildirilmiş"
        assert practical.page_line(mismatch) == "Türkçe olarak bildirilmiş, ancak ana içerik çoğunlukla İngilizce"
        assert practical.page_line(html_lang) == "<html lang> İngilizce diyor, ancak metin Türkçe olarak okunuyor"
        assert [strings.language_name(code) for code in ("en", "tr", "de", "fr", "es", "it", "pt", "nl")] == [
            "İngilizce", "Türkçe", "Almanca", "Fransızca", "İspanyolca", "İtalyanca", "Portekizce", "Felemenkçe"]
    finally:
        strings.set_language("en")
    assert item["values"] == {"headings": 3, "language": "en", "declared": "tr"}  # the item itself is not changed
    from maya_audit.language import NAMES

    assert {code: strings.language_name(code) for code in NAMES} == NAMES and strings.language_name("label") == "label"


def test_a_missing_value_takes_the_plain_form_or_is_written_as_three_dots_never_as_braces(caplog):
    with caplog.at_level(logging.WARNING, logger="maya_audit_web.strings"):
        # A sentence with a plain form uses it.
        assert t("bypage.headings_language", headings=3) == "Has section headings in another language than it declares"
        assert t("bypage.title_long") == "Title above the editorial guidance band (over … characters)" and t("bypage.title_long", limit=60) == "Title above the editorial guidance band (over 60 characters)"
        # One without: the missing value is "…", the values that were given are still written.
        assert t("result.headline.found", problems="3 problems") == "3 problems across assessed scope; … read for content"
        assert t("result.affects.pages") == "Affects …" and t("result.affects.pages", "tr") == "… sayfayı etkiler"
        assert t("bypage.revealed_words.plain") == "More content appears only after a click or scroll"
    assert "result.headline.found" in caplog.text and "['pages']" in caplog.text  # said in the log, so it can be fixed
    assert open_holes(t("bypage.headings_language")) == [] and open_holes(t("result.summary_line")) == []
    # A value of the wrong kind for its form (text where a number is grouped) is not shown as a template either.
    assert t("bypage.content_after_js", raw="many", rendered=5) == "Main content appears only after JavaScript runs"
    assert strings._filled_anyway("{raw:,} words, {rendered:,} after", {"raw": "many", "rendered": 5}) == "many words, 5 after"
    assert t("no.such.key") == "no.such.key"


def test_the_pages_own_sentence_filler_follows_the_same_rule(tmp_path):
    """static/app.js T(): the plain form when a value is missing, else "…"; never the braces. Run in Node when this
    computer has it (the page itself is plain JavaScript with no build step)."""
    import shutil
    import subprocess
    from pathlib import Path

    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is not installed on this computer")
    source = (Path(strings.__file__).parent / "static" / "app.js").read_text(encoding="utf-8")
    function = source[source.index("function T(key, values) {"):source.index("function money(amount)")]
    table = {key: strings.STRINGS["en"][key] for key in ("bypage.headings_language", "bypage.headings_language.plain", "result.headline.found", "result.affects.pages")}
    script = tmp_path / "t.js"
    script.write_text('"use strict";\nconst state = {language: "en", strings: ' + json.dumps(table) + "};\nconst window = {};\n"
                      "const num = (value) => new Intl.NumberFormat(state.language).format(Number(value) || 0);\n" + function
                      + 'console.log(JSON.stringify([T("bypage.headings_language", {headings: 3, language: "English", declared: "Turkish"}), '
                      'T("bypage.headings_language", {headings: 3}), T("result.headline.found", {problems: "3 problems"}), T("result.affects.pages"), '
                      'T("result.affects.pages", {count: 1}), T("result.affects.pages", {count: 1234}), T("no.such.key")]));\n', encoding="utf-8")
    shown = json.loads(subprocess.run([node, str(script)], capture_output=True, check=True, timeout=60).stdout.decode("utf-8"))  # Node writes UTF-8; Windows text mode would read the ANSI code page
    assert shown == ["3 section headings are in English, but the page is declared as Turkish", "Has section headings in another language than it declares",
                     "3 problems across assessed scope; … read for content", "Affects …", "Affects 1 page", "Affects 1,234 pages",
                     "…"]  # DECISIONS 314: a key no table has is never shown raw
    assert [text for text in shown if open_holes(text)] == []


def sample(template: str) -> dict:
    """A made-up value for every hole of a sentence: a number where the sentence counts or formats one."""
    values = {}
    for _, name, form, _ in string.Formatter().parse(template):
        if name:
            values[name] = 3 if form else {"language": "en", "declared": "tr", "detected": "de"}.get(name, f"made-up {name}")
    return values


def test_every_sentence_of_the_web_app_fills_every_hole_it_has_in_english_and_turkish(caplog):
    english = strings.STRINGS["en"]
    raw_turkish = json.loads((strings.LOCALES / "tr.json").read_text(encoding="utf-8"))
    with_holes = [key for key in english if HOLE.search(english[key]) or HOLE.search(raw_turkish.get(key, ""))]
    assert len(with_holes) > 200 and {"bypage.headings_language", "bypage.language_mismatch", "result.headline.limited"} <= set(with_holes)
    names = {name for key in with_holes for name in sample(english[key])}
    assert "language" in names  # a sentence does have a value of that name
    left = {}
    with caplog.at_level(logging.WARNING, logger="maya_audit_web.strings"):
        for key in with_holes:
            for language, template in (("en", english[key]), ("tr", raw_turkish[key])):
                # Values named `language`, `key` and `values` go in with every call: none of them is taken for anything else.
                shown = t(key, language, **{"language": "en", "key": "made-up key", "values": "made-up values", **sample(english[key]), **sample(template)})
                if HOLE.search(shown):
                    left[(key, language)] = shown
    assert left == {} and caplog.text == ""  # nothing left open, and nothing had to be patched with "…"


# -- every row of the per-page table, in both forms ---------------------------------------------------------------------
def every_page_sentence():
    """A made-up report's "Problems by page": one finding for every row of the per-page rules (as the engine derives
    it from a finding with no evidence), and one item for every kind in its full form and in its plain form."""
    findings = [finding(check_id, _TITLES[pattern], "S3", ["/a", "/b"], number=number)
                for number, (check_id, pattern, _rule) in enumerate(PAGE_RULES, 1)]
    findings.append(finding("STR-21", "No FAQ page was found among the 12 page(s) of the site", "S4", ["/a", "/b"], number=999))  # no rule: `affected`
    # A problem one shared element causes on most pages (one whole-site line each), and a file with a problem (listed apart).
    from maya_audit import shared_elements

    for number, (check_id, kind, values) in enumerate((
            ("STR-14", "link_no_text", {"href": "/account#/favourites"}), ("STR-19", "link_no_address", {"text": "Cookie settings"}),
            ("TSEO-1", "heading_jump", {"text": "Support line", "to": 5, "before": 2}), ("TSEO-1", "heading_jump_varied", {"text": "Newsletter", "to": 4}),
            ("STR-7", "image_no_alt", {"src": "/media/banner.jpg"}),
            ("STR-19", "links_no_address", {"links": 6, "texts": shared_elements.named(["Departments", "Diagnosis", "Treatment", "Our team", "Guide", "About"])}),
            ("STR-14", "link_generic", {"text": "click here", "href": "/cookie-notice/"}),
            ("STR-14", "link_no_text_pattern", {"pattern": "/media/products/…/*.png", "href": "/media/products/2026/04/walnut-tray.png"})), 2000):
        element = {"type": "link", "where": "footer", "kind": kind, "pages": 2, **{name: value for name, value in values.items() if name in ("href", "text", "src")}}
        findings.append(finding(check_id, shared_elements.TITLES[kind].format(pages=2, **values), "S4", ["/a", "/b"], {"shared_element": element}, kind="sitewide", number=number))
    assert len({f["title"] for f in findings[-8:]}) == len(shared_elements.TITLES)
    findings.append(finding("IDX-1", "1 URL(s) return a client error (4xx), linked internally or listed in the sitemap", "S3", ["/files/price-list.pdf", "/robots.txt"], number=3000))
    summary = problem_summary(findings, pages_checked=2)
    assert len(summary["whole_site"]["shared_elements"]) == 8 and len(summary["files"]) == 2
    full, plain = [], []
    for kind, (text, short) in PAGE_KINDS.items():
        base = {"finding_id": f"X-1-made-up-{kind}", "check_id": "X-1", "severity": "S4", "kind": kind}
        full.append({**base, "values": {**sample(text), "more": 2}})
        plain.append({**base, "values": sample(short) if short else {}})
        assert page_form(full[-1]) == "text" and (short is None or page_form(plain[-1]) == "plain" or not sample(text))
    extra = [{"url": f"{SITE}/full", "problems": len(full), "worst_severity": "S4", "finding_ids": [i["finding_id"] for i in full], "items": full},
             {"url": f"{SITE}/plain", "problems": len(plain), "worst_severity": "S4", "finding_ids": [i["finding_id"] for i in plain], "items": plain}]
    return findings, {**summary, "by_page": summary["by_page"] + extra}


def test_problems_by_page_has_no_open_hole_for_any_rule_or_kind_in_full_or_plain_form_in_any_output():
    findings, summary = every_page_sentence()
    kinds = {item["kind"] for row in summary["by_page"] for item in row["items"]}
    assert kinds == set(PAGE_KINDS) and len(summary["by_page"][0]["items"]) == len(PAGE_RULES) + 1
    assert {page_item(f, f"{SITE}/a")["kind"] for f in findings} >= {"affected", "headings_language", "language_mismatch", "template_markers"}
    allowed = site_markers({"checks": [{"check_id": "STR-13", "findings": [f for f in findings if f["check_id"] == "STR-13"]}]})
    titles = {f["id"]: f["title"] for f in findings}
    rows = [{"id": f["id"], "title": f["title"]} for f in findings]
    # The Markdown report and the JSON report's display strings (the engine's English).
    markdown = "\n".join(problems_by_page_lines(summary, titles, SITE))
    assert "Shared header/footer: link to /account#/favourites has no text (on 2 page(s))" in markdown and "**Files (sitemaps, robots.txt, documents)**" in markdown
    sentences = [page_sentence(item) for row in summary["by_page"] for item in row["items"]]
    assert open_holes(markdown, allowed) == [] and [s for s in sentences if open_holes(s, allowed)] == [] and len(sentences) > 3 * len(PAGE_KINDS)
    assert "section headings are in English, but the page is declared as Turkish" in markdown and "<html lang> says Turkish, but the text reads as German" in markdown
    # The card and the practical report's table, and the printed page, in both languages.
    for language in ("en", "tr"):
        strings.set_language(language)
        try:
            from maya_audit_web import wording

            # The whole-site row keeps each problem's title as this layer shows it; a file's row holds its problems' titles.
            table = practical.by_page(summary, [{**row, **({"title_shown": wording.title(f["check_id"], f["title"])[0]} if f["scope"]["kind"] == "sitewide" else {})}
                                                for row, f in zip(rows, findings)])
            whole = table["rows"][0]
            assert whole["whole_site"] and len(whole["lines"]) == 8 and [line for line in whole["lines"] if open_holes(line, allowed) or "(s)" in line or "(İngilizce)" in line] == []
            assert ("Ortak üst/alt bölüm: " if language == "tr" else "Shared header/footer: ") in whole["lines"][0]
            assert len(table["files"]["rows"]) == 2 and [line for row in table["files"]["rows"] for line in row["lines"] if open_holes(line, allowed)] == []
            assert open_holes(json.dumps(table["files"], ensure_ascii=False), allowed) == []
            lines = [line for row in table["rows"][1:] for line in row["lines"]]
            # A row says a line once, however many findings say it (team-preview-12): fewer lines than sentences, never more.
            assert 0 < len(lines) <= len(sentences) and [line for line in lines if open_holes(line, allowed)] == [], language
            assert all(len(row["lines"]) == len(set(row["lines"])) for row in table["rows"]), language
            assert open_holes(pdf._by_page(table, SITE), allowed) == [], language
            if language == "en":
                assert set(lines) == set(sentences) and lines[0] == sentences[0]  # word for word the engine's, each said once in a row
            else:
                assert "İngilizce" in " ".join(lines) and " en dilinde" not in " ".join(lines)
        finally:
            strings.set_language("en")


# -- whole audits ---------------------------------------------------------------------------------------------------------
def test_the_demo_shop_has_no_open_hole_in_any_output(web):
    client = web()
    audit = start(client, plan(client, key_pages=["/about"]))
    assert audit["state"] == "finished"
    report = assert_no_open_hole(client, audit)
    assert report["problem_summary"]["problems"] > 0 and report["problem_summary"]["by_page"]


def test_an_audit_read_through_the_main_reader_has_no_open_hole_in_any_output(web, tmp_path):
    client = web(site=Site(respond=cloudflare), firecrawl=services(tmp_path, Firecrawl(PAGES)))
    audit = start(client, plan(client))
    assert audit["outcome"]["code"] == "COMPLETED" and audit["outcome"]["reason"].startswith("We read 3 page(s) through Firecrawl")
    report = assert_no_open_hole(client, audit)
    assert report["firecrawl"]["used"] and report["firecrawl"]["purpose"] == "main page reader"


def test_a_blocked_site_has_no_open_hole_in_any_output(web):
    client = web(site=Site(respond=cloudflare))
    client.app.state.runner.engine.archives_transport = httpx.MockTransport(demo._no_archives)
    audit = start(client, plan(client, archives=True))
    assert audit["outcome"]["code"] == "DEGRADED"
    assert_no_open_hole(client, audit)


# -- the sentences about how much was read ------------------------------------------------------------------------------------
def test_the_page_count_the_stop_sentence_and_the_left_out_addresses_have_no_open_hole_in_either_language():
    from maya_audit.report import ALLOWANCE, ALLOWANCE_ELSEWHERE, ALSO_FETCHED, LEFT_OUT, READ_SENTENCE, also_fetched, phrase, read_sentence, reader_gaps
    from maya_audit_web import summary, wording

    said = [phrase(READ_SENTENCE, pages=pages) for pages in (1, 43)] + [phrase(text, files=files, same=same) for text in ALSO_FETCHED.values()
                                                                        for files, same in ((1, 1), (5, 7))]
    said += [read_sentence({"pages": 43, "other_addresses": {"files": 5, "same_page": 7}}), also_fetched({"files": 1, "same_page": 0})]
    assert "1 address that leads to a page already read" in said[2] and "7 addresses that lead to a page already read" in said[3]
    reasons = [phrase(ALLOWANCE, n=51, m=m) + phrase(ALLOWANCE_ELSEWHERE, k=k) for m, k in ((43, 8), (1, 1))] + [phrase(LEFT_OUT, n=n) for n in (1, 12)]
    reasons += reader_gaps({"used": True, "pages_read": 43, "requests_sent": 51, "coverage": {
        "not_requested_because": "request_allowance_used", "page_requests": 51, "requests_without_a_new_page": 8, "known_urls_not_requested": 449,
        "unread_left_out": {"robots_disallowed": 9, "not_a_page": 3}}})
    assert len(said) == 10 and len(reasons) == 6 and [text for text in said + reasons if open_holes(text) or "(s)" in text] == []
    for reason in reasons:
        turkish, translated = wording.reason(reason, "tr")
        assert translated and open_holes(turkish) == [] and "(İngilizce)" not in turkish, reason
    for language in ("en", "tr"):
        strings.set_language(language)
        try:
            shown = [summary.also_fetched(other) for other in ({"files": 5, "same_page": 7}, {"files": 1, "same_page": 0}, {"files": 0, "same_page": 1})]
            shown += [t("result.pages.sentence", pages=43), t("result.coverage.left_out", n=12), t("practical.by_page.files.title")]
            assert all(shown) and [text for text in shown if open_holes(text)] == [], language
        finally:
            strings.set_language("en")
    assert summary.also_fetched({"files": 0, "same_page": 0}) is None and summary.also_fetched(None) is None
