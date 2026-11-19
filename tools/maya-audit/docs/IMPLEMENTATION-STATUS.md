# Implementation status

Tracks `docs/Maya-Audit-Claude-Code-Uygulama-Rehberi-2026-10-28.md` (the guide). Status values: NOT_STARTED,
IN_PROGRESS, VERIFIED, BLOCKED_ON_INPUT. A command that was not run is written NOT RUN, never implied as passed.

Source: `~/Projects/maya-audit`, Git repo created from `maya-audit-0.2.8-w13-2026-10-28.zip`, baseline commit `a40500b`.
Since 2026-10-30 the repository is the private GitHub repo **withmaya/seo-audit** (remote `origin`,
https://github.com/withmaya/seo-audit), branch `main`; this tool is its folder `tools/maya-audit/`, and
`~/Projects/maya-audit` is the whole repository's root (DECISIONS 292). Pushes to withmaya/seo-audit are allowed when
the owner asks for them, never otherwise; never force-push. Package 0.2.8. Interpreter `.venv/bin/python` = CPython 3.13.1 (macOS arm64).
`HANDOVER.md` not available. Call map and code-level findings: `docs/architecture/baseline.md`.
The v0.3 plan (stages, status, goals): `docs/ROADMAP-v0.3.md`.

| Stage | Status | Note |
|---|---|---|
| 00 Baseline | IN_PROGRESS | Baseline, call map, test state recorded. Step 7 (`tests/fixtures/quality/`) not started |
| 01 Packaging | IN_PROGRESS | Packaging defect fixed and verified from an installed wheel; guide steps 5 (report/static smoke) and 6 (explicit missing-catalogue error) open |
| 02 Result contract | IN_PROGRESS | M1 minimum: `maya_audit/final.py` (`FinalAuditResult`, `seal`, `from_report`) |
| 03 Rule identity | NOT_STARTED | |
| 04 Shared finalization | IN_PROGRESS | `final.settle`/`verify` in `run_audit` and after a page reader; batch not moved |
| 05 Shared service (CLI/batch/web) | IN_PROGRESS | CLI and web use `final.seal`; the `maya-audit-pro` skill reads through `final.from_report`; batch not moved |
| 06 Output generations | NOT_STARTED | |
| 07 Source/page type/scope/render | IN_PROGRESS | H1: raw vs rendered per page (`h1_sources`); a page cut off at the size limit is not assessed for its <h1> or its section headings; page grouping per page (v0.3 stage 3, DECISIONS 297; importance fixes 298) |
| 08 Rule contract + catalogue | IN_PROGRESS | Missing catalogue is an error; actions for idx6.broken and every H1 rule |
| 09 One publication gate | IN_PROGRESS | Every web report download and the final client export gated; CLI writes and warns; batch not gated |
| 10 URL-level report | IN_PROGRESS | Broken-link cards (page, link text, target, status, replacement unknown) in Markdown, web PDFs and the `maya-audit-pro` client PDF |
| 11 Team status vs engine verification | NOT_STARTED | |
| 12 SEO accuracy measurement | BLOCKED_ON_INPUT | Needs human SEO labels; nothing labelled yet |
| 13 Integration and release | VERIFIED | w14d (tag `team-preview-w14d`, `21b54a2`): extracted-archive verification PASS. w14c superseded; w14 FAIL |

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

## w14d release (2026-10-30)

Tag `team-preview-w14d` → `21b54a2` (local, not pushed). Zip `~/Projects/releases/maya-audit-0.2.8-w14d-2026-10-30.zip`,
SHA-256 `412f83d1ba0fb3c741a0aeccbc9d1cfd077d5c07f78d1d14c3a3e568fe337340`, 496 files, matches `RELEASE-SNAPSHOT.json`, none
under the excluded paths and no audit output. A git bundle with the full history and all tags is beside it, with
`TEAM-HANDOFF.md`; both are copied to the Desktop.

| Gate (extracted archive, fresh venv, Python 3.13.1, macOS) | Result |
|---|---|
| Checkout suite before the tag | `2663 passed, 4 skipped, 1 warning in 728.26s (0:12:08)` |
| Full suite (extracted) | `2662 passed, 5 skipped, 1 warning in 738.07s (0:12:18)` — 0 failed |
| Wheel + `tools/check_installed_package.py --wheel` | PASS; `test_distribution_contract.py` with the wheel: 10 passed |
| Demo audit (`--demo --port 8791`, demo-kafe.localhost) | finished, COMPLETED; web PDF 200, gate PASS |
| `maya-audit-pro` Turkish PDF from the demo report | 5 pages, 4 cards, validate + render clean; gate PASS (0 hard; IDX-2 High not re-tested, listed) |
| gitleaks 8.30.1, full history, `.gitleaks.toml` | no leaks found |
| ruff, Linux/Windows, live providers | NOT RUN |

VERDICT: PASS.

## Published to withmaya/seo-audit (2026-10-30, DECISIONS 292)

Owner's request: the project goes into `tools/maya-audit/` of the private repository withmaya/seo-audit, keeping its
first commit (`ba7dc9e`, README) and our full history. Write access confirmed with gh; `main` has no branch protection,
so `main` was pushed directly (fast-forward, no force).

| Step | Result |
|---|---|
| Branch | `master` renamed to `main` |
| `87ddd72` | the move: 494 pure renames into `tools/maya-audit/`; `.github/` and `.gitleaks.toml` stay at the root |
| `b54c685` | fixes for the move: CI `working-directory: tools/maya-audit`; source commit found in the repository root above the project (`report.py`, benchmark); release-metadata test asks Git; root `.gitignore`; `.gitleaks.toml` allows the snapshot at old and new path; README "New teammate" (`cd seo-audit/tools/maya-audit`); release/verifier skills archive from `tools/maya-audit` |
| `00d74c4` | merge of `origin/main` (`--allow-unrelated-histories`); root README keeps its title and description, adds "Contents" |
| Full suite, `tools/maya-audit`, before the merge and after it | `2663 passed, 4 skipped` both times |
| Demo web app from `tools/maya-audit` (port 8792, temp `MAYA_AUDIT_HOME`) | page 200, stopped |
| gitleaks 8.30.1, full history, `.gitleaks.toml` | 55 commits scanned, no leaks found |
| Pushed | `main` (`ba7dc9e..00d74c4`), tags `team-preview-w14`, `w14b`, `w14c`, `w14d` |
| GitHub Release | https://github.com/withmaya/seo-audit/releases/tag/team-preview-w14d with the w14d zip and VERIFICATION.json (GitHub's SHA-256 digests match the local ones) |

The w14d zip is built from tag `team-preview-w14d`, before the move, so it has the old layout. Local setup: the
virtual environment stays at the repository root (`~/Projects/maya-audit/.venv`); `tools/maya-audit/.venv` is a
symlink to it, and its editable install was pointed at `tools/maya-audit/` (paths only; nothing installed). `.env` was
moved unopened into `tools/maya-audit/` (the app reads `./.env`). Start the web app:
`cd ~/Projects/maya-audit/tools/maya-audit && .venv/bin/python -m maya_audit_web`.
NOT RUN: CI on GitHub for the pushed commit was not checked here; ruff; Linux/Windows.

## v0.3 stage 1: where an audit's time goes (2026-11-02, measured offline, no code change)

Read-only from the saved web audits: `report.json` (`crawl.steps`, `generation.native_requests_by_purpose`,
`audit_status.timing`, `firecrawl.calls`, `content_coverage`) and the web app's event log (`web-v1.db` table `events`,
opened read-only). No website or provider was contacted. Audits: nihan `b3198942…` (Standard, 500 pages, 2026-10-30),
adile `6f2830d5…` (Quick, 50, 2026-10-29), enpara `07297f4d…` (Quick, 50, 2026-10-29).

Steps as the request asked; mapped from the engine's steps: access = ACC step (AI-crawler access; enpara also 9.6 s
before Maya's first request, web worker start, not attributed); sitemap URL checks = `sitemap_check` + `llms_links`;
checks = `index` + `structure` + `performance` (their seconds) + `other_sites` (requests only: it runs in a pool beside
them) + "Working out the results" (no request; from the event log, 1 s resolution); Firecrawl = `page_reader`;
report = from Firecrawl's last answer to `done`. Rows add up to the whole job within 1 s.

| Step | nihan s (min) | req | adile s (min) | req | enpara s (min) | req |
|---|---|---|---|---|---|---|
| access | 7.7 | 9 | 13.5 | 9 | 8.6 (+9.6 start) | 8 |
| sitemap | 30.7 | 27 | 35.7 | 14 | 2.3 | 3 |
| crawl | 534.7 (8.9) | 523 | 181.1 (3.0) | 103 | 73.1 (1.2) | 60 |
| sitemap URL checks | 828.6 (13.8) | 1,028 | 534.5 (8.9) | 183 | 293.4 (4.9) | 208 |
| rendering | 124.8 (2.1) | 560 | 104.5 (1.7) | 286 | 82.8 (1.4) | 139 |
| checks | 107.0 + 17 results | 115 | 210.8 + 27 results | 155 | 102.8 + 2 results | 88 |
| Firecrawl | **3,451.3 (57.5)** | 501 calls | 420.2 (7.0) | 40 calls | 209.6 (3.5) | 51 calls |
| report | ~5 | 0 | ~1 | 0 | ~1 | 0 |
| **whole job** | **5,106 (85.1)** | 2,262 + 501 | **1,527 (25.5)** | 750 + 40 | **785 (13.1)** | 506 + 51 |

Share of the job: nihan Firecrawl 68 %, sitemap URL checks 16 %, crawl 10 %; adile sitemap URL checks 35 %, Firecrawl
28 %, checks 16 %; enpara sitemap URL checks 37 %, Firecrawl 27 %, checks 13 %.

