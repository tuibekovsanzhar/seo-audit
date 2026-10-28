"""The engine's text and Markdown reports after the preview-23 review (W4a: H18, H19, H37, CR-02, CR-05, CR-06, CR-07,
CR-13, CR-16, CR-23, CR-24, CR-25, CR-29, D-07). Notes: docs/review-fixes/w4a-report.md."""

from __future__ import annotations

import json
import re
from dataclasses import replace

import pytest

from fakeserver import FakeServer
from fakeserver.arjava_scenarios import ARJAVA_SCENARIOS
from maya_audit import cli, evidence_store, report as R
from maya_audit.audit import run_audit
from maya_audit.config import CrawlConfig
from maya_audit.findings import Finding, Severity, priority_key, scope_for
from maya_audit.models import Confidence
from test_evidence_store import site  # noqa: F401  (fixture)

FIRECRAWL_408 = ("Firecrawl returned no document (HTTP 408): Request timed out. The scrape operation did not complete "
                 "within the configured timeout. Please try increasing the timeout parameter in your request, check that "
                 "the URL is reachable, and if the problem persists contact support.")


def _audit(**extra):
    scenario = ARJAVA_SCENARIOS["arjava"]
    with FakeServer(scenario.build()) as server:
        config = CrawlConfig(**{"request_delay_s": 0.0, "robots_sample_interval_s": 0.05, "probe_retry_cooldown_s": 0.0,
                                "refetch_delay_s": 0.0, "render_enabled": False, "prf_round_gap_s": 0.0, **scenario.config, **extra})
        return run_audit(server.base_url + "/", config)


@pytest.fixture(scope="module")
def arjava():
    return _audit()


@pytest.fixture(scope="module")
def arjava_partial():
    return _audit(max_pages=12)


def _section(markdown: str, title: str) -> str:
    found = re.search(rf"^## {re.escape(title)}\n(.*?)(?=^## |\Z)", markdown, re.S | re.M)
    return found.group(1) if found else ""


def _made(check, severity, pages=1, confidence=Confidence.VERIFIED, gated=(), evidence=None, title=None, how="Fix it."):
    return Finding(check, title or f"{check} made-up", severity, confidence, "made-up", [],
                   scope_for([f"https://shop.example/p{n}" for n in range(pages)]), dict(evidence or {}), "expected", how,
                   launch_gated=list(gated))


# -- CR-23 / H26: priority ---------------------------------------------------------------------------------------------
def test_within_a_severity_verified_comes_before_estimated_and_unverified_rules_whatever_their_reach():
    verified = _made("STR-2", Severity.S2, pages=1)
    estimated = _made("ACC-1", Severity.S2, pages=40, confidence=Confidence.ESTIMATED)
    gated = _made("IDX-1", Severity.S2, pages=90, gated=["LG-15"])
    lower = _made("ACC-1", Severity.S3, pages=1)
    assert sorted([gated, lower, estimated, verified], key=priority_key) == [verified, estimated, gated, lower]


# -- CR-07 / H18 / H19: the result sentence --------------------------------------------------------------------------
def test_a_complete_audit_says_how_many_checks_could_not_run_and_never_claims_every_check_ran(arjava):
    code, word, sentence = R.run_outcome(arjava.result, arjava.gates, None, arjava.checks)
    not_run = [c.check_id for c in arjava.checks if not c.check_id.startswith("ANS") and c.status == "not_assessed"]
    assert code == 0 and word == "COMPLETED" and not_run
    assert sentence == f"The audit completed: every discovered page was crawled; {len(not_run)} checks could not run (see Coverage and checks)."
    # Without the checks, nothing is claimed about them.
    assert R.run_outcome(arjava.result, arjava.gates)[2] == "The audit completed: every discovered page was crawled."
    assert "every check ran" not in R.render_markdown(arjava.result, arjava.gates, arjava.checks)
    everything_ran = [replace(c, status="pass") if c.status == "not_assessed" else c for c in arjava.checks]
    assert R.run_outcome(arjava.result, arjava.gates, None, everything_ran)[2].endswith("every discovered page was crawled and every check ran.")


