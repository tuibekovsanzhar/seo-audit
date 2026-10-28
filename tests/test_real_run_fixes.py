"""Fixes from the first real audit of a site read through Firecrawl (team-preview-5 on a bank's site).

Every page here is made up but shaped like what the real run returned: a reader whose "raw" HTML has absolute
addresses, titles that share a long tagline, a careers page that describes its openings inline, and search data
for a brand whose name is an ordinary word.
"""
import json

import httpx
import pytest

pytest.importorskip("fastapi")

from maya_audit.analysis import analyze_html, dead_link_kind  # noqa: E402
from maya_audit.checks.small_site import inline_openings  # noqa: E402
from maya_audit.config import CrawlConfig  # noqa: E402
from maya_audit.dataforseo import DataForSEOClient, DataForSEOError, Ledger, insights, panel, pricing  # noqa: E402
from maya_audit.dataforseo import client as dfs_client  # noqa: E402
from maya_audit.dataforseo.cache import CACHE_NAME, Cache  # noqa: E402
from maya_audit.dataforseo.credentials import Credentials  # noqa: E402
from maya_audit.dataforseo.ledger import LEDGER_NAME  # noqa: E402
from maya_audit.firecrawl import Options, reader  # noqa: E402
from maya_audit.urls import UnresolvedHostError, UnsafeTargetError  # noqa: E402
from maya_audit_web import pdf, practical  # noqa: E402
from test_firecrawl import ROBOTS_TEXT, TEXT, Firecrawl, blocked_audit, client_for, doc, no_lookups  # noqa: E402,F401
from test_review_fixes import QUIET  # noqa: E402
from test_web_app import API, SHOP, get, plan, start, web  # noqa: E402,F401

ROOT = "https://bank.test"
TAGLINE = "Powerful infrastructure to transform the banking system."
NAV = f'<a class="btn" href="{ROOT}/#">Log in</a> <a href="{ROOT}/careers">Careers</a> <a href="{ROOT}/privacy">Privacy</a> <a href="{ROOT}/terms">Terms</a>'
JOB = "<h2>{name}</h2><h3>Responsibilities</h3><p>Do the work well.</p><h3>Qualifications</h3><p>Know the work.</p>"
BANK = {
    f"{ROOT}/robots.txt": f"<html><body><pre>{ROBOTS_TEXT}</pre></body></html>",
    f"{ROOT}/": doc(TAGLINE, f"<h1>{TAGLINE}</h1>" + TEXT + NAV),
    f"{ROOT}/privacy": doc(f"{TAGLINE} · Privacy Policy", "<h1>Privacy Policy</h1>" + TEXT + NAV),
    f"{ROOT}/terms": doc(f"{TAGLINE} · Terms of Use", "<h1>Terms of Use</h1>" + TEXT + NAV),
    f"{ROOT}/careers": doc("Maximum · Careers", "<h1>Careers.</h1>" + TEXT + "".join(JOB.format(name=n) for n in ("Operations Manager", "Staff Engineer", "Recruiter"))
                           + "<h2>Company</h2>" + NAV),
}


@pytest.fixture
def audited(tmp_path, no_lookups):
    outcome = blocked_audit()
    info = reader.apply(outcome, CrawlConfig(**{**QUIET, "max_pages": 10}), client_for(tmp_path, Firecrawl(BANK)), Options(read_always=True, max_pages=10))
    assert info["used"] and info["pages_read"] == 4
    return outcome, info


