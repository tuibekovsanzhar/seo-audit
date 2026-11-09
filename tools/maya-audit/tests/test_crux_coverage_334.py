"""DECISIONS 334-335, from the live enpara Akıllı run (audit 2e5829fb). Core Web Vitals asked for the origin the site
lands on (enpara.com -> www.enpara.com), the homepage's own record, "Google'da yeterli ziyaretçi verisi yok" when Google
has none, the figures in the results, the team report and CORE-013, and fetched again for a saved audit; the coverage
line of a sampled audit ("Örneklem: 128 sayfa okundu, 499 bilinen adres okunmadı") with why fewer pages than the limit
were read. Offline: recorded Google answers, a made-up key, synthetic reports and the demo web app."""
from __future__ import annotations

import copy
import json

import httpx
import pytest

from maya_audit import crux, sampling
from maya_audit.sector_audit import REASON, crux_state
from test_web_app import API, get, plan, start, web  # noqa: F401  (fixture)

KEY = "made-up-google-key"
TYPED, FINAL = "https://enpara.test", "https://www.enpara.test"
RECORD = {"record": {"metrics": {
    "largest_contentful_paint": {"percentiles": {"p75": 1400}},
    "interaction_to_next_paint": {"percentiles": {"p75": 322}},
    "cumulative_layout_shift": {"percentiles": {"p75": "0.02"}},
    "first_contentful_paint": {"percentiles": {"p75": 1000}}},
    "collectionPeriod": {"lastDate": {"year": 2026, "month": 11, "day": 7}}}}


def google(answers: dict, seen: list):
    """A recorded Chrome UX Report: {origin or url: status}; 200 answers RECORD."""
    def respond(request):
        body = json.loads(request.content)
        seen.append(body)
        status = answers.get(body.get("origin") or body.get("url"), 404)
        if status == 200:
            return httpx.Response(200, json=RECORD)
        if status == 404:
            return httpx.Response(404, json={"error": {"code": 404, "message": "chrome ux report data not found"}})
        return httpx.Response(status, json={"error": {"message": f"key {KEY} rejected"}})
    return httpx.MockTransport(respond)


# ---------------------------------------------------------------- 1: which origin

def test_the_origin_the_site_lands_on_is_asked_first_then_the_typed_one():
    seen = []
    section = crux.collect(TYPED + "/", KEY, transport=google({FINAL: 200, FINAL + "/": 200}, seen),
                           final_url=FINAL, homepage=FINAL + "/")
    assert section["status"] == "assessed" and section["origin"] == FINAL and section["data_until"] == "2026-11-07"
    assert [b.get("origin") or b.get("url") for b in seen] == [FINAL, FINAL + "/"]
    assert all(b["formFactor"] == "PHONE" for b in seen)
    assert section["homepage"]["status"] == "assessed" and section["homepage"]["url"] == FINAL + "/"
    assert [(a.get("origin") or a.get("url"), a["http_status"]) for a in section["attempts"]] == [(FINAL, 200), (FINAL + "/", 200)]
    assert KEY not in json.dumps(section)


def test_the_typed_origin_is_asked_when_the_final_one_has_no_record():
    seen = []
    section = crux.collect(TYPED + "/", KEY, transport=google({TYPED: 200}, seen), final_url=FINAL, homepage=None)
    assert section["origin"] == TYPED and [b["origin"] for b in seen] == [FINAL, TYPED]


def test_no_record_anywhere_says_google_has_too_little_data():
    section = crux.collect(TYPED + "/", KEY, transport=google({}, []), final_url=FINAL, homepage=FINAL + "/")
    assert section["status"] == "not_available" and section["reason_code"] == "no_data"
    assert f"asked for {FINAL} and {TYPED}" in section["summary"] and section["origins_asked"] == [FINAL, TYPED]
    assert crux_state(section) == "no_data"
    from maya_audit_web import strings, wording
    strings.set_language("tr")
    try:
        said, ok = wording.line(section["summary"], "tr")
        assert ok and said.startswith("Google'da yeterli ziyaretçi verisi yok")
    finally:
        strings.set_language("en")


