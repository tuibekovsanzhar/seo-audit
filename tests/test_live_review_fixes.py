"""Five corrections from the first real audit run through the web app (2026-10-07). Offline: fake server only.

Each has the case that was wrong, and the neighbouring case that must stay as it was.
"""
import json

from maya_audit.coverage import CRAWL_GAP, CRAWL_GAP_NAMES
from maya_audit.report import build_report
from maya_audit_web import catalog, summary
from test_review_fixes import TR, audit, links, page, short

LONG = f"<p>{TR}</p><p>{TR}</p><p>{TR}</p><p>{TR}</p>"


# a. ACC-2: the signed-in app, its API and dashboard are private paths ------------------------------------------
def test_acc2_treats_app_api_and_dashboard_paths_as_private_unless_the_site_puts_them_forward():
    private = ["/app/settings/mcp", "/dashboard/reports", "/api/v1", "/admin/users", "/account/billing", "/sign-in", "/login",
               "/uygulama/ayarlar", "/kontrol-paneli/ozet", "/oturum-ac"]
    robots = "User-agent: *\n" + "".join(f"Disallow: /{name}\n" for name in (
        "app/", "dashboard/", "api/", "admin/", "account/", "sign-in", "login", "uygulama/", "kontrol-paneli/", "oturum-ac", "blog/"))
    home = page(f"<h1>Yazılım</h1>{LONG}" + links(private + ["/app/pricing-calculator", "/blog/yazi", "/urunler"]))
    outcome = audit({"/": home, "/urunler": page(f"<h1>Ürünler</h1>{LONG}")}, robots=robots,
                    sitemap=["/", "/urunler", "/app/pricing-calculator"])  # the site lists one /app/ page as a page to find
    search = [f for f in outcome.by_id["ACC-2"].findings if "search bot" in f.title]
    by_severity = {}
    for finding in search:
        by_severity.setdefault(finding.severity.value, set()).update(short(outcome, finding.scope["urls"]))
    assert by_severity["Info"] == set(private)  # housekeeping, in English and Turkish
    assert by_severity["S3"] == {"/blog/yazi"}  # an ordinary page behind a rule is still Medium
    assert by_severity["S1"] == {"/app/pricing-calculator"}  # in the sitemap: the site itself puts it forward
    info = next(f for f in search if f.severity.value == "Info" and "/app/" in f.title)
    assert info.evidence["path_kind"] == {"kind": "private_or_technical", "matched_segments": ["app"]}
    assert any("private or technical one (app)" in note for note in info.notes)
    assert not [f for f in outcome.by_id["ACC-2"].findings if f.severity.value == "S3" and set(short(outcome, f.scope["urls"])) & set(private)]


# b. RND-4: a canvas in the layout is one note; a page's own canvas is still a finding -------------------------
def canvas_site(layout_on, chart_on=()):
    routes = {}
    for n in range(1, 8):
        path = f"/sayfa-{n}/"
        body = f"<h1>Sayfa {n}</h1>{LONG}"
        if n in layout_on:
            body += "<canvas></canvas>"
        if n in chart_on:
            body += '<canvas id="sales-chart"></canvas>'
        routes[path] = page(body)
    return routes


def test_rnd4_reports_a_canvas_found_on_most_pages_once_as_a_note():
    outcome = audit(canvas_site(layout_on=range(1, 8), chart_on=(3,)), image_checks_max=0)
    findings = {f.severity.value: f for f in outcome.by_id["RND-4"].findings}
    note = findings["Info"]
    assert note.title == "The same <canvas> is on 7 of 8 page(s): part of the site's layout, with no text equivalent"
    assert note.scope["kind"] == "sitewide" and note.scope["count"] == 7 and note.confidence.value == "inferred"
    assert "nothing needs fixing" in note.how_to_fix and note.evidence["canvas"] == ["(no id or class)"]
    chart = findings["S4"]  # the one page with a canvas of its own is still flagged, and only that page
    assert chart.title == "1 page(s) draw content on a <canvas> with no text equivalent"
    assert short(outcome, chart.scope["urls"]) == ["/sayfa-3/"] and chart.evidence["items"] == [
        {"url": outcome.base + "/sayfa-3/", "canvas": "sales-chart"}]
    assert '"_mark"' not in json.dumps(build_report(outcome.result, outcome.gates, outcome.checks))


