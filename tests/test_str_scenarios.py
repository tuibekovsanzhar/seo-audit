"""STR-1..STR-10 against local fake websites."""

import pytest

from fakeserver import FakeServer
from fakeserver.str_scenarios import FAST_STR, entity_site, external_site
from maya_audit.audit import run_audit
from maya_audit.config import CrawlConfig


def names(item):
    """Paths without the leading slash; the homepage is "/"."""
    return sorted(u.split("//", 1)[1].split("/", 1)[1] or "/" for u in item.scope["urls"])


def only(findings, text):
    [match] = [f for f in findings if text in f.title]
    return match


def test_titles(run_audit_scenario):
    run = run_audit_scenario("str_pages")
    f = run.checks["STR-1"].findings
    assert names(only(f, "have no <title>")) == ["no-title"]
    dup = only(f, "shared by")
    assert names(dup) == ["dup-a", "dup-b"]  # noindex copy and canonicalized copy are not counted
    generic = only(f, "generic title")
    assert names(generic) == ["brand", "welcome"]  # homepage may use the site name alone
    assert {p["why"] for p in generic.evidence["pages"]} == {"the site name alone", "a generic placeholder title"}
    assert all(x.severity.value == "S4" and x.rationale == "Hypothesis" for x in f)

    h = run.checks["STR-2"]
    assert names(only(h.findings, "no <h1>")) == ["no-h1"]  # the client-rendered shell is RND-1's root cause
    assert any(u.endswith("/csr-shell") for u in h.evidence["excluded_as_rnd1_root_cause"])
    assert names(only(h.findings, "no subheadings")) == ["long"]
    multi = only(h.findings, "more than one <h1>")
    assert names(multi) == ["multi-h1"] and multi.severity.value == "Info"
    assert h.observations[0]["question_headings"] == 3 and h.observations[0]["subheadings"] == 5

    assert names(only(run.checks["STR-9"].findings, "no <html lang>")) == ["no-lang"]

    p = run.checks["STR-10"].findings
    dead = only(p, "og:image that returns 404")
    assert names(dead) == ["features"] and dead.severity.value == "S4" and dead.confidence.value == "verified"
    assert names(only(p, "no og:title")) == ["no-h1"] and names(only(p, "no meta description")) == ["no-title"]
    assert run.checks["STR-5"].status == "pass"  # "Product analytics" title segment is not a brand variant


def test_structured_data_presence(run_audit_scenario):
    run = run_audit_scenario("str_structured_data")
    f = run.checks["STR-3"].findings
    parse = only(f, "does not parse")
    assert names(parse) == ["products/broken-json"] and '"name": "Broken",}' in parse.evidence["pages"][0]["blocks"][0]["snippet"]
    org = only(f, "no Organization")
    assert org.severity.value == "S3" and names(org) == ["/"]  # Medium: the homepage says who the site belongs to
    required = only(f, "Google-required properties")
    assert required.severity.value == "Info"
    assert required.evidence["items"] == [{"url": run.url("/products/incomplete"), "type": ["Product"],
                                           "missing": ["one of offers / review / aggregateRating"]}]
    expected = only(f, "expected for their page kind")
    assert expected.confidence.value == "estimated"
    assert names(expected) == ["blog/tr-yazi", "blog/undated", "pricing", "products/broken-json"]


