"""IDX-1..IDX-10 against local fake websites, HTTPS test servers, and fake Google/Bing APIs."""

import json
import socket

import pytest

from fakeserver import FakeServer
from fakeserver.idx_scenarios import IDX_SCENARIOS, bing_api, gsc_api, tls_sites

# The HTTPS test sites make their own throwaway certificates with `cryptography`, a test tool that is in the "dev"
# extra and not in "team". Without it these tests are skipped with this reason, not failed.
NEEDS_CERTIFICATES = 'the test tool "cryptography" is not installed (pip install -e ".[dev]")'
from maya_audit.audit import run_audit
from maya_audit.config import CrawlConfig
from maya_audit.intent import IntentMarking
from maya_audit.report import build_report


def names(finding_or_item):
    return sorted(u.rsplit("/", 1)[-1] for u in finding_or_item.scope["urls"])


@pytest.fixture
def idx(run_audit_scenario):
    return run_audit_scenario


def test_status_codes(idx):
    run = idx("idx_status_codes")
    found = {(f.severity.value, f.confidence.value): f for f in run.findings("IDX-1")}
    assert names(found[("S1", "verified")]) in (["broken-500"], ["drop"])
    s1_verified = [f for f in run.findings("IDX-1", "S1") if f.confidence.value == "verified"]
    assert sorted(n for f in s1_verified for n in names(f)) == ["broken-500", "drop"]
    timeout = found[("S3", "inferred")]
    assert names(timeout) == ["hang"] and "Vendors do not document" in timeout.notes[0]
    # A URL that times out on every attempt is IDX-1's only; PRF-1's intermittent-timeout finding must not repeat it.
    assert not any(u.endswith("/hang") for f in run.findings("PRF-1") for u in f.scope["urls"])
    # DECISIONS 278: the failing addresses are kept apart from the pages to edit (the scope).
    linked = found[("S2", "verified")]
    assert sorted(u.rsplit("/", 1)[-1] for u in linked.evidence["target_urls"]) == ["deleted", "gone", "sitemap-only-404"]
    assert "sitemap-only-404" in names(linked) and not {"deleted", "gone"} & set(names(linked))

    transient = [o for o in run.checks["IDX-1"].observations if "intermittent failure" in o["metric"]]
    assert [o["url"].rsplit("/", 1)[-1] for o in transient] == ["flaky-500"]
    persistent = next(f for f in s1_verified if names(f) == ["broken-500"])
    # "Every attempt" covers the crawl, the IDX-1 refetch, and both PRF rounds.
    assert [a["source"] for a in persistent.evidence["pages"][0]["attempts"]] == [
        "crawl", "idx_refetch", "prf_round_2", "prf_round_3"]
    assert {a["status"] for a in persistent.evidence["pages"][0]["attempts"]} == {500}

    # IDX-6: one finding per broken target; the transient 500 is not a broken link. A 4xx target IDX-1 already reports is
    # said there, with its links as a row (review H10): one dead URL, one finding.
    # (Links to an address that redirects are their own IDX-6 finding since DECISIONS 315.)
    broken_links = [f for f in run.findings("IDX-6") if "target" in f.evidence]
    targets = sorted(f.evidence["target"].rsplit("/", 1)[-1] for f in broken_links)
    assert targets == ["broken-500"]
    assert all(f.severity.value == "S3" for f in broken_links)
    assert broken_links[0].evidence["links"][0]["anchor"]
    [linked] = [f for f in run.findings("IDX-1") if "; linked from " in f.title]
    assert [row["target"].rsplit("/", 1)[-1] for row in linked.evidence["broken_links"]] == ["gone"]
    assert run.gates["INT-4"].state == "compliant"


def test_http_redirect_check_uses_the_audited_path(idx):
    """Found by the first live crawl: a site published under a subdirectory answers 404 at the origin
    root, which read as "no HTTP->HTTPS redirect" without ever testing a live URL."""
    run = idx("idx_status_codes")
    [host] = [h for h in run.checks["IDX-2"].evidence["hosts"] if h["role"] == "start"]
    checked = host["http_redirect"]["http_url"]
    assert checked.endswith(run.result.start_url.split(run.result.origin)[1] or "/")


