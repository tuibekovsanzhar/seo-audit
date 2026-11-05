"""v0.3 stage 4, business types ("İşletme türü", DECISIONS 311): the profiles from the owner's sector file, page-type
detection per profile, importance 50% profile weight + 35% links + 15% depth, the suggestion, "not found among the pages
read" notes, "Diğer" = Stage 3 exactly, the web app's field, choice, progress line and team report lines, the time
estimate from counted runs only, and hiding an audit. Fake sites and saved fixtures only; nothing is requested."""
from __future__ import annotations

import json
import re
import zipfile
from html import unescape
from pathlib import Path

import httpx
import pytest

from maya_audit import business_types as bt
from maya_audit import client_selection
from maya_audit.audit import run_audit
from maya_audit.config import CrawlConfig
from maya_audit.models import to_jsonable
from maya_audit.report import build_report
from test_deadline_hosted_hardening import QUIET
from test_page_groups import SHOP, _doc, _respond, _shop
from test_web_app import API, CAFE, audit_of, plan, web  # noqa: F401  (fixture)

ROOT = Path(__file__).resolve().parents[1]
SECTOR_FILE = ROOT / "docs" / "business-types" / "Maya-sektor-ve-oncelikli-sayfa-turleri.xlsx"


def _sector_rows() -> list[tuple[str, list[str]]]:
    """(sector, page types in order) from the owner's file, read as XML (no spreadsheet library needed)."""
    xml = zipfile.ZipFile(SECTOR_FILE).read("xl/worksheets/sheet1.xml").decode("utf-8")
    rows = []
    for row in re.findall(r"<x:row [^>]*>(.*?)</x:row>", xml, re.S)[1:]:
        cells = [unescape(v) for v in re.findall(r"<x:v>(.*?)</x:v>", row, re.S)]
        if len(cells) == 2:
            rows.append((cells[0], [re.sub(r"^\d+\.\s*", "", line).strip() for line in cells[1].splitlines() if line.strip()]))
    return rows


# ---------------------------------------------------------------- profiles

def test_one_profile_per_sector_of_the_owners_file_in_its_order_plus_restaurant_and_other():
    rows = _sector_rows()
    assert len(rows) == 12
    by_label = {p["label"]["tr"]: p for p in bt.profiles().values()}
    for sector, types in rows:
        prof = by_label[sector]
        ranked = [t for t in sorted((t for t in prof["page_types"] if t["rank"]), key=lambda t: t["rank"])]
        assert [t["label"]["tr"] for t in ranked] == types, sector
        assert [t["weight"] for t in ranked] == [max(w, bt.HOME_MIN) if t["id"] == "home" else w
                                                for t, w in zip(ranked, bt.RANK_WEIGHTS)], sector
    restaurant = bt.profile("restoran")
    assert [t["label"]["tr"] for t in restaurant["page_types"] if t["rank"]] == [
        "Menü", "Şube ve konum", "Rezervasyon / sipariş", "Ana sayfa", "İletişim"]
    assert set(bt.profiles()) == {"eticaret", "bankacilik", "yatirim", "kart", "saglik", "otomotiv", "saas", "su_aritma",
                                  "guvenlik", "ev_hizmetleri", "gida", "seyahat", "restoran", "diger"}
    assert bt.profile("diger")["page_types"] == []


def test_the_homepage_is_at_least_85_everywhere_and_a_citable_guide_type_exists_in_every_sector():
    for pid, prof in bt.profiles().items():
        if pid == "diger":
            continue
        assert bt.weight(prof, "home") >= 85, pid
        assert any(t.get("citable") for t in prof["page_types"]), pid
        for t in prof["page_types"]:
            if t.get("added") and t["id"] == "guide":
                assert t["weight"] == 30 and t["citable"] and t["label"]["tr"] == "Rehber / SSS / blog", pid
    assert bt.weight(bt.profile("eticaret"), "home") == 85  # rank 3 (70) raised to the floor
    assert bt.weight(bt.profile("bankacilik"), "home") == 100  # rank 1


def test_finance_is_one_group_in_the_choices():
    finance = [c["id"] for c in bt.choices("tr") if c["group"] == "finans"]
    assert finance == ["bankacilik", "yatirim", "kart"]
    assert {c["group_label"] for c in bt.choices("tr") if c["group"]} == {"Finans"}
    assert {c["group_label"] for c in bt.choices("en") if c["group"]} == {"Finance"}


