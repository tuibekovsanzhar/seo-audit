# Implementation status

Tracks `docs/Maya-Audit-Claude-Code-Uygulama-Rehberi-2026-10-28.md` (the guide). Status values: NOT_STARTED,
IN_PROGRESS, VERIFIED, BLOCKED_ON_INPUT. A command that was not run is written NOT RUN, never implied as passed.

Source: `~/Projects/maya-audit`, Git repo created from `maya-audit-0.2.8-w13-2026-10-28.zip`, baseline commit `a40500b`.
Branch `master`, no remote, nothing pushed. Package 0.2.8. Interpreter `.venv/bin/python` = CPython 3.13.1 (macOS arm64).
`HANDOVER.md` not available. Call map and code-level findings: `docs/architecture/baseline.md`.

| Stage | Status | Note |
|---|---|---|
| 00 Baseline | IN_PROGRESS | Baseline, call map, test state recorded. Step 7 (`tests/fixtures/quality/`) not started |
| 01 Packaging | IN_PROGRESS | Packaging defect fixed and verified from an installed wheel; guide steps 5 (report/static smoke) and 6 (explicit missing-catalogue error) open |
| 02 Result contract | IN_PROGRESS | M1 minimum: `maya_audit/final.py` (`FinalAuditResult`, `seal`, `from_report`) |
| 03 Rule identity | NOT_STARTED | |
| 04 Shared finalization | IN_PROGRESS | `final.settle`/`verify` in `run_audit` and after a page reader; batch not moved |
| 05 Shared service (CLI/batch/web) | IN_PROGRESS | CLI and web use `final.seal`; the `maya-audit-pro` skill reads through `final.from_report`; batch not moved |
| 06 Output generations | NOT_STARTED | |
| 07 Source/page type/scope/render | IN_PROGRESS | H1: raw vs rendered per page (`h1_sources`); a page cut off at the size limit is not assessed for its <h1> or its section headings |
| 08 Rule contract + catalogue | IN_PROGRESS | Missing catalogue is an error; actions for idx6.broken and every H1 rule |
| 09 One publication gate | IN_PROGRESS | Every web report download and the final client export gated; CLI writes and warns; batch not gated |
| 10 URL-level report | IN_PROGRESS | Broken-link cards (page, link text, target, status, replacement unknown) in Markdown, web PDFs and the `maya-audit-pro` client PDF |
| 11 Team status vs engine verification | NOT_STARTED | |
| 12 SEO accuracy measurement | BLOCKED_ON_INPUT | Needs human SEO labels; nothing labelled yet |
| 13 Integration and release | IN_PROGRESS | w14d (tag `team-preview-w14d`): archive verification pending. w14c VERIFIED; w14b superseded; w14 FAIL |

## Stage 00 — baseline

**Commands and results (2026-10-29, macOS, Python 3.13.1 unless noted):**

| Command | Result |
|---|---|
| `python3.11 -m compileall -q maya_audit maya_audit_web maya_audit_web_lite.py tests tools` | OK (CPython 3.11.15, lowest in `requires-python`) |
| `.venv/bin/python -m pytest -q -rfE --durations=15` (full suite, once) | `2 failed, 2572 passed, 1 skipped, 1 warning in 726.10s (0:12:06)` |
| `.venv/bin/python -m pytest -q tests/test_w13_release_gate.py` | `26 passed in 0.33s` |
| `ruff check --select E9,F821,F841 ...` | NOT RUN: ruff is not installed in `.venv` (no install without authorization) |
| CI matrix (Linux/Windows, 3.11/3.12) | NOT RUN: no push |

**Failures, classified:**

| Test | Kind | Cause |
|---|---|---|
| `test_rnd_scenarios.py::test_websocket_page_finishes_within_deadline_without_opening_a_socket` | Environment (test harness) | Reproducible, not flaky. The test runs the audit in a child process via `tests/offline_process.environment()`, which points `HOME` and `XDG_CACHE_HOME` at a temp folder. Playwright then looks for Chromium under that temp HOME, finds none, and the render falls back to `raw_html_only` ("Executable doesn't exist at .../maya-offline-child-*/home/Library/Caches/ms-playwright/..."), so `render.pages` is empty. The in-process `_browser_available()` check sees the real cache, so the test does not skip. Windows already gets a `PLAYWRIGHT_BROWSERS_PATH` fallback; macOS/Linux do not. Proven: with `PLAYWRIGHT_BROWSERS_PATH=~/Library/Caches/ms-playwright` both tests pass (`2 passed in 6.22s`). |
| `test_rnd_scenarios.py::test_websocket_server_that_accepts_and_never_replies_does_not_hold_up_the_render` | Environment (test harness) | Same cause and same proof as above. |

