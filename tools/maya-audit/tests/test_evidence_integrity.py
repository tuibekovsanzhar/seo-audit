"""Phase 1 (evidence integrity): a report must never say more than its evidence supports.

Covers the report 0.4 status model (partial / observed), the coverage rules, the 0.3 → 0.4
migration, and the specific false-pass and mislabelled-confidence defects found in the Phase 0
reconnaissance (docs/PHASE-0-RECONNAISSANCE.md).
"""

import json
import os
import re
from types import SimpleNamespace

import pytest

from maya_audit.analysis import analyze_html
from maya_audit.ans_data import load_citations
from maya_audit.checks.access import acc4_ua_differential
from maya_audit.checks.answers import _site_view, ans1_cited_url_health
from maya_audit.checks.render import rnd3_interaction
from maya_audit.checks.structure import _compare_page
from maya_audit.config import CrawlConfig
from maya_audit.coverage import RULES, derive, settle, settle_all
from maya_audit.findings import SEVERITY_DEFINITIONS, STATUS_MEANINGS, CheckResult
from maya_audit.ai_skills.rules import EVIDENCE_RULES, SEVERITY_LADDER
from maya_audit.migrate import migrate_report
from maya_audit.models import Confidence, FetchClass, PageFetch, StopReason
from maya_audit.registry import REGISTRY, entry
from maya_audit.report import build_report

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ORIGIN = "https://example.com"


def page(path, html, headers=None, status=200):
    analysis = analyze_html(html) if html is not None else None
    return PageFetch(url=ORIGIN + path, discovered_via="link", depth=1, requested_at="2026-09-22T10:00:00+00:00",
                     user_agent="Maya-Audit/0.2", status=status, error=None, elapsed_ms=10.0,
                     content_type="text/html; charset=utf-8", body_bytes=len(html or ""), body_truncated=False,
                     headers=headers or {}, fetch_class=FetchClass.OK,
                     classification_confidence=Confidence.VERIFIED, classification_evidence=[], analysis=analysis)


# -- the status model ---------------------------------------------------------------

def test_a_pass_with_an_unassessed_part_is_partial():
    gap = {"not_assessed": [{"part": "x", "reason": "y", "count": 3}]}
    assert CheckResult("STR-4", "t", "pass", "s", coverage=gap).status == "partial"
    assert CheckResult("STR-4", "t", "pass", "s", coverage={"not_assessed": []}).status == "pass"
    # Findings stay findings: the coverage block still says what was not looked at.
    assert CheckResult("STR-4", "t", "findings", "s", coverage=gap).status == "findings"
    assert CheckResult("STR-4", "t", "not_assessed", "s", coverage=gap).status == "not_assessed"


def test_page_dependent_pass_becomes_partial_when_page_cap_left_urls_unfetched():
    result = SimpleNamespace(stop_reason=StopReason.PAGE_CAP, stop_detail="page cap reached",
                             not_fetched_urls=[ORIGIN + "/unseen"], pages=[], deadline_hit=False,
                             collector_errors={})
    [check] = settle_all([CheckResult("IDX-6", "Broken links", "pass", "None found")], result)
    assert check.status == "partial"
    assert check.coverage["not_assessed"][0]["count"] == 1


def test_an_unknown_status_is_refused():
    with pytest.raises(ValueError):
        CheckResult("STR-4", "t", "ok", "s")


def test_observation_only_checks_are_observed_not_passed():
    check = CheckResult("ANS-5", "t", "pass", "s")
    settle(check)
    assert check.status == "observed"


def test_every_status_has_a_meaning_in_the_report():
    assert set(STATUS_MEANINGS) == {"findings", "needs_review", "pass", "partial", "observed", "not_assessed", "not_applicable"}
    assert "not a pass" in STATUS_MEANINGS["partial"]


# -- coverage rules: enough evidence, not enough, capped, malformed --------------------

