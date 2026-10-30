"""The brand name and the launch-gate label (Round 1, run 4: DECISIONS 201 and 203; docs/FALSE-ALARMS.md FA-022).

- The brand is the name the person typed or saved, else the site's own name, else the address split into the site's own
  words, else none; with none, the keyword panels are not sorted into brand searches and other searches at all. The plan
  passes a brand only when it was confirmed, so the Business Profile is not looked up under a guessed name.
- A finding of a rule not yet validated on real sites carries its launch-gate items and is labelled "Unverified check"
  on the web card, in the printed report and in the Markdown, in English and Turkish; a row set to "off" leaves the
  finding out and says so; the table cannot drift from docs/LAUNCH-GATE.md.

Every site is made up and held in memory (an in-memory transport, the web app's test sites, a mock DataForSEO). Each
rule has its healthy case beside it.
"""
import json
import re
import socket
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

pytest.importorskip("fastapi")

from maya_audit import brand, launch_gate  # noqa: E402
from maya_audit.dataforseo import DataForSEOClient, Ledger, insights, panel, pricing  # noqa: E402
from maya_audit.dataforseo.cache import CACHE_NAME, Cache  # noqa: E402
from maya_audit.dataforseo.credentials import Credentials  # noqa: E402
from maya_audit.dataforseo.ledger import LEDGER_NAME  # noqa: E402
from maya_audit.report import build_report, render_markdown, render_text  # noqa: E402
from maya_audit_web import paid, pdf, strings, summary, wording  # noqa: E402
from test_false_alarms import HTML_TYPE, TR, audited  # noqa: E402
from test_web_app import plan, web  # noqa: E402,F401

DOCS = Path(__file__).resolve().parent.parent / "docs"
STATIC = Path(__file__).resolve().parent.parent / "maya_audit_web" / "static"


@pytest.fixture
def no_lookups(monkeypatch):
    """Made-up names (.test, .example) never reach a resolver: the TLS probe records 'not checked' and moves on."""
    real = socket.getaddrinfo

    def lookup(host, *args, **kwargs):
        if str(host).endswith((".test", ".example")):
            raise socket.gaierror(socket.EAI_NONAME, "not known")
        return real(host, *args, **kwargs)
    monkeypatch.setattr(socket, "getaddrinfo", lookup)


def page(title, body="", *, lang="tr", head="", text=TR):
    return httpx.Response(200, headers=HTML_TYPE, text=f'<!doctype html><html lang="{lang}"><head><title>{title}</title>{head}</head><body>'
                                                       f'<header><nav><a href="/">Ana Sayfa</a></nav></header><main><h1>{title}</h1>'
                                                       f'<p>{text}</p>{body}</main></body></html>')


def shown(outcome, language="en", **report_options):
    report = json.loads(json.dumps(build_report(outcome.result, outcome.gates, outcome.checks, **report_options), default=str))
    strings.set_language(language)
    try:
        view = summary.build(report, outcome="COMPLETED", reason="as saved")
        rows = summary.search(report, limit=100)["items"]
        printed = pdf.render_html(view, rows=rows, plan=summary.action_plan(report), generated_at="2026-10-14T00:00:00+00:00")
    finally:
        strings.set_language("en")
    return report, view, rows, printed


# -- #13: the brand ------------------------------------------------------------------------------------------------------
LEZZETLI = "https://lezzetliyemekevi.example"
SITE_NAME = '<meta property="og:site_name" content="Lezzetli Yemek Evi">'


def recipe_site():
    """30 pages, each with og:site_name "Lezzetli Yemek Evi"; the address is the name glued into one word."""
    links = "".join(f'<a href="/tarif-{n}">Tarif {n}</a>' for n in range(1, 30))
    routes = {"/": page("Lezzetli Yemek Evi", f"<h2>Yemek tarifleri</h2>{links}", head=SITE_NAME)}
    routes.update({f"/tarif-{n}": page(f"Tarif {n}", "<h2>Yemek tarifleri ve ev yemekleri</h2>", head=SITE_NAME) for n in range(1, 30)})
    return routes


def ranked(*words):
    """A mock DataForSEO answering the ranked-keywords request with `words` (keyword, searches, position)."""
    def answer(request):
        items = [{"keyword_data": {"keyword": w, "keyword_info": {"search_volume": n}},
                  "ranked_serp_element": {"serp_item": {"rank_group": p, "url": "https://site.example/"}}} for w, n, p in words]
        result = {"total_count": len(items), "items": items}
        return httpx.Response(200, json={"status_code": 20000, "tasks": [{"status_code": 20000, "cost": 0.01, "result": [result]}]})
    return httpx.MockTransport(answer)