# ---------------------------------------------------------------- page types per profile

def _facts(url, title="", h1="", schema=(), generic=None, menu=(), **analysis):
    a = {"title": title, "h1_elements": [{"text": h1}] if h1 else [], "structured_data": {"types": list(schema)}, **analysis}
    return bt.page_facts(url, a, menu, generic)


def test_address_words_name_the_page_and_item_versus_list_folders_are_told_apart():
    auto = bt.profile("otomotiv")
    assert bt.classify(auto, _facts("https://x.test/fiyat-listesi", "Fiyat Listesi"))[0] == "pricelist"
    assert bt.classify(auto, _facts("https://x.test/modeller/egea-sedan", "Egea Sedan", schema=["Car"]))[0] == "model"
    assert bt.classify(auto, _facts("https://x.test/modeller", "Modeller"))[0] == "models"
    assert bt.classify(auto, _facts("https://x.test/en/dealers", "Dealers"))[0] == "dealers"  # language folder skipped


def test_an_faq_block_on_a_product_page_does_not_make_it_a_help_page():
    bank = bt.profile("bankacilik")
    product = _facts("https://bank.test/hesaplar/vadeli-mevduat", "Vadeli Mevduat", schema=["FAQPage", "Service"],
                     headings=[{"level": 2, "text": "Sıkça sorulan sorular"}] + [{"level": 3, "text": f"Soru {i}?"} for i in range(4)])
    kind, _, signals = bt.classify(bank, product)
    assert kind == "products" and {s["kind"] for s in signals} >= {"url"}
    assert bt.classify(bank, _facts("https://bank.test/destek", "Destek"))[0] == "support"


def test_home_utility_and_policy_come_first_and_a_profile_may_count_policies_as_its_help_type():
    shop, bank = bt.profile("eticaret"), bt.profile("bankacilik")
    assert bt.classify(shop, _facts("https://s.test/", generic="home"))[0] == "home"
    assert bt.classify(shop, _facts("https://s.test/sepet", generic="utility"))[0] == "utility"
    assert bt.classify(shop, _facts("https://s.test/iade-politikasi", generic="policy"))[0] == "help"
    assert bt.classify(bank, _facts("https://bank.test/kvkk-basvuru", generic="policy"))[0] == "policy"
    # No signal: the general page type maps to the profile's type, else "other".
    assert bt.classify(shop, _facts("https://s.test/x/y", generic="product"))[0] == "product"
    assert bt.classify(bank, _facts("https://bank.test/kariyer", generic="other"))[0] == "other"


# ---------------------------------------------------------------- importance

def _record(link, depth_score, page_type="other", capped=False, rank=1, importance=None):
    parts = {"internal_link_score": link, "click_depth": depth_score, "page_type": 50, "capped": capped}
    return {"page_type": page_type, "importance": importance if importance is not None else 50, "importance_rank": rank,
            "importance_parts": parts, "tie_break": {"body_inlinks": 0, "products_listed": 0, "sitemap_position": None}}


def test_importance_is_half_the_profile_weight_35_percent_links_15_percent_depth_with_stage_3s_caps():
    records = {"https://s.test/collections/a": _record(40, 70, "category", rank=2, importance=61),
               "https://s.test/products/b": _record(80, 55, "product", rank=1, importance=67),
               "https://s.test/hidden": _record(100, 100, "category", capped="not indexable", rank=3, importance=20)}
    facts = {u: bt.page_facts(u, {}, (), g["page_type"]) for u, g in records.items()}
    summary = bt.apply(records, facts, "eticaret")
    cat, prod, hidden = records.values()
    assert cat["importance"] == round(0.5 * 100 + 0.35 * 40 + 0.15 * 70)  # 74.5 -> 74, as Stage 3 rounds
    assert prod["importance"] == round(0.5 * 85 + 0.35 * 80 + 0.15 * 55) == 79
    assert hidden["importance"] == 20 and hidden["importance_links"] == 20  # the cap stays
    assert cat["importance_links"] == 61 and cat["importance_rank_links"] == 2 and cat["importance_source"] == "profile:eticaret"
    assert [u for u, g in sorted(records.items(), key=lambda kv: kv[1]["importance_rank"])][:2] == [
        "https://s.test/products/b", "https://s.test/collections/a"]
    assert summary["formula"] == {"page_type": 0.5, "internal_link_score": 0.35, "click_depth": 0.15}
    # Back to "Diğer": Stage 3's own values, exactly.
    bt.apply(records, facts, "diger")
    assert cat["importance"] == 61 and cat["importance_rank"] == 2 and "business_page_type" not in cat
    assert cat["importance_source"] == "links" and "profile_weight" not in cat["importance_parts"]


