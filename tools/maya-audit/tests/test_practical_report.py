"""The practical report: executive summary, scorecard, timeline, every issue with its fix, the page table, sources."""
import pytest

pytest.importorskip("fastapi")

from maya_audit_web import practical  # noqa: E402
from test_firecrawl import Firecrawl  # noqa: E402
from test_web_app import API, Site, cloudflare, confirm, get, plan, start, web  # noqa: E402,F401
from test_web_firecrawl import PAGES, ROOT, services  # noqa: E402


def row(severity, effort, title="A problem", fix="Do this. Then that."):
    return {"id": title, "check_id": "STR-1", "severity": severity, "severity_label": severity, "area": "STR", "title": title, "affects": "3 pages",
            "sample_pages": [], "pages_total": 3, "why": "why", "fix": fix, "confidence_label": "Verified", "requires_fix": severity != "Info",
            "estimates": {"owner": "content", "owner_label": "Content", "effort": effort, "effort_label": effort}}


def test_the_timeline_puts_harm_first_and_small_jobs_early():
    # Each its own problem: the same check with the same title on other pages would be one row (DECISIONS 225).
    rows = [row(level, effort, f"Problem {word}") for (level, effort), word in zip(
        (("S1", "L"), ("S2", "M"), ("S3", "S"), ("S3", "L"), ("S4", "S"), ("S4", "M"), ("Info", "S")), "ABCDEFG")]
    assert [practical.when(r) for r in rows[:6]] == ["week", "week", "week", "month", "month", "later"]
    steps = practical.timeline(rows)
    assert [(s["id"], len(s["items"])) for s in steps] == [("week", 3), ("month", 2), ("later", 1)]  # a note is nothing to schedule
    assert steps[0]["label"] == "This week" and steps[0]["items"][0]["owner"] == "Content"


def test_fix_examples_are_chosen_by_the_findings_own_words_and_absent_when_there_is_no_honest_one():
    assert "actual subject" in practical.example_for("3 page(s) have no <title>")
    assert "actual image" in practical.example_for("1 likely meaningful image(s) on 1 page(s) have missing or empty alt text")
    assert "editorial guidance, not Google limits" in practical.example_for("3 page title(s) above the 60-character guidance band")
    assert "rel=\"canonical\"" in practical.example_for("2 page(s) declare conflicting canonicals")
    assert "before changing security settings" in practical.example_for("The site blocks or challenges automated visitors: Cloudflare (bot challenge) answered 1 of 1")
    assert practical.example_for("Something this tool has no generic example for") is None
    import re
    assert all(re.compile(pattern) for pattern, _ in practical.EXAMPLES)


def test_the_executive_summary_has_at_most_five_of_each_and_withholds_when_too_little_was_read():
    rows = [row("S2", "S", f"Problem {n}", f"Fix number {n}. More detail.") | {"check_id": f"STR-{n + 1}"} for n in range(8)]
    summary = practical.executive(rows, None, None, withheld=None)
    assert len(summary["problems"]) == len(summary["actions"]) == 5 and summary["problems_total"] == 8
    assert summary["actions"][0] == {"text": "Fix number 0.", "for": "Problem 0", "titles": ["Problem 0"], "owner": "Content", "effort": "S", "when": "This week"}
    held = practical.executive(rows, None, None, withheld="Only 1 page(s) could be read.")
    assert held["problems"] == [] and held["actions"] == [] and held["withheld"]
    assert practical.executive([row("Info", "S")], None, None, withheld=None)["no_problems"]


def test_two_problems_of_one_check_with_one_fix_are_one_action_naming_both_and_five_distinct_actions_are_listed():
    same = "Describe the entity once, or make every description agree. Then check it."
    rows = [row("S2", "S", "Problem 0", "Fix number 0. More."), {**row("S3", "M", "Two dateModified values", same), "check_id": "STR-11"},
            {**row("S3", "M", "Two name values", same), "check_id": "STR-11"}, row("S3", "S", "Problem 3", "Fix number 3."),
            row("S4", "S", "Problem four", "Fix number 4."), row("S4", "S", "Problem five", "Fix number 5."), row("S4", "S", "Problem six", "Fix number 6.")]
    summary = practical.executive(rows, None, None, withheld=None)
    assert [action["text"] for action in summary["actions"]] == ["Fix number 0.", "Fix number 3.", "Describe the entity once, or make every description agree.",
                                                                 "Fix number 4.", "Fix number 5."]  # five, each said once
    merged = summary["actions"][2]  # Same tier/scope: smaller effort comes first.
    assert merged["for"] == "Two dateModified values; Two name values" and merged["titles"] == ["Two dateModified values", "Two name values"]
    # The top problems name each check once (CR-19): every row here but the two STR-11 ones is STR-1.
    assert [p["title"] for p in summary["problems"]] == ["Problem 0", "Two dateModified values"] and summary["problems_title"] == "Top 2 of 7 problems"
    # The same fix under another check is another action: only the same check and the same fix are one.
    other = practical.executive([row("S3", "S", "A", same), {**row("S3", "S", "B", same), "check_id": "STR-4"}], None, None, withheld=None)
    assert [action["for"] for action in other["actions"]] == ["A", "B"]


