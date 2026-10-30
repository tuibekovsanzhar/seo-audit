"""Phase 1A: job status, direct access, content coverage and vendor-crawler evidence are separate facts, and a
provider's page keeps its own identity (address asked for, address reached, status known or not, when it was seen).

Every site is a mock transport and every reader is in memory.
"""
import json

import httpx
import pytest

from maya_audit.config import CrawlConfig
from maya_audit.findings import check_id_key
from maya_audit.firecrawl import Options, panel, reader
from maya_audit.models import GateResult
from maya_audit.report import audit_status, build_report, render_markdown, render_text, run_outcome
from test_firecrawl import HTML, ROBOTS_TEXT, SITE, TEXT, Firecrawl, blocked_audit, client_for, doc, no_lookups  # noqa: F401
from test_firecrawl_main_reader import open_site
from test_review_fixes import QUIET

ROOT = "https://bank.test"
MAIN = Options(read_always=True, max_pages=10)
CFG = CrawlConfig(**{**QUIET, "max_pages": 10})
CLAIMS = ("not affected", "unaffected", "Nothing needs fixing", "bots can read", "AI crawlers can access", "crawlers are allowed")


def read(tmp_path, pages=SITE, options=MAIN, transport=None, responder=None, **cfg):
    outcome = blocked_audit(transport, **cfg) if transport else blocked_audit(**cfg)
    config = CrawlConfig(**{**QUIET, "max_pages": 10, **cfg})
    info = reader.apply(outcome, config, client_for(tmp_path, Firecrawl(pages, responder)), options)
    section = panel.section(info)
    return outcome, info, section, build_report(outcome.result, outcome.gates, outcome.checks, firecrawl=section)


# 1 ----------------------------------------------------------------------------------------------------------------
def test_a_direct_challenge_and_a_readable_sample_keep_the_challenge_and_claim_nothing_about_real_crawlers(tmp_path, no_lookups):
    outcome, info, section, report = read(tmp_path)
    status = report["audit_status"]
    assert status["direct_access"]["state"] == "challenged" and status["direct_access"]["by_response"]["blocked"] == 1
    assert status["content_coverage"] == {**status["content_coverage"], "level": "complete_sample", "readable_unique_urls": 4,
                                          "pages_read": 4, "other_addresses": {"files": 0, "same_page": 0},
                                          # three numbers that do not overlap and add up to `total`; `firecrawl` is kept from schema 1.6
                                          "read_by": {"maya_only": 0, "firecrawl_only": 4, "both": 0, "firecrawl": 4, "total": 4}, "reasons": []}
    assert "the sample this audit could discover" in status["content_coverage"]["note"] and "not proof about pages it never found" in status["content_coverage"]["note"]
    assert status["vendor_crawler_evidence"] == {"state": "not_measured", "note": "Genuine AI-crawler access was not measured."}
    assert status["summary"].startswith("We read 4 page(s) through Firecrawl. Maya's direct crawler was challenged")
    # The raw gate and the direct observation are untouched; only the finding's presentation is a note.
    assert next(g for g in report["gates"] if g["check_id"] == "INT-1")["state"] == "degraded"
    assert report["crawl"]["pages"][0]["status"] == 403 and report["crawl"]["pages"][0]["fetch_class"] == "blocked"
    [note] = next(c for c in report["checks"] if c["check_id"] == "ACC-9")["findings"]
    assert note["severity"] == "Info" and note["evidence"]["severity_before_reader"] == "S3" and note["evidence"]["pages"][0]["status"] == 403
    code, word, sentence = run_outcome(outcome.result, outcome.gates, section)
    assert (code, word) == (0, "COMPLETED") and "some direct-request checks could not be completed" in sentence
    everything = json.dumps(report) + sentence + render_text(outcome.result, outcome.gates, outcome.checks, firecrawl=section) \
        + render_markdown(outcome.result, outcome.gates, outcome.checks, firecrawl=section) + "\n".join(panel.summary_lines(section))
    for claim in CLAIMS:
        assert claim not in everything, claim
    assert "does not show what a crawler that runs no JavaScript receives" in section["notice"]


