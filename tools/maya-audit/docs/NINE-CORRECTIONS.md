# Nine bounded corrections — 21 October 2026

## Source and boundaries

Application0.2.6, branch `stage1-integration`, base commit
`10645ec0ac401862644d8fb383b58590da8e0bcc`; this is the preserved working tree,
not bare HEAD. Preview22 and earlier accuracy/client-integration work were already
uncommitted. No reset/stash, dependency/configuration change, paid request, live
site audit, release, tag or push. No claims about current customer websites.

The pre-change file snapshot, status and hashes are retained in the directory
named by `/tmp/maya-nine-baseline.txt`. `output/nine-corrections/task-only.patch`
and `task-changed-files.json` distinguish this task from older dirty work.
Changes overlap that work, so there is no safely isolated task commit.

## Evidence-to-decision and implementation review

All nine allegations were reproduced on controlled evidence against the preserved
starting implementation. Old historical pages are not claimed verified by these
fixtures. Severity and observation confidence remain separate; no rank/impact or
server-cause inference was added. An unresolved role/name remains an assessment gap.

|#|Original behavior / established cause|Supported correction and shared location|Regression and retained contrast|
|---|---|---|---|
|1|EN UI leaked “Intent, client behavior, sampling and missing context may change the interpretation.” into TR client notes after the temporary locale was restored.|`maya_audit_web/client_reports.py::generate` explicitly requests `tr`; `html` translates known old English source notes without relabelling already Turkish text. Technical EN output unchanged.|`test_turkish_client_does_not_inherit_english_ui`: Turkish interpretation/alternatives, no false English marker; English technical alternative remains English.|
|2|H1 and external-link cards shared generic steps/verification/decision. A numeric `evidence.pages` also crashed the initial new adapter during actual saved replay.|`client_reporting/advice.py::procedure` derives procedures from qualified engine repair/expected result and subtype, with actual source/target/element evidence. HEAD-only records require GET corroboration before removal. Numeric counts stay numbers. Owner/effort still come from the shared action metadata.|Distinct H1/sourceURL and HEAD/source+destination/GET procedures; same subtype retains separate URLs; numeric-count source remains immutable.|
|3|Same nonzero shell with actual RND-2 rendered-only evidence was independently counted as IDX-1 and RND-2.|`related_evidence.reconcile/objects` runs at root grouping and qualification after rendered evidence exists. Only proven same-URL overlap is removed from actionable IDX-1; original finding/provenance is retained in `js_dependency_observations` and attached to RND-2. Server/static-HTML advice stays qualified. `judgments.qualify_report` rebuilds priority IDs and derived page lists rather than using stale companions.|One actionable rendered dependency; zero-byte/render-empty, substantive raw, absent render, absent RND-2 and mixed-URL retrieval failures remain. Real RND-2/root pipeline and public serialized render counts tested. Mixed scope does not reappear through affected-URL companions.|
|4|Four generic-link findings were retitled identically despite distinct destinations.|`judgments.qualify` STR-14 title retains measured counts plus recorded wording, component and destination. `wording`/TR locale recognize that qualified title. No ID merge.|Four distinct target URLs in JSON titles and Markdown; counts and separate IDs retained.|
|5|Root grouping selected only empty/server-message findings, omitting HTTP404/410. Its first new version also expanded a partly qualifying group back to all URLs.|`related_evidence.retrieval_urls`, `root_cause._empty_pages/_idx5`, shared copied-report reconciliation include actual qualifying IDX-1 failures perURL, exclude contradictory successful attempts, and preserve independent redirect/noindex/mixed sitemap decisions. Complete original review/membership/raw records and separately actionable scope are retained.|404+410+empty overlap3; separate redirect/noindex/contradictory states remain. Direct root-group regression retains a mixed-success URL and original total review scope. Complete overlap is not an independent second repair.|
|6|An unnamed captured iframe produced only an Info embedding observation.|`element_context.enrich` resolves title/ARIA naming; `checks.render.rnd4_non_text` reports applicable unnamed frames separately as S4/Verified within the captured markup scope, with page/src/element/time evidence. Existing embedding Info stays; no SEO extraction claim. `coverage` marks incomplete old records unassessed.|Unnamed frame detected; nonempty title, aria-label, resolved aria-labelledby, hidden ancestor and presentation role excluded; old title:null without complete naming evidence is a gap, not verified. Ordinary loopback audit tested.|
|7|Any nonempty alt bypassed STR-7, including IMG_2041.jpg and image.|`checks.structure.str7_alt` estimates likely placeholders from whole-value patterns only, retains observed alt/page/src/context/time and purpose-dependent repair advice. A filename does not establish what an image depicts.|Five filename/label patterns detected as Estimated; meaningful sentence, phrase containing photo, decorative empty alt unaffected. Image-only link remains detectable during ordinary audit.|
|8|A lone partial token could be promoted through the title/global vocabulary even though the full-brand identity guard rejected it.|`dataforseo.relevance.assess` removes identity-only context for this case; a full brand repeated in readable blocks is also not independent service evidence. Confirmed aliases and independent page topics are retained. `reassess_nine` reuses existing relevance/counting pipeline on copied provider rows and retains other assessments and original decisions.|Anadolu Fırın/anadolu and Cedar Workshop/cedar become ambiguous with confirmed-relevant count0. Full Turkish/diacritic variants and confirmed alias stay branded; independently supported cedar editorial context stays relevant.|
|9|A real60finding draft produced65pages and the existing50page refusal.|`client_reporting/grouped.py`, `advice.group_signature`, `render_report._build/build` share procedures only in large compact reports (>40members). Check/subtype/severity/remedy/verification/owner/effort/qualifications must match. Owner-edited cards remain separate. Every member ID, URL association, qualifications, dates, evidence, text/code and verification record remains. `full=true` does not enable grouping.|Real installed Chromium:60same-subtype=33pages;60H1/subheading mix=34pages/two incompatible groups;10findings=14pages/existing card structure. All60IDs and affectedURL annotations checked. Explicit50page failure guard remains for excessive/unmergeable documents.|

