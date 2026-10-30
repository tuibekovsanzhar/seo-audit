"""Unit tests for the STR parsers and heuristics."""

from datetime import date
from decimal import Decimal

from fakeserver.str_scenarios import EN, TR
from maya_audit.analysis import analyze_html
from maya_audit.checks.structure import brand_key, parse_number, price_tokens, visible_dates
from maya_audit.language import detect_language, english_text_assessable


def test_numbers_in_both_conventions():
    assert parse_number("1,299.00") == Decimal("1299.00")
    assert parse_number("1.299,00") == Decimal("1299.00")
    assert parse_number("49,90") == Decimal("49.90")
    assert parse_number("1,299") == Decimal("1299")
    assert parse_number("49") == Decimal("49")


def test_price_tokens_and_currencies():
    tokens = price_tokens("Pro $49/mo, Team 99 EUR, Kurumsal ₺1.299,00 or 250 TL; 30 kr. Version 2.0 has 10 seats")
    got = {(t["value"], tuple(sorted(t["currencies"]))) for t in tokens}
    assert (Decimal("49"), ("AUD", "CAD", "HKD", "MXN", "NZD", "SGD", "USD")) in got
    assert (Decimal("99"), ("EUR",)) in got and (Decimal("1299.00"), ("TRY",)) in got
    assert (Decimal("250"), ("TRY",)) in got and (Decimal("30"), ("DKK", "ISK", "NOK", "SEK")) in got
    assert len(tokens) == 5  # "2.0" and "10 seats" are not prices


def test_language_guess_is_conservative():
    assert detect_language(EN * 3)["language"] == "en"
    assert detect_language(TR * 3)["language"] == "tr"
    short = detect_language("We use cookies. Accept all cookies to continue.")
    assert short["language"] is None and "too little text" in short["reason"]
    assert detect_language("home0 home1 " * 60)["language"] is None


def test_english_signatures_trust_content_over_declaration():
    tr_declared_en = analyze_html(f'<html lang="en"><body><p>{TR * 3}</p></body></html>')
    assert english_text_assessable(tr_declared_en)[0] is False
    short_en = analyze_html('<html lang="en-GB"><body><p>Accept all cookies</p></body></html>')
    assert english_text_assessable(short_en) == (True, "declared lang='en-GB'; language guess inconclusive")
    short_undeclared = analyze_html("<html><body><p>Accept all cookies</p></body></html>")
    assert english_text_assessable(short_undeclared)[0] is False


def test_brand_name_normalization():
    assert brand_key("Acme Analytics, Inc.") == brand_key("ACME analytics") == "acme analytics"
    assert brand_key("Acme Yazılım A.Ş.") == "acme yazılım"
    assert brand_key("Acme logo") == "acme"
    assert brand_key("Acme GmbH & Co") == "acme"  # stacked legal suffixes; "&" alone stays out of the count
    assert brand_key("Inc") == "inc"  # never normalizes a name away entirely


def test_visible_dates():
    a = analyze_html('<html><body><main><p>Published March 3, 2026 · Updated 2026-06-01</p>'
                     '<time datetime="2026-03-03">3 Mar</time><p>Etkinlik 14.09.2026</p></main>'
                     '<footer><time datetime="2020-01-01">old</time></footer></body></html>')
    found = {(d["date"], d["kind"]) for d in visible_dates(a)}
    assert found == {(date(2026, 3, 3), "published"), (date(2026, 6, 1), "modified"), (date(2026, 9, 14), None)}


def test_structured_data_extraction():
    a = analyze_html(
        '<html><head><script type="application/ld+json">{"@graph": [{"@type": "Organization", "name": "Acme"}]}</script>'
        '<script type="application/ld+json">{"@type": "Product",}</script></head><body>'
        '<div itemscope itemtype="https://schema.org/Product"><span itemprop="name">Lamp</span>'
        '<div itemprop="offers" itemscope itemtype="https://schema.org/Offer"><meta itemprop="price" content="30"></div></div>'
        '<div vocab="https://schema.org/" typeof="Person"><span property="name">Jane</span></div>'
        '</body></html>')
    sd = a["structured_data"]
    assert sd["types"] == ["Offer", "Organization", "Person", "Product"]
    assert sd["formats"] == ["json-ld", "microdata", "rdfa"]
    assert [b["ok"] for b in sd["jsonld_blocks"]] == [True, False]
    microdata = next(i["data"] for i in a["_structured_items"] if i["format"] == "microdata")
    assert microdata == {"@type": ["Product"], "name": "Lamp", "offers": {"@type": ["Offer"], "price": "30"}}


def test_image_and_heading_counts_remain_exact_past_detail_caps():
    images = "".join(f'<img src="/{i}.png">' for i in range(205))
    jumps = "<h1>Title</h1><h2>Section</h2><h4>Skipped</h4>" * 25
    analysis = analyze_html(f"<main>{images}{jumps}</main>")
    assert len(analysis["images"]) == 200
    assert analysis["image_counts"]["main_content"] == {
        "total": 205, "missing_alt": 205, "empty_alt": 0, "details_retained": 200,
    }
    assert analysis["heading_counts"]["total"] == 75
    assert analysis["heading_counts"]["skipped_level_jumps_total"] == 25


def test_div_grid_detection():
    def grid(rows, cls="row"):
        return "<div class='g'>" + "".join(f"<div class='{cls}'>" + "".join(f"<div>{c}</div>" for c in r) + "</div>"
                                           for r in rows) + "</div>"

    table_like = analyze_html("<main>" + grid([["Plan", "Pro"], ["Price", "$49"], ["Seats", "10"]]) + "</main>")
    assert table_like["div_grids"][0]["rows"] == 3 and table_like["div_grids"][0]["cells_per_row"] == 2
    two_by_two = analyze_html("<main>" + grid([["a", "b"], ["c", "d"]]) + "</main>")
    assert two_by_two["div_grids"] == []  # fewer than 6 cells
    prose = analyze_html("<main>" + grid([["Why", "x" * 80], ["How", "y" * 80], ["When", "z" * 80]]) + "</main>")
    assert prose["div_grids"] == []
    with_lists = analyze_html("<main><div class='g'>" + "<div class='c'><div>Pro</div><ul><li>a</li></ul><div>$9</div></div>" * 3
                              + "</div></main>")
    assert with_lists["div_grids"] == []
    in_footer = analyze_html("<footer>" + grid([["a", "b", "c"], ["d", "e", "f"]]) + "</footer>")
    assert in_footer["div_grids"] == []
