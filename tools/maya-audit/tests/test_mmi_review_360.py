"""DECISIONS 360: İlginay's review of the MMI Ek as global rules. (1) no "no <title>" when some copy of the page has one
(metadata a Next.js page prints in the body, a reader's copy without it); (2) an <h1> is hidden only by display:none,
visibility:hidden or the hidden attribute, and the evidence says where; (3) page subjects before the brand in titles
are not brand names; (4) a link to a page whose canonical names other content is not an alias link; (5) link cards
name their links (page, text, address, place) in "Bağlantı yerleri", on the card and in each row's step; (6) a card
judged on the timing sample says how many pages it measured. Mock-transport sites and made-up records only."""
from __future__ import annotations

import json
from types import SimpleNamespace

import httpx

from maya_audit.analysis import analyze_html
from maya_audit.audit import run_audit
from maya_audit.config import CrawlConfig
from maya_audit.models import to_jsonable
from maya_audit.report import build_report
from test_deadline_hosted_hardening import QUIET
from test_firecrawl import no_lookups  # noqa: F401

HTML = {"content-type": "text/html; charset=utf-8"}
SITE = "https://shop.test"
TEXT = "<p>" + "Wine, spirits and beer delivered to your door in two hours across the city, with daily offers. " * 8 + "</p>"
ABOUT = "<p>" + "An alcohol licence lets residents buy, carry and keep alcohol at home; here is how to apply for one. " * 8 + "</p>"
FOOT = '<footer><a href="/about">About</a> <a href="https://social.test/shop?igsh=abc123">instagram</a></footer>'
ORG = ('<script type="application/ld+json">{"@context":"https://schema.org","@type":"Organization","name":"MMI Home Delivery",'
       '"url":"https://shop.test/"}</script><meta property="og:site_name" content="MMI Home Delivery">')


def page(title, body, head_extra="", streamed=False):
    head = (f"<head><meta charset=utf-8>{ORG}{head_extra}</head><body><title>{title}</title>"
            f'<meta name="description" content="Buy {title} online.">' if streamed else
            f'<head><meta charset=utf-8><title>{title}</title><meta name="description" content="Buy {title} online.">{ORG}'
            f"{head_extra}</head><body>")
    return f'<!doctype html><html lang="en">{head}<main>{body}{TEXT}</main>{FOOT}</body></html>'


SUBJECTS = {"/absolut-1": "Absolut", "/absolut-2": "Absolut", "/france-1": "France", "/france-2": "France",
            "/chardonnay-1": "Chardonnay", "/chardonnay-2": "Chardonnay"}
ROUTES = {
    "/": page("Shop | MMI Home Delivery", "<h1>Shop</h1>" + "".join(f'<a href="{p}">{p}</a>' for p in
              ["/streamed", "/aria", "/stream-h1", "/none-h1", "/responsive"] + list(SUBJECTS))),
    "/streamed": page("Glassware | MMI Home Delivery", "<h1>Glassware</h1>", streamed=True),
    "/aria": page("Aria | MMI Home Delivery", '<h1 aria-hidden="true">Aria</h1>'),
    "/stream-h1": page("Streamed | MMI Home Delivery", '<div hidden id="S:0"><h1>Streamed</h1></div>'),
    "/none-h1": page("Hidden | MMI Home Delivery", '<div class="wrap" style="display: none"><h1>Hidden</h1></div>'),
    "/responsive": page("Twice | MMI Home Delivery", '<h1 style="display:none">Twice</h1><h1>Twice</h1>'),
    "/about": ('<!doctype html><html lang="en"><head><title>About | MMI Home Delivery</title>'
               f'<link rel="canonical" href="{SITE}/">{ORG}</head><body><main><h1>Licence</h1>{ABOUT}</main>{FOOT}</body></html>'),
    **{p: page(f"Buy {s} {p[-1]} | {s} MMI Home Delivery", f"<h1>{s} {p[-1]}</h1>") for p, s in SUBJECTS.items()},
}


def respond(request):
    path = request.url.path
    if path == "/robots.txt":
        return httpx.Response(200, text="User-agent: *\nAllow: /\n")
    if path in ROUTES:
        return httpx.Response(200, headers=HTML, text=ROUTES[path])
    return httpx.Response(404, headers=HTML, text="<h1>yok</h1>")


def crawl():
    config = CrawlConfig(**{**QUIET, "max_pages": 30, "sitemap_check_max": 0})
    outcome = run_audit(SITE + "/", config, httpx.MockTransport(respond))
    report = json.loads(json.dumps(to_jsonable(build_report(outcome.result, outcome.gates, outcome.checks))))
    return report, {f.get("rule_id"): f for c in report["checks"] for f in c.get("findings") or []}


