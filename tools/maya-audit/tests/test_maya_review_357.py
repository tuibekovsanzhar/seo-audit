"""DECISIONS 357: the review of the Maya sheets (Ticimax's Ek): one page type in every sheet, competitor brand pages told
apart from comparison sites, the brand page of each topic, and page shares that never pass 100%. Fake exports only."""
from __future__ import annotations

import json
from pathlib import Path

from maya_audit import maya_data, maya_sheets

from test_maya_data_352 import SITE, csv_text, meta, prompts, report, sheet, texts, write

LABEL = {"p-a": "lab1", "p-b": "lab1", "p-c": "lab1"}


def cites(folder: Path) -> Path:
    """Topic "Kartlar": three answers. The homepage is cited by all three, the card page by two and twice inside
    answer r1; competitor IdeaSoft's own site has no domain in the meta; a third-party list page names several brands."""
    rows, n = [], 0

    def add(pid, run, url, domain):
        nonlocal n
        n += 1
        rows.append(f"c{n},chatgpt,{pid},{run},,,true,false,0.75,,2026-09-10 10:00:00,{url},{domain},0.5")
    for run in ("r1", "r2", "r3"):
        add("p-a", run, "shop.test/", "shop.test")
        add("p-a", run, "ideasoft.com.tr/blog/kart", "ideasoft.com.tr")
        add("p-a", run, "rehber.test/en-iyi-10-kart", "rehber.test")
        add("p-a", run, "haber.test/kart-haberi", "haber.test")
        add("p-a", run, "haber.test/kart-haberi", "haber.test")
    add("p-a", "r1", "shop.test/kartlar/kredi-karti", "shop.test")
    add("p-a", "r1", "shop.test/kartlar/kredi-karti", "shop.test")  # twice in one answer: once
    add("p-a", "r2", "shop.test/kartlar/kredi-karti", "shop.test")
    return write(folder, "shop.test-citation-mentions-2026-09-01-2026-10-31.csv",
                 csv_text("id,model,prompt_id,run_id,kind,source_type,is_direct,is_indirect,confidence,title,created_at,url,domain,authority_score", rows))


def exports(tmp_path: Path, with_mentions: bool = True) -> dict:
    meta(tmp_path, labels={"lab1": "Kartlar"})
    data = json.loads((tmp_path / "shop.test-meta.json").read_text())
    data["project"][0]["brand_facts"]["competitors"] = [{"name": "IdeaSoft", "domain": ""}]  # a name, no domain
    (tmp_path / "shop.test-meta.json").write_text(json.dumps(data))
    prompts(tmp_path, LABEL)
    cites(tmp_path)
    if with_mentions:
        write(tmp_path, "shop.test-competitor-mentions-daily-2026-09-01-2026-10-31.csv",
              csv_text("date,competitorKey,displayName,domain,mentions,sentimentWeightSum,sentimentWeightedScoreSum",
                       ["2026-09-10 00:00:00,ideasoft,IdeaSoft,,30,1,1"]))
        write(tmp_path, "shop.test-topic-visibility-snapshots-2026-09-01-2026-10-31.csv",
              csv_text("week_start,topic,total,brand_rate,top_competitor_name,top_competitor_rate",
                       ["2026-10-26,Kartlar,100,20.0,ideasoft,40.0"]))
    return maya_data.prepare([tmp_path], SITE)


def test_shares_count_a_page_once_per_answer_over_the_topics_answers(tmp_path):
    s = exports(tmp_path)
    assert s["ai"]["prompt_brand_pages"]["p-a"]["https://www.shop.test/kartlar/kredi-karti"] == 2  # r1 once, r2
    t = maya_sheets.topic_rows(s)[0]
    shares = dict(t["brand_pages"])
    assert t["runs"] == 3 and shares["https://www.shop.test/"] == 1.0 and round(shares["https://www.shop.test/kartlar/kredi-karti"], 2) == 0.67
    assert all(v <= 1.0 for v in shares.values())


