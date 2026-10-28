# Keyword relevance and action prioritization — 2026-10-16

## Specification

Owner requested general improvements, not domain exceptions. Starting HEAD: `12b4177` on stage1-integration;
only existing untracked `.claude/`. Existing normal-report safeguards and saved audits remain intact.

Confirmed causes: `dataforseo/insights.py` compares lowercased words without diacritic folding, ignores the
ranking URL and page-specific context, has no confirmed-alias input, and extrapolates sample classifications to
DFS-3 totals. `practical.executive` and `timeline` only receive site findings, excluding available Lighthouse data.

Changes: normalize comparison tokens only; preserve original provider rows/metrics. Use same-origin ranking paths
and readable saved page title/description/heading evidence. Short topic tokens are retained; isolated weak matches
stay ambiguous. Explicit owner-confirmed brand aliases and related-organization names come from optional profile
API lists; no inferred affiliation or brand-specific dictionaries. Keep brand, service, related organization,
ambiguous and unrelated categories separate. Record reasons/context per sampled row; never project to all totals.

One shared presentation planner ranks genuine S1/S2 blockers first, then measured S3 issues/performance diagnostics,
then S4 hygiene, considering evidence quality and scope with stable ties. Include available slow lab/field evidence
in executive actions, action plan and timeline. Lab actions identify URL/device/source/date (missing stays unknown),
name measured metrics and recommend investigation, never an invented cause. Do not count provider diagnostics as
new engine findings. No new providers, SEO checks, performance thresholds, costs or acquisition calls.

Tests: Turkish accented/unaccented variants; supported short acronyms; confirmed brand versus organization names;
unrelated intent and unknown-page ambiguity; original metrics unchanged; sample versus total language; missing and
healthy performance; separate lab/field scope; blocker preservation; matching summary/plan/timeline/print/download.
Update only superseded expectations. Use existing .venv, fixtures and isolated storage; focused tests then full once.

Compatibility: new evidence keys are open objects (schema 1.14 unchanged); no frozen report fields change.
Optional profile inputs preserve existing lists when omitted; older profiles/reports need no migration. No UI redesign.
Competitor ownership and PDF pagination are excluded. Manual owner smoke test may use synthetic local fixtures
without spending; real provider calls require separate authorization and the normal existing budget confirmation.

## Reproduction and before/after evidence

Before implementation, `.venv/bin/python /tmp/maya-relevance/reproduce.py` used a minimal synthetic vocabulary
`Kart yükleme ve ödeme`. It returned: `yükleme` relevant, `yukleme` unrelated, `hgs yukleme` unrelated,
`hgs ödeme` relevant, `isbankasi` unrelated. A saved-style observed DFS-9 lab payload (performance 8,
LCP past the existing threshold) produced **no first actions**. Code references: `insights._tokens`,
`classify_keyword`, `apply_relevance`; `practical.executive`, `summary.action_plan`, `practical.timeline`.
No historical Maximum requests were made, copied or inferred in this round: regression inputs are anonymized.

`tests/test_keyword_actions.py` now reproduces these paths through `apply_relevance`, not only token helpers:

| Input and supporting evidence | Before | After |
|---|---|---|
| `hgs yukleme`, ranking `/hgs-yukleme`, saved HGS title/description | unrelated without homepage vocabulary | relevant; original query/volume/position unchanged; page/path sources retained |
| `hgs yükleme`, `HGS YÜKLEME`, `hgs yüklemesi` with matching context | inconsistent forms | same related-service category |
| `isbankasi` / `iş bankası`, homepage rank but no confirmed association | unrelated | uncertain |
| Same query with owner-declared related organization `İş Bankası` | no supported input | related organization, not audited brand or automatic quick win |
| Owner-confirmed `Açık Kart`: `acikkart giris` / `açık kart giriş` | no alias input | branded; matched owner name recorded |
| Brand `XY`, query `xy` | branded via compact-name fallback | branded; short name tokens retained consistently |
| `hgs casino`, only HGS supported | confidently unrelated without context | uncertain; incomplete topic support |
| `maximum heart rate`, no matching subject | unrelated | unrelated lexical estimate, still visible for review |
| Host rank alone, no readable matching page/topic | unrelated | uncertain, never automatically relevant |
| Slow Lighthouse lab run, no S1/S2 | opportunities only | first diagnostic action, then medium/lower site work |
| Five genuine S1/S2 actions plus slow lab | lab absent | blockers/high retain all five slots; diagnostic remains in plan/timeline |

Keyword relevance remains lexical evidence, not semantic proof. Every new sample summary says this explicitly,
counts uncertain/organization rows and disclaims classification of provider totals. Original rows are in
`evidence.data.provider_table`; reasons/sources/confidence are in `keyword_assessments`. Small Turkish suffix
normalization is heuristic, not a full morphological analyzer. CLI and web both supply readable page context.