# 1 ----------------------------------------------------------------------------------------------------------------
def test_titles_that_differ_only_after_what_a_search_result_shows_are_reported_from_the_same_titles_the_table_shows(audited):
    outcome, info = audited
    titles = outcome.by_id()["STR-1"]
    [finding] = [f for f in titles.findings if "begin with the same 50 characters" in f.title]
    [group] = finding.evidence["groups"]
    assert finding.severity.value == "S4" and group["shared_start"] == TAGLINE[:50] and finding.evidence["characters_compared"] == 50
    assert {row["url"] for row in group["pages"]} == {f"{ROOT}/", f"{ROOT}/privacy", f"{ROOT}/terms"}
    assert "Put what is different first" in finding.how_to_fix and not [f for f in titles.findings if "are shared by" in f.title]  # different in full
    # The check and the page table read the same pages: every title the finding names is the title the reader's page has.
    read = {page.url: page.analysis["title"] for page in info["view_pages"]}
    assert all(read[row["url"]] == row["title"] for row in group["pages"])
    assert "begin with the same" not in json.dumps([f.title for f in titles.findings if f is not finding])


def test_distinct_short_titles_and_exact_duplicates_are_not_reported_as_sharing_a_start(tmp_path, no_lookups):
    pages = {f"{ROOT}/robots.txt": BANK[f"{ROOT}/robots.txt"],
             f"{ROOT}/": doc("Kettles | Brand", "<h1>Kettles</h1>" + TEXT + f'<a href="{ROOT}/a">a</a> <a href="{ROOT}/b">b</a>'),
             f"{ROOT}/a": doc("Teapots | Brand", "<h1>Teapots</h1>" + TEXT), f"{ROOT}/b": doc("Teapots | Brand", "<h1>More teapots</h1>" + TEXT)}
    outcome = blocked_audit()
    reader.apply(outcome, CrawlConfig(**{**QUIET, "max_pages": 10}), client_for(tmp_path, Firecrawl(pages)), Options(read_always=True, max_pages=10))
    found = [f.title for f in outcome.by_id()["STR-1"].findings]
    # The two near-copies' shared title is said on their IDX-8 group's line (decision 225); nothing says "begin with the same".
    [copies] = outcome.by_id()["IDX-8"].findings
    assert [g["signals"] for g in copies.evidence["duplicate_groups"]] == [["nearly_same", "same_title"]]
    assert not any("are shared by" in title for title in found) and not any("begin with the same" in title for title in found)


# 2 ----------------------------------------------------------------------------------------------------------------
def test_a_link_to_nowhere_is_found_after_a_reader_has_made_its_address_absolute(audited):
    outcome, _info = audited
    nowhere = outcome.by_id()["STR-19"]
    # Recognised after the reader made its address absolute, and recognised for what it is: a sign-in control, which is an
    # accessibility note and not a link a crawler should follow (the false alarm of the maximum.com run).
    assert nowhere.status == "findings" and nowhere.evidence["links_without_address"] == 0 and nowhere.evidence["controls_coded_as_links"] >= 1
    assert [f.severity.value for f in nowhere.findings] == ["Info"] and "Log in" in json.dumps(nowhere.findings[0].evidence)


def test_only_the_pages_own_address_with_an_empty_fragment_counts_as_nowhere():
    page = "https://site.example/pricing"
    assert dead_link_kind({"href": "https://site.example/pricing#"}, False, page) == 'href="#"'
    assert dead_link_kind({"href": "https://site.example/pricing/#!"}, False, page) == 'href="#"'
    assert dead_link_kind({"href": "https://site.example/pricing#plans"}, False, page) is None  # a real place on the page
    assert dead_link_kind({"href": "https://site.example/#"}, False, page) is None             # another page
    assert dead_link_kind({"href": "https://site.example/pricing#", "aria-expanded": "false"}, False, page) is None  # a menu toggle
    assert dead_link_kind({"href": "https://site.example/pricing#"}, False) is None and dead_link_kind({"href": "#"}, False) == 'href="#"'
    html = '<html><body><main><a href="https://site.example/pricing#">Log in</a> <a href="https://site.example/pricing#content">Skip</a></main></body></html>'
    assert [d["text"] for d in analyze_html(html, page)["dead_links"]] == ["Log in"] and analyze_html(html)["dead_links"] == []


