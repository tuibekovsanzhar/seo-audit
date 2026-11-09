"""DECISIONS 329: fixes from the first live Akıllı runs (moodisthastanesi 2d72fea0, enpara 87f0425a). The audit's total
and step times; Firecrawl only where needed (the plan's choice reaches the audit, a redirect or a 4xx is not "could not
read", templates as the page grouping sees them); a person's profile typed by its content and an article's publisher
markup left out; IDX-8's place-name groups only on location pages; a High card at least P2; the client brief with
measured problems only and precise "already good" lines; broken links with sitemap entries for developer and content.
Offline: synthetic records, an in-memory site and Firecrawl, the demo web app."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from maya_audit import business_types as bt
from maya_audit import priority_levels as pl
from maya_audit import step_times
from maya_audit.checks.index import LOCATION_RULE, gate_location_templates, location_template_kept
from maya_audit.findings import CheckResult, Confidence, Finding, Severity, scope_for
from maya_audit.firecrawl.reader import needed_scope
from maya_audit.firecrawl.settings import Options
from maya_audit.models import FetchClass, PageFetch, StopReason, CrawlResult
from maya_audit.config import CrawlConfig
from test_web_app import web  # noqa: F401  (fixture)

ROOT = Path(__file__).resolve().parents[1]
H = "https://klinik.test"
WORDS = "Bu sayfa kendi içeriğini anlatan yeterince uzun bir metin içerir ve okunur. " * 4


# ---------------------------------------------------------------- 1: time

def _timed_report(reader=True):
    return {"crawl": {"elapsed_s": 1210.9, "finished_at": "2026-11-09T06:59:28+00:00", "steps": [
        {"step": "sitemap", "seconds": 15.5}, {"step": "crawl", "seconds": 394.4},
        {"step": "other_sites", "seconds": 22.9}, {"step": "access", "seconds": 137.3},
        {"step": "sitemap_check", "seconds": 236.5, "beside": ["access", "index", "structure", "render"]},
        {"step": "render", "seconds": 258.5}, {"step": "page_reader", "seconds": 447.5}]},
        "generation": {"native_finished_at": "2026-11-09T06:59:28+00:00", "processed_at": "2026-11-09T07:00:22+00:00"},
        "firecrawl": {"used": reader}}


def test_total_and_step_times_come_from_the_report():
    info = step_times.summary(_timed_report())
    assert info["total_s"] == 1264.9  # Maya's own wall time + 54 s to the report
    steps = {r["id"]: r for r in info["steps"]}
    assert steps["finishing"]["seconds"] == 54.0 and not steps["finishing"]["beside"]
    assert steps["sitemap_check"]["beside"] and steps["page_reader"]["beside"] and steps["other_sites"]["beside"]
    tr, en = step_times.text(info, "tr"), step_times.text(info, "en")
    assert tr.startswith("Denetim süresi 21 dk 5 sn: site haritasını okuma 16 sn · sayfaları okuma 6 dk 34 sn")
    assert "; yanında: başka sitelere bağlantılar 23 sn · site haritasındaki adresleri kontrol 3 dk 56 sn · Firecrawl ile okuma 7 dk 28 sn." in tr
    assert "sonuçlar, Firecrawl kopyaları ve rapor 54 sn" in tr
    assert en.startswith("Audit time 21 min 5 s: reading the sitemap 16 s")
    assert "results and the report 54 s" in step_times.text(step_times.summary(_timed_report(reader=False)), "en")
    assert step_times.summary({"crawl": {}}) is None and step_times.text(None) is None
    assert [step_times.duration(s) for s in (5, 60, 61, 3600)] == ["5 sn", "1 dk", "1 dk 1 sn", "60 dk"]


def test_the_web_page_and_the_team_report_show_the_times():
    app = (ROOT / "maya_audit_web" / "app.py").read_text(encoding="utf-8")
    assert '"timing": timing_view(report),' in app and "def timing_view(" in app
    script = (ROOT / "maya_audit_web" / "static" / "app.js").read_text(encoding="utf-8")
    assert "planNode || null, timingSlot, parts" in script and "context.onTiming(view.timing)" in script
    from maya_audit_web.strings import t
    assert t("job.timing.total", "tr", time="21 dk 5 sn") == "Toplam: 21 dk 5 sn"
    assert t("job.timing.beside", "en") == "beside the other steps"
    data = (ROOT / "maya_audit_web" / "team_report" / "build_data.py").read_text(encoding="utf-8")
    assert "step_times.text(step_times.summary(self.r), lang)" in data


def test_the_team_report_coverage_section_has_the_time(tmp_path):
    from test_team_report import built, synthetic
    report = synthetic([("STR-2", "str2.no_h1")])
    report["crawl"] = {**report.get("crawl", {}), **_timed_report()["crawl"]}
    report["generation"] = _timed_report()["generation"]
    data = built(tmp_path, report, "tr")
    text = json.dumps(data, ensure_ascii=False)
    assert "Denetim süresi 21 dk 5 sn: " in text


# ---------------------------------------------------------------- 2: Firecrawl only where needed

def test_the_options_keep_the_read_scope_through_the_plan():
    from maya_audit_web.fc import options_from
    saved = Options(read_scope="needed").as_dict()
    assert saved["read_scope"] == "needed"
    assert options_from(saved).read_scope == "needed"  # the web app stores as_dict() and rebuilds the options from it
    assert options_from(Options().as_dict()).read_scope == "all"


def test_a_smart_web_plan_saves_needed_and_full_read_saves_all(web, tmp_path):  # noqa: F811
    from test_web_app import Site, cloudflare, plan
    from test_web_firecrawl import Firecrawl, PAGES, services
    client = web(site=Site(respond=cloudflare), firecrawl=services(tmp_path, Firecrawl(PAGES)))
    assert plan(client, mode="smart")["firecrawl"]["options"]["read_scope"] == "needed"
    assert plan(client, mode="smart", firecrawl_full_read=True)["firecrawl"]["options"]["read_scope"] == "all"
    assert plan(client, mode="quick")["firecrawl"]["options"]["read_scope"] == "all"


def test_the_cli_smart_mode_reads_through_firecrawl_only_where_needed():
    src = (ROOT / "maya_audit" / "cli.py").read_text(encoding="utf-8")
    assert 'read_scope="needed" if getattr(args, "smart", False) and not getattr(args, "firecrawl_full_read", False)' in src
    from maya_audit.cli import _parser as build_parser
    args = build_parser().parse_args(["crawl", "https://x.test/", "--smart", "--firecrawl-full-read", "--no-firecrawl"])
    assert args.smart and args.firecrawl_full_read


def _page(url, status=200, fetch=FetchClass.OK, error=None, analysis=None, location=None):
    a = analysis if analysis is not None else {"title": url, "visible_words": 300, "mount_nodes": [], "headings": [],
                                               "h1_elements": [], "structured_data": {"types": []}}
    return PageFetch(url=url, discovered_via="link", depth=1, requested_at="2026-11-09T00:00:00+00:00", user_agent="ua",
                     status=status, error=error, elapsed_ms=10.0, content_type="text/html", body_bytes=1000,
                     body_truncated=False, headers={}, fetch_class=fetch, classification_confidence=Confidence.VERIFIED,
                     classification_evidence=[], redirect_location=location, analysis=a if 200 <= (status or 0) < 300 else {})


def _result(pages, known=()):
    return CrawlResult(start_url=H + "/", origin=H, user_agent="ua", product_token="Maya", started_at="", finished_at="",
                       elapsed_s=0.0, config={}, robots=[], pages=pages, skipped_robots=[], sitemap_docs=[],
                       sitemap_urls=list(known), discovered_urls=[], not_fetched_urls=[],
                       stop_reason=StopReason.PAGE_CAP, stop_detail="", requests=[])


def test_redirects_and_4xx_answers_are_not_pages_maya_could_not_read():
    pages = [_page(H + "/"), _page(H + "/old/", 301, location=H + "/"), _page(H + "/gone/", 404),
             _page(H + "/busy/", 429, FetchClass.RATE_LIMITED), _page(H + "/wall/", 403, FetchClass.BLOCKED),
             _page(H + "/down/", 503), _page(H + "/cut/", None, FetchClass.ERROR, error="timeout"),
             _page(H + "/empty/", 200, analysis={"empty_response": True})]
    scope = needed_scope(_result(pages), CrawlConfig())
    wanted = {p.url.replace(H, ""): scope["wanted"](p.url) for p in pages}
    assert wanted == {"/": True, "/old/": False, "/gone/": False, "/busy/": True, "/wall/": True, "/down/": True,
                      "/cut/": True, "/empty/": True}
    counts = scope["record"]["counts"]
    assert counts["site_answer"] == 2 and counts["not_read_by_maya"] == 5 and counts["cross_check"] == 1


def test_one_cross_check_per_template_as_the_page_grouping_sees_it():
    """moodist: blog posts at /tr/<slug>/ beside /tr/<section>/... were 80 templates for 149 pages when only the pages
    read were patterned; with every known address (the sitemap) they are one template."""
    posts = [f"{H}/tr/yazi-numara-{w}-uzun-bir-baslik/" for w in ("bir", "iki", "uc", "dort", "bes", "alti")]
    known = posts + [f"{H}/tr/tedavi/{w}/" for w in ("a", "b", "c")] + [f"{H}/tr/yazi-{w}/" for w in ("x", "y", "z", "q")]
    pages = [_page(u) for u in posts]
    scope = needed_scope(_result(pages, known), CrawlConfig())
    assert sum(scope["wanted"](u) for u in posts) == 1
    assert scope["record"]["templates"] == 1 and scope["record"]["counts"]["maya_copy_enough"] == 5


# ---------------------------------------------------------------- 3: page typing by content

def _analysis(h1, title=None, types=(), description=None, headings=(), slug_words=()):
    return {"title": title or f"{h1} - Özel Hastane", "h1_elements": [{"text": h1}],
            "headings": [{"level": 1, "text": h1}] + [{"level": 2, "text": h} for h in headings],
            "structured_data": {"types": list(types)}, "og": {"og:description": [description]} if description else {},
            "meta": {}}


SAGLIK = bt.profile("saglik")


def _type(url, analysis, generic="other", sitewide=frozenset()):
    return bt.classify(SAGLIK, bt.page_facts(url, analysis, (), generic, set(sitewide)))[0]


def test_a_psychologists_profile_is_doctors_not_clinic():
    """moodist /tr/team/klinik-psikolog-merve-ceren-safak/: H1 the name, the title in the description and address."""
    a = _analysis("Merve Ceren Şafak", description="Klinik Psikolog Merve Ceren Safak, hastanemizde psikoterapi sunar.",
                  headings=("Hakkında", "Eğitim", "Uzmanlık Alanları"))
    url = H + "/tr/team/klinik-psikolog-merve-ceren-safak/"
    assert bt.person_profile(url, a, set())
    assert _type(url, a) == "doctors"
    # No title anywhere, but CV headings; and a name with Person markup; and "Uzm. Dr." in the H1 itself
    cv = _analysis("İsmail Anıl Usta", headings=("Eğitim", "Uzmanlık Alanları", "Ayrıntılı Özgeçmiş"))
    assert _type(H + "/tr/team/anil-usta/", cv) == "doctors"
    assert bt.person_profile(H + "/kisi/", _analysis("Ayşe Yılmaz", types=("Person",)), {"Person"})
    assert bt.person_profile(H + "/kisi/", _analysis("Uzm. Dr. Merve Gümüşay"), set())


@pytest.mark.parametrize("h1,description,types,headings", [
    ("Ketamin İnfüzyon Tedavisi", "Uzman doktor eşliğinde ketamin infüzyon tedavisi uygulanır.", (), ()),
    ("Our Team", "Meet our doctors and psychologists.", (), ("Education", "Expertise")),
    ("Yetişkin Psikiyatri Merkezi", "Uzman psikiyatrist kadromuzla hizmet veriyoruz.", (), ()),
    ("Uzman Psikologdan Ezber Bozan Hediye Uyarısı", None, ("BlogPosting", "Person"), ()),
    ("Merve Ceren Şafak", "Klinik Psikolog Merve Ceren Safak yazdı.", ("BlogPosting",), ()),  # a post by a psychologist
])
def test_subject_pages_and_articles_are_not_profiles(h1, description, types, headings):
    a = _analysis(h1, description=description, types=types, headings=headings)
    assert not bt.person_profile(H + "/tr/sayfa/", a, set(types))


def test_an_articles_publisher_markup_does_not_type_the_page():
    """moodist: every blog post carries the hospital's Hospital markup; 30 posts were typed "Klinik ve konum"."""
    a = _analysis("Mevsimsel depresyon nedir?", types=("BlogPosting", "Hospital", "MedicalOrganization", "Person", "Place"))
    facts = bt.page_facts(H + "/tr/mevsimsel-depresyon-nedir/", a, (), "other")
    assert facts["schema"] == {"BlogPosting"}
    assert bt.classify(SAGLIK, facts)[0] == "guide"
    clinic = _analysis("Kadıköy Kliniğimiz", types=("MedicalClinic", "Place"))
    assert bt.page_facts(H + "/tr/klinikler/kadikoy/", clinic, (), "other")["schema"] == {"MedicalClinic", "Place"}


