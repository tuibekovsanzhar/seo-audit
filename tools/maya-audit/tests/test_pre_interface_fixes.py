"""Three corrections from the review of the second ground-truth run, and the frozen report format.

Offline: fake server only. The one test that opens a browser renders a page served by the fake server.
"""

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from fakeserver import Response
from fakeserver.rnd_scenarios import FAST_RND
from maya_audit import schema
from maya_audit.checks.content_quality import RAW_ONLY, str13_template_markers
from maya_audit.checks.index import idx3_redirects, unfollowed_redirects
from maya_audit.config import CrawlConfig
from maya_audit.language import has_personal_title, heading_language, looks_like_name
from maya_audit.report import build_report
from test_dataforseo import Api, home  # noqa: F401  (home is a fixture)
from test_dataforseo_backlinks import run_plan
from test_review_fixes import EN, TR, audit, page, short
from test_rnd_scenarios import _browser_available

# 1. STR-12: a person's name is not language evidence ---------------------------------------------------
TEAM = ("<h3>Prof. Dr. Vehbi Alp Üçok</h3><h3>Pelin Taş, M.D.</h3><h3>Çağdaş Yokuşoğlu M. D.</h3>"
        "<h3>Uzm. Psk. Ayşe Gülşen Yılmaz</h3><h3>Doç. Dr. Işıl Göğcegöz</h3><h3>Mehmet Ali Yılmaz</h3>"
        "<h3>Şükrü Çağrı Öztürk</h3><h3>Op. Dr. Gökçe Şahin Ünlü</h3>")


@pytest.mark.parametrize("heading", [
    "Prof. Dr. Vehbi Alp Üçok", "Pelin Taş, M.D.", "Çağdaş Yokuşoğlu M. D.", "Uzm. Psk. Ayşe Yılmaz", "DOÇ. DR. IŞIL GÖĞCEGÖZ",
    "Dyt. Elif Şahin Çelik", "Op. Dr. Gökçe Ünlü", "Yrd. Doç. Ömer Kılıç", "Ayşe Yılmaz, PhD", "Öğr. Gör. Çiğdem Ateş"])
def test_a_heading_with_a_title_or_degree_is_a_name_and_has_no_language(heading):
    assert has_personal_title(heading) and heading_language(heading) is None


def test_ordinary_headings_are_not_taken_for_names():
    for heading in ("Tedavi süreci nasıl ilerler", "Information for new patient", "Our doctors and their team",
                    "Mrs Dalloway and other stories", "Drama terapisi nedir", "Operasyon öncesi hazırlık",
                    "Document your medical history"):
        assert not has_personal_title(heading), heading
    assert heading_language("Tedavi süreci nasıl ilerler") == "tr"
    assert heading_language("Information for new patient") == "en"
    # A title-case Turkish heading is still Turkish on a page that lists no people ...
    assert looks_like_name("Şizofreni Tedavi Yöntemleri") and heading_language("Şizofreni Tedavi Yöntemleri") == "tr"
    # ... and on a page that does, a short all-capitalised heading without a title is taken for one more name.
    assert heading_language("Şükrü Çağrı Öztürk", among_names=True) is None
    assert heading_language("Tedavi süreci nasıl ilerler", among_names=True) == "tr"


def test_str12_an_english_team_page_listing_turkish_names_is_not_reported():
    """moodisthastanesi.com/en/ and /en/our-team/: English pages whose headings are the doctors' names."""
    routes = {
        "/en/our-team/": page(f"<h1>Our Team</h1><p>{EN}</p><p>{EN}</p>" + TEAM, lang="en"),
        # Control: an English page that really has Turkish section headings is still reported.
        "/en/services/": page(f"<h1>Services</h1><p>{EN}</p><p>{EN}</p><h2>Tedavi süreci nasıl ilerler</h2>"
                              "<h2>Randevu için bizi arayın</h2><h2>Çocuk ve ergen psikiyatrisi</h2>"
                              "<h3>Prof. Dr. Vehbi Alp Üçok</h3>", lang="en"),
    }
    outcome = audit(routes)
    [finding] = [f for f in outcome.by_id["STR-12"].findings if "section headings" in f.title]
    [row] = finding.evidence["pages"]
    assert short(outcome, [row["url"]]) == ["/en/services/"]
    assert row["headings_count"] == 3 and row["name_headings_left_out"] == 1
    assert not any("Dr." in heading for heading in row["headings"])


