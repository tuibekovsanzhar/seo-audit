"""Stage 8a, borrowed from Screaming Frog (DECISIONS 315): every redirect hop per address; internal links to a redirect;
canonical chains; hreflang targets in the wrong language; images over 100 KB; one card for one redirect/canonical chain;
the issue type (Sorun / Kontrol edin / Fırsat) beside severity; problems per template. Fake sites and hand-made reports
only; nothing is requested."""
from __future__ import annotations

import json
from pathlib import Path

import httpx

from maya_audit import client_appendix, client_selection as cs
from maya_audit.audit import run_audit
from maya_audit.checks import stage8_rules as s8
from maya_audit.config import CrawlConfig
from maya_audit.models import to_jsonable
from maya_audit.report import build_report
from maya_audit.xlsx import read as read_xlsx
from test_deadline_hosted_hardening import QUIET
from test_v03_client_report import finding, page, report

ROOT = Path(__file__).resolve().parents[1]
SITE = "https://chain.test"
HTML = {"content-type": "text/html; charset=utf-8"}
TEXT = "<p>" + "Hastanemizde tedavi ve bakım hizmetleri her gün özenle sunulur. " * 12 + "</p>"


def _doc(title, body="", head="", lang="tr"):
    return (f'<!doctype html><html lang="{lang}"><head><title>{title}</title>{head}</head><body>'
            f'<nav><a href="/">Ana sayfa</a><a href="/eski">Eski</a></nav><main><h1>{title}</h1>{TEXT}{body}</main></body></html>')


def _site():
    """/eski -> 301 /ara -> 301 /yeni (a chain linked from every page); /a's canonical is /b, whose canonical is /c;
    /tr links /en with hreflang "en", but /en declares <html lang="de">."""
    pages = {
        "/": _doc("Ana", '<a href="/a">A</a><a href="/b">B</a><a href="/c">C</a><a href="/tr">TR</a><a href="/en">EN</a>'),
        "/yeni": _doc("Yeni"),
        "/a": _doc("A", head=f'<link rel="canonical" href="{SITE}/b">'),
        "/b": _doc("B", head=f'<link rel="canonical" href="{SITE}/c">'),
        "/c": _doc("C", head=f'<link rel="canonical" href="{SITE}/c">'),
        "/tr": _doc("TR", head=f'<link rel="alternate" hreflang="tr" href="{SITE}/tr"><link rel="alternate" hreflang="en" href="{SITE}/en">'),
        "/en": _doc("EN", lang="de", head=f'<link rel="alternate" hreflang="tr" href="{SITE}/tr"><link rel="alternate" hreflang="en" href="{SITE}/en">'),
    }
    moves = {"/eski": "/ara", "/ara": "/yeni"}

    def respond(request):
        path = request.url.path
        if path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        if path in moves:
            return httpx.Response(301, headers={"location": SITE + moves[path]})
        if path in pages:
            return httpx.Response(200, text=pages[path], headers=HTML)
        return httpx.Response(404, text="nope", headers=HTML)
    return respond


def _report():
    config = CrawlConfig(**{**QUIET, "max_pages": 20, "sitemap_check_max": 5, "business_type": "diger"})
    outcome = run_audit(SITE + "/", config, httpx.MockTransport(_site()))
    return json.loads(json.dumps(to_jsonable(build_report(outcome.result, outcome.gates, outcome.checks))))


def _by_rule(r):
    return {f.get("rule_id"): f for c in r["checks"] for f in c["findings"]}


# ---------------------------------------------------------------- 1, 4: redirects, canonical chains, hreflang

