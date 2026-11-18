# The JSON report format

Current version: `1.33`

Every JSON report the tool writes (`--json`, and one per brand from `batch`) starts with `schema_version`.
Anything that reads a report, including the web interface, reads that number first.

- Same first number: safe to read. A higher second number only adds fields.
- Different first number: a field was removed, renamed or changed meaning. Do not read it without a migration.
- No `schema_version` at all: the report was written before the format was frozen.
  `maya_audit.schema.unsupported_reason(report)` returns the reason as a sentence, or nothing when the report can be read.

The frozen shape for each version is in `docs/report-schema-<version>.json`. A test compares it with the code, so
the shape cannot change by accident.

## Changing the format

1. Change the code.
2. Raise `SCHEMA_VERSION` in `maya_audit/schema.py` (first number for a removal, rename or change of meaning; second for an addition).
3. Run `python -m maya_audit.schema`. It writes the frozen copy for the new version. Keep the old copies.
4. Describe the change in the "Versions" section at the end of this file, and every new field in the tables.

The tests fail until the code, the frozen copy and this document agree.

## What the version does not cover

These hold whatever one check needed, and differ from check to check. They are for a person reading the report
and for the check that wrote them. A program should show them, not depend on their inner keys.

- `evidence` on a finding, a review item, a check or a gate.
- `observations` on a check.
- `analysis` on a page.
- The per-family data on the crawl: `access`, `index`, `render`, `structure`, `perf`, `citations`, `citation_domains`.

## Top level