def test_unreferenced_4xx_is_info(idx):
    run = idx("idx_start_404")
    [finding] = run.findings("IDX-1")
    assert finding.severity.value == "Info" and names(finding) == ["start-gone"]


def test_redirect_chains_and_loops(idx):
    run = idx("idx_redirects")
    [loops] = run.findings("IDX-3", "S1")
    assert len(loops.evidence["loops"]) == 2
    [chain] = run.findings("IDX-3", "S4")
    assert [h.rsplit("/", 1)[-1] for h in chain.evidence["chains"][0]["hops"]] == ["a", "b", "c"]
    [obs] = run.checks["IDX-3"].observations
    assert obs["metric"] == "internal links pointing at redirecting URLs" and obs["value"] == 3


def test_canonical_signals(idx):
    run = idx("idx_canonicals")
    findings = run.findings("IDX-4")
    by_title = {f.title: f for f in findings}
    broken = next(f for t, f in by_title.items() if "broken, noindexed" in t)
    assert broken.severity.value == "S2" and names(broken) == ["canon-broken", "canon-noindex"]
    assert next(f for t, f in by_title.items() if "conflicting" in t).severity.value == "S3"
    different = next(f for t, f in by_title.items() if "different content" in t)
    assert (different.severity.value, different.confidence.value, names(different)) == ("S3", "estimated", ["canon-different"])
    same = [f for t, f in by_title.items() if "same content" in t]
    assert {(f.confidence.value, tuple(names(f))) for f in same} == {
        ("verified", ("canon-redirect", "print-version")), ("estimated", ("near-copy",))}
    assert all(f.severity.value == "Info" for f in same)
    [review] = run.checks["IDX-4"].review_items
    assert names(review) == ["canon-offsite"] and run.checks["IDX-4"].status == "findings"


def test_canonical_marking(idx):
    marking = IntentMarking("m-canon", "IDX-4", "canonicalized", "/canon-different", marked_by="owner")
    run = idx("idx_canonicals", intent_markings=(marking,))
    marked = next(f for f in run.findings("IDX-4") if f.intent)
    assert names(marked) == ["canon-different"] and marked.severity.value == "Info"
    assert marked.intent["severity_otherwise"] == "S2"


def test_sitemap_health(idx):
    run = idx("idx_sitemap_health")
    # The two dead URLs are IDX-1's (review CR-28) and the noindex page ACC-3's, whose one finding says the sitemap
    # lists it (review G16): nothing is left for the share, so it is settled, not a third finding.
    assert run.findings("IDX-5", "S3") == []
    assert run.checks["IDX-5"].evidence["noindex_reported_under_acc3"]["count"] == 1
    assert "reported under IDX-1" in run.checks["IDX-5"].summary
    [noindex] = [f for f in run.findings("ACC-3") if "the sitemap lists" in f.title]
    assert names(noindex) == ["hidden"] and noindex.severity.value == "S3"
    [lastmod] = run.findings("IDX-5", "S4")
    assert "identical" in lastmod.title

    future = idx("idx_sitemap_future")
    [finding] = future.findings("IDX-5")
    assert "future" in finding.title and names(finding) == ["b"]


def test_a_sitemap_document_stamped_with_its_generation_time(idx):
    run = idx("idx_sitemap_stamped_docs")
    [stamped] = run.findings("IDX-5", "S4")
    assert "same <lastmod>" in stamped.title and stamped.confidence.value == "verified"
    assert stamped.scope["kind"] == "sitewide"  # a sitemap document is a file, not a page: it makes no page row (decision 170)
    [doc] = stamped.evidence["documents"]
    assert doc["sitemap"].endswith("/sitemap-products.xml") and doc["same_lastmod"] == 6
    assert doc["value"] == "2026-09-17T10:43:24+03:00"
    assert any("Inferred" in n for n in stamped.notes)
    # The whole-sitemap "identical" rule does not also fire: the posts document has real dates.
    assert not any("are identical" in f.title for f in run.findings("IDX-5"))


