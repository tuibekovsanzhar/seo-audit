"""One page count, one stop sentence, one "not read" figure; files are not pages; a problem one shared header or
footer element causes is reported once for the whole site (DECISIONS 170, 171, 172).

Seen in four saved reports on 2026-10-11: "55 pages" under a cap of 50 (5 PDFs and 7 addresses that led to a page
already read were counted as pages); three stop reasons in one list, one of them "a credit or request limit" when no
credit had been refused; two different "not read" figures in one report; sitemap files listed as pages; and "1 link
has no text at all" on 50 of 50 pages for one heart icon in the header.

Every site, reader, page and report here is made up. Nothing is requested: sites are mock transports or the fake
server, and Firecrawl is in memory.
"""
import json
import re
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest

from maya_audit import coverage, shared_elements
from maya_audit.analysis import analyze_html
from maya_audit.checks.content_quality import str14_anchor_text
from maya_audit.checks.small_site import str19_links_to_nowhere
from maya_audit.checks.structure import str7_alt, str10_previews
from maya_audit.config import CrawlConfig
from maya_audit.firecrawl import Options, panel, reader
from maya_audit.html_links import extract_link_edges
from maya_audit.models import StopReason
from maya_audit.report import (allowance_sentence, also_fetched, audit_status, build_report, content_coverage_shown, headline,
                               known_unread, page_checks, page_item, page_sentence, problem_summary, problems_by_page_lines,
                               read_counts, read_sentence, reader_gaps, render_markdown, run_outcome, with_page_items)
from maya_audit.structure_data import StructureData
from maya_audit.technical_seo import run_traditional_seo_quality_check
from maya_audit.urls import non_page_kind
from test_firecrawl import HTML, ROBOTS_TEXT, SITE, TEXT, Firecrawl, blocked_audit, client_for, doc, no_lookups  # noqa: F401
from test_firecrawl_main_reader import open_site
from test_page_wording import finding
from test_page_wording import SITE as SHOP
from test_review_fixes import QUIET, TR, audit, page

ROOT = "https://bank.test"
MAIN = Options(read_always=True, max_pages=10)
CFG = CrawlConfig(**{**QUIET, "max_pages": 10})


# -- (a) pages are documents read, not addresses ----------------------------------------------------------------------
def fifty_addresses(tmp_path):
    """Maya's own crawl read 50 addresses: 38 pages, 5 PDFs and 7 /blog?tab= addresses. The page reader read 43 pages
    (the 38, and 5 only it reached) and recorded the 7 as redirecting to /blog, which it had read."""
    outcome = blocked_audit(open_site)
    info = reader.apply(outcome, CFG, client_for(tmp_path, Firecrawl(SITE)), MAIN)
    like = next(p for p in outcome.result.pages if p.url == f"{ROOT}/about")
    pages = [replace(like, url=f"{ROOT}/blog")] + [replace(like, url=f"{ROOT}/page-{n}") for n in range(37)]
    pdfs = [replace(like, url=f"{ROOT}/download?file={n}", content_type="application/pdf", analysis=None, outlinks=[]) for n in range(5)]
    tabs = [replace(like, url=f"{ROOT}/blog?tab=topic-{n}") for n in range(7)]
    outcome.result.pages = pages + pdfs + tabs
    rows = ([{"url": p.url, "outcome": "read", "status": 200} for p in pages]
            + [{"url": f"{ROOT}/only-the-reader-{n}", "outcome": "read", "status": 200} for n in range(5)]
            + [{"url": p.url, "outcome": "redirected", "final_url": f"{ROOT}/blog", "status": 200,
                "reason": "redirects to an address that is read under its own name"} for p in tabs]
            + [{"url": f"{ROOT}/gone", "outcome": "error", "status": 404}])
    section = {**panel.section(info), "pages": rows, "pages_read": 43, "requests_sent": 51,
               "stopped_because": "the Firecrawl request allowance of 50 for this audit is used. No request was sent.",
               "coverage": {**info["coverage"], "read": 43, "page_cap": 50, "cap_reached": False, "known_urls_not_requested": 449,
                            "not_requested_because": "request_allowance_used", "page_requests": 51, "requests_without_a_new_page": 8,
                            "unread_left_out": {"robots_disallowed": 9, "not_a_page": 3}, "sitemap_addresses_known": 273}}
    return outcome, section


def test_fifty_addresses_with_five_pdfs_and_seven_that_lead_to_a_read_page_are_43_pages_in_every_output(tmp_path, no_lookups):
    pytest.importorskip("fastapi")
    from maya_audit_web import pdf, practical, strings, summary

    outcome, section = fifty_addresses(tmp_path)
    counts = read_counts(outcome.result, section)
    assert counts == {"pages": 43, "read_by": {"maya_only": 0, "firecrawl_only": 5, "both": 38, "firecrawl": 43, "total": 43},
                      "other_addresses": {"files": 5, "same_page": 7}}
    by = counts["read_by"]
    assert by["maya_only"] + by["firecrawl_only"] + by["both"] == by["total"] == counts["pages"]
    assert read_sentence(counts) == "43 pages read. Also fetched: 5 files (PDF or other documents) and 7 addresses that lead to a page already read."

    # The JSON report: one figure, wherever a page count is held.
    report = json.loads(json.dumps(build_report(outcome.result, outcome.gates, outcome.checks, firecrawl=section)))
    report["firecrawl"] = section
    cover = report["audit_status"]["content_coverage"]
    assert cover["pages_read"] == cover["readable_unique_urls"] == report["problem_summary"]["pages_checked"] == 43
    assert cover["read_by"] == by and cover["other_addresses"] == {"files": 5, "same_page": 7} and cover["unread_left_out"] == {"robots_disallowed": 9, "not_a_page": 3}
    assert cover["note"].startswith("43 page(s) were read;") and cover["note"].endswith("Also fetched: 5 files (PDF or other documents) and 7 addresses that lead to a page already read.")
    assert report["audit_status"]["summary"].startswith("We read 43 page(s) through Firecrawl.")
    # The reading used its request allowance with 43 pages read: exactly one sentence about the stop, and no "credit".
    assert cover["reasons"] == ["the page reader used all 51 page requests this audit allows and read 43 pages; "
                                "8 requests led to pages already read or to missing pages",
                                "+12 addresses left out: disallowed by robots.txt or not a page"] and cover["known_urls_not_read"] == 449
    assert "credit" not in json.dumps(cover) and "Maya's crawl stopped" not in json.dumps(cover)
    assert "55" not in json.dumps({key: value for key, value in report.items() if key in ("problem_summary", "audit_status", "page_counts")})

    # The Markdown report.
    markdown = render_markdown(outcome.result, outcome.gates, outcome.checks, firecrawl=section)
    assert "**Pages read:** 43 (via Firecrawl). Also fetched: 5 files (PDF or other documents) and 7 addresses that lead to a page already read" in markdown
    assert "across assessed scope; 43 pages read for content" in markdown.split("## What this audit covers")[0] and "55 page" not in markdown

    # The results card and the printed page, in both languages.
    sentence = run_outcome(outcome.result, outcome.gates, section)[2]
    for language, said, also in (("en", "43 pages read.", "Also fetched: 5 files (PDF or other documents) and 7 addresses that lead to a page already read."),
                                 ("tr", "43 sayfa okundu.", "Ayrıca: 5 dosya (PDF veya başka belge) ve zaten okunmuş bir sayfaya giden 7 adres.")):
        strings.set_language(language)
        try:
            view = summary.build(report, outcome="INCOMPLETE", reason=sentence)
            assert view["pages_read"] == view["pages_stat"]["value"] == view["counts"]["pages_checked"] == view["method"]["pages_checked"] == 43
            assert view["pages_stat"]["also"] == also and view["pages_stat"]["sentence"] == f"{said} {also}"
            assert "43" in view["headline"] and "55" not in view["headline"] and view["status"]["coverage"]["read_by"] == by
            assert also in view["status"]["rows"][1]["note"] and "43" in view["status"]["rows"][1]["note"]
            rows = summary.search(report, limit=1000)["items"]
            html = pdf.render_html(view, rows=rows, plan=summary.action_plan(report), generated_at="2026-10-12", practical=practical.build(view, rows, report, None))
            assert f"<td class=\"wrap\">43 ({view['pages_stat']['detail']}). {also}</td>" in html and ">55<" not in html and "55 (" not in html
        finally:
            strings.set_language("en")


def test_what_else_was_fetched_is_worded_for_one_kind_or_both_and_left_out_when_there_is_none():
    assert also_fetched({"files": 0, "same_page": 0}) is None and read_sentence({"pages": 1, "other_addresses": {"files": 0, "same_page": 0}}) == "1 page read."
    assert also_fetched({"files": 1, "same_page": 0}) == "Also fetched: 1 file (PDF or other documents)."
    assert also_fetched({"files": 0, "same_page": 1}) == "Also fetched: 1 address that leads to a page already read."
    assert also_fetched({"files": 2, "same_page": 3}) == "Also fetched: 2 files (PDF or other documents) and 3 addresses that lead to a page already read."
    # An address whose redirect ends on a page nobody read is still a page Maya read; a PDF the reader was never asked for is a file.
    crawl = {"pages": [{"url": f"{ROOT}/a", "fetch_class": "ok", "status": 200, "content_type": "text/html"},
                       {"url": f"{ROOT}/b?x=1", "fetch_class": "ok", "status": 200, "content_type": "text/html; charset=utf-8"},
                       {"url": f"{ROOT}/price-list.pdf", "fetch_class": "ok", "status": 200, "content_type": "application/pdf"},
                       {"url": f"{ROOT}/moved", "fetch_class": "ok", "status": 301}, {"url": f"{ROOT}/wall", "fetch_class": "blocked", "status": 403}]}
    section = {"used": True, "pages": [{"url": f"{ROOT}/a", "outcome": "read"},
                                       {"url": f"{ROOT}/b?x=1", "outcome": "redirected", "final_url": f"{ROOT}/elsewhere"}]}
    assert read_counts(crawl, section) == {"pages": 2, "read_by": {"maya_only": 1, "firecrawl_only": 0, "both": 1, "firecrawl": 1, "total": 2},
                                           "other_addresses": {"files": 1, "same_page": 0}}
    assert read_counts(crawl, None)["pages"] == 2 and read_counts(crawl, {"used": False, "pages": section["pages"]})["read_by"]["maya_only"] == 2