# 3 ----------------------------------------------------------------------------------------------------------------
def test_a_careers_page_that_describes_its_openings_inline_is_reported_without_jobposting_data(audited):
    outcome, _info = audited
    jobs = outcome.by_id()["STR-23"]
    [finding] = jobs.findings
    assert finding.title == "1 careers page(s) list 3 job opening(s) on the page itself, with no JobPosting structured data"
    assert finding.evidence["pages"][0]["openings"] == ["Operations Manager", "Staff Engineer", "Recruiter"] and finding.severity.value == "Info"
    assert jobs.evidence == {**jobs.evidence, "job_pages": 0, "careers_pages_listing_openings": 1} and "Inferred from its headings" in " ".join(finding.notes)


def test_inline_openings_need_a_job_heading_with_its_own_sections_more_than_once():
    h = lambda *rows: [{"level": level, "text": text} for level, text in rows]  # noqa: E731
    assert inline_openings(h((1, "Careers"), (2, "Why work here"), (2, "Benefits"))) == []
    assert inline_openings(h((1, "Careers"), (2, "Engineer"), (3, "Sorumluluklar"), (2, "Designer"), (3, "Aranan Nitelikler"))) == ["Engineer", "Designer"]
    assert inline_openings(h((2, "Responsibilities"), (2, "Qualifications"))) == []  # sections with no job above them


def test_a_careers_page_with_jobposting_markup_or_one_section_is_not_reported(tmp_path, no_lookups):
    marked = '<script type="application/ld+json">{"@context":"https://schema.org","@type":"JobPosting","title":"Engineer"}</script>'
    pages = {**BANK, f"{ROOT}/careers": doc("Maximum · Careers", "<h1>Careers</h1>" + TEXT + JOB.format(name="A") + JOB.format(name="B"), head=marked)}
    outcome = blocked_audit()
    reader.apply(outcome, CrawlConfig(**{**QUIET, "max_pages": 10}), client_for(tmp_path, Firecrawl(pages)), Options(read_always=True, max_pages=10))
    assert outcome.by_id()["STR-23"].status == "pass"


# 4 and 5 ----------------------------------------------------------------------------------------------------------
def keyword(word, searches, position):
    return {"keyword_data": {"keyword": word, "keyword_info": {"search_volume": searches}},
            "ranked_serp_element": {"serp_item": {"rank_group": position, "url": "https://maximum.example/"}}}


WORDS = [("maximum heart rate", 90000, 14), ("maximum", 40000, 9), ("maximum bank", 900, 1), ("core banking system", 700, 12),
         ("maximum occupancy calculator", 5000, 8), ("ai banking platform", 300, 6), ("maximum careers", 50, 1)]


def answers(request):
    path, payload = request.url.path, json.loads(request.content)
    if path == pricing.LABS_RANKED_KEYWORDS:
        result = {"total_count": 465, "items": [keyword(*w) for w in WORDS]}
    elif path == pricing.LABS_COMPETITORS:
        result = {"total_count": 4705, "items": [{"domain": d, "intersections": n, "avg_position": 9.0, "full_domain_metrics": {"organic": {"count": 9, "etv": 9.0}}}
                                                 for d, n in (("maximum.example", 465), ("www.maximum.example", 12), ("dictionary.example", 80), ("heart-health.example", 60))]}
    else:
        result = {"items": [{"metrics": {"organic": {"count": 465, "etv": 1930.7}}}]}
    return httpx.Response(200, json={"status_code": 20000, "tasks": [{"status_code": 20000, "cost": 0.01, "result": [result]}]})


def paid_client(tmp_path, transport, **more):
    return DataForSEOClient(Credentials("login", "password-made-up"), Ledger(tmp_path / LEDGER_NAME), Cache(tmp_path / CACHE_NAME),
                            daily_budget=5.0, approved_usd=5.0, approved_always_ask=True, transport=transport, **more)