def test_a_refused_key_is_an_error_not_missing_data():
    section = crux.collect(TYPED + "/", KEY, transport=google({FINAL: 403, TYPED: 403}, []), final_url=FINAL)
    assert section["reason_code"] == "error" and "HTTP 403" in section["summary"] and KEY not in json.dumps(section)
    assert len(section["attempts"]) == 1  # a refused key is the same for every origin


def test_a_section_saved_before_reason_codes_is_read_from_its_sentence():
    old = {"status": "not_available", "summary": crux.NO_DATA, "metrics": []}
    assert crux_state(old) == "no_data" and crux_state(None) == "no_key"
    assert crux_state({"status": "not_available", "summary": crux.NO_KEY}) == "no_key"


# ---------------------------------------------------------------- 1: CORE-013

def _cwv_rows(section):
    from maya_audit import client_selection as cs, sector_audit
    from test_sector_method_324 import _sector_report
    report = _sector_report()
    report["crux"] = section
    res = sector_audit.evaluate(report, cs.select(report, business="bankacilik"), None, "bankacilik")
    return next(r for r in res["core"] if r["id"] == "CORE-013")


def _assessed(lcp=1400, inp=322, cls="0.02"):
    record = copy.deepcopy(RECORD)
    record["record"]["metrics"]["largest_contentful_paint"]["percentiles"]["p75"] = lcp
    record["record"]["metrics"]["interaction_to_next_paint"]["percentiles"]["p75"] = inp
    record["record"]["metrics"]["cumulative_layout_shift"]["percentiles"]["p75"] = cls
    return crux.collect(FINAL + "/", KEY, transport=httpx.MockTransport(lambda r: httpx.Response(200, json=record)), final_url=FINAL)


def test_core_013_is_filled_from_google_figures(monkeypatch):
    row = _cwv_rows(_assessed())
    assert row["durum"] == "Kısmen Uygun" and "INP 322 ms (iyileştirilmeli)" in row["evidence"] and FINAL in row["reason"]
    assert _cwv_rows(_assessed(lcp=4800))["durum"] == "Hatalı"
    good = _cwv_rows(_assessed(inp=150))
    assert good["durum"] == "Kontrol Edilmedi" and good["reason"].startswith("Üç Core Web Vitals metriği de iyi")
    none = _cwv_rows(crux.collect(TYPED + "/", KEY, transport=google({}, []), final_url=FINAL))
    assert none["durum"] == "Kontrol Edilmedi" and none["reason"] == REASON["cwv_no_data"].format(asked=f"{FINAL}, {TYPED}")
    assert _cwv_rows(None)["reason"] == REASON["cwv_no_key"]


# ---------------------------------------------------------------- 1: the team report

def _report_with(section, sampled_report=False):
    from test_team_report import synthetic
    report = synthetic([("STR-2", "str2.no_h1")])
    report["crux"] = section
    return report


@pytest.mark.parametrize("lang,value,sub", [("tr", "2/3 iyi", "INP 322 ms (iyileştirilmeli)"),
                                            ("en", "2/3 good", "INP 322 ms (needs improvement)")])
def test_page_one_shows_google_figures_when_there_is_no_lab_score(tmp_path, lang, value, sub):
    from test_team_report import built
    data = built(tmp_path, _report_with(_assessed()), lang)
    field = next(k for k in data["kpis"] if k["label"].startswith(("Gerçek kullanıcı", "Real users")))
    assert field["value"] == value and field["sub"] == sub and data["field"]["rows"]


def test_page_one_says_google_has_too_little_data(tmp_path):
    from test_team_report import built
    data = built(tmp_path, _report_with(crux.collect(TYPED + "/", KEY, transport=google({}, []), final_url=FINAL)), "tr")
    field = next(k for k in data["kpis"] if k["label"].startswith("Gerçek kullanıcı"))
    assert field["sub"] == "Google'da yeterli ziyaretçi verisi yok" and data["field_none"] == field["sub"]


# ---------------------------------------------------------------- 1: a saved audit

