"""Upgrade a saved report to the current format without re-crawling (report 0.3 → 0.4).

0.4 changed what a status means: a check that found nothing but left part of its question
unassessed is `partial`, not `pass`, and a check that only records measurements is `observed`
(DECISIONS §99). A 0.3 report still says `pass` for both. This reads the evidence each check
recorded and applies the same rules a live run applies (`maya_audit.coverage.derive`), so an old
report can be read under the new meaning.

What it cannot do, and says so in the migrated file:
- It never re-runs a check. Findings, severities and confidences are copied unchanged.
- A few 0.4 coverage parts rest on evidence 0.3 did not record (for example RND-3's English-only
  "load more" heuristic on non-English pages, and ANS-1's paged-input check). Those parts cannot be
  derived, so a migrated report can understate what was not assessed; it never overstates a pass.
- Where 0.3 capped a list (40 or 60 rows), the count is marked as a lower bound.
"""

from __future__ import annotations

import copy
from typing import Any

from .coverage import page_access, settle
from .findings import STATUS_MEANINGS, CheckResult
from .report import REPORT_VERSION

MIGRATION_LIMITS = [
    "Derived from recorded evidence; no check was re-run and nothing was fetched.",
    "Coverage parts that need evidence 0.3 did not record are missing (RND-3 non-English 'load more' pages, "
    "ANS-1 paged input), so this can understate what was not assessed.",
    "Counts taken from lists 0.3 capped are marked count_is_lower_bound.",
]


def migrate_check(check: dict[str, Any], access: dict | None = None) -> dict[str, Any]:
    """Apply the live settlement (`coverage.settle`) to a saved check. Findings are never touched."""
    out = copy.deepcopy(check)
    before = out["status"]
    shadow = CheckResult(out["check_id"], out.get("title", ""), before, out.get("summary", ""),
                         evidence=out.get("evidence") or {}, observations=out.get("observations") or [])
    settle(shadow, access)
    out.update(status=shadow.status, summary=shadow.summary, coverage=shadow.coverage)
    if out["status"] != before:
        out["status_before_migration"] = before
    return out


def migrate_report(report: dict[str, Any]) -> dict[str, Any]:
    version = report.get("report_version")
    if version == REPORT_VERSION:
        return report
    if version != "0.3":
        raise ValueError(f"cannot migrate report_version {version!r}; only 0.3 is supported")
    out = {k: v for k, v in report.items() if k not in ("checks", "answer_engine_panel")}
    out["report_version"] = REPORT_VERSION
    out["status_meanings"] = STATUS_MEANINGS
    access = page_access((report.get("crawl") or {}).get("pages") or []) if report.get("crawl") else None
    out["checks"] = [migrate_check(c, access) for c in report.get("checks", [])]
    out["answer_engine_panel"] = [migrate_check(c, access) for c in report.get("answer_engine_panel", [])]
    out["migrated"] = {"from_version": version, "to_version": REPORT_VERSION, "limits": MIGRATION_LIMITS,
                       "status_changes": [{"check_id": c["check_id"], "from": c["status_before_migration"],
                                           "to": c["status"]}
                                          for c in out["checks"] + out["answer_engine_panel"]
                                          if "status_before_migration" in c]}
    # Order the keys as a 0.4 report orders them, with the crawl dump last.
    order = ["report_version", "status_meanings", "migrated", "scope", "gates", "checks", "answer_engine_panel",
             "findings_in_priority_order", "needs_human_review", "crawl"]
    return {k: out[k] for k in order if k in out} | {k: v for k, v in out.items() if k not in order}
