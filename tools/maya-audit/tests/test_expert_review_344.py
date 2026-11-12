"""DECISIONS 344: the SEO expert's review of the enpara Ek built from the DECISIONS 343 rules, as global rules.

One hand-written site, offline (a loopback fake server):
  every page closes its head early with <div id="overlay"> (one template cause); /iki-head writes </head> twice;
  /hesap/bilgiler and /hesap/bilgiler?sw=1 are one application step at two addresses (canonical or noindex, no 301);
  /odemeler/fatura has the section's H1 ("Ödemeler"); /yatirim/hisse has its own title as H1 (left out);
  the sitemap lists /odemeler/eski-fatura and /kampanya-yok, both 302 to /404?aspxerrorpath=..., which answers 404:
  the sitemap card takes them (a 301 target, or 410), the separate redirect card goes;
  /krediler links to /kredi/basvuru, a 302 to /kredi/hesaplama: an application step, a note.
"""
from __future__ import annotations

import json

import pytest

from fakeserver import Response
from maya_audit import client_selection, final, page_rows, reassess_rules
from test_review_fixes import TR
from test_firecrawl import no_lookups  # noqa: F401  (fixture)

LINKS = ["/odemeler", "/odemeler/fatura", "/yatirim", "/yatirim/hisse", "/hesap/bilgiler", "/hesap/bilgiler?sw=1",
         "/krediler", "/kredi/hesaplama", "/iki-head"]


def html(title: str, h1: str, words: str, head: str = "", body: str = "", extra_head_close: bool = False) -> Response:
    nav = " ".join(f'<a href="{p}">{p}</a>' for p in LINKS)
    second = "</head>" if extra_head_close else ""
    return Response(body=f'<!doctype html><html lang="tr"><head><title>{title}</title>{head}\n<div id="overlay"></div>'
                         f'<meta name="description" content="{title}"></head>{second}<body><header><nav>{nav}</nav></header>'
                         f'<main><h1>{h1}</h1><p>{words} {TR}</p>{body}</main></body></html>')


def routes(state: dict) -> dict:
    form = '<form action="/hesap/gonder"><input name="tc"></form>'
    return {
        "/robots.txt": Response(body="User-agent: *\nAllow: /\n", content_type="text/plain"),
        "/sitemap.xml": lambda site, req: Response(
            body='<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                 + "".join(f"<url><loc>{state['base']}{p}</loc></url>" for p in ("/", "/odemeler/eski-fatura", "/kampanya-yok"))
                 + "</urlset>", content_type="application/xml"),
        "/": html("Banka", "Banka", "Ana sayfa."),
        "/odemeler": html("Ödemeler | Banka", "Ödemeler", "Ödeme çeşitleri."),
        "/odemeler/fatura": html("Fatura Ödemeleri | Banka", "Ödemeler", "Fatura ödemek için."),
        "/yatirim": html("Yatırım | Banka", "Yatırım", "Yatırım ürünleri."),
        "/yatirim/hisse": html("Hisse Senedi | Banka", "Hisse Senedi", "Hisse almak için."),
        "/hesap/bilgiler": html("Kimlik bilgileriniz | Banka", "Kimlik bilgileriniz", "Başvuru adımı.", body=form),
        "/krediler": html("Krediler | Banka", "Krediler", "Kredi seçenekleri.", body='<a href="/kredi/basvuru">Başvur</a>'),
        "/kredi/basvuru": Response(302, "", headers={"Location": "/kredi/hesaplama"}),
        "/kredi/hesaplama": html("Kredi hesaplama | Banka", "Kredi hesaplama", "Hesaplayın."),
        "/iki-head": html("İki head | Banka", "İki head", "Bozuk şablon.", extra_head_close=True),
        "/odemeler/eski-fatura": Response(302, "", headers={"Location": "/404?aspxerrorpath=/odemeler/eski-fatura"}),
        "/kampanya-yok": Response(302, "", headers={"Location": "/404?aspxerrorpath=/kampanya-yok"}),
        "/404": Response(404, "<html><title>Bulunamadı</title><body>Sayfa yok</body></html>"),
    }


