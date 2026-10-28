# W2 — page content and structure checks (branch fix/w2-content)

Notes for the lead, one section per item. "Test" names a function in `tests/test_w2_*.py` unless a file is given.

## Part 1 (commit 4b1516e, tests in dd8b602)

### H11 — the homepage's Organization in three states
- `analysis.py:parse_error`, `_jsonld`: a block that does not parse keeps the parser's error, line, column, character
  position, the character by name ("newline (U+000A)"), the property it sits in and an excerpt with control characters
  written out. It is also parsed leniently (`json.loads(strict=False)`) only to name the types it describes
  (`recovered_types`); nothing read leniently is used as structured data.
- `checks/structure.py:str3_structured_data`: absent → "The homepage has no Organization structured data" (S3);
  present in a broken block → "The homepage's Organization block does not parse" (S3, where + excerpt, fix says repair
  the block and not add a second one; the block is not listed again under "JSON-LD that does not parse"); present and
  parsed without logo/sameAs → Info (`organization_gaps`).
- Tests: `test_a_homepage_with_no_organization_block_is_told_to_add_one`,
  `test_a_broken_organization_block_is_reported_as_broken_with_where`, `test_a_valid_organization_without_logo_is_one_info_note`;
  Arjava `test_a_broken_organization_block_is_reported_as_broken_not_missing` (xfail removed).

### H12 — the "Capped at S4" note only on capped findings
- `str2_headings` (homepage without <h1>) and `str3_structured_data` (no Organization) are S3 by the owner's calibration
  (DECISIONS 181); they no longer carry `CAPPED`. Test `test_an_s3_finding_does_not_say_it_is_capped_at_s4`; Arjava
  `test_severity_and_cap_note_agree` (xfail removed).

### H14 — a shop has product pages whatever they are called (STR-21)
- `checks/small_site.py:shop_pages`: Product/Offer structured data, or a price of its own beside a buy control, counts as
  a product page when no address/title word found one. `basic_pages_found` uses it last.
- B09 part done here too: `page_words.BASIC_PAGE_STEMS` + `small_site._stem_match` (segment starts with `urun`, `menu`,
  `hizmet`, `sube`, `iletisim`, `hakkimizda`).
- Tests: `test_a_shop_with_product_markup_has_product_pages_whatever_they_are_called`,
  `test_a_shop_with_a_price_beside_an_add_to_cart_button_has_product_pages`, `test_a_brochure_site_without_product_signals_keeps_the_gap`;
  Arjava `test_a_shop_is_not_told_it_has_no_product_page` (xfail removed).

### H15 — a hidden <h1>
- `analysis.py:hidden_by_markup`: a heading is hidden by its own markup or an ancestor's (hidden attribute, aria-hidden,
  inline display:none / visibility:hidden); `headings[]` and `h1_elements[]` carry `hidden: true`.
- `render.py:H1_VISIBILITY_JS`: on a rendered page the computed style (display, visibility, opacity, box size of it and
  its ancestors) wins, so a class-hidden heading is seen there.
- `str2_headings`: "The homepage's only <h1> is hidden" (S3, not capped) and "N page(s) have only a hidden <h1>" (S4,
  capped); says when the hidden <h1> repeats the <title>; evidence says how visibility was assessed.
- Tests: `test_a_homepage_whose_only_h1_is_hidden_is_reported_as_hidden` (5 variants), `test_a_hidden_h1_repeating_the_title_says_so`,
  `test_a_visible_h1_is_not_reported_hidden`; Arjava `test_a_hidden_h1_is_reported` (xfail removed).

### H16 — placeholder alt text (STR-7)
- `config.PLACEHOLDER_ALTS` (folded whole-value words, English and Turkish), `config.PLACEHOLDER_ALT_FILE` (file names and
  camera numbering); `structure.placeholder_alt` also flags an alt equal to the image's title attribute (analysis keeps
  `title` on images). Each row says why.
