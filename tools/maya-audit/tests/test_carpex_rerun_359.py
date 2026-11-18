"""DECISIONS 359: the review of the Carpex re-audit (149 of 150 read, a draft) as global rules. (1) a merged card counts
the union of its findings' addresses, never their counts added up; (2) pages the site's earlier address answers itself
after the crawl moved to its twin are one card and are read once; (3) contact, about and references pages are never
categories; (4) Maya's raw topic keys are shown readably. Mock-transport sites and made-up records only."""
from __future__ import annotations

import json
from types import SimpleNamespace

import httpx

from maya_audit import page_groups, page_rows
from maya_audit.audit import run_audit
from maya_audit.config import CrawlConfig
from maya_audit.models import to_jsonable
from maya_audit.report import build_report
from test_deadline_hosted_hardening import QUIET
from test_firecrawl import no_lookups  # noqa: F401

HTML = {"content-type": "text/html; charset=utf-8"}
BARE, WWW = "https://shop.test", "https://www.shop.test"
TEXT = "<p>" + "Kokular, makineler ve kartuşlar için güvenilir alışveriş, hızlı kargo ve iade. " * 10 + "</p>"
PAGES = ["/makineler", "/kartuslar", "/kokular-55", "/bize-ulasin-", "/referanslarimiz"]
PRODUCTS = [f"/koku-makinesi-model-{i}-{100 + i}" for i in range(4)]


# ---------------------------------------------------------------- 1: a merged card's scope

def _labels(lang):
    from maya_audit_web.team_report import build_data
    return build_data.load(build_data.REFS / "etiketler.json")[lang]


def scope(members, affected, lang="tr"):
    from maya_audit_web.team_report import build_data
    facts = []
    me = SimpleNamespace(groups=lambda: [members], affected=affected, L=_labels(lang), lang=lang, sel={},
                         unit_for=lambda f, m=None: "page", fact=lambda *v: facts.extend(v))
    return build_data.Builder.group_scope(me, members[0]), facts


def test_a_merged_card_counts_the_union_of_its_findings_never_their_counts_added_up():
    site = {"id": "a", "scope": {"count": 11, "urls": [f"u{i}" for i in range(11)]}}
    names = {"id": "b", "scope": {"count": 94, "urls": ["u0", "u1", "x2", "x3", "x4"]}}  # only examples listed
    text, facts = scope([site, names], {"a": site["scope"]["urls"], "b": names["scope"]["urls"]})
    assert text == "en az 94 sayfa" and 94 in facts and "105" not in text  # carpex card 14 said "105 sayfa"
    assert scope([site, names], {}, "en")[0] == "at least 94 pages"
    both = {"id": "c", "scope": {"count": 3, "urls": ["u0", "u1", "z"]}}
    assert scope([site, both], {})[0] == "12 sayfa"  # complete lists: the union (two shared pages counted once)
    from maya_audit.report import group_pages
    F = lambda n, urls: SimpleNamespace(scope={"count": n, "urls": urls, "kind": "template"})  # noqa: E731
    assert group_pages([F(11, [f"u{i}" for i in range(11)]), F(94, ["u0"])]) == 94


# ---------------------------------------------------------------- 2: the twin address's copies

def shop():
    """The bare host answers its homepage and two pages itself, redirects the rest to www (Carpex's shape after the
    re-audit); every page names its www address as canonical."""
    def page(path, extra=""):
        return (f'<!doctype html><html lang="tr"><head><title>{path}</title><link rel="canonical" href="{WWW}{path}">'
                f'</head><body><main><h1>{path}</h1>{TEXT}{extra}</main></body></html>')
    links = "".join(f'<a href="{BARE}{p}">{p}</a>' for p in PAGES + PRODUCTS)
    items = "".join(f'<a href="{BARE}{p}">{p}</a>' for p in PRODUCTS)

    def respond(request):
        host, path = request.url.host, request.url.path
        if path == "/robots.txt":
            return httpx.Response(200, text=f"User-agent: *\nAllow: /\nSitemap: {WWW}/sitemap.xml\n")
        if path == "/sitemap.xml":
            return httpx.Response(404, headers=HTML, text="<h1>yok</h1>")
        if host == "shop.test" and path not in ("/", "/kokular-55", "/makineler"):
            return httpx.Response(301, headers={"location": WWW + path})
        if path == "/":
            return httpx.Response(200, headers=HTML, text=page("/", f"<nav>{links}</nav>"))
        if path in PAGES:
            return httpx.Response(200, headers=HTML, text=page(path, f"<section>{items}</section>"))
        if path in PRODUCTS:
            return httpx.Response(200, headers=HTML, text=page(path))
        return httpx.Response(404, headers=HTML, text="<h1>yok</h1>")
    return respond


