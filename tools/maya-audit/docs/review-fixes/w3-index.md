# W3 — index checks and root-cause grouping (branch fix/w3-index)

Notes for the lead, one block per item: what changed, why, the test, and anything left undone. Proposed DECISIONS
entries are marked **Decision**.

## H09 — Cloudflare /cdn-cgi/ is not a broken link
- `config.py` (appended): `CLOUDFLARE_PATH_SEGMENT = "cdn-cgi"`, `CLOUDFLARE_EMAIL_PATH`.
- `index_data.cloudflare_machinery(url)`: the first path segment is `cdn-cgi`. Only that segment, not all of
  `PRIVATE_PATH_SEGMENTS`: a dead link under `/api/` or `/admin/` is still a dead link.
- `checks/index.idx1_http_status`: such URLs leave every IDX-1 group; listed in check evidence
  `cloudflare_machinery_left_out`. `idx6_broken_links`: such targets are not broken.
- `index_data.cloudflare_email_pages(result)` + IDX-6 Info finding "Cloudflare e-mail obfuscation is on: the address is
  readable only with JavaScript" (scope = the pages). Signals: an outlink to `/cdn-cgi/l/email-protection`, or the text
  "[email protected]" in `_visible_text` (covers `data-cfemail` / `__cf_email__` without a link). `html_links.py` was
  not changed: the outlink plus the placeholder text covered every form seen; no raw-HTML pass was added.
- Tests: Arjava `test_cloudflare_email_obfuscation_is_a_note_not_a_broken_link` (xfail removed);
  `test_w3_index.py::test_an_address_hidden_by_cloudflare_without_a_link_is_a_note`.