# 2. STR-13: a slot the browser fills in --------------------------------------------------------------
def analysed(url, blocks):
    return SimpleNamespace(url=url, analysis={"_text_blocks": blocks, "_visible_text": " ".join(blocks)})


def markers_check(pages, rendered):
    result = SimpleNamespace(render=SimpleNamespace(pages={
        url: {"ok": True, "rendered": {"_visible_text": text}} for url, text in rendered.items()}))
    check = str13_template_markers(result, CrawlConfig(), pages, set())
    return check, {f.evidence["where"]: f for f in check.findings}


def test_str13_a_marker_gone_from_the_rendered_view_is_raw_html_only_and_info():
    """magazanolsun.com: the cart total `{{item.toplam | number }} TL` is filled in by the page's own script."""
    pages = [analysed("https://shop.example/", ["Sepet toplamı {{item.toplam | number }} TL"]),
             analysed("https://shop.example/yazi", ["Yayın tarihi {{publishDate}} olarak görünüyor"]),
             analysed("https://shop.example/eski", ["Yazar {{author_name}} tarafından yazıldı"])]
    check, by_where = markers_check(pages, {
        "https://shop.example/": "Sepet toplamı 1.250 TL",                           # filled in by the browser
        "https://shop.example/yazi": "Yayın tarihi {{publishDate}} olarak görünüyor"})  # still there: a reader sees it
    raw_only, visible = by_where[RAW_ONLY], by_where["visible text"]
    assert RAW_ONLY == "raw HTML only (filled in by the browser)" and RAW_ONLY in raw_only.title
    assert raw_only.severity.value == "Info" and raw_only.scope["urls"] == ["https://shop.example/"]
    assert raw_only.evidence["found"][0]["in_rendered_view"] is False
    assert "a reader does not see it" in raw_only.notes[0]
    # Seen after rendering, or never rendered: still a finding at S3.
    assert visible.severity.value == "S3"
    assert sorted(visible.scope["urls"]) == ["https://shop.example/eski", "https://shop.example/yazi"]
    seen = {row["url"]: row.get("in_rendered_view") for row in visible.evidence["found"]}
    assert seen == {"https://shop.example/yazi": True, "https://shop.example/eski": None}
    assert any("a reader sees it" in note for note in visible.notes)
    assert any("were not opened in a browser" in note for note in visible.notes)


def test_str13_without_rendering_nothing_is_called_raw_html_only():
    check, by_where = markers_check([analysed("https://shop.example/", ["Toplam {{item.toplam}} TL"])], {})
    assert set(by_where) == {"visible text"} and by_where["visible text"].severity.value == "S3"


def test_str13_raw_html_only_with_a_real_browser():
    reason = _browser_available()
    if reason:
        pytest.skip(f"T1 rendering tests need a headless browser: {reason}")
    script = ("<script>document.getElementById('toplam').textContent = '1.250 TL';</script>")
    routes = {
        "/sepet-ozeti": page(f'<h1>Sipariş Özeti</h1><p>{TR}</p><p id="toplam">{{{{item.toplam | number }}}} TL</p>' + script),
        "/taslak": page(f"<h1>Taslak</h1><p>{TR}</p><p>Yayın tarihi {{{{publishDate}}}} olarak görünüyor.</p>"),
    }
    outcome = audit(routes, **{**FAST_RND, "render_enabled": True, "render_budget": 5, "render_settle_ms": 500})
    by_where = {f.evidence["where"]: f for f in outcome.by_id["STR-13"].findings}
    assert short(outcome, by_where[RAW_ONLY].scope["urls"]) == ["/sepet-ozeti"]
    assert by_where[RAW_ONLY].severity.value == "Info"
    assert short(outcome, by_where["visible text"].scope["urls"]) == ["/taslak"]
    assert by_where["visible text"].evidence["found"][0]["in_rendered_view"] is True


# 3. IDX-3: a redirect the audit does not follow ----------------------------------------------------------
def fetched(url, status=200, location=None):
    return SimpleNamespace(url=url, status=status, redirect_location=location, outlinks=[])