def test_an_open_site_read_fully_reports_the_page_count_it_always_did(tmp_path, no_lookups):
    outcome = blocked_audit(open_site)
    info = reader.apply(outcome, CFG, client_for(tmp_path, Firecrawl(SITE)), MAIN)
    section = panel.section(info)
    report = build_report(outcome.result, outcome.gates, outcome.checks, firecrawl=section)
    cover = report["audit_status"]["content_coverage"]
    assert cover["pages_read"] == cover["readable_unique_urls"] == report["problem_summary"]["pages_checked"] == 4
    assert cover["read_by"] == {"maya_only": 0, "firecrawl_only": 0, "both": 4, "firecrawl": 4, "total": 4}
    assert cover["other_addresses"] == {"files": 0, "same_page": 0} and cover["reasons"] == [] and cover["level"] == "complete_sample"
    assert "Also fetched" not in cover["note"] and "Also fetched" not in render_markdown(outcome.result, outcome.gates, outcome.checks, firecrawl=section)
    assert content_coverage_shown(report) is cover  # a report that holds the figure is shown as it is
    # The reader was not asked for the sitemap; what Maya's own crawl knew of it is said beside the reader's own 0.
    assert section["coverage"]["sitemap_addresses_found"] == 0 and section["coverage"]["sitemap_addresses_known"] == len(outcome.result.sitemap_urls)


# -- (b) one stop sentence ------------------------------------------------------------------------------------------------
REDIRECTS = [f"{ROOT}/campaign?source={n}" for n in range(8)]
WIDE = {**SITE, f"{ROOT}/": SITE[f"{ROOT}/"] + "".join(f'<a href="/campaign?source={n}">Campaign {n}</a>' for n in range(8)),
        **{url: doc("Campaign", "<h1>Campaign</h1>" + TEXT) for url in REDIRECTS}}


def wide_site(request):
    if request.url.path == "/robots.txt":
        return httpx.Response(200, text=ROBOTS_TEXT, headers={"content-type": "text/plain"})
    url = str(request.url)
    return httpx.Response(200, headers=HTML, text=WIDE[url]) if url in WIDE else httpx.Response(404, headers=HTML, text="<html><title>x</title></html>")


def campaign_leads_home(body):
    """The reader finds every campaign address redirecting to the homepage, which it has read."""
    if "/campaign" in body["url"]:
        return httpx.Response(200, json={"success": True, "data": {"rawHtml": WIDE[f"{ROOT}/"], "metadata": {"statusCode": 200, "url": f"{ROOT}/", "sourceURL": body["url"]}}})
    return None


def read_wide(tmp_path, **client_options):
    outcome = blocked_audit(wide_site, max_pages=9)  # Maya's own crawl stops at its page cap, with addresses left over
    options = Options(read_always=True, max_pages=5)
    info = reader.apply(outcome, CrawlConfig(**{**QUIET, "max_pages": 9}), client_for(tmp_path, Firecrawl(WIDE, campaign_leads_home), max_pages=5, **client_options), options)
    section = panel.section(info)
    return outcome, section, audit_status(outcome.result, outcome.gates, outcome.checks, section)


def test_a_reading_that_used_its_request_allowance_says_so_in_one_sentence_and_never_says_credit(tmp_path, no_lookups):
    outcome, section, status = read_wide(tmp_path)
    cover = section["coverage"]
    assert outcome.result.stop_reason == StopReason.PAGE_CAP and section["stopped_because"].startswith("the Firecrawl request allowance of 6 ")
    assert '(5 plus one bootstrap reserve)' in section['stopped_because']
    assert cover["not_requested_because"] == "request_allowance_used" and cover["cap_reached"] is False and cover["known_urls_not_requested"] > 0
    read, sent = section["pages_read"], cover["page_requests"]
    assert sent == 6 and 1 <= read < 5 and cover["requests_without_a_new_page"] == sent - read  # the allowance is requests; fewer pages came of them
    reasons = status["content_coverage"]["reasons"]
    stop = (f"the page reader used all 6 page requests this audit allows and read {read} page{'' if read == 1 else 's'}; "
            f"{sent - read} request{'' if sent - read == 1 else 's'} led to pages already read or to missing pages")
    assert allowance_sentence(section) == stop and reasons[0] == stop
    # One sentence about the stop: not "reading stopped early", not a second "remain unchecked", not Maya's own page cap, and no "credit".
    said = "; ".join(reasons)
    assert len([text for text in reasons if re.search(r"stopped|remain unchecked|page cap|allow", text)]) == 1, reasons
    assert "credit" not in said and "Maya's crawl stopped" not in said and "reading stopped early" not in said
    assert outcome.result.stop_reason.value == "page_cap"  # still in the crawl's own record
    # The outcome sentence of a site Maya's own crawler could read names Maya's own stop and the one "not read" figure.
    sentence = run_outcome(outcome.result, outcome.gates, section)[2]
    assert f"{cover['known_urls_not_requested']} discovered URL(s) were not read" in sentence and "credit" not in sentence
    # On a site that challenged Maya's crawler the reader's sentence is the outcome's reason.
    walled = run_outcome(blocked_audit().result, blocked_audit().gates, {**section, "crawl_blocked": {"blocked": True}})[2]
    assert stop in walled and "credit" not in walled and walled.startswith(f"The audit finished with partial coverage: {read} page(s) were read through Firecrawl; ")
    # Both languages word it; a figure is never dropped.
    pytest.importorskip("fastapi")
    from maya_audit_web import wording

    turkish, translated = wording.reason(stop, "tr")
    assert translated and turkish.startswith("sayfa okuyucu bu denetimin izin verdiği 6 sayfa isteğinin tamamını kullandı") and str(sent - read) in turkish
    assert wording.outcome(sentence, "tr")[1] and wording.outcome(walled, "tr")[1] and "kredi" not in wording.outcome(walled, "tr")[0]


def test_a_real_credit_refusal_still_says_credit(tmp_path, no_lookups):
    outcome, section, status = read_wide(tmp_path, approved_credits=4)  # two pages' worth: the third request is refused for credits
    assert "credits" in section["stopped_because"] and section["coverage"]["not_requested_because"] == "credit_or_request_limit"
    assert allowance_sentence(section) is None
    said = "; ".join(status["content_coverage"]["reasons"])
    assert "reading stopped early (this audit's Firecrawl requests would reach" in said and "a credit or request limit was reached" in said


def test_a_reading_with_nothing_spent_elsewhere_drops_the_second_clause_and_an_old_report_is_recognised_by_its_refusal():
    section = {"used": True, "pages_read": 50, "requests_sent": 50, "coverage": {"not_requested_because": "request_allowance_used", "page_requests": 50,
                                                                                "requests_without_a_new_page": 0, "known_urls_not_requested": 3}}
    assert reader_gaps(section) == ["the page reader used all 50 page requests this audit allows and read 50 pages"]
    old = {"used": True, "pages_read": 43, "requests_sent": 51, "robots": {"source": "Maya's own crawler"},
           "stopped_because": "the Firecrawl page cap of 50 for this audit is reached. No request was sent.",
           "coverage": {"not_requested_because": "credit_or_request_limit", "known_urls_not_requested": 449}}
    assert reader_gaps(old) == ["the page reader used all 51 page requests this audit allows and read 43 pages; "
                                "8 requests led to pages already read or to missing pages"]
    # When the reader itself asked for robots.txt, that request was not for a page.
    assert allowance_sentence({**old, "robots": {"source": "Firecrawl"}}).startswith("the page reader used all 50 page requests")
    # The reader's own page cap is another matter, and is said as before.
    capped = {"used": True, "pages_read": 50, "coverage": {"not_requested_because": "page_cap", "cap_reached": True, "page_cap": 50, "known_urls_not_requested": 8357}}
    assert reader_gaps(capped) == ["8357 more discovered URL(s) remain unchecked (the page cap of 50 was reached)"]
    assert reader_gaps({**capped, "coverage": {**capped["coverage"], "unread_left_out": {"robots_disallowed": 9, "not_a_page": 3}}})[1] == \
        "+12 addresses left out: disallowed by robots.txt or not a page"


# -- (c) one "not read" figure ---------------------------------------------------------------------------------------------
def test_every_checks_crawl_gap_count_is_the_reports_one_not_read_figure(tmp_path, no_lookups):
    outcome, section, status = read_wide(tmp_path)
    unread = status["content_coverage"]["known_urls_not_read"]
    assert unread == known_unread(outcome.result, section) == section["coverage"]["known_urls_not_requested"] > 0
    assert unread != len(outcome.result.not_fetched_urls)  # Maya's own figure is another number; no check repeats it
    read = read_counts(outcome.result, section)["pages"]
    gaps = [(check.check_id, part) for check in outcome.checks for part in check.coverage.get("not_assessed") or []
            if part["part"] in coverage.CRAWL_GAP_NAMES]
    assert len(gaps) > 20 and {part["count"] for _, part in gaps} == {unread}
    assert all(part["reason"].startswith(f"this check ran on the {read} page(s) that were read; {unread} more page(s) were found and not read (") for _, part in gaps)
    assert all(part["reason"].endswith("page cap of 9 reached). Its result says nothing about pages that were not read") for _, part in gaps)
    left = section["coverage"]["unread_left_out"]
    assert set(left) == {"robots_disallowed", "not_a_page"} and status["content_coverage"]["unread_left_out"] == left


