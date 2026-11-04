"""DECISIONS 309: team report fixes for every audit. A web confirmation covers its whole group and changes the next
build (the card shows its note); platform steps only on that platform; the platform from saved data when a page
reader's copies hide it; the key pages list (main homepage first, every homepage typed one, no gaps); Note cards only
in free slots and at most two; pages read with no importance are not "not read"; RND-6 on rendered HTML goes to
"Teyit edin"; a low-coverage banner and the client-brief gate; the history list says how each audit read the site;
plurals, capitals, units and IDs that wrap.
"""
from __future__ import annotations

import json
import re
import string
from pathlib import Path

import pytest

from maya_audit import client_selection, reassess_rules
from maya_audit.client_selection import NEUTRAL_IMPORTANCE, _reach, client_brief_allowed, key_pages, low_coverage
from maya_audit.site_platform import recognise_saved
from maya_audit_web.team_report import build_data, current, render, texts
from maya_audit_web.runner import REPORT_JSON
from test_team_report import _pdf_text, built, finished, synthetic, visible_strings  # noqa: F401  (fixture)
from test_web_app import API, web  # noqa: F401  (fixture)

ROOT = Path(__file__).resolve().parents[1]
PLATFORM_WORD = re.compile(r"\b(Shopify|WordPress|WooCommerce|Ticimax|Wix|Webflow|ikas|Magento|Shopware|PrestaShop)\b")
LABELS = build_data.load(build_data.REFS / "etiketler.json")


# ---------------------------------------------------------------- (1) platform steps only on that platform

def test_no_generic_step_names_a_platform():
    """A platform's own step lives under `steps_by_platform`, never in the steps every site gets."""
    catalogue = json.loads((ROOT / "maya_audit" / "rule_actions.json").read_text(encoding="utf-8"))["actions"]
    for rule, entry in catalogue.items():
        for lang, lines in (entry.get("steps") or {}).items():
            assert not [line for line in lines if PLATFORM_WORD.search(line)], (rule, lang)
    for lang in texts.LANGS:
        lib = texts.library(lang)
        for rule, entry in lib["rules"].items():
            assert not [line for line in entry.get("steps") or [] if PLATFORM_WORD.search(line)], (rule, lang)
            assert not [line for line in texts.rule(rule, lang)["steps"] if PLATFORM_WORD.search(line)], (rule, lang)
        for topic, entry in lib["notes"].items():
            assert not PLATFORM_WORD.search(entry.get("step") or ""), (topic, lang)
        assert not [line for line in lib["generic"]["steps"] if PLATFORM_WORD.search(line)]


@pytest.mark.parametrize("lang", texts.LANGS)
def test_a_card_gets_the_shopify_step_only_on_a_shopify_site(tmp_path, lang):
    report = synthetic([("IDX-6", "idx6.alias_links")])
    (tmp_path / "plain").mkdir()
    (tmp_path / "shop").mkdir()
    plain = built(tmp_path / "plain", report, lang)
    wordpress = dict(report, platform={"name": "WordPress", "cdn": None, "signals": ["test"]})
    (tmp_path / "wp").mkdir()
    for data in (plain, built(tmp_path / "wp", wordpress, lang)):
        card = next(t for t in data["todos"] if t.get("rule_id") == "idx6.alias_links")
        assert "within: collection" not in card["steps"] and not PLATFORM_WORD.search(card["steps"])
        assert card["platform_steps"] is None
    shop = built(tmp_path / "shop", dict(report, platform={"name": "Shopify", "cdn": None, "signals": ["test"]}), lang)
    card = next(t for t in shop["todos"] if t.get("rule_id") == "idx6.alias_links")
    assert "within: collection" in card["steps"] and card["platform_steps"] == "Shopify"


# ---------------------------------------------------------------- (2) the platform from saved data