Shared priorities are a presentation policy: S1/S2, measured poor performance diagnostics, other S3, S4, notes;
within tiers use evidence quality, observed scope and effort, with stable ties. Missing timings get a lower-priority
assessment-gap action; absent provider data creates no healthy claim. Field scope is an origin aggregate, never
counted as one assessed page. Diagnostics recommend investigation, not configuration changes inferred from scores.
They have no fake engine finding/evidence links, including the existing assistant's plan/top-action consumers.

Optional confirmed names are supported by `PUT /api/v1/projects/{project_id}/profile` using `brand_aliases` and
`related_organizations` arrays. Each has at most 30 names of 1–120 characters. Omitted arrays survive ordinary
profile updates; `[]` clears a list. The existing profile UI was not redesigned. No organization or alias is inferred
from shared ranking domains, a brand word or suspected corporate ownership. Old saved reports are not rewritten
or silently reclassified; a new audit receives the new evidence-based classification.

Existing tests were updated only for the changed contract: distinct advisory actions need not equal problem counts;
smaller effort breaks same-tier/scope ties; ambiguous titles cover missing context; current Turkish sentences use
sample-scoped language. Historical translation patterns remain supported. The schema stays 1.14 because additions
are inside open provider evidence, presentation responses or optional project-profile inputs, not frozen report fields.

## Verification and evidence review

Final verification ran from `12b4177f1fffe1fe571a2f3b0e5fd0c9564076ee` plus the task's working-tree changes on
`stage1-integration`. Existing `.claude/` was the only pre-task untracked work and is excluded from the commit.
The existing .venv is Python 3.13.1. No dependencies or API configuration changed. Every test/QA child used an
allowlisted environment, fresh MAYA_AUDIT_HOME, nonexistent MAYA_AUDIT_ENV_FILE, temporary TMPDIR/locks,
XDG cache/config/data, bytecode and pytest basetemp. Tests block non-loopback connections; providers use mock
transports. The real audit home, history, caches and owner process on port 8770 were untouched.

Commands: `.venv/bin/python /tmp/maya-normal-report/run_tests.py [test paths]` wraps
`.venv/bin/python -m pytest -q -ra -p no:cacheprovider --basetemp=<work>/pytest --junitxml=<work>/results.xml`.
The final focused paths were `tests/test_keyword_actions.py`, `test_practical_report.py`,
`test_brand_and_launch_gate.py`, `test_real_run_fixes.py`, `test_preview16_false_alarms.py`,
`test_turkish_report.py`, `test_web_language.py`, `test_report_agreement.py`, `test_search_data.py`,
`test_round2_followups.py`, `test_normal_report_accuracy.py`, `test_fixture_matrix.py` (all under `tests/`).
The full run used no path selection. Fixture inventory regenerated with the isolated wrapper
`.venv/bin/python /tmp/maya-normal-report/inventory.py` → `.venv/bin/python -m scripts.fixture_matrix`.

| Check | Result | Pytest elapsed | Log folder suffix (`maya-normal-tests-…`) |
|---|---|---|---|
| Initial focused implementation | 104 passed, 9 failed, 1 skipped | 16.76s | `_lua5eqs` |
| Focused corrections | 113 passed, 1 failed | 16.06s | `ux4hg05p` |
| Expanded offline checks | 232 passed | 156.40s | `2t97olk0` |
| Context/wording checks | 91 passed | 12.60s | `cno1rg7j` |
| Shared consumers | 72 passed | 9.34s | `p71hohr2` |
| Consolidated intermediate | 159 passed | 21.88s | `yt0_b3b0` |
| Context/CLI/uncertainty wording | 159 passed | 16.86s | `41yqvn_p` |
| Interrupted pre-final full attempt 1 | 349 passed, no failed tests; interrupted | 84.57s | `qwaaxm3d` |
| Post-syntax correction focused | 65 passed | 9.33s | `jpb5dl_1` |
| Interrupted pre-final full attempt 2 | 958 passed, 1 skipped, no failed tests; interrupted | 264.43s | `wsu71yt8` |
| **Final consolidated focused** | **162 passed, 0 failed/errors/skipped** | **22.55s** | `bnutzge4` |
| **Final complete offline suite** | **1470 passed, 0 failed, 0 errors, 1 skipped** | **551.42s** | `u3fggckl` |

Logs/JUnit/commands/source hashes are under
`/var/folders/10/dlfrps1x6rnc6py046hx23_w0000gn/T/<folder above>/`.
Final full subprocess wall time: 553.35s. The final full run was the only completed full run on final sources.
There are **30 new discovered regression cases**. Final skip:
`tests/test_evidence_integrity.py:184` — live-run examples are not committed to Git. One existing Starlette/httpx
API deprecation warning remains; no dependency upgrade was attempted.

Original failures were preserved, not erased by reruns. Initial failed names: new unread-page context assertion;
normal summary/print/download tests in both languages; existing merged first-actions order; practical end-to-end
action/issue equality; common-word keyword ambiguous title; Turkish data-panel sentence coverage; full Turkish
report translation; translation catalog/frame agreement. Their causes were an overly broad new assertion about
all path evidence, missing `search_data` in the new fixture, intentionally superseded ordering/count/title
expectations, and new translation frames initially put in the wrong catalog map. The second run's remaining
failure was stale current-source wording coverage in `test_every_data_panel_title_sentence_and_column_name_has_a_turkish_wording`.
The initial Chromium skip was a sandbox restriction; the permitted local run executed it successfully.