| Key | Always | What it holds |
|---|---|---|
| `schema_version` | yes | The version of this format, as text: `"1.14"`. Read it as numbers, not as text: 1.10 comes after 1.9 (`maya_audit.schema.version_key`). |
| `report_version` | yes | The version of the check-status vocabulary, used only by the `migrate` command. Not the format version. |
| `status_meanings` | yes | One sentence for each check status, so a reader never has to guess. |
| `scope` | yes | Which check families ran, as one line of text. |
| `gates` | yes | The four integrity gates (INT-1 to INT-4). List of gate records. |
| `checks` | yes | Every site check. List of check records. |
| `answer_engine_panel` | yes | The ANS checks, kept apart from the site checks. List of check records. |
| `findings_in_priority_order` | yes | Finding ids from `checks`, most important first. |
| `needs_human_review` | yes | Ids of the review items across all checks. |
| `page_counts` | yes | `pages_checked` (what the page cap counts) and `redirects` (fetched, but not pages). |
| `brand` | yes (since 1.14) | The brand name the audit used and where it came from (`maya_audit.brand.resolve`, DECISIONS 201): `name` (null when none could be found), `source` (`typed`: the name typed or saved, the only confirmed one; `site`: the site's own name; `domain`: the address's label split into the site's own words; null: none), `confirmed`, `found_in` (for a name read from the site: `og_site_name`, `organization`, `website` or `title`; `address` for `domain`) and `pages` (how many pages gave the name). It decides which DataForSEO keywords are brand searches and what the cover is titled. Reports before 1.14 hold none; the cover then shows the address. |
| `problem_summary` | yes | The totals every output prints and which page each problem is on (below). Reports before 1.9 hold none; a reader derives it with the same function, `maya_audit.report.problem_summary`. |
| `time_limit_cuts` | yes | Empty unless the time limit was reached. One row per data collector it stopped: `collector`, `reason`, `checks_not_run`, `checks_run_on_fetched_pages_only`. |
| `crawl` | yes | The crawl record (below). The bulk of the file. |
| `dataforseo` | no | The backlinks panel, when DataForSEO was used (below). |
| `firecrawl` | no | What Firecrawl was used for, when it was switched on for the audit (below). |
| `evidence_saved` | no | Present when page evidence was saved: `folder`, `mode`, `pages`, `not_saved`, `total_bytes`. |
| `migrated` | no | Present only on a report converted by `migrate`. |

## Problem summary

Counted once, by the engine, from the site findings (the answer-engine panel is not counted). A problem is a finding
whose severity is not `Info`; an `Info` finding is a note and appears in no row.

| Field | What it holds |
|---|---|
| `pages_checked` | The number of pages the headline names. When a page reader read any: pages read, the same figure as `audit_status.content_coverage.pages_read` (since 1.11 a page is a distinct HTML document; before, each address was counted, so a PDF and a second address of the same page added to it). Otherwise `page_counts.pages_checked`. |
| `problems`, `notes` | How many findings are problems, and how many are notes. |
| `by_severity` | The number of findings at `S1`, `S2`, `S3`, `S4` and `Info`. |
| `whole_site` | The problems whose `scope.kind` is `sitewide`, and since decision 198 the problems one shared element of a single section causes (see `shared_elements`): `problems`, `worst_severity` (null when there are none), `finding_ids` and `shared_elements`. They are counted here only, never against the pages they list. |
| `whole_site.shared_elements` | Since 1.11: the site-wide problems that one shared element causes on most pages (DECISIONS 171), each `{finding_id, kind, element, pages}`. `kind` is `link_no_text`, `link_no_address`, `heading_jump`, `heading_jump_varied` or `image_no_alt`. `element` names the element so it can be found: `type` (`link`, `image` or `heading`), then `href` (as the page wrote it, fragment included, as a path when it is on the audited site), `src` or `text` (and `level` for a heading, `why` for a link without an address), and `where`: `header`, `nav`, `footer`, `aside`, or `repeated` when the markup names no region. `pages` is how many pages carry it. The same facts are in the finding's `evidence.shared_element`. Since decision 198 (no version change: additions inside the element) an element may also hold `block` (the nearest element around it with a class or an id, `div.post-related`), and for nameless links grouped by their block `hrefs` and `links`; an element that only one section's pages carry is listed here too, once, and never on its pages' rows: its finding's `scope.kind` is not `sitewide`, its id is in `whole_site.finding_ids`, and its `element` holds `section` (`blog`; an empty string when its pages are in more than one section), which is how a reader tells it from a site-wide one. An empty list when there is none; a report saved before holds no such key and a reader derives it with `maya_audit.report.with_page_items`. |
| `by_page` | One row per page with at least one problem: `url`, `problems`, `worst_severity`, `finding_ids`, `items`. Worst severity first, then most problems, then the address. A problem counts once for each distinct page it names. |
| `by_page[].items` | What each of the page's problems is on that page (since 1.10), one entry per `finding_ids` entry and in the same order: `finding_id`, `check_id`, `severity`, `kind` and `values`. `kind` names the sentence (a key of `maya_audit.report.PAGE_KINDS`, for example `title_long`); `values` holds that page's own figures for it (for example `{"characters": 71, "limit": 60}`) and differs from kind to kind. A figure the finding's evidence does not hold for the page is left out of `values`, and the sentence then takes its plain form; the finding's site-wide count is never used as the page's. A finding with no rule of its own has the kind `affected`, with the finding's `title` and its page `count`. `maya_audit.report.page_sentence(item)` gives the English sentence. Reports of 1.9 hold rows without `items`; a reader derives them with `maya_audit.report.with_page_items`. |
| `files` | Since 1.11: one row, in the shape of a `by_page` row, for each address with a problem that is a file and not a page: a sitemap, robots.txt, a PDF or another document, an image (`maya_audit.urls.non_page_kind`, judged from the path). Such an address is never a row of `by_page`. Printed under the table as "Files (sitemaps, robots.txt, documents)". A report saved before holds no such key; a reader moves the rows with `maya_audit.report.with_page_items`. |
| `not_listed` | One row per problem that affects more pages than are listed for it: `finding_id` and `pages`, the number of pages missing from `by_page`. Empty when the full lists were at hand, as they are when a report is written. |
| `page_checks` | How many of the report's page checks could run (since 1.11): `total` (the checks in the report whose question is answered by reading the audited pages, `maya_audit.coverage.PAGE_DEPENDENT`; the answer-engine panel and the paid data panels are never among them), `could_run` (those whose status is not `not_assessed` and whose own evidence does not say they looked at no page: `pages_checked` or `candidates` of 0 on a check with no finding) and `limited` (true when fewer than half could run). When `limited`, every output's headline starts "Only 16 of 41 page checks could run, so this is not a clean result." A report saved before 1.11 holds none; a reader counts it from the report's own `checks` with `maya_audit.report.page_checks`, and the web app counts it that way for every report it shows, so a report whose zero-page checks were saved as `partial` reads the same. |
| `single_page` | Present only in a single-page audit (since 1.13): `{url}`, the one address that was read. Then the headline ends "Only this page was read; other pages of the site were not checked.", the report's title is "Single-page audit: <URL>", the whole-site row is labelled "Site-level (affects this page)", and the checks that compare the pages of a site (`maya_audit.single_page.COMPARES_PAGES`) are `not_assessed` with `evidence.single_page` and are not counted in `page_checks`. `crawl.config.single_page` is true for such a run. |
| `start_address` | Present only when the address the audit was started on answered 400-599 and the audit ran from another page that was read (since 1.14; DECISIONS 202): `{entered, status, audited_from}`, the address as typed, its status and the homepage the audit used (`maya_audit.access_data.homepage_url`). Then every output says first: "The start address you entered returned {status} ({path}). The audit was run from {audited_from} instead." Never in a single-page audit. |

## Gate record

| Field | What it holds |
|---|---|
| `check_id` | `INT-1` to `INT-4`. |
| `title` | The gate's name. |
| `state` | The gate's outcome, in the gate's own words. Gates have no severity. |
| `confidence` | One of the confidence values below. |
| `summary` | One or two plain sentences. |
| `evidence` | Not covered by the version. |
| `how_to_fix` | Text, or null. |

## Check record

| Field | What it holds |
|---|---|
| `check_id` | For example `IDX-3` or `STR-13`. |
| `title` | The check's name. |
| `status` | One of: `findings`, `needs_review`, `pass`, `partial`, `observed`, `not_assessed`. |
| `summary` | One or two plain sentences. For `not_assessed`, the reason. |
| `findings` | List of finding records. |
| `evidence` | Not covered by the version. |
| `observations` | Measurements without a threshold. Not covered by the version. |
| `review_items` | List of review-item records: things a person should look at that have no severity. |
| `coverage` | `not_assessed`: the parts of the check's question that could not be answered, each with a reason. `rule`: where that list comes from. |

A `pass` with anything in `coverage.not_assessed` is written as `partial`, never as `pass`.

## Finding record

| Field | What it holds |
|---|---|
| `id` | Stable for the same check, title and pages: `IDX-3-1a2b3c4d`. |
| `check_id` | The check that reported it. |
| `title` | The finding in one line. |
| `severity` | `S1` (most serious), `S2`, `S3`, `S4` or `Info`. |
| `confidence` | `verified`, `inferred`, `estimated` or `not_assessed`. |
| `rationale` | Why it matters: Documented, Measured, Hypothesis (never above S4) or Self-evident harm. |
| `engines` | Which search and answer engines it concerns. |
| `scope` | `kind` (`sitewide`, `template` or `page`), `count` (all affected pages) and `urls` (the first 25). |
| `evidence` | Not covered by the version. |
| `expected` | What a correct site does. |
| `how_to_fix` | The concrete fix. |
| `cost_tier` | `T0` (plain fetch) or `T1` (needed a browser). |
| `intent` | Null, or the site owner's declared intent that changed the severity. |
| `launch_gated` | Launch-gate items that apply: the bot registry's reasons (ACC), and since 2026-10-14 the docs/LAUNCH-GATE.md items (`LG-16`) of a rule not yet validated on real sites (`maya_audit.launch_gate`, DECISIONS 203). A finding that carries any is shown with "Unverified check" on the web card, in the PDF and in the Markdown. |
| `notes` | Caveats, in plain sentences. |
| `importance_tier` | 0 a confirmed key page is affected, 1 a suggested key page, 2 other pages. |
| `observed_at` | When it was observed (UTC). |

## Review-item record

`id`, `check_id`, `title`, `confidence`, `engines`, `scope`, `evidence`, `launch_gated`, `importance_tier` and
`observed_at` as on a finding, plus:

| Field | What it holds |
|---|---|
| `why_review` | Why a person should look. |
| `suggested_action` | What to do about it. |

## Crawl record

| Field | What it holds |
|---|---|
| `start_url`, `origin` | The URL given and the scheme and host the audit stayed on. |
| `user_agent`, `product_token` | How the tool identified itself. |
| `started_at`, `finished_at`, `elapsed_s` | Times in UTC, and the duration in seconds. |
| `config` | The settings of the run. |
| `robots` | What each robots.txt answered. |
| `pages` | List of page records, redirects included. |
| `skipped_robots` | URLs not fetched because robots.txt disallows them. List of skipped-URL records. |
| `sitemap_docs`, `sitemap_urls`, `sitemap_lastmods`, `sitemap_notes` | The sitemaps read, the URLs they list, their dates, and disclosures about sitemap discovery. |
| `discovered_urls`, `not_fetched_urls` | Every URL found, and those found but not fetched. |
| `stop_reason` | `exhausted`, `page_cap`, `time_limit`, `rate_limit`, `error`, `robots_disallowed`, `network_problem` (no answer from the site reached this computer, so nothing was crawled directly; not a statement about the site) or `stopped` (a stop was requested). |
| `stop_detail` | The stop reason as a sentence. |
| `deadline_hit` | True when the time limit was reached. |
| `stopped` | True when a stop was requested at any point, during the crawl or the checks after it. Such an audit is incomplete and can be resumed. |
| `render_discovery` | Whether link discovery also read rendered pages (for sites that write their links with JavaScript): `enabled`, `used`, the pages rendered, and the links that added. |
| `requests` | Every HTTP request made. List of request records. |
| `bot_info_check` | The check of the tool's own public information page, or null. |
| `network` | How this computer looked hosts up: `preflight` (the check made before anything was requested: `status`, `host`, `answered_by`) and `dns` (per host: `lookups`, `answered_by` — `system`, `doh:cloudflare` or `doh:google` — `failures`, `system_resolver_failed`). About this computer, not the site. Null when the audit used no real network. |
| `collector_errors` | Which data collectors failed or were cut, with the reason. |
| `backoff`, `sessions` | Rate-limit slowdowns, and one row per crawl session (more than one after a resume). |
| `steps` | The step timing table (1.14, team-preview-16): one row per step in order, `step` (`sitemap`, `crawl`, `access`, `index`, `structure`, `render`, `performance`, `sitemap_check`, `llms_links`, `citations`, `citation_domains`, `robots_wait`, `other_sites` (the pool of requests to other sites, beside the other steps) and `other_sites_wait`, and `page_reader` for the Firecrawl page reader), `started_at` (null for the reader), `seconds`, `requests` and `waiting_s` (the part of the time spent waiting: the gap between requests, Retry-After, the performance rounds' pauses; null for the reader). |
| `skipped_for_time` | The optional steps the time limit cut (1.14, team-preview-16), in the order they give way: `other_site_links`, `llms_links`, `sitemap_check`, `performance`, `rendering`. Empty when nothing was cut or the audit was stopped. |
| `page_grouping` | The page grouping's summary (1.23, DECISIONS 297), or null in a report that has none: `method_version`, `confidence` ("Estimated"), `pages_scored`, `pages_not_scored`, `page_types` (count per type), `templates` (the 40 largest template keys with their page counts), `templates_total`, `not_reached_from_homepage`, `reached_through_hreflang`, `aliases`, `canonical_pages_scored`, `canonical_pages` ({url: grouping} for canonicals scored from their aliases without being read, DECISIONS 298), `citable_content_pages`, `weights`, `type_weights`, `footer_link_weight`, `not_indexable_cap`, `policy_footer_cap`, `order`, `basis`. Its inner keys are not covered by the version. |
| `reader_page_grouping` | The same grouping for the pages a page reader (Firecrawl) read when Maya's crawler was blocked or rate-limited (1.24, DECISIONS 304), or null: the keys of `page_grouping` plus `reader` (its name) and `pages` ({url: grouping record}, as a page record's `grouping`). Worked out while the reader's pages and their links were in memory; Maya's own page records hold no content then. `{"reader", "error"}` when the grouping failed. |
| `business_type` | The business type the audit used (1.25, DECISIONS 311), or null in an older report: `id` (a profile of `maya_audit/business_types/profiles/`, `diger` for none), `label` {tr, en}, `chosen_by` (`user` or `suggestion`), `suggestion` {`id`, `label`, `reason` {tr, en}, `signals`, `scores`, `version`}, `page_types` (the importance summary: `profile`, `formula`, `weights`, `pages_by_type`), `not_found` (the profile's first three page types no page read was typed as: `type`, `label`, `rank`), `version`. Its inner keys are not covered by the version. |
| `redirects` | Every requested address that redirected (1.26, DECISIONS 315), or null in an older report: `url`, `hops` ([{`url`, `status`, `target`}] in order), `final` (where the redirects end), `final_status` (its answer, null when not fetched), `loop` (the walk came back to an address already passed). Its inner keys are not covered by the version. |
| `locales` | The site's country/language folders (1.27, DECISIONS 316), or null in an older report: `folders` (the locale folders, such as `global-en` or `tr`), `main` (the folder the homepage landed on, `""` for the root, null when unknown), `versions` (the folders, and the root when it holds a version), `root_is_version`, `basis` ({folder: why it counts}). Its inner keys are not covered by the version. |
| `page_measures` | What was measured on each page whose content was read (1.29, DECISIONS 323), or null in an older report: {url: record}, Maya's pages and a page reader's (a page both read keeps Maya's). A record holds only what was measured: `status`, `html_bytes`, `main_offset_bytes`, `ttfb_ms`, `cache`, `title`, `description` (and their lengths), `canonical`, `h1_count`, `heading_jumps`, `html_lang`, `hreflang`, `words`, `main_chars`, `images`, `blocking_scripts`, `analytics`, `schema_types` and the link counts (see the 1.29 section). Its inner keys are not covered by the version. |
| `host_moves` | Moves to the site's twin address after the start (1.33, DECISIONS 358): when the site's own pages redirect to it (apex and www, http to https), [{`from`, `to`, `redirects`, `after_pages`, `sitemap_named`}]; empty when the crawl stayed where the start led it. The earlier origin's addresses are still requested and their links count as internal. |
| `sampling` | The plan of an Akıllı ~150 audit (1.30, DECISIONS 327), null for any other audit and in an older report: `mode` (`smart`), `version`, `budget`, `profile`, `folders`, `main`, `types` ({type: {`rank`, `label`, `known` (addresses typed as it before reading, corrected after the first wave), `planned`, `examples`}}), `waves` ([{`wave`, `after_pages`, `planned`}]), `retyped`, `known`, `files_left_out`, `planned_urls`, `method`. Pages read per type come from the page grouping (`business_page_type`). Its inner keys are not covered by the version. |
| `access`, `index`, `render`, `structure`, `perf`, `citations`, `citation_domains` | Not covered by the version. |

## Page record

| Field | What it holds |
|---|---|
| `url` | The address fetched. |
| `discovered_via` | `start`, `key_page`, `link`, `rendered_link` (a link found only in a rendered page), `sitemap` or `redirect`. |
| `depth` | Clicks from the start URL, or null for a sitemap-only URL. |
| `requested_at`, `elapsed_ms`, `ttfb_ms` | When, how long, and time to first byte. |
| `user_agent` | The user agent sent. |
| `status`, `error` | HTTP status, or the transport error. |
| `content_type`, `body_bytes`, `body_truncated`, `headers` | What came back. |
| `fetch_class` | `ok`, `blocked`, `rate_limited` or `error`. |
| `classification_confidence`, `classification_evidence` | How sure that class is, and why. |
| `redirect_location` | The target, when the response was a redirect. |
| `retried_after_429` | True when the fetch was repeated after a rate limit. |
| `view` | `raw`: the record describes the HTML the server sent. |
| `content_checks_eligible` | False when the tool could not read the page. |
| `links_found`, `outlinks`, `external_links` | The count of links, the links to this site, and the links to other sites (capped; the caps are in `config`). Each link has its target, every anchor text used for it, how many links go there, and how many of those have no text. A link found only in the rendered page is marked `rendered`. |
| `grouping` | The page grouping (1.23, DECISIONS 297), Estimated, never used for a severity; null in a report that has none. For a page read: `template_key` (the URL pattern such as `/products/*`, with ` ~ <layout>` where a pattern holds two layouts, or for flat pages grouped by layout), `url_pattern`, `layout` (a 6-character layout fingerprint), `page_type` (`home`, `category`, `product`, `blog_article`, `policy`, `utility` for search/cart/account, `other`), `page_type_basis` (why), `internal_link_score` (0-100, weighted PageRank over the links between pages read, log scale against the site's best-linked page), `inlinks` (pages read that link to it), `click_depth` (link steps from the homepage over the pages read, the homepage's hreflang alternates one step; null when not reached, never 0), `click_depth_basis`, `importance` (0-100), `importance_parts` (`internal_link_score`, `click_depth`, `page_type`, `capped`: false, "not indexable", "utility page" or "policy page linked only from footers or sitewide blocks"), `importance_rank` (1 = first; ties broken by `tie_break`: `body_inlinks`, `products_listed`, `sitemap_position`, then crawl order, never the address), `citable_content` (true on blog and article pages; no score effect), and on an alias `canonical` and `canonical_importance` (DECISIONS 298). For a page not read: `{"not_scored": "redirect" \| "not a readable HTML page"}`. |
| `analysis` | Not covered by the version. Since 1.24 (DECISIONS 304) it may hold `structured_data.products` (per Product node, at most 5: `type`, `gtin` {key: value}, `mpn`, `sku`, `brand`, `offers` [at most 5: `price`, `priceCurrency`, `availability`, any `gtin`/`mpn`/`sku`], `has_variant`, `variant_identifiers`, `in_list`), `pagination_links` (`next`/`prev` hrefs as written) and `author_signals` (where the page names an author). |

## Request, sitemap and skipped-URL records

- Request: `seq`, `url`, `purpose`, `user_agent`, `started_at`, `status`, `error`, `elapsed_ms`, `ttfb_ms`,
  `extra_headers`, `started_mono`, `ended_mono`.
- Sitemap document: `url`, `status`, `error`, `kind`, `urls_found`, `lastmod_count`, `lastmod_distinct`,
  `lastmod_top`, `lastmod_top_count`, and (1.24) `image_entries`, `video_entries`: the `<image:image>` and
  `<video:video>` entries of a urlset (0 for an index or a file that was not read).
- Skipped URL: `url`, `discovered_via`, `decision`.

## Backlinks panel (`dataforseo`)

| Field | What it holds |
|---|---|
| `source` | Says the data is third-party, not measured by the crawl. |
| `audit_id` | Ties the section to its rows in the cost ledger. |
| `panel` | The panel's name. |
| `confidence` | Always an estimate from a third-party index. |
| `target` | The domain looked up. |
| `status` | `assessed`, `partly_assessed` or `not_assessed`. |
| `checks` | DFS-1 and DFS-2, in the shape the panel uses. |
| `calls` | One row per planned call: endpoint, estimate, real cost, and whether it came from the cache. |
| `requests_sent` | Paid requests actually sent (0 when everything came from the cache). |
| `estimated_usd`, `cost_usd` | Planned and real cost of this audit's calls, in US dollars. |
| `stopped` | Optional, only when requests were left out because of the account's balance or the audit's own spending limit: `code` (`provider_credits_insufficient`: DataForSEO refused a request for no credit during the run; `balance_at_start`: the person chose to run without paid data because of the balance; `audit_cap_reached`, team-preview-14: the audit reached its own DataForSEO limit, $5.00 unless configured, so the request that would pass it and those after it were not sent), `after` (the check that was refused; for `audit_cap_reached` the last check asked for before the limit; or null), `not_requested` (the checks that were not sent). The new code is a new value of an existing field, so the schema version is unchanged (1.13). |
| `note` | Optional, with `stopped`: one sentence for the whole panel ("DataForSEO refused a request because the account has no credit, so the remaining 6 were not sent. Nothing was charged for them." "Search data was not requested: the DataForSEO balance was $0.00 when the audit started." or "This audit reached its $5.00 DataForSEO limit after DFS-6, so the remaining 3 request(s) were not sent: DFS-7, DFS-8, DFS-9. Nothing was charged for them."). The checks left out have `status: "not_assessed"` and a summary that begins "not requested:". |
| `relevance` | Optional, when the search data panels ran: `brand_words`, `common_word_brand` (the brand name's word when it is also an ordinary word, else null), `warning`, `site_words_used`, and since 1.14 `sorted` (false when no brand name was known: the keyword tables then stay as they are, with "The brand name could not be confirmed, so these keywords are not sorted into brand searches and other searches."), `brand_source` and `brand_confirmed` (as the report's `brand`). How the keyword panels were sorted into branded, relevant and unrelated. |

## Firecrawl section (`firecrawl`)

Present only when Firecrawl was used for the audit (the default when a key is set). Maya's own crawler always runs first; nothing in this
section changes a gate or the crawl record. One access result changes with it: when Firecrawl, as `main page reader`, read a site that
challenged Maya's crawler, the ACC-9 finding is written as severity `Info` with the measurement kept in its evidence
(`read_through`, `severity_before_firecrawl_read`).

| Field | What it holds |
|---|---|
| `source` | Says the reading is a third party's, not Maya's own crawler's. |
| `enabled`, `used` | Switched on for this audit; and whether any check ended up resting on it. |
| `purpose` | `main page reader` (Firecrawl read the audit's pages, blocked or not), `content reader for a blocked site` (older reports) or `rendering fallback`, when used. |
| `reason` | Why it was not used, when it was not. Begins "Firecrawl basic was also blocked" (or the proxy used) when every page asked for came back as a challenge page, an error or no document. |
| `notice` | The sentence shown with every result built on it (for a blocked site: AI crawlers may not see this content). |
| `options` | What the person chose: `read_blocked`, `read_always` (page reader of every audit), `render_fallback`, `max_pages`, `proxy`, `owner_approved_bypass`, `allow_without_zero_data_retention`. |
| `proxy` | `basic`, or `enhanced` / `auto` when `owner_approved_bypass` is true. |
| `owner_approved_bypass` | True when the person stated, for this audit, that the site owner approved bypassing bot protection. |
| `zero_data_retention` | `requested`, `applied`, and `status`: `applied`, `not available` (Firecrawl refused; nothing was sent without it) or `waived by the user for this audit`. |
| `page_cap` | The most pages Firecrawl could read in this audit. |
| `crawl_blocked` | `blocked` and `why`: whether Maya's own crawl was blocked, by INT-1's rule. May hold `homepage_fallback` (DECISIONS 286, 288): `url`, `why`, `maya_blocked` ("blocked for Maya's crawler (429 on pages)" or null), `owner_approved_bypass`, `continued` (the reader went on past the homepage, only with the owner's approval), `proxy`, `pages_asked`, `read`. Inside `crawl_blocked`, which the frozen shape does not describe, so 1.20 is unchanged. |
| `robots` | Where the robots.txt rules came from (`Maya's own crawler` or `Firecrawl`) and whether they could be read. `status`, `mode`, and `reason` disclose the applied policy: 4xx except 429 allows all; 429 pauses requests; 5xx/unreachable disallows all. |
| `pages` | One row per page asked for: `url`, `outcome` (`read`, `blocked`, `error`, `failed`), `status`, `bytes`, `from_cache`. No page content. |
| `rendered` | The same, for the rendering fallback. |
| `pages_read`, `skipped_by_robots`, `pages_blocked_for_firecrawl_too` | Counts. |
| `checks_from_firecrawl` | The ids of the checks whose results rest on Firecrawl's reading. Each of those checks also says so in its summary, and each of their findings in its first note. |
| `needs_decision` | `zero_data_retention` when Firecrawl refused it and the person has to choose. |
| `errors` | Optional provider failures: `url`, `http_status`, full redacted `message`, `engines_tried`, `kind` (`engine_selection` or `provider_load_failure`), `meaning`, `note`. Not proof of a target block. |
| `stopped_because` | Why reading ended early, when it did. |
| `calls` | One row per request: `url`, `status`, `bytes`, `from_cache`, `credits`, `estimate_credits`, `billing_status`, `data_from`. |
| `requests_sent` | Requests actually sent to Firecrawl. |
| `credits` | `per_page`, `estimated_max`, `used_or_reserved`. |
| `usd` | `per_credit` (null until configured), `estimated_max`, `used_or_reserved`, `note`. |
| `sitemap` | Present when the reader was asked for the site's sitemap because Maya's own crawler could read none: `documents` (each `url`, `outcome` of `read`, `index`, `not_found`, `unreadable` or `disallowed_by_robots`, `status`, `addresses`, `from_cache`), `addresses_found`, `note`. At most two documents an audit; each counts as one of the audit's page requests. |
| `coverage` | What the reader's sample covers: `read`, `page_cap`, `cap_reached`, `known_urls_not_requested`, `requested_without_a_readable_document`, `answered_with_an_error_status`, `status_unknown`, `from_cache`, `key_pages_not_read`, `examples_not_requested`, `not_requested_because` (`page_cap`, `time_limit`, `stopped_on_request`, `reader_kept_failing`, `request_allowance_used`, `credit_or_request_limit`, `not_reached` or null; `request_allowance_used`, since 1.11, is the audit's request allowance spent before the pages read reached the cap, which earlier reports called `credit_or_request_limit`), `causes` (a count per reason a requested page was not read: `reader_challenged`, `redirect_to_another_site`, `redirect_within_the_site`, `error_status`, `empty_document`, `provider_could_not_load`, `timeout_or_no_answer`, `credit_or_request_limit`, `provider_refused`), `sections_sampled`, `sitemap_addresses_found` (addresses found by the reader itself, when it was asked for the sitemap of a site Maya's own crawler could not read; 0 on a site Maya read), `sitemap_addresses_known` (since 1.11: the addresses Maya's own crawl knew from the sitemap, which the reading queue is seeded with), `page_requests` and `requests_without_a_new_page` (since 1.11: page requests sent to the provider, and how many answers gave no new page because they redirected to a page already read or found no page), `unread_left_out` (since 1.11: `robots_disallowed` and `not_a_page`, the known addresses that are not counted in `known_urls_not_requested`), `attempted`, `elapsed_s`. Each row of `pages` carries the same reason as `cause` (null when read). |
| `coverage.indexability_disagreements` | Since 1.11, when Firecrawl read a site Maya's own crawler could read too: the pages whose two copies disagree on noindex, each `{url, own, reader}` (the noindex declarations found in Maya's own response and in the reader's document; an empty list means none). The first 40; `coverage.indexability_disagreements_count` is the exact number. Maya's own response is the one used (DECISIONS 167). |

## `audit_status`

Four answers kept apart, so that none is inferred from another. A finished job is not a complete audit; content
read through a reader is not access; a user-agent probe is not a vendor's crawler.

| Field | What it holds |
|---|---|
| `direct_access` | `state`: `readable`, `challenged`, `rate_limited` or `unknown`, from Maya's own page requests; `note`; `page_requests`; `by_response` (counts of `ok`, `blocked`, `rate_limited`, `error`). Never changed by a reader's success. |
| `content_coverage` | `level`: `complete_sample`, `partial` or `none`; `pages_read` (since 1.11: pages, each distinct HTML document once, whoever read it; DECISIONS 170) and `readable_unique_urls` (the name the figure had before; it holds the same number, and in reports before 1.11 it counted addresses); `read_by`: `maya_only`, `firecrawl_only`, `both` and `total` (three numbers that do not overlap and add up to `total`, which is `pages_read`; `firecrawl_only` and `total` since 1.11) and `firecrawl` (every page the reader read: `firecrawl_only` + `both`; kept from 1.6); `other_addresses` (since 1.11): `files` (addresses Maya's crawler fetched that are not HTML: a PDF or another document) and `same_page` (addresses the page reader recorded as redirecting to a page that was read), neither counted as pages; `page_requests_by_maya`; `discovered_urls`; `known_urls_not_read` (the report's one "not read" figure: every check's "pages found but not read" coverage part carries the same number); `unread_left_out` (since 1.11): `robots_disallowed` and `not_a_page`, the known addresses that figure leaves out; `key_pages_not_read`; `reasons` (at most one sentence about why reading stopped; when the page reader is the audit's main reader, the page cap of Maya's own crawl is not repeated here and stays in `crawl.stop_reason`); `note`. `complete_sample` means every address found within the audit's scope was read: a sample, not the whole site. A reader shows a report saved before `pages_read` existed with `maya_audit.report.content_coverage_shown`, which counts pages from the report's own `crawl` and `firecrawl` sections. |
| `vendor_crawler_evidence` | `state`: `verified_log_evidence` (server logs supplied, ACC-5), `limited_user_agent_probe` (ACC-4 ran: requests under crawlers' names from Maya's own network) or `not_measured`; `note`. |
| `summary` | The three notes as one sentence group, for any interface to show as it is. |

## `archives` (optional)

Present only when the plan asked for archived copies and neither Maya's crawler nor Firecrawl could read the site.
A separate section: nothing here changes a check of the live site.

| Field | What it holds |
|---|---|
| `enabled` | The archives asked: `wayback`, `common_crawl`. |
| `cost_usd` | Always 0: both archives are free. |
| `page_cap` | The most archived pages read, shared between the archives. |
| `notice` | "Historical content only; live access findings are unchanged." |
| `sources` | One per archive: `id`, `name`, `status` (`assessed` or `not_assessed`), `pages_read`, `notes` (what the archive answered, and its limits), `pages` (`url`, `date`, `archive_url`, `label` "archived/indexed copy, date X; the live site may differ", `title`, `text_sample`) and `checks` (the content checks run on those copies, each finding id prefixed with the archive's id). |
| `requests_sent`, `downloaded_bytes`, `fetched_at` | What was asked of the archives, and when. |

## `crux` (optional)

Core Web Vitals from Google's Chrome UX Report. Present when `MAYA_AUDIT_CRUX_API_KEY` is set.

| Field | What it holds |
|---|---|
| `source` | Says what the figures are: real Chrome visitors on phones, the last 28 days, 75th percentile. |
| `status` | `assessed` or `not_available`. |
| `summary` | One sentence; when not available, why (no data for a small site, a refused key, an unreachable service). |
| `metrics` | One row per metric: `metric`, `label`, `p75`, `shown`, `rating` (`good`, `needs improvement`, `poor`; null for a metric that is not a Core Web Vital). |
| `origin`, `form_factor`, `data_until`, `fetched_at` | What was asked about, and the last day the data covers. |
| `passes_core_web_vitals` | True only when all three core metrics are published and good. |

## `ownership` (optional)

Whether the person running the audit proved control of the site. Present when a verification was attempted.

| Field | What it holds |
|---|---|
| `verified` | True when the token was found. |
| `method` | `meta_tag` or `dns_txt`, when verified. |
| `token` | The token looked for. It is not a secret: it only proves who can edit the site or its DNS. |
| `checked_at`, `summary` | When, and what was found. |
| `instructions` | The two ways to verify, as text to copy. |

## Versions

- `1.14` (2026-10-14): additions only. `problem_summary` gains `start_address` (`entered`, `status`, `audited_from`), present only when the start address answered 400-599 and the audit ran from another page (`problem_start_address` in the frozen shape). This version grows with its batch (team-preview-14): later changes of the batch are added under this entry. Second change of the batch (2026-10-14): the report gains the top-level `brand` (`name`, `source`, `confirmed`, `found_in`, `pages`; `brand` in the frozen shape, with the vocabularies `brand_source` and `brand_found_in`), and `dataforseo.relevance` gains `sorted`, `brand_source` and `brand_confirmed` (inside the panel, not covered by the frozen shape; the evidence `relevance` of DFS-4 and DFS-5 gains the same two, or `{sorted: false}` when no brand was known). A finding's `launch_gated` may now hold launch-gate item numbers (`LG-16`) as well as the bot registry's reasons (no new field); a check whose finding a launch-gate row set to "off" left out says so in its summary and lists the titles in `evidence.left_out_unverified` (no row is "off" today). A 1.13 report has no `brand` and is read unchanged. Also in this batch, added without a version because they sit inside evidence or add a value: `dataforseo.stopped.code` may be `audit_cap_reached` (the audit's own spending limit, not the account's balance); a shared element's `element` may hold `section` (only the pages of one section carry it) and `block` (the named block a nameless link sits in); STR-8's grid evidence gains `selector` and `first_row`, and its new empty-table finding `empty_tables`; IDX-3's evidence gains `rechecks` (each looping URL and the homepage walked 3 more times), `loops_rechecked`, `homepage_rechecks` and `recheck_requests`, with two new titles ("N URL(s) intermittently redirect to themselves; the page loads on another try", "N URL(s) redirected to themselves once; this could not be re-checked"); IDX-6's link to another site at one of this site's paths now has two titles ("..., and the other address returns {status}" and "...; the other address could not be checked") and its check evidence gains `of_which_the_other_address_answers_with_a_page_or_a_redirect`, `links_to_brand_family_domains_not_checked`, `brand_family_domains` and `other_site_requests`; `crawl.config` gains `brand_family_domains`, `idx6_other_site_checks_max`, `redirect_recheck_attempts` and `redirect_recheck_max_hops`; the request purposes `redirect_recheck` and `other_site_link` are new. Reports of 1.13 and before are read unchanged; their old IDX-6 title is still worded in both languages. Round 2, run 2 (2026-10-14), also without a version: a page's `analysis` may hold `empty_response` (`body_bytes`, `limit`) for a 2xx answer with nothing in it; IDX-1 has two new titles ("N page(s) answer with an empty page (under 512 bytes)", "N page(s) show a server error message with the server's file paths") and its refetch rows gain `empty_response` and `body_bytes`; INT-1's evidence gains `empty_responses`; `crawl.access` gains `ua_check` (a browser and Googlebot's user agent on a site whose ownership is not verified) and ACC-4 two new titles ("A request with Googlebot's user agent got {status} on N of M URL(s) where a browser got {browser}", "N of M URL(s) sent Googlebot's user agent a page of very different size than a browser's"); INT-4's evidence gains `ua_check`; the request purpose `ua_check` is new; `crawl.config` gains `empty_response_max_bytes` and `ua_check_urls`. team-preview-16, run 1 (2026-10-15), also without a version: an ACC-4 `ua_check` pair may have the outcome `browser_not_real` (not assessed; the browser itself got an empty or error page) and each answer gains `empty_response`; IDX-3 has a new title ("N URL(s) loop for visitors without cookies (crawlers); with the cookie the site sets, the page loads"), its loop evidence gains `cookie_walks`, a hop gains `set_cookie` (and in a cookie walk `cookie_sent`), never a cookie's value, its check evidence gains `cookie_recheck_requests`, and the request purpose `redirect_recheck_cookies` is new; ACC-3 has a new title ("noindex via {where} on N utility page(s) (such as a QR menu or a print page): check that this is intended") with `utility_segments` in its evidence; STR-5's evidence (check and finding) gains `branches_not_counted`; a page's `analysis.tables[]` and `analysis.div_grids[]` gain `has_controls`, a grid also `heading` and `label`, STR-8's `grids_left_out` may hold calculators and empty tables (`container: "table"`), and `problem_summary.by_page[].items` may have the kind `div_grid_heading`; an STR-9 mismatch row gains `main_words`, and a page left out of the language comparison may say why with `detected` and `stopword_hits`. team-preview-16, run 3 (2026-10-15): the crawl record gains `steps` (the step timing table: `step`, `started_at`, `seconds`, `requests`, `waiting_s`, with the Firecrawl page reader's row `page_reader` when it read pages) and `skipped_for_time` (the optional steps the time limit cut), both in the frozen shape's `crawl`; `crawl.config` gains `fast_check` and `crawl_time_share` is 1.0 (was 0.6). A report without them is read unchanged. team-preview-16, run 4 (2026-10-15), also without a version: `crawl.steps` may hold the rows `other_sites` and `other_sites_wait`; `crawl.backoff` gains `adaptive_pacing`, `narrowed` (`from_s`, `to_s`, `after_requests`), `floor_s`, `narrowing_stopped`, `site_host` and `host_gaps_s`; INT-4's `politeness` evidence gains `adaptive_pacing`, `narrowed`, `floor_s`, `narrowing_stopped`, `by_host` (`host`, `requests`, `min_gap_ms`, `required_gap_ms`) and `hosts`, and its gaps are measured per host (`required_gap_ms` is the audited site's floor in use); `crawl.config` gains `adaptive_pacing`, `min_request_delay_s`, `pacing_clean_answers`, `pacing_factor`, `pacing_clean_ttfb_ms`, `pacing_reset_ttfb_ms` and `other_site_workers`; IDX-8's merged title reads "1 group of indexable pages that are copies or near-copies of each other (N pages)" / "N groups of …" (the run-2 title is still worded).
- `1.13` (2026-10-13): additions and two changes inside findings; the report's own keys are the same as in 1.12, except `problem_summary.single_page` (below). This version grows with its batch (team-preview-13): later changes of the batch are added under this entry. **IDX-2**: every host whose http:// address is not redirected to https:// is now in ONE finding, titled "No HTTP to HTTPS redirect on {hosts}" with no parenthesis after the hosts (before: one finding for each different answer, the answer in a parenthesis). Its `evidence.hosts[]` holds every host that was tested, also the ones that redirect correctly, and each row gains `host`, `outcome` (`served_on_http`, `redirects_to_http_served`, `redirects_to_http_then_https`, `redirects_elsewhere`, `other_status` or `redirects_to_https`) (the list is `vocabulary.http_redirect_outcome` in the frozen shape, the one part of the shape that is new) and `line` (the English sentence for that host, shown under the finding in the Markdown report, the card and the printed report). The severity is the highest of its parts: High for `served_on_http` and `redirects_to_http_served`, Low otherwise (DECISIONS 188). **IDX-8** no longer writes the finding "N indexable pages share the title …": a shared title is STR-1's finding only (DECISIONS 187; a saved report that holds the old finding is displayed as before). A near-duplicate finding's evidence gains `variant_like` (true when the pages look like variants of one product; its fix then asks for what sets each variant apart), `titles` (address to title) and, when `variant_like`, `differs_in` on each row of `pairs`: `{"url": {"a": [...], "b": [...]}, "title": {...}}`, the words only one side has (DECISIONS 190). **STR-7**: the check's evidence gains `map_images_left_out_count` (images served by a map host with a deliberate `alt=""`, left out as decorative), and an image row's `why` gains the value "a map tile or map control (decorative)" (DECISIONS 186). Nothing new is stored for "No problem found on the N pages read (M not read)": it is worked out from the report when it is shown (DECISIONS 189). Added with the single-page mode (2026-10-13): `problem_summary` may hold `single_page` (`url`), only in an audit of one address; a check set aside in such an audit is `not_assessed` with `evidence.single_page` (`compares_pages` or `not_the_homepage`); an older reader that ignores the key reads the report as an audit of a one-page site.
- `1.12` (2026-10-12): additions only. A shared element's `kind` gains `links_no_address` (several links without an address on exactly the same pages, listed in `element.texts`), `link_generic` (one link with only generic text, `element.text` and `element.href`) and `link_no_text_pattern` (links with no text whose addresses follow one pattern, `element.pattern` and `element.example`). Per-page kind `no_organization`. No field is removed. Not a shape change, but worth knowing when comparing reports: findings are ordered by severity, then by what they stand in the way of, and only then by page count; an http:// address that answers 200 is High, a missing sitemap on a site of more than 50 URLs is Medium, and a homepage without an `<h1>` or without Organization data is Medium.
- `1.11`, added 2026-10-12 without a new version (additions only; older reports are read unchanged): `dataforseo` may hold `stopped` and `note` when requests were left out because of the account's balance; a check refused for no credit says "the DataForSEO account has no credit for this request (provider code 40200)" instead of the provider's raw "40200 Payment Required"; the Lighthouse check (DFS-9) is aimed at the homepage the crawl ended on.
- `1.11` (2026-10-11): `problem_summary` gains `page_checks` (`total`, `could_run`, `limited`): how many of the page checks could run, said first in the headline when fewer than half could. `firecrawl.coverage` gains `indexability_disagreements` and `indexability_disagreements_count`; when Firecrawl is the page reader of a site Maya's own crawler read too, `firecrawl.crawl_blocked.why` now reads "Maya's own crawler read the site; Firecrawl read the pages as this audit's main page reader". Page `analysis` (not covered by the version) gains `embedded_documents` (documents a page reader wrote into the page in place of an iframe, each `{src, chars}`; taken out before the page was read) and `outside_head` (`title`, `meta`, `canonical`: tags found after the body started, which are not read as the page's). A check of page content that had no page to look at is now `not_assessed` rather than `pass` (IDX-8, STR-1 to STR-23, TSEO-1). Nothing is removed. This entry grows with the team-preview-11 batch: later changes of the batch add their fields here, under the same version. Second change of the batch (2026-10-12): `audit_status.content_coverage` gains `pages_read`, `other_addresses` (`files`, `same_page`) and `unread_left_out` (`robots_disallowed`, `not_a_page`), and its `read_by` gains `firecrawl_only` and `total`; `readable_unique_urls` and `problem_summary.pages_checked` now count pages, not addresses. `problem_summary` gains `files`, and `problem_summary.whole_site` gains `shared_elements`. `firecrawl.coverage` gains `sitemap_addresses_known`, `page_requests`, `requests_without_a_new_page` and `unread_left_out`, and `not_requested_because` may be `request_allowance_used`. `content_coverage.reasons` holds one sentence for a reading that used its request allowance ("the page reader used all 51 page requests this audit allows and read 43 pages; 8 requests led to pages already read or to missing pages"), and every check's "pages found but not read" part carries `known_urls_not_read`. A problem one shared element causes on most pages is one site-wide finding with `evidence.shared_element` (STR-7, STR-14, STR-19, TSEO-1). The IDX-5 finding about stamped sitemap documents is site-wide. STR-10 says "have an empty og:title" for a tag that is present with no content. Not covered by the version: a page's `outlinks` entries gain `hrefs` and `where` on a link with no name; `analysis.heading_counts.skipped_level_jumps` entries gain `text`, `in_chrome` and `where`; a `data:` image address in STR-7 evidence is stored as its first 60 characters and its size. Added on 2026-10-12 without a new number (additions inside `evidence`, `analysis` and the page-kind vocabulary, none of which the frozen shape covers): the page kind `markup_price_differs` (`values`: `markup`, `currency`, `shown`) for an STR-4 price that differs; in an STR-4 price row `schema_currency`, `offer_parent` (`type`, `name`), `visible` as a list of `{text, value, currency, context, where}` (it was a list of texts, or a sentence for a value not shown), `why_not_reliable` and `why_code` (DECISIONS 175); in STR-5's `variants` rows `name`, `spellings`, `pages` and `by_source`, and the finding "og:site_name holds the page title" with `pages` rows of `{url, og_site_name, title}` (176); in STR-7's image rows `count` and `src_pattern`, and `images_count`, `no_alt`, `empty_alt` beside them; in STR-8 `grids_left_out` (178); in a page's `analysis`, `beside_label` on each image, `row_labels` on each table, and `in_collapse` and `row_labels` on each `<div>` grid.
- `1.10` (2026-10-11): each row of `problem_summary.by_page` gains `items`: what each of the page's problems is on that page (`finding_id`, `check_id`, `severity`, `kind`, `values`), read from the finding's own evidence. "Problems by page" in the Markdown report, the web card and the printed report now says what is wrong on each page with that page's own numbers ("Title too long (71 characters)") where it used to repeat the site-wide title ("31 page title(s) above the 60-character guidance band"); the "Whole site" row keeps the titles. The STR-19 finding about links with no address also records `by_page` (`url`, `links`) in its evidence. `finding_ids` and every other key are unchanged. Reports of 1.0 to 1.9 remain readable and are not rewritten: the web app derives `items` for them with the same engine function. The version is compared as numbers (1.10 is after 1.9).
- `1.9` (2026-10-10): the report gains `problem_summary`: `pages_checked`, `problems`, `notes`, `by_severity`, `whole_site`, `by_page` and `not_listed` (the headline's totals and the problems by page, counted once by the engine). The Markdown report gains the headline line and a "Problems by page" section. Reports of 1.0 to 1.8 remain readable: the web app derives the section for them with the same engine function and does not rewrite the saved files.
- `1.8` (2026-10-09): the crawl record gains `network`; `stop_reason` gains `network_problem`; a robots record's `mode` gains `not_checked` (no answer reached this computer: nothing is assumed about the site) with a `cause`; the request log's `error` gains `local_dns_failure`, `host_not_found` and `unresolved_host` beside `unsafe_target`; `firecrawl.robots` may hold `mayas_own_attempt` and `firecrawl.crawl_blocked` may hold `direct_not_reached`; in the evidence of DFS-4 and DFS-5, `relevance` gains `ambiguous` and the data may hold an `ambiguous` list (the brand's ordinary word on its own). A fetch answered with HTTP 202 is classified `blocked`. Older reports are read unchanged.
- `1.7` (2026-10-09): `firecrawl` gains `sitemap` (what the reader was asked for and found when Maya's own crawler could read no sitemap); `firecrawl.options` gains `spread_by_section`, `sitemap_discovery` and `stop_after_unreadable`; `firecrawl.coverage` gains `not_requested_because`, `causes`, `sections_sampled` and `sitemap_addresses_found`; each `firecrawl.pages` row gains `cause`; `crawl.config` gains `reader_reserve_s`. Reports of 1.0 to 1.6 remain readable.
- `1.6` (2026-10-09): adds the required section `audit_status` (direct access, content coverage, vendor crawler evidence, and one sentence). `firecrawl` gains `coverage`; its `pages` rows gain `status_known`, `observed_at`, and, where the reader was redirected, `final_url`, `host_alias` and the outcomes `redirected` and `redirected_out_of_scope`; a row's `status` is null when the reader reported none. ACC-9's evidence, when a reader read the pages, holds `severity_before_reader` and `shown_as_a_note_because` (the earlier `severity_before_firecrawl_read` is no longer written). Reports of 1.0 to 1.5 remain readable; a reader of them must treat `audit_status` as absent.
- `1.5` (2026-10-09): adds `dataforseo.relevance` (`brand_words`, `common_word_brand`, `warning`, `site_words_used`). In the evidence of DFS-4 and DFS-5, `table` gains a `Relevance` column and holds only branded and relevant keywords, with `relevance` (counts and method) and `unrelated` beside it; DFS-6 gains `own_domain_removed` and `possibly_generic_overlap`; STR-23's evidence gains `careers_pages_listing_openings`. Reports of 1.0 to 1.4 remain readable.
- `1.4` (2026-10-08): adds `firecrawl.options.read_always` and the `firecrawl.purpose` value `main page reader` (Firecrawl as the page reader of every audit); ACC-9 may be written with severity `Info` and `evidence.read_through` when a challenged site was read through Firecrawl; adds the optional sections `archives`, `crux` and `ownership`; the `dataforseo` section may hold the search data checks DFS-3 to DFS-12, whose `evidence.data` has `metrics` and `table`. Reports of 1.0 to 1.3 remain readable.

- `1.3` (2026-10-08): adds optional `firecrawl.errors` for complete provider-load diagnostics. Existing fields remain readable. Engine failures are distinguished from target blocks; the page queue can continue without retrying the failed URL.

- `1.2` (2026-10-07): one addition, the optional `firecrawl` section. A reader written for 1.1 still works.

- `1.1` (2026-10-06): additions only. The crawl record gains `stopped` and `render_discovery`; `stop_reason` gains
  `stopped`; `discovered_via` gains `rendered_link`. New checks STR-14 (anchor text) and STR-15 (thin content);
  IDX-7 and STR-7 report more. Links now carry every anchor text. A reader written for 1.0 still works.
- `1.0` (2026-10-06): the first frozen version. It is report version 0.4 with `schema_version`, `page_counts`,
  `time_limit_cuts` and the optional `dataforseo` and `evidence_saved` sections.

### Stage 1 accounting clarification (schema 1.1)

The top-level shape remains 1.1. `dataforseo.cost_usd` now includes every attempted paid call, including
failed calls: the reported cost when available, otherwise the retained reservation. It is an accounted
spend-or-reserved total, not a claim that every cent was billed. `dataforseo.calls[].billing_status`
distinguishes `reported`, `estimated`, `possibly_billed`, and `failed` for new non-cache records;
older records and cache hits may omit it. A cache hit costs zero. The ledger remains the durable source.
Do not add call estimates to `cost_usd` again. Paid calls with ambiguous outcomes are not retried.

The existing `crawl.sessions` and Markdown resume disclosure describe mixed-session coverage. Current
request-level detail covers the latest session; earlier session totals and page timestamps are retained.
The shape has not changed; resume bindings are internal crawl-database metadata, not report fields.

### Additions that did not change the shape (still 1.1, 2026-10-07)

- Two more checks appear in `checks`: `STR-16` (the same meta description on several indexable pages) and `STR-17`
  (indexable pages with no link to another page of the site). Both use the ordinary check and finding records. A
  reader written for 1.1 needs no change; it sees two more entries.
- `scope.urls` still holds the first 25 affected pages and `scope.count` the total. The full lists are not in the
  report. `maya_audit.report.affected_urls(checks)` returns them by finding id; the web app saves them beside the
  report as `affected-urls.json`.
- The progress hook (not part of the report) has a `sitemap` phase, and its `crawl` events carry `other_fetches`
  and `requests_sent`.
- In an LLM brief (`--llm-brief`, a separate file), each skill gains `missing_reasons`: why each entry of `missing`
  is missing. A named check now has to be assessed and hold data; a check that measured zero still counts.
- Corrections after the first real audit through the web app (2026-10-07), none changing the shape:
  the coverage part every page-reading check gets on an incomplete crawl is now named `pages found but not read`
  (before: `pages not checked because the crawl was incomplete`) and says the check ran on the pages read;
  `maya_audit.coverage.CRAWL_GAP_NAMES` holds both names. STR-4 reports a markup price the page did not show as a
  review item when every price shown is matched by another offer. RND-4 reports a canvas found on most pages once,
  as Info. ACC-2 treats the signed-in app, dashboard and settings paths as private (`config.PRIVATE_PATH_SEGMENTS`).
- After an audit of a site behind bot protection (2026-10-07), still shape 1.1: seven more checks appear in `checks`
  (`ACC-9` automated visitors blocked or challenged; `STR-18` to `STR-23`: homepage title and brand, links that lead
  nowhere, message in video, basic pages, news page of outside links, job pages without JobPosting). INT-1's evidence
  gains `blocked_by`. Page `analysis` gains `dead_links`, `dead_link_total` and `media`. IDX-2 no longer reports a
  missing redirect when a start address typed with http:// redirects to https://.

### T0a robots policy clarification (schema 1.2)

No frozen format fields change. ACC-1 evidence and summary disclose the applied robots policy;
Firecrawl’s existing `robots` object records the reused or fetched policy and its reason.
429 is a temporary rate-limit stop (`crawl.stop_reason: rate_limit`), not an RFC claim
that the site disallows all crawling. Retry on a later owner-initiated audit. Existing
request pacing/backoff remains in force. Other 4xx responses, including HTML challenges,
mean no rules; 5xx means complete disallow. A fetch that got no answer at all (a failed DNS lookup on this
computer, a timeout, a refused connection) is `not_checked`: nothing is assumed about the site and nothing is
reported against it, and Maya's own crawler requests no page (`crawl.stop_reason: network_problem`).

### Native redirect diagnostic evidence (2026-10-16, unchanged schema 1.14)

`crawl.index.redirect_rechecks` and finding `evidence` are open diagnostic objects, excluded from the frozen shape
as explained above. Walks now retain observed-cycle and readable-HTML flags, fetch classification, native client
context and hop request timestamps/errors. Intermittent findings also retain readable initial-crawl successes.
Missing legacy flags do not prove readable success; cookie-state transitions cannot be reconstructed from redacted
cookies. Consumers should show these diagnostics, not treat an HTTP 200 or a hop cutoff as proof of page access.
No versioned field was added, removed or renamed. Saved artifacts are not migrated or rewritten.

## 1.15 — evidence-qualified diagnostics

Adds optional `firecrawl.unsupported_resources` (URL, kind, source/outcome and response observation/cache time where
available). Known media never reaches the page reader; media-typed responses remain diagnostics, not unreadable
page failures. Coverage stop reasons additionally distinguish `provider_timeout` and `provider_error` from explicit
credit/request limits. Existing 1.x reports remain readable; absent historical reasons are never invented.
Keyword intent dimensions live inside open DataForSEO check evidence; originals and provider totals are preserved.


## 1.33 — the crawl follows the site to its twin address (2026-11-18)

Added for DECISIONS 358; nothing was removed or renamed, so 1.x readers keep working.

- `crawl.host_moves`: when the site's own pages answer with a redirect to its twin address (carpexonline.com ->
  www.carpexonline.com) three times, or once when robots.txt names its sitemap there, the crawl moves there as it does
  for a start redirect: that address's robots.txt and sitemaps are read and the redirect targets are queued.
  `crawl.origin` is the address moved to. Each move is a row {`from`, `to`, `redirects`, `after_pages`,
  `sitemap_named`}, and since DECISIONS 359 `copies`: the pages the earlier address answered with their content instead
  of redirecting ({`url`, `status`, `canonical`, `twin`}); such a page record keeps no analysis and is not a page read
  (`content_checks_eligible` false), its `twin` address is read instead. The rows' inner keys are not covered by the
  version.

## 1.32 — which sitemap file lists each address (2026-11-11)

Added for DECISIONS 337; nothing was removed or renamed, so 1.x readers keep working.

- `crawl.sitemap_docs[]` gains `new_urls`: how many of a urlset file's addresses no earlier file listed. `crawl.sitemap_urls`
  holds these new addresses file by file in reading order, so the file that lists each address follows from the two
  (`maya_audit.sitemap.file_map`). For a report written before, the file is recovered only when the files' address
  counts add up exactly to the addresses known; otherwise it is not said.
- Not in the frozen shape (evidence and page analysis are open): each link record in `crawl.pages[].outlinks` carries
  `href`, the address as the page wrote it; IDX-1's broken-link findings carry `split: 337`, and the sitemap-only one
  `sitemap_entries` (address, where it ends, its status, its sitemap file, a matching heading, what to do),
  `sitemap_files` and `likely_cause`.

## 1.31 — where Core Web Vitals were asked (2026-11-09)

Added for DECISIONS 334; nothing was removed or renamed, so 1.x readers keep working.

- `crux.reason_code` (`no_key`, `no_data`, `error`, `time_limit`, null when assessed), `crux.attempts` (every request:
  `origin` or `url`, `http_status`), `crux.origins_asked` (the origin the site landed on first, then the typed one),
  `crux.homepage` (the homepage's own record: `url`, `http_status`, `status`, and when assessed its `metrics`,
  `data_until`, `passes_core_web_vitals`, `summary`) and `crux.fetched_for_saved_audit` (true in `artifacts/crux.json`,
  the section fetched again for a saved audit; report.json is never written).

## 1.30 — the Akıllı ~150 plan (2026-11-08)

Added for DECISIONS 327; nothing was removed or renamed, so 1.x readers keep working.

- `crawl.sampling`: the plan of an Akıllı audit (`maya_audit.sampling`): per page type of the business profile the
  addresses known before reading (typed by address and menu text, corrected by URL template after the first wave)
  and the pages planned, the two waves, how many addresses were re-typed, the planned addresses (the page reader's
  order when Maya is blocked). Null for every other audit. The coverage line per type ("Klinik ve konum: 4/4 okundu")
  is worked out from it and the page grouping when a report is built.

## 1.29 — what was measured on every page read (2026-11-08)

Added for DECISIONS 323; nothing was removed or renamed, so 1.x readers keep working.

- `crawl.page_measures`: `{url: record}` for every page whose content was read, Maya's own pages and the pages a page
  reader (Firecrawl) read; a page both read keeps Maya's record. A record holds only what was measured on that page:
  `status`, `view` (when not Maya's raw copy), `html_bytes` (and `html_truncated`), `main_offset_bytes`, `ttfb_ms`,
  `cache`, `title` and `title_chars`, `description` and `description_chars` (texts cut at 160 characters), `canonical`
  (and `canonicals` when a page declares several), `h1_count`, `heading_jumps` and `heading_jump_examples`, `html_lang`,
  `hreflang` (how many), `words`, `main_chars`, `images` and `images_missing_alt`, `blocking_scripts`, `analytics`,
  `schema_types`, `dead_link_total`, `link_control_total` (`maya_audit.page_measures`). Why a version: the checks'
  evidence keeps a sample of pages, and a page read only through a page reader keeps no record in the report, so
  without this field those pages' values would be lost once the audit ends. For a report saved before 1.29 the same
  records are worked out offline from `crawl.pages[].analysis`; a page read only through a page reader there has none.

## 1.28 — block pages and the page limit (2026-11-06)

Added for DECISIONS 317; nothing was removed or renamed, so 1.x readers keep working.

- `firecrawl.coverage.page_limit`: how the plan's one page limit was shared: `plan`, `maya_pages_read` (Maya's own pages
  read, which count), `block_answers` (page requests Maya's crawler got a block page, a challenge or a 429 for),
  `block_answers_counted` (always 0: a block answer is not a page read and never uses up the limit) and
  `reader_new_pages_allowed` (what the page reader could read beside Maya's pages). A saved audit's current-engine copy
  works it out from the saved data and adds `worked_out_offline: true`.
- Not covered by the version: the ACC-9 finding `acc9.bot_protection` (a named bot-protection service answered Maya's
  page requests with its block page; its evidence adds `ai_crawlers_named` and, when a page reader read the site,
  `read_through`), and `crawl.reader_page_grouping`, now also written when the main page reader read pages Maya's crawler
  did not read (or got a block page for).

## 1.27 — country/language versions (2026-11-06)

Added for DECISIONS 316; nothing was removed or renamed, so 1.x readers keep working.

- `crawl.locales`: the site's country/language folders, its main version and how many versions it has. The crawl and the
  page reader read one version of each page before a second (at most two before the rest of the site), so the pages read
  are no longer mostly copies of the same page.
- `firecrawl.pages[].outcome` may be `over_page_cap`: a redirect led the page reader to a page Maya had not read after the
  plan's one page limit was reached (the pages both readers read now stay within it).

## 1.26 — redirect hops, Stage 8a rules (2026-11-06)

Added for DECISIONS 315; nothing was removed or renamed, so 1.x readers keep working.

- `crawl.redirects`: every requested address that redirected, hop by hop, with the final address and its status.
- New finding kinds (rule ids, no shape change): `idx6.links_to_redirect`, `idx4.chain`, `str9.wrong_language`,
  `str7.over_100kb`.

## 1.25 — business type (2026-11-05)

Added for DECISIONS 311; nothing was removed or renamed, so 1.x readers keep working. Why a new version: the crawl
record gained `business_type`, and the page grouping's records can now be re-scored by it, so a 1.24 reader that took
`importance` for Stage 3's link-based value would be wrong for a 1.25 report with a profile.

- `crawl.business_type`: the business type (suggested or chosen), its suggestion and reason, the importance summary and
  the "not found among the pages read" list.
- Inside a page's `grouping` (not covered by the version, listed for readers): `importance_source` (`links` for
  "Diğer" and older reports, `profile:<id>` otherwise), and with a profile `business_page_type`,
  `business_page_type_basis`, `business_signals`, `business_citable`, `importance_links` and `importance_rank_links`
  (Stage 3's own values), `importance_parts.profile_weight` and `importance_parts.formula`.
- `crawl.config.business_type`: `auto` or the profile id asked for (config keys are not covered by the version).
- `crawl.page_grouping.business_type` and `importance_source` (inner keys, not covered).

## 1.24 — the page reader's grouping, sitemap media counts, Product fields (2026-11-03)

Added for DECISIONS 304; nothing was removed or renamed, so 1.x readers keep working. Why a new version: two records
gained fields (`crawl.reader_page_grouping`; the sitemap document's `image_entries`, `video_entries`), and a 1.23
reader that took their absence as "no grouping" or "no image sitemap" would be wrong for a 1.24 report.

- `crawl.reader_page_grouping`: when Maya's crawler was blocked (or rate-limited) and Firecrawl read the pages, the
  page grouping (templates, page types, importance) of Firecrawl's pages, computed while their links were in memory.
  Before 1.24 such an audit had no importance at all (DECISIONS 303). The client reports read it first.
- Sitemap document `image_entries`, `video_entries` (SEO-036). A 1.23 report has neither; the image and video sitemap
  rule says "not assessed" for it, never "no image sitemap".
- Inside `analysis` (not covered by the version, listed for readers): `structured_data.products` (the key Product
  fields: identifiers, brand, offers), `pagination_links`, `author_signals`.
- New finding kinds (rule ids, no shape change): `idx6.alias_links`, `str15.empty_collections`, `tseo1.url_decomposed`,
  `acc3.robots_noindex`, `idx7.pagination_unlinked`, `idx7.product_no_category`, `idx5.no_image_sitemap`,
  `idx5.no_video_sitemap`, `tseo1.url_slug_unclear`, `str3.article_no_author`, `str3.product_no_identifier`.

## 1.23 — page grouping (2026-11-02)

Added for DECISIONS 297; nothing was removed or renamed, so 1.x readers keep working.

- A page record has `grouping` (see "Page record"): template key, URL pattern, layout fingerprint, page type and its
  basis, internal link score, inlinks, click depth and its basis, importance and its parts.
- The crawl record has `page_grouping`: the method's weights and the counts per page type and template.
- Before 1.23 was first pushed, DECISIONS 298 added inner keys (method 2): `importance_rank`, `tie_break`,
  `citable_content`, alias `canonical`/`canonical_importance`, and `page_grouping.canonical_pages`.
- Both are Estimated and are not used by any check, severity, confidence or the release gate. A 1.22 report has
  neither; they are not invented for it (`tools/page_groups_saved.py` works them out offline for a saved report).

## 1.22 — Firecrawl's own pace, timeouts asked again, and time the computer slept (2026-11-02)

Added for DECISIONS 295; nothing was removed or renamed, so 1.x readers keep working.

- `firecrawl.coverage.timeouts`: `{"timed_out", "retried", "read_on_retry", "skipped"}`: pages whose call timed out
  (no answer, or Firecrawl's own HTTP 408), pages asked for a second time, pages read on that second try, and pages
  skipped (timed out twice, or never asked again because reading had stopped). A page row (`firecrawl.pages[]`) may
  carry `retried` (true when its document came from the second request, or it failed after it).
- `firecrawl.concurrency` (not part of the frozen shape) now describes Firecrawl's own pace, not Maya's site limit:
  `own_pace`, `gap_s` (seconds between request starts, the setting, at least a robots.txt Crawl-delay), `gap_final_s`,
  `crawl_delay_s`, and each `backed_off` step adds `gap_from_s` and `gap_to_s`. Reasons are "429 from Firecrawl",
  "5xx from Firecrawl", "429 from the site", "5xx from the site" and "timeout"; "slow answer" is no longer used.
  `site_limit` is always false: Firecrawl's requests no longer go through Maya's limit, and `crawl.backoff.site_limit`
  counts Maya's own requests only.
- `firecrawl.options.gap_s`: the gap asked for, or `null` for this computer's setting (`MAYA_AUDIT_FIRECRAWL_GAP_S`).
- `audit_status.timing` adds `slept_s` (how long the computer slept during the audit: wall clock less the audit's own
  clock, which stops during sleep; `null` when not measured) and `slept_note` (the sentence, when it is 2 min or more).
- RND-6 may carry `evidence.source` "firecrawl", `evidence.measured_on` and `evidence.pages_measured`: when Maya's
  crawler was blocked it is measured on the HTML Firecrawl returned.

## 1.21 — the shared site limit and the reader's measured pace (2026-11-02)

Added for DECISIONS 294; nothing was removed or renamed, so 1.x readers keep working.

- A request record (`crawl.requests[]`) has `slot`: which slot of the shared site limit carried it (`0` the audit's own
  thread, `1`-`9` the sitemap check's workers), or `null` for a request made before the limit existed (the crawl) or
  to another host. INT-4 measures the polite gap per slot, and between starts where slots overlapped.
- `firecrawl.concurrency`: `configured` (the setting, 1 to 10), `start` (what was used: 1 without a shared site limit),
  `final`, `backed_off` (each step down: `from`, `to`, `reason` such as "429 from Firecrawl", "5xx from the site" or
  "slow answer", `after_answers`), `max_in_flight`, `site_limit` (whether the shared limit spaced the starts).
- `firecrawl.coverage` adds `seconds_per_page_measured` (wall time per page asked for, with the requests in flight),
  `call_seconds_measured` (the median time one call took), `seconds_per_page_assumed` (the planning figure, 8),
  `skipped_for_time` (pages known and allowed but not asked for because the time limit came first; 0 otherwise) and
  `ran_beside_maya` (true when the reader started as soon as Maya's crawl ended).
- Inside `crawl.backoff` (not part of the frozen shape): `site_limit` with the limit's `configured` and `final` values,
  `backed_off` steps, `max_in_flight` and `starts` by who asked. Inside `crawl.index.sitemap_check`: `sample_files`,
  `asked_by_file`, `workers` and `rate_limited`.

## 1.20 — the finding contract and the release gate (2026-10-27)

Added for the release gate (`maya_audit/release_gate.py`, DECISIONS 278); nothing was removed or renamed, so 1.x
readers keep working. Each field is `null` when the engine has not established it; it is never guessed.

- A finding may carry `page_types`: `{url: kind}` for its affected pages (`homepage`, `product`, `article`,
  `pagination`, `listing`, ... or `"unknown"`). Content advice is never given for an unknown kind.
- `measurement`: `{"claims": [{"element", "state", "urls"}]}`: what the finding says about which element on which
  page (`state` e.g. `absent`, `empty`, `after_head`), so two findings that report one element on one page are seen.
- `remediation`: `{"task_id", "content", "page_types"}`: the catalogue task (`rule_actions.json`) that fixes the
  finding and, for content advice, the page kinds it may be given for.
- `dedup_key`: the cause the finding reports; another finding with the same key and the same pages is a double count.
- Every report carries `release_gate` (a required key): `{"version", "decision": "PASS" | "CONDITIONAL" | "BLOCKED", "violations":
  [{"rule", "hard", "message", "finding_id"}], "counts", "high_not_retested", "cards_checked"}`. It never changes a
  finding or a severity.

## 1.19 — the second look (2026-10-27)

- A finding may carry `verification`: what a second request saw before the report was written (DECISIONS 272).
  `{"state": "confirmed" | "changed" | "not_reproduced" | "not_retested", "checked": [rows: url, client,
  requested_at, status, error, fetch_class, body_bytes, empty_response, outcome], "reason": (only when not retested),
  "second_client": (a browser's answer, recorded beside it)}`. `null` when the finding's rule has no re-test or the
  finding is not High/Critical (or a Medium one from an unverified check). It never changes `severity`.
- `crawl.verification`: the stage's summary: `enabled`, `user_agent`, `cap`, `requests`, `findings`, `states`, and
  `reason` when it did not run. These requests come after the integrity gates and are not in `crawl.requests`.

## 1.18 — rule ids (2026-10-27)

- Every finding and review item carries `rule_id`: the stable kind of the finding, the key of the title frame it
  matches in `maya_audit_web/wording.py` (e.g. `"str2.home_hidden_h1"`), generated into `maya_audit/rule_ids.json`.
  `null` only for a title no frame matches. A reader that must know what a finding is reads `rule_id` rather than
  matching the English title, which may be reworded (DECISIONS 269).

## 1.17 — review fixes (2026-10-21)

Added while closing the preview-23 review findings (docs/review-fixes/). Each addition is listed by the change
that made it; nothing was removed or renamed, so 1.x readers keep working.

- W4a (CR-25, D-07): `generation.source_commit` (the git commit, or RELEASE-SNAPSHOT.json's base commit, or "not recorded") and `generation.source_provenance` (`source_commit`, `source_kind`, `release`, `base_commit`); `evidence_saved.folder` and the evidence `index.json` `folder` hold the folder's name or its path relative to the JSON report, never an absolute local path.
- Page record `wire_bytes` (W1, A10): bytes that came over the network for the answer, as sent (compressed if it was),
  beside `body_bytes` decoded; `null` when not measured (a failed request, a saved report). Page `headers` also keep
  `content-encoding`, `vary`, `cache-control`, `etag`, `age`, `x-cache`, `cf-cache-status`,
  `strict-transport-security`, `content-security-policy` and `x-content-type-options`, each cut at 512 characters.
- `checks[].status` may be `not_applicable` (B18): none of the pages read is what the check is about (STR-22 with no
  news page, STR-23 with no job page); coverage still lists any part of the site not read. Neither a pass nor a gap; a run that read no page still says `not_assessed`.
- `platform` (optional, H34): `{"name", "cdn", "signals"}` — the platform (Ticimax, Shopify, WooCommerce,
  WordPress, Wix, ikas) and CDN (Cloudflare) the pages read show, with the script, generator, header or /cdn-cgi/
  address behind each; present only when one of them is recognised, either may be null. A hint, used by no check.

## 1.16 — processing and phase provenance

New reports include `generation`: engine version, processing time, native collection interval/stop reason/page cap, native request purposes and separately scoped reader budgets/stops. Native crawl finish is not whole-job finish. Missing historical counters remain unavailable. Existing 1.x reports remain readable unchanged. Finding evidence additionally retains element/table context, explicit DOM/group/page counting units, keyword assessment gaps and semantic shared-element identity; these are defensive evidence fields rather than frozen schema keys. New shared findings include their semantic element/target identity in their ID seed; old IDs are preserved in saved reports and comparison remains evidence-based.
