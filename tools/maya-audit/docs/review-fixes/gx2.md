# gx2: generalisation fixes (review G, brand-independent quality)

Branch `fix/gx2`. Items from BRIEF_G (gx2 list); G ids from the overfitting review (`G_asiri_uyum.md`).
Acceptance: `tests/test_brand_neutral.py` (25 xfail markers removed, listed at the end), `tests/test_arjava_regression.py`
stays green (one assertion retargeted, see G13).

## 1. G07: STR-7 format mismatch behind an image service
- What: `checks/structure.py` `negotiated_format()` + `media_weight_findings()`: no mismatch when the answer has
  `Vary: Accept`, the address matches `config.FORMAT_NEGOTIATING_IMAGE` (cdn.shopify.com, `/cdn/shop/`, Cloudinary
  `f_auto`, imgix `auto=format`, `/_next/image`, `/cdn-cgi/image/`, `format=auto`/`fm=webp`), or the server sent WebP or
  AVIF for an older name (lighter than promised: the purpose of the service). A PNG under `.jpg` is still noted. The
  count left out is in the finding's evidence (`left_out_as_format_negotiation`).
- The sample now sends `Accept: image/avif,image/webp,image/apng,image/*,*/*;q=0.8` (`config.IMAGE_ACCEPT`) on every
  image request, own site and other-site pool (`media_sample.IMAGE_HEADERS`).
- Why the lighter-format rule: the Shopify fixture serves `/cdn/shop/...jpg?width=800` as WebP without Vary; no host
  list would cover every store front, the format direction does.
- Tests: `test_gx2_media.py::test_an_image_service_or_a_lighter_format_is_not_a_mismatch` (6 cases),
  `::test_a_heavier_format_under_a_lighter_name_is_still_noted`.

## 2. G08: heavy media severity by page importance
- What: `media_weight_findings(images, videos, key_urls, home)`: S3 only when a file over 1 MB is shown on the homepage
  (`homepage_url`) or a key page; otherwise S4; still one finding listing the files. Thresholds moved to config
  (`IMAGE_HEAVY_BYTES`, `IMAGE_VERY_HEAVY_BYTES`, `VIDEO_HEAVY_BYTES`). Note text and its Turkish updated.
- `tests/test_w2_assets.py::test_an_image_over_one_mb_is_s3...` now passes the homepage (its file is on it).
- Tests: `test_gx2_media.py::test_a_very_heavy_image_off_the_homepage_and_key_pages_is_s4` (the Adile campaign GIF case),
  `::test_a_very_heavy_image_on_a_key_page_is_s3`.

## 3. G09: alt == title is not a placeholder
- What: `placeholder_alt()` dropped the alt == title branch; `config.PLACEHOLDER_ALTS_MORE` adds bild, imagen,
  immagine, imagem, صورة (whole alt only; "foto" was already whole-alt only). The H16 comment in analysis.py updated.
- Reverses H16's third sign. `test_w2_part1.py` test renamed to `..._is_not_a_placeholder` with the reverse assertion.
- Tests: `test_gx2_words.py` (G09 block).

## 4. Live gaps 1 and 4: the image sample
- New module `maya_audit/media_sample.py` (mine). `image_sample(result, limit, key_urls)`: at most half the sample
  (`IMAGE_SAMPLE_PRIORITY_SHARE`) first: the homepage's `<link rel=preload as=image>` images and its first 3 content
  images (`IMAGE_SAMPLE_HERO`), the largest-declared images of the homepage and key pages, each key page's first
  images; then page by page as before.
- Asset host rule (documented in the module docstring and config): a host on another registrable domain that serves
  at least 50 % of the site's distinct content images and at least 5 of them (`ASSET_HOST_SHARE`,
  `ASSET_HOST_MIN_IMAGES`) is the site's own: its images are requested also with `--no-external-links`, under the same
  `image_checks_max` cap and its robots.txt. `own_image()` is used by both `structure_data._check_images` and
  `other_sites.build`, with the same `image_sample` arguments, so the pool and the collector agree.
- Decision touched: DECISIONS 211 ("an image on another site only when links to other sites are checked"); narrowed to
  hosts that are not the site's asset host. For the lead to record.
- Tests: `test_gx2_media.py::test_the_homepage_hero_is_sampled_before_the_other_pages_images` (cap 4, 36 thumbnails,
  2.5 MB hero sampled and S3), `::test_the_sites_asset_host_is_sampled_with_other_sites_off_and_asked_like_a_browser`
  (second loopback host; 6 requests, each with the image Accept header).