def test_unfollowed_redirects_tells_an_http_downgrade_from_another_host():
    pages = [fetched("https://clinic.example/"),
             fetched("https://clinic.example/bolum", 301, "http://clinic.example/tr/bolum/"),
             fetched("https://clinic.example/randevu", 302, "https://randevu.clinic.example/"),
             fetched("https://clinic.example/app", 302, "https://apps.apple.com/app/id1"),
             fetched("https://clinic.example/eski", 301, "https://clinic.example/yeni"),   # on the site: followed
             fetched("https://clinic.example/yeni")]
    result = SimpleNamespace(origin="https://clinic.example", pages=pages)
    redirects = {p.url: p.redirect_location for p in pages if p.redirect_location}
    rows = {row["url"].rsplit("/", 1)[-1]: row for row in unfollowed_redirects(result, redirects, {p.url: p for p in pages})}
    assert set(rows) == {"bolum", "randevu", "app"}
    assert rows["bolum"] == {"url": "https://clinic.example/bolum", "status": 301, "target": "http://clinic.example/tr/bolum/",
                             "kind": "http", "same_site": True}
    assert (rows["randevu"]["kind"], rows["randevu"]["same_site"]) == ("other_host", True)
    assert (rows["app"]["kind"], rows["app"]["same_site"]) == ("other_host", False)


def test_idx3_reports_a_key_page_that_redirects_to_another_host_with_the_target():
    """moodisthastanesi.com: a key page redirected off the audited origin; the tool stopped there and said nothing."""
    target = "http://elsewhere.example/tr/cinsel-islev-bozukluklari/"
    routes = {"/tr/bolum/cinsel-islev-bozukluklari/": Response(status=301, headers={"Location": target}),
              "/tr/bolum/kaygi/": page(f"<h1>Kaygı</h1><p>{TR}</p>")}
    outcome = audit(routes)
    check = outcome.by_id["IDX-3"]
    [finding] = [f for f in check.findings if "did not follow" in f.title]
    assert finding.title == "1 page(s) redirect to another host, which this audit did not follow"
    assert finding.severity.value == "Info" and finding.confidence.value == "verified"
    [row] = finding.evidence["redirects"]
    assert row["target"] == target and row["status"] == 301 and row["same_site"] is False
    assert "nothing is known about the page a visitor ends on" in finding.notes[0]
    assert check.evidence["redirects_not_followed"] == 1
    assert target not in {p.url for p in outcome.result.pages}  # and it was not fetched


def test_idx3_a_redirect_from_https_to_http_is_an_s3_finding(monkeypatch):
    import maya_audit.checks.index as index_checks

    monkeypatch.setattr(index_checks, "key_page_urls", lambda result, cfg: ["https://clinic.example/bolum"])
    pages = [fetched("https://clinic.example/"), fetched("https://clinic.example/bolum", 301, "http://clinic.example/tr/bolum/")]
    check = idx3_redirects(SimpleNamespace(origin="https://clinic.example", pages=pages), CrawlConfig())
    [finding] = check.findings
    assert finding.title == "1 page(s) redirect from https:// to an http:// address, which this audit did not follow"
    assert finding.severity.value == "S3" and finding.importance_tier == 0
    assert finding.evidence["redirects"][0]["target"] == "http://clinic.example/tr/bolum/"
    assert check.status == "findings"


# 4. The report format is frozen under schema_version ---------------------------------------------------
DOC = Path(schema.__file__).resolve().parent.parent / "docs" / "REPORT-SCHEMA.md"


def test_the_report_shape_matches_the_frozen_copy_for_its_version():
    path = schema.frozen_path()
    assert path.exists(), (f"no frozen copy for schema {schema.SCHEMA_VERSION}: run `python -m maya_audit.schema` and "
                           "describe the change in docs/REPORT-SCHEMA.md")
    frozen = json.loads(path.read_text(encoding="utf-8"))
    changed = schema.differences(frozen, schema.shape())
    assert not changed, ("the report's shape changed without a version bump. Raise SCHEMA_VERSION in maya_audit/schema.py, "
                         "run `python -m maya_audit.schema`, and describe the change in docs/REPORT-SCHEMA.md:\n  "
                         + "\n  ".join(changed))


def test_a_changed_shape_is_noticed(monkeypatch):
    frozen = json.loads(schema.frozen_path().read_text(encoding="utf-8"))
    monkeypatch.setattr(schema, "REPORT_KEYS", schema.REPORT_KEYS + ("score",))
    monkeypatch.setattr(schema, "SCOPE_KEYS", ("kind", "urls"))
    assert schema.differences(frozen, schema.shape()) == ["report.required: added ['score']", "scope: removed ['count']"]


def test_version_1_1_only_adds_to_1_0():
    """The promise of a second-number bump: nothing a reader of 1.0 relies on is gone."""
    old = json.loads(schema.frozen_path("1.0").read_text(encoding="utf-8"))
    changes = [line for line in schema.differences(old, schema.shape()) if not line.startswith("schema_version")]
    assert changes and all(": added" in line for line in changes), changes  # "x: added [..]" for a list, "x: added" for a new section