# ---------------------------------------------------------------- 1: titles

def test_metadata_printed_in_the_body_after_a_normal_head_is_the_pages_own():
    a = analyze_html('<html><head><meta charset=utf-8></head><body><title>Buy Glassware</title>'
                     '<meta name="description" content="Glasses"><meta name="robots" content="noindex">'
                     '<meta property="og:title" content="G"><svg><title>icon</title></svg></body></html>')
    assert a["title"] == "Buy Glassware" and a["metadata_in_body"] == ["title", "description", "og:title"]
    assert [m["name"] for m in a["meta"]] == ["description"]  # a robots tag in the body stays ACC-3's note
    broken = analyze_html('<html><head><title>A</title><div>x</div><meta name="description" content="late"></head><body></body></html>')
    assert broken["title"] == "A" and broken["metadata_in_body"] == []  # after a <head> broken early: still "lost"


def test_no_title_is_never_said_when_a_copy_of_the_page_has_one(no_lookups):  # noqa: F811
    report, found = crawl()
    assert "str1.no_title" not in found and "str10.no_description" not in found
    from maya_audit.firecrawl.reader import _merged
    from maya_audit.models import Confidence, FetchClass, PageFetch
    ok = {"fetch_class": FetchClass.OK, "classification_confidence": Confidence.VERIFIED, "classification_evidence": []}
    own = PageFetch(url=SITE + "/x", discovered_via="link", depth=1, requested_at="t", user_agent="Maya", status=200,
                    error=None, elapsed_ms=1, content_type="text/html", body_bytes=10, body_truncated=False, headers={}, **ok,
                    analysis=analyze_html("<html><head><title>Mine</title></head><body><h1>x</h1></body></html>"))
    read = PageFetch(url=SITE + "/x", discovered_via="link", depth=1, requested_at="t", user_agent="Firecrawl", status=200,
                     error=None, elapsed_ms=1, content_type="text/html", body_bytes=10, body_truncated=False, headers={}, **ok,
                     analysis=analyze_html("<html><head></head><body><h1>x</h1></body></html>"))
    assert _merged(own, read).analysis["title"] == "Mine"  # the reader's copy came back without it


# ---------------------------------------------------------------- 2: hidden <h1>

def test_only_a_really_hidden_h1_is_reported_and_the_evidence_says_where(no_lookups):  # noqa: F811
    report, found = crawl()
    hidden = found["str2.hidden_h1"]
    rows = {r["url"]: r for r in hidden["evidence"]["pages"]}
    assert set(rows) == {SITE + "/none-h1"}  # not aria-hidden, not a streaming wrapper, not a duplicate beside a visible one
    assert rows[SITE + "/none-h1"]["hidden_by"].startswith("display:none on div.wrap")


# ---------------------------------------------------------------- 3: brand names

def test_page_subjects_before_the_brand_in_titles_are_not_brand_names(no_lookups):  # noqa: F811
    report, found = crawl()
    names = found.get("str5.names")
    assert names is None or "Absolut MMI Home Delivery" not in json.dumps(names["evidence"].get("variants"))


# ---------------------------------------------------------------- 4 and 5: links

def test_a_canonical_to_other_content_is_not_an_alias_and_link_cards_name_their_links(no_lookups):  # noqa: F811
    report, found = crawl()
    assert "idx6.alias_links" not in found  # /about's canonical names the homepage, whose content is other
    assert found["idx4.different"]["evidence"]["pages"][0]["url"] == SITE + "/about"
    from maya_audit import final, link_places
    rows = link_places.places(report)["IDX-6"]
    assert rows[0]["link_text"] == "instagram" and rows[0]["position"] == "footer" and rows[0]["parameters"] == ["igsh=abc123"]
    assert final.broken_link_cards(report)["IDX-6"]  # an observation's rows pass, with no finding of their own
    assert "instagram" not in final.cards_markdown(report)  # not a broken link


def test_each_pages_step_names_its_links():
    from maya_audit.link_fixes import alias_fixes, no_text_fixes
    fixes = no_text_fixes([{"source": "https://s.test/blog", "target": "https://s.test/p/1", "hrefs": ["/p/1"], "block": "p.text"}])
    assert fixes[0]["fix"]["tr"] == "Bu bağlantılara görünür metin ya da aria-label verin: (metin yok) → /p/1 (gövde, p.text)."
    pages = [{"url": "https://s.test/a", "outlinks": [{"target": "https://s.test/old", "anchor": "Wine", "nav": True}]}]
    fix = alias_fixes(pages, {"https://s.test/old": "https://s.test/wine"})[0]["fix"]["tr"]
    assert fix == "Bağlantıyı kanonik adrese verin: «Wine» → /old (menü) ⇒ /wine."
    from maya_audit.page_rows import row_fix
    assert row_fix({"evidence": {"page_fixes": fixes}}, "https://s.test/blog", "tr").startswith("Bu bağlantılara")


