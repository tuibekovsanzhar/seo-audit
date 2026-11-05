"""DECISIONS 313: the business type as a compact chip with the type in use in "Değiştir"; headlines with exact counts
("Engelleyici" only with a Blocker); hints after the title; "adres", never "URL", in Turkish text; a homepage whose
importance a canonical or redirect problem holds down is said so in the key pages."""
from __future__ import annotations

import json
import re
from pathlib import Path

from maya_audit.client_appendix import WORDS, build as appendix_build
from maya_audit.client_selection import importance_unknown, key_pages
from maya_audit.xlsx import read as read_xlsx
from maya_audit_web import strings
from maya_audit_web.team_report import texts as T
from maya_audit_web.team_report.render import LABELS, page6
from test_web_ux_310 import _browser, _page

ROOT = Path(__file__).resolve().parents[1]
SITE = "https://h.example"


# ---------------------------------------------------------------- 1. the business type

def test_the_business_type_is_a_chip_with_its_reason_folded_and_the_dropdown_shows_the_type_in_use():
    sync_playwright = _browser()
    with sync_playwright() as pw:
        browser, page, errors = _page(pw)
        info = {"id": "saglik", "label": "Sağlık / klinikler", "chosen_by": "suggestion", "suggested_id": "saglik",
                "reason": "ana sayfada Hospital yapısal verisi", "not_found": "Okunan sayfalar arasında bulunamadı: Klinik ve konum",
                "choices": [{"id": "eticaret", "label": "E-ticaret / perakende", "group": None},
                            {"id": "saglik", "label": "Sağlık / klinikler", "group": None},
                            {"id": "otomotiv", "label": "Otomotiv", "group": None}]}
        got = page.evaluate("""info => {
            const box = businessBox({ audit: { id: "c581ff0a00000000" } }, info, () => null);
            document.getElementById("result").append(box);
            const select = box.querySelector("select");
            return { chip: box.querySelector(".business-chip").textContent, why: box.querySelector("details summary").textContent,
                     open: box.querySelector("details").open, reason: box.querySelector("details p").textContent,
                     shown: select.options[select.selectedIndex].text, values: [...select.options].map(o => o.value) };
        }""", info)
        assert got["chip"] == "İşletme türü: Sağlık / klinikler" and got["why"] == "Neden?" and not got["open"]
        assert got["reason"] == "Siteden önerildi: ana sayfada Hospital yapısal verisi"
        assert got["shown"] == "Sağlık / klinikler (önerilen)" and "auto" not in got["values"]
        chosen = page.evaluate("""info => {
            const box = businessBox({ audit: { id: "c581ff0a00000000" } }, info, () => null);
            const s = box.querySelector("select"); return [s.options[s.selectedIndex].text, box.querySelector("details p").textContent];
        }""", {**info, "id": "otomotiv", "chosen_by": "user"})
        assert chosen == ["Otomotiv", "Sizin seçiminiz."]
        assert not errors
        browser.close()


# ---------------------------------------------------------------- 2. the headline

def test_the_headline_says_the_exact_counts_and_blocking_only_with_a_blocker():
    one = T.headline(["S2"], ["geri dönen kanonik adres"], "tr", counts={"S2": 1})
    assert one == "1 yüksek önemde sorun var; önce geri dönen kanonik adres."
    many = T.headline(["S2", "S3"], ["a"], "tr", counts={"S2": 1, "S3": 7, "S4": 11, "Info": 6})
    assert many.startswith("1 yüksek, 7 orta ve 11 düşük önemde sorun var") and "Engelleyici" not in many
    assert "engelleyici" not in many.casefold()
    blocker = T.headline(["S1"], ["a"], "tr", counts={"S1": 1, "S2": 2})
    assert blocker.startswith("1 engelleyici ve 2 yüksek önemde sorun var")
    assert T.headline(["S3"], ["a"], "en", counts={"S3": 1}).startswith("There is 1 medium-severity issue")
    assert T.headline(["S2", "S3"], ["a"], "en", counts={"S2": 1, "S3": 2}).startswith("There are 1 high and 2 medium-severity issues")
    assert "blocking" not in T.headline(["S2"], ["a"], "en", counts={"S2": 3})


# ---------------------------------------------------------------- 3. hints

def test_the_hint_comes_after_the_whole_title_never_inside_it():
    sync_playwright = _browser()
    with sync_playwright() as pw:
        browser, page, errors = _page(pw)
        got = page.evaluate("""() => {
            const host = el("strong", {}, hinted("Canonical'ı sayfanın kendi adresi yapın; hreflang da"));  // as the page builds it
            return { first: host.childNodes[0].textContent, hints: host.querySelectorAll(".hint").length,
                     text: host.textContent };
        }""")
        assert got["first"] == "Canonical'ı sayfanın kendi adresi yapın; hreflang da"  # whole, first
        assert got["hints"] == 2 and got["text"].startswith("Canonical'ı sayfanın kendi adresi yapın; hreflang da ?")
        assert not errors
        browser.close()