def keyword_section(tmp_path, url, *words):
    calls = [c for c in insights.audit_plan(url, country="Türkiye") if c.check_id == "DFS-4"]
    client = DataForSEOClient(Credentials("acct-7f3e", "pw-91c2"), Ledger(tmp_path / LEDGER_NAME), Cache(tmp_path / CACHE_NAME),
                              daily_budget=5.0, approved_usd=5.0, approved_always_ask=True, transport=ranked(*words))
    try:
        return panel.run_checks(calls, client)
    finally:
        client.close()


def table(section, check_id="DFS-4"):
    return next(c for c in section["checks"] if c["check_id"] == check_id)


# -- FA-022: the brand was the glued address label, a word no keyword contains (DECISIONS 201) ---------------------------
def test_the_sites_own_name_is_the_brand_when_the_address_is_one_glued_word(no_lookups, tmp_path):
    outcome = audited(recipe_site(), start=LEZZETLI + "/", sitemap=("/",), max_pages=40)
    pages = [p for p in outcome.result.pages if p.analysis]
    assert len(pages) == 30
    found = brand.resolve(outcome.result)
    assert found == {"name": "Lezzetli Yemek Evi", "source": "site", "confirmed": False, "found_in": "og_site_name", "pages": 30}
    # What the address alone gave before: one glued word, which no search contains.
    assert insights.brand_words(None, "lezzetliyemekevi.example") == {"lezzetliyemekevi"}
    section = keyword_section(tmp_path, LEZZETLI + "/", ("lezzetli yemek evi", 900, 1), ("yemek tarifleri", 5000, 8),
                              ("lezzetliyemekevi", 300, 1), ("ev yemekleri", 2000, 12), ("ucuz uçak bileti", 700, 30))
    insights.apply_relevance(section, brand=None, domain="lezzetliyemekevi.example", texts=insights.page_texts(pages), brand_info=found)
    data = table(section)["evidence"]["data"]
    kept = {row[0]: row[-1] for row in data["table"]["rows"]}
    assert data["table"]["columns"][-1] == "Relevance"
    assert kept["lezzetli yemek evi"] == "branded" and kept["lezzetliyemekevi"] == "branded"
    # This provider fixture ranks every query on an unassessed, different host. Site vocabulary is provisional.
    assert 'yemek tarifleri' not in kept and 'yemek tarifleri' in [row[0] for row in data['ambiguous']['rows']]
    assert kept.get("ev yemekleri") != "branded" and not data["unrelated"]["rows"]
    assert next(a for a in data['keyword_assessments'] if a['keyword']=='ucuz uçak bileti')['uncertain']
    assert section["relevance"]["brand_source"] == "site" and section["relevance"]["brand_confirmed"] is False
    assert data["relevance"]["brand_source"] == "site" and section["relevance"]["sorted"] is True
    # The cover shows the site's own name and says where it was read, in both languages; the report keeps the source.
    report, view, _rows, printed = shown(outcome, brand=found)
    assert report["brand"] == found and view["brand"]["name"] == "Lezzetli Yemek Evi" and not view["brand"]["confirmed"]
    assert view["brand"]["label"] == "Name read from the site's own pages (og:site_name); not confirmed by you."
    assert '<h1 class="wrap">Lezzetli Yemek Evi</h1>' in printed and "lezzetliyemekevi.example</h1>" not in printed
    _, turkish, _, _ = shown(outcome, "tr", brand=found)
    assert turkish["brand"]["label"] == "Ad, sitenin kendi sayfalarından okundu (og:site_name); sizin tarafınızdan onaylanmadı."
    # Without a crawl record, a label that is the site's own words is split into them.
    assert brand.from_texts(None, "lezzetliyemekevi.example", ["Lezzetli tarifler", "Yemek evi"])["name"] == "Lezzetli Yemek Evi"


