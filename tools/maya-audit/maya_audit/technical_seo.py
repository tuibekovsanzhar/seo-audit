"""Traditional on-page SEO quality checks layered onto Maya's existing audit.

Status, link, image-alt, and response-time checks already live in IDX, STR, and
PRF. This module adds only the editorial quality gaps those checks do not judge:
title and description length bands, plus heading-level jumps. The bands are
explicit heuristics, not Google limits or ranking guarantees.
"""

from __future__ import annotations

import unicodedata
from collections import defaultdict

from . import shared_elements
from .findings import CheckResult, Finding, Rationale, Severity, scope_for
from .models import Confidence, CrawlResult

TITLE_MIN_CHARS = 10
TITLE_MAX_CHARS = 60
DESCRIPTION_MIN_CHARS = 70
DESCRIPTION_MAX_CHARS = 160
EVIDENCE_LIMIT = 40


def _stop_value(result: CrawlResult) -> str:
    return getattr(result.stop_reason, "value", result.stop_reason)


def run_traditional_seo_quality_check(
    result: CrawlResult,
    pages: list,
    key_urls: set[str],
    rendering_gap: set[str],
) -> CheckResult:
    """Check measured metadata length and heading order without duplicating STR/IDX/PRF.

    Only indexable readable HTML pages are supplied by the caller. Pages with a
    known raw-vs-rendered content gap or truncated response are withheld and
    recorded as not assessed.
    """
    title = "Traditional metadata and heading quality"
    if not pages:
        return CheckResult("TSEO-1", title, "not_assessed", "No indexable readable HTML pages.")

    excluded: list[dict[str, str]] = []
    checked = []
    for page in pages:
        if page.url in rendering_gap:
            excluded.append({"url": page.url, "reason": "raw HTML has a detected rendering gap (RND-1)"})
        elif page.body_truncated:
            excluded.append({"url": page.url, "reason": "response body was truncated before analysis completed"})
        else:
            checked.append(page)

    if not checked:
        return CheckResult(
            "TSEO-1", title, "not_assessed",
            "Not assessed: every candidate page had incomplete raw HTML evidence.",
            evidence={"pages_checked": 0, "excluded_pages": excluded[:EVIDENCE_LIMIT],
                      "excluded_pages_count": len(excluded)},
        )

    short_titles: list[dict] = []
    long_titles: list[dict] = []
    short_descriptions: list[dict] = []
    long_descriptions: list[dict] = []
    heading_jumps: list[dict] = []
    heading_jump_count = 0
    jumps_by_page: dict[str, tuple[int, list[dict]]] = {}
    measurements: list[dict] = []

    for page in checked:
        analysis = page.analysis or {}
        # Counted after NFC (B19): "é" written as e and a combining accent is one character, as a reader sees it.
        title_text = unicodedata.normalize("NFC", (analysis.get("title") or "").strip())
        descriptions = [
            (meta.get("content") or "").strip()
            for meta in analysis.get("meta", [])
            if meta.get("name", "").casefold() == "description" and (meta.get("content") or "").strip()
        ]
        description = unicodedata.normalize("NFC", descriptions[0]) if descriptions else ""
        row = {"url": page.url, "title_chars": len(title_text) if title_text else None,
               "meta_description_chars": len(description) if description else None}
        measurements.append(row)

        if title_text and len(title_text) < TITLE_MIN_CHARS:
            short_titles.append({"url": page.url, "title": title_text, "characters": len(title_text)})
        elif title_text and len(title_text) > TITLE_MAX_CHARS:
            long_titles.append({"url": page.url, "title": title_text, "characters": len(title_text)})

        if description and len(description) < DESCRIPTION_MIN_CHARS:
            short_descriptions.append({"url": page.url, "characters": len(description),
                                       "description": description})
        elif description and len(description) > DESCRIPTION_MAX_CHARS:
            long_descriptions.append({"url": page.url, "characters": len(description),
                                      "description": description})

        heading_counts = analysis.get("heading_counts") or {}
        headings = heading_counts.get("skipped_level_jumps")
        if headings is None:  # Older serialized/fixture analyses may not include streaming counts.
            levels = [heading.get("level") for heading in analysis.get("headings", [])]
            headings = [{"from": before, "to": after} for before, after in zip(levels, levels[1:])
                        if after > before + 1]
            if levels and levels[0] > 2:  # a first heading of H3 or lower is a skip too (B19)
                headings.insert(0, {"from": 1, "to": levels[0], "first_heading": True})
            jump_count = len(headings)
        else:
            jump_count = heading_counts.get("skipped_level_jumps_total", len(headings))
        if jump_count:
            jumps_by_page[page.url] = (jump_count, list(headings))

    # A jump onto a heading that most pages carry (a footer's column title) is one element, not a fault of each
    # page: it is counted apart from the jumps inside a page's own content and reported once for the whole site,
    # by the heading's text (maya_audit.shared_elements). A heading is known by its level and its text.
    def heading_key(jump: dict) -> tuple | None:
        return (jump.get("to"), jump["text"]) if jump.get("text") else None

    shared_headings = shared_elements.split(
        {url: {heading_key(jump) for jump in listed if heading_key(jump)} for url, (_, listed) in jumps_by_page.items()}, [page.url for page in checked])
    landed: dict[tuple, list[tuple[str, dict]]] = defaultdict(list)
    for url, (jump_count, listed) in jumps_by_page.items():
        own = [jump for jump in listed if heading_key(jump) not in shared_headings]
        for jump in listed:
            if heading_key(jump) in shared_headings:
                landed[heading_key(jump)].append((url, jump))
        left = jump_count - (len(listed) - len(own))
        if left > 0:
            heading_jump_count += left
            heading_jumps.append({"url": url, "jump_count": left, "examples": own[:10]})

    findings: list[Finding] = []
    # Each finding has its own list of notes: a note added to one (the source of its pages) is not added to the others.
    band_notes = [
        "Heuristic only: these character bands are editorial guidance, not Google limits or a ranking guarantee.",
        "Measured from Maya's extracted page title and the first non-empty meta description in raw HTML.",
    ]
    heading_notes = ["Heading order is guidance for readers and screen readers, not a ranking rule."]

    def add_finding(entries: list[dict], label: str, expected: str, fix: str,
                    item_count: int | None = None, note: list[str] = band_notes) -> Finding:
        urls = sorted({entry["url"] for entry in entries})
        count = len(entries) if item_count is None else item_count
        return keep(bool(entries), Finding(
            check_id="TSEO-1",
            title=f"{count} {label}",
            severity=Severity.INFO if "guidance band" in label else Severity.S4,
            confidence=Confidence.VERIFIED,
            rationale=Rationale.HYPOTHESIS.value,
            engines=["Search results and pages citing this site"],
            scope=scope_for(urls),
            evidence={"items": entries[:EVIDENCE_LIMIT], "item_count": count,
                      "examples_truncated": len(entries) > EVIDENCE_LIMIT},
            expected=expected,
            how_to_fix=fix,
            notes=list(note),
            importance_tier=0 if any(url in key_urls for url in urls) else 2,
        ))

    def keep(wanted: bool, finding: Finding) -> Finding:
        if wanted:
            findings.append(finding)
        return finding

    add_finding(
        short_titles, "page title(s) below the 10-character guidance band",
        f"A page-specific title around {TITLE_MIN_CHARS}–{TITLE_MAX_CHARS} characters, where that fits the page.",
        "Expand the title with the page topic so readers can distinguish it in search results and shared links.",
    )
    add_finding(
        long_titles, "page title(s) above the 60-character guidance band",
        f"A concise, page-specific title around {TITLE_MIN_CHARS}–{TITLE_MAX_CHARS} characters, where that fits.",
        "Move the page topic toward the start and remove words that do not help identify this page.",
    )
    add_finding(
        short_descriptions, "meta description(s) below the 70-character guidance band",
        f"A useful page summary around {DESCRIPTION_MIN_CHARS}–{DESCRIPTION_MAX_CHARS} characters, where practical.",
        "Add a specific summary of the page and the useful next step it offers.",
    )
    add_finding(
        long_descriptions, "meta description(s) above the 160-character guidance band",
        f"A concise page summary around {DESCRIPTION_MIN_CHARS}–{DESCRIPTION_MAX_CHARS} characters, where practical.",
        "Keep the central page summary and remove repeated or secondary detail.",
    )
    in_content = add_finding(
        heading_jumps, "heading level jump(s) in the page structure",
        "Headings progress through levels without skipping an intermediate level.",
        "Use the next heading level in sequence (for example, follow an H2 with an H3 before an H4).",
        item_count=heading_jump_count, note=heading_notes,
    )
    for (level, text), found in sorted(landed.items(), key=lambda item: (-len({url for url, _ in item[1]}), str(item[0]))):
        urls = sorted({url for url, _ in found})
        before = sorted({jump.get("from") for _, jump in found if jump.get("from") is not None})
        # The heading before it is each page's last content heading, so the level it comes after may differ by page.
        findings.append(shared_elements.finding(
            in_content, "heading_jump" if len(before) == 1 else "heading_jump_varied",
            {"type": "heading", "text": text, "level": level, "where": shared_elements.region(jump.get("where") for _, jump in found)},
            urls, {"comes_after_levels": before, "jumps": len(found),
                   "items": [{"url": url, "from": jump.get("from"), "to": level} for url, jump in found[:EVIDENCE_LIMIT]]},
            importance_tier=0 if any(url in key_urls for url in urls) else 2, section=shared_headings.section((level, text), urls),
            text=text, to=level, before=before[0] if before else level))

    # H30/H32/H33: what the page's markup says about loading and measurement (maya_audit.page_markup).
    from .checks.page_markup import page_markup_findings

    markup_observations: list[dict] = []
    findings += page_markup_findings(checked, key_urls, markup_observations)

    unvisited = list(getattr(result, "not_fetched_urls", []) or [])
    stop_reason = _stop_value(result)
    incomplete_crawl = stop_reason != "exhausted"
    evidence = {
        "pages_checked": len(checked),
        "excluded_pages": excluded[:EVIDENCE_LIMIT],
        "excluded_pages_count": len(excluded),
        "crawl_stop_reason": stop_reason,
        "crawl_incomplete": incomplete_crawl,
        "not_fetched_url_count": len(unvisited) if incomplete_crawl else 0,
        "not_fetched_urls": unvisited[:EVIDENCE_LIMIT] if incomplete_crawl else [],
        "measurements": measurements[:EVIDENCE_LIMIT],
        "measurements_count": len(measurements),
        "thresholds_characters": {"title": [TITLE_MIN_CHARS, TITLE_MAX_CHARS],
                                  "meta_description": [DESCRIPTION_MIN_CHARS, DESCRIPTION_MAX_CHARS]},
    }
    summary = (f"{len(findings)} finding(s) across {len(checked)} checked page(s)." if findings else
               f"No title/description length or heading-order heuristic was triggered on {len(checked)} checked page(s).")
    return CheckResult("TSEO-1", title, "findings" if findings else "pass", summary, findings,
                       evidence=evidence,
                       observations=[{"metric": "pages with measured title and meta-description lengths",
                                      "value": sum(bool(row["title_chars"] and row["meta_description_chars"])
                                                   for row in measurements),
                                      "pages_checked": len(checked)}, *markup_observations])
