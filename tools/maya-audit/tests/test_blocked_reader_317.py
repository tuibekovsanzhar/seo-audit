"""Follow-up to the airastana.com fixes (DECISIONS 317): block pages never use up the page limit, a named bot-protection
service gets an access finding with its AI-crawler warning, pages read only through the page reader get link score,
click depth and importance from the reader's own links, and a long card title never stops the team report's PDF.
Fake sites, a made-up Firecrawl and hand-made reports only; nothing is requested."""
from __future__ import annotations

import json
import re

import httpx
import pytest

from maya_audit import client_selection as cs
from maya_audit.audit import run_audit
from maya_audit.client_appendix import block_pages_text
from maya_audit.config import CrawlConfig
from maya_audit.firecrawl import Options, reader
from maya_audit.models import to_jsonable
from maya_audit.reassess_rules import apply as reassess
from maya_audit.report import read_counts
from maya_audit_web import wording
from maya_audit_web.team_report import render, texts
from test_airastana_316 import HTML, INCAPSULA, _doc, _saved_blocked_report
from test_deadline_hosted_hardening import QUIET
from test_firecrawl import Firecrawl, client_for, no_lookups  # noqa: F401  (fixture)
from test_team_report import built, synthetic

S = "https://imp.test"
URLS = [f"{S}/p{i}" for i in range(1, 21)]
AI = ("GPTBot", "ClaudeBot", "PerplexityBot", "Google-Extended")


def _pages():
    """Twenty pages; the homepage links to p1-p5, p1 links to p6-p10 (two clicks from home), the rest only in the sitemap."""
    pages = {u: _doc(u) for u in URLS}
    pages[S + "/"] = _doc("Home").replace("</main>", "".join(f'<a href="/p{i}">P{i}</a>' for i in range(1, 6)) + "</main>")
    pages[S + "/p1"] = _doc("P1").replace("</main>", "".join(f'<a href="/p{i}">P{i}</a>' for i in range(6, 11)) + "</main>")
    return pages


# A block page per service, as each answers Maya's crawler: (status, headers, body).
BLOCKS = {
    "Imperva": (200, {"x-iinfo": "1"}, INCAPSULA),
    "Cloudflare": (403, {"server": "cloudflare", "cf-mitigated": "challenge", "cf-ray": "a1-FRA"},
                   "<html><title>Just a moment...</title><body>Checking your browser</body></html>"),
    "Akamai": (403, {"server": "AkamaiGHost"}, "<html><body>Access Denied. Reference&#32;&#35;18.abc errors.edgesuite.net</body></html>"),
    "DataDome": (403, {"x-datadome": "protected"}, '<html><body><script src="https://ct.captcha-delivery.com/c.js"></script></body></html>'),
    "HUMAN (PerimeterX)": (403, {}, '<html><body><div id="px-captcha"></div></body></html>'),
}


