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
| 05 Shared service (CLI/batch/web) | IN_PROGRESS | CLI and web use `final.seal`; batch and skills not moved |
| 06 Output generations | NOT_STARTED | |
| 07 Source/page type/scope/render | IN_PROGRESS | H1 only: raw HTML vs rendered page per page (`h1_sources`) |
| 08 Rule contract + catalogue | IN_PROGRESS | Missing catalogue is an error; actions for idx6.broken and every H1 rule |
| 09 One publication gate | IN_PROGRESS | Every web report download and the final client export gated; CLI writes and warns; batch not gated |
| 10 URL-level report | IN_PROGRESS | Broken-link cards (page, link text, target, status, replacement unknown) in Markdown and PDFs |
| 11 Team status vs engine verification | NOT_STARTED | |
| 12 SEO accuracy measurement | BLOCKED_ON_INPUT | Needs human SEO labels; nothing labelled yet |
| 13 Integration and release | NOT_STARTED | |

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
