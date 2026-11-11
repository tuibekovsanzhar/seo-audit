"""The page's own document and its own head (DECISIONS 167, 168; docs/FALSE-ALARMS.md FA-001, FA-002).

A widget's document written into a page by a reader, a <title> or a robots tag in the body: none of it is the page's.
A check that had no page to look at is not a pass, and a report where fewer than half of the page checks could run
says so first. Every site here is made up; every request goes to a mock transport or an in-memory Firecrawl.
"""
import json
import time
from html import escape

import httpx
import pytest

from maya_audit import coverage, schema
from maya_audit.analysis import analyze_html
from maya_audit.config import CrawlConfig
from maya_audit.directives import noindex_directives
from maya_audit.firecrawl import Options, reader
from maya_audit.html_links import extract_link_edges, extract_links
from maya_audit.own_document import strip_embedded
from maya_audit.report import build_report, headline, page_checks, problem_summary, render_markdown
from maya_audit.structure_data import indexable_pages
from test_firecrawl import HTML, ROBOTS_TEXT, SITE, TEXT, Firecrawl, blocked_audit, client_for, doc, no_lookups  # noqa: F401
from test_review_fixes import QUIET

MAIN = Options(read_always=True, max_pages=10)
CFG = CrawlConfig(**{**QUIET, "max_pages": 10})
HOME = "https://shop.test/"

# What a page reader hands back for a page with a chat widget in an iframe: the frame's whole document, written into
# the page inside a marked element (the shape seen on 2026-10-11, with made-up names).
WIDGET = ('<div id="widget-holder"><div src="https://widgets.example/chat/index.html?site=shop" style="height: 0px;" data-original-tag="iframe">'
          '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="robots" content="noindex, nofollow"><title>Widget</title>'
          '<meta name="description" content="A chat widget"><link rel="canonical" href="https://widgets.example/chat/">'
          '<script type="application/ld+json">{"@type": "SoftwareApplication", "name": "Chat"}</script></head>'
          '<body><div id="root"><h2>Chat with us</h2><p>Widget words that are not the shop\'s.</p><a href="https://widgets.example/terms">Widget terms</a>'
          '<img src="https://widgets.example/logo.png" alt="Widget logo"></div></body></html></div></div>')
OWN_HEAD = ('<meta name="robots" content="INDEX,FOLLOW"><meta name="description" content="Handmade oak tables.">'
            '<link rel="canonical" href="https://shop.test/">')
PAGE = doc("Oak Tables | Shop", "<h1>Oak tables</h1>" + TEXT + '<a href="/about">About the workshop</a>', OWN_HEAD)


def with_widget(page: str, widget: str = WIDGET) -> str:
    return page.replace("</main>", "</main>" + widget + '<footer><a href="/contact">Contact</a></footer>')


# -- (a) an embedded document is not the page's --------------------------------------------------------------------------
def test_an_inlined_iframe_documents_noindex_is_not_the_pages():
    html = with_widget(PAGE)
    analysis = analyze_html(html, HOME)
    # The page's own head says index: the widget's noindex, title, description and canonical are not the page's.
    assert noindex_directives(analysis, {}) == [] and analysis["title"] == "Oak Tables | Shop"
    assert [m["content"] for m in analysis["meta"] if m["name"] == "robots"] == ["INDEX,FOLLOW"]
    assert [m["content"] for m in analysis["meta"] if m["name"] == "description"] == ["Handmade oak tables."]
    assert analysis["canonicals"] == ["https://shop.test/"] and analysis["html_lang"] == "en"
    # Nor are its headings, text, links, images or structured data.
    assert [h["text"] for h in analysis["headings"]] == ["Oak tables"] and "Widget words" not in analysis["_visible_text"]
    assert analysis["structured_data"]["types"] == [] and not [i for i in analysis["images"] if "widgets.example" in (i["src"] or "")]
    links = extract_links(html, HOME)
    assert links == ["https://shop.test/", "https://shop.test/about", "https://shop.test/contact"]  # what follows the widget is still read
    assert [edge["target"] for edge in extract_link_edges(html, HOME)] == links
    # It is recorded as what it is, with the frame's address, and is not counted as an iframe (RND-4 gains nothing).
    [embedded] = analysis["embedded_documents"]
    assert embedded["src"] == "https://widgets.example/chat/index.html?site=shop" and embedded["chars"] > 400 and analysis["iframes"] == []
    # Sizes are those of the HTML as received; the text after the widget is kept.
    assert analysis["html_chars"] == len(html) and "Contact" in analysis["_visible_text"]
    assert analysis["main_offset_bytes"] == len(html[: html.index("<main")].encode())
    # The same page without the widget reads the same.
    plain = analyze_html(with_widget(PAGE, ""), HOME)
    assert all(plain[key] == analysis[key] for key in ("title", "meta", "canonicals", "headings", "visible_words", "text_sha256", "images"))
    assert plain["embedded_documents"] == [] and plain["outside_head"] == {"title": 0, "meta": [], "canonical": 0, "closed_early_by": None, "hreflang": 0, "robots_content": [], "properties": []}