def test_with_no_site_name_and_an_address_that_cannot_be_split_the_keywords_are_not_sorted(no_lookups, tmp_path):
    routes = {"/": page("Kahve", '<a href="/cay">Çay</a>'), "/cay": page("Çay")}
    outcome = audited(routes, start="https://xqzvbk.example/", sitemap=("/", "/cay"))
    found = brand.resolve(outcome.result)
    assert found == brand.none() and found["name"] is None
    section = keyword_section(tmp_path, "https://xqzvbk.example/", ("kahve", 900, 3), ("ucuz uçak bileti", 700, 30))
    before = [list(row) for row in table(section)["evidence"]["data"]["table"]["rows"]]
    insights.apply_relevance(section, brand=None, domain="xqzvbk.example", texts=["Kahve", "Çay"], brand_info=found)
    check = table(section)
    data = check["evidence"]["data"]
    assert "Relevance" not in data["table"]["columns"] and data["table"]["rows"] == before and "unrelated" not in data
    assert check["summary"].endswith(insights.NOT_SORTED)
    assert insights.NOT_SORTED == ("The brand name could not be confirmed, so these keywords are not sorted into brand searches and "
                                   "other searches.")
    assert section["relevance"] == {**section["relevance"], "sorted": False, "brand_source": None, "brand_confirmed": False}
    # Said again, nothing more is added.
    again = json.dumps(section, sort_keys=True)
    insights.apply_relevance(section, brand=None, domain="xqzvbk.example", texts=[], brand_info=found)
    assert json.dumps(section, sort_keys=True) == again
    turkish, ok = wording.line(check["summary"], "tr")
    assert ok and turkish.endswith("Marka adı doğrulanamadı; bu nedenle bu anahtar kelimeler marka aramaları ve diğer aramalar olarak ayrılmadı.")
    # The cover shows the address, labelled as that.
    report, view, _rows, _printed = shown(outcome)
    assert report["brand"]["source"] is None and view["brand"] == {"name": "xqzvbk.example", "confirmed": False,
                                                                   "label": strings.t("result.brand.from_domain"), "country": None}


def test_the_plan_passes_a_brand_only_when_it_was_confirmed_so_the_business_profile_needs_a_typed_name(web):
    client = web()
    made = plan(client, search_data=True, local_business=True, market_default_accepted=True)
    # The card still suggests a name from the address, and says it is a suggestion; the run is not given it.
    assert made["business"]["brand_name"] == "Demo Shop" and made["business"]["brand_confirmed"] is False
    assert made["paid_options"]["brand"] is None and made["paid_options"]["local_business"] is True
    real = paid.PaidServices(credentials=lambda: None, stores=lambda: (None, None))  # the real plan of calls; nothing is sent
    public = "https://demo-shop.example/"  # a public-looking name: the local test host would be refused for another reason
    profile = next(c for c in real.search_plan(public, made["paid_options"]) if c.check_id == "DFS-12")
    assert profile.not_sent == "the plan names no brand, so there is no business to look up. No request was sent."
    # Typed on the card: the name is the run's, and the Business Profile is looked up under it. (The suggestion itself,
    # "Demo Shop", posted back unchanged is not a typed name since DECISIONS 220: tests/test_preview16_false_alarms.py.)
    typed = plan(client, search_data=True, local_business=True, market_default_accepted=True, brand_name="Demo Shop Ltd")
    assert typed["paid_options"]["brand"] == "Demo Shop Ltd" and typed["business"]["brand_confirmed"] is True
    profile = next(c for c in real.search_plan(public, typed["paid_options"]) if c.check_id == "DFS-12")
    assert profile.not_sent is None and profile.payload[0]["keyword"] == "Demo Shop Ltd"


def test_a_typed_brand_classifies_as_before(no_lookups, tmp_path):
    outcome = audited(recipe_site(), start=LEZZETLI + "/", sitemap=("/",), max_pages=40)
    typed = brand.resolve(outcome.result, "Demo Shop")
    assert typed == {"name": "Demo Shop", "source": "typed", "confirmed": True, "found_in": None, "pages": None}
    section = keyword_section(tmp_path, "https://demo-shop.example/", ("demo shop", 5400, 1), ("demo shop login", 300, 1),
                              ("kettle reviews", 2400, 6), ("ucuz uçak bileti", 700, 30))
    insights.apply_relevance(section, brand="Demo Shop", domain="demo-shop.example", texts=["Kettle reviews and teapots"])
    data = table(section)["evidence"]["data"]
    kept = {row[0]: row[-1] for row in data["table"]["rows"]}
    assert kept == {"demo shop": "branded", "demo shop login": "branded"}
    assert {row[0] for row in data['ambiguous']['rows']}=={'kettle reviews','ucuz uçak bileti'}
    assert not data["unrelated"]["rows"]
    assert section["relevance"]["brand_source"] == "typed" and section["relevance"]["brand_confirmed"] is True
    # A confirmed name is shown on the cover without a label.
    report, view, _rows, _printed = shown(outcome, brand=typed)
    assert view["brand"] == {"name": "Demo Shop", "confirmed": True, "label": None, "country": None}