SITE_TEXT = [TAGLINE, "Maximum is an AI-native operating system for banks.", "Careers", "Banking platform for core operations"]


def test_keywords_are_sorted_into_branded_relevant_and_unrelated_and_a_common_word_brand_is_said(tmp_path):
    calls = [c for c in insights.audit_plan("https://maximum.example/", country="United States") if c.check_id in ("DFS-3", "DFS-4", "DFS-5", "DFS-6")]
    section = panel.run_checks(calls, paid_client(tmp_path, httpx.MockTransport(answers)))
    from test_keyword_actions import page as evidence_page
    insights.apply_relevance(section, brand="Maximum", domain="maximum.example", texts=SITE_TEXT,
                             pages=[evidence_page("https://maximum.example/", "Core banking system and AI banking platform")])
    by_id = {c["check_id"]: c for c in section["checks"]}
    ranked = by_id["DFS-4"]["evidence"]["data"]
    assert ranked["table"]["columns"][-1] == "Relevance"
    kept = {row[0]: row[-1] for row in ranked["table"]["rows"]}
    # The ordinary word on its own is ambiguous: neither a brand search nor an opportunity. The name with a qualifier stays branded.
    assert kept == {"maximum bank": "branded", "maximum careers": "branded", "core banking system": "relevant", "ai banking platform": "relevant"}
    assert [row[0] for row in ranked["ambiguous"]["rows"]] == ["maximum"] and "insufficient context" in ranked["ambiguous"]["title"]
    assert [row[0] for row in ranked["unrelated"]["rows"]] == ["maximum heart rate", "maximum occupancy calculator"]  # the word, not the company
    assert ranked["relevance"] == {**ranked["relevance"], "branded": 2, "relevant": 2, "unrelated": 2, "ambiguous": 1, "common_word_brand": "maximum"}
    assert "2 name the brand, 2 have supported topic matches and 2 look unrelated" in by_id["DFS-4"]["summary"]
    assert "the bare word “maximum”, which is ambiguous and not counted" in by_id["DFS-4"]["summary"]
    assert "“Maximum” is also an ordinary word" in by_id["DFS-4"]["summary"] and "lexical evidence" in ranked["relevance"]["method"]
    assert section["relevance"]["common_word_brand"] == "maximum" and section["relevance"]["warning"]
    # Competitors: the audited domain itself is gone, and the overlap is labelled.
    rivals = by_id["DFS-6"]
    assert [row[0] for row in rivals["evidence"]["data"]["table"]["rows"]] == ["dictionary.example", "heart-health.example"]
    assert rivals["evidence"]["data"]["own_domain_removed"] == 2 and "Possibly generic-word overlap" in rivals["summary"]
    assert "the audited domain itself are left out" in rivals["summary"]
    # Applying it twice changes nothing more.
    again = json.dumps(section, sort_keys=True)
    insights.apply_relevance(section, brand="Maximum", domain="maximum.example", texts=SITE_TEXT)
    assert json.dumps(section, sort_keys=True) == again
    text = panel.render_text(section) + panel.render_markdown(section)
    assert "Unrelated searches (not counted as opportunities): 2" in text and "maximum heart rate" in text
    assert "Ambiguous searches (insufficient context; not counted as opportunities): 1" in text
    # Opportunities quote only the branded and relevant quick wins.
    view = {"checks": [{"check_id": c["check_id"], "status": c["status"], "data": c["evidence"]["data"]} for c in section["checks"]]}
    lines = practical.opportunities(view, None, [])
    assert any("already rank in positions 4 to 20" in line for line in lines) and "heart rate" not in json.dumps(lines) and "occupancy" not in json.dumps(lines)


