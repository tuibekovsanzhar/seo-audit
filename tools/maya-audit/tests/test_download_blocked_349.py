"""DECISIONS 349: naturesgarden.net 342a0b14's appendix and sector downloads came back as "xlsx.json" in Chrome.

The chain: Firecrawl read 146 pages (DECISIONS 348); Shopify recipe posts under /blogs/ carry a product widget (a price
and "ADD TO CART"), so STR-3 took them for product pages and gave product markup advice; the release gate refused the
advice because those pages, read only by the page reader, had page kind "unknown" (RG-7); and the appendix and sector
links, plain links, got the gate's 409 JSON instead of a file.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

from maya_audit import reassess_rules, release_gate
from maya_audit.checks.structure import annotate_page_types, evidence_page_kinds, product_template
from test_false_alarms import ROOT, TR, html, site
from test_m1_publication import HARD, finished, set_gate  # noqa: F401  (fixture)
from test_web_app import API, web  # noqa: F401  (fixture)


def widget(price: str) -> str:
    return html(f"<h1>Ürün</h1><p>{TR}</p><p>Fiyat: {price}</p><button>Sepete Ekle</button>")


def test_a_blog_post_with_a_product_widget_is_not_a_product_page():
    pages = {"/": html(f"<p>{TR}</p>"), "/blogs/tarifler/kurabiye": widget("$19.49")}
    pages.update({f"/urun-{c}": widget(f"{100 + i} TL") for i, c in enumerate("abc")})
    _, read = site(pages)
    products = product_template(read, ROOT + "/")["products"]
    assert {u.removeprefix(ROOT) for u in products} == {"/urun-a", "/urun-b", "/urun-c"}


def test_a_page_only_the_reader_read_takes_the_kind_its_finding_gave_it():
    url = "https://n.test/products/granola"
    finding = SimpleNamespace(scope={"urls": [url, "https://n.test/unread"]}, page_types=None,
                              evidence={"pages": [{"url": url, "page_kind": "product"}]})
    check = SimpleNamespace(check_id="STR-3", findings=[finding])
    annotate_page_types([check], SimpleNamespace(pages=[], start_url="https://n.test/", origin="https://n.test"))
    assert finding.page_types == {url: "product", "https://n.test/unread": "unknown"}
    assert evidence_page_kinds({"pages": [{"url": url, "page_kind": "article"}], "x": 3}) == {url: "article"}


def saved(rows: list[dict]) -> tuple[dict, dict]:
    f = {"id": "STR-3-a", "check_id": "STR-3", "rule_id": "str3.expected_type", "severity": "Info",
         "title": f"{len(rows)} page(s) lack the structured data type expected for their page kind",
         "scope": {"urls": [r["url"] for r in rows], "count": len(rows)}, "evidence": {"pages": rows},
         "page_types": {r["url"]: "unknown" for r in rows},
         "remediation": {"content": True, "page_types": ["article", "product"]}}
    return {"checks": [{"check_id": "STR-3", "status": "fail", "findings": [f]}]}, {"STR-3-a": [r["url"] for r in rows]}


def row(url: str, why: str = "one price of its own ($19.49) and a buy control (ADD TO CART)") -> dict:
    return {"url": url, "page_kind": "product", "classified_by": why, "expected_one_of": ["Product"]}


def test_a_saved_audit_leaves_out_blog_posts_taken_for_products_and_names_reader_pages():
    report, affected = saved([row("https://n.test/blogs/recipes/salad"), row("https://n.test/blogs/tips/snacks"),
                              row("https://n.test/products/granola")])
    changes: list[str] = []
    reassess_rules._decisions_349(report, affected, changes)
    [f] = report["checks"][0]["findings"]
    assert f["title"].startswith("1 page(s) lack") and [r["url"] for r in f["evidence"]["pages"]] == ["https://n.test/products/granola"]
    assert affected == {f["id"]: ["https://n.test/products/granola"]} and f["id"] != "STR-3-a"
    assert f["page_types"]["https://n.test/products/granola"] == "product"
    assert not [v for v in release_gate.run(report, affected).get("violations") or [] if v.get("rule") == "RG-7"]


def test_a_saved_finding_made_only_of_blog_posts_goes():
    report, affected = saved([row("https://n.test/blogs/recipes/salad")])
    changes: list[str] = []
    reassess_rules._decisions_349(report, affected, changes)
    assert report["checks"][0]["findings"] == [] and affected == {} and "DECISIONS 349" in changes[0]


def test_a_product_judged_by_its_markup_stays_even_in_a_blog_folder():
    report, affected = saved([row("https://n.test/blogs/shop/kit", why="Product markup with an Offer")])
    reassess_rules._decisions_349(report, affected, [])
    assert len(report["checks"][0]["findings"]) == 1


def test_a_blocked_appendix_and_sector_file_download_as_marked_drafts_not_json(finished):  # noqa: F811
    client, audit, path = finished
    set_gate(path, release_gate.BLOCKED, [HARD])
    for fmt in ("xlsx", "sector"):
        response = client.get(f"{API}/audits/{audit['id']}/downloads/{fmt}")
        assert response.status_code == 200, (fmt, response.text[:300])
        assert response.headers["content-type"].startswith("application/vnd.openxmlformats")
        assert response.content[:2] == b"PK"  # an xlsx (zip), never a JSON error
        assert response.headers["x-maya-release-gate"] == release_gate.BLOCKED
        assert response.headers["content-disposition"].endswith('-draft.xlsx"')
    # The client's report forms stay refused without draft=true (DECISIONS 280).
    assert client.get(f"{API}/audits/{audit['id']}/downloads/markdown").status_code == 409


def test_the_naturesgarden_shape_passes_the_gate_after_the_offline_step():
    rows = [row(f"https://n.test/blogs/recipes/r{i}") for i in range(26)]
    report, affected = saved(rows)
    assert [v["rule"] for v in release_gate.run(report, affected).get("violations") or [] if v.get("hard")] == ["RG-7"]
    reassess_rules._decisions_349(report, affected, [])
    assert release_gate.run(report, affected)["decision"] != release_gate.BLOCKED
    json.dumps(report)  # still a plain JSON report
