"""DECISIONS 327: Akıllı ~150 (v0.3 Stage 5). Typing before reading, the team's budget rule and split, two waves with
re-typing, the main language version, the crawl order, coverage per page type, Firecrawl only where needed, the web
mode and the "Sektör seçilmedi" line of the Sektör audit. Offline: synthetic addresses and an in-memory site."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import httpx
import pytest

from maya_audit import business_types as bt, client_selection as cs, sampling, sector_audit, xlsx
from maya_audit.audit import run_audit
from maya_audit.config import CrawlConfig
from maya_audit.report import build_report
from maya_audit.schema import frozen_path
from maya_audit.models import to_jsonable
from test_deadline_hosted_hardening import QUIET

ROOT = Path(__file__).resolve().parents[1]
H = "https://klinik.test"
SAGLIK = bt.profile("saglik")


# ---------------------------------------------------------------- typing before reading

@pytest.mark.parametrize("url,want", [
    (H + "/locations.kml", "file"),
    (H + "/tr/", "home"),
    (H + "/tr/arama/", "utility"),
    (H + "/tr/cocuklarda-secici-yeme-ne-zaman-klinik-sorun/", "guide"),   # a long top-level slug: a blog post
    (H + "/tr/anlasmali-kurumlar/", "insurers"),
    (H + "/tr/doktorlarimiz/", "doctors"),
])
def test_addresses_are_typed_before_reading(url, want):
    assert sampling.pre_type(SAGLIK, url, folders=("tr",))[0] == want


# ---------------------------------------------------------------- the budget rule and the team's split

def test_small_types_in_full_large_ones_thirty_and_the_reserve():
    counts = {"treatment": 80, "doctors": 3, "clinic": 4, "appointment": 2, "insurers": 1, "guide": 140, "other": 300,
              "policy": 5, "utility": 4}
    alloc = sampling.allocate(counts, SAGLIK, 146)
    assert alloc["doctors"] == 3 and alloc["clinic"] == 4 and alloc["appointment"] == 2 and alloc["insurers"] == 1
    assert alloc["treatment"] >= 30 and alloc["guide"] >= 30
    assert alloc["policy"] == 3 and alloc["utility"] == 2 and alloc["other"] >= 10
    assert sum(alloc.values()) == 146
    tight = sampling.allocate({"treatment": 80, "guide": 140, "doctors": 3}, SAGLIK, 40)
    assert tight["doctors"] == 3 and tight["treatment"] == 30 and sum(tight.values()) <= 40  # floors in rank order


def test_inside_a_large_type_the_teams_split_rotates_over_url_templates():
    pool = [f"{H}/tr/tedavi/{t}/{i}/" for t in ("a", "b", "c") for i in range(30)]
    lastmods = {u: f"2026-10-{(i % 28) + 1:02d}" for i, u in enumerate(pool)}
    patterns = {u: u.rsplit("/", 2)[0] for u in pool}
    picks = sampling.choose(pool, 30, folders=("tr",), menu_linked={pool[0]}, lastmods=lastmods, patterns=patterns)
    slots = Counter(slot for _, slot in picks)
    assert slots == {"importance": 10, "long_tail": 10, "newest": 5, "exception": 5}
    assert picks[0][0] == pool[0]  # the menu-linked page first
    assert len({patterns[u] for u, _ in picks[:3]}) == 3  # rotating over the templates
    assert sampling.choose(pool[:5], 30, folders=(), menu_linked=set(), lastmods={}, patterns={}) == [(u, "all") for u in pool[:5]]


def _sampler(extra=()):
    s = sampling.Sampler("saglik", budget=40, folders=("tr", "en"), main="tr")
    urls = ([H + "/tr/", H + "/en/", H + "/tr/anlasmali-kurumlar/", H + "/tr/iletisim/", H + "/tr/doktorlarimiz/"]
            + [f"{H}/tr/tedaviler/t{i}/" for i in range(40)] + [f"{H}/tr/hizmet/s{i}/" for i in range(12)] + list(extra))
    s.add(urls)
    return s


def test_the_order_rotates_over_types_and_fills_the_budget():
    s = _sampler()
    order = s.plan(fixed=[H + "/tr/", H + "/en/"])
    assert len(order) == 40 and order[:2] == [H + "/tr/", H + "/en/"]
    first = order[2:10]
    assert {H + "/tr/anlasmali-kurumlar/", H + "/tr/iletisim/", H + "/tr/doktorlarimiz/"} <= set(first)
    rec = s.record()
    assert rec["mode"] == "smart" and rec["types"]["insurers"] == {**rec["types"]["insurers"], "known": 1, "planned": 1}
    assert sum(r["planned"] for r in rec["types"].values()) == 40


def test_after_the_first_wave_unread_addresses_follow_their_url_template():
    s = _sampler()
    s.plan(fixed=[H + "/tr/"])
    service = [f"{H}/tr/hizmet/s{i}/" for i in range(12)]
    assert all(s.types[u][0] == "other" for u in service)
    analysis = {"title": "Psikiyatri tedavisi", "h1_elements": [{"text": "Tedavi"}], "structured_data": {"types": ["MedicalTherapy"]}}
    read = s.retype({u: analysis for u in service[:4]})
    assert set(read.values()) == {"treatment"} and s.retyped == 8
    assert all(s.types[u][0] == "treatment" for u in service)
    order = s.plan(fixed=[H + "/tr/"], read=read)
    assert not set(order) & set(service[:4])  # pages read are not planned again


def test_the_main_language_version_and_every_language_homepage():
    s = sampling.Sampler("saglik", budget=30, folders=("tr", "en", "ru"), main="tr")
    s.add([H + "/tr/", H + "/en/", H + "/ru/", H + "/en/contact-us/", H + "/tr/iletisim/", H + "/en/our-team/"])
    homes = [u for u, (t, _) in s.types.items() if t == "home"]
    assert homes == [H + "/tr/", H + "/en/", H + "/ru/"]
    order = s.plan(fixed=homes)
    # the main version first; another language's page of the same type only from the budget left over
    assert order.index(H + "/tr/iletisim/") < order.index(H + "/en/contact-us/")
    assert H + "/en/our-team/" in order  # no main version of that type: another language's page


# ---------------------------------------------------------------- the crawl

BLOG = [f"/tr/cocuklarda-uyku-sorunlari-ve-cozum-yollari-{i}/" for i in range(60)]
SPECIAL = ["/tr/depresyon-tedavisi/", "/tr/doktorlarimiz/", "/tr/iletisim/", "/tr/anlasmali-kurumlar/", "/tr/kvkk-aydinlatma-metni/"]
TEXT = "<p>" + "Hastanemiz uzman kadrosuyla hizmet verir ve hastalarına yardımcı olur. " * 12 + "</p>"
HTML = {"content-type": "text/html; charset=utf-8"}


def _doc(title, links=()):
    return (f'<!doctype html><html lang="tr"><head><title>{title}</title></head><body><nav><a href="/tr/">Ana sayfa</a></nav>'
            f'<main><h1>{title}</h1>{TEXT}' + "".join(f'<a href="{u}">{u}</a>' for u in links) + "</main></body></html>")


def _respond(request):
    path = request.url.path
    if path == "/robots.txt":
        return httpx.Response(200, text=f"User-agent: *\nAllow: /\nSitemap: {H}/sitemap.xml\n")
    if path == "/sitemap.xml":
        return httpx.Response(200, headers={"content-type": "application/xml"}, text=(
            '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            + "".join(f"<url><loc>{H}{u}</loc></url>" for u in BLOG + SPECIAL) + "</urlset>"))
    if path == "/":
        return httpx.Response(301, headers={"location": H + "/tr/"})
    if path == "/tr/":
        return httpx.Response(200, headers=HTML, text=_doc("Klinik", BLOG[:25]))
    if path in BLOG or path in SPECIAL:
        return httpx.Response(200, headers=HTML, text=_doc(path.strip("/").split("/")[-1]))
    return httpx.Response(404, headers=HTML, text="x")


def _crawl(smart: bool, pages: int = 10):
    cfg = CrawlConfig(**{**QUIET, "max_pages": pages, "sitemap_check_max": 0, "business_type": "saglik", "sampling": smart})
    return run_audit(H + "/", cfg, httpx.MockTransport(_respond))


def test_a_smart_crawl_reads_every_page_type_on_a_tight_budget():
    normal = {p.url.replace(H, "") for p in _crawl(False).result.pages if p.status == 200}
    outcome = _crawl(True)
    smart = {p.url.replace(H, "") for p in outcome.result.pages if p.status == 200}
    assert len(smart) == 10 and set(SPECIAL) <= smart
    assert not set(SPECIAL) <= normal  # the order links are found in leaves a page type out
    record = outcome.result.sampling
    assert record["mode"] == "smart" and record["profile"] == "saglik" and record["main"] == "tr"
    assert [w["wave"] for w in record["waves"]] == [1, 2] and record["planned_urls"][0] == H + "/tr/"
    report = json.loads(json.dumps(to_jsonable(build_report(outcome.result, outcome.gates, outcome.checks))))
    assert report["schema_version"] == "1.32" and report["crawl"]["sampling"]["types"]["insurers"]["known"] == 1
    assert _crawl(False).result.sampling is None


def test_coverage_per_page_type_in_the_reports():
    outcome = _crawl(True)
    report = json.loads(json.dumps(to_jsonable(build_report(outcome.result, outcome.gates, outcome.checks))))
    rows = {r["type"]: r for r in sampling.coverage(report)}
    assert rows["insurers"]["read"] == 1 and rows["insurers"]["state"] == "all"
    assert rows["clinic"]["state"] == "none"
    text = sampling.coverage_text(list(rows.values()), "tr")
    assert "Anlaşmalı kurumlar: 1/1 okundu" in text and "Klinik ve konum: bulunamadı" in text
    assert sampling.coverage_text(list(rows.values()), "en").startswith("Smart sample, page types: ")
    lines = cs.select(report)["coverage"]["lines"]
    assert any(line["kind"] == "sampling" for line in lines)
    from maya_audit.client_appendix import coverage_text
    assert "Klinik ve konum: bulunamadı" in coverage_text(next(x for x in lines if x["kind"] == "sampling"), "tr")
    sel = cs.select(report, business="saglik")
    res = sector_audit.evaluate(report, sel, None, "saglik")
    clinic = next(r for r in res["sec"] if r["type_id"] == "clinic" and r["dimension"] == "Sektöre Özel")
    assert "Akıllı örneklem: Klinik ve konum: bulunamadı." in clinic["reason"]


# ---------------------------------------------------------------- Firecrawl only where needed

def test_firecrawl_reads_blocked_pages_javascript_templates_and_one_page_per_template():
    from maya_audit.firecrawl.reader import needed_scope
    from maya_audit.firecrawl.settings import Options
    from maya_audit.models import FetchClass
    outcome = _crawl(False, pages=12)
    result = outcome.result
    ok = [p for p in result.pages if p.status == 200]
    blocked = ok[-1]
    blocked.fetch_class, blocked.content_checks_eligible = FetchClass.BLOCKED, False
    shell = ok[1]
    shell.analysis = {**shell.analysis, "mount_nodes": [{"id": "app", "chars": 0}], "visible_words": 3,
                      "noscript_text": "Please enable JavaScript"}
    scope = needed_scope(result, outcome.config if hasattr(outcome, "config") else CrawlConfig(**QUIET))
    wanted = {p.url: scope["wanted"](p.url) for p in ok}
    assert wanted[blocked.url] and wanted[shell.url]
    assert scope["record"]["counts"]["cross_check"] >= 1 and scope["record"]["counts"]["maya_copy_enough"] >= 1
    assert not scope["wanted"](H + "/never-asked/")
    assert Options(read_scope="needed").problem() is None and Options(read_scope="x").problem()
    from maya_audit_web.fc import options_from
    assert options_from({"read_scope": "needed"}).read_scope == "needed" and options_from({}).read_scope == "all"


# ---------------------------------------------------------------- the web mode

def test_the_smart_mode_in_the_web_app(tmp_path):
    from maya_audit_web import runner
    from maya_audit_web.strings import t
    assert runner.MODES == {"single": 1, "quick": 50, "smart": 150, "standard": 500}
    config = runner.crawl_config(runner.Engine(), {"url": "https://example.test/", "mode": "smart", "key_pages": []},
                                 tmp_path / "c.db", resume=False)
    assert config.sampling and config.max_pages == 150
    quick = runner.crawl_config(runner.Engine(), {"url": "https://example.test/", "mode": "quick", "key_pages": []},
                                tmp_path / "d.db", resume=False)
    # DECISIONS 331: every mode reads the Akıllı selection; "Tam tarama sırası" keeps the crawl's own order
    assert quick.sampling and quick.max_pages == 50
    order = runner.crawl_config(runner.Engine(), {"url": "https://example.test/", "mode": "quick", "key_pages": [],
                                                  "crawl_order": True}, tmp_path / "e.db", resume=False)
    assert not order.sampling
    assert t("new.mode.smart", "tr") == "Akıllı ~150 (önerilen)" and t("new.mode.quick", "tr") == "Hızlı ~50"
    assert t("fc.full_read", "tr") == "Tam okuma (Firecrawl her sayfa)"
    script = (ROOT / "maya_audit_web" / "static" / "app.js").read_text(encoding="utf-8")
    assert 'draft: { mode: "quick"' in script  # Quick stays the default until a live run confirms Akıllı's time


def test_a_smart_plan_reads_through_firecrawl_only_where_needed_unless_full_read():
    from test_web_app import API, web  # noqa: F401
    import maya_audit_web.app as app_module  # noqa: F401
    src = (ROOT / "maya_audit_web" / "app.py").read_text(encoding="utf-8")
    # DECISIONS 331: every sampled mode, not only Akıllı (the plan round trip is tested in test_live_fixes_329)
    assert '"read_scope": "needed" if sampled(chosen_mode) and not body.firecrawl_full_read else "all"' in src
    assert 'pattern="^(single|quick|smart|standard|custom)$"' in src


# ---------------------------------------------------------------- the Sektör audit without a business type

def test_the_sector_audit_says_when_no_sector_was_chosen(monkeypatch):
    from test_sector_method_324 import _sector_report
    monkeypatch.setattr(cs, "low_coverage", lambda report: None)
    r = _sector_report()
    r["crawl"]["business_type"] = {"id": "diger", "chosen_by": "person"}
    sel = cs.select(r, None, {}, business="diger")
    book = xlsx.read(sector_audit.build(r, sel, None, "diger"))
    assert book["Audit Özeti"][3][0] == "Sektör seçilmedi: sektörel satırlar için iş türünü seçin."
    assert book["Metodoloji"][-1][0] == "Sektör seçilmedi (Maya)"
    assert book["Audit Özeti"][4][0] == "Sektör"  # the team's header stays on row 5
    head, *rows = book["Sektörel SEO Kontrolleri"]
    reason = head.index("Maya: Durum nedeni")
    assert all(x[reason] == "Sektör seçilmedi: sektörel satırlar için iş türünü seçin." for x in rows)


# ---------------------------------------------------------------- the report shape and resuming

def test_the_frozen_schema_adds_sampling_and_nothing_else():
    from maya_audit.schema import differences
    old = json.loads(frozen_path("1.29").read_text(encoding="utf-8"))
    new = json.loads(frozen_path("1.30").read_text(encoding="utf-8"))
    assert differences(old, new) == ["crawl: added ['sampling']", "schema_version: '1.29' -> '1.30'"]


def test_a_crawl_without_sampling_keeps_its_resume_binding():
    from maya_audit.crawler import Crawler
    src = Path(__import__("maya_audit.crawler", fromlist=["x"]).__file__).read_text(encoding="utf-8")
    assert 'if not settings.get("sampling"):' in src and Crawler
