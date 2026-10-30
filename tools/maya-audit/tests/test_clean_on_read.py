"""A check that found nothing on the pages read, when not every page found was read, says so where the checks in
order are listed: "No problem found on the 50 pages read (9 not read)" (DECISIONS 189).

Seen in a saved report on 2026-10-12: sixteen checks had found nothing on 50 pages and were `partial` only because 9
more pages were found and not read. They appeared under "What could not be checked" and nowhere else, so the report
never said what they did find out. Such a check stays partial (DECISIONS 99) and stays listed there too.

The site is made up and served by the fake server; nothing else is requested.
"""
import json

import pytest

from maya_audit.coverage import CRAWL_GAP, clean_on_what_was_read, crawl_gap_part
from maya_audit.report import build_report, clean_on_read_sentence, known_unread, read_counts, render_markdown, run_outcome
from test_review_fixes import TR, audit, links, page

EN = "No problem found on the 50 pages read (9 not read)"
TURKISH = "Okunan 50 sayfada sorun bulunmadı (9 sayfa okunmadı)"


@pytest.fixture(scope="module")
def fifty_of_fifty_nine():
    """A made-up site of 59 pages audited with a cap of 50: 50 pages read, 9 found and not read."""
    names = [f"/sayfa-{n}" for n in range(58)]
    routes = {name: page(f"<h1>Sayfa {n} başlığı</h1><p>{TR} özgün{n} " + " ".join(f"k{n}x{i}" for i in range(80)) + "</p>",
                         title=f"Sayfa {n} hakkında bilgi | Atölye") for n, name in enumerate(names)}
    routes["/"] = page(f"<h1>Atölye</h1><p>{TR}</p>" + links(names), title="Atölye")
    outcome = audit(routes, max_pages=50, image_checks_max=0)
    assert (read_counts(outcome.result, None)["pages"], known_unread(outcome.result, None)) == (50, 9)
    return outcome


def made(check_id="STR-13", status="partial", parts=(CRAWL_GAP,), evidence=None, summary="No unfilled template marker on 50 page(s).", **more):
    """A check as a saved report holds it."""
    return {"check_id": check_id, "title": check_id, "status": status, "summary": summary, "findings": [], "review_items": [],
            "evidence": {"pages_checked": 50} if evidence is None else evidence,
            "coverage": {"not_assessed": [crawl_gap_part(50, 9, "page cap of 50 reached") if name == CRAWL_GAP
                                          else {"part": name, "reason": "made up", "count": 3} for name in parts]}, **more}


def test_which_checks_found_nothing_on_what_was_read():
    assert clean_on_what_was_read(made())
    assert clean_on_what_was_read(made(parts=("pages not checked because the crawl was incomplete",)))    # the part's name before 2026-10-07
    assert clean_on_what_was_read(made("TSEO-1", parts=("discovered pages not fetched", CRAWL_GAP)))      # the same addresses, counted twice
    assert clean_on_what_was_read(made("RND-6", evidence={}, summary="No oversized HTML and no late-starting main content."))
    # Not it: a pass (listed as before), a check with a finding or a review item, one that is not about the pages.
    assert not clean_on_what_was_read(made(status="pass", parts=()))
    assert not clean_on_what_was_read(made(status="findings", findings=[{"id": "x"}]))
    assert not clean_on_what_was_read(made(review_items=[{"title": "x"}]))
    assert not clean_on_what_was_read(made("ACC-1"))
    assert not clean_on_what_was_read(made(status="not_assessed", parts=()))
    assert not clean_on_what_was_read(made(parts=()))                                                    # partial for no reason on record
    # Another part of its question went unanswered: "no problem found" would say more than was looked at.
    assert not clean_on_what_was_read(made("IDX-7", parts=("orphan pages", CRAWL_GAP)))
    assert not clean_on_what_was_read(made("STR-13", parts=("discovered pages not fetched", CRAWL_GAP)))  # only TSEO-1 has that twin part
    # It looked at nothing (DECISIONS 168), or compared nothing: by its evidence, and by its summary where no count was kept.
    assert not clean_on_what_was_read(made("STR-8", evidence={"pages_checked": 0}))
    assert not clean_on_what_was_read(made("IDX-8", evidence={"candidates": 0}))
    assert not clean_on_what_was_read(made("RND-2", evidence={"declared_facts": 0}, summary="All 0 declared fact(s) are in raw HTML; no rendered-only candidates."))
    assert not clean_on_what_was_read(made("STR-16", evidence={"pages_checked": 51, "pages_compared": 0}, summary="Source: Firecrawl. No meta description is shared between the 0 page(s) compared."))
    assert not clean_on_what_was_read(made("STR-16", evidence={"pages_checked": 51}, summary="No meta description is shared between the 0 page(s) compared."))
    assert clean_on_what_was_read(made("STR-16", evidence={"pages_checked": 51, "pages_compared": 40}, summary="No meta description is shared between the 40 page(s) compared."))
    assert not clean_on_what_was_read(made("STR-22", evidence={"news_pages": 0}, summary="No news or press page among the pages read."))
    assert not clean_on_what_was_read(made("STR-23", evidence={"job_pages": 0, "careers_pages_listing_openings": 0}, summary="No job page among the pages read."))
    assert clean_on_what_was_read(made("STR-23", evidence={"job_pages": 0, "careers_pages_listing_openings": 1}, summary="1 careers page lists openings as text."))
    assert not clean_on_what_was_read(made("PRF-2", evidence={"attempts_counted": 0}, summary="0 failure(s) in 0 counted fetch(es)."))
    assert clean_on_what_was_read(made("PRF-2", evidence={"attempts_counted": 66, "failures": 0}, summary="0 failure(s) in 66 counted fetch(es); no URL failed intermittently."))
    assert clean_on_what_was_read(made("STR-11", summary="No entity is described twice with different values (0 of 51 page(s) describe an entity more than once)."))


