"""W2 part 1 regressions: the homepage's Organization in three states (H11), a cap note only on capped findings (H12),
a shop's product pages found from its markup (H14), a hidden <h1> (H15) and placeholder alt text (H16)."""

from __future__ import annotations

import pytest

from maya_audit.analysis import analyze_html
from maya_audit.checks.small_site import str21_basic_pages
from maya_audit.checks.structure import CAPPED, placeholder_alt, str2_headings, str3_structured_data
from test_false_alarms import CFG, ROOT, TR, html, images_check, ld, path, site

ORG = {"@type": "Organization", "name": "Örnekmağaza", "url": ROOT + "/"}
# A theme's Organization with the street address on two lines: a raw newline inside a JSON string.
BROKEN_ORG = ('<script type="application/ld+json">{"@context":"https://schema.org","@type":"Organization",'
              '"name":"Örnek","address":{"streetAddress":"Tem Yan Yolu\n1 No\'lu Cadde"}}</script>')


def org_findings(head):
    result, pages = site({"/": html(f"<h1>Ana</h1><p>{TR}</p>", head=head)})
    return [f for f in str3_structured_data(result, CFG, pages, set()).findings if "organization" in f.title.lower()]


# -- H11 -------------------------------------------------------------------------------------------------------------
def test_a_homepage_with_no_organization_block_is_told_to_add_one():
    [finding] = org_findings("")
    assert finding.title == "The homepage has no Organization structured data" and finding.severity.value == "S3"


def test_a_broken_organization_block_is_reported_as_broken_with_where():
    [finding] = org_findings(BROKEN_ORG)
    # High since DECISIONS 258 (owner: homepage items an expert audit rates High are High here too).
    assert finding.title == "The homepage's Organization block does not parse" and finding.severity.value == "S2"
    [block] = finding.evidence["blocks"]
    assert (block["line"], block["character"], block["in_property"]) == (1, "newline (U+000A)", "streetAddress")
    assert block["column"] == block["char_position"] + 1 and "\\n" in block["excerpt"]
    assert finding.evidence["where"].startswith("line 1, column ")
    assert "add organization json-ld" not in finding.how_to_fix.lower()


def test_a_valid_organization_without_logo_is_one_info_note():
    [finding] = org_findings(ld(ORG))
    assert finding.title == "The homepage's Organization structured data has no logo or sameAs"
    assert finding.severity.value == "Info" and finding.evidence["missing"] == ["logo", "sameAs"]
    assert org_findings(ld({**ORG, "logo": ROOT + "/logo.png", "sameAs": ["https://x.example/o"]})) == []


# -- H12 -------------------------------------------------------------------------------------------------------------
def test_an_s3_finding_does_not_say_it_is_capped_at_s4():
    result, pages = site({"/": html(f"<p>{TR}</p>"), "/a/": html(f"<p>{TR}</p>")})
    findings = (str2_headings(result, CFG, pages, set(), set()).findings
                + str3_structured_data(result, CFG, pages, set()).findings)
    s3 = [f for f in findings if f.severity.value == "S3"]
    assert {f.title for f in s3} >= {"The homepage has no <h1>", "The homepage has no Organization structured data"}
    assert all(CAPPED not in f.notes for f in s3)
    assert [f for f in findings if f.severity.value == "S4" and CAPPED in f.notes]   # the capped ones keep their note


# -- H14 -------------------------------------------------------------------------------------------------------------
BASICS = {"/": html(f"<h1>Ana</h1><p>{TR}</p>"), "/hakkimizda/": html(f"<h1>Biz</h1><p>{TR}</p>"),
          "/iletisim/": html(f"<h1>İletişim</h1><p>{TR}</p>"), "/sss/": html(f"<h1>Sorular</h1><p>{TR}</p>")}


def product_gap(extra):
    result, pages = site({**BASICS, **extra})
    return [f for f in str21_basic_pages(result, CFG, pages, set()).findings if "product" in f.title.lower()]


def test_a_shop_with_product_markup_has_product_pages_whatever_they_are_called():
    item = ld({"@type": "Product", "name": "Bej", "offers": {"@type": "Offer", "price": "1299", "priceCurrency": "TRY"}})
    assert product_gap({"/arjava-bej-13": html(f"<h1>Bej</h1><p>{TR}</p>", head=item)}) == []


