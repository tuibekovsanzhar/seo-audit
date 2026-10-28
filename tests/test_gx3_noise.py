"""Report noise policy (review G25 and section 2; gx3): every output keeps each S1-S3 finding visible in its first list,
and site-wide hygiene notes are one short, capped list after the Notes.

Two healthy neutral sites (tests/test_brand_neutral.py): bank-multi, whose ACC-3 has an S2 and an S3 today (one check,
two serious findings: the case a "one row per check" list used to hide), and news-video (no S1-S3, a few notes)."""

from __future__ import annotations

import json
import re
from types import SimpleNamespace

import pytest

from maya_audit import report as R
from maya_audit.config import HYGIENE_LINES
from maya_audit.findings import Finding, Severity, is_hygiene, priority_key, scope_for
from maya_audit.models import Confidence
from tests.test_brand_neutral import audit

SERIOUS = ("S1", "S2", "S3")
NOTE_LINES_CAP = 6  # Notes + Hygiene bullet lines on a healthy site (measured 2026-10-22: bank-multi 5, news-video 2)


@pytest.fixture(scope="module", params=["bank-multi", "news-video"])
def site(request, tmp_path_factory):
    run = audit(request.param, str(tmp_path_factory.mktemp("gx3-noise")))
    report = json.loads(json.dumps(run.report, default=str))
    return SimpleNamespace(name=request.param, run=run, report=report)


def _section(markdown: str, title: str) -> str:
    found = re.search(rf"^## {re.escape(title)}\n(.*?)(?=^## |\Z)", markdown, re.S | re.M)
    return found.group(1) if found else ""


def _bullets(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.startswith("- ")]


def test_a_healthy_site_renders_few_note_and_hygiene_lines(site):
    markdown = R.render_markdown(site.run.outcome.result, site.run.outcome.gates, site.run.outcome.checks)
    notes, hygiene = _bullets(_section(markdown, R.NOTES_TITLE)), _bullets(_section(markdown, R.HYGIENE_TITLE))
    assert len(notes) + len(hygiene) <= NOTE_LINES_CAP, (notes, hygiene)
    assert len(hygiene) <= HYGIENE_LINES + 1  # the capped lines, and "… N more"
    # A hygiene finding is never a "no action implied" note.
    assert not any("Strict-Transport-Security" in line for line in notes)


def test_no_serious_finding_is_missing_from_the_first_fixes_or_what_to_fix_first(site):
    markdown = R.render_markdown(site.run.outcome.result, site.run.outcome.gates, site.run.outcome.checks)
    first = _section(markdown, next((h for h in re.findall(r"^## (First .+)$", markdown, re.M)), "First fixes"))
    fix_first = _section(markdown, "What to fix first")
    # The qualified findings the report shows (judgments may reword a title), not the checks' raw ones.
    serious = [f for c in site.report["checks"] for f in c["findings"] if f["severity"] in SERIOUS]
    for finding in serious:
        assert finding["title"] in fix_first, finding["title"]
        # One row per check, but the row names the check's other serious cards ("also #n …").
        assert finding["title"] in first, finding["title"]


def test_the_web_first_list_and_the_concise_print_name_every_serious_finding(site):
    from maya_audit_web import pdf, practical, summary
    view = summary.build(site.report, outcome="COMPLETE", reason="")
    rows = summary.search(site.report, limit=100_000)["items"]
    built = practical.build(view, rows, site.report, None)
    html = pdf.render_html(view, rows=rows, plan=summary.action_plan(site.report), generated_at="2026-10-22",
                           practical=built, concise=True)
    text = R_text(html)
    executive = built["executive"]["problems"]
    shown = " ".join(p["title"] + " " + (p.get("also") or "") for p in executive)
    for row in rows:
        if row["severity"] in SERIOUS:
            assert row["id"] in text
            if len(executive) < practical.TOP:  # the five-row list is not cut: every serious problem is named in it
                assert (row.get("title_shown") or row["title"]) in shown, row["title"]
    # Every finding ID still appears, hygiene ones included (the concise report's promise).
    assert all(row["id"] in text for row in rows)
    hygiene = [row for row in rows if row.get("hygiene")]
    part = html.split("<h2>Hygiene</h2>")[1].split("<h2>")[0] if hygiene else ""
    assert len(re.findall(r"<li[^>]*>", part)) <= HYGIENE_LINES + 1  # the capped lines, and "N more, by ID"