def test_every_redirect_hop_is_recorded_and_links_to_a_redirect_name_the_final_address():
    r = _report()
    record = next(x for x in r["crawl"]["redirects"] if x["url"] == SITE + "/eski")
    assert [(h["url"], h["status"], h["target"]) for h in record["hops"]] == [
        (SITE + "/eski", 301, SITE + "/ara"), (SITE + "/ara", 301, SITE + "/yeni")]
    assert record["final"] == SITE + "/yeni" and record["final_status"] == 200 and record["loop"] is False
    found = _by_rule(r)
    links = found["idx6.links_to_redirect"]
    target = next(t for t in links["evidence"]["targets"] if t["url"] == SITE + "/eski")
    assert target["final"] == SITE + "/yeni" and target["hops"] == [SITE + "/eski", SITE + "/ara", SITE + "/yeni"]
    assert links["severity"] == "S4" and links["title"].endswith("point to an address that redirects")
    assert "idx3.chain" in found  # 3 addresses (2 redirects): today's IDX-3 rule, kept (owner: A)


def test_a_canonical_of_a_canonical_and_an_hreflang_target_in_another_language_are_found():
    found = _by_rule(_report())
    chain = found["idx4.chain"]
    assert chain["evidence"]["pages"] == [{"url": SITE + "/a", "canonical": SITE + "/b", "canonical_of_canonical": SITE + "/c"}]
    assert chain["severity"] == "S3"
    wrong = found["str9.wrong_language"]
    assert {(row["page"], row["target"], row["target_lang"]) for row in wrong["evidence"]["links"]} >= {
        (SITE + "/tr", SITE + "/en", "de")}


def test_images_between_100_and_500_kb_are_an_opportunity_and_larger_ones_stay_in_str7_heavy():
    images = {"a": {"url": "https://x.test/a.jpg", "pages": ["https://x.test/"], "source": "fetched", "status": 200, "content_length": "150000"},
              "b": {"url": "https://x.test/b.jpg", "pages": ["https://x.test/p"], "source": "fetched", "status": 200, "content_length": "700000"},
              "c": {"url": "https://x.test/c.jpg", "pages": ["https://x.test/"], "source": "fetched", "status": 200, "content_length": "90000"},
              "d": {"url": "https://x.test/d.jpg", "pages": ["https://x.test/"], "source": "fetched", "status": 200}}
    made = s8.images_over_100kb({"images": images})
    assert len(made) == 1 and made[0].title == "1 sampled image file(s) are between 100 and 500 KB"
    assert [row["image"] for row in made[0].evidence["images"]] == ["https://x.test/a.jpg"]
    assert made[0].evidence["unknown_size"] == 1  # unknown is unknown, not small
    assert cs.rule_type("str7.over_100kb") == "opportunity"
    assert s8.images_over_100kb(None) == []


# ---------------------------------------------------------------- 1: one card for one chain (moodist's case)

def _moodist_findings():
    tr, en, home = "https://m.test/tr/", "https://m.test/en/", "https://m.test/"
    return [
        finding("IDX-4-loop", "idx4.redirect_loop", "S2", urls=[tr], check="IDX-4",
                evidence={"pages": [{"url": tr, "canonical": tr + "tr/", "resolved_via": [tr + "tr/", home, tr], "redirects_to": tr}]}),
        finding("IDX-4-redir", "idx4.redirecting", "S3", urls=[en], check="IDX-4",
                evidence={"pages": [{"url": en, "canonical": en + "en/", "resolved_via": [en + "en/", home, tr], "redirects_to": tr}]}),
        finding("IDX-3-chain", "idx3.chain", "S4", urls=[tr + "tr/"], check="IDX-3",
                evidence={"chains": [{"hops": [tr + "tr/", home, tr], "redirects": 2}]}),
        finding("IDX-6-links", "idx6.links_to_redirect", "S4", urls=[tr, en, "https://m.test/tr/a/"], check="IDX-6",
                evidence={"page_count": 50, "targets": [{"url": home, "final": tr, "hops": [home, tr], "linked_from": [tr, en]}]}),
        # Another site section's chain shares nothing with the one above: its own card.
        finding("IDX-3-other", "idx3.chain", "S4", urls=["https://m.test/old/"], check="IDX-3",
                evidence={"chains": [{"hops": ["https://m.test/old/", "https://m.test/older/", "https://m.test/new/"], "redirects": 2}]}),
        finding("STR-1-x", "str1.no_title", "S3", urls=[tr]),
    ]