def test_location_types_by_profile():
    assert bt.location_types("saglik") == {"clinic"} and bt.location_types("eticaret") == {"stores"}
    assert bt.location_types("restoran") == {"branches"} and bt.location_types("otomotiv") == {"dealers"}
    assert bt.location_types("ev_hizmetleri") == {"service_location"}
    assert bt.location_types("bankacilik") == frozenset() and bt.location_types("diger") == frozenset()


# ---------------------------------------------------------------- 4: IDX-8 place-name groups on location pages only

def _location_finding(section, urls):
    return Finding("IDX-8", f"{len(urls)} pages under /{section}/ differ mostly by the place name in their address",
                   Severity.S3, Confidence.ESTIMATED, "doorway", ["google"], scope_for(urls),
                   {"section": f"/{section}/"}, "distinct", "Give each page its own content.")


def test_the_place_name_rule_fires_only_on_location_pages():
    sss = [f"https://www.enpara.test/sss/{w}" for w in ("kart", "hesap", "kredi", "odeme", "fatura", "vergi")]
    clinics = [f"{H}/klinikler/{w}/" for w in ("kadikoy", "besiktas", "uskudar", "sisli")]
    assert not location_template_kept(sss, {u: "support" for u in sss}, bt.location_types("bankacilik"), 3)
    assert location_template_kept(clinics, {u: "clinic" for u in clinics}, bt.location_types("saglik"), 3)
    assert not location_template_kept(clinics, {u: "guide" for u in clinics}, bt.location_types("saglik"), 3)
    mixed = {**{u: "clinic" for u in clinics[:2]}, **{u: "guide" for u in clinics[2:]}}
    assert location_template_kept(clinics, mixed, bt.location_types("saglik"), 2)
    assert not location_template_kept(clinics, mixed, bt.location_types("saglik"), 3)


