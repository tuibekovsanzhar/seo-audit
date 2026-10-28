"""ANS-1..ANS-3: the answer-engine panel, against a local site and local citation records."""

import json

import pytest

from fakeserver import FakeServer
from fakeserver.ans_scenarios import ANS_SCENARIOS, FAST_ANS, citation_records, empty_records, write_citations
from maya_audit.ans_data import load_citations
from maya_audit.audit import run_audit
from maya_audit.config import CrawlConfig
from maya_audit.report import build_report


def run_ans(tmp_path, records="default", **overrides):
    scenario = ANS_SCENARIOS["ans_cited_pages"]
    with FakeServer(scenario.build()) as site:
        if records == "default":
            citations = write_citations(str(tmp_path), site.base_url)
        elif records is None:
            citations = None
        else:
            citations = write_citations(str(tmp_path), site.base_url, records)
        config = CrawlConfig(**{**FAST_ANS, **overrides}, citations_file=citations)
        outcome = run_audit(site.base_url + "/", config)
        return outcome, list(site.requests), site.base_url, config


def checks(outcome):
    return {c.check_id: c for c in outcome.checks}


def entries(check):
    return {f.scope["urls"][0].split("//", 1)[1].split("/", 1)[1] or "/": f for f in check.findings}


@pytest.fixture(scope="module")
def cited(tmp_path_factory):
    return run_ans(tmp_path_factory.mktemp("ans"))


def test_panel_lists_every_failing_cited_url_with_the_site_checks_severity(cited):
    outcome, requests, base, _ = cited
    ans1 = checks(outcome)["ANS-1"]
    rows = entries(ans1)
    assert set(rows) == {"guides/ai-visibility", "internal/private", "noindex-page", "app", "removed",
                         "cited-canonical-other", "moved-broken"}
    severities = {url: f.severity.value for url, f in rows.items()}
    assert severities == {"guides/ai-visibility": "S1", "internal/private": "S1", "noindex-page": "Info",
                          "app": "S3", "removed": "Info", "cited-canonical-other": "S3", "moved-broken": "S2"}
    # A redirect or canonical is followed to where it lands, and judged there (ANS-1 v2).
    handed = {h["url"].rsplit("/", 1)[-1]: h for h in ans1.evidence["consolidated_cited_urls"]}
    assert handed["old-post"]["kind"] == "redirect" and handed["old-post"]["final_url"].endswith("/new-post")
    assert handed["cited-canonical"]["comparison"] == "identical visible text (hash)"
    assert handed["cited-canonical"]["confidence"] == "verified"
    other = rows["cited-canonical-other"]
    assert other.evidence["site_view"]["failures"] == ["canonicalized_to_different_content"]
    assert other.confidence.value == "estimated"  # a similarity estimate, like IDX-4
    broken = rows["moved-broken"].evidence["site_view"]
    assert broken["failures"] == ["redirect_target_broken"] and broken["handoff"]["final_status"] == 404
    assert "hand their citation to a live page" in ans1.summary
    healthy = next(h for h in ans1.evidence["healthy_cited_urls"] if h["url"].endswith("/pricing"))
    assert healthy["checks_applied"]["edge_blocking_acc4"].startswith("not checked")
    # Severity is copied from the check that reports the failure, not from any finding naming the same URL.
    assert [f["check_id"] for f in rows["noindex-page"].evidence["site_findings"]] == ["ACC-3"]
    assert [f["check_id"] for f in rows["app"].evidence["site_findings"]] == ["RND-1"]
    assert any(f["check_id"] == "STR-10" for f in rows["app"].evidence["other_site_findings_for_this_url"])
    assert rows["guides/ai-visibility"].evidence["site_view"]["failures"] == ["robots_disallowed_search"]
    # A 404 that nothing links to is Info under IDX-1 and still appears in the panel (spec example).
    assert "not part of the crawl" in " ".join(rows["removed"].notes)
    assert rows["removed"].evidence["site_view"]["source"] == "ans_fetch"
    assert all(f.cost_tier == "T4+T0" for f in ans1.findings)
    assert all(f.confidence.value == "verified" for f in ans1.findings if f is not other)
    assert all("Estimated observation" in " ".join(f.notes) for f in ans1.findings)


