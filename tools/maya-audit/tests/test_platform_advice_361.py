"""DECISIONS 361: the MMI re-check after 4d158c8. (1) Advice for one platform (Shopify, WordPress, …) is shown only on a
site recognised as that platform, in the PDF and in the appendix, and RG-19 blocks any that is still shown (also when
the finding's own fix text names the platform, the loophole MMI's GTIN card went through); (2) the appendix says what the
PDF's cards say: a finding on a card gets the card's steps and the links it names in "Ne yapılmalı", and the Özet and
"Bulgular" show the card's scope with its sample note. Made-up records and a mock-transport shop only."""
from __future__ import annotations

from maya_audit import text_gate
from maya_audit.platform_text import for_platform, other_platform

GTIN_FIX = ("Add the product's GTIN (its barcode: gtin13 for an EAN) or, when it has none, its MPN, and the brand, to the "
            "Product markup. On Shopify, fill each variant's barcode field so the theme writes it.")


def test_another_platforms_sentence_clause_or_line_is_left_out():
    assert for_platform(GTIN_FIX, None).endswith("to the Product markup.") and "Shopify" not in for_platform(GTIN_FIX, None)
    assert for_platform(GTIN_FIX, "Shopify") == GTIN_FIX  # on a Shopify site it stays
    assert for_platform("Noindex them; on Shopify, add it in the theme's <head>.", "Ticimax") == "Noindex them."
    assert for_platform("Adım bir\nShopify'da: her varyantın barkod alanını doldurun\nAdım iki", None) == "Adım bir\nAdım iki"
    assert for_platform("Use the WordPress plugin", "WooCommerce") == "Use the WordPress plugin"  # WooCommerce runs on it
    assert other_platform("Ticimax panelinde düzeltin", "Ticimax") is None and other_platform("ikas'ta", None) == "ikas"


def _card(steps):
    return {"lang": "tr", "todos": [{"n": 1, "title": "Product işaretlemesine GTIN ya da MPN ekleyin", "steps": steps,
                                     "finding_ids": ["STR-3-x"], "scope": "82 sayfa"}]}


REPORT = {"platform": None, "checks": [{"check_id": "STR-3", "findings": [
    {"id": "STR-3-x", "check_id": "STR-3", "rule_id": "str3.product_no_identifier", "title": "82 product page(s) ...",
     "how_to_fix": GTIN_FIX, "scope": {"count": 82, "urls": []}, "evidence": {"pages": []}}]}]}


def test_rg19_blocks_platform_advice_even_when_the_findings_fix_names_the_platform():
    shown = text_gate.run(_card("GTIN'i ekleyin\nShopify'da: her varyantın barkod alanını doldurun"), REPORT, platform="")
    assert any(v["rule"] == "RG-19" and v["hard"] for v in shown["violations"]) and shown["decision"] == text_gate.BLOCKED
    clean = text_gate.run(_card("GTIN'i ekleyin\nMarkayı da ekleyin"), REPORT, platform="")
    assert not any(v["rule"] == "RG-19" for v in clean["violations"])
    on_shopify = text_gate.run(_card("GTIN'i ekleyin\nShopify'da: barkod alanını doldurun"), REPORT, platform="Shopify")
    assert not any(v["rule"] == "RG-19" for v in on_shopify["violations"])


def test_rg19_reads_the_appendixs_own_advice():
    record = {"version": "x", "decision": text_gate.PASS, "violations": [], "counts": {}, "hard": 0}
    hit = text_gate.with_platform_advice(record, [("Bulgular", "Ekleyin. Shopify'da her varyantın barkodunu doldurun.")], None)
    assert hit["decision"] == text_gate.BLOCKED and hit["counts"]["RG-19"] == 1
    assert text_gate.with_platform_advice(record, [("Bulgular", "Shopify'da doldurun.")], "Shopify")["decision"] == text_gate.PASS
    from maya_audit.client_appendix import advice_cells
    made = [{"name": "Bulgular", "header": ["Bulgu", "Ne yapılmalı"], "rows": [["a", "Shopify'da x"], ["b", ""]]},
            {"name": "Rakip", "header": ["Sayfa", "Not"], "rows": [["https://shopify.com/x", "Shopify"]]}]
    assert advice_cells(made) == [("Bulgular", "Shopify'da x")]  # site data in other columns is not advice


def test_the_appendix_says_what_the_cards_say(tmp_path, no_lookups):  # noqa: F811
    import json
    from maya_audit import final, xlsx
    from maya_audit_web.runner import REPORT_JSON
    from maya_audit_web.team_report import build_data, render
    import test_mmi_review_360 as shop
    report, _ = shop.crawl()
    folder = tmp_path / "artifacts"
    folder.mkdir()
    sealed = final.from_report(report, {})
    (folder / REPORT_JSON).write_text(json.dumps(sealed.report), encoding="utf-8")
    d = build_data.build_from_files(folder / REPORT_JSON, "tr")[0]
    todos = build_data.cards_for_appendix(d)
    card = next(t for t in todos if t.get("n") and t.get("steps"))
    card["scope"] = "3 sayfa (ölçülen 7 sayfadan; diğerleri de etkilenebilir)"  # as a sampled card says it
    card["sub"] = ["/blog: (metin yok) → /p/1 (gövde)"]
    content, _ = render.appendix_bytes(sealed.report, sealed.affected, {}, "tr", todos=todos)
    book = xlsx.read(content)
    head = book["Bulgular"][0]
    row = next(r for r in book["Bulgular"][1:] if r[0] == card["finding_ids"][0])
    assert row[head.index("Ne yapılmalı")] == "\n".join([card["steps"], *card["sub"]])
    assert row[head.index("Kapsam (sayı)")] == card["scope"]
    summary = next(r for r in book["Özet"][1:] if str(r[0]) == str(card["n"]))
    assert summary[book["Özet"][0].index("Etkilenen adres")] == card["scope"]


from test_firecrawl import no_lookups  # noqa: E402,F401  (fixture)
