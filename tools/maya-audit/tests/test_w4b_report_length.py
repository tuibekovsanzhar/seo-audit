"""The concise (client) report of the Arjava-like shop says each thing once, in the audit's language, without internal
terms or links into the owner's app (review items H35, H36, H38, CR-05..CR-19, CR-34, D-08, D-09, D-23).

The audit is the regression site of tests/test_arjava_regression.py; its report is placed in a web app as the report
of an ordinary audit, so every route reads it exactly as it reads one the worker wrote."""
from __future__ import annotations

import html as markup
import io
import json
import re

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from fakeserver import FakeServer  # noqa: E402
from fakeserver.arjava_scenarios import ARJAVA_SCENARIOS  # noqa: E402
from maya_audit import ownership  # noqa: E402
from maya_audit.audit import run_audit  # noqa: E402
from maya_audit.config import CrawlConfig  # noqa: E402
from maya_audit.report import build_report  # noqa: E402
from maya_audit_web import demo, pdf, practical, summary  # noqa: E402
from maya_audit_web.app import create_app  # noqa: E402
from maya_audit import clock  # noqa: E402
from maya_audit_web.runner import Engine  # noqa: E402

API = "/api/v1"
# The sentences the Arjava PDF repeated 60, 45, 15 and 13 times (arjava-rapor-karsilastirma.md, 3.4).
SHARED = {
    "en": ["Complete URLs, fields and request records", "the recorded check", "report export or owner approval is not verification",
           "Evidence sample (complete records", "Check the same affected URLs, client and property"],
    "tr": ["Tam adresler, alanlar ve istek kayıtları", "kayıtlı kontrolü", "Rapor indirme veya sahip onayı doğrulama değildir",
           "rapor indirme veya sahip onayı doğrulama değildir", "Kanıt örneği (tam kayıtlar", "Aynı URL, istemci ve özelliği"],
}


def repeated_sentences(page: str) -> dict[str, int]:
    """Every sentence over 40 characters said more than twice, with addresses and numbers masked so that "the same
    sentence about another page" counts as the same. The page table is left out: it is one row per page by design, and
    its repeated "/cdn-cgi/" row is the engine's (H09), not the report's."""
    from collections import Counter
    sections = [s for s in page.split("<h2>") if not s.startswith(("Problems by page", "Sayfa bazında sorunlar"))]
    text = text_of("<h2>".join(sections))
    masked = re.sub(r"\d+", "N", re.sub(r"https?://\S+", "URL", text))
    said = Counter(x.strip() for x in re.split(r"(?<=[.!?])\s+|\n|  +", masked) if len(x.strip()) > 40)
    return {sentence: n for sentence, n in said.items() if n > 2}


INTERNAL = ("recorded_observation", "diagnostic_concern", "informational_observation", "Capped at S4", "LG-", "Decision status",
            "Yargının durumu")


@pytest.fixture(scope="module")
def arjava_app(tmp_path_factory):
    scenario = ARJAVA_SCENARIOS["arjava"]
    # A fake clock (DECISIONS 299) for both audits made here: their polite gaps are counted, not waited (31 s of sleep).
    fake = clock.FakeClock()
    with clock.using(fake), FakeServer(scenario.build()) as server:
        config = CrawlConfig(**{"request_delay_s": 0.0, "robots_sample_interval_s": 0.05, "probe_retry_cooldown_s": 0.0,
                                "refetch_delay_s": 0.0, "render_enabled": False, "prf_round_gap_s": 0.0, **scenario.config})
        outcome = run_audit(server.base_url + "/", config)
    report = json.loads(json.dumps(build_report(outcome.result, outcome.gates, outcome.checks), default=str))
    saved = ownership.TRANSPORT
    ownership.TRANSPORT = demo.NO_DNS_RECORDS
    folder = tmp_path_factory.mktemp("w4b")
    engine = Engine(paid=demo.paid_services(folder / "paid"), firecrawl=demo.firecrawl_services(folder / "firecrawl"),
                    transport_factory=lambda: demo.site_transport(0), allow_loopback=True, overrides=demo.OVERRIDES,
                    crux_key=lambda: None, crux_transport=demo.CRUX_TRANSPORT, archives_transport=demo.ARCHIVES_TRANSPORT)
    client = TestClient(create_app(folder / "app", engine=engine, port=8770), base_url="http://127.0.0.1:8770")
    client.__enter__()
    try:
        client.get("/")
        client.headers["x-maya-token"] = client.get(f"{API}/session").json()["token"]
        made = client.post(f"{API}/plans", json={"url": demo.CAFE})
        with clock.using(fake):
            started = client.post(f"{API}/audits", json={"plan_id": made.json()["id"], "message": "arjava"})
            audit_id = started.json()["id"]
            client.app.state.runner.wait(audit_id, 120)
        artifacts = client.app.state.runner.artifacts(audit_id)
        (artifacts / "report.json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
        (artifacts / "affected-urls.json").unlink(missing_ok=True)
        yield client, audit_id, report
    finally:
        client.__exit__(None, None, None)
        ownership.TRANSPORT = saved


def text_of(page: str) -> str:
    return markup.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"<style.*?</style>", " ", page, flags=re.S)))