def test_structured_data_vs_visible(run_audit_scenario):
    run = run_audit_scenario("str_structured_data")
    check = run.checks["STR-4"]
    by = {(f.title.split("structured-data ")[1].split(" differs")[0], f.confidence.value): f for f in check.findings}
    assert set(by) == {("price", "verified"), ("currency", "verified"), ("availability", "estimated"),
                       ("date", "verified"), ("rating", "verified"), ("author", "estimated"),
                       ("product name", "estimated")}
    # Verified price/currency stay High; estimated availability has the owner's Medium ceiling.
    assert {field: f.severity.value for (field, _), f in by.items()} == {
        "price": "S2", "currency": "S2", "availability": "S3", "date": "S3", "rating": "S3", "author": "S3",
        "product name": "S3"}
    assert names(by[("price", "verified")]) == ["products/micro", "products/pro-widget"]  # Microdata and JSON-LD
    assert by[("price", "verified")].severity.value == "S2"
    assert names(by[("currency", "verified")]) == ["products/euro-widget"]
    assert names(by[("availability", "estimated")]) == ["products/sold-widget"]
    assert by[("availability", "estimated")].severity.value == "S3"
    assert names(by[("date", "verified")]) == ["blog/launch"] and by[("date", "verified")].severity.value == "S3"
    assert sorted(v["property"] for v in by[("date", "verified")].evidence["values"]) == ["dateModified", "datePublished"]
    assert names(by[("rating", "verified")]) == ["products/rated-widget"]
    assert names(by[("author", "estimated")]) == ["blog/byline"]
    assert names(by[("product name", "estimated")]) == ["products/renamed"]
    # Consistent pages, including the Turkish price "₺1.299,00" = 1299.00 TRY, are not reported.
    reported = {u for f in check.findings for u in names(f)}
    assert not reported & {"products/ok-widget", "products/tr-widget", "blog/future"}
    [review] = check.review_items
    assert names(review) == ["products/no-price-shown"] and "price" in review.title
    # Unlabelled dates on a page (testimonials, comments) are not the page's own: no conflict is claimed.
    assert not any("testimonials" in u for f in check.findings for u in f.scope["urls"])
    dates_not_assessed = [r for r in check.evidence["not_assessed"] if r["field"] == "date"]
    assert [r["url"].rsplit("/", 1)[-1] for r in dates_not_assessed] == ["testimonials", "testimonials"]
    assert "unlabelled dates" in dates_not_assessed[0]["reason"]

    [tr] = [r for r in check.evidence["not_assessed"] if r["field"] == "availability"]
    assert tr["url"].endswith("/products/tr-widget") and tr["field"] == "availability"


def test_freshness(run_audit_scenario):
    run = run_audit_scenario("str_structured_data")
    check = run.checks["STR-6"]
    assert names(only(check.findings, "future date")) == ["blog/future"]
    # Sitemap resource time versus editorial modification was the unsupported conflict here.
    assert not [f for f in check.findings if 'days apart' in f.title]
    assert check.observations[0]["value"] == 1
    undated = only(check.findings, "show no published")
    assert names(undated) == ["blog/undated"] and undated.severity.value == "Info"
    assert [r["url"].rsplit("/", 1)[-1] for r in check.evidence["not_assessed"]] == ["tr-yazi"]
    # /blog/launch has a date conflict reported by STR-4; STR-6 does not repeat it.
    assert not any(u.endswith("/blog/launch") for f in check.findings for u in f.scope["urls"])


def test_autostamp(run_audit_scenario):
    run = run_audit_scenario("str_autostamp")
    [stamp] = run.checks["STR-6"].findings
    assert "auto-stamped" in stamp.title and stamp.scope["kind"] == "sitewide" and stamp.scope["count"] == 6
    assert any("uncalibrated guesses" in n for n in stamp.notes)


def test_same_day_headers_are_one_sitewide_pattern_without_proving_a_cache_cause(run_audit_scenario):
    run = run_audit_scenario("str_stamped_headers")
    str6 = run.checks["STR-6"]
    stamps = {f.evidence["signal"]: f for f in str6.findings if "auto-stamped" in f.title}
    header = stamps["Last-Modified header"]
    assert header.evidence["pattern"] == "dated the audit day" and header.scope["kind"] == "sitewide"
    assert any("do not establish incorrect edit dates or a cache cause" in n for n in header.notes)
    assert stamps["schema dateModified"].evidence["pattern"] == "one identical date (2024-01-15)"
    # The shared date pattern is excluded from per-page conflicts without claiming a cache cause.
    assert not any("apart" in f.title for f in str6.findings)
    assert set(str6.evidence["stamped_signals_not_compared"]) == {"Last-Modified header", "schema dateModified"}


