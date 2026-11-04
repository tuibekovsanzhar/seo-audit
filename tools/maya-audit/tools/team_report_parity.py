"""The team report made by the web app vs the maya-audit-pro skill, offline (DECISIONS 307).

    .venv/bin/python tools/team_report_parity.py <artifacts folder of a saved audit> --out DIR [--lang tr|en]
        [--approved data.json] [--label NAME] [--review review.json]

The artifacts folder (report.json, affected-urls.json, review.json, evidence/) is copied into DIR; the real web folder
is only read. `--review` uses another review file (the owner's manual checks) instead of the folder's. The web path: an
isolated web app (`create_app` on DIR/web, the copy served as an `analysis-*` entry) answers GET /team-report and the
two links it returns over HTTP, as the "Ekip raporu (PDF)" and "Ek (XLSX)" buttons ask; both re-evaluate the saved
audit with the current engine first (DECISIONS 308), into DIR/analyses/<id>/current-engine/. The skill
path: the skill's build_data.py, validate_data.py and render.py on the same copy. Every page of both PDFs is rendered
to PNG and compared; the result and, with --approved, the text fields that differ from an approved data.json are
written to DIR/parity.md. No request leaves this computer: no crawl, no provider, the renderer refuses the network.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import zlib
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SKILL = ROOT / ".agents" / "skills" / "maya-audit-pro" / "scripts"


def png_pixels(data: bytes) -> bytes:
    """The decompressed image data of a PNG (enough to tell how much of two same-size pages differs)."""
    pos, chunks = 8, []
    while pos < len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        if kind == b"IDAT":
            chunks.append(data[pos + 8:pos + 8 + length])
        pos += 12 + length
    return zlib.decompress(b"".join(chunks))


def pages_png(pdf: Path, folder: Path) -> list[Path]:
    from maya_audit_web.team_report import render
    render.write_previews(pdf, folder)
    return sorted(folder.glob("*.png"), key=lambda p: int(re.sub(r"\D", "", p.stem) or 0))


def manifest(audit_id: str, report: dict) -> dict:
    crawl = report.get("crawl") or {}
    origin = crawl.get("origin") or crawl.get("start_url") or "https://site.invalid/"
    host = re.sub(r"^www\.", "", re.sub(r"^https?://", "", origin).split("/")[0])
    started = crawl.get("started_at") or datetime.now(timezone.utc).isoformat()
    return {"id": audit_id, "plan_id": "0" * 32, "project_id": host, "url": origin, "mode": "standard", "key_pages": [],
            "backlinks": False, "approved_usd": 0.0, "config": {}, "state": "finished", "outcome": "COMPLETE",
            "outcome_reason": "", "crawl_stop": None, "error_code": None, "progress": {}, "sessions": 1, "paid_state": "done",
            "queue_seq": 1, "created_at": started, "started_at": started, "finished_at": started,
            "firecrawl": {"state": "none", "options": {}, "approved_credits": 0.0, "attempts": []}, "language": "tr", "flags": {}}


def web_path(work: Path, analysis_id: str, lang: str):
    from fastapi.testclient import TestClient
    from maya_audit_web.app import create_app
    client = TestClient(create_app(work / "web", port=8770, analysis_folder=work / "analyses"), base_url="http://127.0.0.1:8770")
    with client:
        client.get("/")
        base = f"/api/v1/audits/{analysis_id}"
        prepared = client.get(f"{base}/team-report", params={"lang": lang})
        if prepared.status_code != 200:
            return prepared, None, None
        body = prepared.json()
        team = client.get(body["pdf"]["url"])
        xlsx = client.get(body["xlsx"]["url"])
    return team, xlsx, body


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("artifacts")
    ap.add_argument("--out", required=True)
    ap.add_argument("--lang", default="tr", choices=["tr", "en"])
    ap.add_argument("--approved", default=None, help="an approved data.json to list text differences against")
    ap.add_argument("--label", default="team-report")
    ap.add_argument("--review", default=None, help="a review.json to use instead of the artifacts folder's")
    a = ap.parse_args()
    out = Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    analysis_id = "analysis-" + re.sub(r"[^a-z0-9-]+", "-", a.label.lower()).strip("-")[:50]
    art = out / "analyses" / analysis_id / "artifacts"
    if art.exists():
        shutil.rmtree(art.parent)
    art.mkdir(parents=True)
    for name in ("report.json", "affected-urls.json", "review.json", "dataforseo.json"):
        if (Path(a.artifacts) / name).is_file():
            shutil.copy2(Path(a.artifacts) / name, art / name)
    if (Path(a.artifacts) / "evidence").is_dir():
        shutil.copytree(Path(a.artifacts) / "evidence", art / "evidence")
    if a.review:
        shutil.copy2(a.review, art / "review.json")
    report = json.loads((art / "report.json").read_text(encoding="utf-8"))
    record = {"audit": manifest(analysis_id, report),
              "analysis": {"id": analysis_id, "label": a.label, "processed_at": datetime.now(timezone.utc).isoformat(),
                           "analysis_version": "team-report-parity", "source_audit_id": "0" * 32,
                           "report_sha256": hashlib.sha256((art / "report.json").read_bytes()).hexdigest()}}
    (art.parent / "analysis.json").write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")

    team, xlsx, body = web_path(out, analysis_id, a.lang)
    lines = [f"# Team report parity: {a.label} ({a.lang})", "",
             f"Source: `{Path(a.artifacts).resolve()}` (copied; the original is only read).",
             f"Review file: `{Path(a.review).resolve() if a.review else 'the artifacts folder' + chr(39) + 's (' + ('present' if (art / 'review.json').is_file() else 'none') + ')'}`.", ""]
    if team.status_code != 200:
        lines += [f"Web path: HTTP {team.status_code}", "", "```", team.text, "```"]
        (out / "parity.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("\n".join(lines))
        return 1
    pdf_name = team.headers.get("content-disposition", "").split("filename=")[-1].strip('"')
    xlsx_name = xlsx.headers.get("content-disposition", "").split("filename=")[-1].strip('"')
    web_pdf = out / pdf_name
    web_pdf.write_bytes(team.content)
    (out / xlsx_name).write_bytes(xlsx.content)
    if body.get("reassessed"):
        lines += [f"Re-evaluation: {body['reassessed']}", ""]

    skill = out / f"skill-{a.lang}"
    skill.mkdir(exist_ok=True)
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    steps = [[SKILL / "build_data.py", art / "report.json", "--lang", a.lang, "-o", skill / "data.json"],
             [SKILL / "validate_data.py", skill / "data.json"],
             [SKILL / "render.py", skill / "data.json", "-o", skill / f"{a.label}.html", "--pdf", skill / f"{a.label}.pdf"]]
    for step in steps:
        run = subprocess.run([sys.executable, *map(str, step)], capture_output=True, text=True, encoding="utf-8", cwd=SKILL, env=env)
        if run.returncode:
            lines += [f"Skill step {Path(step[0]).name} failed:", "```", run.stdout + run.stderr, "```"]
            (out / "parity.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
            print("\n".join(lines))
            return 1
    web_pages = pages_png(web_pdf, out / f"png-web-{a.lang}")
    skill_pages = pages_png(skill / f"{a.label}.pdf", out / f"png-skill-{a.lang}")
    from maya_audit import xlsx as sheet
    skill_xlsx = next(skill.glob("*.xlsx"))
    same_xlsx = sheet.read(xlsx.content) == sheet.read(skill_xlsx.read_bytes())
    lines += [f"Web app: GET /team-report?lang={a.lang} -> HTTP 200, release gate {team.headers.get('x-maya-release-gate')}, "
              f"{team.headers.get('x-maya-pages')} pages, language {team.headers.get('x-maya-language')}; files `{pdf_name}`, `{xlsx_name}`",
              f"Skill: build_data.py, validate_data.py, render.py -> {len(skill_pages)} pages", "",
              "| Page | Web PNG | Skill PNG | Same pixels | Differing bytes |", "|---|---|---|---|---|"]
    differing = []
    for n in range(max(len(web_pages), len(skill_pages))):
        w = web_pages[n] if n < len(web_pages) else None
        s = skill_pages[n] if n < len(skill_pages) else None
        if not w or not s:
            differing.append(n + 1)
            lines.append(f"| {n + 1} | {w.name if w else '—'} | {s.name if s else '—'} | no (page missing) | — |")
            continue
        wb, sb = w.read_bytes(), s.read_bytes()
        if wb == sb:
            lines.append(f"| {n + 1} | {w.name} | {s.name} | yes | 0 |")
            continue
        wp, sp = png_pixels(wb), png_pixels(sb)
        diff = sum(1 for x, y in zip(wp, sp) if x != y) + abs(len(wp) - len(sp))
        same = diff == 0
        if not same:
            differing.append(n + 1)
        lines.append(f"| {n + 1} | {w.name} | {s.name} | {'yes' if same else 'no'} | {diff} of {max(len(wp), len(sp))} |")
    lines += ["", f"Pages that differ: {', '.join(map(str, differing)) if differing else 'none'}.",
              f"XLSX appendix (web download vs the skill's file), every sheet and cell: {'same' if same_xlsx else 'DIFFERENT'}.", ""]

    built = json.loads((skill / "data.json").read_text(encoding="utf-8"))
    lines += [f"## Cards ({a.lang})", "", "| # | Severity | Rule | Card | Findings |", "|---|---|---|---|---|"]
    for n, t in enumerate(built["todos"], 1):
        lines.append(f"| {n} | {t.get('severity')} | {t.get('rule_id') or '—'} | {str(t.get('title')).replace('|', '/')} | "
                     f"{', '.join(t.get('finding_ids') or [])} |")
    lines.append("")
    if a.approved:
        def get(o, p):
            for part in re.findall(r"[^.\[\]]+", p):
                o = (o[int(part)] if part.isdigit() and isinstance(o, list) and int(part) < len(o) else
                     o.get(part) if isinstance(o, dict) else None)
                if o is None:
                    return None
            return o
        approved = json.loads(Path(a.approved).read_text(encoding="utf-8"))
        same_cards = [(t.get("finding_ids"), t.get("severity")) for t in built["todos"]] == \
                     [(t.get("finding_ids"), t.get("severity")) for t in approved["todos"]]
        lines += [f"## Text against the approved report (`{a.approved}`)", "",
                  f"Cards, their order and severities: {'the same' if same_cards else 'DIFFERENT'} "
                  f"({len(built['todos'])} cards here, {len(approved['todos'])} approved).", "",
                  "| Field | Approved (model-written) | Now (text library) |", "|---|---|---|"]
        changed = 0
        for slot in built["_slots"]:
            now, before = get(built, slot["path"]), get(approved, slot["path"])
            if now != before:
                changed += 1
                cell = lambda v: str(v).replace("\n", " / ").replace("|", "\\|")  # noqa: E731
                lines.append(f"| `{slot['path']}` | {cell(before)} | {cell(now)} |")
        lines += ["", f"{changed} of {len(built['_slots'])} text fields differ from the approved wording; the rest are the same.", ""]
    (out / "parity.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 1 if differing or not same_xlsx else 0


if __name__ == "__main__":
    raise SystemExit(main())