def test_the_engine_gate_removes_faq_groups_and_keeps_clinic_groups():
    sss = [f"https://www.enpara.test/sss/{w}" for w in ("kart", "hesap", "kredi", "odeme", "fatura", "vergi")]
    copies = Finding("IDX-8", "3 indexable pages have nearly identical main content (estimate)", Severity.S4,
                     Confidence.ESTIMATED, "hypothesis", ["google"], scope_for(sss[:3]), {}, "distinct", "Consolidate.")
    check = CheckResult("IDX-8", "Duplicates", "findings", "Source: Firecrawl. 2 duplicate group(s) among 40 pages.",
                        [copies, _location_finding("sss", sss)])
    assert check.findings[1].rule_id == LOCATION_RULE
    left = gate_location_templates([check], {u: "support" for u in sss}, "bankacilik", 3)
    assert [r["section"] for r in left] == ["/sss/"] and left[0]["reason"] == "the business type has no location page type"
    assert check.findings == [copies] and check.status == "findings"
    assert check.summary.startswith("Source: Firecrawl. 1 duplicate group(s) among 40 pages.") and "DECISIONS 329" in check.summary
    assert check.evidence["location_templates_left_out"] == left
    clinics = [f"{H}/klinikler/{w}/" for w in ("kadikoy", "besiktas", "uskudar", "sisli")]
    alone = CheckResult("IDX-8", "Duplicates", "findings", "1 duplicate group(s) among 9 pages.", [_location_finding("klinikler", clinics)])
    assert gate_location_templates([alone], {u: "clinic" for u in clinics}, "saglik", 3) == [] and len(alone.findings) == 1
    assert gate_location_templates([alone], {u: "clinic" for u in clinics}, "bankacilik", 3) and alone.status == "pass"
    assert alone.summary.startswith("No duplicate groups among 9 pages.")


