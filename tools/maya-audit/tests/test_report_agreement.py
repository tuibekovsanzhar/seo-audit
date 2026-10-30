"""Phase 1D: every output of one audit says the same thing, and the offline demonstration covers each repair.

The app here is the demonstration app: made-up sites, a made-up reader and made-up search data. Nothing real is asked.
"""
import json

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from maya_audit import ownership  # noqa: E402
from maya_audit_web import demo, summary, wording  # noqa: E402
from maya_audit_web.app import create_app  # noqa: E402
from maya_audit_web.runner import Engine  # noqa: E402
from test_web_app import API, BASE, get  # noqa: E402


@pytest.fixture
def demo_app(tmp_path, monkeypatch):
    monkeypatch.setattr(ownership, "TRANSPORT", demo.NO_DNS_RECORDS)
    folder = tmp_path / "demo"
    engine = Engine(paid=demo.paid_services(folder / "paid"), firecrawl=demo.firecrawl_services(folder / "firecrawl"),
                    transport_factory=lambda: demo.site_transport(0), allow_loopback=True, overrides=demo.OVERRIDES, demo=True,
                    crux_key=lambda: "demo-made-up-key", crux_transport=demo.CRUX_TRANSPORT, archives_transport=demo.ARCHIVES_TRANSPORT)
    client = TestClient(create_app(folder, engine=engine, port=8770), base_url=BASE)
    client.__enter__()
    client.get("/")
    client.headers["x-maya-token"] = client.get(f"{API}/session").json()["token"]
    yield client
    client.__exit__(None, None, None)


def audit(client, site, **options):
    made = client.post(f"{API}/plans", json={"url": site, **options})
    assert made.status_code == 201, made.text
    started = client.post(f"{API}/audits", json={"plan_id": made.json()["id"], "message": f"audit {site}"})
    assert started.status_code == 201, started.text
    client.app.state.runner.wait(started.json()["id"], 120)
    return client.get(f"{API}/audits/{started.json()['id']}").json()


def outputs(client, one):
    view = get(client, one, "/summary")
    return (view, get(client, one, "/result"), client.get(f"{API}/audits/{one['id']}/downloads/markdown").text,
            client.get(f"{API}/audits/{one['id']}/print?full=true").text)


def test_the_card_the_markdown_the_pdf_page_and_the_json_agree_on_what_was_read_and_what_was_not_measured(demo_app):
    one = audit(demo_app, demo.BANK)
    view, report, markdown, printed = outputs(demo_app, one)
    status = report["audit_status"]
    assert one["outcome"]["code"] == "COMPLETED" and status["direct_access"]["state"] == "challenged"
    read = status["content_coverage"]["readable_unique_urls"]
    assert read == 4 == view["pages_read"] == view["counts"]["pages_checked"] == view["pages_stat"]["value"]
    assert f"**Pages read:** {read} (via Firecrawl)" in markdown and f"{read} (via Firecrawl)" in printed and f"{read} pages checked." in view["summary_line"]
    assert report["page_counts"]["pages_checked"] == 1  # Maya's own request, kept under its own name and never added to the pages read
    rows = {row["id"]: row for row in view["status"]["rows"]}
    assert rows["direct_access"]["state_label"] == "Challenged or blocked" and rows["vendor_crawler_evidence"]["state_label"] == "Not measured"
    assert rows["content_coverage"]["state_label"] == "Every page found was read (a sample)"
    for note in (status["direct_access"]["note"], status["vendor_crawler_evidence"]["note"]):
        shown = wording.english(note)  # the card and the page say "1 of 1 page request", the report's own text keeps "request(s)" (decision 166)
        assert note in markdown and shown in json.dumps(view) and shown.replace("'", "&#x27;") in printed and "(s)" not in shown, note
    assert "## What this audit covers" in markdown and "What this audit covers" in printed
    for text in (markdown, printed, json.dumps(view), json.dumps(report)):
        for claim in ("not affected", "Nothing needs fixing", "bots can read", "The site blocked this audit"):
            assert claim not in text, claim
    # Paid observations are their own panels: none is counted among the site's problems.
    site_ids = {f["id"] for check in report["checks"] for f in check["findings"]}
    assert view["counts"]["problems"] + view["counts"]["notes"] == len(site_ids) and not [i for i in site_ids if i.startswith(("DFS", "ANS"))]
    assert view["spend"]["firecrawl"]["credits"] == report["firecrawl"]["credits"]["used_or_reserved"] and view["spend"]["firecrawl"]["usd_known"] is False
    assert "Cost in dollars: unknown" in printed and view["spend"]["dataforseo"] is None
    timing = view["status"]["timing"]
    assert timing["all_phases_s"] is not None and "Whole audit, every step" in view["status"]["duration_line"] and "for the whole audit, every step included" in markdown
    follow = demo_app.post(f"{API}/audits/{one['id']}/messages", json={"text": "summary"})
    if follow.status_code == 200:
        assert "Genuine AI-crawler access was not measured" in json.dumps(follow.json())