def test_canonical_redirect_chain_and_links_into_it_are_one_card_and_an_unrelated_chain_stays_apart():
    sel = cs.select(report(_moodist_findings()))
    chain = sel["by_finding"]["IDX-4-loop"]
    assert chain["finding_ids"] == ["IDX-4-loop", "IDX-4-redir", "IDX-3-chain", "IDX-6-links"]
    assert chain["merge_group"] == "redirect_chain" and chain["severity"] == "S2" and chain["placement"] == "card"
    assert chain["chain"]["hops"] == ["https://m.test/tr/tr/", "https://m.test/", "https://m.test/tr/"]
    assert chain["chain"]["linking_pages"] == 50 and chain["chain"]["final"] == "https://m.test/tr/"
    assert [p["url"] for p in chain["chain"]["canonical_pages"]] == ["https://m.test/tr/", "https://m.test/en/"]
    assert sel["by_finding"]["IDX-3-other"]["finding_ids"] == ["IDX-3-other"]
    assert sel["by_finding"]["STR-1-x"]["finding_ids"] == ["STR-1-x"]
    # Links to a redirect alone are never merged into anything.
    alone = cs.select(report([_moodist_findings()[3]]))
    assert alone["by_finding"]["IDX-6-links"]["merge_group"] is None
    assert not any("_chain_cluster" in f for f in _moodist_findings())  # the report's own findings are not marked


# ---------------------------------------------------------------- 2: issue type

def test_every_rule_has_a_type_and_the_labels_are_turkish_and_english():
    rules = {k for v in json.loads((ROOT / "maya_audit" / "rule_ids.json").read_text(encoding="utf-8"))["rules"].values() for k, _ in v}
    types = json.loads((ROOT / "maya_audit" / "issue_types.json").read_text(encoding="utf-8"))
    assert rules == set(types["rules"]) and set(types["rules"].values()) == {"issue", "warning", "opportunity"}
    assert [cs.issue_type_label(k, "tr") for k in ("issue", "warning", "opportunity")] == ["Sorun", "Kontrol edin", "Fırsat"]
    assert [cs.issue_type_label(k, "en") for k in ("issue", "warning", "opportunity")] == ["Issue", "Warning", "Opportunity"]


def test_teyit_edin_is_kontrol_edin_until_checked_and_a_check_keeps_review_json_as_it_is(tmp_path):
    r = report([finding("A", "str1.no_title", "S3"), finding("B", "str7.formats", "S4"), finding("C", "str7.placeholder", "S4"),
                finding("D", "str1.shared", "S4", intent={"kind": "intent_marking"})])
    sel = cs.select(r)
    kinds = {fid: g["issue_type"] for fid, g in sel["by_finding"].items()}
    assert kinds["A"] == "issue" and kinds["B"] == "opportunity" and kinds["C"] == "warning"
    assert sel["by_finding"]["D"]["placement"] == "confirm" and kinds["D"] == "warning"
    confirmed = cs.select(r, confirmations={"D": {"result": "confirmed", "by": "Ayşe"}, "C": {"result": "confirmed", "by": "Ayşe"}})
    assert confirmed["by_finding"]["D"]["issue_type"] == "issue" and confirmed["by_finding"]["C"]["issue_type"] == "issue"
    # Order and placement are as before: the type is a label.
    assert [g["finding_ids"] for g in sel["cards"]] == [g["finding_ids"] for g in cs.select(r)["cards"]]


