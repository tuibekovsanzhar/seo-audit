# w9-chrome: P4, menu language, question headings, address spelling (2026-10-22)

Plan: `seo_audit/maya-audit-kor-nokta-plani.md` (P4). Decision: DECISIONS 252. Built on `fix/w8-consistency`.

## Changes

- `analysis.py`: `_content_block_toggles` (text inside `<summary>` or `<dt>`).
- `checks/structure.py`: `_qa_run`, `questions_not_headings` (STR-2 observation); `chrome_labels`,
  `chrome_language_mismatch` (STR-9 observation).
- `checks/content_quality.py`: `slug_typos` (STR-14 observation).
- `page_words.py`: `UI_WORDS`, `UI_WORD_LANGUAGES`.

## Oracle checked first

- `/ciceksi-kukular` is linked as "Çiçeksi Kokular" (so the rule can fire live); `/en` pages declare en-US (so their
  English menu is not a false alarm).
- The English labels of the Turkish menu are not visible text but the icons' alt and title ("My Cart" before
  "Sepetim"): the rule reads alt text, as a screen reader does.

## Tests

`tests/test_p4_chrome.py`, 19 tests: must-not cases are <h3>, <summary>, <dt>, <button> questions; inflection
endings, `sets`, `difuzor-8`, a last-letter brand variant, a coined word; an English page, a German menu of loanwords,
a language switcher, a single foreign label. Neutral probe: question and address rules fire on none of the 8
fixtures; the menu rule notes the Spanish pages of bank-multi and news-video, which reuse the English and French
menus (true by the rule). Info counts unchanged; the arjava fixture's concise PDF stays within ten pages.

## Not done

H30 (image preloaded but hidden on phones): needs a phone-width render.

## Full suite

2,405 passed, 1 skipped, 1 failed: `test_round2_sitemap_and_llms.py::test_a_cap_above_the_sitemap_checks_every_url_and_says_of_n`.
It is flaky before this change too (2 of 6 runs fail alone on `fix/w8-consistency`): the empty-answer classification
of the fixture varies between `repeated_empty_same_client_only` and a single probe. Not touched here.