# (check id, evidence, observations, expected part names). Each row is one "insufficient evidence" case.
GAPS = [
    ("ACC-1", {"samples": [{"status": 429}, {"status": 429}, {"status": 200}]}, [], ["robots.txt availability"]),
    ("ACC-4", {"urls_not_assessed": [{"url": "u"}], "capped": True, "cap": 150}, [],
     ["UA differential on sampled URLs", "remaining bot/URL pairs"]),
    ("ACC-5", {"never_fetched_check": "not assessed: no IP ranges loaded for any search bot"},
     [{"metric": "non-2xx share", "threshold": "not set (spec follow-up)"}],
     ["allowed pages never fetched by a verified search bot", "non-2xx share and last-seen per bot"]),
    ("IDX-1", {}, [{"metric": "failure not fetched again (refetch cap reached)"}],
     ["persistent vs intermittent failure"]),
    ("IDX-4", {"not_assessed": [{"url": "a"}], "not_assessed_count": 1}, [], ["canonical targets"]),
    ("IDX-5", {"listed_urls_not_fetched": 626}, [], ["sitemap-listed URLs"]),
    ("IDX-10", {"index_status": "not assessed: no index field"}, [], ["Bing index status"]),
    ("RND-1", {"render_mode": "raw_html_only", "render_reason": "disabled"}, [],
     ["raw vs rendered comparison (T1)"]),
    ("RND-3", {"rendered_pages": 3, "text_heuristics_not_assessed_count": 2}, [],
     ["'load more' controls on unrendered pages"]),
    ("RND-5", {"text_signatures_not_assessed_count": 47}, [], ["in-page walls and paywalls"]),
    ("STR-4", {"not_assessed": [{}] * 40, "not_assessed_count": 55}, [],
     ["structured-data vs visible comparisons"]),
    ("STR-6", {"agreement_not_assessable_pages": 25}, [], ["agreement between date signals"]),
    ("TSEO-1", {"excluded_pages_count": 2, "crawl_incomplete": True, "crawl_stop_reason": "page_cap",
                "not_fetched_url_count": 7}, [],
     ["pages excluded for incomplete raw HTML", "discovered pages not fetched"]),
    ("ANS-1", {"input_completeness": "incomplete: paged: 20 of 90 record(s) returned"}, [],
     ["citations of this site"]),
]


@pytest.mark.parametrize("check_id,evidence,observations,expected", GAPS, ids=[g[0] for g in GAPS])
def test_insufficient_evidence_is_listed_as_not_assessed(check_id, evidence, observations, expected):
    parts = derive(check_id, "pass", evidence, observations)["not_assessed"]
    assert [p["part"] for p in parts] == expected
    assert all(p["reason"] for p in parts)


@pytest.mark.parametrize("check_id", sorted(RULES))
def test_complete_or_missing_evidence_adds_no_invented_gap(check_id):
    # Enough evidence (nothing unassessed recorded) and malformed/absent evidence both give no parts,
    # never an exception: the check's own status already speaks for a check that could not run.
    complete = {"render_mode": "raw_plus_sampled_render", "rendered_pages": 5, "agreement_not_assessable_pages": 0,
                "input_completeness": "complete as far as the file shows", "cited_urls_not_checked": []}
    assert derive(check_id, "pass", complete, [])["not_assessed"] == []
    derive(check_id, "pass", None, None)  # malformed or absent evidence never raises
    assert derive(check_id, "not_assessed", {"render_mode": "raw_html_only"}, [])["not_assessed"] == []


def test_exact_counts_win_over_capped_lists_and_capped_lists_say_so():
    exact = derive("STR-4", "pass", {"not_assessed": [{}] * 40, "not_assessed_count": 55}, [])["not_assessed"][0]
    assert exact["count"] == 55 and "count_is_lower_bound" not in exact
    capped = derive("STR-4", "pass", {"not_assessed": [{}] * 40}, [])["not_assessed"][0]
    assert capped["count"] == 40 and capped["count_is_lower_bound"] is True


# -- report and migration --------------------------------------------------------------

def test_the_report_is_version_0_4_and_explains_its_statuses(run_audit_scenario):
    run = run_audit_scenario("acc_ai_friendly")
    report = build_report(run.result, list(run.gates.values()), list(run.checks.values()))
    assert report["report_version"] == "0.4" and report["status_meanings"] == STATUS_MEANINGS
    assert all("coverage" in c for c in report["checks"] + report["answer_engine_panel"])
    assert {c["status"] for c in report["answer_engine_panel"] if c["check_id"] == "ANS-5"} <= {"observed",
                                                                                                "not_assessed"}