def test_the_platform_is_recognised_from_saved_data():
    sitemap = {"crawl": {"sitemap_docs": [{"url": "https://s.example/sitemap_products_1.xml?from=1&to=9"}]}}
    assert recognise_saved(sitemap)["name"] == "Shopify"
    assert recognise_saved({"crawl": {}}, ['{"og:image": "//s.example/cdn/shop/files/a.jpg"}'])["name"] == "Shopify"
    assert recognise_saved({"crawl": {}}, ["https://cdn.shopify.com/s/files/1/a.js"])["name"] == "Shopify"
    paths = {"crawl": {"sitemap_urls": [f"https://s.example/products/p{n}" for n in range(3)]
                       + [f"https://s.example/collections/c{n}" for n in range(3)]}}
    assert recognise_saved(paths)["name"] == "Shopify"
    # One folder alone, or a hospital on WordPress, names nothing: no guess.
    assert recognise_saved({"crawl": {"sitemap_urls": [f"https://s.example/products/p{n}" for n in range(9)]}}) is None
    hospital = {"crawl": {"sitemap_docs": [{"url": "https://h.example/wp-sitemap.xml"}],
                          "sitemap_urls": ["https://h.example/tr/hakkimizda/", "https://h.example/en/about/"]}}
    assert recognise_saved(hospital, ["<link href='/wp-content/themes/x.css'>"]) is None
    # The CDN the report already names is kept.
    kept = recognise_saved({**sitemap, "platform": {"name": None, "cdn": "Cloudflare", "signals": ["Cloudflare: header"]}})
    assert kept["cdn"] == "Cloudflare" and "Cloudflare: header" in kept["signals"]


def test_a_saved_firecrawl_only_audit_gets_its_platform_in_the_current_engine_copy(tmp_path):
    """A report of the current schema with no platform: the derived copy gets it from the saved data; a report that
    names its platform is used as written; the source is never written."""
    folder = tmp_path / "audit" / "artifacts"
    (folder / "evidence-firecrawl").mkdir(parents=True)
    report = synthetic([("IDX-5", "idx5.stamped")])
    report["crawl"]["sitemap_docs"] = [{"url": "https://shop.example/sitemap_products_1.xml?from=1&to=2"}]
    (folder / "evidence-firecrawl" / "001-home.json").write_text(json.dumps({"url": "https://shop.example/",
                                                                              "meta": "//shop.example/cdn/shop/a.png"}))
    (folder / REPORT_JSON).write_text(json.dumps(report), encoding="utf-8")
    before = (folder / REPORT_JSON).read_bytes()
    cur = current.current(folder / REPORT_JSON)
    assert cur.reassessed and (folder / REPORT_JSON).read_bytes() == before
    made = json.loads(cur.report_path.read_text(encoding="utf-8"))
    assert made["platform"]["name"] == "Shopify" and any("platform: Shopify" in c for c in cur.changes)
    data = build_data.build_from_files(folder / REPORT_JSON, "tr")[0]
    card = next(t for t in data["todos"] if t.get("rule_id") == "idx5.stamped")
    assert card["platform_steps"] == "Shopify"
    other = tmp_path / "named" / "artifacts"
    other.mkdir(parents=True)
    (other / REPORT_JSON).write_text(json.dumps(dict(report, platform={"name": "WordPress", "cdn": None, "signals": []})))
    assert not current.current(other / REPORT_JSON).reassessed


def test_the_offline_reassessment_names_the_platform_and_labels_rendered_html():
    report = synthetic([("RND-6", "rnd6.large")])
    report["crawl"]["sitemap_docs"] = [{"url": "https://shop.example/sitemap_collections_1.xml?from=1&to=2"}]
    report["checks"][0]["findings"][0]["evidence"]["source"] = {"reader": "firecrawl", "why": "test"}
    new, changes = reassess_rules.saved_data(report)
    assert new["platform"]["name"] == "Shopify" and "platform" not in report
    f = new["checks"][0]["findings"][0]
    assert "rendered HTML via Firecrawl, not comparable" in f["title"] and f["evidence"]["html_measured"].startswith("rendered")
    assert len(changes) == 2