def test_core_web_vitals_fetched_again_for_a_saved_audit(tmp_path):
    folder = tmp_path / "artifacts"
    folder.mkdir()
    report = {"crawl": {"start_url": TYPED + "/", "origin": FINAL,
                        "pages": [{"url": TYPED + "/", "depth": 0, "status": 301}, {"url": FINAL + "/", "depth": 0, "status": 200}]},
              "crux": {"status": "not_available", "summary": crux.NO_DATA, "metrics": [], "origin": TYPED}}
    (folder / "report.json").write_text(json.dumps(report), encoding="utf-8")
    assert crux.targets_of(report) == (TYPED + "/", FINAL, FINAL + "/")
    seen = []
    section = crux.refresh_saved(folder, KEY, transport=google({FINAL: 200, FINAL + "/": 200}, seen))
    assert section["status"] == "assessed" and section["fetched_for_saved_audit"]
    assert json.loads((folder / "report.json").read_text())["crux"]["status"] == "not_available"  # never written
    assert crux.with_saved(report, folder)["crux"]["origin"] == FINAL and KEY not in (folder / crux.SAVED_FILE).read_text()


def test_the_web_app_fetches_them_again_and_every_output_reads_them(web):  # noqa: F811
    client = web()
    audit = start(client, plan(client))
    assert get(client, audit, "/summary")["crux_refresh"]["available"] is False
    refused = client.post(f"{API}/audits/{audit['id']}/crux", json={})
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "crux_no_key"
    engine = client.app.state.runner.engine
    seen = []
    engine.crux_key = lambda: KEY
    engine.crux_transport = google({"http://demo-shop.localhost": 200, "http://demo-shop.localhost/": 200}, seen)
    answer = client.post(f"{API}/audits/{audit['id']}/crux", json={})
    assert answer.status_code == 200 and answer.json()["crux"]["status"] == "assessed"
    view = get(client, audit, "/summary")
    assert view["crux"]["status"] == "assessed" and view["crux_refresh"]["fetched_again"]
    assert view["crux"]["homepage"]["status"] == "assessed"
    # the derived copy (team report, appendix, Sektör audit, brief) reads it too
    from maya_audit_web.team_report import current
    from pathlib import Path
    folder = Path(client.app.state.runner.artifacts(audit["id"]))
    cur = current.current(folder / "report.json")
    assert json.loads(cur.report_path.read_text())["crux"]["status"] == "assessed"
    assert KEY not in client.get(f"{API}/audits/{audit['id']}/result").text


def test_the_results_show_the_origin_the_homepage_and_the_button():
    from pathlib import Path
    script = (Path(__file__).resolve().parents[1] / "maya_audit_web" / "static" / "app.js").read_text(encoding="utf-8")
    assert "function cruxBlock(section, refresh)" in script and 'T("crux.refresh")' in script and 'T("crux.homepage"' in script
    from maya_audit_web.strings import t
    assert t("crux.refresh", "tr") == "Google'dan yeniden al"


# ---------------------------------------------------------------- 2-3: the coverage line of a sampled audit

def _sampled(read=128, cap=150, errors=21, files=1, unread=499, reader_read=(), stop="page_cap"):
    pages = ([{"url": f"{FINAL}/p{i}", "status": 200, "fetch_class": "ok", "content_type": "text/html"} for i in range(read)]
             + [{"url": f"{FINAL}/e{i}", "status": 404, "fetch_class": "ok", "content_type": "text/html"} for i in range(errors)]
             + [{"url": f"{FINAL}/f{i}.xlsx", "status": 200, "fetch_class": "ok", "content_type": "application/vnd.ms-excel"} for i in range(files)]
             + [{"url": f"{FINAL}/r", "status": 301, "fetch_class": "ok"}])
    return {"crawl": {"sampling": {"mode": "smart", "types": {}}, "config": {"max_pages": cap}, "stop_reason": stop,
                      "pages": pages, "not_fetched_urls": [f"{FINAL}/u{i}" for i in range(unread)]},
            "firecrawl": {"used": True, "options": {"read_scope": "needed"},
                          "pages": [{"url": u, "outcome": "read"} for u in reader_read]},
            "audit_status": {"content_coverage": {"level": "complete_sample", "pages_read": read, "known_urls_not_read": 0}}}