The first full attempt was stopped only after a Python 3.11 static compile found one new f-string using Python
3.12 quoting. Fixed quoting; all 16 changed Python files then passed Python 3.11 **syntax-only** compilation
using the already installed system interpreter (`-I -S`, no application imports/dependencies). Application tests
still ran only in the existing .venv. The second attempt was stopped after PDF visual review exposed the new
category's internal code leaking into Turkish output. A direct English/Turkish display-map assertion now protects
that case; the QA fixture also uses a genuine translatable provider-summary frame. Only each uniquely identified
task-created pytest process was interrupted; no owner process was terminated.

**Normal export:** `.venv/bin/python /tmp/maya-relevance/qa_export.py` created an isolated in-memory demo audit,
then inserted explicit synthetic keyword/lab evidence and requested the real print and Download PDF routes.
Offline Chromium generated English and Turkish PDFs, 13 pages each; pypdf extracted all pages. Assertions checked
original queries, source URL, measurement timestamp, first-action presence, friendly organization labels and no
Turkish English-fallback marker. Representative executive, action-continuation and provider pages were rasterized
with existing macOS `sips` and inspected. No clipping/overlap was seen on those inspected pages. Poppler was not
installed and no packages were added. Pagination still splits the executive actions over pages; this round does
not claim exhaustive text/glyph fidelity or pagination correctness.
Final QA files: `/var/folders/10/dlfrps1x6rnc6py046hx23_w0000gn/T/maya-keyword-pdf-0mdh67rw/`.
No synthetic/customer report, provider cache or QA output is committed.

**maya-report-checker review, synthetic scope only:** audit `7f8481dbf8134a8dad80a0a456d251a0`, schema 1.14;
`report.json`, native/reader `001-home.json`, request records, synthetic keyword assessments and English/Turkish
summary/print/PDF outputs. Native homepage: HTTP 403 at 2026-10-16T13:11:56.236937+00:00; reader homepage: HTTP
200 at 2026-10-16T13:11:56+00:00. No S1/S2 findings exist in this fixture; both non-Info findings were reviewed.
The two pipelines remain separate: the client-card converter/validator/renderer was read as a reporting contract,
not changed or presumed to validate ordinary application exports.

- **Report says:** no Organization data on the fixture homepage (STR-3, S3). **Page contains:** saved reader title
  `Demo Bank: everyday banking | Demo Bank`, zero JSON-LD blocks. **Verdict: real**, within the saved synthetic
  reader document, never proof of native or genuine crawler access.
- **Report says:** no HTTP-to-HTTPS redirect on the tested host (IDX-2, S4). **Page contains:** native HTTP 403
  without an HTTPS redirect; raw request evidence remains distinct from reader success. **Verdict: real** for this
  tested response. The implementation does not infer a server/WAF cause or erase the access limitation.
- **Report says:** `hgs yukleme` is a relevant lexical estimate. **Page contains:** provider ranking path
  `/hgs-yukleme`; no readable page document for that injected URL in this QA fixture. **Verdict: unsure** about
  semantic intent; the limited path match is real and the summary explicitly says estimates do not prove intent.
- **Report says:** `isbankasi` is a related-organization query. **Page contains:** no independent ownership proof;
  the fixture explicitly supplies owner-confirmed `İş Bankası`, retained in assessment sources. **Verdict: real**
  as a match to supplied context, not independent corporate verification or a competitor label.
- **Report says:** investigate the stated Lighthouse lab evidence. **Page contains:** no performance evidence in
  page text; the explicitly injected provider payload states mobile, score 8 and an LCP threshold flag for
  `https://kart.example/`, measurement 2026-10-16T10:00:00+00:00, collection 10:05:00. **Verdict: real** within the
  synthetic input contract; no actual website performance or technical cause was measured in this task. This
  injected URL is identified explicitly, not silently treated as native-access or real-user field evidence.

Summary: 4 real within the stated synthetic/input scope, 0 false, 1 unsure about semantic intent. Provider metrics
remain their own sample/index/field/lab claims; no sample share changes DFS-3 totals. This is not historical
Maximum re-verification or live-site validation. Source-hash comparison confirmed no application/test changes
between the final full run and commit preparation; only verification notes and a decision-attribution clarification were edited afterward.

**Verdict: PASS for offline development verification.** Ready for an owner-controlled offline local smoke test;
the existing running app was not restarted. Existing minimum-coverage withholding of site-wide first-fix advice
is retained. Relevance remains heuristic; full Turkish morphology, semantic intent and independent affiliation
verification are not solved. Confirmed-name lists currently use the profile API, not new UI fields. Competitor
ownership, PDF pagination/text fidelity and native Windows LG-101 remain open. Next accuracy round: establish
company/competitor relationships from confirmed business evidence and keep those labels separate from query overlap.
**Release verification: NOT RUN.** No push, tag or release archive.