def test_a_second_html_document_with_no_wrapper_is_cut_the_same_way():
    bare = WIDGET.split('data-original-tag="iframe">', 1)[1].rsplit("</div></div>", 1)[0]  # the document alone, no marked element
    assert bare.startswith("<!DOCTYPE html>") and bare.endswith("</html>")
    html = PAGE.replace("</main>", "</main><section>" + bare + '</section><footer><a href="/contact">Contact</a></footer>')
    analysis = analyze_html(html, HOME)
    assert noindex_directives(analysis, {}) == [] and analysis["title"] == "Oak Tables | Shop" and "Widget words" not in analysis["_visible_text"]
    assert analysis["embedded_documents"] == [{"src": None, "chars": len(bare)}] and "Contact" in analysis["_visible_text"]
    assert extract_links(html, HOME) == ["https://shop.test/", "https://shop.test/about", "https://shop.test/contact"]
    # With no doctype, the second <html> is where the cut starts.
    assert analyze_html(html.replace("<!DOCTYPE html><html lang", "<html lang"), HOME)["title"] == "Oak Tables | Shop"
    # No </html>: cut to the end of the element it sits in; what follows that element is still the page's.
    open_ended = html.replace("</body></html></section>", "</section>")
    cut = analyze_html(open_ended, HOME)
    assert cut["title"] == "Oak Tables | Shop" and "Widget words" not in cut["_visible_text"] and "Contact" in cut["_visible_text"]
    assert noindex_directives(cut, {}) == []


def test_ordinary_documents_are_left_exactly_as_they_came():
    for html in (PAGE, "<!doctype html><html><head><title>One</title></head><body><p>Text</p></body></html>", "", "<p>no document at all</p>",
                 # a doctype and <html> written in a script or a comment are text, not a second document
                 '<!doctype html><html><head><title>T</title></head><body><p>a</p><script>var s = "<!DOCTYPE html><html><head>";</script>'
                 "<!-- <html> --><p>b</p></body></html>",
                 # server warnings printed before the document: the first document is still the page's own
                 "<br /><b>Warning</b>: something<br /><!DOCTYPE html><html><head><title>T</title></head><body><p>a</p></body></html>"):
        assert strip_embedded(html) == (html, []), html[:60]
    # A real iframe element is still an iframe, as before.
    framed = analyze_html(PAGE.replace("</main>", '<iframe src="https://maps.example/embed" title="Map"></iframe></main>'))
    assert [frame["src"] for frame in framed["iframes"]] == ["https://maps.example/embed"] and framed["embedded_documents"] == []