def test_migrating_a_0_3_report_agrees_with_a_live_run(run_audit_scenario):
    """The migration and a live run apply the same rules: rebuild the 0.3 view of a live report and migrate it."""
    run = run_audit_scenario("str_pages")
    live = build_report(run.result, list(run.gates.values()), list(run.checks.values()))
    old = json.loads(json.dumps(live))
    old["report_version"] = "0.3"
    old.pop("status_meanings")
    for check in old["checks"] + old["answer_engine_panel"]:
        check.pop("coverage")
        if check["status"] in ("partial", "observed"):
            check["status"] = "pass"
    migrated = migrate_report(old)
    got = {c["check_id"]: c["status"] for c in migrated["checks"] + migrated["answer_engine_panel"]}
    want = {c["check_id"]: c["status"] for c in live["checks"] + live["answer_engine_panel"]}
    assert got == want
    assert any(c["from"] == "pass" and c["to"] == "partial" for c in migrated["migrated"]["status_changes"])


def test_migration_never_touches_findings_and_refuses_unknown_versions():
    report = {"report_version": "0.3", "checks": [
        {"check_id": "STR-4", "status": "pass", "summary": "s", "findings": [], "observations": [],
         "evidence": {"not_assessed": [{"field": "date"}] * 40}},
        {"check_id": "IDX-3", "status": "findings", "summary": "s", "findings": [{"id": "IDX-3-x"}],
         "observations": [], "evidence": {}}],
        "answer_engine_panel": [{"check_id": "ANS-5", "status": "pass", "summary": "s", "findings": [],
                                 "observations": [], "evidence": {}}]}
    out = migrate_report(report)
    statuses = {c["check_id"]: c["status"] for c in out["checks"] + out["answer_engine_panel"]}
    assert statuses == {"STR-4": "partial", "IDX-3": "findings", "ANS-5": "observed"}
    assert out["checks"][1]["findings"] == [{"id": "IDX-3-x"}]
    assert out["migrated"]["limits"] and report["checks"][0]["status"] == "pass"  # the input is not mutated
    with pytest.raises(ValueError):
        migrate_report({"report_version": "0.1"})


MOODIST = os.path.join(ROOT, "examples", "live-runs", "moodist", "audit-report.json")


@pytest.mark.skipif(not os.path.exists(MOODIST), reason="live-run examples are not committed to git")
def test_the_moodist_live_report_shows_its_partial_pass():
    """Regression pin on real data: STR-4 said values 'match on 46 pages' with 40+ comparisons not assessed."""
    with open(MOODIST, encoding="utf-8") as fh:
        migrated = migrate_report(json.load(fh))
    checks = {c["check_id"]: c for c in migrated["checks"]}
    assert checks["STR-4"]["status"] == "partial"
    gap = checks["STR-4"]["coverage"]["not_assessed"][0]
    assert gap["count"] == 40 and gap["count_is_lower_bound"] is True


# -- the severity scale a model is taught ------------------------------------------------

def test_the_prompt_severity_ladder_is_the_spec_s():
    spec = open(os.path.join(ROOT, "docs", "technical-audit-checklist.md"), encoding="utf-8").read()
    table = spec[spec.index("### 2.1"):spec.index("### 2.2")]
    # Each level's defining phrase in the spec table appears in the definition the prompts use.
    anchors = {"S1": "cannot retrieve the page(s), or is told not to use them",
               "S2": "content an engine would cite is missing, wrong",
               "S3": "Degrades discovery, extraction, or understanding without preventing it",
               "S4": "Hygiene with a plausible but weakly evidenced effect"}
    for level, phrase in anchors.items():
        assert phrase in table
        assert phrase.casefold() in SEVERITY_DEFINITIONS[level].casefold()
        assert f"- {level} — {SEVERITY_DEFINITIONS[level]}" in SEVERITY_LADDER
    # The defect this replaces: content the engine cannot see is S2 (RND-1), never S3.
    assert not re.search(r"S3 —[^\n]*cannot see", SEVERITY_LADDER)
    assert "`partial`" in SEVERITY_LADDER and "`partial`" in EVIDENCE_RULES


# -- RND-3: the English-only fallback must not pass non-English pages ----------------------

def _rnd3(html):
    result = SimpleNamespace(origin=ORIGIN, pages=[page("/sayfa", html)], render=None)
    check = rnd3_interaction(result, CrawlConfig(render_enabled=False))
    settle(check)
    return check