- Tests: `test_placeholder_alt_patterns_are_recognised`, `test_a_real_alt_is_not_a_placeholder`,
  `test_an_alt_that_repeats_the_title_attribute_is_a_placeholder`, `test_placeholder_alt_is_reported_by_str7`; Arjava
  `test_placeholder_alt_text_is_reported` (xfail removed).

### H27 code (in part 1, tests in group C below)
- `structure.listing_reason` / `product_template`: a page with ItemList/OfferCatalog/CollectionPage/SearchResultsPage
  markup, two or more buy buttons of its own, or links to two or more other product-looking pages is a listing; it is
  neither a product page nor a "maybe product" page.

## Part 2 (commits 9adc75d, 20a861a, 924632b, abb0f60; tests in `tests/test_w2_rules.py`)

### A. H23 / B04 — hreflang beyond its shape (STR-9)
- `language.hreflang_code_problem`: shape check on the folded value (language 2-3 letters, optional 4-letter script,
  region 2 letters or 3 digits), `WRONG_REGIONS = {"UK": "GB"}`, private-use ranges (qaa-qtz, zz; AA, QM-QZ, XA-XZ, ZZ).
  No ISO registry is shipped on purpose (kept small): `eng-USA` fails by shape, `tr-TU` is NOT caught (not in the list).
  Each bad row says why; still Info. `html_lang` validation is unchanged (BCP47 regex).
- `structure.str9_language`: one code to two or more URLs on one page is S4 "give the same hreflang code to two or more
  URLs"; `_hreflang_target_page`: a crawled target that is noindex, canonical elsewhere, or has an empty <title> or meta
  description is S4 "hreflang target page(s) are not indexable or have an empty title or description" (scope = the
  targets); missing x-default or self link is Info. A target answered by the link check but not crawled is listed in
  evidence `hreflang_target_pages_not_read` (never a pass; the old `hreflang_targets_not_assessed` count is unchanged).
- The x-default/self Info note fires on many multilingual sites that passed before; it says Google recommends both
  but does not require them.
- Tests: `test_usable_hreflang_codes_pass`, `test_wrong_hreflang_codes_say_why`, `test_en_uk_is_reported_with_the_right_region`,
  `test_the_same_code_for_two_urls_is_s4`, `test_a_target_that_cannot_stand_for_its_language_is_s4` (3),
  `test_a_good_cluster_has_no_target_or_cluster_finding`, `test_a_cluster_without_x_default_or_self_is_info`,
  `test_a_target_that_was_not_crawled_is_not_read_never_fine`; Arjava `test_an_hreflang_target_with_an_empty_title_is_reported`
  (xfail removed).

### B. H24 / B07-B10
- B07 `content_quality.generic_anchor` tries the Turkish fold and casefold ("CLICK HERE" is found).
- B08 `thin_exempt`: whole word of a path segment (split on - and _) or of the folded title; a page under an article
  folder (`page_words.ARTICLE_FOLDERS`) is never exempt (the appendix's D4 diff would still have exempted
  `/blog/odeme-yontemleri-rehberi`). STR-15 leaves out a short page with a form as STR-17 does, but only when the form is
  not on most pages (a footer newsletter or search form would otherwise exempt every page).
- B09 Turkish `GENERIC_TITLES` (compared as-is and folded), Turkish month names (`TR_MONTHS`, with and without marks),
  labels Yayın tarihi / Yayınlanma tarihi / Son güncelleme / Güncelleme tarihi / Güncellendi. STR-21 stems were in part 1.
- B10 `language.lower` (capital İ to i, combining dot removed) used by detect_language, looks_like_name and the
  block/heading guesses.