def test_demo_a_partly_read_site_with_missing_provider_data_is_reported_as_partial_everywhere(demo_app):
    one = audit(demo_app, demo.PARTIAL, search_data=True, market_default_accepted=True)
    view, report, markdown, printed = outputs(demo_app, one)
    cover = report["firecrawl"]["coverage"]
    assert one["outcome"]["code"] == "INCOMPLETE" and one["outcome"]["reason"].startswith("The audit finished with partial coverage: 3 page(s) were read")
    assert cover["read"] == 3 and cover["requested_without_a_readable_document"] == 2 and cover["status_unknown"] == 1 and cover["known_urls_not_requested"] == 0
    rows = {(row["url"].rsplit("/", 1)[-1], row["outcome"]): row for row in report["firecrawl"]["pages"]}
    assert rows[("booking", "redirected_out_of_scope")]["final_url"] == "https://made-up-booking.example/demo-clinic"
    assert rows[("pricing", "blocked")]["status"] == 403 and rows[("contact", "read")]["status"] is None and rows[("contact", "read")]["status_known"] is False
    assert report["audit_status"]["content_coverage"]["level"] == "partial" and view["status"]["rows"][1]["state_label"] == "Partial"
    assert "2 requested URL(s) gave no readable document" in markdown and "Partial" in printed and "Made-up booking service" not in printed + markdown
    panel = {c["check_id"]: c for c in report["dataforseo"]["checks"]}
    assert report["dataforseo"]["status"] == "partly_assessed"
    assert panel["DFS-3"]["status"] == "partial" and "Not reported by the provider" in panel["DFS-3"]["summary"]
    assert panel["DFS-6"]["status"] == "not_assessed" and panel["DFS-7"]["status"] == "not_assessed"  # unreadable, and a row with no count
    assert panel["DFS-8"]["status"] == "observed" and panel["DFS-8"]["summary"].startswith("DataForSEO returned an empty sample")
    assert panel["DFS-9"]["status"] == "partial" and "not measured in this answer, so not judged" in panel["DFS-9"]["summary"]
    everything = markdown + printed + json.dumps(view)
    assert "within Google's" not in everything and "No mention" not in everything and "Measured zero" not in everything
    assert not [line for line in view["practical"]["executive"]["opportunities"] if "lab performance" in line or "not found in DataForSEO" in line]


def test_demo_a_javascript_site_and_true_zeros_are_said_as_what_they_are(demo_app):
    one = audit(demo_app, demo.APP, search_data=True, market_default_accepted=True)
    view, report, markdown, printed = outputs(demo_app, one)
    status = report["audit_status"]
    assert status["direct_access"]["state"] == "readable" and status["content_coverage"]["read_by"]["both"] == 3
    assert one["outcome"]["code"] == "COMPLETED" and view["pages_stat"]["line"] == "Pages read: 3 (via Firecrawl)"
    # The raw HTML Maya received is an empty shell; the reader's document has the text. Both facts are kept.
    own = {page["url"].rsplit("/", 1)[-1]: page for page in report["crawl"]["pages"] if page["status"] == 200}
    assert all(page["analysis"]["title"] == "Demo App" for page in own.values())
    full = get(demo_app, one, "/practical")
    table = {row["url"].rsplit("/", 1)[-1]: row for row in full["pages"]["rows"]}
    assert table["pricing"]["title"] == "Pricing | Demo App" and table["pricing"]["read_by"] == "Firecrawl" and table["pricing"]["words"] > 10
    assert "does not show what a crawler that runs no JavaScript receives" in report["firecrawl"]["notice"]
    panel = {c["check_id"]: c for c in report["dataforseo"]["checks"]}
    assert panel["DFS-7"]["summary"].startswith("Measured zero:") and panel["DFS-7"]["status"] == "observed" and panel["DFS-7"]["evidence"]["data"]["metrics"]["Matching AI answers in the sample"] == 0
    assert "empty sample" in panel["DFS-3"]["summary"] and panel["DFS-4"]["evidence"]["data"]["listed"] == 0
    assert "the three main lab metrics are within Google's \"good\" thresholds" in panel["DFS-9"]["summary"] and panel["DFS-9"]["status"] == "observed"
    assert report["dataforseo"]["status"] == "assessed" and "Measured zero" in printed and "Measured zero" in markdown


