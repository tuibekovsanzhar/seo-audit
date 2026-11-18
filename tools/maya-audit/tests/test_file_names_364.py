"""DECISIONS 364: image and file names with an unencoded space, an accent written as a combining mark, brackets or commas
(tseo1.file_name_unsafe, TSEO-1, S4, "Kontrol edin"). The MMI homepage banner "MMIBannerWebsite(Espolòn,Celebrate
DíadeMuertos,DayoftheDead)-01.jpg" (o + U+0300, i + U+0301, behind Next.js's /_next/image proxy) is the test case; the
rule is for every audit. Fake pages and saved-report fragments only."""
from __future__ import annotations

import json
from types import SimpleNamespace

from maya_audit import file_names as fn
from maya_audit.analysis import analyze_html

NAME = "MMIBannerWebsite(Espolo\u0300n,CelebrateDi\u0301adeMuertos,DayoftheDead)-01.jpg"  # as macOS keeps it
BANNER = ("/_next/image?url=https%3A%2F%2Fcdn.test%2Ffiles%2F6ae0%2FMMIBannerWebsite(Espolo%CC%80n%2CCelebrateDi%CC%81ade"
          "Muertos%2CDayoftheDead)-01.jpg&w=3840&q=75")
# a page record as a saved report keeps it
PAGE = {"discovered_via": "link", "depth": 0, "requested_at": "t", "user_agent": "Maya", "status": 200, "error": None,
        "elapsed_ms": 1, "content_type": "text/html", "body_bytes": 10, "body_truncated": False, "headers": {},
        "fetch_class": "ok", "classification_confidence": "verified", "classification_evidence": []}


def test_a_file_name_is_tested_as_written_and_an_image_proxy_on_its_file():
    assert fn.problems(BANNER) == [fn.COMBINING, fn.PUNCT]
    assert fn.file_name(BANNER) == NAME
    assert fn.marks(BANNER) == ["U+0300", "U+0301"]
    assert fn.problems("/docs/Fiyat Listesi.pdf") == [fn.SPACE]
    assert fn.problems("/docs/Fiyat%20Listesi.pdf") == []  # an encoded space is a valid address
    assert fn.problems("/img/a+b.jpg") == []  # a plus is not a space
    assert fn.problems("/img/Ünlü-çiçek.jpg") == []  # composed letters are fine
    assert fn.problems("/img/plain-name.webp?v=(1)") == []  # the query is not the file name
    assert fn.problems("data:image/png;base64,(x)") == [] and fn.problems("") == []
    assert fn.plain_name("BannerWebsite(Espolòn,Día)-01.jpg") == "banner-website-espolon-dia-01.jpg"
    assert fn.plain_name("İndirim Kampanyası.PNG") == "indirim-kampanyasi.png"


def test_srcset_is_read_as_browsers_read_it():
    assert fn.srcset_urls("/a.jpg 1x, /b(2).jpg 2x") == ["/a.jpg", "/b(2).jpg"]
    assert fn.srcset_urls("/a,b.jpg 640w,/c.jpg 1280w") == ["/a,b.jpg", "/c.jpg"]


def test_a_new_crawl_records_srcset_css_backgrounds_file_links_og_image_and_product_images():
    product = {"@type": "Product", "name": "Wine", "image": [{"@type": "ImageObject", "url": "https://s.test/p/Bottle Shot.png"}]}
    html = (f'<html><head><title>T</title><meta property="og:image" content="https://s.test/Blog(Guide)-01.jpg">'
            f'<script type="application/ld+json">{json.dumps(product)}</script>'
            '<style>.hero{background:url(/img/Hero(1).jpg)}</style></head><body><h1>x</h1>'
            f'<img src="{BANNER.replace("&", "&amp;")}" srcset="/ok.jpg 1x, /b(2).jpg 2x">'
            "<div style=\"background-image:url('/bg/Sale, Winter.jpg')\"></div>"
            '<a href="/docs/Price List.pdf">prices</a><img src="/fine-name.webp"></body></html>')
    found = {r["url"]: r for r in analyze_html(html, "https://s.test/")["file_names"]}
    assert found[BANNER]["where"] == ["img src"] and found[BANNER]["problems"] == [fn.COMBINING, fn.PUNCT]
    assert found["/b(2).jpg"]["where"] == ["srcset"]
    assert found["/img/Hero(1).jpg"]["where"] == ["css background"]  # an unquoted url() with brackets is read whole
    assert found["/bg/Sale, Winter.jpg"]["problems"] == [fn.SPACE, fn.PUNCT]
    assert found["/docs/Price List.pdf"]["where"] == ["file link"]
    assert found["https://s.test/Blog(Guide)-01.jpg"]["where"] == ["og:image"]
    assert found["https://s.test/p/Bottle Shot.png"]["where"] == ["Product image"]
    assert "/fine-name.webp" not in found and "/ok.jpg" not in found
    assert "file_names" not in analyze_html("<html><body><img src='/a.jpg'></body></html>")  # only when there are some