def test_rnd3_does_not_pass_a_non_english_page_it_cannot_read():
    turkish = ("<html lang='tr'><body><main>" + "Bu sayfa bir hastane ve çok daha fazla bilgi için bizi arayın, "
               "ve bu bilgi için bir sonraki adım ile değil ama olarak göre ancak. " * 6 + "</main></body></html>")
    check = _rnd3(turkish)
    assert check.status == "partial"
    assert check.evidence["text_heuristics_not_assessed_count"] == 1
    assert "'load more' controls on unrendered pages" in [g["part"] for g in check.coverage["not_assessed"]]
    english = ("<html lang='en'><body><main>" + "This page is for the hospital and it is the one you need to read "
               "about the care we can give you with our team. " * 6 + "</main></body></html>")
    assert _rnd3(english).evidence["text_heuristics_not_assessed_count"] == 0


# -- ACC-4: one unretried difference is not a confirmed block ------------------------------

def _acc4(confirmed, capped):
    browser = {"status": 200, "headers": {}, "visible_words": 300, "title": "Home", "fetch_class": "ok"}
    attempt = {"status": 403, "fetch_class": "blocked", "headers": {}, "visible_words": 5, "title": None,
               "classification_evidence": ["status 403"], "requested_at": "2026-09-22T10:00:00+00:00"}
    probes = {"browser_user_agent": "Mozilla/5.0", "probe_headers": {}, "bots": ["OAI-SearchBot"],
              "sample": [{"url": ORIGIN + "/", "assessed": True, "baseline": browser}],
              "pairs": [{"url": ORIGIN + "/", "token": "OAI-SearchBot", "role": "search", "engine": "ChatGPT search",
                         "outcome": "blocked", "first_outcome": "blocked", "confirmed": confirmed,
                         "attempts": [attempt] * (3 if confirmed else 1), "notes": [], "launch_gate": []}],
              "requests_used": 150, "cap": 150, "capped": capped}
    access = SimpleNamespace(probes=probes, ownership={"verified": True}, probes_skipped_reason=None)
    result = SimpleNamespace(origin=ORIGIN, access=access, pages=[])
    check = acc4_ua_differential(result, CrawlConfig())
    settle(check)
    return check


def test_an_unconfirmed_block_keeps_its_severity_but_not_its_certainty():
    unconfirmed = _acc4(confirmed=False, capped=True)
    [finding] = unconfirmed.findings
    assert finding.severity.value == "S1"  # spec §2.2: an estimate is never discounted
    assert finding.confidence == Confidence.ESTIMATED and "not retried" in finding.title
    assert finding.evidence["confirmed_by_retries"] is False
    assert any(g["part"] == "remaining bot/URL pairs" for g in unconfirmed.coverage["not_assessed"])
    [confirmed] = _acc4(confirmed=True, capped=False).findings
    assert confirmed.confidence == Confidence.VERIFIED and "not retried" not in confirmed.title
    assert confirmed.evidence["bot_provenance"]["OAI-SearchBot"]["ua_source"].startswith("unverified")


# -- STR-4: several prices on a page make the conflict an inference -------------------------

OFFER = '<script type="application/ld+json">{"@type": "Offer", "price": "49", "priceCurrency": "USD"}</script>'


@pytest.mark.parametrize("shown,outcome", [("$29", "conflict"), ("$29 and $99", "not_visible")])
def test_price_conflict_confidence_follows_how_many_prices_are_shown(shown, outcome):
    """One price on the page that differs is a conflict (Verified). Several used to be an "Inferred" conflict, still
    High; since 2026-10-11 (DECISIONS 175) which of them is this offer's is for a person to say: a review item."""
    html = f"<html><body>{OFFER}<p>Pro plan {shown} per month</p></body></html>"
    analysis = analyze_html(html)
    rows = [r for r in _compare_page(SimpleNamespace(analysis=analysis), analysis["_visible_text"], True)
            if r["field"] == "price"]
    assert rows[0]["outcome"] == outcome and (rows[0].get("confidence"), rows[0].get("why_code")) == (
        ("verified", None) if outcome == "conflict" else (None, "several"))
    assert rows[0]["schema_currency"] == "USD" and [shown["text"] for shown in rows[0]["visible"]] == shown.split(" and ")


# -- ANS-1: incomplete input is not zero citations; canonicals from the header count -------