## 5. Live gap 2: videos loaded by script
- What: `render.collect_render_data` calls `media_sample.size_rendered_videos()` after the browser closes: the media
  requests of each rendered page (`type == media` or a video extension; `.m3u8`, `.mpd`, `.ts`, `.m4s` left out) are
  stored as `media_requests` on the render entry and, when not already in `structure.videos`, sized with the same GET
  (`video_size`, 4 KB), same-site only, robots.txt, within what is left of `VIDEO_CHECKS_MAX`; marked
  `found_by: rendering`. STR-7's video finding reads them unchanged.
- Tests: `test_gx2_media.py::test_media_requests_are_the_video_files_without_stream_manifests` (unit),
  `::test_a_video_a_script_inserts_is_sized_when_rendering_ran` (browser; skipped without Chromium).

## 6. G10-G13 and the markup noise policy
- (a) G11 `checks/page_markup.py`: `blocking_rows()` leaves out `config.SYNC_REQUIRED_SCRIPT_HOSTS` (OneTrust/cookielaw,
  Cookiebot, Usercentrics, Didomi/privacy-center, Iubenda, Optimizely, VWO) and never names them; render-blocking
  scripts are a TSEO-1 observation (pages, scripts, top 5 hosts) and a finding only on pages that block on at least
  `BLOCKING_SCRIPTS_FINDING_MIN` (3) of the site's own scripts. Arjava (6 own scripts) keeps its finding; the WordPress
  jQuery pair is an observation. `technical_seo.py` passes the observations into TSEO-1.
  `test_w2_assets.py::test_only_classic_head_scripts...` now checks `blocking_scripts()`, the observation and the
  three-script finding.
- (b) G12 `analysis.py`: image records get `css_sized` (a class matching `config.CSS_SIZED_IMAGE_CLASS`, an inline
  aspect-ratio/object-fit/numeric height, a sized `<source>` of its `<picture>`, or a `data-*` lazy source);
  `image_loading_findings` skips them.
- (c) G13 STR-10: a missing twitter:card is an observation. Conflict: `test_arjava_regression.py::
  test_social_preview_gaps_are_reported` asserted a finding titled "twitter"; nothing honestly tells Arjava apart from
  the healthy local-wp fixture, so following the brief its assertion now reads the STR-10 observation (and that the
  og: gaps are still findings). Wording: `str10.no_twitter` added to `wording.SAVED_ONLY`, its explanation to
  `catalog.SAVED_ONLY` (reports saved before).
- (d) G10: a `<link>` is not a loader (`analysis._LINK_TAG` stripped before counting); GTM beside a gtag for another id
  is an observation (`tag_manager_beside_gtag`); one gtag id loaded twice is a finding; `GT-`/`DC-` ids read.
  `test_w2_assets.py::test_a_container_printed_twice...` updated (GTM + gtag no longer a finding; gtag twice is).
- (e) Markup Info notes (blocking scripts, analytics twice, unsized images) covering at least half of the pages read (and
  at least 3 pages for TSEO-1's notes, 4 for STR-7's) are scoped `sitewide`.
- Tests: `test_gx2_markup.py`.

## 7. G17/G18/G19: STR-9
- `_same_page()` (private, in `checks/structure.py`; scheme, leading www, trailing slash; query kept). Used in the
  self-target skip, the cluster self-link test, the return-link test and the target canonical. Lead: swap for gx1's
  `structure_data.same_page` when merged (same semantics intended).
- A target on another registrable domain that was not fetched while links to other sites are off goes to
  `hreflang_targets_out_of_scope` (+ `_count`, a summary line `str9.out_of_scope` with Turkish) instead of
  `hreflang_targets_not_assessed`, so coverage (`coverage._str9`, unchanged) does not mark STR-9 partial. With external
  checks on, a target not asked (cap) is still not assessed.
- G19 `language.WRONG_LANGUAGES`: jp→ja, cn→zh, gr→el, dk→da, cz→cs, ua→uk. Not added: uk, se, kr, ee (real ISO 639-1
  languages: Ukrainian, Northern Sami, Kanuri, Ewe); lowercase regions are valid (hreflang is case-insensitive);
  en_US already fails the shape check.
- Not done: G17's "empty meta description in its own Info row" (left in the same S4 target finding; Arjava's
  regression test reads that finding for the empty title).
- Tests: `test_gx2_str9.py`, `test_gx2_words.py` (G19 block).

