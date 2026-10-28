# W4a — engine-side reports (text and Markdown)

Branch `fix/w4a-report`. Tests for every item: `tests/test_w4a_report.py` (24 tests). No Arjava xfail maps to these
items (H37's "first three" depends on H11/H13/H15, owned elsewhere), so no marker was removed.

## Measurements (Arjava fixture, `fakeserver/arjava_scenarios.py`)

Script: the worker's own folder `w4a/measure.py`. "full" is the fixture as configured (crawl exhausted, no reader). "partial" is the
same site with `max_pages=12` plus a made-up main-reader section that stopped on a long Firecrawl 408 message with 34
known pages unread (the real Arjava run).

| | before | after |
|---|---|---|
| full: words / lines | 6,485 / 875 | 6,198 / 609 |
| full: repeated lines (>30 chars, counted twice or more) | 177 | 60 |
| full: line of the first action (table row or card) | 55 (card #1, after the 29-row page table) | 24 (First 10 fixes row 1); card #1 at 54 |
| full: "This check has not yet been validated…" per card | 11 | 0 (said once in the cards' intro) |
| full: "every check ran" while 5 checks were not assessed | 1 | 0 |
| partial: words / lines | 6,918 / 723 | 5,208 / 490 |
| partial: "pages found but not read" rows | 34 | 0 rows, 1 sentence above the table |
| partial: Firecrawl's own 408 paragraph in the Markdown | 1 | 0 |
| short report (`--markdown-brief`) | — | 685 words, 56 lines (full); 677 words (partial) |

The three per-card sentences of item 8 ("Complete URLs, fields and request records…", "Verification: repeat the
recorded check…", "Check the same affected URLs… A report export or owner approval is not verification.") occur **0
times** in the engine Markdown before and after. They are produced by the web layer (`maya_audit_web/strings.py`
`concise.full_evidence`, `concise.verify`; `summary.py` reads `judgment.action.verification`, which is judgments.VERIFY)
and by the client reports: **W4b**. The engine Markdown's own per-card repetition was the launch-gate sentence; that is
now said once.

## Items

1. **H18 / CR-07** — `report.run_outcome(..., checks=None)` (new optional argument; exit codes unchanged).
   - COMPLETED says only what is known: `COMPLETE` "…every discovered page was crawled." without checks;
     `COMPLETE_NOT_RUN` "…; N checks could not run (see Coverage and checks)." when checks are passed and some are
     `not_assessed` (`checks_not_run`: site checks only, ANS excluded, single-page set-asides excluded);
     `COMPLETE_ALL_RAN` (the old sentence) only when none was not assessed.
   - `reader_left_pages_unread`: a *main page reader* (not blocked, DECISIONS 131) whose coverage line names a gap
     (`bool(reader_gaps(section))`: its page cap or request allowance with pages waiting, an early stop, pages with no
     readable document, a key page not read) now makes the audit INCOMPLETE (exit 3) even when Maya's own crawl was
     exhausted. Before, that case fell through to COMPLETED while the coverage line said "N more discovered URL(s)
     remain unchecked". This is DECISIONS 138 as written (the reader's cap and a stop make the audit incomplete); the
     result is decided on the same signal as the coverage sentence, so the two cannot disagree. A cap-only reader gap
     with Maya exhausted is worded with 226's PARTIAL_PAGE_CAP and the reader's cap; other gaps with the generic
     INCOMPLETE sentence (the reader's stop/allowance phrase plus the one "N discovered URL(s) were not read" figure).
     Consequence to note in DECISIONS: a keyed audit whose capped reader leaves pages unread exits 3, not 0.
   - The Markdown and text renderers pass the checks; the web runner and `batch` do not (W4b / owner may add `checks=`
     to `runner.py:416` to get the count in the stored sentence). Tests: `test_a_complete_audit_says_…`,
     `test_a_page_reader_that_stopped_early_…`.
2. **H19** — `report.provider_reason`: a provider error ("Firecrawl … (HTTP 408): <paragraph>") is said by status
   ("the page reader timed out (HTTP 408)"; 401/403 refused, 402 credit, 429 rate limit, 5xx could not load, other
   "returned no document"); Maya's own short stop sentences pass through; other long text keeps its first clause.
   Used by `reader_gaps` (so `audit_status.content_coverage.reasons`, the outcome sentence and the Markdown) and by
   the Firecrawl panel's "Stopped early:" line. The raw text stays in `firecrawl.stopped_because` and
   `firecrawl.errors[].message` (evidence). Not changed: `reader.py` `info["reason"] = "Firecrawl read nothing: <raw>"`
   (shown by the panel's "Not used"/reason line) — owner of `firecrawl/` may wrap it the same way.
3. **CR-05** — `render_markdown`: the "pages found but not read" part (`coverage.CRAWL_GAP_NAMES`) is said once, as a
   quote above the coverage table; rows keep only check-specific gaps. Test: `test_pages_found_but_not_read_is_said_once…`.
4. **CR-06** — `card_groups` splits Info findings out; `note_lines` prints "## Notes (no action implied)", one line each
   (check · title · pages · unverified items). The text report's "Priority order" numbers problems only and lists notes
   apart. JSON unchanged.
5. **CR-02 / CR-24** — `presentation_group_key` (new, wraps `qualified_group_key`): IDX-6 broken targets of one status
   and fix are one card "N internal link targets return 404" with a table of the first 10 targets and their source-page
   counts, "N more targets: JSON report, IDX-6 findings"; ACC-2 findings of one robots.txt line are one card at the worst
   severity with each role's finding listed with its own severity; ACC-6 provider notes are one note line plus a
   provider × token table. Engine findings and headline counts unchanged (DECISIONS 20, 225).
   *Deviation from the brief:* done in a wrapper, not inside `qualified_group_key`, because `maya_audit_web/summary.py`
   stores `qualified_group_key` as `semantic_group` and `practical.merged` would then merge IDX-6 rows under a title
   naming source pages as if they were targets. W4b can adopt `report.presentation_group_key` for the PDF/client.
6. **CR-13** — `problems_by_page_lines(..., limit=BY_PAGE_ROWS=25)`; "N more pages with problems: JSON report,
   `problem_summary.by_page`." The whole-site row is always shown. `limit=None` gives every row (two pinned tests use it).
   The section now comes after the cards and notes.
7. **H37** — Markdown order: header and headline; "## Summary" (5 lines: Result, Scope, Problem 1–3); "## First 10
   fixes" (one row per check: # = card number · problem (+ unverified/estimated mark) · pages affected · severity ·
   effort · owner); "## Impact and effort" 2×2 (quick wins / major projects / fill-ins / later; impact = S1/S2, effort
   S vs M/L from the judgment's or catalogue's estimate; every card placed by number); what the audit covers; cards;
   notes; problems by page; review items; internal links; coverage; appendices. The header no longer repeats the Result
   line (it is the summary's first line). `render_markdown_brief` + CLI `--markdown-brief PATH` (also in the output
   preflight, so an existing file is refused): summary, first 10, grid, "## Not assessed" (one line per not-assessed
   check), pointer to the full report. Ordering reuses `priority_key` (item 10), which now applies the same tiers as
   the web's `action_priority.ordered`; that function was **not** moved (row-shaped, W4b's file). Agent defaults: the
   impact threshold (S1/S2), 25 rows, 5 example pages per card, 10 targets per IDX-6 table.
8. **Boilerplate once** — Markdown: "## What to fix first" opens with one paragraph (full records in the JSON by finding
   ID; how to verify = judgments.VERIFY; what "Unverified check (LG-n)" means); a card keeps only "**Unverified check
   (LG-42)**". Web/client strings: see Measurements — **for W4b** (`concise.full_evidence`, `concise.verify`, the
   per-card `verification`).
9. **CR-16** — "**Why it matters:**" is `recommendation_catalog.why(check_id, source title, shown title)` (new; None when
   only the general fallback note exists, then the line is left out); "**Expected:**" prints `finding.expected`.
10. **CR-23 / H26** — `findings.priority_key`: (severity, `evidence_quality`, importance tier, impact, -pages,
    confidence). `evidence_quality`: 0 verified, 1 inferred/estimated, 2 launch-gated, 3 not assessed (the web's tiers,
    plus not-assessed last). `judgments.qualify_report` passes `launch_gated` to it. The JSON's
    `findings_in_priority_order` changes accordingly.
11. **CR-25 / C62** — `report.source_provenance()` (cached per process; `root` argument for tests):
    `generation.source_commit` = the git HEAD read from files (a `.git` folder, or a worktree's `gitdir:` file with
    `commondir`/`packed-refs`), else RELEASE-SNAPSHOT.json's `base_commit`, else "not recorded"; `generation.source_provenance`
    holds `source_kind`, `release`, `base_commit`. Never raises. `concise_report.py:66` already reads `source_commit`.
12. **D-07** — `evidence_store.save_evidence` writes `index.json` `folder` as the folder's name;
    `evidence_store.shown_folder` gives the CLI's `evidence_saved.folder` relative to the JSON report (the default
    "<json>-evidence") or the name. The console line still prints the local path (it is not a file). Test updated:
    `test_evidence_store.py::test_key_pages_are_saved_by_default…` now expects "audit-evidence".
13. **CR-29** — `repeated_key` removed (dead since `qualified_group_key` replaced it; the comment above `MERGED` says
    so). The web imported it without using it: one line removed from `maya_audit_web/practical.py`'s import. The lead
    should note in DECISIONS that 225's "titles that differ only in their counts are one row" is narrowed by the
    accuracy round to semantic evidence identity.

## Schema
No new frozen key. `generation` inner keys are not frozen; one line added under "## 1.17" in docs/REPORT-SCHEMA.md
(source_commit / source_provenance; evidence folder without local path). `python -m maya_audit.schema` not needed.

## Pinned tests updated (wording/order changed on purpose)
- `test_brand_and_launch_gate.py` — the Markdown card shows "**Unverified check (LG-16, LG-23)**"; the sentence is said once.
- `test_report_agreement.py` — order is now headline < Summary < What this audit covers < What to fix first < Problems by page.
- `test_page_wording.py`, `test_preview16_grouping.py` — call `problems_by_page_lines(..., None)` to see all 45/33 rows.
- `test_web_app.py::test_pdf_markdown_and_json_agree…` — an IDX-6 finding's own title is not in the Markdown when its
  targets are grouped; the grouped heading is accepted.
- `test_evidence_store.py` — `evidence_saved.folder` is "audit-evidence".

## Touched outside my files
- `maya_audit_web/wording.py`: frames `outcome.complete.crawled`, `outcome.complete.not_run`, `gap.reader_http`.
- `maya_audit_web/locales/findings/tr.json`: their Turkish, and six "the page reader …" terms.
- `maya_audit_web/practical.py`: `repeated_key` dropped from one import line.
- `maya_audit/firecrawl/panel.py`: "Stopped early:" uses `provider_reason` (one line).
- Tests listed above.

## Left for others / not done
- W4b: per-card "Complete URLs…", "Verification: repeat…", and judgment `verification` in concise/client outputs
  (say once per section); `action_priority.ordered` can stay — the engine's `priority_key` now agrees with it;
  `presentation_group_key` is available for the PDF/client grouping; `runner.py:416` may pass `checks=` to
  `run_outcome`.
- README.md line for exit code 0 still says "every check ran" (not my file).
- The coverage table still repeats DECISIONS 189's "No problem found on the N pages read (M not read)" on each clean
  partial check (owner decision; not changed).

## Later additions
- `test_judgment_consistency.py`: an IDX-6 finding grouped into "N internal link targets return …" counts as named.
  Notes that are one group name every finding's title on their line.
- `docs/FIXTURE-MATRIX.md` regenerated (`scripts/fixture_matrix.py`, then CRLF -> LF): the new tests count for ACC-1/2/6
  etc. Expect a merge conflict here with other workers; regenerate after merging.
- Full suite (3.12, TEMP shortened to `%TEMP%/w4at` because `<worktree>/.tmp` hit WinError 206 path-too-long in the web
  runner): 5 failed, 1772 passed. Two failed on base a66a97b too (`test_no_unfilled_placeholders::…filler_follows…`,
  encoding; `test_pre_interface_fixes::…frozen_copies…`, 1.17 has the 1.16 shape until a key is added); one is the
  shared venv312 launcher having lost its `cpython-3.12-…` link mid-run, so the suite ran on the base interpreter with
  PYTHONPATH and a subprocess test could not import httpx (`test_dataforseo_backlinks::…6b…`); two were mine and are fixed.
