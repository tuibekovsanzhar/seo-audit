"""DECISIONS 261: structured-data values in a form Google cannot read (seen live on a shop: a rating "4,38", a key
"reviewCount " with a trailing space, a currency "try"). Offline, made-up pages; the severity policy runs."""
from types import SimpleNamespace

from test_false_alarms import CFG, html, ld, site

from maya_audit.checks.structure import str3_structured_data
from maya_audit.severity import apply as apply_severity

PRODUCT = {"@type": "Product", "name": "Örnek Difüzör", "image": "https://shop.example.test/a.jpg",
           "offers": {"@type": "Offer", "price": "1299.90", "priceCurrency": "TRY"},
           "aggregateRating": {"@type": "AggregateRating", "ratingValue": "4.4", "reviewCount": "13"}}


def value_findings(product):
    result, pages = site({"/": html("<h1>Örnekmağaza</h1>"), "/urun": html("<h1>Ürün</h1><p>Fiyat</p>", head=ld(product))})
    check = str3_structured_data(result, CFG, pages, set())
    apply_severity([check], result)
    return [f for f in check.findings if "cannot read" in f.title]


def test_comma_decimal_spaced_key_and_lower_case_currency_are_one_medium_finding():
    broken = {**PRODUCT, "offers": {"@type": "Offer", "price": "1.299,90", "priceCurrency": "try"},
              "aggregateRating": {"@type": "AggregateRating", "ratingValue": "4,38", "reviewCount ": "13"}}
    [finding] = value_findings(broken)
    assert finding.severity.value == "S3" and finding.confidence.value == "verified"
    problems = {(p["property"], p["problem"].split(" ")[0]) for item in finding.evidence["items"] for p in item["problems"]}
    assert {("ratingValue", "comma"), ("reviewCount ", "property"), ("priceCurrency", "not"), ("price", "comma")} <= problems


def test_well_formed_values_are_not_reported():
    assert value_findings(PRODUCT) == []