def _ans1(tmp_path, payload):
    path = tmp_path / "citations.json"
    path.write_text(json.dumps(payload))
    data = load_citations(str(path), ORIGIN)
    result = SimpleNamespace(origin=ORIGIN, pages=[], robots_policy_by_origin={})
    check = ans1_cited_url_health(result, CrawlConfig(), data, [])
    settle(check)
    return check


def test_a_paged_export_with_no_row_for_the_site_is_not_zero(tmp_path):
    paged = _ans1(tmp_path, {"examples": [], "page": {"returned": 0, "total": 90, "hasMore": True}})
    assert paged.status == "not_assessed" and "not 'zero citations'" in paged.summary
    invalid = _ans1(tmp_path, {"records": [{"url": "x"}, {"model": "chatgpt"}]})
    assert invalid.status == "not_assessed" and "invalid" in invalid.evidence["input_completeness"]
    empty = _ans1(tmp_path, {"records": []})
    assert empty.status == "observed" and "Zero cited URLs" in empty.summary


def test_ans1_reads_a_canonical_declared_in_the_link_header_as_idx4_does():
    cited = page("/guide", "<html><body><p>hello</p></body></html>",
                 headers={"link": f'<{ORIGIN}/guide/>; rel="canonical"'})
    result = SimpleNamespace(origin=ORIGIN, pages=[cited], robots_policy_by_origin={})
    view = _site_view(ORIGIN + "/guide", result, CrawlConfig(), load_citations(None, ORIGIN))
    assert "canonicalized_away" in view["failures"] and view["canonical"] == ORIGIN + "/guide/"


# -- the bot registry never claims more than its sources ------------------------------------

def test_registry_provenance_never_upgrades_a_gated_row():
    for bot in REGISTRY:
        prov = bot.provenance()
        assert (prov["verification_status"] == "verified") == (not bot.launch_gate), bot.token
    claude = entry("Claude-SearchBot").provenance()
    # Identity and role come from Anthropic's own article since 2026-09-22; the probe UA string still does not.
    assert claude["identity_source"].startswith("https://support.claude.com") and claude["ua_source"].startswith("unverified")
    assert claude["verification_status"] == "partially verified" and entry("ClaudeBot").provenance()[
        "verification_status"] == "verified"
    assert entry("Amazonbot").provenance()["role_source"].startswith("provisional")
    gptbot = entry("GPTBot").provenance()
    assert gptbot["verification_status"] == "verified" and gptbot["ip_source"] == "https://openai.com/gptbot.json"


def test_a_cited_url_with_userinfo_is_not_credited_to_the_site(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"records": [
        {"model": "chatgpt", "url": "https://attacker.test@example.com/pricing"},
        {"model": "chatgpt", "url": "example.com/pricing"}]}))
    data = load_citations(str(path), ORIGIN)
    assert [r["url"] for r in data.records] == [ORIGIN + "/pricing"]
    assert "userinfo" in data.invalid_records[0]["reason"]


# -- a site that blocks Maya: nothing read is nothing checked (found live on 2026-09-22) ------------------

def test_checks_that_read_pages_are_not_assessed_when_every_page_was_blocked(run_audit_scenario):
    from maya_audit.coverage import PAGE_DEPENDENT

    run = run_audit_scenario("cloudflare_challenge")
    assert run.gates["INT-1"].state == "degraded"
    for check_id in sorted(PAGE_DEPENDENT & set(run.checks)):
        check = run.checks[check_id]
        assert check.status in ("not_assessed", "findings"), (check_id, check.status, check.summary)
        if check.status == "not_assessed" and "Maya could read none" in check.summary:
            assert "INT-1" in check.summary
    assert run.checks["IDX-1"].status == "not_assessed"  # it used to say "no 4xx ... across 0 fetched URLs": PASS
    assert run.checks["ACC-1"].status == "pass"  # robots.txt was readable; that check does not depend on pages


def test_some_blocked_pages_make_a_page_check_partial(run_audit_scenario):
    run = run_audit_scenario("forbidden_mix")
    idx3 = run.checks["IDX-3"]
    assert idx3.status == "partial"
    assert idx3.coverage["not_assessed"][0]["part"] == "pages Maya was blocked or rate-limited on (INT-1)"


