"""ANS-4/ANS-5: the cited-domain panel, against a local site and a local export.

The rules worth protecting here are about what the checks refuse to say:

* no data is not zero citations, and a missing site row is not "absent from AI answers";
* a truncated export never yields a per-engine share, because the denominator would be wrong;
* nothing in the output is ever called Share of Voice, which is a different Maya metric;
* no third-party domain named in the export is ever fetched.
"""

import json

import pytest

from fakeserver import FakeServer
from fakeserver.ans_scenarios import ANS_SCENARIOS, FAST_ANS, domain_rows, write_citations, write_domain_rows
from maya_audit.ans_domains import classify_domain, load_citation_domains
from maya_audit.audit import run_audit
from maya_audit.config import CrawlConfig
from maya_audit.report import build_report


def run_domains(tmp_path, rows="default", **overrides):
    scenario = ANS_SCENARIOS["ans_cited_pages"]
    with FakeServer(scenario.build()) as site:
        citations = write_citations(str(tmp_path), site.base_url)
        if rows == "default":
            path = write_domain_rows(str(tmp_path), site.base_url)
        elif rows is None:
            path = None
        else:
            path = write_domain_rows(str(tmp_path), site.base_url, rows)
        config = CrawlConfig(**{**FAST_ANS, **overrides}, citations_file=citations, citation_domains_file=path)
        outcome = run_audit(site.base_url + "/", config)
        return outcome, list(site.requests), site.base_url


def checks(outcome):
    return {c.check_id: c for c in outcome.checks}


@pytest.fixture(scope="module")
def loaded(tmp_path_factory):
    return run_domains(tmp_path_factory.mktemp("ansdom"))


def test_both_checks_report_not_assessed_without_the_export(tmp_path):
    outcome, _, _ = run_domains(tmp_path, rows=None)
    for check_id in ("ANS-4", "ANS-5"):
        result = checks(outcome)[check_id]
        assert result.status == "not_assessed"
        assert "no data" in result.summary and "not" in result.summary
        assert not result.findings


def test_unreadable_export_is_not_assessed_and_names_the_error(tmp_path):
    bad = tmp_path / "citation-domains.json"
    bad.write_text("{not json", encoding="utf-8")
    scenario = ANS_SCENARIOS["ans_cited_pages"]
    with FakeServer(scenario.build()) as site:
        config = CrawlConfig(**FAST_ANS, citation_domains_file=str(bad))
        outcome = run_audit(site.base_url + "/", config)
    for check_id in ("ANS-4", "ANS-5"):
        result = checks(outcome)[check_id]
        assert result.status == "not_assessed"
        assert result.evidence["error"]


def test_export_without_this_site_is_not_assessed_not_zero(tmp_path):
    """A truncated export can omit the site. That must never read as "no engine cites you"."""
    rows = domain_rows("http://absent.example")
    # Drop the site's own row, as a truncated export legitimately can.
    rows["domains"] = [row for row in rows["domains"] if row["domain"] != "absent.example"]
    outcome, _, _ = run_domains(tmp_path, rows=rows)
    result = checks(outcome)["ANS-4"]
    assert result.status == "not_assessed"
    assert "truncated export can omit the site" in result.summary
    assert not result.findings


def test_site_engine_counts_and_total_share(loaded):
    outcome, _, base = loaded
    ans4 = checks(outcome)["ANS-4"]
    counts = {o["engine"]: o["citations_of_this_site"] for o in ans4.observations}
    assert counts == {"chatgpt": 40, "perplexity": 60}
    # The site's own split is exact: it comes from its own row, not from a truncated denominator.
    shares = {o["engine"]: o["share_of_this_site's_citations"] for o in ans4.observations}
    assert shares == {"chatgpt": 40.0, "perplexity": 60.0}
    # 100 of 1000 total mentions, and totalMentions covers every domain, not just the listed rows.
    assert ans4.evidence["share_of_all_cited_domain_mentions_pct"] == 10.0


def test_truncated_export_refuses_a_per_engine_share(loaded):
    outcome, _, _ = loaded
    ans4 = checks(outcome)["ANS-4"]
    assert ans4.evidence["export_truncated"] is True
    for observation in ans4.observations:
        assert observation["share_of_engine's_cited_domains"] is None
        assert "would overstate this site" in observation["why_no_share"]


def test_complete_export_does_compute_a_per_engine_share(tmp_path):
    rows = domain_rows("http://placeholder", truncated=False)
    with FakeServer(ANS_SCENARIOS["ans_cited_pages"].build()) as site:
        rows["project"]["domain"] = site.base_url.split("//", 1)[1]
        rows["domains"][0]["domain"] = site.base_url.split("//", 1)[1]
        path = write_domain_rows(str(tmp_path), site.base_url, rows)
        config = CrawlConfig(**FAST_ANS, citation_domains_file=path)
        outcome = run_audit(site.base_url + "/", config)
    ans4 = checks(outcome)["ANS-4"]
    assert ans4.evidence["export_truncated"] is False
    shares = {o["engine"]: o["share_of_engine's_cited_domains"] for o in ans4.observations}
    # chatgpt: site 40 of (40 + 90 + 120 + 30) = 280 listed chatgpt mentions.
    assert shares["chatgpt"] == round(40 / 280 * 100, 1)
    assert shares["perplexity"] == round(60 / 200 * 100, 1)