def test_a_latest_posts_list_does_not_make_a_trailing_slash_copy_different_content(idx):
    run = idx("idx_canonical_latest_posts")
    by_title = {f.title: f for f in run.findings("IDX-4")}
    same = next(f for t, f in by_title.items() if "same content" in t)
    assert names(same) == ["fund-guide"] and same.severity.value == "Info"
    row = same.evidence["pages"][0]
    assert 0.8 <= row["value"] < 1 and row["comparison"].startswith("share of words")
    assert any("freshpost0" in d["this_page"] for d in row["differing_blocks"])  # what differs is quoted
    different = next(f for t, f in by_title.items() if "different content" in t)
    assert names(different) == ["moved-guide"] and different.severity.value == "S3"
    assert different.evidence["pages"][0]["value"] < 0.8


def test_missing_sitemap_depends_on_site_size(idx):
    large = idx("idx_no_sitemap_large")
    [finding] = large.findings("IDX-5")
    assert finding.severity.value == "S3" and "61 discovered URLs" in finding.title  # Medium on a site of more than 50 URLs
    small = idx("idx_no_sitemap_small")
    assert small.checks["IDX-5"].status == "pass"


def test_orphans_depth_and_marking(idx):
    run = idx("idx_orphans_depth")
    [orphans] = run.findings("IDX-7", "S4")
    assert names(orphans) == ["campaign", "orphan"]
    [deep] = run.findings("IDX-7", "Info")
    assert names(deep) == ["l5"]

    marked = idx("idx_orphans_depth", intent_markings=(IntentMarking("m-camp", "IDX-7", "orphan", "/campaign"),))
    s4 = marked.findings("IDX-7", "S4")
    assert [names(f) for f in s4] == [["orphan"]]

    partial = idx("idx_orphans_depth", max_pages=3)
    assert "not assessed" in partial.checks["IDX-7"].evidence["orphans"]
    assert not partial.findings("IDX-7", "S4")


def test_duplicates(idx):
    run = idx("idx_duplicates")
    # One finding for both groups, a line a group (decision 225); the two pages that share a title are STR-1's finding,
    # once: their text differs, so they are in no group (decision 187).
    [merged] = run.findings("IDX-8")
    assert merged.title == "2 groups of indexable pages that are copies or near-copies of each other (4 pages)"
    assert (merged.confidence.value, tuple(names(merged))) == ("estimated", ("dup-a", "dup-b", "near-a", "near-b"))
    assert [g["signals"] for g in merged.evidence["duplicate_groups"]] == [["nearly_same"], ["same_text"]]
    assert all(f.severity.value == "S4" for f in run.findings("IDX-8"))
    assert not [f for f in run.findings("IDX-8") if "share the title" in f.title]
    shared = [f for f in run.findings("STR-1") if "title(s) are shared" in f.title]
    assert len(shared) == 1 and {"title-1", "title-2"} <= set(names(shared[0]))


def test_google_and_bing_index_status(tmp_path):
    scenario = IDX_SCENARIOS["idx_gsc_bing"]
    with FakeServer(scenario.build()) as site:
        with FakeServer(gsc_api(lambda: site.base_url)) as gsc, FakeServer(bing_api(lambda: site.base_url)) as bing:
            config = CrawlConfig(
                **{**scenario.config, "key_pages": tuple(site.base_url + p for p in scenario.config["key_pages"])},
                gsc_access_token="test-token", gsc_site_url=site.base_url + "/",
                gsc_endpoint=gsc.base_url + "/v1/urlInspection/index:inspect",
                bing_api_key="bing-key", bing_site_url=site.base_url + "/",
                bing_endpoint=bing.base_url + "/webmaster/api.svc/json", indexnow_key="wrongkey123",
            )
            outcome = run_audit(site.base_url + "/", config)
            gsc_requests, bing_requests = list(gsc.requests), list(bing.requests)
    checks = {c.check_id: c for c in outcome.checks}

    idx9 = checks["IDX-9"]
    found = {f.title.split(" (")[0]: f for f in idx9.findings}
    assert names(found["Google reports the page excluded by noindex"]) == ["docs"]
    assert names(found["Google reports: Crawled - currently not indexed"]) == ["pricing"]
    canonical = found["Google chose a different canonical than the page declares"]
    assert canonical.severity.value == "S3" and names(canonical) == ["about"]
    assert all(f.cost_tier == "T2" for f in idx9.findings)
    [review] = idx9.review_items
    assert review.evidence["inspections"][0]["coverageState"] == "URL is unknown to Google"
    assert [o["url"].rsplit("/", 1)[-1] for o in idx9.observations] == ["snippetless"]
    assert all(json.loads(r.body)["languageCode"] == "en-US" for r in gsc_requests)

    idx10 = checks["IDX-10"]
    assert "not assessed" in idx10.evidence["index_status"]
    [bing_review] = idx10.review_items
    assert names(bing_review) == ["docs"]
    [indexnow] = idx10.findings
    assert indexnow.severity.value == "Info"
    assert len(bing_requests) == 6

    report = json.dumps(build_report(outcome.result, outcome.gates, outcome.checks), default=str)
    assert "test-token" not in report and "bing-key" not in report
    assert {c.check_id: c for c in outcome.checks}["IDX-9"].status == "findings"
    assert next(g for g in outcome.gates if g.check_id == "INT-4").state == "compliant"


