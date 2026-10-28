# Normal report accuracy — owner-requested round, 2026-10-16

## Specification

Starting commit: `2ee8ef336a6f8ca33d0926f9d8c8b138f42cc8e9`, `stage1-integration`; only pre-existing untracked `.claude/`.

**Problem and confirmed cause.** Normal reports follow audit/checks → `report.build_report` → saved JSON →
`summary`/`practical` → `pdf.render_html` → app print/download routes → Chromium `to_pdf`.
Client cards follow the separate installed `from_maya_report` → cards-v2 validator → skill renderer path.
They share source evidence/schema, not validation. Card safeguards cannot validate ordinary exports.
`index_data.redirect_verdict` confirms persistence without a completed cookie walk; `_walk_again` calls a hop
cutoff a loop. `checks/index.py` and `catalog.py` make universal access/cause claims. `practical.EXAMPLES`
injects unrelated industries and invented prices/dates. STR-13, STR-6 and RND-7 remedies exceed observations.
Length checks already call their bands guidance; ordinary examples nevertheless prescribe character limits.

**Change.** Require observed cycles in sufficient native attempts AND a completed cyclic cookie walk for S1;
retain genuine cycles, intermittent success, cookie-dependent success and incomplete verification separately.
A readable, non-challenge HTML response is success; a cutoff/block/empty response is not. Retain request times,
errors and native client context; cached reader success never cancels native observations. Explain observations
and investigate logs before choosing a remedy. Replace unrelated examples with generic instructions, distinguish
low ratio from missing main, and qualify date/character/length advice in engine and normal presentation, including
legacy saved wording without rewriting stored reports. No rule based on numeric bands is a Google limit.
Update the existing report-checker to cover all Blocker/High findings and native access evidence.

**Tests.** Mocked persistent/intermittent/cookie/incomplete/cutoff/challenge/healthy cases; native versus cached
reader observations; real summary → printable → download routing in English/Turkish; no unrelated examples or
universal conclusions. Test source timestamps, legacy wording and low-ratio/date guidance. Existing assertions
for changed language must change, without weakening access/severity/evidence assertions.

**Compatibility and boundaries.** Keep schema 1.14 field shapes and saved artifacts, spending, retention, resume,
reader flow, provider behavior, thresholds and CLI. Walk evidence is an existing open object; additional flags
and timestamps are additive diagnostic contents. Historical severity remains historical; a fresh audit uses the
corrected classifier. No claim that existing saved diagnoses have been recomputed. Offline re-test requires no
paid services; an optional owner-requested future live audit has its normal configured cost, not authorized here.

## Evidence review

Read-only source: `~/.maya-audit/web/audits/<id>/artifacts/report.json`, saved native and Firecrawl evidence.
Older `ab110959f5c24326a50557914fca8dd3`: crawl 06:26:36–06:43:13 UTC Oct 15, 18 problems.
Newer `5e540cbd72f74b4aab6906dc70b92886`: crawl 19:48:20–19:59:50 UTC, 15 problems.
Downloads dated Oct 15: 25 pages / 28 pages; PDF metadata 06:52:18 / 20:01:48 UTC, about 1–2 seconds after the
provided generation timestamps. Identity corroborated by host, findings/counts and native attempts, not filenames alone.

Older /ticari: crawl 301 at 06:28:04; three self-301 retries 06:30:56, 57, 59; **no cookie walk**. Real native
cycles, insufficient evidence for the universal/persistent Blocker conclusion. Newer: crawl 301 19:49:47;
retries 301/301/200 19:50:20/21/24. Status intermittency confirmed for this client/run, not a historical fix or frequency. The successful retry
body was not retained: readable page success cannot independently be confirmed from the saved status alone.
Neither saved reader set includes /ticari. Newer homepage Firecrawl copy has morning observation timestamp and
`from_cache=true`; native and reader times are not interchangeable. No current Maximum requests were made.

All saved findings (including Info and review items), executive actions and DFS-1 through DFS-9 summaries were
inspected, not only the top ten. Evidence review by measured condition below; consequences/remedies remain advice.

