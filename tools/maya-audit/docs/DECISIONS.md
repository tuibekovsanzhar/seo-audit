# Build decisions

Everything here is a decision this implementation made that the specification
([`technical-audit-checklist.md`](technical-audit-checklist.md)) did not settle. Each was put to
review in the round that produced it; the heading says whether that review happened. Read this
before changing behavior: most of these look like small choices and are not.

The numbering is historical (decisions were added round by round) and is referenced from code
comments, so keep the numbers stable and add new ones at the end.

## Approved in review (INT)


1. **Extra INT-2 stop reason `robots_disallowed`.** Used when robots.txt stops Maya from fetching anything.
2. **INT-2 "complete" definition.** The queue ran dry **and** no fetched page was blocked, rate-limited, or failed. URLs skipped by robots.txt don't make a crawl incomplete, but they are reported as a caveat.
3. **429 on robots.txt stops the crawl.** It's treated as complete disallow (politeness), although RFC 9309 would allow crawling.
4. **5xx pages have fetch class `ok`.** That's the server's own response; IDX-1 will report it. A 503 carrying a challenge signature is `blocked` (Estimated).
5. **INT-1 gate confidence** is Verified only if the same result holds using Verified classifications alone. Otherwise it is Estimated.
6. **Crawl-delay is capped at 90 s.** A declared value is honored up to that ceiling. The declared value is reported in INT-4's summary and evidence, and as an ACC-7 Info finding.
7. **Redirects** don't count toward the page cap; a fetch budget of 3× the cap stops loops.

## ACC decisions (reviewed)

8. **Ownership verification: meta tag only, by design (v1 scope).** The only method is `<meta name="maya-site-verification" content="…">` on the homepage. DNS and Search Console verification are a **documented v1 limitation**, not a gap to fill quietly later; adding them needs its own review. INT-4 re-derives ownership from the raw homepage tags rather than trusting the collection step.
9. **First-run S1s on deliberately blocked paths are expected.** The ACC-2 sample includes URLs Maya itself skipped, so a routine `*` Disallow on `/admin/` shows up as S1 for search bots until someone marks it intended. This is the approved design, not a bug.
10. **ACC-3 interpretations (approved):**
    - A `bingbot`-scoped `noindex` is S1 for Copilot, consistent with the Google rule.
    - `none` counts as `noindex` + `nosnippet`.
    - "Main content is hidden from snippets" means at least 90% of `<main>`/`<article>` text is inside `data-nosnippet` (the whole body is used, labeled Estimated, when those elements are missing). **The 90% figure is a round-number estimate, not calibrated; revisit it once real pages are available to check it against.**
11. **ACC-4 outcome mapping:**
    - *(approved)* A transport failure for the bot user agent while the browser succeeded counts as `blocked`.
    - *(approved)* `degraded` means fewer than 50% of the browser's visible words.
    - **"Different content" is a visible review item, not an Info finding.** It carries no severity, because harm can't be shown, but it's printed prominently as "NEEDS HUMAN REVIEW", listed in a separate section ahead of the severity-ranked list, and recorded under `needs_human_review` in the JSON. A check whose only output is review items has status `needs_review`, never `pass`.
    - Probes only go to URLs Maya itself was allowed to fetch. Non-matching results are retried twice; a pair that matches on retry becomes a "transient" observation.
12. **ACC-1 sampling (accepted):** robots.txt is fetched 3 times, 120 s apart, adding up to ~4 minutes to a live audit. The cost exists to catch intermittently failing robots.txt files. A 429 on robots.txt is recorded as an observation without severity.
13. **ACC-5:**
    - With thresholds unset, measured values (non-2xx share, last seen) are reported as observations without severity.
    - IP ranges must be local files; nothing is downloaded. Reverse-DNS verification (Google/Bing) is not built.
    - Log formats are limited as described in "ACC-5 log formats".
14. **ACC-6** emits an Info finding only when a training token is blocked. When the search bot is blocked too, the finding points to ACC-2 rather than repeating the S1.

## IDX decisions (reviewed)

15. **IDX-1:**
    - 5xx pages and transport failures are refetched once, 5 s after the crawl, at most 20 URLs.
    - *(changed with PRF, decision 49)* "On every attempt" now means every counted fetch of the URL in the audit: the crawl, the refetch, and the PRF rounds. A URL that works on any attempt is an observation pointing to PRF-1 (timeouts) or PRF-2 (other failures).
    - Timeout-only failures are reported separately from other transport errors, because only the timeout finding is Inferred.
    - A redirect pointing at a 4xx URL counts as an internal reference, making it S2.
16. **IDX-2** *(www-variant check added after review)*:
    - The start host **and its www / non-www variant** are both checked: certificate validity, expiry, and HTTP→HTTPS redirect. When both hosts have the same problem, it's reported as one finding naming both; an invalid certificate on the variant alone is S1, because links and typed URLs using it fail. A variant that doesn't resolve is recorded, with no finding. IP-address hosts have no variant.
    - Certificates are verified against the certifi (Mozilla) CA bundle, the same trust store the crawler uses. A CA that browsers trust but certifi doesn't would be flagged.
    - The HTTP→HTTPS check fetches each http origin's robots.txt before its homepage.
    - A site whose start URL is plain http gets the S4 "no redirect" finding.
17. **IDX-3:** internal links pointing at redirecting URLs are an observation without severity; the spec gives them none. A chain means 2+ redirects before the final URL.
18. **IDX-4** *(0.9 threshold: unvalidated round-number estimate; revisit with real data)*:
    - Several differing `<link rel=canonical>` tags on one page count as a conflict (S3).
    - A redirecting canonical is judged at its final URL.
    - **A canonical on another site is a visible review item**: it isn't fetched, so content can't be compared.
    - "Same content" means an identical visible-text hash (Verified) or an estimated similarity ≥ 0.9 from a shingle sketch (Estimated). **0.9 is a round-number estimate, not calibrated**, the same caveat as ACC-3's 90%.
19. **IDX-5:**
    - Listed URLs that redirect count as non-200.
    - The bad-URL share is computed over the listed URLs that were fetched, and labeled Estimated when some weren't.
    - "All lastmod identical" needs at least 2 values; "future" means more than 1 day ahead.
    - An unparseable sitemap counts as no sitemap.
    - Site size is the number of discovered URLs, a lower bound when the crawl stopped early.
20. **IDX-6:** one finding per broken target, as the spec's "4 dead URLs is 4 tasks" asks. Targets whose 5xx succeeded on refetch are excluded.
21. **IDX-7:** click depth is measured from the start URL (normally the homepage). The robots-skipped caveat from INT-2 is attached to orphan findings.
22. **IDX-8:** noindexed and canonicalized pages are excluded, as the spec says. Shared titles are their own groups. Near-duplicates use the same 0.9 estimate.
23. **IDX-9** *(approved)*:
    - A page Google reports as blocked by robots.txt is S1, added to the spec's IDX-9 states by the §2.1 definition ("cannot retrieve").
    - Any other non-PASS state, such as "URL is unknown to Google", becomes a **review item**.
    - `coverageState` is free text in the API (checked against Google's reference, 2026-09-14), so it's matched as English with `languageCode: en-US`. **Known v1 gap: this depends on Google returning English labels.** Whether `languageCode` controls `coverageState` is not documented, so for a non-English Search Console account "Crawled – currently not indexed" and similar states won't match. The failure isn't silent: an unmatched non-PASS state becomes a review item, never a pass (tested with a German label), but it loses its S1. Results based on the `indexingState` and `robotsTxtState` enums (noindex, robots.txt) are unaffected.
    - A page that is indexed but has `nosnippet` becomes an observation pointing to ACC-3.
24. **IDX-10** *(approved; endpoint still launch-gated)*:
    - **"Not indexed" cannot be determined.** Bing's documented `UrlInfo` object (GetUrlInfo) has no index-status field (checked against Microsoft's reference, 2026-09-14), so that part of IDX-10 is Not assessed.
    - Bing crawl facts are recorded as observations; a crawl HTTP error on a key page becomes a review item.
    - The JSON endpoint path (`/webmaster/api.svc/json/GetUrlInfo`) and the `{"d": …}` response wrapper are **not verified**; Microsoft's example uses the `/pox/` XML endpoint. **Enforced in code:** `bing_api_verified` defaults to False, isn't exposed as a CLI flag, and while it's False no call is made to a non-loopback Bing endpoint.

## RND decisions (reviewed)

25. *(approved)* **Third-party resources are not loaded while rendering (default).** The headless browser only loads resources from the audited origin. This keeps "don't crawl anything else" true during rendering, at a cost: a site whose JavaScript lives on a CDN will look less rendered than it is, so RND-1 **under-reports** the gap rather than inventing one. INT-3 says so on every rendered report; `--render-third-party` turns it off.
26. **Rendering safety rules**, enforced on every browser request and each tested by a deliberately broken version of the rule:
    - only GET requests leave the browser;
    - the page can't navigate away;
    - same-origin resources must be allowed by robots.txt for Maya's user agent;
    - interaction clicks only unselected tabs, collapsed sections (`aria-expanded="false"`), and "load / show / see / view / read more" or "expand" controls, never anything inside a form, at most 10 clicks, then one scroll.

    The browser identifies as `Maya-Audit` and uses a fresh context per page. Its requests go into the request log INT-4 audits. Politeness is measured between page-level requests (one render to the next), not within the burst of resources a single page load makes.
27. *(approved)* **Render sample:** the approved order (homepage → user-marked key pages ≤10 → one page per template, ≥6 slots reserved → backfill). With a small budget, the 6 template slots are reserved first, so key pages may only be rendered as template representatives or backfill.
28. **RND-1** *(thresholds approved as documented guesses, not calibrated)*:
    - A page that was rendered is compared against its raw HTML using the spec thresholds.
    - A page outside the sample is flagged "may be client-rendered" (Estimated) on 2+ raw-HTML signals, or 1 signal with under 50 raw words. The signals are: an empty framework mount node (`#root`, `#app`, `#__next`, `#__nuxt`, `#___gatsby`, `#svelte`, `#q-app`), a `<noscript>` JavaScript notice, or inline script over 10× the visible text. **These heuristic thresholds are uncalibrated.**
29. **RND-2:**
    - Declared facts are matched as case-insensitive exact text with whitespace collapsed.
    - "Only inside markup" (script data or attributes) is checked before "only after JavaScript". Raw markup is kept only for key pages.
    - A fact found nowhere becomes a **review item**.
    - Without declared facts, rendered-only headings and price patterns become an Estimated S2 candidate list.
30. **RND-3** *(thresholds approved as documented guesses, not calibrated)*:
    - Content counts as revealed at 30+ new visible words or 20%+ growth after interaction. **Both numbers are uncalibrated guesses.**
    - The raw-HTML fallback (Estimated) looks for empty `role="tabpanel"` elements or "load more" buttons outside forms. The "load more" wording is English only.
31. **RND-4:**
    - "May contain text" means a wide image (width ≥ 300 px, aspect ratio ≥ 2.5; **both uncalibrated guesses**) with missing or empty alt, judged from HTML `width`/`height` attributes only (CSS sizes are not read, and OCR is not built).
    - Iframes with a `src`, and canvases with neither fallback text nor `aria-label`, are counted when inside `<main>`/`<article>`, or anywhere if the page has neither.
    - PDF links are an observation only.
32. **RND-5:**
    - Walls are detected on Maya's own cookie-less fetch, **not a browser user-agent fetch as the spec says**. A browser-UA fetch exists only as ACC-4 probes on verified sites.
    - Redirect walls are matched by target path (`/login`, `/consent`, `/age`, `/country`, and so on); this works in any language. In-place walls need a text signature plus 200 or fewer visible words (**200 is an uncalibrated guess**). Pages whose own path is a wall path are skipped.
    - **Signatures are English only, and this is on the launch gate.** So that a Turkish or other non-English client never gets a false "no wall found", a page the signatures did not match counts as checked only when its text is English: a confident language guess says English, or the guess is inconclusive and `<html lang>` says `en`. Every other page is listed as **not assessed** in the evidence and named in the summary; if no page could be checked, RND-5's status is `not_assessed`, not `pass`. A signature match is still reported on any page.
33. **RND-6:** size is the decompressed HTML. The main-content offset is measured to `<main>`/`<article>`, else to the first `<h1>` (Estimated).
34. **RND-7:**
    - The flag is main-content share below 30% (**an uncalibrated guess**). Without `<main>`/`<article>`, the share of `<p>` text is used.
    - Pages already reported by RND-1 are left out: one report per root cause.

## STR decisions (reviewed)

35. **Linked URLs on other origins are not requested unless `--check-external-links` is on.** STR-5 (`sameAs`), STR-9 (hreflang), and STR-10 (`og:image`) need the status of URLs that are often on other sites (LinkedIn, a CDN, a ccTLD). Requesting them by default would break "don't crawl anything else", so by default they are **not assessed**, with the reason in the evidence and a count in the summary. URLs on the audited origin that the crawl didn't fetch are requested (robots.txt obeyed, at most 50). When the flag is on, each other origin's robots.txt is fetched first and obeyed, at most 20 URLs are requested with Maya's user agent, and INT-4 audits those requests like any other (tested from the other server's side). The flag counts as the operator's permission for these status requests; `--allow-live-host` is not required for each linked host. *Amended by decision 211 (2026-10-14): these status requests are on by default, `--no-external-links` turns them off, and other links to other sites are asked too, within one cap.*
36. **Which pages STR looks at.** Indexable pages only: readable HTML, no noindex, and a canonical that is absent or points to itself. Everything is judged on the raw HTML. **Root cause once:** pages RND-1 reports as client-rendered (S2/S3) are left out of STR-2, STR-4, STR-6's visible dates, STR-7, and STR-8; banner-shaped images RND-4 reports are left out of STR-7; generic titles are not also counted as duplicates; the homepage's missing Organization schema is reported by STR-3 only (STR-5's evidence points there); dates STR-4 already reported as conflicting are not compared again by STR-6.
37. **STR-1:** the homepage may be titled with the site name alone; any other page titled only with the site name (from `og:site_name` or the Organization name) is generic. The placeholder list ("Home", "Untitled", "React App", …) is **English plus framework defaults**. Title length is not checked (spec §7).
38. **STR-2:** "long" is more than 800 words of `<main>`/`<article>` text, or of all visible text when those elements are missing. "No subheadings" means no `<h2>`–`<h6>`. Whether the `<h1>` matches the page topic is **not measured**. Question headings are those ending in `?` (also `؟`, `？`).
39. **STR-3:**
    - Organization means `Organization` or one of 23 common subtypes. The list is not exhaustive (LocalBusiness alone has hundreds of subtypes), so an unusual subtype would be reported as missing; `types_seen` in the evidence shows what was there.
    - **Required properties** follow Google's docs, checked 2026-09-14: Product needs `name` and one of `offers`/`review`/`aggregateRating`; Offer needs `price`; AggregateOffer `lowPrice` and `priceCurrency`; AggregateRating `ratingValue`, `ratingCount` or `reviewCount`, and `itemReviewed` unless nested; Review `author`, `reviewRating`, and `itemReviewed` unless nested; BreadcrumbList items need `position`, `name`, and `item` (except the last). Article and Organization have no required properties per Google. **Missing required properties are Info**: the spec measures them but sets no severity, and Google's consequence is "not eligible for rich results", not "ignored".
    - Expected type by page kind (Info, Estimated) is guessed from the URL path and `og:type` only, never from the structured data being checked: `/products/…` or `og:type=product` → Product; a path ending in `/pricing` or `/plans` → Product, Offer, or SoftwareApplication; `/faq` → FAQPage; `/blog/…`, `/news/…` or `og:type=article` → an Article type. The path words are English. **BreadcrumbList and LocalBusiness are not expected on any page kind** (too noisy to guess). *Amended by decision 229 (2026-10-15): Turkish path words, a product page told by its own price and a buy button, 38 Organization types, and a page typed Restaurant or CollectionPage is not an article by og:type alone.*
    - RDFa types are read, and simple `property` values too, but RDFa has had less testing than JSON-LD and Microdata.
40. **STR-4 comparison rules:**
    - **Conflict** means both values exist and differ. **A structured-data value that is not shown on the page at all becomes a review item, not a finding**: the spec defines severities for conflicts only, and a missing value may be shown as an image or be stale.
    - Price: the markup value must equal a price shown next to a currency marker (`$`, `€`, `₺`, `TL`, ISO codes, …); both `1,299.00` and `1.299,00` are read. Verified. Currency: compared only for the matched prices; `$` counts as any dollar currency. Verified.
    - Availability: `InStock`-type markup vs "sold out / out of stock" wording and the reverse. **English wording only, so it's Estimated, and on non-English pages it is not assessed.** S2 per the spec.
    - Rating: `ratingValue` vs a shown `x/5` or "x out of 5" on the same scale (±0.05). Verified.
    - Dates: a markup date conflicts with a visible date **labeled** the same way (published/updated, or `itemprop`) when they are more than 1 day apart (Verified). If no visible date is labeled, it conflicts only when neither markup date matches any visible date (Estimated).
    - Product name and author: normalized text containment; otherwise product name vs title and `<h1>` word overlap below 50%, and author vs an English "By Name" byline. Estimated. **No LLM comparison is built (no T4 cost).**
41. **STR-5:**
    - Name variants come from the Organization `name`, `og:site_name`, the homepage footer's © line, the homepage logo's alt text, and repeated title prefixes/suffixes. A title segment counts only if it is the most common one or matches another source word for word, so "Pricing" in "Pricing | Acme" isn't taken for a brand.
    - Variants are compared after removing case, punctuation, a trailing "logo", and legal suffixes (Inc, LLC, GmbH, A.Ş., …). Names declared in Organization `alternateName` or `legalName` are shown but not counted. More than 2 remaining variants is S4 (Estimated).
    - Dead `sameAs` means 404 or 410. Other statuses (403, 999, redirects to a login page) are listed as inconclusive, not findings.
42. **STR-6:**
    - Signals per page: markup `datePublished`/`dateModified`, visible dates (from `<time>` and text), sitemap `<lastmod>`, and the `Last-Modified` header. **A `Last-Modified` within 5 minutes of the request time is treated as generated per request**: it isn't compared, and it's counted in an observation.
    - Conflict (S4) means last-modified signals more than 30 days apart, or one of them more than 30 days before the publication date.
    - **Future-dated (S4, not in the spec's severity line)** means a markup, sitemap, header, or labeled visible date more than 1 day after the fetch. Unlabeled visible dates (events, deadlines) are ignored.
    - **Auto-stamped (S4)** means at least 5 pages carry the sitemap `<lastmod>` or markup `dateModified`, and at least 90% of them are dated the audit day (±1 day). **Both thresholds are uncalibrated guesses.** An auto-stamped signal is left out of the conflict comparison.
    - Visible dates: ISO and `d.m.yyyy` formats are read in any language; month names and "Published/Updated" labels are **English only**. "No visible date" on an article-type page (Info) is therefore **not assessed on non-English pages**, which are listed in the evidence.
43. **STR-7:** main content is `<main>`/`<article>`, or everything outside nav/header/footer/aside when neither exists. The missing attribute is Verified. **"Meaningful" is an Estimated guess**: declared width or height of at least 150 px, inside a `<figure>`, or a file name hinting at a chart, diagram, screenshot, product, or photo means S4. 48 px or less, or icon/sprite/spacer names, count as decorative (Info). No size and no hint also goes to Info. `alt=""` is accepted as decorative.
44. **STR-8:** a `<div>` "table" is a container with repeated rows of the same shape: at least 2 rows, 2 cells per row, and 6 cells in total; cells under 60 characters (40 on average); no list or table inside; not in nav/header/footer/aside. **All of these numbers are uncalibrated guesses.** "Pricing or spec comparison" (S4) means prices in the cells or a URL path like `/pricing`, `/plans`, `/compare`, `/specs`, `-vs-`; any other grid is Info. Runs of 3+ numbered paragraphs are recorded as an observation (no severity).
45. **STR-9:**
    - Mismatched `lang` (S4, Estimated) is reported only when the stopword language guess is confident (50+ words, 8+ stopwords, twice the runner-up) and the declared language is one of the 8 it covers (en, tr, de, fr, es, it, pt, nl). Other declared languages are listed as not assessed.
    - A missing or malformed `<html lang>`, malformed hreflang codes, and relative hreflang URLs are **Info**: the spec measures them but gives severities only to mismatch, non-reciprocal, and non-200.
    - A hreflang target that redirects counts as non-200. Reciprocity requires the target page to link back to the exact source URL. A non-200 target isn't also reported as non-reciprocal. Only HTML `<link>` annotations are read (HTTP-header and sitemap hreflang are not built).
46. **STR-10:** a dead `og:image` means 404 or 410. Other statuses are inconclusive. Missing `og:title`, `og:description`, `og:image`, or meta description is one Info finding per tag.
47. *(all STR decisions approved as built)* **RND-5's English guard uses the same language helper** (`language.py`) as STR-4, STR-6, and STR-9. The guard trusts a confident content guess over the declared `lang`, because templates often ship `lang="en"` on translated pages.

## PRF decisions (reviewed)

48. **Sampling and rounds.** PRF samples up to 30 URLs: the homepage, key pages (up to 10), one page per template (up to 6), and every URL that failed during the crawl (so it's tested again). The crawl fetch is attempt 1. After all other post-crawl collection (so it's already spaced from the crawl), 2 extra rounds run 30 s apart, giving each sampled URL 3 attempts (4 for URLs IDX-1 refetched). The spec says "spaced over the crawl"; the rounds run after it instead, so the crawler stays simple. Every attempt's timestamp is in the evidence. For a 30-URL sample, the cost is about 60 extra requests plus 30 s, more if pages are slow or time out.
49. **One attempt history for IDX-1, PRF-1, and PRF-2.** `perf_data.attempts_by_url` merges the crawl fetch, the IDX-1 refetch, and the PRF rounds. IDX-1's "fails on every attempt" (S1) uses all of them, so a page that failed on the crawl and the refetch but worked in a PRF round is **not** an S1 (tested). Blocked and rate-limited answers (INT-1's) count neither as success nor failure.
50. **PRF-1:**
    - The 1.5 s rule is applied to the **total** time (request sent to last byte), because a live fetcher needs the whole document. TTFB (request sent to response headers) is reported beside it. Both include connection setup when a new connection was opened; Maya's politeness wait is excluded.
    - A URL is judged slow only with 3 successful 2xx samples (the median). With 3 samples, p90 is the slowest sample. Fewer samples means that URL is listed as "not enough samples".
    - An intermittent timeout means at least one timeout and at least one success for the same URL (Verified). All attempts timing out is IDX-1's.
    - **The egress region is whatever the operator passes with `--egress-region`.** Maya doesn't look up its own IP, since that would mean calling an outside service.
51. **PRF-2:**
    - Failure means a transport error or a 5xx. 4xx is not a reliability failure.
    - A URL is reported when it failed at least once and worked at least once, and at least one failure was not a timeout. Timeout-only URLs are PRF-1's; URLs that failed every time are IDX-1's and are left out of the rate as well (one report per root cause).
    - **The sitewide rate (>5%, spec) is only judged from 20 or more counted attempts. 20 is an uncalibrated guess, not from the spec;** below it, the rate is an observation. Timeouts count toward the rate.
    - If the extra rounds didn't run (`--no-prf`, or the crawl was rate-limited), PRF-1 and PRF-2 are **not assessed** rather than passed, unless crawl and refetch attempts alone already show a finding.
52. **No extra requests to a site that rate-limited Maya.** If the crawl stopped because of rate limiting, no PRF round runs. If a PRF request gets a 429, the rounds stop.
53. **PRF-3 (optional, T2, off by default):**
    - **Field data comes from the CrUX API, not from the PSI response's `loadingExperience`.** Google's PSI docs say PSI's real-world data component is being discontinued, and they recommend the CrUX API. Metrics: LCP, INP, and CLS at p75, plus TTFB p75 (shown with PRF-1). If the URL has no record, the origin's record is used, labeled `scope: origin`.
    - **Lab data:** PSI `runPagespeed` with strategy mobile and category PERFORMANCE, 3 runs per key page (up to 5 pages; the homepage when no key page is set). The median of LCP, CLS, TBT, and TTFB (`server-response-time`) is shown with its run count, labeled Estimated.
    - **Lab runs require verified ownership**, because they make Google's servers load the site with a Lighthouse user agent, not Maya-Audit, so robots.txt for Maya doesn't govern them. CrUX is a lookup of aggregate data and touches nothing on the site.
    - **Category scores are never read.** Only `lighthouseVersion`, `fetchTime`, `finalUrl`, `runtimeError`, and the four audits' `numericValue` are extracted; `categories` is never touched (a test fails if the fake API's score appears anywhere in the report).
    - Findings are **Info** only: one per metric where the field p75 is in Google's published "poor" range (LCP > 4000 ms, INP > 500 ms, CLS > 0.25). Lab values are observations with no finding.
    - The API key is read from the environment only and redacted from the report, including from any API error text.
    - Lighthouse CLI self-hosted (T1) and DataForSEO (T4) are not built.

## ANS decisions (reviewed)

