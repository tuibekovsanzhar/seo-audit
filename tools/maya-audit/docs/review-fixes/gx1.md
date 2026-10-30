# gx1: generalisation fixes (review G, brand-independent quality)

Worker gx1, branch fix/gx1. Items from BRIEF_G: G01, G02+G03, G04, G16, G27+G06 (link side), empty-response
corroboration (C1/C2), crawl priority for hreflang/canonical targets, same_page helper (G17, for gx2).

## Item 8 (G17 helper): `structure_data.same_page(url_a, url_b)`
- What: `maya_audit/structure_data.py:same_page` (+ `_page_key`). True when two addresses differ at most by scheme
  (http/https), a "www." prefix, a default port and a trailing slash. Query and path letter case must match.
- Why: STR-9 compares `canonical != page.url` directly, so `/en` with canonical `/en/` reads as "canonical points
  elsewhere" (G17). structure.py is gx2's file; gx2 should use `same_page(canonical, page.url)` there.
- Test: tests/test_gx1_same_page.py.
- For gx2: `from ..structure_data import same_page`.

## Item 1 (G01): IDX-4 parameter and pagination views are consolidation, not "different content"
- What: `maya_audit/urls.py:listing_view_of(url, target)` returns "parameters" (same host and path, target query a
  strict subset of the page's, by `parse_qsl` pairs) or "pagination" (`is_pagination(url)` and the target is page 1 of
  the same list: the path with `/page/N` removed or the same path, query a subset of the page's without the page
  parameter). `checks/index.py:idx4_canonicals` checks it only in the last branch, after a broken, noindexed or
  unreadable target has been judged as before, and puts the page in a check observation "parameter or pagination
  pages consolidate to their listing" (with `view` per row) instead of comparing content.
- Why an observation, not an Info finding: it is normal and present on most listing sites (noise policy); Info lines
  are counted against the per-site caps. Genuinely different same-site targets (another path) still get S2.
- Pagination is strict on purpose: page 2 canonical to an unrelated page is still compared (and S2 when different).
- Tests: tests/test_gx1_listing_views.py; neutral suite (shop-de, tarif-sube, shopify).
- Left: the 0.8 word-share threshold was not recalibrated (needs five site types of real data).

## Item 2 (G02 + G03): IDX-5 draft/test pages
- What: `maya_audit/index_data.py:draft_pages` rewritten, with helpers `_draft_word`, `placeholder_title`,
  `_shell_page`, `_own_content`, `_fold_label`. config.py (appended): `DRAFT_PATH_WORDS_OTHER` (de/fr/es/it/ar) and
  `DRAFT_PLACEHOLDER_TITLES` (tr/en/fr/es/de/it/ar, 14 items).
- Rule now: (address signal) AND (no title OR a CMS placeholder title, whole or one part between site-name separators)
  AND (found only through the sitemap). Address signals:
  - draft word: a whole path segment ("/test", "/taslak/"), or the FIRST word of the last segment when draft words are
    at least half of its non-numeric words ("/test-marka", "/test-22222"). Not "/request-demo", "/blog/ab-test-nedir",
    "/latest", "/demo-day-istanbul-2026".
    Deviation from the brief's letter: "/test-drive" and "/sample-recipes" have the same shape as Arjava's must-find
    "/test-marka" and "/test-sayfaaaa", so the word rule alone cannot tell them apart; their titles do (the AND).
  - "-N copy": the last segment is a stem sibling's slug plus "-<digits>", AND the page's own main content
    (`content_blocks`, chrome left out, normalised, non-empty) equals that sibling's. Not the raw-HTML text hash, which
    every SPA shell shares. Only stem siblings count (the old "any page with the same text hash" is gone).
- A raw page with an empty framework mount node (the RND-1 shell signal) is not judged on its missing title; when the
  audit rendered the page, the rendered title is used. Repeated-block filtering is NOT applied to the content compare:
  Arjava's drafts reuse site text and would come out empty.
- Tests: tests/test_gx1_drafts.py; neutral suite saas-spa (raw + rendered), tarif-sube (/ornek-menu, /tarifler/kek-2),
  draft-real (positive control, still one S3 with /taslak, /test, /hakkimizda-2); Arjava regression green.
- Note: config's comment on DRAFT_PATH_WORDS ("whole words of the segment") predates this rule; config is append-only
  for me, so the new rule is described beside DRAFT_PATH_WORDS_OTHER and in `_draft_word`.

## Item 3 (G04): IDX-8 "reachable at two addresses"
- What: `maya_audit/index_data.py:address_pairs` with `_address_differences` and `_points_to`. `differs_in` names every
  difference in order: "trailing slash", "file extension", "letter case" (joined with " and "). `/x` vs `/x/` was
  labelled "file extension" because the key folds the slash but the label compared raw paths. A pair where one address
  names the other as canonical (`canonical_target`) or redirects to it is left out: the site already says which
  address is the page. (idx8_duplicates already drops canonical-elsewhere pages before pairing; the check now also
  holds for any caller.) The evidence "rule" sentence in checks/index.py:idx8_duplicates says so.