## 8. G20: VideoObject default
- `PLACEHOLDER_VIDEO_NAMES` + `config.PLACEHOLDER_VIDEO_NAMES_MORE` (vidéo, vídeo, sans titre, sin titulo, ohne titel,
  فيديو; compared casefolded and folded). The audit-day uploadDate counts only beside a placeholder name or a missing
  thumbnailUrl. Arjava's "Video" + today still reports both reasons.
- Tests: `test_gx2_words.py` (G20 block).

## 9. G21-G24: STR-21 and words
- `page_words.fold` also strips Latin letter marks (à, é, ñ, ü, ß, œ ...); Turkish behaviour unchanged.
- `BASIC_PAGES_MORE` (de/fr/es/it/ar, merged into `BASIC_PAGES`), `BUY_WORDS` phrases (in den warenkorb, ajouter au
  panier, añadir al carrito, add to bag, ...; no bare "kaufen"/"comprar"), `CART_ACTION` adds basket, checkout,
  warenkorb, panier, carrito, carrello. `basic_pages_found` reads AboutPage/ContactPage/FAQPage first. Product, article,
  category, pricing and FAQ folders in de/fr/es/it. The STR-21 note text (and its Turkish) says so.
- G22 dates: `config.MONTH_NAMES_MORE` (de/fr/es), `DATE_LABELS_MORE`; d.m.y with "3. März", "1er mars",
  "14 de febrero de 2026"; labels followed by le/am/el; "aktualisiert/mis à jour/actualizado" are "modified".
- G23: generic titles de/fr/es/ar (startseite, accueil, inicio, sans titre, sin título, الرئيسية ...).
- G24: `small_site._stem_match` matches the whole segment (stem + up to 8 letters): `/menu-settings` is not matched,
  `/menumuz`, `/urunlerimiz`, `/sube` still are.
- Not done: `itemprop=price` outside an itemscope (the parser keeps microdata only inside itemscope) and AddAction.
- Tests: `test_gx2_words.py`.

## 10. G06: platform and CDN
- `site_platform.py` rewritten: every page read votes, most pages wins, `BUILT_ON` (WooCommerce over WordPress), ties to
  the more specific. Added Magento, Shopware, PrestaShop, OpenCart, Squarespace, Webflow, Drupal, Next.js (also
  X-Powered-By); Ticimax now needs its static host. CDNs: Akamai, CloudFront, Fastly, Sucuri, Imperva, Vercel, Netlify.
  Only headers in `crawler.KEPT_HEADERS` are seen (server, x-cache, x-cdn, x-iinfo, x-powered-by); via, x-amz-cf-id,
  x-served-by, x-vercel-id are listed so they count once another worker keeps them. Not done: H09's vendor-machinery
  paths (index_data, not mine).
- Tests: `test_gx2_platform.py`.

## 11. Fixture-build bugs
- STR-4: a number before a prefix symbol ($, £, ¥, ₩) followed by a number is not a price ("No. 1 $28.00" reads
  $28.00); suffix markers (€, TL, kr) keep "28,00 € 30,00 €" as two prices.
- STR-6: news folders in other languages (actualites, noticias, nachrichten, aktuelles, artikel, ...) are article
  folders; Article markup and og:type=article were already read by STR-6.
- STR-18: a leading article (the/le/la/l'/der/die/das/el/los/las/il/lo/gli) is dropped from the brand name before it
  is looked for in the title.
- Tests: `test_gx2_words.py` (item 11), `test_gx2_markup.py::test_the_homepage_title_names_a_brand...`.

## xfail markers removed (tests/test_brand_neutral.py)
G07 x2, G08, G09, G10, G11 x2 (+ bank and local-wp Notes caps), G13, G17, G18 x2, G19, G20, G21 x6 (shop-de x4 incl.
its cap, shopify Add to bag, news /a-propos), G22, G06 x2, shopify cap (G10+G07). 25 in all; the 16 left name
G01-G05 and G16.

## Touched outside my files
- `maya_audit/structure_data.py`: `image_sample` delegates to `media_sample`; `_check_images` uses `own_image`,
  `asset_hosts`, `key_page_urls` and sends `IMAGE_HEADERS` (a few lines).
- `maya_audit_web/sentences.py` (one line, `str9.out_of_scope`), `maya_audit_web/catalog.py` (`SAVED_ONLY` + one row).
- `tests/test_arjava_regression.py` (G13 assertion), `tests/test_w2_assets.py`, `tests/test_w2_part1.py` (behaviour
  changes above).
