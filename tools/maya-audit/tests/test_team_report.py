"""DECISIONS 307: one place for reports. The web app builds the team report (the maya-audit-pro design) and its XLSX
appendix by itself, from the same template and the same text library the skill renders with; the text library covers
every rule in Turkish and English; no report has an empty text field; the skill may polish words, never severities,
counts or order; a blocked report says why in plain words.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from maya_audit.client_selection import MERGE_GROUPS
from maya_audit.schema import SCHEMA_VERSION
from maya_audit_web.team_report import build_data, service, texts, validate_data
from maya_audit_web.runner import REPORT_JSON
from test_web_app import API, audit_of, error, web  # noqa: F401  (fixture)

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".agents" / "skills" / "maya-audit-pro" / "scripts"
RULES = sorted({(check, rule) for check, rows in json.loads((ROOT / "maya_audit" / "rule_ids.json").read_text(
    encoding="utf-8"))["rules"].items() for rule, _ in rows}, key=lambda pair: pair[1])
EN_WORDS = validate_data.EN_WORDS
TR_CHARS = validate_data.TR_CHARS
SITE = "https://shop.example"


def _note_topics() -> set[str]:
    B = build_data.Builder
    return ({label for label in B.HYGIENE_OBS.values()} | {label for label in B.CONTENT_OBS.values()}
            | {label for _, _, label in B.PERF_INFO} | {label for _, _, label in B.SHARE_INFO}
            | set(build_data.KIND_SCHEMA.values()) | {"WebSite", "BreadcrumbList", "Organization", "llms.txt links that redirect"})


def _texts_of(entry: dict) -> list[tuple[str, str]]:
    out = [(f, entry[f]) for f in texts.LIMITS if isinstance(entry.get(f), str)]
    out += [(f"steps[{i}]", s) for i, s in enumerate(entry.get("steps") or [])]
    out += [(f"{p}[{i}]", s) for p, lines in (entry.get("steps_by_platform") or {}).items() for i, s in enumerate(lines)]
    return out


@pytest.mark.parametrize("lang", texts.LANGS)
def test_every_rule_and_merge_group_has_every_text_field(lang):
    lib = texts.library(lang)
    missing = [rule for _, rule in RULES if rule not in lib["rules"]]
    assert missing == [], f"rules with no {lang} text: {missing}"
    entries = [(rule, texts.rule(rule, lang)) for _, rule in RULES] + [(g["id"], texts.group(g["id"], lang)) for g in MERGE_GROUPS]
    problems = []
    for name, entry in entries:
        for field in texts.FIELDS:
            if not entry.get(field):
                problems.append(f"{name}.{field}: empty")
        if not 2 <= len(entry.get("steps") or []) <= texts.STEP_LINES:
            problems.append(f"{name}.steps: {len(entry.get('steps') or [])} steps")
        for field, value in _texts_of(entry):
            limit = texts.LIMITS.get(field, texts.STEP_CHARS)
            if len(value) > limit:
                problems.append(f"{name}.{field}: {len(value)} > {limit}")
            # The catalogue's approved steps may name a heading tag (<h1>, or "H1 etiketi" as the SEO team writes it,
            # DECISIONS 338) and the HTTP status codes of the SEO team's card titles (301, 302, 404, 410: DECISIONS 343); no
            # other digit, in either source.
            if re.search(r"\d", re.sub(r"</?h[1-6]>|\bH[1-6]\b|\b(?:301|302|404|410)\b", "", value)) or "{" in value \
                    or re.search(r"\bLG-\d|\b(?:ACC|IDX|STR|RND|PRF|TSEO|ANS)-\d", value):
                problems.append(f"{name}.{field}: digit, placeholder or internal code: {value!r}")
            if lang == "tr" and EN_WORDS.search(value):
                problems.append(f"{name}.{field}: English word in Turkish: {value!r}")
            if lang == "en" and TR_CHARS.search(value):
                problems.append(f"{name}.{field}: Turkish letter in English: {value!r}")
            if "firecrawl" in value.lower():
                problems.append(f"{name}.{field}: vendor name")
    assert problems == []


def test_both_languages_have_the_same_structure():
    tr, en = texts.library("tr"), texts.library("en")
    for section in ("rules", "groups", "notes", "page1", "blocked", "generic"):
        assert set(tr[section]) == set(en[section]), section
    for rule in tr["rules"]:
        assert set(tr["rules"][rule].get("steps_by_platform") or {}) == set(en["rules"][rule].get("steps_by_platform") or {}), rule


@pytest.mark.parametrize("lang", texts.LANGS)
def test_every_note_card_topic_has_a_step_and_a_summary(lang):
    notes = texts.library(lang)["notes"]
    assert all(notes.get(topic, {}).get("step") and notes[topic].get("summary") for topic in _note_topics()), \
        sorted(t for t in _note_topics() if t not in notes)


def test_a_conditional_catalogue_step_is_never_printed_by_the_library():
    catalogue = json.loads((ROOT / "maya_audit" / "rule_actions.json").read_text(encoding="utf-8"))["actions"]
    for rule, entry in catalogue.items():
        for lang in texts.LANGS:
            conditional = {line for n, line in enumerate(entry["steps"][lang])
                           if n < len(entry.get("step_when") or []) and entry["step_when"][n]}
            assert not conditional & set(texts.rule(rule, lang)["steps"]), rule


# ---------------------------------------------------------------- built reports

def synthetic(batch, severity="S4"):
    """One card per rule: a finding of each rule id on its own page."""
    findings = []
    for n, (check, rule) in enumerate(batch):
        url = f"{SITE}/p{n}"
        findings.append({"id": f"{check}-{n:08x}", "check_id": check, "rule_id": rule, "title": "Something about the page",
                         "severity": severity, "confidence": "verified", "scope": {"kind": "pages", "count": 1, "urls": [url]},
                         "how_to_fix": "", "expected": "", "evidence": {"pages": [url]},
                         "verification": {"state": "not_retested", "reason": "not re-tested in this test"}})
    pages = [{"url": f"{SITE}/p{n}", "status": 200} for n in range(len(batch))] + [{"url": SITE + "/", "status": 200}]
    return {"schema_version": SCHEMA_VERSION, "checks": [{"check_id": f["check_id"], "findings": [f]} for f in findings],
            "findings_in_priority_order": [f["id"] for f in findings],
            "problem_summary": {"problems": len(findings), "by_severity": {severity: len(findings)}, "by_page": [],
                                "whole_site": {"problems": 0}},
            "crawl": {"origin": SITE, "started_at": "2026-11-01T00:00:00+00:00", "pages": pages},
            "audit_status": {"content_coverage": {"pages_read": len(pages), "level": "partial"}}}


def built(tmp_path, report, lang):
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    return build_data.build_from_files(path, lang)[0]


def visible_strings(value, path=""):
    if isinstance(value, dict):
        for k, v in value.items():
            if not str(k).startswith("_"):
                yield from visible_strings(v, f"{path}.{k}" if path else str(k))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from visible_strings(v, f"{path}[{i}]")
    elif isinstance(value, str):
        yield path, value


@pytest.mark.parametrize("lang", texts.LANGS)
@pytest.mark.parametrize("severity", ["S3", "S4"])
def test_no_report_has_an_empty_text_field_for_any_rule(tmp_path, lang, severity):
    for start in range(0, len(RULES), 10):
        data = built(tmp_path, synthetic(RULES[start:start + 10], severity), lang)
        slots = {s["path"] for s in data["_slots"]}
        empty = [p for p, v in visible_strings(data) if p in slots and (not v.strip() or "⟪" in v)]
        assert empty == [], (RULES[start:start + 10], empty)
        checked = validate_data.check(data)
        assert [e["text"] for e in checked["errors"]] == [], RULES[start:start + 10]


def test_page_one_is_built_from_the_top_cards(tmp_path):
    batch = [("RND-6", "rnd6.large"), ("STR-1", "str1.shared"), ("STR-2", "str2.no_h1")]
    data = built(tmp_path, synthetic(batch, "S3"), "tr")
    first = texts.group("html_weight", "tr")
    assert data["assessment"]["headline"] == "3 orta önemde sorun var; öncelik: sayfa HTML ağırlığı ve ortak başlık ve açıklamalar."  # DECISIONS 313: exact counts
    assert data["priorities"][0]["title"] == first["summary"]
    assert data["priorities"][0]["text"] == first["explanation"]
    assert data["next_action"]["lead"] == "Önce sayfa HTML'ini hafifletin."
    assert data["next_action"]["text"].startswith(first["explanation"])
    en = built(tmp_path, synthetic(batch, "S3"), "en")
    assert en["assessment"]["headline"].startswith("There are 3 medium-severity issues; start with the page HTML weight")


def test_polishing_words_is_allowed_but_not_severity_count_or_order(tmp_path):
    report = synthetic([("STR-2", "str2.no_h1"), ("STR-14", "str14.no_text")], "S4")
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    data, _ = build_data.build_from_files(path, "en")
    data["assessment"]["headline"] = "Low-severity issues; begin with the main headings."
    data["todos"][0]["steps"] = "Add one main heading\nDefine it once in the template"
    assert [e for e in validate_data.check(data)["errors"] if e["kind"] == "locked"] == []
    for change in (lambda d: d["todos"][0].update(severity="S2"), lambda d: d["kpis"][0].update(value="9"),
                   lambda d: d["todos"].reverse(), lambda d: d["findings"][0].update(scope="40 pages")):
        changed = json.loads(json.dumps(data))
        change(changed)
        assert [e["kind"] for e in validate_data.check(changed)["errors"]].count("locked") == 1


def test_a_report_with_nothing_read_is_blocked_with_a_plain_reason(tmp_path):
    report = synthetic([("STR-2", "str2.no_h1")])
    report["audit_status"]["content_coverage"]["pages_read"] = 0
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    out = service.build(path, "tr")
    assert out.blocked and out.pdf is None
    assert texts.library("tr")["blocked"]["RG-14"] in out.reasons
    assert any("RG-14" in line for line in out.details)


# ---------------------------------------------------------------- the web app

@pytest.fixture
def finished(web):  # noqa: F811
    client = web()
    audit = audit_of(client)
    assert audit["state"] == "finished"
    return client, audit, client.app.state.runner.artifacts(audit["id"])


def test_the_results_page_offers_the_team_report_in_turkish_first(finished):
    client, audit, _ = finished
    view = client.get(f"{API}/audits/{audit['id']}").json()
    result = client.get(f"{API}/audits/{audit['id']}/summary").json() if "team_report" not in view else view
    team = result.get("team_report") or {}
    assert team == {"prepare": f"/api/v1/audits/{audit['id']}/team-report", "pdf": f"/api/v1/audits/{audit['id']}/downloads/team",
                    "xlsx": f"/api/v1/audits/{audit['id']}/downloads/xlsx", "default_lang": "tr",
                    "brief": f"/api/v1/audits/{audit['id']}/client-brief",
                    # DECISIONS 324: the team's sector audit workbook
                    "sector": f"/api/v1/audits/{audit['id']}/downloads/sector", "sector_name": team["sector_name"],
                    "maya": f"/api/v1/audits/{audit['id']}/maya-data"}  # DECISIONS 352: the optional Maya data upload
    script = (ROOT / "maya_audit_web" / "static" / "app.js").read_text(encoding="utf-8")
    # DECISIONS 310: the Downloads card (team report PDF, appendix XLSX, client brief: DECISIONS 319), one language switch.
    assert 'T("download.pdf.title")' in script and 'T("download.xlsx.title")' in script and 'choice("tr"), choice("en")' in script
    assert 'team.prepare + "?lang=" + asked' in script and 'download: body.pdf.filename' in script
    tr = json.loads((ROOT / "maya_audit_web" / "locales" / "tr.json").read_text(encoding="utf-8"))
    assert tr["download.pdf.title"] == "Ekip raporu (PDF)" and tr["download.xlsx.title"] == "Ek (XLSX)"
    assert tr["download.brief.title"] == "Müşteri özeti (PDF)"


def test_a_blocked_team_report_says_why_in_plain_words(finished):
    client, audit, folder = finished
    path = folder / REPORT_JSON
    report = json.loads(path.read_text(encoding="utf-8"))
    report["audit_status"]["content_coverage"]["pages_read"] = 0
    path.write_text(json.dumps(report), encoding="utf-8")
    body = error(client.get(f"{API}/audits/{audit['id']}/downloads/team"), 422, "team_report_blocked")
    assert body["message"] == "Ekip raporu üretilmedi"
    assert texts.library("tr")["blocked"]["RG-14"] in body["details"]["reasons"]
    en = error(client.get(f"{API}/audits/{audit['id']}/downloads/team", params={"lang": "en"}), 422, "team_report_blocked")
    assert texts.library("en")["blocked"]["RG-14"] in en["details"]["reasons"]


def test_the_web_appendix_is_the_skills_appendix(finished, tmp_path):
    client, audit, folder = finished
    web_file = client.get(f"{API}/audits/{audit['id']}/downloads/xlsx", params={"lang": "tr"}).content
    report = json.loads((folder / REPORT_JSON).read_text(encoding="utf-8"))
    affected = json.loads((folder / "affected-urls.json").read_text(encoding="utf-8")) if (folder / "affected-urls.json").is_file() else None
    from maya_audit_web.team_report import build_data, render
    from maya_audit import xlsx
    # DECISIONS 322: both carry the team report's cards ("Özet"); the skill passes its data.json's todos.
    data, _ = build_data.build_from_files(folder / REPORT_JSON, "tr", audit_id=audit["id"],
                                          affected_path=folder / "affected-urls.json" if (folder / "affected-urls.json").is_file() else None)
    current = json.loads(Path(data["_report_path"]).read_text(encoding="utf-8"))
    current_affected = json.loads(Path(data["_affected_path"]).read_text(encoding="utf-8")) if data.get("_affected_path") else None
    assert xlsx.read(web_file) == xlsx.read(render.appendix_bytes(current, current_affected, {}, "tr", todos=data["todos"])[0])


def _skill(*args, cwd):
    run = subprocess.run([sys.executable, *map(str, args)], capture_output=True, text=True, encoding="utf-8", cwd=cwd)
    assert run.returncode == 0, run.stdout + run.stderr
    return run.stdout


def _pngs(pdf: bytes, folder: Path) -> list[bytes]:
    from maya_audit_web.team_report import render
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "r.pdf").write_bytes(pdf)
    render.write_previews(folder / "r.pdf", folder / "png")
    return [p.read_bytes() for p in sorted((folder / "png").glob("*.png"), key=lambda p: int(re.sub(r"\D", "", p.stem)))]


@pytest.mark.slow
def test_the_web_app_and_the_skill_print_the_same_report_and_a_manual_check_rebuilds_it(finished, tmp_path):
    pytest.importorskip("playwright")
    client, audit, folder = finished
    response = client.get(f"{API}/audits/{audit['id']}/downloads/team")
    assert response.status_code == 200, response.text
    assert response.headers["content-disposition"].endswith('-ekip-raporu-tr.pdf"')
    web_pages = _pngs(response.content, tmp_path / "web")
    out = tmp_path / "skill"
    out.mkdir()
    _skill(SKILL / "build_data.py", folder / REPORT_JSON, "--lang", "tr", "-o", out / "data.json", cwd=SKILL)
    _skill(SKILL / "validate_data.py", out / "data.json", cwd=SKILL)
    _skill(SKILL / "render.py", out / "data.json", "-o", out / "r.html", "--pdf", out / "r.pdf", cwd=SKILL)
    skill_pages = _pngs((out / "r.pdf").read_bytes(), tmp_path / "skill-png")
    assert len(web_pages) == len(skill_pages) == int(response.headers["x-maya-pages"])
    assert [n for n, (a, b) in enumerate(zip(web_pages, skill_pages), 1) if a != b] == []
    # A manual check in "Teyit edin" rebuilds the report on the next download.
    pending = client.get(f"{API}/audits/{audit['id']}/review").json()["confirm"]
    assert pending, "the demo audit has a finding to confirm first"
    if pending:
        posted = client.post(f"{API}/audits/{audit['id']}/review", headers={"X-Maya-Token": client.get(f"{API}/session").json()["token"]},
                             json={"finding_id": pending[0]["finding_id"], "result": "rejected", "by": "test", "seen": "not seen"})
        assert posted.status_code == 200, posted.text
        again = client.get(f"{API}/audits/{audit['id']}/downloads/team")
        assert again.status_code == 200 and again.content != response.content


# ---------------------------------------------------------------- DECISIONS 308

def _old(folder: Path) -> bytes:
    """Make the saved report look written by an older engine (schema 1.20); returns its bytes."""
    path = folder / REPORT_JSON
    report = json.loads(path.read_text(encoding="utf-8"))
    report["schema_version"] = "1.20"
    path.write_text(json.dumps(report), encoding="utf-8")
    return path.read_bytes()


def test_a_saved_report_is_re_evaluated_with_the_current_engine_and_never_written(finished):
    from maya_audit_web.team_report import current
    _, audit, folder = finished
    before = _old(folder)
    affected_before = (folder / "affected-urls.json").read_bytes()
    cur = current.current(folder / REPORT_JSON)
    assert cur.reassessed and cur.report_path == folder.parent / "current-engine" / REPORT_JSON
    assert (folder / REPORT_JSON).read_bytes() == before and (folder / "affected-urls.json").read_bytes() == affected_before
    made = json.loads(cur.report_path.read_text(encoding="utf-8"))
    engine = made["generation"]["analysis"]["engine"]
    assert engine["fingerprint"] == current.fingerprint() and engine["schema"] and engine["version"]
    assert made["generation"]["analysis"]["requests"] == 0
    line = current.line(cur, "tr")
    assert line.startswith("Güncel motorla yeniden değerlendirildi (Maya Audit ") and engine["schema"] in line
    assert current.line(cur, "en").startswith("Re-evaluated with the current engine (Maya Audit ")
    # Made once: the next call reads the copy; a change to the source makes it again.
    stamp = cur.report_path.stat().st_mtime_ns
    assert current.current(folder / REPORT_JSON).report_path.stat().st_mtime_ns == stamp
    (folder / REPORT_JSON).write_bytes(before + b" ")
    assert current.current(folder / REPORT_JSON).report_path.stat().st_mtime_ns != stamp
    # A copy is current only for the engine that made it; a report of the current schema is used as written.
    assert not current._is_current(made, "another-engine") and current._is_current(made, current.fingerprint())
    fresh = dict(made, generation={k: v for k, v in made["generation"].items() if k != "analysis"})
    fresh["schema_version"] = __import__("maya_audit.schema", fromlist=["SCHEMA_VERSION"]).SCHEMA_VERSION
    assert current._is_current(fresh, current.fingerprint())


def test_confirm_first_the_team_report_and_the_appendix_read_the_current_engine_copy(finished, monkeypatch):
    """A finding only the current engine finds can be confirmed in "Teyit edin", and that one review file counts in
    the web app's report and in the skill's (both build through build_from_files)."""
    from maya_audit import reassess_rules
    client, audit, folder = finished
    _old(folder)
    real = reassess_rules.apply

    def apply(report, affected=None, **kw):  # the current engine adds one finding a saved report does not have
        new, aff, record = real(report, affected, **kw)
        check = next(c for c in new["checks"] if c.get("findings"))
        added = dict(check["findings"][0], id="NEW-1-0000aaaa", title="Found only by the current engine")
        check["findings"].append(added)
        aff[added["id"]] = list(aff.get(check["findings"][0]["id"]) or [])
        return new, aff, record
    monkeypatch.setattr(reassess_rules, "apply", apply)
    token = client.get(f"{API}/session").json()["token"]
    posted = client.post(f"{API}/audits/{audit['id']}/review", headers={"X-Maya-Token": token},
                         json={"finding_id": "NEW-1-0000aaaa", "result": "rejected", "by": "owner", "seen": "not on the page"})
    assert posted.status_code == 200, posted.text
    review = folder / "review.json"
    # The added finding shares its group with the one it copies: the check covers the group (DECISIONS 309).
    saved = [e["finding_id"] for e in json.loads(review.read_text(encoding="utf-8"))["entries"]]
    assert "NEW-1-0000aaaa" in saved and posted.json()["saved"]["finding_ids"] == saved
    assert not (folder.parent / "current-engine" / "review.json").exists()  # one review file, the audit's
    data, notes = build_data.build_from_files(folder / REPORT_JSON, "tr")  # the skill's build step
    assert data["_review_path"] == str(review) and "NEW-1-0000aaaa" in data["_confirmations"]
    assert any("Güncel motorla" in line for line in notes)
    assert any(line["k"] == "Değerlendirme:" for line in data["provenance"]["lines"])
    assert data["_report_path"] == str(folder.parent / "current-engine" / REPORT_JSON)


def test_the_downloads_section_names_the_short_summary_apart_from_the_team_report(finished):
    client, audit, _ = finished
    view = client.get(f"{API}/audits/{audit['id']}/summary").json()
    formats = [d["format"] for d in view["downloads"]]
    assert "xlsx" not in formats  # the appendix is the team report's, in its section
    label = next(d["label"] for d in view["downloads"] if d["format"] == "pdf")
    assert label.startswith("Short technical summary (PDF, ") and "team" not in label.lower()
    tr = json.loads((ROOT / "maya_audit_web" / "locales" / "tr.json").read_text(encoding="utf-8"))
    assert tr["result.download.pdf"] == "Kısa teknik özet (PDF, {language})" and tr["result.downloads"] == "Diğer indirmeler"
    script = (ROOT / "maya_audit_web" / "static" / "app.js").read_text(encoding="utf-8")
    assert script.index("teamReport(view.team_report)") < script.index('T("result.downloads")')


def _template_phrases(lang: str) -> set[str]:
    """Fixed wording of one language's templates (labels and library), as whitespace-free fragments of 14+ letters
    that the other language does not use as well: printed in the other language's report, they mean a mix-up."""
    from maya_audit_web.team_report import build_data as B

    def strings(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for v in value.values():
                yield from strings(v)
        elif isinstance(value, list):
            for v in value:
                yield from strings(v)
    from maya_audit.client_appendix import WORDS
    labels = B.load(B.REFS / "etiketler.json")
    other = "en" if lang == "tr" else "tr"
    sources = [labels[lang], texts.library(lang)["page1"], texts.library(lang)["blocked"], WORDS[lang]]
    mine = {re.sub(r"\s+", "", part) for s in (x for src in sources for x in strings(src))
            for part in re.split(r"\{[^}]*\}|\[\[|\]\]|[0-9]", s)}
    theirs = {re.sub(r"\s+", "", part) for s in strings([labels[other], texts.library(other), WORDS[other]])
              for part in re.split(r"\{[^}]*\}|\[\[|\]\]|[0-9]", s)}
    return {p for p in mine if len(p) >= 10 and not any(p in t for t in theirs)}


def _pdf_text(content: bytes) -> str:
    import io
    from pypdf import PdfReader
    return re.sub(r"\s+", "", "".join(page.extract_text() for page in PdfReader(io.BytesIO(content)).pages))


def _xlsx_text(content: bytes) -> str:
    from maya_audit import xlsx
    sheets = xlsx.read(content)
    return re.sub(r"\s+", "", " ".join(list(sheets) + [str(v) for rows in sheets.values() for row in rows for v in row
                                                        if isinstance(v, str)]))


@pytest.mark.slow
def test_each_language_downloads_only_that_language_through_the_real_routes(finished):
    """The TR/EN switch: GET /team-report?lang= builds that language, its link serves that file under a name with the
    language, and the PDF and XLSX hold no template text of the other language (the demo site's own words are
    English, so the English report must hold no Turkish letter at all)."""
    pytest.importorskip("playwright")
    pytest.importorskip("pypdf")
    client, audit, _ = finished
    base = f"{API}/audits/{audit['id']}"
    got = {}
    for lang in ("tr", "en", "tr"):  # back to Turkish: nothing of the first build is reused for the other language
        prepared = client.get(f"{base}/team-report", params={"lang": lang})
        assert prepared.status_code == 200, prepared.text
        body = prepared.json()
        assert body["lang"] == lang and f"lang={lang}" in body["pdf"]["url"] and f"lang={lang}" in body["xlsx"]["url"]
        pdf = client.get(body["pdf"]["url"])
        xlsx_file = client.get(body["xlsx"]["url"])
        assert pdf.status_code == 200 and xlsx_file.status_code == 200
        assert pdf.headers["x-maya-language"] == lang and xlsx_file.headers["x-maya-language"] == lang
        names = (pdf.headers["content-disposition"], xlsx_file.headers["content-disposition"])
        assert names[0].endswith('-ekip-raporu-tr.pdf"' if lang == "tr" else '-team-report-en.pdf"')
        assert names[1].endswith('-ek-tr.xlsx"' if lang == "tr" else '-appendix-en.xlsx"')
        assert body["pdf"]["filename"] in names[0] and body["xlsx"]["filename"] in names[1]
        # Without the page's build token the route builds the language asked for, too.
        direct = client.get(f"{base}/downloads/team", params={"lang": lang})
        assert direct.headers["x-maya-language"] == lang
        got[lang] = (_pdf_text(pdf.content), _xlsx_text(xlsx_file.content))
    # A token is served only for its own language: asking English with a Turkish build's token builds English.
    tr_token = client.get(f"{base}/team-report", params={"lang": "tr"}).json()["pdf"]["url"].split("build=")[1]
    crossed = client.get(f"{base}/downloads/team", params={"lang": "en", "build": tr_token})
    assert crossed.headers["x-maya-language"] == "en" and crossed.headers["content-disposition"].endswith('-team-report-en.pdf"')
    tr_phrases, en_phrases = _template_phrases("tr"), _template_phrases("en")
    # DECISIONS 342: the team's checklist names its Turkish items with English words ("Önemli URL HTTP status"); they
    # are the team's own wording, not a template of the other language.
    from maya_audit import checklist
    names = {"tr": [re.sub(r"\s+", "", x) for it in checklist.items() for x in (it["item"], it["group"])], "en": []}
    for lang, (pdf_text, xlsx_text) in got.items():
        foreign = en_phrases if lang == "tr" else tr_phrases
        own = tr_phrases if lang == "tr" else en_phrases
        for name, text in (("PDF", pdf_text), ("XLSX", xlsx_text)):
            for own_name in sorted(names[lang], key=len, reverse=True):
                text = text.replace(own_name, "")
            leaked = sorted(p for p in foreign if p in text)
            assert leaked == [], f"{lang} {name} holds the other language's template text: {leaked[:5]}"
        assert sum(p in pdf_text for p in own) >= 10, f"the {lang} PDF holds too little of its own templates"
        assert sum(p in xlsx_text for p in own) >= 5, f"the {lang} XLSX holds too little of its own templates"
    assert not re.search(r"[ğışİŞĞ]", got["en"][0] + got["en"][1]), "the English report holds Turkish letters"
    assert re.search(r"[ğışİŞ]", got["tr"][0]) and re.search(r"[ğışİŞ]", got["tr"][1])


def test_a_report_the_current_engine_cannot_re_read_is_used_as_saved_and_says_so(finished, monkeypatch):
    from maya_audit import reassess_rules
    _, _, folder = finished
    _old(folder)

    def broken(*args, **kwargs):
        raise KeyError("fetch_class")
    monkeypatch.setattr(reassess_rules, "apply", broken)
    data, notes = build_data.build_from_files(folder / REPORT_JSON, "tr")
    assert data["_reassess_failed"] == "KeyError: 'fetch_class'" and data["_report_path"] == str(folder / REPORT_JSON)
    assert any("UYARI: güncel motorla yeniden değerlendirilemedi" in line for line in notes)
    assert data["provenance"]["lines"][-1] == {"k": "Değerlendirme:", "v": "Güncel motorla yeniden değerlendirilemedi; "
                                                                        "rapor kaydedildiği hâliyle kullanıldı."}