def test_a_report_made_before_this_version_is_still_shown_and_nothing_is_reconstructed_for_it(demo_app):
    one = audit(demo_app, demo.CAFE)
    report = get(demo_app, one, "/result")
    older = {key: value for key, value in report.items() if key != "audit_status"}
    older["schema_version"] = "1.5"
    view = summary.build(older, outcome="COMPLETED", reason="as saved")
    assert view["status"] is None and view["counts"]["pages_checked"] >= 1 and view["spend"]["firecrawl"] is not None
    from maya_audit_web import pdf
    html = pdf.render_html(view | {"brand": view["brand"], "site": view["site"]}, rows=summary.search(older, limit=10)["items"],
                           plan=summary.action_plan(older), generated_at="2026-10-09T00:00:00+00:00")
    assert "Executive summary" in html and "What this audit covers" not in html


@pytest.mark.parametrize("site", [demo.CAFE, demo.BANK])
def test_the_card_the_pdf_page_the_markdown_and_the_json_carry_the_same_headline_and_the_same_problems_by_page(demo_app, site):
    from html import escape

    from maya_audit.report import headline
    from maya_audit_web import pdf

    one = audit(demo_app, site)
    view, report, markdown, printed = outputs(demo_app, one)
    totals, counts = report["problem_summary"], view["counts"]
    assert view["problem_summary"] == totals and totals["problems"] > 0
    assert (totals["pages_checked"], totals["problems"], totals["notes"]) == (counts["pages_checked"], counts["problems"], counts["notes"])
    assert totals["by_severity"] == counts["by_severity"]
    # One sentence, word for word, in all three; the JSON holds its numbers.
    assert view["headline"] == headline(totals) and f"**{view['headline']}**" in markdown
    assert f'<p class="headline wrap">{escape(view["headline"], quote=True)}</p>' in printed
    # The fixes come before the page table (review CR-13, H37).
    assert markdown.index(view["headline"]) < markdown.index("## Summary") < markdown.index("## What this audit covers")         < markdown.index("## What to fix first") < markdown.index("## Problems by page")
    # The same rows: the whole site first, then each page with a problem, with the same count.
    table = view["practical"]["by_page"]
    expected = ([(None, totals["whole_site"]["problems"])] if totals["whole_site"]["problems"] else []) + [(row["url"], row["problems"]) for row in totals["by_page"]]
    assert [(row["url"], row["problems"]) for row in table["rows"]] == expected and expected
    assert get(demo_app, one, "/practical")["by_page"] == table
    # The table names each problem as the reader is shown it ("1 page is ...", not "1 page(s) are ...").
    titles = {f["id"]: wording.title(f["check_id"], f["title"])[0] for check in report["checks"] for f in check["findings"]}
    assert all(row["titles"] == [titles[i] for i in row["finding_ids"]] for row in table["rows"])
    assert not any("(s)" in title for row in table["rows"] for title in row["titles"])
    if totals["whole_site"]["problems"]:
        assert f"| Whole site | {totals['whole_site']['problems']} | " in markdown and f"<b>Whole site</b></td><td>{totals['whole_site']['problems']}</td>" in printed
    for row in totals["by_page"]:
        path = pdf._path(row["url"], view["site"])
        assert f"| `{path}` | {row['problems']} | " in markdown, path
        assert f'<td class="url">{escape(path, quote=True)}</td><td>{row["problems"]}</td>' in printed, path
    # A note is in no row, and the "Issues" column of "Every page" reads the same per-page counts.
    notes = {f["id"] for check in report["checks"] for f in check["findings"] if f["severity"] == "Info"}
    assert not notes & {i for row in table["rows"] for i in row["finding_ids"]}
    issues = {row["url"]: row["issues"] for row in get(demo_app, one, "/practical")["pages"]["rows"] if row["issues"]}
    assert issues == {url: count for url, count in expected if url and url in issues} and all(
        url in issues for url, _ in expected if url in {page["url"] for page in report["crawl"]["pages"]})
    assert totals["not_listed"] == [] and "not listed here" not in markdown + printed  # the full lists were at hand


