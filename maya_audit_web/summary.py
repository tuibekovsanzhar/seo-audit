"""The report adapter: one saved JSON report, laid out for people.

Everything the results page, the action plan, the follow-up answers, the comparison and the PDF show comes
through here, so the formats agree. This reads what the engine already decided (statuses, severities, the
priority order, coverage) and arranges it. It never re-judges a page and never produces a number the report
does not hold: no visibility score, mention rate, ranking or sentiment is derived here. The answer-engine
panel stays apart from the site findings and is never added into their severity counts.
"""

from __future__ import annotations

from collections import Counter
from typing import Any
from urllib.parse import urlsplit

from maya_audit.checks.access import blocker_phrase
from maya_audit import allowlist, launch_gate, timeplan
from maya_audit.classify import describe_blockers, identify_blocker
from maya_audit.coverage import CRAWL_GAP_NAMES, PAGE_DEPENDENT, clean_on_what_was_read, restated
from maya_audit.findings import SEVERITY_DEFINITIONS, check_id_key, impact_rank, is_hygiene, page_importance
from maya_audit.firecrawl.reader import MAIN_PURPOSE, MAIN_WHY
from maya_audit.report import (PARTIAL_PAGE_CAP_SENTENCE, clean_on_read_sentence, content_coverage_shown, problem_summary, read_counts,
                               with_page_items, qualified_group_key, finding_counts)
from maya_audit.index_data import redirect_verdict
from maya_audit.schema import unsupported_reason
from maya_audit import schema

from . import catalog, wording
from .practical import details as detail_texts, merged
from .practical import names_line, top_title
from .strings import current_language, has, t

SEVERITIES = ("S1", "S2", "S3", "S4", "Info")
FAMILIES = ("ACC", "IDX", "RND", "STR", "TSEO", "PRF")
# A check whose area is not its id's prefix. RND-7 (the main content's share of the page text) is page structure, not
# JavaScript rendering; it keeps its id, which saved reports, the comparison and the launch gate use (DECISIONS 207).
# Applied when any report is shown, so a saved one is grouped the same way.
AREA_OF = {"RND-7": "STR"}
GROUPS = (("fix_now", ("S1", "S2")), ("fix_next", ("S3",)), ("improve_later", ("S4", "Info")))
TOP = 5
FOLLOW_UPS = ("follow.q.plan", "follow.q.critical", "follow.q.top", "follow.q.compare", "follow.q.coverage")


class UnreadableReport(ValueError):
    """The saved report is of a version this app does not read. Shown as is; nothing is guessed."""


def check_readable(report: dict[str, Any]) -> None:
    reason = unsupported_reason(report)
    if reason:
        raise UnreadableReport(reason)


def check_row(check: dict[str, Any]) -> dict[str, Any]:
    """A check (or an answer-engine panel check) as a row: the report's own title and summary, and the same as a person
    reads them (`title_shown`, `summary_shown`): in the reader's language, with "1 page(s)" said as "1 page"."""
    title, title_ok = wording.label(check["title"], check_id=check["check_id"])
    said, said_ok = wording.line(check["summary"], check_id=check["check_id"])
    return {"check_id": check["check_id"], "title": check["title"], "title_shown": title, "status": check["status"],
            "status_label": t(f"result.status.{check['status']}"), "summary": check["summary"], "summary_shown": said,
            "untranslated": not (title_ok and said_ok), "findings": len(check.get("findings") or []),
            "not_assessed": [{**g,"part_shown":wording.label(g.get('part'))[0],"reason_shown":wording.line(g.get('reason'))[0]} for g in (check.get('coverage') or {}).get('not_assessed') or []]}


def gate_row(gate: dict[str, Any]) -> dict[str, Any]:
    """An integrity gate as a row, with its title, state and summary as a person reads them. (A gate's "how to fix" is
    not on the card or in the printed report; `wording.line` words it wherever it is shown.)"""
    title, title_ok = wording.label(gate["title"], check_id=gate["check_id"])
    said, said_ok = wording.line(gate["summary"], check_id=gate["check_id"])
    state = gate["state"]
    return {"check_id": gate["check_id"], "title": gate["title"], "title_shown": title, "state": state,
            "state_label": t(f"result.gate.{state}") if has(f"result.gate.{state}") else state,
            "summary": gate["summary"], "summary_shown": said, "untranslated": not (title_ok and said_ok)}


def _family(check_id: str) -> str:
    prefix = AREA_OF.get(check_id) or check_id.split("-")[0]
    return prefix if prefix in FAMILIES else "other"


def _scope_line(scope: dict[str, Any], section: str | None = None) -> str:
    """`section` is the one section whose pages carry a shared element (`evidence.shared_element.section`): "Affects 26
    pages of /tr/", never "the whole site"."""
    if scope.get("kind") == "sitewide":
        return t("result.affects.sitewide")
    count = scope.get("count") or len(scope.get("urls") or [])
    return t("result.affects.section", count=count, section=section) if section else t("result.affects.pages", count=count)


