"""The reasoning frameworks, and how `report.py` pairs them with a finished audit.

What is worth protecting here is not the wording of a prompt. It is that a brief cannot quietly
lose the evidence model: a skill without its data must not render, the rules must travel with the
payload, and the evidence report must stay free of prompt text.
"""

import json

import pytest

from fakeserver import FakeServer
from fakeserver.ans_scenarios import ANS_SCENARIOS, FAST_ANS, write_citations, write_domain_rows
from maya_audit.ai_skills import SKILLS, AUDIT_REPORT, CITED_DOMAIN_LANDSCAPE, skill_names
from maya_audit.audit import run_audit
from maya_audit.config import CrawlConfig
from maya_audit.report import analysis_payload, build_llm_brief, build_report


@pytest.fixture(scope="module")
def audited(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("skills")
    with FakeServer(ANS_SCENARIOS["ans_cited_pages"].build()) as site:
        config = CrawlConfig(**FAST_ANS, citations_file=write_citations(str(tmp), site.base_url),
                             citation_domains_file=write_domain_rows(str(tmp), site.base_url))
        outcome = run_audit(site.base_url + "/", config)
    report = build_report(outcome.result, outcome.gates, outcome.checks)
    return report, outcome.result


def briefs_by_name(brief):
    return {s["skill_name"]: s for s in brief["skills"]}


def test_every_skill_renders_against_a_real_audit(audited):
    report, result = audited
    brief = build_llm_brief(report, result)
    assert set(briefs_by_name(brief)) == set(skill_names())
    for name, entry in briefs_by_name(brief).items():
        assert entry["prompt"], f"{name} did not render: missing {entry['missing']}"
        assert entry["goal"]


def test_the_brief_carries_the_audit_once_and_the_prompts_point_at_it(audited):
    report, result = audited
    brief = build_llm_brief(report, result)
    assert brief["audit"]["checks"], "the payload must travel with the brief"
    for entry in brief["skills"]:
        assert "supplied alongside this prompt" in entry["prompt"]
    # One copy, not one per skill: four inlined copies of a real report is 20+ MB.
    for entry in brief["skills"]:
        assert '"check_id"' not in entry["prompt"], f"{entry['skill_name']} inlined the audit"


def test_inline_mode_renders_a_self_contained_prompt(audited):
    report, result = audited
    brief = build_llm_brief(report, result, skills=["audit-report"], inline=True)
    prompt = brief["skills"][0]["prompt"]
    assert '"check_id": "ANS-1"' in prompt
    assert json.dumps(report["gates"][0]["evidence"]["pages_fetched"]) in prompt
    assert brief["audit"] is None  # it is in the prompt instead, so it is not stored twice


def test_the_payload_drops_the_raw_crawl_but_keeps_the_method_detail(audited):
    report, result = audited
    payload = build_llm_brief(report, result)["audit"]
    assert "crawl" not in payload
    summary = payload["crawl_summary"]
    # The report's Method section is written from these.
    for key in ("origin", "user_agent", "elapsed_s", "stop_reason"):
        assert key in summary
    assert "omitted" in summary
    assert len(json.dumps(payload)) < len(json.dumps(report))


def test_the_payload_stays_small_when_the_crawl_is_large(audited):
    """The saving is the point: a real 50-page report is 5.3 MB, of which 5.17 MB is `crawl`."""
    report, _ = audited
    fat = {**report, "crawl": {**report["crawl"], "pages": [{"body": "x" * 2000} for _ in range(500)]}}
    payload = analysis_payload(fat)
    assert len(json.dumps(fat)) > 1_000_000
    # The payload is the report without its crawl, plus a short summary of it (DECISIONS 356: the bound was a fifth of
    # the fat report, which the fixture's findings came within 1% of; the property is that the crawl is gone).
    without_crawl = len(json.dumps({k: v for k, v in fat.items() if k != "crawl"}))
    assert len(json.dumps(payload)) < without_crawl + 5_000 and without_crawl < len(json.dumps(fat)) / 3


def test_the_non_negotiable_rules_travel_with_every_prompt(audited):
    report, result = audited
    for name, entry in briefs_by_name(build_llm_brief(report, result)).items():
        prompt = " ".join(entry["prompt"].split())
        assert '"Not assessed" is never "fine"' in prompt, name
        assert "Severity and confidence are different things and never merge" in prompt, name
        assert "Never invent a score" in prompt, name


def test_attribution_is_present(audited):
    report, result = audited
    for entry in briefs_by_name(build_llm_brief(report, result)).values():
        assert "MIT, Ben Senescu, 2026" in entry["prompt"]


def test_a_skill_without_its_data_is_not_rendered(audited):
    """An empty section reads as "nothing to report". Refuse instead."""
    report, result = audited
    stripped = {**report, "answer_engine_panel": []}
    brief = build_llm_brief(stripped, result)
    panel_skills = [s for s in brief["skills"] if s["skill_name"] in ("cited-domain-landscape", "cited-page-mapping")]
    assert len(panel_skills) == 2
    for entry in panel_skills:
        assert entry["prompt"] is None
        assert all(m.startswith("answer_engine_panel") for m in entry["missing"])
    # The skills that do have their data still render.
    assert briefs_by_name(brief)["audit-report"]["prompt"]


def test_missing_data_is_named_not_silently_dropped(audited):
    report, result = audited
    brief = build_llm_brief({**report, "checks": [], "gates": []}, result)
    entry = briefs_by_name(brief)["audit-report"]
    assert entry["prompt"] is None
    assert sorted(entry["missing"]) == ["checks", "gates"]
    # The skill is still listed, so a reader sees it was considered and why it did not run.
    assert entry["goal"]


def test_skills_can_be_selected(audited):
    report, result = audited
    brief = build_llm_brief(report, result, skills=["audit-report"])
    assert list(briefs_by_name(brief)) == ["audit-report"]


def test_an_unknown_skill_is_an_error_not_a_silent_skip(audited):
    report, result = audited
    with pytest.raises(ValueError, match="unknown skill"):
        build_llm_brief(report, result, skills=["audit-report", "seo-strategy"])


def test_the_evidence_report_carries_no_prompt_text(audited):
    """The report is the evidence file. Prompt text belongs in the brief, not in what a finding cites."""
    report, _ = audited
    blob = json.dumps(report, ensure_ascii=False)
    assert "Rules you cannot break" not in blob
    assert "Ben Senescu" not in blob
    assert set(report) == {"generation", "schema_version", "report_version", "status_meanings", "scope", "gates", "checks", "answer_engine_panel",
                           "findings_in_priority_order", "needs_human_review", "page_counts", "brand", "problem_summary", "time_limit_cuts", "audit_status",
                           "crawl", "release_gate"}


def test_brand_name_uses_the_registrable_domain(audited):
    report, result = audited
    brief = build_llm_brief(report, result, brand_name="Özel Moodist Hastanesi")
    assert brief["brand_name"] == "Özel Moodist Hastanesi"
    assert "Özel Moodist Hastanesi" in briefs_by_name(brief)["audit-report"]["prompt"]
    # Without one supplied it is derived, never left blank.
    assert build_llm_brief(report, result)["brand_name"]


def test_no_skill_promises_a_ranking_or_citation_outcome(audited):
    report, result = audited
    for entry in briefs_by_name(build_llm_brief(report, result)).values():
        assert "Never promise a ranking or citation outcome" in " ".join(entry["prompt"].split())


def test_the_landscape_skill_refuses_the_share_of_voice_name(audited):
    """ANS-4/ANS-5 carry a metric a model could easily mislabel. The prompt has to head that off."""
    report, result = audited
    # Prompts are hard-wrapped, so match on the text with runs of whitespace collapsed.
    prompt = " ".join(briefs_by_name(build_llm_brief(report, result))["cited-domain-landscape"]["prompt"].split())
    assert "This is not Share of Voice" in prompt
    assert "Never use the phrase" in prompt


def test_the_landscape_skill_forbids_claims_about_uncrawled_competitors(audited):
    report, result = audited
    prompt = " ".join(briefs_by_name(build_llm_brief(report, result))["cited-domain-landscape"]["prompt"].split())
    assert "never crawled any of these domains" in prompt
    assert "is invention" in prompt


def test_the_mapping_skill_forbids_inventing_topics_from_prompt_ids(audited):
    """Real exports carry `promptId` and no prompt text. A model must not name the topic anyway."""
    report, result = audited
    prompt = briefs_by_name(build_llm_brief(report, result))["cited-page-mapping"]["prompt"]
    assert "Prompt IDs are not topics" in prompt


@pytest.mark.parametrize("skill", SKILLS.values(), ids=list(SKILLS))
def test_no_openseo_product_coupling_survived_the_port(skill):
    """The frameworks ported; that product's tools, billing and data sources did not."""
    text = skill.template.casefold()
    for leaked in ("get_project_context", "update_project_context", "research_log", "dataforseo",
                   "list_projects", "run_site_audit", "get_backlinks", "research_keywords",
                   "save_keywords", "get_ranked_keywords", "credits", "greptile", "mcp"):
        assert leaked not in text, f"{skill.name} still references {leaked}"


def test_rendering_with_an_unknown_placeholder_raises(audited):
    with pytest.raises(KeyError):
        AUDIT_REPORT.render(brand_name="x")  # site_url, report_json missing


def test_requires_is_accurate_for_each_skill():
    """A skill that declares no requirement would render against an empty audit and say nothing."""
    for skill in SKILLS.values():
        assert skill.requires, f"{skill.name} declares no required data"
        assert skill.missing({}) == list(skill.requires)
    panel = [{"check_id": "ANS-4", "status": "observed", "observations": [{"cited_domains": 0}]},
             {"check_id": "ANS-5", "status": "observed", "evidence": {"domains": []}}]
    assert CITED_DOMAIN_LANDSCAPE.missing({"answer_engine_panel": panel}) == []


def test_a_named_check_must_be_assessed_and_hold_data_and_a_measured_zero_counts():
    """A check ID in the panel is not enough: it must have run and have something to read."""
    def panel(ans4, ans5=None):
        return {"answer_engine_panel": [ans4, ans5 or {"check_id": "ANS-5", "status": "observed", "evidence": {"x": 1}}]}

    not_assessed = {"check_id": "ANS-4", "status": "not_assessed", "summary": "Not assessed: no citation-domain file was given"}
    reasons = CITED_DOMAIN_LANDSCAPE.unavailable(panel(not_assessed))
    assert list(reasons) == ["answer_engine_panel:ANS-4"] and "no citation-domain file was given" in reasons["answer_engine_panel:ANS-4"]
    empty = CITED_DOMAIN_LANDSCAPE.unavailable(panel({"check_id": "ANS-4", "status": "observed"}))
    assert "holds no findings, observations or evidence" in empty["answer_engine_panel:ANS-4"]
    assert "holds no" in CITED_DOMAIN_LANDSCAPE.unavailable(panel({"check_id": "ANS-4"}))["answer_engine_panel:ANS-4"]
    # Zero is a result: the engines were asked and cited nothing.
    zero = {"check_id": "ANS-4", "status": "observed", "summary": "0 of 12 prompts cited this site",
            "observations": [{"prompts": 12, "cited": 0}]}
    assert CITED_DOMAIN_LANDSCAPE.unavailable(panel(zero)) == {}
    assert CITED_DOMAIN_LANDSCAPE.unavailable(panel({"check_id": "ANS-4", "status": "pass", "evidence": {"cited": 0}})) == {}
    # A site-check list where nothing ran is not something to write a report from.
    from maya_audit.ai_skills import AUDIT_REPORT
    dead = {"checks": [{"check_id": "IDX-1", "status": "not_assessed"}], "gates": [{"check_id": "INT-1"}]}
    assert list(AUDIT_REPORT.unavailable(dead)) == ["checks"]
    assert AUDIT_REPORT.unavailable({**dead, "checks": dead["checks"] + [{"check_id": "IDX-2", "status": "pass"}]}) == {}


def test_the_brief_says_why_a_skill_could_not_run(audited):
    report, result = audited
    brief = briefs_by_name(build_llm_brief(report, result))
    for name, entry in brief.items():
        assert set(entry["missing_reasons"]) == set(entry["missing"])
        assert (entry["prompt"] is None) == bool(entry["missing"])
    silenced = {**report, "answer_engine_panel": [
        {**c, "status": "not_assessed", "summary": "Not assessed: no citations file"} for c in report["answer_engine_panel"]]}
    entry = briefs_by_name(build_llm_brief(silenced, result))["cited-page-mapping"]
    assert entry["prompt"] is None and "no citations file" in entry["missing_reasons"]["answer_engine_panel:ANS-1"]


def test_a_panel_without_the_named_checks_does_not_satisfy_the_requirement(audited):
    """Found by running for real: a panel holding ANS-1..3 is non-empty but has nothing for ANS-4/5.

    A bare key requirement let the landscape skill render against a panel that carried none of the
    evidence its prompt names, leaving a model to describe data it had not been given.
    """
    report, result = audited
    older = {**report, "answer_engine_panel": [c for c in report["answer_engine_panel"]
                                               if c["check_id"] in ("ANS-1", "ANS-2", "ANS-3")]}
    brief = briefs_by_name(build_llm_brief(older, result))
    assert brief["cited-domain-landscape"]["prompt"] is None
    assert brief["cited-domain-landscape"]["missing"] == ["answer_engine_panel:ANS-4", "answer_engine_panel:ANS-5"]
    # ANS-1 is present, so the mapping skill still runs.
    assert brief["cited-page-mapping"]["prompt"]