def test_a_cited_page_behind_a_bot_challenge_is_not_reported_broken(tmp_path):
    blocked = page("/pricing", None, headers={"cf-mitigated": "challenge"}, status=403)
    blocked.fetch_class = FetchClass.BLOCKED
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"records": [{"model": "chatgpt", "url": ORIGIN + "/pricing"}]}))
    data = load_citations(str(path), ORIGIN)
    result = SimpleNamespace(origin=ORIGIN, pages=[blocked], robots_policy_by_origin={})
    check = ans1_cited_url_health(result, CrawlConfig(), data, [])
    settle(check)
    assert check.findings == []
    [row] = check.evidence["cited_urls_not_checked"]
    assert "403" in row["reason"] and "INT-1" in row["reason"]
    assert check.status == "partial"


def test_an_article_loaded_by_infinite_scroll_is_not_content_behind_interaction():
    """Seen live (Midas, 2026-09-22): scrolling a news page loaded the next article, and RND-3 reported S3."""
    body = "<html lang='en'><body><main><h1>Rates held</h1><p>" + "The bank held rates today. " * 60 + "</p>"
    first = analyze_html(body + "</main></body></html>")
    after = analyze_html(body + "<article><h1>Next: rates raised</h1><p>" + "A different story entirely. " * 40
                         + "</p></article></main></body></html>")
    raw = page("/news/rates", body + "</main></body></html>")
    render = SimpleNamespace(pages={raw.url: {"ok": True, "rendered": first,
                                              "interaction": {"clicked": [], "control": first, "after": after}}})
    check = rnd3_interaction(SimpleNamespace(origin=ORIGIN, pages=[raw], render=render), CrawlConfig())
    assert check.findings == []
    [obs] = [o for o in check.observations if o["metric"].startswith("another article")]
    assert obs["pages"][0]["new_h1"] == ["Next: rates raised"]


def test_a_menu_opened_by_a_click_is_not_content_behind_interaction():
    """Seen live (withmaya.ai, 2026-09-22): "Open menu" added 47 words outside <main> on 8 pages; RND-3 said S3."""
    main = "<main><h1>Docs</h1><p>" + "Read how the product works. " * 40 + "</p></main>"
    before = analyze_html("<html lang='en'><body><nav><button>Open menu</button></nav>" + main + "</body></html>")
    after = analyze_html("<html lang='en'><body><nav><button>Open menu</button><ul>"
                         + "".join(f"<li>Menu item number {i}</li>" for i in range(20)) + "</ul></nav>" + main
                         + "</body></html>")
    raw = page("/docs", "<html lang='en'><body>" + main + "</body></html>")
    render = SimpleNamespace(pages={raw.url: {"ok": True, "rendered": before, "interaction": {
        "clicked": [{"text": "Open menu"}], "control": before, "after": after}}})
    check = rnd3_interaction(SimpleNamespace(origin=ORIGIN, pages=[raw], render=render), CrawlConfig())
    assert check.findings == []
    [obs] = [o for o in check.observations if o["metric"].startswith("clicks opened menus")]
    assert obs["pages"][0]["chars_added_to_main_content"] == 0


def test_live_prices_that_changed_before_the_render_are_not_missing_from_raw_html():
    """Seen live (Midas /canli-kripto/, 2026-09-22): 272 prices in the raw text, reported S2 because the live
    values had changed by the time of the render."""
    from maya_audit.checks.render import rnd2_critical_facts

    def quotes(values):
        return "<html lang='en'><body><main><h1>Live prices</h1>" + "".join(
            f"<p>Coin {i} ${v}</p>" for i, v in enumerate(values)) + "</main></body></html>"
    raw = page("/live", quotes([f"0,{i + 10}" for i in range(12)]))
    moved = analyze_html(quotes([f"0,{i + 50}" for i in range(12)]))          # same prices, new values
    render = SimpleNamespace(pages={raw.url: {"ok": True, "rendered": moved}})
    check = rnd2_critical_facts(SimpleNamespace(origin=ORIGIN, pages=[raw], render=render), CrawlConfig())
    assert check.findings == [] and check.evidence["live_values_not_missing"][0]["prices_in_raw_text"] == 12
    empty = page("/shell", "<html lang='en'><body><main><h1>Live prices</h1><div id='root'></div></main></body></html>")
    render = SimpleNamespace(pages={empty.url: {"ok": True, "rendered": moved}})
    check = rnd2_critical_facts(SimpleNamespace(origin=ORIGIN, pages=[empty], render=render), CrawlConfig())
    assert [f.severity.value for f in check.findings] == ["S2"]  # prices really are rendered-only here