**Known issues that did not fail here:**

| Test | Kind | Detail |
|---|---|---|
| `test_batch.py::test_a_batch_reads_pages_through_firecrawl_when_a_key_is_set_and_no_firecrawl_switches_it_off` (lines 316, 323) | Real test defect, hidden on macOS | Batch writes `<slug>.json` with the CSV name's case (`Alpha.json`; `batch.py:62`, and the same file's line 118 expects `Alpha.json`). Lines 316/323 read `alpha.json`. This Mac's filesystem is case-insensitive, so it passes here; on a case-sensitive filesystem (Linux CI) it fails. The product behaviour is consistent; the test path is wrong. |
| Timing-sensitive tests | Possibly flaky | Reported by the owner as one flaky timing test. It did not fail in this run; not identified by name. |

**Skipped (1):** `test_evidence_integrity.py:184` — "live-run examples are not committed to git". Expected.
**Warning (1):** Starlette deprecation (`httpx` with `starlette.testclient`). Dependency notice, not a test result.

**Code-level findings confirmed in this source** (details in `docs/architecture/baseline.md`):

1. The wheel leaves out `maya_audit/rule_ids.json` and `maya_audit/rule_actions.json` (only these two). → stage 01.
2. After `firecrawl.reader.apply` replaces checks, `broken_link_sources`, `annotate_page_types` and `verification.run`
   are not re-run. → stage 04.
3. `build_report` and the Markdown each run `qualify_checks` again (title/scope/confidence may change, then severity and
   rule ids are re-assigned). → stages 02/04.
4. The web PDF/Markdown/JSON download, print view and client-report export do not use the `release_gate` decision;
   only the `maya-audit-pro` skill does. → stage 09.
5. `facts._catalogue()` returns `{}` when `rule_actions.json` is missing: a missing catalogue looks like "no action".
6. Internal 4xx links are `idx1.4xx.referenced(.linked)` (have actions); `idx6.broken` and the H1 rules `str2.hidden_h1`,
   `str2.many_h1`, `str2.home_no_h1` have no entry in `rule_actions.json`. → M1.

**Isolation:** `tests/conftest.py` blocks non-loopback sockets and public DNS in-process. Child processes use
`tests/offline_process.environment()` (temp HOME/MAYA_AUDIT_HOME/XDG dirs, absent `.env`, Firecrawl off, a
`sitecustomize` guard). The real `.env` was not read. The browser-path gap above is the one isolation defect found.

**Remaining for stage 00:** step 7, the small in-memory quality fixture set (`tests/fixtures/quality/`: broken internal
link, working counterpart, raw/render difference, partial crawl, healthy pagination), with expected results written
independently of current output. Planned as the first M1 task. Optional: fix the browser-path pass-through in
`tests/offline_process.py` and the `alpha.json` test path (each a one-line test change; not done, out of scope).

## Stage 01 — packaging and installed-package smoke

**Changed:** `pyproject.toml` (`maya_audit = ["rule_ids.json", "rule_actions.json"]` in package-data; existing web and
client entries kept), `tools/check_installed_package.py` (new), `tests/test_distribution_contract.py` (new),
`.github/workflows/ci.yml` (new step "Installed package smoke", after the source tests).

**Commands and results (2026-10-29):**