def test_rnd4_still_flags_canvases_that_only_some_pages_have_and_small_sites():
    some = audit(canvas_site(layout_on=(1, 2)), image_checks_max=0)
    [finding] = some.by_id["RND-4"].findings
    assert finding.severity.value == "S4" and finding.title.startswith("2 page(s) draw content on a <canvas>")
    small = audit({"/a/": page(f"<h1>A</h1>{LONG}<canvas></canvas>"), "/b/": page(f"<h1>B</h1>{LONG}<canvas></canvas>")}, image_checks_max=0)
    [finding] = small.by_id["RND-4"].findings  # three pages are too few to call anything site-wide
    assert finding.severity.value == "S4" and finding.scope["count"] == 2


# c. STR-7: the image-format note explains file size, not alt text ------------------------------------------------
def test_the_webp_note_has_its_own_explanation():
    formats = catalog.note("STR-7", "24% of 84 content image(s) are offered in WebP or AVIF")
    alt = catalog.note("STR-7", "12 likely meaningful image(s) on 4 page(s) have missing or empty alt text")
    assert "do not establish delivered" in formats["why"] and "byte sizes" in formats["why"] and "not guaranteed" in formats["why"] and "Alt text" not in formats["why"]
    assert formats["owner"] == "developer" and "Alt text" in alt["why"] and alt["owner"] == "content"
    assert "gap" in catalog.note("STR-7", "3 of 20 sampled image file(s) do not load")["why"]
    row = summary.item({"id": "STR-7-x", "check_id": "STR-7", "title": "24% of 84 content image(s) are offered in WebP or AVIF",
                        "severity": "Info", "confidence": "estimated", "scope": {"kind": "template", "count": 22, "urls": []},
                        "evidence": {"format_counts": {"webp": 20, "jpeg": 64}}})
    assert "different scopes" in row["why"] and "unassessed" in row["title"] and row["requires_fix"] is False
    assert "pixels" in catalog.note("RND-4", "The same <canvas> is on 43 of 50 page(s): part of the site's layout, with no text equivalent")["why"]


# d. "The crawl was incomplete" is said once, and says the checks ran -------------------------------------------
def test_an_incomplete_crawl_is_worded_as_checks_that_ran_on_the_pages_read_and_shown_once():
    outcome = audit({f"/sayfa-{n}/": page(f"<h1>Sayfa {n}</h1>{LONG}") for n in range(1, 13)}, max_pages=4, image_checks_max=0)
    report = build_report(outcome.result, outcome.gates, outcome.checks)
    assert report["page_counts"]["pages_checked"] == 4 and len(report["crawl"]["not_fetched_urls"]) == 9
    parts = [(check["check_id"], part) for check in report["checks"] for part in check["coverage"]["not_assessed"]
             if part["part"] in CRAWL_GAP_NAMES]
    assert len(parts) > 25 and {part["part"] for _, part in parts} == {CRAWL_GAP} == {"pages found but not read"}
    reason = parts[0][1]["reason"]
    assert reason.startswith("this check ran on the 4 page(s) that were read; 9 more page(s) were found and not read (page cap of 4 reached)")
    assert "not checked" not in reason and parts[0][1]["count"] == 9
    assert all(check["status"] != "not_assessed" or not any(p["part"] in CRAWL_GAP_NAMES for p in check["coverage"]["not_assessed"])
               for check in report["checks"])  # a check that got this note did run

    view = summary.build(report, outcome="INCOMPLETE", reason="page cap")
    coverage = view["coverage"]
    assert coverage["read_only_note"].startswith("Covered only the 4 pages read; 9 found pages were not read.")
    assert f"The {len(parts)} checks that read pages all ran, on those pages only." in coverage["read_only_note"]
    assert not [gap for gap in coverage["gaps"] if gap["part"] in CRAWL_GAP_NAMES]  # no row listing every check ID
    assert view["counts"]["not_checked"] == len(coverage["gaps"]) < len(parts)
    assert all(len(gap["checks"]) < 10 for gap in coverage["gaps"])
    # A report saved before the rewording says the same thing in the old words; it is shown the new way too.
    old = json.loads(json.dumps(report).replace(CRAWL_GAP, "pages not checked because the crawl was incomplete"))
    assert summary.build(old, outcome="INCOMPLETE", reason="page cap")["coverage"] == coverage


