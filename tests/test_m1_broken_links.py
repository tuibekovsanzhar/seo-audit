"""M1 slice A: a broken internal link, end to end (guide stages 02/04/09/10, minimum contract).

Hand-written cases; the expected values below are written from the fake site's own routes, not copied from output:

  BROKEN    /urunler links "Eski ürün" to /eski-urun, which redirects (301) to /bulunamadi, a 404.
            /urunler also links "Kampanya" to /kampanya, which works.
  WORKING   the same site, but /eski-urun redirects to /kampanya (200): nothing is broken.
  PARTIAL   BROKEN with a page cap that stops the crawl before the redirect is followed: no card, and the report does
            not call the link check a pass.

Offline: a loopback fake server, verification against that server only.
"""
from __future__ import annotations

import json
from dataclasses import replace

import pytest

from fakeserver import FakeServer, Response, Site
from maya_audit import final, release_gate
from maya_audit.audit import run_audit
from maya_audit.config import CrawlConfig
from test_deadline_hosted_hardening import QUIET
from test_review_fixes import TR, page
from test_firecrawl import no_lookups  # noqa: F401  (fixture)

LINK_TEXT = "Eski ürün"


def routes(old_product_goes_to: str = "/bulunamadi") -> dict:
    return {
        "/robots.txt": Response(body="User-agent: *\nAllow: /\n", content_type="text/plain"),
        "/sitemap.xml": Response(404, "", content_type="text/plain"),
        "/": page(f"<h1>Ana sayfa</h1><p>{TR}</p><a href=\"/urunler\">Ürünler</a> <a href=\"/iletisim\">İletişim</a>", nav=""),
        "/urunler": page(f"<h1>Ürünler</h1><p>{TR}</p><a href=\"/eski-urun\">{LINK_TEXT}</a> "
                         "<a href=\"/kampanya\">Kampanya</a>", nav=""),
        "/eski-urun": Response(301, "", headers={"Location": old_product_goes_to}),
        "/bulunamadi": Response(404, "<html><title>Bulunamadı</title><body>Sayfa yok</body></html>"),
        "/kampanya": page(f"<h1>Kampanya</h1><p>{TR}</p>", nav=""),
        "/iletisim": page(f"<h1>İletişim</h1><p>{TR}</p>", nav=""),
    }


def audit(site_routes: dict, **cfg):
    with FakeServer(Site(site_routes)) as fake:
        outcome = run_audit(fake.base_url + "/", replace(CrawlConfig(), **{**QUIET, "verification_enabled": True, **cfg}))
    return outcome, fake.base_url


@pytest.fixture(scope="module")
def broken():
    outcome, base = audit(routes())
    return outcome, final.seal(outcome), base


def link_findings(report: dict) -> list[dict]:
    return [f for c in report["checks"] for f in c["findings"] if (f.get("rule_id") or "").startswith("idx1.4xx.referenced")]


# ------------------------------------------------------------------ the card


def test_broken_link_via_redirect_gives_one_card_at_its_source(broken):
    _, sealed, base = broken
    [finding] = link_findings(sealed.report)
    assert finding["scope"]["urls"] == [base + "/urunler"]  # the page to edit, never the error page
    [card] = sealed.cards[finding["id"]]
    assert card == {
        "finding_id": finding["id"], "rule_id": finding["rule_id"], "severity": finding["severity"], "kind": "link",
        "source_url": base + "/urunler", "link_text": LINK_TEXT, "links_to": base + "/eski-urun",
        "target_url": base + "/bulunamadi", "target_status": 404,
        "replacement_url": None, "replacement": "unknown",
        "verification": finding["verification"]["state"],
    }
    assert card["verification"] == "confirmed"  # the second look found the link still there and still failing


def test_the_working_link_on_the_same_page_has_no_card(broken):
    _, sealed, base = broken
    cards = [c for rows in sealed.cards.values() for c in rows]
    assert base + "/kampanya" not in json.dumps(cards)


def test_working_counterpart_has_no_broken_link_finding():
    outcome, base = audit(routes(old_product_goes_to="/kampanya"))
    sealed = final.seal(outcome)
    assert link_findings(sealed.report) == []
    assert sealed.cards == {}


def test_partial_crawl_makes_no_card_and_no_pass():
    """Three pages: /, /urunler, /iletisim. The redirect target is never fetched, so nothing is known about it."""
    outcome, base = audit(routes(), max_pages=3)
    sealed = final.seal(outcome)
    assert sealed.cards == {}
    [idx1] = [c for c in sealed.report["checks"] if c["check_id"] == "IDX-1"]
    assert idx1["status"] != "pass"  # unread addresses are not "no broken links" (INV-01)