def test_the_client_compact_report_names_the_other_serious_findings_of_a_check(site):
    from maya_audit.client_reporting import from_maya_report as F, render_report as CR
    data = F.convert(site.report)
    page = CR.build(data, draft=True, group_large=True)
    for card in data["cards"] + data["appendix_cards"]:
        assert f'id="finding-{card["id"]}"' in page
    serious_by_check: dict[str, int] = {}
    for card in data["cards"] + data["appendix_cards"]:
        if card["maya"]["severity_report"] in SERIOUS:
            serious_by_check[card["maya"]["check_id"]] = serious_by_check.get(card["maya"]["check_id"], 0) + 1
    if any(n > 1 for n in serious_by_check.values()):
        assert "Aynı kontrolden ayrıca:" in page


def test_web_rows_follow_the_engine_order_of_importance_within_a_severity(site):
    from maya_audit_web import summary
    from maya_audit_web.action_priority import ordered
    rows = ordered([summary.item(f) for f in summary.findings(site.report)])
    for a, b in zip(rows, rows[1:]):
        if a["severity"] == b["severity"] and a.get("confidence") == b.get("confidence") and not a.get("unverified") \
                and not b.get("unverified"):
            assert a["importance"] <= b["importance"], (a["id"], b["id"])


def R_text(html: str) -> str:
    import html as markup
    return markup.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"<style.*?</style>", " ", html, flags=re.S)))


# -- unit cases, no audit --------------------------------------------------------------------------------------------
def _f(check, title, severity, urls=("https://e.com/a",)):
    return Finding(check, title, severity, Confidence.VERIFIED, "Documented", [], scope_for(list(urls)), {}, "x", "y")


def test_a_first_fixes_row_names_its_checks_other_serious_cards():
    found = sorted([_f("TSEO-1", "1 page(s) have no viewport", Severity.S3),
                    _f("TSEO-1", "1 page(s) load http:// resources (mixed content)", Severity.S3, ("https://e.com/b",)),
                    _f("TSEO-1", "2 page(s) stop readers from zooming", Severity.S4, ("https://e.com/c",)),
                    _f("STR-1", "1 page(s) have no title", Severity.S2)], key=priority_key)
    problems, _ = R.card_groups(found)
    table = "\n".join(R.first_fixes_lines(problems, "https://e.com"))
    rows = [line for line in table.splitlines() if line.startswith("| ") and line[2].isdigit()]
    assert len(rows) == 2  # one per check
    tseo = next(line for line in rows if "TSEO" in line or "viewport" in line or "mixed" in line)
    assert "viewport" in tseo and "mixed content" in tseo and "zooming" not in tseo


def test_hygiene_notes_are_listed_after_the_notes_and_capped():
    hsts = _f("PRF-1", "The https homepage sends no Strict-Transport-Security header", Severity.INFO)
    others = [_f("STR-10", f"{n} page(s) have Open Graph tags but no Twitter card", Severity.INFO, (f"https://e.com/{n}",))
              for n in range(1, HYGIENE_LINES + 3)]
    note = _f("STR-3", "1 page(s) have a VideoObject with default values", Severity.INFO)
    assert is_hygiene(hsts) and not is_hygiene(note) and not is_hygiene(_f("PRF-1", "x Strict-Transport-Security", Severity.S4))
    _, notes = R.card_groups(sorted([hsts, note, *others], key=priority_key))
    lines = R.note_lines(notes)
    text = "\n".join(lines)
    assert text.index(R.NOTES_TITLE) < text.index("## " + R.HYGIENE_TITLE)
    assert "VideoObject" in _section(text, R.NOTES_TITLE) and "Strict-Transport" not in _section(text, R.NOTES_TITLE)
    hygiene = _bullets(_section(text, R.HYGIENE_TITLE))
    assert len(hygiene) == HYGIENE_LINES + 1 and "more hygiene items in the JSON report" in hygiene[-1]