@pytest.fixture(scope="module")
def site():
    from dataclasses import replace
    from fakeserver import FakeServer, Site
    from maya_audit.audit import run_audit
    from maya_audit.config import CrawlConfig
    from test_deadline_hosted_hardening import QUIET
    state: dict = {}
    with FakeServer(Site(routes(state))) as fake:
        state["base"] = fake.base_url
        outcome = run_audit(fake.base_url + "/", replace(CrawlConfig(), **{**QUIET, "verification_enabled": True}))
    sealed = final.seal(outcome)
    found = {f["rule_id"]: f for c in sealed.report["checks"] for f in c["findings"]}
    return sealed, found, fake.base_url


def rows_of(sealed, rule: str, base: str) -> dict:
    sel = client_selection.select(sealed.report, sealed.affected, {})
    return {r["url"].removeprefix(base): r for r in page_rows.finding_rows(sel, sealed.affected, "tr") if r["rule_id"] == rule}


# ---------------------------------------------------------------- 1. the head card names the element and the place


def test_each_head_row_names_the_element_its_line_and_the_heads_in_the_source(site):
    sealed, _, base = site
    rows = {**rows_of(sealed, "tseo1.head_closed_later", base), **rows_of(sealed, "tseo1.head_closed_lost", base)}
    assert "Head'i kapatan öğe: <div#overlay>, ham HTML satır 2; ham HTML'de 1 <head>, 2 </head> (</head> satır 2, 2)" \
        in rows["/iki-head"]["value"]
    assert "ham HTML'de 1 <head>, 1 </head>" in rows["/odemeler"]["value"]
    assert rows["/odemeler"]["fix"].startswith("<div#overlay> öğesini (head içinde, ham HTML satır 2) gövdeye taşıyın")


# ---------------------------------------------------------------- 2. sub-pages: one site-wide card


def test_a_sub_page_with_the_sections_h1_is_on_the_card_one_with_its_own_title_as_h1_is_not(site):
    _, found, base = site
    f = found["str1.sections_as_pages"]
    rows = {r["url"].removeprefix(base): r for r in f["evidence"]["pages"]}
    assert set(rows) == {"/odemeler/fatura"} and rows["/odemeler/fatura"]["parent"] == base + "/odemeler"
    assert f["rule_id"] == "str1.sections_as_pages" and "str2.h1_parent_name" not in found


def test_the_card_is_a_decision_to_check(site):
    sealed, _, _ = site
    sel = client_selection.select(sealed.report, sealed.affected, {})
    [g] = [g for g in sel["groups"] if g["rule_id"] == "str1.sections_as_pages"]
    assert g["issue_type"] == "warning"  # "Kontrol edin"


# ---------------------------------------------------------------- 3. a form step is never told to 301


def test_the_second_address_of_an_application_step_gets_canonical_or_noindex(site):
    sealed, found, base = site
    assert "idx8.self_canonical_copies" not in found
    rows = rows_of(sealed, "idx8.form_step_copies", base)
    assert rows["/hesap/bilgiler?sw=1"]["fix"] == ("Kanonik etiketini /hesap/bilgiler adresine verin ya da noindex ekleyin; "
                                                    "301 vermeyin (adım çalışmayı bırakır).")
    assert "301 ile yönlendirin" not in " ".join(r["fix"] for r in rows.values())


# ---------------------------------------------------------------- 4. the sitemap card takes the redirects to an error page


def test_the_sitemap_card_gives_each_address_its_chain_and_a_301_target_or_410(site):
    sealed, found, base = site
    f = found["idx1.4xx.sitemap_only"]
    assert f["evidence"]["redirects_to_error_page"] == 2
    rows = rows_of(sealed, "idx1.4xx.sitemap_only", base)
    fatura = rows["/odemeler/eski-fatura"]
    # DECISIONS 345: the direct parent first (a page in the same folder only when it shares most words)
    assert fatura["value"] == "302 → /404?aspxerrorpath=/odemeler/eski-fatura → 404; önerilen 301 hedefi: /odemeler (üst klasör sayfası)"
    assert fatura["fix"] == "Site haritasından çıkarın ve bu adresi /odemeler adresine 301 ile yönlendirin."
    assert rows["/kampanya-yok"]["value"].endswith("ilgili bir sayfa yok: 410")
    # the same addresses are not a second card
    assert "idx1.error_redirect" not in found