- Kept address: without the extension, else the lower-case one, else the first in crawl order (slash-only pairs).
- Tests: tests/test_gx1_address_pairs.py; neutral local-wp (`/iletisim` pair still S4, now "trailing slash");
  test_w3_index pair tests unchanged and green.

## Item 4 (G16): a noindex page in the sitemap is one finding (S3)
- What: `checks/access.py:_should_be_indexed` no longer adds the separate S2 "The sitemap lists N page(s) that carry
  noindex". The S3 "noindex via ... on N page(s) the sitemap lists: check that this is intended" (title already states
  both facts; LISTED_NOINDEX_FIX already says to take the pages out of the sitemap) carries `listed_in_sitemaps` and
  `sitemap_side` in its evidence. Key pages and sitemap pages the menu links stay S1 (unchanged).
  `checks/index.py:idx5_sitemap`: a noindex page the crawl read is listed beside the share
  (`noindex_reported_under_acc3`, also in `breakdown`), not counted in it, like canonical-elsewhere URLs; a noindex
  seen only by the sitemap check's light request (ACC-3 never sees it) is still counted.
- Decision narrowed: H26 / CR-33 (sitemap contradiction as its own S2). Reason: one state, two findings, and the
  hygiene side ranked above the directive; many CMSs list noindex pages automatically. SITEMAP_NOINDEX_TITLE/FIX and
  the wording entry `acc3.sitemap_noindex` are left in place (unused by the engine now; removing them is the lead's
  call because the catalogue test lists them).
- Tests changed consciously: test_preview16_false_alarms (renamed `..._is_one_s3_finding`), test_w1_crawler
  (renamed `test_a_sitemap_page_with_noindex_is_one_s3_finding`), test_idx_scenarios::test_sitemap_health (the share
  now settles: dead URLs are IDX-1's, the noindex page ACC-3's). Neutral bank-multi G16 tests now pass.

## Item 5 (G27 + G06 link side): CDN/edge machinery is never a broken link
- What: config.py (appended) `EDGE_MACHINERY_SEGMENTS` = cdn-cgi (Cloudflare), akam (Akamai), _vercel (Vercel),
  .netlify (Netlify), _incapsula_resource (Imperva). `index_data.edge_machinery(url)` returns the vendor of a URL whose
  first path segment is one of them. IDX-1 leaves those URLs out (evidence key `cloudflare_machinery_left_out` kept for
  compatibility, now with `vendors`), IDX-6 never counts a link there as broken. `cloudflare_machinery` is kept (now
  unused by the engine) so nothing that imports it breaks.
- The neutral tests for /akam/ and /_vercel/ passed vacuously (both paths were only <script src>/<img>, never an
  <a>, so no link was ever judged). fakeserver/neutral_scenarios.py, minimal edit, two lines: shop-de's /datenschutz
  links `/akam/13/2e5f8a1b` (404); saas-spa's static /legal/print links `/_vercel/insights/script.js` (404). With the old
  code both tests and both S1-S3 set tests went red (IDX-1 S2 4xx linked); with the fix green; Info caps unchanged.
- Tests: tests/test_gx1_edge_machinery.py; neutral shop-de and saas-spa.
- Left: platform/CDN naming from headers (the G06 site_platform side) is gx3's.

## Item 6 (first review C1/C2): empty pages need a second client before S1/S2
- What: `index_data.empty_browser_check` (collector, run in `collect_index_data` right after the IDX-1 refetches):
  pages empty on the crawl AND on the refetch are asked once more with `probes.BROWSER_USER_AGENT`, at most
  `config.EMPTY_BROWSER_CHECK_URLS = 3` (homepage and key pages first), purpose `empty_browser_check`, header
  `X-Maya-Probe: ua-differential`, robots.txt checked for Maya's token, the fetcher's pace and time limit, never
  retried; off when `probes_enabled` is False or the crawl stopped early (rate limit, robots, network). Stored in
  `IndexData.empty_browser_check`.
  `checks/index.py:_empty_pages`: a browser got content on any sampled page -> one finding "N page(s) answer with an
  empty page to automated clients only (under 512 bytes); a browser gets content", S3, Estimated, fix BOT_EMPTY_FIX
  (bot filter / WAF / CDN rule / UA-keyed cache), evidence `browser_check`; the browser also empty -> the old verdict
  (S1 key / S2 other, evidence `browser_check`); not asked -> repeated rows stay at S3 with
  `observation_strength: repeated_empty_same_client_only`. Single-observation rows unchanged (S3).
  INT-4 (`checks/integrity.py`): these requests are kept apart from Maya's own; compliant when at most 3, all tagged,
  browser user agent only; the summary counts them.
