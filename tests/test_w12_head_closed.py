"""DECISIONS 260: a body element printed inside <head> (a widget's <div>) ends the head there; the canonical, robots and
hreflang tags after it are lost to Google. Offline, made-up pages; the severity policy runs as in a report."""
from types import SimpleNamespace

from test_false_alarms import CFG, ROOT, site

from maya_audit.checks.page_markup import page_markup_findings
from maya_audit.severity import apply as apply_severity

WIDGET = '<div id="erisim-araci" class="a11y-widget">Erişilebilirlik</div>'


def page(head_extra_before="", head_extra_after=""):
    return ('<!doctype html><html lang="tr"><head><title>Sayfa | Örnekbanka</title>'
            '<meta name="description" content="Örnek sayfa">' + head_extra_before +
            head_extra_after + '</head><body><h1>Başlık</h1><p>Metin.</p></body></html>')


def findings(pages_html):
    result, pages = site(pages_html)
    check = SimpleNamespace(check_id="TSEO-1", findings=page_markup_findings(pages, set()), evidence={})
    apply_severity([check], result)
    return [f for f in check.findings if "end <head> early" in f.title]


def test_a_widget_inside_head_that_pushes_the_canonical_into_the_body_is_high_and_named():
    after = (f'<link rel="canonical" href="{ROOT}/"><meta name="robots" content="index,follow">'
             f'<link rel="alternate" hreflang="en" href="{ROOT}/en">')
    [lost] = findings({"/": page(WIDGET, after), "/a": page()})
    assert lost.severity.value == "S2" and lost.confidence.value == "verified"
    row = lost.evidence["pages"][0]
    assert row["closed_by"]["tag"] == "div" and row["closed_by"]["id"] == "erisim-araci"
    assert row["canonical_after"] == 1 and row["robots_after"] == ["robots"] and row["hreflang_after"] == 1


def test_only_open_graph_tags_after_the_break_is_medium():
    [later] = findings({"/": page(WIDGET, '<meta property="og:title" content="Örnek">'), "/a": page()})
    assert later.severity.value == "S3" and later.evidence["pages"][0]["properties_after"] == ["og:title"]


def test_a_tracking_pixel_in_a_head_noscript_and_a_clean_head_are_not_reported():
    pixel = '<noscript><img src="https://px.example/p.gif" height="1" width="1"></noscript>'
    assert findings({"/": page(pixel, f'<link rel="canonical" href="{ROOT}/">'), "/a": page()}) == []


def test_a_body_element_after_head_closed_normally_is_not_reported():
    html = page(f'<link rel="canonical" href="{ROOT}/">').replace("<body>", "<body>" + WIDGET)
    assert findings({"/": html, "/a": page()}) == []