def _shop_audit(business):
    config = CrawlConfig(**{**QUIET, "max_pages": 40, "sitemap_check_max": 5, "business_type": business})
    return run_audit(SHOP + "/", config, httpx.MockTransport(_respond(_shop())))


def _report(outcome):
    return json.loads(json.dumps(to_jsonable(build_report(outcome.result, outcome.gates, outcome.checks))))


def test_other_gives_today_s_results_exactly():
    """"Diğer" = Stage 3: the same importance and rank on every page, the same cards, priorities and key pages as the
    selection without any business layer."""
    outcome = _shop_audit("diger")
    report = _report(outcome)
    assert report["crawl"]["business_type"]["id"] == "diger" and report["crawl"]["business_type"]["chosen_by"] == "user"
    from maya_audit.page_groups import annotate
    from types import SimpleNamespace
    view = SimpleNamespace(pages=[p for p in outcome.result.pages], start_url=outcome.result.start_url,
                           origin=outcome.result.origin, discovered_urls=outcome.result.discovered_urls,
                           sitemap_urls=outcome.result.sitemap_urls, page_grouping=None)
    saved = {p.url: dict(p.grouping) for p in outcome.result.pages}
    annotate(view)  # Stage 3 alone, on the same pages
    for p in outcome.result.pages:
        if "importance" in (p.grouping or {}):
            assert saved[p.url]["importance"] == p.grouping["importance"]
            assert saved[p.url]["importance_rank"] == p.grouping["importance_rank"]
    with_layer = client_selection.select(report, business="diger")
    stage3 = client_selection._stage3_grouping
    original = client_selection.grouping
    client_selection.grouping = lambda r, business=None: stage3(r)
    try:
        without = client_selection.select(report)
    finally:
        client_selection.grouping = original
    assert [(c["finding_ids"], c["priority"], c["reach"]) for c in with_layer["cards"]] == [
        (c["finding_ids"], c["priority"], c["reach"]) for c in without["cards"]]
    assert [(k["url"], k["importance"]) for k in with_layer["key_pages"]] == [(k["url"], k["importance"]) for k in without["key_pages"]]
    assert with_layer["key_pages_not_found"] == []


def test_a_profile_changes_importance_and_key_pages_never_a_finding_or_a_severity():
    plain, shop = _report(_shop_audit("diger")), _report(_shop_audit("eticaret"))
    findings = lambda r: sorted((f["id"], f["severity"], f["confidence"]) for c in r["checks"] for f in c["findings"])  # noqa: E731
    assert findings(plain) == findings(shop)
    assert plain["release_gate"]["decision"] == shop["release_gate"]["decision"]
    pages = {p["url"]: p["grouping"] for p in shop["crawl"]["pages"] if "importance" in (p.get("grouping") or {})}
    assert all(g["importance_source"] == "profile:eticaret" for g in pages.values())
    assert pages[SHOP + "/collections/elbise"]["business_page_type"] == "category"
    assert pages[SHOP + "/products/mavi-elbise"]["business_page_type"] == "product"
    assert pages[SHOP + "/blogs/news/sezon-rehberi"]["business_page_type"] == "guide"
    assert pages[SHOP + "/blogs/news/sezon-rehberi"]["business_citable"] is True


# ---------------------------------------------------------------- suggestion

def test_the_suggestion_reads_the_homepages_markup_the_platform_the_addresses_and_the_menu():
    cafe = bt.suggest({"structured_data": {"types": ["Restaurant", "WebSite"]}},
                      [{"target": "https://k.test/menu", "nav": True, "anchors": ["Menü"]},
                       {"target": "https://k.test/subeler", "nav": True, "anchors": ["Şubelerimiz"]}], None,
                      ["https://k.test/menu", "https://k.test/subeler", "https://k.test/subeler/kadikoy"])
    assert cafe["id"] == "restoran"
    assert "Restaurant" in cafe["reason"]["tr"] and "menüde" in cafe["reason"]["tr"]
    assert "structured data on the homepage" in cafe["reason"]["en"]
    shop = bt.suggest({}, [], "Shopify", [f"https://s.test/products/p{i}" for i in range(20)])
    assert shop["id"] == "eticaret" and "Shopify" in shop["reason"]["tr"]
    nothing = bt.suggest({}, [], None, ["https://x.test/hakkimizda"])
    assert nothing["id"] == "diger" and nothing["reason"]["tr"].startswith("Net bir işaret yok")