- Tests: `test_generic_anchors_match_in_any_case`, `test_a_word_inside_a_longer_word_or_an_article_does_not_exempt_a_short_page`,
  `test_a_contact_legal_or_cart_page_is_still_exempt`, `test_a_short_page_built_around_a_form_is_left_out_of_thin_content`,
  `test_a_form_on_every_page_exempts_no_short_page`, `test_turkish_placeholder_titles_are_generic`,
  `test_turkish_dates_and_labels_are_read`, `test_basic_page_stems_take_a_turkish_suffix`, `test_capital_dotted_i_counts_as_turkish`.
- Not done: STR-17's `_ends_by_design` still matches substrings (not in this item list).

### C. H27 — tests only (code was in part 1)
- `test_a_page_with_one_price_and_no_buy_button_is_still_a_maybe`,
  `test_a_category_listing_with_item_list_markup_is_not_a_maybe_product`, `test_a_page_linking_to_several_priced_pages_is_a_listing`.

### D. H31 / B11 — VideoObject and required fields (STR-3)
- `structure.MORE_REQUIRED`: Event (name, startDate, location), Recipe (name, image), VideoObject (name, thumbnailUrl,
  uploadDate), LocalBusiness and 11 common subtypes (name, address), JobPosting (title, description, datePosted,
  hiringOrganization, jobLocation or applicantLocationRequirements). The note lists the types checked.
- `_video_placeholder`: a name such as "Video" (small folded list) or an uploadDate equal to the audit day (from
  `result.started_at`, the source STR-6 uses) gives Info/Estimated "N page(s) have a VideoObject that looks like an
  unfilled default"; evidence rows carry `uploadDate` and `why`.
- FAQ note: "Since August 2023 Google shows FAQ rich results only for authoritative government and health sites".
- Tests: `test_a_video_named_video_and_dated_the_audit_day_is_reported`, `test_a_real_video_is_not_a_placeholder`,
  `test_more_types_have_their_required_properties_checked` (5), `test_the_faq_note_gives_the_2023_restriction_not_a_2025_end`;
  Arjava `test_a_placeholder_video_object_is_reported` (xfail removed).

### E. B18, B19, B23, B24
- B18: new check status `not_applicable` (`findings.STATUSES` and its meaning; schema vocabulary regenerated; one
  REPORT-SCHEMA 1.17 line). STR-22/STR-23 return it when there is no news/job page. `coverage.settle` and `report.py`
  treat it like a pass when no page could be read, so that case is still `not_assessed`. Web label "Not applicable" /
  "Uygulanmaz". Test `test_no_news_or_job_page_is_not_applicable_not_a_pass`.
