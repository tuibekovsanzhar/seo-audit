"""DECISIONS 278 (T6): a page's kind decides which content advice it may get. Page 2 of a blog is a list, not a post; a
page of unknown kind gets no Article, product, price or conversion advice. Offline, made-up pages (shop.example.test)."""
from types import SimpleNamespace

from test_false_alarms import CFG, ROOT, html, site

from maya_audit import release_gate
from maya_audit.checks.structure import annotate_page_types, page_kind, str3_structured_data
from maya_audit.facts import attach
from maya_audit.models import to_jsonable
from maya_audit.rules import assign

POSTS = "".join(f'<a href="/blog/post-{n}">Yazı {n}</a>' for n in range(1, 6))
TEXT = "<p>" + "Kokular ve makineler hakkında bilgi. " * 12 + "</p>"


def kinds(pages_html):
    result, pages = site(pages_html)
    return {p.url.removeprefix(ROOT): page_kind(p, ROOT + "/")[0] for p in pages}, result, pages


def test_blog_pagination_expects_no_article():
    found, result, pages = kinds({"/": html(TEXT), "/blog/2": html(POSTS + TEXT, title="Blog | Örnek - Sayfa 2"),
                                  "/blog/post-1": html(TEXT, title="Koku makinesi nasıl çalışır")})
    assert found["/blog/2"] == "pagination" and found["/blog/post-1"] == "article"
    check = str3_structured_data(result, CFG, pages, set())
    expected = [f for f in check.findings if "structured data type expected" in f.title]
    assert expected and all(p["url"] != ROOT + "/blog/2" for f in expected for p in f.evidence["pages"])


def test_one_pagination_signal_is_not_enough():
    """A post whose address ends in a year is still a post."""
    found, *_ = kinds({"/": html(TEXT), "/blog/2024": html(TEXT, title="2024 yılının kokuları")})
    assert found["/blog/2024"] == "article"


def test_page_types_for_many_kinds_and_unknown_ones():
    found, result, pages = kinds({
        "/": html(TEXT), "/fiyatlar": html(TEXT), "/urun/koku-makinesi": html(TEXT, head='<meta property="og:type" content="product">'),
        "/blog/yazi": html(TEXT), "/blog/page/3": html(POSTS + TEXT, title="Blog - Page 3"), "/kategori/makineler": html(TEXT),
        "/docs/kurulum": html(TEXT), "/arsiv": html(TEXT)})
    assert found == {"/": "homepage", "/fiyatlar": "pricing", "/urun/koku-makinesi": "product", "/blog/yazi": "article",
                     "/blog/page/3": "pagination", "/kategori/makineler": "category", "/docs/kurulum": None, "/arsiv": None}
    finding = SimpleNamespace(scope={"urls": [ROOT + u for u in ("/blog/yazi", "/docs/kurulum", "/gone", "/never-read")]},
                              page_types=None)
    result.pages.append(SimpleNamespace(url=ROOT + "/gone", status=404, analysis=None, depth=1))
    annotate_page_types([SimpleNamespace(findings=[finding])], result)
    assert finding.page_types == {ROOT + "/blog/yazi": "article", ROOT + "/docs/kurulum": "unknown", ROOT + "/gone": "404",
                                  ROOT + "/never-read": "unknown"}


def contract_report(check, result):
    assign([check])
    attach([check])
    annotate_page_types([check], result)
    return {"checks": [to_jsonable(check)]}


def test_engine_content_advice_passes_the_gate():
    _, result, pages = kinds({"/": html(TEXT), "/blog/2": html(POSTS + TEXT, title="Blog - Sayfa 2"),
                              "/blog/post-1": html(TEXT)})
    report = contract_report(str3_structured_data(result, CFG, pages, set()), result)
    expected = [f for c in report["checks"] for f in c["findings"] if f["rule_id"] == "str3.expected_type"]
    assert expected and expected[0]["remediation"]["content"] and expected[0]["page_types"] == {ROOT + "/blog/post-1": "article"}
    assert [v for v in release_gate.check_report(report) if v["rule"] == "RG-7"] == []


def test_unknown_page_type_gets_no_content_advice_from_the_gate():
    """A saved report whose content advice names a page of no established kind is stopped, with the reason."""
    saved = {"id": "STR-3-x", "check_id": "STR-3", "rule_id": "str3.expected_type", "severity": "Info",
             "scope": {"urls": [ROOT + "/x"]}, "evidence": {"pages": [{"url": ROOT + "/x"}]}}
    check = {"check_id": "STR-3", "findings": [saved]}
    attach([check])
    out = [v for v in release_gate.check_report({"checks": [check]}) if v["rule"] == "RG-7"]
    assert len(out) == 1 and out[0]["hard"] and "sayfa" not in out[0]["message"]
    assert "page type unknown; no content advice" in out[0]["message"]
