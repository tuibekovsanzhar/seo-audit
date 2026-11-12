"""DECISIONS 345: the 301 target suggested for each missing sitemap address (the owner's check of enpara fee70191's 21).

A target never leaves the address's top section; the closest existing parent comes first, "existing" meaning a page
that answered 200, a sitemap-check answer of 200, or a sitemap address no request showed to fail; words decide only
within the section and only when clearly better; a weak case says "önerilen hedef (kontrol edin)".
"""
from __future__ import annotations

from types import SimpleNamespace

from maya_audit.checks import team_rules
from maya_audit.checks.team_rules import known_live, suggest_target

B = "https://b.test"


def page(path: str, title: str = "", status: int = 200):
    return SimpleNamespace(url=B + path, status=status, analysis={"title": title})


def result(pages=(), sitemap=(), rows=()):
    return SimpleNamespace(pages=list(pages), sitemap_urls=[B + p for p in sitemap],
                           index={"sitemap_check": {"rows": [{"url": B + p, "status": s} for p, s in rows]}})


def test_a_target_never_leaves_the_business_section():
    # the personal section has a page with nearly the same words: a trap
    r = result([page("/kartlar/kredi-karti-aidati", "Kredi kartı aidatı | Banka"), page("/sirketim", "Şirketim | Banka")])
    known = known_live(r, {B + "/sirketim/kampanya/kredi-karti-aidati-yok"})
    target, why, firm = suggest_target(B + "/sirketim/kampanya/kredi-karti-aidati-yok", known)
    assert target == B + "/sirketim" and why == "far_parent" and firm is False  # "kontrol edin", never /kartlar/...


def test_the_closest_parent_wins_also_when_only_the_sitemap_knows_it():
    r = result([page("/odemeler", "Ödemeler")], sitemap=["/odemeler/islem-kisitlari", "/odemeler/islem-kisitlari/islem-saatleri"])
    missing = B + "/odemeler/islem-kisitlari/islem-saatleri"
    known = known_live(r, {missing})
    assert known[B + "/odemeler/islem-kisitlari"]["basis"] == "sitemap" and missing not in known
    assert suggest_target(missing, known) == (B + "/odemeler/islem-kisitlari", "parent", True)


def test_an_address_that_failed_is_never_a_target():
    r = result([page("/hesap"), page("/hesap/eski", status=404)], sitemap=["/hesap/yeni"], rows=[("/hesap/yeni", 302)])
    known = known_live(r, set())
    assert B + "/hesap/eski" not in known and B + "/hesap/yeni" not in known


def test_words_decide_within_the_section_only_when_clearly_better():
    r = result([page("/kartlar", "Kartlar"), page("/kartlar/encard/basvuru-sartlari", "Encard başvuru şartları")])
    # the direct parent /kartlar/encard does not exist; a page of the section shares most words: a firm target
    known = known_live(r, set())
    assert suggest_target(B + "/kartlar/encard/encard-basvuru-sartlari", known)[:2] == (B + "/kartlar/encard/basvuru-sartlari", "similar")
    # with the direct parent known, the parent wins over a page sharing some words
    r = result([page("/kartlar/encard", "Encard"), page("/kartlar/encard-genc/basvuru", "Başvuru")])
    known = known_live(r, set())
    assert suggest_target(B + "/kartlar/encard/basvuru-adimlari", known)[:2] == (B + "/kartlar/encard", "parent")


def test_a_word_match_only_the_sitemap_lists_is_to_check():
    r = result([page("/sirketim")], sitemap=["/sirketim/kartlar/kredi-karti-aidati"])
    known = known_live(r, set())
    target, why, firm = suggest_target(B + "/sirketim/kampanya/kredi-karti-aidati-yok", known)
    assert target == B + "/sirketim/kartlar/kredi-karti-aidati" and why == "similar" and firm is False


def test_no_related_page_is_410_and_a_top_address_stays_at_the_top():
    known = known_live(result([page("/en/payments", "Payments")]), set())
    assert suggest_target(B + "/kampanya-yok", known) == (None, "none", True)
    known = known_live(result([page("/kampanyalar", "Kampanyalar | Banka"), page("/en/campaigns", "Campaigns")]), set())
    target, why, firm = suggest_target(B + "/aktif-kampanyalar", known)
    assert target == B + "/kampanyalar" and firm is False


def test_the_card_rows_say_firm_or_to_check():
    sitemap = {"check_id": "IDX-1", "rule_id": "idx1.4xx.sitemap_only",
               "evidence": {"sitemap_entries": [{"url": B + "/sirketim/kampanya/aidat-yok"}, {"url": B + "/odemeler/x/y"}]}}
    check = {"check_id": "IDX-1", "findings": [sitemap]}
    r = result([page("/sirketim"), page("/odemeler/x")])
    r.redirects = []
    team_rules.settle([check], r)
    rows = {x["url"]: x for x in sitemap["evidence"]["suggestions"]}
    assert rows[B + "/sirketim/kampanya/aidat-yok"]["row"]["tr"] == "önerilen hedef (kontrol edin): /sirketim (en yakın var olan üst sayfa)"
    assert rows[B + "/sirketim/kampanya/aidat-yok"]["fix"]["tr"] == ("Site haritasından çıkarın; /sirketim uygunsa 301 ile oraya "
                                                                    "yönlendirin, değilse 410 döndürün.")
    assert rows[B + "/odemeler/x/y"]["row"]["tr"] == "önerilen 301 hedefi: /odemeler/x (üst klasör sayfası)"
    assert sitemap["evidence"]["suggestion_rule"] == 345