## H10 / CR-03 — one dead target, one finding
- `root_cause._broken_targets` (runs after `_empty_pages`, guarded by `MARK` in IDX-6's evidence): IDX-6's
  "Link target returns …" findings whose target is in IDX-1's referenced-4xx finding are removed from IDX-6 and folded
  into that IDX-1 finding: title gets `IDX6_SUFFIX` ("; linked from M page(s)"), evidence gets `broken_links` (one row
  per dead target with status, `linked_from_count`, the links), `linked_from`, `linked_from_count`; importance tier is the
  best of the merged ones. IDX-6's summary says "N broken target(s) are said under IDX-1, with the pages that link to
  them." and its status settles like the IDX-5 pattern (`_settle`).
- **Decision** (narrows DECISIONS 20): the per-target task is kept as a row of IDX-1's evidence, not as its own finding,
  when IDX-1 already reports the URL. Targets IDX-1 does not report (5xx targets) stay one IDX-6 finding each.
- Test: `test_w3_index.py::test_a_dead_target_linked_from_four_pages_is_one_finding_with_its_sources` (also checks
  `findings_in_priority_order` holds the dead URL once).

## H13 — draft / test pages
- `index_data.draft_pages(result)`; `config.DRAFT_PATH_WORDS`. Only pages listed in the sitemap, 200, HTML, no noindex,
  not canonical elsewhere. Signals: (a) a folded word of a path segment in the list (word boundary on `-`/`_`/`.`) AND
  (no title OR found only through the sitemap) — so a titled, linked `/request-demo` is not caught; (b) last segment
  `<stem>-<digits>` AND no title AND sitemap-only AND (another page has that stem — a sibling `/arjava-3` or `/arjava` —
  or another page has the same text hash). Product slugs ending in a number have titles and links, so never match.
- **Decision** (deviation from the plan): the finding lives in **IDX-5** (sitemap health), not a new IDX-11. A new check
  id ripples into the registry, coverage, findings.py, recommendation catalog, the client `kontrol_katalogu.json` (two
  copies) and several tests; the finding is about what the sitemap offers, which IDX-5 owns. Title
  "N draft or test page(s) are indexable and listed in the sitemap", S3, Confidence Inferred (that it is a draft is
  inferred; indexable + listed is verified), fix "Add noindex to these pages or remove them, and take them out of the
  sitemap." Drafts not listed in the sitemap are not reported (not covered by this item).
- Said once: IDX-7 leaves drafts out of orphans (`evidence.draft_pages_left_out`), IDX-8 leaves them out of the
  comparison, and `root_cause._said_elsewhere` takes them out of STR-1 "have no <title>" and also STR-15 thin content
  (STR-15's fix mentions noindex, so the Arjava test saw two findings; a draft's shortness is the draft's problem).
  STR-1 and STR-15 were not edited (W2's files).
- Tests: Arjava `test_draft_pages_are_reported_once_with_the_right_advice` (xfail removed);
  `test_w3_index.py::test_a_demo_page_with_a_title_and_links_is_not_a_draft`.

## H20 — one page at two addresses
- `index_data.address_pairs(pages)`: same host and query, path equal after lower-casing and dropping
  `config.PAGE_EXTENSIONS` (.aspx/.asp/.php/.html/.htm/.jsp), and the same `text_sha256`. `kept` = the address without
  the extension (else the lower-case one).
- IDX-8: new S4 finding "N page(s) are reachable at two addresses" (both URLs in scope, `evidence.pairs`), fix: one
  address, 301 or canonical. The second address leaves IDX-8's own copy comparison.
- `root_cause._said_elsewhere` removes the second address from STR-1 shared-title and STR-16 shared-description groups
  (groups left with one page are dropped, with a summary sentence); `_duplicates` then absorbs what is left as before.
- Tests: Arjava `test_one_page_at_two_addresses_is_reported` (xfail removed);
  `test_w3_index.py::test_one_page_in_two_letter_cases_is_one_pair_and_not_a_shared_title`,
  `test_address_pairs_need_the_same_text`.

## H22 / B02, B03 — canonicals
- `index_data.canonical_variant(canonical, url)` (same host ignoring `www.`, same port, other scheme and/or www →
  `counterpart` on the page's own scheme/host), `canonical_target(page)`, `canonical_elsewhere(page)`. Used by
  `structure_data.indexable_pages` (a variant canonical of the page itself is self-canonical, so the page stays in
  STR/TSEO), IDX-8 candidates, `answer_kind` (IDX-5 no longer calls it canonical_elsewhere), the canonical-target fetch
  in `collect_index_data`, and IDX-4.
- IDX-4: S3 "N page(s) declare a canonical on the http:// or www variant of this site" (evidence `judged_as`); the
  target is then judged as its counterpart. A canonical that only upgrades an http:// page to its https:// address is
  not reported. S3 "N page(s) are noindex and declare a canonical to another URL" (mixed signals). With more than one
  distinct canonical the page goes to `not_assessed` and no target is judged. Relative canonical and "indexable page
  declares no canonical" are **observations**, not Info findings: several fixtures use relative canonicals and most
  pages declare none, so an Info finding would flip IDX-4's status across the suite and add noise; Google resolves a
  relative canonical and does not require one.
- Not touched (other owners): `checks/structure.py:577` still compares `effective_canonical` to the page URL for the
  WebPage `url` mismatch check (W2) — a variant canonical there is read as "own" address only when equal.
- Tests: `test_a_canonical_on_the_http_or_www_variant_is_judged_as_the_same_address`,
  `test_canonical_variant_noindex_conflict_and_two_canonicals`.

## B12 — temporary http→https redirect
- IDX-2: rows with outcome `redirects_to_https` and status 302/303/307 give an S4 finding "http:// redirects to https://
  with a temporary redirect on <hosts>"; no new outcome name (the web layer words outcomes by name).
- Test: `test_a_302_from_http_to_https_is_a_temporary_redirect_finding` (constructed hosts; loopback skips the probe).
- Not done: HSTS/CSP header capture and mixed content (the rest of B12) — crawler/probe files are not mine.

## B16 / C21 — empty 200s in INT-2
- `integrity.int2_crawl_completeness`: empty 200 responses add the reason "N page(s) answered with an empty page, so
  links on them could not be read", evidence `empty_pages`, and a fix sentence. The crawl is then incomplete, so IDX-7
  does not call pages orphans. Arjava stays complete (no empty pages).
- Test: `test_an_empty_page_makes_the_crawl_incomplete_and_no_page_is_called_an_orphan`.

## B17 / C22 — a single 5xx observation
- IDX-1: a 5xx seen once and not asked again (refetch cap) is an S3, Confidence Estimated finding "N URL(s) returned a
  server error (5xx) on the one request made" (`observation_strength: single_observation`), not only an observation.
  Its title contains "server error (5xx)", so it also gets `retrieval_membership` and root_cause counts it in the IDX-5
  overlap like the persistent 5xx finding (intended: it is said once, under IDX-1).
- Test: `test_a_single_server_error_beyond_the_refetch_cap_is_an_estimated_finding`.

## B22 — dead code; CR-28 / C15
- `in_exact` no longer exists. `_empty_pages(…, history, …)`: unused parameter removed.
- CR-28: when root_cause takes IDX-1's pages out of IDX-5's share finding, the title is rebuilt (`IDX1_BESIDE`) so its
  first number is the URLs left — the number "Affects N" shows — and the share (with IDX-1's pages, DECISIONS 215) is
  said after them: "8 of 41 sitemap URL(s) are not live, indexable pages besides the 12 empty or failing page(s)
  reported under IDX-1 (49% with them)". Old title keys stay as `SAVED_ONLY`. Tests updated:
  `test_preview16_grouping`, `test_round2_sitemap_and_llms`, `test_web_app` BUILT_TITLES samples.

## CR-29 — note only
- `report.repeated_key` (DECISIONS 225) is still dead; `report.py` belongs to W4a, not changed here.

## Touched outside my files
- `maya_audit_web/wording.py`, `maya_audit_web/sentences.py`, `maya_audit_web/locales/findings/tr.json`,
  `maya_audit_web/locales/catalog/tr.json`, `maya_audit/recommendation_catalog.py`: table rows for the new titles,
  fixes, expected results, notes, summary sentences and catalogue notes (appended rows only).
- `tests/test_web_app.py` (BUILT_TITLES samples), `tests/test_preview16_grouping.py`, `tests/test_round2_sitemap_and_llms.py`
  (CR-28 title), `tests/test_arjava_regression.py` (three xfail markers removed), `tests/test_brand_and_launch_gate.py`,
  `tests/test_false_alarms.py`, `tests/test_idx_scenarios.py` (the dead 404 target is now read under IDX-1; CR-28 title),
  `tests/test_next_accuracy.py` (`_empty_pages` lost its unused `history` argument), `docs/FIXTURE-MATRIX.md`
  (regenerated by `scripts/fixture_matrix.py`).

## Full suite (Python 3.12, this machine)
- 1757 passed, 9 failed before the last test fixes; after them the 7 W3-caused failures pass. The 2 left fail identically
  on the base commit a66a97b (checked in a clean worktree), so they are environment, not W3:
  `test_no_unfilled_placeholders.py::test_the_pages_own_sentence_filler_follows_the_same_rule` (“…” read back as “�”:
  console code page) and `test_pre_interface_fixes.py::test_earlier_frozen_copies_are_kept_and_differ_from_each_other`
  (schema-shape count 17 vs 18).
- Run pytest with a short `--basetemp`: the worktree path is so long that the web tests' evidence files pass Windows'
  260-character limit (FileNotFoundError, the audit ends `internal_error`).
