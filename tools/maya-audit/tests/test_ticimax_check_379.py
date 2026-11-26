"""DECISIONS 379: the owner's check of the Ticimax Ek (2026-11-26), as global rules. Ticimax is only the test case.

(1) A file whose folder name holds the space or the combining mark (`/Kampanya Gorsel/offer.svg`) was reported as
    «dosya adı «offer.svg» (boşluk); önerilen ad: offer.svg»: the suggested name was the name itself. The row now names
    the folder and suggests a plain folder name; a saved report's rows are rewritten the same way.
(2) Images of 100-500 KB (str7.over_100kb, "Büyük görselleri hafifletin", Fırsat) and over 500 KB (str7.heavy, "Ağır
    görselleri küçültüp sıkıştırın", Sorun) were two cards on the same homepage banners: one cause, one fix, now one card.
Synthetic data only, offline.
"""
from __future__ import annotations

import copy

from maya_audit import client_selection as cs
from maya_audit import file_names as fn
from maya_audit import reassess_rules
from maya_audit.checks.quick_rules import unsafe_file_names
from test_v03_client_report import SITE, finding, report

HOME = "https://s.test/"


# ---------------------------------------------------------------- (1) a folder name

def test_the_problem_is_placed_in_the_file_name_or_in_a_folder():
    assert fn.folder_problem("https://s.test/Uploads/Kampanya Gorsel/offer.svg") == ("Kampanya Gorsel", ["space"])
    assert fn.folder_problem("https://s.test/img/Kampanya Gorsel.png") is None           # the name itself
    assert fn.folder_problem("https://s.test/Ürünler/Kategori/ok.png") is None            # nothing wrong
    assert fn.folder_problem("https://s.test/Espolòn/ok.png") == ("Espolòn", ["combining"])
    assert fn.plain_name("Kampanya Gorsel", extension=False) == "kampanya-gorsel"
    assert fn.plain_name("v1.2 assets", extension=False) == "v1-2-assets"


def test_a_folder_with_a_space_is_named_and_never_a_suggestion_equal_to_the_name():
    found = unsafe_file_names([(HOME, {"images": [{"src": "/Uploads/Kampanya Gorsel/offer.svg"},
                                                  {"src": "/img/Yaz Kampanyasi.png"}]})])
    f = found[0]
    files = {r["file"]: r for r in f.evidence["files"]}
    assert files["offer.svg"]["folder"] == "Kampanya Gorsel" and files["Yaz Kampanyasi.png"]["folder"] is None
    row = {r["url"]: r["row"] for r in f.evidence["pages"]}[HOME]
    assert "«offer.svg» dosyasının klasör adı «Kampanya Gorsel» (boşluk); önerilen klasör adı: kampanya-gorsel" in row["tr"]
    assert "folder name «Kampanya Gorsel» of «offer.svg» (space); suggested folder name: kampanya-gorsel" in row["en"]
    assert "dosya adı «Yaz Kampanyasi.png» (boşluk); önerilen ad: yaz-kampanyasi.png" in row["tr"]
    assert "önerilen ad: offer.svg" not in row["tr"]


def _saved(rows_tr: str, rows_en: str, address: str) -> dict:
    f = {"id": "TSEO-1-files", "check_id": "TSEO-1", "rule_id": "tseo1.file_name_unsafe", "severity": "S4",
         "title": "1 image or file name(s) hold spaces, accents written as combining marks, brackets or commas",
         "evidence": {"files": [{"file": "offer.svg", "address": address, "problems": ["space"], "characters": [],
                                 "plain_name": "offer.svg", "where": ["img src"], "pages": [HOME]}],
                      "pages": [{"url": HOME, "files": 1, "row": {"tr": rows_tr, "en": rows_en}}]}}
    return {"checks": [{"check_id": "TSEO-1", "status": "fail", "findings": [f]}]}


def test_a_saved_reports_rows_are_rewritten_with_the_folder():
    r = _saved("dosya adı «offer.svg» (boşluk); önerilen ad: offer.svg",
               "file name «offer.svg» (space); suggested name: offer.svg",
               "https://s.test/Uploads/Kampanya Gorsel/offer.svg")
    changes: list[str] = []
    reassess_rules._decisions_379(r, {}, changes)
    f = r["checks"][0]["findings"][0]
    assert f["evidence"]["pages"][0]["row"]["tr"] == ("«offer.svg» dosyasının klasör adı «Kampanya Gorsel» (boşluk); "
                                                      "önerilen klasör adı: kampanya-gorsel")
    assert f["evidence"]["files"][0]["folder"] == "Kampanya Gorsel" and changes
    again = copy.deepcopy(r)
    reassess_rules._decisions_379(again, {}, [])
    assert again == r                                                                  # applied once


def test_a_saved_file_whose_name_holds_the_problem_is_left_as_it_is():
    r = _saved("dosya adı «Yaz Kampanyasi.png» (boşluk); önerilen ad: yaz-kampanyasi.png",
               "file name «Yaz Kampanyasi.png» (space); suggested name: yaz-kampanyasi.png",
               "https://s.test/img/Yaz Kampanyasi.png")
    before = copy.deepcopy(r["checks"][0]["findings"][0]["evidence"]["pages"])
    changes: list[str] = []
    reassess_rules._decisions_379(r, {}, changes)
    assert r["checks"][0]["findings"][0]["evidence"]["pages"] == before and not changes


# ---------------------------------------------------------------- (2) one card for image weight