def test_a_saved_reports_parts_are_restated_when_shown_and_what_was_left_out_is_said_beside_the_figure():
    pytest.importorskip("fastapi")
    from maya_audit_web import strings, summary

    old = coverage.crawl_gap_part(50, 8358, "page cap of 50 reached")
    tseo = {"part": "discovered pages not fetched", "reason": "the crawl stopped at page_cap; their metadata and headings were not read", "count": 8358}
    kept = {"part": "truncated page bodies", "reason": "some HTML bodies exceeded the fetch-size limit", "count": 2}
    again = coverage.restated([old, tseo, kept], 50, 8357)
    assert [part.get("count") for part in again] == [8357, 8357, 2] and again[2] is kept and old["count"] == 8358  # a copy
    assert again[0]["reason"] == "this check ran on the 50 page(s) that were read; 8357 more page(s) were found and not read (page cap of 50 reached). Its result says nothing about pages that were not read"
    assert coverage.restated([old], 50, 0)[0] == {"part": coverage.CRAWL_GAP, "reason": "this check ran on the 50 page(s) that were read (page cap of 50 reached). "
                                                  "Its result says nothing about pages that were not read"}
    report = {"schema_version": "1.11", "gates": [], "answer_engine_panel": [],
              "checks": [{"check_id": "TSEO-1", "title": "Traditional metadata and heading quality", "status": "findings", "summary": "1 finding(s) across 50 checked page(s).",
                          "findings": [], "coverage": {"not_assessed": [tseo, old]}}],
              "crawl": {"pages": [{"url": f"{ROOT}/p{n}", "fetch_class": "ok", "status": 200, "content_type": "text/html"} for n in range(50)], "not_fetched_urls": ["x"] * 8358},
              "firecrawl": {"used": True, "purpose": "main page reader", "pages_read": 50, "pages": [{"url": f"{ROOT}/p{n}", "outcome": "read"} for n in range(50)],
                            "coverage": {"known_urls_not_requested": 8357, "cap_reached": True, "page_cap": 50}},
              "audit_status": {"content_coverage": {"known_urls_not_read": 8357, "unread_left_out": {"robots_disallowed": 1, "not_a_page": 0}, "level": "partial",
                                                    "pages_read": 50, "read_by": {}, "other_addresses": {}, "reasons": []}}}
    assert summary.unread_figures(report) == (50, 8357)
    assert [part["count"] for part in summary.check_view(report, "TSEO-1")["not_assessed"]] == [8357, 8357]
    assert [gap["count"] for gap in summary.coverage_gaps(report)] == [8357]  # the crawl gap itself is said once, by the note below
    assert summary._read_only_note(report).startswith("Covered only the 50 pages read; 8,357 found pages were not read. "
                                                      "(+1 address left out: disallowed by robots.txt or not a page) ")
    strings.set_language("tr")
    try:
        assert "(+1 adres kapsam dışında: robots.txt izin vermiyor veya sayfa değil)" in summary._read_only_note(report)
    finally:
        strings.set_language("en")


# -- (d) files are not pages --------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("url, kind", [
    (f"{ROOT}/sitemap.xml", "sitemap"), (f"{ROOT}/sitemaps/sitemap-products-1.xml.gz", "sitemap"), (f"{ROOT}/robots.txt", "robots"),
    (f"{ROOT}/files/price-list.PDF", "document"), (f"{ROOT}/feed.xml", "document"), (f"{ROOT}/catalogue.zip", "document"),
    (f"{ROOT}/media/hero.JPG?v=2", "image"), (f"{ROOT}/logo.svg", "image"), (f"{ROOT}/", None), (f"{ROOT}/blog/sitemap-of-ideas", None),
    (f"{ROOT}/products/kettle.html", None), (f"{ROOT}/Hesabim.aspx#/Favorilerim", None), (f"{ROOT}/robots.txt/about", None)])
def test_a_file_is_told_from_a_page_by_its_path(url, kind):
    assert non_page_kind(url) == kind


def test_a_stamped_sitemap_finding_makes_no_page_row_and_a_stray_file_address_is_listed_under_files():
    pytest.importorskip("fastapi")
    from maya_audit_web import pdf, practical, strings

    stamped = finding("IDX-5", "2 sitemap document(s) give (nearly) every URL the same <lastmod>", urls=["/sitemap-1.xml", "/sitemap-2.xml"], kind="sitewide", number=1)
    robots = finding("ACC-3", "noindex via X-Robots-Tag on 2 page(s)", "S3", ["/robots.txt", "/guide"], number=2)
    brochure = finding("IDX-1", "2 URL(s) return a client error (4xx), linked internally or listed in the sitemap", "S3", ["/files/brochure.pdf", "/old"],
                       {"pages": [{"url": f"{SHOP}/old", "status": 404}, {"url": f"{SHOP}/files/brochure.pdf", "status": 404}]}, number=3)
    summary = problem_summary([stamped, robots, brochure], pages_checked=12)
    assert summary["whole_site"]["finding_ids"] == [stamped["id"]] and summary["problems"] == 3
    assert [row["url"] for row in summary["by_page"]] == [f"{SHOP}/guide", f"{SHOP}/old"]
    assert [(row["url"], row["problems"], row["finding_ids"]) for row in summary["files"]] == [
        (f"{SHOP}/files/brochure.pdf", 1, [brochure["id"]]), (f"{SHOP}/robots.txt", 1, [robots["id"]])]
    assert set(summary["files"][0]) == set(summary["by_page"][0])  # the same row shape
    titles = {f["id"]: f["title"] for f in (stamped, robots, brochure)}
    lines = problems_by_page_lines(summary, titles, SHOP)
    table = "\n".join(lines)
    assert "| `/sitemap-1.xml` |" not in table and "**Files (sitemaps, robots.txt, documents)**" in lines
    assert lines.index("**Files (sitemaps, robots.txt, documents)**") > lines.index("| `/old` | 1 | Medium | Returns 404 |")
    assert f"| `/robots.txt` | 1 | Medium | {robots['title']} |" in lines and "| File | Problems | Worst severity | What is wrong with this file |" in lines
    rows = [{"id": f["id"], "title": f["title"]} for f in (stamped, robots, brochure)]
    for language, title in (("en", "Files (sitemaps, robots.txt, documents)"), ("tr", "Dosyalar (site haritaları, robots.txt, belgeler)")):
        strings.set_language(language)
        try:
            shown = practical.by_page(summary, rows)
            assert shown["files"]["title"] == title and [row["url"] for row in shown["files"]["rows"]] == [f"{SHOP}/files/brochure.pdf", f"{SHOP}/robots.txt"]
            assert not [row for row in shown["rows"] if row["url"] and non_page_kind(row["url"])] and shown["total"] == 3  # the whole site and two pages
            html = pdf._by_page(shown, SHOP)
            assert f"<h3>{title}</h3>" in html and html.index("/robots.txt") > html.index(f"<h3>{title}</h3>")
        finally:
            strings.set_language("en")
    # A report saved before files were listed apart: its sitemap rows are moved when it is shown, and it is not changed.
    saved = {key: value for key, value in summary.items() if key != "files"}
    saved["by_page"] = summary["by_page"] + summary["files"]
    saved["whole_site"] = {key: value for key, value in summary["whole_site"].items() if key != "shared_elements"}
    derived = with_page_items(saved, [stamped, robots, brochure])
    assert [row["url"] for row in derived["files"]] == [f"{SHOP}/files/brochure.pdf", f"{SHOP}/robots.txt"] and len(derived["by_page"]) == 2
    assert "files" not in saved and len(saved["by_page"]) == 4 and derived["whole_site"]["shared_elements"] == []
    # Only a file listed under files and nothing else still makes a section.
    assert problems_by_page_lines(problem_summary([finding("ACC-1", "robots.txt returns an HTML page", "S2", ["/robots.txt"])], pages_checked=1),
                                  {}, SHOP)[:3] == ["## Problems by page", "", "**Files (sitemaps, robots.txt, documents)**"]


# -- D1: one shared element, reported once ----------------------------------------------------------------------------------
HEART = '<div class="favi"><a href="/account#/favourites"><div class="svgIcon"><svg viewBox="0 0 10 10"></svg></div></a></div>'


VIEWPORT = '<meta name="viewport" content="width=device-width, initial-scale=1">'


def shell(body, header="", footer="", title="A made-up page"):
    # A viewport, so TSEO-1's page-markup findings (H32) stay out of these counts.
    return (f'<!doctype html><html lang="en"><head><title>{title}</title>{VIEWPORT}</head><body><header><nav><a href="/">Home</a>{header}</nav></header>'
            f"<main>{body}</main><footer>{footer}</footer></body></html>")


def made_pages(htmls):
    """Pages as the checks see them, from made-up HTML: nothing is fetched."""
    return [SimpleNamespace(url=url, analysis=analyze_html(html, url), body_truncated=False,
                            outlinks=[edge for edge in extract_link_edges(html, url) if edge["target"].startswith(SHOP)]) for url, html in htmls.items()]


def site_of(pages, **extra):
    return SimpleNamespace(origin=SHOP, pages=pages, stop_reason=StopReason.EXHAUSTED, not_fetched_urls=[], **extra)


def in_report(check):
    from maya_audit.models import to_jsonable

    findings = to_jsonable(check.findings)
    return findings, problem_summary(findings, {f.id: f.scope["_all_urls"] for f in check.findings}, pages_checked=50)