def crawl():
    config = CrawlConfig(**{**QUIET, "max_pages": 30, "sitemap_check_max": 0, "business_type": "eticaret"})
    outcome = run_audit(BARE + "/", config, httpx.MockTransport(shop()))
    return outcome, json.loads(json.dumps(to_jsonable(build_report(outcome.result, outcome.gates, outcome.checks))))


def test_pages_the_earlier_address_serves_itself_are_one_card_and_read_once(no_lookups):  # noqa: F811
    outcome, r = crawl()
    crawl_ = r["crawl"]
    assert crawl_["origin"] == WWW
    copies = {c["url"] for c in crawl_["host_moves"][0]["copies"]}
    assert copies == {BARE + "/kokular-55", BARE + "/makineler"}
    read = {p["url"] for p in crawl_["pages"] if p.get("analysis")}
    assert {WWW + "/kokular-55", WWW + "/makineler"} <= read and not copies & read  # each page read once, on www
    findings = {f["rule_id"]: f for c in r["checks"] for f in c["findings"]}
    card = findings["idx4.twin_served"]
    assert card["title"] == "3 page(s) on shop.test answer with their content instead of redirecting to www.shop.test"
    assert set(card["scope"]["urls"]) == copies | {BARE + "/"}  # the start page answered itself too
    assert "idx4.variant" not in findings  # the same problem is not told twice


def test_a_saved_audit_gets_the_card_offline_from_its_page_records(no_lookups):  # noqa: F811
    from maya_audit import reassess_rules
    outcome, r = crawl()
    move = r["crawl"]["host_moves"][0]
    move.pop("copies")  # as a report saved before DECISIONS 359
    for c in r["checks"]:
        c["findings"] = [f for f in c["findings"] if f["rule_id"] != "idx4.twin_served"]
    for p in r["crawl"]["pages"]:
        if p["url"] in (BARE + "/kokular-55",):
            p["analysis"] = {"canonicals": [WWW + "/kokular-55"]}
    affected, changes = {}, []
    reassess_rules._decisions_359(r, affected, changes)
    card = next(f for c in r["checks"] for f in c["findings"] if f["rule_id"] == "idx4.twin_served")
    assert BARE + "/kokular-55" in card["scope"]["urls"] and affected[card["id"]] == card["scope"]["urls"]
    assert any("DECISIONS 359" in line for line in changes)


# ---------------------------------------------------------------- 3: contact and references pages

def test_contact_about_and_references_pages_are_never_categories(no_lookups):  # noqa: F811
    assert page_groups.basic_page("https://x.test/bize-ulasin-") == "contact"
    assert page_groups.basic_page("https://x.test/referanslarimiz") == "references"
    assert page_groups.basic_page("https://x.test/hakkimizda") == "about"
    assert page_groups.basic_page("https://x.test/kokular-55") is None
    outcome, r = crawl()
    g = {p["url"]: p.get("grouping") or {} for p in r["crawl"]["pages"] if p.get("analysis")}
    for path, kind in (("/bize-ulasin-", "basic_contact"), ("/referanslarimiz", "basic_references")):
        rec = g[WWW + path]
        assert rec["page_type"] == "other" and rec["business_page_type"] != "category"
        assert page_rows.page_kind_of(rec) == kind
    from maya_audit.client_appendix import WORDS
    assert page_rows.type_word("basic_contact", "tr", "eticaret", WORDS["tr"]["page_type"]) == "iletişim sayfası"


# ---------------------------------------------------------------- 4: readable topic names

def test_raw_topic_keys_are_shown_as_words_spelt_as_the_prompts_spell_them():
    from maya_audit.maya_sheets import topic_name
    summary = {"ai": {"prompts": {"a": {"text": "Koku makinesinin bakımı ne kadar enerji harcar?", "topic": "makine-bakim-enerji"},
                                  "b": {"text": "Kartuş maliyeti", "topic": "Kartuş Maliyeti"}}}}
    assert topic_name("makine-bakim-enerji", summary, ["Koku makinesinin bakımı ne kadar enerji harcar?"]) == "Makine bakım enerji"
    assert topic_name("kartus-maliyeti", summary) == "Kartuş Maliyeti"  # Maya's own label for the same key
    assert topic_name("koku-secimi", summary) == "Koku secimi"  # no prompt spells it: the letters are not guessed
    assert topic_name("Koku Makineleri", summary) == "Koku Makineleri"