def _reader(outcome, stopped=FIRECRAWL_408, unread=34, failed=0):
    read = [p.url for p in outcome.result.pages if p.status == 200]
    return {"used": True, "purpose": "main page reader", "pages_read": len(read), "requests_sent": len(read) + 1,
            "pages": [{"url": u, "outcome": "read"} for u in read], "stopped_because": stopped,
            "coverage": {"known_urls_not_requested": unread, "not_requested_because": "provider_timeout" if unread else None,
                         "page_cap": 50, "requested_without_a_readable_document": failed}}


def test_a_page_reader_that_stopped_early_with_pages_unread_makes_the_audit_incomplete_in_a_short_sentence(arjava):
    section = _reader(arjava)
    code, word, sentence = R.run_outcome(arjava.result, arjava.gates, section, arjava.checks)
    assert (code, word) == (R.EXIT_INCOMPLETE, "INCOMPLETE")
    assert "reading stopped early (the page reader timed out (HTTP 408))" in sentence
    assert "34 discovered URL(s) were not read" in sentence and "every discovered page" not in sentence
    # The provider's own paragraph is never in a summary or a coverage sentence; it stays in the reader's section.
    markdown = R.render_markdown(arjava.result, arjava.gates, arjava.checks, firecrawl=section)
    status = R.build_report(arjava.result, arjava.gates, arjava.checks, firecrawl=section)["audit_status"]
    for text in (sentence, markdown, json.dumps(status)):
        assert "try increasing the timeout" not in text
    assert "the page reader timed out (HTTP 408)" in " ".join(status["content_coverage"]["reasons"])
    # A stop is itself a gap the coverage line names (DECISIONS 138): the result agrees with it.
    quiet = _reader(arjava, unread=0)
    assert R.run_outcome(arjava.result, arjava.gates, quiet, arjava.checks)[1] == "INCOMPLETE"
    assert R.reader_gaps(quiet) == ["reading stopped early (the page reader timed out (HTTP 408))"]
    # A reader that left no gap does not change the result.
    assert R.run_outcome(arjava.result, arjava.gates, _reader(arjava, stopped=None, unread=0), arjava.checks)[1] == "COMPLETED"


@pytest.mark.parametrize("text, said", [
    (FIRECRAWL_408, "the page reader timed out (HTTP 408)"),
    ("Firecrawl refused the key or the request (HTTP 401): " + "x " * 80, "the page reader refused the request (HTTP 401)"),
    ("Firecrawl could not load the page as a website (HTTP 502): all engines failed", "the page reader could not load the page (HTTP 502)"),
    ("the last 5 pages asked for came back unreadable, so no more were requested",
     "the last 5 pages asked for came back unreadable, so no more were requested"),
])
def test_a_provider_error_is_said_by_its_status_and_maya_s_own_sentences_are_kept(text, said):
    assert R.provider_reason(text) == said


def test_the_short_provider_reasons_are_worded_in_turkish():
    from maya_audit_web import wording
    assert wording.reason("reading stopped early (the page reader timed out (HTTP 408))", "tr") == (
        "okuma erken durdu (sayfa okuyucu zaman aşımına uğradı (HTTP 408))", True)
    assert wording.outcome("The audit completed: every discovered page was crawled; 5 checks could not run (see Coverage and checks).", "tr")[1]
    assert wording.outcome("The audit completed: every discovered page was crawled.", "tr")[1]