def test_the_sample_line_says_pages_read_known_unread_and_why_fewer():
    report = _sampled()
    assert sampling.sample_line(report, "tr") == (
        "Örneklem: 128 sayfa okundu, 499 bilinen adres okunmadı. 150 sayfalık sınırdan 128 sayfa okundu: 21 adres hata "
        "döndü (404 ×21); 1 adres dosyaydı, sayfa değil; sayfa sınırı her sayfa isteğini sayar.")
    assert sampling.sample_line(report, "en").startswith("Sample: 128 pages read, 499 known addresses not read. 128 of the 150-page limit read: 21 addresses answered an error (404 ×21); 1 address was a file, not a page")
    assert sampling.unread_count(_sampled(reader_read=[f"{FINAL}/u0", f"{FINAL}/u1"])) == 497
    done = _sampled(read=120, errors=0, files=0, unread=0, stop="exhausted")
    assert "örneklem planı bitti: sayfa türleri doldu, 30 sayfalık bütçe kaldı" in sampling.sample_line(done, "tr")
    assert sampling.sample_line(_sampled(read=150, errors=0, files=0), "tr") == "Örneklem: 150 sayfa okundu, 499 bilinen adres okunmadı."
    not_sampled = _sampled()
    not_sampled["crawl"]["sampling"] = None
    assert sampling.sample_line(not_sampled) is None and sampling.known_not_read(not_sampled) == 0


def test_the_engine_counts_maya_s_unread_addresses_when_the_reader_read_only_where_needed():
    from types import SimpleNamespace
    from maya_audit.report import known_unread
    result = SimpleNamespace(not_fetched_urls=[f"{FINAL}/u{i}" for i in range(5)])
    section = {"used": True, "options": {"read_scope": "needed"}, "coverage": {"known_urls_not_requested": 0},
               "pages": [{"url": f"{FINAL}/u0", "outcome": "read"}, {"url": f"{FINAL}/p", "outcome": "read"}]}
    assert known_unread(result, section) == 4
    assert known_unread(result, {**section, "options": {"read_scope": "all"}}) == 0


@pytest.mark.parametrize("lang", ["tr", "en"])
def test_page_one_the_limits_and_the_brief_say_the_same_sample(tmp_path, lang):
    from test_team_report import built, synthetic
    from maya_audit_web.team_report import brief
    report = synthetic([("STR-2", "str2.no_h1")])
    sample = _sampled()
    report["crawl"] = {**report.get("crawl", {}), **sample["crawl"]}
    report["firecrawl"] = sample["firecrawl"]
    report.setdefault("audit_status", {})["content_coverage"] = sample["audit_status"]["content_coverage"]
    data = built(tmp_path, report, lang)
    line = sampling.sample_line(report, lang)
    text = json.dumps(data, ensure_ascii=False)
    assert line in data["client"]["limits"] if "client" in data else line in text
    pages = next(k for k in data["kpis"] if k["value"] == "128")
    assert pages["sub"] == ("Örneklem · 499 bilinen adres okunmadı" if lang == "tr" else "Sample · 499 known addresses not read")
    assert data["meta"]["coverage_level"] == "sample"
    assert "Keşfedilen bütün sayfalar okundu" not in text and "Every discovered page was read" not in text
    assert "Complete sample" not in text and "Örneklem tamam" not in text
    assert brief.coverage_line(report, 128, lang) == line


def test_the_web_results_say_sample_not_every_page_found():
    from maya_audit_web import strings, summary
    report = _sampled()
    report["audit_status"].update(direct_access={"state": "readable", "note": "x"},
                                  vendor_crawler_evidence={"state": "not_measured", "note": "y"}, summary="z")
    report["audit_status"]["content_coverage"].update(reasons=[], note="every address found", read_by={}, other_addresses={})
    for lang, label in (("en", "Sample"), ("tr", "Örneklem")):
        strings.set_language(lang)
        try:
            row = next(r for r in summary.status_view(report)["rows"] if r["id"] == "content_coverage")
        finally:
            strings.set_language("en")
        assert row["state"] == "sample" and row["state_label"] == label and row["note"] == sampling.sample_line(report, lang)