def test_a_complete_crawl_has_no_read_only_note():
    outcome = audit({"/a/": page(f"<h1>A</h1>{LONG}")}, image_checks_max=0)
    report = build_report(outcome.result, outcome.gates, outcome.checks)
    assert summary.build(report, outcome="COMPLETED", reason="")["coverage"]["read_only_note"] is None


# e. STR-4: a price the page shows in another state is not a conflict ---------------------------------------------
def pricing(offers, visible):
    ld = {"@context": "https://schema.org", "@type": "SoftwareApplication", "name": "Örnek", "applicationCategory": "BusinessApplication",
          "offers": [{"@type": "Offer", "name": name, "price": str(price), "priceCurrency": "USD", "category": category}
                     for name, price, category in offers]}
    body = "<h1>Pricing</h1><p>Monthly Yearly -17%</p>" + "".join(f"<h2>{plan}</h2><p>{price} / mo</p>" for plan, price in visible) + LONG
    return page(body, lang="en", head=f'<script type="application/ld+json">{json.dumps(ld)}</script>', title="Pricing")


BOTH_PERIODS = [("Starter (monthly)", 99, "monthly subscription"), ("Starter (yearly)", 990, "annual subscription"),
                ("Premium (monthly)", 399, "monthly subscription"), ("Premium (yearly)", 3990, "annual subscription"),
                ("Enterprise (monthly)", 899, "monthly subscription"), ("Enterprise (yearly)", 8990, "annual subscription")]


def test_str4_markup_listing_monthly_and_yearly_prices_is_a_review_item_not_a_conflict():
    outcome = audit({"/pricing": pricing(BOTH_PERIODS, [("Starter", "$99"), ("Premium", "$399")])}, image_checks_max=0)
    check = outcome.by_id["STR-4"]
    assert [f for f in check.findings if "price" in f.title] == []  # was: an S2 "price differs" with four values
    [item] = [r for r in check.review_items if "did not show" in r.title]
    assert item.title == "1 page(s): the markup lists 4 price(s) the page did not show when it was read"
    assert "monthly/yearly switch" in item.why_review and "not a conflict" in item.why_review and item.confidence.value == "inferred"
    rows = {row["schema_value"]: row for row in item.evidence["values"]}
    assert set(rows) == {"990", "3990", "899", "8990"} and all(row["outcome"] == "not_visible" and row["other_state"] for row in rows.values())
    assert rows["990"]["likely"] == "a yearly price: 990 is 10 × the 99 the page shows" and rows["990"]["offer"].startswith("Starter (yearly)")
    assert rows["3990"]["likely"].startswith("a yearly price: 3990 is 10 × the 399")
    assert rows["8990"]["likely"] == "a yearly price (the offer is named as yearly)" and "likely" not in rows["899"]
    matched = [row for row in check.evidence["price_comparisons"] if row["outcome"] == "match"]
    assert {row["schema_value"] for row in matched} == {"99", "399"} and check.status == "needs_review"
    assert '"_value"' not in json.dumps(build_report(outcome.result, outcome.gates, outcome.checks))


def test_str4_still_reports_a_markup_price_that_contradicts_a_price_on_the_page():
    stale = audit({"/pricing": pricing([("Starter", 89, "monthly"), ("Premium", 399, "monthly")], [("Starter", "$99"), ("Premium", "$399")])},
                  image_checks_max=0)
    [finding] = [f for f in stale.by_id["STR-4"].findings if "price" in f.title]  # $99 is shown and nothing in the markup explains it
    assert finding.severity.value == "S2" and [row["schema_value"] for row in finding.evidence["values"]] == ["89"]
    assert not [r for r in stale.by_id["STR-4"].review_items if "did not show" in r.title]
    single = audit({"/urun": pricing([("Plan", 49, "monthly")], [("Plan", "$59")])}, image_checks_max=0)
    [finding] = [f for f in single.by_id["STR-4"].findings if "price" in f.title]
    row = finding.evidence["values"][0]
    assert finding.confidence.value == "verified" and [shown["text"] for shown in row["visible"]] == ["$59"]
    assert (row["schema_value"], row["schema_currency"], row["visible"][0]["where"]) == ("49", "USD", "main content")