# -- H37, CR-06, CR-13, CR-16: the Markdown --------------------------------------------------------------------------
def test_the_markdown_opens_with_a_five_line_summary_and_the_first_ten_fixes_one_row_per_check(arjava):
    markdown = R.render_markdown(arjava.result, arjava.gates, arjava.checks)
    summary = [line for line in _section(markdown, "Summary").splitlines() if line.startswith("- ")]
    assert len(summary) == 5 and summary[0].startswith("- **Result:** COMPLETED") and summary[1].startswith("- **Scope:** ")
    assert [line.split(":**")[0] for line in summary[2:]] == ["- **Problem 1", "- **Problem 2", "- **Problem 3"]
    rows = [line for line in _section(markdown, "First 10 fixes").splitlines() if re.match(r"\| \d+ \|", line)]
    assert len(rows) == 10
    cards = re.findall(r"^### (\d+)\. \[(S\d)\] .*$", markdown, re.M)
    numbers = [int(row.split("|")[1]) for row in rows]
    assert numbers == sorted(numbers) and all(row.split("|")[4].strip() in ("S1", "S2", "S3", "S4") for row in rows)
    assert all(row.split("|")[5].strip() in ("small", "medium", "large") for row in rows)
    # One row per check: a check's second card is not a second row.
    checks = re.findall(r"^\*\*Check:\*\* ([A-Z]+-\d+)", markdown, re.M)
    assert len({checks[n - 1] for n in numbers}) == 10 and len(cards) == len(checks)
    # The fixes come before the page table, and before the coverage table.
    assert markdown.index("## First 10 fixes") < markdown.index("## What to fix first") < markdown.index("## Problems by page") \
        < markdown.index("## Coverage and checks")
    grid = _section(markdown, "Impact and effort")
    for label in ("Quick wins", "Major projects", "Fill-ins", "Later"):
        assert f"**{label}:**" in grid
    assert sorted(int(n) for n in re.findall(r"#(\d+) ", grid)) == list(range(1, len(cards) + 1))


def test_notes_are_one_line_each_and_never_numbered_cards(arjava):
    markdown = R.render_markdown(arjava.result, arjava.gates, arjava.checks)
    assert "[Info]" not in markdown.split("## Notes (no action implied)")[0]
    notes = [line for line in _section(markdown, "Notes (no action implied)").splitlines() if line.startswith("- ")]
    infos = [f for c in arjava.checks if not c.check_id.startswith("ANS") for f in c.findings if f.severity.value == "Info"]
    assert infos and 0 < len(notes) <= len(infos) and all(line.count(" · ") >= 2 for line in notes)


def test_why_it_matters_is_the_catalogue_sentence_and_the_pass_condition_is_said_as_expected(arjava):
    markdown = R.render_markdown(arjava.result, arjava.gates, arjava.checks)
    # Which card comes first depends on the other fixes (H09 took /cdn-cgi/ out of IDX-1 on this fixture), so every
    # card is checked: its "Why" is the catalogue's sentence and its pass condition is said as "Expected".
    cards = [part.split("\n### ")[0] for part in markdown.split("### ")[1:] if "**Why it matters:**" in part]
    assert cards
    for card in cards:
        why = card.split("**Why it matters:** ", 1)[1].split("\n", 1)[0]
        assert "**Expected:** " in card
        expected = card.split("**Expected:** ", 1)[1].split("\n", 1)[0]
        assert why and why != expected
    assert "**Why it matters:** internal links" not in markdown


def test_what_every_card_would_repeat_is_said_once(arjava):
    markdown = R.render_markdown(arjava.result, arjava.gates, arjava.checks)
    assert markdown.count("A report export or owner approval is not verification") == 1
    assert "This check has not yet been validated on real sites" not in markdown
    gated = [f for c in arjava.checks for f in c.findings if f.launch_gated and f.severity.value != "Info"]
    assert gated and "**Unverified check (LG-" in _section(markdown, "What to fix first")


def test_problems_by_page_names_at_most_25_pages_and_points_to_the_json_for_the_rest(arjava):
    summary = R.build_report(arjava.result, arjava.gates, arjava.checks)["problem_summary"]
    titles = {}
    lines = R.problems_by_page_lines(summary, titles, arjava.result.origin)
    pages = [line for line in lines if line.startswith("| `")]
    assert len(summary["by_page"]) > 25 and len(pages) == 25
    assert f"{len(summary['by_page']) - 25} more pages with problems: JSON report, `problem_summary.by_page`." in lines
    assert len([line for line in R.problems_by_page_lines(summary, titles, arjava.result.origin, None) if line.startswith("| `")]) == len(summary["by_page"])


# -- CR-05 ------------------------------------------------------------------------------------------------------------
def test_pages_found_but_not_read_is_said_once_above_the_coverage_table(arjava_partial):
    markdown = R.render_markdown(arjava_partial.result, arjava_partial.gates, arjava_partial.checks)
    gapped = [c for c in arjava_partial.checks if any(p["part"] == "pages found but not read" for p in c.coverage.get("not_assessed", []))]
    assert len(gapped) > 5
    table = _section(markdown, "Coverage and checks")
    assert table.count("Pages found but not read: this check ran on the") == 1
    assert "pages found but not read:" not in table