def test_one_icon_link_with_no_text_on_every_page_is_one_whole_site_line_that_names_its_href_with_the_fragment():
    pages = made_pages({f"{SHOP}/p{n}": shell(f"<h1>Page {n}</h1>", header=HEART) for n in range(50)})
    check = str14_anchor_text(site_of(pages), CFG, pages, set())
    [shared] = check.findings
    assert shared.title == "Shared header/footer: link to /account#/favourites has no text (on 50 page(s))"
    assert shared.scope["kind"] == "sitewide" and shared.scope["count"] == 50 and shared.severity.value == "S4"  # the severity of the per-page finding
    assert shared.evidence["shared_element"] == {"type": "link", "href": "/account#/favourites", "where": "nav", "kind": "link_no_text", "pages": 50}
    assert shared.expected == "every link has a name" and "aria-label" in shared.how_to_fix
    findings, summary = in_report(check)
    assert summary["by_page"] == [] and summary["whole_site"]["finding_ids"] == [shared.id]
    assert summary["whole_site"]["shared_elements"] == [{"finding_id": shared.id, "kind": "link_no_text", "pages": 50,
                                                         "element": {"type": "link", "href": "/account#/favourites", "where": "nav"}}]
    lines = problems_by_page_lines(summary, {shared.id: shared.title}, SHOP)
    assert lines[4] == "| Whole site | 1 | Low | Shared header/footer: link to /account#/favourites has no text (on 50 page(s)) |" and lines[5] == ""
    pytest.importorskip("fastapi")
    from maya_audit_web import catalog, practical, strings, wording

    assert wording.title("STR-14", shared.title, "en") == ("Shared header/footer: link to /account#/favourites has no text (on 50 pages)", True)
    assert wording.title("STR-14", shared.title, "tr") == ("Ortak üst/alt bölüm: /account#/favourites bağlantısının metni yok (50 sayfada)", True)
    assert "no idea where it leads" in catalog.note("STR-14", shared.title)["why"]
    strings.set_language("tr")
    try:
        [row] = practical.by_page(summary, [{"id": shared.id, "title": shared.title, "title_shown": wording.title("STR-14", shared.title)[0]}])["rows"]
        assert row["whole_site"] and row["label"] == "Tüm site" and row["lines"] == ["Ortak üst/alt bölüm: /account#/favourites bağlantısının metni yok (50 sayfada)"]
    finally:
        strings.set_language("en")


def test_the_same_icon_on_two_of_fifty_pages_stays_on_those_pages_and_a_pages_own_nameless_link_stays_beside_a_shared_one():
    few = made_pages({f"{SHOP}/p{n}": shell(f"<h1>Page {n}</h1>", header=HEART if n < 2 else "") for n in range(50)})
    [per_page] = str14_anchor_text(site_of(few), CFG, few, set()).findings
    assert per_page.title == "2 link(s) on 2 page(s) have no text at all" and per_page.scope["kind"] == "template"
    assert per_page.evidence["links"][0] == {**per_page.evidence["links"][0], "hrefs": ["/account#/favourites"], "where": "nav"}
    findings, summary = in_report(str14_anchor_text(site_of(few), CFG, few, set()))
    assert [row["url"] for row in summary["by_page"]] == [f"{SHOP}/p0", f"{SHOP}/p1"] and summary["whole_site"]["problems"] == 0
    assert page_sentence(summary["by_page"][0]["items"][0]) == "1 link has no text at all"
    # Both at once: the header's icon on all 50, and one page with a nameless link of its own.
    both = made_pages({f"{SHOP}/p{n}": shell(f"<h1>Page {n}</h1>" + ('<a href="/offers#spring"><i class="icon"></i></a>' if n == 7 else ""), header=HEART) for n in range(50)})
    titles = sorted(f.title for f in str14_anchor_text(site_of(both), CFG, both, set()).findings)
    assert titles == ["1 link(s) on 1 page(s) have no text at all", "Shared header/footer: link to /account#/favourites has no text (on 50 page(s))"]
    # Two icons that differ only in their fragment are two elements: each is named.
    two = made_pages({f"{SHOP}/p{n}": shell(f"<h1>Page {n}</h1>", header=HEART + '<a href="/account#/basket"><svg></svg></a>') for n in range(10)})
    assert sorted(f.evidence["shared_element"]["href"] for f in str14_anchor_text(site_of(two), CFG, two, set()).findings) == ["/account#/basket", "/account#/favourites"]


def test_a_small_site_of_four_pages_reports_per_page_exactly_as_before():
    footer = '<a href="#">Cookie policy</a><h5 class="footer-title">Support line</h5>'  # a link to content (a settings opener is a control)
    banner = '<figure><img src="/media/free-delivery.jpg" width="400" height="300"><figcaption>Diagram of delivery coverage</figcaption></figure>'
    htmls = {f"{SHOP}/p{n}": shell(f"<h1>Page {n}</h1><h2>About</h2>{banner}<figure><img src=\"/media/chart-{n}.png\"><figcaption>Chart of demand</figcaption></figure>", header=HEART, footer=footer) for n in range(4)}
    pages = made_pages(htmls)
    site = site_of(pages)
    assert shared_elements.MIN_PAGES == 5 and shared_elements.split({page.url: {"k"} for page in pages}, 4) == set()
    [links] = str14_anchor_text(site, CFG, pages, set()).findings
    assert links.title == "4 link(s) on 4 page(s) have no text at all" and links.scope["kind"] == "template"
    dead = [f for f in str19_links_to_nowhere(site, CFG, pages, set()).findings if f.severity.value != "Info"]
    assert [f.title for f in dead] == ["4 link(s) have no address a crawler can follow (they may still work for visitors through JavaScript)"] and dead[0].scope["count"] == 4
    jumps = [f for f in run_traditional_seo_quality_check(site, pages, set(), set()).findings if "heading" in f.title]
    assert [f.title for f in jumps] == ["4 heading level jump(s) in the page structure"] and jumps[0].scope["count"] == 4
    images = [f for f in str7_alt(site, CFG, pages, set(), set()).findings if f.severity.value == "S4"]
    assert [f.title for f in images] == ["8 likely meaningful image(s) on 4 page(s): 8 with no alt text, 0 with an empty alt"]
    assert not [f for check in (str14_anchor_text(site, CFG, pages, set()), str19_links_to_nowhere(site, CFG, pages, set())) for f in check.findings
                if "shared_element" in f.evidence]


def test_the_bar_is_the_shared_block_rule_sixty_percent_of_the_pages_checked_and_at_least_three():
    from maya_audit.config import SITEWIDE_SHARE

    assert SITEWIDE_SHARE == 0.6
    def on(count, total):
        return shared_elements.split({f"/p{n}": {"icon"} for n in range(count)}, total)
    assert on(30, 50) == {"icon"} and on(29, 50) == set()          # 60% of 50
    assert on(3, 5) == {"icon"} and on(2, 5) == set() and on(4, 4) == set()  # at least 3 pages, and 5 or more audited
    assert shared_elements.split({"/a": {"x", "y"}, "/b": {"x"}, "/c": {"x"}, "/d": {"y"}, "/e": set()}, 5) == {"x"}
    assert shared_elements.link_key("#/favourites", f"{SHOP}/account") == f"{SHOP}/account#/favourites"
    assert shared_elements.shown_address(f"{SHOP}/account?tab=1#/favourites", SHOP) == "/account?tab=1#/favourites"
    assert shared_elements.shown_address("https://cdn.example/a.png", SHOP) == "https://cdn.example/a.png"
    assert shared_elements.region(["footer", None, "footer", "nav"]) == "footer" and shared_elements.region([None, None]) == "repeated"


def test_footer_heading_jumps_and_content_jumps_are_two_findings_and_the_footer_one_names_the_heading():
    footer = '<h5 class="footer-title"> Support line</h5>'
    def body(n):
        # The heading before the footer's differs by page: an H2, an H3, or the page's only heading, its H1.
        last = ("<h2>Section</h2>", "<h2>Section</h2><h3>Detail</h3>", "" if n >= 16 else "<h2>Closing</h2>")[n % 3]
        own = "<h2>Plans</h2><h4>Small print</h4>" if n < 16 else ""          # 16 pages with a jump inside their own content
        return f"<h1>Page {n}</h1>{own}{last}"
    htmls = {f"{SHOP}/p{n}": shell(body(n), footer=footer if n < 37 else "<p>© Made-Up Shop</p>") for n in range(50)}
    pages = made_pages(htmls)
    check = run_traditional_seo_quality_check(site_of(pages), pages, set(), set())
    content, shared = check.findings
    assert content.title == "16 heading level jump(s) in the page structure" and content.scope["count"] == 16 and content.scope["kind"] == "template"
    assert shared.title == "Shared header/footer: heading “Support line” (H5) comes after a higher-level heading, skipping levels (on 37 page(s))"
    assert shared.scope["kind"] == "sitewide" and shared.severity == content.severity
    assert shared.evidence["shared_element"] == {"type": "heading", "text": "Support line", "level": 5, "where": "footer", "kind": "heading_jump_varied", "pages": 37}
    assert shared.evidence["comes_after_levels"] == [1, 2, 3] and shared.evidence["jumps"] == 37
    assert all(item["jump_count"] == 1 and item["examples"] == [{"from": 2, "to": 4, "text": "Small print", "in_chrome": False}] for item in content.evidence["items"])
    findings, summary = in_report(check)
    assert len(summary["by_page"]) == 16 and summary["whole_site"]["shared_elements"][0]["element"] == {"type": "heading", "text": "Support line", "level": 5, "where": "footer"}
    assert page_sentence(summary["by_page"][0]["items"][0]) == "Heading jumps H2→H4"
    # When every page comes to it from the same level, the level is said.
    same = made_pages({f"{SHOP}/p{n}": shell(f"<h1>Page {n}</h1><h2>Section</h2>", footer=footer) for n in range(6)})
    [only] = run_traditional_seo_quality_check(site_of(same), same, set(), set()).findings
    assert only.title == "Shared header/footer: heading “Support line” (H5) comes after an H2, skipping a level (on 6 page(s))"
    pytest.importorskip("fastapi")
    from maya_audit_web import wording

    assert wording.title("TSEO-1", shared.title, "tr") == (
        "Ortak üst/alt bölüm: “Support line” başlığı (H5) daha üst düzey bir başlıktan sonra geliyor, düzey atlanıyor (37 sayfada)", True)
    assert wording.title("TSEO-1", only.title, "tr")[0] == "Ortak üst/alt bölüm: “Support line” başlığı (H5) bir H2 başlığından sonra geliyor, bir düzey atlanıyor (6 sayfada)"
    assert wording.title("TSEO-1", only.title, "en")[0].endswith("skipping a level (on 6 pages)")