def test_competitor_brand_sites_are_found_by_name_and_lists_are_comparison_sites(tmp_path):
    s = exports(tmp_path)
    t = maya_sheets.topic_rows(s)[0]
    assert t["competitor_page"][0] == "https://ideasoft.com.tr/blog/kart"
    assert t["comparison_page"][0] == "https://rehber.test/en-iyi-10-kart"  # a third party listing brands
    keys = maya_sheets.competitor_keys(s)
    assert "ideasoft" in keys and "shop" not in keys
    kind = maya_sheets.domain_kind
    assert kind("help.ideasoft.com.tr", s, keys, set(), "https://help.ideasoft.com.tr/x") == "competitor"
    assert kind("haber.test", s, keys, set(), "https://haber.test/kart-haberi") == "other"  # not shown to list brands
    assert kind("haber.test", s, keys, set(), "https://haber.test/x", "IdeaSoft, Ikas ve Shopify karşılaştırması") == "comparison"
    assert kind("images.openai.com", s, keys, set(), "https://images.openai.com/a.png") == "other"
    assert kind("www.shop.test", s, keys, set(), "https://www.shop.test/") == "brand"


def test_a_leader_or_mentions_name_alone_makes_a_competitor(tmp_path):
    s = exports(tmp_path)
    s["competitors"] = []
    assert "ideasoft" in maya_sheets.competitor_keys(s)  # from competitor-mentions and Topic Pulse
    s["mentions"] = {"top": []}
    s["visibility"] = {"topics": [{"topic": "Kartlar", "leader": "maid"}]}  # a generic word is no competitor
    assert maya_sheets.competitor_keys(s) == {}


def test_the_structure_sheet_compares_the_topics_own_brand_page_not_the_homepage(tmp_path):
    s = exports(tmp_path)
    t = maya_sheets.topic_rows(s)[0]
    assert t["brand_page"] == "https://www.shop.test/kartlar/kredi-karti"
    rows = texts(sheet(maya_sheets.build(s, report()), maya_sheets.SHEETS["structure"])["rows"])
    brand = next(r for r in rows if r[1] == "Marka")
    assert brand[2] == "https://www.shop.test/kartlar/kredi-karti"
    assert any(r[1] == "Rakip marka" and r[2].startswith("https://ideasoft.com.tr") for r in rows)
    only_home = {**s, "ai": {**s["ai"], "prompt_brand_pages": {"p-a": {"https://www.shop.test/": 3}}}}
    assert maya_sheets.topic_rows(only_home)[0]["brand_page"] == "https://www.shop.test/"  # nothing else cited


def test_every_maya_sheet_names_a_page_type_as_sayfa_bazinda_does(tmp_path):
    s = exports(tmp_path)
    s["gsc"] = {"pages": {SITE + "kartlar/kredi-karti": {"clicks": 10, "impressions": 100, "ctr": 0.1, "position": 3}}}
    records = {SITE + "kartlar/kredi-karti": {"page_type": "category", "business_page_type": "pricing", "importance": 90}}
    built = maya_sheets.build(s, report(), None, records, "saas")
    rows = texts(sheet(built, maya_sheets.SHEETS["segments"])["rows"])
    head = sheet(built, maya_sheets.SHEETS["segments"])["header"]
    col = next(i for i, h in enumerate(head) if "tür" in h.lower())
    card = next(r for r in rows if r[1] == SITE + "kartlar/kredi-karti")
    assert card[col] == "Fiyatlandırma"  # the profile's type, as "Sayfa bazında" names it
    crawl = maya_sheets.Crawl(report(), None, None, records, "saas")
    assert crawl.type_word("https://www.shop.test/fiyatlandirma") == "Fiyatlandırma (adresten)"  # not read: by address
    assert crawl.kind(SITE + "kartlar/kredi-karti") == "fee"
    without = maya_sheets.Crawl(report(), None, None)
    assert without.type_word(SITE + "kartlar/kredi-karti") == "ürün"  # no selection: the saved crawl's own type


def test_an_older_summary_is_made_again_from_the_files_beside_it(tmp_path):
    folder = tmp_path / "artifacts"
    files = folder / maya_data.FOLDER
    files.mkdir(parents=True)
    s = exports(files)
    maya_data.save({**s, "version": 1}, folder)
    again = maya_data.load_for(folder)
    assert again and again["version"] == maya_data.VERSION
    assert json.loads((folder / maya_data.SUMMARY_FILE).read_text())["version"] == maya_data.VERSION
    lone = tmp_path / "lone"
    lone.mkdir()
    maya_data.save({**s, "version": 1}, lone)
    assert maya_data.load_for(lone) is None  # no files to make it from: not used
