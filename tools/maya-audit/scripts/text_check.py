"""The post-report text check (DECISIONS 353) on saved audits, as the downloads run it.

  python scripts/text_check.py REPORT.json [REPORT.json ...] [--lang tr] [--json out.json] [--llm-review]

Each REPORT.json is a saved audit's report (its affected-urls.json beside it is used). The team report's data is built
from the current engine as the web app builds it, then the release gate's text checks run (RG-18 to RG-23). Provider
free: no network unless --llm-review is given and a key is set (MAYA_AUDIT_ANTHROPIC_API_KEY), and then it only suggests.
Exit 1 when any report is BLOCKED (its downloads would be drafts).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def check_one(report_path: Path, lang: str, llm: bool) -> dict:
    from maya_audit import text_gate
    from maya_audit_web.team_report import build_data, llm_review
    affected = report_path.with_name("affected-urls.json")
    data, _ = build_data.build_from_files(report_path, lang, audit_id=report_path.parent.parent.name[:8] or None,
                                          affected_path=affected if affected.is_file() else None)
    report = json.loads(Path(data["_report_path"]).read_text(encoding="utf-8"))
    record = text_gate.run(data, report)
    if llm:
        record = llm_review.attach(record, llm_review.review(data, report, force=True))
    return record


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("reports", nargs="+")
    ap.add_argument("--lang", default="tr", choices=("tr", "en"))
    ap.add_argument("--json", default=None)
    ap.add_argument("--llm-review", action="store_true")
    a = ap.parse_args(argv)
    from maya_audit import text_gate
    names = text_gate.RULE_NAMES[a.lang]
    out, blocked = {}, False
    for path in a.reports:
        record = check_one(Path(path), a.lang, a.llm_review)
        out[path] = record
        blocked |= record["decision"] == text_gate.BLOCKED
        counts = ", ".join(f"{r} {names.get(r, r)}: {n}" for r, n in sorted(record["counts"].items())) or "bulgu yok"
        print(f"{path}: {record['decision']} (engelleyici {record['hard']}) · {counts}")
        for v in record["violations"]:
            print(f"  {v['rule']} {'ENGEL' if v['hard'] else 'uyarı'}: {v['message']}")
        if record.get("llm"):
            print(f"  LLM: {record['llm']['note']}")
        for s in record.get("suggestions") or []:
            print(f"  öneri {s['where']}: {s['problem']} -> {s['text']}")
    if a.json:
        Path(a.json).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return 1 if blocked else 0


if __name__ == "__main__":
    raise SystemExit(main())