def test_an_audit_on_auto_uses_the_suggestion_and_a_chosen_type_wins():
    auto = _report(_shop_audit("auto"))["crawl"]["business_type"]
    assert auto["id"] == "eticaret" and auto["chosen_by"] == "suggestion" and auto["suggestion"]["id"] == "eticaret"
    chosen = _report(_shop_audit("saglik"))["crawl"]["business_type"]
    assert chosen["id"] == "saglik" and chosen["chosen_by"] == "user" and chosen["suggestion"]["id"] == "eticaret"


def test_the_command_line_takes_a_business_type_and_refuses_an_unknown_one():
    from maya_audit import cli
    args = cli._parser().parse_args(["crawl", "https://x.test/", "--business-type", "otomotiv"])
    assert cli._crawl_config(args).business_type == "otomotiv"
    with pytest.raises(SystemExit):
        cli._crawl_config(cli._parser().parse_args(["crawl", "https://x.test/", "--business-type", "uzay"]))


def test_the_homepage_s_suggestion_is_sent_to_the_progress_listener_as_soon_as_it_is_read():
    from maya_audit.progress import Hooks
    events = []
    config = CrawlConfig(**{**QUIET, "max_pages": 5, "sitemap_check_max": 5})
    run_audit(SHOP + "/", config, httpx.MockTransport(_respond(_shop())), Hooks(on_progress=events.append))
    early = [e for e in events if e.get("business_suggestion")]
    assert len(early) == 1 and early[0]["business_suggestion"]["id"] == "eticaret"
    crawl = [e for e in events if e.get("phase") == "crawl" and e.get("pages_fetched")]
    assert events.index(early[0]) < len(events) - 1 and crawl  # during the crawl, not after it


# ---------------------------------------------------------------- not found among the pages read

def test_the_profiles_top_three_types_not_found_among_the_pages_read_are_noted_and_never_on_low_coverage():
    records = {"https://a.test/": {"business_page_type": "home"}, "https://a.test/modeller/x": {"business_page_type": "model"}}
    missing = bt.not_found(records, "otomotiv")
    assert [m["label"]["tr"] for m in missing] == ["Fiyat listesi", "Model listesi"]
    assert bt.not_found(records, "diger") == []
    report = _report(_shop_audit("otomotiv"))
    sel = client_selection.select(report)
    # The shop's products and collections map to "Model detayı" and "Model listesi" (their general types); only the
    # price list is not found among the pages read.
    assert [n["type"] for n in sel["key_pages_not_found"]] == ["pricelist"]
    tiny = json.loads(json.dumps(report))
    tiny["crawl"]["config"]["max_pages"] = 500  # 17 pages read of 500 planned: low coverage
    assert client_selection.low_coverage(tiny) and client_selection.select(tiny)["key_pages_not_found"] == []


def test_a_saved_report_without_a_business_type_gets_the_suggestion_and_the_persons_choice_wins():
    report = _report(_shop_audit("diger"))
    report["crawl"].pop("business_type")  # as saved before schema 1.25
    for p in report["crawl"]["pages"]:
        if isinstance(p.get("grouping"), dict):
            bt.reset(p["grouping"])
    sel = client_selection.select(report)
    assert sel["business_type"]["id"] == "eticaret" and sel["business_type"]["chosen_by"] == "suggestion"
    chosen = client_selection.select(report, business="saglik")
    assert chosen["business_type"]["id"] == "saglik" and chosen["business_type"]["chosen_by"] == "user"
    assert all("business_page_type" not in (p.get("grouping") or {}) for p in report["crawl"]["pages"])  # not written


# ---------------------------------------------------------------- web app