# -- CR-02 / CR-24: presentation groups -------------------------------------------------------------------------------
def test_broken_internal_targets_are_one_card_with_a_table_of_the_first_ten():
    fix = "Update these links to the correct live URL or remove them."
    broken = [_made("IDX-6", Severity.S3, pages=n % 3 + 1, title=f"Link target returns 404, linked from 1 page(s): https://shop.example/gone{n}",
                    evidence={"target": f"https://shop.example/gone{n}", "target_status": 404}, how=fix) for n in range(12)]
    problems, notes = R.card_groups(sorted(broken, key=priority_key))
    assert len(problems) == 1 and notes == []
    lines = R.card_lines(1, problems[0], "https://shop.example", {f.id: R.to_jsonable(f) for f in broken})
    assert lines[0] == "### 1. [S3] 12 internal link targets return 404"
    assert len([line for line in lines if line.startswith("| `/gone")]) == 10 and "| 2 more targets: JSON report, IDX-6 findings | |" in lines
    # The findings themselves are untouched: twelve, one per target (DECISIONS 20).
    assert len({f.id for f in broken}) == 12


def test_one_robots_line_is_one_card_at_its_worst_severity_and_provider_notes_are_one_table():
    rule = {"robots_url": "https://shop.example/robots.txt", "rule": {"line": 4, "directive": "disallow", "pattern": "/cart"}}
    roles = [("search", Severity.S1), ("live", Severity.S3), ("training", Severity.S4)]
    acc2 = [_made("ACC-2", sev, title=f"robots.txt line 4 (Disallow: /cart) blocks {role} bot(s) X on 1 sampled URL(s)", evidence=rule)
            for role, sev in roles]
    acc6 = [_made("ACC-6", Severity.INFO, title=f"{v}: Training (T{v}): blocked · Search (S{v}): allowed · Live fetch: no token")
            for v in ("OpenAI", "Google")]
    problems, notes = R.card_groups(sorted(acc2 + acc6, key=priority_key))
    assert len(problems) == 1 and len(notes) == 1
    card = R.card_lines(1, problems[0], "https://shop.example", {f.id: R.to_jsonable(f) for f in acc2})
    assert card[0] == "### 1. [S1] robots.txt line 4 (Disallow: /cart) blocks search, live, training bots"
    assert [line[:5] for line in card if line.startswith("- [S")] == ["- [S1", "- [S3", "- [S4"]
    table = R.note_lines(notes)
    assert sum(1 for line in table if line.startswith("- ")) == 1
    assert "| OpenAI | TOpenAI: blocked | SOpenAI: allowed | no token |" in table


# -- the short report, the CLI, the evidence folder, provenance ---------------------------------------------------------
def test_the_short_markdown_is_the_summary_the_first_fixes_and_what_could_not_run(arjava):
    brief = R.render_markdown_brief(arjava.result, arjava.gates, arjava.checks)
    assert [h for h in re.findall(r"^## (.+)$", brief, re.M)] == ["Summary", "First 10 fixes", "Impact and effort", "Not assessed",
                                                                  "More in the full report"]
    assert len(brief.split()) < 1000 and "### " not in brief
    assert "- **IDX-9 Google index status of key pages:**" in brief


def test_the_cli_writes_the_short_markdown_and_keeps_local_paths_out_of_the_report(site, tmp_path, capsys):  # noqa: F811
    report, brief = tmp_path / "audit.json", tmp_path / "brief.md"
    code = cli.main(["crawl", site.base_url + "/", "--key-page", "/tr/yazi/", "--json", str(report), "--markdown-brief", str(brief)])
    assert code in (0, 3)
    text = brief.read_text(encoding="utf-8")
    assert text.startswith("# Maya Audit: ") and "## Summary" in text and "short Markdown report written to" in capsys.readouterr().out
    saved = json.loads(report.read_text(encoding="utf-8"))
    assert saved["evidence_saved"]["folder"] == "audit-evidence"
    index = json.loads((tmp_path / "audit-evidence" / "index.json").read_text(encoding="utf-8"))
    assert index["folder"] == "audit-evidence" and str(tmp_path) not in json.dumps(index)
    assert saved["generation"]["source_commit"] and saved["generation"]["source_provenance"]["source_kind"]
    # The short report is an output like the others: an existing file is not overwritten.
    assert cli.main(["crawl", site.base_url + "/", "--markdown-brief", str(brief)]) == 2