def _site(blocked=lambda url: True, service="Imperva"):
    status, headers, body = BLOCKS[service]
    pages = _pages()

    def respond(request):
        path = request.url.path
        if path == "/robots.txt":
            return httpx.Response(200, text=f"User-agent: *\nAllow: /\nSitemap: {S}/sitemap.xml\n", headers={"content-type": "text/plain"})
        if path == "/sitemap.xml":
            return httpx.Response(200, headers={"content-type": "application/xml"}, text=(
                '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                + "".join(f"<url><loc>{u}</loc></url>" for u in URLS) + "</urlset>"))
        url = str(request.url)
        if url in pages and not blocked(url):
            return httpx.Response(200, headers=HTML, text=pages[url])
        return httpx.Response(status, headers={**HTML, **headers}, text=body)
    return respond, pages


def _read(tmp_path, transport, pages, cap=10, **options):
    cfg = CrawlConfig(**{**QUIET, "max_pages": cap})
    outcome = run_audit(S + "/", cfg, httpx.MockTransport(transport))
    info = reader.apply(outcome, cfg, client_for(tmp_path, Firecrawl(pages)), Options(read_always=True, max_pages=cap, **options))
    return outcome, info


# ---------------------------------------------------------------- 1: block pages never use up the page limit

def test_when_every_page_is_a_block_page_the_reader_reads_up_to_the_plans_limit(tmp_path, no_lookups):
    transport, pages = _site()
    outcome, info = _read(tmp_path, transport, pages)
    assert all(p.fetch_class.value == "blocked" for p in outcome.result.pages)
    assert info["pages_read"] == 10 and info["coverage"]["not_requested_because"] == "page_cap"
    assert info["coverage"]["page_limit"] == {"plan": 10, "maya_pages_read": 0, "block_answers": 10, "block_answers_counted": 0,
                                              "reader_new_pages_allowed": 10}
    assert read_counts(to_jsonable(outcome.result), to_jsonable(info))["pages"] == 10


def test_a_blocked_crawls_good_pages_count_and_its_block_pages_do_not(tmp_path, no_lookups):
    # The homepage and p1-p3 are the site's; the rest is Imperva's block page: the crawl counts as blocked (6 of 10).
    transport, pages = _site(blocked=lambda url: not url.endswith(("/", "/p1", "/p2", "/p3")))
    outcome, info = _read(tmp_path, transport, pages)
    assert sum(p.fetch_class.value == "ok" for p in outcome.result.pages) == 4 and info["crawl_blocked"]["blocked"]
    limit = info["coverage"]["page_limit"]
    assert (limit["maya_pages_read"], limit["block_answers"], limit["reader_new_pages_allowed"]) == (4, 6, 6)
    counts = read_counts(to_jsonable(outcome.result), to_jsonable(info))
    assert counts["pages"] == 10                       # before: 4 of Maya's + 10 of the reader's different pages = 12 / 14


def test_the_coverage_line_says_the_block_pages_did_not_count_in_both_languages():
    line = {"kind": "block_pages", "blocked": 50, "allowed": 50, "read": 13, "plan": 50, "stopped": "time_limit"}
    assert block_pages_text(line, "en") == ("Block pages did not count toward the page limit: Maya's crawler got a block page "
                                            "or a 429 on 50 requests; the page reader could read up to 50 pages and read 13 (the time limit came first).")
    assert block_pages_text(line, "tr").startswith("Engel sayfaları sayfa sınırına sayılmadı: Maya'nın tarayıcısı 50 istekte")
    assert block_pages_text({**line, "stopped": "page_cap", "read": 50}, "tr").endswith("50 sayfa okudu.")


def test_a_saved_audit_with_block_pages_gets_its_page_limit_worked_out_offline():
    r = _saved_blocked_report()
    r["firecrawl"].update(page_cap=50, coverage={"read": 2, "not_requested_because": "time_limit"})
    new, _aff, record = reassess(r, {})
    limit = new["firecrawl"]["coverage"]["page_limit"]
    assert limit == {"plan": 50, "maya_pages_read": 0, "block_answers": 3, "block_answers_counted": 0,
                     "reader_new_pages_allowed": 50, "worked_out_offline": True}
    assert any("Page limit: 3 block answer(s)" in c for c in record["changes"])
    line = cs.block_pages_line(new)
    assert line == {"kind": "block_pages", "blocked": 3, "allowed": 50, "read": 2, "plan": 50, "stopped": "time_limit"}


# ---------------------------------------------------------------- 2: an access finding for a named bot-protection service

@pytest.mark.parametrize("service", sorted(BLOCKS))
def test_a_named_bot_protection_service_gets_an_access_finding_with_the_ai_crawler_warning(tmp_path, no_lookups, service):
    transport, pages = _site(service=service)
    outcome, info = _read(tmp_path, transport, pages)
    [finding] = next(c for c in outcome.checks if c.check_id == "ACC-9").findings
    assert finding.rule_id == "acc9.bot_protection"
    # Read through Firecrawl, it stays the site's finding (like the 429 card), not a note.
    assert finding.severity.value == "S3" and finding.evidence["read_through"]["pages_read"] == info["pages_read"]
    assert finding.title.startswith(f"Maya's crawler blocked by bot protection ({service}): 10 of 10 page request(s) got its block page.")
    assert all(name in finding.title for name in AI)
    # The block is measured: Verified from a header or a status, Estimated from the block page's body (Imperva's 200).
    assert finding.confidence.value == ("estimated" if service == "Imperva" else "verified")
    assert f"In the bot settings of {service}" in finding.how_to_fix and "Google-Extended is a robots.txt setting" in finding.how_to_fix
    tr, translated = wording.title("ACC-9", finding.title, "tr")
    assert translated and tr.startswith(f"Maya'nın tarayıcısı bot korumasına takıldı ({service}): 10 sayfa isteğinden 10 tanesine")
    fix, fixed = wording.fix(finding.how_to_fix, "tr")
    assert fixed and fix.startswith(f"{service} bot ayarlarında")


def test_a_429_keeps_its_own_card_and_an_unnamed_403_its_own_wording(tmp_path, no_lookups):
    def denied(request):
        return httpx.Response(403, headers=HTML, text="<html><title>Forbidden</title></html>")
    outcome = run_audit(S + "/", CrawlConfig(**{**QUIET, "max_pages": 3}), httpx.MockTransport(denied))
    [finding] = next(c for c in outcome.checks if c.check_id == "ACC-9").findings
    assert finding.rule_id == "acc9.blocked"


@pytest.mark.parametrize("lang", texts.LANGS)
def test_the_team_report_card_names_the_service_and_the_ai_crawlers(tmp_path, lang):
    report = synthetic([("ACC-9", "acc9.bot_protection")], "S3")
    f = report["checks"][0]["findings"][0]
    f.update(title="Maya's crawler blocked by bot protection (Imperva): 50 of 50 page request(s) got its block page. AI crawlers "
                   "(GPTBot, ClaudeBot, PerplexityBot, Google-Extended) may be blocked the same way",
             evidence={"blocked_by": [{"name": "Imperva", "kind": "bot challenge", "status": 200, "responses": 50}]},
             scope={"kind": "sitewide", "count": 50, "urls": [report["crawl"]["origin"] + "/"]})
    data = built(tmp_path, report, lang)
    card = data["todos"][0]
    assert card["title"] == texts.rule("acc9.bot_protection", lang)["title"]
    # One line under the status: it fits a card at 105 characters (airastana's Turkish line, 103, printed whole).
    assert any("Imperva" in line and all(name in line for name in AI) and len(line) <= 105 for line in card.get("sub") or [])


def test_a_saved_imperva_blocked_audit_gets_the_finding_as_a_card_not_a_note():
    new, aff, _record = reassess(_saved_blocked_report(), {})
    [acc9] = next(c for c in new["checks"] if c["check_id"] == "ACC-9")["findings"]
    assert acc9["rule_id"] == "acc9.bot_protection" and acc9["severity"] == "S3" and acc9["confidence"] == "estimated"
    assert acc9["title"].startswith("Maya's crawler blocked by bot protection (Imperva): 3 of 3 page request(s)")
    sel = cs.select(new, aff, {})
    assert any(acc9["id"] in g["finding_ids"] for g in sel["cards"])


# ---------------------------------------------------------------- 3: link score, depth and importance from the reader's links

def test_pages_read_only_through_the_reader_get_importance_and_click_depth(tmp_path, no_lookups):
    transport, pages = _site()
    outcome, info = _read(tmp_path, transport, pages)
    grouping = outcome.result.reader_page_grouping
    assert grouping and grouping["reader"] == "Firecrawl"
    scored = {u: g for u, g in grouping["pages"].items()}
    assert scored[S + "/"]["click_depth"] == 0 and scored[S + "/p1"]["click_depth"] == 1
    assert all(isinstance(g["importance"], int) and "internal_link_score" in g for g in scored.values())
    assert scored[S + "/p1"]["internal_link_score"] > min(g["internal_link_score"] for g in scored.values())


def test_the_main_reader_scores_pages_maya_got_a_block_page_for(tmp_path, no_lookups):
    # One block page in ten: the crawl is not "blocked", Firecrawl is the main reader and reads p5 again; before, p5 had no
    # importance ("not computed"); now it is scored on one link graph with Maya's own pages.
    transport, pages = _site(blocked=lambda url: url.endswith("/p5"))
    outcome, info = _read(tmp_path, transport, pages)
    assert not info["crawl_blocked"]["blocked"]
    report = json.loads(json.dumps(to_jsonable(outcome.result)))
    records, _summary = cs._stage3_grouping({"crawl": report, "firecrawl": to_jsonable(info)})
    assert isinstance(records[S + "/p5"]["importance"], int) and records[S + "/p5"]["click_depth"] == 1


# ---------------------------------------------------------------- 4: long card titles never stop the PDF

LONG = {"en": "Make sure that every single one of the many affected pages across the whole website gets its own clear, "
              "complete and correctly written title, description and main heading before the next release",
        "tr": "Sitenin tamamındaki etkilenen sayfaların her birine bir sonraki yayından önce kendine özgü, açık, eksiksiz ve "
              "doğru yazılmış bir başlık, açıklama ve ana başlık eklendiğinden emin olun"}
RULES = [("STR-1", "str1.shared"), ("STR-2", "str2.no_h1"), ("STR-14", "str14.no_text"), ("RND-6", "rnd6.large"),
         ("STR-7", "str7.over_100kb"), ("STR-10", "str10.no_description"), ("IDX-1", "idx1.4xx.referenced"),
         ("ACC-9", "acc9.bot_protection")]


@pytest.mark.parametrize("lang", texts.LANGS)
def test_every_card_with_a_very_long_title_still_prints(tmp_path, lang):
    pytest.importorskip("playwright")
    data = built(tmp_path, synthetic(RULES, "S3"), lang)
    slots = 0
    for section in ("todos", "priorities", "findings", "actions", "confirm"):
        for item in data.get(section) or []:
            item["title"] = LONG[lang]
            slots += 1
    assert len(data["todos"]) >= 4 and slots >= 10
    result = render.produce(data, tmp_path / "r.html", tmp_path / "r.pdf")
    assert result["stop"] is None and result["overflow"] == [], result["lines"]
    assert result["pdf"] and (tmp_path / "r.pdf").stat().st_size > 0
    # A card title shrinks and keeps every word; only a one-line table row of this length is cut at a word, with "…".
    assert not [s for s in result["shortened"] if s.startswith(("todos", "priorities", "confirm"))], result["shortened"]
    assert all(s.startswith(("findings", "actions")) for s in result["shortened"])
    html = (tmp_path / "r.html").read_text(encoding="utf-8")
    assert len(re.findall(r'data-slot="todos\[\d+\]\.title" data-fit=', html)) == len(data["todos"])


# ---------------------------------------------------------------- DECISIONS 318: a consistent 429 block is measured, a card

from test_rate_limited_start import CF, audit as bank_audit, rate_limited_audit, site as bank_site, slept  # noqa: E402,F401


def test_the_429_rule_is_consistent_only_when_widespread_and_repeated():
    from maya_audit.checks.access import consistent_429
    assert consistent_429(1, True, True)            # nihan: the homepage, its one request, 429 again after the wait
    assert consistent_429(5, False, True)           # five page requests answered 429
    assert not consistent_429(1, False, True)       # one 429, never asked again
    assert not consistent_429(3, True, False)       # occasional: under the degraded share, the homepage fine


def test_a_consistent_429_block_on_mayas_pages_is_verified_and_a_card(slept, no_lookups):
    outcome = rate_limited_audit(slept)  # the homepage answers 429, also after the wait; robots.txt is served
    [finding] = next(c for c in outcome.checks if c.check_id == "ACC-9").findings
    assert finding.rule_id == "acc9.blocked_429" and finding.confidence.value == "verified"
    report = json.loads(json.dumps(to_jsonable({"checks": outcome.checks, "crawl": outcome.result})))
    group = next(g for g in cs.groups(report, None, {}, {}) if finding.id in g["finding_ids"])
    assert group["confirm_reason"] is None   # before: "low_confidence", so "Teyit edin"


def test_a_single_429_on_a_later_page_stays_inferred(slept, no_lookups):
    handler, _ = bank_site([(200, None)], other=lambda r: httpx.Response(429, headers={**HTML, **CF, "retry-after": "60"}, text="x"))
    outcome = bank_audit(handler, max_pages=10)
    [finding] = next(c for c in outcome.checks if c.check_id == "ACC-9").findings
    assert finding.rule_id == "acc9.rate_limited_429" and finding.confidence.value == "inferred"


def test_a_saved_nihan_shaped_429_block_becomes_verified_in_the_current_engine_copy():
    r = _saved_blocked_report()
    from test_airastana_316 import _block_record
    page = {**_block_record("https://air.test/"), "status": 429, "fetch_class": "rate_limited", "discovered_via": "start",
            "retried_after_429": True, "analysis": None, "body_bytes": 40, "classification_evidence": ["status 429"]}
    r["crawl"]["pages"] = [page]
    acc9 = {"id": "ACC-9-n", "check_id": "ACC-9", "rule_id": "acc9.blocked_429", "severity": "S3", "confidence": "inferred",
            "title": "Maya's crawler blocked (429 on pages): Cloudflare answered 1 of 1 page request(s) with 429 while robots.txt "
                     "and the sitemap were served. AI crawlers may get the same treatment", "scope": {"urls": ["https://air.test/"]},
            "evidence": {"pages_requested": 1, "pages_blocked_or_challenged": 1, "start_url_blocked": True}}
    r["checks"] = [{"check_id": "ACC-9", "status": "findings", "findings": [acc9]}]
    r["findings_in_priority_order"] = ["ACC-9-n"]
    new, _aff, record = reassess(r, {})
    [f] = new["checks"][0]["findings"]
    assert f["confidence"] == "verified" and any("ACC-9-n: Verified, a card" in c for c in record["changes"])