def test_panel_order_is_failure_type_then_most_recent_citation(cited):
    outcome, _, _, _ = cited
    order = [f.evidence["site_view"]["failures"][0] for f in checks(outcome)["ANS-1"].findings]
    assert order == ["robots_disallowed_search", "robots_disallowed_search", "noindex", "not_found",
                     "redirect_target_broken", "canonicalized_to_different_content", "content_missing_from_raw_html"]
    first, second = checks(outcome)["ANS-1"].findings[:2]
    assert first.evidence["cited_by"][0]["most_recent_cited_at"] > second.evidence["cited_by"][0]["most_recent_cited_at"]


def test_maya_record_shape_is_read(cited):
    """The shape checked against Maya's live citation API on 2026-09-16."""
    outcome, requests, base, _ = cited
    ans1 = checks(outcome)["ANS-1"]
    maya = next(r for r in outcome.result.citations.records if r["scheme_assumed"])
    assert maya["engine"] == "chatgpt"  # no "engine" field: the provider comes from "model"
    assert maya["scheme_assumed"] and maya["url_as_supplied"].startswith("127.0.0.1")
    assert "utm_source" not in maya["url"] and maya["url"] == base + "/healthy"  # tracking query stripped
    assert maya["cited_at"] == "2026-09-15T20:10:19.085Z"  # "citedAt", not "cited_at"
    assert maya["prompt"] == "promptId 00000000-0000-4000-8000-000000000000" and maya["answer_excerpt"] is None
    assert not outcome.result.citations.off_site or all(
        "127.0.0.1" not in r["url"] for r in outcome.result.citations.off_site)  # it matched the audited site
    healthy = {h["url"] for h in ans1.evidence["healthy_cited_urls"]}
    assert base + "/healthy" in healthy  # the record joined the crawled page, not a second fetch
    # No extra fetch for the citation, and no request ever carried the engine's tracking query.
    assert not [r for r in outcome.result.requests if r.purpose == "ans_cited_url" and "/healthy" in r.url]
    assert not [r for r in requests if "utm_source" in r.path]


def test_per_engine_evidence_and_freshness(cited):
    outcome, _, base, _ = cited
    ans1 = checks(outcome)["ANS-1"]
    assert ans1.evidence["citations_per_engine"] == {"chatgpt": 7, "gemini": 3, "perplexity": 5}
    assert "not shown" in ans1.evidence["cross_engine_totals"]
    assert ans1.evidence["sample_size"] == {"prompts": 120, "answers": 340}
    assert "fetched 2026-09-15T09:00:00Z" in ans1.summary and "refresh: daily" in ans1.summary
    healthy = {h["url"].rsplit("/", 1)[-1] or "/" for h in ans1.evidence["healthy_cited_urls"]}
    assert ans1.evidence["citations_per_engine"]["chatgpt"] == 7
    assert healthy == {"pricing", "about", "healthy"}
    assert [u["url"] for u in ans1.evidence["cited_urls_not_on_this_site"]] == ["https://news.example.com/acme-raises"]
    assert len(ans1.evidence["invalid_records"]) == 2
    entry = entries(ans1)["noindex-page"].evidence["cited_by"][0]
    assert entry == {"engine": "chatgpt", "citations": 1, "most_recent_cited_at": "2026-09-09T10:00:00Z",
                     "models": ["gpt-5"], "sample": [{"cited_at": "2026-09-09T10:00:00Z", "model": "gpt-5",
                                                      "prompt": "acme internals"}]}


def test_nothing_is_fetched_outside_the_site(cited):
    outcome, requests, base, _ = cited
    hosts = {r.url.split("//", 1)[1].split("/", 1)[0] for r in outcome.result.requests}
    assert hosts == {base.split("//", 1)[1]}  # the off-site cited URL was never requested
    assert [r.path for r in requests if r.path.startswith("/internal/")] == []  # robots.txt disallows it
    assert [r.path for r in requests].count("/removed") == 1  # the uncrawled cited URL, fetched once
    blocked = entries(checks(outcome)["ANS-1"])["internal/private"].evidence["site_view"]
    assert blocked["source"] == "not_fetched" and "robots.txt disallows" in blocked["reason"]


