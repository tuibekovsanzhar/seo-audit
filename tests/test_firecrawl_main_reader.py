"""Firecrawl as the page reader of every audit, blocked or not.

Maya's own crawler still makes the direct requests (robots.txt, sitemap, redirects, headers, timing, the bot-access
test). Every Firecrawl here is in memory, and every site is a mock transport.
"""
import json

import httpx

from maya_audit.config import CrawlConfig
from maya_audit.firecrawl import Options, reader, settings
from maya_audit.report import build_report, readable_pages, render_markdown, render_text, run_outcome
from test_firecrawl import HTML, ROBOTS_TEXT, SITE, Firecrawl, blocked_audit, client_for, no_lookups  # noqa: F401
from test_review_fixes import QUIET

MAIN = Options(read_always=True, max_pages=10)
CFG = CrawlConfig(**{**QUIET, "max_pages": 10})
CONTENT = lambda outcome: [(c.check_id, c.status, sorted(f.title for f in c.findings)) for c in outcome.checks if c.check_id in reader.CONTENT_CHECKS]  # noqa: E731


def open_site(request):
    if request.url.path == "/robots.txt":
        return httpx.Response(200, text=ROBOTS_TEXT, headers={"content-type": "text/plain"})
    if request.url.path == "/old":
        return httpx.Response(301, headers={"location": "https://bank.test/about"})
    url = str(request.url)
    return httpx.Response(200, headers=HTML, text=SITE[url]) if url in SITE else httpx.Response(404, headers=HTML, text="<html><title>x</title></html>")


def test_a_challenged_site_read_through_firecrawl_is_not_called_blocked(tmp_path, no_lookups):
    outcome = blocked_audit()
    assert run_outcome(outcome.result, outcome.gates)[1] == "DEGRADED"
    gates_before = [(g.check_id, g.state) for g in outcome.gates]
    info = reader.apply(outcome, CFG, client_for(tmp_path, Firecrawl(SITE)), MAIN)
    assert info["used"] and info["pages_read"] == 4 and info["purpose"] == "main page reader" and info["options"]["read_always"] is True
    assert "AI crawlers may not see this content" not in json.dumps({k: v for k, v in info.items() if k != "view_pages"})

    # The outcome is no longer "could not be read properly"; the integrity gate of Maya's own crawl is unchanged.
    code, word, sentence = run_outcome(outcome.result, outcome.gates, info)
    assert (code, word) == (0, "COMPLETED") and sentence.startswith("We read 4 page(s) through Firecrawl") and "direct crawler was challenged" in sentence and "not measured" in sentence
    assert [(g.check_id, g.state) for g in outcome.gates] == gates_before
    assert run_outcome(outcome.result, outcome.gates)[1] == "DEGRADED"  # without the reader's section, Maya's crawl alone

    # The challenge is one Info note under AI crawler access, with the measurement kept as evidence.
    acc9 = outcome.by_id()["ACC-9"]
    [note] = acc9.findings
    assert note.severity.value == "Info" and note.title == (
        "Cloudflare challenged Maya's direct crawler on 1 of 1 request(s). 4 page(s) were read through Firecrawl instead. "
        "Genuine AI-crawler access was not measured.")
    assert note.evidence["pages_blocked_or_challenged"] == 1 and note.evidence["read_through"] == {"reader": "firecrawl", "pages_read": 4}
    assert note.evidence["severity_before_reader"] == "S3" and "presentation choice" in note.evidence["shown_as_a_note_because"]
    said = " ".join([note.title, note.how_to_fix, *note.notes, outcome.by_id()["ACC-9"].summary])
    for claim in ("not affected", "unaffected", "Nothing needs fixing", "can read this", "bots can read"):
        assert claim not in said, claim  # nothing was measured about real AI crawlers, so nothing is claimed
    assert "Not measured" in note.notes[1] and "not the vendors' real requests" in note.notes[1] and "This audit cannot say" in note.how_to_fix
    assert not [f for c in outcome.checks for f in c.findings if f.check_id == "ACC-9" and f.severity.value != "Info"]

    # Content checks carry the plain source, without the old warning.
    titles = outcome.by_id()["STR-1"]
    assert titles.summary.startswith("Source: Firecrawl. ") and titles.findings[0].notes[0] == "Source: Firecrawl."
    assert titles.evidence["source"] == {"reader": "firecrawl", "why": "Firecrawl is the page reader for this audit"}

    section = __import__("maya_audit.firecrawl.panel", fromlist=["x"]).section(info)
    assert readable_pages(outcome.result, section) == "4 (via Firecrawl)"
    text, markdown = render_text(outcome.result, outcome.gates, outcome.checks, firecrawl=section), render_markdown(outcome.result, outcome.gates, outcome.checks, firecrawl=section)
    assert "Pages read  4 (via Firecrawl)" in text and "Result      COMPLETED" in text
    assert "**Pages read:** 4 (via Firecrawl)" in markdown and "**Result:** COMPLETED" in markdown and "DEGRADED" not in markdown.split("##")[0]
    assert set(section) <= set(__import__("maya_audit.schema", fromlist=["x"]).FIRECRAWL_KEYS)