No frozen schema keys or enums changed. Added optional page.analysis, check/finding
`evidence` records are explicitly open in `schema.py`; no schema bump was required.
The client editorial workspace remains a draft; rendering does not establish review
or live verification. Existing client sidecars are preserved, not regenerated over edits.

## Workflow responsibilities actually used

All paths are repository-relative; no skill was installed or restored.

- `.agents/skills/maya-spec-writer/SKILL.md`: inspected the suspected code paths and wrote `docs/NINE-CORRECTIONS-SPEC.md` before implementation.
- `.agents/skills/maya-implementer/SKILL.md`: bounded Python, translation and regression changes, using the existing .venv.
- `.agents/skills/maya-judgment-validator/SKILL.md`: separated shell retrieval vs render evidence, actual overlap vs independent states, captured name vs missing naming evidence, placeholder estimate vs informative-purpose proof, and partial identity vs independently supported relevance. Reproducer and benign/genuine contrasts above are the review record.
- `.agents/skills/maya-verifier/SKILL.md`: isolated focused/full tests and exact-source manifest; user-authorized browser/PDF acceptance overrides its narrower baseline-only prohibition on report generation.
- `.agents/skills/maya-report-checker/SKILL.md`: compared qualified findings/counters, full page scopes, action metadata, technical output and client draft, preserving unknowns and original sources.
- `.agents/skills/maya-audit-rapor/SKILL.md`: Turkish wording, draft/final boundaries, traceable recommendations and complete compact delivery. Runtime uses Python modules, no agent or shell invocation.

Review was sequentially performed by the same agent, not an independent assessment.
The release skill was not invoked. No full historical accuracy review is claimed.

## Reproduction and test records

The new tests are in `tests/test_nine_corrections.py`. Existing exhaustive wording/catalog
coverage in `tests/test_web_app.py` gained one qualified title sample; no useful
assertion was removed or weakened. Fixture inventory was regenerated.