**Waiting (Maya's pace on the audited site):** of the sitemap URL checks, 485 s (nihan), 181 s (adile), 193 s (enpara)
is the gap between requests; nihan's pace narrowed to the 0.5 s floor, adile and enpara stayed at 1.0 s and 0.56–1.0 s.
Adile's site is slow: 1.9 s network time per light request (nihan 0.3 s, enpara 0.4 s).

**Pages read** (`content_coverage.read_by`):

| | Maya page requests | Firecrawl pages read (calls) | read by both | Firecrawl only | Maya only | pages in report |
|---|---|---|---|---|---|---|
| nihan | 500 | 500 (501) | 499 | 1 | 0 | 500 |
| adile | 50 (17 were redirects) | 35 (40; stopped: time limit) | 35 | 0 | 2 | 37 |
| enpara | 50 | 50 (51) | 47 | 3 | 0 | 50 |

Firecrawl is the main reader (DECISIONS 131), so it re-reads the pages Maya already read. Its calls go one at a time,
each after Maya's pace (`runclock.wait_for_turn`): 6.9 s per call on nihan, 10.6 s on adile, 4.1 s on enpara. Adile ran
out of time: its reader allowance assumes 8 s + pace per page (450 s for 50), and the site's 10.6 s per call needed 530 s,
so 15 pages were not read.

**Firecrawl concurrency** (https://docs.firecrawl.dev/rate-limits, read 2026-11-02): concurrent browsers Free 2, Hobby 5,
Standard 25, Growth 50, Scale/Enterprise 100+; jobs above the limit wait in a queue (the wait counts against the
request's timeout), and only a full queue (50,000 jobs on Free–Standard) or the per-minute limit returns 429. `/scrape`
per minute: Free 10, Hobby 100, Standard 500, Growth 5,000, Scale 10,000; limits are per team. Our plan is not recorded
in the repository; the local ledger shows 1,866 credits settled in October 2026, more than Free's 1,000, so the plan is
at least Hobby (5 at once). To be confirmed by the owner (not looked up: that is a call with the key).

**Three biggest time savings (proposals; none implemented):**

1. **Firecrawl: up to 5 calls in flight** (Hobby's limit; the start of each call still keeps Maya's pace). Per page
   ≈ call time / 5, not below the pace. Expected: nihan 57.5 → ~11.5 min (**−46 min**), adile 7.0 → ~1.8 min for all 50 pages
   (−5 min, and no page left unread by the time limit), enpara 3.5 → ~0.9 min (−2.6 min). Owner decision: the audited site then
   sees up to 5 overlapping reads through Firecrawl instead of one.
2. **Start Firecrawl right after the crawl, beside rendering, checks and the sitemap URL checks** (postponed by the owner
   on 2026-10-15, DECISIONS "Part 1": "a later round"). Saves the shorter of the reader and the steps after the crawl.
   Alone: nihan −18 min, adile −7 min, enpara −3.5 min. With 1: nihan's whole reader (~11.5 min) is hidden behind
   the ~18 min of later steps. Owner decision: whether the reader's and Maya's requests share one pace on the site
   (then they slow each other) or each keeps its own (Firecrawl's requests come from Firecrawl's network).
3. **Smaller sitemap URL check sample**: Standard 1,000 → 300, Quick 200 → 100 (`section_sample` already picks one URL
   per section in turn). At the measured cost per request (0.81 s nihan, 2.92 s adile, 1.41 s enpara): **nihan −9.5 min,
   adile −4 min, enpara −2.4 min.** Cost: IDX-5 says "checked a sample" (Estimated) on more sites instead of every URL.

All three together, nihan: about 85 → ~21 min (sitemap and crawl ~9.5, then the reader ~11.5 with the later steps,
~8.6 after 3, beside it). Estimates from these three runs only; not measured.

## v0.3 stage 2: speed (2026-11-02, DECISIONS 294)

**Changed:** new `maya_audit/sitelimit.py` (one limit on the audited site after the crawl, Maya's and the reader's
requests together: 5 at once, starts the polite gap apart, back-off 5 → 2 → 1); `fetcher.py` (requests to the site go
through it; `RequestRecord.slot`; INT-4 gaps per slot and between overlapping starts); `audit.py` (`run_audit(reader=)`,
the limit, Maya's steps get the whole deadline when the reader runs beside them); `firecrawl/reader.py` (reading split
from the checks; up to `Options.concurrency` at once, one at a time until the first page; back-off; measured pace;
`EarlyReading`); `firecrawl/client.py` (thread-safe guard and records, a slot per request, call time,
`ProviderRateLimited`); `firecrawl/settings.py` (`concurrency`, `MAYA_AUDIT_FIRECRAWL_CONCURRENCY`, `SLOW_CALL_S`);
`runclock.py` (`take_turn`/`give_back`, `needs_s` from measured calls, reserve ÷ requests at once); `index_data.py`
(sample over the sitemap files, 4 at a time, back-off on 429), `sitemap.py`/`crawler.py` (which file listed each URL);
`checks/index.py`, `checks/integrity.py`, `report.py` (sample and time-skip sentences); `cli.py`
(`--firecrawl-concurrency`, `--site-concurrency`, caps 300/100, early start); `maya_audit_web/runner.py`, `app.py`,
`fc.py`, `paid.py`, `static/app.js`, strings EN/TR (early start, progress box, estimate). Schema 1.21
(`docs/report-schema-1.21.json`, REPORT-SCHEMA.md). Tests: `tests/test_v03_speed.py` (new), updated
`test_round2_sitemap_and_llms.py` (429 backs off; caps 100/300), `test_time_limit.py` (smaller default limit),
`test_firecrawl.py` (test helper passes `reader`).

**Found and fixed while verifying:** (a) tests that patch `time.monotonic`/`time.sleep` hung, because the limit had
captured the real clock; it now reads the time module at each call and waits out a gap with `time.sleep`. (b) The
first request after the crawl skipped the polite gap (the limit knew nothing of the crawl's last request); the limit is
now seeded with it (`test_the_first_request_through_the_limit_keeps_the_gap_after_the_crawls_last_one`). (c) Maya's own
thread waiting for its gap blocked the reader entirely; the reader may now start when that does not delay Maya's next
request. (d) robots.txt samples were not sent while the sitemap check ran on worker threads; the audit's own thread now
sends them meanwhile.

**Expected times** (estimates from the stage-1 measurements, not measured; Firecrawl assumed to keep its single-call
time at 5 at once):

| Run | Before | Expected | Where the time goes |
|---|---|---|---|
| nihan, Standard 500 | 85.1 min | ~24-25 min | crawl 9.4 min unchanged; then Firecrawl ~12-15 min (500 × 6.9 s ÷ 4-5 at once), with Maya's later steps (~7-8 min, sitemap check 300 URLs) beside it |
| Quick 50, fast site (enpara) | 13.1 min | ~6 min | crawl 1.4 min; Maya's later steps ~4.7 min (sitemap check 100 URLs); Firecrawl ~1 min, hidden beside them |
| Quick 50, slow site (adile) | 25.5 min | ~11-12 min | crawl 3.6 min; Maya's later steps ~7.8 min; Firecrawl ~2.2 min, hidden; all 50 pages read (35 before) |

If Firecrawl backs off to 1 at a time, nihan's reader takes ~60 min again and the time limit (about 72 min for
Standard with the reader) may leave pages unread; the report then counts them ("not read for lack of time").

## Double reading (DECISIONS 131): what Firecrawl's copy changes on nihan (offline, 2026-11-02; no code change)

DECISIONS 131 (Owner, 2026-10-08) made Firecrawl the page reader of every audit when a key is set; the repository records
the decision, not a reason. What the code does with it: Maya's own request decides status, headers, timing and whether
a page may be indexed (DECISIONS 167); Firecrawl's document replaces the page content for the content checks (IDX-8,
STR-1 to STR-23, TSEO-1), the same way on blocked and open sites. The report's own notice says Firecrawl's document "may
already hold what JavaScript added, so it does not show what a crawler that runs no JavaScript receives".

Method: the nihan report (`b3198942…`, engine `065f0b9`, the version that wrote it) was rebuilt from `report.json`
(Maya's 500 page records with full analysis) and the content checks were run on Maya's own reading, sockets refused; the
result was compared rule by rule with the report's checks, which ran on Firecrawl's reading of the same pages (499 read
by both). Per page (`evidence/` vs `evidence-firecrawl/`): title, canonical, H1, JSON-LD blocks and `<html lang>` are
identical on all 499 pages; Firecrawl's main text is longer (median 617 vs 545 words, +14%). The local browser's render
sample (20 pages) found the same word count as the raw HTML, so the extra text is not JavaScript content: Firecrawl
received visitor-specific blocks (e.g. headings "Cart 0 items", "Henüz favoriniz yok.").

| Rule | Maya's reading | Firecrawl's reading |
|---|---|---|
| 7 rules | same | same |
| STR-1 shared titles (S4) | 9 titles on 18 pages | 6 titles on 12 pages (the other pages fall under IDX-8's copies) |
| STR-14 links without text (S4) | 4 links / 4 pages; shared-link groups on 80-88 pages | 3 links / 3 pages; different groups |
| STR-15 thin pages (Info) | 162 pages | 13 pages |
| STR-19 links without address (S4) | grouped by Maya's copy | grouped differently |
| TSEO-1 heading jumps (S4) | 214; repeated "Secure Shopping" H3 | 47; repeated "Cart 0 items" H3, "Henüz favoriniz yok." H4 |
| IDX-8 near copies (S4) | — | 6 groups, 12 pages |
| STR-12 language mismatch (**S3**) | — (169 pages "too little main content to tell") | 47 pages declared English, written mostly in Turkish |
| STR-9 lang mismatch (S4) | — | 6 pages |
| STR-3 FAQ without FAQPage (Info) | — | 10 pages |
| STR-20 message in video (S4) | 2 pages | — |

Totals: Maya's reading 15 S4 + 5 Info; Firecrawl's 1 S3 + 20 S4 + 6 Info. The only S3 (STR-12) exists only in
Firecrawl's copy.

**Proposal (not implemented; waits for the owner): "Firecrawl only where needed".** Firecrawl reads a page only when
(a) Maya could not read it (blocked, challenged, 429, empty to Maya, no answer), or (b) its template depends on
JavaScript: the render sample shows rendered text well above raw (rendered > 1.5 × raw + 50 words, RND-1/RND-2), or the
raw page is an app shell (a mount node with under 50 raw words). Every other page keeps Maya's own reading, which is
also what a crawler that runs no JavaScript receives. On the three saved audits that is 0 pages (Maya read every page;
the 20-page render samples showed no JavaScript content), so: credits 501 / 51 / 40 → 0 per run; time, after stage 2,
nihan ~24-25 → ~17 min (the reader is what ends the run there), Quick runs ~0 min (the reader is already hidden) but
no credits. Findings: the rows above in Firecrawl's column would follow Maya's copy (the STR-12 S3 would disappear).
Owner decision needed: which copy the content checks should judge on a site that reads fine without JavaScript.

**Verification of stage 2** (working tree on `c22a0b0`+, macOS, Python 3.13.1; isolated home, no .env, no providers):

| Command | Result |
|---|---|
| `pytest -q -m "not slow and not timing"` (fast suite) | `1 failed, 2551 passed, 4 skipped, 132 deselected, 1 warning in 400.78s` |
| the one failure | `test_release_metadata.py::test_snapshot_and_checkpoint_state_the_applications_version`: `RELEASE-SNAPSHOT.json` records the w14d release (schema 1.20); it is rewritten only by release preparation (`tools/release_metadata.py`), not done here. Expected until the next release |
| `tests/test_v03_speed.py` | `20 passed` |
| `python3.11 -m compileall` | OK |
| full suite, ruff (not installed), Linux/Windows, live runs | NOT RUN |

## After the live nihan run: Firecrawl's own pace, timeout retry, keep-awake, RND-6, wording (2026-11-02, DECISIONS 295, 296)

**The live run** (owner's report, nihan Standard 500 on the stage-2 code; the saved audit was not re-analysed here):
Maya's crawler blocked after 1 page (429); Firecrawl read 388 of 500; 2,687 s active, wall clock 13:47-15:51 (the Mac
slept); reading stopped on one Firecrawl `ReadTimeout`.

**Changed:** new `maya_audit/firecrawl/pace.py` (Firecrawl's own pace: up to 5 at once, starts at least the gap apart,
1 s by default, back-off 5 -> 2 -> 1 with the gap doubled, on Firecrawl's 429/5xx, the site's 429/5xx through it, and
timeouts; a Crawl-delay is a floor); `runclock.py` (`reader_pace`, `started_wall`, `slept_s`); `firecrawl/reader.py`
(own pace instead of Maya's limit; a timed-out page asked for once more after 5 s, then skipped; 5 failures in a row
stop; `coverage.timeouts`; RND-6 on Firecrawl's HTML when Maya was blocked); `firecrawl/client.py` (`PossiblyBilled.timed_out`,
`ProviderTimedOut` for HTTP 408); `firecrawl/settings.py` (`gap_s`, `RETRY_WAIT_S`); new `maya_audit/keepawake.py`
(`caffeinate -i -w <pid>` on macOS around CLI `crawl`/`batch` and each web job); `report.py` (outcome sentence for a 429
stop with pages read, the coverage line's timeout counts, `timing.slept_s`/`slept_note`, duration line); `audit.py`,
`cli.py` (`--firecrawl-gap`), `crawler.py` (`delay_s` in progress events), `sitelimit.py` (docs); web: `runner.py`,
`app.py`, `summary.py`, `static/app.js`, `fc.py`, `paid.py`, strings EN/TR. Schema 1.22. `tests/test_release_metadata.py`
no longer fails between releases (DECISIONS 295 (6)). DECISIONS 296 + `docs/BACKLOG.md`: "Firecrawl only where needed"
is not adopted now.

**Tests:** new `tests/test_v03_live_fixes.py` (16); updated `test_v03_speed.py`, `test_run_clock.py`,
`test_firecrawl.py`, `test_coverage_phase2.py` (the old rules they asserted, or one at a time for an exact count),
schema `1.21` -> `1.22` literals in 8 files; `conftest.py` sets Firecrawl's gap and retry wait to 0 and keep-awake off.

**Verification** (working tree on `57a74fc`, macOS, Python 3.13.1; isolated home, no .env, no providers): see the
table below.

| Command | Result |
|---|---|
| `pytest -q -ra` (full offline suite, all markers) | `2700 passed, 4 skipped, 1 warning in 1304.65s` (skips: 2 wheel builds without setuptools, live-run examples not in git, real-site corpus outside the repo) |
| `tests/test_v03_live_fixes.py` | `16 passed` |
| `python3.11 -m compileall -q maya_audit maya_audit_web maya_audit_web_lite.py tests tools` | OK (CPython 3.11) |
| CLI on a loopback fake site, `--json`/`--markdown` | exit 0; `out.json` schema 1.22, `timing.slept_s` 0.0, no sleep note |
| `ruff check --select E9,F821,F841` | NOT RUN: ruff is not installed in `.venv` |
| Linux/Windows, live runs, pip-audit | NOT RUN |

The first full run had 2 failures, both from this change: the coverage benchmark counted requests one at a time (now
pinned to 1 at once, `scripts/coverage_benchmark.py`), and `docs/FIXTURE-MATRIX.md` was stale (already since stage 2;
regenerated). The fast suite before that also showed 5 failures from this change (CLI duration line, a test listing
RND-6 as untouched, schema 1.21 in README and a schema-history test); all fixed before the final run above.

**Not measured:** the effect on a live audit (the next live nihan run will show the time with Firecrawl's own pace,
and whether timeouts recover on the retry). Why Maya was blocked after one page is not examined.

## v0.3 stage 3: page grouping (2026-11-02, DECISIONS 297)

**Changed:** new `maya_audit/page_groups.py` (template key = URL pattern + layout fingerprint; page type home /
category / product / blog_article / policy / utility / other with its basis; internal link score = weighted PageRank,
footer-only links 0.25, links to a duplicate counted for its canonical; click depth from the homepage, its hreflang
alternates one step, `null` when not reached; importance 0-100 = 50% link + 25% depth + 25% type, capped at 20 for
non-indexable and utility pages), run in `final.settle`; `models.py` (`PageFetch.grouping`, `CrawlResult.page_grouping`);
schema **1.23** (`docs/report-schema-1.23.json`, REPORT-SCHEMA.md, README; the frozen shape lists page and crawl fields,
so new fields need a bump); new `tools/page_groups_saved.py` (offline, read-only, for saved reports). Not read by any
check, severity or the release gate. Tests: new `tests/test_page_groups.py` (9); schema literals 1.22 -> 1.23 in 9 test files.

**Saved audits, offline** (copies of `report.json` in a temp folder; `~/.maya-audit/web` untouched, byte-compared):

| Audit | Scored / not | Templates | Page types | Not reached from home |
|---|---|---|---|---|
| nihan `b3198942` | 498 / 2 (an image, agents.md) | 18 | product 331, category 149, policy 6, utility 4, blog_article 4, home 2, other 2 | 0 (241 via the homepage's hreflang) |
| adile `6f2830d5` | 36 / 31 (17 redirects, 14 empty 200s or files) | 16 | other 22, policy 6, blog_article 4, category 3, home 1 | 4 |
| enpara `07297f4d` | 50 / 1 (redirect) | 19 | other 45, category 4, home 1 | 0 |

nihan: 329 of 331 product pages are `/collections/*/products/*` copies whose canonical is `/products/*` (capped at 20);
only 8 canonical `/products/*` pages were read. Found on the way, not changed: STR-3's `page_kind` calls those 323
`/collections/<c>/products/<p>` pages listings ("category"), which feeds `page_types` on findings and the release gate.

**Verification** (working tree on `762ac12`, macOS, Python 3.13.1; isolated home, no .env, no providers):

| Command | Result |
|---|---|
| `pytest -q -m "not slow and not timing"` | `1 failed, 2576 passed, 4 skipped, 132 deselected, 1 warning in 996.51s`; the failure was this change's own edit of the schema-history test (an inline comment cut a line); fixed, then the three affected files: `39 passed in 3.54s` |
| `tests/test_page_groups.py` | `9 passed` |
| `python3.11 -m compileall` (changed files) | OK |
| CLI `crawl` on a loopback fake site (`healthy`), `--json`/`--markdown` | exit 0; `out.json` schema 1.23, `grouping` on every page, release gate PASS |
| full suite, ruff (not installed), Linux/Windows, live runs | NOT RUN |

## v0.3 stage 3b: page importance fixes (2026-11-03, DECISIONS 298)

**Changed:** STR-3 `page_kind` takes `/collections/<c>/products/<p>` (also after a language folder) for a `product`, not
a listing (`checks/structure.nested_product`). Page grouping (method 2): a page whose canonical names another same-site
address is its alias; links to it, and its own links, count for the canonical, and a canonical not read but ending in
the same item is scored from its aliases (`page_grouping.canonical_pages`); policy pages linked only from footers or a
sitewide block are capped at 35; `importance_rank` breaks ties by body links in, products listed, sitemap order, crawl
order (never the address); `citable_content` on blog and article pages (no score change). No schema bump: 1.23 is not
pushed and the new keys are inside free-form objects. `tools/page_groups_saved.py` lists in rank order with the
canonicals. Tests: `tests/test_page_groups.py` 9 -> 15; `docs/FIXTURE-MATRIX.md` regenerated.

**STR-3 before/after, saved audits offline:** nihan 323 pages category -> product, 1,322 `page_types` labels on 25
findings; no finding, severity or confidence changes; release gate PASS before and after. adile, enpara: no change.

**Importance after, saved audits offline** (`~/.maya-audit/web` untouched, byte-compared):

| Audit | Aliases / canonicals scored unread | Products (not capped) | Policies | Read pages whose importance changed |
|---|---|---|---|---|
| nihan | 329 / 283 | 285 at 24-52 (TR 28-52 median 40; EN 24-35 median 33); before: 8 at 28-46 | 6 at 35 (were 53/41) | 81 (`/en` half -1 or -2, policies) |
| adile | 0 / 0 | none | 3 newly capped at 35 (74, 74, 54); `/kvkk` 56 (one body link) | 3 |
| enpara | 0 / 0 | none | none | 0 |

**Verification** (working tree on `f338bb5`, macOS, Python 3.13.1; no .env, no providers, no live requests):

| Command | Result |
|---|---|
| `pytest -q -rfE -p no:cacheprovider -m "not slow and not timing"` (fast suite) | `2583 passed, 4 skipped, 132 deselected, 1 warning in 972.83s (0:16:12)` |
| `pytest -q -rfEs -p no:cacheprovider` (full suite) | `1 failed, 2714 passed, 4 skipped, 1 warning in 1313.23s (0:21:53)`: `test_fixture_matrix` (generated matrix out of date after the new tests); regenerated, then `tests/test_fixture_matrix.py`: `3 passed` |
| `tests/test_page_groups.py` + the 7 other `page_kind` test files | `197 passed` |
| `python3.11 -m compileall` (changed files) | OK |
| CLI `crawl` on a loopback fake site (`healthy`) | exit 0; schema 1.23, `page_grouping.method_version` 2, `grouping` on every page, release gate PASS |
| Linux/Windows, live runs | NOT RUN |

**Before the push (2026-11-03, on `ecad113`):**

| Check | Result |
|---|---|
| `git status` | clean; `docs/FIXTURE-MATRIX.md` was in `ecad113` |
| full suite again, `pytest -q -rfEs -p no:cacheprovider` | `2715 passed, 4 skipped, 1 warning in 1318.67s (0:21:58)` |
| ruff: in CI (`ci.yml`, `full.yml`) as `ruff check --select E9,F821,F841 maya_audit maya_audit_web maya_audit_web_lite.py`; installed in `.venv` (0.17.3, dev only) | CI rule set: `All checks passed!` on the CI paths and on the changed files. Ruff's wider default rules: 9 style notes in the new files (import order, an unused `noqa`, `sorted()[0]`), none a defect; not changed |
| Canonicals scored but not read change no page count (nihan; saved report filled with grouping by `f338bb5` vs by `ecad113` + the STR-3 relabel; isolated copies of the web database and the audit folder; each rendered with its own code; no network) | Identical before/after: `crawl.pages` 500; `page_counts` {pages_checked 500, redirects 0}; coverage `readable_unique_urls` 500 and the Markdown line "**Pages read:** 500 (via Firecrawl)"; summary "500 pages checked. 27 parts could not be checked.", counts (28 problems, 20 notes, S3 5, S4 23, Info 20, findings 48, discovered 23001, not fetched 22499); 48 findings, 3560 affected addresses; gate PASS, no violations; web summary, practical, action plan, findings, Markdown, print and full print: identical (timestamps aside); web PDF 13 pages, text identical; Pro client report: `data.json` identical but for source paths and the report digest, HTML identical, PDF 9 pages text identical, address CSV (434 lines) byte-identical. Only `page_grouping.canonical_pages` differs: 0 -> 283 |

**Pushed** `762ac12..630815a` to withmaya/seo-audit `main` (2026-11-03). CI `maya-audit` run
[41584039938](https://github.com/withmaya/seo-audit/actions/runs/41584039938): **success**; job `fast` 17m41s (05:27:43 to
05:45:24 UTC), of which the "Fast tests" step 17m00s. The run before (`762ac12`) was 17m59s (step 17m11s); the one before
that (`c22a0b0`, 2026-10-30) 9m44s (step 8m48s); setup (install, Chromium) is under a minute in all three.

**Why the fast job doubled** (measured locally, `--durations=40` on the fast suite, `970.17s`): one fixture setup,
`tests/test_coverage_phase2.py::measured` (module scope, 11 benchmark scenarios run before and after), takes **589.24s**.
`slow_tests.txt` lists `test_benchmark_more_of_the_right_pages_are_read_where_it_was_possible` as slow but not
`test_benchmark_healthy_sites_are_unchanged_and_gain_no_findings`, which uses the same fixture, so the fast suite still
builds it. The fixture took 23.3s on `c22a0b0` and 23.1s on `1dbdf3d` (stage 2), and 589s from `762ac12` on (DECISIONS
295/296: Firecrawl's own pace, the timeout retry): those waits run in real time in the benchmark's made-up runs. The next
slowest fast-suite setup is 43.9s. Not changed here (a fix is to list that second test as slow, or to make the benchmark's
pace and retry waits use a fake clock; owner's choice).

## v0.3 speed follow-up (2026-11-03, DECISIONS 299; pushed as `8015f0d`)

**CI of the status commit `54e85a5`** (run 41585995041): **failed**, by chance: `test_counts_and_shared_elements.py`
looked for "55" anywhere in the counts and met a measured `0.055` s. Fixed here (55 as a whole number). Status-only
commits are no longer pushed (Owner).

**Changed:** (1) one clock for every wait (`maya_audit/clock.py`, 21 modules; the headless browser keeps the system
clock); the coverage benchmark and the w4b fixture run under a fake clock, both still in the fast suite. (2) Firecrawl
starts at Maya's first 429 (start page or one of the first 3 page requests), before the Retry-After wait, from a copy of
what the crawl knew; the web app makes the early reader for the blocked-site reader too. (3) A large sitemap index is
read in part: one file of each family (folder kept) first, then stop at page cap + sitemap check sample; the
discovered count says "(partial ...)". (4) The outcome reason under the "Maya's crawler was blocked (429 on pages); read
through Firecrawl: N pages" label no longer repeats it (card, print, PDF; English and Turkish); the status summary no
longer says the Firecrawl count twice. (5) Firecrawl's `rawHtml` is rendered HTML (nihan: median +36% against Maya's
raw copy, 499 pages); RND-6 measured on it says "(rendered HTML via Firecrawl, not comparable with raw size)" in every
title, with a note and `evidence.html_measured`. Tests: new `tests/test_v03_speed_followup.py` (11).

**The 10 slowest fast-suite tests** (`pytest -m "not slow and not timing" --durations=10`, this Mac):

| Before (`54e85a5`, fast suite 970.17 s) | | After (fast suite 409.58 s) | |
|---|---|---|---|
| 589.24 s | coverage_phase2 benchmark (setup) | 46.36 s | brand_neutral saas_spa_rendered (setup, real browser) |
| 43.88 s | brand_neutral saas_spa_rendered (setup) | 28.74 s | rnd_scenarios render sample (setup, real browser) |
| 27.27 s | rnd_scenarios render sample (setup) | 24.52 s | coverage_phase2 benchmark (setup, fake clock) |
| 12.24 s | w4b concise report [tr] (setup) | 3.59 s | prf_scenarios intermittent timeout (setup) |
| 3.52 s | prf_scenarios intermittent timeout (setup) | 2.20 s | web_firecrawl challenged site result page |
| 1.69 s | nine_corrections large h1 | 2.08 s | nine_corrections large h1 |
| 1.56 s | web_firecrawl challenged site result page | 1.38 s | w4b concise report [tr] (setup, fake clock) |
| 1.13 s | review_fixes idx8 | 1.20 s | dataforseo_backlinks 6b |
| 1.06 s | web_app daily limit | 1.19 s | web_app daily limit |
| 1.03 s | gx3_length concise print (setup) | 1.16 s | web_app one audit at a time |

The two remaining long setups run a real headless browser (Playwright): their time is the browser's, not a wait.

**Saved nihan Quick 50 (`50473193`, 2 Nov), offline** (isolated copies; `~/.maya-audit/web` untouched): rendered with
`54e85a5` and with this tree, every web output compared. Only the outcome reason under the label changed (card, print,
full print, PDF): "Maya's crawler was blocked (429 on pages); read through Firecrawl: 50 pages. 18192 more discovered
URLs remain unchecked ..." instead of saying the first part twice. Markdown, practical view, action plan, findings and
counts: identical. A saved report keeps its RND-6 titles, sitemap count and status summary (they are written when an
audit runs).

**nihan Quick 50, estimated** (2 Nov timeline: preflight 10 s, sitemaps 30 s, crawl 61 s = the homepage's 60 s
Retry-After, access + index 13 s, llms links 30 s, robots.txt re-sample wait 107 s, then Firecrawl 108 s; 349.5 s of
steps, ~6.0 min wall, Firecrawl shown at "1 of 50" until it started): sitemaps ~14 s (12 requests, not 26); Firecrawl
starts at the homepage's 429 (~25 s) and ends ~135 s; Maya's steps end with the robots.txt re-sample (due 240 s after
the first robots.txt request, ~250 s), as before. **About 4.2 min**, set now by the robots.txt re-sample wait. Not
measured live.

**Verification** (working tree on `54e85a5`, macOS, Python 3.13.1; no .env, no providers, no live requests):

| Command | Result |
|---|---|
| fast suite (local fast-job time), `pytest -q -rfE -p no:cacheprovider -m "not slow and not timing" --durations=10` | `3 failed, 2591 passed, 4 skipped, 131 deselected, 1 warning in 409.58s (0:06:49)`: the RND-6 note in the check summary (no Turkish; removed from the summary) and `maya_audit/rule_ids.json` out of date (regenerated); then the three files: `50 passed` |
| full suite, `pytest -q -rfEs -p no:cacheprovider` | first `2 failed, 2723 passed, 4 skipped, 1 warning in 762.26s`: `docs/FIXTURE-MATRIX.md` out of date (regenerated), and a sitemap-check test whose three numbered files are one family (files made smaller; families are now also spread first, last, middle); then `2725 passed, 4 skipped, 1 warning in 754.15s (0:12:34)` |
| `ruff check --select E9,F821,F841` (CI's) | `All checks passed!` |
| `python3.11 -m compileall` | OK |
| Linux/Windows, live runs | NOT RUN |

**CI of `8015f0d`** (run [41599353639](https://github.com/withmaya/seo-audit/actions/runs/41599353639)): **success**; whole run 9m51s (07:53:45 to 08:03:36 UTC), "Fast tests" step 9m05s (17m11s on the two runs before; 8m48s on 2026-10-30).

## v0.3 stage 6: client report — priority, 10 pages, 15 cards, XLSX appendix, gate (2026-11-03, DECISIONS 300)

**Changed:** one client selection for the web concise PDF and the `maya-audit-pro` report (`maya_audit/client_selection.py`):
root-cause groups (one rule = one card, an example per language), priority = severity × confidence × reach ×
business (1.0), placement into cards (≤15, every Blocker/High kept), "Teyit edin", notes, Maya's own limits
(coverage), appendix-only. XLSX appendix (`client_appendix.py`, stdlib `xlsx.py`): web `downloads/xlsx`, pro
`<name>-ek.xlsx`. Gate RG-15 (>10 pages), RG-16 (>15 cards), RG-17 (appendix missing a finding), all hard. Web concise
rewritten (summary, coverage and own limits, search/performance sample, cards, "Teyit edin", key pages scorecard, plan
and quick wins, appendix pointer; max 10 pages). Pro: cards in priority order, a last page "Kapsam ve ek", quick wins
on the plan page, `--confirm`/`--reject` for the owner's manual checks. Nihan text fixes: no "kontrol canlı sitelerde
henüz doğrulanmadı" on client cards; Shopify-aware IDX-5 lastmod steps (`steps_by_platform`, RG-11 checks the
platform); new ACC-3 rule `acc3.utility_indexable` (search/cart pages without noindex, Low); empty columns dropped;
numbers labelled. Findings seen only in Firecrawl's copy are marked (`double_reading.py`: engine and offline
reassessment) and go to "Teyit edin"; so do 403/429 to a spoofed Googlebot. Skill `SKILL.md` and
`references/veri_sozlesmesi.md` updated. Tests: new `tests/test_v03_client_report.py` (23); 13 existing tests moved to
the new contract (every finding ID in the appendix, not in the PDF; summary heading; 10-page cap); 5 pro-skill tests.

**nihan `b3198942`, rebuilt offline** (sockets refused; copies in a temp folder; `~/.maya-audit/web` untouched).
`tools/reassess_saved.py` → 13 changes: ACC-4 S3 → Info and RND-3 maybe S3 → S4 (290); STR-5 removed (290, category
titles); 9 findings marked Firecrawl-only (IDX-8, STR-3, STR-9, STR-12, STR-19 ×1, TSEO-1 ×4); ACC-3
`acc3.utility_indexable` added (4 pages: `/search`, `/cart`, `/en/search`, `/en/cart`); gate PASS. Outputs in
`reviews/2026-11-03/nihan/` (git-ignored).

| Output | Before (stage 3b) | After |
|---|---|---|
| Web concise PDF (tr, en) | 13 pages | **5 pages**, 10 cards, gate PASS |
| Pro report (tr) | 9 pages, ~20 cards | **7 pages**, 12 cards (10 problem + 2 Not), gate PASS, 0 overflow |
| Appendix | CSV of card addresses (434 lines) | XLSX: 48 findings, 3,065 address rows, key pages, coverage, method |

48 findings → 32 groups: 10 cards, 10 "Teyit edin", 12 note groups, 0 appendix-only, 0 own-limit findings (the page cap
and 23 not-assessed parts are coverage lines).

| Card | Score | Severity | Finding(s) |
|---|---|---|---|
| 1 | 25.0 | Low | STR-16 3 shared meta descriptions on 26 pages |
| 2 | 25.0 | Low | RND-6 main content after 500 KB on 494 pages |
| 3 | 25.0 | Low | TSEO-1 47 heading level jumps |
| 4 | 25.0 | Low | STR-1 6 shared titles on 12 pages |
| 5 | 25.0 | Low | RND-6 192 pages above 1000 KB |
| 6 | 17.5 | Low | STR-2 8 pages without `<h1>` |
| 7 | 14.4 | Medium | RND-6 homepage HTML 885 KB |
| 8 | 11.7 | Low | STR-14 3 links without text |
| 9 | 8.0 | Low | IDX-5 16 sitemaps with one lastmod (Shopify steps) |
| 10 | 4.0 | Low | ACC-3 4 search/cart pages indexable |

"Teyit edin": STR-12 47 `/en` pages mostly Turkish (Medium, Firecrawl-only, 30.0); STR-19 ×3, TSEO-1 shared ×5, IDX-8,
STR-9, STR-3 FAQ (Firecrawl-only); STR-14 shared ×4, RND-3 ×2 (unverified check); ACC-4 429 to a spoofed Googlebot.
Moved off the old cards: those 10 groups, and STR-5 (removed by 290). The owner's manual check of nihan's `/en` pages
was not given (placeholder in the request): STR-12 stays in "Teyit edin" until `--confirm str12.language` or `--reject`.

**Verification** (working tree on `a25fe76`, macOS, Python 3.13.1; no .env, no providers, no live requests):

| Command | Result |
|---|---|
| fast suite, `pytest -q -rfE -p no:cacheprovider -m "not slow and not timing"` | first run `20 failed, 2597 passed` (old concise contract, two title corpora); after the fixes `2617 passed, 4 skipped, 131 deselected, 1 warning in 409.77s (0:06:49)` |
| full suite, `pytest -q -rfEs -p no:cacheprovider` | first run `3 failed, 2745 passed` (concise contract); after the fixes `2748 passed, 4 skipped, 1 warning in 750.12s (0:12:30)` (skips: 2 wheel builds, live-run examples, real-site corpus) |
| pro skill tests, `pytest -q .agents/skills/maya-audit-pro/tests` (outside `testpaths`) | `56 passed` |
| `ruff check --select E9,F821,F841` (CI paths) | `All checks passed!` (it caught a 3.12-only f-string, fixed) |
| `python3.11 -m compileall` (maya_audit, maya_audit_web, pro scripts) | OK |
| `docs/FIXTURE-MATRIX.md` | regenerated |
| Linux/Windows, live runs | NOT RUN |

**Not done:** the third client report (`maya-audit-rapor`, `client_reports`) keeps its 50-page limit; the web UI has no
button for the XLSX (the route and the companion line exist); manual confirmations are a pro-report flag only (the web
app has none); reach cap 5 makes broad Low findings tie at 25.0 (ties broken by severity, then report order).

## Report-quality rules for every audit (2026-11-03, DECISIONS 301)

**Changed:** (1) a per-audit review file for manual checks (`maya_audit/manual_review.py`; `review.json` beside the
report; web "Teyit edin" panel with Confirmed/Rejected buttons, `GET/POST /audits/{id}/review`; `build_data.py
--confirm/--reject --by --seen [--note] [--review]`); a confirmed finding is "measured, confirmed by manual check" with
its note on the card. (2) Language-mismatch findings name the page regions in the other language
(`maya_audit/language_regions.py`, `evidence.regions`) and their advice follows them, with Shopify Translate & Adapt /
WordPress WPML-Polylang first. (3) Cards by severity band, then priority; reach = 1 + ln(1 + importance / 100), at most
10; scores kept to 3 decimals. (4) Merge table `client_selection.MERGE_GROUPS` (8 groups, listed in DECISIONS 301): one
card, one title, one fix, worst pages as examples. (5) Every count from `select()["counts"]`; a test compares the web
PDF, pro data, XLSX and Markdown. (7) XLSX button on the results page. Pro: steps of merged cards de-duplicated and kept
to three when a card already shows two lines above them. Tests: `tests/test_v03_client_report.py` 23 -> 31.

**(6) maya-audit-rapor — recommendation: retire it.** It is the third client report (`maya_audit/client_reporting/`,
`maya_audit_web/client_reports.py`, the web "Client report" workspace, the `maya-audit-rapor` skill; about 2,170 lines
and 14 test files). It has its own grouping, score and wording, so it would need the selection rewired into all of them
to obey the 10-page/15-card rule, and it would then duplicate the pro report. Its one feature the others lack, a
reviewer's sign-off (draft → reviewed), is covered by the review file now. Suggested path: hide the web button and
mark the skill deprecated now, delete with its tests one release later. Not changed here; owner's decision.

**nihan, adile, enpara rebuilt offline** (copies in a temp folder; `~/.maya-audit/web` untouched; each saved report
through `tools/reassess_saved.py`, then the web concise PDF (tr) through an isolated copy of the web app, the pro report
(tr, draft: model fields unfilled; page and card counts do not depend on them). Before = commit `5f6d21f` (stage 6) run
the same way; after = this tree, with nihan's review file (STR-12 confirmed by the owner).

| Audit | | Web PDF pages | Web cards | Pro pages | Pro cards | Teyit edin | Groups |
|---|---|---|---|---|---|---|---|
| nihan | before | 5 | 10 | 7 | 12 | 10 | 32 |
| nihan | after | 5 | 8 | 7 | 10 | 9 | 29 |
| adile | before | 4 | 4 | 6 | 7 | 14 | 39 |
| adile | after | 4 | 4 | 6 | 7 | 14 | 39 |
| enpara | before | 4 | 5 | 6 | 8 | 10 | 30 |
| enpara | after | 4 | 5 | 6 | 8 | 10 | 30 |

Top cards (score, severity, cause):

- nihan before: 25.0 Low STR-16 · 25.0 Low RND-6 late · 25.0 Low TSEO-1 · 25.0 Low STR-1 · 25.0 Low RND-6 large · 17.5
  Low STR-2 · 14.4 Medium RND-6 homepage · 11.7 Low STR-14 · 8.0 Low IDX-5 · 4.0 Low ACC-3.
- nihan after: 93.4 Medium html_weight (3 RND-6) · 67.3 Medium language_mismatch (STR-12, confirmed by manual check;
  menu 39%, item titles 70%, body 98% in Turkish; Translate & Adapt) · 22.9 Low heading_levels · 19.4 Low template_meta
  (STR-16 + STR-1) · 12.5 Low STR-2 no `<h1>` · 11.0 Low links_without_text · 9.8 Low sitemap_lastmod (Shopify steps) ·
  7.9 Low ACC-3 search/cart indexable.
- adile before: 17.9 Low TSEO-1 · 2.3 Low STR-14 · 1.5 Medium IDX-5 failed files · 0.6 Low STR-2 empty `<h1>`.
- adile after: 16.4 Medium IDX-5 failed files · 12.6 Low heading_levels · 6.9 Low links_without_text · 5.6 Low STR-2.
- enpara before: 73.6 High TSEO-1 early `</head>` · 15.0 Low STR-5 · 10.8 Low STR-14 · 5.9 Low STR-2 · 1.0 Low IDX-2.
- enpara after: 81.8 High TSEO-1 early `</head>` · 12.4 Low STR-5 · 10.8 Low links_without_text · 8.9 Low STR-2 · 5.9
  Low IDX-2.

**Verification** (working tree on `5f6d21f`, macOS, Python 3.13.1; no .env, no providers, no live requests):

| Command | Result |
|---|---|
| fast suite, `pytest -q -rfE -p no:cacheprovider -m "not slow and not timing"` | `2625 passed, 4 skipped, 131 deselected, 1 warning in 410.89s (0:06:50)` |
| full suite, `pytest -q -rfEs -p no:cacheprovider` | `2756 passed, 4 skipped, 1 warning in 748.31s (0:12:28)` |
| pro skill tests (outside `testpaths`) | `56 passed` |
| `ruff check --select E9,F821,F841` (CI paths + pro scripts) | `All checks passed!` (caught a 3.12-only f-string in `render.py`, fixed) |
| `python3.11 -m compileall`, `node` syntax check of `static/app.js` | OK |
| Linux/Windows, live runs, the web UI in a real browser | NOT RUN |

Final nihan pro report (fields filled, validated, gate PASS, no overflow): 7 pages, 10 cards (8 problem + 2 Not), XLSX
appendix with all 48 findings. Outputs: `reviews/2026-11-03/rebuild-301/` (git-ignored).

## The checklist's quick checks, Product fields, Firecrawl pages' importance (DECISIONS 304, 2026-11-03)

Global rules; nihan, adile and enpara are test cases only. What changed: (1) when Maya's crawler is blocked, Firecrawl's
pages are grouped while their links are in memory (`crawl.reader_page_grouping`), so key pages and reach work for a
blocked site; (2) ten new rules (`maya_audit/checks/quick_rules.py`): SEO-061 links to an alias, SEO-099 empty
collections, decomposed characters in addresses, SEO-031 noindex behind robots.txt, SEO-046 next page not linked,
SEO-093 product with no category link, SEO-036 image/video sitemap, SEO-067 unclear slugs, SEO-078 article author,
SEO-097 GTIN/MPN; (3) the key Product fields in report.json. Schema 1.24. Details in DECISIONS 304.

**nihan, adile, enpara rebuilt offline** (copies in the scratchpad; `~/.maya-audit/web` untouched, sha1 compared;
sockets refused). Before = commit `aa68c0b` exported with `git archive`, after = this tree, both through
`tools/reassess_saved.py`, then `client_selection.select` (nihan with its review file: STR-12 confirmed by the owner).
PDFs were not rendered. Outputs: `reviews/2026-11-03/rebuild-304/` (git-ignored).

| Audit | New finding | Severity, confidence | Count | Placement |
|---|---|---|---|---|
| nihan | TSEO-1 decomposed character (`tseo1.url_decomposed`) | Low, verified | 1,689 addresses (68 read, 704 in the sitemap) | card 3 (30.9) |
| nihan | IDX-6 links to an alias (`idx6.alias_links`) | Low, verified | 1,112 links on 141 pages, to 324 aliases (`/collections/x/products/y`) | card 4 (28.5) |
| nihan | STR-15 empty or near-empty collections (`str15.empty_collections`) | Low, estimated, LG-102 | 7 collection pages, TR and EN (perfume: 2 products; outlet sweater, jumpsuit, t-shirt: 1-2) | Teyit edin |
| nihan | IDX-7 product with no category link (`idx7.product_no_category`) | Low, estimated, LG-102 | 1 product (`/products/aksesuar-detayli-kap-lacivert-1`, no breadcrumb) | Teyit edin |
| adile | none | | | |
| enpara | none | | | |

No finding, measured: nihan SEO-097 (331 product pages; every one has an MPN, a GTIN on each offer and a brand), SEO-078
(nihan's 4 and adile's 4 articles name an author), SEO-046 (collections link `?page=2`), SEO-067. Not assessed offline,
said in `generation.analysis`: SEO-031 (no robots.txt text in a saved report), SEO-036 (no sitemap media counts before
1.24). Release gate PASS -> PASS on all three.

Top cards: nihan changes (8 -> 10 cards; confirm 9 -> 11): before RND-6 html_weight 93.4 · STR-12 67.3 · TSEO-1
heading_levels 22.9 · template_meta 19.4 · STR-2 12.5 · STR-14 11.0 · IDX-5 9.8 · ACC-3 7.9; after the same with the
two new Low cards at 3 and 4 (no card dropped; both Medium cards stay first). The decomposed-address card ranks above
the heading jumps by reach: 1,689 addresses, each unscored one counted 10 (DECISIONS 300 (2)). adile and enpara: no
change.

**Checklist mapping** (`reviews/checklist/mapping.xlsx`, git-ignored): done 101 -> 109 of 165 (61% -> 66%), full 53 ->
57 (32% -> 35%). Full: SEO-061, -078, -097, -099. Partial: SEO-031, -036, -046, -067, -093 (what is missing is in the
row). Missing-automatable 17 -> 9.

**Verification** (working tree on `aa68c0b`, macOS, Python 3.13.1; no .env, no providers, no live requests):

| Command | Result |
|---|---|
| fast suite, `pytest -q -rfE -p no:cacheprovider -m "not slow and not timing"` | `2644 passed, 4 skipped, 131 deselected, 1 warning in 494.90s (0:08:14)` (the first run failed 1: the decomposed-address fix began with "Rename", not an action verb the action sentence knows; reworded to "Change") |
| full suite, `pytest -q -rfEs -p no:cacheprovider` | `2775 passed, 4 skipped, 1 warning in 783.84s (0:13:03)` (skips: 2 wheel builds without setuptools, live-run examples not in git, real-site corpus outside the repo) |
| pro skill tests (outside `testpaths`) | `56 passed` |
| `ruff check --isolated --select E9,F821,F841` (maya_audit, maya_audit_web, tools, new test) | `All checks passed!` |
| `python3.11 -m compileall` | OK |
| CLI `crawl` on a loopback fake site (`healthy`) | exit 0; schema 1.24, gate PASS, `image_entries`/`video_entries` on sitemap records, `grouping` on 5/5 pages |
| Linux/Windows, live runs, PDFs of the rebuilt audits | NOT RUN |

## Report fixes and nihan pro v3 (DECISIONS 305, 2026-11-03)

What changed: percent-escape case is one address (`%cc` = `%CC`) for page identity, grouping and importance; reach
counts only pages that were read (unread addresses counted apart); one count of the parts not assessed across every
client output; merged cards keep their title and whole scope in the pro summary, findings table and action plan;
evidence tables print the measured value and drop empty columns.

**Card #3 changes position.** nihan, offline (same method as DECISIONS 304's rebuild): the decomposed-address card
(1,689 addresses, 68 read) goes from 30.9, 3rd, to 18.8, 6th; the alias-links card moves up to 3rd. adile and enpara:
same cards in the same order (adile's IDX-5 failed-files card 16.4 -> 25.4: a finding on sitemap files now takes the
homepage's reach instead of 10 per file).

**nihan pro report v3** (`reviews/2026-11-03/nihan-v3/`, git-ignored; built from the offline-reassessed b3198942 report
with the maya-audit-pro skill, Turkish, review file with the owner's STR-12 confirmation; 19 model fields written,
`validate_data.py` 0 warnings, release gate PASS): 7 pages, 12 cards (10 problem, 2 Not).

| # | Card | Severity | Score |
|---|---|---|---|
| 1 | Sayfa HTML'ini hafifletin (3 RND-6, merged) | Orta | 93,5 |
| 2 | Belirtilen dili içerikle uyumlu hâle getirin (STR-12, confirmed by the owner) | Orta | 67,3 |
| 3 | İç bağlantıları kanonik adrese yönlendirin (IDX-6, new) | Düşük | 28,5 |
| 4 | Atlanan başlık seviyelerini düzeltin (TSEO-1) | Düşük | 22,9 |
| 5 | Ortak başlık ve açıklamaları ayırın (STR-16 + STR-1) | Düşük | 19,4 |
| 6 | Adresleri birleşik harflerle yeniden yazın (TSEO-1, new) | Düşük | 18,8 |
| 7 | Ana başlığı olmayan sayfalara tek bir ana başlık ekleyin (STR-2) | Düşük | 12,5 |
| 8 | Metni olmayan bağlantılara ad verin (STR-14) | Düşük | 11,0 |
| 9 | Site haritası lastmod tarihlerini gerçek düzenleme tarihinden alın (IDX-5) | Düşük | 8,4 |
| 10 | Site içi arama ve sepet sayfalarını dizin dışında tutun (ACC-3) | Düşük | 7,9 |
| 11 | Soru başlıklarını ve menü dilini düzeltin | Not | — |
| 12 | Sayfa yüklemesini ve etiketleri toparlayın | Not | — |

Pages checked as images: 1 (priorities "Sayfa HTML ağırlığı · 494 sayfa", coverage box 25), 2 (merged row "Sayfa
HTML'ini hafifletin · 494 sayfa"; evidence sample ADRES / ÖLÇÜLEN / SINIR: "/ · 885 KB · 500 KB"), 4, 5 (the two new
cards), 7 ("Değerlendirilemeyen 25 kısım"; "Teyit edin" lists the near-empty collections and the product without a
category link). Page 3's provenance line says 25 too (text extracted).

**Verification** (working tree on `5219b38`, macOS, Python 3.13.1; no .env, no providers, no live requests):

| Command | Result |
|---|---|
| fast suite | `2651 passed, 4 skipped, 131 deselected, 1 warning in 467.87s (0:07:47)` |
| full suite | `1 failed, 2781 passed, 4 skipped, 1 warning in 792.55s (0:13:12)`: the failure was `test_fixture_matrix.py::test_the_matrix_file_matches_the_tests` (the generated `docs/FIXTURE-MATRIX.md` was stale after the new test file); regenerated with `scripts/fixture_matrix.py`, that file's tests then `3 passed`; the full suite was not run again end to end |
| pro skill tests | `56 passed` |
| `ruff check --isolated --select E9,F821,F841`, `python3.11 -m compileall` | `All checks passed!`; compile OK |
| Linux/Windows, live runs | NOT RUN |

## Client-report polish and nihan pro v4 (DECISIONS 306, 2026-11-03)

What changed: rename-and-redirect fixes are at least "Orta" effort and never a quick win; "handle" explained in plain
Turkish; "Teyit edin" reasons in client words with no vendor name (technical reason in the XLSX only); findings table
rows phrased as findings; Turkish XLSX fully Turkish (coverage explanations, page types, manual-check result); the saved
copies row hidden at 0.

**nihan pro v4** (`reviews/2026-11-03/nihan-v4/`, git-ignored; offline-reassessed b3198942, Turkish, STR-12
confirmation kept; `validate_data.py` 0 warnings, gate PASS): 7 pages, 12 cards, same order and scores as v3. Card 6
(decomposed addresses) is "Orta"; quick wins 03, 04, 05, 07. PDF text: "Firecrawl" 0, "gerçek sitelerde" 0, "Kayıtlı
kopyadan" 0. XLSX: no engine English (the only English is the owner's own manual-check note).

**Verification** (working tree on `3c9975f`, macOS, Python 3.13.1; no .env, no providers, no live requests):

| Command | Result |
|---|---|
| fast suite | `2655 passed, 4 skipped, 131 deselected, 1 warning in 436.63s (0:07:16)` |
| full suite | `2786 passed, 4 skipped, 1 warning in 808.27s (0:13:28)` |
| pro skill tests | `56 passed` |
| `ruff check --isolated --select E9,F821,F841`, `python3.11 -m compileall` | `All checks passed!`; compile OK |
| CI on push | see the commit's GitHub Actions run |

## One place for reports: the team report from the web app (DECISIONS 307, 2026-11-04)

What changed: the pro report's template (build, validate, render), labels, logo and font moved from the skill into
`maya_audit_web/team_report/`; the skill's scripts are thin entries to the same modules. A text library
(`texts/tr.json`, `texts/en.json`: all 299 rule ids, 8 merge groups, 27 Note-card topics, page-1 templates, plain
reasons) fills the 19 fields the model wrote and the 2 it shortened, so the web app prints the report with no model:
results page "Ekip raporu" (TR/EN switch, TR first; "Ekip raporu (PDF)" = `GET /downloads/team`, "Ek (XLSX)" =
`/downloads/xlsx`, now the skill's own appendix function). The validator and release gate run on every download; a
blocked report answers 422 with the reasons in plain words. "Teyit edin" Confirm/Reject counts on the next download. The
skill may still polish wording; `_locked` refuses a changed severity, count, order or address.

**nihan through the web path** (`tools/team_report_parity.py` on the v4 source with the owner's STR-12 confirmation,
Turkish, isolated web folder and analysis entry in `reviews/2026-11-04/nihan-web/`, git-ignored; `~/.maya-audit/web`
only read for the manifest format, not changed): web `GET /downloads/team` HTTP 200, gate PASS, 7 pages
(`web-nihan.pdf`, `web-nihan-ek.xlsx`); skill path 7 pages; every page the same pixels (PNG byte-identical, pages 1-7);
XLSX the same in every sheet and cell. Against the approved v4: the same 12 cards, order and severities; 17 of 69 text
fields worded differently (`parity.md` lists them: the library's generic wording where v4 named the site, e.g. "Dil
sürümlerindeki çeviri" for "İngilizce sayfaların çevirisi"). Pages 1 and 7 checked as images.

**Verification** (working tree on `844b14f`, macOS, Python 3.13.1; no .env, no providers, no live requests):

| Command | Result |
|---|---|
| fast suite, `pytest -q -rfE -p no:cacheprovider -m "not slow and not timing"` | `2671 passed, 4 skipped, 132 deselected, 1 warning in 430.01s (0:07:10)` |
| full suite, `pytest -q -rfEs -p no:cacheprovider` | `2803 passed, 4 skipped, 1 warning in 790.52s (0:13:10)` (skips: 2 wheel builds without setuptools, live-run examples not in git, real-site corpus outside the repo) |
| pro skill tests (`unittest discover -s .agents/skills/maya-audit-pro/tests`) | `Ran 56 tests` `OK` |
| `tests/test_team_report.py` | `17 passed` (one slow: web vs skill PNGs, a manual check rebuilding the report) |
| `ruff check --isolated --select E9,F821,F841`, `python3.11 -m compileall` | `All checks passed!`; compile OK |
| Web app restarted on port 8770, browser click-through | NOT RUN (the owner's process; restart needed to load the new code) |
| Linux/Windows, live runs, wheel build | NOT RUN |

## Web team report fixes: current engine first, one language per click (DECISIONS 308, 2026-11-04)

What changed: the team report (web app and pro skill, one `build_from_files`) is built from the saved audit
re-evaluated with the current engine (`team_report/current.py`: the `reassess_saved.py` steps on a copy in
`<audit>/current-engine/`, made again when the source or the engine changes; report.json never written). The line
"Güncel motorla yeniden değerlendirildi (Maya Audit 0.2.8 · şema 1.24 · <commit>, <date>)" is in the PDF's provenance
box and under the web buttons. "Teyit edin", the XLSX appendix and its gate read the same copy; the one review file is
the audit's `artifacts/review.json`. TR/EN: the server always built the asked language; the script-started download
20-50 s after the click was blocked by the browser after the first file, and the XLSX had one name for both. Now
`GET /team-report?lang=` builds, then the page shows two ordinary links named `…-ekip-raporu-tr.pdf` /
`…-team-report-en.pdf`, `…-ek-tr.xlsx` / `…-appendix-en.xlsx`. "İndir" is "Diğer indirmeler", below the team report;
its PDF is "Kısa teknik özet (PDF, <dil>)"; its XLSX button is gone.

**Where confirmations live (nihan):** the owner's STR-12 confirmation is only in the skill-path copies
(`reviews/2026-11-03/nihan-v4/source/review.json`, v3, rebuild-301). The web audit
`~/.maya-audit/web/audits/b3198942…/artifacts/` has no `review.json` (not changed here), so the web app lists STR-12
under "Teyit edin" until it is confirmed there.

**nihan through the real web routes** (`tools/team_report_parity.py` on a copy of the original b3198942 artifacts and
evidence; isolated web folder; `reviews/2026-11-04/nihan-web-v2/`, git-ignored):

| Run | Web route result | Web vs skill | Cards |
|---|---|---|---|
| TR, v4 review file (STR-12 confirmed) | `GET /team-report?lang=tr` 200, gate PASS, 7 pages, `…-ekip-raporu-tr.pdf`, `…-ek-tr.xlsx` | pages 1-7 same pixels; XLSX same | 12, the same cards, order and severities as v4 (IDX-6 3rd, decomposed addresses 6th, no STR-5) |
| EN, v4 review file | `lang=en` 200, gate PASS, 7 pages, `…-team-report-en.pdf`, `…-appendix-en.xlsx` | pages 1-7 same pixels; XLSX same | the same 12 cards in English |
| TR, the web audit's own review state (no file) | 200, 7 pages | same | 11: v4's without STR-12 (left in "Teyit edin") |

Browser click-through (isolated server on port 8793 serving the copy, headless Chromium, Turkish interface): TR, EN,
TR again each gave that language's PDF and XLSX under their own names; the re-evaluation line shows under the links.
Page 3 (provenance box with the "Değerlendirme" line) and page 7 checked as images.

**Verification** (working tree on `5749501`, macOS, Python 3.13.1; no .env, no providers, no live requests):

| Command | Result |
|---|---|
| fast suite, `pytest -q -rfE -p no:cacheprovider -m "not slow and not timing"` | `2675 passed, 4 skipped, 133 deselected, 1 warning in 451.43s (0:07:31)` |
| full suite, `pytest -q -rfEs -p no:cacheprovider` | `2808 passed, 4 skipped, 1 warning in 828.74s (0:13:48)` (skips: 2 wheel builds without setuptools, live-run examples not in git, real-site corpus outside the repo) |
| pro skill tests (`unittest discover -s .agents/skills/maya-audit-pro/tests`) | `Ran 56 tests` `OK` |
| `tests/test_team_report.py` (slow included) | `22 passed` |
| `ruff check --isolated --select E9,F821,F841 .` | changed files clean; 4 F841 in test files not changed here (`test_oct18_corrections`, `test_real_run_fixes`, `test_review_fixes`, `test_run_clock`) |
| `python3.11 -m compileall` | OK |
| Owner's web app on port 8770 | NOT RUN (restart needed to load the new code) |
| Linux/Windows, live runs, wheel build | NOT RUN |

## Team report fixes for every audit (DECISIONS 309, 2026-11-05)

What changed: a web confirmation covers its whole "Teyit edin" group (and the skill's `--confirm`), names its finding
in the form and the save notice, and the next build shows the card with "Elle kontrol: <note>"; the review file is
`<audit>/artifacts/review.json`. Platform steps (Shopify "within: collection" and two more) moved to
`steps_by_platform`; the platform is also read from saved data (sitemap names, `/products/` + `/collections/`,
`/cdn/shop/`); key pages: main homepage first, every language homepage typed and listed, ranks 1..N; at most 2 Note
cards, after the problem cards; read-but-unscored pages count a neutral 50, never "Okunmayan"; RND-6 on Firecrawl's
HTML goes to "Teyit edin" ("işlenmiş HTML, karşılaştırılamaz"); low coverage (<10 pages or <20% of the plan) puts a
banner on PDF page 1 and the web results and blocks a client brief (`client_brief_allowed`); the history list shows
date and time, mode, pages read and reading path; plural-aware English labels, "JavaScript'e", "1 sayfa isteği",
"adres" when most addresses were unread, card-header IDs wrap.

**Found on nihan b3198942:** `~/.maya-audit/web/audits/b3198942…/artifacts/review.json` holds six saves of
ACC-4-17ea40ab (the Googlebot 429 row) with the STR-12 note, none of STR-12; the build read it correctly. Not changed.

**Rebuilt through the real web routes** (isolated copy of the web home, `create_app` + TestClient; GET /review,
POST /review, GET /team-report, both links; `reviews/2026-11-05/team-report-309/`, git-ignored):

| Audit | TR / EN | Cards | Key pages | Teyit edin (PDF) |
|---|---|---|---|---|
| nihan b3198942, review file as saved | 200, PASS, 7 p. / same | 11 (9 + 2 notes); IDX-6, ACC-3, IDX-5 with Shopify steps | 1 `/`, 2 `/en`, then collections | 10, STR-12 first |
| nihan b3198942, STR-12 confirmed via POST | 200, PASS, 7 p. / same | 12: STR-12 + STR-9 card 2 with the note | same | 9 |
| nihan 50473193 (Firecrawl-only) | 200, PASS, 6 p. / same | 5; IDX-5 Shopify; neutral-reach lines | empty (reader-only note) | 7, RND-6 "rendered HTML" |
| nihan efb50ee4 (1 page) | 200, PASS, 7 p. / same | 9 (8 + 1 note) | 1 `/` | 1 (ACC-9, "1 sayfa isteği"); low-coverage banner |
| moodist c581ff0a | 200, PASS, 8 p. / same | 13 (11 + 2 notes), no Shopify step | 1 `/tr/`, 2 `/ru/`, 3 `/ar/`, 4 `/en/`, then by importance | 6 |

**Verification** (working tree on `647fcbc`, macOS, Python 3.13.1; no .env, no providers, no live requests):

| Command | Result |
|---|---|
| fast suite, `pytest -q -rfE -p no:cacheprovider -m "not slow and not timing"` | `2697 passed, 4 skipped, 134 deselected, 1 warning in 439.15s (0:07:19)` |
| full suite, `pytest -q -rfEs -p no:cacheprovider` | `1 failed, 2830 passed, 4 skipped, 1 warning in 810.38s (0:13:30)`: `test_fixture_matrix` (the generated docs/FIXTURE-MATRIX.md counted the new test file); regenerated, then `tests/test_fixture_matrix.py`, `test_team_report_309.py`, `test_team_report.py`: `48 passed` |
| `tests/test_team_report_309.py` (slow included) | `23 passed` |
| pro skill tests | `Ran 56 tests` `OK` |
| `ruff check --isolated --select E9,F821,F841 .` | changed files clean; the same 4 F841 in test files not changed here |
| `python3.11 -m compileall` | OK |
| Owner's web app on port 8770 | NOT RUN (restart needed) |
| Linux/Windows, live runs, wheel build, CLI run | NOT RUN |

## Web app UX: one clear path (DECISIONS 310, 2026-11-05)

What changed (behaviour and data unchanged; routes and downloads kept): the results page is Summary → Neyi düzeltmeli →
Önce bunları kontrol edin → İndir → questions → Teknik ayrıntılar (folded: everything the page had). Summary and cards
come from the team report's own data (GET `/audits/{id}/overview`, the current-engine copy), so the page shows the PDF's
numbers. "Önce bunları kontrol edin": three items open, the optional line, "Doğru" / "Doğru değil", the name asked once,
plain errors beside the field, "Kontrol edilenler" with "Geri al" (DELETE `/audits/{id}/review/{finding_id}`; the entry
moves to review.json's `replaced`). Times from the median of the last five runs per mode (a range without history).
History: date and time, mode, pages read, path, plain status, short ID; revised analyses fixed. New audit: address,
depth cards, extra options folded; the plan in three lines; progress in plain steps with the time left. "?" hints for
canonical, hreflang, noindex. Turkish by default.

Screenshots (isolated copies of the four audits and the demo; `reviews/2026-11-05/ux-proposal/built/`, git-ignored):
new audit, the name error, the plan, progress, history, nihan/Moodist/efb/Firecrawl-only results in TR and EN, the
check error, a saved item with Undo, Downloads, technical details opened; no horizontal scroll at 1280 or 1440 px.

**Verification** (working tree on `e053b9f`, macOS, Python 3.13.1; no .env, no providers, no live requests):

| Command | Result |
|---|---|
| fast suite, `pytest -q -rfE -p no:cacheprovider -m "not slow and not timing"` | `2706 passed, 4 skipped, 134 deselected, 1 warning in 463.45s (0:07:43)` |
| full suite (first run) | `2 failed, 2838 passed, 4 skipped`: the generated FIXTURE-MATRIX.md, and the demo test that now starts in Turkish; both fixed |
| full suite, `pytest -q -rfEs -p no:cacheprovider` (rerun) | `2840 passed, 4 skipped, 1 warning in 844.47s (0:14:04)` (skips: 2 wheel builds, live-run examples, real-site corpus) |
| `tests/test_web_ux_310.py` | `9 passed` |
| pro skill tests | `OK` |
| `ruff check --isolated --select E9,F821,F841 .` | changed files clean; the same 4 F841 in old test files |
| `python3.11 -m compileall`, JS syntax check | OK |
| Owner's web app on port 8770 | NOT RUN (restart needed) |
| Windows/Linux browsers, screen readers, live runs | NOT RUN |

## Business types, v0.3 stage 4 (DECISIONS 311, 2026-11-05)

What changed: 14 business-type profiles (`maya_audit/business_types/profiles/`): the 12 sectors of the owner's file
(`docs/business-types/Maya-sektor-ve-oncelikli-sayfa-turleri.xlsx`), "Restoran / kafe" and "Diğer"; each page read gets
the profile's page type from its address, structured data, title/H1, menu and link text and content signals; importance
= 50% profile weight + 35% link score + 15% click depth (`importance_source`); the suggestion with a one-line reason;
"not found among the pages read" notes for the top 3 types; `crawl.business_type` (schema 1.25); the web app's
"İşletme türü" on the new-audit form, the plan, the progress box and the results ("Değiştir"); the team report's page 6
line and page types; time estimates from current-engine runs only (defaults 1 / 10 / 25 min below three runs); "Gizle"
in the history. "Diğer" = Stage 3 exactly. Signals for the team to review: `docs/business-types/signals.md` and
`signals.xlsx` (1,155 signals, 1,047 still guesses). Also fixed: `/qr-menu/` was taken for a language folder.

**Offline on copies of four saved audits** (copied to a scratch folder; current-engine copies made there;
`tools/business_types_saved.py --current`; nothing under `~/.maya-audit/web` written):

| Audit | Suggested type, reason | Not found among the pages read | Cards (order) |
|---|---|---|---|
| nihan b3198942 (500 pages) | E-ticaret: Shopify; 22.114 addresses with 'products', 'collections'; menu 'koleksiyon' | none | same 9 in the same order |
| moodist c581ff0a | Sağlık: Hospital, MedicalOrganization on the homepage; 58 addresses with 'tedavi', 'doctors'; menu 'anlaşmalı kurumlar', 'check-up' | Klinik ve konum | same 9 in the same order |
| enpara 07297f4d | Bankacılık: 143 addresses with 'kredi', 'mevduat'; menu 'kredi', 'kredi kartı', 'mevduat' | Destek | same 5 in the same order |
| adile 6f2830d5 | Restoran / kafe: FoodEstablishment on the homepage; 85 addresses with 'sube', 'subeler' | Rezervasyon / sipariş | same 4 in the same order |

Top 10 key pages, before (Diğer) -> after (the suggested type): nihan: homepage, `/en`, then 8 collections, unchanged
(collections 91 -> 98, homepage 96 -> 90). moodist: the four language homepages, then six treatment pages (89-87);
`/tr/ekibimiz/` (Doktor ve ekip) and the English adult-psychiatry page leave the top 10; `/tr/` stays 20 (its canonical names `/tr/tr/`, the S2 card). enpara:
homepage, `/sirketim`, then product pages (cards, insurance, accounts, `/odemeler`) at 69-70; `/transferler` (72) leaves
the top 10. adile: homepage, the two branch pages (`/sube/...`, 76), `/restoranlar-iletisim` (contact), `/blog`, then the
story pages; before: homepage, `/blog`, the story pages, `/sss`. `/qr-menu/` is the "Menü" page (it was typed a
homepage). Priorities move by a few tenths; no finding, severity or gate decision changes. Team report PDFs (adile,
enpara; Turkish): 6 pages each, page 6 shows "İşletme türü: … (önerildi; neden: …)", the profile's page types and the
"not found" line, nothing cut.

**Incident:** the one CLI run of the platform check (against a loopback fake site, with an isolated audit home) did not
switch Firecrawl off or isolate the env file: the CLI read the project's Firecrawl key and sent 5 scrape requests for
the loopback pages; all failed (HTTP 500), 0 credits spent or reserved (the scratch ledger). The owner's ledger in
`~/.maya-audit` does not hold them. No other provider was called. Not repeated.

**Verification** (working tree on `c676483`, macOS, Python 3.13.1; no .env read, no live site requests; see the
incident above for the one CLI run):

| Command | Result |
|---|---|
| fast suite, `pytest -q -rfE -p no:cacheprovider -m "not slow and not timing"` (first run) | `3 failed, 2725 passed`: README schema line (2), the early suggestion lacked the crawl counters (1); fixed |
| fast suite (rerun) | `2728 passed, 4 skipped, 134 deselected, 1 warning in 492.69s (0:08:12)` |
| full suite (first run) | `1 failed, 2861 passed, 4 skipped`: the suggestion was sent as a "progress" web event without counters; now its own event `business` |
| full suite, `pytest -q -rfEs -p no:cacheprovider` (rerun) | `2862 passed, 4 skipped, 1 warning in 869.00s (0:14:29)` (skips: 2 wheel builds, live-run examples, real-site corpus) |
| `tests/test_business_types_311.py` | `22 passed` |
| pro skill tests | `Ran 56 tests` `OK` |
| `ruff check --isolated --select E9,F821,F841 .` | changed files clean; the same 4 F841 in old test files |
| `python3.11 -m compileall`, `node --check app.js` | OK |
| CLI run with stdout to a file | ran once on a loopback fake site (exit 0, Markdown to stdout; no `--json`, so no JSON written); see the incident; not repeated |
| Owner's web app on port 8770 | NOT RUN (restart needed; the `hidden` column is added on the next start) |
| Live runs, Windows/Linux, wheel build | NOT RUN |

## Key pages: one homepage row, a place per page type; provider-free runs (DECISIONS 312, 2026-11-05)

What changed: the homepage's language versions are one key-pages row ("Ana sayfa (4 dil)"); with a business type each
profile page type found keeps a place for its best page; AGENTS.md (both) require provider-free local runs (temporary
folder, `MAYA_AUDIT_ENV_FILE` to a missing file, every provider key empty, `--no-firecrawl`); tests also unset the
CrUX, PageSpeed, Bing and Search Console keys.

moodist's top 10 after (offline copy): 1 homepage (4 languages: `/tr/`, `/ru/`, `/ar/`, `/en/`; 20), 2
`/tr/tibbi-bolumlerimiz/bagimlilik-merkezi-amatem/` (89), 3 `/tr/tani-ve-tedavi-yontemleri/yatakli-servis/` (89), 4
`…/direncli-depresyon/` (88), 5 `…/elektro-konvulsif-tedavi-ekt/` (88), 6 `/tr/tibbi-bolumlerimiz/noroloji-birimi/`
(87), 7 `…/uyku-laboratuvari-uyku-testleri/` (87), 8 `/tr/tibbi-bolumlerimiz/acil-psikiyatri/` (87), 9
`…/yatakli-servis/psikiyatri-servisi/` (87), 10 `/tr/ekibimiz/` (Doktor ve ekip, 80). Cards unchanged.

| Command | Result |
|---|---|
| fast suite (first run) | `1 failed, 2732 passed`: the Turkish appendix test knew only the fixed page-type labels; it now accepts "ana sayfa (N dil)" |
| fast suite, `pytest -q -rfE -p no:cacheprovider -m "not slow and not timing"` | `2733 passed, 4 skipped, 134 deselected, 1 warning in 466.24s (0:07:46)` |
| full suite, `pytest -q -rfEs -p no:cacheprovider` | `2867 passed, 4 skipped, 1 warning in 868.47s (0:14:28)` |
| the AGENTS.md recipe, once as written (loopback fake site) | exit 0; `out.json` written (schema 1.25); no Firecrawl section; no provider ledger in the temporary home |
| Owner's web app on port 8770 | NOT RUN (restart needed) |

## Global UI fixes (DECISIONS 313, 2026-11-05)

What changed: business type as a chip with "Neden?" and the type in use in "Değiştir" ("Sağlık / klinikler
(önerilen)"); headline with exact counts ("1 yüksek, 7 orta ve 11 düşük önemde sorun var; önce geri dönen kanonik
adres."), "Engelleyici" only with a Blocker, web and PDF; "?" hints after the whole title; "adres" for "URL" in all
Turkish text (230 values); moodist's homepage row "Ana sayfa (4 dil) · önem hesaplanamadı (kanonik sorunu, bkz. kart
#1)". Checked on moodist c581ff0a in an isolated copy of the web app (scratch web home with that audit's rows and saved
files, port 8771, provider-free environment; headless Chromium screenshot) and its team report PDF (7 pages, page 6).

| Command | Result |
|---|---|
| fast and full suites (first run) | `7 failed`: tests holding the old Turkish "URL" wording (6) and the old headline (1, both languages); updated |
| fast suite, `pytest -q -rfE -p no:cacheprovider -m "not slow and not timing"` | `2739 passed, 4 skipped, 134 deselected, 1 warning in 466.28s (0:07:46)` |
| full suite, `pytest -q -rfEs -p no:cacheprovider` | `2873 passed, 4 skipped, 1 warning in 859.94s (0:14:19)` |
| `ruff check --isolated --select E9,F821,F841` (changed code), `python3.11 -m compileall`, `node --check` | clean / OK |
| Owner's web app on port 8770 | NOT RUN (restart needed) |

## One version per running app; centred column (DECISIONS 314, 2026-11-05)

What was wrong on 8770: an app process started before 03bc8ae served the new script (read from disk each request) with
its old text table and engine: raw keys, the old headline, "4 URL", engine 6ed3f4b. Not missing keys and not the
derived copy (rebuilt with 03bc8ae at 21:45 after the restart). Now the page's files come from the process's start-up
snapshot with a version token, the page says when a restart is needed, a missing key is never shown raw, and the
derived copy is also rebuilt when a text library changes. The report column is centred (a finished audit's card was
left-aligned at wide windows).

Checked on the normal app path: `python -m maya_audit_web --port 8772` with a copy of the owner's web home (63 audits;
database copied with SQLite's backup, read-only source), provider-free environment, moodist c581ff0a opened in
headless Chromium: chip, "Neden?", "Sağlık / klinikler (önerilen)", "1 yüksek, 7 orta ve 11 düşük önemde sorun var;
…", engine 03bc8ae in the footer (the working tree), centred at 1024/1440/1920/2560 px and at 67% zoom. The first test
start showed my own bug (the new `snapshot` variable hid the module of the same name: the summary route failed); fixed
before the measurements.

**To see the change on port 8770:** stop the running app (Ctrl+C in its Terminal window), start it again from
`tools/maya-audit` with `.venv/bin/python -m maya_audit_web`, then reload the page in the browser (Cmd+Shift+R). From
now on the page itself says when a restart is needed.

| Command | Result |
|---|---|
| fast and full suites (first run) | `1 failed`: `test_no_unfilled_placeholders` expected an unknown key shown raw; now "…" (the owner's rule) |
| fast suite, `pytest -q -rfE -p no:cacheprovider -m "not slow and not timing"` | `2746 passed, 4 skipped, 134 deselected, 1 warning in 496.01s (0:08:16)` |
| full suite, `pytest -q -rfEs -p no:cacheprovider` | `2880 passed, 4 skipped, 1 warning in 880.25s (0:14:40)` |
| `ruff check --isolated --select E9,F821,F841`, `python3.11 -m compileall`, `node --check` | clean / OK |
| Owner's web app on port 8770 | NOT RUN by me (restart needed: steps above) |

## Stage 8a: borrowed from Screaming Frog (DECISIONS 315, 2026-11-06)

What changed: every redirect hop per address (`crawl.redirects`, schema 1.26); new rules `idx6.links_to_redirect`,
`idx4.chain`, `str9.wrong_language`, `str7.over_100kb`; redirect/canonical findings that share an address are one card;
issue type Sorun / Kontrol edin / Fırsat on cards, in the XLSX and the web app; problems per template (PDF page,
XLSX sheet, card line). Research file: `docs/research/screaming-frog-research-for-maya-audit.md`.

**Before / after, offline on copies of the saved audits** (current-engine copies made in a scratch folder):

| | moodist c581ff0a | nihan b3198942 |
|---|---|---|
| Headline | "1 yüksek, 7 orta ve 11 düşük …" -> "1 yüksek, 7 orta ve 12 düşük …" (+ links to `/`) | "3 orta ve 28 düşük" -> "3 orta ve 29 düşük" (+ an image over 100 KB) |
| Problem cards | 9 -> 7 | 10 -> 11 |
| Merged | 01 idx4.redirect_loop + 03 idx4.redirecting + 09 idx3.chain + new links to `/` (50 pages) -> card 01, High, Sorun | none (no redirect in the crawl) |
| New | — (inside card 01) | card 09 str7.over_100kb, Low, Fırsat (the homepage hero, 135 KB) |
| Types | card 07 str7.placeholder is Kontrol edin; the rest Sorun | card 09 Fırsat; the rest Sorun |
| Template lines | none (no card has 80% of its pages in one template) | 02 str12.language: kategori şablonu (/collections/*) 43 sayfa; 03 idx6.alias_links: /collections/* 141 sayfa; 06 tseo1.url_decomposed: ürün şablonu (/collections/*/products/*) 63 sayfa |
| Templates page | /tibbi-bolumlerimiz/*/* 9, /tani-ve-tedavi-yontemleri/*/* 8 … (Tedavi ve bölüm şablonu) | /collections/*/products/* 323, /collections/* 143, /products/* 8 … |
| PDF (Turkish, built and checked: nothing cut) | 8 pages: the templates page added (7 in DECISIONS 313) | 9 pages: the templates page and a fourth card page (13 cards) |

| Command | Result |
|---|---|
| fast suite (first run) | `17 failed`: text-library rules (digits, length, plurals, Turkish entries), README schema, sheet order, a hand-made test copying the loop's rule id, a fake site's malformed hreflang code; all fixed |
| fast suite, `pytest -q -rfE -p no:cacheprovider -m "not slow and not timing"` | `2756 passed, 4 skipped, 134 deselected, 1 warning in 479.26s (0:07:59)` |
| full suite (first run) | `1 failed`: test_idx_scenarios assumed every IDX-6 finding is a broken link; narrowed |
| full suite, `pytest -q -rfEs -p no:cacheprovider` | `2890 passed, 4 skipped, 1 warning in 871.46s (0:14:31)` |
| ruff E9/F821/F841, `python3.11 -m compileall`, `node --check` | clean / OK |
| Owner's web app on port 8770 | NOT RUN (restart needed) |

## Fixes from the airastana.com audit (DECISIONS 316, 2026-11-06)

What changed: Imperva's 200 block page is recognised (live and in saved data); one page limit for Maya's crawler and the
page reader together; country/language folders found (`crawl.locales`, schema 1.27) and one version of each page read
first; "Havayolu" split from "Seyahat / rezervasyon" (now "Tur / otel"); the same four summary tiles and a plain sitemap
line on its card; "Teyit edin" explained and freed of meaningless "seen only in Firecrawl's copy" marks; "the" in English
headlines, "öncelik:" in Turkish ones; one Turkish instruction form (imperative).

**Before / after, offline on copies of the saved audits** (current-engine copies made in a scratch folder):

| | airastana d12146fb | moodist c581ff0a | nihan b3198942 |
|---|---|---|---|
| Tiles | 10 · 61 · sitemap 149/149 · lab not measured -> 6 · 13 · Medium+ pages 1/13 · not measured | unchanged (20 · 50 · 7/50 · —) | unchanged (32 · 500 · 49/500 · —) |
| Suggested type | Seyahat / rezervasyon ('tur' from /tur-en/) -> Havayolu | Sağlık (58 -> 54 addresses) | E-ticaret (22,114 -> 12,220 addresses) |
| Top cards | 01 noindex in sitemap (block pages), 02 TLS, 03 slow pages -> 01 TLS, 02 heading levels, 03 JSON-LD | unchanged | unchanged |
| Key pages | 10 block pages, importance 20 -> Firecrawl's pages typed (routes, flight search, check-in …), importance not computed | unchanged | unchanged |
| Teyit edin | 17 -> 3 | 13 | 9 |
| Versions line | — -> "20 versions; at most 2 of a page" | "4 versions; one per page (homepage in 4)" | "2 versions; at most 2 (homepage in 2)" |
| PDF | 6 pages TR and EN, nothing cut | 8 pages TR and EN | 9 pages TR; EN blocked by card 02's title box, as at HEAD |

| Command | Result |
|---|---|
| fast suite (first run) | `18 failed`: pinned wording/headlines, business-type list and groups, schema file name, the deprecated client brief's "-malısınız" check, two crawl-order and one grouping expectation, the demo shop's homepage in Turkish read late (fixed: homepage versions exempt), a request-allowance reason (fixed); all fixed |
| fast suite, `pytest -q -rfE -p no:cacheprovider -m "not slow and not timing"` | `1 failed, 2772 passed, 4 skipped, 134 deselected` (LG-103 not registered; fixed, its test file `8 passed`) |
| full suite, `pytest -q -rfEs -p no:cacheprovider` | `2907 passed, 4 skipped, 1 warning in 926.62s (0:15:26)` |
| ruff E9/F821/F841, `python3.11 -m compileall`, `node --check` | clean / OK |
| CLI, provider-free, loopback fake site with 5 locale folders, `--max-pages 10 --no-firecrawl` | schema 1.27, no Firecrawl section, no provider ledger; 6 pages of /global-en/ before any second version |
| Owner's web app on port 8770 | NOT RUN (restart needed) |

## Next step

1. A live nihan Standard 500 run on this code (owner's explicit request needed: it is paid and live).
2. Push to withmaya/seo-audit when the owner asks.
3. Backlog: `docs/BACKLOG.md`.

## Block pages, bot protection, reader links, long titles (DECISIONS 317, 2026-11-06)

What changed: block pages and 429s never use up the page limit (`firecrawl.coverage.page_limit`, schema 1.28, and one
line under Maya's own limits); Firecrawl reads pages Maya got a block page for; ACC-9 `acc9.bot_protection` names the
service, the blocked requests and the AI crawlers that may be blocked the same way, with steps, and stays a card when
Firecrawl read the site; the page grouping (link score, click depth, importance) runs on Firecrawl's own links whenever
a page was read only through it; every title slot of the team report shrinks to fit and never stops the PDF.

**Before / after, offline on copies of the saved audits** (current-engine copies in a scratch folder):

| | airastana d12146fb | moodist c581ff0a | nihan b3198942 |
|---|---|---|---|
| ACC-9 | Info note "Imperva challenged Maya's direct crawler …" -> S3 card 02 "Let crawlers past the bot protection's block page" (Imperva, 50 of 50, GPTBot/ClaudeBot/PerplexityBot/Google-Extended) | no block, unchanged | no block, unchanged |
| Recorded issues | 6 -> 7 (pages read 13, Medium+ pages 1, lab not measured: unchanged) | 20 | 32 |
| Page limit | new line: 50 block answers not counted; the reader could read up to 50, read 13 (the time limit came first) | no line | no line |
| Key pages | unchanged (saved copies hold no reader links: "not computed") | unchanged | unchanged |
| PDF | 6 pages TR and EN | 8 pages TR and EN | 8 pages TR and EN |

| Command | Result |
|---|---|
| fast suite (first run) | `14 failed`: tests that pinned a named service's challenge as an Info note, the schema history list, LG-104 not registered, a title written with a join (not readable by the wording test); all fixed |
| fast suite, `pytest -q -rfE -p no:cacheprovider -m "not slow and not timing"` | `2790 passed, 4 skipped, 134 deselected, 1 warning in 485.71s` (final run, after every change) |
| full suite, `pytest -q -rfEs -p no:cacheprovider` | `2 failed, 2922 passed, 4 skipped` : the fixture matrix (regenerated) and one sitemap-sampling test that failed while a second pytest ran beside it (passes alone) |
| ruff E9/F821/F841, `python3.11 -m compileall` | clean / OK |
| CLI, provider-free, loopback fake site serving Imperva's block page, `--max-pages 5 --no-firecrawl` | schema 1.28, no Firecrawl section, no provider ledger; ACC-9 `acc9.bot_protection` S3 Estimated; exit 1 (blocked audit) |
| Owner's web app on port 8770 | NOT RUN (restart needed) |

## A consistent 429 block is a card (DECISIONS 318, 2026-11-06)

nihan's three saved 429 audits (0dc805b9, 50473193, 8b872028), current-engine copies offline: ACC-9 `acc9.blocked_429`
Inferred ("Teyit edin") -> Verified, a card; PDFs TR and EN print, 6 pages each. A single or occasional 429 stays
Inferred. Results of the suites are in the commit message of this change.

## The client brief "Müşteri özeti" (DECISIONS 319, 2026-11-06)

What changed: new `maya_audit_web/team_report/brief.py` and its words `texts/brief-tr.json`, `texts/brief-en.json`: at
most 5 pages for a business owner (summary, key pages, the top 3-5 measured or confirmed problems, a 30/60/90 plan),
built from the team report's data and gated (pages, IDs/rule names, unconfirmed items, vendor names, unexplained terms,
`client_brief_allowed`). Web app: "Müşteri özeti (PDF)" in the Downloads card, TR/EN (GET `/client-brief`,
`/downloads/brief`); skill: `maya-audit-pro/scripts/brief.py`. Also fixed: page-reader key-page types no longer listed
as "not found" (airastana). No schema bump.

**Offline on copies of the saved audits** (current-engine copies in a scratch folder, provider-free): every brief 5
pages, nothing blocked; PDFs and page images in `reviews/2026-11-06/client-brief/` (git-ignored).

| | nihan b3198942 | moodist c581ff0a | airastana d12146fb |
|---|---|---|---|
| Verdict band | S3 (sound base) | S2 (fix in 30 days) | S3 |
| Problems | 5: page code weight, language versions (confirmed by hand), duplicate-address links, heading order, shared titles | 5: redirect chain (High), tracking parameters, duplicate-address links, heading order, brand name | 4: certificate, Imperva block page, heading order, broken markup |
| Already good | https, server reliability, no crawl delay | protection lets crawlers in, AI programs allowed, https | correct main addresses, sitemap, click depth |
| Key pages | 8, homepage (2 languages) first | 8, `/tr/ekibimiz/` kept | 8, site-wide note for problems 1 and 2; not found: fares only (was 3) |

Team report, same copies: moodist 8 pages TR/EN, airastana 6 pages TR/EN, nihan TR 9 pages; nihan EN blocked by card
02's box ("kutu: todos[1].title"), the same at HEAD (checked from a `git archive HEAD` copy): the owner's STR-12 note
makes the English card too tall. Not changed here.

| Command | Result |
|---|---|
| `pytest tests/test_client_brief_319.py tests/test_team_report.py` | `54 passed` |
| fast suite (first run) | `1 failed, 2824 passed`: `test_web_ux_310` pinned the old "Yakında" card; now checks the working card in Chromium |
| fast suite, `pytest -q -rfE -p no:cacheprovider -m "not slow and not timing"` | `2825 passed, 4 skipped, 135 deselected, 1 warning in 499.92s (0:08:19)` |
| full suite, `pytest -q -rfEs -p no:cacheprovider` | `1 failed, 2959 passed, 4 skipped`: the fixture matrix (regenerated; with the brief tests `35 passed`) |
| ruff E9/F821/F841, `python3.11 -m compileall`, `node --check` | clean / OK |
| skill `scripts/brief.py` on moodist (EN), provider-free | exit 0, 5 pages |
| Owner's web app on port 8770 | NOT RUN (restart needed) |

## Cards never block printing, brief SEO owner, 429 service words (2026-11-07, DECISIONS 320)

Owner's three small fixes, global for every audit. (1) A long confirmation note or any long card part wraps and shrinks
like a title; a too-tall card shrinks its parts (to 80%), then folds its least important lines into "+N more" (the
note last); the overflow check still runs after. nihan b3198942 EN, blocked before by card 02 ("kutu/kart:
todos[1].title"), now prints (9 pages), card 02 shrunk, nothing cut. (2) The brief's "SEO" owner reads "SEO / pazarlama
ekibi" / "SEO / marketing team". (3) The 429 card names the service and what was refused and what loaded (nihan
0dc805b9: "Cloudflare refused 1 of 1 page request with 429 (too many requests); robots.txt, 26 sitemap files and
llms.txt loaded."); the brief's 429 words name the service and the robots file and sitemap with their explanations.
No schema bump.

**Offline on copies of the saved audits** (scratch folder, provider-free, no provider ledger created): team report TR and
EN of nihan b3198942, nihan 0dc805b9, moodist c581ff0a, airastana d12146fb: all print, no overflow, nothing shortened.
Briefs: nihan, moodist, airastana 5 pages, not blocked (moodist shows "SEO / pazarlama ekibi"); nihan 0dc805b9
correctly blocked for low coverage (1 of 500 pages).

| Command | Result |
|---|---|
| `pytest tests/test_card_fit_320.py` | `18 passed`; with the card fitter switched off, its 4 render tests fail (overflow) |
| related suites (team report, brief 319, 317, files naming the changed parts) | `113 passed` |
| fast suite, `pytest -q -rfE -p no:cacheprovider -m "not slow and not timing"` | `2843 passed, 4 skipped, 135 deselected, 1 warning in 524.94s (0:08:44)` |
| full suite, `pytest -q -rfEs -p no:cacheprovider` (one run, on its own) | `2978 passed, 4 skipped, 1 warning in 920.54s (0:15:20)` |
| ruff E9/F821/F841 on `maya_audit maya_audit_web` and the new test; `python3.11 -m compileall` | clean / OK (ruff on all of `tests/` shows 4 old F841 in untouched files) |
| Owner's web app on port 8770 | NOT RUN (restart needed to pick up the change) |

## Fixes from reviewing the client briefs (2026-11-07, DECISIONS 321)

Owner's five fixes, global for every audit. (1) Certificate expiry: severity by days left at the audit (under 7 Blocker,
under 14 High, under 30 Medium; window 30 days), also for saved audits (`reassess_rules._decisions_321`, in `apply` and
`saved_data`); expiry date and days left on the card, in the evidence table, in the brief and in the web results; the
brief's verdict/health speak for every High card and a certificate under 14 days, and the High health line no longer
says "nothing is urgent". (2) Host-level cards name their hosts, never "addresses not read". (3) Brief p1: one line
when fewer pages were read than planned, with why. (4) Merged cards: owner of the most technical part, plus the next
when two are needed ("Developer + SEO"). (5) XLSX: an empty sheet says why; "importance not computed" in plain words.
No schema bump.

**Offline on copies of the saved audits** (scratch folder, provider-free, no provider ledger): team reports TR/EN print
(airastana 6, moodist 8, nihan 9 pages; no overflow, nothing shortened); briefs TR/EN 5 pages, none blocked.

| | airastana d12146fb | moodist c581ff0a | nihan b3198942 |
|---|---|---|---|
| Certificate | 9.1 days: S3 -> High; "Expires 14 November 2026; 9 days left at the audit (5 November 2026)"; table host/date/days/issuer | exactly 30.0 days: no finding (strictly under 30) | 52 days: none |
| Brief p1 | coverage line "protection service slowed our reading … 13 pages (we planned 50)"; High health line | High health line (no "nothing is urgent") | calm S3 line (nothing High) |
| Merged owner | — | card 1 "Developer + SEO" | card 2 "Developer + Content" |
| XLSX | Templates: "none of the pages our crawler asked for could be read …" | all sheets have rows | all sheets have rows |

| Command | Result |
|---|---|
| `pytest tests/test_brief_review_321.py` | `54 passed` |
| related suites (team report, briefs 319/320, 317, idx scenarios, reassess, v03 client report, appendix users) | `1 failed, 108 passed`: `test_idx_scenarios` near_expiry pinned S3 for 7 days; now High, expectation updated, `6 passed` |
| fast suite, `pytest -q -rfE -p no:cacheprovider -m "not slow and not timing"` | `2897 passed, 4 skipped, 135 deselected, 1 warning in 492.54s (0:08:12)` |
| full suite, first run | `1 failed, 3031 passed, 4 skipped`: the fixture matrix (regenerated with `scripts/fixture_matrix.py`; its tests `3 passed`) |
| full suite, second run, `pytest -q -rfEs -p no:cacheprovider` | `3032 passed, 4 skipped, 1 warning in 928.60s (0:15:28)` |
| ruff E9/F821/F841 (package + changed tests), `python3.11 -m compileall`, `node --check app.js` | clean / OK / OK |
| Owner's web app on port 8770 | NOT RUN (restart needed) |
| Push | NOT DONE (owner: don't push) |

## XLSX appendix for non-technical teammates, web affected pages, inclusive certificate bands (2026-11-07, DECISIONS 322)

Owner's seven items, global for every audit. (1-5) The appendix opens with "Nasıl okunur" (six lines), "Özet" (the PDF's
cards, each linked to its first row), "Sayfa bazında" (one row per page with a problem: clickable address, page type,
importance, problem count, worst severity, short Turkish list; by importance then severity) and "Bulgu bazında" (one row
per finding and page: problem, severity, type, clickable address, the value measured on that page, what to do; IDs at
the end); the technical sheets follow. Frozen bold headers, filters, widths, wrapped text, hyperlinks; TR headers in the
TR file, EN in the EN file. New `maya_audit/page_rows.py` feeds the sheets and the web list. (6) Web: "Etkilenen
sayfalar (N)" on each problem card opens the full list (`GET /audits/{id}/cards/{n}/pages`) with search and CSV
download. (7) Certificate bands inclusive (30 or fewer Medium, 14 or fewer High, 7 or fewer Blocker: moodist's 30.0-day
certificate is now a Medium card); certificate hosts as plain host names in the address sheets and the web list.
No schema bump.

**Offline on copies of the saved audits** (scratch folder, provider-free, no provider ledger created):

| | nihan b3198942 | moodist c581ff0a | airastana d12146fb |
|---|---|---|---|
| Team report TR/EN | 9 pages, 13 cards, PASS | 8 pages, 10 cards (certificate card 3, 30 days, Medium), PASS | 6 pages, 6 cards, PASS |
| Brief TR/EN | 5 pages | 5 pages | 5 pages |
| XLSX (10 sheets, RG-17 ok) | Özet 13, Sayfa bazında 2,119, Bulgu bazında 4,902 | 10 / 52 / 705 | 6 / 35 / 86 (EN) |
| Certificate rows | — | "moodisthastanesi.com", "www.moodisthastanesi.com" | "airastana.com", "www.airastana.com" (9 days) |

| Command | Result |
|---|---|
| `pytest tests/test_xlsx_pages_322.py` | `30 passed` |
| related suites (321, 320, 319, idx scenarios, reassess, 315, team report, v03 client report and fixes, 317) | `13 failed, 253 passed` first (old band and sheet-list expectations, test fixture without groups); after updates `149 passed` on the affected files |
| fast suite, `pytest -q -rfE -p no:cacheprovider -m "not slow and not timing"` | `2931 passed, 4 skipped, 135 deselected, 1 warning in 509.75s (0:08:29)` |
| full suite, first run | `1 failed, 3065 passed, 4 skipped`: the fixture matrix (regenerated with `scripts/fixture_matrix.py`; its tests `3 passed`) |
| full suite, second run, `pytest -q -rfEs -p no:cacheprovider` | `3066 passed, 4 skipped, 1 warning in 904.11s (0:15:04)` |
| ruff E9/F821/F841 (package + new test), `python3.11 -m compileall`, `node --check app.js` | clean / OK / OK |
| Opening the XLSX in Excel or Google Sheets | NOT RUN (neither available here; every XML part parses, schema element order tested) |
| The web dialog in a browser | NOT RUN (API and script covered by tests) |
| Owner's web app on port 8770 | NOT RUN (restart needed) |
| Push | NOT DONE (owner: don't push) |

## "Okundu mu?" and a measured value for every page read, schema 1.29 (2026-11-08, DECISIONS 323)

Owner's two XLSX follow-ups, global for every audit. (1) "Sayfa bazında" and "Bulgu bazında" have "Okundu mu?" (Evet /
Hayır, okunmadı; "—" for hosts and the whole site); pages read first (importance, then severity), addresses never read
after them as one group (inside each card in "Bulgu bazında", so the card links still land on the card's first row);
"Nasıl okunur" has a seventh line; the web "Etkilenen sayfalar" list and its CSV have the column. (2) New
`maya_audit/page_measures.py`: one compact record per page read (status, HTML size, content start, headings and skipped
levels, title/description, canonical, language, words, first response, cache, images, scripts, tags, structured data).
New audits store `crawl.page_measures` (schema 1.29: a new field of the frozen crawl shape; the checks' evidence keeps
a sample and a page read only through a page reader keeps no record otherwise); older reports work the records out
from the saved `crawl.pages[].analysis`. "Ölçülen değer": the finding's own evidence first, then the page record's
values for that kind of finding; an address not read says "okunmadı"; "ayrıntı kaydedilmedi" only where nothing can be
worked out.

**Offline on copies of the saved audits** (scratch folder, provider-free, no provider ledger). "Bulgu bazında", TR:

| | nihan b3198942 | moodist c581ff0a | airastana d12146fb |
|---|---|---|---|
| "ayrıntı kaydedilmedi" before -> after | 1,877 -> 10 | 272 -> 0 | 15 -> 11 |
| what is left | pages read only through Firecrawl, agents.md | — | pages read only through Firecrawl |
| "okunmadı" rows | 103 | 2 | 4 |
| Team report / brief | 9 pages / 5, PASS | 8 / 5, PASS | 6 / 5, PASS |

nihan "Sayfa bazında": 498 pages read first, then 1,621 addresses not read. "Before" was measured on the committed code
(`549b1e5`) in a separate scratch worktree; the working tree was not touched.

| Command | Result |
|---|---|
| `pytest tests/test_page_values_323.py tests/test_xlsx_pages_322.py` | `42 passed` |
| CLI on a local static site, provider-free (`--no-firecrawl`, empty keys, temp home and env file) | exit 0; schema 1.29; `crawl.page_measures` for both pages read; no `firecrawl` section; no provider home or ledger |
| fast suite, first run | `15 failed, 2928 passed`: tests pinned to schema 1.28 (version asserts; a synthetic "current schema" report, now `SCHEMA_VERSION`); fixed |
| fast suite, second run | `1 failed, 2942 passed, 4 skipped, 135 deselected`: `page_measures` not described in `docs/REPORT-SCHEMA.md`; added, file `26 passed` |
| full suite (fixture matrix regenerated first), `pytest -q -rfEs -p no:cacheprovider` | `3078 passed, 4 skipped, 1 warning in 966.33s (0:16:06)` |
| ruff E9/F821/F841 (package + new tests), `python3.11 -m compileall`, `node --check app.js` | clean / OK / OK |
| Opening the XLSX in Excel or Google Sheets | NOT RUN here |
| Owner's web app on port 8770 | NOT RUN (restart needed) |
| Push | NOT DONE (owner: don't push) |

## The team's sector audit method: P0-P3, the "Sektör audit" XLSX, homepage weights (2026-11-08, DECISIONS 324)

Owner's Step 2 after the Step 1 analysis (`reviews/sector-method/`, offline, not in git). Source:
`docs/business-types/Sektor_Bazli_SEO_Audit_Onceligi.xlsm` (read with openpyxl, data only; no macro in it), turned into
`maya_audit/sector_method.json` by `tools/sector_method_build.py`. New `maya_audit/priority_levels.py` and
`maya_audit/sector_audit.py`; P0 marks in review.json (`manual_review.record_p0/undo_p0`); web: chips, the P0 block in
"Önce bunları kontrol edin", `POST/DELETE /audits/{id}/review/p0`, `GET /audits/{id}/downloads/sector`; the stdlib XLSX
writer gains formulas, dropdowns and recalculation on opening; `page_rows` drops the generic "status; size" value.
Homepage weight follows the sector's rank (E-ticaret 70, Sağlık 55, Ev hizmetleri 55, Restoran 55); `seyahat` renamed.

**Offline on current-engine copies of the saved audits** (scratch folder, provider-free, no provider ledger). Card order,
severities and priority scores are those of the selection (unchanged by the labels):

| Audit (type) | Cards: P-label (score) | Sector workbook: rows filled of 62 |
|---|---|---|
| nihan b3198942 (E-ticaret) | 1 P2 (70), 2 P1 (80), 3 P2 (33.3), 4-9 P3 (13.3-23.3), 10 P2 (33.3), 11 none (utility pages, weight 0) | 27: Uygun 12, Kısmen Uygun 13, Hatalı 2 |
| moodist c581ff0a (Sağlık) | 1 P0 automatic: canonical loop on the homepage `/tr/` (73.3), 2 P2 (40), 3 P1 certificate (100), 4 P2, 5 P3, 6 P2, 7-8 P3 | 20: Uygun 9, Kısmen Uygun 6, Hatalı 5; 9 rows "page type not found" (Klinik, Randevu, Anlaşmalı kurumlar) |
| airastana d12146fb (Havayolu, draft rows) | 1 P1 certificate (133.3), 2-4 P3 | 13: Uygun 8, Kısmen Uygun 2, Hatalı 3 (44 common + 18 draft rows) |

| Command | Result |
|---|---|
| `pytest tests/test_sector_method_324.py` | `20 passed` |
| related suites (311, 312, 315-323, team report, v03 client report, web UX) | `11 failed, 344 passed` first (old expectations: the 85 floor, "Tur / otel", seven "Nasıl okunur" lines, the downloads dict, the generic value, the summary column; a P-code pattern matching a CSS comment, fixed); after updates `155 passed` |
| fast suite, `pytest -q -rfE -p no:cacheprovider -m "not slow and not timing"` | `2963 passed, 4 skipped, 135 deselected, 1 warning in 508.03s (0:08:28)` |
| full suite, first run | `1 failed, 3097 passed, 4 skipped in 923.81s`: the fixture matrix (regenerated with `scripts/fixture_matrix.py`; its tests `3 passed`) |
| full suite, second run, `pytest -q -rfEs -p no:cacheprovider` | `3098 passed, 4 skipped, 1 warning in 936.26s (0:15:36)` |
| ruff E9/F821/F841 (package, new test, tool), `python3.11 -m compileall`, `node --check app.js` | clean / OK / OK |
| CLI on a local static site, provider-free (`--no-firecrawl`, empty keys, temp home and env file) | exit 0; schema 1.29; 2 pages; no `firecrawl` section; no home folder or ledger created |
| The workbook opened with openpyxl (scratch) | five sheets, the team's formulas (ranges to row 208), dropdowns on Durum and 1-5; cached values agree |
| Opening the workbooks in Excel, Numbers or LibreOffice | NOT RUN here |
| Owner's web app on port 8770 | NOT RUN (restart needed) |
| Push | NOT DONE (owner: don't push) |

## "Sektör audit" XLSX precision pass (2026-11-08, DECISIONS 325)

Owner's five items, global. The mapping is exact per rule id (each rule in at most one common row; one sector row per
finding and page type); only measured or confirmed findings set a Durum; a valid certificate is "Hatalı" only at High;
host-level findings count host names and are site-wide; "Uygun" rows say what was checked on how many pages or hosts;
every problem card has a P level (0-weight pages: P3). Every mapping change is listed in DECISIONS 325.

**Offline on current-engine copies** (scratch folder, provider-free). Rows of 62 (44 common + the sector's 18):

| Audit | Uygun | Kısmen Uygun | Hatalı | Kontrol Edilmedi | Rows changed |
|---|---|---|---|---|---|
| nihan b3198942 | 12 -> 13 | 13 -> 12 | 2 -> 2 | 35 -> 35 | CORE-006 KE -> Kısmen (`idx6.alias_links`); CORE-012 Kısmen -> Uygun (`str9.lang_mismatch` is CORE-027); CORE-031 Kısmen -> KE (`idx5.stamped` is a sitemap date) |
| moodist c581ff0a | 9 -> 9 | 6 -> 4 | 5 -> 3 | 42 -> 46 | CORE-008 Hatalı -> KE (certificate not a host variant); CORE-016 Kısmen -> KE (placeholder alt is not image size); CORE-021 KE -> Kısmen (`str19.no_target`); CORE-026 Kısmen -> KE (placeholder alt estimated); CORE-036 Kısmen -> KE (`str5.names` estimated); CORE-038 Kısmen -> KE (STR-5 no longer here; STR-21 not run); CORE-041 Hatalı -> Kısmen (30-day certificate, Medium) |
| airastana d12146fb | 8 -> 8 | 2 -> 0 | 3 -> 1 | 49 -> 53 | CORE-008 Hatalı -> KE; CORE-024 Kısmen -> KE (heading jumps estimated); CORE-034 Kısmen -> KE (`str3.unparsed` estimated); CORE-044 Hatalı -> KE (Maya's crawler blocked, ACC-9) |

Cards: nihan 11 now P3 (search/cart pages weigh 0); the other levels unchanged.

| Command | Result |
|---|---|
| `pytest tests/test_sector_precision_325.py tests/test_sector_method_324.py` | `28 passed` |
| fast suite (fixture matrix regenerated first) | `2971 passed, 4 skipped, 135 deselected, 1 warning in 533.46s (0:08:53)` |
| full suite, `pytest -q -rfEs -p no:cacheprovider` | `3106 passed, 4 skipped, 1 warning in 928.07s (0:15:28)` |
| ruff E9/F821/F841, `python3.11 -m compileall` | clean / OK |
| Opening the workbooks in Excel or Numbers | NOT RUN here |
| Owner's web app on port 8770 | NOT RUN (restart needed) |
| Push | NOT DONE (owner: don't push) |

## "Sektör audit" XLSX: Yaygınlık and Efor on every row (2026-11-08, DECISIONS 326)

Every row has Yaygınlık (measured spread, else 1) and Efor (the rules' catalogue default, else 3); a Metodoloji line says
they are pre-filled and editable. Workbooks rebuilt from current-engine copies (scratch, provider-free): moodist
c581ff0a, nihan b3198942, airastana d12146fb: 0 rows of 44 + 207 without Yaygınlık or Efor in each; "Uygun" rows show
"0 / Yok".

| Command | Result |
|---|---|
| Recalculation in Numbers (AppleScript, scratch copy of the moodist workbook, closed without saving) | CORE-001 Uygun -> Hatalı: 0 / Yok -> 100 / P1; SEC-066 Uygun -> Hatalı: 0 / Yok -> 33,3 / P2; Audit Özeti "Sağlık / klinikler": Hatalı 1 -> 2, Uygun 2 -> 1, Denetlenen 3 |
| LibreOffice headless | NOT RUN: not installed (no install without authorization) |
| `pytest tests/test_sector_prefill_326.py tests/test_sector_precision_325.py tests/test_sector_method_324.py` | `33 passed` |
| fast suite (fixture matrix regenerated first) | `2976 passed, 4 skipped, 135 deselected, 1 warning in 529.38s (0:08:49)` |
| full suite, `pytest -q -rfEs -p no:cacheprovider` | `3111 passed, 4 skipped, 1 warning in 924.75s (0:15:24)` |
| ruff E9/F821/F841, `python3.11 -m compileall` | clean / OK |
| Push of 14e104f, b15aa40 and this commit; GitHub CI | see the owner's summary of this session (not a status-only commit) |

## Akıllı ~150, v0.3 Stage 5 (2026-11-08, DECISIONS 327)

New `maya_audit/sampling.py` (typing before reading, the team's budget rule and split, two waves with re-typing, the
plan record and coverage per type), frontier `plan_rank`, crawler hooks (plan at the first page read, re-plan after 60%),
CLI `--smart`, web mode "Akıllı ~150 (önerilen)" (Quick renamed "Hızlı ön bakış · 50 sayfa", still the default),
Firecrawl `read_scope` ("needed" in Akıllı; "Tam okuma (Firecrawl her sayfa)" = "all"), progress line per type,
coverage line in the team report / XLSX / Sektör audit, schema 1.30 `crawl.sampling`, "Sektör seçilmedi" in the
Sektör audit. Dry-run tool: `tools/sampling_dryrun.py`.

**Dry runs on saved data** (no request; outputs `reviews/smart-sampling/step2-*.json`, not in git):

| | moodisthastanesi c581ff0a (Sağlık) | nihan b3198942 (E-ticaret) |
|---|---|---|
| Known pages (one version each) | 549, main folder `tr` | 8,059, main folder root |
| Planned per type | Tedavi ve bölüm 56/56, Doktor ve ekip 4/4, Klinik ve konum 2/2*, Ana sayfa 4 of 6, Randevu ve iletişim 3/3, Anlaşmalı kurumlar 1/1, blog 57/147, other 22/328, policy 1 | Kategori 46/145, Ürün 39/7,844, Ana sayfa 2/2, Mağaza 3/3, Kampanya 2/2, Yardım ve güven 12/12, blog 33/33, other 11/13, utility 2/4 |
| Re-typed after wave 1 | 0 (only 17 of the 90 wave-1 pages were read in the saved audit) | 23 |
| Fillable sector rows (of 18) | 9 -> 17 | 13 -> 16 |

\* two psychologists' profiles typed "Klinik ve konum" by address; reading is expected to re-type them.

**Where Quick 50's 10-25 minutes go today** (step timings of the saved reports, seconds): moodist (10.2 min wall)
crawl 96, structure 108, render 119, performance 45, access + index 19, sitemap check 200 (101 requests), Firecrawl 131
beside them; airastana (16.1 min) crawl 114, performance 56, sitemap check 194, Firecrawl 842 (blocked site); nihan
Standard 500 (85 min) crawl 535, sitemap check 806 (1,004 requests), Firecrawl 3,451. The sitemap check runs last, alone,
its light requests spaced by the shared site limit (one start per crawl gap, ~1 s) and sharing its slots with the
reader, so ~2 s each.

**Proposal to cut the sitemap check without changing results (not built; owner to decide):** (a) start it right after
the crawl, beside access/index/structure/render/performance, instead of after them: the same requests through the same
shared site limit and the same rows, only earlier (moodist: up to ~200 s saved, the steps it runs beside take ~290 s);
(b) in Akıllı, Firecrawl reading only where needed takes fewer of the site limit's slots, so the check's requests are
no longer slowed to ~2 s each. Not proposed: a smaller sample or HEAD instead of the light GET (that would change what
the check finds: meta robots and canonical are read from the first 64 KB).

| Command | Result |
|---|---|
| `pytest tests/test_sampling_327.py` | `19 passed` |
| CLI `--smart --business-type saglik` on a local static site, provider-free (`--no-firecrawl`, empty keys, temp home and env file) | exit 0; schema 1.30; 4 pages read; `crawl.sampling` with every type; no `firecrawl` section; no home folder or ledger |
| fast suite (fixture matrix regenerated), first run | `2 failed, 2993 passed`: mode list and the renamed label pinned in two tests; updated, `12 passed` |
| full suite, `pytest -q -rfEs -p no:cacheprovider` | `3130 passed, 4 skipped, 1 warning in 941.51s (0:15:41)` |
| ruff E9/F821/F841, `python3.11 -m compileall`, `node --check app.js` | clean / OK / OK |
| A live Akıllı audit | NOT RUN (owner runs one after restarting the web app) |
| Push | NOT DONE (owner: don't push) |

## The sitemap check beside the other steps (2026-11-09, DECISIONS 328)

The sitemap check starts right after the crawl on a thread of its own, beside access, index, structure and rendering,
and is joined before the performance rounds; llms.txt's links follow on the audit's own thread. Same requests, same
rows, same findings. Fetcher "lanes" give it its own row of the step timing table (`beside: [access, index, structure,
render]`) and its own time-limit refusals. Fixed on the way: a robots.txt sample's next due time read the wrong log
entry once another thread wrote to the log.

| Measurement | Before (committed code, scratch worktree) | After |
|---|---|---|
| In-memory site, 0.2 s per answer, 30 sitemap URLs checked | 5.7 s | 3.7 s |
| Sitemap check rows / findings | 30 / 14 | identical |
| Requests per step | — | unchanged |

Expected on the saved audits (step timings; the overlap is at most the four steps beside it): moodist about 200 s saved
(10.2 -> ~6.9 min), airastana about 43 s, nihan Standard 500 about 196 s.

| Command | Result |
|---|---|
| `pytest tests/test_sitemap_beside_328.py` | `3 passed` |
| fast suite, first run | `3 failed, 2995 passed`: phase order, a time-limit test (the check now ends before the limit), the robots samples' position; updated |
| full suite, first run | `2 failed, 3131 passed`: a robots sample due 118.8 s after the one before (a real bug: fixed), in-flight 5 within the site limit of 5 (test bound updated) |
| fast suite, final | `2998 passed, 4 skipped, 135 deselected, 1 warning in 533.84s (0:08:53)` |
| full suite, final | `3133 passed, 4 skipped, 1 warning in 947.45s (0:15:47)` |
| ruff E9/F821/F841, `python3.11 -m compileall` | clean / OK |
| A live audit | NOT RUN (owner) |
| Push | NOT DONE (owner: don't push) |

## Fixes from the first live Akıllı runs (2026-11-09, DECISIONS 329)

Worked from the saved reports moodisthastanesi 2d72fea0 and enpara 87f0425a (scratch copies; no new crawl, no provider
call). New `maya_audit/step_times.py`; Firecrawl's `read_scope` kept through the plan (`Options.as_dict`) and set by the
CLI's `--smart` (`--firecrawl-full-read`); "needed" without redirects and 4xx answers, templates as the page grouping's;
the "person" signal and article publisher markup in `business_types`; `"location": true` on five profile types and the
IDX-8 gate (`checks.index.gate_location_templates`, `final.settle`, `reassess_rules._decisions_329`); `HIGH_FLOOR`; the
brief's measured-only problems and precise ACC-9 line; `card_owner` with sitemap entries.

| Item | Before | After |
|---|---|---|
| 1 Time | not shown | web "Süre": moodist 21 dk 4 sn, enpara 11 dk 37 sn, one line per step; same line in the team report's "Bu denetimin sınırları" |
| 2 Firecrawl pages (Akıllı) | moodist 150/150, enpara 151 requests ("needed" lost in the plan) | moodist 31 (1 failed request + 30 cross-checks), enpara 34; no JavaScript template on either |
| 2 Minutes (estimated from saved timings) | moodist: reader 7.5 beside, end 54 s, total 21.1 | reader ~1.5, end ~30 s, total ~20.7 |
|  | enpara: reader 3.3 beside, end 82 s, total 11.6 | reader ~0.9, end ~51 s, total ~11.1 |
| 3 Page types | moodist "Klinik ve konum" 32 (30 blog posts by the publisher's Hospital markup, 2 profiles) | 33 pages change: 30 -> blog, 2 -> Doktor ve ekip, `/tr/team/anil-usta/` Diğer -> Doktor ve ekip; enpara 0 |
| 4 IDX-8 place-name | enpara card 3 (/sss/ 10 pages, /odemeler/ 6) | removed (Bankacılık has no location type) |
| 5 P level | enpara card 2 High P3 | P2 ("yüksek önem: en az P2"); order unchanged |
| 6 Brief | enpara problem 5 "brand named different ways" (Ölçüldü; kapsamı tahmini); good: "… engellemiyor" beside a robots.txt card blocking AI assistants, ACC-7 line about AI assistants | problem 5 the measured hreflang one; good: "Sitenizin güvenlik koruması sayfa isteklerimizi geri çevirmedi …", ACC-7 line dropped (key pages line instead); moodist: only the ACC-9 wording changes |
| 7 Owner | enpara card 2 (21 sitemap entries) İçerik | Geliştirici + İçerik |
| Sektör audit | moodist Uygun 10 · Kısmen 8 · Hatalı 3 · KE 41 (of 62); enpara 10 · 12 · 2 · 35 (of 59) | moodist 9 · 7 · 3 · 43 (SEC-071, SEC-072 -> KE: no clinic page read); enpara unchanged |

Team reports 9 pages each, briefs 5 pages each, not blocked (TR). Where moodist's 20 minutes of Maya's own steps go
(not changed; for the owner): the site limit fell 5 -> 1 after two answers over 2 s and every later request waited
~2 s (access 137 s / 10 requests, index 103 s, structure 89 s, llms.txt links 128 s / 50); rendering 4.3 min (21
pages); crawl 6.6 min (250 requests). Possible cuts: let the limit step back up after clean answers (up to ~4 min of
waiting on moodist), cap llms.txt link checks in Akıllı (~1.5 min), fewer render slots in Akıllı. The saved Akıllı
plan's own counts (moodist "Klinik ve konum: 0/52") stay as the run recorded them; a new run plans with the new typing.

| Command | Result |
|---|---|
| `pytest tests/test_live_fixes_329.py` | `27 passed` |
| related suites (311-328, team report, brief, Firecrawl, IDX) | `2 failed, 450 passed` first (estimated cards in the brief; a fake builder without cards); after updates passed |
| fast suite (fixture matrix regenerated), `pytest -q -rfE -p no:cacheprovider -m "not slow and not timing"` | `3025 passed, 4 skipped, 135 deselected, 1 warning in 535.21s (0:08:55)` |
| full suite, `pytest -q -rfEs -p no:cacheprovider` | `3160 passed, 4 skipped, 1 warning in 971.43s (0:16:11)` |
| ruff E9/F821/F841, `python3.11 -m compileall`, `node --check app.js` | clean / OK / OK |
| CLI `--smart --business-type saglik --no-firecrawl` on a loopback static site, empty keys, temp home and env file | exit 0; schema 1.30; no `firecrawl` section; no home folder or ledger; the psychologist profile typed `doctors`, the post `guide` |
| A live audit | NOT RUN (owner) |
| Owner's web app on port 8770 | NOT RUN (restart needed) |
| Push | NOT DONE (owner: don't push) |

## Speed, page selection in every mode, one Google key (2026-11-09, DECISIONS 330-332)

**1 Speed** (`sitelimit`: step back up after 10 answers under 1 s, the audit's own thread first; `audit`: access and
llms.txt's links to this site on lanes). Estimated per step from the saved request logs (a replay through a model of the
site limit, which gives the real totals: moodist 726 s modelled / 716 s real, enpara 330 / 331); the minutes before are
the saved runs', after the model's:

| Step (minutes) | moodist before | moodist after | enpara before | enpara after |
|---|---|---|---|---|
| access | 2.3 | beside (lane, 3.3) | 1.1 | beside (2.3) |
| index | 1.7 | 0.4 | 0.8 | 0.2 |
| structure | 1.5 | 1.5 | 2.1 | 1.7 |
| render | 4.3 | 4.3 | 1.4 | 1.4 |
| sitemap check | beside (3.9) | beside (5.4) | beside (2.7) | beside (3.6) |
| waiting for the lanes | 0 | 1.4 | 0 | 0.5 |
| llms.txt links | 2.1 | beside (4.3) | 0.2 | beside (1.4) |
| post-crawl part | 12.1 | ~7.6 | 5.5 | ~3.7 |
| whole audit (with DECISIONS 329) | ~20.7 | ~16 | ~11.1 | ~9.3 |

The step-up alone barely helps moodist (HTML answers 1-2 s; fast runs only on static files); the order does.
Unchanged: crawl (moodist 6.6 min), rendering, performance rounds.

**2 Modes.** Hızlı ~50, Akıllı ~150, Derin ~500, Özel sayı 25-2000: all with the Akıllı selection; "Tam tarama sırası"
advanced. The plan shows time, Firecrawl's maximum and usual credits, and how pages are chosen. Docs: TEAM-SETUP, README,
WEB-API, WEB-APP.

**3 PageSpeed / Core Web Vitals.** The web app reads `MAYA_AUDIT_CRUX_API_KEY` (now also `MAYA_AUDIT_GOOGLE_API_KEY`):
Chrome UX Report field data for the origin (phones, 28 days), one request, a second or two. PageSpeed Insights lab runs
exist only in the CLI (`--pagespeed`, now reading either name from `.env` too): mobile, 3 runs for each of up to 5 key
pages, only on ownership-verified sites. Seen in the web app: plan details "Core Web Vitals from real Chrome visitors are
included", results "Core Web Vitals (real visitors)", team report "Saha verisi" with values instead of "Ölçülmedi".

**4 Search Console.** Proposal only: `docs/proposals/SEARCH-CONSOLE.md` (waiting for the owner's OK).

| Command | Result |
|---|---|
| `pytest tests/test_speed_modes_330.py` | `20 passed` |
| fast suite, first run (fixture matrix regenerated) | `4 failed, 3041 passed, 4 skipped, 135 deselected` in 552.92 s: three pinned the old mode list, labels and the last robots.txt sample's place; one found that "needed" left out the ranking pages of the search data (fixed: still read) |
| full suite after the fixes, `pytest -q -rfEs -p no:cacheprovider` | `3180 passed, 4 skipped, 1 warning in 931.52s (0:15:31)` |
| ruff E9/F821/F841, `python3.11 -m compileall`, `node --check app.js` | clean / OK / OK |
| CLI `--smart --no-firecrawl` on a loopback static site with llms.txt, empty keys, temp home and env file | exit 0; schema 1.30; no `firecrawl` or `crux` section; no home folder or ledger; rows `access`, `llms_links` beside index/structure/render, `llms_links_other_sites` after performance; llms.txt links checked |
| A live audit | NOT RUN (owner) |
| Owner's web app on port 8770 | NOT RUN (restart needed) |
| Push | NOT DONE (owner: don't push) |

## The plan's Core Web Vitals line, paid line and time (2026-11-09, DECISIONS 333)

The owner's app on port 8770 (pid 52575, started 16:11 from `tools/maya-audit`, after `c705e46`) loads
`tools/maya-audit/.env`; its own loader sees a non-empty Core Web Vitals key: yes (checked through `crux.load_key` in the
same folder with the same empty environment; `.env` not opened, no value printed). The plan did not say so because the
page never showed `search_data.core_web_vitals`: now a "Core Web Vitals" row of the plan's details. "Paid data: at most
$0.0516" was the backlink price shown for the details although backlinks and search data were off: the short line now
shows a paid total only for chosen paid data. The plan's two times now agree (both the short line's "about N min"; the
details add the time limit).

| Command | Result |
|---|---|
| `pytest tests/test_speed_modes_330.py` and the plan/language tests | `29 passed` (after two old expectations were updated: the "Rough estimate" wording, the list of sentences equal in TR and EN) |
| fast suite, `pytest -q -rfE -p no:cacheprovider -m "not slow and not timing"` | `3050 passed, 4 skipped, 135 deselected, 1 warning in 530.38s (0:08:50)` |
| full suite, `pytest -q -rfEs -p no:cacheprovider` | `3185 passed, 4 skipped, 1 warning in 929.63s (0:15:29)` |
| Owner's web app on port 8770 | NOT RUN here (restart needed) |
| Push | NOT DONE (owner: don't push) |

## Live enpara Akıllı run 2e5829fb: Core Web Vitals and the sample's coverage line (2026-11-09, DECISIONS 334-335)

Worked from a scratch copy of the saved audit (no crawl). The CrUX request had been made for `https://enpara.com` (404);
asked live today with the app's key (never printed): `https://www.enpara.com` and its homepage answer 200, the typed
origin 404. Fetched for the scratch copy with `tools/crux_saved.py` (3 requests to Google, free).

| Item | Before | After (scratch copy, TR) |
|---|---|---|
| Field data | none ("Ölçülmedi"; origin enpara.com, 404) | LCP 1.4 s good, INP 322 ms needs improvement, CLS 0.02 good (www.enpara.com, to 2026-11-07); homepage alone 1.6 s / 205 ms / 0.06 |
| Team report page 1 | "Mobil laboratuvar performansı: Ölçülmedi" | "Gerçek kullanıcı (CrUX): 2/3 iyi · INP 322 ms (iyileştirilmeli)"; page 3 "Arama ve performans" appears (10 pages, was 9) |
| CORE-013 | Kontrol Edilmedi, "İlgili kontrol bu denetimde çalışmadı." | Kısmen Uygun, the three values and the origin |
| Sektör audit rows (of 59) | Uygun 10 · Kısmen 11 · Hatalı 2 · KE 36 | Uygun 10 · Kısmen 12 · Hatalı 2 · KE 35 |
| Coverage, page 1 | "Örneklem tamam", pages box "Keşfedilen bütün sayfalar okundu" | chip "Örneklem", "Örneklem · 499 bilinen adres okunmadı" |
| Limits | "Sayfa sınırı: en çok 150 sayfa okundu; bilinen 499 adres okunmadı." | "Örneklem: 128 sayfa okundu, 499 bilinen adres okunmadı. 150 sayfalık sınırdan 128 sayfa okundu: 21 adres hata döndü (404 ×21); 1 adres dosyaydı, sayfa değil; sayfa sınırı her sayfa isteğini sayar." |
| Client brief | "Bazı adresler okunamadı; bu yüzden bu özet planlanan 150 sayfa yerine 128 sayfaya dayanıyor." | the same sample line (brief 5 pages, not blocked) |

| Command | Result |
|---|---|
| `pytest tests/test_crux_coverage_334.py` | `17 passed` |
| fast suite (fixture matrix regenerated) | `2 failed, 3065 passed, 4 skipped, 135 deselected` in 520.26 s after the first fixes (the README still named schema 1.30; a run before that had 3 failures: two coverage-label pins, which led to `sample_shown`, and the frozen CrUX keys, which led to schema 1.31) |
| full suite after the README fix, `pytest -q -rfEs -p no:cacheprovider` | `3202 passed, 4 skipped, 1 warning in 939.34s (0:15:39)` |
| A live audit | NOT RUN (owner) |
| Owner's web app on port 8770 | NOT RUN (restart needed) |
| Push | NOT DONE (owner: don't push) |

## "Google'dan yeniden al" gave "There is nothing at that address" (2026-11-10, DECISIONS 336)

On the saved enpara audit 2e5829fb (app at `6a339b3`) the button posted to `/api/v1/api/v1/audits/<id>/crux`: the
server hands over the whole address and the page's `api()` added `/api/v1` again. Fixed in `api()`; the results now say
which address Google was asked about (for 2e5829fb's saved section: `https://enpara.com`, and that the site lands on
`https://www.enpara.com`). The saved audit's folder already holds `artifacts/crux.json` from the terminal run
(www.enpara.com, assessed, 2026-11-10 07:29 UTC), which the results read: after a restart and reload they show the
figures; the button now works too. Saved audit read, not written.

| Command | Result |
|---|---|
| `pytest tests/test_crux_coverage_334.py tests/test_turkish_report.py` | `51 passed` |
| the new browser test with the old `api()` (fix reverted for the check, then restored) | `1 failed` (the button's request got the 404), as expected |
| fast suite, `pytest -q -rfE -p no:cacheprovider -m "not slow and not timing"` | `3069 passed, 4 skipped, 135 deselected, 1 warning in 600.37s (0:10:00)` |
| full suite, `pytest -q -rfEs -p no:cacheprovider` | `3204 passed, 4 skipped, 1 warning in 1076.21s (0:17:56)` |
| `python3.11 -m compileall` (changed Python files), `node --check app.js` | OK |
| Owner's web app on port 8770 | NOT RUN here (restart needed) |
| Push | NOT DONE (owner: don't push) |

## enpara 2e5829fb card 2: broken links split, "Bağlantı yerleri", sitemap file per address (2026-11-11, DECISIONS 337)

Investigated offline first (shown to the owner before any change): none of card 2's 21 addresses is a link on a page
read; all 21 are sitemap entries (302 → 404), 15 spelling a heading or FAQ question on a page read. Built: IDX-1 split
into links / sitemap-only entries / mistyped hrefs; one "where" row per problem address and the page or entry naming it
(IDX-1 4xx and 5xx, IDX-6 links to redirects, IDX-3 chains and loops, IDX-4 canonicals, STR-9 hreflang), shown in the
Ek's new "Bağlantı yerleri" sheet, the PDF card's "NEREDE DÜZELTİLECEK" box (3 rows), the address list and the web card's
"Etkilenen sayfalar" dialog; the sitemap file per address (schema 1.32 `sitemap_doc.new_urls`); "Nasıl okunur" + the
Quick Look line. Saved audits get it through the current-engine copy (`reassess_rules._decisions_337`); report.json and
`~/.maya-audit/web` were only read (scratch copies for the before/after).

| Audit (current engine, scratch copy) | Before | After |
|---|---|---|
| enpara 2e5829fb, card 2 | "Hata veren sayfalara giden bağlantıları düzeltin ya da kaldırın", Geliştirici + İçerik, Küçük; 21 rows "sitemap.xml kaydı", file and status unknown | "Site haritasındaki hata veren adresleri düzeltin ya da çıkarın", Geliştirici, Orta; lines: files (/sirketim/sitemap.xml 9, /sitemap.xml 12), likely cause (inference, 15 match headings), 6 removed pages "kaldırın veya yönlendirin"; 21 rows "302 → 404", each with its file |
| enpara, card 8 (links to redirects) | no rows | 3 "where" rows (page, link text, menü, the redirect's end to use) |
| enpara Ek | no "where" sheet | "Bağlantı yerleri": 26 rows (21 sitemap entries, 3 links to redirects, 2 hreflang) |
| moodist 2d72fea0 | 14 cards | same 14 cards; card 1 (canonical/chain/links to redirect) gains 158 "where" rows |
| nihan b3198942 | 13 cards | no change |

| Command | Result |
|---|---|
| `pytest tests/test_link_places_337.py` | `19 passed` |
| fast suite, first run | `20 failed, 3068 passed`: pins for the new link field, how-to lines, schema 1.32, rule registries; a name clash (`_words`) in `checks/index.py` that broke the variants test (renamed); a sitemap-only re-test that asked the entry without following its redirect (fixed in `verification._broken_link`) |
| fast suite, `pytest -q -rfE -p no:cacheprovider -m "not slow and not timing"` | `1 failed, 3087 passed, 4 skipped, 135 deselected` (one more exact link-record pin, fixed) |
| full suite, first run | `2 failed, 3221 passed, 4 skipped`: `test_idx_scenarios::test_status_codes` (two S2 findings now) and the fixture matrix (regenerated: IDX-1 38 → 42 findings) |
| full suite after those, `pytest -q -rfEs -p no:cacheprovider` | `3223 passed, 4 skipped, 1 warning in 916.67s (0:15:16)` |
| `python3.11 -m compileall`, `node --check app.js` | OK |
| CLI, provider-free (loopback fake site, `--no-firecrawl`, empty keys, isolated home) | exit 3 (stopped at `--max-pages 5`, as expected), schema 1.32, IDX-1: linked + sitemap_only + href_mistyped, `new_urls` recorded, no `firecrawl` section, no provider ledger |
| `ruff check` | NOT RUN (not installed in `.venv`) |
| Owner's web app on port 8770 | NOT RUN here (restart needed) |
| Push | NOT DONE (owner: don't push) |

## Uzman kontrolü: enpara 2e5829fb reviewed card by card by the SEO team (2026-11-11, DECISIONS 338)

The team's SEO expert marked each card of the 2026-11-09 Ek (`docs/expert-reviews/enpara-2e5829fb.json`, the first human
labels for Stage 12). Each note was checked against the saved evidence before any change; raw HTML was not saved, so
Maya's own and Firecrawl's page analyses were compared instead.

| Card | Rule(s) | Her verdict | Evidence says | Fixed (every audit) | enpara after |
|---|---|---|---|---|---|
| 1 Head erken kapanıyor | tseo1.head_closed_lost/later | wrong | partly right: break real, canonical/hreflang/title before it | High only when they or a restricting robots value are lost; card names what stays | Medium, 46 pages; "Head içinde … / <div#blueLightOverlay> sonrasında …" |
| 2 Hata veren sayfalar | idx1.4xx.referenced | incomplete | right | DECISIONS 337 | sitemap card with files |
| 3 robots.txt | acc2.blocks.sample | wrong | right | parameter / old-script / form rules Info | no card (18 Info) |
| 4, 7, 8, 10 | str14.no_text, str16.shared, idx6.links_to_redirect, str3.unparsed | correct | — | — | unchanged |
| 5 Marka adı | str5.names | wrong | mostly right: 2 real names on 2 pages | domain form = brand, sub-brands not counted, only pages to fix | 3 names, 2 pages, "Teyit edin" |
| 6 H1 | str2.no_h1 | wording | right | "H1 etiketi" in every H1 rule | "H1 etiketi olmayan sayfalara tek bir H1 etiketi ekleyin" |
| 9 Bölüm başlıkları | str2.no_subheadings | wrong | partly right: no <h2>/<h3>; one listing page | listing pages left out; styled titles counted (new audits) | 3 pages, "Uzun sayfalara H2/H3 bölüm başlıkları ekleyin" |
| 11 http → https | idx2.temporary | wrong | partly right: 302 real, HSTS 1,825 days | Info under HSTS ≥ a year | no card |
| 12 Küçük tutarsızlıklar | acc8.redirecting (+ notes) | incomplete | right | each address with what redirects where; repeat of card 8 dropped | /llms.txt: /sikca-sorulan-sorular → /404…, … |
| 13 Soru başlıkları | (notes) | incomplete | right | every page listed with its questions; Ek rows | /odemeler: 4 soru düz metin, … (5 of 24 kept in this saved audit) |

Verdicts: 4 correct, 5 wrong, 1 wording, 3 incomplete. Rules for follow-up (marked wrong): acc2.blocks.sample,
idx2.temporary, str2.no_subheadings, str5.names, tseo1.head_closed_lost/later. enpara: 13 cards → 10; moodist 2d72fea0:
same 14 cards (brand card lists 14 of its pages to fix; the note card drops the repeat of its links-to-redirect card);
nihan b3198942: same 13 cards, H1 card worded "H1 etiketi", question card lists its pages.

| Command | Result |
|---|---|
| `pytest tests/test_expert_review_338.py` | `26 passed` |
| fast suite, first run | `8 failed, 3106 passed`: pins of the parser's `outside_head` (new `robots_content`), the head line on evidence given as plain addresses (fixed), the RG-9 test's brand pages (the name count now lists only pages with another name; the test now uses such a name) |
| fast suite, `pytest -q -rfE -p no:cacheprovider -m "not slow and not timing"` | `3114 passed, 4 skipped, 135 deselected, 1 warning in 521.32s (0:08:41)` |
| full suite, `pytest -q -rfE -p no:cacheprovider` | `1 failed, 3248 passed, 4 skipped, 1 warning in 930.88s (0:15:30)`: the fixture matrix (regenerated; `tests/test_fixture_matrix.py` `3 passed`) |
| Owner's web app on port 8770 | NOT RUN here (restart needed) |
| Push | NOT DONE (owner: don't push) |

## enpara fee70191: one card, two severities; head card from its evidence; Ek "Kapsam" and "Yöntem" (2026-11-11, DECISIONS 339)

fee70191 (Akıllı ~150, run on `fb4f070`) printed card 1 "Head'i erken kapatan öğeyi taşıyın" as High, P1, 90 pages.
The evidence (report and Maya's own crawl records): 2 pages carry `robots noindex` only after `<div#blueLightOverlay>`
(High is right for them); on 88 canonical, hreflang and title stay in the head (Medium). The 338 rule had applied; the
two findings share one cause, so the selection's one card took High for all 90 and the lost rule's fixed words.

| Card 1 | Before | After |
|---|---|---|
| Severity, P | Yüksek, P1 (85) | Yüksek, P1 (85: from the 88 Medium pages, team method) |
| Scope | 90 sayfa | 2 sayfa (+88 sayfa: Orta) |
| Why | "… ondan sonra gelen canonical, robots ya da hreflang etiketi yok sayılır." | "2 sayfada robots (noindex) head kırıldıktan sonra geliyor; Google bu kuralı uygulamayabilir. 88 sayfada canonical, title, hreflang head'de; yalnız description, Open Graph, generator sonra geliyor." |
| Priority text | "… canonical, robots ve hreflang etiketlerinin head'de kalmasını sağlayın." | "<div#blueLightOverlay> öğesini gövdeye taşıyın; robots (noindex) head'de, bu öğeden önce kalmalı." |
| Step 3 | Search Console'da canonical'ı teyit edin | Search Console Adres Denetimi'nde robots (noindex) kuralını teyit edin |
| Examples | /kartlar/encard-genc (a Medium page), /acentelik-bilgileri | /sirketim/basvuru, /acentelik-bilgileri |

| Ek | Before | After |
|---|---|---|
| Kapsam, PRF-3 | Core Web Vitals ve Lighthouse metrikleri (isteğe bağlı): İsteğe bağlı panel çalıştırılmadı (--pagespeed). | Lighthouse laboratuvar metrikleri (isteğe bağlı): Laboratuvar testi yapılmadı (--pagespeed); Core Web Vitals, Google'ın gerçek ziyaretçi verisinden (Chrome UX Report) değerlendirildi. |
| Yöntem | İş önemi: 1,0 (iş türü profilleri gelene kadar) | İş türü: Bankacılık (önerildi; değiştirilebilir) · Sayfa türü ağırlığı: Ana sayfa 100 · Destek 85 · Finansal ürün ve ürün listesi 70 · Ücret ve başvuru 55 · Hesaplama aracı 40 · Rehber / SSS / blog 30 · eşleşmeyen sayfa 25 · politika / yasal 15 · yardımcı sayfa 0 · İş önemi: puanda 1,0 (çarpan değil); iş türü puana sayfa önemiyle girer … |

Other saved audits with a mixed card (same card order): moodist redirect loop "1 sayfa (+1 Orta, +151 Düşük)", nihan
large homepage "1 sayfa (+494 Düşük)", enpara 87f0425a head card "20 sayfa (+1 Orta)".

| Command | Result |
|---|---|
| `pytest tests/test_head_card_339.py` | `6 passed` |
| fast suite, first run | `2 failed, 3118 passed, 4 skipped, 135 deselected` in 8:50: the English head labels said "On 1 pages" (now plural-aware), and the pinned "31 sayfa" of a Medium+Low merged card (now "1 sayfa (+30 sayfa: Düşük)") |
| after the fix: `pytest tests/test_v03_report_fixes.py tests/test_team_report_309.py tests/test_head_card_339.py tests/test_expert_review_338.py` | `66 passed` |
| full suite, `pytest -q -rfE -p no:cacheprovider` | `1 failed, 3254 passed, 4 skipped, 1 warning in 936.44s (0:15:36)`: the fixture matrix (regenerated; `tests/test_fixture_matrix.py` `3 passed`) |
| Owner's web app on port 8770 | NOT RUN here (restart needed) |
| Push | NOT DONE (owner: don't push). 338 (`fb4f070`) was pushed; CI run 43013066846 success (11:34:29 → 11:47:54 UTC) |

Same audit, follow-up (DECISIONS 339 (7)-(9)):

| | Before | After |
|---|---|---|
| Brand card "Marka için sitede tek bir ad kullanın" (2 pages) | card 12, Düşük, P2 | "Teyit edin": "Doğrulama bekliyor: diğer adlar yalnız yapısal veride; işaretlemede kontrol edin" ("Enpara" in every title; "Bankanın güzeli \| Enpara" and "Homepage" only as an Organization name) |
| "Soru başlıklarını düzeltin" | found (25 pages, all kept) but never made: the PDF's 2 note slots went to the structured-data and small-fixes cards; its pages were in no output | still not printed (2-note limit); made for the Ek and the web page list: 25 rows, e.g. "/odemeler: 4 soru düz metin: «Ödeme İste nedir?»" |
| "Küçük bağlantı ve etiket tutarsızlıklarını temizleyin" | PDF card listed /llms.txt with both redirects and the 3 pages; the Ek: one llms.txt row "ayrıntı kaydedilmedi", no row for the 3 pages | Ek: /llms.txt "/sikca-sorulan-sorular → /404?aspxerrorpath=/sikca-sorulan-sorular; /enparacom-nedir → /hakkimizda"; 3 rows "Open Graph etiketleri var, twitter:card yok" |

| Command | Result |
|---|---|
| `pytest tests/test_head_card_339.py tests/test_v03_report_fixes.py tests/test_expert_review_338.py tests/test_team_report_309.py` | `70 passed` |
| full suite on its own, `pytest -q -rfE -p no:cacheprovider` (fixture matrix regenerated first) | `3259 passed, 4 skipped, 1 warning in 955.96s (0:15:55)` |
| Push | owner asked: `fffddad` and this commit |
| CI for `1db0ddf` (run 43044201930) | attempts 1 and 2 failed before any test ran (the runner could not resolve archive.ubuntu.com in "Chromium system libraries"); attempt 3 success, job "fast" 18:34:52 → 18:45:04 UTC |

## Uzman kontrolü 2: enpara fee70191, the SEO team's 2nd review (2026-11-11, DECISIONS 340)

Her file is an Ek made before `fffddad`/`1db0ddf` (15 cards). Verdicts: 9 correct, 4 wrong, 1 wording, 1 incomplete
(`docs/expert-reviews/enpara-fee70191.json`); per rule over both reviews: `docs/expert-reviews/ACCURACY.md` (28 cards, 13
correct).

| Card | Rule(s) | Her verdict | Evidence says | Fixed (every audit) | enpara after |
|---|---|---|---|---|---|
| 1 Head | tseo1.head_closed_lost/later | wrong | right (old file) | DECISIONS 339 | 2 sayfa (+88 sayfa: Orta) |
| 2 Site haritası | idx1.4xx.sitemap_only | wrong | not supported: all 21 from the two sitemap files (12:07 UTC); 10 percent-encoded there but shown decoded in the Ek | <loc> as written, its line and the read time kept and shown | same 21; Ek: <loc> text (Maya's form, "kaydedilmedi (eski denetim)"), "12:07:49 UTC (15:07:49 TSİ) — yaklaşık" |
| 3-7, 9-11, 13 | str14.no_text, str9.no_return, str7.over_100kb, str2.no_h1, str16.shared, str3.unparsed, str9.status, str2.styled_subheadings, str8.headers | correct | — | — | unchanged |
| 8 Yönlendiren bağlantılar | idx6.links_to_redirect | wording | right; one link's redirect ends on its own page | own sheet: page, (old) address, redirect, final address, note | "Yönlendiren bağlantılar": 3 rows, /kredi-musteri/ihtiyac-kredisi-hesaplama noted |
| 12 Marka | str5.names | wrong | right: both other names are page titles in Organization/WebSite name | a name equal to its page's <title> not counted | no brand finding |
| 14 FAQPage | str3.qa_no_faqpage | wrong | right: 16/16 no accordion, no FAQ heading | FAQPage only for an accordion or under an FAQ heading | no card (16 → 0); the freed note slot shows "Soru başlıklarını düzeltin" (25 pages) |
| 15 Küçük tutarsızlıklar | acc8.redirecting | incomplete | right | each item says what to do | /sikca-sorulan-sorular: "hata sayfasına gidiyor (404) …"; /enparacom-nedir: "bağlantıyı şu adrese verin: /hakkimizda (… ölçülmedi …)" |

Other saved audits (offline re-evaluation of scratch copies): FAQPage suggestions dropped on moodist 2d72fea0 (31 of 36),
enpara 87f0425a (21), 2e5829fb (15), nihan b3198942 (6); 2e5829fb's brand finding also loses its two page-title names. The
full rule on the saved crawl records keeps 3 moodist pages, 1 enpara 87f0425a page and no nihan page (each under an FAQ
heading).

| Command | Result |
|---|---|
| `pytest tests/test_expert_review_340.py` | `24 passed` |
| fast suite, first run | `4 failed, 3144 passed, 4 skipped, 135 deselected` in 9:06: the new note's Turkish (added); two tests whose "real FAQ" was plain question paragraphs or headings (given an FAQ heading); the per-page redirect sentence pinned (new wording) |
| after the fixes: the six affected test files | `122 passed` |
| full suite, `pytest -q -rfE -p no:cacheprovider` (fixture matrix and accuracy summary regenerated first) | `3283 passed, 4 skipped, 1 warning in 940.42s (0:15:40)` |
| `node --check app.js` | OK |
| Owner's web app on port 8770 | NOT RUN here (restart needed) |
| Push | `ec46b7b` pushed (1db0ddf..ec46b7b); CI run 43091447492 success on attempt 1, job "fast" 19:54:01 → 20:07:53 UTC |

## Rows of an early-closed <head> from each page's record (2026-11-11, DECISIONS 341)

enpara fee70191, Ek "Bulgu bazında", card 1 (90 rows):

| | Before | After |
|---|---|---|
| High rows (2) | "<head> erken kapanıyor, kritik etiketler okunmuyor"; value "—"; "… canonical, robots ve hreflang etiketlerinin head'de kalmasını sağlayın." | "<head> erken kapanıyor: robots (noindex) bu öğeden sonra kalıyor"; "robots (noindex), <div#blueLightOverlay> sonrasında; head'de bu etiketin bir kopyası yok. <div#blueLightOverlay> öncesinde, head'de: canonical, title[, hreflang]"; "<div#blueLightOverlay> öğesini gövdeye taşıyın; robots (noindex) head'de, bu öğeden önce kalmalı." |
| Medium rows (88) | "<head> erken kapanıyor"; value "—" | "… yalnız meta ve Open Graph etiketleri sonra geliyor"; "<div#blueLightOverlay> sonrasında: description, Open Graph[, robots (index, follow) / keywords / ikinci bir canonical kopyası]; canonical, title, hreflang ondan önce, head'de" (40 / 36 / 5 / 4 pages …) |

Merged cards of the saved audits checked for rows without their own value: fee70191 (cards 1, 13), 2e5829fb (9),
87f0425a (4, 9), moodist 2d72fea0 (1, 7), nihan b3198942 (1, 4, 11): 0 left after nihan card 11's menu-language row.

| Command | Result |
|---|---|
| `pytest tests/test_head_rows_341.py` | `5 passed` |
| fast suite, `pytest -q -rfE -p no:cacheprovider -m "not slow and not timing"` | `3153 passed, 4 skipped, 135 deselected, 1 warning in 540.54s (0:09:00)` |
| full suite, `pytest -q -rfE -p no:cacheprovider` | `3288 passed, 4 skipped, 1 warning in 951.14s (0:15:51)` |
| Owner's web app on port 8770 | NOT RUN here (restart needed) |
| Push | `ec46b7b..f3285d1` pushed 2026-11-11 (owner: "push"). CI run 43098088162 (`maya-audit`) was created 20:47:12Z and was still "queued" with no job at 2026-11-12 09:28 UTC; GitHub refused both cancel ("completed") and re-run ("already running"). Owner: leave it, start nothing else for it. |

## SEO team's 165-item checklist in every audit (2026-11-12, DECISIONS 342)

Ek: "Kontrol listesi" (165 rows: ID, group, item, priority, result, evidence, Maya rule / card, missing data source)
and "Kontrol listesi özeti" (totals per result and per group). Team report: one page "SEO kontrol listesi" (outside
RG-15's ten pages). Built from the same selection as the cards, so every saved audit has it.

enpara fee70191 (current-engine copy, provider-free, PDF 10 pages, gate passed):

| | Items | Geçti | Sorun | Veri eksik | İnceleme gerekli | Uygulanmaz |
|---|---|---|---|---|---|---|
| Total | 165 | 41 | 13 | 31 | 49 | 31 |

Missing data sources: Search Console 18, GA4 10, Manuel 7, DataForSEO 3, Bing Webmaster Tools 1, PageSpeed 1, CRM 1.
Sorun: SEO-011/033 (card 2), -043/064 (card 5), -056/127 (card 3), -061 (card 6), -065 (card 4), -066 (card 8),
-100/101 (card 7), -132 (card 1), -112 (INP p75 323 ms, CrUX). Uygulanmaz: the 15 e-commerce items (banking, no
product page), local SEO (no local-business signal), news sitemap, IndexNow (no key), SPA items (no render gap), video,
internal search, large-site crawl budget. The hreflang and image-weight cards wait under "Teyit edin": İnceleme gerekli.

| Command | Result |
|---|---|
| `pytest tests/test_checklist_342.py` | `14 passed` |
| fast suite, `pytest -q -rfE -p no:cacheprovider -m "not slow and not timing"` | `3167 passed, 4 skipped, 135 deselected, 1 warning in 527.22s (0:08:47)` |
| full suite, `pytest -q -rfE -p no:cacheprovider` | `3302 passed, 4 skipped, 1 warning in 967.85s (0:16:07)` |
| Owner's web app on port 8770 | NOT RUN here (restart needed) |
| Push | `f3285d1..f0f7bf4` pushed 2026-11-12 (owner: "push"). CI run 43201559274 FAILED 10:34:27-10:35:08Z at "Syntax and undefined names": ruff F841, an unused `pages` in `maya_audit/checklist.py` (the local suites do not run that lint). f3285d1's run 43098088162 still "queued". |
| Fix | the unused line removed; `python -m compileall -q maya_audit maya_audit_web maya_audit_web_lite.py tests` and `ruff check --select E9,F821,F841 maya_audit maya_audit_web maya_audit_web_lite.py`: `All checks passed!` |
| fast suite after the fix | `3167 passed, 4 skipped, 135 deselected, 1 warning in 574.41s (0:09:34)` |
| full suite after the fix | `3302 passed, 4 skipped, 1 warning in 954.46s (0:15:54)` |
| Push of the fix | `f0f7bf4..757ed76` pushed 2026-11-12 (owner: "push"). CI run 43206110467 (`maya-audit`, job `fast`) green: 11:05:38-11:16:34Z (~11 min). f3285d1's run 43098088162 still "queued" (checked 2026-11-12), left alone as the owner asked. |

## Technical rules from the SEO team's review (Efsa's enpara report) (2026-11-12, DECISIONS 343)

New rules in `maya_audit/checks/team_rules.py`, run live and on saved reports (both reassessment paths); STR-13 gets
%%…%% and `str13.markers_data` for JSON-LD/meta; the sitemap check reads a sitemap of up to 1,000 addresses whole.
Every Ek row of the new cards says what was seen on that page.

enpara fee70191, from the saved data (copies of `artifacts/` in a scratch folder, built the app's way; before: the
committed engine `757ed76`, after: this change):

| # | Before | After |
|---|---|---|
| 1 | Head'i erken kapatan öğeyi taşıyın (Yüksek) | same |
| 2 | Site haritasındaki hata veren adresleri düzeltin ya da çıkarın (Yüksek, 21 adres) | same |
| 3 | Metni olmayan bağlantılara ad verin (Düşük) | **Blog yazılarındaki Product işaretlemesini kaldırın** (Orta, 39 sayfa) |
| 4 | hreflang bağlantılarını karşılıklı yapın | **Alt sayfalara kendi başlığını, H1'ini ve hreflang'ini verin** (Orta, 12 sayfa) |
| 5 | Büyük görselleri hafifletin | **Aynı sayfanın ikinci adreslerini asıl adrese 301'leyin** (Orta, 2 sayfa: /bireysel-basvuru/kimlik-bilgileriniz ve ?sw=1) |
| 6 | H1 etiketi olmayan sayfalara tek bir H1 etiketi ekleyin | **Olmayan adreslerde 302 yerine doğrudan 404/410 döndürün** (Orta, 21 adres) |
| 7 | Aynı açıklamayı paylaşan sayfalara ayrı açıklama yazın | Metni olmayan bağlantılara ad verin |
| 8 | Bağlantıları doğrudan son adrese verin | **Alt sayfalara kendi konusunu anlatan bir H1 verin** (Düşük, 20 sayfa) |
| 9-14 / 9-15 | 9 ayrıştırılamayan JSON-LD, 10 hreflang'deki çalışmayan adresler, 11 H2/H3, 12 tablo başlık hücreleri, 13-14 two note cards | 9 hreflang karşılıklı, 10 büyük görseller, 11 H1 yok, 12 ortak açıklama, 13 son adrese bağlantı, 14 ayrıştırılamayan JSON-LD, 15 hreflang'deki çalışmayan adresler |

Before 14 cards, after 15 (the limit): H2/H3, table header cells and the two note cards ("Küçük bağlantı ve etiket
tutarsızlıkları", "Soru başlıkları") now go to the Ek.

Kontrol listesi: Geçti 41 → 39, Sorun 18 → 24, Veri eksik 31 → 30, İnceleme gerekli 44 → 41, Uygulanmaz 31 → 31.
Changed: SEO-013 Veri eksik → Sorun (card 6), SEO-041 Geçti → Sorun and SEO-049, SEO-076 İnceleme → Sorun (card 5),
SEO-062 İnceleme → Sorun (card 4), SEO-106 Geçti → Sorun (card 3).

Not confirmable from the saved data (need a new run, not claimed): /anasayfa vs / (found, not read: page cap 150),
/sss/default.aspx (not found); the 185 sitemap addresses the sample left out (the next run asks all 285 not read).
Rule 4: no template variable in the JSON-LD or meta tags of the 174 saved copies.

Side effect found and stopped: verification builds earlier on 2026-11-12 (DECISIONS 342 and this one) were pointed at
fee70191's `current-engine/report.json`, so the app's own derived-copy code wrote `current-engine/report.current-engine/`
inside that audit (a copy the app does not read). Left for the owner to remove; builds now run on copies in a scratch folder.

| Command | Result |
|---|---|
| `pytest tests/test_team_rules_343.py` | `26 passed` |
| fast suite, `pytest -q -rfE -p no:cacheprovider -m "not slow and not timing"` | `3193 passed, 4 skipped, 135 deselected, 1 warning in 525.48s (0:08:45)` |
| full suite, `pytest -q -rfE -p no:cacheprovider` | `3328 passed, 4 skipped, 1 warning in 936.15s (0:15:36)` |
| CI's lint (`compileall`, `ruff --select E9,F821,F841`) | `All checks passed!` |
| Owner's web app on port 8770 | NOT RUN here (restart needed) |
| Push | pushed with 5a91953 on 2026-11-12 (see DECISIONS 344's row) |

## The SEO expert's review of the enpara Ek built from the DECISIONS 343 rules (2026-11-12, DECISIONS 344)

Removed at the owner's word: `~/.maya-audit/web/audits/fee70191335c4e608540a08f084abd7c/current-engine/report.current-engine/`
(report.json, affected-urls.json, meta.json; made from `current-engine/report.json` by DECISIONS 343's verification
builds). Nothing else in that audit was touched.

enpara fee70191 from the saved data (copies of `artifacts/` in a scratch folder; before: `5687276`, after: this change):

| # | Before (5687276) | After |
|---|---|---|
| 1 | Head'i erken kapatan öğeyi taşıyın | same; why: "Tüm 90 sayfada head'i aynı şablon öğesi kapatıyor: <div#blueLightOverlay>"; step "… (satır 1, 21, 39, 478)" |
| 2 | Site haritasındaki hata veren adresleri … (21) | same, each row "302 → /404?aspxerrorpath=… → 404; önerilen 301 hedefi: …" (21 targets: 7 by address and title words, e.g. /hesaplar/altin-hesabi/altin-hesabi → /hesaplar/altin-hesabi, /aktif-kampanyalar → /kampanyalar; 14 the folder's page above, e.g. /sirketim/anasayfa/… → /sirketim; none 410) |
| 3 | Blog yazılarındaki Product … (39) | same |
| 4 | Alt sayfalara kendi başlığını, H1'ini ve hreflang'ini verin (12) | **Sayfa içindeki başlıklar/sorular ayrı adres oluşturuyor** (Kontrol edin, 22 sayfa) |
| 5 | Aynı sayfanın ikinci adreslerini asıl adrese 301'leyin (2) | Olmayan adreslerde 302 yerine … (1 adres: Maya's made-up address) |
| 6 | Olmayan adreslerde 302 yerine … (21) | Metni olmayan bağlantılara ad verin |
| 7 | Metni olmayan bağlantılara ad verin | hreflang bağlantılarını karşılıklı yapın |
| 8 | Alt sayfalara kendi konusunu anlatan bir H1 verin (20) | Büyük görselleri hafifletin |
| 9-12 | hreflang karşılıklı, büyük görseller, H1 yok, ortak açıklama | H1 yok, ortak açıklama, ayrıştırılamayan JSON-LD, hreflang'deki çalışmayan adresler |
| 13 | Bağlantıları doğrudan son adrese verin (3) | Uzun sayfalardaki bölüm başlıkları (H2/H3) |
| 14 | Ayrıştırılamayan JSON-LD | **Başvuru adımlarının ikinci adreslerine canonical ya da noindex verin** (2) |
| 15 | hreflang'deki çalışmayan adresler | Veri tablolarının başlık hücreleri |

"Bağlantıları doğrudan son adrese verin" became the note "N iç bağlantı … geçici yönlendiren bir başvuru adımına
gidiyor" (Bilgi; /kredi-musteri/kredi-basvuru: 302 → /kredi-musteri/ihtiyac-kredisi-hesaplama → 200).
Sub-page card: the 12 /sss sub-pages and 10 with the section's H1; left out, their H1 being their own title: /iletisim/* (2),
/sirketim/iletisim/* (2), /ucretler/* (3), /sirketim/ucretler/* (2), /yatirim-hesabi/hisse-senedi.
Head rows: `<head>`/`</head>` counts "kaydedilmedi" for fee70191 (no raw HTML kept); the next audit records them.

Kontrol listesi: Geçti 39 → 40, Sorun 24 → 23, Veri eksik 30, İnceleme gerekli 41, Uygulanmaz 31. Changed: SEO-061
Sorun → Geçti (the only link to a redirect is an application step's, a note); SEO-041, -049, -076 now name card 14
(form steps); SEO-043, -062, -064, -065, -145 card 4 (sections).

| Command | Result |
|---|---|
| `pytest tests/test_expert_review_344.py` | `9 passed` |
| fast suite, `pytest -q -rfE -p no:cacheprovider -m "not slow and not timing"` | `3201 passed, 4 skipped, 135 deselected, 1 warning in 522.35s (0:08:42)` |
| full suite, `pytest -q -rfE -p no:cacheprovider` | `3336 passed, 4 skipped, 1 warning in 926.40s (0:15:26)` |
| CI's lint (`compileall`, `ruff --select E9,F821,F841`) | `All checks passed!` |
| Owner's web app on port 8770 | NOT RUN here (restart needed) |
| Push | `757ed76..5a91953` (with 5687276) pushed 2026-11-12 (owner: "push"). CI run 43241573282: attempt 1 failed only on the flaky sitemap-order test (`test_round2_sitemap_and_llms`, the log order of four requests in flight), attempt 2 passed 15:05-15:19Z; the test is fixed in DECISIONS 345. |

## 301 targets of the sitemap-errors card: section, closest parent, "kontrol edin" (2026-11-12, DECISIONS 345)

enpara fee70191, all 21 sitemap addresses (copies of `artifacts/` in a scratch folder; before: `5a91953`, after: this
change). After: 15 firm 301 targets, 6 "kontrol edin", no 410; the five the owner marked weak are rows 1, 13, 14, 12, 19.

| Address | Before (5a91953) | After |
|---|---|---|
| /kartlar/enparacom-kredi-karti/kredi-karti-basvuru-sartla… | 301 → /ucretler/kredi-karti (adres ve başlık benzerliği) | 301 → /kartlar/enparacom-kredi-karti (üst klasör sayfası) |
| /sirketim/anasayfa/apartman-site-yönetimleri-de-tüm-avant… | 301 → /sirketim (aynı klasörün üst sayfası) | kontrol edin: /sirketim (en yakın var olan üst sayfa) |
| /sirketim/anasayfa/kısa-başvuru-formumuzu-hemen-doldurun | 301 → /sirketim (aynı klasörün üst sayfası) | kontrol edin: /sirketim (en yakın var olan üst sayfa) |
| /sirketim/anasayfa/maas-fatura-vergi-sgk-gibi-tüm-odemele… | 301 → /sirketim (aynı klasörün üst sayfası) | kontrol edin: /sirketim (en yakın var olan üst sayfa) |
| /hesaplar/altin-hesabi/altin-hesabi | 301 → /hesaplar/altin-hesabi (adres ve başlık benzerliği) | 301 → /hesaplar/altin-hesabi (üst klasör sayfası) |
| /kartlar/encard-genc/çocuğunuz-da-enparalı-oluyor--) | 301 → /kartlar/encard-genc (aynı klasörün üst sayfası) | 301 → /kartlar/encard-genc (üst klasör sayfası) |
| /odemeler/islem-kisitlari/islem-limit-ve-kisitlari | 301 → /odemeler (aynı klasörün üst sayfası) | 301 → /odemeler/islem-kisitlari (üst klasör sayfası; site haritasında, bu denetimde okunmadı) |
| /sirketim/anasayfa/en-az-3-yıl-eft-havale-ve-hesap-isleti… | 301 → /sirketim (aynı klasörün üst sayfası) | kontrol edin: /sirketim/anasayfa/eft-fast-havale-masrafi-yok (aynı bölümde, adres ve başlık benzerliği; site haritasında, bu denetimde okunmadı) |
| /sirketim/hesaplar/altin-hesabi/sirketim-icin-nasil-altin… | 301 → /sirketim/hesaplar/altin-hesabi (adres ve başlık benzerliği) | 301 → /sirketim/hesaplar/altin-hesabi (üst klasör sayfası) |
| /hesaplar/altin-hesabi/empty | 301 → /hesaplar/altin-hesabi (aynı klasörün üst sayfası) | 301 → /hesaplar/altin-hesabi (üst klasör sayfası) |
| /kartlar/encard-genc/çocuğunuz-için-güvenlik--güvenlik--g… | 301 → /kartlar/encard-genc (aynı klasörün üst sayfası) | 301 → /kartlar/encard-genc (üst klasör sayfası) |
| /odemeler/islem-kisitlari/islem-saatleri | 301 → /odemeler (aynı klasörün üst sayfası) | 301 → /odemeler/islem-kisitlari (üst klasör sayfası; site haritasında, bu denetimde okunmadı) |
| /sirketim/anasayfa/kredi-kartı-aidatı-yok! | 301 → /ucretler/kredi-karti (adres ve başlık benzerliği) | kontrol edin: /sirketim/kartlar/kredi-karti (aynı bölümde, adres ve başlık benzerliği; site haritasında, bu denetimde okunmadı) |
| /sirketim/hesaplar/altin-hesabi/sirketimin-altin-hesabina… | 301 → /bilgi-bankasi/altin-hesabina-nasil-altin-eklenir (adres ve başlık benzerliği) | 301 → /sirketim/hesaplar/altin-hesabi (üst klasör sayfası) |
| /hesaplar/birikim-hesabi/birikim-hesabi | 301 → /hesaplar/birikim-hesabi (adres ve başlık benzerliği) | 301 → /hesaplar/birikim-hesabi (üst klasör sayfası) |
| /sirketim/hesaplar/altin-hesabi/sirketimin-altin-hesabind… | 301 → /sirketim/hesaplar/altin-hesabi (aynı klasörün üst sayfası) | 301 → /sirketim/hesaplar/altin-hesabi (üst klasör sayfası) |
| /hesaplar/birikim-hesabi/birikim-hesabi-birikmis-parami-d… | 301 → /hesaplar/birikim-hesabi (aynı klasörün üst sayfası) | 301 → /hesaplar/birikim-hesabi (üst klasör sayfası) |
| /kartlar/encard-genc/10-17-yaş-arasındaki-çocuğunuz-için-… | 301 → /kartlar/encard-genc (aynı klasörün üst sayfası) | 301 → /kartlar/encard-genc (üst klasör sayfası) |
| /sirketim/hesaplar/gunluk-hesap/en-az-3-yıl-boyunca-hesap… | 301 → /sirketim (aynı klasörün üst sayfası) | 301 → /sirketim/hesaplar/gunluk-hesap (üst klasör sayfası; site haritasında, bu denetimde okunmadı) |
| /hesaplar/birikim-hesabi/birikim-hesabindan-odeme-para-tr… | 301 → /hesaplar/birikim-hesabi (aynı klasörün üst sayfası) | 301 → /hesaplar/birikim-hesabi (üst klasör sayfası) |
| /aktif-kampanyalar | 301 → /kampanyalar (adres ve başlık benzerliği) | kontrol edin: /kampanyalar (aynı bölümde, zayıf adres benzerliği) |

| Command | Result |
|---|---|
| `pytest tests/test_redirect_targets_345.py` | `7 passed` |
| fast suite, `pytest -q -rfE -p no:cacheprovider -m "not slow and not timing"` | `3208 passed, 4 skipped, 135 deselected, 1 warning in 536.51s (0:08:56)` |
| full suite, `pytest -q -rfE -p no:cacheprovider` | `3343 passed, 4 skipped, 1 warning in 961.17s (0:16:01)` |
| CI's lint (`compileall`, `ruff --select E9,F821,F841`) | `All checks passed!` |
| Push | `5a91953..aedfdd1` pushed 2026-11-12 (owner: "push"); CI run 43294813481 green on the first attempt, 19:53:50-20:04:58Z (~11 min). |

## "Bağlantı yerleri": the card's 301 target per sitemap address (2026-11-12, DECISIONS 346)

enpara fee70191 (copy of `artifacts/` in a scratch folder): "Önerilen hedef" for the 21 sitemap rows was "site haritası
oluşturucuyu düzeltin" or "kaldırın veya yönlendirin"; now the same target and reason as "Bulgu bazında", e.g.
"301 → /kartlar/enparacom-kredi-karti (üst klasör sayfası)", "301 → /sirketim (kontrol edin; en yakın var olan üst
sayfa)", "301 → /odemeler/islem-kisitlari (üst klasör sayfası; site haritasında, bu denetimde okunmadı)",
"301 → /kampanyalar (kontrol edin; aynı bölümde, zayıf adres benzerliği)". 21 of 21 with a target (15 firm, 6 kontrol
edin); 13 made from a heading also end "; site haritası oluşturucuyu düzeltin".

| Command | Result |
|---|---|
| `pytest tests/test_where_targets_346.py tests/test_link_places_337.py` | `2 passed` + `test_link_places_337` passed |
| fast suite, `pytest -q -rfE -p no:cacheprovider -m "not slow and not timing"` | `3210 passed, 4 skipped, 135 deselected, 1 warning in 535.85s (0:08:55)` |
| full suite, `pytest -q -rfE -p no:cacheprovider` | `3345 passed, 4 skipped, 1 warning in 929.83s (0:15:29)` |
| CI's lint (`compileall`, `ruff --select E9,F821,F841`) | `All checks passed!` |
| Push | `3c5f9ea` pushed on the owner's word (2026-11-12); CI run 43306672486 passed, 21:05:07-21:18:14 UTC (recorded with DECISIONS 347) |


## The atasunoptik review as global rules: sign-in links, training-bot blocks, files, page types, typos, homepage (2026-11-16, DECISIONS 347)

atasunoptik f06a2129 (Smart ~150, 149 pages read; copy of `artifacts/` in a scratch folder, before = `git archive HEAD`,
after = this change; the person's E-ticaret choice kept):

| | Before | After |
|---|---|---|
| Card 4 "Bağlantıları doğrudan son adrese verin" | 149 addresses (menu "Sipariş Takip" → /Uye/Siparislerim 302 → sign-in) | 3 addresses, each row "son adrese verin: /eski → /gunes-gozlugu"; the sign-in links are a Bilgi note "(beklenen)" |
| Card 5 robots.txt (Bytespider only) | Düşük, Sorun, **P0** | Düşük, **Kontrol edin**, P3 (`acc2.training_block.sitewide`, at most P2) |
| /sitemap.xml, /kurumsal.xml in the Ek | rows of "Sayfa bazında" | not pages: "—", no type, not in "Sayfa bazında" |
| Page types, no profile | ürün 140, politika 3, blog 3, yardımcı 2, ana sayfa 1 | kategori 116, diğer 11, yardımcı 7, ürün 4, konum 3, politika 3, blog 3, ana sayfa 1 |
| Suggested business type | Diğer | E-ticaret ("120 okunan sayfa ürün ya da kategori sayfası") |
| E-ticaret: /Uye/PlusLogin, /Uye, /kurumsal/uyelik_1519 | ürün 77-90 | utility 20 (and /Uye/OrderTracker 18) |
| E-ticaret: homepage | 85, below categories at 90 | 98, rank 1 |
| Typo addresses | none | new card (Orta, P3): /inesta-…-modellerix 200 → /inesta-…-modelleri; /cocuk-…-modelleri- 301 → /gunes-gozlugu, point it at /cocuk-…-modelleri |

| Command | Result |
|---|---|
| `pytest tests/test_shop_review_347.py` | `50 passed` |
| fast suite, first run | `6 failed, 3204 passed` (all fixed: payload size, two catalog notes, a title sample, method version, product folders under a sitewide og:type; the 429 sitemap test passed alone, a timing flake) |
| full suite, `pytest -q -rfE -p no:cacheprovider` | `3395 passed, 4 skipped, 1 warning in 1074.29s (0:17:54)` |
| CI's lint (`compileall`, `ruff --select E9,F821,F841`) | `All checks passed!` |
| Push | `2af8d74` pushed on the owner's word (2026-11-16); CI run 43876848811 passed, 13:33:11-13:46:22 UTC (recorded with DECISIONS 348) |

## A rate-limited site: the reader takes the whole plan, Maya waits up to 90 s once per host, reads per source (2026-11-16, DECISIONS 348)

naturesgarden.net (Shopify), runs 7549f7ce, f105ec3c, 9269c4f8, from the saved data: Maya read 6 pages, then
/collections/all answered 429 with Retry-After: 60 and the crawl stopped; Firecrawl was asked for 7 addresses and read
all 7 (200 each; 0 × 403, 0 × 429, 0 challenge pages; 0 known addresses counted as "not requested" although 384 were
unread). Cause: the Akıllı "needed" reading sent only addresses Maya had asked for. Züber 2bf9b1ce read 148 because its
crawl counted as blocked (2 pages read), which skips that scope.

| | Before | After |
|---|---|---|
| Reader after Maya's rate limit or block | "needed" scope: 7 addresses | the plan, links and sitemap up to the page limit: up to 144 new pages for 9269c4f8 |
| Firecrawl 429 (its own or the site's) | the page failed, not asked again | asked once more after a 1.0-1.5 × jittered wait; concurrency steps down |
| Maya's Retry-After 31-90 s on a later page | stop | waited once per host, then asked again; a second long one stops |
| Kapsam / PDF / audit page | no per-source line | "Kaynaklar": Maya direct 7 asked, 6 read, 0 block, 1 × 429 (hız sınırında durdu); Firecrawl 7 asked, 7 read, 0 block, 0 × 429 |

Not done offline: the extra pages need Firecrawl (paid) calls. The 9269c4f8 team report is refused before and after by an
older check ("Teyit edin" title naming /cart).

| Command | Result |
|---|---|
| `pytest tests/test_rate_limit_handoff_348.py tests/test_rate_limited_start.py` | `27 passed` |
| fast suite, first run | `2 failed, 3269 passed` (expected text of the block-pages line and the coverage order; updated) |
| full suite, `pytest -q -rfE -p no:cacheprovider` | `3406 passed, 4 skipped, 1 warning in 991.62s (0:16:31)` |
| CI's lint (`compileall`, `ruff --select E9,F821,F841`) | `All checks passed!` |
| Push | NOT DONE (owner: don't push) |

## Appendix and sector downloads of naturesgarden.net 342a0b14 (2026-11-16, DECISIONS 349)

Reproduced with the app's own code (`create_app` + TestClient) on a scratch copy of the audit folder and a backup of
`web-v1.db`; the running app on 8770 was not touched (its API asks for the browser's session).

| | Before | After |
|---|---|---|
| `GET …/downloads/xlsx?lang=tr` | 409 `release_blocked` (RG-7: STR-3-58e82347, a blog post of type "unknown"); Chrome saved "xlsx.json" | 200, `maya-audit-naturesgarden.net-2026-11-16-ek-tr.xlsx`, 12 sheets, valid xlsx |
| `GET …/downloads/sector` | 409 `release_blocked` | 200, `maya-audit-naturesgarden.net-2026-11-16-sektor-audit.xlsx`, 5 sheets, valid xlsx |
| Release gate (current-engine copy) | BLOCKED (RG-7) | PASS (the 26 blog posts with a product widget left out of STR-3) |
| Pages read | Maya 6 (429 on the 7th request), Firecrawl 146 (146 distinct pages read) | same |

The running app needs a restart to load the fix.

| Command | Result |
|---|---|
| `pytest tests/test_download_blocked_349.py` | `7 passed` |
| fast suite, `pytest -q -rfE -p no:cacheprovider -m "not slow and not timing"` | `3278 passed, 4 skipped, 135 deselected, 1 warning in 550.48s (0:09:10)` |
| full suite, `pytest -q -rfE -p no:cacheprovider` | `3413 passed, 4 skipped, 1 warning in 974.48s (0:16:14)` |
| CI's lint (`compileall`, `ruff --select E9,F821,F841`) | `All checks passed!` |
| Push | NOT DONE (owner: don't push) |

## isbank review: place pages, profile page types in the Ek, template links, the reader's new pages (2026-11-16, DECISIONS 350)

isbank 1b81bee4 (Smart ~150, Bankacılık suggested), copy of `artifacts/` in a scratch folder; before = `git archive
HEAD`, after = this change. The 15 cards keep their order and severities.

| | Before | After |
|---|---|---|
| /ihtiyac-kredisi, /ek-hesap | mağaza / konum sayfası | Finansal ürün ve ürün listesi |
| "Sayfa bazında" types | diğer 123, blog 8, kategori 4, mağaza / konum 3, politika 3, ana sayfa 2, yardımcı 1 | Finansal ürün ve ürün listesi 42, Destek 39, diğer 32, Ücret ve başvuru 11, Hesaplama aracı 9, Rehber / SSS / blog 5, politika 3, ana sayfa 2, yardımcı 1 |
| Card 7 `idx6.alias_links` (124 pages) | generic steps | "Şablonda alt bilgideki “Çerez Ayarları” bağlantısını bir kez değiştirin" / "Yeni adresi: www.isbank.com.tr/" |
| Card 8 `idx6.links_to_redirect` (124 pages) | generic steps | "Şablonda menüdeki “Kredi” bağlantısını bir kez değiştirin" / "Yeni adresi: personalloanapp.isbank.com.tr/?amount=50000&term=24" |
| Kapsam "Engel sayfaları" | "en çok 2 sayfa okuyabilirdi, 91 sayfa okudu" | "Maya'nın okumadığı en çok 2 yeni sayfa okuyabilirdi, 0 yeni sayfa okudu (ayrıca Maya'nın okuduğu 91 sayfayı yeniden okudu)" |
| Team PDF | built | built (11 pages) |

Cards 7 and 8 are two different template links (footer and menu), not one link counted twice. atasunoptik's three store
pages stay "location".

| Command | Result |
|---|---|
| `pytest tests/test_bank_review_350.py` | `14 passed` |
| fast suite, first run | `1 failed, 3291 passed` (`test_blocked_reader_317` expected the line without the new counts; updated) |
| full suite, `pytest -q -rfE -p no:cacheprovider` | `3427 passed, 4 skipped, 1 warning in 960.88s (0:16:00)` |
| CI's lint (`compileall`, `ruff --select E9,F821,F841`) | `All checks passed!` |
| Push | NOT DONE (owner: don't push) |

## isbank follow-up: entry links kept, platform advice only on its platform, CMS edit addresses (2026-11-17, DECISIONS 351)

isbank 1b81bee4 (the audit the review called 690098d9: no such id in the history; its current-engine copy, rebuilt with
f5d8066, was used), copy of `artifacts/` in a scratch folder; before = `git archive HEAD`, after = this change.

| | Before | After |
|---|---|---|
| Card 8 | "Bağlantıları doğrudan son adrese verin" (P2, Sorun, `idx6.links_to_redirect`, 124 adres) | "Giriş ve başvuru bağlantılarının yönlendirmesini kontrol edin" (P3, Kontrol edin, `idx6.links_to_entry_redirect`); steps "Şablonda menüdeki “Kredi” bağlantısını tutun; kaldırmayın" / "Son adresi: personalloanapp.isbank.com.tr/?amount=50000&term=24" / "Yönlendirmesi kalıcıysa (301, 308) doğrudan son adrese verebilirsiniz" / "Menüdeki bağlantıyı asla kaldırmayın" |
| Card 8 in "Bağlantı yerleri" | 124 rows, "Önerilen hedef: kaldırın" | 124 rows, the final address |
| Card 7 "Ne yapılmalı" | the Shopify "within: collection" step | "Bağlantıları kanonik adresi gösterecek şekilde değiştirin. Bağlantıları bir şablon üretiyorsa (menü, alt bilgi, kart), bir kez orada değiştirin." |
| Card 7 in "Bağlantı yerleri" | none | 139 rows (page, link text, place, href, canonical), e.g. "Çerez Ayarları", altbilgi, /?efl--edit=1 → https://www.isbank.com.tr/ |
| /?efl--edit=1 | a page read, typed "category", a row of "Sayfa bazında" | not a page; Kapsam: "CMS düzenleme/önizleme adresleri ayrı sayfa sayılmadı: 1 okunan, 2 bağlantı verilen adres (/?efl--edit=1) …" |
| Pages read | 148 | 147 |
| Card 15 | sameAs (the homepage and its edit copy) | "Videodaki mesajı sayfaya metin olarak yazın" (sameAs now reaches one page and drops to the appendix) |
| Team PDF | built, 11 pages | built, 11 pages |

| Command | Result |
|---|---|
| `pytest tests/test_bank_followup_351.py` | `19 passed` |
| fast suite, first run | `1 failed, 3310 passed` (`test_wording`: the alias fix chosen at run time was not listed; added) |
| full suite, `pytest -q -rfE -p no:cacheprovider` | `3446 passed, 4 skipped, 1 warning in 1057.06s (0:17:37)` |
| CI's lint (`compileall`, `ruff --select E9,F821,F841`) | `All checks passed!` |
| Push | NOT DONE (owner: don't push) |

## Maya data in the audit: Search Console, AI citations, competitors (2026-11-17, DECISIONS 352)

Enpara fee70191 (copy of `artifacts/` in a scratch folder) with the exports in ~/Downloads (prompts, citation-mentions
1.46 M rows, result-items 164 129 answers, gsc-daily-stats, gsc-top-pages, gsc-query-intents; 15 Aug – 13 Nov), read in
about 20 s, compared with Efsa's "enpara-seo-tum-bulgular-2026-11-12_duzeltilmis (2).xlsx" (read in place, not copied).

| | Efsa | This build |
|---|---|---|
| GSC Sep / Oct (clicks, impressions) | 501069 / 7889507, 443676 / 5920594 | equal |
| AI citation rows Sep / Oct (all, Enpara) | 595542 / 34407, 372611 / 22078 | equal |
| Aug / Nov | 13 Aug – 11 Nov export | differ by the two-day export shift |
| Citation share per provider | ChatGPT 0.069 | 0.0692 |
| Top cited domains (prompts of 400) | Garanti 389, İş 388, Akbank 369, Yapı Kredi 368, Ziraat 361 | 389, 388, 369, 369, 361 |
| AI thresholds | ≥ 15 strong, < 7 few | equal |
| AI prompts per page | 125 pages in both | equal on 103, ±1–4 on the rest |
| Mon–Fri weeks from 13 Oct | Tue–Sat (one-day shift) | Mon–Fri |
| Share of voice | 0.09–0.19 | 0.04–0.08 (her source not in the exports) |
| Segments | 3: 32, 1: 8, 4: 10, 2: 29, 2b: 27, 5: 2, 6: 1, 0: 61 | 2b: 208, 5: 1, 0: 48 (no gsc-page-scores / gsc-search-performance) |
| Sayfa detay | 37 pages | 40 pages, 8 shared (no GSC impressions in the importance) |
| Rakip sheets | 12 topics | not built: topic-visibility-snapshots, competitor-mentions-daily, meta.json missing |

To export for www.enpara.com (13 Aug – 11 Nov): gsc-page-scores or gsc-search-performance, topic-visibility-snapshots,
competitor-mentions-daily, meta.json (gsc-top-queries, gsc-query-opportunities optional).

| Command | Result |
|---|---|
| `pytest tests/test_maya_data_352.py` | `15 passed` |
| fast suite, first run | `3 failed, 3323 passed` (an English "(s)", the results page's link list, the skill's Ek without the "Maya verisi eklenmedi" line; fixed) |
| full suite, `pytest -q -rfE -p no:cacheprovider` | `3461 passed, 4 skipped, 1 warning in 979.54s (0:16:19)` |
| CI's lint (`compileall`, `ruff --select E9,F821,F841`) | `All checks passed!` |
| Push | NOT DONE (owner: don't push) |

## Finding catalogue and the text check on every report (DECISIONS 353, 2026-11-17)

Requested by İlginay (SEO reviewer). VERIFIED locally; not pushed.

- `scripts/finding_catalogue.py export OUT.xlsx --home ~/.maya-audit/web`: 535 rows (319 rules, 16 platform/region
  variants, 9 merged cards, 25 Note topics, 1 generic text, 165 checklist items), counted over 79 saved audits (copies of
  the saved reports; the web home only read): 223 of the 319 rules triggered at least once.
- `scripts/finding_catalogue.py import EDITED.xlsx [--dry-run]`: writes the "Yeni …" texts back with placeholder, digit,
  length and step checks; refused rows listed in the diff report. The merged cards' texts moved to
  `maya_audit/merge_group_texts.json`.
- `maya_audit/text_gate.py` (RG-18–RG-23) before the team PDF, brief, XLSX and sector downloads; "Kontrol raporu" sheet;
  a blocking result makes the download a marked draft. Banned phrases: `maya_audit/banned_phrases.json`.
- Optional second reader (`llm_review.py`): off by default; needs `MAYA_AUDIT_ANTHROPIC_API_KEY` and the `anthropic`
  package, which is NOT installed in the venv (no install without approval), so it is NOT RUN on real reports.

Post-report check on the six saved audits (scratch copies; `scripts/text_check.py` and the appendix as downloaded):

| Audit | Findings | Cards | Result | Flagged |
|---|---|---|---|---|
| Enpara fee70191 | 80 | 15 | PASS | — |
| Atasun f06a2129 | 55 | 15 | PASS | — |
| Züber 2bf9b1ce | 43 | 9 | CONDITIONAL | RG-21 (soft): the coverage-limits line "Cloudflare rate-limited Maya's direct crawler on 1 of 2 request(s) …" is English in the report and the appendix |
| MMI 536b4b64 | 56 | 15 | PASS | — |
| Nature's Garden 342a0b14 | 49 | 8 | PASS | — |
| İş Bankası 1b81bee4 | 63 | 15 | PASS | — (an early version flagged "özetleyin" for the phrase "özetle"; phrases now match whole words) |

Planted problems in a copy of Atasun's cards (invented number, Shopify step, menu link to remove, English in a card,
a repeated card, "kritik öneme sahiptir"): all six found.

| Command | Result |
|---|---|
| `pytest tests/test_text_check_353.py` | `20 passed` |
| fast suite, first run | `1 failed, 3345 passed, 4 skipped, 135 deselected` (the skill-vs-web appendix test built the skill's file without the check; fixed, `test_team_report.py` 22 passed) |
| full suite, `pytest -q -rfE -p no:cacheprovider` | `3481 passed, 4 skipped, 1 warning in 965.69s (0:16:05)` |
| `python3.11 -m compileall`, `ruff --select E9,F821,F841` (source folders) | OK, `All checks passed!` |
| Push | NOT DONE (owner: don't push) |

## English left in Turkish reports (DECISIONS 354, 2026-11-17)

VERIFIED locally; not pushed.

- The Züber line (page reader's Kapsam line) is Turkish: the coverage line carries its check id.
- Sweep of all 79 saved audits (report copies in the scratchpad; team data and the XLSX as downloaded): 16 English
  sentences before, 0 after (older wordings in `wording.SAVED_TITLES` and `saved_titles`, the rest ordinary entries).
- 26 older saved audits could not build a team report (`external_scripts` saved as a number); fixed.
- Still flagged, left as found: repeated cards (RG-22) in moodisthastanesi.com 9156e1fd, e346db8d, b366e1c3 and
  adilehanim.com 88aff6d1; their downloads are drafts.
- Catalogue exported to `~/Downloads/bulgu-katalogu.xlsx` (535 rows; 319 rules). `anthropic` not installed (owner).

| Command | Result |
|---|---|
| `pytest tests/test_english_lines_354.py tests/test_text_check_353.py` | `24 passed` |
| fast suite | `3350 passed, 4 skipped, 135 deselected, 1 warning in 555.62s (0:09:15)` |
| full suite, `pytest -q -rfE -p no:cacheprovider` | `3485 passed, 4 skipped, 1 warning in 984.11s (0:16:24)` |
| `python3.11 -m compileall`, `ruff --select E9,F821,F841` (source folders) | OK, `All checks passed!` |
| Push | NOT DONE (owner: don't push) |

## One title, one card (DECISIONS 355, 2026-11-17)

VERIFIED locally; not pushed. Cards with the same title on the same pages are one card when they are one problem, else
titled apart (`client_selection.same_card`).

| Audit | Before | After |
|---|---|---|
| moodisthastanesi.com 9156e1fd | cards 3, 4 "Çelişen yapısal veri değerlerini giderin" (dateModified / name, same 2 pages); 15 cards; check BLOCKED (RG-22) | one card 3 with both findings; 14 cards; PASS |
| moodisthastanesi.com e346db8d | same pair; 15 cards; BLOCKED | one card; 15 cards; PASS |
| moodisthastanesi.com b366e1c3 | same pair; 15 cards; BLOCKED | one card; 15 cards; PASS |
| adilehanim.com 88aff6d1 | cards 12, 13 "http adreslerini https adreslerine yönlendirin" (www / apex); 3 Open Graph notes on 51 pages; 15 cards; BLOCKED | one card naming both domains; one Open Graph note; 14 cards; PASS |

All 79 saved audits: the text check flags nothing.

| Command | Result |
|---|---|
| `pytest tests/test_same_card_355.py` | `7 passed` |
| fast suite | `3357 passed, 4 skipped, 135 deselected, 1 warning in 565.19s (0:09:25)` |
| full suite, `pytest -q -rfE -p no:cacheprovider` | `3492 passed, 4 skipped, 1 warning in 1002.71s (0:16:42)` |
| `python3.11 -m compileall`, `ruff --select E9,F821,F841` (source folders) | OK, `All checks passed!` |
| Push | NOT DONE (owner: don't push) |

Push (owner: "push", 2026-11-17): DECISIONS 348–355 (`4a480f9`..`e21db34`) pushed to withmaya/seo-audit main; CI run
44129811114 on `e21db34` passed (16:47–17:00 UTC, job "fast": success).

## SaaS / Yazılım profile and its checks (DECISIONS 356, 2026-11-17)

VERIFIED locally; not pushed. Profile `saas` relabelled "SaaS / Yazılım" with eleven page types and weights; menu
("nav") and demo/trial signals; six profile-only rules (`checks/profile_rules.py`), live and offline.

| www.ticimax.com c77ebf6d | Before | After |
|---|---|---|
| Business type | Diğer (closest E-ticaret 4 / Kart 4 / SaaS 3) | SaaS / Yazılım (9) |
| Page types (147 read) | none typed | other 64, features 19, integrations 19, blog 11, references 7, policy 7, pricing 7, sales 6, guide 2, utility 2, demo 1, comparison 1, home 1 |
| Cards | 15 | 15; new "Fiyat sayfasına Offer işaretlemesi ekleyin" (4 pages) |
| Teyit edin (profile) | — | pricing as text 2, feature first paragraph 4, integrations as logos 3, story results 3 |
| Checklist (Geçti/Sorun/Veri eksik/İnceleme/Uygulanmaz) | 50/21/21/43/30 | 48/23/21/45/28 |

| Command | Result |
|---|---|
| `pytest tests/test_saas_profile_356.py` | `11 passed` |
| fast suite, first run | `4 failed, 3364 passed` (fixture sites now SaaS: the panel test's fresh re-run, the payload bound, brief words and catalogue explanations for the new rules; fixed) |
| fast suite | `3368 passed, 4 skipped, 135 deselected, 1 warning in 551.38s (0:09:11)` |
| full suite, `pytest -q -rfE -p no:cacheprovider` | `3503 passed, 4 skipped, 1 warning in 977.56s (0:16:17)` |
| `python3.11 -m compileall`, `ruff --select E9,F821,F841` (source folders) | OK, `All checks passed!` |
| Push | NOT DONE (owner: don't push) |

Push (owner: "push", 2026-11-17): `20bfe15` (DECISIONS 356) pushed; CI run 44142856394 passed.

## Maya sheets after the Ticimax review (DECISIONS 357, 2026-11-17)

VERIFIED; pushed as `90ecc55` (`20bfe15..90ecc55`), CI run 44163567764 success.

| Ticimax c77ebf6d (with Maya data) | Before | After |
|---|---|---|
| Page types vs "Sayfa bazında" | 8 of 9 shared pages differ; /e-ticaret-paketleri "diğer", /is-ortaklarimiz "ürün" | 0 differ; "Fiyatlandırma", "Entegrasyon" |
| "Rakip marka" filled | 0 / 18 topics (ikas.com counted as a comparison site) | 17 / 18 (ikas.com, shopify.com, ideasoft.com.tr) |
| Brand page in "Rakip - Sayfa yapısı" | homepage in 16 / 18 topics | homepage in 0 / 18; 11 different pages |
| Brand page shares | up to 329% (20 above 100%) | up to 100% (none above) |

| Command | Result |
|---|---|
| `pytest tests/test_maya_review_357.py tests/test_maya_data_352.py` | `21 passed` |
| fast suite | `3374 passed, 4 skipped, 135 deselected, 1 warning in 552.14s (0:09:12)` |
| full suite, `pytest -q -rfE -p no:cacheprovider` | `3509 passed, 4 skipped, 1 warning in 994.91s (0:16:34)` |
| `ruff --select E9,F821,F841` (source folders) | `All checks passed!` |
| Push | NOT DONE (owner: don't push) |

## The carpexonline.com review (DECISIONS 358, 2026-11-18)

VERIFIED; pushed as `9c766e2` (`90ecc55..9c766e2`, full suite `3520 passed, 4 skipped` before the push), CI run
44263523587 success. Report schema 1.33 (`crawl.host_moves`), page grouping method 6, Maya summary version 3.

| Carpex 5f049bf1 (saved data, with Maya data) | Before | After |
|---|---|---|
| 1. Pages read / why | 32 of 150; no reason given | Same 32 (needs a new crawl); Kapsam "Sınırın altında": 144 redirects to www.carpexonline.com not followed, sitemap on www not read |
| 2. Product pages in "Sayfa bazında" | diğer 19 | ürün 19 |
| 3. "Lider rakip" = carpex / carpex.com.tr in domains | 2 topics / 2 topics | 0 / 0; Kapsam names «carpex», 58 product names, carpex.com.tr, carpex.si, shop.carpex.si as the brand's own |
| 4. Non-topic labels as topics | intent:discovery, intent:comparison, intent:branded, intent:evaluation | none (they join their cluster: topic) |
| 5. Pages downloaded | the summary had no download step | choice read on every reading; live download NOT RUN (live requests) |
| Text check | PASS | PASS |

| Command | Result |
|---|---|
| `pytest tests/test_carpex_review_358.py` | `11 passed` |
| fast suite | `3385 passed, 4 skipped, 135 deselected, 1 warning in 554.76s (0:09:14)` |
| full suite | NOT RUN (before a push) |
| `ruff --select E9,F821,F841` (source folders) | `All checks passed!` |
| A new Carpex crawl (point 1 live) | NOT RUN (live request; owner's call) |
| Push | NOT DONE (owner: don't push) |

## The Carpex re-audit review (DECISIONS 359, 2026-11-18)

VERIFIED; pushed as `adf2478` (`9c766e2..adf2478`), CI run 44276291855 success. Page grouping method 7; `crawl.host_moves[].copies` (inner keys of schema 1.33).

| Carpex 1fd871f0 (saved data) | Before (`9c766e2`) | After |
|---|---|---|
| Text check | Taslak: RG-18, card 14 "105 sayfa" (11 + 94 added) | Geçti; card 14 "en az 94 sayfa" |
| Bare host serving pages | 20 pages as `idx4.variant` (canonical on www) | one card "Sitenin diğer adresini ana adrese yönlendirin" (20 sayfa); `idx4.variant` gone |
| /referanslarimiz, /bize-ulasin- | kategori, kategori | referans / güven sayfası, iletişim sayfası |
| Topic names | makine-bakim-enerji, kartus-maliyet, rakip-karsilastirma | Makine bakım enerji, Kartuş maliyet, Rakip karşılaştırma |
| Each page read once | — | needs a new crawl (NOT RUN) |

| Command | Result |
|---|---|
| `pytest tests/test_carpex_rerun_359.py` | `6 passed` |
| fast suite | `3390 passed, 4 skipped, 135 deselected, 1 warning in 571.28s (0:09:31)` |
| full suite | `3525 passed, 4 skipped, 1 warning in 1003.27s (0:16:43)` |
| `ruff --select E9,F821,F841` (source folders) | `All checks passed!` |
| A new Carpex crawl | NOT RUN (live request; owner's call) |
| Push | NOT DONE (owner: don't push) |

## İlginay's review of the MMI Ek (DECISIONS 360, 2026-11-18)

VERIFIED; pushed as `4d158c8` (`adf2478..4d158c8`, full suite `3534 passed, 4 skipped` before the push), CI run
44297021030 success. Source: İlginay (SEO team). No "Düzeltme kaydı" exists in the repository.

| Saved audit (scratch copy) | Before (`adf2478`) | After |
|---|---|---|
| MMI 536b4b64 | 14 cards, incl. "İç bağlantıları kanonik adrese yönlendirin" (148), "Başlığı olmayan sayfalara başlık yazın" (13), "Gizli H1 etiketlerini görünür yapın" (5), "Marka için sitede tek bir ad kullanın" (52); "Bağlantı yerleri" 0 rows | 10 cards (those four gone); "Yavaş sayfaları hızlandırın" says "ölçülen 7 sayfadan"; link cards name their links; "Bağlantı yerleri" 53 rows |
| İş Bankası 1b81bee4 | — | timeout card says its 7 measured pages; no-text card names its links |
| Atasun f06a2129, Carpex 1fd871f0 | — | broken-link and redirect cards name their first links |
| Enpara fee70191 | — | unchanged |
| Text check | PASS in all five | PASS in all five |

| Command | Result |
|---|---|
| `pytest tests/test_mmi_review_360.py` | `9 passed` |
| fast suite | `3399 passed, 4 skipped, 135 deselected, 1 warning in 560.86s (0:09:20)` |
| full suite | `1 failed, 3533 passed, 4 skipped, 1 warning in 984.00s (0:16:23)`: `test_fixture_matrix` (the generated `docs/FIXTURE-MATRIX.md` was not regenerated); regenerated with `scripts/fixture_matrix.py`, `tests/test_fixture_matrix.py` `3 passed` |
| `ruff --select E9,F821,F841` (source folders) | `All checks passed!` |
| Push | NOT DONE (owner: don't push) |

## The MMI re-check: platform advice and the Ek as the PDF (DECISIONS 361, 2026-11-18)

VERIFIED; pushed with `d1ef515` (`4d158c8..d1ef515`, full suite `3543 passed, 4 skipped` before the push), CI run 44314452104 success.

| Saved audit (scratch copy) | Before (`4d158c8`) | After |
|---|---|---|
| MMI 536b4b64 "Ne yapılmalı" naming another platform | 1 ("Shopify'da her varyantın barkod alanını doldurun") | 0 |
| Carpex 1fd871f0 (Ticimax) | 1 | 0 |
| Enpara, Atasun, İş Bankası | 0 | 0 |
| MMI "Bulgular", no-text links | generic engine fix | the card's steps and its named link |
| MMI "Yavaş sayfaları hızlandırın" Kapsam (Bulgular, Özet) | 3 | 3 sayfa (ölçülen 7 sayfadan; diğerleri de etkilenebilir) |
| Text check | PASS in all five | PASS in all five |

| Command | Result |
|---|---|
| `pytest tests/test_platform_advice_361.py` | `4 passed` |
| fast suite | `3403 passed, 4 skipped, 135 deselected, 1 warning in 570.36s (0:09:30)` |
| full suite | `3538 passed, 4 skipped, 1 warning in 976.12s (0:16:16)` |
| `ruff --select E9,F821,F841` (source folders) | `All checks passed!` |
| Push | NOT DONE (owner: don't push) |

## The MMI Ek with Maya data: the brand's former name, unrelated uploads, prompt categories (DECISIONS 362, 2026-11-18)

VERIFIED; pushed with `d1ef515` (`4d158c8..d1ef515`, full suite `3543 passed, 4 skipped` before the push), CI run 44314452104 success. `maya_data.VERSION` 4.

| "Rakip - Konu" (scratch copies) | Before (`4d0307f`) | After |
|---|---|---|
| MMI 536b4b64 rows | 17 (six prompt categories as topics) | 12 |
| MMI leader / gap | legalhomedelivery.com (the brand's former name) on 8 topics, gaps 23.7-83.9 | real rivals from the topic's AI answers (African + Eastern 7, CityDrinks 2, …), gaps -2.9 to -91.9 |
| MMI Kapsam | names of the unrelated files | "2 tanınmayan dosya kullanılmadı"; the names taken for the brand; topic assignment counts (54 labelled, 369 nearest topic, 160 off-topic labels, 12 none) |
| Carpex 1fd871f0 rows | 20 ("Kötü Koku Giderici" twice) | 19; leaders of 18 topics from the AI answers |
| Text check | PASS | PASS |

| Command | Result |
|---|---|
| `pytest tests/test_maya_brand_topics_362.py` | `5 passed` |
| fast suite | `3408 passed, 4 skipped, 135 deselected, 1 warning in 558.12s (0:09:18)` |
| full suite | `3543 passed, 4 skipped, 1 warning in 982.35s (0:16:22)` |
| `ruff --select E9,F821,F841` (source folders) | `All checks passed!` |
| Push | done with `d1ef515` |

## The review fix log and the SEO team's gaps (DECISIONS 363, 2026-11-18)

VERIFIED; pushed as `d11ddd4` (`d1ef515..d11ddd4`), CI run 44338300398 success. `maya_audit/fix_log.json` (76 items), `fix_log_status.json`, `tools/fix_log.py`; every Turkish
Ek gets "Düzeltme kaydı" (and "Önceki denetimden değişenler" when the site has a previous audit).

| Newest audit per domain (rebuilt from copies, 2026-11-18) | Items | Düzeltildi | Yeni tarama gerekli |
|---|---|---|---|
| Enpara fee70191 (11 Nov) | 37 | 36 | 1 (a JavaScript page not in the sample) |
| Atasun Optik f06a2129 (16 Nov) | 5 | 5 | 0 |
| Nature's Garden 342a0b14 (16 Nov) | 2 | 2 | 0 |
| İş Bankası 1b81bee4 (16 Nov) | 4 | 4 | 0 |
| Ticimax c77ebf6d (17 Nov) | 7 | 7 | 0 |
| Carpex 1fd871f0 (18 Nov) | 9 | 7 | 2 (pages read twice; the 32-page crawl) |
| MMI 536b4b64 (16 Nov) | 12 | 12 | 0 |
| Total | 76 | 73 | 3 (Hâlâ var 0, Kısmen 0) |

| Command | Result |
|---|---|
| `pytest tests/test_fix_log_363.py` | `15 passed` |
| `tools/fix_log.py --work <tmp> --write-status` (provider-free) | 7 audits rebuilt, text check PASS in all; 10 test files named by items passed |
| fast suite | `3423 passed, 4 skipped, 135 deselected, 1 warning in 555.15s (0:09:15)` |
| full suite | `3558 passed, 4 skipped, 1 warning in 979.41s (0:16:19)` |
| `ruff --select E9,F821,F841` (source folders, `tools/fix_log.py`) | `All checks passed!` |
| Push | done with `d11ddd4` |

## Image and file names (DECISIONS 364, 2026-11-19)

VERIFIED; pushed as `593be24` (`d11ddd4..593be24`), CI run 44473495261 success. New rule `tseo1.file_name_unsafe` (TSEO-1, S4 Düşük, Kontrol edin; checklist SEO-141
partial): image and file names with an unencoded space, an accent written as a combining mark, brackets or commas
(`maya_audit/file_names.py`; `analysis.file_names` in new crawls; saved audits offline via `_decisions_364`). A card of
this rule never names a template fix. Fix log item 77.

| Saved audit (rebuilt from copies, no request) | Before (`d11ddd4`) | After |
|---|---|---|
| MMI 536b4b64 | 10 cards | 11: card 5 "Görsel ve dosya adlarını düz, küçük harfli adlarla yükleyin", 240 files on 40 pages (combining marks: the Espolòn banner, first on the homepage row); no other card changed |
| Ticimax / İş Bankası / Enpara / Atasun | — | 26 / 6 / 2 / 1 file(s) |
| Carpex / Nature's Garden | — | none |
| Text check | PASS | PASS (all 7) |

| Command | Result |
|---|---|
| `pytest tests/test_file_names_364.py` | `7 passed` |
| fast suite | `1 failed, 3429 passed, 4 skipped, 135 deselected, 1 warning in 558.43s (0:09:18)`: the TR "why" text was 175 characters (limit 170); shortened, `tests/test_team_report.py` + `tests/test_file_names_364.py` then `29 passed` |
| full suite | `3565 passed, 4 skipped, 1 warning in 985.74s (0:16:25)` |
| `tools/fix_log.py --work <tmp> --write-status` (provider-free) | 7 audits rebuilt; 77 items: Düzeltildi 74, Yeni tarama gerekli 3; 11 test files passed |
| `ruff --select E9,F821,F841` (source folders, `tools/fix_log.py`) | `All checks passed!` |
| Push | done with `593be24` |

## Checklist ways of checking and the platform (DECISIONS 365, 2026-11-19)

VERIFIED; pushed as `2262e81` (`593be24..2262e81`); CI run 44489447004 success. Every checklist item says how it is checked (Otomatik 55 / Veri gerekir 37 / Uzman incelemesi
73), what data or why an expert, and how it could become automatic (64 could: S 21, M 37, L 6); 11 data items measured
from Maya's Search Console export (`maya_audit/checklist_maya.py`); the platform recognised from more signals, with a
confidence, in Kapsam and Özet (`site_platform`, `platform_text.advice_by_platform`). Fix log items 78 and 79.

| Saved audit (rebuilt from copies, no request) | Platform before (`593be24`) | Platform after | Otomatik / Veri gerekir / Uzman | Measured with Maya data | "Veri eksik" rows before -> after |
|---|---|---|---|---|---|
| MMI 536b4b64 | Next.js | Next.js (high, 20/20) | 55 / 37 / 73 | 11 | 26 -> 19 |
| Carpex 1fd871f0 | Ticimax | Ticimax (high) | 55 / 37 / 73 | 11 | 27 -> 20 |
| Enpara fee70191 | — | Sitefinity (medium, 1/20) | 55 / 37 / 73 | — (no Maya data) | 21 -> 21 |
| Atasun f06a2129 | — | — | 55 / 37 / 73 | — | 30 -> 30 |
| İş Bankası 1b81bee4 | — | — | 55 / 37 / 73 | — | 23 -> 23 |
| Ticimax c77ebf6d | — | Ticimax (high, X-Powered-By) | 55 / 37 / 73 | 8 (page scores only) | 21 -> 16 |
| Nature's Garden 342a0b14 | Shopify | Shopify (high, 6/6) | 55 / 37 / 73 | — | 25 -> 25 |

Cards and the text check unchanged in all 7 (PASS).

| Command | Result |
|---|---|
| `pytest tests/test_checklist_platform_365.py` | `6 passed` |
| fast suite, first run | `11 failed, 3425 passed`: Kapsam is never empty now (the platform row), the package data lacked `checklist_how.json`, the WordPress result's new keys, and a saved platform the pages do not confirm was given a confidence (counted as a change); fixed |
| fast suite | `3436 passed, 4 skipped, 135 deselected, 1 warning in 614.31s (0:10:14)` |
| full suite | `3571 passed, 4 skipped, 1 warning in 998.44s (0:16:38)` |
| `tools/fix_log.py --work <tmp> --write-status` (provider-free) | 7 audits rebuilt; 79 items: Düzeltildi 76, Yeni tarama gerekli 3 |
| `ruff --select E9,F821,F841` (source folders, `tools/fix_log.py`) | `All checks passed!` |
| Push | done with `2262e81` |

## Every problem in the Ek's Özet (DECISIONS 366, 2026-11-19)

VERIFIED; pushed as `9a3e474` (`2262e81..9a3e474`), CI run 44497027858 success. "Özet": the platform and "İlk N kart PDF raporundadır; diğer bulgular aşağıdadır." on top,
the PDF's cards as before, then "Diğer bulgular": every other problem group (S1-S4, Sorun / Kontrol edin / Fırsat; no
Info, no rejected finding, no Maya limit) with the cards' columns, by severity then priority. The PDF is unchanged.
Fix log item 80.

| Saved audit (rebuilt from copies, no request) | Cards (unchanged) | "Diğer bulgular" | Types | Text check |
|---|---|---|---|---|
| MMI 536b4b64 | 11 | 13 | Kontrol edin 13 | PASS |
| Carpex 1fd871f0 | 15 | 14 | Kontrol edin 9, Fırsat 3, Sorun 2 | PASS |
| Enpara fee70191 | 15 | 14 | Kontrol edin 14 | PASS |
| Atasun f06a2129 | 15 | 12 | Kontrol edin 12 | PASS |
| İş Bankası 1b81bee4 | 15 | 21 | Kontrol edin 18, Sorun 3 | PASS |
| Ticimax c77ebf6d | 15 | 18 | Kontrol edin 18 | PASS |
| Nature's Garden 342a0b14 | 6 | 15 | Kontrol edin 15 | PASS |

| Command | Result |
|---|---|
| `pytest tests/test_summary_others_366.py` | `2 passed` |
| fast suite | `3438 passed, 4 skipped, 135 deselected, 1 warning in 569.97s (0:09:29)` |
| full suite | `3573 passed, 4 skipped, 1 warning in 1009.30s (0:16:49)` |
| `tools/fix_log.py --work <tmp> --write-status` (provider-free) | 7 audits rebuilt; 80 items: Düzeltildi 77, Yeni tarama gerekli 3 |
| `ruff --select E9,F821,F841` (source folders, `tools/fix_log.py`) | `All checks passed!` |
| Push | done with `9a3e474` |

## Findings waiting for a check take card slots before Info cards (DECISIONS 367, 2026-11-19)

VERIFIED locally; not pushed. A "Teyit edin" group that is High/Blocker (always) or P0/P1 (while there is room) is a card,
"Kontrol edin", its PDF card opening with "Doğrulama bekliyor: …"; Info note cards fill only the slots left. PDF and
Özet match. Also fixed: "Bağlantı yerleri" failed when a note card with link rows had no PDF number. Fix log item 81.

| Saved audit (rebuilt from copies, no request) | Cards | Added | Left the cards | PDF = Özet | Text check |
|---|---|---|---|---|---|
| MMI 536b4b64 | 11 -> 13 | 1 "Ana içeriği sunucuda oluşturun" (Yüksek, P1), 4 "Yapısal veriyi sayfadaki bilgiyle eşleyin" (Orta, P1) | — (the 2 Info cards move to 12-13) | yes | PASS |
| Carpex 1fd871f0 | 15 -> 15 | — | — | yes | PASS |
| Enpara fee70191 | 15 -> 15 | — | — | yes | PASS |
| Atasun f06a2129 | 15 -> 15 | 3 "Ana içeriği data-nosnippet dışına çıkarın" (Yüksek) | "Ayrıştırılamayan JSON-LD'yi düzeltin" (Düşük, P3; now under "Diğer bulgular") | yes | PASS |
| İş Bankası 1b81bee4 | 15 -> 15 | — | — | yes | PASS |
| Ticimax c77ebf6d | 15 -> 15 | 2 "Ağır görselleri küçültüp sıkıştırın" (Orta, P1) | Info card "Küçük bağlantı ve etiket tutarsızlıklarını temizleyin" (appendix only) | yes | PASS |
| Nature's Garden 342a0b14 | 6 -> 6 | — | — | yes | PASS |

| Command | Result |
|---|---|
| `pytest tests/test_confirm_cards_367.py` | `5 passed` |
| fast suite | `3443 passed, 4 skipped, 135 deselected, 1 warning in 560.23s (0:09:20)` |
| full suite | `3578 passed, 4 skipped, 1 warning in 1192.73s (0:19:52)` |
| `tools/fix_log.py --work <tmp> --write-status` (provider-free) | 7 audits rebuilt; 81 items: Düzeltildi 78, Yeni tarama gerekli 3 |
| `ruff --select E9,F821,F841` (source folders, `tools/fix_log.py`) | `All checks passed!` |
| Push | NOT DONE (owner: don't push) |

## İlginay's review of "Diğer bulgular" (DECISIONS 368, 2026-11-19)

VERIFIED locally; not pushed. A homepage with many headings is never "too few" (product names as <h2> said instead);
headings compared with the page's own language; a canonical said only when every reading agrees and one is final
(raw vs rendered difference is its own finding); each page's line names the text, element and place; three link/address
findings in plain Turkish; the Özet's "Örnek" column, a problem without a concrete example left out of "Diğer
bulgular" and named by RG-24. Fix log items 82-88 (source İlginay).

| Saved audit (rebuilt from copies, no request) | Cards | Diğer bulgular | Left out, no example (RG-24) | Text check |
|---|---|---|---|---|
| MMI 536b4b64 | 13 -> 14 (+ "H2'yi ürün adlarına değil bölüm başlıklarına verin") | 11 -> 8 | 0 | PASS |
| Carpex 1fd871f0 | 15 | 14 -> 8 | 6 | PASS |
| Enpara fee70191 | 15 | 14 -> 12 | 2 | PASS |
| Atasun f06a2129 | 15 | 12 -> 10 | 2 | PASS |
| İş Bankası 1b81bee4 | 15 (+ raw/rendered canonical card, - "Ara ara zaman aşımına uğrayan sayfaları düzeltin") | 21 -> 15 | 6 | PASS |
| Ticimax c77ebf6d | 15 | 17 -> 9 | 8 | PASS |
| Nature's Garden 342a0b14 | 6 | 15 -> 11 | 4 | PASS |

| Command | Result |
|---|---|
| `pytest tests/test_review_368.py` | `9 passed` |
| fast suite | `3452 passed, 4 skipped, 135 deselected, 1 warning in 589.89s (0:09:49)` |
| `tools/fix_log.py --work <tmp> --write-status` (provider-free) | 7 audits rebuilt; 88 items: Düzeltildi 85, Yeni tarama gerekli 3 |
| `ruff --select E9,F821,F841` (source folders, `tools/fix_log.py`) | `All checks passed!` |
| Environment | Playwright's browser cache was missing; `playwright install chromium` restored it |
| Push | NOT DONE (owner: don't push) |

## Site-wide findings keep their place in the Özet (DECISIONS 369, 2026-11-19)

VERIFIED locally; not pushed. A site-wide or once-measured finding gets a site-level "Örnek" (the file or address
measured and its value, with the limit), else the first measured value of its rows; only a finding with no measured
value at all stays out (RG-24). Fix log item 89.

| Saved audit (rebuilt from copies, no request) | Diğer bulgular (368 -> 369) | Left out (RG-24) | Text check |
|---|---|---|---|
| MMI 536b4b64 | 8 -> 8 | 0 | PASS |
| Carpex 1fd871f0 | 8 -> 14 | 0 | PASS |
| Enpara fee70191 | 12 -> 14 | 0 | PASS |
| Atasun f06a2129 | 10 -> 12 | 0 | PASS |
| İş Bankası 1b81bee4 | 15 -> 21 | 0 | PASS |
| Ticimax c77ebf6d | 9 -> 17 | 0 | PASS |
| Nature's Garden 342a0b14 | 11 -> 15 | 0 | PASS |

| Command | Result |
|---|---|
| `pytest tests/test_site_examples_369.py` | `3 passed` |
| fast suite | `3455 passed, 4 skipped, 135 deselected, 1 warning in 607.94s (0:10:07)` |
| `tools/fix_log.py --work <tmp> --write-status` (provider-free) | 7 audits rebuilt; 89 items: Düzeltildi 86, Yeni tarama gerekli 3 |
| `ruff --select E9,F821,F841` (source folders, `tools/fix_log.py`) | `All checks passed!` |
| Push | NOT DONE (owner: don't push) |

Pushed `cb2779b`, `21e816d` and `bf259c2` after the full suite (`3590 passed, 4 skipped, 1 warning in 995.15s
(0:16:35)`); CI run 44562213151 started, its result not read yet (GitHub unreachable from this machine at the time).

## A robots.txt finding only where its rule blocks (DECISIONS 370, 2026-11-19)

VERIFIED locally; not pushed. ACC-6 is attached only to the addresses its bots are blocked on, each with the rule and
the bots, plus one site-wide line (its Özet example); no address says "engellenen botlar" for a bot that can fetch it;
ACC-2's blocked addresses carry the same line. Fix log item 90.

| Saved audit (rebuilt from copies, no request) | ACC-6 rows | "engellenen botlar" rows | "Bulgu bazında" rows | Text check |
|---|---|---|---|---|
| MMI 536b4b64 | 150 -> 5 (/profile/gift-cards) | 150 -> 0 | 1764 -> 1619 | PASS |
| Enpara fee70191 | 150 -> 15 | 150 -> 0 | 1365 -> 1230 | PASS |
| Nature's Garden 342a0b14 | 125 -> 10 | 125 -> 0 | 1026 -> 911 | PASS |
| Carpex, Atasun, İş Bankası, Ticimax | no ACC-6 finding | 0 | unchanged | PASS |

| Command | Result |
|---|---|
| `pytest tests/test_robots_rows_370.py` | `5 passed` |
| fast suite | `3460 passed, 4 skipped, 135 deselected, 1 warning in 565.12s (0:09:25)` |
| `tools/fix_log.py --work <tmp> --write-status` (provider-free) | 7 audits rebuilt; 90 items: Düzeltildi 87, Yeni tarama gerekli 3 |
| `ruff --select E9,F821,F841` (source folders, `tools/fix_log.py`) | `All checks passed!` |
| Push | NOT DONE (owner: don't push) |

Pushed `f37e100` after the full suite (`3595 passed, 4 skipped, 1 warning in 1005.43s (0:16:45)`); CI run 44589238029
started, its result not read yet. `bf259c2`'s CI run 44562213151: success.

## İlginay's second review: Nature's Garden Ek (DECISIONS 371, 2026-11-19)

VERIFIED locally; not pushed. Every card has an "Örnek" (RG-24 names an empty one); an <h1> a screen reader reads is not
"hidden"; a heading with a common word of the page's language is in it, another needs 4+ words, repeats count once;
"no products" only with 0 in the HTML and the rendered page; account, sign-in and cart pages leave RND-1/RND-3; dead
links and shared heading jumps say what is wrong; the small-fixes card names the empty tag. Fix log items 91-97.

| Saved audit (rebuilt from copies, no request) | Cards | Cards with empty Örnek | Diğer bulgular | Text check |
|---|---|---|---|---|
| MMI 536b4b64 | 14 | 8 -> 0 | 8 -> 8 | PASS |
| Carpex 1fd871f0 | 15 | 7 -> 0 | 14 -> 14 | PASS |
| Enpara fee70191 | 15 | 4 -> 0 | 14 -> 14 | PASS |
| Atasun f06a2129 | 15 | 9 -> 0 | 12 -> 11 (no empty collection) | PASS |
| İş Bankası 1b81bee4 | 15 | 5 -> 0 | 21 -> 21 | PASS |
| Ticimax c77ebf6d | 15 | 7 -> 0 | 17 -> 17 | PASS |
| Nature's Garden 342a0b14 | 6 | 2 -> 0 | 15 -> 12 (hidden H1, heading language, /account/login gone; collections 4 -> 1) | PASS |

| Command | Result |
|---|---|
| `pytest tests/test_ng_review_371.py` | `8 passed` |
| fast suite | `3468 passed, 4 skipped, 135 deselected, 1 warning in 560.05s (0:09:20)` |
| `tools/fix_log.py --work <tmp> --write-status` (provider-free) | 7 audits rebuilt; 97 items: Düzeltildi 94, Yeni tarama gerekli 3 |
| `ruff --select E9,F821,F841` (source folders, `tools/fix_log.py`) | `All checks passed!` |
| Push | NOT DONE (owner: don't push) |

Pushed `9a922d5` after the full suite (`3603 passed, 4 skipped, 1 warning in 979.59s (0:16:19)`); CI 44599690850:
success. `f37e100`'s CI 44589238029: success.

## Efsa's revision-compliance review: expert lock, error families, fix log, bugs (DECISIONS 372, 373, 2026-11-19)

VERIFIED locally; not pushed. The expert lock (83 active labels from 80 reviewed cards, frozen noted audits outside the
repository), error-family tests, the fix log's three states with a test linked to every item, note import, version
stamp, unapproved rules as "Kontrol edin", İlginay's NG follow-ups, and bugs F01 / missing-as-0 / short brand names.
CI wiring of the frozen set waits for the secret MAYA_AUDIT_BENCHMARK_URL (until then CI warns that the lock did not run).

| Saved audit (rebuilt from copies, no request) | Cards | Diğer bulgular | Now "Kontrol edin" | Other | Text check |
|---|---|---|---|---|---|
| MMI 536b4b64 | 14 | 8 -> 8 | — | — | PASS |
| Carpex 1fd871f0 | 15 | 14 -> 14 | lastmod card (questioned rule) | — | PASS |
| Enpara fee70191 | 15 | 14 -> 14 | — | table row renamed | PASS |
| Atasun f06a2129 | 15 | 11 -> 11 | lastmod card | — | PASS |
| İş Bankası 1b81bee4 | 15 | 21 -> 21 | — | table row renamed | PASS |
| Ticimax c77ebf6d | 15 | 17 -> 17 | lastmod card | — | PASS |
| Nature's Garden 342a0b14 | 6 | 12 -> 10 | lastmod card | unrendered collection and 1 of 7 429s to "Kapsam" | PASS |

| Command | Result |
|---|---|
| `scripts/real_sites_benchmark.py expert` (frozen 2e5829fb, fee70191, 536b4b64, 342a0b14) | all labels hold |
| Proof: DECISIONS 368's English question words reverted in a scratch copy | `79 labels: 78 hold, 1 red` (mmi-R368-2-heading-language), exit 1 |
| new tests | test_bugs_372 8, test_expert_lock 4, test_error_families_373 18, test_review_compliance_373 10 |
| fast suite (with the frozen set) | `3509 passed, 4 skipped, 135 deselected, 1 warning in 577.64s (0:09:37)` |
| `tools/fix_log.py --work <tmp> --write-status` | 112 items: Düzeltildi 109, Hâlâ var 0, Doğrulanmadı 3 (new crawl needed); 84 labels checked, 0 red |
| `ruff --select E9,F821,F841` | `All checks passed!` |
| Push | NOT DONE (owner: don't push) |