# -- D: the launch-gate label ----------------------------------------------------------------------------------------------
NOTE = "This check has not yet been validated on real sites (LG-16, LG-23). Confirm the finding by hand before acting on it."
TURKISH_NOTE = "Bu kontrol henüz gerçek sitelerde doğrulanmadı (LG-16, LG-23). Harekete geçmeden önce bulguyu elle doğrulayın."


def mismatch_site():
    """A page that says it is English and is written in Turkish (STR-9), and a link to a page that is gone (IDX-6)."""
    return {"/": page("Ana Sayfa | Demo Kafe", '<a href="/hakkimizda">Hakkımızda</a><a href="/kayip">Eski</a>'),
            "/hakkimizda": page("Hakkımızda | Demo Kafe", lang="en", text=TR * 4)}  # 150 main words (DECISIONS 224)


def test_an_unverified_finding_is_labelled_on_the_card_in_print_and_in_the_markdown_in_both_languages(no_lookups):
    outcome = audited(mismatch_site(), sitemap=("/", "/hakkimizda"))
    [mismatch] = [f for f in outcome.by_id["STR-9"].findings if "does not match the content language" in f.title]
    assert mismatch.launch_gated == ["LG-16", "LG-23"]
    report, view, rows, printed = shown(outcome)
    row = next(r for r in rows if r["id"] == mismatch.id)
    assert row["unverified"] == {"label": "Unverified check", "note": NOTE, "items": ["LG-16", "LG-23"]}
    assert f'<b>Unverified check</b>. {NOTE}' in printed
    markdown = render_markdown(outcome.result, outcome.gates, outcome.checks)
    # The Markdown names the items on the card; the sentence is said once, above the cards (review item 8).
    assert "**Unverified check (LG-16, LG-23)**" in markdown and "not yet validated on real sites" in markdown
    assert "LAUNCH-GATED: LG-16 | LG-23" in render_text(outcome.result, outcome.gates, outcome.checks)  # as before
    _, _, turkish_rows, turkish_printed = shown(outcome, "tr")
    turkish = next(r for r in turkish_rows if r["id"] == mismatch.id)
    assert turkish["unverified"] == {"label": "Doğrulanmamış kontrol", "note": TURKISH_NOTE, "items": ["LG-16", "LG-23"]}
    assert f"<b>Doğrulanmamış kontrol</b>. {TURKISH_NOTE}" in turkish_printed and "Unverified check" not in turkish_printed
    # The saved report holds the items; the web card builds the chip as page elements, never from markup.
    saved = next(f for c in report["checks"] for f in c["findings"] if f["id"] == mismatch.id)
    assert saved["launch_gated"] == ["LG-16", "LG-23"]
    script = (STATIC / "app.js").read_text(encoding="utf-8")
    assert 'el("span", { class: "state-chip unverified", text: row.unverified.label })' in script

    # Healthy: a link to a page that is gone is a Verified finding of a validated rule, and has no label anywhere.
    # (IDX-6's per-target finding is said under IDX-1's 4xx finding when IDX-1 reports the same URL: review H10.)
    [broken] = [f for f in outcome.by_id["IDX-1"].findings if "client error (4xx)" in f.title and "; linked from " in f.title]
    assert broken.launch_gated == [] and next(r for r in rows if r["id"] == broken.id)["unverified"] is None
    # The last mention is the finding's own card: the summary and the First 10 table name it earlier (W4a).
    section = markdown.split(f"[{broken.severity.value}] {broken.title}")[-1].split("### ")[0]
    assert "Unverified check" not in section