def test_stripping_is_safe_on_huge_and_broken_html():
    # Never closed, never quoted properly, a million tags: one pass, and what cannot be matched is cut to the end.
    never_closed = PAGE.replace("</main>", '</main><div data-original-tag="iframe"><html><head><meta name="robots" content="noindex"><title>W</title>')
    cut = analyze_html(never_closed, HOME)
    assert cut["title"] == "Oak Tables | Shop" and noindex_directives(cut, {}) == [] and len(cut["embedded_documents"]) == 1
    began = time.monotonic()
    for hostile in ("<div a=\"" * 200_000, "<" * 500_000, "<a href='x" * 200_000 + ">", "<div>" * 300_000 + '<x data-original-tag="iframe">' + "</span>" * 300_000,
                    "<html>" * 200_000, "<p>" + "<!DOCTYPE html>" * 100_000, '<i data-original-tag=iframe>' * 100_000):
        stripped, _ = strip_embedded(hostile)
        assert len(stripped) <= len(hostile)
    assert time.monotonic() - began < 20


# -- (b) the page's own head ----------------------------------------------------------------------------------------------
def test_a_title_in_the_body_is_not_the_pages_title():
    stray = '<div class="chat"><title>chat.example</title><meta name="description" content="chat.example"><link rel="canonical" href="https://chat.example/"></div>'
    html = PAGE.replace("</main>", stray + "</main>")
    analysis = analyze_html(html, HOME)
    assert analysis["title"] == "Oak Tables | Shop"  # it used to read "Oak Tables | Shop chat.example"
    assert [m["content"] for m in analysis["meta"] if m["name"] == "description"] == ["Handmade oak tables."]
    assert analysis["canonicals"] == ["https://shop.test/"]
    assert analysis["outside_head"] == {"title": 1, "meta": ["description"], "canonical": 1, "closed_early_by": None, "hreflang": 0, "robots_content": [], "properties": []}
    assert "chat.example" not in analysis["_visible_text"]  # a <title> is not text a visitor sees, wherever it is
    # Only the first <title> of the head is the title.
    twice = analyze_html("<html><head><title>First</title><title>Second</title></head><body><p>x</p></body></html>")
    assert twice["title"] == "First" and twice["outside_head"]["title"] == 0


def test_a_document_with_no_head_tag_keeps_its_title_and_an_svg_title_is_still_ignored():
    bare = analyze_html('<title>Bare page</title><meta name="description" content="No head tag."><link rel="canonical" href="/bare">'
                        '<meta property="og:title" content="Bare"><p>Words of the page.</p><svg><title>Icon</title></svg>')
    assert bare["title"] == "Bare page" and bare["canonicals"] == ["/bare"] and bare["og"] == {"og:title": ["Bare"]}
    assert bare["meta"] == [{"name": "description", "content": "No head tag."}] and bare["outside_head"] == {"title": 0, "meta": [], "canonical": 0, "closed_early_by": None, "hreflang": 0, "robots_content": [], "properties": []}
    # A tracking pixel in a head's <noscript> does not end the head: the tags after it are still the page's.
    pixel = analyze_html('<html><head><noscript><img src="https://pixel.example/p.gif" height="1" width="1"></noscript><title>After the pixel</title>'
                         '<meta name="robots" content="noindex"></head><body><p>x</p></body></html>')
    assert pixel["title"] == "After the pixel" and noindex_directives(pixel, {})
    # An <svg> with its own <title> before the page's title, in the body or not: never the page's title.
    drawn = analyze_html("<html><head><title>Real</title></head><body><svg><title>Logo</title></svg><p>x</p></body></html>")
    assert drawn["title"] == "Real" and drawn["outside_head"]["title"] == 0