| Command | Result |
|---|---|
| Baseline wheel (built from `git archive HEAD` in a temp dir), contents compared with `git ls-files` | Missing exactly `maya_audit/rule_ids.json`, `maya_audit/rule_actions.json` |
| `tools/check_installed_package.py --wheel <baseline wheel>` | `FAIL: missing from the wheel: maya_audit/rule_ids.json, maya_audit/rule_actions.json` |
| `MAYA_AUDIT_WHEEL=<baseline wheel> pytest -q tests/test_distribution_contract.py` | `4 failed` (installed run: `FileNotFoundError: ... site-packages/maya_audit/rule_ids.json`) |
| `.venv/bin/python tools/check_installed_package.py` (after the fix; real wheel, pip build isolation, new temp venv, `--no-deps --no-index` install, run with `-I` from a temp cwd) | `PASS: installed package resolves a rule and an action outside the checkout`; module loaded from `.../maya-wheel-*/venv/lib/python3.13/site-packages/maya_audit/`; rule `idx6.broken`; action `str2.no_h1` = "Add one main heading to pages that have none" |
| `MAYA_AUDIT_WHEEL=<fixed wheel> pytest -q tests/test_distribution_contract.py` | `4 passed in 2.48s` |
| `pytest -q tests/test_distribution_contract.py` (no wheel given) | `2 passed, 2 skipped` — `.venv` has no setuptools, so the wheel tests cannot build offline and skip with that reason |
| `pytest -q` release gate, rule actions, rule ids, verification target, report agreement, distribution contract | `50 passed, 2 skipped, 1 warning in 4.94s` |
| `python3.11 -m compileall` on the two new files | OK |
| Full suite after stage 01 | NOT RUN (stage changes packaging metadata, one test file, one tool only) |
| CI step | NOT RUN (no push) |

**Tests:** `test_rule_resources_declared_as_package_data`, `test_package_data_covers_every_resource_file` (any data
file in a package directory that no package-data pattern covers fails; always runs, offline),
`test_wheel_contains_required_rule_resources`, `test_installed_package_resolves_rule_and_action_outside_checkout`.

**Network:** building with isolation downloads the setuptools backend from PyPI. No website or paid provider is
contacted. The tests themselves build only with `--no-build-isolation --no-index`.

**Open (guide stage 01):** step 5 rest — in-memory report and web static file from the installed package; step 6 —
`facts._catalogue()` still returns `{}` when the catalogue is missing or broken (`rules._table` raises). Making that an
explicit error is a behaviour decision for a separate small change with its own test
(`test_missing_required_catalogue_is_explicit_error`). To make the wheel tests run locally without the tool, setuptools
would have to be added to `.venv` (not done: no dependency installs without authorization).

## M1 slice A — broken internal links end to end (2026-10-29)

**Changed:** new `maya_audit/final.py`; `audit.py` (finalization through `final`, outcome keeps transport/hooks, not
pickled), `firecrawl/reader.py` (`final.after_provider` when checks were replaced), `verification.py` (`only_missing`,
`cap`), `report.py` (`report_and_affected`), `cli.py` and `maya_audit_web/runner.py` (`final.seal`, cards in Markdown,
companion list from the sealed result), `coverage.py` (IDX-1 "addresses found but never requested"),
`maya_audit_web/app.py` (gate on downloads, client export, print banner, draft links), `pdf.py`, `concise_report.py`,
`practical.py`, `summary.py` (cards), strings EN/TR. DECISIONS 280. Tests: `tests/test_m1_broken_links.py` (hand-written
broken-via-redirect, working counterpart, partial crawl, adapter, provider finalization),
`tests/test_m1_publication.py` (web downloads vs the gate, cards in rows and HTML).

**Results:** `pytest -q tests/test_m1_broken_links.py` → `10 passed`; `tests/test_m1_publication.py` → `10 passed`;
w13 + client report app + report agreement + Firecrawl + distribution → `147 passed, 2 skipped`. The provider test was
checked to fail with the old behaviour (`TypeError: 'NoneType' object is not subscriptable` on the missing re-test
record). A full-suite run during the slice is not counted: files changed while it ran. Final full run: see slice B.

**Found and fixed in the slice:** IDX-1 called a page-capped crawl "pass" though addresses were never requested
(`coverage.probe_scope_recorded` exempts IDX-1 from the crawl gap). Now partial with its own part (DECISIONS 280 (5)).

**Not done (slice A):** batch and the skills still build reports without `final.seal`; the CLI writes a BLOCKED report
(prints the decision) instead of refusing; `render_markdown` re-qualifies on its own; the client-report editorial cards
(`client_reporting`) do not show the broken-link card yet; the evidence zip is not gated (by choice).

## M1 slice B — the main heading (2026-10-29)