def test_the_sentence_counts_one_page_as_one_page_and_says_a_reading_cut_short():
    pytest.importorskip("fastapi")
    from maya_audit_web import strings

    assert clean_on_read_sentence(50, 9) == EN and clean_on_read_sentence(1, 3) == "No problem found on the 1 page read (3 not read)"
    assert clean_on_read_sentence(12, 0) == "No problem found on the 12 pages read (the reading was cut short)"
    assert strings.t("result.clean_on_read", "en", n=1, m=3) == clean_on_read_sentence(1, 3) and strings.t("result.clean_on_read.cut", "en", n=12) == clean_on_read_sentence(12, 0)
    assert strings.t("result.clean_on_read", "tr", n=50, m=9) == TURKISH
    assert strings.t("result.clean_on_read.cut", "tr", n=12) == "Okunan 12 sayfada sorun bulunmadı (okuma yarıda kesildi)"


def test_a_partial_check_that_found_nothing_says_so_in_the_markdown_the_printed_report_and_the_card(fifty_of_fifty_nine):
    pytest.importorskip("fastapi")
    from maya_audit_web import pdf, practical, strings, summary

    outcome = fifty_of_fifty_nine
    by_id = {check.check_id: check for check in outcome.checks}
    clean = [check.check_id for check in outcome.checks if clean_on_what_was_read(check)]
    assert {"ACC-3", "IDX-4", "STR-13", "STR-17"} <= set(clean) and all(by_id[name].status == "partial" for name in clean)
    # IDX-1 assesses response/probe evidence, not just readable-content pages. A content-read
    # cap cannot be restated as its HTTP assessment population; retain its actual response scope.
    assert 'IDX-1' not in clean
    assert sum(by_id['IDX-1'].evidence['status_counts'].values()) == len(outcome.result.pages)
    assert 'not limited to content-readable pages' in by_id['IDX-1'].evidence['assessment_scope']['population']
    assert not any(g['part'] == 'pages found but not read' for g in by_id['IDX-1'].coverage['not_assessed'])
    # A check with another part not assessed, one that compared nothing, a pass, a check with findings: not among them.
    assert by_id["IDX-7"].status == by_id["STR-16"].status == "partial" and by_id["ACC-1"].status == "pass" and by_id["STR-10"].findings
    assert not {"IDX-7", "STR-16", "STR-22", "ACC-1", "STR-10", "STR-21"} & set(clean)

    markdown = render_markdown(outcome.result, outcome.gates, outcome.checks)
    table = markdown.split("## Coverage and checks")[1]
    row = next(line for line in table.splitlines() if line.startswith("| STR-13 "))
    assert row == f"| STR-13 {by_id['STR-13'].title} | partial | {EN}. {by_id['STR-13'].summary} |"
    assert table.count(EN) == len(clean)
    for name in ("IDX-7", "STR-16", "ACC-1", "STR-10"):
        assert EN not in next(line for line in table.splitlines() if line.startswith(f"| {name} "))

    report = json.loads(json.dumps(build_report(outcome.result, outcome.gates, outcome.checks)))
    assert EN not in json.dumps(report)  # computed when the report is shown: no new field, and a saved report shows it too
    sentence = run_outcome(outcome.result, outcome.gates, None)[2]
    passes = {area: sum(1 for check in outcome.checks if check.status == "pass" and check.check_id.startswith(area + "-")) for area in ("ACC", "IDX", "STR")}
    for language, said in (("en", EN), ("tr", TURKISH)):
        strings.set_language(language)
        try:
            view = summary.build(report, outcome="INCOMPLETE", reason=sentence)
            rows = summary.search(report, limit=1000)["items"]
            built = practical.build(view, rows, report, None)
            html = pdf.render_html(view, rows=rows, plan=summary.action_plan(report), generated_at="2026-10-13", practical=built)
            listed = {check["check_id"]: check for area in built["passed"] for check in area["checks"]}
            # The checks that passed are listed as before; the clean partial ones stand beside them, marked.
            assert {name for name, check in listed.items() if check.get("read_only")} == set(clean)
            assert {name for name, check in listed.items() if not check.get("read_only")} == {check.check_id for check in outcome.checks if check.status == "pass"}
            assert listed["ACC-1"]["summary_shown"] == next(c for area in view["areas"] for c in area["checks"] if c["check_id"] == "ACC-1")["summary_shown"]
            assert listed["STR-13"]["summary_shown"].startswith(said + ". ") and listed["STR-13"]["read_only_shown"] == said
            assert listed["STR-13"]["summary"] == f"{EN}. {by_id['STR-13'].summary}"                       # the engine's English, as the Markdown has it
            section = html.split(f"<h2>{pdf._e(strings.t('pdf.passed'))}</h2>")[1].split("<h2>")[0]
            assert section.count(pdf._e(said) + ". ") == len(clean) and f"<b>STR-13 " in section
            assert pdf._e(said) not in html.replace(section, "")
            # Still partial: not counted as in order, and still told under what could not be checked.
            card = {area["area"]: area for area in built["scorecard"]}
            assert {area: card[area]["in_order"] for area in passes} == passes
            rows_of = {check["check_id"]: check for area in view["areas"] for check in area["checks"]}
            assert rows_of["STR-13"]["status"] == "partial" and rows_of["STR-13"]["read_only_shown"] == said and "read_only" not in rows_of["ACC-1"]
            assert view["coverage"]["read_only_note"] and "50" in view["coverage"]["read_only_note"] and "9" in view["coverage"]["read_only_note"]
        finally:
            strings.set_language("en")
