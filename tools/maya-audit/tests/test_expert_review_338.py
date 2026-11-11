"""DECISIONS 338: the SEO team's card-by-card review of enpara 2e5829fb (docs/expert-reviews/enpara-2e5829fb.json), each
rule checked against the saved evidence and fixed for every audit. Hand-written markup and synthetic saved reports;
a loopback fake site for the long pages. Offline."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from fakeserver import Response
from maya_audit.analysis import analyze_html
from maya_audit.checks.access import deliberate_rule
from maya_audit.checks.page_markup import head_closed_early_findings
from maya_audit.checks.structure import brand_key, drop_listing_pages
from maya_audit.reassess_rules import _decisions_338
from test_m1_broken_links import audit
from test_review_fixes import TR, page
from test_firecrawl import no_lookups  # noqa: F401  (fixture)

ROOT = Path(__file__).resolve().parents[1]


def head_page(after: str, url="https://bank.test/p") -> SimpleNamespace:
    html = ('<html><head><title>Sayfa</title><link rel="canonical" href="https://bank.test/p">'
            '<link rel="alternate" hreflang="en" href="https://bank.test/en/p">'
            f'<div id="blueLightOverlay"></div>{after}</head><body><h1>Sayfa</h1></body></html>')
    return SimpleNamespace(url=url, analysis=analyze_html(html, url))


# ------------------------------------------------------------------ card 1: the head closed early

def test_a_plain_robots_tag_after_the_break_is_medium_and_the_head_s_tags_are_named():
    [f] = head_closed_early_findings([head_page('<meta name="robots" content="index, follow"><meta name="description" content="d">')], set())
    assert f.severity.value == "S3" and f.title.endswith("meta or Open Graph tags after it are read as body")
    row = f.evidence["pages"][0]
    assert row["robots_content"] == ["index, follow"] and row["kept_in_head"] == ["canonical", "hreflang", "title"]
    assert row["closed_by"]["id"] == "blueLightOverlay"


@pytest.mark.parametrize("after", ['<meta name="robots" content="noindex">', '<meta name="googlebot" content="nosnippet">'])
def test_a_robots_tag_that_restricts_something_after_the_break_stays_high(after):
    [f] = head_closed_early_findings([head_page(after)], set())
    assert f.severity.value == "S2"


def test_a_second_canonical_after_the_break_is_a_duplicate_not_a_lost_canonical():
    [f] = head_closed_early_findings([head_page('<link rel="canonical" href="https://bank.test/p"><meta property="og:title" content="x">')], set())
    assert f.severity.value == "S3"


def test_a_canonical_only_after_the_break_is_high():
    html = ('<html><head><title>T</title><div id="w"></div><link rel="canonical" href="https://bank.test/p"></head>'
            '<body><h1>T</h1></body></html>')
    [f] = head_closed_early_findings([SimpleNamespace(url="https://bank.test/p", analysis=analyze_html(html, "https://bank.test/p"))], set())
    assert f.severity.value == "S2"


# ------------------------------------------------------------------ card 3: deliberate robots.txt rules

@pytest.mark.parametrize("pattern, kind", [("/*?ref=", "parameter"), ("/*?sort=*", "parameter"), ("/*.aspx$", "legacy"),
                                           ("/*.php$", "legacy"), ("/basvuru-amaciniz", "form"), ("/checkout/", "form"),
                                           ("/", None), ("/urunler/", None), ("/blog/", None)])
def test_parameter_legacy_and_form_rules_look_deliberate(pattern, kind):
    assert deliberate_rule(pattern) == kind


# ------------------------------------------------------------------ a saved report shaped like enpara's

def _saved():
    base = "https://www.bank.test"
    home = {"url": base + "/", "depth": 0, "status": 200, "headers": {"Strict-Transport-Security": "max-age=157680000"},
            "analysis": {}, "grouping": {"page_type": "home"}}
    listing = {"url": base + "/bilgi-bankasi", "depth": 1, "status": 200, "headers": {}, "analysis": {}, "grouping": {"page_type": "category"}}
    terms = {"url": base + "/kosullar", "depth": 1, "status": 200, "headers": {}, "analysis": {}, "grouping": {"page_type": "policy"}}

    def f(cid, title, sev, urls, ev, rule=None):
        return {"check_id": cid, "title": title, "severity": sev, "confidence": "verified", "scope": {"kind": "page", "count": len(urls), "urls": urls},
                "evidence": ev, "notes": [], "id": f"{cid}-{abs(hash(title)) % 10**8:08d}", "rule_id": rule}
    variant = lambda name, n, src, urls: {"name": name, "pages": n, "by_source": {src: n},  # noqa: E731
                                          "seen_as": [{"source": src, "value": name, "url": u} for u in urls]}
    checks = [
        {"check_id": "ACC-2", "findings": [f("ACC-2", "robots.txt line 12 (Disallow: /*?ref=) blocks search bot(s) Googlebot on 1 sampled URL(s)", "S3",
                                             [base + "/x?ref=1"], {"rule": {"line": 12, "pattern": "/*?ref="}, "path_kind": {"kind": "not_put_forward"}},
                                             "acc2.blocks.sample"),
                                           f("ACC-2", "robots.txt line 3 (Disallow: /urun/) blocks search bot(s) Googlebot on 1 sampled URL(s)", "S1",
                                             [base + "/urun/a"], {"rule": {"line": 3, "pattern": "/urun/"}, "path_kind": {"kind": "put_forward"}},
                                             "acc2.blocks.sample")]},
        {"check_id": "STR-5", "findings": [f("STR-5", "The brand is named 5 different ways", "S4", [base + "/"], {"variants": [
            variant("Enpara", 86, "title suffix/prefix", [base + "/"]), variant("Enpara.com", 49, "Organization name", [base + "/iletisim"]),
            variant("Enpara Şirketim", 17, "og:site_name", [base + "/sirketim/a"]),
            variant("Bankanın güzeli | Enpara", 1, "Organization name", [base + "/"]),
            variant("Homepage", 1, "Organization name", [base + "/en/homepage"])]}, "str5.names")]},
        {"check_id": "STR-2", "findings": [f("STR-2", "2 long page(s) (>800 words) have no subheadings", "S4", [listing["url"], terms["url"]],
                                             {"pages": [{"url": listing["url"]}, {"url": terms["url"]}]}, "str2.no_subheadings")]},
        {"check_id": "IDX-2", "findings": [f("IDX-2", "http:// redirects to https:// with a temporary redirect on bank.test, www.bank.test", "S4",
                                             ["http://bank.test/"], {"hosts": [{"host": "bank.test", "status": 302}]}, "idx2.temporary")]},
    ]
    return {"checks": checks, "crawl": {"start_url": base + "/", "pages": [home, listing, terms]}}


def test_a_saved_report_gets_the_four_rule_fixes():
    report, affected, changes = _saved(), {}, []
    _decisions_338(report, affected, changes)
    by = {c["check_id"]: c["findings"] for c in report["checks"]}
    deliberate, kept = by["ACC-2"]
    assert deliberate["severity"] == "Info" and deliberate["intent"]["kind"] == "deliberate_rule"
    assert deliberate["notes"][-1].startswith("Reported as Info: the rule (/*?ref=) blocks only addresses with a query parameter")
    assert kept["severity"] == "S1"  # a rule that reaches a page the site puts forward keeps its severity
    [brand] = by["STR-5"]
    assert brand["title"] == "The brand is named 3 different ways"
    assert brand["scope"]["urls"] == ["https://www.bank.test/", "https://www.bank.test/en/homepage"]
    assert brand["evidence"]["sub_brands_not_counted"] == ["Enpara Şirketim"] and affected[brand["id"]] == brand["scope"]["urls"]
    [flat] = by["STR-2"]
    assert flat["title"] == "1 long page(s) (>800 words) have no subheadings" and flat["scope"]["urls"] == ["https://www.bank.test/kosullar"]
    assert flat["evidence"]["listing_pages_left_out"] == ["https://www.bank.test/bilgi-bankasi"]
    [http] = by["IDX-2"]
    assert http["severity"] == "Info" and "1825 days" in http["notes"][-1]
    assert sum("DECISIONS 338" in c for c in changes) >= 4


def test_only_the_domain_form_and_a_sub_brand_leave_no_brand_finding():
    report = _saved()
    by = {c["check_id"]: c for c in report["checks"]}
    by["STR-5"]["findings"][0]["evidence"]["variants"] = by["STR-5"]["findings"][0]["evidence"]["variants"][:3]
    _decisions_338(report, {}, [])
    assert by["STR-5"]["findings"] == []


@pytest.mark.parametrize("name, key", [("Enpara.com", "enpara"), ("www.enpara.com.tr", "enpara"), ("Booking.com", "booking"),
                                       ("Bankanın güzeli | Enpara", "bankanın güzeli enpara"), ("Acme Inc.", "acme")])
def test_the_domain_form_of_a_brand_is_the_brand(name, key):
    assert brand_key(name) == key


# ------------------------------------------------------------------ card 6: H1 wording

def test_the_team_report_says_h1_etiketi_for_every_h1_rule():
    rules = json.loads((ROOT / "maya_audit_web/team_report/texts/tr.json").read_text(encoding="utf-8"))["rules"]
    for key in ("str2.no_h1", "str2.home_no_h1", "str2.many_h1", "str2.empty_h1", "str2.hidden_h1", "str2.home_hidden_h1"):
        text = json.dumps(rules[key], ensure_ascii=False)
        assert "ana başlı" not in text.lower() and "H1 etiket" in text, key
    assert rules["str2.no_h1"]["title"] == "H1 etiketi olmayan sayfalara tek bir H1 etiketi ekleyin"


# ------------------------------------------------------------------ card 9: long pages, styled titles, listings

WORDS = " ".join([TR] * 12)


def test_styled_section_titles_are_counted_and_said_as_titles_without_tags():
    titles = "".join(f'<button aria-expanded="false">Soru {i}</button><p>{WORDS}</p>' for i in range(3))
    outcome, base = audit({
        "/robots.txt": Response(body="User-agent: *\nAllow: /\n", content_type="text/plain"),
        "/sitemap.xml": Response(404, "", content_type="text/plain"),
        "/": page(f"<h1>Ana sayfa</h1><p>{TR}</p><a href=\"/sss\">SSS</a> <a href=\"/kosullar\">Koşullar</a>", nav=""),
        "/sss": page(f"<h1>SSS</h1>{titles}", nav=""),
        "/kosullar": page(f"<h1>Koşullar</h1><p>{WORDS}</p><p>{WORDS}</p><p>{WORDS}</p>", nav=""),
    })
    found = {f.rule_id: f for c in outcome.checks if c.check_id == "STR-2" for f in c.findings}
    assert found["str2.styled_subheadings"].scope["urls"] == [base + "/sss"]
    assert found["str2.no_subheadings"].scope["urls"] == [base + "/kosullar"]


def test_a_listing_page_is_left_out_of_long_pages_without_subheadings():
    from maya_audit.findings import Finding, Severity, scope_for
    from maya_audit.models import Confidence
    f = Finding("STR-2", "2 long page(s) (>800 words) have no subheadings", Severity.S4, Confidence.VERIFIED, "Hypothesis", [],
                scope_for(["https://s.test/list", "https://s.test/doc"]), {"pages": [{"url": "https://s.test/list"}, {"url": "https://s.test/doc"}]},
                "", "")
    check = SimpleNamespace(check_id="STR-2", findings=[f])
    drop_listing_pages([check], {"https://s.test/list": "category", "https://s.test/doc": "policy"})
    assert f.title.startswith("1 long page(s)") and f.scope["urls"] == ["https://s.test/doc"] and f.rule_id == "str2.no_subheadings"


# ------------------------------------------------------------------ cards 12-13: every note card lists its pages

def test_a_note_card_s_addresses_are_rows_of_the_appendix_with_what_was_seen():
    from maya_audit import page_rows
    todos = [{"n": 13, "title": "Soru başlıklarını düzeltin", "severity": "Info", "finding_ids": ["STR-2"],
              "all_urls": ["https://s.test/sss", "https://s.test/odemeler"], "steps": "Soruları başlık yapın",
              "url_notes": {"https://s.test/sss": "480 soru düz metin: «Kod neden istendi?»"}}]
    rows = page_rows.finding_rows({"groups": []}, None, "tr", todos=todos)
    assert [(r["card"], r["url"], r["value"]) for r in rows] == [(13, "https://s.test/sss", "480 soru düz metin: «Kod neden istendi?»"),
                                                                 (13, "https://s.test/odemeler", "")]
    assert page_rows.card_pages(rows, 13)[0]["values"] == ["480 soru düz metin: «Kod neden istendi?»"]


# ------------------------------------------------------------------ item 8: the review is kept as accuracy data

def test_the_expert_review_is_kept_per_rule_with_its_follow_up():
    review = json.loads((ROOT / "docs/expert-reviews/enpara-2e5829fb.json").read_text(encoding="utf-8"))
    rules = {k for rows in json.loads((ROOT / "maya_audit/rule_ids.json").read_text(encoding="utf-8"))["rules"].values() for k, _ in rows}
    cards = review["cards"]
    assert [c["card"] for c in cards] == list(range(1, 14))
    assert all(c["verdict"] in ("correct", "wrong", "wording", "incomplete") for c in cards)
    assert all(r in rules for c in cards for r in c["rule_ids"])
    assert review["follow_up"] == sorted({r for c in cards if c["verdict"] == "wrong" for r in c["rule_ids"]})
    assert review["summary"] == {"correct": 4, "wrong": 5, "wording": 1, "incomplete": 3}