**Changed:** `maya_audit/checks/structure.py` (STR-2: per-page `h1_sources` raw vs rendered; new `str2.js_only_h1`;
homepage empty <h1> built as its own finding under its existing rule `judgment.heading.home`), `maya_audit_web/wording.py`
+ regenerated `maya_audit/rule_ids.json` (one new frame), `maya_audit/rule_actions.json` (actions for `idx6.broken`,
`str2.home_no_h1`, `judgment.heading.home`, `str2.hidden_h1`, `str2.many_h1`, `str2.js_only_h1`),
`recommendation_catalog.py` + TR wording (catalog, findings), `docs/FIXTURE-MATRIX.md` (regenerated). DECISIONS 281.
Tests: `tests/test_m1_h1.py` (hand-written pages for each state; homepage missing/empty/hidden; counter-example; raw vs
rendered with the local browser).

**Correction to stage 00 note 6:** the homepage-empty title already had a rule (`judgment.heading.home`); it had no action.

**Final results (whole tree after slices A and B, macOS, Python 3.13.1):**

| Command | Result |
|---|---|
| `.venv/bin/python -m pytest -q -rfEs` (full suite) | `2610 passed, 3 skipped, 1 warning in 701.07s (0:11:41)` |
| `.venv/bin/python -m pytest -q .agents/skills/maya-audit-pro/tests/*.py` | `27 passed` |
| `tests/test_m1_h1.py` | `8 passed` (2 of them render with the local Chromium) |
| `.venv/bin/python tools/check_installed_package.py` | `PASS` |
| `python3.11 -m compileall` | OK |
| ruff, Linux/Windows CI | NOT RUN |

Skipped: the two wheel tests (no setuptools in `.venv`), the live-run examples test. The two WebSocket render tests and
the batch file-name test now pass (fixes in `feebcf3`).

**Still open after M1:** batch and the skills on `final.seal`; CLI refusing a blocked report; `render_markdown`'s own
qualification pass; broken-link card in the editorial client report (`client_reporting`) and the skill's cards (they
already show target and sources); web UI shows a 409 for direct links only (the results card offers draft links);
step 7 quality fixtures beyond these two rules; SEO accuracy labels (stage 12, needs people).

## Judgment review of M1 and its fixes (2026-10-29)

**Review** (`maya-judgment-validator`, read-only, 12 offline reproducer cases; records kept outside the repo):
IDX-1 "partial" when the crawl did not fetch found addresses — **qualify** (status right, wording "never requested"
false when the sitemap check requested them). `str2.js_only_h1` — **remove** (repeats RND-2 for the same page and
heading). Also found: `h1_sources` wrote `null` ("not rendered") for a rendered page without an <h1>; and a pre-existing
false "The homepage has no <h1>" (verified) when the HTML was cut off at the fetch-size limit before the <h1>.

**Fixed** (DECISIONS 281 corrected, 282): IDX-1 part "addresses found but not fetched by the crawl"; `str2.js_only_h1`
removed (frame, rule id, action, note, Turkish); `rendered_h1` is `[]` when rendered with none; a page cut off before any
<h1> goes to `evidence.h1_cut_off` and coverage part "pages whose HTML was cut off before an <h1>" (STR-2 partial)
instead of "no <h1>". Files: `maya_audit/coverage.py`, `maya_audit/checks/structure.py`, `maya_audit_web/wording.py`,
`maya_audit/rule_ids.json` (regenerated), `maya_audit/rule_actions.json`, `maya_audit/recommendation_catalog.py`, TR
locales, `docs/FIXTURE-MATRIX.md`, `tests/test_m1_h1.py`, `tests/test_m1_broken_links.py`.

**Tests added:** `test_unread_addresses_part_does_not_claim_they_were_never_requested`, `test_an_h1_only_a_script_adds_is_left_to_rnd2`,
`test_a_rendered_page_without_an_h1_records_none_not_unknown`, `test_an_h1_after_the_size_limit_is_not_assessed_not_missing`,
`test_an_h1_before_the_size_limit_is_still_seen`, `test_a_short_page_without_an_h1_is_still_reported`.

**Verification** (source: `b950494` + the files above, macOS, Python 3.13.1):

