# Client reporting reliability — 16 October 2026

## Spec (maya-spec-writer)

Problem: clients can receive a healthy score without assessment, unsupported fixed claims,
hash values as text evidence, and unchecked factual recommendations.

Confirmed offline at `7f56673` with existing Python; commands:
`MAYA_AUDIT_ENV_FILE=/tmp/maya-report-reliability/nonexistent.env MAYA_AUDIT_HOME=/tmp/maya-report-reliability/home PYTHONPYCACHEPREFIX=/tmp/maya-report-reliability/pycache .venv/bin/python /tmp/maya-report-reliability/reproduce.py`
and the same environment with `/tmp/maya-report-reliability/repro_extra.py`.
Reproducers use only synthetic in-memory reports and temporary output.

| Target / source | Actual | Required |
| --- | --- | --- |
| `from_maya_report.score` | Empty input = 100; one page defect = 96, adding 1,000 sitemap checks = 98 | No assessment = unavailable; page scoring independent of unrelated URL counts |
| `from_maya_report.diff` | Missing newer assessment = fixed; changed title with same id = fixed + new | Comparable pass and full affected scope required; otherwise unknown |
| `page_facts_from_report` | `[12345678,98765432]` becomes source text | Hash sketches never text; native/provider observations separate |
| `validate_cards` | Changed fee 10 → 99 and nested `Brand` code both exit 0 | Recursively check visible fields and numeric facts; cite exact evidence fields |
| `validate_cards` | Date string alone satisfies live-verification gate | URL/check/time/evidence/conclusion records, explicit sample scope |
| `render_report` | Direct invalid input writes HTML, exit 0 | Final rendering validates without mutating; explicit watermarked draft only |

Evidence review (maya-report-checker): these synthetic claims are false/unsupported;
no real page copies or customer history were consulted. Engine `models.to_jsonable` deliberately
removes `_visible_text`; `analysis.text_sketch` contains integer hashes. Firecrawl report rows
record outcome/status/observed_at, not raw page text. Native crawl analysis is not provider content.
Existing web comparison already avoids saying fixed, but uses normalized titles and only requires
one named URL reread; reuse of that weaker rule would not satisfy final-report requirements.

Exact change: keep the application report schema 1.14 and web behavior intact. Add a shared helper
inside the reporting skill for assessment scope, conservative comparison, source observations and
structured verification. Update converter, validator and renderer plus reporting references. Bump
**cards contract to 2**: score status/scope, unknown comparisons, evidence provenance, structured live
verification and reviewed recommendation references. Old cards can be rendered only as explicit drafts.
Retain documented severity transformations, weights, floors and per-check caps for supported assessment.
Partial scores stay draft and explicitly scoped; unavailable scores are null, never 100.

Regression tests: empty/missing/partial and complete healthy assessment; denominator stability;
unassessed vs genuinely resolved, title changes, truncated/changed scope, missing provider;
hash vs readable fields and conflicting native/provider observations; nested text/code, changed
numbers, field-specific missing references, incomplete/sample verification; invalid final direct API/CLI,
valid final and labeled draft without input mutation. Tests live in normal `tests/` discovery.

Do not change providers, application checks, configuration, spending, retention, resume or LG-101.
No real re-test is needed in this round (cost zero); owner can later authorize a saved-report review
or live recheck separately. Automated checks establish structure, traceability and lexical/numeric
consistency, never semantic truth. Human/model review remains required for recommendations.

## Implementation and validation notes

- Implementation stays in `.agents/skills/maya-audit-rapor/`; no engine report schema or app behavior changes.
  `scripts/reliability.py` is the shared source of assessment, comparison and evidence rules.
- Normal discovery: `.venv/bin/python -m pytest ... tests/test_client_reporting.py`; all new fixtures are synthetic.
  Isolated runner `/tmp/maya-report-reliability/run_tests.py` starts pytest with an environment allowlist,
  nonexistent MAYA_AUDIT_ENV_FILE, temporary MAYA_AUDIT_HOME/TMPDIR/cache/bytecode/pytest/output paths.
- Focused run 1: **29 passed, 1 failed** (0.62 s). Failure: single-text rendering lacked the semantic-review caveat.
  Added caveat to the common footer. Run 2: **35 passed** (0.77 s). Expanded scope/newer-timestamp checks:
  run 3 **37 passed** (0.77 s). Further focused run: **41 passed** (0.80 s), including signed/percentage/currency
  changes and missing assessment denominators. No assertions were weakened and no application tests were altered.
- PDF QA uses a synthetic partial assessment, real final validation, installed Chromium and embedded fonts.
  External HTTP(S) routing is blocked during rendering. PyMuPDF/Poppler are unavailable; no dependency installed.
  `pypdf` inserts spaces around some Turkish glyphs (initial exact-word QA failed on Başlık); preserve that result.
  Whitespace-normalized checks establish text presence only, not exact copy/paste fidelity. macOS sips supplies
  page PNGs for visual inspection. PDF text/copy fidelity remains a limitation, not a new application failure.

- Final focused checks after coverage and cross-page/provenance guards: **47 passed** (0.82 s).
  Source reports/configuration/customer data were not changed. The existing partial-score box now wraps
  its longer label; this is a small correctness fix, not a report redesign.

## Final verification (maya-verifier, offline baseline mode)

Commands (existing `.venv`, isolated runner described above):