54. **Citation records come from a file, not from an API call here.** `--citations FILE.json` takes records produced upstream (Maya's prompt tracking or a paid API), so this build makes no metered call: the T4 cost is paid where the records are made. The file is operator input and is validated, never trusted: a record without a usable `engine` and `url` is listed under `invalid_records` with the reason, and a malformed file makes the panel Not assessed instead of crashing the audit. **The record shape is Maya's assumed format (spec §8 Q7: engine, model, citedAt, no locale); confirm it against the real database before wiring it up.**
55. **The panel is separate in every output.** In the text report ANS results are printed under their own header, after the site checks and their priority order, with their own panel order. In the JSON they are under `answer_engine_panel`, not `checks`, and their finding ids never appear in `findings_in_priority_order`. A test re-runs every site check from the same crawl and compares, so the panel provably changes nothing (mutation-tested).
56. **ANS-1 severity comes from the check that reports the failure**, not from any finding that happens to name the same URL: robots blocks from ACC-2, noindex from ACC-3/IDX-4, status from IDX-1, raw-HTML gaps from RND-1, walls from RND-5, edge blocking from ACC-4. Other findings on that URL are still listed, under `other_site_findings_for_this_url`.
57. **Cited URLs the crawl never reached are fetched once each** (robots.txt obeyed, cap 50, purpose `ans_cited_url` in the request log). When no site check covers such a URL, ANS-1 applies the site checks' own severity from the spec's §6 table (5xx/transport S1, unreferenced 4xx Info, noindex S1, robots-disallowed search S1 / live S3 / training S4, canonicalized away S2) and says so in a note. **Cited URLs on other sites are recorded and never fetched**, the same rule as STR's off-site links, and they are not covered by `--check-external-links`.
58. **ANS-2 claim extraction is upstream (T4).** When a record carries `claims` (extracted from the answer by an LLM in Maya's pipeline), they are compared to the cited page. When it does not, Maya reads prices out of `answer_excerpt` with the same T0 tokenizer the STR checks use, and every such row is labeled `derived_by_maya`. **No LLM runs here.** Price claims are compared as numbers; any other claim is compared by text containment, so a paraphrase on the page reads as "not found" — the note says so and asks for human confirmation.
59. **ANS-2 quotes one line of the page, not a run-on string.** The analyzer keeps text nodes separately so the answer sentence and the page sentence can be shown side by side as the spec asks.
60. **ANS-3 is reported, not hidden.** It appears in the panel with status Not assessed and the reason it was cut from v1, so a reader sees it was considered and why.
61. **Failure order in the panel:** transport error, 5xx, robots-disallowed (search), noindex, 4xx, canonicalized away, raw-HTML gap, wall, edge block, robots-disallowed (live, then training), redirect, not fetched. Within a failure type, most recently cited first.

## Live-run decisions (reviewed)

62. **Key pages are seeded into the crawl queue.** `--key-page` used to affect only sampling and sort
    order, so a key page outside the page cap was never fetched at all: the first client audit marked
    five key pages and four were never crawled. They are now queued right after the start URL, marked
    `discovered_via: "key_page"`, and are otherwise ordinary fetches — robots.txt is still obeyed, the
    politeness delay still applies, and they count toward the page cap.

## Appendix: ACC-5 log formats: what is and is not supported

**ACC-5 does not work with server logs in general.** It reads exactly two formats:

| `--access-log-format` | What it reads | What was checked, and against what |
|---|---|---|
| `combined` (default) | nginx's predefined `combined` log format | Layout checked against nginx.org docs (2026-09-14). Apache's `combined` uses the same layout but was **not** re-checked. |
| `cloudflare_logpush` | **Cloudflare Logpush `http_requests` only**, one JSON object per line | The five fields used (`ClientIP`, `EdgeStartTimestamp`, `ClientRequestURI`, `EdgeResponseStatus`, `ClientRequestUserAgent`) and all three `timestamp_format` options (`unixnano` default, `unix`, `rfc3339`) were checked against Cloudflare's field and Logpush docs (2026-09-14). The **one-object-per-line record layout was not confirmed** on the pages checked. |

Other CDNs (Fastly, Vercel, Akamai, CloudFront) and custom JSON logs are **not supported**. An unknown
format is refused rather than guessed. IP-range files must be local; the JSON layout follows Google's and
OpenAI's published files, and other vendors' layouts were not checked.

## Appendix: the CrUX deprecation (PRF-3)

**What will break.** PRF-3's real-user (field) data comes from the CrUX API (`chromeuxreport.googleapis.com`,
`records:queryRecord`). Google's PageSpeed Insights docs say the real-world data in the **PSI** response is being
discontinued and point to the CrUX API instead, which is why this build calls CrUX directly. If Google later
retires or restricts the CrUX API itself, PRF-3's field half stops returning records.

**What it looks like when it happens.** Not a crash, and not a silent zero:
- a non-200 from `records:queryRecord` (today a missing record is a 404, which is also the normal "not enough
  traffic" answer, so the two are indistinguishable from the status alone);
- `perf_data._crux` then records the attempts and returns no `p75`;
- PRF-3 prints `assessed: False, reason: no CrUX record for the URL or its origin` with the HTTP statuses, and
  PRF-1 loses its `crux_field_ttfb_p75` line. No Info finding can fire, because those come only from field p75
  values.

**What to watch for.** A sudden jump in that "no CrUX record" reason across sites that used to return data
(especially high-traffic origins, where "not enough traffic" is not a plausible explanation), or a 403/404 on
every request including the origin fallback.

**The fallback when it is really gone.** Ship PRF-3 as **lab-only**, and say so in the report rather than
leaving an empty panel:
1. Keep the PSI lab runs exactly as they are (3 runs per key page, median of LCP/CLS/TBT/TTFB, ownership-verified
   sites only, no category scores).
2. Make the field half report Not assessed with the reason "CrUX API withdrawn", not "no data for this URL".
3. **Drop the Info findings.** They are defined on field p75 against Google's published thresholds; lab values are
   Estimated single-environment runs and must not be compared to those thresholds. Lab data stays observations
   with no severity.
4. Tell PRF-1 that `crux_field_ttfb_p75` is gone; its own measured TTFB is unaffected and needs no fallback.
5. Do not substitute a paid provider (for example DataForSEO Lighthouse) without a fresh review: the spec
   (§7) rejects that route while free ones exist, and it would move PRF-3 from T2 to T4.

If instead Google only removes field data from the **PSI** response and keeps the CrUX API, nothing here changes:
this build already avoids `loadingExperience`.

## ANS-4 / ANS-5 decisions (cited-domain panel)

63. **Nothing this tool computes is called Share of Voice.** Maya's product already has one: `compare_competitors`
    counts brand mentions in answer text across a curated competitor set. The cited-domain export counts cited
    source domains, including image CDNs and reference sites. On Moodist the two read 35.9% and 7.3% — both
    correct, measuring different things. Two conflicting numbers under one name inside one company's tooling is
    worse than no number, so every ANS-4/ANS-5 result carries a disclaimer field, a test asserts no metric is
    *named* share of voice, and a mutation proves that test bites.
64. **A truncated export yields no per-engine share.** The export carries `totalMentions` and `page.total` for
    every domain, so a site-level share has an honest denominator. It carries no per-engine totals, so summing
    the listed rows would divide by a fraction of reality and overstate the site on every engine. ANS-4 reports
    the site's own per-engine counts (exact, from its own row) and states why the share is absent.
    `engine_totals_complete` gates this in one place rather than at each use.
65. **No row for the site is Not assessed, not "zero citations."** A truncated export can omit a site that is in
    fact cited. Reporting that as absence from AI answers would be the worst false positive this panel could
    produce.
66. **ANS-5 produces observations, no findings.** The spec sets no threshold for "too much of your presence is on
    someone else's page," and inventing one would be a composite score wearing a different hat (§2). The rows are
    reported so a reader can judge them.
67. **ANS-4's only finding is Info, and Hypothesis.** An engine citing a topic and never this site has causes the
    tool cannot see — most obviously that the engine does not cover the language or market. When ACC-2 or ACC-6
    already reports that engine's crawler as disallowed, ANS-4 links to that finding rather than re-reporting the
    block (one report per root cause). Flagged LG-30 until confirmed against a known cause.
68. **Third-party domains named in the export are never fetched.** The export names competitors, CDNs and social
    profiles. Crawling them would put Maya's crawler on sites that never consented and that the live-host guard
    was written to keep it off. A test asserts every request stays on the audited origin.
69. **The cited-domain reader is a separate module and a separate flag.** `--citations` and `--citation-domains`
    carry different shapes for different questions. Merging them would mean one loader guessing which it got,
    and a wrong guess failing silently.
70. **`registrable_domain()` shares its suffix tables with `is_registrable_domain()`.** Site matching must agree
    with TLS and origin logic about where a site's boundary is. Written after a `lstrip("www.")` in the first
    draft turned `www.web.com` into `eb.com`; a mutation test now pins it.

### On open-seo as a source

71. **No AEO heuristic was ported from open-seo, because it has none.** `brandLookup.ts`, `citedSources.ts`,
    `shareOfVoice.ts` and `promptExplorer.ts` are an orchestration and shaping layer over DataForSEO's LLM
    Mentions API (83 server files reference DataForSEO); `src/server/mcp/` is OAuth and transport; the
    `.agents/skills/` files are report-writing prompts. Grepping `src/` for RAG parsing, entity density, semantic
    density, citation readiness or context-window weight returns nothing. The repo is MIT (Ben Senescu, 2026), so
    porting would have been permitted — there was simply nothing of that kind to port.
72. **What was taken is the share-of-voice *discipline*, not the metric:** seed every requested row so a missing
    one reads as "no data" instead of vanishing, keep null and zero apart, and cap per platform so a big engine
    cannot crowd out a small one. Those shapes come from `shareOfVoice.ts` and `citedSources.ts`. No open-seo code
    is copied verbatim; if any is later, its MIT notice travels with it.

## AI skill library decisions (`maya_audit/ai_skills/`)

73. **The prompts live beside the audit, not inside the report.** `build_report` is unchanged and
    `build_llm_brief` is a separate call with its own file. The report is the evidence file — what a
    finding cites, what gets diffed between runs, what someone re-reads in a year. Prompt text is
    instructions to a model, larger than the findings it wraps, and rewritten whenever the wording
    improves. Mixed together, every report diff fills with prose edits and a reader loses the line
    between measured evidence and instructions about how to describe it. A test asserts the report
    carries no prompt text.
74. **The brief carries an analysis payload, not the report.** A real 50-page report is 5.3 MB, of
    which 5.17 MB is `crawl` — page bodies, every discovered URL, every sitemap lastmod. None of it
    is evidence a finding cites, because each finding already quotes what it rests on. The payload
    is the report minus `crawl`, plus the method detail the report's own Method section needs:
    0.16 MB, about 40k tokens. Inlining the untrimmed report four times would have produced a 21 MB
    brief no model could read.
75. **The payload is embedded once and the prompts point at it.** `inline=True` renders one
    self-contained prompt when someone wants to paste a single thing into a model.
76. **A skill whose data is missing is not rendered.** It is returned with `prompt: null` and the
    missing keys named. Rendering it against empty placeholders would produce a document with an
    empty section, and an empty section reads as "nothing to report" — the same mistake as showing a
    `not_assessed` check as a pass.
77. **The evidence rules travel with every prompt.** The audit spends its whole design budget on not
    overstating what it knows; a model writing prose can undo that in one paragraph. "Not assessed is
    never fine", severity kept apart from confidence, and no invented scores are repeated in each
    prompt rather than left implied. Mutations prove the tests bite when any of them is removed.
78. **Four skills, not the eight OpenSEO ships.** `seo-audit` and `seo-coach` map onto this data
    directly. `competitor-analysis` became a cited-domain landscape: Maya never crawls a competitor,
    so every claim about a rival's pages or strategy is invention, and the prompt says so. The rest —
    `keyword-research`, `link-prospecting`, `local-seo`, `competitive-landscape`, `seo-project-setup`
    — need keyword volume, backlink and SERP data this tool does not collect, and porting them would
    have produced prompts asking a model to analyse fields that do not exist.
79. **`keyword-clustering` had no counterpart and was not faked.** There are no keywords in this
    audit. What ported is its reasoning — group by intent not surface similarity, do not over-group a
    small set, label the unconfirmed as proposed, watch for two pages competing for one intent —
    applied to the only grouping the data supports: cited URLs and the prompts behind them. Because
    Maya's export usually carries a `promptId` and no prompt text, that prompt forbids naming a topic
    from a URL and presenting it as the question a user asked.
80. **Nothing in this package calls a model.** A brief is a prompt plus a payload, handed to whatever
    model the caller chooses. An audit that called a model mid-run would stop being reproducible, and
    the integrity gates could no longer say whether a result came from the site or from a guess.

## Adaptive backoff (ported from OpenSEO's crawl throttle)

81. **A rate limit widens the gap for the rest of the crawl, not just once.** Maya used to honour a
    short `Retry-After`, sleep, and then resume at the configured pace — the same pace the site had
    just refused. The gap now grows by `rate_limit_backoff_factor` on every rate-limited page and is
    never narrowed again. A site saying "slow down" is telling us something about the whole crawl.
82. **Widening only ever increases the gap, which is why it is safe inside a politeness-audited
    crawl.** INT-4 asserts the smallest observed gap is at least the configured delay; a gap that
    only grows cannot break that invariant. This is the reason backoff needed no change to the gate's
    logic, only to its evidence. *Amended by 219 part 2 (2026-10-15, owner): on a fast, error-free site the audited
    site's gap may narrow to 0.5 s (never below Crawl-delay), and INT-4 judges against the floor in use, per host.*
83. **The widening is reported in INT-4's evidence** (`configured_delay_s`, `final_delay_s`,
    `widened_after_rate_limit`). Politeness is the thing INT-4 exists to audit; a backoff it cannot
    see is a backoff nobody can check, and a reader should not have to infer it from elapsed time.
84. **A cumulative cooldown budget stops the crawl** (`max_total_cooldown_s`, default 30 min). The
    existing guards catch a single long `Retry-After` and a run of consecutive refusals, but not a
    site that refuses politely and relentlessly — every page, one second at a time. Past the budget
    the site has spent long enough saying no that continuing is not a judgment call.
85. **What was not taken from OpenSEO's throttle:** its checkpoint/resume machinery, which exists
    because their crawl runs as a resumable Cloudflare workflow across steps. Maya's crawl is one
    process with a time limit, so the state lives in the `Fetcher` and dies with the run.

### OpenSEO pieces adapted and left out of Maya

86. **Their audit engine detects 30 classic technical-SEO issues** (`src/shared/audit-issues.ts`)
    graded `critical` / `warning` / `info`, with no confidence, no rationale, and no "not assessed".
    Maya's 49 checks now cover the overlapping status, redirect, broken-link, metadata, heading, image,
    and timing areas under a stricter evidence model. TSEO-1 adds title/description length bands and
    heading-order observations as S4 hypotheses, not as ranking facts. `no-outgoing-links` stays out:
    its rationale is link equity, and Maya does not claim a missing link is evidence of a technical
    failure. Missing checks were not copied just to match OpenSEO's issue list.
87. **Their `page-analyzer.ts` (261 lines) is narrower than Maya's `analysis.py`.** It extracts
    title, meta, headings, links and word counts. Maya's analyzer already produces all of that plus
    structured data with parse errors, text blocks, time elements, tables, div grids and logo alts.
88. **`url-policy.ts` and `discovery.ts` duplicate `urls.py` and `sitemap.py`** without covering a
    case Maya misses. Maya's is the more careful of the two on registrable domains and multi-label
    suffixes, which live-run defect 1 forced it to get right.

## The SQLite frontier and resumable crawls

89. **The frontier is SQLite, defaulting to `:memory:`.** A crawl with no `--db-path` behaves
    exactly as it did when the frontier was a `deque` and a `set` — one code path, not two. A path is
    what makes the frontier outlive the process, and `--resume` is what continues it.
90. **`INSERT OR IGNORE` on the URL primary key is the seen-set.** There is no separate visited set
    to fall out of step with the queue, and a URL already crawled cannot be resurrected by a later
    link to it. A mutation proves the test bites if this becomes `INSERT OR REPLACE`.
91. **Claiming a URL is not completing it.** `get_next_url` stamps the session and leaves the row
    `queued`; only the fetch outcome writes a terminal status. A process killed mid-fetch therefore
    leaves that URL claimable by the next session rather than silently lost.
92. **Traversal order is preserved in SQL, not approximated.** `priority` reproduces the old
    `appendleft` for redirect targets and the rule that sitemap URLs are drained only once links run
    out; `seq` keeps discovery order within a priority. Redirects get a negative `seq` so the most
    recent one sorts first, as `appendleft` did.
93. **Reopening a frontier without `--resume` is refused, not overwritten.** Silently starting fresh
    over a saved frontier destroys the only thing `--resume` needs.

### What a resumed crawl is allowed to claim

94. **Politeness is judged per session, and INT-4 says so.** "All N requests used one user agent,
    robots.txt was fetched first, the smallest gap was X" is true of a session, not of an assembled
    crawl. INT-4 measures the session it ran in and lists each earlier session's own figures, so
    nothing implies this run's compliance covers requests it never made.
95. **INT-2 leads with the assembly.** A resumed crawl's reasons begin "assembled from N sessions
    between A and B; pages were not all seen at the same moment". Every finding that compares two
    pages — IDX-4 canonical targets, IDX-8 duplicates, STR-4 date conflicts — is comparing across
    that gap, and a reader deciding how much to trust the crawl needs that before the findings.
96. **Each session re-fetches robots.txt, and a change between sessions is recorded.** The policy is
    hashed per session; differing hashes set `robots_changed_between_sessions`. A queue built under
    the old policy may hold URLs the new one disallows, and inheriting it silently would break the
    one promise the crawler makes unconditionally.
97. **The backoff delay is inherited across a resume.** Without this, a site that rate-limited Maya
    yesterday is met at full speed today and the backoff that session earned is undone — which would
    have made resumption a politeness regression rather than a feature.
98. **What was not taken from OpenSEO's scratchpad:** the Durable Object, the 7-day cleanup alarm,
    the chunk-claim/retry protocol and the `page_links`/`page_mirror` mirrors. Those exist because
    their crawl is a resumable Cloudflare Workflow billed per row written and capped at ~1MiB per
    step output. Maya's crawl is one process, and its link and page data already live on the result.

## Evidence integrity, report 0.4 (Phase 1 of v2; approved 2026-09-22)

The reconnaissance behind these is [`PHASE-0-RECONNAISSANCE.md`](PHASE-0-RECONNAISSANCE.md).

99. **`pass` means every part of the check's question was assessed; otherwise it is `partial`.** The
    first client audits passed STR-4 "values match on 46 pages" with 40+ date comparisons not
    assessed, RND-5 on one page of 48, and STR-5 with every sameAs link unfetched. Each check now
    carries `coverage.not_assessed` (part, count, reason), and `CheckResult` itself turns a `pass`
    with any such part into `partial`, so no check can forget to. A compatible alternative (coverage
    data under the old statuses) was rejected on purpose: it would have let `pass` keep meaning two
    things. Findings stay `findings`; their coverage block still says what was not looked at.
100. **`observed` is for checks with no pass condition.** ANS-5 only measures, and so does ANS-1
    when the data holds zero citations of this site. Calling either `pass` implied a judgement that
    was never made.
101. **Coverage is derived from each check's recorded evidence, in one module** (`coverage.py`).
    The same function upgrades a saved 0.3 report (`migrate-report`), so a live run and a migrated
    report cannot disagree about what `partial` means (tested by migrating the 0.3 view of a live
    run). A part is listed only where the check's own question went unanswered; the spec's own
    sampling (ACC-2's URL sample, PRF's sample) is scope, not a gap. Evidence lists capped for size now
    come with exact `*_count` keys; a count read from a capped list is marked a lower bound.
102. **An ACC-4 difference seen once and never retried is Estimated, at the same severity.** The
    probe cap can stop retries; a single differing response may be transient (spec ACC-4 step 5).
    It is reported apart, titled "seen once, not retried", with `confirmed_by_retries: false`.
    Severity is unchanged because an estimate is never discounted (§2.2).
103. **An STR-4 price conflict is Verified only when the page shows one price.** "None of the shown
    prices equals the markup price" is always Verified, but with several prices (other plans,
    related products) which one belongs to this offer is an assumption, so the conflict is Inferred
    and the note names the assumption. Severity stays S2.
104. **RND-3's English-only "load more" fallback does not pass non-English pages.** As RND-5 already
    did: an unrendered page whose language is not English (or unknown) is listed as not assessed for
    that heuristic. Tab panels are language independent and are still checked.
105. **ANS-1: incomplete input is not "zero citations", and a URL Maya did not fetch is not a failing
    page.** A paged export (`hasMore`, or fewer rows returned than exist) or one whose every record
    is invalid makes an empty result `not_assessed` (decision 65, now applied to ANS-1 too). A cited
    URL left unfetched by the cap or robots.txt used to be a "failing" Info finding; it is now a
    coverage gap listed under `cited_urls_not_checked`, unless a robots.txt block for an AI bot
    makes it a finding in its own right. Canonicals are read from the HTML and then the `Link`
    header, as IDX-4 reads them.
106. **The severity scale a model is taught is built from the spec's definitions.**
    `ai_skills/rules.py` had called "content exists but the engine cannot see it" S3, which is S2 by
    §2.1 (RND-1), and redefined S2 around canonicals. `findings.SEVERITY_DEFINITIONS` is now the one
    source; the ladder and the status meanings are generated from it, and a test checks it against
    the §2.1 table in the spec itself. The prompts now say a `partial` is a gap, never "what is
    working".
107. **Registry facts carry provenance per field, derived, never upgraded.** `BotEntry.provenance()`
    reports identity, role, robots, user-agent and IP sources and a verification status, computed
    only from what the row already records. A row is `verified` only with no launch-gate reason left.
    ACC-2 and ACC-4 findings include it as `bot_provenance`. The possible official Anthropic page
    (LG-04) was noted and deliberately not used to upgrade anything until someone reads it.

## Highest-value AEO checks (Phase 2 of v2; approved 2026-09-22)

108. **ACC-4 judges "same" on visible text, not bytes, and names what differed.** Markup noise (nonces,
    CSRF tokens, build ids) changes the body hash on every request, so the visible-text hash decides
    "same"; the same title with estimated text similarity below the IDX-4 threshold is
    `different_content`. Every attempt records status, Location, content type, bytes, visible-text
    hash and word count, and a non-`same` pair carries a word-level text delta.
109. **A 4xx/5xx the bot gets while the browser gets 2xx is `blocked`.** *(Severity change confirmed by the owner, 2026-09-22.)* Whatever the reason, the bot
    cannot retrieve the page, which is §2.1's S1 (search) / S2 (live) case. It used to be a review item.
    A bot-only redirect is a new outcome, `redirected`: a review item, because where it lands may be a
    block page or a harmless locale redirect, and the Location is shown.
110. **The browser baseline is re-taken before every ACC-4 retry.** A page that changed between two
    loads (a deploy, rotating content) used to be read as the bot being served different content.
    Each retry is judged against a fresh browser response; re-baselines cost probe requests and count
    against the cap.
111. **RND-1 quotes the gap.** For every page with a missing or partial gap, `content_delta` lists the
    rendered text blocks absent from the raw HTML (three or more words, or any digit, so a short fact
    like "Pro plan $49/mo" is kept and a "Menu" label is not), whether each sits in raw `<noscript>`
    or raw markup, and the XHR/fetch requests made while rendering. Requests are listed, not matched to
    blocks: which one supplied which text is not determined. CSS is not read, so hidden text counts as
    text in both views.
112. **RND-3 has a no-click control.** The page is left alone for `render_control_wait_ms` (1000 ms,
    policy) before clicking, and the same wait follows the clicks. Only text beyond the control is
    credited to interaction; text that appeared with no click is an observation (late loading).
113. **ANS-1 follows a cited URL's redirect or canonical to where it lands.** A hand-off to a live,
    indexable page (for a canonical, with the same visible text) is *consolidated*, not a failure. A
    hand-off to an error or noindexed page, or a canonical to different content, is a failure at the
    site checks' own severity (IDX-1 decision 15, ACC-3, IDX-4). A hop that was not fetched is
    *unresolved* and listed in coverage, so decision 56's "take the lower severity" is no longer
    needed where the target can be fetched. Targets share `ans_max_fetches` with cited URLs. Healthy
    URLs list the checks applied, and ACC-4 not having probed a cited URL is a coverage gap
    ("Firewall blocking was not assessed", §8 F4).
114. **ANS-2 separates contradicted from absent.** *(Severity change confirmed by the owner, 2026-09-22.)* Only a page stating a different value is a
    contradiction (a finding). A claim the page does not state is a review item: it may be
    paraphrased, sourced elsewhere, or dropped. Prices and numbers are compared deterministically
    against the page sentence that shares the claim's words (at least two words of four or more
    letters, or all of them if fewer). A comparison supplied upstream is used as given and labelled
    model-assisted; Maya still runs no model. If the raw HTML lacks a claim, the rendered view is used
    and the row says so.
115. **STR-11 (new): structured data that contradicts itself.** Two top-level descriptions of one
    entity on one page (same `@id`: Verified; same type family and name: Inferred) that give
    non-overlapping price, currency, availability, dates, or (same `@id`) name. S2 for price, currency
    and availability, as STR-4; S3 otherwise. A field STR-4 already reports on the same page is left
    to STR-4. An unparseable JSON-LD block is a coverage gap. Cross-page `@id` comparison is left to
    Phase 3.

## Entity, freshness and structure (Phase 3 of v2; 2026-09-22)

116. **The Last-Modified header can be auto-stamped, and then it is not compared.** On two real clients
    (Midas and Moodist, 2026-09-17) every page's `Last-Modified` was set by a page cache or CDN 0-73
    minutes before Maya's request, beside sitemap and schema dates months older. The 5-minute
    "generated per request" rule caught only some of them, so STR-6 reported 5 and 3 page "conflicts"
    that were one sitewide cause — on Moodist, pages whose schema and sitemap dates agreed with each
    other. The header now joins the auto-stamp detection (per-request headers count toward the
    pattern, since they are the same pattern), is reported once, sitewide, and is left out of the
    per-page comparison. Replayed on the saved reports: Midas 5 → 0 conflicts (44/44 headers dated
    the audit day), Moodist 3 → 0 (46/46).
117. **One identical non-today date on nearly every page is a stamp too** (a template or migration
    date), with the same thresholds. For the sitemap this stays IDX-5's finding; STR-6 only leaves it
    out of the comparison.
118. **STR-6's judgement is a pure function (`judge_dates`)** over per-page rows, so a saved report's
    evidence can be re-judged without re-crawling, as Phase 2 did for ANS-1.
119. **IDX-5 records `lastmod` statistics per sitemap document** and reports documents that give
    (nearly) every URL one timestamp to the second: the file's generation time. The whole-sitemap
    "all identical" finding takes precedence (root cause once).
120. **ACC-3 checks non-HTML documents' `X-Robots-Tag`.** A PDF can be cited, and its header is its
    only control; `noindex` there carries the same severity as on a page.
121. **STR-3 checks the structured-data graph across the crawl; `@id` keeps its fragment.**
    `normalize_url` drops fragments, which is right for fetching and wrong for identity: `/#org` and
    `/#jane` collapsed into the homepage URL, hiding dangling references and able to merge two
    STR-11 entities into one false contradiction. `id_key` resolves an `@id` with its fragment; a
    regression case (`#widget` vs `#gadget`) pins it. Dangling references and type clashes are Info;
    a page-level `url` that names another page is Info, one that returned an error is S4.
122. **STR-5: one @id with different names is Verified; name variants stay Estimated.** The first is
    the markup contradicting itself; the second needs judgement about spelling. The variant finding
    now spells out which part is which. WebSite `name` is a name source.
123. **A cited URL carrying `user:pass@` is an invalid record** (from OpenSEO's `safeUrl.ts`):
    `normalize_url` would drop the userinfo and credit the audited site with it.

## Found by the live runs of 2026-09-22 (Midas, Carpex, withmaya.ai)

124. **A check that read no page is Not assessed, never a pass.** Carpex answered all 50 of Maya's
    requests with a Cloudflare challenge (403, `cf-mitigated: challenge`). IDX-1 then reported "no 4xx
    ... across 0 fetched URLs" as PASS, and nine more page-reading checks passed having looked at
    nothing. `coverage.PAGE_DEPENDENT` lists the checks whose question is answered by reading pages;
    with no readable page they become `not_assessed` with the INT-1 reason, and with some pages blocked
    the blocked count is a coverage part (so a pass becomes `partial`). The migration applies the same
    rule from a saved report's pages.
125. **ANS-1: a block or bot challenge is not a broken page.** The same run reported Carpex's 13 most
    cited URLs as failing with "4xx" — the challenge's 403. A blocked or rate-limited answer now
    leaves the page unchecked (listed, with the status, in coverage), never "not found".
126. **"Same content" is the share of words identical and in the same order** (IDX-4, ANS-1). On
    Midas the same article at `/x` and `/x/` differed only in a "latest posts" list cached on different
    days: 90% of words identical, yet the shingle sketch estimated 0.69 and IDX-4 (since September) and
    ANS-1 (10 cited URLs) called it "canonicalized to different content", S2. Two different articles on
    that template share 42% of words. The threshold `same_content_block_share` (0.8) sits between the
    two measured values; one site is not a calibration (LG-21). The differing passages are quoted in
    the evidence. The sketch remains only where the page text is not in memory (saved reports). Words,
    not text blocks: one edited word in a long paragraph would otherwise make the whole block differ.
127. **RND-3: text that arrives with a new `<h1>` is another article, not hidden content.** A Midas news
    page, scrolled during rendering, fetched the next article through a "loadmore" request (a second
    `<h1>`, "Fed, faiz kararını açıkladı") and was reported as S3 content behind interaction. Verified
    by a separate render on 2026-09-22. Such additions are now an observation (Estimated: the new
    `<h1>` is the signal), and the page's own interaction results are unaffected.
128. **RND-3: text that opens outside `<main>`/`<article>` is page chrome, not hidden content.** On
    withmaya.ai, "Open menu" / "Product" clicks added 47 words to 8 docs pages and were reported as S3.
    A render of `/docs` showed the main content at exactly the same length (754 characters) before and
    after, with all 329 new characters in the menus. When a page marks up its main content and that
    region grew by less than a fifth of the growth, the result is an observation. Pages without
    `<main>`/`<article>` are judged as before.
129. **RND-2: live values that changed before the render are not missing from raw HTML.** Midas's
    `/canli-kripto/` shows 272 prices in its raw visible text, but each live quote had a new value by the
    time the page was rendered, so RND-2 listed them as "prices only after JavaScript" (S2). When the raw
    text holds at least 80% as many prices as the rendered view, the differing values are recorded as
    live data, not as content missing from the raw HTML. A page whose prices really arrive only by
    JavaScript still reports S2 (tested).
130. **TSEO-1 adds traditional metadata and heading hygiene without duplicating existing checks.**
    IDX already owns HTTP status, redirects, broken links, orphans, and crawl depth; STR owns title and
    description presence, heading presence/sectioning, and image-alt coverage; PRF owns repeated
    response-time measurements and the optional PSI/CrUX panel. TSEO-1 therefore adds only title and
    meta-description character bands and skipped heading levels. The bands (title 10–60, description
    70–160) are editorial heuristics, not Google limits. Measurements are Verified, the impact
    rationale is Hypothesis, and severity is capped at S4. Pages with a rendering gap, a truncated
    body, or unvisited URLs on an incomplete crawl are listed as not assessed; they cannot turn a clean
    result into a pass. The image analyzer separately keeps exact alt-attribute totals beyond its
    200-image detail cap, while making the unclassified remainder a coverage gap.

## Page reader, spending and status (2026-10-08 and 2026-10-09)

Each entry says where the decision came from. **Owner** means the project owner stated it in the working session
(for the spending and reader rules, as decided with the team lead); nothing in the repository recorded it at the
time, which is why it is written here. **Agent default** means the implementing agent chose a value nobody
approved. **Pending** means a decision the owner has not made.

131. **Firecrawl reads the pages of every audit when a key is set (Owner, 2026-10-08).** Basic proxy, Firecrawl's own
    cache off, credits recorded in the ledger, no separate confirmation for a normal run, page cap as the plan's.
    Maya's own crawler still makes every direct request: robots.txt, sitemap, redirects, headers, timing, the
    bot-access test. `--no-firecrawl`, the plan card's tick and `MAYA_AUDIT_FIRECRAWL=off` switch it off. A key's
    presence authorises this reader only: no other provider, no stronger proxy.
132. **Stronger proxies stay behind the owner-approval tick and an exact confirmation (standing rule).** `enhanced`
    and `auto` are refused without the recorded approval, in the plan, the client and the command line. Nothing
    escalates by itself after a failure.
133. **DataForSEO: $100 a day and approval above $10 an audit (Owner, 2026-10-09; first $30 and $10 on 2026-10-08).**
    A plan at or under the threshold shows its cost and runs; above it the exact total is confirmed. The day's limit is
    `MAYA_AUDIT_DATAFORSEO_DAILY_USD` or `--dfs-daily-budget`. The earlier rule ($2 a day, a confirmation before
    every paid plan) is superseded; `docs/OPENSEO-ADAPTATION.md` described that earlier rule.
134. **Firecrawl's daily guard of 10,000 credits is an Agent default. PENDING.** The owner said budget was not a
    concern for the reader and named no number; 200 credits a day would have stopped one Standard audit. 10,000 was
    picked by the agent and is not an approved policy. It must not be raised or described as approved. The decision
    (a number, and whether a dollar price per credit is to be configured) is the owner's and the team lead's.
135. **Zero data retention is asked for unless the computer's settings say otherwise (Owner set it off on this
    computer, 2026-10-08).** `MAYA_AUDIT_FIRECRAWL_ZERO_DATA_RETENTION=off` is the owner's own setting; the code never
    reads or changes it beyond that name. Every report states what was applied (`firecrawl.zero_data_retention.status`).
    A refusal when it is asked for still stops the reader and asks for a recorded per-audit decision. Normal-run
    retention consent was not redesigned in this phase.
136. **A site that challenged Maya's crawler and was read through a reader is not headlined as blocked (Owner,
    2026-10-08), and its access note says only what was observed (corrected 2026-10-09).** ACC-9 stays a finding,
    shown at Info, with the original severity and every measurement in its evidence. It no longer says verified
    crawlers are unaffected or that nothing needs fixing: neither was measured. The INT-1 gate and the crawl record are
    never changed by a reader.
137. **Reading through a reader is content coverage, not access.** `audit_status` keeps four facts apart: Maya's own
    direct access, content coverage, what is known about the vendors' own crawlers, and (in the web app) the job's
    state. A user-agent probe (ACC-4) comes from Maya's network, not the vendor's: it is `limited_user_agent_probe`.
    Ownership verification is permission to run it, not proof of a crawler's identity.
138. **"Complete" means every address found within scope was read.** With a reader, anything it left unread (its page
    cap, a stop, the deadline, a page with no readable document, a key page) makes the audit INCOMPLETE (exit 3). A
    page that answered with an error status is an answer, not a gap. Exit codes keep their meaning: 0 complete,
    1 degraded, 2 error, 3 incomplete. A complete sample is called a sample.
139. **A provider's page keeps its own identity.** An HTTP status the provider did not report is null, never a
    stand-in 200; its document may still feed the HTML-only checks (`PageFetch.view` is `provider`). The address
    reached is recorded: the www twin of the address asked for is the same page; another address of the site is
    recorded under that address; another site's or an unsafe address's document is not analysed. A provider field
    called `rawHtml` is not evidence of what a crawler that runs no JavaScript receives.
140. **One deadline, stop request and pace for every step (`maya_audit/runclock.py`).** Nothing is reserved or sent
    after the audit's time limit or a stop. A request that reaches the audited site through a reader waits the gap
    Maya's own crawler ended on. A site that rate-limited Maya is not asked again through a reader in the same run
    (decision 52 applied to readers). An audit that plans to use a reader gets 8 seconds a page added to its time
    limit: an Agent default, a planning figure like the limit it extends.
141. **One retry, only for a request that never left the computer (Owner, 2026-10-09).** A DataForSEO call whose
    address lookup failed or whose connection was refused is tried once more. A request that was sent and got no
    answer is never repeated: it stays reserved as possibly billed.
142. **A missing measurement is not assessed or partial, never zero or healthy.** A measured zero, an empty provider
    sample and an unreadable answer are three statuses. Lighthouse lab figures are kept apart from real-visitor
    figures (the Chrome UX Report), and a metric is called good only when it was measured. The AI-mentions request's
    scope (`any`) is unchanged, so its cost is unchanged; the wording now says what that scope matches.
143. **Lighthouse through DataForSEO reads category scores (Owner asked for the panel, 2026-10-08).** This differs from
    decision 53, which is about PRF-3 (PageSpeed Insights) and still holds there: PRF-3 never reads a score. The DFS
    Lighthouse panel is third-party data in its own section, never a finding.
144. **A Google Business Profile found by name is the business only when its website is the audited domain.**
    Otherwise it is shown, and nothing is recommended from it.
145. **Keyword relevance is word matching and says so.** Branded, relevant and unrelated are sorted from the brand
    name, the site's own titles, headings and descriptions and the business description; the unrelated rows stay
    visible. It is a heuristic, not a judgement of meaning.
146. **The reader takes pages in the crawler's order (Agent default, 2026-10-09).** On a site Maya's own crawler
    cannot read, the reader's queue is: the start page and marked important pages, pages linked from the menu, then
    the kind of page read least so far, with sitemap-only pages after linked ones and page 2 of a list last
    (`maya_audit/firecrawl/reading.py`). The number of requests is unchanged; only which pages they are spent on.
147. **A challenged site's sitemap may be asked for through the reader (Agent default, 2026-10-09).** Only when Maya
    could read no sitemap itself, only after the reader has read a first page, only where robots.txt allows, at most
    two documents (2 requests), and only when the page cap is 10 or more. The requests are inside the confirmed
    maximum, which now counts them. On in the app and the command line; a refusal or an unanswered request stops the
    reading rather than paying again. Not yet seen against the real service (LG-50).
148. **Five unreadable answers in a row stop the reading (Agent default, 2026-10-09).** A reader that is being turned
    away is not asked for the rest of the site. The site's own error answers (404, 410, 5xx) do not count. The pages
    never asked for are counted as unchecked, with the reason `reader_kept_failing`, and the audit reads INCOMPLETE.
    The figure (`Options.stop_after_unreadable`) is a guess, not a measurement.
149. **The reader's share of the time is kept up front (Agent default, 2026-10-09).** When a reader is planned, Maya's
    own crawl stops at the time limit less `pages x (delay + seconds a page)`, so a slow crawl cannot use the time the
    reader needs. A limit the operator typed is not extended; at most half of it is kept. The 8 seconds a page of
    decision 140 is now adjustable (`MAYA_AUDIT_READER_SECONDS_PER_PAGE`, `--reader-seconds-per-page`, 1 to 120). It
    remains a planning figure: the benchmark shows it is not enough for a reader that really takes 20 seconds a page.
150. **Every page asked for and not read carries a cause, and every page not asked for carries a reason (schema
    1.7).** Causes: reader challenged, provider could not load, provider refused, timeout or no answer, credit or
    request limit, empty document, error status, redirect within the site, redirect to another site. Reasons for not
    asking: page cap, time limit, stopped, credit limit, reader kept failing, site rate-limited Maya.
151. **Pages on an open site are still read twice, once by Maya and once by the reader (Owner policy, decision 131,
    unchanged).** Maya's fetch gives the status, headers and timing; the reader gives the content. Phase 2 removed no
    fetch from that arrangement. What it avoids: asking for an address twice in one run, asking again within a day
    (the saved copy), and asking for the rest of a site the reader cannot read.
152. **No further rendering provider is added (Owner, 2026-10-09).** After Phase 2 the benchmark's remaining unread
    pages are caused by the page cap, by a reader that is itself challenged, and by time. None of those is solved by
    a second renderer. See `docs/COVERAGE-BENCHMARK.md`.
153. **A host is looked up through the system resolver, then DNS over HTTPS (Owner, 2026-10-09).** The system resolver
    is given 4 seconds, asked once more after a pause, and then the name is asked of Cloudflare and, failing that,
    Google, each reached by its published IP address (`maya_audit/resolver.py`). Which method answered is written in
    the report (`crawl.network`). Private and reserved addresses stay refused whoever answered, and the connection is
    made to the addresses that were checked. The host name of the audited site is therefore sent to Cloudflare or
    Google when the system resolver fails; `MAYA_AUDIT_DNS_OVER_HTTPS=off` switches the fallback off. The timeouts,
    the single retry and the one-minute reuse of an answer are Agent defaults.