def test_a_report_saved_before_the_problem_summary_gets_the_same_table_derived_and_its_saved_files_are_not_rewritten(demo_app):
    one = audit(demo_app, demo.CAFE)
    report = get(demo_app, one, "/result")
    folder = demo_app.app.state.runner.artifacts(one["id"])
    older = {key: value for key, value in report.items() if key not in ("problem_summary", "audit_status")}
    older["schema_version"] = "1.5"
    # Shown through the adapter alone, with no saved lists: the table is derived from the pages the report itself names.
    view = summary.build(older, outcome="COMPLETED", reason="as saved")
    from maya_audit_web import pdf
    html = pdf.render_html(view, rows=summary.search(older, limit=100_000)["items"], plan=summary.action_plan(older), generated_at="2026-10-10T00:00:00+00:00")
    assert "<h2>Problems by page</h2>" in html and view["headline"] in html and view["problem_summary"]["problems"] == report["problem_summary"]["problems"]
    # With the full lists saved beside the report, the same engine function gives exactly what a new report holds.
    full = summary.build(older, outcome="COMPLETED", reason="as saved", affected=json.loads((folder / "affected-urls.json").read_text(encoding="utf-8")))
    assert full["problem_summary"] == report["problem_summary"] and full["headline"] == get(demo_app, one, "/summary")["headline"]

    # The same audit as an older saved one on disk: it opens, the table is derived, and the files stay as they were.
    (folder / "report.json").write_text(json.dumps(older, ensure_ascii=False), encoding="utf-8")
    before = {name: (folder / name).read_bytes() for name in ("report.json", "report.md", "affected-urls.json")}
    shown = get(demo_app, one, "/summary")
    printed = demo_app.get(f"{API}/audits/{one['id']}/print?full=true").text
    assert shown["schema_version"] == "1.5" and shown["problem_summary"] == report["problem_summary"]
    assert shown["practical"]["by_page"]["rows"] and get(demo_app, one, "/practical")["by_page"] == shown["practical"]["by_page"]
    assert "<h2>Problems by page</h2>" in printed and shown["headline"] in printed
    assert demo_app.get(f"{API}/audits/{one['id']}/downloads/json").content == before["report.json"]
    assert {name: (folder / name).read_bytes() for name in before} == before and "problem_summary" not in json.loads(before["report.json"])


def test_pages_missing_from_an_older_reports_lists_are_said_on_the_card_the_printed_page_and_in_the_markdown(demo_app):
    from maya_audit.report import problems_by_page_lines
    from maya_audit_web import pdf

    one = audit(demo_app, demo.CAFE)
    older = {key: value for key, value in get(demo_app, one, "/result").items() if key != "problem_summary"}
    older["schema_version"] = "1.8"
    cut = next(f for check in older["checks"] for f in check["findings"] if f["severity"] != "Info" and f["scope"]["kind"] != "sitewide")
    # A made-up older finding: 40 pages affected, the first 25 listed, and no full list saved beside the report.
    cut["scope"] = {"kind": "template", "count": 40, "urls": [f"http://{demo.CAFE}/made-up-{n}" for n in range(25)]}
    view = summary.build(older, outcome="COMPLETED", reason="as saved")
    assert {"finding_id": cut["id"], "pages": 15} in view["problem_summary"]["not_listed"]
    line = f"“{cut['title']}” also affects 15 more pages not listed here."
    rows = summary.search(older, limit=100_000)["items"]
    html = pdf.render_html(view, rows=rows, plan=summary.action_plan(older), generated_at="2026-10-10T00:00:00+00:00")
    from html import escape
    assert escape(line, quote=True) in html
    from maya_audit_web import practical
    assert line in [entry["line"] for entry in practical.build(view, rows, older, None)["by_page"]["not_listed"]]
    assert line in problems_by_page_lines(view["problem_summary"], {row["id"]: row["title"] for row in rows}, f"http://{demo.CAFE}")


