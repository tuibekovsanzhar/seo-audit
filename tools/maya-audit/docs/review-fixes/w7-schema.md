# w7-schema: P2, structured data a site lacks (2026-10-22)

Plan: `seo_audit/maya-audit-kor-nokta-plani.md` (P2). Decision: DECISIONS 250. Built on `fix/w6-media` (P1).

## What was missed, and why

| Missed live | Cause in the code |
|---|---|
| No WebSite node on the homepage | `EXPECTED_TYPES["homepage"]` held only Organization types |
| Seven questions with answers on the homepage, no FAQPage | FAQ pages were told by their address only (`FAQ_WORDS`), never by what they show |
| The broken Organization also lacks logo and sameAs | `organization_gaps` runs only on a block that parses |
| The English FAQ page has no FAQPage | `frequently-asked-questions` and `sikca-sorulan-sorular` were not FAQ words |

## Changes

- `analysis.py`: `breadcrumbs` (a visible element whose class, id or aria-label says breadcrumb: links and items).
- `checks/structure.py`: `qa_block` (question-mark runs, any script); STR-3 Info for Q&A without FAQPage/QAPage and
  for a breadcrumb trail without BreadcrumbList; WebSite as an STR-3 observation; `recommended_still_lacking` in the
  broken Organization's evidence; FAQ rich-results note as one constant.
- `page_words.py`: FAQ words in their spelled-out forms.
- `root_cause.py`: STR-3's Q&A note leaves out IDX-5's drafts, as STR-1 and STR-15 do.
- `single_page.py`: the WebSite observation is left out when the page audited is not the homepage.
- `recommendation_catalog.py`, `maya_audit_web/wording.py`, `sentences.py`, `locales/*/tr.json`: titles, fixes,
  expectations, notes and catalog explanations in Turkish; STR-10's 200 px and 600 px notes split.

## Tests

`tests/test_p2_schema.py`, 16 tests; on the code before P2 the 6 "must find" tests fail and the 10 "must not" tests
pass: two pairs, long question-led sections, questions answered by questions, a hidden breadcrumb, a one-step
breadcrumb, a breadcrumb with no link, a page that has the markup, WebSite inside an unparsable block.

Brand-neutral probe (8 fixtures, not committed): the Q&A and breadcrumb notes fire on none; WebSite would have fired
on all 8, which is why it is an observation.

## Client report

The `maya-audit-pro` skill (Efsa's, outside this repository) turns these into one "structured data the site could
add" to-do card and adds the logo/sameAs line to the broken Organization card.