154. **Only an answer the site sent can be the site's failure (Owner, 2026-10-09).** A robots.txt fetch that got no
    answer (a DNS lookup that failed on this computer, a timeout, a refused connection) is `not_checked`: no rule is
    assumed, RFC 9309's "assume complete disallow" is not applied, and nothing is reported against the site. RFC
    9309's disallow-all is kept for a robots.txt answered with 5xx, and ACC-1's Blocker likewise. This departs from
    the RFC's own wording, which also counts network errors as unreachable: one computer's failed request cannot tell
    the site's fault from its own. Maya's own crawler still requests no page from an origin whose rules it could not
    read (`crawl.stop_reason: network_problem`). A timeout or refused connection is worded as "no answer reached this
    computer; whether the site or the connection failed is not known" (Agent wording), a failed lookup as "network
    problem on this computer".
155. **A pre-flight check before anything is requested or spent (Owner, 2026-10-09).** The target is looked up, and
    if that fails one well-known public name (`example.com`). If nothing can be looked up the audit does not start:
    "Network problem on this computer (DNS lookup failed). Check VPN / iCloud Private Relay / Wi-Fi and try again."
    No report, no findings, no spend. A name a public resolver says does not exist is said as that.
156. **A local failure never stops the reader (Owner, 2026-10-09).** When Maya's own robots.txt fetch got no answer
    and Firecrawl is on, Firecrawl is asked for robots.txt and RFC 9309 is applied to that answer. The report says
    direct access was not measured; it does not say the site challenged anyone.
157. **202, SiteGround's captcha path and three more Cloudflare markers count as a bot check (Owner asked for OpenSEO's
    list, 2026-10-09).** A 202 is classified blocked with confidence Estimated. The body markers count only beside a
    denial status or a 503, so an article that mentions them stays a page. A 429 is a rate limit even when Cloudflare
    marks it. Not validated against current vendor challenge pages (LG-54).
158. **The brand's ordinary word on its own is ambiguous (Owner, 2026-10-09).** "maximum" alone is neither a brand
    search nor an opportunity; it is listed apart. The name with a company word or one or two of the site's subject
    words stays branded. Word matching, as before (decision 145).
159. **A control coded as a link is an accessibility note, not an SEO finding (Owner, 2026-10-09).** STR-19 is Low
    only for an `href="#"` or `javascript:` link whose text reads like navigation to content. A sign-in, sign-up,
    forgot-password, menu, search, close, cart or language control (English and Turkish labels), an `<a>` marked with
    `role="button"`, `aria-haspopup`, `aria-controls`, `aria-expanded`, `data-toggle` or a dialog attribute, and an
    icon with no text are listed in one Info note: "N control(s) are coded as links (href="#"); use <button> for
    screen readers." A note is never in the action plan. The label list is exact word matching (an Agent default): a
    link to content labelled exactly "Search" would be read as a control. The Low finding now says what a crawler
    sees: "N link(s) have no address a crawler can follow (they may still work for visitors through JavaScript)."
160. **A headline with every total, the problems by page, and "Top N of M" (Owner, 2026-10-10).** A manager read
    "15 problem(s) found, of which 0 blocker(s) and 1 high" as "one error was found". The first line of the PDF
    summary, of the results card and of the Markdown report is now "15 problems found on 50 pages (1 high, 5 medium,
    9 low) + 12 notes"; the severity boxes follow under "By severity"; the top list is headed "Top 5 of 15 problems"
    (or "All 3 problems"); and a "Problems by page" section lists the whole site first and then each page with a
    problem. The engine counts once (`problem_summary`, report schema 1.9): a note (Info) is never a problem, a
    site-wide problem is counted under "Whole site" and never against each page, any other problem counts once per
    distinct page, and pages not listed for a problem are said in a line, never dropped. The "Issues" column of
    "Every page" reads the same counts. The Owner also decided that "Whole site" is pinned as the first row and that
    saved reports are not rewritten (the web app derives the table for them with the same engine function).
    Agent wording: the Turkish column names ("En yüksek önem derecesi", "Sorun başlıkları"), the reworded note under
    "Every page", the plain heading kept when no problem is shown, and "All 1 problems" left unpluralised as the
    Owner's wording gives it. Agent defaults: the comparison for `not_listed` uses the length of the list as saved,
    and the Markdown shortens an address by the site's origin.
161. **"Problems by page" says what is wrong on that page, with that page's own numbers (Owner, 2026-10-11).** Each
    row printed the finding's site-wide title, so one page read "31 page title(s) above the 60-character guidance
    band". The engine now gives, for each page and each of its problems, a `kind` and that page's `values`
    (`problem_summary.by_page[].items`, report schema 1.10, `maya_audit.report.page_item`), read from the finding's
    own evidence, so a saved report is worded the same way as a new one; the row reads "Title too long (71
    characters)". The "Whole site" row and "Findings by area" keep the titles. Where the report holds no number for a
    page (an evidence list cut at 40 to 80 rows, or an older report) the row takes a plain form ("Title too long (over
    60 characters)"), never the site-wide count. A finding with no rule reads "Also affected by: “title” (that figure
    is for all N pages, not this page)". STR-19 now records how many such links each page has (`by_page`); a report
    saved before that reads "Has links with no address a crawler can follow (number on this page not recorded)".
    Counting (decision 160), decision 159, `finding_ids`, `scope`, `affected-urls.json` and saved files are unchanged;
    reports of 1.8 and 1.9 get `items` derived when shown. Owner's wording: the column heading "What is wrong on this
    page" / "Bu sayfadaki sorun", the sentences for the canonical target, tagged internal links, two values of one
    entity, words after a click, links with no address (both forms), heading jumps, title and meta description
    length, main-content share, the hreflang target, "Shares its title “…” with 3 other pages", "hreflang to X is not
    returned", and the default sentence. Agent wording: every other kind's sentence, every plain form not listed
    above, the suffix "(and N more on this page)" where a page has several such things and the first is described,
    and all the Turkish (a draft, like the rest of the Turkish). Agent defaults: a kind is chosen by the check and the
    words of the finding's title; a number is said only when the evidence list is whole or holds the page's row; a
    count of one in the default sentence drops the "(that figure is for all N pages…)" part; the results card may now
    be up to 200 KB on a 500-page audit (it was held under 150 KB), because it carries these sentences. Schema
    versions are compared as numbers (`schema.version_key`): "1.10" is after "1.9". Checks with a sentence of their
    own: ACC-3, IDX-1, IDX-3, IDX-4, IDX-6, IDX-7 (orphans), IDX-8, PRF-1, PRF-2 (per URL), RND-1, RND-3, RND-6,
    RND-7, STR-1, STR-2, STR-3 (unparsed JSON-LD, broken markup URL), STR-4, STR-5 (@id name clash), STR-6 (future
    date, dates apart), STR-7 (images that do not load, missing alt), STR-8, STR-9, STR-10 (dead og:image), STR-11,
    STR-12, STR-13, STR-14, STR-16, STR-19, STR-20, TSEO-1. The rest use the default.
162. **Five distinct first actions (Owner, 2026-10-11).** "First five actions" took the top five problems and printed
    one action each, so two STR-11 findings with one fix printed the same sentence twice. Problems are now walked in
    priority order and grouped by check and action text; a group is one line whose `for` names every title in it; the
    list is filled until it holds five distinct actions or the problems end. "Top 5 of 15 problems" is unchanged.
    Agent defaults: the action text compared is the first sentence, as printed; the owner, effort and timing shown
    are those of the group's first problem; `for` joins the titles with "; " and `titles` lists them.
163. **The page count is said once on the executive page (Owner, 2026-10-11).** Under a headline that says "on 50
    pages" the page printed "50 page(s) checked. 29 part(s)…" and then "50 page(s) were checked. That is evidence…".
    It now prints "29 parts could not be checked; see “What could not be checked”." (nothing when no part was left
    out) and "The pages checked are evidence about those pages, not proof about every page of the site." The API
    keeps `summary_line` and gains `gaps_line`. Not changed (an Agent note): the engine's own sentences printed on
    the same page, the outcome's reason and the notes of "What this audit covers", may still name the count.
164. **One page, three pages (Owner, 2026-10-11).** The web layer's own sentences no longer say "page(s)": a
    placeholder may carry the word for one and for many (`{count:page|pages}` gives "1 page", "3 pages"), in
    `strings.t` and in the page's `T()`, which is given the number itself and writes it with thousands separators.
    Turkish does not change the noun after a number, so its sentences keep the plain placeholder with the same name.
    The engine's line about pages not listed is fixed at source; finding titles written by the engine keep "(s)"
    for now. Agent defaults: a whole number written with its word is grouped ("1,234 pages"); a number handed over
    as text ("1") is still one; `{count:.}` groups with a dot for Turkish sentences; verbs agree with the count
    ("1 more problem is", "3 more problems are").
165. **Finding titles, "What to do" and the coverage sentences in the reader's language (Owner, 2026-10-11).** The
    owner asked that the Turkish report hold no English sentence except addresses and code, that titles and actions
    be translated with their numbers filled in, that the translation be marked for a native speaker's review, and
    that English say "1 page", not "1 page(s)". The engine's sentences are reworded at display time only, in
    `maya_audit_web/wording.py`: `report.json`, `report.md`, `affected-urls.json`, the Markdown and JSON downloads and
    `GET /result` stay the engine's English, byte for byte in both languages. A finding row keeps `title`, `fix`,
    `expected` and `notes` as the engine wrote them (the catalog's note, the fix example, the comparison and the
    search are keyed on them) and adds `title_shown`, `fix_shown`, `expected_shown`, `notes_shown`, `untranslated`
    and `notes_untranslated`; every place that prints a finding prints the shown fields, in both languages. English
    titles go through an English display form ("1 page is canonicalized ...", "16 internal links on 4 pages carry
    ..."); English fixes, expected results and notes are shown as written. Turkish comes from
    `maya_audit_web/locales/findings/tr.json`: a title by its pattern's key, a fixed sentence by its exact English
    text, with numbers, addresses, bot names, header names and quoted site text put back unchanged. A sentence with
    no entry is shown whole in English followed by " (İngilizce)": never dropped, never half-translated. The outcome
    sentence stored with an audit is reworded by its frames (stop codes such as `page_cap` come out as words); the
    three rows of "What this audit covers" and the saved-copies note are worded in Turkish from the report's own
    fields (`audit_status`, `crawl.stop_reason`, `firecrawl.pages`), not by taking the English sentence apart, and
    stay the engine's own sentences in English; the reasons under content coverage go through the same table. The
    printed report says which language it is in (`<html lang>`), and its Turkish cover carries one line saying the
    translation is a draft. Agent defaults (nobody approved them): the translations themselves, which are an
    agent's draft (LG-59); Turkish writes a percentage as "%27"; a shown title begins with a capital; a word that
    needs another form in another place has an entry for that place ("blocked" as what happened to a request, or as
    the state of a token); search also finds a finding by the words shown; a review item's title, reason and
    suggested action are shown the same way. Not done in this change, and still English in the Turkish view: check
    titles and summaries, "What could not be checked" reasons, gate summaries, the DataForSEO and Firecrawl panel
    lines, the CrUX summary, the archived-copies panel, the answer-engine panel's findings (ANS), and the notes the
    engine puts together at run time that have no pattern (they take the mark).
166. **The rest of the Turkish report: check titles and summaries, what could not be checked, gates and the data panels (Owner, 2026-10-11).**
    The owner's requirement stands as in 165: "so the Turkish report has no English sentence except URLs and code.
    Mark them for native-speaker review." This change finishes what 165 left English. Still display time only, in
    the web layer: `report.json`, `report.md`, the Markdown and JSON downloads and `GET /result` stay the engine's
    English, byte for byte in both languages. Two more doors in `maya_audit_web/wording.py`, on the same frames and
    the same Turkish file: `label` for a short name (a check's or gate's title, the part of a check that was not
    assessed, a data panel's title, a figure's or a column's name) and `line` for a sentence or a run of sentences
    (a check's or gate's summary, the reason a part was not assessed, a line of the Firecrawl, DataForSEO, Core Web
    Vitals or archive section, a step of the allow-list or of ownership verification). Their frames are in
    `maya_audit_web/sentences.py`; the Turkish is in `locales/findings/tr.json` (`labels`, `label_patterns`, `lines`,
    `line_patterns`, more `terms` and `term_patterns`), still marked for review. Every row keeps the report's own
    English field and gains what is shown beside it: `title_shown` and `summary_shown` on checks, gates (with
    `state_label`) and the answer-engine panel; `part_shown` and `reason_shown` on coverage gaps; `title_shown`,
    `summary_shown` and `data_shown` on data panels; `lines_shown` and `notice_shown` on the Firecrawl section;
    `summary_shown` and `source_shown` on Core Web Vitals; `stop_shown` on the method. The printed report and the
    page print the shown fields. A run of sentences is put into Turkish sentence by sentence; one sentence with no
    entry marks the whole run with " (İngilizce)" (never half-translated). English: every one of these sentences,
    and the fixes, expected results, notes, the outcome sentence and the status rows, is shown through
    `wording.english`, which resolves a counted "(s)" ("1 page was read", "3 pages were read") and says an uncounted
    one as a plural ("the missing pages"); nothing else in the English wording changes. Agent defaults (nobody
    approved them): the translations themselves (LG-59); a provider's table cells, addresses, code, quoted site
    text and Google's metric names are shown as they are; a data panel's labels are a small map (`data_shown.labels`)
    rather than a second copy of its tables, to keep the results card small; a gate's state is shown by a word of
    this layer in Turkish and by the report's own word in English; a reason on a line of its own begins with a
    capital unless it begins with a host name; the count and the cause of an unread page are said one way
    ("boş belge: 1"). The results card of the 500-page fixture grew from about 183 KB to about 202 KB with the new
    fields; its size guard in `tests/test_web_app.py` moved from 200 KB to 215 KB. What knowingly remains English is
    listed under LG-59 and named in the tests' allow-lists.
167. **A page is its own document and its own head; Maya's own response decides indexability (Owner asked for the fix, 2026-10-11; the exact rule is an agent default).**
    Seen on two sites on 2026-10-11 (docs/FALSE-ALARMS.md FA-001, FA-002): the page reader wrote the document of a
    chat-widget iframe into every page copy, `<div src="..." data-original-tag="iframe"><!DOCTYPE html><html><head>
    <meta name="robots" content="noindex, nofollow"><title>...`, and Maya read the widget's robots tag and title as
    the page's. 50 of 50 pages were dropped as noindex and 20 checks said "No indexable HTML pages"; on the other
    site 20 titles were reported too long because the widget's title was added to them. The owner asked for this to
    be fixed. The rule, chosen by an agent: (a) an embedded document is treated like the iframe it came from
    (`maya_audit/own_document.py`): any element carrying `data-original-tag="iframe"`, and any second `<!DOCTYPE>`
    or `<html>` that starts after the page's body content began (up to its `</html>`; when the element it sits in
    ends first, up to there; else to the end of the file), is taken out before the page is analysed or its links
    are read. Its text, headings, links, images, structured data, meta tags and title are not the page's. It is
    recorded in `analysis.embedded_documents` and is not counted as an iframe. Sizes and offsets (`html_chars`,
    `main_offset_bytes`, RND-6) are still those of the HTML as received. (b) A `<title>` (the first one only),
    `<meta name>`, `<meta property>`, canonical link and hreflang link are the page's only before the body starts:
    at `<body>`, or at the first element that is not one of html, head, title, meta, link, script, style, base,
    noscript, template (so a document with no `<head>` tag still works; inside `<noscript>` or `<template>` nothing
    starts the body). Later ones are counted in `analysis.outside_head`. A `<meta name="robots">` in the body never
    drops a page; ACC-3 says it once, as an Info note ("N page(s) carry a robots tag outside <head>: browsers
    ignore it; some crawlers may not"). (c) When Firecrawl reads a site Maya's own crawler read too, whether a page
    may be indexed is decided by Maya's own response: its headers and the robots meta tags of its own head replace
    the reader's in the merged page. Each page whose two copies disagree is listed in
    `firecrawl.coverage.indexability_disagreements` (first 40, with a count) and in the page's
    `classification_evidence`. Limits are under LG-60.
168. **A check that looked at no page is not assessed, and the headline says when most page checks could not run (Owner asked for the line, 2026-10-11; "fewer than half" is an agent default).**
    With no indexable page, five checks still said "pass" ("No news or press page among the pages read", "No
    duplicate groups among 0 indexable self-canonical page(s)") and the report read "No problems found on 50 pages".
    Now, for the checks that read the content of indexable pages (IDX-8, STR-1 to STR-23, TSEO-1;
    `coverage.NEEDS_AN_INDEXABLE_PAGE`, the same list as `reader.CONTENT_CHECKS`): when the audit has no indexable
    page, or the check's own evidence says `pages_checked` or `candidates` is 0, and its status is pass, partial or
    observed, the status becomes `not_assessed` with "Not assessed: none of the {n} pages read could be checked
    ({why}), so there was nothing to look at." The reason is "all are noindex or canonical to another address", or
    "all were withheld because their content arrives after JavaScript" when the audit has indexable pages and the
    check left them all out. The rule is in `coverage.settle`, so a migrated report is settled the same way. The
    report counts once how many page checks could run (`problem_summary.page_checks`: `total`, `could_run`,
    `limited`; a page check is one in `coverage.PAGE_DEPENDENT`, so never the answer-engine or paid panels). When
    fewer than half could, the headline's first sentence in every output is "Only {could_run} of {total} page checks
    could run, so this is not a clean result." and, with no problem found, it goes on "The {could_run} that ran
    found no problems on {pages}". A report saved before schema 1.11 gets the count when it is shown; its file is
    not rewritten. The owner asked for the line; the threshold (fewer than half) and the wording are an agent's.
169. **A sentence is never shown with an unfilled hole (agent default, 2026-10-11).** "Problems by page" printed
    `{headings:section heading is|section headings are} in {language}, but the page is declared as {declared}`:
    the sentence had a value named `language`, and `strings.t(key, language=None, **values)` took it for the
    interface language, failed to fill the sentence and returned the template. Now `t`'s `key` and `language` are
    positional only, so a value may have either name. When a value is missing, `t` uses the sentence's plain form
    (`<key>.plain`) if there is one; otherwise it writes "…" for each missing value and logs a warning. The page's
    `T()` in `static/app.js` does the same. Where a sentence names a language, the reader sees its name in their
    own language ("English", "İngilizce"; web keys `language.en` ... `language.nl`, engine `language.NAMES`); the
    report's JSON keeps the code. `tests/test_no_unfilled_placeholders.py` looks for an open hole in the Markdown
    report, the JSON report's display strings, the results card, the practical report and the printed page, in
    English and Turkish, and fills every sentence of the web app that has a hole; what may hold braces on purpose is
    an explicit allow-list in that file.
170. **Pages are counted as documents read, not addresses; one stop sentence; one "not read" figure (Owner asked for the counts to agree, 2026-10-11; the exact rules are agent defaults).**
    Four saved reports of 2026-10-11 disagreed with themselves. One said "55 pages" under a cap of 50: every address
    either reader had touched was counted, so 5 PDFs and 7 `/blog?tab=` addresses (which Maya read as 200 and the
    page reader recorded as redirecting to `/blog`) were pages. It gave three reasons for one stop, one of them "a
    credit or request limit was reached" when no credit had been refused. Each report held two "not read" figures
    (449 and 448; 8357 and 8358; 297 and 300). One listed 10 sitemap files as pages with problems. All four said
    "sitemap addresses found: 0". Now:
    (a) A page is a distinct HTML document that was read, by Maya's own crawler, by the page reader, or by both
    (`report.read_counts`). An address Maya fetched that is not HTML (a PDF, another document, an image: by its
    content type or its path) is a file; an address the reader recorded as `redirected` to a page that was read is
    the same page under a second address. Neither is a page; both are counted beside the pages
    (`content_coverage.other_addresses`: `files`, `same_page`) and said: "43 pages read. Also fetched: 5 files (PDF
    or other documents) and 7 addresses that lead to a page already read." `read_by` holds three numbers that do
    not overlap (`maya_only`, `firecrawl_only`, `both`) and add up to `total`; `firecrawl` is kept. The headline,
    the cover, `problem_summary.pages_checked`, `content_coverage.pages_read` (and `readable_unique_urls`, its old
    name) and the status rows all use this one figure. Without a page reader the headline's count is still
    `page_counts.pages_checked`, as before.
    (b) What a reading is allowed, and what is paid for, is requests. When the allowance is used before the pages
    read reach the cap, `firecrawl.coverage.not_requested_because` is `request_allowance_used` and the only stop
    sentence is "the page reader used all {n} page requests this audit allows and read {m} pages; {k} requests led
    to pages already read or to missing pages" (the last clause is dropped when k is 0). "Reading stopped early",
    "N more discovered URLs remain unchecked (a credit or request limit was reached)" and "Maya's crawl stopped:
    page_cap" are not said beside it; "credit" is said only for a real credit or budget refusal. When the page
    reader is the audit's main reader, the page cap of Maya's own crawl is never a second reason (it stays in
    `crawl.stop_reason`). The client's refusal now reads "the Firecrawl request allowance of {n} for this audit is
    used"; the cap itself is unchanged. `n` in the sentence is the page requests actually sent. The client allows
    one request more than the page cap (kept for robots.txt); when robots.txt was Maya's own, that request goes to a
    page, so a cap of 50 can read "51 page requests". That is the true number and it is said as it is.
    (c) `content_coverage.known_urls_not_read` is the only "not read" figure. With a page reader it is the reader's
    count, which leaves out addresses robots.txt disallows and addresses that are files; how many were left out is
    in `content_coverage.unread_left_out` and said as "+12 addresses left out: disallowed by robots.txt or not a
    page". When the final list of checks is assembled (`reader.apply`, used by the command line and the web runner
    alike), `coverage.restate_crawl_gap` rewrites every check's "pages found but not read" part, and the count of
    TSEO-1's "discovered pages not fetched" part, with that figure and with the pages read.
    (d) A file is not a page. `urls.non_page_kind` tells a sitemap, robots.txt, a document and an image from a
    page by its path; the reader never asks for one. The IDX-5 finding about stamped sitemap documents is
    site-wide. Any other problem that names a file is listed under `problem_summary.files`, printed under the table
    as "Files (sitemaps, robots.txt, documents)", never as a page's row.
    (e) `firecrawl.coverage.sitemap_addresses_found` is what the reader itself found when it was asked for the
    sitemap of a site Maya could not read; on a site Maya read it is 0 by construction.
    `sitemap_addresses_known` holds what Maya's own crawl knew, and the report says "Sitemap: {n} addresses known
    from Maya's own crawl; the reader was not asked for the sitemap."
    A report saved before these fields existed is shown the same way: `report.content_coverage_shown`,
    `report.with_page_items` and `coverage.restated` apply the same rules to its own `crawl`, `firecrawl` and `checks`
    sections at display time. Saved files are never rewritten. Agent defaults: the wording of the sentences (the stop
    sentence is written without a capital, as one item of a list of reasons); a redirect counts as "the same page"
    only when the page it leads to was read; a file is judged from the content type Maya received or, failing that,
    the path; the reader's list of file endings is wider than the five it had (it now also leaves out .jpeg, .gif,
    .webp, .svg, .doc, .xls and the like); and the page count of a saved report is recounted, so a report that said
    "55 pages" on the day now shows 43.
171. **A problem that one shared element causes on most pages is reported once for the whole site and names the element (Owner, 2026-10-11; the 60% bar reuses the shared-block rule and is an agent default).**
    Owner's rule: "when the same element causes it on most pages, report it once under 'Whole site (shared
    header/footer)' and name the element (link href / image src / heading text) so it can be found. Remove it from
    the per-page rows." Seen on 2026-10-11: "1 link has no text at all" on 50 of 50 pages for one heart icon in the
    header (`<a href="/Hesabim.aspx#/Favorilerim">` around an SVG); 37 of 53 heading jumps landing on one footer
    heading; one footer link with `href="#"` on 47 pages. `maya_audit/shared_elements.py`: a check hands `split` the
    keys each page carries; a key carried by most pages checked is a shared element. "Most" is the bar the audit
    already uses for a text block that most pages share (`main_content.appears_on_most`, `SITEWIDE_SHARE` = 60% of
    the pages checked, and at least 3 pages), and nothing is split on a site of fewer than 5 pages. Keys: a link is
    its href as the page wrote it, made absolute, with its fragment (the crawler's own address drops the fragment,
    which is what tells /account#/favourites from /account#/orders); a link without an address is its text and why
    it leads nowhere; an image is its src; a heading is its level and text. Each shared key becomes one site-wide
    finding (`scope.kind` `sitewide`, `evidence.shared_element` = `{type, href|src|text, where, kind, pages}`) with
    the severity, confidence, expected result, fix and notes of the per-page finding it was split from, and is
    taken out of that finding. Applied to STR-14 (links with no text), STR-19 (links to content with no address),
    STR-7 (likely meaningful images without alt text) and TSEO-1 (heading jumps). The titles: "Shared header/footer:
    link to {href} has no text (on N pages)", "… link “{text}” has no address (on N pages)", "… heading “{text}”
    (H5) comes after an H2, skipping a level (on N pages)" (or "comes after a higher-level heading, skipping
    levels" when the heading before it differs by page), "… image {src} has no alt text (on N pages)". They are
    listed in `problem_summary.whole_site.shared_elements` and printed in the "Whole site" row, whose label is
    unchanged. Agent defaults: the bar; "at least 5 pages" (the shared-block rule itself starts at 4; the brief for
    this change said 5); only a problem is split, never a note (a note makes no page row); a jump is taken out of
    the per-page finding only when its heading meets the bar, so a footer heading that only a few pages carry stays
    with those pages, and the region (`where`: header, nav, footer, aside, or "repeated" when the markup names
    none) is recorded but does not decide; a row of several nameless links is moved only when all of them are
    shared; a link with no name is still not reported when the page names the same target elsewhere (the existing
    STR-14 rule). Each TSEO-1 finding now has its own list of notes (one shared list had collected "Source:
    Firecrawl." once per finding); the two notes about character bands sit only on the four length findings, and
    the heading finding says "Heading order is guidance for readers and screen readers, not a ranking rule." The
    bar is not calibrated: LG-61.
172. **Small slips in what a report says (agent defaults, 2026-10-12).** (1) RND-7's per-page line rounded the
    share: 0.295 read "Only 30%" under a "less than 30%" rule. It is now rounded down ("Only 29%"). (2) STR-10 said
    "no og:title" for `<meta property="og:title" content="">`. A tag that is present with no content is now titled
    "{n} page(s) have an empty og:title", with "Give og:title a value." (a tag that is absent reads as before). (3)
    STR-7 stored an image's whole `data:` address in its evidence (567 KB in one report). It is stored as its first
    60 characters and its size ("… (502 KB data address)"). The page's own `analysis.images` still holds the address
    as the page wrote it. (4) RND-4 listed one row per `<iframe>`; the same `src` twice on one page (a video shown
    once for each screen size) is one row. (5) The count of page checks that could run (decision 168) now also
    leaves out a check whose own evidence says it looked at no page (`pages_checked` or `candidates` of 0, no
    finding), whatever status it was saved with, and is counted again whenever a report is shown: a report whose
    five such checks were saved as `partial` now reads "Only 18 of 41 page checks could run". Nothing is guessed for
    a check that recorded no such figure (STR-22 and STR-23 in reports of that day).
173. **An account, cart or checkout page that sends a visitor to the login page is a note (Owner, 2026-10-11; the list of paths is an agent default).**
    RND-5 called any redirect to a login address a wall, a Blocker. On a shop platform's own site that was
    `/musteri-hesabi` answering 302 to `/login?ReturnUrl=%2Fmusteri-hesabi` (docs/FALSE-ALARMS.md FA-003): what an
    account page should do. Now a redirect to a login page from a page that belongs to one signed-in customer is
    one Info finding, "{n} account, cart or checkout page(s) send a signed-out visitor to the login page
    (expected)", Verified, with the pages and their targets. Such a page is known by a segment of its path
    (`config.ACCOUNT_PATHS`: account, my-account, hesabim, musteri-hesabi, uyelik, uye-girisi, uye-ol, giris,
    giris-yap, login, signin, register, kayit, sepet, sepetim, cart, basket, checkout, odeme, siparis,
    siparislerim, orders, favori, favorilerim, wishlist, profil, profile, adreslerim), compared without case,
    Turkish letter marks or a file extension ("/Hesabım.aspx"). A login page is known by its path (now also giris,
    giris-yap, uye-girisi, oturum-ac) or by a parameter that carries the address to come back to
    (`config.LOGIN_RETURN_PARAMS`: returnurl, return_url, return_to, redirect, next, continue). Unchanged: a content
    page that redirects to the login page is a Blocker, with or without `ReturnUrl=`; consent, age and country
    walls; IDX-3's finding for a redirect from https:// to http://, which the same response also gets. Agent
    defaults: the two lists; a return parameter counts only when its value is an address (it starts with "/" or
    "http"), so a page number written as `?next=2` is not a login; a redirect that goes to a login page only by its
    return parameter is now a wall for a content page too (before, only the path was read).
174. **A term or a name in a heading is not a sentence in its language (agent default, 2026-10-12; the owner asked for the false alarm to be fixed).**
    STR-12 reported a Turkish glossary as having English headings because of the word "of" in "Proof of Work (PoW)
    Nedir?", and counted "Bizi Takip Et" as French (FA-004, FA-005). `heading_language(text, among_names, declared)`
    now leaves three things out of the evidence: words in parentheses; a stopword between two capitalised words;
    and, for the page's declared language, a stopword of another language that is an ordinary word in it
    (`NOT_FOREIGN_IN`; for Turkish: et, de, da, o, en, on, an, son, al, in, ne, se, su). Turkish evidence in a
    heading gains the question words nedir, nasıl, nasil, neden, niçin, kimdir, nelerdir, nerede, hangi, kaç, mi,
    mı, mu, mü. One stopword with no rival is otherwise still enough ("Information for new patient" is English),
    and a page still needs `MIN_FOREIGN_HEADINGS` = 3 such headings. The finding stays Estimated and says in a note
    and in `evidence.method` that it rests on word lists. What the rule does not see is in LG-62.
175. **STR-4 shows both values; a price difference is High only for one reliable differing price, otherwise a person looks (Owner, 2026-10-11; the conditions and the 25% bar are agent defaults).**
    The owner's rule: "every STR-4 finding must show both values (markup price + currency vs visible price text).
    If the visible price can't be found reliably (free events, several prices, 'Ücretsiz'), it goes to 'Needs a
    person to look', not High." Seen on one site (FA-006, FA-007, FA-008): a competitor's "29 USD" in a blog
    teaser read as the price of a free course; a customer's earnings read as the price of a package; a brand
    prefix read as a different product name. **This changes approved behaviour:** a markup price that no shown price
    equals, on a page that shows several prices, was an "Inferred" conflict and still High; it is now a review item.
    (a) A price is the page's own when it stands in the main content (`_content_blocks`), not in link text, not
    in a text block that at least 25% of the pages and at least 5 of them repeat (`config.TEASER_SHARE`,
    `TEASER_MIN_PAGES`; `SITEWIDE_SHARE` stays 0.6), and its currency mark, when it has one, agrees with the
    markup's. Prices that another offer of the page matches are set aside. (b) A markup price of 0 matches
    "ücretsiz", "bedava", "free" or "ücret alınmaz" in the page's own content. (c) High, Verified, when exactly one
    such price is left and it differs. A review item, "{n} page(s): the markup price is not shown on the page, or
    the page's own price could not be told apart", when none is left or several are. (d) Several offers on one
    page: when one of them matches and nothing else is shown, the others listed beside it are still "prices the
    page did not show when it was read" (decision of 2026-10-07, unchanged). When one more price is shown and one
    offer is left, they are a pair and the difference stands: markup 89 beside a shown $99 is still High. When
    several offers are left, the price cannot be given to one of them, and a person looks. With no offer matched,
    one shown price contradicts every offer (the homepage case of 2026-10-06 is still High). When two descriptions
    of the same thing give different prices and the page shows one of them, the other is still a difference (and
    STR-11 still leaves it to STR-4). (e) A product name: the site's own names (og:site_name, the site's
    Organization and WebSite names, its host name) are dropped from the name's title-separator segments before it
    is compared; a name not on the page is `not_visible` ("the product name is not shown on this page"); a
    different name needs a page that describes one product and has an H1 that names something else. (f) Every
    price row holds `schema_currency`, `offer_parent` (`type`, `name`), `visible` (each price of the page as
    `text`, `value`, `currency`, `context` of about 80 characters, and `where` it stands), and, when it could not
    be decided, `why_not_reliable` with a `why_code`. Until now `visible` was a list of texts or a sentence; a
    saved report is still read. (g) Shown: "Problems by page" says "Structured data says {markup} {currency}; the
    page shows “{shown}”" (page kind `markup_price_differs`; the plain form when the report holds no currency),
    and the finding's own section and the review list print one line per row, "Markup: … / Shown: …", in the
    Markdown report, the printed report and the card (`report.detail_lines`, strings `detail.*`). Agent defaults:
    everything in (a), (b), (d) and (e); the review item is Estimated. The bar is not calibrated: LG-63.
176. **STR-5 lists the names; an og:site_name that holds the page title is its own line (agent default, 2026-10-12; the owner asked what the names were).**
    "The brand is named 13 different ways" printed no name. Seven of the thirteen were one defect: the page's title
    in og:site_name ("KVKK | Caprexonline") on seven static pages (FA-009). An og:site_name that has a title
    separator in it ( | , - , – , — , · , • or : between spaces), or that equals the page's own title and is not
    the value most pages give (a homepage titled with the brand alone is right to repeat it), is not a name of the
    brand. Such pages are one finding, Low, Verified, "og:site_name holds the page title on {n} page(s)", with the
    pages and values in its evidence. Each name in "The brand is named {n} different ways" now has `name` (its
    commonest spelling), `spellings`, `pages` and `by_source`, counted before the lists are cut to 10 and 60, and
    every output lists them: "“Carpex”: title suffix (38 pages), Organization name (1 page)", in the finding's own
    section and after its title in the "Whole site" row. `Product.brand` is not read and never was: the brand of a
    product a shop sells is not a name of the shop (a test holds this). Not changed: which title segments count
    as a name (the commonest one, or one that shares a word with another source), so a misspelt suffix that was
    a "name" only through those og:site_name values is no longer one.
177. **More controls: the cookie-settings opener and show/hide toggles, by label and by class (agent default, 2026-10-12).**
    Decision 159 stands: a control coded as a link is an accessibility note, never a problem. Two controls were
    not recognised and were reported as links without an address (FA-010, FA-011). Added labels, compared as before
    (case and Turkish letters folded, the whole label): çerez ayarları, çerez tercihleri, çerez yönetimi, cookie
    settings, cookie preferences, manage cookies, gizle, göster, show, hide, show more, show less, daha fazla
    göster, daha az göster. They are consulted only for an `<a>` that already has no address. Added class hints: a
    class token that contains "toggle"; a token that starts with js-open-, js-close-, js-toggle-, js-show- or
    js-hide-; the token `ot-sdk-show-settings`. Rejected as over-matching, and held by a test: "cookie" anywhere in
    a class (a link to the cookie policy is a link to content), any `js-` class, and `btn` / `button` (a link
    styled as a button is still a link). A control that most pages carry is part of the one accessibility note and
    is never also a "Shared header/footer: link … has no address" problem (decision 171 splits problems only).
178. **Images beside their own label and deliberate empty alt are not "meaningful images without alt text"; a folded copy of a real table is not a missing table (agent default, 2026-10-12).**
    STR-7 (FA-012): (1) an image is `beside_label` when the element that directly holds it (td, th, li, a, button,
    figure, span, div, p, label) has 1 to 60 characters of its own text and at most two images. With `alt=""` it is
    decorative and not counted; with no alt attribute it goes to the Info list ("other images have no alt
    attribute"). (2) The same kind of image (one folder, one file type) five or more times on a page is one row
    with `count` and `src_pattern`; the titles count images, not rows. (3) A deliberate `alt=""` is called
    meaningful only in a `<figure>` or for a file name that says chart, photo or the like, never for its size; the
    others are counted as "could not be classified". (4) A width and height of exactly 300×150 is not size
    evidence: it is the size a browser gives an image with none, and in the saved copies of four sites every one of
    the 2,087 images of exactly that size was an SVG. (5) The title says the two cases apart: "{n} likely
    meaningful image(s) on {p} page(s): {a} with no alt text, {b} with an empty alt" (the old title is still read
    in saved reports). STR-8 (FA-013): a `<div>` grid records `in_collapse` (it or an element around it has
    `data-toggle` or `data-bs-toggle="collapse"`, a class collapse, collapsed, collapsing or collapsible, a class
    containing "accordion", or `aria-expanded`) and its first 20 row labels; a real table records the first cell
    of its first 20 rows. A grid is not reported when it is in a collapse, or when half or more of its row labels
    are row labels of a table with header cells on the same page; those left out are in `evidence.grids_left_out`.
    What these rules no longer catch is in LG-64.

179. **The country on the plan card is the country of the run; an unknown market does not run silently on the United States (Owner, 2026-10-11; the details are agent defaults, 2026-10-12).**
    Owner: "Country = Turkey on the plan card, but all DataForSEO panels used 'United States, en; default market'.
    Pass the chosen country/language to every DataForSEO call; show the market on the plan card." Found by reading
    the code (what the four saved plans stored was not looked at: nobody opened the web database): the page saved
    the card's brand and country to the profile and then started a plan that was already built; a `.com` address
    suggests no country; "TÜRKİYE" and "Türkiye (TR)" were not keys of the country table and fell to the United
    States without a word. Rules now:
    (1) Card. Changing the brand or the country field makes the plan again (`POST /plans` with `brand_name` and
    `country`); Start is off meanwhile. What is typed on the card wins over the saved profile, which wins over a
    suggestion. (2) Server. `POST /audits` and `POST /plans/{id}/confirm` answer 409 `plan_changed` when the
    country or brand saved for the site differs from the plan's `paid_options` (compared as written, trimmed; a
    profile with no country or no brand is not compared). (3) Fingerprint. A plan with paid data holds
    `[location code, language, brand, country recognised, United States accepted]`; a plan with nothing paid does
    not, so the brand still does not change the fingerprint of a plan that asks no provider anything.
    (4) Matching (`insights.location_for`). Case, Turkish letters, other letter marks and punctuation do not
    matter; a name with a code in brackets is tried whole, then by its name, then by its code. The table gained
    the countries' own names and their Turkish names (Deutschland, España, Italia, Nederland, Almanya, …).
    (5) Unknown market. With search data ticked and a country that is missing or not recognised, the plan cannot
    start (`cannot_start.code = market_unknown`, `can_start` false, 409 from `POST /audits`) until the country is
    recognised or the person ticks "Use United States figures" (`paid_options.market_default_accepted`, in the
    fingerprint; the panel titles then say "United States, en; default market" as before). A plan with backlinks
    only has no market and is not blocked. This replaces the earlier behaviour (a muted warning line and a run on
    United States figures). (6) Suggestion. Without a typed or saved country the card suggests one from the
    `html lang` of the homepage in the last saved report of the site, else from the address ending; no page is
    fetched for it. The suggestion is the plan's country and is named as a suggestion on the card with its source.
    A bare `en` or `ar` suggests nothing. (7) Card lines (`search_data.markets`): the search data market, ChatGPT
    (always United States, English), backlinks (no market), and the suggestion. (8) Lighthouse. The run gives the
    crawl's final homepage (`access_data.homepage_url`) to `insights.audit_plan(home=…)`; it takes the typed
    homepage's place when it is on the same registrable domain, so the number of requests and the price do not
    change. The plan card still prices the typed address, so its cache state for that one row can differ from
    the run's. Key pages are sent as typed. (9) Command line. `--dfs-country` is matched the same way; a typed
    country that is not recognised is an error naming the value and some valid spellings, unless
    `--dfs-default-market` is given. Leaving `--dfs-country` out still means the United States, as its help says.
    The command line's Lighthouse request still uses the typed address: its plan is priced and approved before the
    crawl. Not confirmed: the whole flow has only run against mock transports (LG-65).