def test_the_rule_lists_each_file_once_with_a_plain_name_and_a_line_per_page():
    from maya_audit.checks.quick_rules import unsafe_file_names
    from maya_audit.client_selection import rule_type
    from maya_audit.rules import rule_id
    home, blog = "https://s.test/", "https://s.test/blog/guide"
    pages = [(home, {"images": [{"src": BANNER}, {"src": BANNER.replace("w=3840", "w=1920")}, {"src": "/ok.jpg"}]}),
             (blog, {"og": {"og:image": ["https://s.test/Blog(Guide)-01.jpg"]}, "images": [{"src": "/Blog(Guide)-01.jpg"}]})]
    sample = [{"url": "https://s.test/docs/Price%20List.pdf", "pages": [blog]}]
    found = unsafe_file_names(pages, sample, key_urls={home})
    assert len(found) == 1
    f = found[0]
    assert f.title == "2 image or file name(s) hold spaces, accents written as combining marks, brackets or commas"
    assert rule_id("TSEO-1", f.title) == "tseo1.file_name_unsafe" and rule_type("tseo1.file_name_unsafe") == "warning"
    assert f.severity.value == "S4" and f.importance_tier == 0
    files = {r["file"]: r for r in f.evidence["files"]}
    banner = files[NAME]  # the proxy's two sizes: one file
    assert banner["plain_name"] == "mmibanner-website-espolon-celebrate-diade-muertos-dayofthe-dead-01.jpg"
    assert banner["characters"] == ["U+0300", "U+0301"] and f.evidence["files"][0] is banner  # the worst name first
    assert sorted(files["Blog(Guide)-01.jpg"]["where"]) == ["img src", "og:image"]
    rows = {r["url"]: r["row"] for r in f.evidence["pages"]}
    assert rows[home]["tr"].startswith(f"dosya adı «{NAME}»") and "birleşik aksan işareti" in rows[home]["tr"]
    assert "önerilen ad: blog-guide-01.jpg" in rows[blog]["tr"]
    assert "Price" not in json.dumps(f.evidence)  # an encoded space is not a problem


def test_texts_and_registries_name_the_rule_and_it_is_never_a_template_fix():
    from maya_audit.checks.quick_rules import FILE_NAMES_EXPECTED, FILE_NAMES_FIX, FILE_NAMES_NOTE
    from maya_audit.client_selection import template_line
    from maya_audit.recommendation_catalog import note
    root = __import__("pathlib").Path(__file__).resolve().parents[1]
    tr = json.loads((root / "maya_audit_web/locales/findings/tr.json").read_text(encoding="utf-8"))
    assert tr["titles"]["tseo1.file_name_unsafe"].startswith("{n} görsel ya da dosya adında")
    assert FILE_NAMES_FIX in tr["fixes"] and FILE_NAMES_EXPECTED in tr["expected"] and FILE_NAMES_NOTE in tr["notes"]
    actions = json.loads((root / "maya_audit/rule_actions.json").read_text(encoding="utf-8"))
    action = (actions.get("actions") or actions)["tseo1.file_name_unsafe"]
    assert action["tr"] == "Görsel ve dosya adlarını düz, küçük harfli adlarla yükleyin"
    assert all(len(s) <= 75 for lang in ("tr", "en") for s in action["steps"][lang])
    items = json.loads((root / "maya_audit/checklist_items.json").read_text(encoding="utf-8"))
    seo141 = next(i for i in (items if isinstance(items, list) else items["items"]) if i["id"] == "SEO-141")
    assert seo141["rules"] == ["tseo1.file_name_unsafe"] and seo141["method"] == "partial"
    assert note("TSEO-1", "3 image or file name(s) hold spaces, accents written as combining marks, brackets or commas")["owner"] == "content"
    importance = {f"https://s.test/blog/{i}": {"template_key": "/blog/*"} for i in range(9)}
    group = {"urls": list(importance), "members": [{"rule_id": "tseo1.file_name_unsafe"}]}
    assert template_line(group, importance) is None  # each post's own upload: one template fix does not cover them
    assert template_line({**group, "members": [{"rule_id": "tseo1.no_viewport"}]}, importance)["pages"] == 9


def test_a_saved_audit_gets_the_finding_offline_with_the_product_images_of_its_saved_json_ld():
    from maya_audit import reassess_rules
    page = {**PAGE, "url": "https://s.test/product/wine",
            "analysis": {"images": [{"src": "/ok.jpg"}], "og": {}}}
    report = {"crawl": {"pages": [page], "structure": {"images": {BANNER: {"url": "https://s.test" + BANNER,
                                                                          "pages": ["https://s.test/"]}}}},
              "checks": [{"check_id": "TSEO-1", "status": "pass", "findings": [], "observations": []}]}
    product = json.dumps({"@type": "Product", "name": "Wine", "image": "https://s.test/p/Wine Bottle(70cl).png"})
    affected, changes = {}, []
    reassess_rules._decisions_364(report, affected, changes, {page["url"]: [product]})
    f = report["checks"][0]["findings"][0]
    assert f["rule_id"] == "tseo1.file_name_unsafe" and report["checks"][0]["status"] == "findings"
    assert {r["file"] for r in f["evidence"]["files"]} == {"Wine Bottle(70cl).png", NAME}
    assert sorted(affected[f["id"]]) == ["https://s.test/", page["url"]] and changes
    again: list[str] = []
    reassess_rules._decisions_364(report, affected, again, {page["url"]: [product]})
    assert again == [] and len(report["checks"][0]["findings"]) == 1  # run twice: one finding


def test_the_quick_rules_run_it_on_a_crawl():
    from maya_audit.checks.quick_rules import findings
    from maya_audit.models import page_from_record
    html = f'<html><head><title>T</title></head><body><h1>x</h1><img src="{BANNER.replace("&", "&amp;")}"></body></html>'
    page = page_from_record({**PAGE, "url": "https://s.test/",
                             "analysis": analyze_html(html, "https://s.test/")})
    result = SimpleNamespace(pages=[page], start_url="https://s.test/", origin="https://s.test", discovered_urls=[],
                             sitemap_urls=[], sitemap_docs=[], page_grouping=None, structure=None)
    made, _ = findings(result, check_ids={"TSEO-1"})
    assert [f.rule_id for f in made["TSEO-1"]] == ["tseo1.file_name_unsafe"]