def test_an_evidence_folder_outside_the_report_folder_is_named_not_located(tmp_path):
    assert evidence_store.shown_folder(tmp_path / "a" / "evidence", str(tmp_path / "b" / "r.json")) == "evidence"
    assert evidence_store.shown_folder(tmp_path / "r-evidence", str(tmp_path / "r.json")) == "r-evidence"
    assert evidence_store.shown_folder(tmp_path / "x") == "x"


def test_provenance_is_a_commit_or_not_recorded_and_never_fails(tmp_path):
    assert R.source_provenance(tmp_path)["source_commit"] == R.NOT_RECORDED
    (tmp_path / "RELEASE-SNAPSHOT.json").write_text('{"release": "team-preview-23", "base_commit": "' + "a" * 40 + '"}', encoding="utf-8")
    assert R.source_provenance(tmp_path)["source_commit"] == "a" * 40
    git = tmp_path / "repo-git"
    (git / "refs" / "heads").mkdir(parents=True)
    (git / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (git / "refs" / "heads" / "main").write_text("b" * 40 + "\n", encoding="utf-8")
    (tmp_path / ".git").write_text(f"gitdir: {git}\n", encoding="utf-8")
    found = R.source_provenance(tmp_path)
    assert found["source_commit"] == "b" * 40 and found["release"] == "team-preview-23" and found["base_commit"] == "a" * 40
    (tmp_path / "RELEASE-SNAPSHOT.json").write_text("not json", encoding="utf-8")
    assert R.source_provenance(tmp_path)["source_commit"] == "b" * 40


def test_the_text_report_lists_notes_apart_from_the_numbered_problems(arjava):
    text = R.render_text(arjava.result, arjava.gates, arjava.checks)
    order = text.split("Priority order")[1].split(R.NOTES_TITLE)[0]
    assert "[Info]" not in order and R.NOTES_TITLE in text


@pytest.mark.parametrize("kind", ["page_cap", "request_allowance_used"])
def test_a_reader_left_short_by_its_cap_or_allowance_is_incomplete_and_the_result_and_coverage_lines_agree(arjava, kind):
    section = _reader(arjava, stopped=None, unread=34)
    section["page_cap"] = 50
    section["coverage"].update(not_requested_because=kind, cap_reached=kind == "page_cap", page_requests=60,
                               requests_without_a_new_page=3)
    if kind == "request_allowance_used":
        section["stopped_because"] = "the Firecrawl request allowance of 61 for this audit is used (60 plus one bootstrap reserve). No request was sent."
    code, word, sentence = R.run_outcome(arjava.result, arjava.gates, section, arjava.checks)
    assert (code, word) == (R.EXIT_INCOMPLETE, "INCOMPLETE") and "every discovered page" not in sentence
    if kind == "page_cap":
        assert sentence.startswith(f"Partial audit: {section['pages_read']} of {section['pages_read'] + 34} known pages were read (the page limit of 50).")
    else:
        assert "the page reader used all 60 page requests" in sentence and "34 discovered URL(s) were not read" in sentence
    reasons = R.build_report(arjava.result, arjava.gates, arjava.checks, firecrawl=section)["audit_status"]["content_coverage"]["reasons"]
    assert reasons  # the coverage line names the same gap


def test_the_reader_panel_says_its_stop_in_the_short_form_and_keeps_the_provider_text_as_evidence():
    from maya_audit.firecrawl import panel
    info = {"used": False, "reason": "made-up", "stopped_because": FIRECRAWL_408, "zero_data_retention": {"status": "applied"},
            "errors": [], "credits": {"used_or_reserved": 0, "estimated_max": 0}, "usd": {"used_or_reserved": None}, "requests_sent": 1}
    lines = panel.summary_lines(info)
    assert [line for line in lines if line.startswith("Stopped early:")] == ["Stopped early: the page reader timed out (HTTP 408)"]