| Finding group | Evidence verdict and limit |
|---|---|
| IDX-3 | Native attempts support cycles/intermittency; older persistence is unsure without cookie verification. |
| IDX-5 | Four suspicious addresses exist in saved sitemap evidence; suggested corrected spellings are hypotheses, not verified destinations. |
| RND-6 | Two large HTML and two late-content offsets measured; one body hits read cap. Indexing/ranking impact is not measured. |
| RND-7 | 33 low main-text ratios measured heuristically; saved homepage already has main. Adding main is unsupported. |
| STR-2 | Saved homepage has no H1; two pages repeat H1. Ranking consequence unmeasured. |
| STR-3 Organization | Older missing-Organization claim false for saved BankOrCreditUnion subtype; newer absent, current subtype handling already fixed. |
| STR-3 remaining | Five missing-property observations and newer three possible-product review items: markup signals, not proof these financial pages need Product or prices. |
| STR-6 | 50/50 audit-day headers measured; incorrect edit dates/cache origin not established. |
| STR-7 | Five missing alt attributes; 557 image URL-format observations. Decoration/actual negotiated encoding and speed impact not proven. |
| STR-8 (older only) | Five empty-table signals in saved extraction; whether intentional/decorative needs page-level review; newer absence is not proof of repair. |
| STR-10 | 50 favicon og:image observations measured; proposed replacement must use an approved real image. |
| STR-13 | 410 invisible characters on 20 pages; ranking failure is unsupported. Review deliberate language/formatting before removal. |
| STR-14 | Generic anchor and one source-target group without accessible text measured; group count differs from six raw links, not six separate findings. |
| STR-15 | Six pages below configured word guidance; incompleteness or ranking harm not proven. |
| TSEO-1 | Title/description lengths and heading jumps measured. Length guidance is not a technical eligibility limit. |
| Executive | Older first action assumes redirect-rule cause; newer repeats it and assumes false Last-Modified dates. Corrected presentation must ask for verification. |
| Providers, older | DFS-1…9 not assessed; no request sent because starting balance did not permit it. Not zero results. |
| Providers, newer | DFS-1/2 backlink sample; DFS-3 estimated visits; DFS-4/5 keyword samples; DFS-6 overlap domains, explicitly warns not business competitors; DFS-7 broad cited/named/support sample; DFS-8 missing platform total; DFS-9 one simulated-phone lab run, not field performance. |

Diagnostic: `.venv/bin/python /tmp/maya-normal-report/diagnose.py`: three cyclic attempts without cookie walk →
`always` (expected `unchecked`); title guidance → Kettles example (expected generic contextual instruction).
Two initial diagnostic attempts stopped on incorrect helper calls (no application failure); corrected helper call succeeded.
Source inspection reproduces hop cutoff → `loops`; regression below exercises it with mock responses.

## Primary documentation checked