def test_large_and_heavy_images_are_one_card():
    sel = cs.select(report([finding("A", "str7.over_100kb", "S4", urls=[SITE + "/"], check="STR-7"),
                            finding("B", "str7.heavy", "S4", urls=[SITE + "/"], check="STR-7"),
                            finding("C", "str7.video", "S4", urls=[SITE + "/"], check="STR-7")]))
    by = {fid: g for g in sel["groups"] for fid in g["finding_ids"]}
    assert by["A"] is by["B"] and by["A"]["merge_group"] == "image_weight" and by["A"]["placement"] == "card"
    assert by["A"]["issue_type"] == "issue"                      # the heavier rule is a Sorun, the lighter a Fırsat
    assert by["C"] is not by["A"]                                # a video is its own fix
    group = cs.MERGE_BY_ID["image_weight"]
    assert group["title"]["tr"] == "Görselleri küçültüp sıkıştırın" and group["title"]["en"]


# ---------------------------------------------------------------- (1b) a mistyped address

def test_a_space_inside_https_is_a_mistyped_address_not_a_file_name():
    """Ticimax's CSS wrote «https: //www.ticimax.com/img/icons/white/duotone/offer.svg»: a browser reads that as a path
    under the page, so the icon is not loaded. The row says the address is mistyped and gives it as meant."""
    assert fn.mistyped_scheme("https: //s.test/img/offer.svg") == "https://s.test/img/offer.svg"
    assert fn.mistyped_scheme("https:/ /s.test/a.png") == "https://s.test/a.png"
    assert fn.mistyped_scheme("https://s.test/a b.png") is None and fn.mistyped_scheme("/img/a.png") is None
    page = "https://s.test/e-ticaret-paketleri/"
    found = unsafe_file_names([(page, {"file_names": [{"url": "https: //s.test/img/icons/offer.svg",
                                                         "where": ["css background"]}]})])
    rec = found[0].evidence["files"][0]
    assert rec["mistyped"] == {"written": "https: //s.test/img/icons/offer.svg", "address": "https://s.test/img/icons/offer.svg"}
    assert rec["folder"] is None
    row = found[0].evidence["pages"][0]["row"]
    assert row["tr"] == ("«offer.svg» dosyasının adresi bozuk yazılmış: «https: //s.test/img/icons/offer.svg» (iki noktadan "
                         "sonra boşluk; tarayıcı dosyayı bulamaz); doğru yazım: https://s.test/img/icons/offer.svg")
    assert "klasör" not in row["tr"] and "önerilen ad" not in row["tr"]


def test_a_folder_of_only_spaces_is_never_suggested_as_a_folder_name():
    assert fn.folder_problem("https://s.test/e-ticaret-paketleri/ /s.test/img/offer.svg") is None


def test_a_saved_reports_mistyped_address_is_read_from_the_pages_own_file_names():
    page = "https://s.test/e-ticaret-paketleri/"
    r = _saved("dosya adı «offer.svg» (boşluk); önerilen ad: offer.svg",
               "file name «offer.svg» (space); suggested name: offer.svg",
               page + " /s.test/img/icons/offer.svg")
    r["checks"][0]["findings"][0]["evidence"]["pages"][0]["url"] = page
    r["crawl"] = {"pages": [{"url": page, "analysis": {"file_names": [
        {"url": "https: //s.test/img/icons/offer.svg", "where": ["css background"], "problems": ["space"]}]}}]}
    changes: list[str] = []
    reassess_rules._decisions_379(r, {}, changes)
    row = r["checks"][0]["findings"][0]["evidence"]["pages"][0]["row"]
    assert row["tr"].startswith("«offer.svg» dosyasının adresi bozuk yazılmış: «https: //s.test/img/icons/offer.svg»")
    assert row["en"].endswith("correct form: https://s.test/img/icons/offer.svg") and changes


def test_a_current_schema_reports_rows_are_rewritten_too(monkeypatch):
    """The web app builds a new crawl's reports through `saved_data` (not the full re-evaluation): the Ticimax Ek made
    after the fix still read «önerilen ad: offer.svg» until this step ran there too. The other saved-data steps are
    left out here (they need full page records); this step and the order that follows are what is tested."""
    for name in dir(reassess_rules):
        if name.startswith("_decisions_") and name != "_decisions_379":
            monkeypatch.setattr(reassess_rules, name, lambda *a, **k: None)
    monkeypatch.setattr(reassess_rules, "_order", lambda r: [])
    monkeypatch.setattr("maya_audit.report.problem_summary", lambda *a, **k: {})
    page = "https://s.test/e-ticaret-paketleri/"
    r = _saved("dosya adı «offer.svg» (boşluk); önerilen ad: offer.svg",
               "file name «offer.svg» (space); suggested name: offer.svg", page + " /s.test/img/icons/offer.svg")
    r["checks"][0]["findings"][0]["evidence"]["pages"][0]["url"] = page
    r["crawl"] = {"pages": [{"url": page, "analysis": {"file_names": [
        {"url": "https: //s.test/img/icons/offer.svg", "where": ["css background"], "problems": ["space"]}]}}]}
    new, changes = reassess_rules.saved_data(r, {})
    row = new["checks"][0]["findings"][0]["evidence"]["pages"][0]["row"]["tr"]
    assert row.startswith("«offer.svg» dosyasının adresi bozuk yazılmış") and any("379" in c for c in changes)
    assert r["checks"][0]["findings"][0]["evidence"]["pages"][0]["row"]["tr"].startswith("dosya adı")  # source untouched