def test_three_problems_with_three_fixes_keep_their_three_actions():
    rows = [row("S4", "S", f"Problem {n}", f"Fix number {n}. More detail.") | {"check_id": f"STR-{n + 1}"} for n in range(3)] + [row("Info", "S", "A note", "Nothing.")]
    summary = practical.executive(rows, None, None, withheld=None)
    assert [(action["text"], action["for"]) for action in summary["actions"]] == [(f"Fix number {n}.", f"Problem {n}") for n in range(3)]
    assert all(action["owner"] == "Content" and action["effort"] == "S" and action["when"] == "This month" for action in summary["actions"])


def test_the_report_of_a_challenged_site_read_through_firecrawl_is_practical_end_to_end(web, tmp_path):
    client = web(site=Site(respond=cloudflare), firecrawl=services(tmp_path, Firecrawl(PAGES)))
    audit = start(client, confirm(client, plan(client, search_data=True, market_default_accepted=True)))
    brief = get(client, audit, "/summary")["practical"]
    assert set(brief) == {"executive", "scorecard", "timeline", "sources", "by_page", "url"} and brief["url"].endswith("/practical")
    assert not any("already rank in positions 4 to 20" in line for line in brief["executive"]["opportunities"])  # this fixture has rank rows but no supported relevance evidence
    assert get(client, audit, "/result")["dataforseo"]["checks"]  # provider observations remain available
    assert any("not found in DataForSEO's sample of ChatGPT answers" in line for line in brief["executive"]["opportunities"])
    # DECISIONS 317: Cloudflare's challenge to Maya's crawler is a problem of its own (with its AI-crawler warning), not a note.
    assert any("bot protection (Cloudflare)" in p["title"] for p in brief["executive"]["problems"])
    assert brief["executive"]["problems"] and len(brief["executive"]["actions"]) <= 5
    full = get(client, audit, "/practical")
    # The page table comes from what Firecrawl read: Maya's own crawler was challenged on the only page it asked for.
    table = {r["url"]: r for r in full["pages"]["rows"]}
    home = table[f"{ROOT}/"]
    assert home["read_by"] == "Firecrawl" and home["title"] == "Solar Panels" and home["h1"] == "Welcome" and home["words"] > 100 and home["status"] == 200
    assert set(table) >= {f"{ROOT}/", f"{ROOT}/about", f"{ROOT}/products"} and full["pages"]["total"] == len(table)
    shared = next(i for i in full["issues"] if "shared by" in i["what"] and "title" in i["what"])  # as shown: "1 title is shared by 2 ..."
    assert "(s)" not in shared["what"]
    assert home["issues"] >= 1 and shared["example"] and shared["owner"] and shared["effort"] and shared["why"] and shared["fix"] and shared["where"]
    assert sum(len(step["items"]) for step in full["timeline"]) == len(full["issues"]) + len(full["performance_diagnostics"])
    card = {r["area"]: r for r in full["scorecard"]}
    assert card["STR"]["problems"] >= 1 and card["STR"]["checks"] >= 20 and sum(r["problems"] for r in full["scorecard"]) == len(full["issues"])
    assert any(area["checks"] for area in full["passed"])
    named = [s["source"] for s in full["sources"]]
    assert named[0].startswith("Maya's own crawler") and any(s.startswith("Firecrawl") for s in named)
    assert sum(s.startswith("DataForSEO /v3/") for s in named) == 7 and all(s["date"] for s in full["sources"])

    html = client.get(f"{API}/audits/{audit['id']}/print?full=true").text
    order = [html.index("<h2>" + heading) for heading in ("Executive summary", "Problems by page", "Scorecard by area", "Action plan: what to do when", "Findings by area", "Every page",
                                                           "Search data and backlinks", "What else we checked", "What could not be checked", "Technical appendix")]
    assert order == sorted(order)
    # What was read, through whom, and what was not measured sits beside the executive summary, before the scorecard.
    covers = html.index("What this audit covers")
    assert order[0] < covers < order[1] and "Genuine AI-crawler access was not measured." in html[covers:order[1]]
    assert "Challenged or blocked" in html[covers:order[1]] and "Whole audit, every step" in html[covers:order[1]]
    # The headline is the first line of the summary; the severity boxes come after it, under their label.
    assert order[0] < html.index('<p class="headline wrap">') < covers < html.index("By severity") < order[1]
    assert f"<h3>{brief['executive']['problems_title']}</h3>" in html and " problems" in brief["executive"]["problems_title"]
    for needle in ("Problems by page", "By severity", "Top opportunities", "First five actions", "Example", "Owner", "Solar Panels", "Welcome",
                   "Sources and dates", "Firecrawl, a third-party page reader (basic proxy)", "made-up kettle reviews", "Pages read"):
        assert needle in html, needle
    assert all(step["label"] in html for step in full["timeline"] if step["items"]) and any(step["items"] for step in full["timeline"])
    assert "The site blocked this audit" not in html and "<script" not in html


def test_the_page_table_of_a_normal_site_lists_error_pages_too_and_older_audits_without_evidence_do_not_fail(web, tmp_path):
    client = web()
    audit = start(client, plan(client))
    full = get(client, audit, "/practical")
    report = get(client, audit, "/result")
    assert {r["url"] for r in full["pages"]["rows"]} >= {p["url"] for p in report["crawl"]["pages"]}
    assert all(r["read_by"] in ("Maya", None) for r in full["pages"]["rows"]) and any(r["title"] for r in full["pages"]["rows"])
    empty = practical.page_table(tmp_path / "nothing-here", report)
    assert empty["total"] == len(report["crawl"]["pages"]) and all(r["title"] is None for r in empty["rows"])
