# gx3: generalisation, PRF-1 cache/HSTS, report noise policy, ordering, length guard

Branch `fix/gx3`. Review G (`G_asiri_uyum.md`) rows G05, G14, G25 and section 2 (noise policy), plus two lead items:
the length guard and ordering by page importance.

## G05: the CDN cache rule, for every CDN
- What: `maya_audit/checks/perf.py`: `cdn_name` (a small table `CDN_SIGNS`: Cloudflare, CloudFront, Akamai, Fastly,
  Vercel, Netlify, Sucuri; then the name in an RFC 9211 `Cache-Status` member), `cache_state` (the hop nearest the client
  decides: the last item of `x-cache`, so "MISS, HIT" is a hit; the last `Cache-Status` member, a miss is `fwd=` without
  `hit`; `Age > 0` is a hit; status words read with "_" as a space, so `TCP_MISS` is a miss), `_cdn_cache_findings`
  and `cache_observation`. `maya_audit/crawler.py` `KEPT_HEADERS`: + cache-status, x-vercel-cache, x-vercel-id,
  x-nf-request-id, akamai-cache-status, x-served-by, via, x-amz-cf-id, x-amz-cf-pop, x-sucuri-cache (constant only).
  `config.CDN_NOT_CACHED_SHARE = 0.9` (appended).
- Rule now: the Info finding needs (1) a CDN named by its own headers, (2) its status saying miss/dynamic/bypass on at
  least 90% of the HTML pages carrying that status, and (3) Cache-Control `private` or `no-store`. `no-cache` and
  `max-age=0` mean revalidate (RFC 9111 §5.2.2), no longer "uncacheable". No CDN named: only the PRF-1 observation
  "how the HTML pages are cached" (CDN named, states, Cache-Control values).
- Why: G05: Fastly's "MISS, HIT" was read by substring, no-cache counted as uncacheable, only two headers were kept.
  The site's platform (site_platform, G06's file) is deliberately not used: a platform is not a CDN.
- Not done: the review's TTFB threshold idea (finding only when the median TTFB is high). The H28 decision reports the
  header fact; adding a timing gate changes that decision, so left for the lead.
- Tests: `tests/test_gx3_perf.py` (each CDN, last hop, no-cache, Age, no CDN = observation, "nearly every page").
  `test_brand_neutral.py::test_news_video_fastly_miss_hit_with_no_cache_is_not_uncached_prf1` now passes (G05 xfail
  removed). shop-de (Akamai TCP_MISS + no-store) and bank-multi (CloudFront Miss + private, no-store) still report it,
  as their Info caps budget for; Arjava (Cloudflare DYNAMIC + private) still does.

## G14: HSTS advice without a vendor's menu
- What: `perf.HSTS_FIX` names no vendor ("from the web server or the application"); `perf.HSTS_CDN`, one CDN-neutral
  sentence, is added only when `cdn_name` finds a CDN on the homepage answer. The finding stays one site-wide Info.
  `CACHE_FIX` lost its Cloudflare menu path too. The evidence carries `cdn`.
- Turkish: three new entries in `maya_audit_web/locales/findings/tr.json` (the old entries stay for saved reports).
- Test: `test_hsts_advice_names_no_vendor_menu_and_adds_one_cdn_sentence_only_behind_a_cdn`,
  `test_the_new_fix_sentences_have_turkish_wording`.

## G25 + noise policy (section 2)
- (a) First lists never hide a second S1-S3 finding of a check. Still one row per check, but the row names the check's
  other S1-S3 cards (count + first two):
  - Markdown "First N fixes" (full and brief): `report.also_serious`, `first_fixes_lines` (" — also #2 …").
  - Web executive "top problems": `practical.also_line` → `executive()["problems"][i]["also"]`, printed by
    `pdf._executive` (keys `pdf.exec.also`, `pdf.exec.also_more`, en + tr).
  - Client report "Önce bunları düzeltin": `render_report.also_serious` under the row's title.
  - The concise print's priority section already showed every S1-S3 finding as its own card (unchanged).