def test_the_plan_takes_a_business_type_and_says_when_the_suggestion_will_come(web):  # noqa: F811
    client = web()
    made = plan(client, CAFE)
    assert made["business_type"]["chosen"] == "auto" and made["business_type"]["suggested"] is None
    assert made["business_type"]["line"] == "Suggested once the homepage has been read"
    assert {c["id"] for c in made["business_type"]["choices"]} == set(bt.profiles())
    chosen = plan(client, CAFE, business_type="restoran")
    assert chosen["business_type"]["chosen"] == "restoran" and chosen["business_type"]["chosen_label"] == "Restaurant / café"
    refused = client.post(f"{API}/plans", json={"url": CAFE, "business_type": "uzay"})
    assert refused.status_code == 422 and refused.json()["error"]["code"] == "invalid_business_type"
    assert {c["id"] for c in client.get(f"{API}/settings").json()["business_types"]} == set(bt.profiles())


def test_an_audit_records_its_type_the_next_plan_suggests_it_and_a_choice_changes_the_summary(web):  # noqa: F811
    client = web()
    audit = audit_of(client, CAFE, business_type="saglik")
    assert audit["state"] == "finished"
    assert audit["business"]["chosen"] == "saglik" and audit["business"]["final"]["id"] == "saglik"
    assert audit["business"]["suggested_line"].startswith("Suggested business type: ")  # the homepage's, while it ran
    folder = client.app.state.runner.artifacts(audit["id"])
    report = json.loads((folder / "report.json").read_text(encoding="utf-8"))
    assert report["crawl"]["business_type"]["chosen_by"] == "user" and report["crawl"]["config"]["business_type"] == "saglik"
    again = plan(client, CAFE)
    suggested = report["crawl"]["business_type"]["suggestion"]["id"]
    assert again["business_type"]["suggested"]["id"] == suggested and again["business_type"]["line"].startswith("Suggested from")
    over = client.get(f"{API}/audits/{audit['id']}/overview", params={"lang": "en"}).json()
    assert over["business"]["id"] == "saglik" and over["business"]["chosen_by"] == "user"
    before = (folder / "report.json").read_bytes()
    saved = client.post(f"{API}/audits/{audit['id']}/business-type", json={"id": "otomotiv"})
    assert saved.status_code == 200 and json.loads((folder / "business-type.json").read_text())["id"] == "otomotiv"
    over = client.get(f"{API}/audits/{audit['id']}/overview", params={"lang": "tr"}).json()
    assert over["business"]["id"] == "otomotiv" and over["business"]["line"].startswith("İşletme türü: Otomotiv (seçildi)")
    assert over["business"]["not_found"].startswith("Okunan sayfalar arasında bulunamadı")
    client.post(f"{API}/audits/{audit['id']}/business-type", json={"id": "auto"})
    assert not (folder / "business-type.json").exists()
    assert (folder / "report.json").read_bytes() == before  # never written
    bad = client.post(f"{API}/audits/{audit['id']}/business-type", json={"id": "uzay"})
    assert bad.status_code == 422


def test_the_team_report_names_the_type_uses_its_page_types_and_lists_what_was_not_found(web):  # noqa: F811
    from maya_audit_web.team_report import build_data, render
    client = web()
    audit = audit_of(client, CAFE)
    folder = client.app.state.runner.artifacts(audit["id"])
    (folder / "business-type.json").write_text(json.dumps({"id": "otomotiv"}), encoding="utf-8")
    data, _ = build_data.build_from_files(folder / "report.json", "tr", review=folder / "review.json")
    assert data["business_line"] == "İşletme türü: Otomotiv (seçildi)"
    assert data["key_pages_not_found"] and all("okunan sayfalar arasında bulunamadı" in x for x in data["key_pages_not_found"])
    assert data["key_pages"][0]["type"] == "Ana sayfa"
    html = render.page6(data, render.LABELS["tr"])
    assert "İşletme türü: Otomotiv (seçildi)" in html and "sitede olmadığı anlamına gelmez" in html
    (folder / "business-type.json").unlink()
    data, _ = build_data.build_from_files(folder / "report.json", "en", review=folder / "review.json")
    assert data["business_line"].startswith("Business type: ") and "suggested; why: " in data["business_line"]


def _row(store, mode="quick", minutes=8, speed=None, stop="page_cap", pages=50, sessions=1, state="finished"):
    from datetime import datetime, timedelta, timezone
    from maya_audit.timeplan import SPEED_VERSION
    from maya_audit_web.store import new_id
    plan_row = store.create_plan(project_id="t.test", url="https://t.test/", mode=mode, key_pages=[], backlinks=False,
                                 fingerprint="f", total_usd=0.0, document={"id": new_id()}, lifetime_s=600)
    audit, _ = store.create_audit(plan_row, 0.0, {}, None, "en", {"speed_version": SPEED_VERSION if speed is None else speed})
    start = datetime(2026, 11, 5, 10, tzinfo=timezone.utc)
    store.update_audit(audit["id"], state=state, crawl_stop=stop, sessions=sessions, started_at=start.isoformat(),
                       finished_at=(start + timedelta(minutes=minutes)).isoformat(), progress={"pages_checked": pages})
    return audit["id"]