Executed commands (each test wrapper creates a fresh home/audit/config/cache/tmp/bytecode
and nonexistent environment file, passes only an environment allowlist, and uses
`--basetemp`, no pytest cache and disabled plugin autoload):

```
.venv/bin/python /tmp/maya-nine-fast.py
.venv/bin/python /tmp/maya-nine-tests.py --contracts
.venv/bin/python scripts/fixture_matrix.py
.venv/bin/python output/nine-corrections/verify.py --full
.venv/bin/python /tmp/maya-nine-isolated.py /tmp/maya-nine-original-frame.py
.venv/bin/python /tmp/maya-nine-isolated.py /tmp/maya-nine-root-overlap.py
.venv/bin/python /tmp/maya-nine-isolated.py /tmp/maya-nine-reassess.py
.venv/bin/python /tmp/maya-nine-isolated.py /tmp/maya-nine-finish-r9.py
.venv/bin/python /tmp/maya-nine-isolated.py /tmp/maya-nine-r9-pdf.py
```

The wrappers expand tests to `.venv/bin/python -m pytest -q -ra -p no:cacheprovider
--basetemp=<isolated>/pytest --junitxml=<isolated>/results.xml [selected files]`.
`command.json`, `pytest.log`, `results.xml`, `summary.json` preserve actual invocations/results.
Final pointers are `output/nine-corrections/focused-work.txt` and `full-work.txt`;
source hashes under full-work/tested-files.json identify the exact tested working tree.

Original red regressions:14failed/7passed; early iframe fixture lacked the readable_document
method and a keyword assertion used an incorrect counter path. Corrected fixtures and
`original-iframe-reproduction.json` independently demonstrate the original behavior;
those harness errors are not application defects. Implementation diagnostics preserved:
2failed/19passed initially; broader integration5failed/277passed (Turkish validation,
complete private URL scope, title/catalog coverage); contract1failed/94passed; then
95passed, later99passed. Focused follow-ups caught readable full-brand words in main
blocks (1failed/31passed), now corrected. Subsequent contract runs100,104 and105passed.
No failed record was deleted. Four full-suite attempts were interrupted after specific
visual/integration reproducers required further changes; one interrupted log contains
an unidentified F before termination, not a passing result. The completed final suite
and any attributable failures are recorded below. Do not treat interrupted runs as passes.

PDF assertions use actual installed Playwright Chromium, not a mocked to_pdf.
PDFKit contactsheets and bounds checks cover synthetic33/34/14page documents;
text/links are checked across every page, visual inspection samples cover/front,
shared instructions, member continuations and final coverage/companions. This is not
an unlimited-layout guarantee. Missing source times stay unavailable.

## Saved evidence and owner review

`analysis-adile-oct19-r9` is a separately registered copy of r8, processed offline
with nine-corrections-v1; original collection times remain unchanged. r8 SHA256
`5240b442edd74906eb26ed1c36c7712910e80ec4681149e0707187a8fa9da969` remains intact.
The actionable problem count is18before/18after;34finding/note IDs remain present.
No new website request was made. This is changed interpretation/presentation of saved
evidence, not a fresh audit. Old incomplete iframe evidence cannot prove missing names;
new audits now capture that evidence. The r9 client draft has47pages and all34IDs;
it is not approved or live-verified.

Open `http://127.0.0.1:8770/#analysis=analysis-adile-oct19-r9` or History → Revised
analyses → “Adile — nine-correction reassessment r9”. Technical JSON/PDF, page tables,
action plan and Client report refer to that selected revision. Client report → Preview /
Draft PDF / Complete evidence JSON; final export still requires validation/review.
English UI is intentionally used to check the Turkish client notes. Technical EN remains EN.

Normal download routes:
- `/api/v1/audits/analysis-adile-oct19-r9/downloads/json`
- `/api/v1/audits/analysis-adile-oct19-r9/downloads/pdf`
- `/api/v1/audits/analysis-adile-oct19-r9/client-report/export/pdf?mode=draft`
- `/api/v1/audits/analysis-adile-oct19-r9/client-report/export/html?mode=draft`