def test_stale_facts(cited):
    outcome, _, base, _ = cited
    ans2 = checks(outcome)["ANS-2"]
    # Estimated price comparisons keep all conflicts, with the owner's Medium ceiling.
    price = next(f for f in ans2.findings if any(r.get('claim_value') == '39' for r in f.evidence['conflicts']))
    fact = next(f for f in ans2.findings if any(r.get('claim_value') == '2010' for r in f.evidence['conflicts']))
    assert price.severity.value == fact.severity.value == "S3"
    assert price.rationale == "Self-evident harm" and price.confidence.value == "estimated"
    assert "Hypothesis" in " ".join(price.notes)  # the fix, not the finding, is the hypothesis
    rows = {r["answer_says"]: r for r in price.evidence["conflicts"]}
    assert set(rows) == {"The Pro plan costs $39/mo", "$29"}
    stale = rows["The Pro plan costs $39/mo"]
    assert stale["engine"] == "chatgpt" and stale["claim_value"] == "39"
    assert stale["answer_sentence"] == "The Pro plan costs $39/mo and includes 10 seats."
    assert stale["page_sentence"] == "The Pro plan costs $49/mo."  # side by side, as the spec asks
    assert sorted(stale["page_shows"]) == ["$49", "$9"]
    assert rows["$29"]["derived_by_maya"] is True  # no claims supplied: read from the answer with the T0 tokenizer
    assert not stale["derived_by_maya"]
    # The matching $49 claim is not a conflict.
    assert all("49" != r["claim_value"] for f in ans2.findings for r in f.evidence["conflicts"])
    facts = {r["claim_value"]: r for r in fact.evidence["conflicts"]}
    assert set(facts) == {"2010", "45"}
    # The page's own sentence is quoted beside the answer's, and the comparison method is named.
    assert facts["2010"]["page_sentence"] == "Acme was founded in 2012 in Berlin."
    assert facts["2010"]["page_value"] == ["2012"] and "(T0)" in facts["2010"]["comparison_mode"]
    assert facts["45"]["comparison_mode"].startswith("supplied upstream (llm (upstream))")
    assert stale["comparison_mode"].startswith("price in the page sentence")
    # Absent is not a contradiction: a review item without severity.
    [absent] = ans2.review_items
    assert [c["claim_value"] for c in absent.evidence["claims"]] == ["free trial"]
    assert ans2.evidence["verdicts"] == {"contradicted": 4, "absent": 1, "matches": 2}
    assert ans2.evidence["claims_derived_by_maya_because_none_were_supplied"] == 1
    assert "not built here" in ans2.evidence["llm_claim_extraction"]


def test_ans3_is_cut(cited):
    outcome, _, _, _ = cited
    ans3 = checks(outcome)["ANS-3"]
    assert ans3.status == "not_assessed" and "Cut from v1" in ans3.summary


def test_panel_never_changes_the_site_checks(cited):
    outcome, _, _, config = cited
    from maya_audit.checks.access import run_access_checks
    from maya_audit.checks.index import run_index_checks
    from maya_audit.checks.perf import run_perf_checks
    from maya_audit.checks.render import run_render_checks
    from maya_audit.checks.structure import run_structure_checks

    def summarize(check_list):
        return sorted((f.check_id, f.title, f.severity.value, f.confidence.value, tuple(sorted(f.scope["urls"])))
                      for c in check_list for f in c.findings)

    # Re-run the site checks from the same crawl: fresh objects the panel has never touched.
    render = run_render_checks(outcome.result, config)
    fresh = (run_access_checks(outcome.result, config) + run_index_checks(outcome.result, config) + render
             + run_structure_checks(outcome.result, config, render) + run_perf_checks(outcome.result, config))
    from maya_audit.severity import apply as apply_severity
    apply_severity(fresh, outcome.result)  # compare the same final owner policy, not raw constructor impact
    after_panel = [c for c in outcome.checks if not c.check_id.startswith("ANS")]
    assert summarize(after_panel) == summarize(fresh)
    assert [c.status for c in after_panel] == [c.status for c in fresh]
    report = build_report(outcome.result, outcome.gates, outcome.checks)
    assert [c["check_id"] for c in report["answer_engine_panel"]] == ["ANS-1", "ANS-2", "ANS-3", "ANS-4", "ANS-5"]
    assert not any(c["check_id"].startswith("ANS") for c in report["checks"])
    assert not any(fid.startswith("ANS") for fid in report["findings_in_priority_order"])


def test_no_data_is_not_zero(tmp_path):
    none, _, _, _ = run_ans(tmp_path, records=None)
    zero, _, _, _ = run_ans(tmp_path, records=empty_records())
    assert checks(none)["ANS-1"].status == "not_assessed" and "no citation data" in checks(none)["ANS-1"].summary
    # Zero is a count, not a pass: nothing was there to judge (report 0.4 "observed").
    assert checks(zero)["ANS-1"].status == "observed" and "Zero cited URLs" in checks(zero)["ANS-1"].summary
    assert checks(zero)["ANS-2"].status == "not_assessed"


