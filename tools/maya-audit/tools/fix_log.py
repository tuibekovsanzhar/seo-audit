"""The review fix log (DECISIONS 363): every issue the SEO team noted, checked on the newest saved audit of its domain.

    .venv/bin/python tools/fix_log.py --work <tmp> [--out ~/Downloads/duzeltme-kaydi.xlsx] [--write-status]

Reads `maya_audit/fix_log.json` (the items, written by hand from the review files and DECISIONS) and, for each brand, the
newest finished audit of its domain in the web app's folder (www and the bare name are one domain). Each audit is copied
to `--work` and rebuilt there with the current engine (the team report's data and the Ek), so `~/.maya-audit/web` is only
read; no request is made. Each item's `check` is evaluated on that rebuild (`CHECKS`), its Durum set, and the log written:
the XLSX for the team (`--out`) and, with `--write-status`, the statuses the Ek's "Düzeltme kaydı" sheet shows
(`maya_audit/fix_log_status.json`). Run with every provider key empty (AGENTS.md, Shared preamble 8).
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from maya_audit import fix_log  # noqa: E402

WEB = Path.home() / ".maya-audit" / "web"


def newest_audits(web: Path = WEB) -> dict[str, dict]:
    """{domain: {id, url, finished_at, previous}} of the newest finished audit per domain (www and the bare name are
    one), with the one before it (`previous`, or None)."""
    db = sqlite3.connect(f"file:{web / 'web-v1.db'}?mode=ro", uri=True)
    out: dict[str, dict] = {}
    for aid, url, finished in db.execute("select id, url, finished_at from audits where state='finished' "
                                         "and coalesce(hidden,0)=0 order by finished_at desc"):
        domain = (url.split("/")[2] if "//" in url else url).lower().removeprefix("www.")
        if domain not in out:
            out[domain] = {"id": aid, "url": url, "finished_at": finished, "previous": None}
        elif out[domain]["previous"] is None:
            out[domain]["previous"] = {"id": aid, "finished_at": finished}
    return out


def rebuild(aid: str, work: Path, web: Path = WEB, previous: dict | None = None) -> dict:
    """The audit rebuilt with the current engine from a copy: {report, data, book, cards, gate}."""
    from maya_audit import text_gate, xlsx
    from maya_audit_web.team_report import build_data, render
    folder = work / aid
    if folder.exists():
        shutil.rmtree(folder)
    shutil.copytree(web / "audits" / aid / "artifacts", folder / "artifacts")
    a = folder / "artifacts"
    data, _ = build_data.build_from_files(a / "report.json", "tr", audit_id=aid[:8], affected_path=a / "affected-urls.json")
    report = json.loads(Path(data["_report_path"]).read_text(encoding="utf-8"))
    affected = json.loads(Path(data["_affected_path"]).read_text(encoding="utf-8"))
    record = render.text_record(data, report)
    before = None
    if previous and (web / "audits" / previous["id"] / "artifacts" / "report.json").is_file():
        before = {**json.loads((web / "audits" / previous["id"] / "artifacts" / "report.json").read_text(encoding="utf-8")),
                  "_audit": {"id": previous["id"][:8], "date": previous["finished_at"][:10]}}
    files, _ = render.appendix_files(report, affected, data.get("_confirmations") or {}, "tr", data.get("_business"),
                                     todos=build_data.cards_for_appendix(data), maya=render.maya_bundle(a),
                                     text_check=record, previous=before)
    # DECISIONS 376: the client Ek and the team file (its "Kontrol raporu") together
    return {"report": report, "data": data, "book": render.appendix_book(files), "cards": data.get("todos") or [],
            "gate": (files.get("record") or record or {}).get("decision") or text_gate.run(data, report)["decision"]}


def run_tests(files: list[str]) -> dict[str, bool]:
    """{test file: passed} for the test files the items name (pytest, quietly, provider-free as the suite is)."""
    out = {}
    for f in files:
        if not (ROOT / f.split("::")[0]).is_file():
            out[f] = False
            continue
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f], cwd=ROOT, capture_output=True, text=True)
        out[f] = r.returncode == 0
        print(f"test {f}: {'passed' if out[f] else 'FAILED'}")
    return out


def expert_labels(work: Path, built: dict[str, dict]) -> dict[str, bool | None]:
    """DECISIONS 373: {label id: holds} of every expert label, checked on the frozen noted audits (the benchmark's
    `expert` set, MAYA_AUDIT_BENCHMARK_DIR); the audits this run already rebuilt are reused. {} when the frozen set is
    not on this machine: every item with labels is then "Doğrulanmadı"."""
    from scripts import real_sites_benchmark as bench
    if not (bench.expert_dir() / "manifest.json").exists():
        print("expert labels: the frozen set is not on this machine (MAYA_AUDIT_BENCHMARK_DIR); labels not checked")
        return {}
    reuse = {ctx["audit"]["id"]: ctx for ctx in built.values() if ctx.get("audit")}
    rows = bench.run_expert(work / "expert", built=reuse)
    red = [r["id"] for r in rows if r["ok"] is False]
    print(f"expert labels: {len(rows)} checked, {len(red)} red" + (f": {', '.join(red)}" if red else ""))
    return {r["id"]: r["ok"] for r in rows}


def commits() -> dict[int, tuple[str, str]]:
    """{DECISIONS no: (short commit, date)} of the first commit whose message names it."""
    log = subprocess.run(["git", "log", "--reverse", "--format=%h%x09%cs%x09%s"], cwd=ROOT, capture_output=True,
                         text=True, check=True).stdout
    out: dict[int, tuple[str, str]] = {}
    for line in log.splitlines():
        sha, date, subject = line.split("\t", 2)
        for n in re.findall(r"DECISIONS (\d{3})(?:[-–](\d{3}))?", subject):
            for k in range(int(n[0]), int(n[1] or n[0]) + 1):
                out.setdefault(k, (sha, date))
        for group in re.findall(r"DECISIONS ((?:\d{3}(?:, | and |/))+\d{3})", subject):
            for k in re.findall(r"\d{3}", group):
                out.setdefault(int(k), (sha, date))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", required=True, type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--write-status", action="store_true")
    ap.add_argument("--brand", action="append", help="only these brands (for a quick look)")
    args = ap.parse_args(argv)
    args.work.mkdir(parents=True, exist_ok=True)
    items = fix_log.items()
    audits = newest_audits()
    built: dict[str, dict] = {}
    for brand in sorted({i["brand_key"] for i in items if i.get("brand_key")}):
        if args.brand and brand not in args.brand:
            continue
        domain = fix_log.BRANDS[brand]["domain"]
        found = audits.get(domain)
        if found is None:
            continue
        ctx = rebuild(found["id"], args.work, previous=found.get("previous"))
        ctx["audit"] = found
        built[brand] = ctx
        print(f"{brand}: {found['id'][:8]} {found['finished_at'][:10]} rebuilt ({len(ctx['cards'])} cards, {ctx['gate']})")
    done = commits()
    tests = run_tests(sorted({t for i in items for t in fix_log.tests_of(i.get("check") or {})}))
    labels = expert_labels(args.work, built)
    rows = fix_log.evaluate(items, built, done, datetime.now(timezone.utc).date().isoformat(), tests, labels)
    for r in rows:
        print(f"{r['no']:>3} {r['durum']:<20} {r['marka']:<12} {r['sorun'][:70]}")
    if args.out:
        args.out.write_bytes(fix_log.workbook(rows))
        print(f"wrote {args.out}")
    if args.write_status:
        fix_log.save_status(rows)
        print(f"wrote {fix_log.STATUS_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
