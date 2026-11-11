"""M1 slice A, step 5: every web report download passes the release gate (DECISIONS 280).

A finished demo audit (loopback fake site, mocked paid providers) is downloaded with its saved gate decision set to
BLOCKED, then PASS. Blocked: the PDF, Markdown, JSON and the final client-report export are refused; a draft may be
downloaded and says it is a draft. The cards are checked on the rows and the HTML the PDF is printed from.
"""
from __future__ import annotations

import json

import pytest

from maya_audit import final, release_gate
from maya_audit_web import pdf, summary
from maya_audit_web.runner import REPORT_JSON
from test_web_app import API, audit_of, error, web  # noqa: F401  (fixture)

HARD = {"rule": "RG-5", "hard": True, "finding_id": "x", "message": "High finding without a re-test state"}


@pytest.fixture
def finished(web):  # noqa: F811
    client = web()
    audit = audit_of(client)
    assert audit["state"] == "finished"
    path = client.app.state.runner.artifacts(audit["id"]) / REPORT_JSON
    return client, audit, path


def set_gate(path, decision, violations=()):
    report = json.loads(path.read_text(encoding="utf-8"))
    report["release_gate"] = {**(report.get("release_gate") or {}), "decision": decision, "violations": list(violations)}
    path.write_text(json.dumps(report), encoding="utf-8")


@pytest.mark.parametrize("fmt", ["pdf", "markdown", "json"])
def test_a_blocked_report_is_not_downloaded_as_final(finished, fmt):
    client, audit, path = finished
    set_gate(path, release_gate.BLOCKED, [HARD])
    body = error(client.get(f"{API}/audits/{audit['id']}/downloads/{fmt}"), 409, "release_blocked")
    assert body["details"]["rules"] == ["RG-5"] and body["details"]["draft"] is True


def test_a_blocked_report_downloads_as_a_marked_draft(finished):
    client, audit, path = finished
    set_gate(path, release_gate.BLOCKED, [HARD])
    response = client.get(f"{API}/audits/{audit['id']}/downloads/markdown", params={"draft": "true"})
    assert response.status_code == 200
    assert response.headers["x-maya-release-gate"] == "BLOCKED"
    assert response.headers["content-disposition"].endswith('-draft.md"')
    assert response.text.startswith("> **DRAFT: the release gate blocked this report")
    data = client.get(f"{API}/audits/{audit['id']}/downloads/json", params={"draft": "true"})
    assert data.status_code == 200 and data.headers["content-disposition"].endswith('-draft.json"')
    assert data.json()["release_gate"]["decision"] == "BLOCKED"  # the record itself is unchanged
    printed = client.get(f"{API}/audits/{audit['id']}/print")
    assert printed.status_code == 200 and "DRAFT: the release gate blocked this report" in printed.text


def test_a_blocked_report_has_no_final_client_export(finished):
    client, audit, path = finished
    set_gate(path, release_gate.BLOCKED, [HARD])
    for fmt in ("html", "pdf", "json"):
        error(client.get(f"{API}/audits/{audit['id']}/client-report/export/{fmt}", params={"mode": "final"}), 409,
              "release_blocked")


def test_a_passing_report_downloads_normally_with_its_decision(finished):
    client, audit, path = finished
    set_gate(path, release_gate.PASS)
    response = client.get(f"{API}/audits/{audit['id']}/downloads/markdown")
    assert response.status_code == 200 and response.headers["x-maya-release-gate"] == "PASS"
    assert "DRAFT" not in response.text[:200] and not response.headers["content-disposition"].endswith('-draft.md"')


def test_the_evidence_zip_is_not_a_report_and_is_not_gated(finished):
    client, audit, path = finished
    set_gate(path, release_gate.BLOCKED, [HARD])
    assert client.get(f"{API}/audits/{audit['id']}/downloads/evidence").status_code == 200


# ------------------------------------------------------------------ the card on the client's page


def test_rows_and_printed_html_carry_the_broken_link_card():
    from test_m1_broken_links import LINK_TEXT, audit, routes
    outcome, base = audit(routes())
    report = final.seal(outcome).report
    # DECISIONS 337: the link to the redirect (IDX-6) has its "where" rows too; this is the broken link's
    [row] = [r for r in summary.search(report, limit=100_000)["items"] if r.get("link_cards") and r.get("check_id") == "IDX-1"]
    [card] = row["link_cards"]
    assert card["source_url"] == base + "/urunler" and card["replacement"] == "unknown"
    html = pdf.link_cards_html(row["link_cards"])
    for text in ("Where to edit", base + "/urunler", LINK_TEXT, base + "/eski-urun", base + "/bulunamadi (404)",
                 "unknown: choose the page the link should point to, or remove the link"):
        assert text in html, text


def test_link_text_from_the_site_is_escaped():
    card = {"kind": "link", "source_url": "https://a.example/p", "link_text": "<script>x</script>", "links_to": "https://a.example/q",
            "target_url": "https://a.example/q", "target_status": 404, "replacement_url": None, "replacement": "unknown",
            "verification": "confirmed"}
    html = pdf.link_cards_html([card])
    assert "<script>" not in html and "&lt;script&gt;" in html


def test_the_results_card_offers_draft_downloads_for_a_blocked_report(finished):
    client, audit, path = finished
    set_gate(path, release_gate.BLOCKED, [HARD])
    view = client.get(f"{API}/audits/{audit['id']}/summary").json()
    assert view["release_gate"] == "BLOCKED"
    links = {d["format"]: d for d in view["downloads"]}
    assert all(links[f]["url"].endswith("?draft=true") and "draft" in links[f]["label"] for f in ("pdf", "markdown", "json"))
    assert not links["evidence"]["url"].endswith("?draft=true")
    for fmt in ("markdown", "json"):
        assert client.get(links[fmt]["url"]).status_code == 200