def test_a_saved_report_loses_the_faq_group_with_its_order_and_summary(monkeypatch):
    from maya_audit import client_selection, reassess_rules
    from maya_audit.models import to_jsonable
    sss = [f"https://www.enpara.test/sss/{w}" for w in ("kart", "hesap", "kredi", "odeme", "fatura", "vergi")]
    finding = to_jsonable(_location_finding("sss", sss))
    report = {"checks": [{"check_id": "IDX-8", "status": "findings", "summary": "1 duplicate group(s) among 9 pages.",
                          "findings": [finding], "evidence": {}, "coverage": {}}],
              "findings_in_priority_order": [finding["id"]], "crawl": {"config": {}},
              "problem_summary": {"pages_checked": 9}}
    monkeypatch.setattr(client_selection, "grouping", lambda r, business=None: (
        {u: {"business_page_type": "support"} for u in sss}, {"business_type": {"id": "bankacilik"}}))
    new, changes = reassess_rules.saved_data(report, {finding["id"]: sss})
    assert new["checks"][0]["findings"] == [] and new["findings_in_priority_order"] == []
    assert any("left out (DECISIONS 329)" in c for c in changes)
    assert report["checks"][0]["findings"]  # the source is never changed


# ---------------------------------------------------------------- 5: a High card is at least P2