def findings(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Site findings in the engine's priority order. The answer-engine panel is not among them."""
    by_id = {f["id"]: f for check in report["checks"] for f in check["findings"]}
    order = report.get("findings_in_priority_order", [])
    ordered = [by_id[i] for i in order if i in by_id] + [f for i, f in by_id.items() if i not in set(order)]
    if schema.version_key(str(report.get("schema_version") or "1.0")) < schema.version_key("1.12"):
        # A report written before findings were ordered by impact (DECISIONS 182) had the finding on most pages first
        # within a severity. Shown now, it follows the same rule as a new one: severity, then the engine's impact rank.
        # A stable sort, so the saved order still decides between findings of one severity and one rank. The saved
        # severities are kept: only a new audit applies a changed severity.
        ranks = {"S1": 0, "S2": 1, "S3": 2, "S4": 3, "Info": 4}
        ordered.sort(key=lambda f: (ranks.get(f.get("severity"), 5), impact_rank(f.get("check_id") or "")))
    return ordered


def single_page_of(report: dict[str, Any]) -> str | None:
    """The address of a single-page audit, or None for an ordinary one (report `problem_summary.single_page`, or the
    crawl's own setting)."""
    saved = ((report.get("problem_summary") or {}).get("single_page") or {}).get("url")
    crawl = report.get("crawl") or {}
    return saved or (crawl.get("start_url") if (crawl.get("config") or {}).get("single_page") else None)


def item(finding: dict[str, Any], single: bool = False) -> dict[str, Any]:
    """One finding as a row: the report's own facts, plus the catalog's plain note and its labelled estimates.

    `title`, `fix`, `expected` and `notes` stay the engine's own English: the catalog's note, the fix example, the
    comparison and the search are keyed on them. What a person reads is `title_shown`, `fix_shown`, `expected_shown`
    and `notes_shown`: the same sentences in the reader's language (`wording`), with "1 page(s)" said as "1 page".
    `untranslated` says that the title, the fix or the expected result has no translation yet and is shown in English
    with a mark; `notes_untranslated` counts the notes shown that way."""
    from maya_audit.judgments import qualify
    finding = qualify(finding)
    judgment = finding["evidence"]["judgment"]
    scope = finding.get("scope") or {}
    note = catalog.note(finding["check_id"], finding["title"])
    note.update(owner=judgment['action']['owner'], effort=judgment['action']['effort'])
    if judgment.get('qualified'):
        note['why'] = wording.note(judgment['interpretation'])[0]
    severity = finding["severity"]
    title, title_ok = wording.title(finding["check_id"], finding["title"])
    fix, fix_ok = wording.fix(finding.get("how_to_fix") or "")
    expected, expected_ok = wording.expected(finding.get("expected") or "")
    note_texts = list(finding.get("notes") or [])
    if judgment.get("qualified"):
        note_texts = list(dict.fromkeys(note_texts + judgment["alternatives"]))
    notes = [wording.note(text) for text in note_texts]
    # Historical severity is preserved, but incomplete saved verification must be visible in ordinary exports.
    evidence = finding.get("evidence") or {}
    saved_caveat = None
    if finding["check_id"] == "IDX-3" and severity == "S1":
        rechecks = evidence.get("rechecks") or {}
        cookies = evidence.get("cookie_walks") or {}
        wanted = max(1, (evidence.get("attempts_per_url") or 4) - 1)
        if not rechecks or any(redirect_verdict({"attempts": attempts, "cookie_walk": cookies.get(url)}, wanted)
                               != "always" for url, attempts in rechecks.items()):
            saved_caveat = wording.note("Saved Blocker classification retained; persistence is not established by the saved verification.")[0]
            note["why"] += " " + saved_caveat
    if finding["check_id"] == "IDX-3" and "intermittently redirect" in finding["title"]:
        successes = [a for attempts in (evidence.get("rechecks") or {}).values() for a in attempts
                     if a.get("outcome") == "resolves"]
        if not any(a.get("readable_html") is True for a in successes + (evidence.get("native_success_in_crawl") or [])):
            saved_caveat = wording.note("Saved success records HTTP status only; readable page content was not retained for this attempt.")[0]
            title = wording.note("Mixed native redirect and HTTP-success responses; page content not verified.")[0]
            note["why"] += " " + saved_caveat
    from maya_audit.evidence_quality import qualifications
    limits = qualifications(finding)
    if limits and not judgment.get("qualified"):
        # Said once, in `why` (CR-18): not again among the details, and the concise report does not repeat it either.
        note["why"] += " " + " ".join(wording.note(v)[0] for v in limits)
        if finding["check_id"] == "IDX-6":
            # The "destination is gone" caution is about a link target (CR-17); another check keeps its own fix.
            fix = wording.note("Corroborate the recorded response using the same client and affected URLs before choosing a remedy; unavailable verification is not proof that the destination is gone.")[0]
    component = evidence.get("shared_element") or {}
    targets = component.get("hrefs") or ([component["href"]] if component.get("href") else [])
    if component.get("block") and targets:
        title += " · " + str(component["block"]) + " → " + ", ".join(targets)
    return {
        "id": finding["id"], "judgment": judgment, "verification": wording.note(judgment["action"]["verification"])[0], "evidence_limits": limits, "observed_at": finding.get("observed_at"), "check_id": finding["check_id"], "area": _family(finding["check_id"]),
        "semantic_group": qualified_group_key(finding),
        "counting": finding_counts(finding),
        "area_label": t(f"result.family.{_family(finding['check_id'])}"), "title": finding["title"], "title_shown": title,
        "severity": severity, "severity_label": t(f"result.severity.{severity}"),
        # For ordering rows like the engine does: 0 when a key page or the homepage is affected (findings.page_importance).
        "importance": page_importance(finding),
        "severity_meaning": SEVERITY_DEFINITIONS.get(severity, "").partition(": ")[2],
        "confidence": finding.get("confidence"), "confidence_label": t(f"result.confidence.{finding.get('confidence')}"),
        # In a single-page audit a site-wide finding is a site-level fact the page depends on, and is labelled so.
        "rationale": finding.get("rationale"),
        "affects": t("result.affects.site_level") if single and scope.get("kind") == "sitewide"
        else _scope_line(scope, ((finding.get("evidence") or {}).get("shared_element") or {}).get("section")),
        "site_level": bool(single and scope.get("kind") == "sitewide"),
        "pages_total": scope.get("count") or len(scope.get("urls") or []), "sample_pages": list(scope.get("urls") or [])[:5],
        "what": title, "why": note["why"], "fix": finding.get("how_to_fix") or "", "fix_shown": fix,
        "expected": finding.get("expected") or "", "expected_shown": expected,
        "notes": finding.get("notes") or [], "notes_shown": [text for text, _ in notes],
        "untranslated": not (title_ok and fix_ok and expected_ok), "notes_untranslated": sum(1 for _, ok in notes if not ok),
        "engines": finding.get("engines") or [],
        # Advice, not measurement: who usually does this and roughly how big it is.
        "estimates": {"owner": note["owner"], "owner_label": t(f"owner.{note['owner']}"), "effort": note["effort"],
                      "effort_label": t(f"effort.{note['effort']}"), "label": t("result.estimates.label")},
        "requires_fix": severity != "Info",
        # An Info finding with a fix that is site-wide hygiene (findings.is_hygiene): listed short and capped (G25).
        "hygiene": is_hygiene(finding),
        # Set when the finding rests on what a third-party reader fetched, not on Maya's own crawl.
        "source": _source(finding),
        "evidence_record": {k: finding.get(k) for k in ('id','check_id','severity','confidence','observed_at','scope','evidence','notes')},
        # The values behind the title, where a title alone does not say them: both sides of a price, a brand's names.
        "details": ([saved_caveat] if saved_caveat else []) + detail_texts(finding) + ([count_line(finding)] if finding.get("check_id") in ("STR-14", "STR-19") else []), "names_line": names_line(finding),
        # A rule not yet validated on real sites (maya_audit.launch_gate): a label and a sentence, or None.
        "unverified": unverified(finding),
    }


def unverified(finding: dict[str, Any]) -> dict[str, Any] | None:
    """{"label", "note", "items"} for a finding that carries launch-gate items (`launch_gated`), in the reader's
    language; None for any other."""
    gated = [str(item) for item in finding.get("launch_gated") or []]
    if not gated:
        return None
    numbers = launch_gate.gate_items(gated)
    return {"label": t("result.unverified.label"), "items": numbers or gated,
            "note": t("result.unverified.note", items=", ".join(numbers) if numbers else "; ".join(gated))}


def review_item(entry: dict[str, Any]) -> dict[str, Any]:
    """Something a person should look at, as a row: the engine's own words, and the same in the reader's language."""
    title, title_ok = wording.title(entry["check_id"], entry["title"])
    why, why_ok = wording.expected(entry.get("why_review") or "")
    action, action_ok = wording.fix(entry.get("suggested_action") or "")
    return {"id": entry["id"], "check_id": entry["check_id"], "title": entry["title"], "title_shown": title,
            "why": entry.get("why_review"), "why_shown": why, "action": entry.get("suggested_action"), "action_shown": action,
            "untranslated": not (title_ok and why_ok and action_ok), "pages_total": (entry.get("scope") or {}).get("count") or 0,
            "details": detail_texts(entry)}


def _source(finding: dict[str, Any]) -> dict[str, Any] | None:
    source = (finding.get("evidence") or {}).get("source") or {}
    if (finding.get('evidence') or {}).get('header_observations'):
        return {'reader':source.get('reader'),'label':t('source.http_headers'),'notice':None}
    if source.get("reader") != "firecrawl":
        if source.get("reader") and source.get("label"):
            return {"reader": source["reader"], "label": source["label"], "notice": source.get("notice")}
        return None
    rendered = "browser" in (source.get("why") or "")
    if source.get("why") == MAIN_WHY:  # the page reader of every audit: named, with no warning attached
        return {"reader": "firecrawl", "label": t("fc.source.main"), "notice": None}
    return {"reader": "firecrawl", "label": t("fc.source.render" if rendered else "fc.source.blocked"),
            "notice": None if rendered else t("fc.notice")}


def action_plan(report: dict[str, Any], role: str | None = None) -> dict[str, Any]:
    """Fix now (S1, S2), fix next (S3), improve later (S4 and notes). `role` keeps one owner's items."""
    rows = [item(f, bool(single_page_of(report))) for f in findings(report)]
    from .action_priority import performance_rows, ordered
    rows = ordered(rows + performance_rows(report.get("dataforseo"), report.get("crux")))
    if role:
        rows = [row for row in rows if row["estimates"]["owner"] == role]
    groups = [{"id": name, "label": t(f"result.group.{name}"), "severities": list(levels),
               "items": merged([row for row in rows if row["severity"] in levels])} for name, levels in GROUPS]
    return {"role": role, "role_label": t(f"owner.{role}") if role else None, "groups": groups,
            "total": len(rows), "estimates_note": t("result.estimates.note")}


MIN_PAGES_FOR_FIRST_ACTION = 3
BLOCKED_PART = "pages Maya was blocked or rate-limited on (INT-1)"


def live_pages_read(report: dict[str, Any]) -> int:
    """Pages whose content the audit could actually read: answered, not a redirect, not blocked."""
    return sum(1 for page in report["crawl"].get("pages") or []
               if page.get("fetch_class") == "ok" and page.get("status") is not None and not 300 <= page["status"] < 400)


def pages_read(report: dict[str, Any]) -> int:
    """Pages read: the report's own figure (`audit_status.content_coverage.pages_read`, DECISIONS 170). A page is a
    distinct HTML document, whoever read it; a PDF, and a second address of a page already read, are not pages. A
    report saved before the figure existed is counted the same way at display time, from its own records."""
    return read_coverage(report)["pages_read"]


def read_coverage(report: dict[str, Any]) -> dict[str, Any]:
    """`pages_read`, `read_by` (three numbers that add up to `total`) and `other_addresses` for a report: its own
    content coverage as displayed, or, for a report older than schema 1.6, the same engine count applied to it."""
    shown = content_coverage_shown(report)
    if shown:
        return shown
    counts = read_counts(report.get("crawl") or {}, report.get("firecrawl"))
    return {"pages_read": counts["pages"], "read_by": counts["read_by"], "other_addresses": counts["other_addresses"]}


def also_fetched(other: dict[str, Any] | None) -> str | None:
    """"Also fetched: 5 files (PDF or other documents) and 7 addresses that lead to a page already read.", in the
    reader's language. None when every address fetched was a page."""
    files, same = int((other or {}).get("files") or 0), int((other or {}).get("same_page") or 0)
    if not files and not same:
        return None
    return t("result.pages.also." + ("both" if files and same else "files" if files else "same"), files=files, same=same)


def unread_figures(report: dict[str, Any]) -> tuple[int, int] | None:
    """(pages read, addresses known and not read) when a page reader read pages: the two figures every "not read"
    sentence of this report uses. None otherwise (the checks' own figures are then the report's)."""
    reader = report.get("firecrawl") or {}
    known = ((report.get("audit_status") or {}).get("content_coverage") or {}).get("known_urls_not_read")
    if not (reader.get("used") and reader.get("pages_read") and isinstance(known, int)):
        return None
    return pages_read(report), known


def reader_pages_read(report: dict[str, Any]) -> int:
    """Pages whose content came through Firecrawl after Maya's own crawler was refused."""
    reader = report.get("firecrawl") or {}
    return (reader.get("pages_read") or 0) if reader.get("used") else 0


def main_reader(report: dict[str, Any]) -> dict[str, Any] | None:
    """The report's Firecrawl section when Firecrawl was this audit's page reader and read pages; None otherwise."""
    reader = report.get("firecrawl") or {}
    return reader if reader.get("used") and reader.get("pages_read") and reader.get("purpose") == MAIN_PURPOSE else None


def blocked(report: dict[str, Any]) -> dict[str, Any] | None:
    """The block card of a site that could not be read. A site that challenged Maya's own crawler and was then read
    through Firecrawl is not one: the challenge is a note under AI crawler access (ACC-9), not a headline."""
    return None if main_reader(report) else challenged(report)


def challenged(report: dict[str, Any]) -> dict[str, Any] | None:
    """Who blocked the audit and what to do about it, when INT-1 says the audit was degraded by blocking.

    Reads the engine's own record (INT-1 `blocked_by`); for a report saved before that field existed, the same
    engine function is applied to the headers INT-1 kept. Nothing here guesses beyond what the responses said.
    """
    gate = next((g for g in report["gates"] if g["check_id"] == "INT-1"), None)
    evidence = (gate or {}).get("evidence") or {}
    impaired = evidence.get("impaired_pages") or []
    if not gate or gate.get("state") != "degraded" or not impaired:
        return None
    blockers = evidence.get("blocked_by")
    if blockers is None:
        blockers = describe_blockers([b for b in (identify_blocker(p.get("status"), p.get("headers") or {}, p.get("evidence") or [],
                                                                    p.get("fetch_class") or "") for p in impaired) if b])
    who = blocker_phrase(blockers)
    who = wording.term(who) or who  # "a bot challenge", "the site or its firewall": in the reader's language
    read = live_pages_read(report)
    through_reader = reader_pages_read(report)  # content only: what Maya's own crawler was refused stays the access evidence
    requested = evidence.get("pages_fetched") or len(impaired)
    agent = report["crawl"].get("product_token") or report["crawl"].get("user_agent") or "Maya-Audit"
    return {"who": who, "name": blockers[0]["name"] if blockers else None, "kind": blockers[0]["kind"] if blockers else None,
            "blocked_by": blockers, "pages_read": read, "pages_requested": requested,
            # Requests the site answered with a block, a challenge or a rate limit (INT-1's own list).
            "blocked_requests": len(impaired),
            # Steps for the site's owner, shown only here: on the card of a site nothing could read.
            "allowlist": {"title": t("blocked.allowlist.title"), "note": t("blocked.allowlist.note", agent=report["crawl"].get("user_agent") or agent),
                          "blocks": [{**block, "title_shown": wording.label(block["title"])[0], "steps_shown": [wording.line(step)[0] for step in block["steps"]]}
                                     for block in allowlist.instructions(agent, report["crawl"].get("user_agent") or agent, blockers[0]["name"] if blockers else None)]},
            "sections": {"who": t("blocked.section.who"), "meaning": t("blocked.section.meaning"), "next": t("blocked.next"),
                         "firecrawl": t("blocked.section.firecrawl"), "status": t("blocked.section.status")},
            "headline": t("blocked.headline", who=who),
            "lines": [t("blocked.what", who=who, read=read, requested=requested), t("blocked.common"), t("blocked.meaning"),
                      t("blocked.reader", count=through_reader) if through_reader else t("blocked.no_bypass")],
            "next_steps": [t("blocked.step.allow", agent=agent), t("blocked.step.verify"), t("blocked.step.later")]}


BLOCK_CHECK = "ACC-9"


def pages_stat(report: dict[str, Any], block: dict[str, Any] | None, read: int, cap: int | None) -> dict[str, Any]:
    """The page counter of the results card. On a blocked audit it counts what could be read, not what was asked for:
    "Pages checked: 1" beside "0 could be read" says two things at once."""
    counts = report["page_counts"]
    reader = main_reader(report)
    cover = read_coverage(report)
    # What was fetched that is not a page (a PDF, a second address of a page already read): said beside the count.
    also = also_fetched(cover.get("other_addresses"))
    if reader:  # Firecrawl is the page reader: say how many pages, and through whom
        own = int((cover.get("read_by") or {}).get("maya_only") or 0)
        how = t("result.pages.via") if own <= 0 else t("result.pages.via.some", count=read - own, own=own)
        return {"value": read, "label": t("result.pages.read"), "blocked": False, "reader": True, "detail": how, "also": also,
                "sentence": t("result.pages.sentence", pages=read) + (" " + also if also else ""),
                "line": t("result.pages.read.line", read=read, how=how)}
    if not block:
        return {"value": counts["pages_checked"], "label": t("result.pages"), "blocked": False, "also": also,
                "detail": t("result.pages.detail", checked=counts["pages_checked"], cap=cap, redirects=counts["redirects"])}
    count = block["blocked_requests"]
    detail = t("result.pages.blocked.one") if count == 1 else t("result.pages.blocked.many", count=count)
    through_reader = reader_pages_read(report)
    if through_reader:  # the pages were read after all: say by whom, and that the block still stands
        detail = (t("result.pages.firecrawl.some", count=through_reader, live=block["pages_read"]) if block["pages_read"]
                  else t("result.pages.firecrawl.all"))
    return {"value": read, "label": t("result.pages.readable"), "blocked": True, "detail": detail,
            "line": t("result.pages.readable.line", read=read, blocked=detail)}


def redirected(report: dict[str, Any]) -> dict[str, Any] | None:
    """The start address sends visitors to another site: say so, and offer that site."""
    crawl = report["crawl"]
    first = next((p for p in crawl.get("pages") or [] if p.get("discovered_via") == "start"), None)
    target = (first or {}).get("redirect_location")
    if not first or not target or not (first.get("status") and 300 <= first["status"] < 400):
        return None
    here, there = urlsplit(first["url"]).hostname or "", urlsplit(target).hostname or ""
    if not there or here.removeprefix("www.") == there.removeprefix("www."):
        return None
    return {"from": first["url"], "to": target, "to_host": there, "message": t("redirect.message", start=first["url"], target=target),
            "offer": t("redirect.offer", host=there)}


def coverage_gaps(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Every part of a check's question that went unanswered, in the engine's words.

    The same gap reported by several checks (a page cap leaves all of them short) is listed once, with the
    checks it applies to. A check that found nothing in what it could read but could not read everything is
    here too: that is "partial", never a pass.
    """
    gaps: dict[tuple[Any, Any], dict[str, Any]] = {}
    figures = unread_figures(report)
    for check in report["checks"] + report.get("answer_engine_panel", []):
        parts = (check.get("coverage") or {}).get("not_assessed") or []
        if figures:  # one "not read" figure: the report's own, also where a saved check counted Maya's own crawl
            parts = restated(parts, *figures)
        if check["status"] == "not_assessed" and not parts:
            parts = [{"part": check["title"], "reason": check["summary"], "count": None}]
        for part in parts:
            if part.get("part") in CRAWL_GAP_NAMES:
                continue  # one fact about the whole audit, said once (`read_only_note`), not once per check
            gap = gaps.setdefault((part.get("part"), part.get("reason")), {
                "checks": [], "part": part.get("part"), "reason": part.get("reason"), "count": part.get("count"),
                "whole_check": check["status"] == "not_assessed"})
            if check["check_id"] not in gap["checks"]:
                gap["checks"].append(check["check_id"])
    rows = list(gaps.values())
    block = challenged(report)
    if block:
        # Everything that could not be checked for the same reason is one line, not one per check.
        nothing_read = block["pages_read"] == 0
        same = [gap for gap in rows if gap["part"] == BLOCKED_PART
                or (nothing_read and gap["whole_check"] and set(gap["checks"]) <= PAGE_DEPENDENT)]
        if same:
            checks = sorted({check for gap in same for check in gap["checks"]}, key=check_id_key)
            direct = main_reader(report) is not None
            rows = [{"checks": checks, "part": t("direct.gap.part") if direct else t("blocked.gap.part", who=block["who"]),
                     "reason": t("direct.gap.reason", checks=len(checks), who=block["who"]) if direct
                     else t("blocked.gap.reason", checks=len(checks), read=block["pages_read"]),
                     "count": None, "whole_check": nothing_read, "blocked": True}] + [gap for gap in rows if gap not in same]
    for gap in rows:
        gap["checks_label"] = ", ".join(gap["checks"]) if len(gap["checks"]) <= 4 else t("result.coverage.checks", count=len(gap["checks"]))
        if gap.get("blocked"):  # worded by this layer already (`blocked.gap.*`, `direct.gap.*`)
            gap.update(part_shown=gap["part"], reason_shown=gap["reason"], untranslated=False)
            continue
        # `part` and `reason` stay the report's own English; a person reads `part_shown` and `reason_shown`.
        first = gap["checks"][0] if gap["checks"] else None
        part, part_ok = wording.label(gap["part"], check_id=first)
        reason, reason_ok = wording.line(gap["reason"], check_id=first, capital=True)
        gap.update(part_shown=_first_capital(part), reason_shown=reason, untranslated=not (part_ok and reason_ok))
    return rows


def _first_capital(text: str | None) -> str | None:
    return wording._capital(text, current_language()) if text and current_language() != "en" else text


def known_not_read(report: dict[str, Any]) -> int:
    """Addresses known and not read: the report's own figure (schema 1.6 on; with a reader it leaves out what the
    reader read of the pages Maya did not fetch), or, for an older report, what its crawl did not fetch."""
    known = ((report.get("audit_status") or {}).get("content_coverage") or {}).get("known_urls_not_read")
    return known if isinstance(known, int) else len((report.get("crawl") or {}).get("not_fetched_urls") or [])


def clean_on_read(report: dict[str, Any]) -> str:
    """"No problem found on the 50 pages read (9 not read)", in the reader's language: what a check that found nothing
    says when it is partial only because pages were found and not read (DECISIONS 189). Computed from the report's
    one pair of figures at display, so a saved report shows it without being rewritten."""
    read, unread = pages_read(report), known_not_read(report)
    return t("result.clean_on_read", n=read, m=unread) if unread else t("result.clean_on_read.cut", n=read)


def _read_only_note(report: dict[str, Any]) -> str | None:
    """One sentence for "the checks ran, but only on what was read". None when everything found was read."""
    unread = known_not_read(report)
    limited = sum(1 for check in report["checks"] if any(
        part.get("part") in CRAWL_GAP_NAMES for part in (check.get("coverage") or {}).get("not_assessed") or []))
    if not unread and not limited:
        return None
    read = pages_read(report)
    left_out = sum(int(count or 0) for count in (((report.get("audit_status") or {}).get("content_coverage") or {}).get("unread_left_out") or {}).values())
    return (t("result.coverage.read_only", read=read, unread=unread) + (" " + t("result.coverage.left_out", n=left_out) if left_out else "")
            if unread else t("result.coverage.read_only.cut", read=read)) + " " + t("result.coverage.read_only.checks", checks=limited)


def _areas(report: dict[str, Any]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for check in sorted(report["checks"], key=lambda c: check_id_key(c["check_id"])):
        groups.setdefault(_family(check["check_id"]), []).append(check)
    out = []
    said = clean_on_read(report)
    said_in_english = clean_on_read_sentence(pages_read(report), known_not_read(report))
    for family in (*FAMILIES, "other"):
        checks = groups.get(family)
        if not checks:
            continue
        out.append({"area": family, "label": t(f"result.family.{family}"),
                    "problems": sum(f["severity"] != "Info" for c in checks for f in c["findings"]),
                    "notes": sum(f["severity"] == "Info" for c in checks for f in c["findings"]),
                    "not_checked": sum(c["status"] == "not_assessed" for c in checks),
                    "partial": sum(c["status"] == "partial" for c in checks),
                    # A check that found nothing on the pages read and is partial only because pages were not read
                    # carries the sentence that says so (`read_only`, `read_only_shown`). It stays partial.
                    "checks": [{**check_row(c), **({"read_only": True, "read_only_shown": said, "read_only_english": said_in_english}
                                                   if clean_on_what_was_read(c) else {})} for c in checks]})
    return out


def rendering(report: dict[str, Any]) -> dict[str, Any]:
    """Whether pages were opened in a browser, as the report records it."""
    render = report["crawl"].get("render") or {}
    mode = render.get("mode")
    sampled = mode == "raw_plus_sampled_render"
    reason = None if sampled else (render.get("reason") or report["crawl"].get("collector_errors", {}).get("render"))
    return {"mode": mode or "unknown", "available": sampled, "pages_rendered": len(render.get("pages") or {}) if sampled else 0,
            "reason": reason, "reason_shown": wording.reason(reason)[0] if reason else None,
            "label": t("result.rendering.on", count=len(render.get("pages") or {})) if sampled else t("result.rendering.off")}


def method(report: dict[str, Any], audit: dict[str, Any] | None = None) -> dict[str, Any]:
    """How the audit was done: what a reader needs to judge how far the results reach."""
    crawl, config = report["crawl"], report["crawl"].get("config") or {}
    return {"start_url": crawl.get("start_url"), "started_at": crawl.get("started_at"), "finished_at": crawl.get("finished_at"),
            "elapsed_s": crawl.get("elapsed_s"), "page_cap": (audit or {}).get("page_cap") or config.get("max_pages"),
            "pages_checked": pages_read(report) if (report.get("firecrawl") or {}).get("pages_read") else report["page_counts"]["pages_checked"], "redirects": report["page_counts"]["redirects"],
            "requests": len(crawl.get("requests") or []), "discovered": len(crawl.get("discovered_urls") or []),
            "not_fetched": len(crawl.get("not_fetched_urls") or []), "request_delay_s": config.get("request_delay_s"),
            "time_limit_s": config.get("time_limit_s"), "user_agent": crawl.get("user_agent"),
            "key_pages": list(config.get("key_pages") or []), "sessions": len(crawl.get("sessions") or []),
            "stop_reason": crawl.get("stop_reason"), "stop_detail": crawl.get("stop_detail"),
            # Why the crawl stopped, as a person reads it: the code as a word, the detail in the reader's language.
            "stop_shown": _stop_shown(crawl.get("stop_reason"), crawl.get("stop_detail")),
            "rendering": rendering(report), "robots_obeyed": True,
            "optional_sources": {"backlinks": any(c.get("status") != "not_assessed" and c.get("check_id") in ("DFS-1", "DFS-2") for c in (report.get("dataforseo") or {}).get("checks", [])),
                                 "search": any(c.get("status") != "not_assessed" and c.get("check_id") in ("DFS-3", "DFS-4", "DFS-5", "DFS-6") for c in (report.get("dataforseo") or {}).get("checks", [])),
                                 "ai_data": any(c.get("status") != "not_assessed" and c.get("check_id") in ("DFS-7", "DFS-8") for c in (report.get("dataforseo") or {}).get("checks", [])),
                                 "lighthouse": bool((report.get("dataforseo") or {}).get("lighthouse")) or any(c.get("status") != "not_assessed" and c.get("check_id") in ("DFS-9", "DFS-10", "DFS-11") for c in (report.get("dataforseo") or {}).get("checks", [])), "citations": bool(config.get("citations_file")),
                                 "search_console": bool(config.get("gsc_site_url")), "bing": bool(config.get("bing_site_url")),
                                 "pagespeed": bool(config.get("pagespeed_enabled")), "access_logs": bool(config.get("access_logs"))},
            "schema_version": report["schema_version"], "generation": report.get('generation'),
            "whole_job_finished_at": (audit or {}).get('finished_at') or (report.get("generation") or {}).get("whole_job_finished_at")}


def _stop_shown(code: str | None, detail: str | None) -> str:
    if current_language() == "en":
        return f"{code}: {wording.english(detail or '')}"
    whole, ok = wording.reason(f"{code}: {detail}")  # "page_cap: page cap of 50 reached", by the same table as the outcome sentence
    if ok:
        return whole
    return f"{wording.term(code or '') or code}: {wording.line(detail)[0]}"


def brand(report: dict[str, Any], profile: dict[str, Any] | None) -> dict[str, Any]:
    """The name the cover shows, in the order of `maya_audit.brand` (DECISIONS 201): the name confirmed for this site
    (typed or saved), else the report's own brand (`report["brand"]`: the site's own name, or the address split into
    the site's words), else the address. Anything not confirmed is labelled with where it came from."""
    host = urlsplit(report["crawl"].get("start_url") or "").hostname or ""
    country = ((profile or {}).get("countries") or [None])[0]
    confirmed = ((profile or {}).get("brand_name") or "").strip()
    found = report.get("brand") if isinstance(report.get("brand"), dict) else {}
    if confirmed or (found.get("confirmed") and found.get("name")):
        return {"name": confirmed or found["name"], "confirmed": True, "label": None, "country": country}
    if found.get("source") == "site" and found.get("name"):
        where = found.get("found_in") or "title"
        source = t(f"result.brand.source.{where}") if has(f"result.brand.source.{where}") else where
        return {"name": found["name"], "confirmed": False, "label": t("result.brand.from_site", source=source), "country": country}
    if found.get("source") == "domain" and found.get("name"):
        return {"name": found["name"], "confirmed": False, "label": t("result.brand.from_domain"), "country": country}
    return {"name": host.removeprefix("www."), "confirmed": False, "label": t("result.brand.from_domain"), "country": country}


def status_view(report: dict[str, Any]) -> dict[str, Any] | None:
    """The report's `audit_status` with a label for each state: direct access, content coverage, real AI crawlers.
    None for a report made before schema 1.6, which holds no such section; nothing is reconstructed for it."""
    status = report.get("audit_status")
    if not isinstance(status, dict):
        return None
    # Content coverage as displayed: pages (not addresses) and one stop sentence, also for a report saved before both.
    direct, coverage, vendor = status["direct_access"], content_coverage_shown(report), status["vendor_crawler_evidence"]
    timing = status.get("timing") or {}
    from maya_audit.report import cache_note

    # English: the engine's own sentences, word for word. Another language: the same facts, worded here from the
    # report's fields (never by taking the English sentence apart); the reasons through `wording`'s table.
    english = current_language() == "en"
    notes = None if english else status_notes(report)
    said = wording.english  # the engine's own sentences, with "1 page(s)" said as "1 page"
    # The reasons follow the note as a sentence of their own, so the first begins with a capital.
    reasons = "; ".join(coverage["reasons"])
    coverage_note = said(coverage["note"] + (" " + reasons[:1].upper() + reasons[1:] + "." if reasons else "")) if english else notes["coverage"]
    return {"title": t("status.title"),
            "rows": [{"id": "direct_access", "label": t("status.direct"), "state": direct["state"],
                      "state_label": t(f"status.direct.{direct['state']}"), "note": said(direct["note"]) if english else notes["direct"]},
                     {"id": "content_coverage", "label": t("status.coverage"), "state": coverage["level"],
                      "state_label": t(f"status.coverage.{coverage['level']}"), "note": coverage_note},
                     {"id": "vendor_crawler_evidence", "label": t("status.vendor"), "state": vendor["state"],
                      "state_label": t(f"status.vendor.{vendor['state']}"), "note": said(vendor["note"]) if english else notes["vendor"]}],
            "summary": status["summary"], "coverage": coverage,
            "cache_note": said(cache_note(report.get("firecrawl")) or "") or None if english else notes["cache"],
            "untranslated": 0 if english else notes["untranslated"],
            "timing": timing,
            "duration_line": (t("status.duration", whole=timing["all_phases_s"], crawl=timing.get("crawl_and_checks_s"))
                              if timing.get("all_phases_s") is not None else t("status.duration.crawl", crawl=timing.get("crawl_and_checks_s")))}


def status_notes(report: dict[str, Any]) -> dict[str, Any]:
    """The three rows of "What this audit covers" and the saved-copies note, worded from the report's own fields
    (`audit_status`, `crawl.stop_reason`, `firecrawl.pages`) in the reader's language. The numbers are the report's."""
    status = report["audit_status"]
    direct, coverage, vendor = status["direct_access"], content_coverage_shown(report), status["vendor_crawler_evidence"]
    answers, requests = direct.get("by_response") or {}, direct.get("page_requests") or 0
    impaired = (answers.get("blocked") or 0) + (answers.get("rate_limited") or 0)
    state = direct["state"]
    if state == "readable":
        said = t("status.note.direct.readable.impaired" if impaired else "status.note.direct.readable", ok=answers.get("ok") or 0,
                 requests=requests, impaired=impaired)
    elif state in ("challenged", "rate_limited"):
        said = t(f"status.note.direct.{state}", count=answers.get("blocked" if state == "challenged" else "rate_limited") or 0, requests=requests)
    else:  # no page was requested: because no answer reached this computer, or for another reason
        not_reached = not requests and (report.get("crawl") or {}).get("stop_reason") == "network_problem"
        said = t("status.note.direct.not_reached" if not_reached else "status.note.direct.unknown")
    reasons = [wording.reason(text) for text in coverage.get("reasons") or []]
    level = coverage["level"] if coverage["level"] in ("none", "partial", "complete_sample") else "partial"
    covered = (t("status.note.coverage.single") if single_page_of(report) and level == "complete_sample"
               else t(f"status.note.coverage.{level}", pages=coverage.get("pages_read") or 0))
    also = also_fetched(coverage.get("other_addresses"))
    if also:
        covered += " " + also
    if reasons:
        covered += " " + t("status.note.reasons", reasons="; ".join(text for text, _ in reasons))
    known = vendor["state"] if vendor["state"] in ("verified_log_evidence", "limited_user_agent_probe", "not_measured") else "not_measured"
    read = [row for row in (report.get("firecrawl") or {}).get("pages") or [] if row.get("outcome") == "read"]
    saved = sorted(str(row.get("observed_at") or "") for row in read if row.get("from_cache"))
    cached = t("status.note.cache", saved=len(saved), read=len(read), oldest=saved[0][:16].replace("T", " ")) if saved else None
    return {"direct": said, "coverage": covered, "vendor": t(f"status.note.vendor.{known}"), "cache": cached,
            "untranslated": sum(1 for _, ok in reasons if not ok)}


def speed_view(section: dict[str, Any]) -> dict[str, Any]:
    """The report's Core Web Vitals section as a person reads it. English: the engine's sentence. Another language: an
    assessed section is worded from its own figures (`metrics`: the metric's name and value stay, the rating is
    translated); a section that is not available says why through `wording`."""
    rows = [{**row, "rating_shown": t(f"crux.rating.{row['rating']}") if row.get("rating") else ""} for row in section.get("metrics") or []]
    said, ok = wording.line(section.get("summary"))
    if current_language() != "en" and section.get("status") == "assessed" and not ok:
        worst = [f"{row['label']} {row['shown']} ({row['rating_shown']})" for row in rows if row.get("rating") and row["rating"] != "good"]
        said, ok = (t("practical.opp.cwv.worst", worst="; ".join(worst)) if worst else t("practical.opp.cwv.partial")), True
    return {**section, "metrics": rows, "summary_shown": said, "source_shown": wording.label(section.get("source"))[0], "untranslated": not ok}


def archives_view(view: dict[str, Any] | None) -> dict[str, Any] | None:
    """The archived-copies section (maya_audit.archives.view) with every sentence as a person reads it."""
    if not view:
        return view
    sources = [{**source, "notes_shown": [wording.line(note)[0] for note in source.get("notes") or []],
                "pages": [{**page, "label_shown": wording.line(page.get("label"))[0]} for page in source.get("pages") or []],
                "findings": [{**row, "title_shown": wording.title(row["check_id"], row["title"])[0]} for row in source.get("findings") or []]}
               for source in view["sources"]]
    return {**view, "notice_shown": wording.line(view.get("notice"))[0], "sources": sources}


def ownership_view(section: dict[str, Any] | None) -> dict[str, Any] | None:
    """The report's ownership section, with its summary and its steps as a person reads them."""
    if not section:
        return section
    return {**section, "summary_shown": wording.line(section.get("summary"))[0],
            "instructions_shown": [wording.line(step)[0] for step in section.get("instructions") or []]}


def spend_view(report: dict[str, Any]) -> dict[str, Any]:
    """What the audit cost, from the report's own records: estimated, actual and possibly billed, per provider.
    Firecrawl is in credits; dollars only when a price per credit is configured."""
    paid, reader = report.get("dataforseo") or {}, report.get("firecrawl") or {}
    calls = paid.get("calls") or []
    reads = reader.get("calls") or []
    return {"dataforseo": None if not paid else {
                "estimated_usd": paid.get("estimated_usd"), "cost_usd": paid.get("cost_usd"), "requests_sent": paid.get("requests_sent"),
                "possibly_billed": sum(1 for call in calls if call.get("billing_status") == "possibly_billed"),
                "from_cache": sum(1 for call in calls if call.get("from_cache"))},
            "firecrawl": None if not reader else {
                "credits": (reader.get("credits") or {}).get("used_or_reserved"), "estimated_max_credits": (reader.get("credits") or {}).get("estimated_max"),
                "usd": (reader.get("usd") or {}).get("used_or_reserved"), "usd_known": (reader.get("usd") or {}).get("per_credit") is not None,
                "requests_sent": reader.get("requests_sent"),
                "possibly_billed": sum(1 for call in reads if call.get("billing_status") == "possibly_billed"),
                "from_cache": sum(1 for call in reads if call.get("from_cache")),
                "zero_data_retention": (reader.get("zero_data_retention") or {}).get("status"),
                # The report's own word for it ("applied", "waived by the user for this audit"), as a person reads it.
                "zero_data_retention_shown": _word((reader.get("zero_data_retention") or {}).get("status"))}}


def _word(text: str | None) -> str | None:
    """A short state the report names in English, in the reader's language; the report's own word when there is none."""
    if not text or current_language() == "en":
        return text
    return wording.term(text) or wording.reason(text)[0]


def start_failed(report: dict[str, Any]) -> dict[str, Any] | None:
    """The start address answered with an error and the audit ran from another page (report
    `problem_summary.start_address`, schema 1.14): the report's own three values and the sentence that says it, in the
    reader's language. None for every other audit, and for a report saved before 1.14."""
    found = (report.get("problem_summary") or {}).get("start_address")
    if not isinstance(found, dict) or not found.get("audited_from"):
        return None
    parts = urlsplit(str(found.get("entered") or ""))
    path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    return {"entered": found.get("entered"), "status": found.get("status"), "audited_from": found.get("audited_from"),
            "message": t("result.headline.start_failed", status=found.get("status"), path=path, **{"from": found.get("audited_from")})}


def headline(pages: int, problems: int, by_severity: dict[str, int], notes: int, page_checks: dict[str, Any] | None = None,
             single: bool = False, start: dict[str, Any] | None = None) -> str:
    """"15 problems found on 50 pages (1 high, 5 medium, 9 low) + 12 notes", in the reader's language. In English it is
    the sentence the engine writes in the Markdown report (maya_audit.report.headline), word for word: when fewer than
    half of the page checks could run (`page_checks.limited`), that is its first sentence."""
    def counted(key: str, count: int) -> str:
        return t(f"result.headline.{key}.one") if count == 1 else t(f"result.headline.{key}.many", count=count)

    where = counted("pages", pages)
    ran = page_checks or {}
    limited = t("result.headline.limited", could_run=ran["could_run"], total=ran["total"]) if ran.get("limited") else ""
    if problems:
        levels = ", ".join(t(f"result.headline.{level}", count=by_severity[level]) for level in SEVERITIES[:4] if by_severity.get(level))
        text = t("result.headline.found", problems=counted("problems", problems), pages=counted("content_pages", pages)) + (f" ({levels})" if levels else "")
    elif limited:
        text = t("result.headline.limited.none", could_run=ran["could_run"], pages=where)
    else:
        text = t("result.headline.none", pages=where)
    text = (limited + " " if limited else "") + text + (f" + {counted('notes', notes)}" if notes else "")
    text += ". " + t("result.headline.single") if single else ""  # a single-page audit says what it did not look at
    # A start address that answered with an error is said first, as the engine's own headline says it (`start_failed`).
    return f"{start['message']} {text}" if start else text


def problems_of(report: dict[str, Any], affected: dict[str, list[str]] | None, pages_checked: int) -> dict[str, Any]:
    """The report's own totals and problems by page. A report saved before schema 1.9 holds none: the same engine
    function is applied to its findings, with the full page lists saved beside it when the caller has them. A report
    of schema 1.9 holds the rows without what is wrong on each page (`items`, schema 1.10): the engine adds them from
    the report's findings. A report saved before 1.11 does not say how many of its page checks could run
    (`page_checks`): the engine counts them from the report's own checks. The saved report is not changed. Nothing is
    counted here."""
    saved = report.get("problem_summary")
    if isinstance(saved, dict):
        return with_page_items(saved, findings(report), report.get("checks") or [])
    return problem_summary(findings(report), affected or None, pages_checked=pages_checked, checks=report.get("checks") or [])


def outcome_label(outcome: str | None, reason: str | None) -> str | None:
    """The cover's word for the audit's outcome. An audit that stopped at its page limit and at nothing else says so:
    "Partial audit: 50 of 832 pages read (page limit)" (DECISIONS 226), not "Audit incomplete"."""
    if not outcome:
        return None
    found = PARTIAL_PAGE_CAP_SENTENCE.match(reason or "") if outcome == "INCOMPLETE" else None
    if found:
        return t("result.outcome.partial_page_cap", read=int(found["read"]), total=int(found["total"]))
    return t(f"result.outcome.{outcome}")


def build(report: dict[str, Any], *, outcome: str | None, reason: str | None, backlinks: dict[str, Any] | None = None,
          resumable: bool = False, profile: dict[str, Any] | None = None, audit: dict[str, Any] | None = None,
          affected: dict[str, list[str]] | None = None) -> dict[str, Any]:
    """The results card for one audit that has a report (finished, or stopped part-way)."""
    check_readable(report)
    crawl = report["crawl"]
    rows = [item(f, bool(single_page_of(report))) for f in findings(report)]
    counts = Counter(row["severity"] for row in rows)
    review = [review_item(r) for check in report["checks"] for r in check.get("review_items") or []]
    gaps = coverage_gaps(report)
    sessions = len(crawl.get("sessions") or [])
    problems = [row for row in rows if row["requires_fix"]]
    plan = action_plan(report)
    read = pages_read(report)
    # With almost nothing read, "the first thing to fix" would be picked from almost no evidence.
    candidates = [r for group in plan["groups"] for r in group["items"] if r["requires_fix"]]
    first = candidates[0] if candidates and read >= MIN_PAGES_FOR_FIRST_ACTION else None
    withheld = t("result.first_action.withheld", read=read, needed=MIN_PAGES_FOR_FIRST_ACTION) if problems and first is None else None
    how = method(report, audit)
    block = blocked(report)
    if block:
        # The card at the top of the results explains the block once; its own finding row only points there.
        for row in rows:
            row["in_block_card"] = row["check_id"] == BLOCK_CHECK
    stat = pages_stat(report, block, read, how["page_cap"])
    checked = pages_read(report) if (report.get("firecrawl") or {}).get("pages_read") else report["page_counts"]["pages_checked"]
    by_severity = {s: counts.get(s, 0) for s in SEVERITIES}
    totals = problems_of(report, affected, checked)
    shown_reason, reason_ok = wording.outcome(reason)
    def compact_row(row):
        return {k:v for k,v in row.items() if k != "evidence_record"} if row else None
    return {
        "site": crawl.get("origin") or crawl.get("start_url"),
        "host": urlsplit(crawl.get("start_url") or "").hostname,
        "brand": brand(report, profile),
        "schema_version": report["schema_version"],
        # The engine's own outcome and sentence. A report that was written is not thereby a complete audit.
        # `reason` is the engine's sentence as stored; `reason_shown` is that sentence in the reader's language.
        "outcome": {"code": outcome, "label": outcome_label(outcome, reason), "reason": reason,
                    "reason_shown": shown_reason, "reason_untranslated": not reason_ok,
                    "complete": outcome == "COMPLETED", "resumable": resumable,
                    "stop_reason": crawl.get("stop_reason"),
                    "note": None if outcome == "COMPLETED" else t("result.partial_note")},
        # Every problem and every note, on how many pages: the first line of the card and of the printed summary.
        "headline": headline(checked, len(problems), by_severity, counts.get("Info", 0), totals.get("page_checks"),
                             single=bool(single_page_of(report)), start=start_failed(report)),
        # The start address answered with an error and the audit ran from another page. None otherwise.
        "start_address": start_failed(report),
        # A single-page audit: its address and the title every output puts first. None for an ordinary audit.
        "single_page": ({"url": single_page_of(report), "title": t("result.single.title", url=single_page_of(report)),
                         "note": t("result.headline.single")} if single_page_of(report) else None),
        # The engine's totals and its problems by page (schema 1.9; what is wrong on each page, 1.10), or the same engine
        # functions applied to an older report.
        "problem_summary": totals,
        "counts": {"pages_checked": checked, "redirects": report["page_counts"]["redirects"],
                   "page_cap": how["page_cap"], "discovered": how["discovered"], "not_fetched": how["not_fetched"],
                   "problems": len(problems), "notes": counts.get("Info", 0),
                   "by_severity": by_severity, "needs_review": len(review),
                   "not_checked": len(gaps), "findings_total": len(rows)},
        "rendering": how["rendering"],
        "summary_line": t("result.summary_line", pages=read if block or main_reader(report) else report["page_counts"]["pages_checked"], gaps=len(gaps)),
        # For a page whose headline already says how many pages: only what could not be checked. None when nothing was left out.
        "gaps_line": t("result.gaps_line", gaps=len(gaps)) if gaps else None,
        "first_action": compact_row(first), "first_action_withheld": withheld,
        "blocked": block, "redirected": redirected(report), "pages_read": read, "pages_stat": stat,
        "block_pointer": t("blocked.pointer") if block else None,
        # Under a heading that counts problems, only problems: notes fill the list only when there is no problem at all.
        # The same check saying the same thing about other pages is one row (DECISIONS 225).
        "top": [compact_row(row) for row in merged(problems or rows)[:TOP]],
        "top_title": top_title(min(TOP, len(problems)), len(problems), "result.top.title"),
        "more_findings": max(0, len(rows) - TOP),
        "plan_groups": [{"id": g["id"], "label": g["label"], "count": len(g["items"])} for g in plan["groups"]],
        "review": review,
        "coverage": {"gaps": gaps, "not_fetched": how["not_fetched"], "read_only_note": _read_only_note(report), "time_limit_cuts": report.get("time_limit_cuts") or [],
                     # What the time limit cut, and how long each step took (DECISIONS 219). None for an older report.
                     "skipped_note": skipped_note(report), "steps": step_table(report),
                     "sessions": sessions, "resumed_note": t("result.resumed_note", sessions=sessions) if sessions > 1 else None,
                     # Nothing to say about a sample when nothing was read: the blocked notice already leads.
                     "sampled_note": t("result.sampled_note") if read else None},
        "gates": [gate_row(g) for g in report["gates"]],
        "technical": {"title": t("result.technical.title"), "note": t("result.technical.note")},
        "areas": _areas(report),
        # Shown apart from the site findings, as the report keeps them, with what they are not.
        "answers": {"note": t("result.answers.note"), "assessed": any(
            c["status"] != "not_assessed" for c in report.get("answer_engine_panel", [])),
            "checks": [check_row(c) for c in report.get("answer_engine_panel", [])]},
        "backlinks": backlinks,
        # Direct access, content coverage and real AI crawlers, as the report itself records them (schema 1.6).
        "status": status_view(report),
        "spend": spend_view(report),
        "method": how,
        "suggested_key_pages": _suggested_key_pages(report),
        "follow_ups": [t(key) for key in FOLLOW_UPS],
    }


def _step_time(value: Any) -> str:
    if value is None:
        return "—"
    value = float(value)
    if value < 60:
        return t("steps.seconds", seconds=f"{value:.1f}")
    minutes, seconds = divmod(int(round(value)), 60)
    return t("steps.minutes", minutes=minutes, seconds=seconds)


def step_table(report: dict[str, Any]) -> dict[str, Any] | None:
    """The step timing table (`crawl.steps`, DECISIONS 219) as shown: a label in the reader's language for each step,
    its time, its requests and how much of the time was waiting. None for a report that has no such rows."""
    rows = (report.get("crawl") or {}).get("steps") or []
    if not rows:
        return None
    known = set(timeplan.STEP_LABELS)
    return {"title": t("steps.title"),
            "columns": [t(f"steps.col.{name}") for name in ("step", "time", "requests", "waiting")],
            "rows": [{"step": row.get("step"), "label": t(f"steps.name.{row.get('step')}") if row.get("step") in known else str(row.get("step")),
                      "time": _step_time(row.get("seconds")), "requests": "—" if row.get("requests") is None else str(row.get("requests")),
                      "waiting": _step_time(row.get("waiting_s"))} for row in rows]}


def skipped_note(report: dict[str, Any]) -> str | None:
    """"Skipped because the time limit was reached: ..." in the reader's language, or None (DECISIONS 219)."""
    keys = [key for key in (report.get("crawl") or {}).get("skipped_for_time") or [] if key in timeplan.SKIP_LABELS]
    return t("steps.skipped", steps=", ".join(t(f"steps.skip.{key}") for key in keys)) if keys else None


def _suggested_key_pages(report: dict[str, Any]) -> list[str]:
    """The most linked pages, from IDX-7's own measurement. Offered, never applied without the person."""
    idx7 = next((c for c in report["checks"] if c["check_id"] == "IDX-7"), None)
    graph = next((o for o in (idx7 or {}).get("observations") or [] if isinstance(o, dict) and "most_linked" in o), None)
    start = report["crawl"].get("start_url")
    return [row["url"] for row in (graph or {}).get("most_linked", []) if row.get("url") and row["url"] != start][:5]


def search(report: dict[str, Any], *, severity: list[str] | None = None, check_id: str = "", area: str = "",
           owner: str = "", query: str = "", offset: int = 0, limit: int = 20) -> dict[str, Any]:
    """Filter and page through the findings. Filtering chooses which to show; it changes none of them."""
    rows = [item(f, bool(single_page_of(report))) for f in findings(report)]
    from maya_audit.final import broken_link_cards
    cards = broken_link_cards(report)  # where each broken internal link is, read from the final report (DECISIONS 280)
    for row in rows:
        if row["id"] in cards:
            row["link_cards"] = cards[row["id"]]
    needle = query.strip().casefold()
    kept = [row for row in rows
            if (not severity or row["severity"] in severity)
            and (not check_id or row["check_id"] == check_id) and (not area or row["area"] == area)
            and (not owner or row["estimates"]["owner"] == owner)
            and (not needle or needle in f"{row['title']} {row['fix']} {row['check_id']} {row['title_shown']} {row['fix_shown']}".casefold())]
    return {"total": len(kept), "offset": offset, "limit": limit, "items": kept[offset:offset + limit],
            "all_findings": len(rows)}


def detail(report: dict[str, Any], finding_id: str) -> dict[str, Any] | None:
    """One finding or review item, whole, as the report holds it, with the row built from it."""
    for check in report["checks"] + report.get("answer_engine_panel", []):
        for kind in ("findings", "review_items"):
            for entry in check.get(kind) or []:
                if entry.get("id") == finding_id:
                    return {"kind": "finding" if kind == "findings" else "review_item",
                            "check": {"check_id": check["check_id"], "title": check["title"], "summary": check["summary"],
                                      "title_shown": wording.label(check["title"], check_id=check["check_id"])[0],
                                      "summary_shown": wording.line(check["summary"], check_id=check["check_id"])[0],
                                      "status": check["status"]},
                            "row": item(entry, bool(single_page_of(report))) if kind == "findings" else review_item(entry), "record": entry}
    return None


def _parts(report: dict[str, Any], check: dict[str, Any]) -> list[dict[str, Any]]:
    """What a check did not assess, with the report's one "not read" figure in its crawl-gap part."""
    parts = (check.get("coverage") or {}).get("not_assessed") or []
    figures = unread_figures(report)
    return restated(parts, *figures) if figures else parts


def check_view(report: dict[str, Any], check_id: str) -> dict[str, Any] | None:
    """One check: its status, summary, findings and what it could not cover."""
    wanted = check_id.upper()
    for check in report["checks"] + report.get("answer_engine_panel", []) + report["gates"]:
        if check["check_id"] == wanted:
            note = catalog.note(wanted)
            return {"check_id": wanted, "title": check["title"], "status": check.get("status") or check.get("state"),
                    "title_shown": wording.label(check["title"], check_id=wanted)[0],
                    "summary": check["summary"], "summary_shown": wording.line(check["summary"], check_id=wanted)[0], "why": note["why"],
                    "findings": [item(f, bool(single_page_of(report))) for f in check.get("findings") or []],
                    "not_assessed": [{**part, "part_shown": _first_capital(wording.label(part.get("part"), check_id=wanted)[0]),
                                      "reason_shown": wording.line(part.get("reason"), check_id=wanted, capital=True)[0]}
                                     for part in _parts(report, check)]}
    return None


def count_line(finding, *, counts=None):
    from maya_audit.report import finding_counts
    counts = finding_counts(finding) if counts is None else counts
    return t('result.counting.units', occurrences=counts['occurrences'] if counts['occurrences'] is not None else t('result.counting.unavailable'),
             pages=counts['affected_pages'] if counts['affected_pages'] is not None else t('result.counting.unavailable'),
             groups=counts['template_groups'], source_target=counts['source_target_groups'] if counts['source_target_groups'] is not None else t('result.counting.unavailable'), per_template=counts['occurrences_per_template'] if counts['occurrences_per_template'] is not None else t('result.counting.unavailable'))