# ---------------------------------------------------------------- (3) key pages

def test_the_key_pages_list_has_the_main_homepage_first_every_homepage_and_no_gaps():
    site = "https://h.example"
    importance = {
        f"{site}/ru/": {"importance": 91, "importance_rank": 1, "page_type": "other"},  # a language root, typed wrong
        f"{site}/en/en/": {"importance": 90, "importance_rank": 2, "page_type": "home", "read": False},  # never read
        f"{site}/ar/": {"importance": 85, "importance_rank": 3, "page_type": "home"},
        f"{site}/tr/a/": {"importance": 79, "importance_rank": 4, "page_type": "category"},
        f"{site}/tr/": {"importance": 20, "importance_rank": 50, "page_type": "home",
                        "page_type_basis": "the start address's final page"},
        f"{site}/en/": {"importance": 20, "importance_rank": 51, "page_type": "home"},
    }
    pages = key_pages({"crawl": {"start_url": site + "/"}}, [], importance)
    assert [p["rank"] for p in pages] == list(range(1, len(pages) + 1))
    assert pages[0]["url"] == f"{site}/tr/" and pages[0]["main_homepage"]
    urls = [p["url"] for p in pages]
    assert f"{site}/en/en/" not in urls
    assert {f"{site}/ru/", f"{site}/ar/", f"{site}/en/"} <= set(urls)
    assert all(p["page_type"] == "home" for p in pages if p["url"] != f"{site}/tr/a/")
    assert urls.index(f"{site}/tr/a/") == len(urls) - 1  # the homepages first
    # Without the start address's final page, the start address itself when it was read.
    plain = {f"{site}/": {"importance": 100, "importance_rank": 1}, f"{site}/a": {"importance": 50, "importance_rank": 2}}
    shown = key_pages({"crawl": {"start_url": site + "/"}}, [], plain)
    assert shown[0]["url"] == f"{site}/" and shown[0]["page_type"] == "home"


# ---------------------------------------------------------------- (4) Note cards

def _note_makers():
    return ("schema_card", "hygiene_card", "content_card", "perf_card", "share_card")


@pytest.mark.parametrize("problems", [3, 15])
def test_note_cards_only_fill_free_slots_and_at_most_two(tmp_path, monkeypatch, problems):
    from test_team_report import RULES
    batch = [r for r in RULES if r[1] not in ("idx5.stamped",)][:problems]
    report = synthetic(batch)
    (tmp_path / "a").mkdir()
    sample = built(tmp_path / "a", report, "tr")["todos"][0]
    made = []
    for name in _note_makers():
        def make(self, i, name=name):
            made.append(name)
            return dict(sample, n=i + 1, id=f"NOTE-{name}", severity="Info", finding_ids=[], rule_id=None)
        monkeypatch.setattr(build_data.Builder, name, make)
    (tmp_path / "b").mkdir()
    todos = built(tmp_path / "b", report, "tr")["todos"]
    notes = [t for t in todos if t["severity"] == "Info"]
    real = [t for t in todos if t["severity"] != "Info"]
    assert len(real) == min(problems, build_data.MAX_CARDS)
    assert len(notes) == (0 if problems >= build_data.MAX_CARDS else build_data.NOTES_SHOWN)
    assert todos[:len(real)] == real  # every problem card before any note


# ---------------------------------------------------------------- (5) read, importance unknown

def test_a_page_read_with_no_importance_counts_neutral_and_is_not_not_read():
    read, unread = "https://s.example/read", "https://s.example/never"
    reach, total, counted, not_read, unscored = _reach([read, unread], {}, 100, {read})
    assert (counted, not_read, unscored, total) == (1, 1, 1, NEUTRAL_IMPORTANCE) and reach > 1.0
    # Firecrawl's read pages count as read.
    report = {"crawl": {"pages": [{"url": unread, "status": 429}]},
              "firecrawl": {"pages": [{"url": read, "outcome": "read"}]}}
    assert client_selection.pages_read(report) == {read}
    assert "nötr" in LABELS["tr"]["read_unscored_line"] and "neutral" in LABELS["en"]["read_unscored_line"]