def test_without_connections_google_and_bing_are_not_assessed(idx):
    run = idx("idx_orphans_depth")
    assert run.checks["IDX-9"].status == "not_assessed" and "T2" in run.checks["IDX-9"].summary
    assert run.checks["IDX-10"].status == "not_assessed"


@pytest.fixture
def www_localhost_resolves(monkeypatch):
    """Pin `www.localhost` to loopback for one test instead of inheriting the machine's resolver.

    RFC 6761 reserves `.localhost`, but resolvers disagree about names *under* it: some machines
    answer for `www.localhost` and some do not, and it can change with the network. IDX-2 checks the
    www counterpart of the audited host and, when it does not resolve, records a note and skips it —
    correct behaviour, but it meant this test silently stopped exercising the variant check and
    failed on the assertion instead. Resolution is not what this test is about.

    `socket.getaddrinfo` is the single choke point: `inspect_tls` reaches it through
    `socket.create_connection`, the HTTP redirect check through httpx, and IDX-2's own guard calls
    it directly. Every other name still goes to the real resolver.
    """
    real_getaddrinfo = socket.getaddrinfo

    def getaddrinfo(host, port, *args, **kwargs):
        if isinstance(host, str) and host.lower() == "www.localhost":
            host = "127.0.0.1"
        return real_getaddrinfo(host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)


@pytest.fixture
def www_localhost_does_not_resolve(monkeypatch):
    """The opposite: make the variant unresolvable whatever the machine thinks."""
    real_getaddrinfo = socket.getaddrinfo

    def getaddrinfo(host, port, *args, **kwargs):
        if isinstance(host, str) and host.lower() == "www.localhost":
            raise socket.gaierror(socket.EAI_NONAME, "nodename nor servname provided, or not known")
        return real_getaddrinfo(host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)


@pytest.mark.parametrize("kind,redirect,expected", [
    ("valid", True, []),
    ("near_expiry", True, [("S3", "on localhost, www.localhost expires in 7")]),
    ("expired", True, [("S1", "not valid on localhost, www.localhost: certificate has expired")]),
    ("mismatch", True, [("S1", "not valid on localhost: Hostname mismatch"),
                        ("S1", "not valid on www.localhost: Hostname mismatch")]),
    ("variant_mismatch", True, [("S1", "not valid on www.localhost: Hostname mismatch")]),
    ("valid", False, [("S2", "No HTTP to HTTPS redirect on localhost, www.localhost")]),  # http:// answers 200: the site is served on both
])
def test_tls_and_https_redirect(kind, redirect, expected, www_localhost_resolves):
    pytest.importorskip("cryptography", reason=NEEDS_CERTIFICATES)
    with tls_sites(kind, redirect) as (https, http, ca_bundle):
        config = CrawlConfig(request_delay_s=0, robots_sample_interval_s=0.05, refetch_delay_s=0, prf_round_gap_s=0,
                             ca_bundle=ca_bundle, http_port=http.port, render_enabled=False)
        outcome = run_audit(https.base_url + "/", config)
        http_paths = [r.path for r in http.requests]
    idx2 = next(c for c in outcome.checks if c.check_id == "IDX-2")
    # Both the start host and its www variant must actually have been checked.
    assert [h["host"] for h in outcome.result.index.hosts] == ["localhost", "www.localhost"]
    assert outcome.result.index.variant_note is None
    got = [(f.severity.value, f.title) for f in idx2.findings]
    assert len(got) == len(expected), got
    for (severity, text), (got_severity, got_title) in zip(expected, got):
        assert severity == got_severity and text in got_title
    assert http_paths[0] == "/robots.txt"  # the HTTP origin's robots.txt is fetched before its homepage
    assert next(g for g in outcome.gates if g.check_id == "INT-4").state == "compliant"