def test_images_and_grids(run_audit_scenario):
    run = run_audit_scenario("str_images_grids")
    alt = run.checks["STR-7"]
    meaningful = only(alt.findings, "likely meaningful")
    assert sorted(i["src"] for i in meaningful.evidence["images"]) == [
        "/img/f.png", "/img/product-detail.jpg", "/img/q3.png", "/img/revenue-chart.png"]
    assert next(i for i in meaningful.evidence["images"] if i["src"] == "/img/product-detail.jpg")["alt_state"] == "empty"
    assert meaningful.severity.value == "S4" and meaningful.confidence.value == "estimated"
    other = only(alt.findings, "other image")
    assert sorted(i["src"] for i in other.evidence["images"]) == ["/icons/check.svg", "/img/x1.jpg"]
    assert other.severity.value == "Info"
    obs = alt.observations[0]
    assert (obs["missing"], obs["empty_alt"], obs["total"], obs["left_to_RND-4_as_possible_image_of_text"]) == (6, 3, 10, 1)
    assert any(item["part"] == "images with empty alt text and unknown purpose"
               for item in alt.coverage["not_assessed"])
    rnd4 = [i["src"] for f in run.checks["RND-4"].findings for i in f.evidence["items"]]
    assert rnd4 == ["/img/banner.png"]  # the banner is reported once, by RND-4

    grids = run.checks["STR-8"]
    pricing = only(grids.findings, "pricing or spec")
    assert names(pricing) == ["pricing"] and pricing.severity.value == "S4"
    assert pricing.evidence["grids"][0]["sample_rows"][1] == ["Price", "$9/mo", "$49/mo"]
    other_grid = only(grids.findings, "other table-like")
    assert names(other_grid) == ["integrations"] and other_grid.severity.value == "Info"
    # Footer link columns, prose cards, and a real <table> are not grids.
    assert not {"cards", "table-pricing", "/"} & {u for f in grids.findings for u in names(f)}
    assert grids.observations[0]["sample"][0]["items"] == 3


def test_traditional_metadata_and_heading_quality_uses_advisory_bands(run_audit_scenario):
    run = run_audit_scenario("traditional_seo_quality")
    check = run.checks["TSEO-1"]
    assert check.status == "findings"
    titles = [finding.title for finding in check.findings]
    assert any("below the 10-character" in title for title in titles)
    assert any("above the 60-character" in title for title in titles)
    assert any("below the 70-character" in title for title in titles)
    assert any("above the 160-character" in title for title in titles)
    [heading] = [finding for finding in check.findings if "heading level jump" in finding.title]
    assert heading.confidence.value == "verified"
    assert heading.severity.value == "S4"
    assert "next heading level" in heading.how_to_fix
    assert any("not Google limits" in note for finding in check.findings for note in finding.notes)
    # The scenario's pages have no viewport (H32, its own finding); the bands and headings are what is tested here.
    reported_urls = {url for finding in check.findings if "viewport" not in finding.title for url in finding.scope["urls"]}
    assert run.url("/clean") not in reported_urls  # valid lengths and sequential headings are a near miss


def test_incomplete_traditional_check_is_partial_not_a_pass(run_audit_scenario):
    run = run_audit_scenario("traditional_seo_quality", max_pages=1)
    check = run.checks["TSEO-1"]
    assert check.status in ("partial", "findings")  # not a pass; "findings" since the pages have no viewport (H32)
    assert any(item["part"] == "discovered pages not fetched" for item in check.coverage["not_assessed"])


def test_image_alt_coverage_reports_extraction_cap_as_partial(run_audit_scenario):
    run = run_audit_scenario("str_images_over_cap", image_checks_max=0)  # the fake site serves no image files
    check = run.checks["STR-7"]
    # All 205 images are JPEGs, which is its own (Info) finding; nothing is found about alt text. (They also have no
    # width and height: H30's layout-shift note, left out here.)
    found = [f for f in check.findings if "layout shift" not in f.title]
    assert [f.severity.value for f in found] == ["Info"] and "WebP or AVIF" in found[0].title
    assert (check.observations[0]["missing"], check.observations[0]["total"]) == (0, 205)
    [gap] = [item for item in check.coverage["not_assessed"]
             if item["part"] == "image alt details beyond the extraction cap"]
    assert gap["count"] == 5


def run_entity(external: bool | None):
    """`external` None: the default, which checks links to other sites (DECISIONS 211)."""
    options = {} if external is None else {"check_external_links": external}
    with FakeServer(external_site(lambda: site.base_url)) as ext, FakeServer(entity_site(lambda: ext.base_url)) as site:
        outcome = run_audit(site.base_url + "/", CrawlConfig(**FAST_STR, **options))
        return outcome, list(site.requests), list(ext.requests), site.base_url, ext.base_url


@pytest.fixture(scope="module")
def entity_off():
    return run_entity(False)


@pytest.fixture(scope="module")
def entity_on():
    return run_entity(None)


def _checks(outcome):
    return {c.check_id: c for c in outcome.checks}