# ---------------------------------------------------------------- (6) RND-6 on rendered HTML

@pytest.mark.parametrize("lang", texts.LANGS)
def test_rnd6_on_the_page_readers_rendered_html_is_confirmed_first(tmp_path, lang):
    report = synthetic([("RND-6", "rnd6.large"), ("STR-2", "str2.no_h1")])
    report["checks"][0]["findings"][0]["evidence"].update(html_measured="rendered (Firecrawl)")
    sel = client_selection.select(report)
    group = sel["by_finding"][report["checks"][0]["findings"][0]["id"]]
    assert group["placement"] == "confirm" and group["confirm_reason"] == "rendered_html"
    data = built(tmp_path, report, lang)
    assert not [t for t in data["todos"] if t.get("rule_id") == "rnd6.large"]
    assert any(c["reason"] == LABELS[lang]["confirm_reasons"]["rendered_html"] for c in data["confirm"])


# ---------------------------------------------------------------- (7) low coverage

def test_low_coverage_and_the_client_brief_gate():
    def report(read, planned):
        return {"audit_status": {"content_coverage": {"pages_read": read}}, "crawl": {"config": {"max_pages": planned}}}
    assert low_coverage(report(1, 500)) == {"pages_read": 1, "planned": 500}
    assert low_coverage(report(9, None)) == {"pages_read": 9, "planned": None}
    assert low_coverage(report(50, 500)) == {"pages_read": 50, "planned": 500}  # under a fifth of the plan
    assert low_coverage(report(50, 50)) is None and low_coverage(report(100, 500)) is None
    assert client_brief_allowed(report(1, 500)) == (False, "low_coverage")
    assert client_brief_allowed(report(50, 50)) == (True, None)


@pytest.mark.parametrize("lang", texts.LANGS)
def test_page_one_shows_the_low_coverage_banner(tmp_path, lang):
    report = synthetic([("STR-2", "str2.no_h1")])
    report["crawl"]["config"] = {"max_pages": 500}
    data = built(tmp_path, report, lang)
    assert data["low_coverage"]["text"].startswith("Düşük kapsam" if lang == "tr" else "Low coverage")
    assert "500" in data["low_coverage"]["text"]
    html = render.build_html(data)
    assert 'data-banner="low_coverage"' in html
    report["crawl"]["config"] = {"max_pages": 12}
    report["audit_status"]["content_coverage"]["pages_read"] = 12  # ten or more, and the whole plan
    (tmp_path / "ok").mkdir()
    assert built(tmp_path / "ok", report, lang)["low_coverage"] is None


def test_the_web_results_say_low_coverage_as_the_report_does(finished):
    from maya_audit.client_selection import low_coverage as engine_low
    client, audit, folder = finished
    view = client.get(f"{API}/audits/{audit['id']}/summary").json()
    report = json.loads((folder / REPORT_JSON).read_text(encoding="utf-8"))
    expected = engine_low(report)
    assert (view["low_coverage"] is None) == (expected is None)
    if expected:
        assert str(expected["pages_read"]) in view["low_coverage"]["text"]


# ---------------------------------------------------------------- (8) the history list