- B19: TSEO-1 counts title/description after NFC; a first heading of H3 or lower is a skip (`from: 1`,
  `first_heading: true`) in `analysis.py` and in the fallback in `technical_seo.py`. Checklist TSEO-1 section and table
  now say Info for the bands, S4 for skips (the code's severities kept). Tests `test_a_first_heading_of_h3_is_a_skipped_level`,
  `test_a_title_with_combining_accents_is_counted_as_read`.
- B23: STR-6 auto-stamp title says "carry a date within ±1 day of the audit" (evidence `pattern` unchanged).
  Test `test_the_auto_stamp_title_says_within_a_day`.
- B24: STR-14 named-block groups are keyed by (block, section); the page set is the union. Test
  `test_one_named_block_is_one_finding_whatever_pages_it_is_on` (fails on the old key).

### F. STR-14 accessible names
- Already honoured by `html_links.extract_link_edges` (aria-label, resolved aria-labelledby, title, img alt, svg title).
  An aria-labelledby naming no element still leaves the link nameless, as the ARIA name computation does.
  Test `test_a_link_named_by_aria_title_or_image_alt_is_not_nameless` (5 cases). No code change.

### Catalogue and wording (part 1 had added none)
- `wording.py` STR-2/3/9 title entries and `locales/findings/tr.json` titles for part 1 (hidden <h1>, broken or partial
  Organization) and part 2; fixes, expected, notes and the new STR-6 term translated.
- `recommendation_catalog._BY_TITLE` notes (STR-2 hidden h1; STR-3 broken Organization, Organization gaps, VideoObject;
  STR-9 same code, target, cluster) and `locales/catalog/tr.json`. Part 1's titles had made
  `test_web_app.py::test_every_kind_of_finding_has_its_own_matching_explanation` fail.
- H11's fix sentence no longer holds a literal backslash-n (the catalogue could not translate it): "must be removed or escaped".

### Touched outside my files
- `maya_audit_web/wording.py`, `maya_audit_web/locales/findings/tr.json`, `maya_audit_web/locales/catalog/tr.json`,
  `maya_audit_web/locales/tr.json`, `maya_audit_web/strings.py` (one status label), `maya_audit/recommendation_catalog.py`
  (notes), `maya_audit/findings.py` (status), `maya_audit/coverage.py` and `maya_audit/report.py` (one tuple each),
  `docs/REPORT-SCHEMA.md`, `docs/report-schema-1.17.json`, `docs/technical-audit-checklist.md`; tests `test_wording.py`
  (fix sentence), `test_own_document.py` (STR-22/23 status), `test_page_wording.py` (schema diff list).

### Environment notes
- Web-audit tests under pytest's default temp dir fail here with WinError 206 (path too long); run with
  `--basetemp=<temp>/<short>`.
- `test_no_unfilled_placeholders.py::test_the_pages_own_sentence_filler_follows_the_same_rule` fails before and after these
  changes (an ellipsis mangled by the console code page). Two `test_nine_corrections.py` tests failed once in a long
  combined run and pass alone.

### Follow-up (after review)
- An hreflang target page that was not read is now a coverage part of STR-9 (`coverage._str9`) and is named in the
  summary, so STR-9 cannot settle to a clean pass (test `test_an_unread_hreflang_target_keeps_str9_from_a_clean_pass`).
- `not_applicable` meaning says "none of the pages read"; coverage still lists any unread part of the site.
- For the lead: `report.py:_heading_jumps` prints a first-heading skip as "H1→H3"; it could use `first_heading` to say
  "starts at H3" instead (not changed: report.py is not mine).

### For the merge
- W3's `structure_data.canonical_elsewhere` (branch fix/w3-index) should replace two direct comparisons here, so a
  canonical that is the page's own http:// or www variant counts as self-canonical:
  `checks/structure.py:_hreflang_target_page` (`if canonical and canonical != page.url`, ~line 2446) and
  `graph_integrity` (`target == own`, ~line 719, the "~577" line in the original numbering).
- Turkish catalogue: the STR-9 coverage part name and reason added in 22f80f6 are translated (`labels`, `lines`).

## Item group G (commits abd8742, ed01261, bb19b36, e88d65e, 07561c1; tests in `tests/test_w2_assets.py`)

No new check id (PRF-4 / MOB / SEC would need ~15 registrations): image and media findings sit in STR-7, the
Twitter card in STR-10, page-level markup (head scripts, viewport, mixed content, analytics) in TSEO-1 through the
new `maya_audit/checks/page_markup.py` (in `checks/` so the catalogue tests read its titles from the source).
`analysis.py` adds `external_scripts`, `image_preloads`, `insecure_refs`, `analytics_ids`, `media[].src/sources`,
`images[].aspect_ratio` (page analysis is outside the schema).

### H29 — heavy and mislabelled media (STR-7)
- `structure.media_weight_findings`: sampled images over 500 KB (one finding, S3 when one is over 1 MB, size from
  Content-Length; unknown size counted in evidence, never "small"); Content-Type unlike the extension (Info);
  videos over 5 MB (S4). `structure_data._check_videos`: `<video src>`/`<source src>` on read pages, one GET each
  (purpose `video_size`, 4 KB cap), at most 5 and never above `image_checks_max`, same site only, robots.txt honoured.
  No HEAD, so fakeserver untouched. The fetcher sends no Range header, so Content-Length is the file's size.
  Checked through build_report on Arjava: S3/S4/Info severities are kept by qualify_checks. Tests: `test_an_image_over_one_mb_is_s3_and_names_file_and_size` and 4 more;
  Arjava `test_heavy_media_is_reported`.

### H30 — loading behaviour (STR-7, TSEO-1)
- `structure.image_loading_findings`: content images with neither width+height nor inline aspect-ratio (map tiles
  left out) → one Info; `<link rel=preload as=image type=image/jpg>` → Info. `page_markup.blocking_scripts`:
  external classic scripts in <head> without defer/async → Info. Not done: the preload-of-a-mobile-hidden image
  (needs class-name heuristics I could not test well). Arjava `test_loading_behaviour_is_reported`.

### H32 — markup part (TSEO-1, STR-10)
- No viewport → S3 (Documented; one printed after <body> started counts as present); user-scalable=no or maximum-scale<=1 → Info; https page with http:// sub-resources
  (not <a> links) → S3; og tags without twitter:card → Info. Not done: og:image pixel size and redirect, HSTS/CSP.
  Arjava `test_social_preview_gaps_are_reported` (the fixture is http://, so mixed content is unit-tested only).

### H33 — analytics twice (TSEO-1)
- `page_markup.double_counting`: a GTM id whose loader or noscript is printed more than once, or GTM plus a direct
  gtag G- id → Info (Hypothesis, Estimated), ids in evidence, fix says confirm with Tag Assistant. Arjava
  `test_duplicate_analytics_tags_are_reported` (the fixture: noscript twice + gtag G-8W55STRKEZ).

### H34 — platform (report.platform)
- `maya_audit/site_platform.py:recognise` (renamed from platform.py at merge, so it never shadows the standard library) (Ticimax, Shopify, WooCommerce, WordPress, Wix, ikas; Cloudflare from
  server/cf-* headers or /cdn-cgi/ addresses). IdeaSoft and T-Soft left out (hosts not confirmed). The module name
  shadows stdlib `platform` only if a file inside `maya_audit/` is run as a script; rename if the lead prefers.
  Arjava `test_the_platform_is_recognised`. Platform-specific catalogue sentences (plan H34) not done.

### Wording
- `wording.py` titles (str7.heavy/mime/video/unsized/preload_type, str10.no_twitter, tseo1.blocking_scripts/
  no_viewport/no_zoom/mixed/analytics_twice), `locales/findings/tr.json` (titles, fixes, expected, notes),
  `recommendation_catalog` notes + `locales/catalog/tr.json`. Fix sentences start with a verb in
  `practical.ACTION_VERBS` (Shrink/Replace/Reduce), as `test_counts_and_shared_elements` requires.

### Tests changed because the new findings fire on old fixtures (intent kept)
- `test_str_scenarios.py`: image-cap test leaves the layout-shift note out; TSEO-1 band test leaves viewport out of
  the reported pages; TSEO-1 partial and STR-10 partial tests accept "findings" (still not a pass).
- `test_false_alarms.py` (two map/alt filters skip the layout-shift note); `test_counts_and_shared_elements.py`
  (synthetic pages carry a viewport); `test_page_wording.py` (schema diff lists `platform`);
  `test_evidence_integrity.py::test_every_status_has_a_meaning_in_the_report` now includes part 2's
  `not_applicable` (it failed before group G).
- Not run (no full suite): other tests that count S3 findings or TSEO-1/STR-7/STR-10 statuses on fixtures without
  a viewport may need the same treatment; the lead's full run will show them.

### Touched outside my files (group G)
- `maya_audit/report.py` (build_report: 4 lines, W4a), `maya_audit/schema.py`, `docs/REPORT-SCHEMA.md`,
  `docs/report-schema-1.17.json` (W1 also edits it: regenerate after merge), `maya_audit/structure_data.py`
  (videos field + `_check_videos`; W3 also edits this file), `maya_audit/technical_seo.py` (2 lines), wording files.
