# Client reports in the normal application

Owner-requested specification, 2026-10-16; starting commit 61af28f.

Confirmed gaps: profile API accepts brand_aliases and related_organizations but its form omits them;
normal results have only technical downloads; hardened client-card tooling has no application persistence/editor.
Generating cards previously required a manual CLI. Normal and client reports are separate formats.

Implement the two confirmed-name lists in the existing bilingual profile form. Names are owner-confirmed,
not independent proof of an organizational relationship. Preserve omitted fields for API compatibility.

Extract the installed hardened converter, validator and renderer into a packaged Python library. Retain
skill CLI compatibility entry points; never restore ZIP code. Keep cards contract 2 and audit schema 1.14.
New editable-workspace contract 1 is a separate sidecar inside the audit artifact folder: source digest,
revision, cards, editorial review. It follows existing audit retention; it never rewrites report.json.
Generate only from a saved, inactive audit. Saving edits invalidates review; review is not live verification.
Reject stale revisions/source changes and arbitrary evidence/score/verification edits. No runtime shell or
provider calls, and no language-model requirement. Drafts contain saved wording and explicit review tasks;
never synthesize business facts. All findings retain full details in the appendix. Include existing measured
performance context without changing finding totals or the experimental score.

Expose generation, editing, saving, review, validation, preview and explicit draft/final HTML/PDF downloads
inside normal results/history. Validate every final export without repairing input. Drafts carry a repeated
warning. Existing technical exports remain intact. Use the application's network-blocked PDF renderer.
Keep source timestamps, collection/cache/sampling/crawl limits and full affected scope visible. Comparison
uses the existing conservative cards comparison; missing newer evidence never proves a fix.

Regression coverage: profile list validation/persistence; saved audit generation/no requests/immutability;
all editable fields, revision conflict/review invalidation; unsupported final claims and forged verification;
critical overflow, incomplete scores, cached/native/provider distinctions, Lighthouse metadata;
HTML/PDF endpoint parity and existing technical downloads. Exercise normal UI with isolated synthetic data,
Turkish glyphs and representative PDF pages, then regenerate fixture inventory and run full offline suite.
No changes to budgets/configuration/retention/resume, real audit storage, dependencies or SEO checks.

Limit: automated structural/lexical checks cannot prove semantic truth. Editorial review remains necessary;
there is no automatic live-verification button in this round. Saved evidence is not a new live observation.

## Implemented flow and checks

History → open a saved audit → Client report / Müşteri raporu (beside the saved profile and technical downloads).
The same profile details are available there and in a new audit's plan options. Confirmed names are one per line.
Save summary and individual cards; edit unassessed notices/comparison labels without changing assessment status.
Select exact saved evidence for proposed text/code, save, record editorial review, then validate and export.
Draft HTML/PDF is always explicitly marked; final output is gated on current review and validation.
All appendix cards retain full explanations, steps and verification instructions. Critical overflow is called out.
Source digest/revision conflicts preserve the workspace rather than overwriting it. A resumed audit that changes
its source requires explicit reconciliation; edits are not silently rebased onto changed evidence.

Implementation uses maya-spec-writer → maya-implementer, maya-report-checker for saved synthetic evidence review,
and maya-audit-rapor's hardened contract. maya-verifier performs the final offline suite. No release workflow.
Installed skill script entry points delegate to maya_audit.client_reporting. Resources retain their relative paths;
parity tests guard scoring/catalog/CSS copies. The normal app has no dependency on a Codex session or a runtime LLM.
Only credential-free assessment controls are copied from crawl configuration; provider configuration is not copied.

Focused checks (all with isolated audit/config/cache/pytest/bytecode paths and no inherited provider keys):
- Initial: 58 passed, 1 failed (12.69 s). Minimal provider fixture exposed an unnecessary dependency on display-panel
  metadata. Generation now reads saved provider evidence directly. Original failure log retained outside the repo.
- Follow-up: 45 passed (14.18 s), then 133 passed (24.61 s).
- Expanded API/normal app coverage: 199 passed, 1 skipped (147.36 s), then 200 passed, 1 skipped (158.44 s).
  The sandbox could not launch Chromium for that existing optional PDF check; actual PDF QA below used the installed
  browser with loopback-only access. Test homes and locks were separate. No assertions were weakened.
- Final focused client tests: 65 passed (17.21 s). Existing 47 hardened-contract tests remain passing.

Browser/PDF QA: isolated ordinary application code on a temporary port, synthetic fixtures and mocked providers;
English/Turkish profile controls, loading/saving, draft→edit→review→validation→final HTML/PDF, draft watermark,
normal JSON/Markdown/PDF exports and source immutability checked. Final synthetic QA audit:
3d598ca3454c46e49cfa80d557829202. Actual final and draft PDFs: 6 pages; no browser errors or external requests.
Turkish text presence checked with pypdf after whitespace normalization; pages 1, 4 and 6 rasterized with macOS
sips and visually reviewed. Characters, scope labels, review/live distinction, tables and evidence remained readable.
This is representative layout QA, not proof of copy/paste fidelity or all pagination cases; long cards still span pages.

Report-checker scope: these synthetic saved reports and their page observations only; no customer audits reviewed.
Deliberately injected findings exercise the editor/validation path, not proof that an SEO diagnosis is true. In the
synthetic export the injected missing-title URL does not match a saved page observation: diagnosis is UNSURE until
matching evidence is reviewed. No source or successful generation is claimed to verify that finding. The native
historical redirect fixture lacks confirmation: UNSURE, with the normal report's uncertainty caveat preserved.
All 12 synthetic critical findings, including overflow, were retained in the dedicated appendix regression.
A human must still assess the semantic validity of diagnoses and recommendations. No live verification was run.

The owner app process on port 8770 was left running. After its active audit finishes, stop it in its own Terminal
with Ctrl+C, then run `.venv/bin/python -m maya_audit_web --port 8770` from the project root (without --demo).
Reload the page to load the new UI. This preserves the existing normal storage and provider configuration.
Full-suite results are reported in the task response; no release verification, tag, archive, push or commit is made.

Full-suite run 1: **1,487 passed, 1 failed, 1 skipped** (530.20 s). Failure:
`test_web_firecrawl.py::test_the_result_page_of_a_challenged_site_read_through_firecrawl_has_no_block_card`.
Appending editor functions after `boot()` broke the existing renderer test's removal of the final startup call,
causing startup against its intentionally minimal DOM. Returned to the implementer phase: restore `boot()` as
app.js's final statement, without changing the test or normal startup behavior. The original failure is preserved
in the external full-suite log. Focused browser check and a full final-state rerun are required for this correction.

After restoring startup-call placement, the affected browser suite and focused report suites passed:
**149 passed, 0 failed, 0 skipped** (24.38 s), with installed Chromium available. This includes the original
failing Firecrawl result-page check; its assertions were not changed. Final full-suite rerun follows this fix.

Acceptance patch 0.2.2: final application exports reject the reproduced universal-access assertions, loss of source
uncertainty in changed diagnostic text, and affected-page totals borrowed from unrelated page content. Explicitly
labelled verification samples remain samples. Each card displays the original qualified source judgment independently
of editorial text; older workspaces receive that display without rewriting the sidecar. These checks are deliberately
bounded contradiction checks, not semantic certification. Human review must still compare every serious claim with its
saved evidence. Draft previews remain available when final validation fails.
