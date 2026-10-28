"""Compare two audits of the same site without claiming more than the two reports support.

Matching. A finding's id is built from its title and its pages, so it changes whenever the count in the
title or the list of pages changes; ids cannot be used to match across audits. Two findings are taken to be
the same problem when they come from the same check and have the same title once every number in it is
replaced by "#" ("3 page(s) have no <title>" and "5 page(s) have no <title>" match). A finding left unmatched that way
is matched by its rule id (DECISIONS 269) when exactly one unmatched finding of each audit has it: a title reworded
between versions is still the same problem (DECISIONS 273).

A problem still reported carries `trend` (DECISIONS 273): "worse" when its severity rose or it names more pages,
"better" when its severity fell or it names fewer, "same" otherwise. Page counts are compared only when the two audits
ran under the same conditions; otherwise only the severity decides.

Reading the result. A problem missing from the newer report is only called "no longer reported" when the
newer audit ran that check and read at least one of the pages the older finding named. If the check did
not run, or none of those pages was read (a smaller page cap, a stop, a block), the honest answer is
"cannot tell", and that is what is returned. Nothing here claims a fix: the report can show that a problem
is no longer seen, not why.
"""

from __future__ import annotations

import re
from typing import Any

from . import summary, wording
from .strings import t

SHOWN = 50


def match_key(finding: dict[str, Any]) -> tuple[str, str]:
    return finding["check_id"], re.sub(r"\d+(?:[.,]\d+)?", "#", finding["title"]).casefold().strip()


def _rule(finding: dict[str, Any]) -> str | None:
    if finding.get("rule_id"):
        return finding["rule_id"]
    from maya_audit.rules import rule_id  # a report saved before 1.18
    return rule_id(finding["check_id"], finding["title"])


def _pair_by_rule(now: dict, before: dict) -> dict:
    """Unmatched older keys -> newer keys, where one rule id is held by exactly one unmatched finding on each side."""
    def single(side: dict, other: dict) -> dict:
        rules: dict[str, list] = {}
        for key, finding in side.items():
            if key not in other and _rule(finding):
                rules.setdefault(_rule(finding), []).append(key)
        return {rule: keys[0] for rule, keys in rules.items() if len(keys) == 1}
    new_by_rule, old_by_rule = single(now, before), single(before, now)
    return {old_by_rule[rule]: new_by_rule[rule] for rule in old_by_rule.keys() & new_by_rule.keys()}


def _trend(current: dict[str, Any], older: dict[str, Any], same_conditions: bool) -> str:
    order = {s: n for n, s in enumerate(summary.SEVERITIES)}  # most severe first
    a, b = order.get(current["severity"], 9), order.get(older["severity"], 9)
    if a != b:
        return "worse" if a < b else "better"
    if same_conditions:
        pages_now = (current.get("scope") or {}).get("count") or 0
        pages_before = (older.get("scope") or {}).get("count") or 0
        if pages_now != pages_before:
            return "worse" if pages_now > pages_before else "better"
    return "same"


def _pages_read(report: dict[str, Any]) -> set[str]:
    return {page["url"] for page in report["crawl"].get("pages") or [] if page.get("status") is not None}


def _status_by_check(report: dict[str, Any]) -> dict[str, str]:
    return {check["check_id"]: check["status"] for check in report["checks"]}


