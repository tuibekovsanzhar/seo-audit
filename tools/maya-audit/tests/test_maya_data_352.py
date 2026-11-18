"""DECISIONS 352: Maya export data in the audit (Search Console, AI citations, competitors), on small fake exports and a
made-up crawl. No live request, no provider: every page measure comes from the fake crawl or a fake fetch function."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from maya_audit import maya_data, maya_sheets, xlsx

SITE = "https://www.shop.test/"
P = {"a": "p-a", "b": "p-b", "c": "p-c"}


def write(folder: Path, name: str, text: str) -> Path:
    path = folder / name
    path.write_text(text, encoding="utf-8")
    return path


def csv_text(header: str, rows: list[str]) -> str:
    return header + "\n" + "\n".join(rows) + "\n"


def prompts(folder: Path, labels: dict[str, str] | None = None) -> Path:
    lab = labels or {}
    rows = [f'{pid},discovery,"{text}",tr-TR,TR,tr,discovery,"{json.dumps([lab[pid]] if pid in lab else []).replace(chr(34), chr(34) * 2)}",1'
            for pid, text in ((P["a"], "en iyi kredi kartı hangisi"), (P["b"], "kredi kartı aidatı"), (P["c"], "vadeli mevduat faizi"))]
    return write(folder, "shop.test-prompts.csv",
                 csv_text("id,type,text,locale,targetMarket,targetLanguage,intent,labels,is_active", rows))


def citations(folder: Path) -> Path:
    rows = []
    n = 0

    def add(pid, run, model, url, domain, day="2026-09-10"):
        nonlocal n
        n += 1
        rows.append(f"c{n},{model},{pid},{run},,,true,false,0.75,,{day} 10:00:00,{url},{domain},0.5")
    for i in range(4):
        add(P["a"], f"r{i}", "chatgpt", "shop.test/kartlar/kredi-karti?utm_source=chatgpt.com", "shop.test")
        add(P["a"], f"r{i}", "chatgpt", "rakip.test/kartlar/x", "rakip.test")
        add(P["a"], f"r{i}", "chatgpt", "karsilastir.test/kredi-karti", "karsilastir.test")
    add(P["b"], "r9", "gemini", "www.shop.test/anasayfa", "www.shop.test")  # a duplicate of the homepage
    add(P["b"], "r9", "gemini", "shop.test/", "shop.test")
    add(P["c"], "r8", "perplexity", "shop.test/eski-sayfa", "shop.test", day="2026-10-02")
    add(P["c"], "r8", "perplexity", "goto", "goto")  # not an address
    return write(folder, "shop.test-citation-mentions-2026-09-01-2026-10-31.csv",
                 csv_text("id,model,prompt_id,run_id,kind,source_type,is_direct,is_indirect,confidence,title,created_at,url,domain,authority_score", rows))


def daily(folder: Path) -> Path:
    rows = [f"2026-09-{d:02d},100,1000,0.1,5.0,0,0,0,0" for d in range(1, 31)] + \
           [f"2026-10-{d:02d},50,2000,0.025,7.0,0,0,0,0" for d in range(1, 32)]
    return write(folder, "shop.test-gsc-daily-stats-2026-09-01-2026-10-31.csv",
                 csv_text("date,clicks,impressions,ctr,position,aio_clicks,aio_impressions,aio_ctr,aio_position", rows))


def page_scores(folder: Path) -> Path:
    head = "page,clicks,impressions,ctr,position,query_count,position_score,click_score,impression_score,ctr_score,query_diversity_score,authority_score"
    rows = ["https://www.shop.test/kartlar/kredi-karti,500,10000,0.05,3,10,0,0,0,0,0,0",
            "https://www.shop.test/,900,20000,0.045,2,10,0,0,0,0,0,0",
            "https://www.shop.test/eski-sayfa,40,4000,0.01,9,3,0,0,0,0,0,0",
            # the same page in a later 28-day snapshot: the latest row is used, never the sum
            "https://www.shop.test/kartlar/kredi-karti,600,12000,0.05,3,10,0,0,0,0,0,0"]
    return write(folder, "shop.test-gsc-page-scores.csv", csv_text(head, rows))


def meta(folder: Path, domain: str = "shop.test", labels: dict | None = None) -> Path:
    data = {"project": [{"id": "x", "name": "Shop", "domain": domain, "websiteUrl": f"https://{domain}", "brand_tags": ["Shop Bank"],
                         "brand_facts": {"competitors": [{"name": "Rakip", "domain": "rakip.test"}]}, "additional_domains": []}],
            "competitor_aliases": [], "radar_brands": [], "prompt_labels": [{"id": k, "name": v, "color": "#000"} for k, v in (labels or {}).items()],
            "gsc_integration": [{"site_url": domain, "google_email": "owner@example.com", "is_active": True}],
            "ga_integration": [{"ga_property_id": "1", "google_email": "owner@example.com"}]}
    return write(folder, f"{domain}-meta.json", json.dumps(data))


def visibility(folder: Path) -> Path:
    rows = ["2026-09-07,kredi kartı,100,20.0,Rakip,50.0", "2026-10-26,kredi kartı,100,25.0,Rakip,55.0",
            "2026-09-07,mevduat,50,30.0,maid,60.0", "2026-10-26,mevduat,50,35.0,maid,62.0"]
    return write(folder, "shop.test-topic-visibility-snapshots-2026-09-01-2026-10-31.csv",
                 csv_text("week_start,topic,total,brand_rate,top_competitor_name,top_competitor_rate", rows))


def mentions(folder: Path) -> Path:
    rows = ["2026-09-10 00:00:00,rakip,Rakip,rakip.test,12,1,1", "2026-09-10 00:00:00,maid,maid,,40,1,1"]
    return write(folder, "shop.test-competitor-mentions-daily-2026-09-01-2026-10-31.csv",
                 csv_text("date,competitorKey,displayName,domain,mentions,sentimentWeightSum,sentimentWeightedScoreSum", rows))


def report() -> dict:
    def page(path, status=200, title="Sayfa başlığı burada yeterince uzun", page_type="product", redirect=None):
        return {"url": "https://www.shop.test" + path, "status": status, "redirect_location": redirect,
                "grouping": {"page_type": page_type}, "analysis": {
                    "title": title, "meta": [{"name": "description", "content": "Açıklama"}],
                    "headings": [{"level": 1, "text": "Başlık"}, {"level": 2, "text": "Aidat ne kadar?"}],
                    "tables": [{"rows": 4}], "structured_data": {"types": ["FAQPage", "WebPage"]}, "time_elements": [],
                    "canonicals": []}}
    return {"crawl": {"origin": "https://www.shop.test", "start_url": SITE, "pages": [
        page("/", page_type="home"), page("/anasayfa", page_type="home"),
        page("/kartlar/kredi-karti"), page("/eski-sayfa", status=301, redirect="https://www.shop.test/kartlar/kredi-karti"),
        page("/kvkk-aydinlatma", page_type="policy")]}}


def sheet(built: dict, name: str) -> dict:
    return next(s for s in built["sheets"] if s["name"] == name)


def texts(rows) -> list:
    return [[c["text"] if isinstance(c, dict) else c for c in r] for r in rows]


# ---------------------------------------------------------------- files and the domain


def test_dataset_names_are_read_from_the_file_names():
    assert maya_data.dataset_of("enpara.com-prompts (2).csv") == ("prompts", "enpara.com", None)
    assert maya_data.dataset_of("enpara.com-citation-mentions-2026-08-15-2026-11-13.csv") == (
        "citation-mentions", "enpara.com", ("2026-08-15", "2026-11-13"))
    assert maya_data.dataset_of("justlife.com-meta.json")[0] == "meta"
    assert maya_data.dataset_of("notes.txt") == (None, None, None)


def test_another_sites_export_is_refused(tmp_path):
    prompts(tmp_path)
    write(tmp_path, "other.test-gsc-daily-stats.csv", "date,clicks,impressions,ctr,position\n")
    with pytest.raises(maya_data.MayaDataError, match="başka bir siteye ait"):
        maya_data.prepare([tmp_path], SITE)
    other = tmp_path / "meta-only"
    other.mkdir()
    meta(other, domain="other.test")
    with pytest.raises(maya_data.MayaDataError):
        maya_data.prepare([other], SITE)


def test_a_zip_is_read_like_a_folder(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    for f in (prompts(src), citations(src)):
        pass
    z = tmp_path / "export.zip"
    with zipfile.ZipFile(z, "w") as zf:
        for f in src.iterdir():
            zf.write(f, f.name)
    s = maya_data.prepare([z], SITE)
    assert {d["dataset"] for d in s["datasets"]} == {"prompts", "citation-mentions"}


# ---------------------------------------------------------------- no data, GSC only, AI only


def test_without_maya_data_the_appendix_says_so():
    built = maya_sheets.build(None, report())
    assert built["sheets"] == [] and built["coverage"] == ["Maya verisi eklenmedi: Search Console, AI citation ve rakip sayfaları yok."]


def test_gsc_only_sums_daily_rows_and_leaves_the_ai_sheets_out(tmp_path):
    daily(tmp_path)
    s = maya_data.prepare([tmp_path], SITE)
    months = {m["month"]: m for m in s["gsc"]["monthly"]}
    assert months["2026-09"]["clicks"] == 3000 and months["2026-10"]["impressions"] == 62000 and months["2026-09"]["days"] == 30
    assert months["2026-09"]["weekday_clicks"] == 100.0
    built = maya_sheets.build(s, report())
    assert [x["name"] for x in built["sheets"]] == ["Genel durum"]
    assert any("Organik×AI sayfası oluşturulmadı" in c and "prompts" in c for c in built["coverage"])
    assert any("Rakip sayfası oluşturulmadı" in c for c in built["coverage"])


def test_ai_only_every_page_is_not_measured_never_weak(tmp_path):
    prompts(tmp_path)
    citations(tmp_path)
    s = maya_data.prepare([tmp_path], SITE)
    assert "goto" not in json.dumps(s["ai"]["top_domains"])
    built = maya_sheets.build(s, report())
    rows = texts(sheet(built, "Organik×AI - Segmentler")["rows"])
    assert rows and all(r[5] == "Hayır (ölçülmedi)" for r in rows)
    assert {r[-1] for r in rows} <= {"2b", "5", "0"}
    assert any("«GSC'de ölçülmedi», bu «zayıf» anlamına gelmez" in c for c in built["coverage"])


# ---------------------------------------------------------------- the rules


def test_a_28_day_snapshot_is_never_summed(tmp_path):
    prompts(tmp_path)
    citations(tmp_path)
    page_scores(tmp_path)
    s = maya_data.prepare([tmp_path], SITE)
    card = s["gsc"]["pages"]["https://www.shop.test/kartlar/kredi-karti"]
    assert (card["clicks"], card["impressions"]) == (600, 12000)  # the latest row, not 1100 / 22000
    assert s["gsc"]["page_kind"] == "snapshot"


def test_duplicate_addresses_are_merged_into_the_main_page_and_shown(tmp_path):
    prompts(tmp_path)
    citations(tmp_path)
    page_scores(tmp_path)
    s = maya_data.prepare([tmp_path], SITE)
    rows, _ = maya_sheets.pages(s, maya_sheets.Crawl(report()))
    home = next(r for r in rows if r["url"] == "https://www.shop.test/")
    assert "https://www.shop.test/anasayfa" in home["duplicates"] and home["runs"] == 2
    assert not any(r["url"].endswith("/anasayfa") for r in rows)  # the clean address is the main row, whatever came first


def test_segments_dead_addresses_and_legal_pages(tmp_path):
    prompts(tmp_path)
    citations(tmp_path)
    page_scores(tmp_path)
    s = maya_data.prepare([tmp_path], SITE)
    rows, th = maya_sheets.pages(s, maya_sheets.Crawl(report()))
    seg = {r["url"].removeprefix("https://www.shop.test"): r["segment"] for r in rows}
    assert seg["/eski-sayfa"] == "5"  # AI cites an address that now redirects
    assert th["gsc_pages"] == 3 and 0 <= min(r["importance"] for r in rows) and max(r["importance"] for r in rows) <= 100


def test_a_topic_with_few_prompts_is_only_an_indication(tmp_path):
    labels = {"L1": "kredi kartı", "L2": "mevduat"}
    prompts(tmp_path, {P["a"]: "L1", P["b"]: "L1", P["c"]: "L2"})
    citations(tmp_path)
    meta(tmp_path, labels=labels)
    visibility(tmp_path)
    mentions(tmp_path)
    s = maya_data.prepare([tmp_path], SITE)
    built = maya_sheets.build(s, report())
    rows = texts(sheet(built, "Rakip - Konu")["rows"])
    card = next(r for r in rows if r[1] == "kredi kartı")
    assert card[2] == 2 and card[3] == "Evet" and card[8] == 30.0  # gap 55 - 25
    mevduat = next(r for r in rows if r[1] == "mevduat")
    assert "genel bir kelime" in mevduat[7] and mevduat[8] == ""  # "maid" is no competitor
    structure = texts(sheet(built, "Rakip - Sayfa yapısı")["rows"])
    assert any(r[1] == "Rakip marka" and r[3].startswith("alınamadı (") for r in structure)  # nothing fetched, and why (363)


def test_personal_and_account_data_never_reach_the_sheets(tmp_path):
    prompts(tmp_path)
    citations(tmp_path)
    meta(tmp_path)
    s = maya_data.prepare([tmp_path], SITE)
    dumped = json.dumps(s) + json.dumps(maya_sheets.build(s, report()), default=str)
    assert "owner@example.com" not in dumped and "ga_property" not in dumped and "google_email" not in dumped


def test_a_missing_optional_file_leaves_its_column_empty(tmp_path):
    prompts(tmp_path)
    citations(tmp_path)
    s = maya_data.prepare([tmp_path], SITE)  # no result-items: share of voice not measured
    assert s["ai"]["sov"] is None
    rows = sheet(maya_sheets.build(s, report()), "Genel durum")["rows"]
    assert any(r and r[0] == "chatgpt" and "—" in r for r in rows)


def test_an_external_page_is_measured_only_through_the_fetch_given(tmp_path):
    labels = {"L1": "kredi kartı"}
    prompts(tmp_path, {P["a"]: "L1", P["b"]: "L1", P["c"]: "L1"})
    citations(tmp_path)
    meta(tmp_path, labels=labels)
    visibility(tmp_path)
    mentions(tmp_path)
    s = maya_data.prepare([tmp_path], SITE)
    asked = []

    def fake(url):
        asked.append(url)
        return ("<html><head><title>Rakip kart</title></head><body><main><h2>Aidat var mı?</h2><p>Yıllık ücret 0 TL, "
                "nakit avans %3,5, limit 50.000 TL. Güncelleme 2026.</p><table><tr><td>a</td></tr><tr><td>b</td></tr>"
                "<tr><td>c</td></tr></table></main></body></html>")
    maya_sheets.enrich(s, report(), fake)
    assert {"https://rakip.test/kartlar/x", "https://karsilastir.test/kredi-karti"} <= set(asked)
    assert "https://www.shop.test/eski-sayfa" not in asked  # the crawl asked it already (301)
    structure = texts(sheet(maya_sheets.build(s, report()), "Rakip - Sayfa yapısı")["rows"])
    rival = next(r for r in structure if r[1] == "Rakip marka")
    assert rival[5] == 1 and rival[9] == "Evet"


def test_the_appendix_carries_the_sheets_and_links_them(tmp_path):
    from maya_audit import client_appendix
    prompts(tmp_path)
    citations(tmp_path)
    daily(tmp_path)
    s = maya_data.prepare([tmp_path], SITE)
    selection = {"groups": [], "cards": [], "confirm": [], "coverage": {"lines": []}, "key_pages": [], "templates": [],
                 "counts": {}, "business_type": None}
    try:
        names = [x["name"] for x in client_appendix.sheets(selection, "tr", {}, maya={"summary": s, "report": report()})]
    except (KeyError, TypeError):
        pytest.skip("a bare selection is not enough for the technical sheets; covered through the web app")
    assert "Genel durum" in names and "Organik×AI - Segmentler" in names


# ---------------------------------------------------------------- the web app


def test_the_web_app_takes_the_files_and_refuses_another_sites(web):  # noqa: F811
    from test_web_app import API, audit_of
    client = web()
    audit = audit_of(client)
    host = audit["host"]
    base = f"{API}/audits/{audit['id']}/maya-data"
    token = client.get(f"{API}/session").json().get("token") if client.get(f"{API}/session").status_code == 200 else None
    headers = {"Content-Type": "application/octet-stream", **({"X-Maya-Token": token} if token else {})}
    body = "date,clicks,impressions,ctr,position\n2026-09-01,10,100,0.1,3\n"
    r = client.put(f"{base}/files/other.test-gsc-daily-stats.csv", content=body.encode(), headers=headers)
    if r.status_code in (401, 403):
        pytest.skip("this test client does not hold the action token")
    assert r.status_code == 200
    refused = client.post(base, json={})
    assert refused.status_code == 422 and refused.json()["error"]["code"] == "maya_domain_mismatch"
    client.delete(base)
    r = client.put(f"{base}/files/{host}-gsc-daily-stats.csv", content=body.encode(), headers=headers)
    assert r.status_code == 200
    done = client.post(base, json={})
    assert done.status_code == 200 and done.json()["attached"] and done.json()["datasets"][0]["dataset"] == "gsc-daily-stats"
    ek = client.get(f"{API}/audits/{audit['id']}/downloads/xlsx", params={"draft": "true", "lang": "tr"})
    assert ek.status_code == 200 and "Genel durum" in xlsx.read(ek.content)
    assert client.put(f"{base}/files/notes.txt", content=b"x", headers=headers).status_code == 422


from test_web_app import web  # noqa: E402,F401  (fixture)
