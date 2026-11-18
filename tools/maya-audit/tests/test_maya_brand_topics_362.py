"""DECISIONS 362: the MMI Ek with Maya data. (1) a competitor of the meta's alias groups whose key or alias is the brand's
is the brand (its former name too), and a topic's leader and gap come from the real rivals' share of its AI answers when
Topic Pulse names only the brand; (2) unrecognised uploads are counted, never named, and not kept; (3) Maya's prompt
categories are not topics, and prompts with no topic label go to the nearest real topic. Fake exports only."""
from __future__ import annotations

import io
import json
import zipfile

from maya_audit import maya_data, maya_sheets

from test_maya_data_352 import csv_text, write

SITE = "https://www.shop.test/"
LABELS = {"l-buy": "Buying intent", "l-wine": "cluster:wine", "l-red": "need_family:red_wine", "l-beer": "cluster:beer"}


def exports(folder):
    meta = {"project": [{"id": "x", "name": "Shop Home Delivery", "domain": "shop.test", "websiteUrl": SITE, "brand_tags": [],
                         "additional_domains": [], "brand_facts": {"competitors": [{"name": "Rival Co", "domain": ""}]}}],
            "competitor_aliases": [
                {"competitor_key": "shp", "alias_key": "oldshophomedelivery", "alias_label": "oldshophomedelivery.ae"},
                {"competitor_key": "shp", "alias_key": "shop", "alias_label": "https://www.shop.test/"},
                {"competitor_key": "rivalco", "alias_key": "rivalcoonline", "alias_label": "Rival Co Online"}],
            "radar_brands": [{"competitor_name": "oldshophomedelivery.com", "competitor_domain": "oldshophomedelivery.com"}],
            "prompt_labels": [{"id": k, "name": v, "color": "#000"} for k, v in LABELS.items()]}
    write(folder, "shop.test-meta (2).json", json.dumps(meta))

    def labels(*ids):
        return json.dumps(list(ids)).replace('"', '""')
    rows = [f'p1,discovery,"best red wine in dubai",en,AE,en,discovery,"{labels("l-wine", "l-red")}",1',
            f'p2,discovery,"cheap red wine delivered tonight",en,AE,en,discovery,"[]",1',  # no label: nearest topic
            f'p3,discovery,"craft lager beer case",en,AE,en,discovery,"{labels("l-beer")}",1',
            f'p4,discovery,"where can tourists buy",en,AE,en,discovery,"{labels("l-buy")}",1',  # a category only
            f'p5,discovery,"доставка алкоголя",en,AE,en,discovery,"[]",1']  # no word in common: no topic
    write(folder, "shop.test-prompts (1).csv", csv_text("id,type,text,locale,targetMarket,targetLanguage,intent,labels,is_active", rows))
    cites = []
    for i, (pid, run, url, domain) in enumerate([
            ("p1", "a", "www.shop.test/wine", "shop.test"), ("p1", "a", "rivalco.test/wine", "rivalco.test"),
            ("p1", "a", "rivalcoonline.test/wine", "rivalcoonline.test"),  # one answer citing two of the rival's sites
            ("p1", "b", "rivalco.test/x", "rivalco.test"), ("p2", "c", "www.shop.test/wine", "shop.test"),
            ("p2", "d", "oldshophomedelivery.com/wine", "oldshophomedelivery.com")]):
        cites.append(f"c{i},chatgpt,{pid},{run},,,true,false,0.75,,2026-11-10 10:00:00,{url},{domain},0.5")
    write(folder, "shop.test-citation-mentions-2026-10-19-2026-11-18.csv",
          csv_text("id,model,prompt_id,run_id,kind,source_type,is_direct,is_indirect,confidence,title,created_at,url,domain,authority_score", cites))
    write(folder, "shop.test-topic-visibility-snapshots-2026-10-19-2026-11-18.csv",
          csv_text("week_start,topic,total,brand_rate,top_competitor_name,top_competitor_rate",
                   ["2026-11-02,wine,100,10.0,oldshophomedelivery.com,94.0"]))
    write(folder, "shop.test-competitor-mentions-daily-2026-10-19-2026-11-18.csv",
          csv_text("date,competitorKey,displayName,domain,mentions,sentimentWeightSum,sentimentWeightedScoreSum",
                   ["2026-11-10 00:00:00,rivalco,Rival Co,,5,1,1", "2026-11-10 00:00:00,oldshop,oldshophomedelivery.com,,9,1,1"]))
    write(folder, "DL26_proposal.tex", "\\documentclass{article}")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("IEEEtran.cls", "%")
    (folder / "DeepLearning.zip").write_bytes(buf.getvalue())
    return maya_data.prepare([folder], SITE)