def finding_ids(report):
    return {f["id"] for check in report["checks"] for f in check["findings"]}


@pytest.mark.parametrize("language", ["en", "tr"])
def test_the_concise_report_says_each_shared_sentence_once_and_keeps_every_finding(arjava_app, language):
    client, audit_id, report = arjava_app
    page = client.get(f"{API}/audits/{audit_id}/print?lang={language}").text  # the default printable page is the concise one
    assert 'name="maya-concise"' in page and f'<html lang="{language}"' in page
    text = text_of(page)
    for sentence in SHARED[language]:
        assert text.count(sentence) <= 2, sentence
    assert "repeating the recorded check" in text or "kayıtlı kontrolü aynı" in text  # said once, at the head of the section
    assert repeated_sentences(page) == {}  # no sentence of the report itself is said more than twice
    assert finding_ids(report) <= set(re.findall(r"[A-Z]{2,4}-\d{1,2}-[0-9a-f]{8}", text))  # every finding, by ID
    # A finding detailed in the priority section is one "↑" cell in the inventory, not a second card (CR-15).
    priority = page.split("<h2>")[3]
    detailed = set(re.findall(r'<section class="issue" id="([^"]+)"', priority))
    assert detailed and all(page.count(f'id="{fid}"') == 1 for fid in detailed)
    assert text.count("↑") >= len(detailed)
    # Notes are one line each, never cards (CR-06).
    notes = [f for check in report["checks"] for f in check["findings"] if f["severity"] == "Info"]
    assert notes and not any(f'<section class="issue" id="{f["id"]}"' in page for f in notes)
    # The unread-pages line, and every other coverage gap, is said once (CR-05).
    limits = page.split("<h2>")[-3]
    lines = re.findall(r'<p class="small wrap">(.*?)</p>', limits)
    assert len(lines) == len(set(line.split(" · ", 1)[-1] for line in lines))


def test_the_sentence_counter_finds_a_repeated_sentence():
    card = "<p>Check the same affected URLs, client and property before you change anything here.</p>"
    assert repeated_sentences("<h2>Priority</h2>" + card * 3) and not repeated_sentences("<h2>Priority</h2>" + card * 2)


@pytest.mark.parametrize("language", ["en", "tr"])
def test_the_concise_report_shows_no_internal_terms_no_raw_values_and_no_link_into_the_app(arjava_app, language):
    client, audit_id, _ = arjava_app
    page = client.get(f"{API}/audits/{audit_id}/print?lang={language}").text
    text = text_of(page)
    for term in INTERNAL:
        assert term not in text, term
    assert "{'" not in text and "[{" not in text  # no Python repr of an evidence record (CR-14)
    # Companion files are named, never linked through the owner's local app (D-08); the full export keeps its terms.
    assert "/api/v1/audits/" not in page and ":8770" not in page
    assert re.search(r"maya-audit-[\w.-]+-evidence\.zip", text)
    assert "zero data retention" not in text.lower() and "sıfır veri saklama" not in text.lower()
    full = client.get(f"{API}/audits/{audit_id}/print?full=true&lang={language}").text
    assert "maya-concise" not in full and "LG-" in full


def test_the_printed_language_is_the_audits_unless_asked_for_another(arjava_app):
    client, audit_id, _ = arjava_app
    store = client.app.state.store
    try:
        client.cookies.set("maya_language", "tr")
        english = client.get(f"{API}/audits/{audit_id}/print").text
        assert '<html lang="en"' in english and "Executive summary" in english  # the audit was started in English
        assert "Yönetici özeti" in client.get(f"{API}/audits/{audit_id}/print?lang=tr").text
        with store._lock:
            store._db.execute("UPDATE audits SET language = 'tr' WHERE id = ?", (audit_id,))
        client.cookies.set("maya_language", "en")
        assert "Yönetici özeti" in client.get(f"{API}/audits/{audit_id}/print").text  # a Turkish client's audit prints Turkish
        assert "Executive summary" in client.get(f"{API}/audits/{audit_id}/print?lang=en&full=true").text
        assert client.get(f"{API}/audits/{audit_id}/print?lang=english").status_code == 422
    finally:
        with store._lock:
            store._db.execute("UPDATE audits SET language = 'en' WHERE id = ?", (audit_id,))
        client.cookies.set("maya_language", "en")


def test_the_concise_pdf_of_the_arjava_shop_is_at_most_ten_pages(arjava_app):
    pytest.importorskip("playwright")
    from pypdf import PdfReader
    client, audit_id, _ = arjava_app
    for language in ("en", "tr"):
        page = client.get(f"{API}/audits/{audit_id}/print?lang={language}").text
        try:
            content = pdf.to_pdf(page, max_pages=None)
        except pdf.PdfUnavailable as exc:
            pytest.skip(f"Chromium unavailable: {exc}")
        assert len(PdfReader(io.BytesIO(content)).pages) <= 10, language