- Decisions narrowed: 204 (S1/S2 for repeated empty pages now also needs the browser answer to be empty; two answers
  to one client are one client's view) and 241's severity table accordingly; 205 is unchanged (ACC-4 still excludes
  empty pages from its sample, so its browser answers are never reused here; this is a separate, capped check gated by
  the same `probes_enabled`). 216 unchanged. Requests: up to 3 more to the audited site.
- Wording (outside my files, few lines): maya_audit_web/wording.py `idx1.empty.bot`; maya_audit_web/sentences.py
  `int4.empty_check`, `int4.empty_over_cap`, `int4.empty_untagged`, `int4.empty_agents`;
  maya_audit_web/locales/findings/tr.json entries for those, the new fix, expected result and four notes.
  tests/test_web_app.py BUILT_TITLES gets the new IDX-1 title sample.
- Tests: tests/test_gx1_empty_browser_check.py (bot-specific S3; browser empty keeps S2; probes off stays S3; INT-4
  compliant). Changed consciously: tests/test_next_accuracy.py (empty_case and the mixed-importance test model the
  browser answer; two new asserts for the unconfirmed and bot-specific cases), tests/test_round2_empty_and_googlebot.py
  (its audits run with probes off, so the repeated empty page is S3 now).

## Item 7 (live gap 3): hreflang and canonical targets of the homepage/key pages are read early
- What: `crawler.py`: after the homepage or a key page is read (the same `why` that drives render discovery),
  `head_link_targets(page, origin)` (hreflang alternates, then the canonical target, same origin, not the page itself,
  at most config `ALTERNATE_PRIORITY_MAX_PER_PAGE = 10`) is queued with via "alternate". `worker folder.py`:
  `PRIORITY["alternate"] = 1`, the key-page class: strict order, after the start URL and key pages by sequence, before
  navigation links (2), links (3), sitemap URLs (4) and pagination (5). On conflict a URL already queued moves up but
  keeps its route (`via` is not overwritten by "alternate"), so a sitemap URL stays "sitemap" for IDX-7's orphan test,
  INT-2's sitemap-only count and the IDX-5 draft rule. A URL first found this way has `discovered_via == "alternate"`.
- Why priority 1, not 2: `get_next_url` derives `nav=True` from `priority == NAV_PRIORITY`.
- Not changed (not my files): models.py's comment listing discovered_via values (add "alternate"), and the Firecrawl
  reader's own class table (firecrawl/reading.py `_CLASS`) which has no "alternate" route.
- Tests: tests/test_gx1_alternate_priority.py (cap 4 with 15 nav links: /en read via hreflang only; listed in the
  sitemap it is read and stays "sitemap"; frontier order unit test). All three fail without the change.

## Full suite (3.12) and follow-ups
- First full run: 4 failed, 2133 passed, 1 skipped, 27 xfailed. Fixed after it:
  - test_fixture_matrix: docs/FIXTURE-MATRIX.md regenerated (scripts/fixture_matrix.py) for the new/renamed tests.
  - test_round2_sitemap_and_llms::test_a_cap_above_the_sitemap_checks_every_url_and_says_of_n: its audits run with
    probes off, so the crawled empty pages are now `repeated_empty_same_client_only` (item 6); assertion updated.
  - test_time_limit::test_running_out_of_time_before_the_structure_step...: the homepage's hreflang target is now read
    by the crawl (item 7), so it was no longer "not fetched"; the hreflang link moved to the non-key page /basliksiz so
    the test still checks an unrequested target.
  - test_web_app::test_the_api_stays_responsive_while_a_500_page_audit_runs: timing; passes alone (the full run shared
    the machine with a 3.11 run).
- Xfail markers removed: G01 x5, G02 x4, G03 x1, G04 x1, G16 x3 (14). tarif-sube's S1-S3 set stays xfail, re-labelled
  G08 (its IDX-4 and IDX-5 parts are fixed).

## Review follow-ups (after the full run)
- Item 6, mixed browser samples: each sampled page follows its own browser answer (content -> bot-specific S3; empty ->
  confirmed S1/S2); a page not asked follows the sample only when every answer agrees, otherwise S3 with
  `observation_strength: repeated_empty_mixed_browser_sample`. Test: test_gx1_empty_browser_check
  `test_a_mixed_browser_sample_puts_each_page_where_its_own_answer_says`.
- Item 2, shell rule tightened: a raw page is skipped only when it has an empty mount node AND no main-content text of
  its own (a classic CMS with an empty `#app` widget still has its drafts judged).
- `discovered_via == "alternate"` has no label map to update (nothing in maya_audit_web or the report maps
  "rendered_link" either).
- 3.11: the changed test files (neutral, Arjava, next_accuracy, round2 x2, idx_scenarios, preview16_false_alarms,
  w1_crawler, time_limit, fixture_matrix, wording, test_gx1_*): 311 passed, 27 xfailed.