def test_a_footer_link_with_no_address_on_most_pages_is_one_whole_site_line_that_names_its_text():
    # A footer entry that should lead to a page. (Until 2026-10-11 this test used the cookie-settings opener, which is
    # a control and now belongs to the accessibility note: DECISIONS 177, tests/test_false_alarms.py.)
    cookie = '<a href="#">Mağazalarımız</a>'
    htmls = {f"{SHOP}/p{n}": shell(f"<h1>Page {n}</h1>" + ('<a href="javascript:void(0)">Read the guide</a>' if n == 3 else ""),
                                   footer=cookie if n < 47 else "") for n in range(50)}
    pages = made_pages(htmls)
    check = str19_links_to_nowhere(site_of(pages), CFG, pages, set())
    per_page, shared = check.findings
    assert shared.title == "Shared header/footer: link “Mağazalarımız” has no address (on 47 page(s))" and shared.scope["kind"] == "sitewide"
    assert shared.evidence["shared_element"] == {"type": "link", "text": "Mağazalarımız", "why": 'href="#"', "where": "footer", "component":"footer", "kind": "link_no_address", "pages": 47}
    assert shared.severity == per_page.severity and shared.how_to_fix == per_page.how_to_fix
    assert per_page.title.startswith("1 link(s) have no address a crawler can follow") and per_page.scope["urls"] == [f"{SHOP}/p3"]
    assert per_page.evidence["by_page"] == [{"url": f"{SHOP}/p3", "links": 1}]
    findings, summary = in_report(check)
    assert [row["url"] for row in summary["by_page"]] == [f"{SHOP}/p3"] and summary["whole_site"]["problems"] == 1
    pytest.importorskip("fastapi")
    from maya_audit_web import wording

    assert wording.title("STR-19", shared.title, "tr") == ("Ortak üst/alt bölüm: “Mağazalarımız” bağlantısının adresi yok (47 sayfada)", True)
    assert wording.title("STR-19", shared.title, "en")[0] == "Shared header/footer: link “Mağazalarımız” has no address (on 47 pages)"


def test_an_image_without_alt_text_that_most_pages_carry_is_one_whole_site_line_that_names_its_src():
    banner = '<figure><img src="/media/free-delivery-banner.jpg" width="400" height="300"><figcaption>Diagram of delivery coverage</figcaption></figure>'  # not banner-shaped: RND-4 takes those
    htmls = {f"{SHOP}/p{n}": shell(f"<h1>Page {n}</h1>{banner}" + (f'<figure><img src="/media/chart-{n}.png"><figcaption>Chart of demand</figcaption></figure>' if n < 2 else "")) for n in range(12)}
    pages = made_pages(htmls)
    check = str7_alt(site_of(pages), CFG, pages, set(), set())
    per_page, shared = [f for f in check.findings if f.severity.value == "S4"]
    assert per_page.title == "2 likely meaningful image(s) on 2 page(s): 2 with no alt text, 0 with an empty alt"
    # In the main content, in no block the markup names: "Repeated block", not "Shared header/footer" (DECISIONS 198).
    assert shared.title == "Repeated block: image /media/free-delivery-banner.jpg has no alt text (on 12 page(s))" and shared.scope["kind"] == "sitewide"
    assert shared.evidence["shared_element"] == {"type": "image", "src": "/media/free-delivery-banner.jpg", "where": "repeated", "kind": "image_no_alt", "pages": 12}
    pytest.importorskip("fastapi")
    from maya_audit_web import catalog, wording

    assert wording.title("STR-7", shared.title, "tr") == ("Tekrarlanan blok: /media/free-delivery-banner.jpg görselinin alt metni yok (12 sayfada)", True)
    assert "Alt text" in catalog.note("STR-7", shared.title)["why"]


def test_each_tseo1_finding_has_its_own_notes_and_the_band_notes_sit_only_on_the_length_findings():
    long_title = "A very long made-up title that runs far past the sixty characters of the guidance band"
    def html(n):
        description = ("Short.", "x" * 200)[n % 2]
        return (f'<!doctype html><html lang="en"><head><title>{long_title if n < 3 else "Hi"}</title><meta name="description" content="{description}">{VIEWPORT}</head>'
                f"<body><main><h1>Page {n}</h1><h3>Jump</h3></main></body></html>")
    pages = made_pages({f"{SHOP}/p{n}": html(n) for n in range(4)})
    check = run_traditional_seo_quality_check(site_of(pages), pages, set(), set())
    assert len(check.findings) == 5
    reader._label([check], reader.MAIN_SOURCE, reader.MAIN_WHY, notice=None)  # what the page reader adds to every finding
    lengths = [f for f in check.findings if "guidance band" in f.title]
    [heading] = [f for f in check.findings if "heading level jump" in f.title]
    assert len(lengths) == 4
    for found in check.findings:
        assert found.notes.count("Source: Firecrawl.") == 1 and found.notes[0] == "Source: Firecrawl.", found.title
    assert all(len(f.notes) == 3 and f.notes[1].startswith("Heuristic only: these character bands") and f.notes[2].startswith("Measured from Maya's extracted page title")
               for f in lengths)
    assert heading.notes == ["Source: Firecrawl.", "Heading order is guidance for readers and screen readers, not a ranking rule."]
    assert len({id(f.notes) for f in check.findings}) == 5  # no list is shared between findings
    pytest.importorskip("fastapi")
    from maya_audit_web import wording

    assert wording.note(heading.notes[1], "tr") == ("Başlık sırası okuyucular ve ekran okuyucular için bir yönergedir; bir sıralama kuralı değildir.", True)


# -- D3: small slips --------------------------------------------------------------------------------------------------------
def test_a_share_of_0_295_under_a_less_than_30_percent_rule_reads_29_percent():
    made = finding("RND-7", "1 page(s) have less than 30% of their text in the main content", urls=["/a", "/b", "/c"],
                   evidence={"pages": [{"url": f"{SHOP}/a", "main_share": 0.295}, {"url": f"{SHOP}/b", "main_share": 0.2999}, {"url": f"{SHOP}/c", "main_share": 0.29}]})
    assert page_sentence(page_item(made, f"{SHOP}/a")) == "Only 29% of the page's text is main content"
    assert page_item(made, f"{SHOP}/b")["values"] == {"percent": 29, "limit": 30} and page_item(made, f"{SHOP}/c")["values"]["percent"] == 29
    whole = finding("RND-7", "1 page(s) have less than 30% of their text in the main content", urls=["/d"], evidence={"pages": [{"url": f"{SHOP}/d", "main_share": 0.07}]})
    assert page_sentence(page_item(whole, f"{SHOP}/d")) == "Only 7% of the page's text is main content"


def test_an_og_tag_that_is_present_with_no_content_reads_empty_not_missing():
    def html(n):
        head = ('<meta property="og:title" content="">' if n < 2 else "") + '<meta property="og:description" content="A made-up page">'
        return f'<!doctype html><html lang="en"><head><title>Page {n}</title><meta name="description" content="Made up.">{head}</head><body><main><h1>Page {n}</h1></main></body></html>'
    pages = made_pages({f"{SHOP}/p{n}": html(n) for n in range(3)})
    titles = sorted(f.title for f in str10_previews(site_of(pages), CFG, pages, set(), StructureData()).findings)
    assert titles == ["1 page(s) have no og:title", "2 page(s) have an empty og:title", "3 page(s) have no og:image"]
    [empty] = [f for f in str10_previews(site_of(pages), CFG, pages, set(), StructureData()).findings if "empty" in f.title]
    assert empty.scope["urls"] == [f"{SHOP}/p0", f"{SHOP}/p1"] and empty.expected == "og:title has a value" and empty.how_to_fix == "Give og:title a value."
    pytest.importorskip("fastapi")
    from maya_audit_web import catalog, wording

    assert wording.title("STR-10", empty.title, "en") == ("2 pages have an empty og:title", True)
    assert wording.title("STR-10", empty.title, "tr") == ("2 sayfada og:title etiketi boş", True)
    assert wording.fix(empty.how_to_fix, "tr")[1] and wording.expected(empty.expected, "tr")[1] and catalog.has_own_note("STR-10", empty.title)


def test_a_data_address_of_500_kb_is_stored_in_under_100_characters():
    address = "data:image/png;base64," + "iVBORw0KGgoAAAANSUhEUgAA" * 21_400  # about 500 KB
    assert len(address) > 500_000
    pages = made_pages({f"{SHOP}/p{n}": shell(f'<h1>Page {n}</h1><figure><img src="{address}"><figcaption>Chart of results</figcaption></figure>') for n in range(2)})
    [alt] = [f for f in str7_alt(site_of(pages), CFG, pages, set(), set()).findings if f.severity.value == "S4"]
    stored = alt.evidence["images"][0]["src"]
    assert len(stored) < 100 and stored.startswith("data:image/png;base64,iVBORw0KGgo") and stored.endswith("… (502 KB data address)")
    assert len(json.dumps(alt.evidence)) < 1000
    assert shared_elements.short_data_address("https://cdn.example/a.png") == "https://cdn.example/a.png" and shared_elements.short_data_address("data:image/gif;base64,R0lGOD") == "data:image/gif;base64,R0lGOD"


def test_two_identical_youtube_iframes_on_a_page_give_one_row():
    video = '<iframe src="https://www.youtube.com/embed/made-up-id" title="Tanıtım"></iframe>'
    outcome = audit({"/tanitim": page(f"<h1>Tanıtım</h1><p>{TR}</p>{video}<div class=\"mobile\">{video}</div>"
                                      '<iframe src="https://www.youtube.com/embed/another-id"></iframe>')})
    [frames] = [f for f in outcome.by_id["RND-4"].findings if "iframe" in f.title and f.severity.value == 'Info']
    assert [item["iframe_src"] for item in frames.evidence["items"]] == ["https://www.youtube.com/embed/made-up-id", "https://www.youtube.com/embed/another-id"]
    [unnamed] = [f for f in outcome.by_id['RND-4'].findings if 'lack an accessible name' in f.title]
    assert unnamed.severity.value == 'S4' and unnamed.confidence.value == 'verified'
    assert [r['iframe_src'] for r in unnamed.evidence['items']] == ['https://www.youtube.com/embed/another-id']