def test_the_redirect_card_keeps_an_address_no_other_card_lists():
    from types import SimpleNamespace
    from maya_audit.checks import team_rules
    probe = {"sent": True, "url": "https://b.test/maya-no-such", "status": 302, "redirect_location": "https://b.test/404?aspxerrorpath=/x"}
    [made] = team_rules.error_redirects([], [{"url": "https://b.test/eski", "hops": [{"url": "https://b.test/eski", "status": 302,
                                              "target": "https://b.test/404?aspxerrorpath=/eski"}],
                                              "final": "https://b.test/404?aspxerrorpath=/eski", "final_status": 404}], probe)
    sitemap = {"check_id": "IDX-1", "rule_id": "idx1.4xx.sitemap_only", "evidence": {"sitemap_entries": [{"url": "https://b.test/eski"}]}}
    check = {"check_id": "IDX-1", "findings": [sitemap, made]}
    team_rules.settle([check], SimpleNamespace(pages=[], redirects=[]))
    [left] = [f for f in check["findings"] if getattr(f, "rule_id", None) == "idx1.error_redirect"]
    assert [r["url"] for r in left.evidence["pages"]] == ["https://b.test/maya-no-such"]
    assert left.title.startswith("1 missing address(es)")


# ---------------------------------------------------------------- 5. an application step's redirect is a note


def test_a_link_to_an_application_step_that_redirects_is_a_note_with_the_chain_and_how_to_check(site):
    sealed, found, base = site
    f = found["idx6.links_to_flow_redirect"]
    assert f["severity"] == "Info" and "idx6.links_to_redirect" not in found
    rows = rows_of(sealed, "idx6.links_to_flow_redirect", base)
    said = rows["/krediler"]["value"]
    assert f"{base}/kredi/basvuru: 302 → {base}/kredi/hesaplama → 200" in said
    assert "Preserve log" in said and "httpstatus.io" in said


# ---------------------------------------------------------------- saved reports


def test_a_saved_report_with_the_old_rules_gets_the_new_ones(site):
    sealed, found, _ = site
    old = json.loads(json.dumps(sealed.report))
    renamed = {"str1.sections_as_pages": "str1.subpage_copies_parent", "idx6.links_to_flow_redirect": "idx6.links_to_redirect"}
    for c in old["checks"]:
        for f in c["findings"]:
            if f.get("rule_id") in renamed:
                f["rule_id"] = renamed[f["rule_id"]]
            if f.get("rule_id") == "idx1.4xx.sitemap_only":
                f["evidence"].pop("suggestions", None)
                f["evidence"].pop("suggestion_rule", None)
    new, changes = reassess_rules.saved_data(old, dict(sealed.affected))
    rules = {f["rule_id"] for c in new["checks"] for f in c["findings"]}
    assert {"str1.sections_as_pages", "idx6.links_to_flow_redirect", "idx8.form_step_copies"} <= rules
    assert "str1.subpage_copies_parent" not in rules and "idx6.links_to_redirect" not in rules
    [sm] = [f for c in new["checks"] for f in c["findings"] if f["rule_id"] == "idx1.4xx.sitemap_only"]
    assert len(sm["evidence"]["suggestions"]) == 2


def test_the_review_is_kept_as_accuracy_data():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    review = json.loads((root / "docs" / "expert-reviews" / "enpara-fee70191-review3.json").read_text(encoding="utf-8"))
    assert review["review"] == 3 and len(review["cards"]) == 15
    assert sum(review["summary"].values()) == 15 and review["summary"]["correct"] == 9
    import subprocess
    import sys
    out = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, 'scripts'); import expert_accuracy; "
                          "print(expert_accuracy.table())"], cwd=root, capture_output=True, text=True, check=True).stdout
    assert out.strip() == (root / "docs" / "expert-reviews" / "ACCURACY.md").read_text(encoding="utf-8").strip()