def test_a_site_is_still_called_blocked_when_firecrawl_failed_too(tmp_path, no_lookups):
    wall = lambda body: httpx.Response(200, json={"success": True, "data": {  # noqa: E731
        "rawHtml": "<html><title>Just a moment...</title><body>Checking your browser</body></html>", "metadata": {"statusCode": 403}}})
    outcome = blocked_audit()
    info = reader.apply(outcome, CFG, client_for(tmp_path, Firecrawl(SITE, wall)), MAIN)
    assert info["used"] is False and reader.also_blocked(info) and "Firecrawl basic was also blocked" in info["reason"]
    assert run_outcome(outcome.result, outcome.gates, info)[1] == "DEGRADED"
    [finding] = outcome.by_id()["ACC-9"].findings
    assert finding.severity.value == "S3" and finding.title.startswith("The site blocks or challenges automated visitors")


def test_a_normal_site_is_read_through_firecrawl_and_keeps_mayas_own_direct_evidence(tmp_path, no_lookups):
    plain = blocked_audit(open_site)
    outcome = blocked_audit(open_site)
    before = {c.check_id: (c.status, c.summary, len(c.findings)) for c in outcome.checks}
    own_pages = [(p.url, p.status, p.headers, p.elapsed_ms) for p in outcome.result.pages]
    api = Firecrawl(SITE)
    info = reader.apply(outcome, CFG, client_for(tmp_path, api), MAIN)

    # The same pages, asked for once each; robots.txt is Maya's own (no paid request for it) and its rules are obeyed.
    assert "https://bank.test/robots.txt" not in api.urls and len(api.urls) == len(set(api.urls))
    assert set(api.urls) == {"https://bank.test/", "https://bank.test/about", "https://bank.test/products", "https://bank.test/contact"}
    assert info["used"] and info["pages_read"] == 4 and info["purpose"] == "main page reader" and info["crawl_blocked"]["blocked"] is False
    assert info["robots"]["source"] == "Maya's own crawler" and not [u for u in api.urls if "/private/" in u]

    # Identical HTML gives identical content findings: nothing is lost by reading through Firecrawl.
    assert CONTENT(outcome) == CONTENT(plain)
    # Everything that is not a content check is exactly Maya's own, and so is the crawl record.
    untouched = [cid for cid in before if cid not in reader.CONTENT_CHECKS]
    after = {c.check_id: (c.status, c.summary, len(c.findings)) for c in outcome.checks}
    assert all(after[cid] == before[cid] for cid in untouched) and {"ACC-1", "ACC-9", "IDX-1", "PRF-1"} <= set(untouched)
    assert [(p.url, p.status, p.headers, p.elapsed_ms) for p in outcome.result.pages] == own_pages
    assert outcome.by_id()["ACC-9"].status == "pass"
    assert all(c.summary.startswith("Source: Firecrawl. ") for c in outcome.checks if c.check_id in reader.CONTENT_CHECKS)
    # The pages the checks saw keep Maya's own status, headers and timing, with Firecrawl's content.
    seen = {p.url: p for p in info["view_pages"]} if info.get("view_pages") else {}
    assert seen and all(p.user_agent == "Firecrawl" for p in seen.values())
    assert run_outcome(outcome.result, outcome.gates, info) == run_outcome(outcome.result, outcome.gates)
    section = __import__("maya_audit.firecrawl.panel", fromlist=["x"]).section(info)
    assert readable_pages(outcome.result, section) == "4 (via Firecrawl)"
    report = build_report(outcome.result, outcome.gates, outcome.checks)
    assert len(report["crawl"]["pages"]) == len(own_pages)


