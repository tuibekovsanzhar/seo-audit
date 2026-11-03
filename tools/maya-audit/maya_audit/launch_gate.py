"""Which findings rest on a rule that has not been validated on real sites, and what is done with them (DECISIONS 203).

docs/LAUNCH-GATE.md lists every rule, threshold and word list that was written from made-up pages or from one or two
real sites. A finding made by such a rule is labelled "Unverified check" on the web card, in the PDF, in the Markdown
and in the text report, with the launch-gate items it rests on (`Finding.launch_gated`). The label is not a lower
severity: the finding is reported as it was found, and a person is asked to confirm it before acting on it.

`LABELS` is the table: a check, optionally the pattern of the finding titles it applies to (or only the findings that
one shared element causes, `shared`), the launch-gate items, and a mode. "label" fills `launch_gated`; "off" leaves the
finding out of the report and says so in the check's summary ("N finding(s) from an unverified check were left out").
Every row is "label" today (Owner, 2026-10-14): nothing is hidden.

`NOT_LABELLED` holds, for every other OPEN item of docs/LAUNCH-GATE.md, why no finding carries it. `AT_SOURCE` names the
items that the finding itself already carries where it is made (the bot registry's rows, ANS-4's LG-30).
`tests/test_brand_and_launch_gate.py` reads the document and fails when an OPEN item is in none of the three, or when
one of them names an item that is VERIFIED, CLOSED or BY DESIGN.

`apply` is called once the checks are built (`audit.run_audit`, after the single-page rules) and again after a page
reader replaced the content checks (`firecrawl.reader.apply`). It changes nothing twice.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

LABEL, OFF = "label", "off"
MODES = (LABEL, OFF)
# What the Markdown and the text report say (the engine's English; maya_audit_web words it for the reader).
UNVERIFIED_LABEL = "Unverified check"
UNVERIFIED_NOTE = ("This check has not yet been validated on real sites ({items}). Confirm the finding by hand before acting "
                   "on it.")
LEFT_OUT = "{n} finding(s) from an unverified check were left out."
MARK = "left_out_unverified"  # in a check's evidence: the titles of the findings an "off" row left out
ITEM = re.compile(r"^LG-\d+$")


@dataclass(frozen=True)
class Row:
    check_id: str | None  # None: any check (with `shared`)
    pattern: str | None   # a regular expression searched in the finding's English title; None: every finding
    items: tuple[str, ...]
    mode: str = LABEL
    shared: bool = False  # only the findings that one shared element causes (`evidence.shared_element`)

    def matches(self, check_id: str, finding: Any) -> bool:
        if self.check_id is not None and self.check_id != check_id:
            return False
        if self.shared and not isinstance((getattr(finding, "evidence", None) or {}).get("shared_element"), dict):
            return False
        return self.pattern is None or re.search(self.pattern, getattr(finding, "title", "") or "") is not None


# (check, finding titles, launch-gate items). Which finding each LG item covers is an agent's reading of the item
# (DECISIONS 203); the items are in docs/LAUNCH-GATE.md.
LABELS: tuple[Row, ...] = (
    # Language: the homemade language guess and its thresholds; the foreign-language share, headings and placeholders.
    Row("STR-9", r"does not match the content language", ("LG-16", "LG-23")),
    Row("STR-12", r"mostly in another language", ("LG-16", "LG-41")),
    Row("STR-12", r"section headings in another language", ("LG-16", "LG-42", "LG-62")),
    Row("STR-12", r"placeholder or template text", ("LG-41",)),
    # Links and pages: another site at this site's path, soft 404, template markers, orphans, near-duplicates.
    Row("IDX-6", r"point to another site", ("LG-42", "LG-73")),
    Row("IDX-1", r"soft 404", ("LG-42",)),
    # An empty page and a server error message (DECISIONS 204); Googlebot's user agent without ownership (DECISIONS 205).
    Row("IDX-1", r"empty page", ("LG-75",)),
    Row("IDX-1", r"server error message", ("LG-76",)),
    Row("ACC-4", r"Googlebot's user agent", ("LG-77",)),
    # The sitemap check's share when only a sample was checked, the address rules, llms.txt's links (DECISIONS 206, 208).
    Row("IDX-5", r"sitemap URL\(s\) checked .* the sitemap lists", ("LG-78",)),
    Row("IDX-5", r"written wrongly|not percent-encoded", ("LG-79",)),
    Row("ACC-8", r"lead to pages that do not work|does not open with", ("LG-80",)),
    # The share image's icon and size rules, invisible characters, links to other sites (DECISIONS 209, 210, 211).
    Row("STR-10", r"site icon as share image|share image smaller than", ("LG-81",)),
    Row("STR-13", r"invisible characters", ("LG-82",)),
    Row("IDX-6", r"to other sites on .* return 404 or 410", ("LG-83",)),
    Row("STR-13", r"unfilled template markers", ("LG-42",)),
    Row("STR-13", r"template markers in the raw HTML only", ("LG-42", "LG-43")),
    Row("IDX-7", r"listed only in the sitemap", ("LG-44",)),
    Row("IDX-8", r"nearly identical main content", ("LG-21", "LG-41", "LG-69")),
    Row("IDX-4", r"canonicalized to a URL with different content", ("LG-21",)),
    Row("IDX-3", r"redirect to another host", ("LG-43",)),
    Row("IDX-3", r"intermittently redirect to themselves|redirected to themselves once|verification is incomplete", ("LG-72",)),
    # A loop that ends once the site's own cookie is sent back (DECISIONS 217): the three re-checks and the cookie walk.
    Row("IDX-3", r"loop for visitors without cookies|loop in Maya", ("LG-72", "LG-84")),
    # Structure and content: grids, image classing and formats, prices and dates, titles, page kinds, anchors, length.
    Row("STR-8", r"<div> grids", ("LG-23", "LG-64")),
    Row("STR-7", r"likely meaningful image", ("LG-23", "LG-64", "LG-68")),
    Row("STR-7", r"offered in WebP or AVIF", ("LG-44",)),
    Row("STR-4", None, ("LG-15", "LG-63")),
    Row("STR-6", None, ("LG-15", "LG-23", "LG-38")),
    Row("STR-1", r"have a generic title", ("LG-15",)),
    Row("STR-3", r"structured data type expected for their page kind", ("LG-15", "LG-93")),
    Row("STR-3", r"one price and no buy button", ("LG-93",)),
    Row("STR-14", r"generic text", ("LG-44",)),
    Row("STR-15", None, ("LG-44",)),
    Row("STR-11", None, ("LG-38",)),
    # The checklist's quick checks whose thresholds or word lists are agent defaults (DECISIONS 304).
    Row("STR-15", r"list no product or almost none", ("LG-102",)),
    Row("IDX-7", r"do not link to their next page|no breadcrumb or link to a category", ("LG-102",)),
    Row("IDX-5", r"lists no (?:images|videos) although", ("LG-102",)),
    Row("TSEO-1", r"unclear slug", ("LG-102",)),
    Row("STR-3", r"name no author", ("LG-102",)),
    # Every problem one shared element causes, whatever its check: the 60% bar and the section rule.
    Row(None, None, ("LG-61",), shared=True),
    # Rendering: client-render signals, interaction growth, walls, iframes and canvases, main-content share.
    Row("RND-1", None, ("LG-15", "LG-22", "LG-38")),
    Row("RND-3", None, ("LG-15", "LG-22", "LG-38")),
    Row("RND-4", None, ("LG-22", "LG-41")),
    Row("RND-5", None, ("LG-15", "LG-22", "LG-41")),
    Row("RND-7", None, ("LG-22",)),
    # Robots directives: Bing's controls, the nosnippet share, a robots tag outside <head>.
    Row("ACC-3", r"^(?:noarchive|nocache) via", ("LG-10",)),
    Row("ACC-3", r"main content inside data-nosnippet", ("LG-20",)),
    Row("ACC-3", r"robots tag outside <head>", ("LG-60",)),
    # noindex on a utility page (a QR menu, a print page) the menu does not link (DECISIONS 222).
    Row("ACC-3", r"utility page\(s\)", ("LG-89",)),
    # The answer-engine panel: per-run citation events, no answer text, the hand-written domain list, the export.
    Row("ANS-1", None, ("LG-19", "LG-21")),
    Row("ANS-2", None, ("LG-18", "LG-38")),
    Row("ANS-4", None, ("LG-31",)),
    Row("ANS-5", None, ("LG-29", "LG-31")),
)

# Labelled where the finding is made, not by this table.
AT_SOURCE: dict[str, str] = {
    "LG-03": "ACC-4's findings carry the bot registry's launch-gate reasons (maya_audit.registry, `launch_gate`).",
    "LG-05": "ACC-2 and ACC-6 findings carry the bot registry's launch-gate reasons for the six provisional roles.",
    "LG-06": "ACC-2 and ACC-7 findings carry the bot registry's launch-gate reasons for the six rows.",
    "LG-07": "ACC-5 findings carry the bot registry's launch-gate reasons for the rows with no range file.",
    "LG-30": "ANS-4's finding carries LG-30 where it is made (checks/answers.py).",
}

# Every other OPEN item, and why no finding carries it.
NOT_LABELLED: dict[str, str] = {
    "LG-08": "The thresholds are unset, so ACC-5 records these measurements as observations without a severity: there is no finding to label.",
    "LG-09": "Code-enforced: no call is made to a real Bing endpoint, so IDX-10 makes no finding from it.",
    "LG-12": "An unmatched Search Console state already becomes a review item for a person, not a finding (IDX-9).",
    "LG-13": "PRF-3 reports Google's own measurements; a missing field is shown as not assessed, never as a value.",
    "LG-14": "A watch on Google's API; if CrUX is withdrawn PRF-3 returns no record and makes no finding.",
    "LG-24": "PRF-2's 20-attempt minimum decides whether a failure rate is judged at all; below it nothing is reported.",
    "LG-25": "INT-1 is an integrity gate, not a finding; body signatures are already labelled Estimated in its evidence.",
    "LG-26": "PRF-1 and PRF-2 report measured times and failures; the network caveat is about the measurement, not a rule.",
    "LG-34": "INT-4 is an integrity gate about Maya's own pacing, not a finding about the site.",
    "LG-39": "About client documents made from old reports, not about a check's rule.",
    "LG-45": "About how Firecrawl's fields are read; it decides which address a page is recorded under, not a finding.",
    "LG-46": "A pace and time allowance of the page reader, not a finding.",
    "LG-48": "A provider endpoint's status; a refusal is shown as not offered, never as a finding.",
    "LG-50": "How a sitemap read through Firecrawl answers; a refusal is reported in the reader's section.",
    "LG-51": "When the page reader stops; the pages not asked for are counted and named in the coverage.",
    "LG-52": "The time kept for the page reader, not a finding.",
    "LG-54": "How Maya looks names up, not a finding about the site.",
    "LG-55": "About the owner's computer, not a finding about the site.",
    "LG-57": "INT-1's bot-check markers decide whether a page was read, which is an integrity gate, not a finding.",
    "LG-58": "How the local browser looks names up, not a finding.",
    "LG-59": "The Turkish report's cover already says that its wording is a machine draft.",
    "LG-65": "The plan card's market and balance rules decide what is asked of DataForSEO and what it costs, not a finding.",
    "LG-66": "The impact ranks order findings of one severity; they change no finding's content.",
    "LG-70": "Single-page audit is a mode of the audit, not a finding; every output already says that other pages were not checked.",
    "LG-71": "A cost estimate of the DataForSEO plan, not a finding.",
    "LG-74": ("The DataForSEO panels make no findings: the brand's source is said on the panel itself "
              "(`dataforseo.relevance.brand_source`) and on the cover."),
    "LG-85": ("Where \"Problems by page\" lists a problem (the first row or each page's row) is presentation; the finding and "
              "its severity are unchanged."),
    "LG-86": "Adaptive pacing is Maya's own pace, checked by the INT-4 gate, not a finding about the site (as LG-34).",
    "LG-87": ("The brand's source and the brand-search rule decide the cover's name and how the DataForSEO panels are "
              "sorted, which make no findings (as LG-74)."),
    "LG-88": ("The branch rule only takes names out of STR-5's count (listed in `branches_not_counted`); it makes no "
              "finding of its own."),
    "LG-90": ("The calculator rule only leaves grids and empty tables out of STR-8 (listed in `grids_left_out`); the grid "
              "findings STR-8 still makes carry LG-23 and LG-64, and the heading only names the grid."),
    "LG-91": ("The main-text and mixed-language rules only decide when STR-9 does not judge a page; the mismatch it still "
              "reports carries LG-16 and LG-23."),
    "LG-101": ("The Windows file locks keep two processes apart (the worker, the DataForSEO ledger, the per-site crawl lock); "
               "they make no finding."),
}


def items_of(check_id: str, finding: Any, rows: Iterable[Row] = LABELS) -> tuple[list[str], str | None]:
    """(the launch-gate items of every row that applies to the finding, the mode: "off" when any of them is off)."""
    items: list[str] = []
    mode = None
    for row in rows:
        if row.matches(check_id, finding):
            items += [item for item in row.items if item not in items]
            mode = OFF if row.mode == OFF or mode == OFF else LABEL
    return items, mode


def apply(checks: list[Any], rows: Iterable[Row] = LABELS) -> None:
    """Label, or leave out, the findings of unvalidated rules, in place. Does nothing twice."""
    rows = tuple(rows)
    for check in checks:
        kept, left_out = [], []
        for finding in check.findings:
            items, mode = items_of(check.check_id, finding, rows)
            if mode == OFF:
                left_out.append(finding.title)
                continue
            if items:
                finding.launch_gated = [*finding.launch_gated, *(item for item in items if item not in finding.launch_gated)]
            kept.append(finding)
        if not left_out:
            continue
        check.findings = kept
        before = list((check.evidence or {}).get(MARK) or [])
        check.evidence = {**(check.evidence or {}), MARK: before + left_out}
        sentence = LEFT_OUT.format(n=len(before) + len(left_out))
        summary = re.sub(r"\s*\d+ finding\(s\) from an unverified check were left out\.", "", check.summary or "").strip()
        check.summary = f"{summary} {sentence}".strip()
        if not kept and check.status == "findings":
            check.status = "needs_review" if check.review_items else "partial"
            check.coverage = {**(check.coverage or {}), "not_assessed": [
                *((check.coverage or {}).get("not_assessed") or []),
                {"part": "findings of a rule not yet validated on real sites", "reason": "left out by the launch gate (docs/LAUNCH-GATE.md)",
                 "count": len(left_out)}]}


def gate_items(launch_gated: Iterable[str]) -> list[str]:
    """The launch-gate item numbers among a finding's `launch_gated` ("LG-16"); the bot registry's reasons are text."""
    return [item for item in launch_gated or [] if ITEM.match(str(item))]


def note(launch_gated: Iterable[str]) -> str | None:
    """The sentence said under an unverified finding, in the engine's English; None for a finding with no item."""
    shown = list(launch_gated or [])
    if not shown:
        return None
    numbers = gate_items(shown)
    return UNVERIFIED_NOTE.format(items=", ".join(numbers) if numbers else "; ".join(shown))