# -- A1e follow-up: a saved report whose zero-page checks read "partial" --------------------------------------------------------
def test_a_saved_report_whose_five_zero_page_checks_are_partial_says_only_18_of_41_could_run():
    pytest.importorskip("fastapi")
    from maya_audit_web import strings, summary

    names = sorted(coverage.PAGE_DEPENDENT)
    assert len(names) == 41
    zero = {"IDX-8": {"candidates": 0}, "STR-7": {"pages_checked": 0, "excluded_as_rnd1_root_cause": []}, "STR-8": {"pages_checked": 0, "real_tables": 0},
            "STR-22": {"news_pages": 0}, "STR-23": {"job_pages": 0}}  # as saved on 2026-10-11: the last two carry no such figure
    rest = [name for name in names if name not in zero]
    status = {**{name: "not_assessed" for name in rest[:20]}, **{name: "pass" for name in rest[20:]}, **{name: "partial" for name in zero}}
    checks = [{"check_id": name, "title": name, "status": status[name], "summary": "made up", "findings": [], "review_items": [], "evidence": zero.get(name, {}),
               "coverage": {"not_assessed": []}} for name in names] + [{"check_id": "ACC-1", "title": "robots.txt", "status": "pass", "summary": "made up", "findings": [],
                                                                         "review_items": [], "evidence": {}, "coverage": {"not_assessed": []}}]
    assert page_checks(checks) == {"total": 41, "could_run": 18, "limited": True}  # 21 are not "not assessed"; three of them looked at nothing
    # The figure saved with the report said 21: it is counted again when the report is shown, and the report is not changed.
    saved = {**problem_summary([], pages_checked=50), "page_checks": {"total": 41, "could_run": 21, "limited": False}}
    report = {"schema_version": "1.11", "checks": checks, "findings_in_priority_order": [], "problem_summary": saved}
    shown = summary.problems_of(report, None, 50)
    assert shown["page_checks"] == {"total": 41, "could_run": 18, "limited": True} and saved["page_checks"]["could_run"] == 21
    assert headline(shown) == "Only 18 of 41 page checks could run, so this is not a clean result. The 18 that ran found no problems on 50 pages"
    assert summary.headline(50, 0, shown["by_severity"], 0, shown["page_checks"]) == headline(shown)
    strings.set_language("tr")
    try:
        assert "18" in summary.headline(50, 0, shown["by_severity"], 0, shown["page_checks"]) and "41" in summary.headline(50, 0, shown["by_severity"], 0, shown["page_checks"])
    finally:
        strings.set_language("en")
    # A check with a finding, or with pages to look at, could run; one that is not a content check is not judged by this figure.
    assert page_checks([{"check_id": "STR-7", "status": "findings", "findings": [{"id": "x"}], "evidence": {"pages_checked": 0}},
                        {"check_id": "STR-8", "status": "partial", "findings": [], "evidence": {"pages_checked": 12}},
                        {"check_id": "PRF-1", "status": "partial", "findings": [], "evidence": {"pages_checked": 0}}]) == {"total": 3, "could_run": 3, "limited": False}


# -- team-preview-12: calibration from real audits (2026-10-12) -------------------------------------------------------
def test_no_page_row_repeats_a_line_in_any_output():
    """Two checks can say the same thing about a page (IDX-8 and STR-1 both see a shared title): the row says it once,
    and still counts both problems."""
    from maya_audit.report import page_sentence, problems_by_page_lines
    from maya_audit_web import practical

    def item(number, check):
        return {"finding_id": f"{check}-made-up-{number}", "check_id": check, "severity": "S4", "kind": "title_shared",
                "values": {"title": "Walnut Shop", "others": 1}}
    items = [item(1, "IDX-8"), item(2, "STR-1"), {"finding_id": "STR-2-made-up-3", "check_id": "STR-2", "severity": "S4", "kind": "no_h1", "values": {}}]
    assert page_sentence(items[0]) == page_sentence(items[1]) == "Shares its title “Walnut Shop” with 1 other page"
    row = {"problems": 3, "worst_severity": "S4", "finding_ids": [i["finding_id"] for i in items], "items": items}
    summary = {"pages_checked": 2, "problems": 3, "notes": 0, "by_severity": {"S1": 0, "S2": 0, "S3": 0, "S4": 3, "Info": 0},
               "whole_site": {"problems": 0, "worst_severity": None, "finding_ids": [], "shared_elements": []},
               "by_page": [{"url": "https://shop.example/", **row}, {"url": "https://shop.example/en/home/", **row}], "files": [], "not_listed": []}
    titles = {i["finding_id"]: "made-up title" for i in items}
    markdown = [line for line in problems_by_page_lines(summary, titles, "https://shop.example") if line.startswith("| `")]
    assert len(markdown) == 2
    for line in markdown:
        said = line.rstrip(" |").split(" | ")[-1].split("; ")
        assert said == ["Shares its title “Walnut Shop” with 1 other page", "No <h1>"] and " | 3 | " in line, line  # said once; three problems counted
    rows = [{"id": i["finding_id"], "check_id": i["check_id"], "title": "made-up title", "severity": "S4"} for i in items]
    table = practical.by_page(summary, rows)
    assert [r["lines"] for r in table["rows"]] == [["Shares its title “Walnut Shop” with 1 other page", "No <h1>"]] * 2
    assert all(r["problems"] == 3 and len(r["lines"]) == len(set(r["lines"])) for r in table["rows"])


def test_findings_are_ordered_by_severity_then_by_what_they_stand_in_the_way_of_not_by_page_count():
    from maya_audit.findings import Finding, Severity, impact_rank, priority_key, scope_for
    from maya_audit.models import Confidence

    def made(check, severity, pages):
        return Finding(check, f"{check} made-up", severity, Confidence.VERIFIED, "made-up", [], scope_for([f"https://shop.example/p{n}" for n in range(pages)]),
                       {}, "expected", "Fix it.")
    share, canonical, sitemap, heading = made("RND-7", Severity.S4, 41), made("IDX-4", Severity.S4, 1), made("IDX-5", Severity.S3, 1), made("STR-2", Severity.S4, 4)
    ordered = sorted([share, heading, canonical, sitemap], key=priority_key)
    assert [f.check_id for f in ordered] == ["IDX-5", "IDX-4", "STR-2", "RND-7"]  # Medium first; among Low, reach before wording before tidiness
    assert impact_rank("RND-7") > impact_rank("STR-2") > impact_rank("IDX-5") > impact_rank("IDX-4")
    # The share of main content is never first while anything weightier of the same severity exists, whatever its page count.
    assert sorted([share, canonical], key=priority_key)[0] is canonical and sorted([made("RND-7", Severity.S4, 50), made("STR-14", Severity.S4, 3)], key=priority_key)[0].check_id == "RND-7"


def test_a_menu_per_language_is_shared_within_its_own_part_of_the_site_and_its_links_are_one_finding():
    from maya_audit import shared_elements
    turkish = [f"https://clinic.example/tr/p{n}/" for n in range(26)]
    english = [f"https://clinic.example/en/p{n}/" for n in range(14)]
    other = [f"https://clinic.example/ar/p{n}/" for n in range(4)] + [f"https://clinic.example/x{n}" for n in range(6)]
    keys = {**{url: {("Bölümlerimiz", "#"), ("Tanı", "#")} for url in turkish}, **{url: {("Departments", "#")} for url in english},
            **{url: {("قسم", "#")} for url in other[:4]}, turkish[0]: {("Bölümlerimiz", "#"), ("Tanı", "#"), ("Detaylar", "#")}}
    everything = turkish + english + other
    assert shared_elements.split(keys, len(everything)) == set()                    # 26 of 50 is not most of the site
    shared = shared_elements.split(keys, everything)
    assert shared == {("Bölümlerimiz", "#"), ("Tanı", "#"), ("Departments", "#")}   # most of /tr/ and most of /en/; /ar/ has under 5 pages
    assert shared_elements.section_of("https://clinic.example/tr/p1/") == "tr" and shared_elements.section_of("https://clinic.example/about") == ""
    assert shared_elements.named(["A", "B", "C", "D", "E", "F"]) == "“A”, “B”, “C”, “D” and 2 more" and shared_elements.named(["A", "B"]) == "“A”, “B”"
    assert shared_elements.address_pattern("https://shop.example/wp-content/uploads/2017/04/tray.png", "https://shop.example") == "/wp-content/uploads/…/*.png"
    assert shared_elements.address_pattern("https://shop.example/products/tray/", "https://shop.example") is None  # a page is never a pattern
    assert shared_elements.address_pattern("https://cdn.example/img/a.jpg", "https://shop.example") == "https://cdn.example/img/*.jpg"


def test_an_action_starts_with_what_to_do_in_english_and_ends_with_it_in_turkish():
    import json as json_module
    from pathlib import Path as PathType
    from maya_audit_web import practical
    say = practical.action_sentence
    assert say("Engines that honor the canonical will index the target instead of this page's own content. Make the page self-canonical if its "
               "content should be cited, or mark it as intended.", "en") == "Make the page self-canonical if its content should be cited, or mark it as intended."
    assert say("If these pages should appear in AI answers, remove the directive. If it is deliberate, mark it as intended.", "en") == \
        "Remove the directive if these pages should appear in AI answers."
    assert say("An HTML page parses as an empty robots.txt. That is usually harmless; serve plain text if you intend to set rules.", "en") == \
        "Serve plain text if you intend to set rules."
    assert say("Add one <h1> that names the page's topic.", "en") == "Add one <h1> that names the page's topic."
    assert say("No action needed.", "en") == "No action needed." and say("", "en") == ""
    table = json_module.loads((PathType(practical.__file__).parent / "locales" / "findings" / "tr.json").read_text(encoding="utf-8"))["fixes"]
    without = [fix for fix in table if practical._first_word(say(fix, "en")) not in practical.ACTION_VERBS]
    # Every fix text of the engine gives an instruction, except the ones that say there is nothing to do (notes, never in the list).
    assert all(text.startswith(("No action needed", "Normal consolidation", "Nothing to fix")) for text in without), without
    assert say("Canonical'a uyan motorlar bu sayfanın kendi içeriği yerine hedef sayfayı dizine ekler. İçeriğine atıf yapılması gerekiyorsa sayfanın "
               "canonical etiketini kendisine yöneltin; değilse “kasıtlı” olarak işaretleyin.", "tr") == \
        "İçeriğine atıf yapılması gerekiyorsa sayfanın canonical etiketini kendisine yöneltin."
    row = {"check_id": "IDX-4", "title": "1 page(s) are canonicalized to a URL with different content", "sample_pages": ["https://clinic.example/en/"], "pages_total": 1}
    assert practical.specific_action(row) == "Make the canonical of /en/ point to /en/ itself."
    assert practical.specific_action({**row, "pages_total": 3}) == "Make the canonical of each of these 3 pages point to the page itself."
    assert practical.specific_action({**row, "check_id": "STR-1"}) is None