def test_a_row_set_to_off_leaves_the_finding_out_and_says_so(no_lookups):
    outcome = audited(mismatch_site(), sitemap=("/", "/hakkimizda"))
    check = outcome.by_id["STR-9"]
    titles = [f.title for f in check.findings if "does not match the content language" in f.title]
    others = [f.title for f in check.findings if f.title not in titles]
    off = (launch_gate.Row("STR-9", r"does not match the content language", ("LG-16",), mode=launch_gate.OFF),)
    launch_gate.apply(outcome.checks, off)
    assert [f.title for f in check.findings] == others and check.evidence[launch_gate.MARK] == titles
    assert check.summary.endswith("1 finding(s) from an unverified check were left out.")
    assert check.status != "findings" or others
    once = (check.summary, list(check.evidence[launch_gate.MARK]))
    launch_gate.apply(outcome.checks, off)  # nothing twice
    assert (check.summary, check.evidence[launch_gate.MARK]) == once
    turkish, ok = wording.line("1 finding(s) from an unverified check were left out.", "tr")
    assert ok and turkish == "Doğrulanmamış bir kontrolün 1 bulgusu dışarıda bırakıldı."
    assert launch_gate.MODES == ("label", "off") and all(row.mode == launch_gate.LABEL for row in launch_gate.LABELS)


def test_every_problem_one_shared_element_causes_is_labelled_whatever_its_title():
    def made(title, shared):
        return SimpleNamespace(title=title, evidence={"shared_element": {"type": "link"}} if shared else {})
    for title in ("Shared header/footer: link to /x has no text (on 9 page(s))", "“div.related” block: 2 link(s) have no text (on 4 page(s) of /blog/)",
                  "Repeated block: image /a.png has no alt text (on 5 page(s))"):
        assert launch_gate.items_of("STR-14", made(title, True)) == (["LG-61"], "label")
    # Matched on the element, not on the words: a page's own finding is not labelled LG-61.
    assert launch_gate.items_of("STR-14", made("3 link(s) on 2 page(s) have no text at all", False)) == ([], None)


def _launch_gate_items():
    """{LG item: (status, check ids named)} from docs/LAUNCH-GATE.md. A row with no status cell takes its section's
    "Status: all ..." line."""
    text = (DOCS / "LAUNCH-GATE.md").read_text(encoding="utf-8")
    found = {}
    for section in re.split(r"^## ", text, flags=re.MULTILINE):
        whole = re.search(r"^Status: all \*\*([A-Z ]+)\*\*", section, flags=re.MULTILINE)
        for line in section.splitlines():
            row = re.match(r"^\| \*\*(LG-\d+)\*\* \|(.*)\|\s*$", line)
            if not row:
                continue
            last = row.group(2).split("|")[-1]
            status = re.search(r"OPEN|VERIFIED|CLOSED|BY DESIGN|PARTLY DONE|ACCEPTED LIMIT|PENDING OWNER DECISION", last.upper())
            status = status.group(0) if status else (whole.group(1) if whole else None)
            found[row.group(1)] = (status, set(re.findall(r"\b(?:ACC|IDX|RND|STR|PRF|INT|ANS|DFS|TSEO)-\d+\b", line)))
    return found


def test_the_launch_gate_table_cannot_drift_from_the_document():
    items = _launch_gate_items()
    assert all(status for status, _ in items.values()), [item for item, (status, _) in items.items() if not status]
    labelled = {item for row in launch_gate.LABELS for item in row.items}
    named = labelled | set(launch_gate.NOT_LABELLED) | set(launch_gate.AT_SOURCE)
    assert not (labelled & set(launch_gate.NOT_LABELLED)) and not (set(launch_gate.AT_SOURCE) & set(launch_gate.NOT_LABELLED))
    unknown = sorted(item for item in named if item not in items)
    assert not unknown, f"not in docs/LAUNCH-GATE.md: {unknown}"
    closed = sorted(item for item in named if items[item][0] in ("VERIFIED", "CLOSED", "BY DESIGN"))
    assert not closed, f"verified, closed or by design, yet named by the launch-gate tables: {closed}"
    missing = sorted(item for item, (status, ids) in items.items() if status == "OPEN" and item not in named)
    assert not missing, f"OPEN items in none of LABELS, NOT_LABELLED and AT_SOURCE: {missing}"
    assert all(ids for item, (status, ids) in items.items() if item in ("LG-16", "LG-41", "LG-42", "LG-43", "LG-44"))
    assert items["LG-74"][0] == "OPEN" and all(items[item][0] == "OPEN" for item in ("LG-41", "LG-42", "LG-43", "LG-44"))
    for row in launch_gate.LABELS:
        assert row.mode in launch_gate.MODES and row.items and all(launch_gate.ITEM.match(item) for item in row.items)
        if row.pattern:
            re.compile(row.pattern)