def test_time_estimates_count_only_finished_ordinary_runs_of_the_current_engine(web):  # noqa: F811
    client = web()
    store = client.app.state.runner.store
    typical = lambda: {m["id"]: m["typical"] for m in client.get(f"{API}/settings").json()["modes"]}  # noqa: E731
    for minutes in (6, 7):
        _row(store, minutes=minutes)
    # None of these count: an older engine, stopped early, rate-limited, robots-blocked, too few pages, two sessions.
    _row(store, minutes=30, speed=0)
    _row(store, minutes=30, stop="stopped")
    _row(store, minutes=30, stop="rate_limit")
    _row(store, minutes=30, stop="robots_disallowed")
    _row(store, minutes=30, pages=4)
    _row(store, minutes=30, sessions=2)
    quick = typical()["quick"]
    assert quick["basis"] == "default" and quick["minutes"] == 10 and quick["runs"] == 2
    _row(store, minutes=9, stop="exhausted")
    quick = typical()["quick"]
    assert quick["basis"] == "recent_runs" and quick["minutes"] == 7 and quick["runs"] == 3
    assert typical()["standard"]["minutes"] == 25 and typical()["single"]["minutes"] == 1


def test_an_audit_can_be_hidden_from_the_history_and_shown_again(web):  # noqa: F811
    client = web()
    audit = audit_of(client, CAFE)
    listed = client.get(f"{API}/audits").json()
    assert audit["id"] in [a["id"] for a in listed["audits"]] and listed["hidden_total"] == 0
    assert client.put(f"{API}/audits/{audit['id']}/hidden", json={"hidden": True}).status_code == 200
    listed = client.get(f"{API}/audits").json()
    assert audit["id"] not in [a["id"] for a in listed["audits"]] and listed["hidden_total"] == 1
    hidden = client.get(f"{API}/audits", params={"hidden": "true"}).json()
    assert [a["id"] for a in hidden["audits"]] == [audit["id"]] and hidden["audits"][0]["hidden"] is True
    assert client.get(f"{API}/audits/{audit['id']}").status_code == 200  # its files and page stay
    client.put(f"{API}/audits/{audit['id']}/hidden", json={"hidden": False})
    assert audit["id"] in [a["id"] for a in client.get(f"{API}/audits").json()["audits"]]


def test_the_page_offers_the_business_type_on_the_form_the_plan_the_progress_box_and_the_results():
    js = (ROOT / "maya_audit_web" / "static" / "app.js").read_text(encoding="utf-8")
    for needle in ('businessSelect("new-business"', "business_type: state.draft.business_type", "businessRow(current, live",
                   "business.suggested_line", "businessBox(view, data.business", '"/business-type"', '"/hidden"',
                   'T("new.business.auto")'):
        assert needle in js, needle
    from maya_audit_web import strings
    tr = strings.table("tr")
    assert tr["new.business"] == "İşletme türü" and tr["new.business.auto"] == "Otomatik öner"
    assert tr["job.business.suggested"].startswith("Önerilen işletme türü: ") and tr["nav.hide"] == "Gizle"


def test_markup_on_most_pages_is_a_site_default_and_qr_menu_is_not_a_language_folder():
    from maya_audit.page_groups import is_locale
    assert not is_locale("qr-menu") and is_locale("en-us") and is_locale("zh-hans") and is_locale("es-419") and is_locale("tr")
    article = {"structured_data": {"types": ["Article", "WebPage"]}}
    assert bt.sitewide_schema([article] * 9 + [{}]) == {"Article", "WebPage"}
    assert bt.sitewide_schema([article] * 3) == set()  # too few pages to call anything sitewide
    cafe = bt.profile("restoran")
    story = bt.page_facts("https://k.test/hikayemiz/", article, (), "other", {"Article", "WebPage"})
    assert bt.classify(cafe, story)[0] == "other"  # adile: Article on 35 of 36 pages said nothing about this one
    assert bt.classify(cafe, bt.page_facts("https://k.test/qr-menu/", article, (), "other", {"Article"}))[0] == "menu"