180. **The DataForSEO balance is fetched by itself, free, when a plan with paid data is built; the card warns and Start asks once; a refusal for no credit stops further requests in that run (Owner, 2026-10-11; the ten-minute reuse and the details are agent defaults, 2026-10-12).**
    Owner: "DataForSEO said 'account credits are insufficient' on every panel. Check the balance before the audit
    starts and warn on the plan card ('DataForSEO balance $0 — search data will be empty'), so I don't spend
    Firecrawl credits for a report without search data unknowingly." This changes an approved rule: the balance
    was fetched only when a person pressed the button; **building a plan now sends one automatic FREE provider
    request** (`/v3/appendix/user_data`, through the engine's client, recorded in the ledger as the free call it
    is). No paid request is ever automatic, and nothing is bought or raised because of a balance.
    (1) When. Only when backlinks or search data is ticked, credentials are set, it is not demo mode, and the last
    answer is older than ten minutes (`paid.BALANCE_REUSE_S = 600`). A failed attempt is an answer too ("unknown")
    and is also reused for ten minutes, so an account that does not answer is not asked on every keystroke. A
    failure never blocks the plan. The button still asks at once. (2) Warning (`balance_warning` on the plan view,
    read from the stored balance each time the plan is read): balance 0 → "DataForSEO balance $0.00 — search data
    will be empty."; below the plan's maximum → "… is below this plan's maximum of $X: some panels may come back
    empty."; no answer → "DataForSEO balance unknown (the account did not answer); this plan's maximum is $X.";
    enough, or a plan whose every figure is already saved (nothing to pay) → no warning. (3) Start. With a warning,
    `POST /audits` without `balance_choice` answers 409 `balance_decision_required`; the page asks once: "Run
    without search data", "Cancel", and "Run anyway" when the balance is low or unknown (at zero it is not offered:
    422 `balance_choice_not_offered`). (4) "Run without search data" starts the audit with `paid_state =
    "skipped"`: nothing is approved, reserved or sent at DataForSEO; the plan and the Firecrawl approval are
    untouched. The report's `dataforseo` section says why (`note`, `stopped.code = balance_at_start`, each check
    "not requested: the DataForSEO balance was $0.00 when the audit started. No request was sent."). Answers
    Maya's own cache already holds are still shown: they cost nothing. (5) During a run. The client raises
    `NoCredit` for provider codes 40200 and 40210; `panel.run_checks` sends nothing more after it. The refused
    check says "not assessed: the DataForSEO account has no credit for this request (provider code 40200).
    Nothing was charged." (when the answer reported no cost the sentence says the estimate stays counted, which is
    what the ledger does); the rest say "not requested: the DataForSEO account balance ran out earlier in this
    audit. No request was sent."; the section gets `stopped` and one `note`. Cached answers are still shown.
    The ledger rules are unchanged: nothing is retried, and a refused request costs what the provider reported.
    (6) Schema. `dataforseo` gains the optional `stopped` and `note` (same version 1.11: both are additions, and
    older reports are read unchanged). Saved reports are not rewritten: their "40200 Payment Required" lines are
    shown through the existing refusal wording. (7) Tests. The automatic request is switched off for the tests of
    other things (`tests/conftest.py`), whose made-up providers count what they receive; the tests of this rule
    switch it on. Not confirmed against the real provider: LG-65.
181. **Severity calibration from three real audits (Owner, 2026-10-12).** An http:// address that answers 200 (the
    site is served on both) is High; a redirect that goes to another http:// address first stays Low and says where it
    goes. No usable XML sitemap on a site of more than 50 URLs is Medium. A homepage with no `<h1>` is Medium and is its
    own finding ("The homepage has no <h1>"); other pages without one stay Low. A homepage with no Organization
    structured data is Medium. "Less than 30% of the text in the main content" stays Low.
182. **Findings are ordered by severity, then by what they stand in the way of, and only then by page count (Owner,
    2026-10-12).** `findings.IMPACT_RANK`: reaching, reading and indexing a page first; then links, duplicates,
    sitemaps, structured data and speed; then how the content is put; then guidance and tidiness (length bands, share
    of main content, alt text, link wording). Which rank a check has is an agent default. A saved report keeps the
    order it was written with.
