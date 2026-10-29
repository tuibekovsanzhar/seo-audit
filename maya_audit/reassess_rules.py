"""Rules changed after a report was written, applied offline to its saved findings (DECISIONS 285).

A saved report keeps the severities and findings it was written with. This applies the rules DECISIONS 284 changed to
the observations the report already holds, on a copy, with no request and no crawl:

- STR-2 "The homepage's only <h1> is hidden": the rule now gives it Medium (nothing re-tests it). The observation is
  unchanged; the severity and the note follow the current rule.
- STR-8 "pricing or spec comparisons as <div> grids": a grid in a block named as a calculator is left out. Each grid
  keeps its selector, label and heading in the finding's evidence, so the name test runs on them with the engine's own
  pattern. The other new test, a form control beside the grid, needs the page's structure, which a report does not
  keep: it is not assessed here and the result says so.

Then what depends on the findings is derived again as a new report derives it: the severity policy, the priority
order, the problem summary (findings in priority order) and the release gate. Nothing else is re-run: re-running other
checks on Maya's own copies of the pages would mix readers when another reader (Firecrawl) read the site.
"""
from __future__ import annotations

import re
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace

NOT_ASSESSED_OFFLINE = ("a form control beside a grid (a calculator's input column next to its result column): the "
                        "report does not keep the page's structure around a grid")


def _hidden_h1(report: dict, changes: list[str]) -> None:
    from .checks.structure import HIDDEN_H1_MEDIUM, HOME_HIDDEN_H1_SEVERITY
    target = HOME_HIDDEN_H1_SEVERITY.value
    for check in report.get("checks") or []:
        for f in check.get("findings") or []:
            if f.get("rule_id") != "str2.home_hidden_h1" or f.get("severity") in (target, "S4", "Info"):
                continue
            changes.append(f"{f['id']}: {f['severity']} -> {target} (str2.home_hidden_h1, DECISIONS 284 (3))")
            f["severity"] = target
            notes = f.setdefault("notes", [])
            if HIDDEN_H1_MEDIUM not in notes:
                notes.append(HIDDEN_H1_MEDIUM)
            assessment = (f.get("evidence") or {}).get("severity_assessment")
            if isinstance(assessment, dict):
                assessment["source_severity"] = assessment["severity"] = target


def _calculator_grids(report: dict, affected: dict, changes: list[str], unassessed: list[str]) -> None:
    from .analysis import CALCULATOR_NAME
    from .checks.structure import CALCULATOR_LEFT_OUT
    for check in report.get("checks") or []:
        if check.get("check_id") != "STR-8":
            continue
        kept = []
        for f in check.get("findings") or []:
            if f.get("rule_id") != "str8.pricing":
                kept.append(f)
                continue
            grids = (f.get("evidence") or {}).get("grids") or []
            named = [g for g in grids if CALCULATOR_NAME.search(" ".join(str(g.get(k) or "") for k in
                                                                         ("selector", "label", "heading", "container")))]
            rest = [g for g in grids if g not in named]
            if named:
                evidence = check.setdefault("evidence", {})
                left = evidence.setdefault("grids_left_out", [])
                for g in named:
                    left.append({"url": g.get("url"), "container": g.get("container"), "rows": g.get("rows"),
                                 **({"selector": g["selector"]} if g.get("selector") else {}),
                                 "why": CALCULATOR_LEFT_OUT, "calculator_named": True})
                evidence["grids_left_out_count"] = len(left)
            if not rest:
                changes.append(f"{f['id']}: removed; every grid is in a block named as a calculator "
                               f"({', '.join(sorted({str(g.get('url')) for g in named}))})")
                affected.pop(f["id"], None)
                continue
            if named:
                urls = sorted({g["url"] for g in rest if g.get("url")})
                f["evidence"]["grids"] = rest
                f["scope"] = {**(f.get("scope") or {}), "count": len(urls), "urls": urls}
                f["title"] = re.sub(r"^\d+ page", f"{len(urls)} page", f["title"])
                affected[f["id"]] = urls
                changes.append(f"{f['id']}: {len(named)} calculator grid(s) left out, {len(rest)} kept")
            # The kept grids were not checked for a control beside them: say so on the check.
            if rest:
                unassessed.extend(sorted({g["url"] for g in rest if g.get("url")}))
            kept.append(f)
        check["findings"] = kept
        if unassessed:
            parts = check.setdefault("coverage", {}).setdefault("not_assessed", [])
            parts.append({"part": "grids not checked for a form control beside them", "reason": NOT_ASSESSED_OFFLINE,
                          "count": len(unassessed)})
        from .checks.access import _status
        check["status"] = _status(check["findings"], check.get("review_items") or ())


def _order(report: dict) -> list[str]:
    from .findings import Severity, priority_key
    from .models import Confidence
    findings = [f for c in report.get("checks") or [] if not str(c.get("check_id", "")).startswith("ANS")
                for f in c.get("findings") or []]

    def key(f):
        return priority_key(SimpleNamespace(check_id=f["check_id"], severity=Severity(f["severity"]),
                                            importance_tier=f.get("importance_tier", 2), scope=f.get("scope") or {},
                                            confidence=Confidence(f.get("confidence", "inferred")),
                                            launch_gated=f.get("launch_gated") or []))
    return [f["id"] for f in sorted(findings, key=key)]


def apply(report: dict, affected: dict | None = None, *, source_audit_id: str | None = None) -> tuple[dict, dict, dict]:
    """(report, affected, record) for a copy of `report` with the changed rules applied. `record` lists every change
    and what could not be assessed offline; it is also written to `generation.analysis`."""
    from . import release_gate
    from .report import problem_summary
    from .severity import apply as apply_severity
    r, aff = deepcopy(report), deepcopy(affected or {})
    changes: list[str] = []
    unassessed: list[str] = []
    _hidden_h1(r, changes)
    _calculator_grids(r, aff, changes, unassessed)
    apply_severity(r.get("checks") or [], r.get("crawl") or {})
    order = _order(r)
    r["findings_in_priority_order"] = order
    by_id = {f["id"]: f for c in r.get("checks") or [] for f in c.get("findings") or []}
    old = r.get("problem_summary") or {}
    single = old.get("single_page")
    r["problem_summary"] = problem_summary([by_id[i] for i in order], aff, pages_checked=old.get("pages_checked") or 0,
                                           checks=r.get("checks"),
                                           single_page=single.get("url") if isinstance(single, dict) else single,
                                           start_address=old.get("start_address"))
    r["release_gate"] = release_gate.run(r, aff)
    record = {
        "kind": "offline rule reassessment", "rules": "DECISIONS 284 (3) and (4), applied by DECISIONS 285",
        "source_audit_id": source_audit_id, "processed_at": datetime.now(timezone.utc).isoformat(),
        "requests": 0, "changes": changes,
        "not_assessed_offline": ([{"rule": "STR-8 controls beside a grid", "why": NOT_ASSESSED_OFFLINE,
                                   "pages": sorted(set(unassessed))}] if unassessed else
                                 [{"rule": "STR-8 controls beside a grid", "why": NOT_ASSESSED_OFFLINE,
                                   "pages": [], "effect": "no pricing grid left to assess"}]),
        "unchanged": "every other finding, observation, time and count is the source report's",
    }
    r.setdefault("generation", {})["analysis"] = record
    return r, aff, record