def test_a_specific_brand_name_keeps_its_own_searches_as_branded_and_is_not_warned_about():
    assert insights.common_word_brand("Maximum") == "maximum" and insights.common_word_brand("Maximum Bank") is None
    assert insights.common_word_brand("Moodist") is None and insights.common_word_brand("", "ticimax.com") is None
    names = insights.brand_words("Moodist", "moodist.com.tr")
    vocabulary = insights.site_vocabulary(["Psikiyatri hastanesi", "Online terapi randevu"], names)
    assert insights.classify_keyword("moodist randevu", names, vocabulary, False) == "branded"
    assert insights.classify_keyword("moodist nerede", names, vocabulary, False) == "branded"  # a specific name is enough
    assert insights.classify_keyword("online terapi", names, vocabulary, False) == "relevant"
    assert insights.classify_keyword("ucuz uçak bileti", names, vocabulary, False) == "unrelated"


def test_the_plan_card_warns_when_the_brand_name_is_an_ordinary_word_and_the_report_sorts_the_keywords(web):
    client = web()
    assert plan(client)["search_data"]["brand_warning"] is None
    client.put(f"{API}/projects/{SHOP}/profile", json={"brand_name": "Maximum", "countries": ["United States"], "key_pages": []})
    made = plan(client, search_data=True, market_default_accepted=True)
    warning = made["search_data"]["brand_warning"]
    assert "“Maximum” is also an ordinary word" in warning and warning in made["limitations"]
    audit = start(client, made)
    checks = {c["check_id"]: c for c in get(client, audit, "/summary")["backlinks"]["checks"]}
    assert checks["DFS-4"]["data"]["table"]["columns"][-1] == "Relevance" and "relevance" in checks["DFS-4"]["data"]
    assert "demo-shop.example" not in [row[0] for row in checks["DFS-6"]["data"]["table"]["rows"]] and checks["DFS-6"]["data"]["own_domain_removed"] == 1
    assert get(client, audit, "/result")["dataforseo"]["relevance"]["common_word_brand"] == "maximum"
    printed = client.get(f"{API}/audits/{audit['id']}/print?full=true").text
    # No confirmed opportunities may remain after conservative classification; all sampled rows still
    # have visible evidence/intent assessment rather than requiring a nonempty opportunity table.
    assert "Keyword intent evidence (listed sample only)" in printed and "Supported dimensions" in printed and "ordinary word" in printed


# 6 ----------------------------------------------------------------------------------------------------------------
def test_a_failed_address_lookup_is_tried_once_more_charged_nothing_and_never_called_unsafe(tmp_path, monkeypatch):
    monkeypatch.setattr(dfs_client, "RETRY_WAIT_S", 0)
    attempts = []

    def flaky(request):
        attempts.append(request.url.path)
        if len(attempts) == 1:
            raise UnresolvedHostError("host could not be resolved safely: api.dataforseo.com")
        return httpx.Response(200, json={"status_code": 20000, "tasks": [{"status_code": 20000, "cost": 0.02403, "result": [{"backlinks": 5}]}]})

    client = paid_client(tmp_path, httpx.MockTransport(flaky))
    result = client.request(pricing.BACKLINKS_SUMMARY, [{"target": "bank.example"}], target="bank.example")
    assert len(attempts) == 2 and result.cost == 0.02403 and client.requests_sent == 1 and client.ledger.spent_today() == pytest.approx(0.02403)

    def down(request):
        attempts.append("down")
        raise UnresolvedHostError("host could not be resolved safely: api.dataforseo.com")

    broken = paid_client(tmp_path / "down", httpx.MockTransport(down))
    with pytest.raises(DataForSEOError) as failure:
        broken.request(pricing.BACKLINKS_SUMMARY, [{"target": "bank.example"}], target="bank.example")
    message = str(failure.value)
    assert attempts.count("down") == 2 and "could not be looked up (DNS), in 2 attempts" in message and "Nothing was sent and nothing was charged" in message
    assert "safety checks" not in message and broken.requests_sent == 0 and broken.ledger.spent_today() == 0
    assert "address lookup failed 2 times" in (tmp_path / "down" / LEDGER_NAME).read_text(encoding="utf-8")
    from maya_audit_web import paid
    assert paid.refusal("not assessed: " + message)["code"] == "provider_unreachable"

    refused = []

    def unreachable(request):
        refused.append(1)
        raise httpx.ConnectError("refused")
    offline = paid_client(tmp_path / "offline", httpx.MockTransport(unreachable))
    with pytest.raises(DataForSEOError, match="no connection could be made"):
        offline.request(pricing.BACKLINKS_SUMMARY, [{"target": "bank.example"}], target="bank.example")
    assert len(refused) == 2 and offline.ledger.spent_today() == 0

    # A destination that really is unsafe is refused at once, as before; a request that was sent and timed out is never repeated.
    def private(request):
        refused.append("private")
        raise UnsafeTargetError("refusing non-public destination")
    with pytest.raises(DataForSEOError, match="failed network safety checks"):
        paid_client(tmp_path / "private", httpx.MockTransport(private)).request(pricing.BACKLINKS_SUMMARY, [{"target": "bank.example"}])
    assert refused.count("private") == 1
    sent = []

    def slow(request):
        sent.append(1)
        raise httpx.ReadTimeout("no answer")
    with pytest.raises(DataForSEOError, match="may have been billed"):
        paid_client(tmp_path / "slow", httpx.MockTransport(slow)).request(pricing.BACKLINKS_SUMMARY, [{"target": "bank.example"}])
    assert len(sent) == 1


