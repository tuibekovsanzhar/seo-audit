# W1 — crawler, robots, access checks: review fixes

Branch `fix/w1-crawler`. Regression tests for every item are in `tests/test_w1_crawler.py` unless another test is named.
Decisions the lead should merge into docs/DECISIONS.md are marked **Decision**.

## Robots and access

- **H17** (ungrouped robots.txt rules). `robots.parse_robots` keeps `RobotsTxt.ungrouped` = (line, text) for every
  Allow/Disallow/Crawl-delay above the first User-agent line (a Crawl-delay there was silently dropped before).
  `checks/access.acc1_robots_availability` reports them: ACC-1, S4, Verified, "N robots.txt rule(s) come before any
  User-agent line, so no crawler applies them", evidence `ungrouped_lines`. Tests:
  `test_rules_before_any_user_agent_are_kept_with_their_line_and_text_and_apply_to_nobody`, Arjava
  `test_an_ungrouped_robots_rule_is_reported` (xfail removed).
- **A5** (robots.txt still 3xx after the hops / no Location). `robots.policy_from_response`: 3xx is `allow_all`
  with reason "... RFC 9309 §2.3.1.2: unavailable, crawling allowed" (was `disallow_all` "unexpected status").
  Other unexpected statuses (1xx) keep the old disallow. **Decision**: follows RFC 9309 §2.3.1.2; DECISIONS 3 (429)
  unchanged. Test `test_a_robots_txt_still_redirecting_after_the_hops_is_unavailable_and_allows_crawling`.
- **B05** `directives.noindex_directives(None, headers)` reads X-Robots-Tag. Test
  `test_noindex_in_a_header_is_read_without_an_html_analysis`. (Callers in index_data/IDX-5 benefit; not edited.)
- **B06** `directives.unavailable_after()` parses ISO 8601, RFC 822 and RFC 850 dates; `_parts` keeps a date with a
  weekday comma whole. ACC-3: a passed date is treated like noindex with the same severity rules (label
  "unavailable_after (date passed) via ..."); a future date is Info "unavailable_after <date> via ...". Bing is not
  named for it (Google documents the directive). Test `test_unavailable_after_a_past_date_is_a_noindex_and_a_future_one_a_note`.