# 2 ----------------------------------------------------------------------------------------------------------------
def test_a_capped_reader_sample_with_unread_urls_is_incomplete_not_complete(tmp_path, no_lookups):
    outcome, info, section, report = read(tmp_path, options=Options(read_always=True, max_pages=2))
    cover = section["coverage"]
    assert cover["read"] == 2 and cover["cap_reached"] and cover["known_urls_not_requested"] >= 1 and cover["examples_not_requested"]
    code, word, sentence = run_outcome(outcome.result, outcome.gates, section)
    assert (code, word) == (3, "INCOMPLETE") and sentence.startswith("The audit finished with partial coverage: 2 page(s) were read through Firecrawl")
    assert "more discovered URL(s) remain unchecked (the page cap of 2 was reached)" in sentence and "Findings cover only the pages read" in sentence
    status = report["audit_status"]["content_coverage"]
    assert status["level"] == "partial" and status["known_urls_not_read"] == cover["known_urls_not_requested"] and status["reasons"]
    assert "additional discovered URLs remain unchecked" in status["note"]


def test_a_provider_stop_a_failed_page_and_a_missing_key_page_each_make_the_sample_partial(tmp_path, no_lookups):
    wall = lambda body: httpx.Response(200, json={"success": True, "data": {  # noqa: E731
        "rawHtml": "<html><title>Just a moment...</title><body>Checking your browser</body></html>", "metadata": {"statusCode": 403}}}) \
        if body["url"].endswith("/products") else None
    outcome, info, section, report = read(tmp_path, responder=wall, key_pages=("https://bank.test/pricing",))
    cover = section["coverage"]
    assert cover["requested_without_a_readable_document"] == 1 and cover["answered_with_an_error_status"] >= 1  # the challenge; a 404 is an answer
    assert cover["key_pages_not_read"] == [f"{ROOT}/pricing"]
    code, word, sentence = run_outcome(outcome.result, outcome.gates, section)
    assert (code, word) == (3, "INCOMPLETE") and "1 requested URL(s) gave no readable document" in sentence and "1 key page(s) were not read" in sentence
    assert report["audit_status"]["content_coverage"]["key_pages_not_read"] == [f"{ROOT}/pricing"]
    # A reader stopped by its own limit says so in the outcome.
    stopped = dict(section, stopped_because="the Firecrawl page cap of 2 for this audit is reached. No request was sent.")
    assert run_outcome(outcome.result, outcome.gates, stopped)[1] == "INCOMPLETE"


# 3 ----------------------------------------------------------------------------------------------------------------
def test_pages_read_by_both_are_counted_once_and_who_read_what_is_said(tmp_path, no_lookups):
    partial = {url: html for url, html in SITE.items() if not url.endswith("/products")}
    outcome, info, section, report = read(tmp_path, pages=partial, transport=open_site)
    status = report["audit_status"]
    assert status["direct_access"]["state"] == "readable"
    assert status["content_coverage"]["readable_unique_urls"] == 4 and status["content_coverage"]["read_by"] == {"maya_only": 1, "firecrawl_only": 0, "both": 3, "firecrawl": 3, "total": 4}
    assert status["summary"].startswith("We read 3 page(s) through Firecrawl and 1 with Maya's own crawler.")
    assert run_outcome(outcome.result, outcome.gates, section) == run_outcome(outcome.result, outcome.gates)  # Maya's own crawl decides


# 4 ----------------------------------------------------------------------------------------------------------------
def answer(html, status=200, final=None, **meta):
    data = {"rawHtml": html, "metadata": {**({"statusCode": status} if status is not None else {}), **({"url": final} if final else {}), **meta}}
    return httpx.Response(200, json={"success": True, "data": data})