Existing browser session/token protections apply; use the UI for authenticated downloads.
R3/r6/r7/r8 remain accessible and unchanged. No overall accuracy percentage is inferred.
Final suite, visual observations and owner-process verification are appended after completion.


### Final integration corrections and preserved assertions

The first completed full run was **1,696passed,4failed,1skipped in616.69s**
(`/var/folders/10/dlfrps1x6rnc6py046hx23_w0000gn/T/maya-nine-tests-c74ljhzk`).
Its original log/JUnit remain intact. The failures were:

- `test_two_identical_youtube_iframes_on_a_page_give_one_row`: its selector assumed every
  iframe finding was Info. It now separately asserts the unchanged deduplicated embedding
  list and the genuine unnamed frame's S4/Verified finding. No finding was suppressed.
- `test_sitemap_health`: confirmed that overlap could erase a separate noindex concern
  below the residual threshold. Root grouping now retains that owner/indexing decision
  and contradictory evidence while preserving the existing below-threshold redirect policy.
  Expected scope is hidden, not duplicated dead1/dead2; original3of11review and overlap2
  are explicitly asserted, including the original URL records.
- The sampled/full sitemap tests encoded empty-only overlap2/3. The fake evidence also
  has IDX-1 HTTP404s at /blog/2 and /blog/4, so expectations are4/5. The separate /blog/8
  response is not represented by IDX-1 and remains in sitemap scope. Sampling, confidence,
  notes, budgets, URL reachability and Turkish translation assertions were retained.

Focused checks of that first fix found a redirect-threshold behavior change; it was
narrowed back to the original redirect policy rather than weakening the existing test.
A new style fixture initially used an English sentence absent from the catalog; corrected
it to the engine's actual `Add meta description.`. These diagnostic failures are retained
in the corresponding isolated logs, not relabelled as passing runs.

The saved technical export first returned the correct explicit50page error at53pages:
listing every generic-link target in its headline repeated a long appendix throughout
summaries. The final headline identifies one supported target and explicitly reports
additional unique destinations; all original records remain in evidence/JSON. The
technical PDF is now28pages. The final client draft is47pages. This changes neither
finding counts nor detection. Ordinary technical English wording remains English.

New frame/placeholder evidence preserves actual reader collection time and source
separately from the native request time and later finding/reassessment processing time.
New client procedures satisfy the existing Turkish instruction-style validator without
weakening validation. The r9 draft is still unreviewed; final generation remains blocked
by editorial review and the visible check-code wording in one sitemap card. This is an
explicit editing requirement, not a report marked approved or verified by rendering.

Latest focused results: **109passed/0failed/0skipped in35.77s** (nine/client/PDF contracts)
and **94passed/0failed/0skipped in38.15s** (existing count/iframe/IDX/round2/grouping cases).
The new test file contains45executed parameterized cases, including regressions and
contrasts. Representative final r9 technical/client PDFs have no PDFKit out-of-media
text characters or Unicode replacement characters. The sixty-member PDFs remain33/34pages,
all60IDs and every member affectedURL annotation present; the ten-member PDF remains14pages.


Final legacy-path check: an old unqualified empty-response repair still offered URL removal,
while its qualified action required corroboration. `advice.procedure` now uses the action
text from the same qualified record as the action plan, not the obsolete source repair.
Regression covers the actual old repair string and preserves the source. The sitemap-only
HTTP expansion leaves ACC-8's unrelated grouping boundary unchanged. Stronger tests require
exact60member IDs (not prefix matches), genuine nondecorative descriptive alt contrasts,
and unchanged full-export grouping. Latest final contracts:111passed/0failed/0skipped,
35.37s. The fourth interrupted full run had no failures through88%; it was stopped for
the demonstrated legacy-path correction, not called a passing full run. Final full-suite
result below supersedes its incomplete status.


## Completed verification — final source