def audit_of(pages: dict[str, str], **options):
    def site(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n", headers={"content-type": "text/plain"})
        url = str(request.url)
        return httpx.Response(200, headers=HTML, text=pages[url]) if url in pages else httpx.Response(404, headers=HTML, text="<html><title>x</title></html>")
    return blocked_audit(site, **options)


def shop(body_extra: str = "", head: str = "", pages: int = 3) -> dict[str, str]:
    names = ["", "about", "tables", "chairs", "contact"][:pages]
    links = "".join(f'<a href="/{name}">{name or "home"} page</a> ' for name in names)
    return {f"https://bank.test/{name}": doc(f"{name.title() or 'Oak'} furniture from the workshop | Shop",
                                             f"<h1>{name.title() or 'Oak tables'}</h1>" + TEXT.replace("solar panels", f"{name or 'oak'} furniture") + links + body_extra, head)
            for name in names}


def test_a_robots_noindex_in_the_body_never_drops_the_page_and_acc3_says_so_once(no_lookups):
    outcome = audit_of(shop('<div class="widget"><meta name="robots" content="noindex, nofollow"></div>'))
    assert len(indexable_pages(outcome.result)) == 3
    acc3 = outcome.by_id()["ACC-3"]
    [note] = acc3.findings
    assert note.title == "3 page(s) carry a robots tag outside <head>: browsers ignore it; some crawlers may not"
    assert note.severity.value == "Info" and note.scope["count"] == 3 and note.evidence["robots_tags_outside_head"]["https://bank.test/"] == ["robots"]
    assert outcome.by_id()["STR-1"].status != "not_assessed" and outcome.by_id()["TSEO-1"].status != "not_assessed"
    # No page is called noindex because of it, in any check.
    assert not [f.title for c in outcome.checks for f in c.findings if "noindex" in f.title]


def test_a_noindex_in_the_real_head_still_drops_the_page(no_lookups):
    pages = shop()
    pages["https://bank.test/about"] = pages["https://bank.test/about"].replace("</title>", '</title><meta name="robots" content="noindex">')
    outcome = audit_of(pages)
    assert sorted(page.url for page in indexable_pages(outcome.result)) == ["https://bank.test/", "https://bank.test/tables"]
    [finding] = outcome.by_id()["ACC-3"].findings
    assert finding.title.startswith("noindex via meta") and finding.scope["urls"] == ["https://bank.test/about"]


# -- (c) Maya's own response decides indexability ------------------------------------------------------------------------
def test_mayas_copy_says_index_and_the_readers_says_noindex_the_page_is_kept_and_the_disagreement_is_recorded(tmp_path, no_lookups):
    pages = shop()
    outcome = audit_of(pages)
    # The reader's copy of one page has a noindex in its own head (a script added it); the other copies are the same.
    through = {**pages, "https://bank.test/about": pages["https://bank.test/about"].replace("</title>", '</title><meta name="robots" content="noindex">')}
    info = reader.apply(outcome, CFG, client_for(tmp_path, Firecrawl(through)), MAIN)
    assert info["used"] and info["pages_read"] == 3
    assert info["coverage"]["indexability_disagreements"] == [{"url": "https://bank.test/about", "own": [], "reader": ['<meta name="robots" content="noindex">']}]
    assert info["coverage"]["indexability_disagreements_count"] == 1
    # The page stays among the pages the content checks read: STR-1 looked at all three.
    assert outcome.by_id()["STR-1"].evidence["pages_checked"] == 3
    about_own = next(p for p in outcome.result.pages if p.url == "https://bank.test/about")
    about_read = next(p for p in info["view_pages"] if p.url == "https://bank.test/about")
    said = []
    kept = reader._merged(about_own, about_read, said)
    assert noindex_directives(kept.analysis, kept.headers) == [] and len(said) == 1 and kept.status == about_own.status
    assert kept.classification_evidence[-1] == ("Maya's own copy says index and the copy read through Firecrawl says noindex: "
                                                "Maya's own response is the one used")
    section = __import__("maya_audit.firecrawl.panel", fromlist=["x"]).section(info)
    assert section["coverage"]["indexability_disagreements_count"] == 1


def test_mayas_own_header_says_noindex_and_the_readers_copy_does_not_the_page_is_dropped(tmp_path, no_lookups):
    pages = shop()

    def site(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n", headers={"content-type": "text/plain"})
        url = str(request.url)
        extra = {"x-robots-tag": "noindex"} if url.endswith("/about") else {}
        return httpx.Response(200, headers={**HTML, **extra}, text=pages[url]) if url in pages else httpx.Response(404, headers=HTML, text="<html></html>")

    outcome = blocked_audit(site)
    info = reader.apply(outcome, CFG, client_for(tmp_path, Firecrawl(pages)), MAIN)
    assert info["used"] and info["pages_read"] == 3
    [row] = info["coverage"]["indexability_disagreements"]
    assert row == {"url": "https://bank.test/about", "own": ["X-Robots-Tag: noindex"], "reader": []}
    assert outcome.by_id()["STR-1"].evidence["pages_checked"] == 2  # the content checks left it out: Maya's own answer decides


def test_crawl_blocked_why_under_read_always_says_firecrawl_was_the_reader(tmp_path, no_lookups):
    pages = shop()
    info = reader.apply(audit_of(pages), CFG, client_for(tmp_path, Firecrawl(pages)), MAIN)
    assert info["used"] is True and info["crawl_blocked"] == {
        "blocked": False, "why": "Maya's own crawler read the site; Firecrawl read the pages as this audit's main page reader"}
    # Without read-always nothing was read through it, and the old sentence is still the true one.
    plain = reader.apply(audit_of(pages), CFG, client_for(tmp_path / "second", Firecrawl(pages)), Options(max_pages=10))
    assert plain["used"] is False and plain["crawl_blocked"]["why"] == "Maya's own crawler read the site, so Firecrawl was not used"


# -- (d) a check that looked at no page is not a pass ---------------------------------------------------------------------
NONE_INDEXABLE = ("Not assessed: none of the 3 pages read could be checked (all are noindex or canonical to another address), "
                  "so there was nothing to look at.")


def test_with_no_indexable_page_the_checks_that_found_nothing_are_not_assessed_with_the_reason(no_lookups):
    outcome = audit_of(shop(head='<meta name="robots" content="noindex">'))
    assert indexable_pages(outcome.result) == [] and coverage.page_access(outcome.result.pages)["readable"] == 3
    checks = outcome.by_id()
    for check_id in ("STR-7", "STR-8", "STR-22", "STR-23", "IDX-8"):
        assert (checks[check_id].status, checks[check_id].summary) == ("not_assessed", NONE_INDEXABLE), check_id
        assert checks[check_id].coverage["not_assessed"] == []
    # No content check is left saying "pass" over no page at all.
    assert {c.status for c in outcome.checks if c.check_id in reader.CONTENT_CHECKS} == {"not_assessed"}
    assert coverage.NEEDS_AN_INDEXABLE_PAGE == frozenset(reader.CONTENT_CHECKS) <= coverage.PAGE_DEPENDENT
    # The pages were read, and what does not depend on indexability still ran.
    assert checks["ACC-3"].status == "findings" and checks["IDX-1"].status != "not_assessed"


def test_with_indexable_pages_and_no_news_page_str22_still_passes(no_lookups):
    outcome = audit_of(shop(pages=5), max_pages=10)
    assert len(indexable_pages(outcome.result)) == 5
    checks = outcome.by_id()
    assert (checks["STR-22"].status, checks["STR-22"].summary) in (("not_applicable", "No news or press page among the pages read."),
                                                                   ("not_applicable", "No news or press page among the pages read."))
    assert checks["STR-23"].status in ("not_applicable", "pass", "partial") and checks["STR-8"].status in ("pass", "partial") and checks["IDX-8"].status != "not_assessed"


def test_a_check_whose_own_evidence_says_it_looked_at_no_page_is_not_assessed_also_in_a_saved_report():
    from maya_audit.findings import CheckResult
    from maya_audit.migrate import migrate_check

    access = {"fetched": 6, "impaired": 0, "readable": 6}
    empty = CheckResult("STR-8", "Semantic HTML", "pass", "No table-like <div> grids found.", evidence={"pages_checked": 0, "excluded_as_rnd1_root_cause": ["https://x.example/a"]})
    coverage.settle(empty, access, None, 4)
    assert empty.status == "not_assessed" and empty.summary == (
        "Not assessed: none of the 6 pages read could be checked (all were withheld because their content arrives after JavaScript), so there was nothing to look at.")
    looked = CheckResult("STR-8", "Semantic HTML", "pass", "No table-like <div> grids found.", evidence={"pages_checked": 4})
    coverage.settle(looked, access, None, 4)
    assert looked.status == "pass"
    other = CheckResult("IDX-1", "Status codes", "pass", "No errors.", evidence={"pages_checked": 0})  # not a check of indexable pages
    coverage.settle(other, access, None, 0)
    assert other.status == "pass"
    saved = migrate_check({"check_id": "IDX-8", "status": "pass", "summary": "No duplicate groups among 0 indexable self-canonical page(s).",
                           "evidence": {"candidates": 0}}, access)
    assert saved["status"] == "not_assessed" and "none of the 6 pages read" in saved["summary"]


# -- (e) the headline says when most page checks could not run -------------------------------------------------------------
def limited_outcome(run: int):
    """A made-up audit whose page checks are set by hand: the first `run` of them ran clean, the rest could not run."""
    outcome = audit_of(shop())
    known = [check for check in outcome.checks if check.check_id in coverage.PAGE_DEPENDENT]
    assert len(known) == 41
    for number, check in enumerate(known):
        check.findings, check.review_items = [], []
        check.status = "pass" if number < run else "not_assessed"
    for check in outcome.checks:  # nothing else adds a problem or a note
        if check.check_id not in coverage.PAGE_DEPENDENT:
            check.findings = []
    return outcome


def shown(outcome, language):
    pytest.importorskip("fastapi")
    from maya_audit_web import pdf, strings, summary

    report = json.loads(json.dumps(build_report(outcome.result, outcome.gates, outcome.checks), default=str))
    strings.set_language(language)
    try:
        view = summary.build(report, outcome="COMPLETED", reason="as saved")
        printed = pdf.render_html(view, rows=summary.search(report, limit=10)["items"], plan=summary.action_plan(report), generated_at="2026-10-11T00:00:00+00:00")
    finally:
        strings.set_language("en")
    return report, view, printed


def test_when_16_of_41_page_checks_ran_every_output_starts_by_saying_so_in_english_and_turkish(no_lookups):
    outcome = limited_outcome(16)
    english = "Only 16 of 41 page checks could run, so this is not a clean result. The 16 that ran found no problems on 3 pages"
    markdown = render_markdown(outcome.result, outcome.gates, outcome.checks)
    assert f"**{english}**" in markdown and markdown.index(english) < markdown.index("## What this audit covers")
    report, view, printed = shown(outcome, "en")
    assert report["schema_version"] == schema.SCHEMA_VERSION and report["problem_summary"]["page_checks"] == {"total": 41, "could_run": 16, "limited": True}
    assert headline(report["problem_summary"]) == english == view["headline"] and view["problem_summary"]["page_checks"]["limited"] is True
    # The first line of the printed summary, above the severity boxes.
    line = f'<p class="headline wrap">{escape(english, quote=True)}</p>'
    assert line in printed and printed.index(line) < printed.index("By severity")
    _, turkish_view, turkish_printed = shown(outcome, "tr")
    turkish = "41 sayfa kontrolünden yalnızca 16 tanesi çalıştırılabildi; bu temiz bir sonuç değildir. Çalışan 16 kontrol 3 sayfada sorun bulmadı"
    assert turkish_view["headline"] == turkish and f'<p class="headline wrap">{escape(turkish, quote=True)}</p>' in turkish_printed
    # With problems, the same first sentence and then the usual count.
    made = problem_summary([{"id": "X-1", "check_id": "IDX-1", "severity": "S2", "scope": {"kind": "page", "count": 1, "urls": ["https://shop.test/a"]}, "title": "Made-up"}],
                           pages_checked=50, checks=[{"check_id": c.check_id, "status": c.status} for c in outcome.checks])
    assert headline(made) == "Only 16 of 41 page checks could run, so this is not a clean result. 1 problem across assessed scope; 50 pages read for content (1 high)"


def test_when_30_of_41_page_checks_ran_the_headline_has_no_prefix_and_an_older_report_gets_the_count_when_shown(no_lookups):
    outcome = limited_outcome(30)
    report, view, printed = shown(outcome, "en")
    assert report["problem_summary"]["page_checks"] == {"total": 41, "could_run": 30, "limited": False}
    assert view["headline"] == "No problems found on 3 pages" == headline(report["problem_summary"]) and "Only " not in printed.split("By severity")[0].split('class="headline')[1]
    assert "**No problems found on 3 pages**" in render_markdown(outcome.result, outcome.gates, outcome.checks)
    # Exactly half is not "fewer than half"; the paid panels and the answer-engine panel are never page checks.
    assert page_checks([{"check_id": "STR-1", "status": "pass"}, {"check_id": "STR-2", "status": "not_assessed"}])["limited"] is False
    assert page_checks([{"check_id": "ANS-1", "status": "not_assessed"}, {"check_id": "DFS-3", "status": "not_assessed"},
                        {"check_id": "ACC-1", "status": "not_assessed"}]) == {"total": 0, "could_run": 0, "limited": False}
    # A report saved before schema 1.11 holds no `page_checks`: it is counted from the report's own checks when shown,
    # and the saved report is left as it was.
    pytest.importorskip("fastapi")
    from maya_audit_web import summary

    limited, _, _ = shown(limited_outcome(16), "en")
    older = {**limited, "schema_version": "1.10", "problem_summary": {k: v for k, v in limited["problem_summary"].items() if k != "page_checks"}}
    before = json.dumps(older, sort_keys=True)
    old_view = summary.build(older, outcome="COMPLETED", reason="as saved")
    assert old_view["headline"].startswith("Only 16 of 41 page checks could run, so this is not a clean result. ")
    assert old_view["problem_summary"]["page_checks"] == {"total": 41, "could_run": 16, "limited": True} and json.dumps(older, sort_keys=True) == before
    assert "page_checks" not in older["problem_summary"]


# -- the new sentences in the reader's language -----------------------------------------------------------------------------
def test_the_new_sentences_have_turkish_wording_and_english_says_one_page():
    pytest.importorskip("fastapi")
    from maya_audit_web import wording

    assert wording.line(NONE_INDEXABLE, "tr", "STR-22") == (
        "Değerlendirilmedi: okunan 3 sayfanın hiçbiri kontrol edilemedi (hepsi noindex veya canonical'ı başka bir adresi gösteriyor), "
        "bu nedenle bakılacak bir şey yoktu.", True)
    read_through = "Source: Firecrawl. " + NONE_INDEXABLE.replace(coverage.NONE_INDEXABLE, coverage.NONE_WITH_CONTENT)
    shown, translated = wording.line(read_through, "tr", "STR-8")
    assert translated and shown.startswith("Kaynak: Firecrawl. Değerlendirilmedi: okunan 3 sayfanın hiçbiri kontrol edilemedi (içerikleri JavaScript")
    assert wording.line("Not assessed: no page that could be checked was read, so there was nothing to look at.", "tr", "IDX-8")[1] is True
    assert wording.line(reader.MAIN_READER_NOT_BLOCKED_WHY, "tr") == (
        "Siteyi Maya'nın kendi tarayıcısı okudu; Firecrawl sayfaları bu denetimin ana sayfa okuyucusu olarak okudu", True)
    title = "1 page(s) carry a robots tag outside <head>: browsers ignore it; some crawlers may not"
    assert wording.title("ACC-3", title, "en") == ("1 page carries a robots tag outside <head>: browsers ignore it; some crawlers may not", True)
    assert wording.title("ACC-3", title.replace("1 page", "3 page"), "en")[0].startswith("3 pages carry a robots tag outside <head>")
    turkish, translated = wording.title("ACC-3", title.replace("1 page", "3 page"), "tr")
    assert translated and turkish.startswith("3 sayfada <head> dışında bir robots etiketi var")