def test_a_shop_with_a_price_beside_an_add_to_cart_button_has_product_pages():
    body = f'<h1>Bej</h1><p class="price">1.299,00 TL</p><button>Sepete Ekle</button><p>{TR}</p>'
    assert product_gap({"/arjava-bej-13": html(body)}) == []


def test_a_brochure_site_without_product_signals_keeps_the_gap():
    assert len(product_gap({"/blog/yazi/": html(f"<h1>Yazı</h1><p>{TR}</p>")})) == 1


# -- H15 -------------------------------------------------------------------------------------------------------------
def heading_findings(home_body):
    result, pages = site({"/": html(home_body), "/a/": html(f"<h1>A</h1><p>{TR}</p>")})
    return str2_headings(result, CFG, pages, set(), set()).findings


@pytest.mark.parametrize("h1", ['<h1 style="display:none">Örnekmağaza</h1>', '<h1 style="visibility: hidden">Ö</h1>',
                                "<h1 hidden>Ö</h1>",
                                '<div style="display:none"><span><h1>Örnekmağaza</h1></span></div>'])
def test_a_homepage_whose_only_h1_is_hidden_is_reported_as_hidden(h1):
    findings = heading_findings(f"<p>{TR}</p>{h1}")
    [hidden] = [f for f in findings if "hidden" in f.title]
    assert hidden.title == "The homepage's only <h1> is hidden" and path(hidden.scope["urls"][0]) == "/"
    assert not [f for f in findings if "no <h1>" in f.title]                      # one root cause, said once


def test_an_aria_hidden_h1_is_not_hidden_from_readers():
    """DECISIONS 360 (İlginay): aria-hidden hides from screen readers only; the page still shows its <h1>."""
    findings = heading_findings(f'<p>{TR}</p><h1 aria-hidden="true">Ö</h1>')
    assert not [f for f in findings if "hidden" in f.title or "no <h1>" in f.title]


def test_a_hidden_h1_repeating_the_title_says_so():
    [hidden] = [f for f in heading_findings('<h1 style="display:none">Sayfa | Örnekmağaza</h1>') if "hidden" in f.title]
    assert hidden.evidence["pages"][0]["same_as_title"] is True


def test_a_visible_h1_is_not_reported_hidden():
    assert not [f for f in heading_findings(f'<h1 class="x">Ana</h1><p>{TR}</p><div style="display:none">x</div>')
                if "hidden" in f.title or "<h1>" in f.title]
    assert analyze_html("<div hidden></div><h1>Görünür</h1>", ROOT + "/")["headings"][0].get("hidden") is None


# -- H16 -------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("alt", ["image title", "Image Title", "Görsel", "resim", "alt text", "untitled", "Banner",
                                 "IMG-2034.png", "DSC_1.jpg", "img_2034", "Screenshot 12"])
def test_placeholder_alt_patterns_are_recognised(alt):
    assert placeholder_alt({"alt": alt}) is not None


@pytest.mark.parametrize("alt", ["Bej renkli koku difüzörü", "Image of a red bicycle", "Banner ile mağaza girişi"])
def test_a_real_alt_is_not_a_placeholder(alt):
    assert placeholder_alt({"alt": alt}) is None


def test_an_alt_that_repeats_the_title_attribute_is_not_a_placeholder():
    # Review G09 reversed H16's third sign: shop and blog themes write the product's own name in alt and title.
    assert placeholder_alt({"alt": "Bej koku difüzörü", "title": "bej koku difüzörü"}) is None
    assert placeholder_alt({"alt": "Görsel", "title": "Görsel"}) == "a placeholder word"


def test_placeholder_alt_is_reported_by_str7():
    check = images_check('<img src="/u/bej.jpg" alt="image title"><img src="/u/x.jpg" alt="Bej koku difüzörü">')
    [finding] = [f for f in check.findings if "placeholder alt" in f.title]
    assert [(row["alt"], row["why"]) for row in finding.evidence["images"]] == [("image title", "a placeholder word")]
