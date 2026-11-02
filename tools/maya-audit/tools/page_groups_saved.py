"""Page grouping (DECISIONS 297) on a saved report, offline: no request is sent and the report is not changed.

    .venv/bin/python tools/page_groups_saved.py <report.json> [--top 20] [--json out.json]

Rebuilds the page records from `crawl.pages`, runs `maya_audit.page_groups.annotate` and prints the page-type counts,
the templates and the most important pages. `--json` writes {url: grouping} and the summary to a file of your choice.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from maya_audit.models import page_from_record  # noqa: E402
from maya_audit.page_groups import annotate  # noqa: E402


def result_from_report(report: dict):
    crawl = report["crawl"]
    pages = [page_from_record(record) for record in crawl["pages"]]
    return SimpleNamespace(pages=pages, start_url=crawl["start_url"], origin=crawl.get("origin"),
                           discovered_urls=crawl.get("discovered_urls") or [], sitemap_urls=crawl.get("sitemap_urls") or [],
                           page_grouping=None)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("report")
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--json")
    args = ap.parse_args(argv)
    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    result = result_from_report(report)
    summary = annotate(result)
    print(f"{report['crawl']['start_url']}: {summary['pages_scored']} pages scored, "
          f"{summary['pages_not_scored']} not, {summary['templates_total']} templates, "
          f"{summary['not_reached_from_homepage']} not reached from the homepage")
    print("page types:", json.dumps(summary["page_types"]))
    print("templates:", json.dumps(dict(list(summary["templates"].items())[:15]), ensure_ascii=False))
    scored = sorted((p for p in result.pages if p.grouping and "importance" in p.grouping),
                    key=lambda p: (-p.grouping["importance"], -p.grouping["internal_link_score"], p.url))
    print(f"\n{'imp':>3} {'link':>4} {'in':>4} {'dep':>3}  {'type':<12} {'template':<28} url")
    for p in scored[:args.top]:
        g = p.grouping
        print(f"{g['importance']:>3} {g['internal_link_score']:>4} {g['inlinks']:>4} {str(g['click_depth']):>3}  "
              f"{g['page_type']:<12} {g['template_key'][:28]:<28} {p.url}")
    if args.json:
        Path(args.json).write_text(json.dumps({"summary": summary, "pages": {p.url: p.grouping for p in result.pages}},
                                              ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