def test_the_history_list_says_mode_pages_read_and_reading_path(finished):
    client, audit, folder = finished
    row = next(a for a in client.get(f"{API}/audits").json()["audits"] if a["id"] == audit["id"])
    assert row["mode_label"] and row["created_at"] and row["path"] == "maya" and row["path_label"] == "Maya"
    assert row["pages_read"] >= 1 and row["read_by_firecrawl"] == 0
    # A page reader's index beside Maya's: both paths, the pages counted once.
    maya = json.loads((folder / "evidence" / "index.json").read_text(encoding="utf-8"))["pages"] \
        if (folder / "evidence" / "index.json").is_file() else []
    seen = [p["url"] for p in maya if 200 <= int(p.get("status") or 0) < 300]
    (folder / "evidence-firecrawl").mkdir(exist_ok=True)
    (folder / "evidence-firecrawl" / "index.json").write_text(json.dumps({"pages": [
        {"url": u, "status": 200} for u in seen[:1] + ["https://elsewhere.example/only-firecrawl"]]}))
    row = next(a for a in client.get(f"{API}/audits").json()["audits"] if a["id"] == audit["id"])
    assert row["path"] == "both" and row["read_by_firecrawl"] == 2
    assert row["pages_read"] == len(set(seen) | {"https://elsewhere.example/only-firecrawl"})


# ---------------------------------------------------------------- (9) words

def test_label_plurals_capitals_and_units():
    assert texts.label("{read:page|pages} read; {unread:URL|URLs}", read="1", unread="15,400") == "1 page read; 15,400 URLs"
    assert texts.lower_first("JavaScript'e bağlı başlıklar", "tr") == "JavaScript'e bağlı başlıklar"
    assert texts.lower_first("Sayfa HTML ağırlığı", "tr") == "sayfa HTML ağırlığı"
    assert texts.lower_first("WordPress eklentisi", "tr") == "WordPress eklentisi"
    # No English label says "1 pages", "1 groups" or "the first 1" once every count in it is 1.
    plural = re.compile(r"\b1 (?:more |known |site-wide |planned |highest-severity |problem |note )?"
                        r"(pages|groups|addresses|URLs|links|items|parts|seconds|issues|findings|areas|cards|requests)\b|first 1\b")
    for key, template in LABELS["en"].items():
        if not isinstance(template, str):
            continue
        names = {f for _, f, _, _ in string.Formatter().parse(re.sub(r"\{(\w+):[^{}]*\|[^{}]*\}", r"{\1}", template)) if f}
        one = f"{key}_one" if f"{key}_one" in LABELS["en"] else key
        shown = texts.label(LABELS["en"][one], **{n: "1" for n in names})
        assert not plural.search(shown), (key, shown)
    assert LABELS["tr"]["scope_units"]["request"][0] == "sayfa isteği"


@pytest.mark.parametrize("lang", texts.LANGS)
def test_blocked_page_requests_are_counted_as_requests_and_unread_addresses_as_addresses(tmp_path, lang):
    report = synthetic([("STR-2", "str2.no_h1"), ("ACC-9", "acc9.blocked_429")])
    acc9 = report["checks"][1]["findings"][0]
    acc9.update(title="Maya's crawler blocked (429 on pages): 1 of 1 page request(s) while robots.txt was served",
                scope={"kind": "sitewide", "count": 1, "urls": [f"{report['crawl']['origin']}/"]}, severity="S3",
                confidence="estimated")
    unread = [f"https://shop.example/never-{n}" for n in range(3)]
    report["checks"][0]["findings"][0]["scope"] = {"kind": "pages", "count": 4, "urls": ["https://shop.example/p0"] + unread}
    data = built(tmp_path, report, lang)
    shown = "\n".join(v for _, v in visible_strings(data))
    assert ("1 sayfa isteği" if lang == "tr" else "1 page request") in shown
    assert "1 dosya" not in shown and "1 file" not in shown
    row = next(f for f in data["findings"] if f["id"].startswith("STR-2"))
    assert row["scope"] == ("4 adres" if lang == "tr" else "4 addresses")


def test_finding_ids_in_a_card_header_wrap_instead_of_being_cut(tmp_path):
    report = synthetic([("STR-2", "str2.no_h1")])
    data = built(tmp_path, report, "tr")
    html = render.build_html(data)
    assert 'class="mono ids"' in html
    rule = re.search(r"\.todo \.tm \{[^}]*\}", render.CSS).group(0)
    assert "nowrap" not in rule and "overflow: hidden" not in rule