| Gate | Result |
|---|---|
| Full suite, isolated (temp HOME/MAYA_AUDIT_HOME/TMPDIR/cache, no .env, no provider variables, `-p no:cacheprovider`) | `2615 passed, 4 skipped, 1 warning in 722.43s (0:12:02)` |
| Related files (M1, wording, Turkish, rule ids/actions, web app, RND, STR) | `282 passed` |
| CLI once against a loopback fake site, `--json` | exit 0; JSON parses (schema 1.20); STR-2 lists the cut-off homepage as not assessed |
| `python3.11 -m compileall` | OK |
| Skill tests `.agents/skills/maya-audit-pro/tests` | `27 passed` |
| ruff `E9,F821,F841` | NOT RUN (not installed) |
| pip-audit | NOT RUN (not installed) |
| Linux / Windows | NOT RUN |

Skips: two wheel tests (no setuptools), live-run examples, and `test_no_unfilled_placeholders.py:180` "Node is not
installed" — an artifact of the isolated PATH (Node is under nvm; the test ran and passed in the non-isolated runs).
VERDICT (baseline scope): PASS.

**Still open:** on a page cut off at the size limit, "The homepage has N visible section heading(s)" and "long page(s)
have no subheadings" can still fire on the cut body (same limitation, not reviewed); `maya-report-checker` not run on how
IDX-1's part reads beside the report's single "not read" figure.

## Report fixes before w14 (2026-10-29, DECISIONS 283)

Brand-independent; no site-specific code. One commit per item: `3d0b988`, `9b42207`, `38b52b3`, `a20dd45`, `d38a800`,
`df55f7e`, `af3d586`, `86008d7` (Turkish wording for items 4 and 8), `71608b9`.

