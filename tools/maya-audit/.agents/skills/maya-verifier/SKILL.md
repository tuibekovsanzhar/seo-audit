---
name: maya-verifier
description: Use to verify current Maya Audit development code offline, or perform full package verification when release preparation is explicitly requested; never fix code.
---

Follow the shared preamble in the root `AGENTS.md` (environment, untrusted data, evidence model, length budget,
platform matrix, handoffs, live network, shared limits). Run sequentially in the current session; no separate agent
is required. Paths are relative to the project root (the folder holding `pyproject.toml`).

You verify; you never fix. Do not edit, create or delete anything inside the project folder. If something fails, report
it with the output and stop.

## Isolation (both scopes)

Set `MAYA_AUDIT_HOME` to a fresh directory under `<tmp>`, `MAYA_AUDIT_ENV_FILE` to a nonexistent file there, the
temporary directory variable to a private subdirectory (site locks: `TMPDIR` on POSIX, `TEMP` and `TMP` on Windows),
and `PYTHONPYCACHEPREFIX` there. Use `--basetemp=<tmp>/pytest` and `-p no:cacheprovider` (on Windows keep `<tmp>` short:
deep pytest folders exceed the 260-character path limit and fail tests for that reason alone). Remove provider
credentials from the child process environment by variable name without reading or printing their values. Fixtures,
mock providers and loopback fake servers only; no live websites or provider requests. Do not run alongside another
suite using the same locks. Preserve real storage and existing processes. Verify the isolation controls in
`tests/conftest.py` and the storage configuration before either scope. Before a demo, check the port and report any
conflict; never terminate an existing process. Stop only a demo you started.

## Source state (always first)

Record what is being verified, and say it in the report:
- a commit: `git rev-parse HEAD` with a clean `git status --short`; or
- a working-tree snapshot: base commit, branch, and every modified/untracked file included (the
  `RELEASE-SNAPSHOT.json` form); or
- not a Git checkout (a team-preview zip): say so and identify it by archive name and `RELEASE-SNAPSHOT.json`.

Build any archive from the same source state you tested. Never describe a working-tree snapshot as "from the last
commit".

## Baseline scope (development)

Perform only the source-state record, the static gates and the full offline suite in the current tree with the
existing venv. Do not build archives, install packages, create an environment, launch demo apps, or generate reports.
Report the results table and verdict, explicitly scoped to BASELINE; mark release steps NOT RUN, never PASS. Baseline
success does not authorize or establish release readiness.

Static gates (always):
1. `<venv-python> -m ruff check --isolated --select E9,F821,F841 maya_audit maya_audit_web maya_audit_web_lite.py`.
2. Compile with the lowest Python in `requires-python`: `<python3.11> -m compileall -q maya_audit maya_audit_web tests`.
   If that interpreter is not installed, write "lowest Python: NOT RUN".
3. Run the CLI once against a loopback fake site with stdout redirected to a file
   (`<venv-python> -m maya_audit crawl <loopback-url> --json <tmp>/out.json > <tmp>/console.txt`) and confirm
   `out.json` exists and parses.
4. Tests collected versus tests passed. "N collection errors" is FAIL, never "skipped".
5. Dependencies: `pip-audit` against the installed environment when it is available, otherwise "pip-audit: NOT RUN".

Full suite: `<venv-python> -m pytest -q -ra -p no:cacheprovider`. Do not rely on a historical duration: use a timeout of
at least 30 minutes and report the measured seconds.

Platform matrix: state the OS and every Python version actually run. If you cannot run Windows (or macOS/Linux), write
"<platform>: NOT RUN" — never imply it passed.

## Full release verification (explicit release preparation only)

Only an explicit release-preparation request activates these steps. Fresh environments and pip installs are confined
to temporary clean copies under `<tmp>`; never rebuild the project's existing venv. The release mode (A tagged or
B working-tree snapshot) comes from maya-release.

1. Source state as above, the static gates and the full suite in the project.
2. Build the archive into `<tmp>`, never onto the Desktop, from the same source state:
   mode A, run in `tools/maya-audit/` so only the tool's folder is archived,
   `git archive --format=zip --prefix=maya-audit-verify/ -o <tmp>/verify.zip <tag-or-commit>`; mode B exactly
   the files listed in `RELEASE-SNAPSHOT.json`. Check archive member names without opening secrets: no `.env` or secret
   config, no root `HANDOVER.md`, no `design-reference/`, no `.claude/`. If exclusions are missing, FAIL and stop; do
   not silently alter the archive.
3. Unzip in `<tmp>` and follow TEAM-SETUP.md with a new venv there and `pip install -e ".[team]"` (POSIX
   `.venv/bin/pip`, Windows `.venv\Scripts\pip.exe`). pip is the only network use allowed.
4. Demo app from the clean copy, with `MAYA_AUDIT_HOME=<tmp>/home`, on port 8791 (8770 is the owner's):
   `<clean-venv-python> -m maya_audit_web --demo --port 8791`. Check the page answers 200, run one demo audit of
   `http://demo-shop.localhost/` through `/api/v1` and fetch its PDF. Stop the app and confirm the port is free.
5. Suite in the clean copy as the guide says: `pip install -e ".[dev]"`, then `<clean-venv-python> -m pytest -q -ra`.
   Treat any historical skip count as an expectation to check, not permission to ignore a new skip.
6. PDF inspection: render page images of (1) the first summary page, (2) one table page, (3) one finding detail page,
   (4) one action page and (5) the last appendix page. List each by page number and what you checked. "Visually
   inspected" without page numbers is NOT RUN.
7. Report length: for each client PDF, total pages, main-section card count and appendix card or row count. FAIL a
   client report over the page budget (preamble 4: 15 pages unless the owner set another).

## Report

A table: step, PASS / FAIL / NOT RUN, numbers (collected / passed / failed / skipped, seconds). List every failed test by
name and every skip with its reason. Then the source state, the OS and Python versions run, the PDF pages inspected by
number and the page/card counts. End with one line: `VERDICT: PASS` or `VERDICT: FAIL`, and the commit or snapshot you
verified. A test that failed once and passed on a re-run is reported as intermittent, not as a pass.

## Audit-accuracy changes and client exports

For substantive judgment changes, require the maya-judgment-validator record (YAML) including its false-negative sweep.
Check, as separate items:
1. The record has exact observed output, saved-source identity/time, an offline reproduction, and a contrasting defect
   that must remain detected.
2. At least two examples from sites other than the one that motivated the change (fake sites count; say which).
3. Original failures, reruns, pre-existing failures and environment restrictions are kept apart.
4. Engine output, counters, per-page occurrence counts, unique page counts and shared-template groups agree.
5. Finding cards, actions and both technical/client HTML/PDF exports agree with the engine. Equal titles alone do not
   establish semantic identity.
6. Drafts, review and live verification stay distinct; missing evidence stays uncertain, never healthy or fixed.
7. Replays use only copied local evidence with original collection/cache times and a separate processing timestamp;
   never describe a replay as live.
8. Every genuinely supported severe defect is preserved.