# ---------------------------------------------------------------- (0) a web confirmation changes the next build

@pytest.mark.slow
def test_a_confirmation_in_the_web_app_covers_its_group_and_the_next_build_shows_the_card_with_its_note(finished):
    """Confirm first -> POST /review (name, what was seen, card note, Confirmed) -> GET /team-report: the finding is a
    card with the note and no longer under "Teyit edin"; a rejection takes it out of the PDF. Through the real routes,
    the one review file is the audit's artifacts/review.json."""
    pytest.importorskip("playwright")
    pytest.importorskip("pypdf")
    client, audit, folder = finished
    base = f"{API}/audits/{audit['id']}"
    pending = client.get(f"{base}/review").json()["confirm"]
    row = next((r for r in pending if r["severity"] in ("S1", "S2", "S3", "S4")), None)
    if row is None:
        pytest.skip("the demo audit has nothing to confirm")
    note = "Elle bakıldı: kart notu görünmeli"
    posted = client.post(f"{base}/review", json={"finding_id": row["finding_id"], "result": "confirmed", "by": "Owner",
                                                  "seen": "seen in a normal browser", "note": note})
    assert posted.status_code == 200, posted.text
    saved = posted.json()["saved"]
    assert saved["file"] == str(folder / "review.json") and set(row["finding_ids"]) <= set(saved["finding_ids"])
    entries = json.loads((folder / "review.json").read_text(encoding="utf-8"))["entries"]
    assert {e["finding_id"] for e in entries} >= set(row["finding_ids"]) and all(e["note"] == note for e in entries)
    after = client.get(f"{base}/review").json()
    assert row["finding_id"] not in [r["finding_id"] for r in after["confirm"]]
    assert not set(row["finding_ids"]) & {i for r in after["confirm"] for i in r["finding_ids"]}  # nothing left behind
    reviewed = next(r for r in after["reviewed"] if r["finding_id"] == row["finding_id"])
    assert reviewed["manual"]["note"] == note and reviewed["placement"] == "card"
    built_now = client.get(f"{base}/team-report", params={"lang": "tr"})
    assert built_now.status_code == 200, built_now.text
    pdf = _pdf_text(client.get(built_now.json()["pdf"]["url"]).content)
    assert re.sub(r"\s+", "", "Elle kontrol: " + note) in pdf
    # A rejection: out of the PDF's cards and its confirm list, still in the appendix.
    client.post(f"{base}/review", json={"finding_id": row["finding_id"], "result": "rejected", "by": "Owner",
                                        "seen": "not there after all"})
    rebuilt = client.get(f"{base}/team-report", params={"lang": "tr"})
    pdf = _pdf_text(client.get(rebuilt.json()["pdf"]["url"]).content)
    assert re.sub(r"\s+", "", note) not in pdf
    data = build_data.build_from_files(folder / REPORT_JSON, "tr")[0]
    shown = {i for t in data["todos"] for i in t.get("finding_ids") or []} | {i for c in data["confirm"] for i in c["finding_ids"]}
    assert not set(row["finding_ids"]) & shown


def test_the_skills_confirm_covers_the_group_as_the_web_app_does(tmp_path):
    report = synthetic([("STR-2", "str2.no_h1"), ("STR-2", "str2.no_h1")])
    ids = [c["findings"][0]["id"] for c in report["checks"]]
    groups = client_selection.select(report)["by_finding"]
    assert groups[ids[0]]["finding_ids"] == ids  # one cause, one group
    path = tmp_path / REPORT_JSON
    path.write_text(json.dumps(report), encoding="utf-8")
    build_data.record_checks(path, None, [ids[0]], None, by="Owner", seen="seen in a browser", note="kart notu")
    entries = json.loads((tmp_path / "report.review.json").read_text(encoding="utf-8"))["entries"]  # beside the report
    assert sorted(e["finding_id"] for e in entries) == sorted(ids) and {e["note"] for e in entries} == {"kart notu"}