183. **Shared-template grouping, widened (Owner, 2026-10-12).** Beside decision 171: an element most pages of one
    section carry (first part of the path, at least 5 pages: a menu per language) is shared; links without an address
    on exactly the same pages are one finding that lists them; a generic link ("tıklayınız") to one address on most
    pages is one finding; links with no text whose addresses differ per page but follow one file pattern
    (/wp-content/uploads/…/*.png) are one finding with the pattern and an example. A link to a page is never folded
    into a pattern. The section rule and the pattern (two folders and the ending) are agent defaults.
184. **A page row says a line once (Owner, 2026-10-12).** When two findings say the same thing about a page (a shared
    title seen by IDX-8 and STR-1), the row shows the line once and still counts both problems. The default line reads
    "Also affected by: “…” (site-wide: N pages)".
185. **An action says what to do (Owner, 2026-10-12).** "First five actions" takes the sentence of a fix that starts
    with an instruction; a condition in front is moved behind it. In Turkish, where the verb comes last, it takes the
    sentence that ends in an instruction. A canonical that points at another page's content names the page: "Make the
    canonical of /en/ point to /en/ itself." The list of verbs is an agent default, tested against every fix text.
186. **STR-7: a file-name hint is a whole word of the file name, and map tiles are decorative (reviewer's finding;
    Owner asked 2026-10-13).** The hint ("chart", "photo", "map" …) was searched in the whole image address, so every
    tile of an embedded Google Map counted as a "likely meaningful image" ("map" is in `maps.googleapis.com/maps/vt`).
    Now `name_hint` reads the last path segment only, without query, fragment or extension, percent-decoded, split
    into words at anything that is not a letter and at a lower-to-upper case change; a hint is a word of the list or
    that word plus "s". A `data:` address gives no hint. An image served by a map host (`MAP_HOSTS`, the host or any
    subdomain) is decorative whatever its name or size: with `alt=""` it is left out and counted in
    `map_images_left_out_count`; with no alt it goes to the Info list as "a map tile or map control (decorative)".
    The two Google hosts were seen in a real report; the rest of the host list is an agent default (LG-68). FA-014.
187. **A shared title is STR-1's finding only (Owner, 2026-10-13).** IDX-8 no longer reports "N indexable pages share
    the title …": STR-1 looks at the same pages (or more) and says it once. IDX-8 keeps identical text and
    near-identical content. Everything that reads the old finding stays (the per-page rule, the wording pattern
    `idx8.title`, the catalog note; both marked "saved reports only"), so a saved report still shows and translates it.
188. **IDX-2: "http:// is not redirected to https://" is one finding, by the fact (Owner, 2026-10-13). Amends 181.**
    One finding names every host that is not redirected ("No HTTP to HTTPS redirect on www.example, example"), and
    under it stands one line a host, the hosts that redirect correctly too. Its severity is the highest of its parts.
    High: a host answers 200 on http:// (`served_on_http`), or redirects to another tested host's http:// address
    that answers 200 (`redirects_to_http_served`): either way the site is read, whole, without encryption. This is
    what changes in 181, where a redirect to another http:// address stayed Low. Low: the other host goes on to
    https:// (`redirects_to_http_then_https`, one extra step), the redirect goes somewhere that was not tested
    (`redirects_elsewhere`), or the answer is neither (`other_status`). The probe still records one hop; where a
    redirect ends is read from the other host's own entry and nothing more is requested. Agent defaults: a start
    address typed and served on http:// (the probe's reason "the audited start URL is served over plain http") is
    `served_on_http` when it answered 2xx and `other_status` otherwise, with the reason kept in the evidence; a
    redirect to the other host counts as "that host's http:// address" only when the path is the one that was tested.
189. **A partial check that found nothing says so under "What else we checked"; it stays partial (Owner,
    2026-10-13).** "No problem found on the N pages read (M not read)" stands in front of the check's own summary in
    the printed report, in the card's list of checks and in the Markdown table. N and M are the report's one pair
    (decision 170); with M = 0 it reads "(the reading was cut short)". It is worked out when the report is shown, so
    nothing new is stored and a saved report shows it too. Which check (`coverage.clean_on_what_was_read`): a page
    check that is `partial`, has no finding and no review item, and whose every unanswered part is the pages that
    were not read. Decision 99 holds: it is not counted as in order and is still listed under "What could not be
    checked". Agent defaults: a check that looked at nothing or compared nothing does not say it, by its evidence
    (`pages_checked`, `candidates`; RND-2 `declared_facts`, STR-16 `pages_compared`, STR-22 `news_pages`, STR-23
    `job_pages` and `careers_pages_listing_openings`, PRF-1 `sample_size`, PRF-2 `attempts_counted`, each 0) or, where
    no count was kept, by a summary that says "the 0 …" or "All 0 …".
190. **Near-duplicates that look like variants of one product get variant advice (Owner, 2026-10-13).** A
    near-duplicate group is variant-like when every two of its pages are in the same folder at the same depth, their
    last address segments share at least two words and differ by one to three on each side, and their titles (without
    a site name after a title separator) share at least two words and differ by one or two on each side; words are
    compared without case or Turkish letter marks. Such a group is told "Add what sets each variant apart
    (ingredients, weight, use), or create a parent product page." instead of "Consolidate …", with a note that says
    why; title and severity are unchanged. Agent defaults: the word allowances (the owner said "1-2 words"; three are
    allowed in an address because one saved group differs by three there) and "every two pages", not only the pairs
    the comparison joined. Not calibrated: LG-69.

191. **Single-page audit mode (Owner, 2026-10-13).** Chosen next to Quick 50 and Standard 500 in the app, or with
    `--single-page` on the command line: only the address entered is read and checked. The page cap is 1, no link is
    followed, the sitemap is not fetched, the "important pages" are not added, and Firecrawl is sent that one address
    (plan: 1 page, about 2 credits: the page and robots.txt). A redirect of the address itself is followed. The facts
    of the site the page depends on are still checked and are labelled "Site-level": the robots.txt rules, the page's
    redirects and canonical target, HTTP to HTTPS on its host, llms.txt, the not-found answer. The title of every
    output is "Single-page audit: <URL>", and the headline, the outcome sentence and the coverage row each say that
    other pages of the site were not checked. Agent defaults: the checks that compare the pages of a site (IDX-5,
    IDX-7, IDX-8, STR-16, STR-17, STR-21, STR-22, STR-23) are "not assessed" and are left out of the count of page
    checks; when the address is not the site's root, STR-18 (the homepage's entity) is not assessed, STR-3's "the
    homepage has no Organization structured data" is left out, and STR-2's missing `<h1>` is an ordinary Low finding
    rather than the homepage's High one; the paid data panels and the answer-engine panel are unchanged, so a cited
    address check may still ask for other addresses when a citations file is given. Not run against a real site:
    LG-70.

192. **DataForSEO limits: confirmation above $2 an audit, never more than $5 an audit, $20 a day (Owner, 2026-10-14).
    Amends 133.** The $10 confirmation threshold and the $100 daily limit are replaced, and one audit has a hard limit
    of its own for the first time. The defaults are in `maya_audit/dataforseo/pricing.py` (`APPROVAL_THRESHOLD_USD`,
    `AUDIT_CAP_USD`, `DAILY_BUDGET_USD`); `MAYA_AUDIT_DATAFORSEO_CONFIRM_ABOVE_USD`,
    `MAYA_AUDIT_DATAFORSEO_AUDIT_CAP_USD` and `MAYA_AUDIT_DATAFORSEO_DAILY_USD` (environment, then `.env`) change
    them. The limit for one audit is kept by the ledger, in the same locked step as the daily one: what the audit's id
    already has settled or reserved, plus the next estimate, may not pass it, whatever total was confirmed. The
    request that would pass it is not sent, nor any after it; answers already saved are still shown; the report says
    which checks were left out (`dataforseo.stopped.code = audit_cap_reached`, a note, each check "not requested");
    the audit itself finishes. A resumed web audit keeps its id, so the limit covers every session of it; in a batch
    each site has its own. A plan above the limit is a warning that names the checks that would be left out, not a
    refusal. The reserve-then-settle ledger, the daily lock, the cache lifetimes and decisions 179 and 180 are
    unchanged. Agent defaults: a configured value that is not a number from 0 to 10,000 falls back to the default,
    as the daily one always did; a confirmation value above the audit limit is treated as the audit limit; the limit
    counts a settled call at what DataForSEO reported and an unsettled one at its estimate, as the day's does, so a
    plan estimated above $5 can still run fully when the settled costs come in lower; the plan card's "left out" list
    is worked out from the estimates and so may name more than a run leaves out; `stopped.after` is the last check
    asked for before the limit (null, and the note says "before its first request", when the first request alone
    would pass it); the web API's bound on `approved_max_usd` was 2 (the daily limit of the first web app), which no
    plan that needs a confirmation could pass, and is now 10,000, the largest value a limit can be set to; no new
    schema version, because `stopped.code` gained a value and no field changed.
193. **Maya calls only the endpoints on its list, and never the SERP API (Agent, 2026-10-14; the owner asked for
    "SERP API calls: 0" to be shown).** `pricing.ALLOWED_ENDPOINTS` is exactly the priced endpoints, and
    `DataForSEOClient.request` refuses any other path with `EndpointNotAllowed` before anything is priced, reserved
    or sent. A caller that brings its own price table must also name its endpoints (`allowed=`); until now such a
    caller could reach any path it priced. Paths under `/v3/serp/` (`pricing.FORBIDDEN_PREFIXES`) are refused whatever
    `allowed` holds. The plan card and `--dfs-dry-run` print one line for each DataForSEO service in the plan
    (Backlinks, Labs, AI Optimization, OnPage (Lighthouse), Business Data) with its paid requests and dollars,
    "SERP API calls: 0. Maya never calls the SERP API." and the three limits. The AI-mentions estimate
    (`llm_mentions/aggregated_metrics`) is now $0.10 a request plus $0.001 for each entry of the task's `target` list
    (at least one), not for 100 rows: two real requests with one target each settled at $0.101, and the plan for
    backlinks plus search data is estimated at $0.327156 where that audit settled at $0.327. Agent defaults: the
    service names, taken from the endpoint's path; a service whose answers are all saved is listed with 0 paid
    requests; the SERP count is counted from the plan's rows rather than written as a constant; the made-up provider
    of the demo now charges $0.101 for an AI-mentions request (it charged $0.107, above the new estimate). The
    one-row price rests on one audit: LG-71.
194. **The language guess: no addresses, no suffixes, and the declared language is heard (Owner, 2026-10-14, from the
    external review of 2026-10-13; the word list is an agent default). Amends 174.** `language.detect_language` takes
    the page's declared language (`declared`), as `heading_language` has since 174. Three things changed in what it
    counts (`language.words_of`): web addresses, e-mail addresses and any run without a space that has a dot between
    two letters ("ornek.com") are taken out first, so "com" is no longer a Portuguese word; a word with an apostrophe
    (' or ’) counts by the part before it, so "Trendyol'da" is one word and its suffix is not the Portuguese, Italian
    or Dutch "da"; and a stopword of another language that is an ordinary word in the declared one
    (`NOT_FOREIGN_IN`) is not counted for that other language. STR-9 and `text_assessable` pass the declared
    language; `block_language` (STR-12) reads words the same way. Agent defaults: the Turkish list gains `a e no na il
    van at as can para es un sus der den dem hat sur te er u`; a run with a dot between two letters is taken out even
    when it is a sentence end written without a space; French and Italian words written with an apostrophe ("l'eau",
    "dell'acqua") now count by their first part, which costs those languages some evidence. Still a homemade guess
    over eight word lists: LG-16 stays open. FA-015.
195. **IDX-3 asks a looping URL again before calling it a loop (Owner, 2026-10-14, from the error report; the counts
    are agent defaults).** After the crawl, `index_data.recheck_redirects` walks every loop of the crawl (at most
    `max_refetches`, 20) and always the homepage `redirect_recheck_attempts` more times (3), each hop its own request
    through the crawl's fetcher (purpose `redirect_recheck`, same pace, robots.txt, time limit), at most
    `redirect_recheck_max_hops` (10) hops, and saves the attempts in `IndexData.redirect_rechecks`. Every re-check
    loops: S1 "N redirect loop(s): the URL never resolves", the attempts in evidence. One ends on a 2xx page: S3
    Verified "N URL(s) intermittently redirect to themselves; the page loads on another try". Fewer than three
    answers and none loads (robots.txt, the time limit, a crawl that stopped early, a page read only by a page
    reader): S3 Inferred "N URL(s) redirected to themselves once; this could not be re-checked". A homepage that
    answered 200 in the crawl and redirects to itself on a re-check is in the intermittent finding. Agent defaults:
    an attempt that ends on an error status, a block or a redirect off the site counts neither way; a walk longer
    than 10 hops counts as a loop; no re-check is sent after a crawl stopped for a rate limit, robots.txt, an error or
    the network, or when robots.txt could not be read; the attempts stay inside check evidence (no schema change).
    A normal audit sends 3 more requests (the homepage's). Derived from one site: LG-72. FA-016.
196. **IDX-6 asks the other site before it says anything (Owner, 2026-10-14: "request the target once"; the cap and
    the wording of the note are agent defaults).** A link to another site at one of this site's paths is requested
    once per distinct address (`CrawlConfig.idx6_other_site_checks_max`, 10), purpose `other_site_link`, through the
    crawl's fetcher, after that origin's robots.txt is fetched and obeyed as `structure_data` does; no redirect is
    followed; it runs whether or not `check_external_links` is on. 2xx or 3xx: no finding, a count in evidence. 404
    or 410: S3 Verified "... and the other address returns {status}". Anything else (refused by robots.txt, the cap,
    the time limit, an error, 403, 5xx): Info Inferred "...; the other address could not be checked". New
    `CrawlConfig.brand_family_domains` (CLI `--brand-family-domain`, repeatable; the plan card's field "Other domains
    of the same brand", saved in the profile and part of the plan's fingerprint): a link to one of them, a subdomain
    of one or a host with the same registrable domain is never requested and never reported (counted in evidence).
    Values are host names only (`urls.clean_hostname`); anything else is refused (CLI usage error, web 422
    `invalid_brand_family_domains`), at most 20 in the app. "Leads nowhere" is no longer said by IDX-6 (STR-19's
    "lead nowhere" title, kept for saved reports, is another check). The old IDX-6 title stays readable for saved
    reports. Not yet validated against real sites: LG-73. FA-017.
197. **STR-21 reads the footer before it calls a basic page missing (Owner, 2026-10-14; the word lists are an agent
    default).** About gains nine Turkish names (`hikayemiz, bizim-hikayemiz, tarihce, tarihcemiz, bizi-taniyin,
    ekibimiz, vizyon-misyon, misyon-vizyon, sirket-profili`), matched in a page's address and in a footer link's text
    only (`small_site.ADDRESS_ONLY`): in a title "hikayemiz" would match blog posts. Contact gains `iletisim-bilgileri,
    bize-yazin` and FAQ `sik-sorulan-sorular, merak-edilenler`, matched as the other words are. Everything is compared
    the Turkish way (folded, without diacritics). `html_links.extract_link_edges` marks an edge `"footer": True` when
    a link to that target sits inside a `<footer>`. Before a kind is called missing, the footer links of the pages
    read are looked at, by their text and their address: a match that was not read is said as "{kind}: linked from
    the footer ({path}), not among the pages read." and is never "missing". Agent defaults: a footer match that was
    read counts as that kind found; when no kind is missing and one is only linked, the check passes and its summary
    says so ("No basic page is missing among the N page(s) read."); the sentence is in the check's summary and the
    link in `evidence.linked_from_footer_not_read`, not in a finding's notes; the finding's own note is unchanged;
    whether the linked page answers is not tested. FA-018.
198. **A shared element is called by where it is, and a section is not the whole site (Owner, 2026-10-14; the naming
    of a block and the grouping are agent defaults). Amends 171 and 183.** A shared-element finding's title begins
    with "Shared header/footer" only when the markup puts the element in a `<header>`, a `<nav>` or a `<footer>`.
    Otherwise it begins with the name of the block around it, "“div.post-related” block", when the markup names one,
    and with "Repeated block" when it does not (`shared_elements.label`). The block is the nearest element around a
    link that has a class or an id (`html_links.block_name`). `shared_elements.split` still calls an element shared
    when most pages of one section carry it (183), and now says which keys are shared by section only
    (`Shared.sections`): their finding has an ordinary page scope (so its severity, priority and card are a page
    finding's) and says "on N page(s) of /section/", and the web app says "Affects N pages of /section/", never
    "Affects the whole site". It is still one element and one line (the owner's rule of team-preview-12: wider
    grouping, no repeated lines): "Problems by page" lists it once, in the first row beside the site-wide problems
    (`report.grouped_once`, `whole_site.finding_ids` and `whole_site.shared_elements`, whose `element` then holds
    `section`), and it adds no line and no count to any page's row. That row is called "Whole site or one section"
    when it holds such an element, in the Markdown report, the web app, the practical view and the PDF. Before,
    `finding()` gave every shared element the scope of the whole site. Nameless links in one named block on the same
    pages are one finding: "“{block}” block: N link(s) have no text (on M page(s))". Agent defaults: a block is
    named by its tag and its first class that holds no digit ("post-4711" is one post), else by such an id; only a
    nameless link records its block, so a shared image, heading or generic link outside the header and footer is
    "Repeated block" (a generic link is "Shared header/footer" by its edge's `nav` or `footer` mark; a link without
    an address by the region its page analysis now records); "of /section/" is said only when every page that
    carries the element is in that one section (otherwise the element holds `section: ""` and the web app says
    "Affects N pages"); a per-language menu (183's own case) is therefore one grouped line that says "of /tr/", with
    the scope of its language's pages; the first row's name "Whole site or one section"; the kind of a block finding stays `link_no_text`, so no
    schema version changes (`block`, `section`, `hrefs` and `links` are additions inside `evidence.shared_element`).
    The bar itself is unchanged and uncalibrated: LG-61. FA-019.
199. **The homepage is the root that was read when the start address failed (Agent, 2026-10-14, from the error
    report).** `access_data.homepage_url`: the first depth-0 page that answered 2xx; else the site's root
    (`origin + "/"`) when it was read with 2xx; else the start address. A deep start address that answers 200 is
    unchanged (single-page mode, decision 191). STR-18, when the homepage still has no readable record, compares every
    request made for its address (`perf_data.attempts_by_url` and the IDX-3 re-checks) and, when two gave different
    statuses, is not assessed with "Two reads of the homepage disagreed: one answered {a}, another {b}. The title was
    not judged." A homepage that was read without a title keeps its sentence. FA-020.
200. **STR-8 says which grid, leaves a page with a real table alone, and reports an empty table (Owner, 2026-10-14;
    the selector's form is an agent default). Amends 178.** Each `<div>` grid the page analysis records carries
    `selector` (its tag, id and classes after up to two elements around it: "main > section#plans > div.grid") and
    `first_row` (its first row's cells, joined with " | "), and a page's row says them: "<div> grid at {selector};
    first row: “{first_row}”". A page that has a `<table>` with `<th>` and at least 2 rows
    (`structure.REAL_TABLE_ROWS`) is not flagged by either grid finding; its grids go to `evidence.grids_left_out`
    with the reason. New finding, S4 (Low), Verified: "N page(s) contain an empty <table> element", for a `<table>`
    with no row in the HTML the server sent, with the note that a script may fill it; pages in the RND-1 gap are
    skipped, as for the grids. Agent defaults: the rules of 178 (a grid inside a collapse; half its row labels in a
    real table) are tried first and keep their own reasons; a table whose only row is its header row does not excuse
    a grid; the empty-table finding's rationale is Hypothesis, as the grid findings' is; a report saved before the
    selector was kept shows the page line it always had. No schema version changes: the additions are inside page
    analysis and finding evidence. The grid thresholds are still uncalibrated: LG-23. FA-021.
201. **The brand is typed, else the site's own name, else the address in the site's words, else none (Owner, 2026-10-14,
    from the error report; the thresholds and the two-word rule's details are agent defaults).** `maya_audit/brand.py`:
    `resolve(result, typed)` gives `{name, source, confirmed, found_in, pages}`, written to the report as top-level
    `brand` (schema 1.14). Order: (1) the name typed on the plan card or saved for the site (`typed`, the only
    confirmed one); (2) the site's own name (`site`) from STR-5's sources: og:site_name that is not a page title, the
    Organization or WebSite name that describes this site, the first or last part of a title cut at a separator; the
    name on the most pages wins when it is on at least 3 pages or on half of the pages read, and two names on as many
    pages from as good a source give none; (3) the address's own label split into words (`domain`), at "-" and "_" and
    then into the words of the site's titles and headings, accepted only when every piece is such a word (Turkish
    letters are compared without their marks); (4) none. `apply_relevance` and the cover use the same order. At (4)
    DFS-4 and DFS-5 keep their plain table (no Relevance column, no unrelated group) and say "The brand name could not
    be confirmed, so these keywords are not sorted into brand searches and other searches."; `dataforseo.relevance`
    gains `sorted`, `brand_source` and `brand_confirmed`. For a brand of two or more words a search is a brand search
    when it holds two of its words, its first word, or the whole name written as one word (the glued address); one
    later word alone ("yemek tarifleri") is judged as any other search, and the brand's words then count as the
    site's own subject words. A one-word brand is sorted as before (decision 158 and the rules before it). The plan passes `brand`
    only when it was confirmed: the card still shows the suggestion from the address, labelled as one, but the run is
    not given it, so the Business Profile lookup is "not requested" until a name is typed. The cover: a confirmed name
    with no label; a name read from the site with "Name read from the site's own pages ({source}); not confirmed by
    you."; the address split into words, or the address itself, with "Name taken from the website address; no brand
    name has been confirmed." Agent defaults: 3 pages or half; a tie gives none; a title part of up to five words;
    generic titles ("home") are never a name; pieces of at least 2 letters; the batch command does not pass the CSV's
    name as typed (it keeps the site's own name). A 1.13 report has no `brand` and its cover shows the address, as
    before. LG-74, FA-022.
202. **A start address that answered with an error is said first (Owner, 2026-10-14, from the error report; the
    conditions are agent defaults).** `report.problem_summary` gains `start_address` = `{entered, status,
    audited_from}` (schema 1.14) when the address the audit was started on answered 400-599 and the homepage
    (decision 199) is another address that was read with 2xx. "The start address you entered returned {status}
    ({path}). The audit was run from {from} instead." comes before the counts of the headline (so in the Markdown
    report), as a "Start" line of the text header, before the web summary's headline (and as `start_address` in the
    summary view) and on the PDF cover. Agent defaults: not set in a single-page audit (there is no other page, and
    the outcome already says the page could not be read); not set when other pages were read but the root was not; a
    3xx start address is not a failure. Reports of 1.13 and before are read unchanged.
203. **A finding of a rule not yet validated on real sites is labelled "Unverified check" (Owner, 2026-10-14, from the
    error report; which finding each launch-gate item covers is an agent's reading of docs/LAUNCH-GATE.md).**
    `maya_audit/launch_gate.py` holds `LABELS`: a check, optionally a pattern of its finding titles (or only the
    findings one shared element causes, matched on `evidence.shared_element`), the launch-gate items, and a mode.
    `apply(checks)` runs after the single-page rules in `audit.run_audit` and again after a page reader replaced the
    content checks; it changes nothing twice. "label" adds the items to the finding's `launch_gated` (beside the bot
    registry's reasons, which ACC findings already carry); "off" leaves the finding out, lists its title in the check's
    `evidence.left_out_unverified` and adds "N finding(s) from an unverified check were left out." to the check's
    summary (a check left with no finding is then partial, with that part not assessed). Every row is "label": nothing
    is hidden. `NOT_LABELLED` gives, for every other OPEN item, why no finding carries it (a gate, a mode, a cost, a
    measurement Google reports, the Turkish cover's own note); `AT_SOURCE` names the items a finding carries where it is
    made (the registry's LG-03, LG-05 to LG-07; ANS-4's LG-30). A test reads docs/LAUNCH-GATE.md and fails when an OPEN
    item is in none of the three, or when one of them names a VERIFIED, CLOSED or BY DESIGN item; LG-41 to LG-44 gained
    their status cell for it. Shown: a chip and its sentence on the web card ("Unverified check" / "This check has not
    yet been validated on real sites ({items}). Confirm the finding by hand before acting on it."; summary item
    `unverified`, built as page elements), a line in the printed report, "**Unverified check:** …" in the Markdown
    (English, as every download), and `LAUNCH-GATED:` in the text report as before. No schema version change for this
    part (`launch_gated` existed). Agent defaults: review items are not labelled; a finding whose items are only the
    registry's reasons shows them in place of item numbers; the healthy findings (a broken internal link, a missing
    title) carry no label.
204. **An answer that says "OK" and sends nothing is an empty page, and a server error message is reported (Owner,
    2026-10-14, from the error report, item 1; the rule's text and visibility conditions are agent defaults confirmed by
    the lead).** `classify.empty_response`: a 2xx answer, HTML or with no content type, not cut short, under
    `CrawlConfig.empty_response_max_bytes = 512` bytes, with no non-empty `<title>` and no visible text once scripts,
    styles, noscript, templates, comments, whitespace and zero-width characters are left out. The size alone is not the
    rule (agent default): the test sites' pages are 100 to 200 bytes of real HTML, and a short real page is a page. An
    empty page keeps `fetch_class` ok (it is the site's own answer; no new FetchClass value), gets
    `content_checks_eligible` False, `analysis.empty_response = {body_bytes, limit}` and "empty response: status 200
    with N bytes (under 512)" in its classification evidence, and `readable_document()` is False, so the content checks
    (STR, RND, IDX-8 and the others), PRF-1's sample and the page reader leave it out. It is refetched once with the 5xx
    and transport failures, within `max_refetches`. IDX-1 reports "N page(s) answer with an empty page (under 512
    bytes)", Verified, owner developer; S1 when the homepage or a key page is empty or empty pages are at least 10% of
    the HTML pages checked, else S2; empty on some attempts only is an observation. Agent default: a page that could not
    be refetched (the cap) and was empty once is a finding, since every attempt made was empty. INT-1's clean sentence
    says how many were empty ("N fetched pages were answered by the site itself, none blocked or rate-limited; E of
    them were empty …") and its evidence gains `empty_responses`; its state is unchanged. A page reader's 2xx document
    that is empty by the same rule is outcome "error", cause `empty_document`. `classify.error_disclosure` reads the
    first 64 KB of an HTML or text answer of any status and counts a server error message only with both an error marker
    (PHP "Fatal error", "Parse error" or "Warning" … "on line N", "Uncaught", "Traceback (most recent call last)",
    "Stack trace:", "Server Error in '/' Application") and a path on the server (`/home/…/`, `/var/www/`,
    `public_html/`, `C:\inetpub`), and only in a 5xx answer, a body under 4 KB, or before the page's `<html>` or
    doctype, so an article quoting an error is not reported. IDX-1 S3, Verified: "N page(s) show a server error message
    with the server's file paths", the quoted line with the account folder cut to two characters (`/home/u8…/`); the
    raw match is kept in memory only (`PageFetch._error_text`, never written). It also reads the ACC-4 user-agent check's
    answers (205). Agent defaults: the why-note of the error finding ("An error message on a live page shows visitors and
    crawlers how the server is built …") and the expected results ("every page that answers 200 sends its content", "the
    live server shows no error details"). Requests: up to 20 more refetches within the existing cap. Single-page: the
    rule applies to that page. No schema change. FA-023; LG-75, LG-76.
205. **Without ownership, ACC-4 compares a browser with Googlebot's user agent, once each (Owner, 2026-10-14, from the
    error report, item 7; amends spec §8 Q1; how ownership is verified, decision 8, is unchanged).** When the full ACC-4
    does not run because ownership is not verified, `probes.run_ua_check` asks at most `CrawlConfig.ua_check_urls = 3`
    addresses (the homepage, one empty page if there is one, then the first page of the largest page template), each
    once with the browser user agent and once with Googlebot's, purpose `ua_check`, header `X-Maya-Probe:
    ua-differential`, never retried. The Googlebot request is sent only where robots.txt allows both Googlebot and
    Maya's own token; otherwise the pair is "not assessed (robots.txt)" and neither request is sent (agent default: the
    browser request is not sent either). A browser answer that is not the site's own (blocked, rate-limited) leaves the
    pair not assessed and Googlebot is not asked (agent default). Results are in `crawl.access.ua_check`, judged with
    `probes.compare`: Googlebot 5xx where the browser got 2xx is S2; 403, 401, 429 or a challenge is S3; the same status
    with a body under half or over twice the browser's is Info; all Estimated, all with the note "Measured with a
    spoofed user agent from Maya's own address, not by Google …". ACC-4's summary says "Firewall blocking was only
    partly assessed …", and a clean result is partial (coverage part "other AI crawlers' user agents"). INT-4 keeps
    these requests apart from Maya's own and is compliant without ownership when there are at most 2 ×
    `ua_check_urls`, all tagged, with only those two user agents, and robots.txt allows Googlebot for every Googlebot
    request; its summary counts them. Agent defaults: the check is off when `probes_enabled` is False or
    `ua_check_urls` is 0, when robots.txt stops all requests, and after a crawl the site stopped with a rate limit; the ACC-4 why-note and the fix ("Allow Googlebot in
    your WAF …") are reused or adapted from the full check. Requests: 6 to the audited site. Single-page: that address,
    2 requests. No schema change (request purpose `ua_check` is a new value). LG-77.
206. **IDX-5 judges every sitemap URL, reports sitemap files that could not be loaded and addresses written wrongly
    (Owner, 2026-10-14, from the error report, items 10 and 17; the caps are the owner's, the light request, the stopping
    rules, the sample order and the wording details are agent defaults confirmed by the lead).** A new last data
    collector, `sitemap_check` (after the performance rounds, run past the deadline like the structure data),
    `index_data.check_sitemap_urls`: a URL the crawl read is judged from the crawl; a file (`urls.non_page_kind`: a
    nested sitemap, an image, a PDF) is left out; a URL robots.txt disallows is counted as disallowed and not asked; every
    other one gets one light request (`light_request`, purpose `sitemap_check`: GET, at most 64 KB, no redirect followed,
    the fetcher's pace, time limit and URL safety; status, Location, size, X-Robots-Tag, meta robots and canonical from
    the first 64 KB, `classify.empty_response`, `classify.error_disclosure`). `CrawlConfig.sitemap_check_max`: the
    command line gives 200 below 500 pages (Quick, the default), 1,000 from 500 (Standard), 0 with `--single-page`, or
    `--sitemap-check-max N` (0 to 1000); the web modes take it through `cli._crawl_config`. Above the cap,
    `section_sample` takes one URL of each top-level section in turn, each section in sitemap order, the same every run.
    A 429 stops the requests (decision 52), so do 3 blocked answers in a row and the time limit; the rest is said as not
    checked. The data is in `crawl.index.sitemap_check`. The share counts redirects, 4xx, 5xx, empty pages and noindex;
    canonical elsewhere and disallowed are in the breakdown, not the share; a blocked answer or no answer is not counted
    (agent default; before, a crawl page with a transport error counted as bad). Threshold and S3 unchanged. Every URL
    checked: "{bad} of {n} sitemap URL(s) ({share}) are not live, indexable pages", Verified. Not every URL: "… checked
    ({share}) …; the sitemap lists {n}", Estimated, with the sample note (or which URLs were not checked and why) and
    LG-78. The old title stays readable (`SAVED_ONLY`). A URL the cap left out is a sample by design and not a coverage
    part; URLs a 429, blocks, the time limit or an early crawl stop left out are. IDX-1's empty-page and error-text
    findings count what the light requests found (not refetched). A sitemap file named in robots.txt or a sitemap index
    (`CrawlResult._sitemap_named_in`, in memory) that answered 4xx/5xx, did not arrive or could not be parsed as a
    sitemap is S3, Verified, sitewide; the `/sitemap.xml` guess is never reported unless named, and neither is a redirect
    off the site nor a file over Maya's own size limit (agent defaults). Read from `result.sitemap_urls`, no request: an
    address with a "?" where a letter was lost or with a space is S3, Inferred, sitewide, each "?" replaced with ç, ğ, ı,
    ö, ş or ü and named when that word is in the visible text of the pages read ("“?deme” is probably “ödeme”; …"),
    else the general sentence; letters that are not percent-encoded are Info. The time estimate
    (`config.estimated_duration_s`, so the default time limit and the web plan's minutes) adds `sitemap_check_max` ×
    (delay + 0.3) s. Requests: 0 to 200 (Quick) or 0 to 1,000 (Standard) to the audited site. Single-page: off, IDX-5 not
    assessed as before. No schema change (request purpose `sitemap_check` is a new value). LG-78, LG-79.
    *Run 4 (lead's brief, 2026-10-14; agent wording):* when the sitemap check judged every sitemap URL (nothing left
    unchecked, no sample), IDX-5 no longer carries the crawl's "pages found but not read" part: the URLs the crawl did
    not read were asked with a light request, so the page cap leaves no gap in IDX-5's answer
    (`coverage.sitemap_fully_checked`). When it sampled, or a 429, blocks, the time limit or an early crawl stop left
    URLs out, the part and the wording above stay. Other page-reading checks keep the part.
207. **RND-7 is page structure, not JavaScript rendering (Owner, 2026-10-14, from the error report, item 20; the details
    are agent defaults).** The main content's share of the page text keeps its id RND-7 (saved reports, the comparison
    view, LG-22 and the wording keys use it). `maya_audit_web/summary.py` holds `AREA_OF = {"RND-7": "STR"}`, which
    `_family` reads before the id's prefix, so its finding rows, its check and the scorecard are under "Page structure
    and markup" in the web result, the printed report and the follow-up answers, for a saved report too when it is
    opened. The Low finding's fix is now "Mark the page's own content with one <main> element, so the menu, footer and
    sidebars sit outside it. This is page structure: no JavaScript change is needed." (Turkish beside it); the old fix
    keeps its Turkish so a saved report still reads. Both RND-7 findings show the `<main>` example. The engine's
    Markdown and text reports do not group by area and are unchanged. Agent defaults: within its new area RND-7 is
    listed in id order, so before the STR checks; the area filter of the findings search follows the same mapping. No
    schema change. FA-024.
208. **ACC-8 reads the whole llms.txt and follows its links (Owner, 2026-10-14, from the error report, item 21; the
    details are agent defaults).** `llms.txt` and `llms-full.txt` are decoded up to 1 MB (before: 4 KB); their Markdown
    links `[text](url)` are read once each. In the `sitemap_check` collector, after the sitemap URLs,
    `access_data.check_llms_links` judges each link to this site from the crawl, then from the sitemap check's light
    requests, otherwise with the same light request (purpose `llms_link_check`), at most
    `CrawlConfig.llms_link_checks_max = 50` in all, robots.txt obeyed, with the same stopping rules. Links to other
    sites are not checked until the other-site check (run 4) and are a coverage part ("links to other sites are not
    checked yet"). `crawl.access.llms[i].links` holds the counts, the kinds and up to 40 rows (the ones that do not work
    first). One or more links leading to an empty page, a redirect, a 4xx or a 5xx: S4, Verified, "{bad} of {checked}
    link(s) in {file} lead to pages that do not work ({kinds})"; noindex is not counted (agent default). A first
    non-empty line that does not start with "# ": Info, with the note "First line: “…”." A missing file is still a pass;
    the check's summary is unchanged. Single-page: presence and the first line only (site-level), no link requests. The
    plan's time estimate does not add the 50 link requests (agent default: the spec names only the sitemap check).
    Requests: 0 to 50. No schema change. LG-80.
209. **STR-10 says when the share image is the site icon or too small (Owner, 2026-10-14, from the error report, item
    15; the details are agent defaults).** An og:image whose address ends in `.ico`, or whose answer is
    `image/x-icon` or `image/vnd.microsoft.icon`, is the site icon: S4, Verified, "{n} page(s) use the site icon as share
    image (og:image is a .ico file)", told from the address with no request needed (an icon that redirects is still
    reported). The og:image request (GET, at most 64 KB: before, the same request kept only the status) now also reads the
    image's width and height from its first bytes (`structure_data.image_size`: PNG, GIF, JPEG, WebP, ICO, no library),
    kept in `crawl.structure.links[url].image`; under 200 × 200 (either side) is S4, Verified, "{n} page(s) have a share
    image smaller than 200 × 200 pixels". An unknown size (another format, a JPEG whose size marker lies past 64 KB) gives
    nothing. A page whose og:image is the icon is not also reported as too small (agent default). An og:image on this site
    that redirects on this site is followed, at most 3 hops, within `str_link_checks_max` (`hops` in the entry); a
    redirect to another site is not followed. Both fixes ask for an image of at least 1200 × 630. Single-page: applies.
    No schema change. LG-81.
210. **STR-13 counts invisible characters in the main text (Owner, 2026-10-14, from the error report, item 16; the
    threshold is the owner's, the rest agent defaults).** `analysis.invisible_characters` counts U+200B, U+200C, U+2060,
    U+FEFF and U+00AD in the page's own text (`_content_blocks`: header, menu, footer and sidebars left out), and apart
    those with a letter on both sides; it is written as the page's `analysis["invisible_chars"]` (`count`,
    `inside_words`, `by_character`, up to 3 `examples` with the character written as [U+200B]) only when there is one.
    U+200D is not counted (emoji need it). From 10 on one page: S4, Verified, owner content, "{n} page(s) have invisible
    characters in the main text ({count} in all)"; the count inside words does not decide (agent default). STR-13's
    summary is "N finding(s)." when only this finding is there. No schema change. LG-82.
211. **Links to other sites are checked by default (Owner, 2026-10-14, from the error report, item 18; amends 35; the
    caps, the order and the "could not be checked" rules are the lead's spec, the rest agent defaults).**
    `CrawlConfig.check_external_links` is True; `--no-external-links` turns it off (`--check-external-links` is still
    accepted and changes nothing), and the web app's demo mode turns it off (`demo.OVERRIDES`). `maya_audit.external_links`
    holds one budget for the audit (in memory, `CrawlResult._external`; its summary in `crawl.structure.external`): at most
    `external_link_cap` = min(`external_link_checks_max` 100, `external_link_checks_base` 20 + pages read) requests, the
    base alone (20) in a single-page audit, and at most `external_sites_max` 25 other origins. Each other origin's
    robots.txt is fetched and obeyed before anything else there and counts toward the cap; robots.txt that gets no answer
    (a host that does not exist, a timeout) means that site is asked nothing. Order: sameAs profile links first (asked
    also when the check is off, at most `same_as_checks_max` 10, as decision 196 does), then og:image, then hreflang
    alternates, then STR-7's image files on other sites (agent default: they were already requested with the flag on and
    now count toward the same cap), then the other links of the pages read, the most-linked first (by pages, then
    links, then the order found). A link is asked with one HEAD (`Fetcher.get(method=...)`, purpose `external_link_head`);
    405 or 501 is asked again once as a GET of at most 4 KB (purpose `external_link_status`, as the og:image and hreflang
    GETs). Broken is 404 or 410 only; 2xx and 3xx work (no redirect is followed); 401, 403, 429, 999, 5xx, another
    status, a timeout and a host not found are "could not be checked" with their reason, never broken. A site that
    answered 429 or gave no answer is asked nothing more (agent default). An address IDX-6 already asked (decision 196) is
    not asked again; a link to the site's own other hosts (www, a subdomain) or to a brand-family domain is not "another
    site" and is not asked. Every request goes through the crawl's fetcher: Maya's user agent, the pace, the time limit
    and the URL safety rules; nothing goes through Firecrawl or DataForSEO, and a failed lookup changes nothing about the
    audit's own network verdict (it is recorded on that link only). New IDX-6 finding: S4, Verified, "{links} link(s) to
    other sites on {pages} page(s) return 404 or 410", one finding for all such links, links IDX-6's other-site-at-this-
    site's-path finding already reports left out; the summary adds "Links to other sites: N checked, N gone (404 or 410),
    N not checked." (or "Links to other sites were not checked (--no-external-links)."), and the evidence counts what was
    not asked and why (no coverage part: an answer a site refuses is not a gap of this audit, agent default). llms.txt's
    links to other sites (decision 208) now go through the same check within the same cap: 404 or 410 is "not found",
    anything 2xx or 3xx works, the rest is a coverage part with its reason. The time estimate (`config.estimated_duration_s`,
    so the default time limit and the web plan's minutes) adds (delay + 0.3) s for each request of the cap: about 1.5
    minutes in Quick (70) and 2.2 in Standard (100); demo mode adds nothing. Requests: none to the audited site; up to 70
    (Quick) or 100 (Standard) to other sites, 20 in a single-page audit (that page's links), plus at most 10 for decision
    196's check as before. No schema change (`external_link_head` is a new request purpose). LG-83.
212. **A batch's brand is the name in its CSV (Owner, 2026-10-14; amends 201's agent default).** `maya-audit batch` gives
    each row's name to `brand.resolve` as the typed name, with the pages Firecrawl read when it read them, and passes the
    result to `build_report`; the report's `brand` is then `source: "typed"`, confirmed. Before, a batch report took the
    site's own name and ignored the CSV. `crawl` without `--dfs-brand` still takes the site's own name. A batch runs no
    keyword relevance (it has no search-data option), so there is no relevance call to pass the brand to.
213. **The printed report labels an unverified note and top problem (Owner, 2026-10-14, Round 1 follow-up; the place is an
    agent default).** On the printed and PDF report's one-line lists, the notes and the top problems of the summary page,
    a finding with launch-gate items shows `Unverified check (LG-22)` after its title (`result.unverified.label`, both
    languages; the items as on the card). A finding with none shows nothing. The issue cards keep the sentence of 203. Agent default: a finding whose items
    are only the bot registry's reasons (English sentences, given in full in the card's note) shows the label alone.
214. **The browser component cannot be skipped, and Playwright is capped below 1.64 (Owner, 2026-10-14; the cap is raised
    only after a retest).** TEAM-SETUP step 5 says in bold that without it the PDF button gives the app's own message
    and pages are not rendered with JavaScript; the command is `.venv/bin/python -m playwright install chromium`, run
    again after every reinstall or update. The dev, render and team extras require `playwright>=1.45,<1.64`:
    team-preview-14 was tested with 1.63.0, and 1.64 needs a new Chromium build. Raise the cap only after a retest with
    the new version.
215. **Empty and failing pages are said once, under IDX-1 (Owner, 2026-10-15, from the team-preview-15b real-site test,
    item 1; the details are agent defaults).** `maya_audit.root_cause.group` runs once the checks are built (before the
    launch gate) and again after a page reader replaced the content checks; it changes nothing twice. E is the
    addresses of IDX-1's empty-page and server-error-text findings; IDX-1 also counts empty answers to ACC-8's own
    light requests (`llms_link_check`, kept in `sitemap_check.llms_rows`). IDX-5 keeps its share and its 10%
    threshold, counted with E; E leaves the finding's pages (`scope`, `bad_urls`, `reported_under_idx1`) and the title
    gains "; {same} of them are the empty or failing pages reported under IDX-1". When the share without E (the rest
    over the same URLs checked: agent default) is at or under the threshold the finding is left out, IDX-5's summary
    says so and IDX-1's line says it. ACC-8 leaves E out of its links finding (title gains "; {same} of them lead to the
    empty pages reported under IDX-1"; `not_working_urls` holds every link that does not work) and leaves the finding
    out when only E remains (its summary is not changed: the presence finding stays). IDX-1 gains
    `evidence.also_listed_in` ([{where: sitemap | llms.txt | acc4, count, finding_id}], `left_out` when IDX-5 was left
    out, `not_in_share_finding` when IDX-5 had no share finding) and `evidence.by_section` (first path segment, at most 3
    examples, for a finding of 2 pages or more), printed as detail lines in every output, both languages. The ACC-4 line
    ("Also in ACC-4's comparison of Googlebot's user agent with a browser") and the two other sitemap lines are agent
    wording. Finding ids are made again for a changed title. No schema change.
216. **ACC-4 does not blame a firewall when the browser also got an empty or error page (Owner, 2026-10-15, from the
    team-preview-15b real-site test, item 2; amends 205; the rule was written by an agent from the owner's report).**
    In `probes.ua_verdict` the browser's answer is a real page only when it is 2xx, is not an empty page
    (`classify.empty_response`, decision 204) and shows no server error text (`classify.error_disclosure`). Otherwise
    the pair's outcome is `browser_not_real`: not assessed, no finding and no WAF fix, with the reason "the browser also
    got an empty or error page: a server fault (see IDX-1), not a difference made for Googlebot" (Turkish beside it),
    also given as the coverage part "Googlebot user-agent check on sampled URLs". Both answers stay in
    `crawl.access.ua_check.pairs`, so the error text Googlebot's user agent was shown is still IDX-1's finding (204).
    `access_data.build_ua_check_sample` no longer picks an empty page: after the homepage it takes the pages of the
    largest page template in order (then the next template's). Each observation records `empty_response`. Agent
    defaults: the Googlebot request is still sent when the browser's answer was not real (its error text feeds IDX-1);
    the owned-site probes (`run_probes`) are unchanged. Requests: still at most 6. No schema change. FA-025.
217. **A redirect loop is walked once more with the site's own cookie (Owner, 2026-10-15, from the team-preview-15b
    real-site test, item 3: the brief approves one cookie-jar re-walk, amending the "never store cookies" promise; the
    details are agent defaults).** When every one of the three cookie-less re-checks of decision 195 loops, IDX-3 walks
    the URL once more (`index_data._walk_again(cookies=True)`, purpose `redirect_recheck_cookies`, Maya's own user
    agent, at most `redirect_recheck_max_hops` = 10 hops), sending back as a Cookie header only the cookies this site
    set during this walk (`RawResponse.set_cookies` holds each Set-Cookie header as sent, never comma-joined; the name
    and value are kept, the attributes ignored). The cookies live inside that one walk and are then discarded; each hop
    records `set_cookie` and `cookie_sent` (true or false), and the request log shows "(the site's own cookie, sent back
    once; value not kept)" in place of the value. No cookie value is stored or written. A walk that ends on 2xx with a
    cookie sent is the S3, Verified finding "{n} URL(s) loop for visitors without cookies (crawlers); with the cookie
    the site sets, the page loads", with the fix "Make the address answer without a cookie: …" and the note "Search and
    AI crawlers do not keep cookies. …" (both languages); the URL leaves the S1 loop. A walk that still loops leaves S1
    as it was (its evidence gains `cookie_walks`). Agent defaults: a loop is coming back to an address with the same
    cookies; a cookie walk that loads with no cookie to send counts as one more cookie-less load (intermittent, 195);
    only looping URLs are walked, not the homepage's own re-checks. The bot-information page says cookies are "kept for
    one re-check only, never stored". Requests: at most 10 more per loop, only when it loops. No schema change
    (`redirect_recheck_cookies` is a new request purpose). FA-026, LG-84.
218. **A problem on many pages whose page line only repeats its title is said once (Owner, 2026-10-15, from the
    team-preview-15b real-site test, item 4; the thresholds are agent defaults, LG-85).** In `report.problem_summary` a
    page-scope problem goes in the first row and on no page's row (`report.said_once`) when its line under every page
    it lists would be the generic "Also affected by" (kind `affected`) and it is on 10 pages or more, or on 60% or more
    of the pages read and at least 5. A problem whose page line says something about that page stays on the rows. Scope,
    severity, the cards and the headline counts are unchanged; decision 198's first-row label is unchanged. The web's
    practical view and the PDF read the same rows. A saved report keeps the table it was saved with.
219. **Measure each step; robots.txt samples without idle waiting; page reading never cut; Fast check (Owner,
    2026-10-15, from the team-preview-15b real-site test, item 5, part 1 (a, b, f, g, h); amends 206 and 211 for the
    caps; the details are agent defaults).** The crawl record holds `steps` (`step`, `started_at`, `seconds`,
    `requests`, `waiting_s`), measured by the fetcher; the report adds the Firecrawl page reader as its own row. It is
    the appendix table "Step | Time | Requests | Of which waiting" of report.md, under "What could not be checked" in
    the web app, and in the PDF's appendix (both languages). Decision 12 stays (3 samples, at least the interval apart,
    each due the interval after the one before was sent), but nothing waits idle for a sample: the fetcher holds the
    due times and sends a sample that has come due before the next request of the audit's own thread (not from inside
    a rendering); only a sample still not due when Maya's last step ends is waited for (step `robots_wait`).
    `crawl_time_share` is 1.0 (was 0.6): page reading is never cut to make room for checks. The later steps lose their
    optional requests instead, in this order: links to other sites, llms.txt links, the sitemap check, the performance
    rounds, rendering. The steps already run in that order except the links to other sites (asked in the structure
    step, before rendering): such a link (not a sameAs profile) is asked only while the time left is more than the
    later steps are estimated to need (8 s a rendered page, the performance rounds and their pauses, and the sitemap
    check and llms.txt links at the measured pace); one held back counts as "time_limit". The skipped steps are
    `crawl.skipped_for_time` and one sentence: "Skipped because the time limit was reached: {steps}. Run again with
    Fast check off or a larger time limit." (Turkish beside it). Fast check (`--fast`; the web plan's "Fast check"
    switch, off by default; `crawl.config.fast_check`): at most 6 rendered pages (decision 27's template slots), 50
    sitemap addresses, 20 llms.txt links, 10 images and 30 requests to other sites, each a ceiling also over
    `--render-budget` and `--sitemap-check-max`; the page cap, robots.txt samples, ACC-4, redirect re-checks, the
    page reader and DataForSEO are unchanged. The web plan's "Links to other sites" switch (on by default) runs the
    audit with `--no-external-links`. Both switches are in the plan request, the plan document (`switches`), the
    fingerprint (written so a plan at the defaults keeps its old fingerprint) and the command line the runner builds;
    the estimate takes the smaller caps. Owner answers of 2026-10-15: the sitemap check keeps its light GET (one GET
    per address, at most 64 KB read), not HEAD; running the Firecrawl reader alongside Maya's checks is not part of
    this release (a later round), so the reader flow is unchanged. Schema stays 1.14 (`crawl.steps` and
    `crawl.skipped_for_time` are added under its entry).
    **Part 2 (Owner, 2026-10-15, item 5 (c, d, e): faster requests; amends 82; the details are agent defaults).** Each
    host has its own gap, kept behind that host's lock, so two threads never ask one host at once; the time-limit counter
    is locked, and the resolver already was. Right after the crawl every request to another site the later steps would
    make is put in one queue, in the order they asked before (IDX-6's links at one of this site's paths, sameAs profiles,
    og:images and hreflang alternates on another origin, STR-7's images on another site, then the other links,
    most-linked first), with every cap applied then: the same links are asked every run, whatever answers first. Two
    consequences of fixing the caps up front: an address robots.txt disallows no longer frees its place for the next
    one, and a GET after a HEAD the site does not take (405, 501) is sent only within room the queue left under the
    cap, given to the first links in queue order. A pool of 4 threads (`other_site_workers`) asks the queue, each worker
    one other site at a time: its robots.txt first, then its addresses at that site's own gap (the configured delay, or
    its Crawl-delay up to 90 s; `crawl.backoff.host_gaps_s`). Same user agent, URL safety, robots.txt, time limit and stop
    request as every request; never a page reader or a paid provider. The audited site stays on the audit's own thread,
    one request at a time. The pool is joined after the sitemap check, before llms.txt's links (which keep what is left
    of the budget and are still asked in turn); what it did not send is "not checked: time limit", and the answers are
    written into the index and structure data only then. In the pool a link to another site no longer gives way to the
    later steps' estimate (part 1): it runs beside them. Step timing table: the pool has its own row `other_sites` (from
    its start to its last answer; its requests; as "Of which waiting" the time no pool request was in flight), the
    audit's own steps count only their own requests and waiting, and a wait for the pool at the join is the row
    `other_sites_wait`. Adaptive pacing, on the audited site's host only: after 20 clean answers in a row (2xx, 3xx, 404,
    410, no error, first byte within 1,500 ms) the gap is multiplied by 0.75, never below `min_request_delay_s` (0.5 s)
    nor a robots.txt Crawl-delay; any 429, 5xx, timeout, connection error or first byte over 2,000 ms puts the gap back to
    the one before narrowing (the configured delay or the Crawl-delay) and stops narrowing for the rest of the audit; an
    answer in between (a 403, a first byte of 1.5-2 s) only starts the count again. ua_check and render_subresource
    requests do not count. The ×2 widening on a rate limit is unchanged. Decision 82 is amended: the gap no longer only
    grows, so INT-4's required gap for the audited site is the floor in use (the narrowest gap used, else the configured
    delay or Crawl-delay), measured per host (`politeness.by_host`: host, requests, min gap, required gap), with
    `narrowed` ([{from_s, to_s, after_requests}]), `floor_s` and `narrowing_stopped`; `crawl.backoff` holds the same.
    `CrawlConfig.adaptive_pacing` (on) switches all of this off for tests: one gap for every host, no pool, no
    narrowing, the request order of before. The bot information page says the gap may shorten to 0.5 s on a fast,
    error-free site and never below Crawl-delay. LG-86. Also in this run (agent): the merged IDX-8 title reads "1 group
    of indexable pages that are copies or near-copies of each other (2 pages)" / "2 groups of …" (decision 225's
    "group(s) … are" is kept in the wording for reports saved before). No schema change (inside `crawl.backoff`, INT-4's
    evidence and `crawl.config`).
220. **The brand suggested from the address is not a confirmed brand (Owner, 2026-10-15, from the team-preview-15b
    real-site test, item 6; amends 201; the details are agent defaults).** A brand posted on the plan card, or saved in
    the profile, that equals the address's suggestion (compared without spaces, case-insensitive, Turkish letters
    folded: `brand.same_name`) is not confirmed: the plan passes no brand, so the report reads the site's own name. A
    saved value equal to the suggestion is treated as no value (also when a plan is checked against the saved profile).
    The card sends `brand_name` only when the person edited it, and saving the card keeps the saved name instead of
    saving an unedited suggestion. In `brand.resolve` a typed name with no spaces that equals the site's own name written
    without spaces takes the site's spelling and stays typed and confirmed. In `insights.classify_keyword` (when the
    brand is not an ordinary word) a search is a brand search when its words joined without spaces start with the
    brand written without spaces, or are a beginning of it at least 8 letters long made of 2 or more words ("adile
    sultan ev"). No schema change. FA-027, LG-87.
221. **STR-5 does not count copyright years or branch names as other names (Owner, 2026-10-15, from the
    team-preview-15b real-site test, item 7; the details are agent defaults).** Leading years and year ranges are taken
    off a copyright name ("Copyright © 2023-2025 Demo Kafe" is "Demo Kafe"). A name that starts with the most-used name
    and adds 1 to 4 words is a branch, not counted, when a structured-data node (Organization or WebSite name) on a page
    other than the homepage gives it and nothing on the homepage does (the branch page's own title may repeat it); it is
    listed in the evidence `branches_not_counted` and the summary says "Branch names are not counted as other names:
    {names}." (both languages). `_norm` reads a capital dotted İ as i ("İçerenköy" was "i çerenköy"). No schema change.
    FA-028, LG-88.
222. **noindex on a utility page the menu does not link is a note (Owner, 2026-10-15, from the team-preview-15b
    real-site test, item 8; the details are agent defaults).** `config.UTILITY_PATH_SEGMENTS` is
    `PRIVATE_PATH_SEGMENTS` plus qr-menu, qrmenu, qr, print, yazdir, thank-you, thanks, tesekkurler, search and arama. A
    noindexed page with such a path segment that is listed in the sitemap, not a key page and not linked from the
    navigation (an edge marked nav) is S3: "noindex via {where} on {n} utility page(s) (such as a QR menu or a print
    page): check that this is intended", with its own fix (both languages). The same page linked from the menu stays
    S1. It is marked as intended like any noindex (the intent condition is "noindex"). No schema change. FA-029, LG-89.
223. **STR-8 leaves calculators and forms out and names a grid by its heading (Owner, 2026-10-15, from the
    team-preview-15b real-site test, item 10; amends 200; the details are agent defaults).** A grid records
    `has_controls` (an input, select, textarea, output or role=slider inside it, or a `<form>` around it), `heading`
    (the last heading outside the header, menu and footer before it) and `label` (its tag with its id or first class).
    A table records `has_controls` when it is inside a `<form>`, or it or one of its 3 nearest ancestors (not html,
    body, main or article) holds a control. Such grids, and empty tables with `has_controls`, go to `grids_left_out`
    with "a calculator or form: its rows are input fields, not a table of facts" (Turkish beside it), not to findings.
    A page line reads "<div> grid under “{heading}”; first row: “{first_row}”" (kind `div_grid_heading`); with no
    heading it uses the label, never the whole path; the selector stays in the evidence, and a saved report keeps its
    old line. No schema change (a new page-item kind). FA-030, LG-90.
224. **STR-9 guesses the language from the main text and calls two languages mixed (Owner, 2026-10-15, from the
    team-preview-15b real-site test, item 11; amends 194; the details are agent defaults).** The guess reads only the
    page's main text (the header, menu, footer and blocks most pages repeat left out) and needs 150 of its words; with
    fewer the page is not assessed: "too little main text ({words} words, need 150)". When the guess differs from the
    declared language but the declared language itself has at least `language.MIN_HITS` (8) common-word hits, the page
    is not assessed: "the page holds the declared language too ({declared_hits} of its common words): mixed languages,
    not a wrong declaration" (both languages). A reported mismatch records `main_words`. Other checks that use the
    language guess are unchanged. No schema change. FA-031, LG-91.
225. **Copies and near-copies are one IDX-8 finding, and the same problem on other pages is one row (Owner,
    2026-10-15, from the team-preview-15b real-site test, item 9; amends 187; the details are agent defaults).**
    `root_cause.group` joins IDX-8's identical and near-identical groups into one finding, "{groups} group(s) of indexable
    pages are copies or near-copies of each other ({pages} pages)", when there are two groups or more, or when a shared
    title or description moves into a group (one group with nothing moved keeps its old finding). One detail line a
    group, "{pages}: {signals}" (same text / nearly the same main content / same title / same description, and "same
    text on {n} of them" for an identical group inside a near-identical one); a group that looks like variants of one
    product keeps decision 190's advice on its line. A group of STR-1 (shared title) or STR-16 (shared description)
    whose pages all fall inside one duplicate group is said on that group's line; the finding keeps its other groups
    (title and pages counted again) or is left out with a summary note. The merged finding carries the launch-gate
    items of the findings it was made from; its pages say "Copy or near-copy of {others} other pages ({signals})". In
    the top problems, the action plan, the PDF timeline and the Markdown's "What to fix first", rows of the same check
    and severity whose titles differ only in their counts (a number inside an address or a name is kept) are one row:
    "{title}: {up to 3 pages} and {more} more". Headline counts are unchanged. No schema change.
226. **An audit stopped only by its page limit is a partial audit (Owner, 2026-10-15, from the team-preview-15b
    real-site test, item 12; the details are agent defaults).** When the crawl stopped at its page cap ("page cap of N
    reached"; a fetch budget is not), with no time limit, no stop request, no failed step and no reader gap other than
    the reader's own page cap, the sentence is "Partial audit: {read} of {total} known pages were read (the page limit
    of {cap}). Findings cover only the pages read." and the cover label "Partial audit: {read} of {total} pages read
    (page limit)" (both languages; `summary.outcome_label`). {total} is the pages read plus the addresses known and not
    read; {cap} is the reader's page cap when a reader read the pages, else the crawl's. Exit code 3 and the INCOMPLETE
    label stay. A key page the cap left unread does not change the label.
229. **STR-3's page kinds read Turkish words and a product page's price and buy button (the external review's round 3,
    item 6, with the owner's answer of 2026-10-15; amends 39; the details are agent defaults).** The words live in
    `maya_audit/page_words.py`, compared folded (Turkish lower case, no diacritics); STR-21's folding and word lists were
    moved there unchanged. Product folders add urun, urunler, magaza; article folders haber, haberler, makale,
    makaleler, yazilar, rehber, bilgi-bankasi, duyurular; FAQ sss, sik-sorulan-sorular; pricing fiyatlar,
    fiyatlandirma, paketler. kategori, category, etiket, tag, koleksiyon or marka anywhere in the address makes a page a
    list: never a product, never an article. **Product template (owner: the strict rule):** a page off the homepage,
    outside those lists and the article folders, that shows exactly one amount of its own (`located_prices` with
    `not_own` None) and a buy control outside the header, menu, footer and sidebar (a button, an
    `<input type=submit|button>`, or link text "sepete ekle", "sepete at", "satın al", "hemen al", "add to cart",
    "add to basket", "buy now", or a form whose action names cart or sepet) is a product page, when at least 2 pages
    look so. Product markup is never evidence. **2 or more pages with that one price and no buy control**, of no other
    kind and without Product markup, get an Info note (Estimated): "{n} page(s) show one price and no buy button: they
    may be product pages, check" (TR "… bir ürün sayfası olabilir, kontrol edin"), never a problem. STR-6's undated
    article rule reads the same kinds. The STR-3 note reads "Estimated: page kind is guessed from the URL path
    (English and Turkish words), og:type, and for products a page price with a buy button." `page_words.RESTAURANT_WORDS`
    (menu, sube, rezervasyon, paket servis) is written for the sector guess (228); no finding reads it yet. The page
    analysis records `input_buttons`, `form_actions` and each button's `in_chrome`. **Amends 39 (FA-032, FA-033):**
    Organization takes 14 more types (BankOrCreditUnion, InsuranceAgency, AccountingService, FoodEstablishment,
    CafeOrCoffeeShop, Bakery, BarOrPub, FastFoodRestaurant, Hospital, MedicalClinic, Physician, Dentist, Pharmacy,
    Hotel), read by STR-3, STR-5 and the brand name; the "@id given different types" rule keeps the old 24 (a subtype
    beside its parent is no clash). A page typed Restaurant or CollectionPage is not an article by og:type alone (the
    one place where a page's markup counts for its kind, and only against og:type). No schema change. LG-93 (with LG-15).
230. **A page's encoding is read in a browser's order (the external review's round 3, item 7; the details are agent
    defaults).** `html_links.detect_charset`: a byte-order mark (UTF-8, UTF-16), then the HTTP Content-Type charset,
    then a `<meta charset>` or `<meta http-equiv="Content-Type">` in the first 4,096 bytes, else UTF-8. windows-1254,
    iso-8859-9, latin5, x-cp1254 (and the other WHATWG labels of the same encoding) are cp1254; iso-8859-1, us-ascii
    (and their WHATWG labels) are cp1252, as browsers read them. A label that names no text encoding is passed over and
    the next source is read (a browser does the same); none left is UTF-8. `decode_body` uses it, so a BOM is taken off
    the text. The renderer gives the browser the decoded main document as "text/html; charset=utf-8": before, a
    Windows-1254 page was shown to Chromium as UTF-8 bytes under its own charset and rendered garbled (confirmed by the
    render test). No schema change.
231. **The file locks work on Windows (the external review's round 3, item 8; the details are agent defaults).**
    `maya_audit/filelock.py`: `lock(f, blocking)` and `unlock(f)` use fcntl where Python has it and msvcrt where it does
    not, chosen at call time. On Windows they seek to the start and lock 1 byte; a blocking lock asks `LK_LOCK` again
    until it has it (LK_LOCK gives up after about ten seconds), a non-blocking one uses `LK_NBLCK` and raises OSError.
    The web app's worker lock (non-blocking: `WorkerAlreadyRunning`), the DataForSEO ledger (blocking) and the per-site
    crawl lock (non-blocking: `ConcurrentCrawlError`; it no longer writes a byte first) use it, and nothing else. Not run
    on Windows: LG-101.
232. **Client-report evidence gates, without changing the audit engine (Owner scope, 2026-10-16; implementation details are agent defaults).**
    The four reporting reliability fixes use cards contract 2, not a new audit-report schema. An empty or undocumented
    assessment has no numeric score; partial scores name their assessed sample, and content scoring never borrows a
    sitemap denominator. Unverified scored findings or missing check denominators make the score unavailable.
    Missing findings require a comparable complete pass with newer evidence for every affected URL before a client
    comparison can say the issue is no longer seen; incomplete scope, missing provider or unstable identity is unknown.
    Saved hash sketches are not text; native and provider observations have separate provenance. Recommendations
    require field/source/URL/time references plus a reviewer record; numeric/lexical checks do not prove truth.
    Final rendering validates without modifying its input; explicit drafts have a persistent warning. Old client
    cards must be reconverted or rendered as drafts. Spending, retention, resume, engine rules and LG-101 are unchanged.
    Spec, reproduction results and validation limits: `docs/REPORTING-RELIABILITY.md`.

233. **Normal application report accuracy (Owner scope, 2026-10-16; implementation details are agent defaults).**
    The ordinary web/print/PDF pipeline is distinct from cards-v2. Redirect persistence requires enough observed
    native cycles and a completed cyclic cookie walk. Missing checks, timeouts, blocks and hop limits do not confirm
    persistence. A successful page requires nonempty HTML passing the existing fetch classifier and empty-response
    check; legacy HTTP-only success does not establish readable page content. A readable crawl response before
    cyclic retries remains evidence of intermittency. Findings retain native client/time evidence; cached reader
    content cannot cancel a native problem. Genuine persistent cycles remain S1, with language scoped to the tests.
    Investigate request logs before selecting a configuration remedy. Generic guidance contains no invented client
    facts; low main-text ratio, same-day dates, invisible characters and editorial length bands do not establish the
    previously implied technical/ranking causes. Historical data/severity stays intact, with display qualifications
    where verification is incomplete. This supersedes the universal wording and missing-cookie fallback in decisions
    195/217; it changes no request budgets, spending, retention or resume policy. LG-101 stays open.
    Source identity, evidence limits, regressions, deferred work: `docs/NORMAL-REPORT-ACCURACY.md`.

234. **Keyword evidence and shared action priorities (Owner scope, 2026-10-16; agent implementation defaults).**
    Fold Turkish case/diacritic variants for comparison only; retain original provider rows and metrics. Matching
    ranking-page paths and readable page titles/descriptions/headings can support service intent, including short
    acronyms. Ranking on the audited host alone never establishes relevance. Unsupported/mixed context is uncertain;
    lexical matches are not semantic proof. Optional owner profile `brand_aliases` and `related_organizations`
    supply explicit names; related organizations are not the audited brand or automatic keyword opportunities.
    Never infer affiliation, invent aliases or extrapolate classified sample shares to provider totals. This replaces
    the previous `apply_relevance` aggregate-overstatement inference; decision 201's brand-source order stays.
    Historic reports remain unchanged.
    Shared presentation actions retain S1/S2 priority, then investigate measured poor lab/field metrics before medium
    editorial/hygiene work, then lower priorities; evidence quality, scope and effort break ties. Provider diagnostics
    are labelled advisory, not counted as new engine findings, and have no fake finding links. They appear in the
    summary, action plan, timeline and normal print/PDF. Keep lab runs separate from origin field aggregates and
    measurement time separate from collection time; missing stays unavailable. Recommend diagnosis, not a cause
    inferred from a score. No thresholds, providers, spending, retention or resume behavior change.
    Specification, reproductions and verification: `docs/KEYWORD-ACTIONS.md`. Competitor ownership and PDF pagination
    remain outside this implementation; LG-101 remains open.

235. **Client reports are normal application functionality (Owner request, 2026-10-16; agent implementation defaults).**
    Expose existing owner-confirmed aliases and related organizations in bilingual profiles. Generate client drafts
    from saved inactive audits, without provider/LLM/shell execution. The hardened cards contract is one shared Python
    implementation; installed workflow scripts delegate to it. Runtime PDF uses the existing offline renderer.
    Keep an atomic, revision-checked client-report sidecar with source digest; never rewrite the audit. Changes clear
    editorial review. Review is an explicit owner attestation, never live verification; no new live verification UI.
    Final exports require review of all content plus structural/evidence validation, without automatic repair.
    Preserve draft score scope, uncertainty, provider dates and full critical appendix; use normal-report wording
    and historical redirect caveats. Existing technical exports, budgets, retention and resume stay unchanged.
    Automated lexical/numeric checks cannot establish semantic truth. See docs/CLIENT-REPORT-INTEGRATION.md.

236. **Evidence-qualified accuracy round (Owner request, 2026-10-18; agent implementation defaults).**
    Generic service words in a multiword business name do not establish brand identity. Full/confirmed names and
    orthogonal service/local/editorial evidence retain separate dimensions, reasons and sources; keep original provider
    rows/totals. Matched readable content excludes repeated site furniture; lexical evidence is not semantic proof.
    Local equivalence for image labels requires structural proximity plus matching image identity, not arbitrary nearby
    text or a chart caption. Preserve estimated informative-image failures and unknown roles. Consent/dialog controls
    are not navigation defects; interaction remains untested. Iframe presence alone is an inferred Info diagnostic.
    Same-day date patterns are inferred diagnostics, not incorrect-edit-date findings; compare dates of the same event
    and preserve contradictory modifications/impossible chronology. Redirects in llms files require observed destinations;
    unassessed targets are unknown, not broken or healthy. Known audio/video never reaches the reader; response-identified
    media is visible and excluded from failure streaks. Separate provider timeouts/errors from explicit limits. Schema 1.15
    adds optional skipped-resource evidence and stop vocabulary; old 1.x reports stay readable.
    Presentation grouping needs semantic identity and evidence, not titles; occurrence/page/template units stay distinct.
    Search overlap never establishes ownership or business competition. No spending/retention/resume changes. Historical
    analyses use copied evidence, collection/cache times and a new processing timestamp, never fresh-check claims.
    Preserve existing client-report integration; runtime behavior is Python and does not depend on agent skills.
    Local team-preview-17 release is explicitly authorized; LG-101 and fresh-provider verification remain open.

237. **Acceptance corrections (Owner request, 2026-10-18; agent implementation defaults).**
    Allow an allowed-Host, non-foreign-Origin GET of the root document with navigate/document metadata when following
    a link; cross-site API, assets, embedded documents and mutations remain forbidden. Editorial review cannot authorize
    a universal access claim, strip an inferred diagnosis's uncertainty, or borrow unrelated numeric evidence for an
    affected-page total. Explicitly labelled verification samples remain samples, never full verification. The original
    qualified source judgment remains visible alongside edited client text. These narrow deterministic contradictions
    are checked, not arbitrary semantic truth; human evidence review is still required. Aggregate web groups recompute
    affected-page unions; occurrence totals are added only for complete disjoint scopes, unavailable for overlaps.
    Keep original member counts, genuine findings and all historical evidence. No frozen report JSON schema changes.
    Private historical replays are persistently copied under ignored/export-excluded output/acceptance-2026-10-18 as
    explicitly requested. Package this correction as local application 0.2.2 / team-preview-18 only after release gates.

238. **October 18 evidence corrections (Owner request, 2026-10-18; evidence-backed agent implementation).**
STR-6 no longer compares HTTP representation or sitemap resource timestamps with editorial modification dates.
UTC-normalized same-event dates remain comparable; STR-11 retains different modification dates on the same @id.
Bounded structural parsing distinguishes dropdown parents with crawlable children from dead destinations, without
certifying interaction or accessibility. Explicit category labels and nutrient tables can provide equivalent text for
empty-alt category photographs; this remains a structural estimate, with per-image context retained. Charts and
image-only links remain detectable. No brand/file/query whitelist is used.

Keyword identity stays separate from service/local/editorial relevance and confirmed relationships. Conservative
Turkish inflection/definition normalization and saved native content supplement existing provider observations.
Missing ranking-page content is recorded per URL; provisional matches move to uncertain display rows and do not enter
confirmed opportunities. Ranking does not establish ownership; absent vocabulary does not establish unrelatedness.
DOM occurrences, source-target groups, pages and template groups have separate units. Shared IDs include semantic
component/target identity so equal titles/scopes cannot collide. Existing stored IDs/reports remain immutable.

Word-like queries alone are Info/uncertain, not corrupted text. Invalid escapes/replacement characters remain
findings; encoding cannot recover missing letters. Length guidance and low main-content ratio are Info/editorial
observations, not automatic technical failures. The client converter preserves the original severity and explicitly
labels its editorial interpretation. Source estimates and count units survive the normal/client export paths; final
validation rejects reproduced count contradictions and loss of estimated qualifications, without claiming semantic
truth. Both PDFs include repeated table headers, stable schema tokens, bounded evidence continuation blocks and
source-scoped provenance (schema 1.16). Font selection avoids reproduced Turkish subset/ligature extraction problems.
See docs/OCT18-CORRECTIONS-SPEC.md and the private copied-evidence matrix for reproductions, contrasts and limitations.

Preview-19 verification follow-up: catalog and Turkish summary frames now cover the new qualified control/group and provisional-keyword wording. Source evidence appendices remain raw records rather than translated provider statements. The unchanged reader guard permits `max_pages + 1` total requests (the existing bootstrap reserve); its refusal now names that total, distinct from readable-page cap and credit approval. Original historical refusal strings remain in copied evidence. Legacy client cards with known occurrence totals cannot use unqualified contradictory link counts; explicit group units remain possible. A new processing timestamp is the only permitted snapshot report difference in the compatibility regression.

Preview-19 acceptance edge case: a date-only value has no timezone. An adjacent UTC day from a timestamp with an offset
cannot establish a same-event conflict against it. STR-11 records the raw pair as unassessed coverage; it does not add
a problem or claim a pass. Distinct date-only days and genuine timestamp conflicts remain detectable.

239. **Draft PDF warning placement (Owner October18 accuracy/PDF request; agent acceptance follow-up,2026-10-19).** A repeated draft warning must not cover continuation content. Use normal flow for screen HTML and the existing reserved top print margin for PDFs. Keep warnings on every draft page; reviewed-final rendering remains warning-free and validation is unchanged. Reproduce with real renderer/PDF coordinates, preserve the pre-fix failure and verify both draft and final contrast. Preview19 remains immutable and is superseded by application0.2.4/preview20 after exact-source release gates.

240. **October19 qualifying counts and evidence coverage (owner request; agent implementation, 2026-10-19).**
Generic-text page counts use qualifying DOM occurrences, not every anchor in a source-target group; stored derived
page items are recalculated read-only. Unknown legacy counts stay unavailable. Image wrappers, names and intrinsic
sizes alone no longer establish informative purpose: explicit informative captions and unlabelled image links remain
findings; missing role/pixel/CSS evidence is recorded as unassessed. Structural equivalence never overrides an explicit
informative caption. Existing approved search-data collection precedes the reader, without increasing budgets or
adding requests; home/key pages precede a bounded ranking-page priority set. Final relevance uses the final saved
content and original provider rows; saved paid results remain reusable on resume. Editorial topic opportunities are
separately labelled with unestablished commercial value, not ranked as confirmed commercial gains. Historical missing
content remains missing. Evidence-only additions do not change the frozen report shape. See OCT19-ADILE-SPEC.md.

October19 saved-report follow-up: normal views must not trust stale opportunity flags over retained dimensional
assessment evidence. A shared pure engine adapter qualifies those flags and editorial groupings on read without
rewriting historical reports. A supported editorial topic is not a confirmed commercial quick win. Missing/uncertain
assessment records do not gain certainty from a cached display boolean; legacy records without assessments retain their
explicit compatibility path. Regression exercises actual summary/practical/print routes, not only fresh conversion.

241. **Evidence strength and concise exports (owner request; agent policy, October19).** HEAD404/410 requires bounded GET corroboration; redirects are traversed manually through per-hop public-target/robots/deadline/shared external caps (one HEAD+at most4GETs). No provider calls. Unavailable/contradictory results stay uncertain with attempts retained. Empty small-HTML exclusion is unchanged. IDX1 now separates repeated successful empty GETs from single probes/missing corroboration; only repeated homepage/key failure earns S1, other repeated S2, single/unconfirmed S3. Share alone cannot establish critical business impact. Successful readable evidence is needed for recovery; timeout never proves content. Complete per-URL attempts are evidence, affectedURL counts are not content pages read. Existing IDX1/IDX5 root-cause relationship remains.

Native data tables gain conservative HTML header-association evidence, excluding explicit layout tables and ambiguous nonnumeric layouts; table-like numeric facts with unsupported headers are estimated accessibility observations, not ranking penalties. Native/ARIA headers and explicit associations are supported, no mandatory captions. Existing div-grid rules remain.

Normal PDF defaults to concise presentation; full technical PDF/print remain available with full=true and JSON/evidence downloads stay complete. All finding IDs remain in inventory, severe and consequential uncertain findings receive detail, sampled URLs/details explicitly defer to companion evidence.50pages is a hard post-render limit; exceeding it fails without returning an incomplete PDF.10.5pt body text retained. This is presentation, never reduced detection. Native, processing, whole-job and export timestamps are separate; absent historical values stay unavailable. No frozen report field changes; evidence and view adapters only. Prior uncommitted October19 patches preserved.

Decision241 implementation clarification (agent + independent read-only review,2026-10-19): repeated key/homepage
empties and repeated unknown-purpose URLs are separate finding groups. A key URL must not transfer S1 impact to
all URLs sharing evidence strength. Synthetic mixed-group reproduction retains home S1 and non-key S2, both URLs
and their attempts; single/unconfirmed observations remain S3. This boundary was missing from the initial tests.

242. **Separately identified saved-evidence results (owner request,2026-10-19).** An offline reanalysis is not an audit job and must not replace the source history entry. The normal app reads an explicitly prepared, digest-checked registry outside audit history; separate sidebar/deep-link identity, filenames and provenance follow every ordinary result/export adapter. Audit lifecycle/provider mutations are forbidden for these IDs; client draft work is confined to the separate result folder. No web path-import or shell execution. Tests inject an isolated registry; normal entry point reads project output/revised-analyses (isolated MAYA_AUDIT_HOME uses its own analyses folder).

Readable coverage excludes explicit empty, zero-byte or content-ineligible HTML responses while retaining small valid documents and separate fetched-file diagnostics. This repairs the existing readable-document contract; HTTP success is not content coverage. Copied derived coverage/check-gap text and per-page items are regenerated with existing engine functions, preserving source measurements, unknowns and total-anchor evidence. The original JSON remains historical; revised JSON stores the same qualifying counts that the UI/PDF use. Original observation time, versioned processing time and export time/digest are distinct. No frozen report field change or new scoring definition.

243. **Judgment and recommendation consistency (owner request; agent implementation,2026-10-20).**
Open evidence.judgment separates raw source wording, measured scope/times, interpretation/status, confidence,
verification state, alternative explanations and conditional action/owner/effort/verification. New report JSON and
Markdown, ordinary views, client adapters and explicit saved-evidence reassessment use the same pure Python qualifier.
Original IDs/severity and raw request records remain; source wording is retained in companion JSON rather than repeated
as current advice inside printed raw metadata. Missing supporting evidence is explicitly not assessed, preserving the
source confidence separately. No schema-frozen field additions: judgment/count extensions are in open evidence data.

Sitemap review distinguishes unique per-URL response states, not a universal non-live verdict. Single empty probes
require corroboration; repeated empties retain tested-client retrieval concern, no cause inferred. Noindex is an owner
indexing-purpose decision; redirects require destination review. IDX1 overlap remains explicit, never a second invented
failure. HEAD-only 404/410 cannot establish removed destinations; successful/mixed/limited GET evidence stays scoped.
Guarded acquisition/budgets remain unchanged. Actual recorded GET errors and genuine critical retrieval findings remain.

Provider records/unique queries/classification rows and overlapping dimensions are distinct. Legacy rank-only rows
remain visible but cannot become confirmed business opportunities without relevance evidence. Editorial relevance is
not sales value. New audits persist these counters through the existing in-place API. Shared recommendation estimates
were moved unchanged to engine recommendation_catalog; runtime client output no longer invents a separate owner or
blanket medium effort. Consequential edited actions require corroboration/owner conditions, never attestation alone.

Unresolved image-role records become coverage gaps, not passed checks or additional defects; record/instance/source-URL
units differ. Empty heading tags do not supply meaningful headings. Long tables/lists, generic anchor wording, text
similarity and short pages require context/purpose review, not ranking penalties or automatic merging/noindex. Original
measurements remain inspectable. Compact UI summaries link to complete evidence instead of embedding it repeatedly;
existing payload and50-page concise PDF limits remain enforced. Historical originals and r3 stay immutable; r6 is a new
qualified analysis with original collection and new processing times. No paid/live requests or release in this task.

244. **Review r3 criticism against current evidence (owner request; agent implementation,2026-10-20).**
The review document is not source evidence or a source-referenced code review. Recheck each assertion against r6,
separating different native/reader/probe scopes and observation confidence from cause/impact. Do not adopt blanket
severity changes, name-word brand identity or same-title merges. Complete per-URL sitemap review states supply the
review scope; a legacy truncated scope is preserved as source metadata, not reused as the full affected count.
HTTP-header provenance follows saved response client/time, independently of merged reader content; absent identity
remains unknown. Same-day dates remain diagnostic. Missing hreflang annotations cannot yield an affirmative reciprocity
claim. Unavailable sitemap discovery does not establish all listed pages hidden through every other route. Ordinary
report examples use verified subjects or neutral instructions; Lighthouse opportunity summaries expose stored values
and explicitly distinguish the single lab run from field CWV. No thresholds, acquisition costs, severity policy or
source audit records changed. These are shared Python/report-adapter changes, not a brand-specific replay rule.

## Compact client delivery boundary (2026-10-20, agent implementation of owner request)

Normal client preview/HTML/PDF preserves every finding's identity, source qualification,
action and verification but places exhaustive raw page/provider records in explicit JSON
and full HTML companions. Do not mutate editorial/source data to shorten output. Compact
client PDF has the same50-page refusal policy as normal technical delivery. Export success
never constitutes editorial review or live verification; full-evidence drafts stay labelled.

245. **Nine bounded judgment/client corrections (owner requirements; agent implementation,2026-10-21).**
Client judgment notes explicitly use Turkish independently of UI locale. Client procedures reuse the qualified engine
repair, expected result and action metadata, identifying supported source/target/element evidence; uncertain access
observations require corroboration before removal. A same-URL nonzero shell is one actionable rendered-dependency
problem only when actual RND-2 and successful substantive rendered evidence exist. Raw IDX-1 observations remain
cross-referenced; zero-byte, genuinely empty, unrendered and mixed nonoverlapping pages remain. Sitemap overlap
includes actual IDX-1 HTTP failures as well as qualifying empty responses, perURL rather than whole-group expansion;
redirect/noindex/contradictory states remain distinct. Preserve complete original review scope and affected-URL lists.
Generic-link titles retain supported wording/component/destination identity without merging defects. Complete
captured iframe naming evidence can establish an accessibility-name defect; title:null alone in old incomplete
records cannot. ARIA naming and decoration are respected. Whole-value image/filename alt placeholders are Estimated,
never proof of image purpose; actual context and descriptions require review. One partial multiword-brand token does
not establish identity/relevance from repeated full-brand text; confirmed aliases and independent topics still count.
Large compact client documents may share only genuinely compatible procedures while retaining every member ID,
URL association, qualification, evidence and editorial text. Existing10finding/full layouts and explicit50page refusal
remain. No severity-wide downgrade, cost/provider change, frozen-schema-key change, release or live check is implied.

246. **Evidence-specific format, heading, request and decision scopes (owner request; agent implementation,2026-10-21).**
Image URL/type/srcset references are markup observations, never delivered-format percentages. Retain response MIME,
client/method/time/size-limit evidence separately, distinguish occurrences/resources and unobserved alternatives,
and require size/quality evidence before conversion advice. Missing response evidence is not JPEG delivery or zero.
Retain H1 elements separately from meaningful heading text, including empty/whitespace distinctions. Old extracts
without raw markup cannot establish absent versus empty. Fill existing empty headings before considering new markup.
Respect explicit link accessible names and equivalent ARIA main regions; no arbitrary nearby-text equivalence.
Host TLS and HTTP outcomes remain separate; robots retrieval failure is not a disallow rule. A content-read cap is not
an HTTP/probe denominator. Only recorded probe populations justify replacing that caveat; unknown populations stay
incomplete. Sitemap sample limits name their own unassessed URL population. PRF2's existing transport/5xx rate policy
is unchanged;4xx and empty2xx counts describe separate response outcomes, and the request population is explicit.
Overlap uses complete retained classified URL membership, not capped display samples; incomplete membership cannot
produce invented exact overlaps or erase distinct redirect/noindex/conflicting decisions. Owner intent controls
noindex changes; verified directives alone do not establish harm. Keep shared qualifications/actions in every export.
Metadata belongs inside open evidence/analysis records, preserving the frozen schema boundary. Identical repeated
client explanations may be omitted from grouped presentation only when retained once with every finding/member ID,
URL association and qualification. No paid acquisition, historical rewrite, count-reduction target or release implied.

247. **Preview-23 review fixes (reviewer's request through Efsa Ediz; agent implementation, 2026-10-21; owner
     confirmation pending for (a), (e) and (f)).** One pass over the external review of team-preview-23 and the
     live Arjava comparison. Item-by-item changes, tests and open points are in `docs/review-fixes/` (one file per
     work package); `tests/test_arjava_regression.py` is the end-to-end acceptance on a made-up shop with every
     defect of that live audit. Decisions that narrow or reverse earlier ones:
     (a) DECISIONS 131/138: a page reader that leaves a coverage gap (cap, allowance, early stop, unreadable or key
     pages) makes the audit INCOMPLETE (exit 3) even when Maya's own crawl was exhausted, so the outcome agrees with the
     coverage line. Many keyed audits will now exit 3.
     (b) DECISIONS 20: one dead target is one finding. IDX-6's per-target task survives as a row of IDX-1's evidence
     (`broken_links`); headline counts and the priority list name the dead URL once. Targets under /cdn-cgi/ are never
     broken links; Cloudflare e-mail obfuscation is one Info note.
     (c) DECISIONS 222: a noindex page listed only by the sitemap is S3 until the owner's intent is known, with a
     separate S2 "the sitemap lists noindex pages"; key and menu-linked pages keep S1.
     (d) DECISIONS 225: `repeated_key` is removed; merging is by semantic evidence identity only.
     (e) RELEASE-22 and COMPACT-CLIENT-SPEC: print/PDF language follows the audit's stored language (`?lang=`
     overrides), not the browser cookie; compact exports may shorten repeated member procedures and say shared
     sentences once per section. Full exports and JSON stay exhaustive.
     (f) Client report rules (onem_kurallari.json, kart_sozlesmesi.md): a report rule may only lower the engine's
     severity, never raise it (former Kural 9 removed; llms.txt not scored). The draft score is per check over unique
     URLs, leaves unverified findings out with a note, and is not a KPI box.
     (g) Draft/test pages are an IDX-5 finding (S3, Inferred) rather than a new check id; a page reachable at two
     addresses is an IDX-8 finding; checks that do not apply to any page read report `not_applicable` (schema 1.17).
     (h) The LLM brief (0.2) fences page text as data between markers, bounds lists with omitted counts and asks for
     check/finding citations that `maya-audit brief-check` verifies. Skill workflows follow AGENTS.md's shared
     preamble (Windows and POSIX commands, release mode A tagged / B working-tree snapshot).
     Not done and left to the owner: A28 (DFS-8 not planned outside a US/en market), A30 (Firecrawl audit-level cap),
     a stable per-finding code for client rule matching, and the project licence (no LICENSE file was added).

248. **Brand-independent quality (reviewer's request through Efsa Ediz; agent implementation, 2026-10-22; owner
     confirmation pending).** The fixes of 247 were tuned on one live shop; this round checks them against eight
     made-up sites of other kinds (German shop behind Akamai, JS-rendered SaaS on Vercel, Turkish recipe/branch site,
     multilingual bank, WordPress local business behind Sucuri, Shopify store, a site with real drafts, a French news
     site behind Fastly) in `tests/test_brand_neutral.py`, plus two live sites (a Ticimax shop and a WordPress content
     site). Notes per package: `docs/review-fixes/gx1.md`, `gx2.md`, `gx3.md`. Decisions narrowed:
     (a) IDX-4: a filter, sort, facet or pagination view canonicalised to its own listing is an observation, not S2.
     (b) 247(g)/H13: a draft needs a draft word in the address, no or a placeholder title, and sitemap-only discovery;
     "demo", "ornek", "sample" count only first in a slug. A page reachable at a trailing-slash, extension or letter-case
     variant that names the other as canonical or redirects to it is not reported.
     (c) 247(c): a noindex page listed in the sitemap is one ACC-3 S3 finding, not S3 plus S2.
     (d) DECISIONS 204/241: two empty answers to Maya's own user agent are confirmed with at most three browser-identity
     requests before S1/S2; content to the browser makes it an S3 "empty to automated clients only" finding.
     (e) H16 reversed: alt equal to the title attribute is not a placeholder. DECISIONS 211 narrowed: a host serving
     at least half (and at least five) of the site's images is the site's own for the image sample.
     (f) H28 narrowed: "HTML not cached at the CDN" needs a CDN identified by its own headers, its miss/bypass status on
     nearly every HTML page and Cache-Control private/no-store; otherwise an observation. Twitter card absence is an
     observation. Site-wide hygiene findings (HSTS, CDN cache, unsized images, head scripts) are a short Hygiene list.

249. **P1, media on the pages that matter (Efsa Ediz's request, agent implementation, 2026-10-22; owner confirmation
     pending).** A live comparison with a hand-made audit of a Ticimax shop showed three 1.1-1.8 MB homepage banners, a
     10 MB promo video and a 200 × 200 share image that Maya never measured. Notes: `docs/review-fixes/w6-media.md`.
     (a) STR-7: every image the homepage and the key pages show or preload is sized on top of the sample, under its own
     cap `key_image_checks_max` (40; 15 in a fast check; none when image_checks_max is 0). Ordering by declared size
     alone left out banners that declare none.
     (b) STR-7 videos: also from a VideoObject's contentUrl (only an address that names a video file) and a lazy
     loader's data-src on <video>/<source>; a video on the site's asset host is the site's own, as images are (211).
     (c) STR-10: an og:image on the asset host, or redirected there, is read like the site's own; a share image under
     600 × 315 is an Info note ("shown as a small thumbnail"). The 200 × 200 S4 rule is unchanged.
     (d) An IP address has no registrable domain: another port on the same address is another site unless it is the
     asset host (fixtures model other sites that way).

250. **P2, structured data a site lacks, read from what its pages show (Efsa Ediz's request, agent implementation,
     2026-10-22; owner confirmation pending).** The same comparison: the homepage had no WebSite node, showed seven
     questions with answers and no FAQPage, and its broken Organization also lacked logo and sameAs. Notes:
     `docs/review-fixes/w7-schema.md`. Every new item is Info or an observation; no severity was raised (Efsa chose to
     surface them in the client report's own card, not by changing the engine's calibration).
     (a) STR-3 Info: a page that shows at least three short question-and-answer pairs (told by the question mark in any
     script, at most 1,500 characters of answer between questions) and has no FAQPage or QAPage. A page found as an
     FAQ page by its address keeps the existing "expected type" note; a draft IDX-5 reports is said there only.
     (b) STR-3 Info: a page that shows a breadcrumb trail (class, id or aria-label says breadcrumb; two steps, one link)
     and has no BreadcrumbList.
     (c) STR-3 observation "homepage with no WebSite structured data", not a finding: on 8 of 8 neutral fixtures it
     would have fired, as twitter:card does (G13). Left out of a single-page audit of another page.
     (d) The broken homepage Organization's evidence carries `recommended_still_lacking` (logo, sameAs absent even in
     the lenient parse). Evidence only, so the printed concise report stays within ten pages.
     (e) FAQ page words: the spelled-out forms (sikca-sorulan-sorular, frequently-asked-questions, and the de, fr, it,
     pt, nl forms). Live, the English FAQ page of the same shop has no FAQPage while the Turkish one has.
     (f) STR-10's catalog note splits the 200 × 200 S4 from the 600 × 315 Info of DECISIONS 249 (each its own why).

251. **P3, links and tags that disagree with the page (Efsa Ediz's request, agent implementation, 2026-10-22; owner
     confirmation pending).** Notes: `docs/review-fixes/w8-consistency.md`. As in 250, nothing is promoted: one real
     bug is fixed and the rest are observations, which the client report raises in its own card.
     (a) ACC-8 bug: `llms_links` read only Markdown links, so a file that lists its pages as bare addresses ("* https://…",
     seen live) had no links and the existing "points to an address that redirects" note never ran. Bare addresses and
     <url> autolinks are now links too; not mailto:, an address inside a word, or one in a code span.
     (b) STR-10 observation: og:url names another address than the canonical, compared as URLs (an empty path is "/",
     RFC 3986). "https://site" against "https://site/" is the same address and is never reported; the hand audit that
     listed it was wrong on that point.
     (c) STR-10 observation: a <meta name> written with no content (keywords, author…); description stays a finding.
     (d) IDX-6 observation: links to other sites whose address carries a click identifier copied from a browser
     (TRACKING_PARAMETERS: fbclid, gclid…) or a logged-in view parameter (viewAsMember, igsh, igshid). utm_* is left
     out: on a link to another site it is the linking site's referral tagging, on purpose (live: a platform's
     "powered by" footer link).

252. **P4, what a reader of the menu and the outline meets (Efsa Ediz's request, agent implementation, 2026-10-22;
     owner confirmation pending).** Notes: `docs/review-fixes/w9-chrome.md`. Three observations, raised by the client
     report's own content card; nothing promoted.
     (a) STR-9: a header, menu or footer whose control names (link text, buttons, icon alt text) include at least two
     labels of another language than the page's (`UI_WORDS`, 8 languages; loanwords such as login, shop, blog and
     language names left out). The page's language is its main text's when clear, else the declared one. Live: the
     Turkish pages' icons say "My Cart", "Sign up / Login", "Favorites". On the neutral fixtures it also notes the
     Spanish pages that reuse the English or French menu, which is the same thing.
     (b) STR-2: a question-and-answer block (250 (a)) whose questions are all plain text; a question in a heading, a
     link or button, a <summary> or a <dt> is marked up.
     (c) STR-14: an address word of five letters or more that the page's own names (title, <h1>, link text) do not
     hold, while one of them holds a word of the same length one letter off, not in the last letter (an ending that
     changes is inflection). No dictionary and no request.
     (d) Not done: an image preloaded but hidden on phones (H30). Rendering runs at 1280 px only; guessing from class
     names would fit one theme. It needs a phone-width render, which is the owner's call (cost).


253. October 22 archive integration (owner requested; merge choices by Codex). The engineer ZIP's source, not its stale
     Preview23/schema1.16 manifest, is the input: app0.2.6/schema1.17, SHA-256
     ecd4aec000fce79535b78a95257f0a8077759399c3d7a766c750e1d5820aab36. Import reviewed descendants individually,
     preserve unfinished local work and installed workflows, and do not delete absent files or install the stale
     release manifest. Keep required unverified evidence scores unavailable rather than excluding the evidence and
     awarding100. Retain individual consequential qualifications in compact appendix rows and grouped rows. Keep the
     incoming per-check unique-URL deductions for fully assessed drafts. Python3.13 pathlib._local snapshot names
     resolve only the public pathlib data types already explicitly allowlisted; executable globals remain refused.
     Preserve legacy revised analyses by private, hash-checked copies into the new data-home registry, retaining
     original directories, only after SQLite backup (including committed WAL) and idle-server verification. No
     environment recreation, dependency upgrade, paid call, commit, tag or release is part of this integration.
     See docs/OCT22-INTEGRATION.md and tests/test_oct22_integration.py; snapshot regression contrasts executable data.

     Follow-up: the original full suite detected reference drift between the skill and shared runtime. Narrow
     automatic approval allowed only references/onem_kurallari.json and kart_sozlesmesi.md to be aligned, with the
     local score-null safeguard retained. Workflow SKILL.md/scripts/root instructions stay unchanged. Keep the
     exact reference/asset consistency test; normalize imported JSON newlines rather than weakening assertions.


254. Brand-independent benchmark (owner requested, October22; implementation choices by Codex). Start with a ten-site
     opt-in native Quick50 benchmark, outside normal pytest/application startup and owner audit storage. No provider
     clients or credentials; explicit --live for collection. Capture guarded request/response evidence and pin reviewed
     assertions to collection hashes. Supplied site allegations start provisional; independently inspect saved sources
     before scoring them. Distinguish hits/misses/false alarms/correct negatives/unassessed/provisional; unlabelled
     findings are not false alarms. Page-specific assertions do not claim the unread site passed, but unrelated unread
     scope must not invalidate a genuinely assessed page. Complete per-page gap membership is required before setting
     aside another page's gap. Offline replay blocks all DNS/connections and fails closed for missing/truncated capture;
     browser/TLS/cookie-state checks remain unverified. Its processing clock is not a fresh observation time. No
     application judgment rule or report schema changes in Stage A. Preserve original history, current integration and
     8770server. Benchmark domains/paths live in benchmark data, never production exceptions. See
     benchmarks/real-sites/README.md, docs/BRAND-INDEPENDENT-SPEC.md and tests/test_real_sites_benchmark.py.

255. Shared identity/severity/dependency policy (owner requested, October23; implementation choices by Codex).
     Rank identity by independent page/source agreement, retaining explicit owner-name precedence and unresolved ties.
     Preserve Unicode and Turkish folding. Explicit own-entity alternate/legal names retain page/time provenance;
     department names and separately declared locale names are not automatically identity contradictions. Neither a
     product name, domain ranking nor an unconfirmed shortened prefix establishes organizational ownership. Bare
     single-word identity queries require corroboration or a confirmed alias (short uppercase acronyms remain valid);
     saved owned organic sitelinks can corroborate a named query, never turn a generic service query into branded intent.
     A knowledge-panel presence flag has no entity identity and is insufficient. No extra provider calls are introduced.
     API shape checked against https://docs.dataforseo.com/v3/dataforseo_labs-google-ranked_keywords-live/ .
     Apply the documented ordinal impact×reach×certainty ceiling in severity.py after native/provider processing and
     explicit copied reassessment. Never restore a deliberately reduced finding or leave stale action priorities.
     Heuristic/estimated findings are at most Medium; the SaaS raw-shell regression's former High expectation is changed
     for this explicit owner policy. Verified draft-page observations retain their supported Medium ceiling. Cosmetic
     template notes require a recorded cosmetic classification; template repetition alone is insufficient.
     Fold a llms.txt failure into IDX-1 only when it explicitly reuses the same native crawl status and retained complete
     URL membership. Preserve original dependent findings, references and sub-counts. Different response/client context
     remains independent. No inferred server root cause or blanket suppression of all checks on a failing URL.
     Report-schema1.17 remains: additions are within open evidence dictionaries, not public structural fields.
     See docs/BRAND-INDEPENDENT-B-SPEC.md and docs/SEVERITY.md. No history changes or benchmark-domain exceptions.

     Stage B verification follow-up: the first full run retained2432passes,19failures,1skip (790.53s). It exposed
     obsolete exact evidence/severity assertions and a real integration-order defect: ANS-1 copied constructor High
     before the site policy reduced an estimated rendering observation to Medium. Settle/group/qualify site priorities
     before creating the answer panel; a new regression checks every retained site-finding reference against final
     priorities. Existing verified-critical retrieval, verified rendered-content and genuine contradictory-identity
     contrasts remain asserted. Never obtain green results by deleting observations or broadening skip/exclusion rules.

     The next full run completed2453cases (2451passed,1failed,1skipped;978.713s in retained XML). The daemon restarted
     before its wrapper summary was saved; results.xml is authoritative. Its one failed web acceptance was reproduced
     alone (459.24s) and traced to failure persistence following synchronous exception logging. Controlled blocked and
     failing logger regressions both failed before the correction. Persist failed state/done event before diagnostics;
     swallow only log-sink errors, preserving the original sanitized API error and server diagnostics. The original web
     acceptance plus both contrasts then passed (3passed,191.74s), with slow diagnostic cleanup disclosed. This does not
     prove the original filesystem/log delay's cause. Only the web worker changed after the native frozen benchmark;
     native engine files remain byte-identical, documented in benchmarks/real-sites/STAGE-B.json. No live rerun.

     Further Stage B review found that the same-entity localized-name exemption did not reach the global STR-5 name
     counter. Reproduced the native and saved-report cases before fixing both; retain raw inputs and the original
     legacy finding in reassessment evidence, and never assume missing locale/variant membership. Two coverage
     translations were initially stored as finding notes instead of labels/lines; the full translation tests caught
     both. They are now in the correct lookups. A browser-child25second deadline failed intermittently; stack
     diagnostics were added without changing deadlines/assertions. A separate stalled temporary-copy collection was
     traced to reading a macOS dataless installed AnyIO source file; no dependency was installed or changed. Reusing
     current dependency-only bytecode avoids stale cache assumptions. Final source suite2457passed/1skip in1182.52s;
     the skip requires uncommitted historical live examples. Preserve all original failure and rerun logs. Preview25
     remains unverified after its extracted deadline failures; do not overwrite it. Native frozen comparison remains
     8hits/0misses/2false alarms/12correct negatives/1unassessed on identical observations and reviewed labels.

256. **Integrating the 23 October handover into the P1–P4 branch (Efsa Ediz's request, agent implementation,
     2026-10-26; owner confirmation pending).** Base `fix/w9-chrome`; the 0.2.7 handover's source was merged three-way
     against the received preview-23 (`f860887`), and each file was then reviewed against our side. Review notes:
     `seo_audit/handover-0.2.7-denetim.md` (outside this repository).
     Taken: `severity.py` and docs/SEVERITY.md (253/255 policy as written), identity/alias/department and localized-name
     work in STR-5, `brand.py` and DataForSEO relevance (255), the llms.txt fold into IDX-1, the client score staying
     unavailable while required evidence is unverified (253, with both card contracts aligned), compact-row member
     notes, the web worker writing the failed state before logging, the Python 3.13 `pathlib._local` snapshot names,
     the real-site benchmark and its offline replay (254), `tests/offline_process.py`, `tools/pro_offline.py`, the new
     tests, and the maya-audit-pro skill's 23 October changes applied onto the 22 October skill (its COMPATIBILITY.md).
     Not taken: (a) the workflow SKILL.md files, `canli_kontrol.py` and the AGENTS.md shared preamble stay as in
     247/H41–H43 (guarded transport, robots.txt first, browser identity only; untrusted-data and length rules), with
     their tests; (b) STR-5 still counts a declared alias that is also used as the main Organization name
     (`or k in org_names`), and the saved-report reassessment in `brand.py` follows the same rule; (c) no
     handover manifests, README rewrite or client example reports; no documents, CI or tests were deleted.
     Fixed while integrating: `real_sites_benchmark.py` hashes paths with `as_posix()` so the digest is the same on
     every OS; `offline_process.environment()` passes SYSTEMROOT/WINDIR/COMSPEC/PATHEXT and the browser cache on
     Windows (without them asyncio could not start a child, WinError 10106).
     Confirmed by Efsa Ediz (2026-10-26): under 255, an *inferred* finding on an ordinary page drops two levels
     (IDX-1 "times out on every attempt" S1→S3; STR-11 two prices S2→S3); this consequence of the weights is accepted
     and the tests keep those expectations.
     Confirmed by Efsa Ediz (2026-10-26): the brand is the site's own name; a copyright holder seen only in the © line
     is not another name of the brand (the handover's footer rule and its Demo Kafe fixture are taken). This tree is
     version 0.2.8, so it is not confused with the handover's 0.2.7.

257. **Professional report: client text says only what the client can check (Efsa Ediz's request, agent
     implementation, 2026-10-26).** Three defects seen in all three 23 October English PDFs (review notes:
     `seo_audit/handover-0.2.7-denetim.md`, B4). (1) "+N more … full list in the JSON companion file" promised a file
     the client never receives: `render.py` now writes `<name>-addresses.csv` beside the HTML with every card's full
     address list (and a row for addresses the audit counted but did not list), and the label points at it; nothing is
     written, and no promise printed, when every address is shown. (2) Internal launch-gate codes (`LG-42`) are no
     longer printed; the status says the check is not yet validated on live sites, and the codes stay in
     `todos[].launch_gated`. (3) The page KPI counted `problem_summary.by_page`, which by design leaves out shared
     header/footer and site-wide problems (`whole_site`), while a card for such a problem lists every page
     (Moodist: 26/50 beside a card with all 50). The count is unchanged; the label is now "Pages with page-level
     issues" and the sub-line names the site-wide problems it does not count. Tests:
     `.agents/skills/maya-audit-pro/tests/test_client_text.py`. Seen while testing, not changed here: the overflow
     check does not flag an investigation-priority text clipped at its second line.

258. **Homepage priorities follow the expert audit (Efsa Ediz's request, agent implementation, 2026-10-27).**
     Compared with the 1 October hand-made Arjava audit (`seo_audit/arjava_2026-10-26/karsilastirma-manuel-1ekim.md`),
     four homepage items it rates High were Medium, a Note or absent here. Owner: "what it calls High is High here too".
     Brand-independent rules, homepage only, verified evidence (so the 255 policy keeps them High):
     (1) STR-3 the homepage's own Organization block does not parse: S3 → S2. (2) STR-2 the homepage's only <h1> is
     hidden: S3 → S2. (3) New STR-2 finding: the homepage has fewer than 3 visible <h2>/<h3> and either at least 300
     visible words or a question block whose questions are plain text: S2 (`homepage_min_subheadings`,
     `homepage_outline_min_words`). (4) New PRF-1 finding: the homepage's own median time to first byte over its
     PRF samples (at least 3) is above 800 ms, web.dev's "good" bound: S2 (`homepage_ttfb_max_ms`). The site-wide
     median hid it (Arjava: 265 ms site, about 1.1–1.9 s homepage). Also (5) new RND-6 finding: homepage HTML above
     500 KB and not already above the 1000 KB site bar: S3 (`homepage_payload_max_bytes`), the audit's "HTML şişkin".
     These will fire on many sites: the thresholds are policy, said in each finding's notes.
     Professional report: Info findings the expert lists (CDN-uncached HTML, head scripts without defer/async, an
     analytics tag loaded twice, images without width/height, image/jpg preload, no WebP/AVIF; default VideoObject,
     small share image, image format unlike its file name) now reach the PDF in two Note cards instead of staying in
     report.json only. Not changed: the expert's Medium items keep the engine's severity; editorial items (title order,
     meta call to action, trust signals, blog) stay out of a deterministic audit. Tests: `tests/test_w11_homepage.py`,
     `tests/test_w2_part1.py` (Organization now S2), `.agents/skills/maya-audit-pro/tests/test_client_text.py`.

259. **Client report fixes found in the three-brand comparison (Efsa Ediz's request, agent implementation,
     2026-10-27).** Comparison notes: `seo_audit/karsilastirma_2026-10-27/OZET.md`. (1) The CLI writes the full
     affected-address lists beside the JSON report as `<report>.affected-urls.json` (named after the report, so two
     reports in one folder never share one list); the professional report reads it, else the web app's
     `affected-urls.json`. Without it a card said "+21" for 70 pages and the CSV held 25 addresses. (2) The evidence
     sample shows at most 3 rows; a fourth printed over its note. (3) A step that starts with a number ("404 …") keeps
     it: only a list marker is stripped. (4) A grouped card shows at most 3 IDs plus "+N". Seen, not changed here:
     Product/AggregateRating value checks, a `<head>` closed early by a body element, near-copy location pages above
     a note, three false alarms (page language, accessibility-widget text as JavaScript-only content, FAQPage from
     dialogue) and security headers.

260. **A body element inside <head> ends it early (Efsa Ediz's request, agent implementation, 2026-10-27).** Seen live on
     Enpara: an accessibility widget prints `<div id="blueLightOverlay">` inside <head>; Google documents that it then
     stops reading the head ("Use valid HTML for page metadata"). The parser already started the body at that element
     (DECISIONS 167); it now records which element did (`outside_head.closed_early_by`: tag, id, class, line) and the
     hreflang links and Open Graph properties that followed. TSEO-1 reports it: High when a canonical, robots or
     hreflang tag comes after the break, Medium when only meta/Open Graph tags do; verified and documented, so the 255
     policy keeps it. Elements inside <noscript>, <template> or a script do not end the head. Tests:
     `tests/test_w12_head_closed.py`.

261. **Structured-data values Google cannot read (Efsa Ediz's request, agent implementation, 2026-10-27).** Seen live
     on Carpex: `"ratingValue": "4,38"`, a key `"reviewCount "` with a trailing space, `"priceCurrency": "try"`; we
     checked only that properties are present. STR-3 now checks values on every typed node (JSON-LD and microdata):
     property names with spaces around them; ratingValue/bestRating/worstRating with a comma decimal, not a number,
     or above bestRating (default 5); price/lowPrice/highPrice with a comma decimal (4,38 and 1.299,90);
     priceCurrency not a three-letter upper-case ISO 4217 code. One Medium finding (verified, Google-documented
     formats), items listed. Not done: comparing reviewCount with a review count shown on the page. Tests:
     `tests/test_w12_schema_values.py`.

262. **Baseline security headers, a note (Efsa Ediz's request, agent implementation, 2026-10-27).** claude-seo reported
     missing security headers on three sites; we read only HSTS. PRF-1 now adds one Info note when the https homepage
     answers without OWASP's baseline: Content-Security-Policy (or its report-only form), X-Content-Type-Options:
     nosniff, Referrer-Policy, and frame protection (X-Frame-Options or CSP frame-ancestors). Homepage only (headers
     are usually set once per site), https only (as the HSTS note). The crawler now keeps referrer-policy,
     x-frame-options, permissions-policy and content-security-policy-report-only. Not a ranking issue, said in the
     note. `tests/test_brand_neutral.py`: three sites' Info caps +1, each naming this note. Tests:
     `tests/test_w12_security_headers.py`.

263. **A canonical that names an address which redirects (Efsa Ediz's request, agent implementation, 2026-10-27).**
     IDX-4 followed a canonical's redirects and judged only where they ended; seen live on Moodist, the homepage's
     canonical /tr/tr/ redirects back to / and was reported only as an Info "canonicalized to the same content".
     Now: a canonical whose redirects end at the page itself is High ("redirects back to the page itself"; the page
     is not judged again as same/different); one whose redirects end elsewhere is Medium, and the content there is
     still compared. Verified and documented (Google: name the preferred, final URL). The other cross-page cases the
     comparison listed (canonical to a noindexed or broken page, HTML vs HTTP-header conflict) were already covered.
     Tests: `tests/test_w12_canonical_redirect.py`.

264. **Place pages that differ mostly by the place name (Efsa Ediz's request, agent implementation, 2026-10-27).** Seen
     live on Adile: 72 branch pages 0.89–0.95 alike, reported at most as a Low near-duplicate group, because the
     place name in every sentence keeps pairs under the 0.9 threshold. IDX-8 now also groups the pages of one path
     section (at least `location_template_min_pages` = 5) and compares their own text with the words of each page's
     own last path segment masked. When at least five pages and half of the section have a twin above the
     threshold, one Medium finding names the section, each page's closest twin and the similarity (estimated;
     Google's doorway-abuse policy as the documented basis). Tests: `tests/test_w12_location_pages.py`.

265. **Ordinal suffixes are not words for the language guess (FA-034; agent implementation, 2026-10-27).** A Turkish
     shop's product list ("2.si %10 indirimli" on every card) was called Italian. `language.words_of` now drops an
     ordinal suffix written after a number (2.si, 3üncü, 2nd, 1º) before counting stopwords, and "si" joins the words
     that are ordinary in Turkish. Tests: `tests/test_w12_false_alarms.py`.

266. **Place pages are not articles by og:type (FA-035; agent implementation, 2026-10-27).** FA-033 kept branch pages
     typed Restaurant from being articles; untyped branch pages with a site builder's og:type=article still were.
     `page_kind` now leaves a page under a place section (`PLACE_SEGMENTS`: sube, semt, bolge, ilce, magaza, lokasyon,
     branch, location, store and their plurals) without a guessed kind, so no type is expected of it. Tests:
     `tests/test_w12_false_alarms.py`.

267. **Text after an early-ended head is body text (FA-036; agent implementation, 2026-10-27).** The analyzer left out
     every text node until </head>, so an accessibility widget printed inside <head> (DECISIONS 260) was invisible in
     the raw view and its labels became RND-1 "content only after JavaScript". Text and scripts after the element
     that ended the head are now read as body (as browsers do): visible text, word counts, and `in_head` for the
     render-blocking script note. Tests: `tests/test_w12_false_alarms.py`.

268. **A story's dialogue is not a question-and-answer block (FA-037; agent implementation, 2026-10-27).** STR-3's
     FAQPage suggestion and STR-2's "questions not marked as headings" observation now skip an article (Article or
     BlogPosting markup, or og:type=article) whose questions are all plain running text (`narrative_questions`).
     Marked questions (headings, <summary>, <dt>, buttons) on any page are still read as a block. Tests:
     `tests/test_w12_false_alarms.py`.

269. **Stable rule ids for findings (Efsa Ediz's request, agent implementation, 2026-10-27; schema 1.18).** Every finding
     title already matches one frame in `maya_audit_web/wording.py`; that frame's key ("str2.home_hidden_h1") is now
     the finding's `rule_id` (and a review item's). The engine does not import the web package, so
     `scripts/rule_catalog.py` writes the frames to `maya_audit/rule_ids.json`; `maya_audit/rules.py` assigns ids when
     a finding is made and again after severity, root-cause grouping and copied reassessment (titles can be reworded
     there). Schema 1.18 adds `rule_id` to finding and review item. On five real reports, 270 of 270 findings get an id
     that agrees with the web package's own matching. Root-cause grouping and launch-gate labels still match English
     titles, but a test now fails when any of their patterns no longer matches a title the engine writes, so a
     rewording can no longer switch them off silently. Tests: `tests/test_w12_rule_ids.py`, every neutral site's
     findings (`tests/test_brand_neutral.py`).

270. **Rule catalogue fills the professional report's cards (Efsa Ediz's request, agent implementation, 2026-10-27).**
     `maya_audit/rule_actions.json` holds, per rule id, a verb-first action title and two to four card steps in Turkish
     and English, written once (72 rules: every non-Info rule seen in 23 real reports plus this round's new ones); no
     numbers, so a report's numbers still come only from report.json. The maya-audit-pro skill fills each card's title
     and steps from it, the verify line from the engine's translated "expected" sentence, the action-plan rows and
     "later" labels from the same titles, and the five Note cards' titles and verify lines from fixed texts; a field
     it cannot fill safely (no catalogue entry, a fix sentence that does not fit the box) stays for the model. On four
     real reports the model's fields went from 91–121 to 16–17. Tests: `tests/test_w12_rule_actions.py`, the skill's
     `tests/test_client_text.py`.

271. **Structured evidence and per-card address checks (Efsa Ediz's request, agent implementation, 2026-10-27).**
     `maya_audit/facts.py` adds `evidence.facts` (url, element, observed, expected-as-limit) to the findings of 23 rules
     from the evidence their checks already record (nothing re-measured; an unexpected shape gives no facts). The
     professional report prints the first fact under each card's status ("Kanıt: / · 651 KB (sınır 500 KB)") and keeps
     each finding's addresses (`known_paths`); `validate_data.py` now refuses a site address in any text field that the
     card (or, for summary fields, any card) does not hold. On this week's hand-filled reports it caught addresses taken
     from live checks rather than from the audit. Tests: as 270.

272. **The audit's second look at its most serious findings (Efsa Ediz's request, agent implementation, 2026-10-27).**
     `maya_audit/verification.py` runs last in `run_audit`, after severities, rule ids and facts. Every High/Critical
     finding, and every Medium one from an unverified check (`launch_gated`), whose rule has a re-test is asked again:
     a 4xx address (status), an empty page (empty again?), the homepage's Organization block (still unparseable?) and
     the homepage outline (still too few visible headings?). Maya's own user agent, a new fetcher at the crawl's pace
     and never faster than robots.txt's Crawl-delay, only where robots.txt allows Maya's token, at most
     `verification_urls_per_finding` (2) addresses per finding, `verification_max_requests` (12) in all, within
     `verification_time_s` (60 s) of its own, which may run past the audit's time limit as the sitemap check does; a
     stop request ends it. For a 4xx or empty page one browser request is recorded beside the result and never
     decides it (off with `--no-probes`). The finding gets `verification` (schema 1.19): confirmed / changed /
     not_reproduced / not_retested with the reason. **It never changes severity, title or scope**: a page that failed
     once and answered once is reported as found, with both answers. Left out on purpose: the hidden homepage <h1>
     (judged from the rendered page's computed style, which a raw request cannot see) and the homepage TTFB (already
     a median of three requests). `--no-verification` switches the stage off. The requests come after the integrity
     gates (INT-*) and are counted in `crawl.verification`, not in the crawl's request log. Tests:
     `tests/test_w12_verification.py`.

273. **Comparing two audits by rule id, with a trend (Efsa Ediz's request, agent implementation, 2026-10-27).**
     `maya_audit_web/comparison.py` still matches findings by check and by title with its numbers masked. A finding
     left unmatched that way is now matched by its `rule_id` (DECISIONS 269; computed from the title for a report
     saved before 1.18) when exactly one unmatched finding on each side holds it, so a title reworded between versions
     is not read as "one problem gone, one new". Two unmatched findings sharing a rule on one side are never paired by
     guess. A problem still reported carries `severity_before`, `matched_by` ("title" | "rule_id") and `trend`:
     "worse" when its severity rose or it names more pages, "better" when it fell or names fewer, "same" otherwise;
     page counts decide only when the two audits ran under the same conditions. `counts` adds `worse` and `better`.
     Nothing here says "fixed". Tests: `tests/test_w12_drift.py`.

274. **Two requests on one clock tick are still two observations (agent fix, 2026-10-27).** IDX-1 counts an empty page
     as "repeated" when two successful empty answers have different `requested_at` values, so that one stored answer
     read by two checks (a sitemap URL that llms.txt also names) is not counted twice. On Windows the clock ticks in
     ~16 ms steps, and on a fast site the crawl and the IDX-1 refetch could share one timestamp: a page that was empty
     twice was then reported as seen once (S3, Estimated) instead of repeated. This was the cause of the three tests
     known as flaky since 22 October (`test_preview16_grouping`, `test_round2_empty_and_googlebot`,
     `test_round2_sitemap_and_llms`), reproduced 5 of 5 under load. The refetch is always a request of its own
     (`index_data._observe`), so it is now counted by its source as well as its time; the other sources are unchanged.
     Test with a fixed clock: `tests/test_w12_clock_tick.py`.

275. **A priority's second line is shown, and a cut is caught (agent fix, 2026-10-27).** On the professional report's first
     page each review priority sits in a row of fixed height (68 pt). Its text box allows two lines (150 characters),
     but the title, the gap and the padding left room for one and a half, so the second line was cut by the row; the
     overflow check looked only at the text's own box and passed it. The row's padding and the gap are smaller (the row
     keeps its height), and the overflow check also measures the fixed-height boxes around a slot (`.pitem .tx`,
     `.todo`). Tests in the skill's `tests/test_client_text.py` measure the cut in a browser apart from the check.

276. **The pro skill's claims about the engine are tested (Efsa Ediz's request, Ö7, agent implementation, 2026-10-27).**
     `tests/test_w12_skill_claims.py` checks what the maya-audit-pro SKILL.md says under "Motorun bilinen tuzakları"
     against the engine, as claude-seo's canonical-facts test does for its instructions. Its first run found two stale
     claims, both fixed: (1) the skill told the model to write "not confirmed by another client" for an IDX-1 empty page
     marked "repeated measurement", but the engine marks it so only when a browser got an empty page too
     (`repeated_empty`); the skill now explains each `observation_strength` and the test fails when the engine writes
     one the skill does not explain; (2) the skill said it used the ratio in the IDX-5 title, but its pattern matched
     none of the engine's current forms (the evidence judgments reword it as "N sitemap URL observation(s) require
     differentiated review (M checked)"), so the KPI and the table showed the narrowed scope count. The card's status
     line also says what the engine's second look saw (DECISIONS 272).

277. **The second look re-tests empty pages under their running name (agent fix, 2026-10-27).** The live validation of
     DECISIONS 272 on four sites found that Adile's High empty-page finding was never re-tested ("no finding in
     scope"): while the audit runs it is `idx1.empty`, and the evidence judgments rename it `judgment.empty.*` only when
     the report is written, after the second look. `idx1.empty` is now in `verification.RETESTS`. Run alone on the
     saved Adile report against the live site: both empty-page findings re-tested and confirmed (6 requests). Under
     `idx1.empty` no browser request is added: the index step has already asked a browser (`empty_browser_check`). Test:
     `tests/test_w12_verification.py::test_an_empty_page_is_asked_again_under_the_name_it_has_while_the_audit_runs`.

278. **One release gate for a report, its cards and its validation note (Efsa Ediz's request, agent implementation,
     2026-10-28; schema 1.20).** An independent review of the w12 reports (`seo_audit/maya-w12_2026-10-27/
     BAGIMSIZ_DENETIM.md`, plan `RELEASE_GATE_PLANI.md`, both outside this repository) found errors that no single check
     made: Enpara's High card listed the site's own 404 page as the affected address, said the addresses were in the
     sitemap (none was), and "re-tested: confirmed" meant only that the 404 page answers 404; a fixed Note title named
     "menu language" and "address spelling" on sites with neither; Carpex's card told 69 pages with no <h1> to "fill the
     empty <h1>"; /blog/2 (a list of posts) was told to add Article; 104 pages were reported twice for one cause (tags
     after an early-closed <head>), the robots tag at Info and at High; 58 canonicals that could not be read were
     silently treated as absent; 7 of 11 High findings carried no re-test state; and the validation note matched its
     checklist by title, so "kept" and "9/9" rested on findings that held none of the items' addresses.
     Owner decisions: the gate never changes a finding or a severity, it only reports violations and decides PASS /
     CONDITIONAL / BLOCKED; existing modules are extended, not copied; page kind per page with "unknown" allowed and no
     content advice for unknown; the pre-release summary is shown to the person, never in the client PDF; the skill
     holds no copy of the gate and refuses the PDF when it cannot run it; IDX-1 keeps its severity, its affected
     addresses become the pages to edit and the failing target is a separate field; the validation note is generated
     by finding id with manual notes apart.
     (1) `maya_audit/release_gate.py`: rules RG-1..RG-13 over the finding contract only (no brand text; a test reads
     the source for brand names). It runs at three points: G1 `report.build_report` writes `release_gate` (after
     everything else); G2 the skill's `validate_data.py` and `render.py` (no PDF on a hard violation or without the
     gate: "Release gate çalıştırılamadığı için PDF üretilmedi."); G3 `maya_audit_web.comparison.validation_note` /
     `python -m maya_audit_web.comparison --checklist`. The skill's card-address check moved into the gate (RG-3).
     (2) Schema 1.20: Finding `page_types`, `measurement` (`claims`: element, state, pages), `remediation` (catalogue
     task, content advice and its page kinds), `dedup_key`; optional report key `release_gate`. `facts.contract`
     fills claims and remediation; `structure.annotate_page_types` the kinds ("404" for 404/410, "unknown" when not
     read or not established).
     (3) STR-2: no <h1> and an empty <h1> are two findings (`str2.empty_h1`); the homepage's single-page finding keeps
     its weight. (4) `page_kind`: "pagination" on two of three signals (page number in the address, in the title, links
     to several posts), "category" for category/tag/collection paths; STR-3 expects a type only of kinds that have
     one; `str3.expected_type` is content advice for article/product/pricing/faq only. (5) `root_cause._head_closed`:
     STR-10 absent-tag and ACC-3 stray-robots pages whose tag comes after the break are said under TSEO-1
     (`absorbed_from`, `dedup_key`); IDX-4 lists such canonicals as not assessed (element, pages, reason), never as
     absent. (6) `index.broken_link_sources` (after severity): IDX-1's referenced-4xx scope is the source pages and
     the sitemap entries that end at the error; `target_urls`, `link_sources`, `sitemap_only` in evidence. A sitemap
     URL whose redirects end at a page the crawl saw answer 4xx is "not_found". (7) The second look re-tests a broken
     link at its source (still linked? still 4xx at the end?), follows a sitemap entry's redirects, records `subjects`,
     and leaves every High finding with a state (`not_retested` with its reason). (8) Skill: Note titles and verify
     lines are built from the topics present (`topics`), catalogue steps may carry `step_when` (the sitemap step only
     when an address is in the sitemap), cards carry `finding_ids`, `verification_state`, `target_urls`; the card
     shows "Hatalı hedef URL" and "Etkilenen kaynak sayfa" apart and "Yeniden sınanmadı" when not re-tested.
     Not changed: severities; STR-12 and STR-9 on the same pages (the gate reports them only when they share a
     dedup_key, which they do not yet); the hidden-<h1> and TTFB re-tests (DECISIONS 272). Reports saved before 1.20
     carry no contract fields: the gate then blocks content advice and High findings without a state, by design;
     regenerate them with this engine. Tests: `tests/test_w13_*.py`, the skill's `tests/test_client_text.py`.

279. **Missing engine data is an error; batch file names are lower case (owner's request, agent implementation,
     2026-10-29).** (1) `rules.engine_data` loads `rule_ids.json` and `rule_actions.json`; a missing, unreadable or empty
     file raises `rules.EngineDataMissing` naming the file. Before, `facts._catalogue` returned `{}`, so a broken install
     looked like "no action needed" for every finding. Both files are package data since stage 01
     (`tests/test_distribution_contract.py`). (2) `batch` writes `<name>.json`, `.md` and `-evidence/` under a lower-case
     slug (`Alpha` → `alpha.json`): one name on case-sensitive and case-insensitive file systems; two CSV names that differ
     only in case were already refused. (3) Test harness only: `tests/offline_process.environment` passes the user's
     Playwright browser folder to child processes on macOS/Linux, as it already did on Windows.

280. **One final result for every output; broken internal links end to end; the release gate on every web download
     (owner's request, M1 slice A, agent implementation, 2026-10-29).** (1) `maya_audit/final.py`: `settle` (broken-link
     tracing, rule ids, facts, page kinds; no request) and `verify` (the controlled re-test) run inside `run_audit` and
     again in `firecrawl.reader.apply` when a reader replaced checks (`after_provider`): a replaced High finding now gets
     page kinds and a re-test state; the second re-test covers only findings with no record, within what is left of
     `verification_max_requests`, and is recorded as `crawl.verification.after_provider`. `AuditOutcome` carries the
     transport and hooks for it (never pickled into a snapshot). (2) `final.seal(outcome)` builds the report and the full
     address lists once (`report.report_and_affected`); the CLI and the web worker both use it. The companion
     `affected-urls.json` now comes from the qualified checks the report was built from (before: the unqualified ones).
     `final.from_report` reads a saved report; one saved before schema 1.20 gets the gate run on it. Supplementary panels
     may be added after sealing; `digest` covers checks, answer panel, order and gate. (3) Broken-link cards
     (`final.broken_link_cards`): one per link (page to edit, link text, the address it links to, where it ends and that
     address's status) and one per sitemap entry; "replacement: unknown" always, since the right address is never
     known. Shown in the Markdown (CLI and web), on the web's finding rows and in the concise (client) and full PDF.
     (4) Web: PDF, Markdown and JSON downloads and the final client-report export are refused (409 `release_blocked`)
     when the gate is BLOCKED; `draft=true` gives a draft (file name `-draft`, a banner in the PDF/Markdown/print view;
     the JSON is the record and carries the decision). Every report download sends `X-Maya-Release-Gate`. The results
     card offers the draft links when blocked. The evidence zip is not a report and is not gated. CONDITIONAL is not
     blocked. (5) IDX-1 judged only the answers Maya received but was called a pass when the crawl found addresses it
     never requested (page cap): it now lists "addresses found but never requested" as not assessed, so it is partial
     (INV-01). A reader's content cap still does not touch IDX-1. Not changed: severities; batch and the skills still
     build their own report (stage 05); `render_markdown` still runs its own `qualify_checks` pass.

281. **The main heading: one finding per state, raw HTML and rendered page apart (owner's request, M1 slice B, agent
     implementation, 2026-10-29; corrected by 282 the same day).** (1) STR-2 keeps separate findings for each state:
     homepage missing (`str2.home_no_h1`, Medium), homepage empty ("The homepage has no meaningful <h1> text", rule
     `judgment.heading.home`, Medium; now built as its own finding with its own expected sentence and fix instead of
     retitling the "no <h1>" one), homepage hidden (High), and on other pages missing, empty, hidden-only (Low) and more
     than one (Info). (2) Every heading finding records `evidence.h1_sources`: per page the raw HTML's <h1> texts and the
     rendered page's visible ones: `[]` when the page was rendered and showed none, `null` only when it was not rendered
     (unknown, never "none"). (3) Withdrawn (282): a separate `str2.js_only_h1` finding was added here on the claim that a
     page whose <h1> appears only after JavaScript "was silently counted as having one". That claim was wrong: RND-2
     already reports it ("headings or prices that appear only after JavaScript", with the heading text). STR-2 counts such
     a page as having an <h1> and leaves the JavaScript dependence to RND-2. (4) Action entries added for `idx6.broken`,
     `str2.home_no_h1`, `judgment.heading.home`, `str2.hidden_h1`, `str2.many_h1`. Not changed: severities of the
     existing states. Tests: `tests/test_m1_h1.py`.

282. **Fixes from the judgment review of 280 (5) and 281 (owner's request after a `maya-judgment-validator` review,
     agent implementation, 2026-10-29).** (1) IDX-1's part is now "addresses found but not fetched by the crawl": the
     sitemap check (IDX-5) can request a sitemap-listed address the page cap left unread, so "never requested" was false
     there; IDX-1 still has no answer for those addresses and stays partial. (2) `str2.js_only_h1` removed (frame, rule id,
     action, explanation note, Turkish wording): it repeated RND-2's finding for the same page and heading (281 (3)).
     (3) `h1_sources.rendered_h1` is `[]` for a rendered page without a visible <h1>; it was `null`, the value for "not
     rendered". (4) A page whose HTML was cut off at the fetch-size limit (`body_truncated`) with no <h1> before the cut
     (not even an empty one) is no longer "no <h1>" or "The homepage has no <h1>" (confidence verified): the rendered page
     is built from the same cut body, so the evidence cannot tell. STR-2 lists it in `evidence.h1_cut_off` and coverage
     part "pages whose HTML was cut off before an <h1>", so the check is partial; its pass summary counts only the pages
     assessed. Not changed: severities; the long-page and section-heading checks on a cut-off page (same limitation,
     not reviewed). No schema bump: evidence keys only, one finding title removed. Review records and reproducer:
     `maya-judgment-validator` session, 2026-10-29. Tests: `tests/test_m1_h1.py`, `tests/test_m1_broken_links.py`.

283. **Report fixes before the w14 release (owner's request, agent implementation, 2026-10-29).** Brand-independent; no
     site-specific code. (1) The `maya-audit-pro` client PDF is built from the shared final result: `build_data.py`
     loads the report through `maya_audit.final.from_report` (as installed, `--maya-src`, or the repository holding the
     skill) and refuses to build without it; data.json records `_digest` and `_gate_decision`, and `validate_data.py`
     refuses data built from another state of the report (digest differs). A broken-link card carries `link_rows` from
     `final.broken_link_cards` and prints a "links to edit" table (page to edit, link text, links to, ends at with its
     status, replacement "unknown"), two rows on the card and every row in the address CSV; the gate's RG-3 also checks
     the table's pages to edit. Heading cards come from the separate H1 findings (281/282) through their rule ids.
     (2) The client PDF's "pages with problems" headline counts only pages whose worst page-specific problem is Medium
     or higher (`problem_summary.by_page[].worst_severity` S1–S3); the label and sub-line say so ("Orta ve üstü sorunlu
     sayfa", "düşükler sayılmaz"). Carpex showed 145/146 because pages with only Low problems were counted.
     (3) STR-5's "The brand is named N different ways" and "og:site_name holds the page title" share
     `dedup_key = "str5.site_name"`: on the same pages they are one cause said twice, and the release gate's RG-9 (soft)
     now reports it. The name finding's address list is every page a counted name was seen on (as its evidence already
     counted); before, a title-suffix name listed only its first page, so the overlap could not be seen. It stays
     site-wide; severities unchanged.
     (4) PRF-1's homepage time-to-first-byte finding is Medium (S3), not High: it is one measurement from Maya's own
     network (the median of its samples in one audit), and the second look never repeats it (272), so it is never
     re-tested. This lowers 258 (4); the finding's note says why. Test: `tests/test_w11_homepage.py`.
     (5) The client PDF leaves out the "Arama ve performans" page when the audit has no search data, no lab result and
     no field data (the summary is then three pages; tabs and page numbers follow). Page 1's lab KPI still says "not
     measured", so the absence is stated once instead of filling a page with empty boxes. data.json without a `search`
     key keeps the old four pages.
     (6) The client PDF's address CSV keeps its UTF-8 byte-order mark and uses ";" as the delimiter in Turkish (Turkish
     Excel reads "," as the decimal mark and put each row in one cell); English keeps ",".
     (7) `RELEASE-SNAPSHOT.json` and `CHECKPOINT-VERIFICATION.md` were team-preview-23's (0.2.6 / schema 1.16) inside the
     0.2.8 w13 zip. `tools/release_metadata.py --release w14` writes both from the source (version from
     `maya_audit.__version__`, schema from `schema.py`, files = tracked files without export-ignore, hashed); the
     checkpoint claims no result and points at `docs/IMPLEMENTATION-STATUS.md`. `.gitattributes` now also export-ignores
     `benchmarks/real-sites/` (real sites' expected results); `reviews/`, `.env` and `.claude/` were
     already. No archive is built here. Test: `tests/test_release_metadata.py`.
     (8) On a page whose HTML was cut off at the fetch-size limit (`body_truncated`), the homepage-outline finding ("The
     homepage has N visible section heading(s) …") and the long-page finding ("… have no subheadings") no longer fire
     when the cut body has too few <h2>/<h3>: the rest of the page may hold them. STR-2 lists the page in
     `evidence.sections_cut_off` and coverage part "pages whose HTML was cut off before their section headings could be
     counted" (with the reason), so the check is partial, not a pass. Completes the limitation 282 left open.
     (10) The client PDF's "Değerlendirilmeyen kapsam" count no longer counts the unread addresses again: IDX-1's
     "addresses found but not fetched by the crawl" and TSEO-1's "discovered pages not fetched" say the same addresses as
     the report's one "not read" figure, as "pages found but not read" does. `maya_audit.coverage.UNREAD_RESTATEMENTS`
     names them once; the skill's count leaves them out (partial-crawl fixture: 25 → 23). The web's gap list is
     unchanged (it lists IDX-1's part with its own reason). (9 was the report-checker review, no change.)
     (11) Correction to (7): two tests did read `benchmarks/real-sites/` and failed in the extracted w14 archive.
     `real_sites_benchmark.main` now refuses `collect` without `--live` before reading the corpus, and the manifest test
     skips when the corpus is absent (it is never in a release). Found by the w14 archive verification.


284. **Fixes after the 2026-10-29 client PDFs (owner's request, agent implementation, 2026-10-29).** Seen in the
     `maya-audit-pro` PDFs for three sites; brand-independent, no site-specific code. Test file for the engine parts:
     `tests/test_w14c_fixes.py`; for the skill: `.agents/skills/maya-audit-pro/tests/test_client_text.py`.
     (2) The skill takes a card's owner and effort from the engine's catalogue (`recommendation_catalog.note`); its
     static `sahip_efor.json` is the fallback only and gets the same rows. The static copy named İçerik for an
     early-closed <head> and a hidden <h1>; both are template and markup work (Geliştirici), as are template markers.
     (3) STR-2's "The homepage's only <h1> is hidden" is Medium (S3), not High: one reading of the page's markup or
     computed style, and the second look has no re-test for it (`verification.RETESTS`), so it is never re-tested. This
     lowers 258's High; the finding's note says why. A saved report keeps the severity it was written with. The
     page-reader contract test (`test_m1_broken_links.py`) used it as its High example: it is Medium there now and, like
     any Medium finding without a re-test, carries no re-test record (found by the full suite after the commit).
     (4) STR-8 leaves out a `<div>` grid that belongs to a calculator even when no control is inside the grid: a form
     control (or `role="slider"`) in its parent or grandparent block, settled when the page ends because the input
     column may come after the result column (`controls_beside`), or a block whose class, id or heading names a
     calculator (`calculator_named`: calculat, calc, hesapla, simulat, simülasyon, rechner). Enpara's loan calculator
     showed its computed amounts as "pricing laid out as <div> grids". Body, main and html are too wide to count: a
     search box elsewhere on the page does not make a price list a calculator (test).
     (1) The client PDF makes one card per cause, not per finding (`build_data.Builder.groups`): findings with the same
     engine `dedup_key` (an early-closed <head> reported for canonical tags and for meta tags, closed by the same
     element; STR-5's brand names and og:site_name), IDX-1's repeated and single empty answers on overlapping sections,
     and two findings of one check whose cards would carry the same catalogue title (two "Tıklayınız gibi genel
     bağlantı" cards). The first in priority order leads (severity, schedule, owner, steps); the card names every
     finding (`finding_ids`, addresses united, each address's own finding in the address CSV) and shows one line per
     finding (severity · scope · title, up to " — ") in place of the single evidence line. Findings whose re-test states
     differ stay apart: a card shows one state, and RG-4 refuses "confirmed" unless all are. The findings table and the
     action plan list one row per card's lead. The release gate needed no change.
     (5) The client PDF's sitemap card for addresses under review (`total_review_scope` with `sitemap_decisions`) counts
     them by reason: redirect to an error page (Location at /404, a not-found path or an `aspxerrorpath` page), redirect
     elsewhere, empty again, empty once (unconfirmed), not found, server error, noindex. One line per reason on the card
     and the reasons with counts in the findings table ("Site haritası: hata sayfasına yönlenen 41, yönlenen 1,
     noindex 1"), instead of "43 addresses need separate review". The label says "error page", not "404": 404 is not
     one of the report's numbers, and a not-found path need not be a 404. The counts add up to the finding's scope. The
     engine's finding and title are unchanged; the reasons come from the decisions it already records.

285. **Rules changed since a report was written, applied offline to its saved findings (owner's request, agent
     implementation, 2026-10-29).** `maya_audit/reassess_rules.py`, `tools/reassess_saved.py`; test
     `tests/test_reassess_rules.py`. A saved report keeps the severities and findings it was written with (284). This
     applies 284 (3) and (4) to the observations the report already holds, on a copy, with sockets refused:
     the hidden homepage <h1> takes `HOME_HIDDEN_H1_SEVERITY` (now one constant for the check and the reassessment) and
     its note; an STR-8 pricing grid in a block named as a calculator (`analysis.CALCULATOR_NAME` on the grid's saved
     selector, label, heading) is left out, and a pricing finding with no grid left is removed. The other 284 (4) test,
     a form control beside the grid, needs the page structure a report does not keep: not assessed, said in
     `generation.analysis.not_assessed_offline` and, when a grid is kept, as a coverage part of STR-8. Then the severity
     policy, priority order, problem summary (findings in priority order, as `build_report` counts them) and release
     gate are derived again; nothing else is re-run. `judgments.qualify_report` was not used: it re-runs STR-7 and
     RND-4 on Maya's own page copies, which mixes readers when Firecrawl read the site (Adile's WebP count moved
     497 → 503) and rewrites every scope. The tool writes a new folder, never the source, never inside `~/.maya-audit`.

286. **A rate-limited start page is waited out once, then asked for through the basic reader (owner's request, agent
     implementation, 2026-10-29).** nihan.com.tr answered Maya's first page request (the homepage) with Cloudflare's
     429 and `Retry-After: 60`, over the 30 s cap, so the crawl stopped with nothing read and Firecrawl never started
     (52). (1) The start page alone has its own cap, `start_max_retry_after_s = 120`: a 429 there with a Retry-After up
     to it is waited out once and asked again; any other page keeps the 30 s cap, and a second 429 stops the crawl as
     before. Both requests are in the page's `classification_evidence` as "attempt 1: status 429, Retry-After 60 s,
     server cloudflare, cf-ray … at …; waited 60 s and asked once more" and "attempt 2: …" (a new page field would have
     changed the frozen 1.20 report shape; the structured record stays in memory as `PageFetch._attempts`). (2) When the
     crawl stopped on a rate limit and no page at all was read, the Firecrawl reader asks for the homepage alone, once:
     max 1 page, no sitemap discovery, the basic proxy forced on the client for that request (the plan's own proxy is
     restored after) and never the bot-protection bypass. `firecrawl.homepage_fallback` records the URL, proxy, bypass
     (always false) and whether it was read. Once any page was read, 52 holds: no reader request after a rate limit.
     Tests: `tests/test_rate_limited_start.py`; `test_run_clock.py`'s rate-limit test now expects the homepage only.

287. **A report that read no page is a draft, not a delivery (owner's request, agent implementation, 2026-10-29).**
     The nihan.com.tr report read 0 pages and the gate said PASS. Release gate RG-14 (hard): when
     `audit_status.content_coverage.pages_read` is 0 the decision is BLOCKED, "site content could not be read". The web
     app already treats BLOCKED as draft-only (download refused unless asked for as a draft, print view with the draft
     banner), and `maya-audit-pro` prints no PDF on a blocked gate and keeps the HTML. A report without a coverage
     record (older ones) is not judged on it. A saved report is judged with the gate it was sealed with
     (`final.from_report` re-runs the gate only when none was saved), so this applies to reports written from now on
     and to every `maya-audit-pro` build (its validator runs the gate afresh). In the client PDF a report with nothing
     read drops the "Orta ve üstü sorunlu sayfa 0 / 0" tile, and the action plan drops the "Öncelikli aksiyonlar" table
     when it has no row. Tests: `tests/test_nothing_read_gate.py`, skill `NothingRead`.

288. **Maya's crawler blocked by 429 on pages: said so, gated, and read on only with the owner's approval (owner's
     request, agent implementation, 2026-10-29).** The second nihan.com.tr audit read 1 page: every page request from
     Maya's crawler got Cloudflare's 429 with `Retry-After: 60`, also after the one wait (286), while robots.txt, 26
     sitemap files and llms.txt came back 200 in the same minutes, and Firecrawl read the homepage at once. That is a
     rule against this crawler on pages, not "too many requests". `maya_audit/maya_blocked.py` names it: every page
     asked for answered 429, the start page among them, nothing read, and a robots.txt, sitemap or llms.txt request on
     the same host answered 200. Then (1) the crawl's stop detail starts "blocked for Maya's crawler (429 on pages):";
     ACC-9 has its own rule `acc9.blocked_429` ("Maya's crawler blocked (429 on pages): {who} answered N of M page
     request(s) with 429 while robots.txt and the sitemap were served. AI crawlers may get the same treatment"), a fix
     that points at the blocker's bot and rate-limit rules instead of "try again later", and `evidence.maya_blocked`;
     the status note says "blocked (429 on pages)" instead of "rate-limited"; Turkish: "Maya'nın tarayıcısı engellendi
     (sayfalarda 429)". (2) This relaxes 52 only with the site owner's approval: when it holds and the plan's "site
     owner approved bypassing bot protection" is ticked, the Firecrawl reader goes on past the homepage as the page
     reader with the plan's own options (up to its page cap). Without the tick it stops at the homepage, through the
     basic proxy, as 286 does. A plain rate limit (robots.txt refused too) never goes on, approved or not. (3) The
     record is saved: `firecrawl.crawl_blocked.homepage_fallback` (`maya_blocked`, `owner_approved_bypass`,
     `continued`, `proxy`, `pages_asked`, `read`). 286 kept it at the section's top level, where `panel.SECTION_KEYS`
     dropped it; a new top-level key would change the frozen 1.20 shape, `crawl_blocked` is already one of its keys.
     (4) Release gate RG-14 is hard also when the homepage alone was read and the reader did not go on: the report is a
     draft. (5) The client card for `acc9.blocked_429` carries one fixed line: "Yapay zekâ tarayıcıları da aynı
     muameleyi görebilir; {Cloudflare} üzerindeki bot ve hız sınırı kurallarını kontrol edin." Tests:
     `tests/test_rate_limited_start.py`, `test_run_clock.py`, skill `BlockedOnPages`.
     **Changed 2026-10-30 (owner's decision), replacing (2) and (4):** when it holds, the Firecrawl reader goes on as
     the page reader up to the plan's page cap **without** the owner's tick, as it already does for a site that
     challenges Maya's crawler: robots.txt is applied to every address (disallowed ones are left out), Maya's pace
     holds, and the proxy is the plan's, which is basic; the stronger (stealth) proxy still needs "site owner approved
     bypassing bot protection" (`Options.problem` refuses it in the plan otherwise). So 52 is relaxed for this case
     with the basic proxy. The read is the audit's main page reader (`purpose` "main page reader", `homepage_fallback`
     `continued: true`); ACC-9 keeps its `acc9.blocked_429` finding and AI-crawler warning (it is not rewritten into a
     challenge note); the status line says "Maya's own crawler was blocked (429 on pages) on N of M page request(s);
     K page(s) read through Firecrawl". RG-14 is back to 0 pages read only: a report read through Firecrawl is judged
     as usual, PASS or CONDITIONAL. A plain rate limit (robots.txt refused too) still stops at the homepage.
     The web page names the case from the report's own crawl record (`maya_blocked.holds` on the saved data, so older
     reports too): heading "Blocked for Maya's crawler (429 on pages): Cloudflare" in place of "The site blocked this
     audit: Cloudflare (rate limit)", badge "Blocked for Maya's crawler (429 on pages)" in place of "Rate-limited",
     the reader line "homepage only, after Maya's crawler was blocked (429 on pages)" in place of "… after the site
     rate-limited Maya's crawler", and a step to check the blocker's bot and rate rules in place of "try again later";
     ACC-9's summary says "{who} blocked Maya's crawler (429 on pages)". Turkish: "Maya'nın tarayıcısı engellendi
     (sayfalarda 429)". The stop code `rate_limit` stays a code. Test: `tests/test_web_blocked_on_pages.py`.

289. **A rate limit stops Maya's own requests, not the page reader; one count of pages read (owner's request, agent
     implementation, 2026-10-30).** The third nihan.com.tr audit (engine `375ae84`) read 1 page: Maya's crawler got 200
     on the homepage and 429 (`Retry-After: 60`) on `/en`, the crawl stopped, and Firecrawl, ticked as the page reader,
     was never started ("the site rate-limited Maya's crawler, so no further page was asked for through a reader").
     (1) A 429 stops Maya's own page requests, as before; it no longer stops the page reader. When the audit has one,
     it reads the discovered and sitemap addresses up to the page cap as on any audit: robots.txt allows each address,
     Maya's pace holds, the proxy is the plan's (basic unless the owner approved bypassing bot protection). Any 429 on
     pages, not only all of them. This replaces 52's "no reader after a rate limit" and 286 (2)'s homepage-only read;
     with the reader off nothing changes. `firecrawl.crawl_blocked.after_rate_limit` records it (`maya_stopped`,
     `maya_blocked`, `proxy`, `owner_approved_bypass`, `page_cap`, `read`, `pages_read`); the older `homepage_fallback`
     record of saved reports is still read for display. ACC-9 becomes the reader's note ("Cloudflare rate-limited
     Maya's direct crawler on 1 of 2 request(s). N page(s) were read through Firecrawl instead"), except the 288 block
     (every page 429 while robots.txt and the sitemap were served), which keeps its own finding and AI-crawler warning.
     (2) Any 429 is said as what it did to Maya's crawler, in the engine and the web page and PDF alike: ACC-9 has a
     third rule, `acc9.rate_limited_429` ("Maya's crawler rate-limited (429 on pages): {who} answered N of M page
     request(s) with 429. AI crawlers may get the same treatment", Turkish "Maya'nın tarayıcısı hız sınırına takıldı
     (sayfalarda 429)"), with a fix that points at the blocker's bot and rate rules; the blocked box's heading is
     "Rate-limited for Maya's crawler (429 on pages): Cloudflare", and its "try again later" step is replaced by that
     rule step for any 429 (it stays for a challenge). The client card's AI-crawler line covers both 429 rules.
     (3) "N pages read for content" counts the pages read (`report.pages_shown` = `read_counts`), in the engine's
     `problem_summary.pages_checked`, the web headline and the page box, also for saved reports: a page Maya asked for
     and was refused is not one (the PDF said 2 in the headline and 1 elsewhere; Adile's 37 / 50 was the same gap).
     `page_counts` still records what the crawl fetched. Tests: `tests/test_rate_limited_start.py`,
     `tests/test_web_blocked_on_pages.py`, `test_run_clock.py`, skill `BlockedOnPages`.

290. **Three judgments that read as site problems but are not established (owner's decision, agent implementation,
     2026-10-30).** From the nihan.com.tr audit (`b3198942…`, a Shopify store behind Cloudflare). (1) ACC-4: a request
     with Googlebot's user agent from Maya's own address answered 403 or 429 where a browser got 200 (`refused`) is a
     note (Info), not Medium: a firewall that refuses a fake Googlebot on purpose answers exactly so (Cloudflare does by
     default), and a request from Maya cannot tell that from refusing Google. Its fix (`REFUSED_FIX`) says to check
     Google Search Console's crawl stats for 403/429 to the real Googlebot and to change nothing otherwise. A 5xx, an
     empty page or a 404 for the bot keep their severity. (2) RND-3's raw-HTML guess ("N page(s) that were not rendered
     may hide content behind interaction") is Low (S4), a check: the pages were not opened in a browser and the "load
     more" wording is matched in English only (`RND3_CHECK_NOTE`); what a browser saw (`rnd3.revealed`) stays Medium.
     (3) STR-5: a name given only by page titles that is the brand's main name followed by more words ("Nihan Women's
     Coats", "Nihan Outerwear" on collection pages) is a category title, not another name of the brand: listed in
     `category_titles_not_counted`, not counted; a longer name the site also gives as og:site_name or Organization
     name is still counted. `reassess_rules` applies all three to a saved report (DECISIONS 285). Tests:
     `tests/test_w14c_fixes.py`, `tests/test_reassess_rules.py`, `tests/test_w1_crawler.py`.

291. **Repository ready for a private team GitHub repo (owner's request, agent implementation, 2026-10-30).** Client
     names stay (private company repo, team-only access) and the full history is kept. (1) The real-site benchmark
     corpus (`benchmarks/real-sites/`: real clients' expected results) leaves the repository: moved to
     `~/Projects/maya-audit-private/benchmarks/real-sites/`, untracked with `git rm --cached`, and git-ignored.
     `scripts/real_sites_benchmark.py` reads it from `MAYA_AUDIT_BENCHMARK_DIR` (else the old in-repo place); the
     corpus test skips when neither exists. Its 16 files remain in the history of the 50 earlier commits. (2)
     `.gitignore` also ignores `*.zip`, `*.pdf`, `*.csv` and `report.json`, except the made-up examples
     (`examples/brands.example.csv`, `examples/professional-synthetic/`) and the skills' assets and examples;
     `examples/live-runs/` and `examples/generated-documents/` stay ignored. (3) `.env.example` lists every variable the
     code reads, empty, one comment each ([env] marks those read from the shell only); an empty value is "not set".
     (4) README has a "New teammate" section (clone, venv, `.[team,dev]`, Chromium, `.env`, start the web app, update
     with `git pull` and a restart). (5) gitleaks 8.30.1 on all 50 commits: 9 findings, all SHA-256 file hashes in
     `RELEASE-SNAPSHOT.json` read as generic API keys; `.gitleaks.toml` allows that one generated file, and the re-run
     finds no leaks. A pattern scan of every blob found no key, token or password either.