def test_with_external_links_off_only_the_same_as_links_leave_the_site(entity_off):
    # --no-external-links (DECISIONS 211): og:image and hreflang on the other origin are not requested; sameAs profile
    # links still are, after that site's robots.txt, as DECISIONS 196 does for a link to another site.
    outcome, site_requests, ext_requests, base, ext = entity_off
    paths = [r.path for r in ext_requests]
    assert paths[0] == "/robots.txt" and set(paths) <= {"/robots.txt", "/company/acme", "/gone"}
    assert "/blocked/profile" not in paths and "/img/og.png" not in paths and "/fr/guide" not in paths
    assert not [r.path for r in site_requests if r.path.startswith("/private/")]
    checks = _checks(outcome)
    str5 = checks["STR-5"]
    assert [l["sameAs"] for l in only(str5.findings, "404/410").evidence["links"]] == [f"{ext}/gone"]
    reasons = {r["sameAs"]: r["reason"] for r in str5.evidence["sameAs_not_assessed_or_inconclusive"]}
    assert "robots.txt" in reasons[f"{ext}/blocked/profile"]
    assert "not assessed" in str5.summary
    str10 = checks["STR-10"]
    # Nothing wrong was found, but the og:image on the other origin was never requested: that is not a pass.
    # Not a pass ("findings" when the scenario's Twitter-card note, H32, is among them).
    assert str10.status in ("partial", "findings") and "not assessed" in str10.summary
    gap = str10.coverage["not_assessed"]
    assert [g["part"] for g in gap] == ["og:image URLs"] and gap[0]["count"] >= 1
    targets = {r["target"]: r["reason"] for r in checks["STR-9"].evidence["hreflang_targets_not_assessed"]}
    assert "--no-external-links" in targets[f"{ext}/fr/guide"]
    assert "robots.txt" in targets[f"{base}/private/es-guia"]
    assert {g.check_id: g.state for g in outcome.gates}["INT-4"] == "compliant"


def test_entity_and_links_with_external_checks(entity_on):
    outcome, site_requests, ext_requests, base, ext = entity_on
    paths = [r.path for r in ext_requests]
    assert paths[0] == "/robots.txt"  # robots.txt first on the other origin
    assert "/blocked/profile" not in paths  # disallowed there
    assert set(paths) == {"/robots.txt", "/fr/guide", "/img/og.png", "/img/missing.png", "/company/acme", "/gone"}
    # One user agent, besides ACC-4's tagged browser/Googlebot check on the audited site (DECISIONS 205).
    assert {r.user_agent for r in site_requests + ext_requests if not r.headers.get("x-maya-probe")} == {outcome.result.user_agent}
    assert not [r for r in ext_requests if r.headers.get("x-maya-probe")]
    int4 = {g.check_id: g for g in outcome.gates}["INT-4"]
    assert int4.state == "compliant", int4.summary
    # sameAs links are asked with a HEAD (DECISIONS 211); this fake server does not take HEAD (501), so each is asked
    # again once as a GET, beside the GETs of the og:images and the hreflang alternate.
    assert int4.evidence["requests_by_purpose"]["external_link_head"] == 2
    # (The server's library answers HEAD with 501 before the fake site records a request, so only the GETs show here.)
    assert [r.method for r in ext_requests if r.path in ("/company/acme", "/gone")] == ["GET", "GET"]
    assert int4.evidence["requests_by_purpose"]["external_link_status"] == 5

    checks = _checks(outcome)
    str5 = checks["STR-5"]
    variants = only(str5.findings, "named")
    assert variants.severity.value == "S4" and variants.confidence.value == "estimated"
    # Customer logos in main content and the links after the © line must not become brand variants
    # (both seen on the first live crawl of a real site).
    assert sorted(v["normalized"] for v in variants.evidence["variants"]) == ["acme", "acme analytics", "acmehq"]
    footer = next(s for s in str5.evidence["name_sources"] if s["source"] == "footer legal name")
    assert footer["value"] == "Acme Analytics, Inc"
    assert not any("volkswagen" in v["normalized"] for v in variants.evidence["variants"])
    # A customer's Organization markup on a case-study page is not this site's brand name: the first
    # 50-page live audit collected 237 "variants" this way, every one another company.
    assert not any("globex" in v["normalized"] for v in variants.evidence["variants"])
    assert not any("globex" in (s.get("value") or "").casefold() for s in str5.evidence["name_sources"])
    dead = only(str5.findings, "404/410")
    assert [l["sameAs"] for l in dead.evidence["links"]] == [f"{ext}/gone"]
    blocked = {r["sameAs"]: r["reason"] for r in str5.evidence["sameAs_not_assessed_or_inconclusive"]}
    assert "robots.txt" in blocked[f"{ext}/blocked/profile"]
    assert str5.evidence["organization_schema_on_homepage"] is True

    str9 = checks["STR-9"]
    broken = only(str9.findings, "do not return 200")
    assert [l["target"] for l in broken.evidence["links"]] == [f"{base}/de/anleitung"]
    one_way = only(str9.findings, "not returned")
    assert [l["target"] for l in one_way.evidence["links"]] == [f"{base}/tr/rehber"]  # the external fr page links back
    mismatch = only(str9.findings, "does not match the content language")
    assert names(mismatch) == ["tr/rehber"] and mismatch.evidence["pages"][0]["detected"] == "tr"
    assert names(only(str9.findings, "malformed hreflang")) == ["en/guide"]
    assert names(only(str9.findings, "relative hreflang")) == ["en/guide"]

    dead_og = only(checks["STR-10"].findings, "og:image")
    assert names(dead_og) == ["about"]