def test_a_generic_link_on_most_pages_is_one_whole_site_line_naming_its_text_and_address():
    """ticimax, 2026-10-12: "tıklayınız" in the cookie notice on 49 of 50 pages was 49 rows."""
    notice = '<p>Çerezler hakkında bilgi için <a href="/cerez-aydinlatma/">tıklayınız.</a></p>'
    pages = made_pages({**{f"{SHOP}/p{n}": shell(f"<h1>Page {n}</h1>" + notice) for n in range(49)},
                        f"{SHOP}/own": shell('<h1>Own</h1><a href="/p1">devamı</a>')})
    check = str14_anchor_text(site_of(pages), CFG, pages, set())
    shared = next(f for f in check.findings if "shared_element" in f.evidence)
    # The notice is a paragraph of the page's content, not its header or footer: "Repeated block" (DECISIONS 198).
    assert shared.title == "Repeated block: link “tıklayınız.” to /cerez-aydinlatma/ has only generic text (on 49 page(s))"
    assert shared.scope["kind"] == "sitewide" and shared.evidence["shared_element"]["kind"] == "link_generic" and shared.severity.value == "S4"
    own = [f for f in check.findings if "shared_element" not in f.evidence]
    assert [f.title for f in own] == ['1 link(s) on 1 page(s) name their target only with generic text: "devamı" (1)']  # the page's own link stays on its row
    _findings, summary = in_report(check)
    assert [row["url"] for row in summary["by_page"]] == [f"{SHOP}/own"] and len(summary["whole_site"]["shared_elements"]) == 1


def test_a_link_with_no_text_that_one_template_writes_with_a_different_address_on_each_page_is_one_line_with_the_pattern():
    """adilehanim, 2026-10-12: each product page links its own photo with no text: 41 links on 40 pages, one template."""
    def product(n):
        return shell(f'<h1>Product {n}</h1><a href="/wp-content/uploads/2017/04/product_{n}.png"><img src="/thumbs/{n}.png"></a>')
    pages = made_pages({**{f"{SHOP}/urun-{n}/": product(n) for n in range(36)}, **{f"{SHOP}/sayfa-{n}/": shell(f"<h1>Page {n}</h1>") for n in range(10)},
                        f"{SHOP}/galeri/": shell('<h1>Galeri</h1><a href="/galeri/acilis"></a>')})
    check = str14_anchor_text(site_of(pages), CFG, pages, set())
    shared = next(f for f in check.findings if f.title.startswith("Shared"))
    assert shared.title == ("Shared template: links to /wp-content/uploads/…/*.png have no text (on 36 page(s)), for example "
                            "/wp-content/uploads/2017/04/product_0.png")
    assert shared.evidence["shared_element"] == {"type": "links", "pattern": "/wp-content/uploads/…/*.png", "where": "repeated", "kind": "link_no_text_pattern",
                                                  "example": "/wp-content/uploads/2017/04/product_0.png", "pages": 36}
    rest = [f for f in check.findings if not f.title.startswith("Shared")]
    assert [f.title for f in rest] == ["1 link(s) on 1 page(s) have no text at all"]   # a link to a page is never folded into a pattern
    # The same template on a third of the pages is not "most pages": it stays per page.
    few = made_pages({**{f"{SHOP}/urun-{n}/": product(n) for n in range(10)}, **{f"{SHOP}/sayfa-{n}/": shell(f"<h1>Page {n}</h1>") for n in range(30)}})
    assert [f.title for f in str14_anchor_text(site_of(few), CFG, few, set()).findings] == ["10 link(s) on 10 page(s) have no text at all"]


def test_the_entries_of_one_menu_without_an_address_are_one_finding_per_language_and_a_shared_footer_heading_is_named():
    """moodist, 2026-10-12: seven Turkish menu entries with href="#" on 26 of 50 pages and six English ones on 14, and
    the footer's H5 after each Turkish page's H2: half the site each, all of their own language's pages."""
    from maya_audit import technical_seo
    def menu(*texts):
        return "".join(f'<a href="#">{text}</a> ' for text in texts)
    turkish = {f"{SHOP}/tr/sayfa-{n}/": shell(f"<h1>Sayfa {n}</h1><h2>Bölüm</h2><p>metin</p>", header=menu("Bölümlerimiz", "Tanı ve Tedavi", "Kurumsal"),
                                              footer="<h5>100+ Doktor</h5>") for n in range(26)}
    english = {f"{SHOP}/en/page-{n}/": shell(f"<h1>Page {n}</h1><h2>Section</h2><h3>Part</h3>", header=menu("Medical Units", "Patients & Guests")) for n in range(14)}
    other = {f"{SHOP}/haber-{n}": shell(f"<h1>Haber {n}</h1>") for n in range(10)}
    other[f"{SHOP}/haber-0"] = shell('<h1>Haber 0</h1><a href="#">Hizmetlerimiz</a>')
    pages = made_pages({**turkish, **english, **other})
    check = str19_links_to_nowhere(site_of(pages), CFG, pages, set())
    titles = [f.title for f in check.findings if f.severity.value != "Info"]
    assert titles == ["1 link(s) have no address a crawler can follow (they may still work for visitors through JavaScript)",
                      "Shared header/footer: 3 links have no address (“Bölümlerimiz”, “Tanı ve Tedavi”, “Kurumsal”) (on 26 page(s) of /tr/)",
                      "Shared header/footer: 2 links have no address (“Medical Units”, “Patients & Guests”) (on 14 page(s) of /en/)"]
    grouped = check.findings[1].evidence["shared_element"]
    assert grouped["kind"] == "links_no_address" and grouped["texts"] == ["Bölümlerimiz", "Tanı ve Tedavi", "Kurumsal"] and grouped["pages"] == 26
    assert grouped["section"] == "tr" and grouped["where"] in ("header", "nav")
    # Each is one finding about its own section's pages, not about the whole site (DECISIONS 198, which amends 183):
    # its scope is those pages, and it is still one grouped line, never a line on each of its pages' rows.
    assert [(f.scope["kind"], f.scope["count"]) for f in check.findings[1:3]] == [("template", 26), ("template", 14)]
    findings, summary = in_report(check)
    assert [row["url"] for row in summary["by_page"]] == [f"{SHOP}/haber-0"] and summary["by_page"][0]["problems"] == 1
    assert summary["whole_site"]["problems"] == 2 and summary["not_listed"] == []
    assert [(entry["kind"], entry["element"]["section"], entry["pages"]) for entry in summary["whole_site"]["shared_elements"]] == [
        ("links_no_address", "tr", 26), ("links_no_address", "en", 14)]
    markdown = "\n".join(problems_by_page_lines(summary, {f["id"]: f["title"] for f in findings}, SHOP))
    assert "| Whole site or one section | 2 |" in markdown and "| Whole site |" not in markdown
    assert markdown.count("(on 26 page(s) of /tr/)") == 1 and markdown.count("(on 14 page(s) of /en/)") == 1 and "Also affected by" not in markdown
    assert "/tr/sayfa-0/" not in markdown and "/en/page-0/" not in markdown   # no row for a page that has only the menu
    pytest.importorskip("fastapi")
    from maya_audit_web import practical, strings, summary as web_summary

    rows = [web_summary.item(f) for f in findings]
    assert [row["affects"] for row in rows[1:3]] == ["Affects 26 pages of /tr/", "Affects 14 pages of /en/"]
    table = practical.by_page(summary, rows)
    assert [(row["label"], row["problems"]) for row in table["rows"]] == [("Whole site or one section", 2), (f"{SHOP}/haber-0", 1)]
    assert [line.rsplit(" (on ", 1)[1] for line in table["rows"][0]["lines"]] == ["26 pages of /tr/)", "14 pages of /en/)"]
    assert not [line for row in table["rows"] for line in row["lines"] if "whole site" in line.lower() or "Also affected" in line]
    for language, label, affects in (("tr", "Tüm site veya bir bölüm", "/tr/ bölümündeki 26 sayfayı etkiler"),):
        strings.set_language(language)
        try:
            assert practical.by_page(summary, [web_summary.item(f) for f in findings])["rows"][0]["label"] == label
            assert web_summary.item(findings[1])["affects"] == affects
        finally:
            strings.set_language("en")
    result = replace_stop(site_of(pages))
    jumps = [f for f in technical_seo.run_traditional_seo_quality_check(result, pages, set(), set()).findings if "eading" in f.title]
    assert [f.title for f in jumps] == ["Shared header/footer: heading “100+ Doktor” (H5) comes after an H2, skipping a level (on 26 page(s) of /tr/)"]
    assert jumps[0].scope["kind"] == "template"


def replace_stop(result):
    """The made-up site with the fields the technical-SEO check reads from a finished crawl."""
    for name, value in (("stop_reason", StopReason.EXHAUSTED), ("not_fetched_urls", []), ("discovered_urls", []), ("stop_detail", "")):
        if not hasattr(result, name):
            setattr(result, name, value)
    return result