def test_an_unknown_status_stays_unknown_and_the_document_is_still_read(tmp_path, no_lookups):
    pages = {f"{ROOT}/": doc("Home", "<h1>Home</h1>" + TEXT)}
    outcome, info, section, report = read(tmp_path, pages=pages, responder=lambda body: answer(pages[body["url"]], status=None) if body["url"] in pages else None)
    [row] = [r for r in section["pages"] if r["outcome"] == "read"]
    assert row["status"] is None and row["status_known"] is False and row["observed_at"] and row["from_cache"] is False
    assert section["coverage"]["status_unknown"] == 1 and section["pages_read"] == 1
    page = info["view_pages"][0]
    assert page.status is None and page.view == "provider" and page.readable_document() and "HTTP status not reported by the reader" in page.classification_evidence
    assert next(c for c in outcome.checks if c.check_id == "STR-1").status != "not_assessed"  # HTML-only checks ran on the document
    assert '"status": 200' not in json.dumps(section["pages"])
    # A page with no answer at all is not a readable document.
    from dataclasses import replace
    assert not replace(page, error="timeout").readable_document() and not replace(page, view="raw").readable_document()


def test_redirects_are_recorded_and_another_sites_document_is_never_analysed_as_this_sites(tmp_path, no_lookups):
    home = doc("Home", "<h1>Home</h1>" + TEXT + f'<a href="{ROOT}/old">Old</a> <a href="{ROOT}/away">Away</a> <a href="{ROOT}/login">Login</a>')

    def responder(body):
        url = body["url"]
        if url == f"{ROOT}/":
            return answer(home, final="https://www.bank.test/")              # the www twin of the same address
        if url == f"{ROOT}/old":
            return answer(doc("New page", "<h1>New</h1>" + TEXT), final=f"{ROOT}/new")   # moved within the site
        if url == f"{ROOT}/away":
            return answer(doc("Other company", "<h1>Other</h1>" + TEXT), final="https://other.example/landing")
        if url == f"{ROOT}/login":
            return answer(doc("Sign in", "<h1>Sign in</h1>"), final="http://10.0.0.5/admin")
        return None
    outcome, info, section, report = read(tmp_path, pages={}, responder=responder)
    rows = {(r["url"], r["outcome"]): r for r in section["pages"]}
    alias = rows[(f"{ROOT}/", "read")]
    assert alias["final_url"] == "https://www.bank.test/" and alias["host_alias"] is True
    assert rows[(f"{ROOT}/old", "redirected")]["final_url"] == f"{ROOT}/new" and (f"{ROOT}/new", "read") in rows
    for gone, where in ((f"{ROOT}/away", "https://other.example/landing"), (f"{ROOT}/login", "http://10.0.0.5/admin")):
        row = rows[(gone, "redirected_out_of_scope")]
        assert row["final_url"] == where and "not analysed" in row["reason"]
    read_urls = {page.url for page in info["view_pages"]}
    assert read_urls == {f"{ROOT}/", f"{ROOT}/new"} and section["pages_read"] == 2
    assert "Other company" not in json.dumps([p.analysis["title"] for p in info["view_pages"]]) and "Sign in" not in json.dumps([p.analysis["title"] for p in info["view_pages"]])
    assert section["coverage"]["requested_without_a_readable_document"] == 2 and run_outcome(outcome.result, outcome.gates, section)[1] == "INCOMPLETE"
    assert reader.where_it_landed(f"{ROOT}/a", f"{ROOT}/a/", ROOT) == ("same", None) or reader.where_it_landed(f"{ROOT}/a", f"{ROOT}/a/", ROOT)[0] in ("alias", "same")
    assert reader.where_it_landed(f"{ROOT}/a", "javascript:alert(1)", ROOT) == ("outside", "javascript:")
    assert reader.where_it_landed(f"{ROOT}/a", "https://user:pw@bank.test/a", ROOT) == ("outside", "https://bank.test")  # shown without the credentials