def test_engine_that_cites_the_topic_but_never_this_site_is_info_only(tmp_path):
    rows = domain_rows("http://placeholder", site_engines={"perplexity": 60})
    with FakeServer(ANS_SCENARIOS["ans_cited_pages"].build()) as site:
        host = site.base_url.split("//", 1)[1]
        rows["project"]["domain"] = host
        rows["domains"][0]["domain"] = host
        path = write_domain_rows(str(tmp_path), site.base_url, rows)
        outcome = run_audit(site.base_url + "/", CrawlConfig(**FAST_ANS, citation_domains_file=path))
    ans4 = checks(outcome)["ANS-4"]
    gaps = [f for f in ans4.findings if f.evidence["engine"] == "chatgpt"]
    assert len(gaps) == 1
    finding = gaps[0]
    # An absence with many possible causes is a Hypothesis, and never more than Info.
    assert finding.severity.value == "Info"
    assert finding.rationale.value == "Hypothesis"
    assert finding.confidence.value == "estimated"
    assert finding.evidence["engine_mentions_in_export"] == 240  # 90 rival + 120 openai + 30 instagram
    assert "somewhere to look, not as a defect" in finding.how_to_fix


def test_no_output_anywhere_calls_this_share_of_voice(loaded):
    """Maya's product already has a Share of Voice that counts something else. Never collide with it."""
    outcome, _, _ = loaded
    report = json.dumps(build_report(outcome.result, outcome.gates, outcome.checks), ensure_ascii=False)
    for result in [c for c in outcome.checks if c.check_id in ("ANS-4", "ANS-5")]:
        # No metric may be *named* share of voice: not a field, not an observation key.
        keys = ({k.casefold() for k in result.evidence}
                | {k.casefold() for o in result.observations for k in o}) - {"not_share_of_voice"}
        assert not [k for k in keys if "share_of_voice" in k or k == "sov" or k.endswith("_sov")]
        # The phrase may appear only inside the field that exists to disown it.
        elsewhere = json.dumps({k: v for k, v in result.evidence.items() if k != "not_share_of_voice"},
                               ensure_ascii=False, default=str).casefold()
        assert "share of voice" not in elsewhere
        assert result.summary.casefold().find("share of voice") == -1
        # Every check carrying one of these numbers must also carry the disclaimer.
        assert "not Maya's Share of Voice" in result.evidence["not_share_of_voice"]
    # And the disclaimer is actually carried into the report, not just the object.
    assert "not Maya's Share of Voice" in report


def test_no_third_party_domain_is_ever_fetched(loaded):
    """The export names rival.example, instagram.com and an OpenAI CDN. None may be requested."""
    outcome, _, base = loaded
    hosts = {r.url.split("//", 1)[1].split("/", 1)[0] for r in outcome.result.requests}
    assert hosts == {base.split("//", 1)[1]}


def test_domains_are_classified_and_the_list_is_marked_unvalidated(loaded):
    outcome, _, base = loaded
    ans5 = checks(outcome)["ANS-5"]
    by_class = {o["class"]: o for o in ans5.observations}
    assert by_class["site"]["domains"] == 1
    assert by_class["infrastructure"]["top"][0]["domain"] == "images.openai.com"
    assert by_class["reference"]["top"][0]["domain"] == "en.wikipedia.org"
    assert by_class["directory"]["top"][0]["domain"] == "instagram.com"
    assert by_class["other"]["top"][0]["domain"] == "rival.example"
    assert "LG-29" in ans5.evidence["classification_is_unvalidated"]


def test_a_commercial_domain_cited_more_than_the_site_is_named(tmp_path):
    rows = domain_rows("http://placeholder", site_engines={"chatgpt": 5})
    with FakeServer(ANS_SCENARIOS["ans_cited_pages"].build()) as site:
        host = site.base_url.split("//", 1)[1]
        rows["project"]["domain"] = host
        rows["domains"][0]["domain"] = host
        path = write_domain_rows(str(tmp_path), site.base_url, rows)
        outcome = run_audit(site.base_url + "/", CrawlConfig(**FAST_ANS, citation_domains_file=path))
    ans5 = checks(outcome)["ANS-5"]
    ahead = [row["domain"] for row in ans5.evidence["commercial_domains_cited_more_than_this_site"]]
    # rival.example (150) is ahead of the site (5); the image CDN and Wikipedia are not competitors.
    assert ahead == ["rival.example"]


def test_the_panel_never_changes_a_site_check(loaded):
    outcome, _, _ = loaded
    for check in outcome.checks:
        if check.check_id.startswith("ANS-"):
            continue
        for finding in check.findings:
            assert not finding.check_id.startswith("ANS-")