def test_content_only_firecrawl_can_see_reaches_the_content_checks(tmp_path, no_lookups):
    """A page whose text appears only after JavaScript: Maya's raw HTML is thin, Firecrawl's reading is not."""
    def thin(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS_TEXT, headers={"content-type": "text/plain"})
        return httpx.Response(200, headers=HTML, text='<!doctype html><html lang="en"><head><title>App</title></head><body><div id="root"></div></body></html>')
    outcome = blocked_audit(thin)
    assert not (outcome.result.pages[0].analysis or {}).get("h1")
    info = reader.apply(outcome, CFG, client_for(tmp_path, Firecrawl({"https://bank.test/": SITE["https://bank.test/"]})), MAIN)
    assert info["used"] and "Welcome" in json.dumps(info["view_pages"][0].analysis)
    assert outcome.result.pages[0].analysis.get("title") == "App"  # the crawl record itself is not rewritten


def test_a_page_firecrawl_could_not_read_keeps_mayas_own_reading(tmp_path, no_lookups):
    outcome = blocked_audit(open_site)
    partial = {url: html for url, html in SITE.items() if not url.endswith("/products")}
    info = reader.apply(outcome, CFG, client_for(tmp_path, Firecrawl(partial)), MAIN)
    assert info["used"] and info["pages_read"] == 3
    section = __import__("maya_audit.firecrawl.panel", fromlist=["x"]).section(info)
    assert readable_pages(outcome.result, section) == "4 (3 via Firecrawl, 1 by Maya's own crawler)"


def test_the_daily_guard_is_roomy_and_zero_data_retention_can_be_switched_off_for_the_computer(monkeypatch):
    assert settings.DAILY_CREDITS == 10000 and settings.zero_data_retention_wanted() and settings.main_reader_on()
    monkeypatch.setenv("MAYA_AUDIT_FIRECRAWL_ZERO_DATA_RETENTION", "off")
    monkeypatch.setenv("MAYA_AUDIT_FIRECRAWL", "off")
    assert not settings.zero_data_retention_wanted() and not settings.main_reader_on()
    assert Options().read_always is False  # a library caller still has to ask for it


def test_a_page_maya_found_only_in_the_sitemap_is_read_through_the_reader_without_a_made_up_depth(tmp_path, no_lookups):
    """Found by the offline demonstration of a JavaScript site: such a page has no click depth, and following its links crashed."""
    def sitemap_site(request):
        path = request.url.path
        if path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\nSitemap: https://bank.test/sitemap.xml\n", headers={"content-type": "text/plain"})
        if path == "/sitemap.xml":
            return httpx.Response(200, headers={"content-type": "application/xml"}, text=(
                '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                "<url><loc>https://bank.test/</loc></url><url><loc>https://bank.test/products</loc></url></urlset>"))
        shell = '<!doctype html><html lang="en"><head><title>App</title></head><body><div id="root"></div></body></html>'
        return httpx.Response(200, headers=HTML, text=shell) if path in ("/", "/products") else httpx.Response(404, headers=HTML, text="x")
    outcome = blocked_audit(sitemap_site)
    assert any(page.depth is None for page in outcome.result.pages)  # the sitemap-only page
    info = reader.apply(outcome, CFG, client_for(tmp_path, Firecrawl(SITE)), MAIN)
    assert info["used"] and info["pages_read"] >= 2 and any(page.depth is None for page in info["view_pages"])