def test_an_alias_group_naming_the_brand_is_the_brand_and_the_leader_is_a_real_rival(tmp_path):
    s = exports(tmp_path)
    assert {"oldshophomedelivery", "oldshophomedelivery.com", "shp"} <= set(s["own"]["names"])
    assert "oldshophomedelivery.com" in s["own"]["domains"]  # its former site counts as the brand's
    assert not any("oldshop" in c["name"] for c in s["competitors"])
    wine = next(t for t in s["visibility"]["topics"] if t["topic"] == "wine")
    assert wine["leader"] is None and wine["leader_own"] == "oldshophomedelivery.com"
    keys = maya_sheets.competitor_keys(s)
    assert keys["rivalcoonline"] == "Rival Co" and "shp" not in keys
    row = next(t for t in maya_sheets.topic_rows(s) if t["topic"] == "wine")
    # wine: p1 (answers a, b) and p2 (c, d); the brand is cited in a, c and d (its former site), Rival Co in a and b, once each
    assert row["runs"] == 4 and row["rival"] == ("Rival Co", 0.5) and row["gap"] == -25.0
    built = maya_sheets.build(s, {"crawl": {"pages": []}, "checks": []})
    assert any(line.startswith("Lider rakip ve fark: 1 konuda") for line in built["coverage"])
    assert any("«oldshophomedelivery.com»" in line for line in built["coverage"] if line.startswith("Markanın kendisi"))


def test_unrecognised_uploads_are_counted_never_named_and_not_kept(tmp_path):
    s = exports(tmp_path)
    assert s["other_files"] == 2
    built = maya_sheets.build(s, {"crawl": {"pages": []}, "checks": []})
    assert "Maya verisi: 2 tanınmayan dosya kullanılmadı" in built["coverage"]
    assert not any("DL26" in line or "IEEE" in line for line in built["coverage"])
    assert sorted(p.name for p in maya_data.unused_uploads(tmp_path)) == ["DL26_proposal.tex", "DeepLearning.zip"]
    older = {**s, "other_files": ["DL26_proposal.tex"]}  # a summary saved before kept the names
    assert "Maya verisi: 1 tanınmayan dosya kullanılmadı" in maya_sheets.build(older, {"crawl": {"pages": []}, "checks": []})["coverage"]


def test_prompt_categories_are_not_topics_and_unlabelled_prompts_go_to_the_nearest_topic(tmp_path):
    s = exports(tmp_path)
    assert maya_data.topic_of("Buying intent") is None and maya_data.topic_of("Competitor comparison") is None
    topics, counts = maya_sheets.topic_assignment(s)
    assert topics["p1"] == "wine" and topics["p2"] == "wine"  # "red", "wine" from the topic and its need family
    assert topics["p3"] == "beer" and topics["p4"] == maya_data.OFF_TOPIC and topics["p5"] is None
    assert counts == {"labelled": 2, "assigned": 1, "off_topic": 1, "unassigned": 1}
    built = maya_sheets.build(s, {"crawl": {"pages": []}, "checks": []})
    assert any(line.startswith("Konular: 2 prompt Maya'nın konu etiketiyle; 1 prompt") for line in built["coverage"])


def test_one_topic_under_two_keys_is_one_topic():
    s = {"ai": {"prompts": {"a": {"text": "x", "topic": "Kötü Koku Giderici"}, "b": {"text": "y", "topic": "kotu-koku-giderici"}}},
         "visibility": {"topics": []}}
    topics, _ = maya_sheets.topic_assignment(s)
    assert topics == {"a": "Kötü Koku Giderici", "b": "Kötü Koku Giderici"}


def test_the_app_removes_an_unrelated_upload_when_it_reads_the_files(web):  # noqa: F811
    from test_web_app import API, audit_of
    client = web()
    audit = audit_of(client)
    base = f"{API}/audits/{audit['id']}/maya-data"
    session = client.get(f"{API}/session")
    token = session.json().get("token") if session.status_code == 200 else None
    headers = {"Content-Type": "application/octet-stream", **({"X-Maya-Token": token} if token else {})}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("thesis.tex", "x")
    r = client.put(f"{base}/files/papers.zip", content=buf.getvalue(), headers=headers)
    if r.status_code in (401, 403):
        import pytest
        pytest.skip("this test client does not hold the action token")
    body = "date,clicks,impressions,ctr,position\n2026-09-01,10,100,0.1,3\n"
    assert client.put(f"{base}/files/{audit['host']}-gsc-daily-stats.csv", content=body.encode(), headers=headers).status_code == 200
    assert "papers.zip" in client.get(base).json()["files"]
    done = client.post(base, json={}).json()
    assert done["attached"] and "papers.zip" not in done["files"]


from test_web_app import web  # noqa: E402,F401  (fixture)
