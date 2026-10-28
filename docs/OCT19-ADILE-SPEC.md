# October 19 accuracy correction — owner request, 2026-10-19

Starting source: 10645ec (application 0.2.4), stage1-integration. Existing .claude/ is preserved.

1. **Problem / evidence.** Saved audit c9d93233d2e94f9da1928a85aac29ccf (native collection
   06:47–07:00 UTC October 19) records 35 generic-text occurrences across five pages, but stored page items sum
   63 anchors. Mixed empty/generic anchors explain the difference. October 18 audit 0280b2b30c034d9c95b69d23932ba0c6
   is also available. Only the October 18 Desktop PDF was found; October 19 PDF page claims remain unconfirmed.
2. **Confirmed code causes.** report._link_count used links, not links_with_generic_text. with_page_items retained
   old derived items. STR7 treated figure/file/size as informative-purpose evidence. Runner/CLI obtained ranking
   samples after reader slots were exhausted, so those samples could not guide coverage. The executive opportunity
   filter did not distinguish supported editorial topics from service opportunities. Ranking is not commercial value.
3. **Change.** Recalculate only generic page-item counts from qualifying evidence, including saved derived items,
   without rewriting originals. Preserve all-anchor/group/page units. Record per-image role gaps and presentation
   context; retain unnamed functional links and explicit informative-caption cases, structural equivalents separately.
   Unknown image roles remain unassessed, not certified decorative. Use existing approved DFS calls before reading;
   home/key pages first, then at most min(10, effective reader cap // 3) unique same-site ranking pages. Existing
   robots, deadline, request/page/credit guards remain authoritative. Reassess provider rows once final native/reader
   content exists; no duplicate paid call or supplemental crawl. Keep editorial matches visible and explicitly label
   commercial value unestablished. No new keyword whitelist, ownership inference or provider-total extrapolation.
4. **Regression / contrast.** Mixed empty+generic anchors versus two genuine generic occurrences and descriptive
   target names; weak image wrappers versus informative charts and unnamed links; neutral-file chart within a
   nutrient table; other-brand service/editorial/missing-page cases; actual mocked worker order, attempted priority
   URL, final reassessment and saved-paid-result reuse; summary/print/PDF/client routes and immutable source files.
5. **Compatibility / boundaries.** No new frozen report fields: extra check/provider evidence is explicitly outside
   the frozen schema (REPORT-SCHEMA.md). No budget increase, approval bypass, resume-ledger change, historical mutation,
   dependency change or release. Approved search-data collection now precedes reader spending under the same shared
   deadline; a late stop can therefore leave a different approved phase incomplete. Missing historical landing content
   cannot be recreated. Image pixels/computed CSS are absent; human review is required, not a claim of decoration.
6. **Owner retest.** Historical originals remain historical. Inspect copied offline analysis outputs, existing
   History summary/page table/technical PDF and Client report draft. No new paid audit is required for these checks.
   Future audits within the same approved cap can prioritize ranking pages; do not rerun a paid audit solely to test
   this patch. Tests use only mocked provider responses and loopback servers.

Acceptance follow-up: the independent reviewer reproduced a candidate/reader scope mismatch by inspection. Candidate
selection now uses the reader's exact same-origin guard; www/scheme/port variants are not silently treated as equivalent.
The homepage does not consume a ranking-priority slot. Within the bounded candidate set, the approved DFS-5 near-page-one
sample precedes DFS-4-only rows, then estimated search volume orders pages. This prioritizes missing branch/article
assessment without asserting relevance. On the saved October19 sample, the candidate set now includes the holiday,
horoz-şekeri and Beylikdüzü landing pages. They were not fetched during this task and remain historically unassessed.

Existing image fixtures were strengthened with explicit chart captions/functional context while preserving their
original detection/count assertions. They still test sharing, lazy loading, payload bounds and full-engine scenarios;
new tests separately assert uncertainty for wrapper/name/size-only cases. A real immutable-summary identity regression
and a translated-label regression were fixed, not bypassed. PDF visual review also caught a Turkish note incorrectly
labelled English; already-Turkish entries now retain their text/instructions instead of re-entering translation fallback.

Final saved-report acceptance found another path that a passing suite had not exercised: October19 retained an old
opportunity_evidence=true for the already-supported editorial query. Fresh relevance processing fixed it, but ordinary
viewing still trusted the old flag. Reproduction: /tmp/maya-oct19/stale-opportunity-before.py semantics recorded in private
stale-opportunity-before.json (one nearest-gain recommendation, rank4,2900 estimated searches). A shared pure
insights.qualified_opportunity_data adapter now derives recommendation flags/editorial grouping from the existing
saved dimensional assessments in fresh generation, paid.describe and practical.opportunities. No source JSON write or
new collection/classification occurs. New normal-route regression covers stale true editorial and stale false genuine
service flags, source immutability, summary/print propagation and retained uncertain cases. This additional demonstrated
path requires a final full-suite rerun after the earlier1585-pass result; the earlier result alone did not establish accuracy.

Independent review also identified cross-URL borrowing in the new read-time adapter. Offline reproduction returned two
editorial landing rows when only one URL had supported evidence. The adapter now joins query + ranking URL, retaining
an older URL-less record only for a unique landing row. Missing/uncertain second URLs cannot borrow support or qualify
a commercial opportunity. The original two-row failure is preserved privately; an additional non-brand regression checks
both an explicitly uncertain URL and a URL whose assessment is absent. The normal route/source-immutability tests pass.
