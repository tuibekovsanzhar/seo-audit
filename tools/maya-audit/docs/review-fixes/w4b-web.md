# W4b — web app, PDF and Turkish client report (review fixes)

Branch `fix/w4b-web`. Items from `maya-audit-duzeltme-plani.md` (H25, H35, H36, H38, H40) and the appendix (sections C
and D). Every behaviour change has a test in `tests/test_w4b_report_length.py`, `tests/test_w4b_client_report.py` or
`tests/test_w4b_web_hardening.py`.

## Measured on the Arjava-like fixture (concise print / PDF, this branch)

Measured with `fakeserver/arjava_scenarios.py` placed in a web app as an ordinary audit (script in the worker's own folder, `measure.py`). PDF pages from headless Chromium. H09/H10 (other workers) are not in this branch, so the
`/cdn-cgi/` link still appears on every page row; the numbers will drop again after the merge.

| | before EN | after EN | before TR | after TR |
|---|---|---|---|---|
| Words (text of the concise HTML) | 7,583 | 3,140 | 6,690 | 2,819 |
| PDF pages | 21 | **10** | 23 | **10** |
| "Complete URLs, fields and request records …" | 45 | 1 | 45 | 1 |
| "Verification: repeat the recorded check …" | 31 | 0 (said once in the section head) | 31 | 0 |
| "A report export or owner approval is not verification" | 14 | 0 (said once, lower case, in the section head) | 14 | 0 |
| "Unverified check (LG-…)" / `LG-` | 19 | 0 | 19 | 0 |
| `recorded_observation` / "Decision status" / "Capped at S4" | 12 / 14 / 4 | 0 / 0 / 0 | — / 14 / — | 0 / 0 / 0 |
| Links into the app (`127.0.0.1:8770`, in the HTML) | 3 | 0 | 3 | 0 |
| Full priority cards / inventory | 14 cards + 31 full rows | 5 cards + 1-cell "↑" rows | same | same |
| Sections | exec, by page, provenance, downloads, priority, inventory, plan, limits | exec, by page (15 rows), priority, notes, inventory, plan, limits, sources, companion files | | |

Turkish client export (`/client-report/export/html`, draft): compact 9,520 → 3,953 words, 31 → 10 full cards (one per
check), raw `{"…"}` dumps 5 → 0, app links 3 → 0. The full export (`full=true`) is unchanged in content (31 cards).

## Items

**H35 / CR-15 / CR-06 / CR-05 / CR-13 / D-23 — concise report length** (`maya_audit_web/concise_report.py:render`)
- The priority section holds the problems from Medium up (S1–S3); the verification sentence and the companion
  sentence are said once at its head (`concise.how_to_read`); a card prints its own verification only when it differs
  from `judgments.VERIFY`. One evidence sample per card; the "Evidence sample (…complete records…)" prefix is short.
- Notes (Info) are one line each under "Notes (no action implied)".
- The inventory is a table: a problem detailed above is one "↑ detailed above" cell; other rows are ID · severity
  (confidence only when not verified) · title · scope · fix + the fixed example. Every finding ID still appears.
- Coverage gaps are grouped by text, one line naming every check (the unread-pages line once); summaries of partial
  checks stay in the full export.
- "Problems by page" is capped at 15 rows in the concise report (CR-13 asked 25 for the Markdown; the concise report
  also lists every problem by ID, and 25 rows of this fixture alone took three pages) with a pointer to the JSON.
- The executive summary flows into the page table (no half-empty page), and "All N are listed …" points at the
  concise report's own inventory (`concise.exec.more`).
- `/print` defaults to compact (`full=False`); the "Printable" button (no parameter) therefore opens the compact page,
  "Full technical" keeps `?full=true` (`app.py:printable`). ~41 existing test calls to `/print` that assert full-only
  content now pass `?full=true` (mechanical edit, listed below).
- Tests: `test_the_concise_report_says_each_shared_sentence_once_and_keeps_every_finding`,
  `test_the_concise_pdf_of_the_arjava_shop_is_at_most_ten_pages`.

**H36 / C61 / D-09 / CR-09 / CR-14 / C60 — language and internal terms**
- `app.py:report_language`: printed page and PDF use `?lang=` (two letters, validated), else `audits.language`, else the
  cookie (rows without a language). This reverses RELEASE-22's "technical export follows the cookie": the PDF goes to a
  client and a Turkish client's audit must print Turkish whoever downloads it. `test_web_language` now asserts both the
  default (audit language) and `?lang=tr`.
- Compact/concise: no "Decision status", no launch-gate numbers (`pdf._chip(compact=True)` → "Unverified" /
  "Doğrulanmadı"), no "Capped at …" notes (`concise_report._notes`), no check id in headings. The full export keeps them.
- CR-14: evidence samples are words (`concise_report._plain`, `_attempt`), never a dict/list repr.
- CR-09: `client_reporting/grouped.py` rewritten: no `str(records)`, `str(counts)`, `str(items)`; the group heading is
  "Ortak uygulama: <Turkish title> (N bulgu)", the internal subtype only in `data-subtype`.
- Tests: `test_the_concise_report_shows_no_internal_terms_no_raw_values_and_no_link_into_the_app`,
  `test_the_printed_language_is_the_audits_unless_asked_for_another`, `test_an_evidence_sample_with_attempts_is_written_as_words`.

**CR-17 / CR-18 — evidence limits** (`summary.py:item`): the "not proof that the destination is gone" fix replaces the
check's own fix only for IDX-6; the limit sentence is said once, in `why` (no longer also in `details`); the concise
card no longer prints `evidence_limits` a third time. Test: `test_an_evidence_limit_is_said_once_and_only_idx6_gets_the_destination_caution`.

**H25 / B01 / CR-20 / CR-21 / CR-22 / CR-35 — client severity and draft score**
- `from_maya_report.apply_rules`: a rule may only lower; `set_severity` stronger than the engine's is ignored and
  `min_severity` is no longer read. R9 (raised title/meta/H1 to S3) is removed — with lower-only rules it had no effect;
  R11 is now "ACC-8 is recorded, not scored" by check id (agrees with the engine); dead `missing_llms_title` removed.
  Matching: there is no stable finding code in the engine (`evidence.judgment.kind` equals the check id), so rules
  match by `check_ids`, and the remaining lowering rules (R10, R13) still narrow by the engine's fixed title pattern —
  only ever lowering, and shown on the card. A real code would be an engine field (not this package).
- `score`: one deduction per check: worst severity × (floor + (1−floor) × |unique URLs| / denominator), capped; an
  incomplete URL list uses the largest card count as a lower bound, cards are never summed. Unverified (launch-gated,
  not live-verified) cards are left out and `coverage.score_reason` says "N doğrulanmamış bulgu puana dahil değil"
  instead of nulling the score (Kural 8 kept). Missing denominators still give no score. IDX-1/IDX-6 double count is
  left to H10 (engine).
- The score is no longer a KPI box ("Önce doğrulanacak bulgu" took its place); it is on the cover as "Taslak puan
  (ağırlıklar kalibre edilmedi): N/100". `reliability.validation` now rejects a score KPI instead of requiring one.
- SKILL.md: only the lines stating the old rules (Kural 9/11, score, render default) were edited.
- Tests: `test_a_report_rule_only_lowers_the_engines_severity`, `test_the_draft_score_counts_a_check_once_…`,
  `test_the_score_is_on_the_cover_as_a_draft_and_not_in_a_kpi_box`.

**CR-04 / CR-10 / CR-11 / CR-12 / H40 — client layout**
- Main section: at most one card per check (`from_maya_report.convert`); the card names the rest ("Aynı kontrolden N
  bulgu daha ekte: …", `render_report.also_line`).
- Compact appendix (`grouped.appendix`): one table row per finding (ID, title, addresses as links, first step); three
  or more cards with the same `group_signature` are one block with the shared procedure and a member table, whatever
  the total; an editor-changed card is shown whole. Full cards stay in `full=true` and the JSON.
- A qualification carried by ≥3 main cards is said once above the cards (compact only).
- CR-11: `advice.procedure` no longer appends `where` to `verify` (it stays in `steps`).
- `render_report` CLI groups by default; `--no-group` prints every card (the web full export is unchanged).
- Decision conflict: `COMPACT-CLIENT-SPEC` / the `compact_evidence` docstring said compact never shortens member
  procedures; CR-12 asks for a table. Narrowest change: shortening only in compact; the full export and JSON are exhaustive.
- Tests: `test_the_main_section_holds_one_card_per_check_and_names_the_rest`,
  `test_two_cards_of_one_repair_stay_rows_and_the_address_is_said_once_per_card`,
  `test_the_skill_command_groups_by_default_and_no_group_prints_every_card`,
  `test_the_client_compact_report_has_one_card_per_check_and_no_raw_values`.

**CR-19 / CR-34 — order and timeline** (`practical.py`): Top 5 = `one_per_check(ordered(merged(problems)))`;
`when()` puts unverified or estimated/inferred findings (not performance diagnostics) in "Verify first"
(`practical.when.verify`), emitted only when non-empty. Test: `test_the_top_problems_name_each_check_once_in_priority_order`.

**H38 / D-07 / D-08 — privacy**: concise companions are file names (`app.py:companion_files`); client compact names its
companion files (no `127.0.0.1` links, `client_reports.compact_evidence`, `origin` kept and unused); ZDR status only in
the full export (`practical.sources.what_client`). Evidence zip: `index.json` is written with `folder` reduced to its
name (`app.py:_without_local_folder`); W4a fixes `evidence_store` itself. Tests:
`test_the_evidence_zip_names_no_folder_of_this_computer` (scans every file in the zip), the concise/client tests above.

**D-10 / C71** `analyses.Registry`: manifest read as UTF-8; report digests cached by `(st_mtime_ns, st_size)`.
Test: `test_a_revised_analysis_manifest_is_read_as_utf8_and_its_report_hashed_once`.

**D-13** `app._server_log`: rotating `logs/maya-audit-web.log` under the web data folder (opened lazily, closed on
shutdown, one handler per path); `runner._loop` logs the traceback (`log.exception`), `_crash` logs request errors; the
page still shows the class name only. Test: `test_a_failed_job_leaves_its_traceback_in_the_server_log_…`.
**D-18** `client_call`: an OSError with a file name/errno is logged, the page gets a fixed message; a client PDF failure
other than the page limit no longer passes Playwright's first line. Test: `test_an_operating_system_error_never_reaches_…`.
**D-19** `security.py` and the SSE `last-event-id`: `isascii() and isdigit()`. Test: `test_a_length_or_event_id_in_other_digits_…`.
**D-20** `Store.delete_audit` in one `BEGIN IMMEDIATE … COMMIT`; `app._remove_tree` replaces `rmtree(ignore_errors=True)`
and the answer carries `files_left` + a sentence (`job.delete_left`). Test: `test_deleting_an_audit_is_one_transaction_…`.
**D-17** `__main__.probe_options`: `SO_EXCLUSIVEADDRUSE` on Windows, `SO_REUSEADDR` elsewhere. Test: `test_the_port_probe_on_windows_…`.
**D-16 / D-11 / D-12** Lite: child killed in `finally` when still running; cancel under the lock; `--block-loopback`
passed; `content_length()` accepts 0–4096 ASCII digits only (400 otherwise). Test: `test_lite_refuses_odd_lengths_…`.
**D-21** `docs/WEB-APP.md`: Windows ACL note (chmod has no effect), log file and analyses folder rows.
**D-24** snapshot allowlist: `WindowsPath`, `PureWindowsPath`. Test: `test_a_snapshot_may_hold_a_windows_path`.
**D-25** `__main__.build`: analyses under `data_home()/analyses` always. Test: `test_revised_analyses_live_under_the_data_home`.
**D-26** `render_report`: `<meta http-equiv="Content-Security-Policy">` in every exported client HTML. Test:
`test_an_exported_page_carries_its_own_content_security_policy`.

## New user-visible sentences
English in `strings.py`, Turkish in `locales/tr.json`: `concise.how_to_read`, `concise.notes`, `concise.notes_note`,
`concise.above`, `concise.unverified`, `concise.by_page_more`, `concise.exec.more`, `practical.when.verify(.note)`,
`practical.source.firecrawl.what_client`, `job.delete_left`; changed values of `concise.companion_note`,
`concise.inventory(_note)`, `concise.action`, `concise.evidence_sample`. Client (Turkish-only) sentences are in
`render_report.py` / `grouped.py` as before.

## Touched outside my files
Existing tests whose assertion stated behaviour these items reverse (minimal edits, intent kept):
- `/print` → `/print?full=true` where a test asserts full-report content (41 calls in 20 files: test_accuracy_round,
  test_keyword_actions, test_market_and_balance, test_normal_report_accuracy, test_no_unfilled_placeholders,
  test_oct18_corrections, test_oct19_accuracy, test_owner_cooperation, test_practical_report, test_preview16_measure,
  test_real_run_fixes, test_report_agreement, test_single_page, test_turkish_report, test_web_app, test_web_blocked,
  test_web_firecrawl, test_web_language, test_web_search_data, test_wording); `&lang=` / `?lang=` where a test chose
  the printed language through the cookie (test_turkish_report, test_no_unfilled_placeholders, test_web_language,
  test_single_page, test_wording, test_market_and_balance, test_keyword_actions, test_accuracy_round,
  test_normal_report_accuracy).
- test_practical_report: Top 5 one per check. test_client_reporting: fixture KPI without the score; CLI test checks the
  score is not a KPI; the unverified-score test now expects 100 + the "not included" note (CR-21).
- test_nine_corrections: addresses in `steps` (CR-11); ten same-procedure cards = 1 main card + 1 group (CR-04/CR-10).
- test_compact_client: companions by file name (D-08). test_client_report_app: 1 main + 11 named (CR-04).
- `docs/WEB-APP.md` (D-21 asks for it) and `docs/WEB-API.md` (the `/print` default, `?lang=`, the delete answer).

## Not done / notes
- `runner._audit` passes `checks=` to `report.run_outcome` when its signature takes it (W4a's change, on main, not in
  this branch), so the stored outcome sentence carries the not-assessed count after the merge.
- Full suite (3.12): 6 failed / 1774 passed. Pre-existing on the base commit a66a97b: `test_fixture_matrix` (matrix
  file regenerated by W4a on main), `test_pre_interface_fixes::test_earlier_frozen_copies…` (1.17 opened with 1.16's
  shape). Environment: `test_no_unfilled_placeholders::…sentence_filler…` (Node stdout read as cp1254). Load-flaky:
  `test_round2_empty_and_googlebot::…empty_page…` and `test_round2_sitemap_and_llms::…cap_above…` pass alone on this
  branch and on base. Mine, fixed after the run: `test_acceptance_reliability::test_group_counts…` (its per-card count
  line is a full-report record now: the test downloads `?full=true`).
- Changed test files on 3.11: 566 passed, 17 xfailed, 5 failed. The node one is as above; 4 in `test_web_blocked`
  (Firecrawl continuation re-asks the site) fail identically on the base commit a66a97b under 3.11: pre-existing.
- `validate_cards` (fix path) recomputes the score value after a live verification but not the sentence
  "N doğrulanmamış bulgu puana dahil değil" in `coverage.score_reason`; that sentence can go stale after a verification
  (validation still passes, both fields carry the same text). Rebuilding the reason there is a small follow-up.
- `references/kart_sozlesmesi.md` (both copies, byte-identical, CRLF kept): the score/KPI/rule lines updated.
- `static/app.js`: deleting an audit shows the `note` when files were left (D-20).
- H09/H10 (engine) are needed for the page table to shrink further; the concise PDF is exactly 10 pages here.
- CR-20's IDX-1/IDX-6 double deduction remains until H10 merges them in the engine.
- Environment: tests must run with a short TEMP on this machine (`.tmp` inside the worktree exceeds MAX_PATH for the
  web app's audit folders: WinError 206). I used `<temp>/w4bt` (unique to this worker).
- `test_no_unfilled_placeholders::test_the_pages_own_sentence_filler_follows_the_same_rule` fails on this machine
  regardless of these changes: it reads Node's stdout with the cp1254 code page (`text=True`).
