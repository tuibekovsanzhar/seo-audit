"""DECISIONS 337, from enpara 2e5829fb's card 2 (21 addresses, none linked from a page read: all sitemap entries, some
spelling the site's own headings). Hand-written cases; expected values come from the fake site's routes:

  LINKS     /hakkimizda links "Eski kampanya" to /eski (404) and "İkinci sekme" with href="sekme-2" (a tab id missing its
            #: the browser asks /sekme-2, a 404). The homepage has tab and accordion markup (href="#tab-1", data-href,
            data-target, onclick, javascript:, an empty href) that must never become a request or a finding.
  SITEMAP   /sitemap.xml lists /kredi-karti-aidati-yok! (the homepage's heading "Kredi kartı aidatı yok!", 404) and
            /kaldirilmis (404); no page links to either.

Offline: a loopback fake server; the saved-report case is a synthetic report shaped like enpara's.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from fakeserver import Response
from maya_audit import client_appendix, final, xlsx
from maya_audit.html_links import extract_link_edges, extract_links, mistyped_href
from maya_audit.link_places import places
from maya_audit.sitemap import file_map
from test_m1_broken_links import audit
from test_review_fixes import TR, page
from test_firecrawl import no_lookups  # noqa: F401  (fixture)

TABS = ('<h2>Kredi kartı aidatı yok!</h2><div class="tabs"><a href="#tab-1">Birinci sekme</a>'
        '<button data-target="#acc-1">Soru 1</button><div data-href="/veri-href">Kutu</div><a data-href="/a-data-href">x</a>'
        '<span onclick="location.href=\'/onclick-hedef\'">Tıkla</span><a href="javascript:void(0)">Aç</a><a href="">Boş</a>'
        '<a href="   ">Boşluk</a></div>')


def routes() -> dict:
    sitemap = ('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
               "<url><loc>{base}/</loc></url><url><loc>{base}/hakkimizda</loc></url>"
               "<url><loc>{base}/kredi-karti-aidati-yok!</loc></url><url><loc>{base}/kaldirilmis</loc></url></urlset>")
    return {
        "/robots.txt": Response(body="User-agent: *\nAllow: /\nSitemap: /sitemap.xml\n", content_type="text/plain"),
        "/sitemap.xml": Response(body=sitemap, content_type="application/xml"),
        "/": page(f"<h1>Ana sayfa</h1><p>{TR}</p>{TABS}<a href=\"/hakkimizda\">Hakkımızda</a>", nav=""),
        "/hakkimizda": page(f"<h1>Hakkımızda</h1><p>{TR}</p><a href=\"/eski\">Eski kampanya</a> "
                            "<a href=\"sekme-2\">İkinci sekme</a>", nav=""),
        "/eski": Response(404, "<html><title>Yok</title><body>Sayfa yok</body></html>"),
        "/sekme-2": Response(404, "<html><title>Yok</title><body>Sayfa yok</body></html>"),
        "/kredi-karti-aidati-yok!": Response(404, "<html><title>Yok</title><body>Sayfa yok</body></html>"),
        "/kaldirilmis": Response(404, "<html><title>Yok</title><body>Sayfa yok</body></html>"),
    }


@pytest.fixture(scope="module")
def site():
    outcome, base = audit(routes())  # the fake server fills {base} in the sitemap and robots.txt
    return SimpleNamespace(outcome=outcome, base=base, sealed=final.seal(outcome))


def idx1(report: dict) -> dict[str, dict]:
    return {f["rule_id"]: f for c in report["checks"] if c["check_id"] == "IDX-1" for f in c["findings"]
            if (f.get("rule_id") or "").startswith(("idx1.4xx", "idx1.href"))}


# ------------------------------------------------------------------ 1: only real navigable links are followed

def test_tab_accordion_data_and_script_values_are_never_links():
    links = extract_links(TABS + '<a href="/gercek">Gerçek</a><a href="sekme-2">x</a>', "https://site.test/sayfa")
    assert links == ["https://site.test/gercek", "https://site.test/sekme-2"]
    edges = {e["target"]: e for e in extract_link_edges('<nav><a href="/menu">Menü</a></nav><a href="sekme-2">x</a>', "https://site.test/a/")}
    assert edges["https://site.test/a/sekme-2"]["href"] == "sekme-2" and edges["https://site.test/menu"]["nav"]


@pytest.mark.parametrize("href, why", [("sekme-2", "no_slash"), ("kartlar/encard-genc", "no_slash"),
                                       ("Kredi kartı aidatı yok!", "spaces"), ("/kartlar/x", None), ("#tab-1", None),
                                       ("contact.html", None), ("../x", None), ("https://site.test/x", None), ("?p=2", None),
                                       ("mailto:a@b.test", None)])
def test_a_mistyped_href_is_text_or_a_value_missing_its_slash_or_hash(href, why):
    assert mistyped_href(href) == why


def test_the_crawl_never_asks_the_tab_data_or_script_values(site):
    asked = {r["url"].removeprefix(site.base) for r in site.sealed.report["crawl"]["requests"]}
    assert not asked & {"/veri-href", "/a-data-href", "/onclick-hedef", "/acc-1"}
    assert "/sekme-2" in asked  # a real <a href>, even mistyped, is followed: that is how it is found to fail


# ------------------------------------------------------------------ 2: one card per thing to fix

def test_links_mistyped_hrefs_and_sitemap_entries_are_three_findings(site):
    found = idx1(site.sealed.report)
    assert set(found) == {"idx1.4xx.referenced.linked", "idx1.href_mistyped", "idx1.4xx.sitemap_only"}
    linked = found["idx1.4xx.referenced.linked"]
    assert linked["scope"]["urls"] == [site.base + "/hakkimizda"] and linked["severity"] == "S2"
    mistyped = found["idx1.href_mistyped"]
    assert mistyped["title"] == "1 link(s) on 1 page(s) have a mistyped address (href) that ends at a client error (4xx)"
    assert mistyped["severity"] == "S4"  # not a key page and not the homepage
    assert [r["href"] for r in mistyped["evidence"]["link_sources"]] == ["sekme-2"]
    only = found["idx1.4xx.sitemap_only"]
    assert only["title"] == "2 sitemap address(es) end at a client error (4xx); no page read links to them"
    entries = {e["url"].removeprefix(site.base): e for e in only["evidence"]["sitemap_entries"]}
    assert entries["/kredi-karti-aidati-yok!"]["heading_match"]["heading"] == "Kredi kartı aidatı yok!"
    assert entries["/kredi-karti-aidati-yok!"]["suggested"] == "fix_generator"
    assert entries["/kaldirilmis"]["suggested"] == "remove_or_redirect" and entries["/kaldirilmis"]["heading_match"] is None
    assert {e["sitemap_file"] for e in entries.values()} == {site.base + "/sitemap.xml"}
    assert only["evidence"]["likely_cause"] == {"kind": "from_headings", "inference": True, "count": 1}
    assert any(n.startswith("Inference: 1 of these addresses") for n in only["notes"])


# ------------------------------------------------------------------ 3: where each one is

def test_every_row_says_where_the_link_is_and_what_to_do(site):
    rows = [r for rs in places(site.sealed.report).values() for r in rs]
    by = {(r["kind"], r["links_to"].removeprefix(site.base)): r for r in rows}
    link = by[("link", "/eski")]
    assert (link["source"], link["link_text"], link["href"], link["position"], link["status"], link["in_sitemap"],
            link["suggested"]) == (site.base + "/hakkimizda", "Eski kampanya", "/eski", "body", 404, False, "remove")
    assert by[("link", "/sekme-2")]["mistyped"] == "no_slash"
    entry = by[("sitemap", "/kaldirilmis")]
    assert entry["source"] is None and entry["sitemap_file"] == site.base + "/sitemap.xml" and entry["suggested"] == "remove_or_redirect"


def test_the_appendix_has_link_locations_and_the_quick_look_line(site):
    from maya_audit import client_selection
    sealed = site.sealed
    selection = client_selection.select(sealed.report, sealed.affected, {})
    book = xlsx.read(client_appendix.build(selection, "tr", sealed.affected, places=sealed.cards))
    how = [r[0] for r in book["Nasıl okunur"][1:]]
    assert "Bağlantılar Mac'in hızlı önizlemesinde çalışmaz; dosyayı Numbers, Excel veya Google Sheets ile açın." in how
    sheet = book["Bağlantı yerleri"]
    assert sheet[0][:13] == ["Kart", "Bozuk adres", "HTTP durumu", "Bağlantının bulunduğu sayfa", "Bağlantı metni",
                             "Yazılan değer (href)", "Konum", "Site haritasında mı?", "Site haritası dosyası",
                             "Site haritasındaki <loc> metni", "<loc> satırı", "Site haritası okuma zamanı", "Önerilen hedef"]
    rows = {(r[1], r[3]): r for r in sheet[1:]}
    eski = rows[(site.base + "/eski", site.base + "/hakkimizda")]
    assert eski[2:13] == ["404", site.base + "/hakkimizda", "Eski kampanya", "/eski", "gövde", "Hayır", "", "", "", "", "kaldırın"]
    sitemap = rows[(site.base + "/kredi-karti-aidati-yok!", "yalnızca site haritasında")]
    assert sitemap[7:11] == ["Evet", site.base + "/sitemap.xml", site.base + "/kredi-karti-aidati-yok!", "1"]  # DECISIONS 340
    assert sitemap[11].endswith(" TSİ)") and sitemap[12] == "site haritası oluşturucuyu düzeltin"
    assert sitemap[13].startswith("çıkarım:") and "Kredi kartı aidatı yok!" in sitemap[13]


def test_the_pdf_card_shows_three_rows_and_says_the_rest_is_in_the_appendix():
    from maya_audit_web.team_report.render import LABELS, link_table
    rows = [{"kind": "link", "source": f"https://s.test/p{i}", "links_to": "https://s.test/eski", "status": 404,
             "ends_at": "https://s.test/eski", "final_status": 404, "link_text": f"Bağlantı {i}", "position": "menu",
             "suggested": "remove"} for i in range(5)]
    html = link_table(rows, LABELS["tr"])
    assert html.count("<tr>") == 1 + 3 and "+2 satır daha (tam liste ekte: «Bağlantı yerleri»)" in html
    assert "/p0 (menü)" in html and "kaldırın" in html


# ------------------------------------------------------------------ a saved report (enpara's shape)

def _saved(base="https://www.bank.test"):
    def p(url, status, loc=None, headings=(), outlinks=()):
        return {"url": base + url, "discovered_via": "sitemap", "depth": None, "requested_at": "t", "user_agent": "u",
                "status": status, "error": None, "elapsed_ms": 1, "content_type": "text/html", "body_bytes": 10,
                "body_truncated": False, "headers": {}, "fetch_class": "ok", "classification_confidence": "verified",
                "classification_evidence": [], "redirect_location": base + loc if loc else None, "retried_after_429": False,
                "view": None, "content_checks_eligible": True, "links_found": 0,
                "analysis": {"headings": [{"level": 2, "text": h} for h in headings]}, "outlinks": list(outlinks),
                "external_links": []}
    sitemap = [base + "/", base + "/kartlar/genc", base + "/kartlar/genc/çocuğunuz-da-enparalı-oluyor--)",
               base + "/sirketim/", base + "/sirketim/aktif-kampanyalar"]
    pages = [p("/", 200, outlinks=[{"target": base + "/kartlar/genc", "anchor": "Genç", "links": 1, "empty": 0, "nav": True}]),
             p("/kartlar/genc", 200, headings=["Çocuğunuz da Enparalı oluyor :)"]),
             p("/kartlar/genc/%C3%A7ocu%C4%9Funuz-da-enparal%C4%B1-oluyor--)", 302, "/404?x=1"),
             p("/sirketim/aktif-kampanyalar", 302, "/404?x=2"), p("/404?x=1", 404), p("/404?x=2", 404)]
    sitemap[2] = pages[2]["url"]
    finding = {"check_id": "IDX-1", "title": "2 URL(s) return a client error (4xx), linked internally or listed in the sitemap",
               "severity": "S2", "confidence": "verified", "rationale": "Documented", "engines": [],
               "scope": {"kind": "template", "count": 2, "urls": [sitemap[2], sitemap[4]]},
               "evidence": {"pages": [{"url": base + "/404?x=1", "status": 404}, {"url": base + "/404?x=2", "status": 404}],
                            "target_urls": [base + "/404?x=1", base + "/404?x=2"], "target_count": 2, "link_sources": [],
                            "link_sources_count": 0, "sitemap_only": [sitemap[2], sitemap[4]]},
               "expected": "", "how_to_fix": "", "id": "IDX-1-old", "rule_id": "idx1.4xx.referenced", "notes": []}
    return {"checks": [{"check_id": "IDX-1", "findings": [finding]}],
            "crawl": {"origin": base, "start_url": base + "/", "config": {"key_pages": []}, "pages": pages, "sitemap_urls": sitemap,
                      "sitemap_docs": [{"url": base + "/sitemap.xml", "kind": "urlset", "urls_found": 3},
                                       {"url": base + "/sirketim/sitemap.xml", "kind": "urlset", "urls_found": 2}]}}


def test_a_saved_report_is_split_with_each_entry_s_file_and_heading():
    from maya_audit.reassess_rules import _decisions_337
    report, affected, changes = _saved(), {"IDX-1-old": ["x"]}, []
    _decisions_337(report, affected, changes)
    [f] = report["checks"][0]["findings"]
    assert f["rule_id"] == "idx1.4xx.sitemap_only" and f["severity"] == "S2" and "IDX-1-old" not in affected
    assert affected[f["id"]] == f["scope"]["urls"] and any("DECISIONS 337" in c for c in changes)
    entries = {e["url"].rsplit("/", 1)[-1]: e for e in f["evidence"]["sitemap_entries"]}
    young = entries["%C3%A7ocu%C4%9Funuz-da-enparal%C4%B1-oluyor--)"]
    assert young["heading_match"] == {"page": "https://www.bank.test/kartlar/genc", "heading": "Çocuğunuz da Enparalı oluyor :)", "level": 2}
    assert young["sitemap_file"] == "https://www.bank.test/sitemap.xml" and young["status"] == 404
    assert entries["aktif-kampanyalar"]["sitemap_file"] == "https://www.bank.test/sirketim/sitemap.xml"
    assert entries["aktif-kampanyalar"]["suggested"] == "remove_or_redirect"
    again = json.loads(json.dumps(report))
    _decisions_337(again, affected, [])
    assert again == report  # applied once


def test_the_sitemap_file_is_never_guessed_when_the_counts_do_not_add_up():
    docs = [{"url": "a.xml", "kind": "urlset", "urls_found": 2}, {"url": "b.xml", "kind": "urlset", "urls_found": 2}]
    assert file_map(docs, ["1", "2", "3"]) == {}  # an address listed twice: the order no longer says the file
    assert file_map(docs, ["1", "2", "3", "4"]) == {"1": "a.xml", "2": "a.xml", "3": "b.xml", "4": "b.xml"}
    new = [{"url": "a.xml", "kind": "urlset", "urls_found": 2, "new_urls": 2}, {"url": "b.xml", "kind": "urlset", "urls_found": 2, "new_urls": 1}]
    assert file_map(new, ["1", "2", "3"]) == {"1": "a.xml", "2": "a.xml", "3": "b.xml"}  # schema 1.32 records it


# ------------------------------------------------------------------ the web card's list

def test_the_web_card_list_shows_where_each_broken_link_is(web):  # noqa: F811
    from test_web_app import plan, start, get
    client = web()
    audit = start(client, plan(client))
    fixes = client.get(f"/api/v1/audits/{audit['id']}/overview?lang=tr").json()["fixes"]
    card = next(f for f in fixes if any(i.startswith("IDX-1") for i in f["finding_ids"]))
    data = client.get(f"/api/v1/audits/{audit['id']}/cards/{card['n']}/pages?lang=tr").json()
    assert data["where"]["title"] == "Bağlantı yerleri"
    assert data["where"]["columns"][:3] == ["Bozuk adres", "HTTP durumu", "Bağlantının bulunduğu sayfa"]
    first = data["where"]["rows"][0]
    assert first[0]["link"] and "/missing-" in first[0]["text"] and first[2]["link"]
    assert get(client, audit, "/summary")


from test_web_app import web  # noqa: E402,F401  (fixture)
