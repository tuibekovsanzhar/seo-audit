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
            # The catalogue's approved steps may name a heading tag (<h1>); no other digit, in either source.
            if re.search(r"\d", re.sub(r"</?h[1-6]>", "", value)) or "{" in value \
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
    return {"schema_version": "1.24", "checks": [{"check_id": f["check_id"], "findings": [f]} for f in findings],
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
    assert data["assessment"]["headline"] == "Sorunlar orta önemde; önce sayfa HTML ağırlığı ve ortak başlık ve açıklamalar."
    assert data["priorities"][0]["title"] == first["summary"]
    assert data["priorities"][0]["text"] == first["explanation"]
    assert data["next_action"]["lead"] == "Önce sayfa HTML'ini hafifletin."
    assert data["next_action"]["text"].startswith(first["explanation"])
    en = built(tmp_path, synthetic(batch, "S3"), "en")
    assert en["assessment"]["headline"].startswith("Issues are medium severity; start with page HTML weight")


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
    assert team == {"pdf": f"/api/v1/audits/{audit['id']}/downloads/team", "xlsx": f"/api/v1/audits/{audit['id']}/downloads/xlsx",
                    "default_lang": "tr"}
    script = (ROOT / "maya_audit_web" / "static" / "app.js").read_text(encoding="utf-8")
    assert 'T("team.pdf")' in script and 'T("team.xlsx")' in script and 'choice("tr"), choice("en")' in script
    tr = json.loads((ROOT / "maya_audit_web" / "locales" / "tr.json").read_text(encoding="utf-8"))
    assert tr["team.pdf"] == "Ekip raporu (PDF)" and tr["team.xlsx"] == "Ek (XLSX)"


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
    from maya_audit_web.team_report import render
    from maya_audit import xlsx
    assert xlsx.read(web_file) == xlsx.read(render.appendix_bytes(report, affected, {}, "tr")[0])


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
    assert response.headers["content-disposition"].endswith('-ekip-raporu.pdf"')
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