def test_text_report_renders_every_idx_scenario(idx):
    """Guards against renderer assumptions about evidence shapes (a demo crashed on IDX-8 evidence)."""
    from maya_audit.report import render_text

    for name in ("idx_duplicates", "idx_canonicals", "idx_status_codes"):
        run = idx(name)
        text = render_text(run.result, list(run.gates.values()), list(run.checks.values()))
        assert "IDX-8" in text and "Priority order" in text


def test_unresolvable_www_variant_is_noted_not_silently_skipped(www_localhost_does_not_resolve):
    """The other half of the same branch: a variant that does not resolve must say so.

    Previously this path was only ever reached by accident, on a machine whose resolver happened not
    to answer for `www.localhost` — where it failed the test above rather than being checked here.
    """
    pytest.importorskip("cryptography", reason=NEEDS_CERTIFICATES)
    with tls_sites("valid", True) as (https, http, ca_bundle):
        config = CrawlConfig(request_delay_s=0, robots_sample_interval_s=0.05, refetch_delay_s=0,
                             prf_round_gap_s=0, ca_bundle=ca_bundle, http_port=http.port, render_enabled=False)
        outcome = run_audit(https.base_url + "/", config)
    index = outcome.result.index
    assert [h["host"] for h in index.hosts] == ["localhost"]
    assert index.variant_note.startswith("www variant www.localhost does not resolve")
    assert "nothing to check" in index.variant_note
    # The start host was still checked, and no finding claims anything about the variant.
    idx2 = next(c for c in outcome.checks if c.check_id == "IDX-2")
    assert all("www.localhost" not in f.title for f in idx2.findings)


def test_ip_start_host_has_no_www_variant(idx):
    run = idx("idx_redirects")
    assert run.result.index.variant_note.startswith("no www variant")
    assert [h["host"] for h in run.result.index.hosts] == ["127.0.0.1"]


def test_bing_calls_to_real_endpoint_are_launch_gated(idx):
    """While the Bing JSON endpoint is unverified, a non-loopback endpoint is never called."""
    run = idx("idx_gsc_bing", bing_api_key="k", bing_site_url="https://example.com/",
              bing_endpoint="https://ssl.bing.com/webmaster/api.svc/json")
    assert run.result.index.bing is None
    assert run.result.index.bing_skipped.startswith("launch-gated")
    assert run.checks["IDX-10"].status == "not_assessed" and "launch-gated" in run.checks["IDX-10"].summary


def test_non_english_coverage_state_becomes_review_not_pass(tmp_path):
    """A translated coverageState can't match the English labels; it must surface for review, not pass or vanish."""
    from fakeserver import Response, Site

    scenario = IDX_SCENARIOS["idx_gsc_bing"]

    def german(site, request):
        return Response(200, json.dumps({"inspectionResult": {"indexStatusResult": {
            "verdict": "NEUTRAL", "coverageState": "Gecrawlt – zurzeit nicht indexiert",
            "indexingState": "INDEXING_ALLOWED"}}}), content_type="application/json")

    with FakeServer(scenario.build()) as site, FakeServer(Site({"/v1/urlInspection/index:inspect": german})) as gsc:
        config = CrawlConfig(**{**scenario.config, "key_pages": (site.base_url + "/pricing",)},
                             gsc_access_token="t", gsc_site_url=site.base_url + "/",
                             gsc_endpoint=gsc.base_url + "/v1/urlInspection/index:inspect")
        outcome = run_audit(site.base_url + "/", config)
    idx9 = next(c for c in outcome.checks if c.check_id == "IDX-9")
    assert idx9.findings == [] and idx9.evidence["passed"] == []
    [review] = idx9.review_items
    assert review.evidence["inspections"][0]["coverageState"].startswith("Gecrawlt")