def test_an_unresolved_host_is_still_a_refusal_for_every_other_caller():
    assert issubclass(UnresolvedHostError, UnsafeTargetError)


# 7 and 8 ----------------------------------------------------------------------------------------------------------
def test_the_printed_page_table_shows_paths_and_whole_titles(web, tmp_path):
    assert pdf._path("https://bank.test/privacy", "https://bank.test") == "/privacy" and pdf._path("https://bank.test/", "https://bank.test") == "/"
    assert pdf._path("https://www.bank.test/a?b=1", "https://bank.test") == "/a?b=1" and pdf._path("https://other.test/x", "https://bank.test") == "https://other.test/x"
    from test_web_firecrawl import PAGES, services
    from test_web_app import Site, cloudflare
    client = web(site=Site(respond=cloudflare), firecrawl=services(tmp_path, Firecrawl(PAGES)))
    audit = start(client, plan(client))
    printed = client.get(f"{API}/audits/{audit['id']}/print?full=true").text
    table = printed[printed.index('<table class="grid pages">'):]
    table = table[:table.index("</table>")]
    assert '<td class="url">/about</td>' in table and '<td class="url">/</td>' in table and "http://" not in table
    assert "table-layout:fixed" in printed


def test_the_plan_card_never_prints_the_word_null(web, tmp_path):
    from pathlib import Path
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    try:
        with sync_playwright() as pw:
            pw.chromium.launch().close()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"headless Chromium unavailable: {exc}")
    from maya_audit_web import strings
    from test_web_firecrawl import PAGES, services
    client = web(firecrawl=services(tmp_path, Firecrawl(PAGES)))
    made = plan(client)  # Firecrawl on, basic proxy, no rendering fallback offered: the optional parts are absent
    static = Path(__file__).parents[1] / "maya_audit_web" / "static"
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.route("**/*", lambda route: route.abort())
        page.set_content("<main id='card'></main>")
        page.add_script_tag(content=(static / "app.js").read_text(encoding="utf-8").removesuffix("boot();\n"))
        page.evaluate("values => { state.strings = values; }", strings.table("en"))
        page.evaluate("plan => document.querySelector('#card').append(firecrawlBox(plan, {}, true, () => {}))", made)
        text = page.locator("#card").inner_text()
        browser.close()
    assert "The site owner has approved bypassing bot protection" in text and "null" not in text and "undefined" not in text
