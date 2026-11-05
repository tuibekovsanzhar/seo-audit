"""Business type (DECISIONS 311) on a saved audit, offline: the suggestion and its reason, the top 10 key pages and the
card order before ("Diğer" = Stage 3) and after (the suggested or the given type), and the "not found among the pages
read" notes. No request is sent and the saved report is never written.

    .venv/bin/python tools/business_types_saved.py <audit>/artifacts/report.json [--type ID] [--current] \
        [--json out.json] [--seen seen.json] [--name nihan]

`--current` first re-evaluates the report with the current engine, as the web app's team report does
(`team_report.current`): the derived copy is written beside the report (`<audit>/current-engine/` or
`<report>.current-engine/`), so run it on a copy, never on the web app's own folder. `--seen` adds the signals that
matched on this audit to a JSON file (the "seen on a saved audit" column of docs/business-types/signals.md).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from maya_audit import business_types as bt, client_selection  # noqa: E402


def key_rows(selection: dict) -> list[dict]:
    return [{"rank": k["rank"], "url": k["url"], "importance": k["importance"], "page_type": k.get("page_type"),
             "business_page_type": k.get("business_page_type")} for k in selection["key_pages"]]


def card_rows(selection: dict) -> list[dict]:
    return [{"card": g["card"], "rule": g.get("rule_id") or (g["lead"].get("check_id") if g.get("lead") else None),
             "severity": g["severity"], "priority": g["priority"], "reach": g["reach"], "finding_ids": g["finding_ids"]}
            for g in selection["cards"]]


def compare(report: dict, affected: dict | None, business: str | None) -> dict:
    before = client_selection.select(report, affected, business="diger")
    after = client_selection.select(report, affected, business=business)
    info = after.get("business_type") or {}
    records, _ = client_selection.grouping(report, business)
    seen = Counter()
    for g in records.values():
        for s in g.get("business_signals") or []:
            seen[(info.get("id"), g.get("business_page_type"), s["kind"], s["value"] if isinstance(s["value"], str) else str(s["value"]))] += 1
    return {"business_type": info, "key_pages_before": key_rows(before), "key_pages_after": key_rows(after),
            "not_found": after.get("key_pages_not_found") or [], "cards_before": card_rows(before),
            "cards_after": card_rows(after), "seen": [{"profile": k[0], "type": k[1], "kind": k[2], "value": k[3], "pages": n}
                                                     for k, n in sorted(seen.items(), key=lambda kv: (kv[0][1] or "", -kv[1]))]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("report")
    ap.add_argument("--type", default=None, help="a profile id; left out: the report's own, else the suggestion")
    ap.add_argument("--current", action="store_true", help="re-evaluate with the current engine first (writes a derived copy)")
    ap.add_argument("--json", default=None)
    ap.add_argument("--seen", default=None)
    ap.add_argument("--name", default=None, help="the audit's name in the --seen file")
    args = ap.parse_args(argv)
    path = Path(args.report)
    affected_path = next((p for p in (path.parent / "affected-urls.json",) if p.is_file()), None)
    if args.current:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from maya_audit_web.team_report import current
        cur = current.current(path, affected_path)
        path, affected_path = cur.report_path, cur.affected_path
    report = json.loads(path.read_text(encoding="utf-8"))
    affected = json.loads(affected_path.read_text(encoding="utf-8")) if affected_path and affected_path.is_file() else None
    out = compare(report, affected, args.type)
    info = out["business_type"]
    sug = info.get("suggestion") or {}
    print(f"Business type: {info.get('id')} ({info.get('chosen_by')}); suggested {sug.get('id')}: {(sug.get('reason') or {}).get('tr')}")
    for side in ("before", "after"):
        print(f"\nTop 10 key pages {side}:")
        for k in out[f"key_pages_{side}"]:
            print(f"  {k['rank']:>2}  {k['importance']:>3}  {k.get('business_page_type') or k.get('page_type') or '-':<16} {k['url']}")
    print("\nNot found among the pages read:", ", ".join(n["label"]["tr"] for n in out["not_found"]) or "none")
    for side in ("before", "after"):
        print(f"\nCards {side}: " + " ".join(f"{c['card']}:{c['rule']}({c['priority']})" for c in out[f"cards_{side}"]))
    if args.json:
        Path(args.json).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    if args.seen:
        seen_path = Path(args.seen)
        data = json.loads(seen_path.read_text(encoding="utf-8")) if seen_path.is_file() else {}
        name = args.name or path.parent.parent.name[:8]
        for row in out["seen"]:
            key = f"{row['profile']}|{row['type']}|{row['kind']}|{row['value']}"
            data.setdefault(key, {})[name] = row["pages"]
        seen_path.write_text(json.dumps(dict(sorted(data.items())), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