| # | Change | Tests |
|---|---|---|
| 1 | `maya-audit-pro` builds data.json through `final.from_report` (refuses without the engine); records `_digest`/`_gate_decision`; `validate_data.py` refuses data built from another state of the report. Broken-link card prints a "Düzenlenecek bağlantılar" table (page to edit, link text, link address, where it ends + status, new address "bilinmiyor"), 2 rows on the card, all rows in the CSV; RG-3 also checks the table's pages. H1 cards come from the separate H1 rules | skill `FinalResult` (4) |
| 2 | Headline counts pages whose worst page-specific problem is Medium+ ("Orta ve üstü sorunlu sayfa") | skill `test_page_kpi_counts_only_pages_with_a_medium_or_higher_problem` |
| 3 | STR-5 "brand named N ways" and "og:site_name holds the page title" share `dedup_key` `str5.site_name`; the name finding lists every page a counted name was seen on, so RG-9 sees the overlap | `tests/test_w14_report_fixes.py` (3, with a counter-example) |
| 4 | PRF-1 homepage TTFB: S2 → S3 (one measurement from Maya's network, never re-tested); note + Turkish | `tests/test_w11_homepage.py` |
| 5 | "Arama ve performans" page left out when there is no search, lab or field data (3 summary pages) | skill `SearchPage` (2) |
| 6 | Address CSV: UTF-8 BOM kept; ";" in Turkish, "," in English | skill `AddressList` (2) |
| 7 | `tools/release_metadata.py --release w14` wrote `RELEASE-SNAPSHOT.json` and `CHECKPOINT-VERIFICATION.md` (0.2.8 / schema 1.20 / w14; were 0.2.6 / 1.16 / team-preview-23). `.gitattributes` export-ignores `benchmarks/real-sites/`; `.env`, `.claude/`, `reviews/` already were. `git archive HEAD` lists 0 files under those paths. No zip built | `tests/test_release_metadata.py` (4) |
| 8 | Cut-off page (`body_truncated`): homepage-outline and long-page findings not raised; `evidence.sections_cut_off` + coverage part with reason; STR-2 partial | `tests/test_w14_report_fixes.py` (3, with a counter-example) |
| 9 | `maya-report-checker` on the partial-crawl fixture (below) | review only |

**Item 9 — report-checker** (fixture: `test_m1_broken_links.routes()` + sitemap listing the 2 unread addresses,
`max_pages=3`, offline loopback; schema 1.20, engine 0.2.8; gate PASS; outputs: report.json, CLI Markdown, Turkish PDF
from the skill). Order: `findings_in_priority_order`. Groups: IDX-2 S2 (no HTTPS on the loopback host — real for the
fixture, an environment artefact), STR-3 S3 no Organization (real: no JSON-LD), TSEO-1 S3 no viewport (real), IDX-5 S3
/eski-urun in the sitemap ends at a 404 (real: 301 → /bulunamadi 404), IDX-8 S4 near-identical content (real, same
filler text), STR-1 S4 generic title "Sayfa" (real); 7 Info not reviewed in detail. **6 real, 0 false, 0 unsure.**
IDX-1 vs "pages found but not read": **no contradiction.** Markdown top line "3 page(s) read; 2 more found and not read
(page cap)"; IDX-1 partial, summary scoped to "3 fetched URL(s)", part "addresses found but not fetched by the crawl"
count 2, says another step may have requested them — IDX-5 says 5 checked / 0 not assessed (it did). JSON
`known_urls_not_read` 2; Turkish PDF "Okunan sayfa 3 · 2 keşfedilen adres okunmadı", "3 sayfa okundu; 2 URL okunmadı".
Observation (not a contradiction, not changed): the PDF's "Değerlendirilmeyen kapsam 25" counts distinct parts, and
IDX-1's part and TSEO-1's "discovered pages not fetched" both restate the same 2 unread addresses as separate items.
length-defect: none (5-page PDF; repeated step text is the fixture's neutral filler). privacy-defect: not applicable
(fixture on 127.0.0.1, not a client export).

**Client PDF changes (maya-audit-pro):** broken-link card table instead of the one-line target + source links;
headline KPI Medium+ only, with new label and sub-line; page 3 dropped when empty (tabs and page numbers follow); CSV
";" in Turkish and extra link columns when a broken-link card exists; no PDF from data built off a changed report;
homepage TTFB card now Medium (scheduled later than before).

**Verification** (source `71608b9` + this file; macOS, Python 3.13.1):

| Gate | Result |
|---|---|
| `.venv/bin/python -m pytest -q -rfEs -p no:cacheprovider` (full suite) | `2626 passed, 3 skipped, 1 warning in 710.91s (0:11:50)` |
| Skill tests `.agents/skills/maya-audit-pro/tests` | `36 passed` |
| `python3.11 -m compileall` (maya_audit, maya_audit_web, tests, tools, skill scripts) | OK |
| CLI once against a loopback fake site (`crawl … --no-prf --json`, offline child env) | exit 0; JSON parses, schema 1.20, gate PASS |
| Fixture PDFs rendered and pages inspected (broken-link + H1 fixture: pages 1, 3, 5; partial fixture) | table, KPI and 3-page summary as described |
| ruff `E9,F821,F841` | NOT RUN (not installed) |
| Linux / Windows CI | NOT RUN (no push) |
| Wheel tests | skipped (no setuptools in `.venv`) |

Skips: two wheel tests, live-run examples. No live or paid calls; nothing pushed.

## w14 release (2026-10-29)

Tag `team-preview-w14` → `542c67e` (local, not pushed). Zip `~/Projects/releases/maya-audit-0.2.8-w14-2026-10-29.zip`,
SHA-256 `801919a7803414973741f6c6026114f44cb7abf722c8e5fe7ffff23c494d91f9`, 487 files, none under the excluded paths;
details in the `-VERIFICATION.json` beside it (also on the Desktop).

| Gate (extracted archive, fresh venv, Python 3.13.1, macOS) | Result |
|---|---|
| Full suite | `2 failed, 2623 passed, 4 skipped, 1 warning in 746.78s` — **FAIL** |
| Failures | `test_real_sites_benchmark.py` × 2: read `benchmarks/real-sites/sites.json`, which the archive leaves out. Fixed in `632ab19` (after the tag) |
| Wheel + `tools/check_installed_package.py --wheel` | PASS; `test_distribution_contract.py` with the wheel: 10 passed |
| Demo audit (`--demo --port 8791`, demo-kafe.localhost) | finished, COMPLETED; web PDF 200, gate PASS |
| `maya-audit-pro` Turkish PDF from the demo report | 5 pages, 4 cards, validate + render clean; gate PASS |

Next: a w14b tag and zip from `632ab19` or later, verified the same way (the release rule never moves a tag).

## w14b release (2026-10-29)

Tag `team-preview-w14b` → `57aa9d6` (local, not pushed); supersedes w14. Zip
`~/Projects/releases/maya-audit-0.2.8-w14b-2026-10-29.zip`, SHA-256
`434ed760e1eccf2e9fcfa21ef6cff0c2ed2b18da5d488d77077a4ace6a5dfac5`, 487 files, none under the excluded paths.
`tests/test_release_metadata.py` now accepts a letter suffix on the release label.

| Gate (extracted archive, fresh venv, Python 3.13.1, macOS) | Result |
|---|---|
| Full suite | `2624 passed, 5 skipped, 1 warning in 767.13s (0:12:47)` — 0 failed |
| Skips | 3 not a Git checkout; live-run examples not committed; real-site corpus not shipped |
| Wheel + `tools/check_installed_package.py --wheel` | PASS; `test_distribution_contract.py` with the wheel: 10 passed |
| Demo audit (`--demo --port 8791`, demo-kafe.localhost) | finished, COMPLETED; web PDF 200, gate PASS |
| `maya-audit-pro` Turkish PDF | 5 pages, 4 cards, validate + render clean; gate PASS (0 hard violations) |
| ruff, Linux/Windows, live providers | NOT RUN |

VERDICT: PASS. The w14 zip was removed from the Desktop; its copy stays in `~/Projects/releases`.

## Client reports from the 2026-10-29 web audits (w14b)

`maya-audit-pro` Turkish PDF and address CSV from the saved reports (engine 0.2.8, source `31ad1bc`, w14b). Only
card text was written; findings, severities and report.json are unchanged. Outputs are in `reviews/2026-10-29/`
(git-ignored).

| Site | Audit id | Pages read | Cards | PDF pages | Gate |
|---|---|---|---|---|---|
| www.carpexonline.com | `cb760167…` | 50 | 20 | 8 | PASS, 0 violations |
| www.enpara.com | `07297f4d…` | 50 | 16 | 7 | PASS, 0 hard; 1 High not re-tested (TSEO-1) |
| adilesultanevyemekleri.com | `6f2830d5…` | 37 | 20 | 8 | PASS, 0 hard; 1 High not re-tested (STR-2 hidden `<h1>`) |

None of the three had search, lab or field data, so all three have a 3-page summary. The first Enpara draft was
BLOCKED by RG-3: a step named `/hakkimizda`, which is the llms.txt redirect's target and is not among the card's
addresses. The step was reworded and the gate then passed.

**Open: page counts in the Adile report (`6f2830d580134ce3b0239dfa2d398e2b`). No code change yet.**
- `audit_status.summary` and `content_coverage.pages_read` say 37 pages were read (35 Firecrawl + 2 native), but
  `page_counts.pages_checked` is 50.
- `crawl.stop_reason` is `page_cap` ("page cap of 50 reached"), but `crawl.deadline_hit` is true. The reader's own
  stop reason is `time_limit` (40 of 51 requests sent). `native_page_records` is 67; whether the cap counted records
  rather than pages read is not checked yet.
- The stop reason should name the time limit, and `pages_checked` should not exceed the pages read.

## Fixes after the 2026-10-29 client PDFs (DECISIONS 284)

Brand-independent; one commit each, offline tests only.

| # | Fix | Where | Regression test |
|---|---|---|---|
| 1 | One card per cause: same `dedup_key` (early-closed <head>, STR-5 names + og:site_name), IDX-1 repeated + single empty on shared sections, identical catalogue titles. A line per finding, the other findings' steps while they fit, one table row counting every address | skill `build_data.py`, `render.py` | `OneCauseOneCard` (7 tests) |
| 2 | Owner and effort from the engine catalogue: early-closed <head>, hidden <h1>, template markers → Geliştirici | skill `build_data.py`, `sahip_efor.json` | `Owners` (3) |
| 3 | A hidden homepage <h1> is Medium: nothing re-tests it | `checks/structure.py` | `test_w14c_fixes.py`, `test_w11_homepage.py` |
| 4 | STR-8 leaves out a calculator's result grid (control in the same block, or a block named as a calculator) | `analysis.py`, `checks/structure.py` | `test_w14c_fixes.py` (3) |
| 5 | Sitemap review addresses counted by reason on the card and the table row | skill `build_data.py`, `etiketler.json` | `SitemapReasons` (3) |

Cards with the new lines overflowed at first (the render refused the PDF): their steps box now shrinks to its lines and
they show two links (the rest in "+N" and the CSV).

**v2 client PDFs** (same report.json files, `reviews/2026-10-29/v2/`, copied to the Desktop):

| Site | Cards (v1 → v2) | Pages | Gate |
|---|---|---|---|
| carpexonline.com | 20 → 19 (STR-5 merged) | 8 | PASS, 0 violations |
| enpara.com | 16 → 14 (<head> merged; two generic-link cards merged) | 7 | PASS, 0 hard; 1 High not re-tested (TSEO-1) |
| adilesultanevyemekleri.com | 20 → 19 (IDX-1 merged) | 8 | PASS, 0 hard; 1 High not re-tested (STR-2 hidden <h1>) |

Fixes 3 and 4 change the engine, so they apply to new audits. A saved report keeps what it was written with: Adile's
hidden <h1> is still High (S2) and Enpara's loan-calculator STR-8 card is still there in v2. Re-running or re-analysing
those audits is needed to see them change; not done (no new audits were started).

| Command (checkout, macOS, Python 3.13.1) | Result |
|---|---|
| `.venv/bin/python -m pytest -q -rfE` (first run, after the five fixes) | `1 failed, 2629 passed, 3 skipped` — `test_m1_broken_links.py` used the hidden <h1> as a High example; test updated (`f885670`) |
| same, after the test update | `2630 passed, 3 skipped, 1 warning in 779.81s (0:12:59)` |
| skill tests `pytest -q .agents/skills/maya-audit-pro/tests` | `50 passed` |

## w14c release (2026-10-29)

Tag `team-preview-w14c` → `78a27e3` (local, not pushed); supersedes w14b with the DECISIONS 284 fixes. Zip
`~/Projects/releases/maya-audit-0.2.8-w14c-2026-10-29.zip`, SHA-256
`d04460ada20e612fb703984b3c9801b2c37b1090afc8928d86d9bbfe6218c105`, 488 files, matches `RELEASE-SNAPSHOT.json`, none
under the excluded paths. Zip and `-VERIFICATION.json` copied to the Desktop.

| Gate (extracted archive, fresh venv, Python 3.13.1, macOS) | Result |
|---|---|
| Full suite | `2628 passed, 5 skipped, 1 warning in 754.15s (0:12:34)` — 0 failed |
| Skill tests | `50 passed` |
| Wheel + `tools/check_installed_package.py --wheel` | PASS; `test_distribution_contract.py` with the wheel: 10 passed |
| Demo audit (`--demo --port 8791`, demo-kafe.localhost) | finished, COMPLETED; web PDF 200, gate PASS |
| `maya-audit-pro` Turkish PDF from the demo report | 5 pages, 4 cards, validate + render clean; gate PASS (0 hard; IDX-2 High not re-tested, listed) |
| ruff, Linux/Windows, live providers | NOT RUN |

VERDICT: PASS.

## v3 client PDFs: saved reports under the 284 rules, offline (DECISIONS 285)

`tools/reassess_saved.py` on the saved Enpara and Adile report.json (sockets refused, sources unchanged), written to
`reviews/2026-10-29/v3/analysis/<site>/`; then `maya-audit-pro --reanalysis` ("Yeni tarama yapılmadı") into
`reviews/2026-10-29/v3/`, copied to the Desktop.

| Site | Change | Cards | Gate |
|---|---|---|---|
| enpara.com | STR-8-e7c537b5 removed: both grids are in a block named as a calculator (`/krediler/ekpara`, `/sirketim/krediler/ekpara`); problems 12 → 11 | 14 → 13 | PASS, 0 hard; 1 High not re-tested (TSEO-1) |
| adilesultanevyemekleri.com | STR-2-81543ae6 hidden homepage <h1>: S2 → S3; High 2 → 1 | 19 | PASS, 0 hard; 0 High not re-tested |

Not assessed offline: STR-8's "form control beside the grid" test (the report keeps no page structure). No pricing
grid was left on either site for it to decide. Nothing else was re-run.

| Command | Result |
|---|---|
| full suite after `6573d65` | `1 failed, 2634 passed, 3 skipped` — generated `docs/FIXTURE-MATRIX.md` counts out of date; regenerated |
| `pytest -q tests/test_fixture_matrix.py tests/test_reassess_rules.py` | passed |