# ------------------------------------------------------------------ one final result for every output


def test_markdown_shows_the_card_from_the_final_result(broken):
    _, sealed, base = broken
    text = final.cards_markdown(sealed.report)
    assert "## Broken links: what to edit" in text
    assert f"| {base}/urunler | {LINK_TEXT} | {base}/eski-urun | {base}/bulunamadi (404) | unknown |" in text


def test_saved_report_reads_back_to_the_same_cards_and_gate(broken):
    """The adapter for a saved report (JSON round trip) gives the same cards, gate and full address lists."""
    _, sealed, _ = broken
    saved = json.loads(json.dumps(sealed.report))
    again = final.from_report(saved, json.loads(json.dumps(sealed.affected)))
    assert again.cards == sealed.cards
    assert again.gate["decision"] == sealed.gate["decision"]
    assert again.affected == sealed.affected


def test_old_report_without_gate_gets_one_computed():
    """A report saved before schema 1.20 has no release_gate: the adapter runs the gate instead of assuming PASS."""
    old = {"schema_version": "1.19", "checks": [{"check_id": "IDX-1", "findings": [
        {"id": "x1", "check_id": "IDX-1", "severity": "S2", "title": "1 URL(s) return a client error (4xx), linked internally or "
         "listed in the sitemap", "scope": {"urls": ["https://a.example/p"], "count": 1}, "evidence": {}}]}]}
    again = final.from_report(old)
    assert again.gate["decision"] in (release_gate.BLOCKED, release_gate.CONDITIONAL)
    assert again.cards == {}  # no link_sources recorded: no card is invented
    assert again.affected == {"x1": ["https://a.example/p"]}


def test_seal_is_not_changed_by_rendering(broken):
    _, sealed, _ = broken
    before = sealed.digest
    final.cards_markdown(sealed.report)
    final.from_report(sealed.report, sealed.affected)
    assert final.digest_of(sealed.report) == before


def test_cli_and_web_use_the_same_seal():
    """Both adapters call final.seal; neither builds the report or the address lists on its own."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    for path in ("maya_audit/cli.py", "maya_audit_web/runner.py"):
        source = (root / path).read_text(encoding="utf-8")
        assert "final.seal(" in source, path
        assert "build_report(" not in source and "affected_urls(outcome.checks)" not in source, path


# ------------------------------------------------------------------ the same finalization after a page reader


def test_a_finding_a_page_reader_replaced_gets_page_types_and_a_retest_state(tmp_path, no_lookups):
    """Maya's crawl sees a visible <h1>; Firecrawl's copy of the homepage hides it. The reader's STR-2 replaces Maya's,
    and its High finding must leave with the same contract as an engine finding: page kinds and a re-test state."""
    import httpx
    from maya_audit.firecrawl import Options, reader
    from test_firecrawl import HTML, ROBOTS_TEXT, Firecrawl, client_for, doc, TEXT

    seen = {"https://h1.test/": doc("Solar", "<h1>Solar panels</h1>" + TEXT + '<a href="/about">About</a>'),
            "https://h1.test/about": doc("About", "<h1>About</h1>" + TEXT)}
    read = {**seen, "https://h1.test/": doc("Solar", "<h1 hidden>Solar panels</h1>" + TEXT + '<a href="/about">About</a>')}

    def site(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS_TEXT, headers={"content-type": "text/plain"})
        url = str(request.url)
        return httpx.Response(200, headers=HTML, text=seen[url]) if url in seen else httpx.Response(404, headers=HTML, text="<title>x</title>")

    cfg = replace(CrawlConfig(), **{**QUIET, "max_pages": 5, "verification_enabled": True})
    outcome = run_audit("https://h1.test/", cfg, httpx.MockTransport(site))
    assert not [f for c in outcome.checks for f in c.findings if f.rule_id == "str2.home_hidden_h1"]
    info = reader.apply(outcome, cfg, client_for(tmp_path, Firecrawl(read)), Options(read_always=True, max_pages=5))
    assert "STR-2" in info["checks_from_firecrawl"]
    [hidden] = [f for c in outcome.checks for f in c.findings if f.rule_id == "str2.home_hidden_h1"]
    assert hidden.severity.value in ("S1", "S2")
    assert hidden.page_types  # annotated after the reader, as for Maya's own findings
    assert hidden.verification["state"] == "not_retested" and hidden.verification["reason"]
    assert "after_provider" in outcome.result.verification
    report = final.seal(outcome, firecrawl=info).report
    assert [v for v in release_gate.check_report(report) if v["rule"] in ("RG-5", "RG-7")] == []