- (b) Hygiene: `findings.is_hygiene` reads `config.HYGIENE_FINDINGS` (check id + loose title words: HSTS, CDN cache,
  width/height, Twitter card, scripts in <head>; not "analytics tag twice", which after G10 is real double counting). Loose on purpose: G11/G12/G13 may be reworded or
  demoted by other workers; a finding that becomes an observation simply drops out. Markdown: "Notes (no action
  implied)" keeps the other Info findings; a "Hygiene" section follows (one line each, `HYGIENE_LINES` = 4, then
  "… N more hygiene items in the JSON report"). No Finding field was added (no schema change).
  True observations (check `observations`) were already outside the report body; unchanged.
- (c) Same in the other outputs: web rows carry `hygiene` (summary.item); concise print: Notes without hygiene, then a
  "Hygiene" list capped at 4 with "N more hygiene items, by ID: …" (every finding ID still appears, as the concise
  report promises and tests/test_w4b_report_length.py checks); client compact appendix: hygiene Info cards become a
  capped "Hijyen" list at its end, each keeping its `finding-<id>` anchor (cards carry `maya.hygiene`).
- The full (non-concise) web print lists hygiene rows under their own "Hygiene" heading, not under "Notes (nothing to
  fix)" (uncapped: it is the full export). The brief Markdown's closing line counts notes and hygiene items apart.
  On a draft client report (no Turkish titles yet) the "Aynı kontrolden ayrıca" line names the finding IDs, linked.
- (d) `tests/test_gx3_noise.py`: bank-multi and news-video render ≤ 6 Notes + Hygiene lines; every S1-S3 finding is in
  "What to fix first" and in the first-fixes table; the web executive names every serious finding; every ID is in the
  concise print; the client report names the other serious findings of a check; plus unit cases.

## Item 5: severity by page importance, in every output
- Verified: the engine's `priority_key` already sorted by `importance_tier` within a severity (after evidence quality,
  CR-23, kept); the homepage was tier 2 unless configured as a key page; the web's `action_priority.ordered` did not use
  importance at all (page count decided).
- What: `findings.page_importance` (0 for a confirmed key page or the site root, else the saved tier) is used by
  `priority_key`; web rows carry `importance` and `ordered` sorts by it before page count. The saved `importance_tier`
  keeps its meaning (schema: 0 = a confirmed key page): the homepage counts only for ordering. The client report follows
  `findings_in_priority_order`, so it agrees.
- Tests: `tests/test_gx3_order.py`, and `test_web_rows_follow_the_engine_order_of_importance_within_a_severity`.

## Item 4: length guard
- `tests/test_gx3_length.py`, for the 8 neutral sites and Arjava: Markdown and concise words under per-site caps
  (measured 2026-10-22 + ~30%), no line over 40 characters said more than twice (addresses and numbers masked; per-page
  sections and the card's field row are left out), first action within 40 lines.
- Found and fixed: Arjava's og:site_name card said the same value on four lines (one per page). `report.card_lines`
  now uses `merged_detail_sentences`: pages with one value share one line.

## Touched outside my files
- `tests/test_w1_crawler.py` (one test, H28): its pages mixed a bare `x-cache: MISS from edge` with HIT/public pages;
  rewritten to the G05 rule (all pages miss → one finding; mixed → none).
- `tests/test_brand_neutral.py`: the G05 xfail marker removed (no assertion changed).
- `maya_audit_web/action_priority.py` (sort key, 2 lines), `maya_audit_web/strings.py` and `maya_audit_web/locales/tr.json`
  (5 keys each), `maya_audit_web/locales/findings/tr.json` (3 fix sentences).
- `docs/FIXTURE-MATRIX.md` regenerated (`scripts/fixture_matrix.py`): the new test names that say a check id.

## Full suite (3.12)
`2 failed, 2122 passed, 1 skipped, 40 xfailed` before the follow-up commit; both fixed in it and re-run green:
the HSTS CDN sentence needed its own Turkish entry (test_wording), and the fixture matrix needed regenerating.