# ---------------------------------------------------------------- 4. units

KEPT = ("URL Denetimi", "URL is unknown to Google")  # Google's own name, and its English status quoted as written


def _values(x):
    if isinstance(x, dict):
        for v in x.values():
            yield from _values(v)
    elif isinstance(x, list):
        for v in x:
            yield from _values(v)
    elif isinstance(x, str):
        yield x


def test_no_turkish_text_says_url():
    files = [ROOT / "maya_audit_web" / "locales" / name for name in ("tr.json", "findings/tr.json", "catalog/tr.json")]
    values = [v for f in files for v in _values(json.loads(f.read_text(encoding="utf-8")))]
    values += list(_values(json.loads((ROOT / "maya_audit_web/team_report/texts/tr.json").read_text(encoding="utf-8"))))
    values += list(_values(json.loads((ROOT / "maya_audit_web/team_report/refs/etiketler.json").read_text(encoding="utf-8"))["tr"]))
    values += list(_values(WORDS["tr"]))
    bad = [v for v in values if re.search(r"(?<![a-z:/{])URL", v) and not any(k in v for k in KEPT)]
    assert bad == []
    assert LABELS["tr"]["scope_units"]["url"] == ["adres", "adres"]
    assert "{unread} adres okunmadı" in LABELS["tr"]["prov_content_line"]


# ---------------------------------------------------------------- 5. the homepage's importance

def _importance(capped="not indexable"):
    return {f"{SITE}/tr/": {"importance": 20, "importance_rank": 9, "page_type": "home",
                            "page_type_basis": "the start address's final page",
                            "importance_parts": {"internal_link_score": 100, "click_depth": 100, "page_type": 100, "capped": capped}},
            f"{SITE}/tr/a/": {"importance": 80, "importance_rank": 1, "page_type": "category"}}


def test_a_homepage_held_down_by_a_canonical_card_says_so_instead_of_a_number():
    rows = [{"placement": "card", "card": 3, "rule_id": "str5.names", "urls": [f"{SITE}/tr/"], "severity": "S4"},
            {"placement": "card", "card": 1, "rule_id": "idx4.redirect_loop", "urls": [f"{SITE}/tr/"], "severity": "S2"}]
    pages = key_pages({"crawl": {"start_url": SITE + "/"}}, rows, _importance())
    assert pages[0]["importance_unknown"] == {"reason": "canonical", "card": 1} and pages[1]["importance_unknown"] is None
    # Not capped, or capped with no canonical/redirect card: the number stays.
    assert key_pages({"crawl": {"start_url": SITE + "/"}}, rows, _importance(False))[0]["importance_unknown"] is None
    assert importance_unknown(_importance()[f"{SITE}/tr/"], [rows[0]]) is None
    assert importance_unknown(_importance()[f"{SITE}/tr/"], [{"card": 2, "rule_id": "idx3.chain"}]) == {"reason": "redirect", "card": 2}
    L = LABELS["tr"]
    shown = L["kp_importance_unknown"].format(reason=L["kp_importance_reasons"]["canonical"], card=1)
    assert shown == "önem hesaplanamadı (kanonik sorunu, bkz. kart #1)"
    html = page6({"key_pages": [{"rank": 1, "path": "/tr/", "url": f"{SITE}/tr/", "type": "Ana sayfa (4 dil)", "importance": shown,
                                 "importance_unknown": True, "cards": "01", "worst": "Yüksek", "confirm": 0}],
                  "appendix": {"line": "-"}}, L)
    assert "Ana sayfa (4 dil) · önem hesaplanamadı (kanonik sorunu, bkz. kart #1)" in html and 'colspan="2"' in html
    assert strings.t("c6.kp.importance_unknown", "tr", reason=strings.t("c6.kp.reason.canonical", "tr"), card=1) == shown


def test_the_appendix_says_it_too():
    from maya_audit import client_selection
    from test_v03_client_report import finding, report
    selection = client_selection.select(report([finding("A", "r.a")]))
    selection["key_pages"] = [{"rank": 1, "url": f"{SITE}/tr/", "languages": [], "page_type": "home", "importance": 20,
                               "importance_unknown": {"reason": "canonical", "card": 1}, "cards": [1], "worst": "S2",
                               "confirm": 0}]
    rows = read_xlsx(appendix_build(selection, "tr"))["Kilit sayfalar"]
    assert any(r[:4] == ["1", f"{SITE}/tr/", "ana sayfa", "önem hesaplanamadı (kanonik sorunu, bkz. kart #1)"] for r in rows), rows