@pytest.mark.parametrize("domain,expected", [
    ("images.openai.com", "infrastructure"),
    ("lh3.googleusercontent.com", "infrastructure"),
    ("tr.wikipedia.org", "reference"),
    ("pmc.ncbi.nlm.nih.gov", "reference"),      # nih.gov is reference, checked before the .gov rule
    ("alo191.saglik.gov.tr", "public"),
    ("instagram.com", "directory"),
    ("npistanbul.com", "other"),
    ("web.com", "other"),                        # a "www." strip by character would make this "eb.com"
])
def test_domain_classification(domain, expected):
    assert classify_domain(domain, "moodisthastanesi.com") == expected


def test_the_site_is_recognised_across_www_and_subdomains(tmp_path):
    """"www.web.com" is the case that separates a real prefix strip from `lstrip("www.")`.

    A character-wise strip turns it into "eb.com", so the site's own rows stop matching and the
    check reports "not assessed" on a site that is in fact cited.
    """
    export = {"project": {"domain": "www.web.com"}, "page": {"returned": 2, "total": 2},
              "totalMentions": 10, "domains": [{"domain": "blog.web.com", "mentions": 6, "byModel": {"chatgpt": 6}},
                                               {"domain": "rival.example", "mentions": 4, "byModel": {"chatgpt": 4}}]}
    path = tmp_path / "d.json"
    path.write_text(json.dumps(export), encoding="utf-8")
    data = load_citation_domains(str(path), "https://www.web.com")
    assert data.site_domain == "web.com"
    assert data.site_row()["domain"] == "blog.web.com"


def test_rows_missing_mentions_are_recorded_not_silently_dropped(tmp_path):
    export = {"project": {"domain": "example.com"}, "page": {"returned": 2, "total": 2}, "totalMentions": 10,
              "domains": [{"domain": "example.com", "mentions": 6, "byModel": {"chatgpt": 6}},
                          {"domain": "broken.example"}]}
    path = tmp_path / "d.json"
    path.write_text(json.dumps(export), encoding="utf-8")
    data = load_citation_domains(str(path), "https://example.com")
    assert data.rows_returned == 1
    assert data.invalid_rows[0]["reason"].startswith("missing or non-integer 'mentions'")


# -- accepting Maya's exports as they come back -------------------------------

MAYA_EXAMPLES_PAYLOAD = {
    "project": {"id": "b0a4fe41", "name": "Özel Moodist Hastanesi"},
    "period": {"sinceDays": 30, "since": "2026-08-23T04:36:07.504Z"},
    "page": {"limit": 2, "offset": 0, "returned": 2, "total": 314846, "hasMore": True},
    "filter": {"domain": None, "sourceType": None, "model": None, "kind": None},
    "examples": [
        {"domain": "example.com", "url": "example.com/a", "model": "chatgpt",
         "promptId": "c5ee2b54", "citedAt": "2026-09-17T03:56:27.091Z"},
    ],
}


def test_maya_citation_examples_payload_loads_without_rewrapping(tmp_path):
    """`get_citation_examples` returns its rows under "examples", not "records".

    Requiring "records" meant every operator rewrapped the export by hand before passing it, which
    is a step that can be got wrong — and was, three times, while producing the reports in
    examples/live-runs/.
    """
    from maya_audit.ans_data import load_citations
    path = tmp_path / "raw.json"
    path.write_text(json.dumps(MAYA_EXAMPLES_PAYLOAD), encoding="utf-8")
    data = load_citations(str(path), "https://example.com")
    assert data.loaded and data.error is None
    assert len(data.records) == 1
    assert data.records[0]["url"] == "https://example.com/a"   # scheme added, as the loader always did
    assert data.engines == ["chatgpt"]


def test_the_payload_supplies_its_own_provenance(tmp_path):
    """A hand-written file names its source; a raw export has to have one derived, not invented."""
    from maya_audit.ans_data import load_citations
    path = tmp_path / "raw.json"
    path.write_text(json.dumps(MAYA_EXAMPLES_PAYLOAD), encoding="utf-8")
    data = load_citations(str(path), "https://example.com")
    assert "get_citation_examples" in data.source
    # The window start is labelled as a window, not passed off as a fetch time.
    assert data.fetched_at.startswith("covering ")
    assert data.sample == {"returned": 2, "total": 314846, "hasMore": True}


def test_a_hand_written_records_file_still_loads(tmp_path):
    """The old shape must keep working: examples/live-runs/ ships three files that use it."""
    from maya_audit.ans_data import load_citations
    path = tmp_path / "hand.json"
    path.write_text(json.dumps({"source": "maya prompt tracking", "fetched_at": "2026-09-15T09:00:00Z",
                                "refresh_cadence": "daily",
                                "records": MAYA_EXAMPLES_PAYLOAD["examples"]}), encoding="utf-8")
    data = load_citations(str(path), "https://example.com")
    assert data.loaded and len(data.records) == 1
    assert data.source == "maya prompt tracking"


def test_neither_key_present_is_a_clear_error(tmp_path):
    from maya_audit.ans_data import load_citations
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"project": {"name": "x"}}), encoding="utf-8")
    data = load_citations(str(path), "https://example.com")
    assert not data.loaded
    assert "'records' or 'examples'" in data.error
