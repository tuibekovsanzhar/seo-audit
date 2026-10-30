"""The headline with every total, and the problems by page: counted once by the engine, shown the same everywhere.

Every finding, page and site here is made up. Nothing is requested.
"""
import pytest

from maya_audit.report import headline, problem_summary, problems_by_page_lines

SITE = "https://made-up-shop.example"


def finding(number, severity, urls=(), *, kind=None, count=None):
    urls = [f"{SITE}{path}" for path in urls]
    return {"id": f"STR-{number}", "check_id": f"STR-{number}", "title": f"Made-up finding {number}", "severity": severity,
            "scope": {"kind": kind or ("page" if len(urls) == 1 else "template"), "count": len(urls) if count is None else count, "urls": urls}}


def test_a_site_wide_problem_is_counted_once_under_the_whole_site_and_notes_appear_nowhere():
    findings = [finding(1, "S3", ["/a", "/b"]), finding(2, "S4", ["/a"]), finding(3, "S2", ["/a", "/b", "/c"], kind="sitewide"),
                finding(4, "Info", ["/a", "/z"]), finding(5, "Info", ["/b"], kind="sitewide")]
    summary = problem_summary(findings, pages_checked=3)
    assert (summary["pages_checked"], summary["problems"], summary["notes"]) == (3, 3, 2)
    assert summary["by_severity"] == {"S1": 0, "S2": 1, "S3": 1, "S4": 1, "Info": 2}
    assert summary["whole_site"] == {"problems": 1, "worst_severity": "S2", "finding_ids": ["STR-3"], "shared_elements": []}
    assert [{key: value for key, value in row.items() if key != "items"} for row in summary["by_page"]] == [
        {"url": f"{SITE}/a", "problems": 2, "worst_severity": "S3", "finding_ids": ["STR-1", "STR-2"]},
        {"url": f"{SITE}/b", "problems": 1, "worst_severity": "S3", "finding_ids": ["STR-1"]}]
    # Each page's row says what each of its problems is on that page, in the order of `finding_ids` (schema 1.10).
    assert [[item["finding_id"] for item in row["items"]] for row in summary["by_page"]] == [["STR-1", "STR-2"], ["STR-1"]]
    assert "items" not in summary["whole_site"]
    assert summary["not_listed"] == []
    everything = repr(summary["whole_site"]) + repr(summary["by_page"])
    assert "STR-4" not in everything and "STR-5" not in everything and "/z" not in everything and "/c" not in everything
    lines = problems_by_page_lines(summary, {f["id"]: f["title"] for f in findings}, SITE)
    assert lines[:5] == ["## Problems by page", "", "| Page | Problems | Worst severity | What is wrong on this page |", "|---|---|---|---|",
                         "| Whole site | 1 | High | Made-up finding 3 |"]  # the whole site is the first row
    # These made-up findings have no rule of their own: a page's row says so, and never passes the site-wide figure off as its own.
    assert lines[5] == ("| `/a` | 2 | Medium | Also affected by: “Made-up finding 1” (site-wide: 2 pages); "
                        "Also affected by: “Made-up finding 2” |") and lines[6].startswith("| `/b` | 1 | Medium |")
    assert lines[-2] == "Pages with no problem are not listed. Notes are not counted."


def test_rows_are_sorted_by_worst_severity_then_count_then_address_and_a_page_is_counted_once_per_problem():
    findings = [finding(1, "S4", ["/many", "/many", "/b"]), finding(2, "S4", ["/many"]), finding(3, "S1", ["/worst"]), finding(4, "S4", ["/a"])]
    rows = problem_summary(findings, pages_checked=4)["by_page"]
    assert [(row["url"].removeprefix(SITE), row["problems"], row["worst_severity"]) for row in rows] == [
        ("/worst", 1, "S1"), ("/many", 2, "S4"), ("/a", 1, "S4"), ("/b", 1, "S4")]


def test_the_full_list_is_used_when_there_is_one_and_pages_not_listed_are_said_never_dropped():
    listed = [f"/p{n}" for n in range(25)]
    # A finding whose line under each page says what it is there (not only "Also affected by"), so it stays on the rows
    # however many pages it is on (DECISIONS 218).
    cut = {**finding(7, "S3", listed, count=40), "check_id": "STR-2", "title": "40 page(s) have no <h1>"}
    short = problem_summary([cut], pages_checked=40)
    assert short["not_listed"] == [{"finding_id": "STR-7", "pages": 15}] and len(short["by_page"]) == 25
    full = problem_summary([cut], {"STR-7": [f"{SITE}/p{n}" for n in range(40)]}, pages_checked=40)
    assert full["not_listed"] == [] and len(full["by_page"]) == 40
    lines = problems_by_page_lines(short, {"STR-7": cut["title"]}, SITE)
    assert "“40 page(s) have no <h1>” also affects 15 more pages not listed here." in lines
    assert problems_by_page_lines(problem_summary([finding(1, "Info", ["/a"])], pages_checked=1), {}, SITE) == []  # no empty table


def made_up(counts):
    number, findings = 0, []
    for severity, many in counts.items():
        for _ in range(many):
            number += 1
            findings.append(finding(number, severity, [f"/p{number}"]))
    return findings


