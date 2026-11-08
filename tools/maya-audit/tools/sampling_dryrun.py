"""Dry run of an Akıllı ~150 plan on a saved audit (DECISIONS 327): no request, the report is not changed.

    .venv/bin/python tools/sampling_dryrun.py <report.json> [--business-type ID] [--json out.json]

Wave 1 is planned from what the audit knew before reading (its sitemap and its homepage's links, with their menu
texts); wave 2 after re-typing with the pages the audit read that wave 1 planned (their saved analysis).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from maya_audit import business_types as bt  # noqa: E402
from maya_audit import locales, sampling, sector_audit  # noqa: E402


def main_folder(report: dict, folders) -> str | None:
    """The folder the homepage lands on (DECISIONS 316/327): the saved record, else the start address's redirect."""
    crawl = report.get("crawl") or {}
    saved = (crawl.get("locales") or {}).get("main")
    if saved is not None:
        return saved
    for p in crawl.get("pages") or []:
        if p.get("redirect_location"):
            return locales.locale_of(p["redirect_location"], folders)
        if 200 <= int(p.get("status") or 0) < 300:
            return locales.locale_of(p["url"], folders)
    return None


def run(report: dict, business: str | None = None) -> dict:
    crawl = report["crawl"]
    start = crawl["start_url"]
    host = urlsplit(crawl.get("origin") or start).hostname
    pages = [p for p in crawl.get("pages") or [] if isinstance(p, dict)]
    homes = [p for p in pages if (p.get("grouping") or {}).get("page_type") == "home" and p.get("outlinks")] or pages[:2]
    anchors: dict[str, list[str]] = {}
    menu: set[str] = set()
    for h in homes:
        for e in h.get("outlinks") or []:
            target = (e.get("target") or "").split("#")[0]
            if target:
                anchors.setdefault(target, []).extend(e.get("anchors") or ([e["anchor"]] if e.get("anchor") else []))
                if e.get("nav"):
                    menu.add(target)
    known = [u for u in [start, *(crawl.get("sitemap_urls") or []), *anchors] if urlsplit(u).hostname == host]
    info = locales.detect(known, start_url=start)
    folders = info["folders"]
    main = main_folder(report, folders)
    from maya_audit.client_selection import grouping
    records, summary = grouping(report, business)
    pid = business or (summary.get("business_type") or {}).get("id") or bt.DEFAULT
    s = sampling.Sampler(pid, folders=folders, main=main, lastmods=crawl.get("sitemap_lastmods") or {})
    s.add(known, anchors, menu)
    homes_fixed = [u for u, (t, _) in s.types.items() if t == "home"][:locales.HOME_COPIES]
    first = s.plan(fixed=homes_fixed)
    wave_one = first[:s.wave_one_size()]
    by_url = {p["url"]: p.get("analysis") for p in pages if p.get("analysis")}
    read = {u: by_url[u] for u in wave_one if u in by_url}
    real = s.retype(read)
    second = s.plan(fixed=homes_fixed, read=real)
    record = s.record()
    sector = sector_audit.sector_of(pid)
    rows = [r for r in sector_audit.method()["sec"] if r["sector"] == sector] if sector else []
    planned_types = {t for t, row in record["types"].items() if row["planned"] or (t == "home" and homes_fixed)}
    read_types = {r.get("business_page_type") for r in records.values() if r.get("read") is not False}
    fill = lambda types: sum(1 for r in rows if r["type_id"] in types and r["status"] in ("A", "K"))  # noqa: E731
    return {"profile": pid, "main": main, "folders": list(folders), "known": record["known"], "record": record,
            "wave_one": len(wave_one), "wave_one_read_in_audit": len(read), "retyped": s.retyped, "second": second,
            "sector_rows": len(rows), "fillable_audit": fill(read_types), "fillable_plan": fill(planned_types),
            "order": first, "planned": {t: s.planned.get(t, []) for t in s.planned}}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("report")
    ap.add_argument("--business-type", default=None)
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)
    out = run(json.loads(Path(args.report).read_text(encoding="utf-8")), args.business_type)
    rec = out["record"]
    print(f"profile {out['profile']}, main folder {out['main']!r}, folders {out['folders']}, known pages {out['known']}")
    for t, row in rec["types"].items():
        if row["known"] or row["planned"]:
            ex = ", ".join(urlsplit(u).path for u in row["examples"][:3])
            print(f"  {(row['label'] or t)[:34]:34} rank {row['rank'] or '—':>2}  known {row['known']:>5}  planned {row['planned']:>3}  {ex}")
    print(f"wave 1: {out['wave_one']} pages ({out['wave_one_read_in_audit']} of them read in the saved audit); "
          f"re-typed unread addresses: {out['retyped']}; wave 2 plan: {len(out['second'])} pages")
    print(f"sector rows fillable: audit {out['fillable_audit']}/{out['sector_rows']}, plan {out['fillable_plan']}/{out['sector_rows']}")
    if args.json:
        Path(args.json).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