def _ctx(types, profile="bankacilik"):
    importance = {u: {"business_page_type": t, "page_type": "other", "importance": 50} for u, t in types.items()}
    return pl.Context(importance, {"business_type": {"id": profile}}, set(types))


def _group(f, severity):
    return {"members": [f], "finding_ids": [f["id"]], "placement": "card", "severity": severity}


@pytest.mark.parametrize("severity,want", [("S1", "P2"), ("S2", "P2"), ("S3", "P3"), ("S4", "P3")])
def test_a_high_or_blocker_card_is_never_p3(severity, want):
    """enpara: a High broken-link card whose addresses were none of them read scored P3."""
    f = {"id": "IDX-1-1", "rule_id": "idx1.4xx.referenced", "severity": severity, "scope": {"urls": ["https://e.test/x"]}}
    got = pl.label(_group(f, severity), _ctx({"https://e.test/": "home"}), {"IDX-1-1": ["https://e.test/x"]}, {})
    assert got["level"] == want
    if want == "P2":
        assert got["floor"] and got["reason"] == "yüksek önem: en az P2" and got["score"] < 30


def test_the_floor_never_lowers_a_level_and_leaves_order_and_score():
    f = {"id": "S-1", "rule_id": "idx2.expires", "severity": "S2", "scope": {"urls": []}}
    got = pl.label(_group(f, "S2"), _ctx({}), None, {})
    assert got["level"] == "P1" and got["floor"] is None and got["score"] == 133.3
    src = (ROOT / "maya_audit" / "priority_levels.py").read_text(encoding="utf-8")
    assert 'HIGH_FLOOR = {"S1": "P2", "S2": "P2"}' in src