def test_a_stop_or_a_deadline_is_never_a_clean_complete_result(tmp_path, no_lookups):
    outcome, info, section, report = read(tmp_path)
    outcome.result.stopped = True
    assert run_outcome(outcome.result, outcome.gates, section)[1] == "INCOMPLETE" and "stopped on request" in run_outcome(outcome.result, outcome.gates, section)[2]
    outcome.result.stopped = False
    outcome.result.deadline_hit = True
    code, word, sentence = run_outcome(outcome.result, outcome.gates, section)
    assert (code, word) == (3, "INCOMPLETE") and "time limit was reached" in sentence
    assert audit_status(outcome.result, outcome.gates, outcome.checks, section)["content_coverage"]["level"] == "partial"


def test_nothing_read_at_all_is_degraded_with_no_coverage(tmp_path, no_lookups):
    outcome, info, section, report = read(tmp_path, pages={})
    assert not section["used"] and run_outcome(outcome.result, outcome.gates, section)[1] == "DEGRADED"
    status = report["audit_status"]
    assert status["content_coverage"]["level"] == "none" and status["content_coverage"]["readable_unique_urls"] == 0
    assert status["summary"].startswith("No page content was read.") and status["direct_access"]["state"] == "challenged"


# 5 ----------------------------------------------------------------------------------------------------------------
def test_an_identity_or_safety_violation_still_degrades_an_audit_a_reader_read(tmp_path, no_lookups):
    outcome, info, section, report = read(tmp_path)
    gates = [g if g.check_id != "INT-4" else GateResult(**{**g.__dict__, "state": "violation", "summary": "a request left the audited site"}) for g in outcome.gates]
    code, word, sentence = run_outcome(outcome.result, gates, section)
    assert (code, word) == (1, "DEGRADED") and "INT-4" in sentence and "INT-1" not in sentence


# 6 and 7 ----------------------------------------------------------------------------------------------------------
def test_privacy_prose_is_not_a_placeholder_and_real_template_slots_still_are():
    from maya_audit.checks.structure import placeholder_hits
    assert not placeholder_hits(["This may include your company name and job title."])
    assert placeholder_hits(["Welcome to [your company name]."]) and placeholder_hits(["Lorem ipsum dolor sit amet."])


def test_check_ids_sort_naturally_and_priority_order_is_a_separate_list(tmp_path, no_lookups):
    assert sorted(["ACC-10", "ACC-2", "STR-10", "STR-9", "ACC-1"], key=check_id_key) == ["ACC-1", "ACC-2", "ACC-10", "STR-9", "STR-10"]
    outcome, info, section, report = read(tmp_path)
    assert section["checks_from_firecrawl"] == sorted(section["checks_from_firecrawl"], key=check_id_key)
    order = report["findings_in_priority_order"]
    severities = {f["id"]: f["severity"] for c in report["checks"] for f in c["findings"]}
    ranks = [("S1", "S2", "S3", "S4", "Info").index(severities[i]) for i in order]
    assert ranks == sorted(ranks) and order != sorted(order)  # by harm, not by name


def test_a_limited_probe_and_server_logs_are_named_as_what_they_are():
    from types import SimpleNamespace
    from maya_audit.models import StopReason
    result = SimpleNamespace(pages=[], not_fetched_urls=[], discovered_urls=[], stop_reason=StopReason.EXHAUSTED, stop_detail="", stopped=False, deadline_hit=False)
    probe = audit_status(result, [], [SimpleNamespace(check_id="ACC-4", status="pass"), SimpleNamespace(check_id="ACC-5", status="not_assessed")])
    assert probe["vendor_crawler_evidence"]["state"] == "limited_user_agent_probe"
    assert "from Maya's own network" in probe["vendor_crawler_evidence"]["note"] and "not proof of a crawler's identity" in probe["vendor_crawler_evidence"]["note"]
    logs = audit_status(result, [], [SimpleNamespace(check_id="ACC-4", status="pass"), SimpleNamespace(check_id="ACC-5", status="observed")])
    assert logs["vendor_crawler_evidence"]["state"] == "verified_log_evidence" and probe["direct_access"]["state"] == "unknown"