Google's [title links](https://developers.google.com/search/docs/appearance/title-link) and
[snippets](https://developers.google.com/search/docs/appearance/snippet) state no length limit; displayed text is
truncated as needed by device width. Existing bands remain editorial guidance, not Google technical failures.
Google's [sitemap guidance](https://developers.google.com/search/docs/crawling-indexing/sitemaps/build-sitemap)
says lastmod should reflect significant content updates; same-day dates alone do not establish false dates.
No official rule was found/claimed that invisible characters necessarily prevent ranking.

## Deferred issues, in priority order

1. **Turkish relevance/brand aliases — confirmed inconsistent classification.** Newer DFS-4/5
   `evidence.data.unrelated.rows` includes hgs yukleme / hgs yükleme / hgs bakiye yükle with ranking page
   `/hgs-yukleme`, while hgs ödeme is relevant. isbankasi points to the homepage but is unrelated. The classifier
   uses keyword tokens/vocabulary, not ranking URL or approved parent-bank aliases. Add Turkish normalization,
   intent-aware ranking-page support and approved aliases; do not declare every HGS query relevant automatically.
2. **First actions/performance — confirmed separation in code.** First five actions come from findings; lab speed
   is an opportunity panel. Newer saved DFS-9 measures 8/100; next specify a transparent cross-panel priority policy,
   without treating a single lab run as field performance.
3. **Company/competitor labels — unresolved business identity.** DFS-6 correctly warns these are keyword-overlap
   domains, not established competitors. Review corporate affiliation and labels with approved company evidence.
4. **Structured subtype — already fixed in current application.** BankOrCreditUnion satisfies Organization;
   older saved classification is retained historically. Add more subtype coverage only for a reproduced gap.
5. **Empty links — count semantics confirmed, not a proven defect.** Newer evidence has one source-target group,
   six physical links, one anchor-fragment href. Next clarify group versus element counts consistently.
6. **PDF text fidelity/pagination — open.** Existing Turkish text extraction splits words and long reports may
   leave excessive page gaps; this round checks ordinary export but does not redesign PDF pagination/fonts.

No customer reports, caches, full URLs lists, or raw provider payloads are committed. Release verification NOT RUN.

## Verification record

Final implementation also corrects the shared `report.PAGE_KINDS` / web `bypage.*` phrases, including editorial
length guidance, so a safe detailed finding cannot be contradicted by its page brief. The frontend uses the same
`title_shown` / `fix_shown` values as print. Stable page-kind identifiers and severity policy are preserved.
A historical Blocker retains its recorded severity with an explicit incomplete-verification qualification. Legacy
intermittent status-only records are labeled HTTP successes with unverified page content. A newly readable native
crawl response is retained even if all later retries cycle. New `Inspect` instructions use the existing action selector.

Existing expectations updated only for the approved wording: redirect titles/remedies and cookie notes;
low-ratio instructions; generic translated examples; by-page guidance phrases and placeholder fallbacks. Catalog
coverage now also includes source-checked runtime-built TSEO titles. Access severity, counts, evidence, scope and
input-immutability assertions remain. The existing action-format assertion was not weakened.

All test runs use the existing `.venv`; the wrapper allowlists non-provider environment variables and sets fresh
`MAYA_AUDIT_HOME`, nonexistent `MAYA_AUDIT_ENV_FILE`, `TMPDIR`, bytecode/XDG storage, pytest basetemp and JUnit/log
output. Pytest external plugin autoload is disabled. `tests/conftest.py` additionally isolates providers and DNS.
Only in-memory mock transports or loopback fake sites are used. No real saved audit/cache/config is changed.

Development results retained (not replaced by later passes):

| Run | Result | Cause / follow-up |
|---|---|---|
| Initial focused | 77 passed, 6 failed, 6.60s | Five old wording expectations; one sandbox-denied loopback bind. |
| Same selection with loopback permission | 78 passed, 5 failed, 8.74s | Confirms the environment failure was separate; old wording assertions then updated. |
| Expanded web/translation selection | 217 passed, 2 failed, 116.60s | Code-only example inventory and dynamically built TSEO catalog coverage needed updating. Existing real normal PDF test passed. |
| Targeted follow-up | 155 passed, 2 failed, 12.41s | Old alt-code expectation and overbroad runtime catalog test (ANS outside this change); narrowed to the affected TSEO runtime examples. |
| Subsequent focused | 159 / 160 / 161 / 163 passed, no failures | Additional historical success/crawl-success/page-brief regressions added in sequence. |
| Interrupted pre-final full attempt | 348 passed, 1 failed, interrupted at 77.80s | Stopped only task-created pytest after PDF review found absolute by-page length labels. Failure also exposed observations accidentally added to fixes translations. Original log preserved. |
| Broader focused | 223 passed, 1 failed, 18.69s | After removing misplaced observations, legitimate new Inspect instructions were missing from the action verb set. Added Inspect; kept assertion unchanged. |
| Broad focused before full run | **225 passed, 0 failed, 0 errors, 0 skipped, 17.93s** | Includes normal-export regressions and affected wording/translation/action/placeholder tests. |

The 225-test focused argv after `.venv/bin/python -m pytest -q -ra -p no:cacheprovider` (plus fresh basetemp/JUnit paths):
`tests/test_normal_report_accuracy.py tests/test_false_alarms.py tests/test_preview16_false_alarms.py
 tests/test_round2_followups.py tests/test_wording.py tests/test_turkish_report.py tests/test_page_wording.py
 tests/test_no_unfilled_placeholders.py tests/test_counts_and_shared_elements.py
 tests/test_web_app.py::test_every_kind_of_finding_has_its_own_matching_explanation`.

A preliminary export QA used anonymized legacy JSON injected into a temporary app; this caught the shared by-page
universal claim. Final export QA instead runs a fresh synthetic native audit with three readable pages and a cookie-
independent /ticari-like cycle, through a TestClient using the real engine/store/summary/print/download endpoints.
No standalone server/port is launched. Chromium generates real English/Turkish PDFs offline, with network requests
aborted by the existing normal PDF implementation. Supporting QA files stay in temporary storage.

Final native export QA produced **11 English pages / 12 Turkish pages**. Text checks found the scoped native-cycle
claim and no clinical/kettle/universal-access examples. Representative Turkish words were extracted verbatim.
Rasterized executive, by-page, finding, guidance and technical pages were inspected; the final by-page label says
“editorial guidance” rather than “too long”. A4 text/table wrapping was readable on inspected pages. Pagination is
still sparse: executive actions continue on the next page; the preliminary legacy fixture orphaned a single table
row onto an almost empty page. This is confirmation of a layout limitation, not a typography/pagination fix.
The optional contact-sheet helper could not import Pillow; no package was installed. Individual pages were rendered
with existing macOS sips and inspected directly. Full text fidelity across all historical PDFs remains unverified.

Deferred affiliation evidence: saved DFS-6 includes isbank.com.tr, alongside other banks and generic large domains.
Saved homepage JSON-LD identifies Maximum as BankOrCreditUnion but supplies no parentOrganization. The panel
already warns these are search-overlap domains, not established business competitors; classification needs approved
corporate relationship evidence rather than inferring affiliation from search overlap alone.

Files in this round:

- Engine: `maya_audit/index_data.py`, `checks/index.py`, `checks/content_quality.py`, `checks/render.py`,
  `checks/structure.py`, `report.py`, `launch_gate.py`.
- Normal presentation: `maya_audit_web/summary.py`, `practical.py`, `catalog.py`, `wording.py`, `strings.py`,
  `locales/tr.json`, `locales/findings/tr.json`, `locales/catalog/tr.json`.
- Workflow: `.agents/skills/maya-report-checker/SKILL.md`. The separate client-card skill/scripts are unchanged.
- Tests: new `tests/test_normal_report_accuracy.py` (31 regression cases); affected expectations in
  `test_false_alarms.py`, `test_preview16_false_alarms.py`, `test_round2_followups.py`, `test_page_wording.py`,
  `test_turkish_report.py`, `test_web_app.py`, `test_no_unfilled_placeholders.py`, `test_practical_report.py`,
  `test_str_scenarios.py`.
- Documentation: this file, decision 233, open diagnostic-evidence schema note, regenerated fixture matrix.

Completed full run before the final catalog/expectation corrections: **1,437 passed, 3 failed, 0 errors,
1 skipped, 526.77s** (wrapper elapsed 528.71s). Original failures:

- `test_practical_report.py::test_fix_examples_are_chosen_by_the_findings_own_words_and_absent_when_there_is_no_honest_one`:
  expected invented/numeric title examples and a Cloudflare user-agent bypass snippet. Updated to generic,
  evidence-led instructions while preserving unknown-example and matching assertions.
- `test_str_scenarios.py::test_a_cache_timestamp_is_one_sitewide_stamp_not_six_page_conflicts`:
  expected a definite cache-time assertion from same-day headers. Renamed to the measured date pattern; asserts
  uncertainty about edit dates/cache cause, preserving pattern, scope and conflict-suppression assertions.
- `test_web_language.py::test_turkish_has_every_sentence_with_the_same_placeholders`:
  six obsolete catalog explanation keys remained after replacing those explanations. Removed only those orphaned
  keys; the key/placeholder equality assertion is unchanged.

This is why a full rerun was necessary; no earlier failure is reported as a clean pass. Post-correction focused
verification: **249 passed, 0 failed, 0 errors, 0 skipped in 29.02s** (wrapper 30.50s), same 225-test selection plus
`tests/test_practical_report.py tests/test_str_scenarios.py tests/test_web_language.py`.
The fixture matrix was regenerated after the renamed scenario test. Only tests/translations changed after the
completed failing full run; final PDF content remains the inspected content (removed translation keys were unused).

Temporary full-run records: `maya-normal-tests-_l_flp41` (failed original) and `maya-normal-tests-z2wzq9hf`
(final rerun), under the platform temporary folder. Each holds exact `command.json`, starting HEAD/status,
source hashes, `pytest.log`, JUnit XML and wall time; provider credentials are not recorded. Focused final records:
`maya-normal-tests-_jd3ueud`. No source changes are made during a full run.

### Final result

**BASELINE / bounded accuracy verification: PASS.** Final full offline suite: **1,440 passed, 0 failed, 0 errors,
1 skipped in 527.96s** (wrapper wall time 529.80s). Skip: `tests/test_evidence_integrity.py:184`,
“live-run examples are not committed to git”. One existing Starlette/httpx deprecation warning; no dependency changes.

Exact full command, run from the Git root via the sanitized environment wrapper:

```text
.venv/bin/python -m pytest -q -ra -p no:cacheprovider --basetemp=/var/folders/10/dlfrps1x6rnc6py046hx23_w0000gn/T/maya-normal-tests-z2wzq9hf/pytest --junitxml=/var/folders/10/dlfrps1x6rnc6py046hx23_w0000gn/T/maya-normal-tests-z2wzq9hf/results.xml
```

The tested tree is starting commit `2ee8ef336a6f8ca33d0926f9d8c8b138f42cc8e9` plus this round's changes.
Application/test/skill hashes were unchanged throughout the final full run. Only this verification record is updated
afterward. Existing untracked `.claude/` is preserved and excluded from the setup/development commit.
No live site/provider calls, real saved-audit writes, pushes, tags, release archives or owner-process terminations.
LG-101 remains open. Release verification: **NOT RUN**.