# ---------------------------------------------------------------- 6: the client brief

def test_no_estimated_problem_reaches_the_brief():
    from maya_audit_web.team_report import brief
    from test_client_brief_319 import REPORT, _card, _data
    cards = [_card(1, "str2.no_h1"), _card(2, "str5.names", confidence="estimated"), _card(3, "idx6.alias_links")]
    got = brief.problems(_data(cards), REPORT, "tr")
    assert [p["_rule"] for p in got] == ["str2.no_h1", "idx6.alias_links"]
    assert all(p["evidence"] != "Ölçüldü; kapsamı tahmini" for p in got)
    confirmed = _data([_card(2, "str5.names", confidence="measured")], confirmations={"STR-2-00000002": {"result": "confirmed"}})
    assert brief.problems(confirmed, REPORT, "tr")[0]["evidence"] == "Ölçüldü ve elle teyit edildi"


def _checks(*rows):
    return {"checks": [{"check_id": cid, "status": "pass" if not finds else "findings",
                        "findings": [{"id": f"{cid}-{i}", "rule_id": r} for i, r in enumerate(finds)]} for cid, finds in rows]}


def test_already_good_never_contradicts_a_robots_card():
    from maya_audit_web.team_report import brief
    brief._good.cache_clear() if hasattr(brief._good, "cache_clear") else None
    report = _checks(("ACC-9", []), ("ACC-7", []), ("PRF-2", []), ("ACC-2", ["acc2.blocks.sample"]))
    good = brief._good(report, "tr")
    assert "Sitenizin güvenlik koruması sayfa isteklerimizi geri çevirmedi: incelediğimiz sayfaların hepsi açıldı." in good
    assert not any("engellemiyor" in g or "yapay zekâ" in g for g in good)  # neither "bots are not blocked" nor AI lines
    en = brief._good(report, "en")
    assert en[0] == "Your site's security protection did not turn our page requests away: every page we checked opened."
    clean = brief._good(_checks(("ACC-7", []), ("ACC-2", [])), "tr")
    assert any("beklemelerini istemiyorsunuz" in g for g in clean)


# ---------------------------------------------------------------- 7: broken links with sitemap entries

def test_broken_links_with_sitemap_entries_are_developer_and_content():
    from maya_audit_web.team_report import build_data
    builder_cls = next(v for v in vars(build_data).values() if isinstance(v, type) and hasattr(v, "card_owner"))

    class Fake:
        OWNER_RANK = builder_cls.OWNER_RANK
        L = {"owners": {"developer": "Geliştirici", "seo": "SEO", "content": "İçerik"}}

        def __init__(self, cards):
            self.cards = cards

        def owner_effort(self, f):
            return "content", "S"
    member = {"id": "IDX-1-1", "rule_id": "idx1.4xx.referenced"}
    sitemap_only = Fake({"IDX-1-1": [{"kind": "sitemap"}] * 21})  # enpara 87f0425a: 21 sitemap entries
    assert builder_cls.card_owner(sitemap_only, [member]) == "Geliştirici + İçerik"
    mixed = Fake({"IDX-1-1": [{"kind": "link"}, {"kind": "sitemap"}]})
    assert builder_cls.card_owner(mixed, [member]) == "Geliştirici + İçerik"
    links_only = Fake({"IDX-1-1": [{"kind": "link"}]})
    assert builder_cls.card_owner(links_only, [member]) == "İçerik"