def _row(finding: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {"check_id": finding["check_id"], "title": finding["title"], "title_shown": wording.title(finding["check_id"], finding["title"])[0],
            "severity": finding["severity"],
            "severity_label": t(f"result.severity.{finding['severity']}"),
            "pages": (finding.get("scope") or {}).get("count") or 0, "id": finding["id"], **extra}


def differences(new: dict[str, Any], old: dict[str, Any], caps: tuple[int, int] | None = None) -> list[dict[str, Any]]:
    """What differs between the two audits' scope and conditions. Each one limits what the comparison can say.

    `caps` are the two audits' page limits when the caller knows them (a resumed audit's report records only
    its last sitting's share of the limit)."""
    a, b = summary.method(new), summary.method(old)
    if caps:
        a["page_cap"], b["page_cap"] = caps
    out = []

    def differ(code: str, **values: Any) -> None:
        out.append({"code": code, "message": t(f"compare.diff.{code}", **values)})

    if a["start_url"] != b["start_url"]:
        differ("target", new=a["start_url"], old=b["start_url"])
    if a["pages_checked"] != b["pages_checked"]:
        differ("pages", new=a["pages_checked"], old=b["pages_checked"])
    if (a["page_cap"], a["stop_reason"]) != (b["page_cap"], b["stop_reason"]):
        differ("scope", new=f"{a['page_cap']} ({a['stop_reason']})", old=f"{b['page_cap']} ({b['stop_reason']})")
    if a["rendering"]["mode"] != b["rendering"]["mode"]:
        differ("rendering", new=a["rendering"]["label"], old=b["rendering"]["label"])
    if sorted(a["key_pages"]) != sorted(b["key_pages"]):
        differ("key_pages", new=len(a["key_pages"]), old=len(b["key_pages"]))
    for source in a["optional_sources"]:
        if a["optional_sources"][source] != b["optional_sources"][source]:
            differ("source", source=source, new=t("word.yes") if a["optional_sources"][source] else t("word.no"),
                   old=t("word.yes") if b["optional_sources"][source] else t("word.no"))
    return out


def compare(new: dict[str, Any], old: dict[str, Any], *, new_affected: dict[str, list[str]] | None = None,
            old_affected: dict[str, list[str]] | None = None, caps: tuple[int, int] | None = None) -> dict[str, Any]:
    """`new` and `old` are saved reports. `*_affected` are the full affected-page lists, when saved."""
    summary.check_readable(new)
    summary.check_readable(old)
    new_affected, old_affected = new_affected or {}, old_affected or {}

    def pages_of(finding: dict[str, Any], affected: dict[str, list[str]]) -> list[str]:
        return affected.get(finding["id"]) or list((finding.get("scope") or {}).get("urls") or [])

    now = {match_key(f): f for f in reversed(summary.findings(new))}
    before = {match_key(f): f for f in reversed(summary.findings(old))}
    read_now, read_before = _pages_read(new), _pages_read(old)
    ran_now, ran_before = _status_by_check(new), _status_by_check(old)
    still, gone, unclear, fresh, first_seen = [], [], [], [], []
    diffs = differences(new, old, caps)
    paired = _pair_by_rule(now, before)
    matched_new = set(now) & set(before) | set(paired.values())

    for key, finding in before.items():
        if key in now or key in paired:
            current = now[key if key in now else paired[key]]
            still.append(_row(current, pages_before=(finding.get("scope") or {}).get("count") or 0,
                              severity_before=finding["severity"], trend=_trend(current, finding, not diffs),
                              matched_by="title" if key in now else "rule_id"))
            continue
        status = ran_now.get(finding["check_id"])
        named = pages_of(finding, old_affected)
        reread = [url for url in named if url in read_now]
        if status in (None, "not_assessed"):
            unclear.append(_row(finding, why=t("compare.unclear.check", check=finding["check_id"])))
        elif named and not reread:
            unclear.append(_row(finding, why=t("compare.unclear.pages", count=len(named))))
        else:
            gone.append(_row(finding, pages_read_again=len(reread), pages_named=len(named),
                             note=t("compare.gone.note", read=len(reread), named=len(named)) if named else None))
    for key, finding in now.items():
        if key in matched_new:
            continue
        named = pages_of(finding, new_affected)
        seen_before = [url for url in named if url in read_before]
        if ran_before.get(finding["check_id"]) in (None, "not_assessed") or (named and not seen_before):
            first_seen.append(_row(finding, why=t("compare.first_seen.why")))
        else:
            fresh.append(_row(finding))

    order = {s: n for n, s in enumerate(summary.SEVERITIES)}
    for rows in (still, gone, unclear, fresh, first_seen):
        rows.sort(key=lambda row: (order.get(row["severity"], 9), -row["pages"]))
    return {
        "newer": {"started_at": new["crawl"].get("started_at"), "pages_checked": new["page_counts"]["pages_checked"]},
        "older": {"started_at": old["crawl"].get("started_at"), "pages_checked": old["page_counts"]["pages_checked"]},
        "same_conditions": not diffs, "differences": diffs,
        "caution": None if not diffs else t("compare.caution"),
        "matching": t("compare.matching"),
        "counts": {"still_reported": len(still), "no_longer_reported": len(gone), "cannot_tell": len(unclear),
                   "new": len(fresh), "first_seen": len(first_seen),
                   "worse": sum(r["trend"] == "worse" for r in still), "better": sum(r["trend"] == "better" for r in still)},
        "still_reported": still[:SHOWN], "no_longer_reported": gone[:SHOWN], "cannot_tell": unclear[:SHOWN],
        "new": fresh[:SHOWN], "first_seen": first_seen[:SHOWN],
        "summary_line": t("compare.summary", still=len(still), gone=len(gone), unclear=len(unclear), new=len(fresh),
                          first_seen=len(first_seen)),
    }


# -- the validation note (G3, DECISIONS 278) ----------------------------------------------------------------------------
# A validation note ("DOGRULAMA.md") used to be written by hand: checklist items were ticked by how a finding's title
# read, so an item about sitemap URLs was "kept" on the strength of a finding that held none of them, and "9/9 kept"
# counted items nobody re-tested. The note is now made from the release gate's `checklist`: every row is one finding_id
# (or "unmatched"), the counts are computed, and what a person adds stays in its own `manual_notes` column.

RESULT_WORDS = {"kept_and_retested": "kept, re-tested and confirmed", "matched_not_retested": "kept, not re-tested",
                "unmatched": "not matched to any finding", "closed": "closed", "still_reported": "still reported"}


def validation_note(spec: dict[str, Any], report: dict[str, Any], affected: dict[str, list[str]] | None = None) -> str:
    """The validation note as Markdown, from a checklist spec and the report it is checked against.

    spec: {"title", "items": [{"label", "rule_id", "urls", "expected": "kept" | "closed", "manual_notes"}],
           "false_alarm_sweep": what was compared to look for new false alarms, or null when none was done,
           "manual_notes": free text}. Nothing in it is counted unless it was matched by finding id."""
    from maya_audit.release_gate import checklist
    out = checklist(spec.get("items") or [], report, affected)
    c = out["counts"]
    kept_items = c["kept_and_retested"] + c["matched_not_retested"] + c["unmatched"]
    lines = [f"# {spec.get('title') or 'Validation note'}", "",
             "Generated from the report by finding id (maya_audit_web.comparison.validation_note); not written by hand.", "",
             "| Item | Expected | Result | finding_id | rule_id | Severity | Second look | Manual notes |",
             "|---|---|---|---|---|---|---|---|"]
    for row in out["rows"]:
        lines.append("| " + " | ".join(str(v if v not in (None, "") else "—") for v in (
            row["label"], row["expected"], RESULT_WORDS[row["result"]], row["finding_id"], row["rule_id"], row["severity"],
            row["verification"], (row["manual_notes"] or "").replace("|", "/"))) + " |")
    lines += ["", f"- Items to keep: {kept_items}. Kept, re-tested and confirmed: {c['kept_and_retested']}. "
                  f"Kept but not re-tested: {c['matched_not_retested']}. Not matched to any finding: {c['unmatched']}.",
              f"- Items to close: {c['closed'] + c['still_reported']}. Closed: {c['closed']}. Still reported: "
              f"{c['still_reported']}.",
              "- New false alarms: " + (f"swept ({spec['false_alarm_sweep']})." if spec.get("false_alarm_sweep")
                                        else "no false-alarm sweep was done; nothing is claimed.")]
    if spec.get("manual_notes"):
        lines += ["", "## Manual notes", "", str(spec["manual_notes"])]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json
    from pathlib import Path
    ap = argparse.ArgumentParser(description="Write a validation note from a checklist and a report, by finding id.")
    ap.add_argument("--checklist", required=True, help="checklist JSON (items, false_alarm_sweep, manual_notes)")
    ap.add_argument("report", help="report.json; its <name>.affected-urls.json beside it is read when present")
    ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args(argv)
    rp = Path(a.report)
    report = json.loads(rp.read_text(encoding="utf-8"))
    side = rp.with_name(rp.stem + ".affected-urls.json")
    affected = json.loads(side.read_text(encoding="utf-8")) if side.exists() else None
    spec = json.loads(Path(a.checklist).read_text(encoding="utf-8"))
    Path(a.out).write_text(validation_note(spec, report, affected), encoding="utf-8", newline="\n")
    print(f"validation note written to {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