def test_earlier_frozen_copies_are_kept_and_differ_from_each_other():
    copies = {p.name: json.loads(p.read_text(encoding="utf-8")) for p in schema.frozen_path().parent.glob("report-schema-*.json")}
    assert f"report-schema-{schema.SCHEMA_VERSION}.json" in copies
    for name, copy in copies.items():
        assert name == f"report-schema-{copy['schema_version']}.json"
    bodies = [json.dumps({k: v for k, v in copy.items() if k != "schema_version"}, sort_keys=True) for copy in copies.values()]
    assert len(set(bodies)) == len(bodies), "two schema versions with the same shape"


@pytest.fixture(scope="module")
def written():
    routes = {"/tr/a/": page(f"<h1>Bir</h1><p>{TR}</p><p>Yazar {{{{author_name}}}} tarafından yazıldı.</p>"),
              "/tr/b/": Response(status=301, headers={"Location": "/tr/a/"})}
    outcome = audit(routes)
    report = build_report(outcome.result, outcome.gates, outcome.checks)
    return json.loads(json.dumps(report, ensure_ascii=False))  # as read back from disk


def test_a_written_report_has_exactly_the_documented_keys(written):
    shape = schema.shape()
    assert written["schema_version"] == schema.SCHEMA_VERSION and list(written)[0] == "schema_version"
    assert set(written) == set(shape["report"]["required"])
    assert set(written["page_counts"]) == set(shape["page_counts"])
    assert set(written["crawl"]) == set(shape["crawl"])
    for gate in written["gates"]:
        assert set(gate) == set(shape["gate"])
    findings = 0
    for check in written["checks"] + written["answer_engine_panel"]:
        assert set(check) == set(shape["check"]), check["check_id"]
        assert check["status"] in shape["vocabulary"]["check_status"]
        assert set(check["coverage"]) <= set(shape["coverage"])
        for finding in check["findings"]:
            findings += 1
            assert set(finding) == set(shape["finding"])
            assert finding["severity"] in shape["vocabulary"]["severity"]
            assert finding["confidence"] in shape["vocabulary"]["confidence"]
            assert set(finding["scope"]) == set(shape["scope"])
        for item in check["review_items"]:
            assert set(item) == set(shape["review_item"])
    assert findings and set(written["findings_in_priority_order"]) <= {
        f["id"] for c in written["checks"] for f in c["findings"]}
    for record, name in ((written["crawl"]["pages"], "page"), (written["crawl"]["requests"], "request"),
                         (written["crawl"]["sitemap_docs"], "sitemap_doc")):
        assert record and all(set(row) == set(shape[name]) for row in record), name
    assert written["crawl"]["stop_reason"] in shape["vocabulary"]["stop_reason"]


def test_the_backlinks_section_has_the_documented_keys(home):
    section, _ = run_plan(home, Api())
    # `relevance` is added only when the search data panels ran and were sorted; a backlinks-only section has the rest.
    # `stopped` and `note` are added only when requests were left out because of the account's balance (DECISIONS 180).
    assert set(section) == set(schema.DATAFORSEO_KEYS) - {"relevance", "stopped", "note"} and section["status"] in schema.DATAFORSEO_STATUSES


def test_every_field_is_described_in_the_schema_document():
    text = DOC.read_text(encoding="utf-8")
    assert f"`{schema.SCHEMA_VERSION}`" in text
    described = set(re.findall(r"`([A-Za-z_0-9.\-]+)`", text))
    shape = schema.shape()
    names = set(shape["report"]["required"]) | set(shape["report"]["optional"])
    for part in ("gate", "check", "finding", "review_item", "scope", "coverage", "page_counts", "time_limit_cut", "crawl",
                 "page", "request", "sitemap_doc", "skipped_url", "dataforseo", "evidence_saved"):
        names |= set(shape[part])
    for values in shape["vocabulary"].values():
        names |= set(values)
    assert not sorted(names - described), f"not described in docs/REPORT-SCHEMA.md: {sorted(names - described)}"


def test_a_reader_refuses_a_report_from_another_major_version():
    assert schema.unsupported_reason({"schema_version": schema.SCHEMA_VERSION}) is None
    assert schema.unsupported_reason({"schema_version": "1.0"}) is None and schema.unsupported_reason({"schema_version": "1.7"}) is None  # only adds fields
    assert "reads 1.x" in schema.unsupported_reason({"schema_version": "2.0"})
    assert "no schema_version" in schema.unsupported_reason({"report_version": "0.4"})