def test_a_link_card_names_its_first_links_and_the_summary_points_at_them():
    from maya_audit_web.team_report import build_data
    me = SimpleNamespace(lang="tr", link_places=lambda: {"F1": [
        {"kind": "link", "source": "https://s.test/blog", "link_text": None, "href": "https://s.test/p/1", "links_to": "https://s.test/p/1",
         "position": "body", "ends_at": "https://s.test/p/1"}]})
    todos = [{"n": 1, "finding_ids": ["F1"], "sub": None}, {"n": 2, "finding_ids": ["F2"], "sub": ["kept"]}]
    build_data.Builder.name_links(me, todos)
    assert todos[0]["sub"] == ["/blog: (metin yok) → /p/1 (gövde)"] and todos[1]["sub"] == ["kept"]


# ---------------------------------------------------------------- 6: sampled checks

def test_a_card_judged_on_the_timing_sample_says_how_many_pages_it_measured():
    from maya_audit_web.team_report import build_data
    labels = build_data.load(build_data.REFS / "etiketler.json")["tr"]
    facts = []
    me = SimpleNamespace(L=labels, lang="tr", rule_of=lambda f: f.get("rule_id"), fact=lambda *v: facts.extend(v),
                         _scope_text=lambda f: "3 sayfa", SAMPLED_RULES=build_data.Builder.SAMPLED_RULES)
    me.sampled_of = lambda f: build_data.Builder.sampled_of(me, f)
    f = {"rule_id": "prf1.slow", "evidence": {"pages_measured": 7}}
    assert build_data.Builder.scope_text(me, f) == "3 sayfa (ölçülen 7 sayfadan; diğerleri de etkilenebilir)" and 7 in facts
    assert build_data.Builder.scope_text(me, {"rule_id": "str1.no_title", "evidence": {}}) == "3 sayfa"


# ---------------------------------------------------------------- the saved audits

def test_a_saved_report_is_corrected_offline():
    from maya_audit import reassess_rules
    u = [f"{SITE}/{x}" for x in ("a", "b", "c")]
    report = {"crawl": {"perf": {"sample": [{"url": x} for x in u]}, "pages": [
        {"url": u[0], "analysis": {"title": "A", "meta": []}},
        {"url": u[1], "analysis": {"title": None, "meta": [], "outside_head": {"title": 1, "meta": ["description"], "closed_early_by": None}}},
        {"url": u[2], "analysis": {"title": None, "meta": [], "outside_head": {"title": 0, "meta": [], "closed_early_by": None}}}]},
        "checks": [{"check_id": "STR-1", "status": "findings", "findings": [
            {"id": "T", "rule_id": "str1.no_title", "title": "3 page(s) have no <title>", "scope": {"urls": u, "count": 3}, "evidence": {"pages": u}}]},
            {"check_id": "STR-2", "status": "findings", "findings": [
                {"id": "H", "rule_id": "str2.hidden_h1", "title": "1 page(s) have only a hidden <h1>", "scope": {"urls": u[:1], "count": 1},
                 "evidence": {"pages": [{"url": u[0], "hidden_by": "its markup: inline style, the hidden attribute or aria-hidden"}]}}]},
            {"check_id": "STR-5", "status": "findings", "findings": [
                {"id": "N", "rule_id": "str5.names", "title": "The brand is named 3 different ways", "scope": {"urls": u}, "evidence": {"variants": [
                    {"normalized": "mmi home delivery", "name": "MMI Home Delivery", "pages": 9, "by_source": {"Organization name": 9}},
                    {"normalized": "absolut mmi home delivery", "name": "Absolut MMI Home Delivery", "pages": 2, "by_source": {"title suffix/prefix": 2}},
                    {"normalized": "france mmi home delivery", "name": "France MMI Home Delivery", "pages": 2, "by_source": {"title suffix/prefix": 2}}]}}]},
            {"check_id": "PRF-1", "status": "findings", "findings": [
                {"id": "P", "rule_id": "prf1.slow", "title": "1 page(s) take more", "scope": {"urls": u[:1]}, "evidence": {"pages": []}}]}]}
    affected, changes = {"T": list(u)}, []
    reassess_rules._decisions_360(report, affected, changes)
    by = {f["id"]: f for c in report["checks"] for f in c["findings"]}
    assert by["T"]["title"] == "1 page(s) have no <title>" and affected["T"] == [u[2]]  # a: own title, b: in the body
    assert "H" not in by and "N" not in by  # no reason recorded; only page subjects besides the brand
    assert by["P"]["evidence"]["pages_measured"] == 3