def test_cited_url_fetch_cap(tmp_path):
    outcome, requests, base, _ = run_ans(tmp_path, ans_max_fetches=0)
    ans1 = checks(outcome)["ANS-1"]
    # A cited URL Maya never fetched is not a failing page: it is a part of the question left unanswered.
    assert base + "/removed" not in {f.evidence["site_view"]["url"] for f in ans1.findings}
    unchecked = {r["url"]: r for r in ans1.evidence["cited_urls_not_checked"]}
    assert "cap of 0 reached" in unchecked[base + "/removed"]["reason"]
    assert any(g["part"] == "cited URLs the crawl did not cover" for g in ans1.coverage["not_assessed"])
    assert "/removed" not in [r.path for r in requests]


def test_real_world_url_shapes(tmp_path):
    """URL shapes taken from Maya's live citation data for a client project (2026-09-16)."""
    records = {"source": "maya prompt tracking", "records": [
        # Records name the bare domain; the same site is crawled as www. Without aligning the two,
        # every cited URL looks like another site's and the panel silently reports zero.
        {"domain": "enpara.com", "url": "enpara.com/ucretler?utm_source=chatgpt.com", "model": "chatgpt",
         "citedAt": "2026-09-15T22:35:46Z"},
        # Gemini and Google AI Overview attach Chrome text fragments.
        {"domain": "enpara.com", "url": "enpara.com/bilgi-bankasi/masrafsiz-bankacilik#:~:text=hesap%20i%C5%9Fletim",
         "model": "gemini", "citedAt": "2026-09-16T01:51:20Z"},
        # A genuinely different site must stay off-site.
        {"domain": "akbank.com", "url": "https://www.akbank.com/urun-ve-hizmet-ucretleri", "model": "chatgpt",
         "citedAt": "2026-09-15T00:00:00Z"}]}
    path = tmp_path / "citations.json"
    path.write_text(json.dumps(records), encoding="utf-8")
    data = load_citations(str(path), "https://www.enpara.com")

    assert [r["url"] for r in data.records] == [
        "https://www.enpara.com/ucretler",
        "https://www.enpara.com/bilgi-bankasi/masrafsiz-bankacilik"]  # utm and #:~:text= both gone
    assert all(r["host_aligned_to_site"] and r["scheme_assumed"] for r in data.records)
    assert [r["url"] for r in data.off_site] == ["https://www.akbank.com/urun-ve-hizmet-ucretleri"]
    assert data.records[0]["url_as_supplied"] == "enpara.com/ucretler?utm_source=chatgpt.com"


def test_broken_citation_file_is_reported_not_crashed(tmp_path):
    path = tmp_path / "citations.json"
    path.write_text("{not json", encoding="utf-8")
    data = load_citations(str(path), "http://example.com")
    assert not data.loaded and "JSONDecodeError" in data.error
    data = load_citations(str(tmp_path / "missing.json"), "http://example.com")
    assert not data.loaded and "FileNotFoundError" in data.error
    (tmp_path / "wrong.json").write_text(json.dumps({"records": "nope"}), encoding="utf-8")
    data = load_citations(str(tmp_path / "wrong.json"), "http://example.com")
    assert not data.loaded and "records" in data.error


def test_record_validation():
    records = citation_records("http://site.test")
    records["records"].append({"engine": "x", "url": "http://site.test/a", "claims": ["not an object"]})
    data = load_citations_from(records, "http://site.test")
    assert len(data.records) == 16 and len(data.off_site) == 1
    reasons = [r["reason"] for r in data.invalid_records]
    assert "missing or non-string: url" in reasons[0] and "not a usable URL" in reasons[1]
    assert "1 claim(s) dropped" in reasons[2]


def load_citations_from(records, origin, tmp=None):
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        path = write_citations(directory, origin, records)
        return load_citations(path, origin)


def test_answer_panel_references_final_site_priorities_not_raw_constructor_severity(cited):
    outcome, _, _, _ = cited
    site = {f.id: f for c in outcome.checks if not c.check_id.startswith('ANS') for f in c.findings}
    references = [r for f in checks(outcome)['ANS-1'].findings for r in f.evidence.get('site_findings', [])]
    assert references
    for r in references:
        assert r['severity'] == site[r['finding_id']].severity.value
