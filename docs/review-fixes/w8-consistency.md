# w8-consistency: P3, links and tags that disagree with the page (2026-10-22)

Plan: `seo_audit/maya-audit-kor-nokta-plani.md` (P3). Decision: DECISIONS 251. Built on `fix/w7-schema`.

## Changes

- `access_data.py`: `llms_links` reads bare addresses and autolinks (`_BARE_URL`, code spans left out). The redirect,
  404 and empty-page notes of ACC-8 already existed; they now see these links.
- `checks/structure.py` (STR-10): observations `OG_URL_DIFFERS` and `EMPTY_META`.
- `checks/index.py` (IDX-6): observation of other-site links with click identifiers or logged-in view parameters
  (`VIEW_PARAMETERS`); utm_* left out after the live run flagged a platform's referral-tagged footer link.

## Not done, on purpose

- Plan item "promote an observation to a finding when it touches the homepage": replaced, as in P2, by the client
  report's own card (`maya-audit-pro`, "small fixes"), so the engine's calibration (G13, Info caps) is unchanged.
- og:url "https://site" vs canonical "https://site/": the same URL, not reported.

## Tests

`tests/test_p3_consistency.py`, 10 tests: 5 fail on the code before P3, 5 "must not" pass on both (mailto, a word, a
code span, the root slash, a clean profile link with ?hl=). Brand-neutral probe: none of the new rules fires on the 8
fixtures; Info counts unchanged; the arjava fixture's concise PDF stays within ten pages.