def test_the_client_compact_report_has_one_card_per_check_and_no_raw_values(arjava_app):
    client, audit_id, _ = arjava_app
    assert client.post(f"{API}/audits/{audit_id}/client-report", json={}).status_code == 200
    compact = client.get(f"{API}/audits/{audit_id}/client-report/export/html?mode=draft").text
    main = compact.split("<h2>Sorunlar ve çözümleri</h2>")[1].split("<h2>")[0]
    checks = re.findall(r'class="card [^"]*" id="finding-([A-Z]{2,4}-\d{1,2})-', main)
    assert checks and len(checks) == len(set(checks))  # CR-04
    text = text_of(compact)
    for raw in ("{'", "[{", '{"', "Ortak uygulama: IDX", "recorded_observation"):
        assert raw not in text, raw
    assert "/api/v1/audits/" not in compact and ":8770" not in compact and "Content-Security-Policy" in compact
    assert text.count("Aynı adreslerde kaydı incelemelisiniz") <= sum(1 for _ in re.finditer('class="card ', compact))
    full = client.get(f"{API}/audits/{audit_id}/client-report/export/html?mode=draft&full=true").text
    assert full.count('class="card ') > compact.count('class="card ')  # the full export keeps every card


def test_the_top_problems_name_each_check_once_in_priority_order():
    def row(check, severity, title, **extra):
        return {"id": title, "check_id": check, "severity": severity, "severity_label": severity, "area": "STR", "title": title,
                "affects": "1 page", "sample_pages": [], "pages_total": 1, "why": "", "fix": "Fix it.", "requires_fix": True,
                "confidence": "verified", "confidence_label": "Verified",
                "estimates": {"owner": "content", "owner_label": "Content", "effort": "S", "effort_label": "S"}, **extra}
    rows = [row("IDX-1", "S2", "A"), row("IDX-6", "S3", "B"), row("IDX-6", "S3", "C"),
            row("RND-1", "S2", "Guess", confidence="estimated", unverified={"label": "Unverified check", "items": ["LG-15"]}),
            row("STR-3", "S3", "D")]
    top = practical.executive(rows, None, None, withheld=None)["problems"]
    assert [p["title"] for p in top] == ["A", "Guess", "B", "D"]  # one IDX-6; the unverified S2 after the verified one
    assert practical.when(rows[3]) == "verify" and practical.when(rows[0]) == "week"  # never "This week" (CR-34)
    steps = practical.timeline(rows)
    assert [s["id"] for s in steps] == ["week", "verify", "month", "later"]
    assert [s["id"] for s in practical.timeline(rows[:3])] == ["week", "month", "later"]  # said only when needed


def test_an_evidence_limit_is_said_once_and_only_idx6_gets_the_destination_caution(monkeypatch):
    from maya_audit import evidence_quality
    limit = "Single empty response or unavailable corroboration; persistent failure and business impact remain uncertain."
    monkeypatch.setattr(evidence_quality, "qualifications", lambda finding: [limit])
    base = {"title": "1 page(s) have no <title>", "severity": "S4", "confidence": "verified", "rationale": "Measured", "engines": [],
            "scope": {"kind": "page", "count": 1, "urls": ["https://cafe.example/a"]}, "observed_at": "2026-10-21T10:00:00Z",
            "notes": [], "launch_gated": [], "expected": "a title", "evidence": {"pages": [{"url": "https://cafe.example/a"}]}}
    other = summary.item({**base, "id": "STR-1-x", "check_id": "STR-1", "how_to_fix": "Add a <title> that names the page's topic."})
    assert not other["judgment"].get("qualified")
    assert "destination is gone" not in other["fix_shown"] and other["fix"] in ("Add a <title> that names the page's topic.",)  # CR-17
    shown = summary.wording.note(limit)[0]
    assert other["why"].count(shown) == 1 and not any(shown in line for line in other["details"])  # CR-18: said once
    link = summary.item({**base, "id": "IDX-6-x", "check_id": "IDX-6", "title": "Link target returns 404, linked from 1 page",
                         "how_to_fix": "Update these links."})
    if not link["judgment"].get("qualified"):
        assert "not proof that the destination is gone" in link["fix_shown"]


def test_an_evidence_sample_with_attempts_is_written_as_words():
    from maya_audit_web.concise_report import excerpts
    record = {"evidence": {"links": [{"url": "https://cafe.example/a", "status": 404, "attempts": [
        {"url": "https://cafe.example/a", "source": "native_crawl", "method": "GET", "status": 404, "body_bytes": 12,
         "requested_at": "2026-10-21T10:00:00Z", "error": None}]}]}}
    [sample] = excerpts(record)
    said = "; ".join(f"{k}: {v}" for k, v in sample)
    assert "attempts: GET 404 · native_crawl · https://cafe.example/a · 12 B · 2026-10-21T10:00:00Z" in said
    assert "{" not in said and "None" not in said
