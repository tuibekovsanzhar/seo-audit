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