def test_the_executive_page_says_how_many_pages_once_in_the_headline_and_then_only_what_could_not_be_checked(demo_app):
    import re
    from html import escape

    one = audit(demo_app, demo.CAFE)
    view = get(demo_app, one, "/summary")
    printed = demo_app.get(f"{API}/audits/{one['id']}/print?full=true").text
    page = printed[printed.index('<section class="exec'):]
    page = page[:page.index("</section>")]
    pages, gaps = view["counts"]["pages_checked"], len(view["coverage"]["gaps"])
    assert pages > 1 and gaps > 1 and f"across assessed scope; {pages} pages read for content" in view["headline"] and escape(view["headline"], quote=True) in page
    # The engine's own sentences (the outcome's reason and the notes of "What this audit covers") are printed as the report
    # holds them and may name the count themselves; the sentences this layer writes name it once, in the headline.
    own = page
    # Finding titles are the engine's words too ("12 pages have no viewport meta tag" names its own count).
    raw_titles = [f["title"] for c in get(demo_app, one, "/result")["checks"] for f in c["findings"]]
    titles = [t.replace("(s)", s) for t in raw_titles for s in ("", "s")]  # the page shows "page(s)" as page/pages
    for engine_text in [view["outcome"]["reason"], *(row["note"] for row in view["status"]["rows"]), *titles]:
        own = own.replace(escape(engine_text or "", quote=True), "")
    said = [own[max(0, found.start() - 90):found.end() + 30] for found in re.finditer(rf"(?<!Affects )\b{pages} page", own)]  # a finding's own scope may equal the total
    assert len(said) == 1 and "pages checked." not in own and "were checked" not in own, said
    assert view["gaps_line"] == f"{gaps} parts could not be checked; see “What could not be checked”." and escape(view["gaps_line"], quote=True) in page
    assert view["coverage"]["sampled_note"] == "The pages checked are evidence about those pages, not proof about every page of the site."
    assert view["coverage"]["sampled_note"] in page
    assert view["summary_line"] == f"{pages} pages checked. {gaps} parts could not be checked."  # still in the API, for whoever reads it
    from maya_audit_web import strings
    assert strings.t("result.gaps_line", gaps=1) == "1 part could not be checked; see “What could not be checked”."
    assert strings.t("result.gaps_line", "tr", gaps=3) == "3 bölüm kontrol edilemedi; “Kontrol edilemeyenler” bölümüne bakın."
    assert strings.t("result.sampled_note", "tr") == "Kontrol edilen sayfalar o sayfalar hakkında kanıttır; sitenin her sayfası hakkında kanıt değildir."
    # Nothing left out: no line at all, not "0 parts could not be checked".
    report = get(demo_app, one, "/result")
    answered = {**report, "answer_engine_panel": [], "checks": [{**check, "coverage": {}, "status": "pass" if check["status"] == "not_assessed" else check["status"]}
                                                                for check in report["checks"]]}
    whole = summary.build(answered, outcome="COMPLETED", reason="as saved")
    assert whole["coverage"]["gaps"] == [] and whole["gaps_line"] is None
    from maya_audit_web import pdf
    html = pdf.render_html(whole, rows=summary.search(answered, limit=100_000)["items"], plan=summary.action_plan(answered), generated_at="2026-10-11T00:00:00+00:00")
    assert "could not be checked; see" not in html and whole["coverage"]["sampled_note"] in html


def test_the_demo_names_a_site_for_each_repair(demo_app):
    sites = {row["address"]: row["about"] for row in demo_app.get(f"{API}/session").json().get("demo_sites", [])} or dict(demo.SITES)
    assert {demo.SHOP, demo.CAFE, demo.BANK, demo.VAULT, demo.FORTRESS, demo.PARTIAL, demo.APP} <= set(sites)
    assert "measurements missing" in sites[demo.PARTIAL] and "true zeros" in sites[demo.APP]