- Full command: `.venv/bin/python output/nine-corrections/verify.py --full`.
  **1,706passed,0failed,0errors,1skipped in599.36s** (601.35s wrapper wall time).
  Skip: `tests/test_evidence_integrity.py:184`, live-run examples are not committed.
  One existing Starlette/httpx deprecation warning; dependencies were not changed.
- Final focused nine/client/PDF contract command: `.venv/bin/python /tmp/maya-nine-tests.py --contracts`:
  **111passed,0failed,0skipped in35.37s**, including45new parameterized cases.
- Existing affected count/iframe/IDX/round2/grouping files: **94passed in38.15s**.
- Ordinary loopback `run_audit` → shared root grouping/qualification → `build_report`/
  Markdown and saved-copy `qualify_report` are exercised. Client draft creation uses
  qualified action metadata even for legacy unqualified input. Saved source remains unchanged.
- Exact source manifest:256files; fingerprint `b9b973de78fc49856e0a9da6f23dfa75e2805a0ba983a4fc014b68972518710b`.
  Current application/test files still match the completed full-suite hashes.
- Real installed Chromium:60same-subtype draft33pages;60mixed-H1/subheading draft34pages;
 10finding draft14pages. Exact member IDs and affected-URL annotations retained;
  owner edits/incompatible procedures stay separate; full mode stays ungrouped.
- Browser at8770: normal navigation/assets, r9 selection and matching JSON/technical PDF
  and client draft all passed. Technical PDF28pages; Turkish client PDF47pages; all34
  IDs retained;18actionable problems unchanged. English UI produced Turkish judgment notes;
  technical English remained English. No browser errors, HTTP errors or blocked external calls.
- Visually inspected synthetic cover/group/member/final pages, downloaded technical pages1–4
  and representative finding/inventory pages, downloaded client pages13–16 and45–47.
  Turkish characters and links are readable; PDFKit bounds found0out-of-media text characters
  and0replacement characters across each downloaded PDF. This does not verify every future layout.
- The server was verified idle and project-owned, gracefully restarted fromPID14470 toPID25920
  using `.venv/bin/python -m maya_audit_web`. History remained43records; source/revised JSON
  hashes unchanged. Redacted public settings confirm normal mode and configured provider credentials;
  no credential values or environment-file contents were read by the agent, no provider was contacted.
- Matching r9 JSON SHA256: `bbf7294e412e8d471a6c8d996e262bbfd5bef126efbe3256d1dcf8e8674f4de0`.
- Permanent logs, original failures, commands, JUnit, source manifest, baseline code snapshot
  and task-only diff are under `output/nine-corrections/`. No unrelated files were staged.

No remaining reproduced application defect among these nine in the tested cases.
Limitations: incomplete historical iframe-name evidence remains unassessed; placeholder/brand
context still needs human interpretation; r9 is a historical-evidence draft, not a new website
check. The draft still requires editorial review and one sitemap card's client-facing check-code
wording to be edited before final validation. Rendering never marks it verified. Old edited
workspaces are preserved; automatic grouping requires compatible generated procedures, so
unmergeable/excessive documents may still receive the explicit50page error. This bounded60finding
case does not guarantee unlimited content in50pages. No independent reviewer was used for this
round. No overall accuracy percentage or zero-error claim is made.

No task commit: its changes overlap earlier uncommitted/untracked integration work and cannot
be committed as a standalone working change without including that work. Safe baseline copies
and `task-only.patch` preserve reviewability. No ZIP, tag, release, push or dependency upgrade.
Release verification: NOT RUN.

Owner check: open `http://127.0.0.1:8770/#analysis=analysis-adile-oct19-r9`, confirm r9 / nine-corrections-v1 and the historical
source notice, download JSON and PDF from that selected result; click Client report → Preview /
Draft PDF / Complete evidence JSON. Do not open r8 expecting its saved editorial draft to be
rewritten. Future restart: wait until no job is running/queued/stopping, stop only this verified
server's terminal withCtrl+C, then from this root run `.venv/bin/python -m maya_audit_web`.
Do not replace the project folder or switch the owner port.