def test_the_type_is_on_the_cards_in_the_xlsx_and_in_the_web_results():
    sel = cs.select(report([finding("A", "str1.no_title", "S3"), finding("B", "str7.formats", "S4")]))
    sheets = read_xlsx(client_appendix.build(sel, "tr"))
    head = sheets["Bulgular"][0]
    assert "Sorun türü" in head
    col = head.index("Sorun türü")
    assert {row[0]: row[col] for row in sheets["Bulgular"][1:]} == {"A": "Sorun", "B": "Fırsat"}
    js = (ROOT / "maya_audit_web" / "static" / "app.js").read_text(encoding="utf-8")
    assert 'el("span", { class: "itype "' in js and "f.template_line" in js and "f.chain_line" in js
    from maya_audit_web.team_report.render import LABELS
    assert LABELS["tr"]["issue_types"] == {"issue": "Sorun", "warning": "Kontrol edin", "opportunity": "Fırsat"}


# ---------------------------------------------------------------- 3: templates

def _pages_with_templates():
    rows = [page("https://shop.test/", 100, "home", 1)]
    rows[0]["grouping"]["template_key"] = "/"
    for i in range(8):
        for lang in ("", "/en"):
            p = page(f"https://shop.test{lang}/collections/c/products/p{i}", 50, "product")
            p["grouping"]["template_key"] = f"{lang}/collections/*/products/*"
            rows.append(p)
    other = page("https://shop.test/pages/about", 40, "other")
    other["grouping"]["template_key"] = "/pages/*"
    return rows + [other]


def test_problems_per_template_join_language_versions_and_a_card_names_the_template_it_covers():
    pages = _pages_with_templates()
    products = [p["url"] for p in pages if "/products/" in p["url"]]
    r = report([finding("A", "str2.no_h1", "S4", urls=products), finding("B", "str1.no_title", "S3", urls=products[:3] + ["https://shop.test/pages/about"])],
               pages=pages)
    sel = cs.select(r)
    top = sel["templates"][0]
    assert top["template"] == "/collections/*/products/*" and top["pages"] == 16 and top["kind"] == "product"
    assert top["pages_with_problems"] == 16 and top["problem_groups"] == 2
    line = sel["by_finding"]["A"]["template_line"]
    assert line == {"template": "/collections/*/products/*", "kind": "product", "pages": 16}
    assert sel["by_finding"]["B"]["template_line"] is None  # 4 pages: under the minimum of 5
    sheets = read_xlsx(client_appendix.build(sel, "tr"))
    assert sheets["Şablonlar"][0][:3] == ["Şablon", "Tür", "Okunan sayfa"]
    assert sheets["Şablonlar"][1][:3] == ["/collections/*/products/*", "ürün", "16"]


def test_the_team_report_has_a_templates_page_and_the_chain_card_lines():
    from maya_audit_web.team_report.render import LABELS, page_templates
    L = LABELS["tr"]
    html = page_templates({"templates": [{"template": "/collections/*/products/*", "kind": "ürün şablonu", "pages": "323",
                                          "pages_with_problems": "323", "problem_groups": "3", "cards": "01, 06", "worst": "Orta"}]}, L)
    assert "/collections/*/products/*" in html and "ürün şablonu" in html and L["tpl_cols"][0] in html
    assert L["tpl_title"] == "Şablonlara göre sorunlar"
    assert L["template_line"].format(kind="ürün şablonu", tpl="/products/*", n="331") == "Tek şablon düzeltmesi: ürün şablonu (/products/*): 331 sayfa"
    assert L["chain_line"].format(hops="/tr/tr/ → / → /tr/") == "Zincir: /tr/tr/ → / → /tr/."


def test_a_product_inside_a_collection_is_a_product_in_the_shop_profile():
    """Stage 4's matcher (DECISIONS 315): on a tie the deeper address word names the page."""
    from maya_audit import business_types as bt
    shop = bt.profile("eticaret")
    nested = bt.page_facts("https://s.test/collections/elbise/products/kirmizi", {}, (), None)
    assert bt.classify(shop, nested)[0] == "product"
    assert bt.classify(shop, bt.page_facts("https://s.test/collections/elbise", {}, (), None))[0] == "category"
