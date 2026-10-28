# Implementation status

Tracks `docs/Maya-Audit-Claude-Code-Uygulama-Rehberi-2026-10-28.md` (the guide). Status values: NOT_STARTED,
IN_PROGRESS, VERIFIED, BLOCKED_ON_INPUT. A command that was not run is written NOT RUN, never implied as passed.

Source: `~/Projects/maya-audit`, Git repo created from `maya-audit-0.2.8-w13-2026-10-28.zip`, baseline commit `a40500b`.
Branch `main`, no remote, nothing pushed. Package 0.2.8. Interpreter `.venv/bin/python` = CPython 3.13.1 (macOS arm64).
`HANDOVER.md` not available. Call map and code-level findings: `docs/architecture/baseline.md`.

| Stage | Status | Note |
|---|---|---|
| 00 Baseline | IN_PROGRESS | Baseline, call map, test state recorded. Step 7 (`tests/fixtures/quality/`) not started |
| 01 Packaging | NOT_STARTED | |
| 02 Result contract | NOT_STARTED | |
| 03 Rule identity | NOT_STARTED | |
| 04 Shared finalization | NOT_STARTED | |
| 05 Shared service (CLI/batch/web) | NOT_STARTED | |
| 06 Output generations | NOT_STARTED | |
| 07 Source/page type/scope/render | NOT_STARTED | |
| 08 Rule contract + catalogue | NOT_STARTED | |
| 09 One publication gate | NOT_STARTED | |
| 10 URL-level report | NOT_STARTED | |
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
6. `idx6.broken` (broken internal link) has no entry in `rule_actions.json`. → M1.

**Isolation:** `tests/conftest.py` blocks non-loopback sockets and public DNS in-process. Child processes use
`tests/offline_process.environment()` (temp HOME/MAYA_AUDIT_HOME/XDG dirs, absent `.env`, Firecrawl off, a
`sitecustomize` guard). The real `.env` was not read. The browser-path gap above is the one isolation defect found.

**Remaining for stage 00:** step 7, the small in-memory quality fixture set (`tests/fixtures/quality/`: broken internal
link, working counterpart, raw/render difference, partial crawl, healthy pagination), with expected results written
independently of current output. Planned as the first M1 task. Optional: fix the browser-path pass-through in
`tests/offline_process.py` and the `alpha.json` test path (each a one-line test change; not done, out of scope).
