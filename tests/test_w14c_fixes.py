"""Fixes after the 2026-10-29 client PDFs (DECISIONS 284). Hand-written pages; offline, in memory."""
from __future__ import annotations

from maya_audit import verification
from maya_audit.checks.structure import str2_headings
from maya_audit.severity import apply as apply_severity
from test_false_alarms import CFG, TR, html, site


# ------------------------------------------------------------------ (3) a hidden homepage <h1> is at most Medium


def test_a_hidden_homepage_h1_is_medium_because_nothing_re_tests_it():
    assert "str2.home_hidden_h1" not in verification.RETESTS  # if a re-test is added, revisit the cap
    result, pages = site({"/": html('<h1 style="display:none">Örnekmağaza</h1>' + f"<p>{TR}</p>"),
                          "/a": html("<h1>A</h1>")})
    check = str2_headings(result, CFG, pages, set(), set())
    apply_severity([check], result)
    [hidden] = [f for f in check.findings if f.title == "The homepage's only <h1> is hidden"]
    assert hidden.severity.value == "S3"


# ------------------------------------------------------------------ (4) a calculator's result column is not a table

from test_preview16_false_alarms import PRICES, str8_on  # noqa: E402

RESULT = "".join(f'<div class="satir"><span>{label}</span><span>{value}</span></div>'
                 for label, value in (("Aylık faiz oranı", "%4,25"), ("Anapara borcu", "1.000,00 TL"),
                                      ("Faiz ve vergi borcu", "55,26 TL"), ("Toplam borç", "1.055,26 TL")))
SLIDERS = '<div class="girdi"><label>Tutar <input type="range" min="0" max="9"></label></div>'


def calculator(inputs_first: bool, block="kredi"):
    """A loan calculator: an input column with a slider beside a result column whose rows are computed amounts."""
    columns = [SLIDERS, f'<div class="sonuc">{RESULT}</div>']
    return (f'<h2>Kredi</h2><section class="{block}"><div class="{block}__form">'
            + "".join(columns if inputs_first else columns[::-1]) + "</div></section>")


def test_a_loan_calculators_result_column_is_not_a_comparison_table():
    """Enpara /krediler/ekpara (2026-10-29): the sliders are in the column beside the grid, before or after it."""
    for inputs_first in (True, False):
        check = str8_on(calculator(inputs_first), path="/krediler/")
        assert check.findings == [], inputs_first
        assert [g["why"] for g in check.evidence["grids_left_out"]] == ["a calculator or form: its rows are input fields, not a table of facts"]


def test_a_block_named_as_a_calculator_is_left_out_without_standard_controls():
    """Custom sliders (<div>s driven by script) carry no form control; the block's own name says calculator."""
    body = f'<h2>Kredi</h2><section class="loan-calculator"><div class="loan-calculator__column">{RESULT}</div></section>'
    assert str8_on(body, path="/krediler/").findings == []


def test_a_price_grid_is_still_reported_when_a_control_is_elsewhere_on_the_page():
    """Counter-example: a search box in another block does not make a price list a calculator."""
    body = '<div class="arama"><form><input name="q"></form></div>' + PRICES
    check = str8_on(body, path="/paketler/")
    assert [f.title for f in check.findings] == ["1 page(s) lay out pricing or spec comparisons as <div> grids instead of <table>"]


# ------------------------------------------------------------------ DECISIONS 290: category titles, RND-3 guess

from maya_audit.checks.structure import str5_entity  # noqa: E402
from maya_audit.structure_data import StructureData  # noqa: E402
from test_false_alarms import ROOT, ld  # noqa: E402


def nihan_pages(category_site_name=False):
    """A shop named "Nihan" everywhere; two collections whose titles end in "Nihan Women's Coats" / "Nihan Outerwear"."""
    org = ld({"@type": "Organization", "name": "Nihan", "url": ROOT + "/"})
    pages = {f"/urun-{n}": html(f"<h1>Ürün {n}</h1><p>{TR}</p>", title=f"Ürün {n} | Nihan",
                                head='<meta property="og:site_name" content="Nihan">' + org) for n in range(6)}
    for suffix, paths in (("Nihan Women's Coats", ("/kaban-1", "/kaban-2")), ("Nihan Outerwear", ("/dis-1", "/dis-2"))):
        for path in paths:
            site_name = suffix if category_site_name else "Nihan"
            pages[path] = html(f"<h1>{path}</h1><p>{TR}</p>", title=f"{path.strip('/')} | {suffix}",
                               head=f'<meta property="og:site_name" content="{site_name}">' + org)
    pages["/"] = html(f"<h1>Nihan</h1><p>{TR}</p>", title="Nihan", head=org + '<meta property="og:site_name" content="Nihan">')
    result, made = site(pages)
    return str5_entity(result, CFG, made, set(), StructureData())


def test_category_titles_after_the_brand_are_not_brand_names():
    check = nihan_pages()
    assert not [f for f in check.findings if "different ways" in f.title]
    assert check.evidence["category_titles_not_counted"] == ["Nihan Outerwear", "Nihan Women's Coats"]


def test_a_longer_name_the_site_also_gives_as_its_name_is_still_counted():
    """Counter-example: og:site_name says "Nihan Women's Coats" on those pages, so it is a name the site gives itself."""
    check = nihan_pages(category_site_name=True)
    assert check.evidence["category_titles_not_counted"] == []


def test_a_raw_html_guess_about_hidden_content_is_low_with_its_check_note():
    from maya_audit.checks import render
    from test_evidence_integrity import _rnd3
    check = _rnd3("<html lang='en'><body><main><h1>Shop</h1><p>Coats and abayas.</p><button>Load more</button></main></body></html>")
    [guess] = [f for f in check.findings if "raw-HTML heuristics" in f.title]
    assert guess.severity.value == "S4" and guess.confidence.value == "estimated"
    assert render.RND3_CHECK_NOTE in guess.notes and "English only" in render.RND3_CHECK_NOTE