CASES = (({"S2": 1, "S3": 5, "S4": 9, "Info": 12}, 50, "15 problems across assessed scope; 50 pages read for content (1 high, 5 medium, 9 low) + 12 notes",
          "Değerlendirilen kapsamda 15 sorun; içerik için okunan: 50 sayfa (1 yüksek, 5 orta, 9 düşük) + 12 not"),
         ({"S4": 1}, 1, "1 problem across assessed scope; 1 page read for content (1 low)", "Değerlendirilen kapsamda 1 sorun; içerik için okunan: 1 sayfa (1 düşük)"),
         ({"S1": 2, "Info": 1}, 7, "2 problems across assessed scope; 7 pages read for content (2 blocker) + 1 note", "Değerlendirilen kapsamda 2 sorun; içerik için okunan: 7 sayfa (2 engelleyici) + 1 not"),
         ({"Info": 12}, 50, "No problems found on 50 pages + 12 notes", "50 sayfada sorun bulunmadı + 12 not"),
         ({}, 50, "No problems found on 50 pages", "50 sayfada sorun bulunmadı"))


@pytest.mark.parametrize("counts, pages, english, turkish", CASES)
def test_the_headline_names_every_total_and_reads_the_same_from_the_engine_and_the_web(counts, pages, english, turkish):
    pytest.importorskip("fastapi")
    from maya_audit_web import strings, summary

    made = problem_summary(made_up(counts), pages_checked=pages)
    assert headline(made) == english
    assert summary.headline(pages, made["problems"], made["by_severity"], made["notes"]) == english
    strings.set_language("tr")
    try:
        assert summary.headline(pages, made["problems"], made["by_severity"], made["notes"]) == turkish
    finally:
        strings.set_language("en")


def row(number, severity, effort="S"):
    title = f"Made-up problem {number}"
    return {"id": title, "check_id": f"STR-{number}", "severity": severity, "severity_label": severity, "area": "STR", "title": title, "affects": "1 page",
            "sample_pages": [], "pages_total": 1, "why": "why", "fix": f"Fix number {number}. More.", "confidence_label": "Verified",
            "requires_fix": severity != "Info", "estimates": {"owner": "content", "owner_label": "Content", "effort": effort, "effort_label": effort}}


def test_the_top_list_says_how_many_of_how_many_and_a_small_healthy_site_reads_as_before():
    pytest.importorskip("fastapi")
    from maya_audit_web import practical

    many = practical.executive([row(n, "S3") for n in range(15)] + [row(99, "Info")], None, None, withheld=None)
    assert many["problems_title"] == "Top 5 of 15 problems" and many["problems_total"] == 15
    assert many["more"] == "All 15 are listed under “Problems by page” and “Findings by area” below."
    # A site with three low problems: the same three on top, the same actions, the same scorecard counts.
    rows = [row(1, "S4"), row(2, "S4"), row(3, "S4"), row(4, "Info")]
    few = practical.executive(rows, None, None, withheld=None)
    assert [p["title"] for p in few["problems"]] == ["Made-up problem 1", "Made-up problem 2", "Made-up problem 3"] and few["problems_total"] == 3
    assert [a["text"] for a in few["actions"]] == ["Fix number 1.", "Fix number 2.", "Fix number 3."] and few["no_problems"] is None
    assert few["problems_title"] == "All 3 problems" and few["more"] is None
    card = practical.scorecard([{"area": "STR", "label": "Structure", "checks": [{"status": "findings"}, {"status": "pass"}], "not_checked": 0}], rows)
    assert card == [{"area": "STR", "label": "Structure", "checks": 2, "in_order": 1, "by_severity": {"S1": 0, "S2": 0, "S3": 0, "S4": 3},
                     "problems": 3, "notes": 1, "not_checked": 0, "partial": 0}]
    none = practical.executive([row(4, "Info")], None, None, withheld=None)
    assert none["problems_title"] == "Top problems" and none["no_problems"] and none["problems"] == []
    held = practical.executive(rows, None, None, withheld="Only 1 page(s) could be read.")
    assert held["problems_title"] == "Top problems" and held["problems"] == [] and held["more"] is None
    assert practical.top_title(5, 15, "result.top.title") == "Top 5 of 15 problems"


def test_the_card_view_and_the_printed_table_put_the_whole_site_first_and_carry_the_not_listed_line():
    pytest.importorskip("fastapi")
    from maya_audit_web import pdf, practical

    findings = [{**finding(1, "S3", [f"/p{n}" for n in range(25)], count=40), "check_id": "STR-2", "title": "40 page(s) have no <h1>"},
                finding(2, "S2", ["/p0"], kind="sitewide"), finding(3, "Info", ["/p1"])]
    rows = [{"id": f["id"], "title": f["title"]} for f in findings]
    table = practical.by_page(problem_summary(findings, pages_checked=40), rows)
    assert table["title"] == "Problems by page" and table["columns"] == ["Page", "Problems", "Worst severity", "What is wrong on this page"]
    first = table["rows"][0]
    assert first["whole_site"] and first["label"] == "Whole site" and first["problems"] == 1 and first["worst_severity_label"] == "High"
    assert first["titles"] == ["Made-up finding 2"] and table["total"] == 26 and all(r["problems"] == 1 for r in table["rows"][1:])
    assert [entry["line"] for entry in table["not_listed"]] == ["“40 page(s) have no <h1>” also affects 15 more pages not listed here."]
    assert table["note"] == "Pages with no problem are not listed. Notes are not counted."
    html = pdf._by_page(table, SITE)
    assert html.startswith("<h2>Problems by page</h2>") and html.index("Whole site") < html.index('<td class="url">/p0</td>')
    assert "also affects 15 more pages not listed here." in html and "Made-up finding 3" not in html
    assert 'class="wrap"' in html and SITE not in html  # long titles wrap; addresses are shown as paths
    assert practical.by_page(problem_summary([finding(3, "Info", ["/p1"])], pages_checked=1), rows) is None and pdf._by_page(None, SITE) == ""
    assert practical.by_page(None, rows) is None