def test_the_homepage_without_a_main_heading_or_organization_data_is_medium_and_other_pages_stay_low():
    from test_review_fixes import audit, page
    from test_blocked_and_small_sites import LONG
    routes = {"/": page(f"<p>Hoş geldiniz</p>{LONG}", title="Atölye"), "/hakkimizda/": page(f"<p>Biz</p>{LONG}", title="Hakkımızda | Atölye"),
              "/iletisim/": page(f"<h1>İletişim</h1>{LONG}", title="İletişim | Atölye")}
    outcome = audit(routes, image_checks_max=0)
    headings = {f.title: f for f in outcome.by_id["STR-2"].findings}
    assert headings["The homepage has no <h1>"].severity.value == "S3" and headings["The homepage has no <h1>"].scope["urls"] == [outcome.result.origin + "/"]
    assert headings["1 page(s) have no <h1>"].severity.value == "S4" and headings["1 page(s) have no <h1>"].scope["urls"] == [outcome.result.origin + "/hakkimizda/"]
    organization = next(f for f in outcome.by_id["STR-3"].findings if "Organization" in f.title)
    assert organization.severity.value == "S3"
    # Both are Medium, so both come before every Low finding, whatever its page count.
    from maya_audit.findings import priority_key
    ordered = sorted((f for c in outcome.checks for f in c.findings if f.severity.value != "Info"), key=priority_key)
    lows = [n for n, f in enumerate(ordered) if f.severity.value == "S4"]
    assert all(n < min(lows) for n, f in enumerate(ordered) if f.title in ("The homepage has no <h1>", "The homepage has no Organization structured data"))


def _http_hosts(*rows):
    """A made-up IDX-2 probe: (host, status, location) for each host's http:// address, as index_data records it."""
    def host(name, status, location=None):
        to_https = bool(location and location.startswith("https://") and 300 <= status < 400)
        return {"host": name, "role": "start", "tls": {"host": name, "valid": True, "days_left": 200, "not_after": "2027-05-01T00:00:00+00:00"},
                "http_redirect": {"http_url": f"http://{name}/", "checked": True, "status": status, "error": None, "location": location,
                                  "redirects_to_https": to_https}}
    hosts = [host(*row) for row in rows]
    return SimpleNamespace(origin=f"https://{hosts[0]['host']}", index=SimpleNamespace(hosts=hosts, variant_note=None))


def _http_lines(finding, language="en"):
    """The lines under an IDX-2 finding as the Markdown prints them (English) and as the card and the PDF word them."""
    from maya_audit.models import to_jsonable
    from maya_audit.report import detail_lines, detail_sentence
    saved = to_jsonable(finding)
    if language == "en":
        engine = [detail_sentence(line) for line in detail_lines(saved)]
        assert sorted(engine) == sorted(row["line"] for row in finding.evidence["hosts"])  # the lines kept in the evidence
    from maya_audit_web import practical, strings
    strings.set_language(language)
    try:
        shown = practical.details(saved)
    finally:
        strings.set_language("en")
    if language == "en":
        assert shown == engine
    return shown


def test_http_served_beside_https_is_high_and_a_redirect_to_another_http_address_says_where_it_goes():
    """adilehanim, 2026-10-12: http://www… answers 200 (the site is served on both); http://… redirects to
    http://www…. Two findings (one High, one Low) for one fact; now ONE finding, by the fact, with a line for each
    host (decision 188, which amends 181)."""
    pytest.importorskip("fastapi")
    from maya_audit.checks.index import idx2_tls
    from maya_audit_web import wording
    check = idx2_tls(_http_hosts(("www.shop.example", 200), ("shop.example", 301, "http://www.shop.example/")), CFG)
    [finding] = check.findings
    assert finding.title == "No HTTP to HTTPS redirect on www.shop.example, shop.example" and finding.severity.value == "S2"
    assert [row["outcome"] for row in finding.evidence["hosts"]] == ["served_on_http", "redirects_to_http_served"]
    assert _http_lines(finding) == [
        "http://www.shop.example/ answers 200 without redirecting: the site is also served without encryption",
        "http://shop.example/ redirects to http://www.shop.example/, which answers 200: still http://"]
    assert _http_lines(finding, "tr") == [
        "http://www.shop.example/ yönlendirme yapmadan 200 yanıtı veriyor: site şifrelemesiz olarak da sunuluyor",
        "http://shop.example/, http://www.shop.example/ adresine yönlendiriyor; o adres 200 yanıtı veriyor: hâlâ http://"]
    assert wording.title("IDX-2", finding.title, "en") == ("No HTTP to HTTPS redirect on www.shop.example, shop.example", True)
    assert wording.title("IDX-2", finding.title, "tr") == ("www.shop.example, shop.example üzerinde HTTP'den HTTPS'ye yönlendirme yok", True)
    assert check.summary == "1 finding(s) across www.shop.example, shop.example." and wording.line(check.summary, "tr", "IDX-2")[1]
    # A report saved before: one finding for each answer, said in a parenthesis. Its title still translates, and it has no lines.
    old = "No HTTP to HTTPS redirect on shop.example (http:// redirects to http://www.shop.example/, not to https://)"
    assert wording.title("IDX-2", old, "tr") == (
        "shop.example üzerinde HTTP'den HTTPS'ye yönlendirme yok (http:// adresi https:// yerine http://www.shop.example/ adresine yönlendiriyor)", True)
    assert wording.title_key("IDX-2", old) == ["idx2.no_redirect"] and wording.title_key("IDX-2", finding.title) == ["idx2.no_redirect.hosts"]
    from maya_audit.report import detail_lines
    assert detail_lines({"check_id": "IDX-2", "title": old, "evidence": {"hosts": [{"http_url": "http://shop.example/", "status": 301}]}}) == []


def test_a_redirect_that_reaches_https_in_two_steps_is_low_and_a_correct_host_is_listed_as_it_should():
    pytest.importorskip("fastapi")
    from maya_audit.checks.index import idx2_tls
    # The apex goes to http://www, which goes on to https://www: one extra step, nothing is served on http://.
    [extra] = idx2_tls(_http_hosts(("www.shop.example", 301, "https://www.shop.example/"), ("shop.example", 301, "http://www.shop.example/")), CFG).findings
    assert extra.title == "No HTTP to HTTPS redirect on shop.example" and extra.severity.value == "S4"
    assert _http_lines(extra) == ["http://shop.example/ redirects to http://www.shop.example/, which then redirects to https://: one extra step",
                                  "http://www.shop.example/ redirects to https:// as it should"]
    assert _http_lines(extra, "tr") == [
        "http://shop.example/, http://www.shop.example/ adresine yönlendiriyor; o adres de https:// adresine yönlendiriyor: fazladan bir adım",
        "http://www.shop.example/ olması gerektiği gibi https:// adresine yönlendiriyor"]
    # The apex is right and www answers 200: the title names www only, and the apex has its line.
    [served] = idx2_tls(_http_hosts(("shop.example", 301, "https://shop.example/"), ("www.shop.example", 200)), CFG).findings
    assert served.title == "No HTTP to HTTPS redirect on www.shop.example" and served.severity.value == "S2"
    assert served.scope["urls"] == ["http://www.shop.example/"]
    assert _http_lines(served) == ["http://www.shop.example/ answers 200 without redirecting: the site is also served without encryption",
                                   "http://shop.example/ redirects to https:// as it should"]
    # A redirect to an address that was not tested, and an answer that is neither: Low, and said as what was seen.
    [other] = idx2_tls(_http_hosts(("shop.example", 302, "http://other.example/landing"), ("www.shop.example", 404)), CFG).findings
    assert other.severity.value == "S4" and [row["outcome"] for row in other.evidence["hosts"]] == ["redirects_elsewhere", "other_status"]
    assert _http_lines(other) == ["http://shop.example/ redirects to http://other.example/landing, not to https:// (where that leads was not followed)",
                                  "http://www.shop.example/ answered 404 without redirecting to https://"]
    assert _http_lines(other, "tr") == ["http://shop.example/, https:// yerine http://other.example/landing adresine yönlendiriyor (bu adresin nereye vardığı izlenmedi)",
                                        "http://www.shop.example/, https:// adresine yönlendirmeden 404 yanıtı verdi"]


def test_both_hosts_redirecting_to_https_is_a_pass_with_the_same_summary():
    from maya_audit.checks.index import idx2_tls
    check = idx2_tls(_http_hosts(("shop.example", 301, "https://shop.example/"), ("www.shop.example", 308, "https://www.shop.example/")), CFG)
    assert check.status == "pass" and check.findings == []
    assert check.summary == "Certificates valid and http:// redirects to https:// on shop.example, www.shop.example."


def test_a_report_saved_before_the_impact_order_is_shown_in_it_and_keeps_its_severities():
    pytest.importorskip("fastapi")
    from maya_audit_web import summary

    def made(check, severity, pages):
        return {"id": f"{check}-made-up", "check_id": check, "title": f"{check} made-up", "severity": severity, "scope": {"kind": "template", "count": pages, "urls": []}}
    share, links, canonical, sitemap, note = made("RND-7", "S4", 41), made("STR-14", "S4", 40), made("IDX-4", "S4", 1), made("IDX-5", "S4", 1), made("STR-10", "Info", 9)
    saved = {"schema_version": "1.11", "checks": [{"check_id": f["check_id"], "findings": [f]} for f in (share, links, canonical, sitemap, note)],
             "findings_in_priority_order": [f["id"] for f in (share, links, canonical, sitemap, note)]}  # as written: most pages first
    assert [f["check_id"] for f in summary.findings(saved)] == ["IDX-4", "IDX-5", "RND-7", "STR-14", "STR-10"]  # reach, then trust, then tidiness
    assert [f["severity"] for f in summary.findings(saved)] == ["S4", "S4", "S4", "S4", "Info"]                   # the saved severities are kept
    assert [f["check_id"] for f in summary.findings({**saved, "schema_version": "1.12"})] == ["RND-7", "STR-14", "IDX-4", "IDX-5", "STR-10"]  # a new report's own order