def test_markup_that_contradicts_itself(run_audit_scenario):
    run = run_audit_scenario("str_markup_contradictions")
    str11 = run.checks["STR-11"]
    by = {(f.title.rsplit(" ", 1)[-1], f.confidence.value): f for f in str11.findings}
    price = by[("price", "inferred")]
    assert price.severity.value == "S3" and names(price) == ["two-prices"]
    row = price.evidence["contradictions"][0]
    assert row["grouped_by"] == "type and name"
    assert sorted(v for d in row["descriptions"] for v in d["value"]) == ["49", "59"]
    assert {d["format"] for d in row["descriptions"]} == {"json-ld", "microdata"}
    assert any("same type and name" in n for n in price.notes)
    availability = by[("availability", "verified")]
    assert names(availability) == ["same-id"] and availability.severity.value == "S2"
    dates = [f for f in str11.findings if "datePublished" in f.title]
    assert [names(f) for f in dates] == [["article"]] and dates[0].severity.value == "S3"
    # Near misses: agreeing descriptions and two different products never fire.
    fired = {n for f in str11.findings for n in names(f)}
    assert not fired & {"consistent", "two-products", "left-to-str4", "two-ids"}
    # Root cause once: the stale JSON-LD price that the page contradicts is STR-4's.
    assert [r["url"].rsplit("/", 1)[-1] for r in str11.evidence["left_to_STR-4"]] == ["left-to-str4"]
    assert any(n == ["left-to-str4"] for f in run.checks["STR-4"].findings for n in [names(f)])
    # An unparseable block is a gap in what was compared, not a clean result.
    assert [g["part"] for g in str11.coverage["not_assessed"]] == ["structured data in JSON-LD that does not parse"]


def test_structured_data_graph_and_entity_identity(run_audit_scenario):
    run = run_audit_scenario("str_entity_graph")
    str3 = {f.title: f for f in run.checks["STR-3"].findings}
    broken = next(f for t, f in str3.items() if "returns an error" in t)
    assert broken.severity.value == "S4" and names(broken) == ["post"]
    assert broken.evidence["items"][0]["markup_url_status"] == 404
    mismatch = next(f for t, f in str3.items() if "different URL" in t)
    assert mismatch.severity.value == "Info" and names(mismatch) == ["product"]
    dangling = next(f for t, f in str3.items() if "no crawled page defines" in t)
    assert [i["reference"].rsplit("/", 1)[-1] for i in dangling.evidence["items"]] == ["#jane"]
    clash = next(f for t, f in str3.items() if "different types" in t)
    assert clash.evidence["items"][0]["types"] == ["Organization", "Person"]
    fired = {n for f in run.checks["STR-3"].findings for n in names(f)}
    assert "clean" not in fired  # a self url and resolving references are fine

    str5 = run.checks["STR-5"]
    [ids] = [f for f in str5.findings if "@id" in f.title]
    assert ids.confidence.value == "verified"
    assert set(ids.evidence["clashes"][0]["names"]) == {"Acme", "Acme Analytics Ltd"}
    assert {"source": "WebSite name", "value": "Acme", "url": run.url("/")} in str5.evidence["name_sources"]
