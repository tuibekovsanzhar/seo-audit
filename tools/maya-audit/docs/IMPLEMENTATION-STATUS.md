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

## Next step

1. A live nihan Standard 500 run on this code (owner's explicit request needed: it is paid and live).
2. Push to withmaya/seo-audit when the owner asks.
3. Backlog: `docs/BACKLOG.md`.