- **H26 / CR-33** (ACC-3). A noindex page listed in the sitemap that is not a key page and not linked from the
  navigation: the noindex is S3 "noindex via X on N page(s) the sitemap lists: check that this is intended", and a
  separate S2 "The sitemap lists N page(s) that carry noindex". Key pages stay S1. **Decision (narrows DECISIONS 222
  only where needed)**: a sitemap page the menu also links stays S1 and a utility page stays the S3 note, exactly as 222
  says; only "sitemap alone" moved from S1 to S3 + S2. Intent marking of the noindex works as before (condition
  "noindex"); the S2 has no intent condition (the sitemap contradicts the page whatever was meant). IDX-5's share
  finding still counts noindex URLs in its share (different root cause: the sitemap's overall quality). The client
  report rule R13 (`client_reporting/references/onem_kurallari.json`, "(?i)noindex" on utility URLs) only lowers to
  Info, so it does not undo the S3; it also lowers the new S2 when every URL is a utility path.
  Tests: `test_a_sitemap_page_with_noindex_is_s3_and_the_sitemap_listing_it_is_its_own_s2`; the pinned
  `tests/test_preview16_false_alarms.py::test_noindex_on_an_ordinary_page_listed_in_the_sitemap_stays_a_blocker` was
  rewritten consciously as `..._is_s3_and_the_sitemap_contradiction_s2`.
- **B13** ACC-2 builds write `evidence["blocked_tokens"]` (the tokens the rule blocks); the policy-mismatch, group
  precedence and retired-token notes write `[]`; ACC-6 writes the tokens with a blocked count above 0. ANS-4
  (`checks/answers._blocked_tokens_for`) reads only `blocked_tokens`; the title fallback is gone. `ENGINE_CRAWLERS`:
  chatgpt = OAI-SearchBot, ChatGPT-User; AI Overview / AI Mode = Googlebot; claude = Claude-SearchBot, Claude-User.
  **Decision**: gemini keeps Google-Extended beside Googlebot (Google documents Google-Extended as the control for
  Gemini apps' grounding; the registry row says "grounding and training"). Test
  `test_ans4_links_an_engine_only_to_findings_that_block_its_search_or_live_tokens`.
- **B14** registry (`REGISTRY_VERSION` 2026-10-21): Bytespider, GoogleOther, Google-CloudVertexBot (training, role
  gated), Meta-ExternalFetcher (live, gated, `NOT_PROBED`: no probe string, so ACC-4's request counts do not move).
  `tests/test_acc_units.py::test_registry_integrity` now allows a search/live row without a probe string only when its
  gate says `NOT_PROBED`. ACC-2 Info "robots.txt has rules for anthropic-ai, claude-web, which no longer have any
  effect" (`registry.RETIRED_TOKENS`). The training fix text now comes from the registry ("These user agents serve:
  {engines}. ..."); the old sentence is kept as a saved-report fix pattern (`acc2.training_saved`).
  Tests: `test_new_registry_rows_send_no_probe_and_are_gated`, `test_rules_for_retired_anthropic_tokens_are_an_info_note`.
- **B15** llms.txt (`access_data.collect_access_data`, ACC-8): present = 200 AND readable text (not HTML, not blank);
  one same-site redirect is followed when robots.txt allows it, and `redirected_to` is recorded. Links of the file that
  redirect are listed (`links.redirecting`) and reported as ACC-8 Info "N link(s) in llms.txt point to an address that
  redirects" (Arjava's /difuzorler 301). Old reports without `readable` read as before.
- **D-15** (`logs.py`): malformed range entries are skipped and counted; a file that yields no network makes that
  bot's requests unverifiable, never spoofed; `ip_range_files[].unusable` says so; ACC-5's never-fetched check only
  uses tokens with prefixes. Test `test_an_unusable_range_file_makes_requests_unverifiable_not_spoofed`.
- **A21** (`probes.compare`): an empty page to the bot where the browser had words is `blocked`.
  `ua_verdict` (unverified ACC-4): 404/410 to Googlebot where the browser read the page is `not_found_for_bot` (S3,
  titled with the statuses); an empty 2xx is `empty_for_bot` (S3, own title).
- **A22** `ua_verdict`: a challenge (cf-mitigated or challenge signature) to the spoofed Googlebot is `challenged`,
  Info "... the real Googlebot may be on a verified-bot allowlist". A plain 403/401/429 stays `refused` S3.
  **Decision**: amends DECISIONS 205's "a challenge is S3" for the no-ownership check only.

## Transport, pacing, crawl

- **A6** (`fetcher._BoundedDecoder`): Maya sends `Accept-Encoding: gzip, deflate` and decodes gzip / zlib deflate /
  raw deflate itself from `iter_raw`, never producing more than the remaining body cap per step; other encodings
  fall back to httpx's decoding; an answer already in memory (MockTransport) is read as before. A body that is not
  the gzip it claims is `http_error (DecodingError ...)`. Tests: gzip bomb (64 MiB of zeros, 1 MiB cap, peak memory
  < 16 MB), gzip/deflate/raw-deflate equality, bad gzip.
- **A9** `_pace_after(empty=...)`: an empty 2xx (`classify.empty_response`, never for HEAD) resets the clean count
  without narrowing or stopping narrowing. Tests: unit + live loopback.
- **A10 / H28 / H32 headers** `crawler.KEPT_HEADERS` += content-encoding, vary, cache-control, etag, age, x-cache,
  cf-cache-status, strict-transport-security, content-security-policy, x-content-type-options; values cut at 512
  chars (`kept_headers`). `RawResponse.wire_bytes` / `PageFetch.wire_bytes` = `num_bytes_downloaded`. Schema: page
  record gains `wire_bytes` (docs/report-schema-1.17.json regenerated, REPORT-SCHEMA.md 1.17 line).
- **A7** (`urls._checked_address`): the IPv4 inside IPv4-mapped, 6to4 and NAT64 64:ff9b::/96 addresses is judged;
  64:ff9b:1::/48 is refused outright. The connection still goes to the resolved address. Tested on 3.11 and 3.12.
- **A8** `is_allowed_origin_move`: apex <-> www may not go from https to http.
- **A12** `urls.lock_key`: the cross-process and in-process crawl lock is keyed by host without "www." plus a
  non-default port (not by registrable domain: that would lock all loopback test servers together and make two
  subdomains of one company block each other).
- **A13** `CrawlConfig.max_retry_after_s` 5 → 30 s (an edit of an existing default, not an append: the brief's
  30-60 s range, lower end). A 503 with Retry-After within the cap is retried once; its wait counts toward
  `max_total_cooldown_s`. Test `test_a_503_with_a_short_retry_after_is_asked_once_more`.
- **A14 / A15** (`sitemap.discover_sitemap_urls` now returns a list of notes): "read its limit of N sitemap file(s);
  M more were not read", robots.txt sitemaps on another address (named, not read), and the count plus 3 examples of
  off-origin `<loc>` entries. Kept as `crawl.sitemap_notes` (INT-2 caveats); no schema change.
- **A2** (`urls.crawl_identity`, crawler `enqueue`): links/sitemap URLs that differ only in utm_*, gclid, fbclid,
  msclkid, dclid, yclid, mc_cid/mc_eid, *sessid*, jsessionid (query) or ;jsessionid= (path), or in parameter order,
  are enqueued once; the first variant met is the one fetched and reported. Redirect hops and the start URL are never
  dropped. `normalize_url` is unchanged (dot segments and the trailing dot were phase 0). Test
  `test_links_that_differ_only_in_tracking_parameters_are_asked_for_once`.
- **A23** (`external_links.check`): a HEAD that fails in transport (not a timeout, not the deadline) is followed by
  one GET before the site is marked quiet (`sent(quiet=False)`).
- **A26** CrUX (`crux.py`) and PSI/CrUX in `perf_data.py` send the key as `X-Goog-Api-Key`, not in the address.
- **A28 not done (reverted)**: planning DFS-8 as not sent for a non-US market was written and worked, but it moved 11
  pinned tests in `tests/test_market_and_balance.py` and `tests/test_cost_limits.py` (paid-body counts zipped against
  plan rows, plan totals, "not requested" lists, the dry-run text), and `dataforseo/panel._PREVIEW_COST["not_sent"]`
  prints "not sent: not a public domain" for any not-sent row. Recipe for the lead: in `insights.audit_plan` give DFS-8
  `not_sent = "market mismatch: ..."` when `(code, language) != (2840, "en")`, take the preview reason from
  `call.not_sent`, and filter not-sent rows before the tests pair bodies with rows.
- **A29** `dataforseo/insights`: /usr/share/dict/words is no longer read; only the bundled `_COMMON` list.

## PRF-1 (H28, H32)

- PRF-1 records the median TTFB of the HTML pages the crawl read, always (observation + evidence
  `crawl_median_ttfb_ms`, summary sentence "Median time to first byte of N HTML page(s): X ms.").
- Info "The HTML of N page(s) is not cached at the CDN (cf-cache-status DYNAMIC)" when Cache-Control is private /
  no-store / no-cache / max-age=0 / s-maxage=0 and cf-cache-status is DYNAMIC/MISS/BYPASS or X-Cache says MISS.
  Kept even when the timing samples are not assessed. Arjava `test_html_not_cached_at_the_cdn_is_recorded` passes
  (xfail removed).
- **H32 / Decision**: HSTS is an Info inside PRF-1 ("The https homepage sends no Strict-Transport-Security header"):
  PRF-1 already owns "how the HTML is delivered" and a new SEC check id would need audit.py, the checklist, check
  labels and coverage entries owned by others. CSP and X-Content-Type-Options are kept in the headers but not judged.

## Firecrawl

- **A16** The reader cache is read only by the audit that wrote the entry (`_maya_audit_id` stored with it) or by a
  resumed audit (approved credits 0, or `FirecrawlClient(resumed=True)`, which the command line passes with
  `--resume`: its audit id is new each run, so without the flag a CLI resume would buy its pages again); a new audit
  reads the site again the same day.
  `tests/test_firecrawl.py::test_a_page_is_served_from_mayas_own_cache_...` updated (same audit hits, a new audit
  misses, a resume hits).
- **A17** `_merged` records title / canonicals / visible-text-hash differences between Maya's own copy and the
  reader's in `analysis.content_observation.differs_from_own_copy` and a classification note (no schema change).
- **A18** `page_cause`: status None → `no_status`; non-2xx below 400 → `error_status`; `empty_document` only for 2xx.
  `tests/test_coverage_phase2.py` updated.
- **A19** `_label` leaves STR-6 findings whose `signal` is the Last-Modified header or sitemap lastmod unlabelled
  (source `maya`).
- **A30 not done**: passing `audit_cap` to `ledger.reserve` would cap a resumed audit's new approval by its first
  run's spend, and `AuditCapReached`'s message names DataForSEO dollars; what `approved_credits` means on a resume
  with more credits is not settled. Left for a decision.

## Touched outside my files

- `maya_audit/models.py`: `PageFetch.wire_bytes` (3 lines).
- `maya_audit_web/wording.py`, `maya_audit_web/sentences.py`, `maya_audit_web/locales/findings/tr.json`,
  `maya_audit_web/locales/catalog/tr.json`, `maya_audit/recommendation_catalog.py`: title frames, line patterns,
  Turkish entries and catalog notes for every new title/fix/note.
- `maya_audit/cli.py`: passes `resumed=` to the two FirecrawlClient constructions (A16, 2 lines).
- `tests/test_web_app.py` (BUILT_TITLES rows for ACC-3 and ACC-4), `tests/test_wording.py` (the ACC-2 training fix
  sample), `tests/test_acc_units.py`, `tests/test_preview16_false_alarms.py`, `tests/test_firecrawl.py`,
  `tests/test_coverage_phase2.py`.
- `docs/REPORT-SCHEMA.md`, `docs/report-schema-1.17.json`.

## Environment notes

- With `TEMP` set to `<worktree>/.tmp` (≈150 characters) the web-app job tests fail with FileNotFoundError (paths
  past MAX_PATH); with a short TEMP (`<temp>/w1tmp`, still private to W1) they pass.
- During the run the uv junction `<uv python>/cpython-3.12-windows-x86_64-none` disappeared and venv312 could not
  start; it was re-created as a junction to `cpython-3.12.14-windows-x86_64-none`.

## Full suite (3.12, short TEMP) and what still fails

`14 failed, 1767 passed, 1 skipped, 15 xfailed` before the follow-up fixes below; after them, of those 14:
- fixed in this branch: `test_acc_scenarios::test_robots_rules_per_role` (the NOT_PROBED gate text was shown on ACC-2;
  now filtered like the probe-string gate), `test_prf_scenarios` ×3 and `test_search_data::...key_is_never_shown`
  (fakes read the key from `X-Goog-Api-Key`, A26), `test_run_clock::...cached_pages_do_not_wait` (same audit id,
  A16), `test_page_wording::test_schema_1_16_...` (lists `page: added ['wire_bytes']`).
- passed when rerun alone (order-dependent in the full run, not reproduced): `test_round2_sitemap_and_llms::
  test_a_cap_above_the_sitemap_checks_every_url_and_says_of_n`, `test_preview16_grouping::test_empty_pages_...`.
- pre-existing on a66a97b: `test_fixture_matrix::test_the_matrix_file_matches_the_tests`,
  `test_no_unfilled_placeholders::test_the_pages_own_sentence_filler_follows_the_same_rule` (an "…" character).
- **left failing, for the lead** (caused by H26): `test_web_app::test_a_500_page_audit_...`,
  `::test_follow_up_answers_...`, `::test_demo_mode_is_labelled_...`. The demo shop's only S1 was "noindex via meta on
  5 page(s)" (sitemap pages); it is now S3 + S2. With no S1 left, the web summary's first action / "top" answer picks
  IDX-1 while `findings_in_priority_order[0]` is RND-1 (both S2): the web summary and the report order S2 ties
  differently. Either the demo gets a key page with noindex (keeps an S1) or the tests (and maybe the summary's tie
  order, CR-23) change; both are outside W1's files.