```text
.venv/bin/python /tmp/maya-report-reliability/run_tests.py tests/test_client_reporting.py
.venv/bin/python /tmp/maya-report-reliability/run_tests.py
.venv/bin/python scripts/fixture_matrix.py  # isolated environment; generated documentation only
.venv/bin/python /tmp/maya-report-reliability/run_tests.py tests/test_client_reporting.py tests/test_fixture_matrix.py
```

Each test command expands to `.venv/bin/python -m pytest -q -ra -p no:cacheprovider
--basetemp=<temporary-work>/pytest --junitxml=<temporary-work>/results.xml [test paths]`.

- Pre-full focused run: **47 passed, 0 failed, 0 errors, 0 skipped in 0.82 s**.
- One full run on HEAD `7f56673` plus this round's working-tree changes:
  **1,408 passed, 1 failed, 0 errors, 1 skipped in 513.90 s** (515.77 s runner wall time).
- Original failure: `tests/test_fixture_matrix.py::test_the_matrix_file_matches_the_tests`.
  The new reporting regression names IDX-5, so its generated inventory count changed from 9 to 10.
  Regenerated `docs/FIXTURE-MATRIX.md` using the existing generator; two generated lines changed.
  This is documentation drift introduced by the new test, not an application failure or environment restriction.
- Post-sync focused check: **50 passed, 0 failed, 0 errors, 0 skipped in 3.12 s**.
  This includes all 47 new reporting cases and all three matrix tests. The full suite was not rerun.
  SHA-256 manifest confirms no reporting code/assets/references/tests changed after the full run.
- Expected skip: `tests/test_evidence_integrity.py::test_the_moodist_live_report_shows_its_partial_pass`:
  live-run examples are not committed. One existing FastAPI/Starlette httpx deprecation warning.
- Full-run evidence: `/var/folders/10/dlfrps1x6rnc6py046hx23_w0000gn/T/maya-report-tests-q195ya9h/`
  (`pytest.log`, `results.xml`, `tested-files.json`, `command.json`).
  Post-sync evidence: `/var/folders/10/dlfrps1x6rnc6py046hx23_w0000gn/T/maya-report-tests-vvgicepa/`.
- Synthetic PDF: three pages visually inspected after score-label wrapping, no overlap or unreadable glyphs.
  Existing pagination leaves a card footer on the next page and an almost-empty appendix page. No redesign attempted.
  Exact text extraction/copy fidelity remains unverified because of pypdf spacing and unavailable PyMuPDF/Poppler.

Verdict: reporting regressions PASS; full run recorded FAIL due stale generated documentation, corrected and
focused-verified afterward. No claim of a subsequent all-green full run. No confirmed engine/web failure remains
from this run. Semantic truth and reviewer-record authenticity require review beyond lexical/numeric checks.
Next reporting task: dependable PDF text-layer verification and pagination, then testing reviewed v2 evidence
imports from saved provider documents (without changing retention). LG-101 remains open. Release verification: NOT RUN.

## Committed-state revalidation — 16 October 2026

Verified Git root `/Users/YOUR_USER/Desktop/maya-audit-checklist 2`, branch `stage1-integration`,
HEAD `b3438dcf8ba12e9cf1a29635e557d3e2ee44fab3`. Only the original untracked `.claude/` was present.
The four reporting fixes, specification and regression fixtures were already committed. Inspection and
synthetic regression checks found no need to duplicate those changes. Engine/web/dependencies remain
unchanged from `a697158`. This follow-up changes only this verification record.

Commands, with the same isolated environment allowlist and fresh temporary storage described above:

```text
.venv/bin/python /tmp/maya-report-reliability/run_tests.py tests/test_client_reporting.py tests/test_fixture_matrix.py
.venv/bin/python /tmp/maya-report-reliability/qa_recheck.py
.venv/bin/python /tmp/maya-report-reliability/run_tests.py
```

| Check | Passed | Failed | Errors | Skipped | Pytest time |
| --- | ---: | ---: | ---: | ---: | ---: |
| Reporting + matrix | 50 | 0 | 0 | 0 | 4.93 s |
| Full offline suite on committed b3438dc | 1,409 | 0 | 0 | 1 | 519.32 s |

Full-run subprocess wall time: 521.30 s. One full run in this follow-up; no diagnostic reruns.
The expected live-example skip and FastAPI/Starlette httpx deprecation warning remain as described above.
The previous stale-inventory failure is retained in the earlier record; the current committed full run
passes that check. No reporting code or tests changed during this verification.

Evidence directories (exact pytest argv in each command.json; output in pytest.log/results.xml):
- Focused: `/var/folders/10/dlfrps1x6rnc6py046hx23_w0000gn/T/maya-report-tests-27g127hc/`.
- Full: `/var/folders/10/dlfrps1x6rnc6py046hx23_w0000gn/T/maya-report-tests-0qt0wxl5/`.
- New synthetic PDF: `/var/folders/10/dlfrps1x6rnc6py046hx23_w0000gn/T/maya-report-pdf-recheck-f6bm6p4q/`.

Three new PDF page rasters were visually inspected. The partial label fits its box, and Turkish glyphs
are visible. pypdf still inserts spaces inside some words; exact copy/paste fidelity is not verified.
The split card footer and almost-empty appendix remain existing pagination limitations. No packages
were installed; no real audits, provider caches, credentials or processes were modified.

Current verdict: **BASELINE PASS on b3438dc**, limited to the offline suite and synthetic reporting fixtures.
Automated consistency cannot certify semantic truth or reviewer-record authenticity. Scores remain
uncalibrated drafts. The next reporting priority remains PDF text-layer verification and pagination.
LG-101 remains open. **Release verification: NOT RUN.**
