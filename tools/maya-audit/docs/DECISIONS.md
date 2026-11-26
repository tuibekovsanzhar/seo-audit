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

292. **The tool moves into `tools/maya-audit/` of the private repository withmaya/seo-audit (owner's request, agent
     implementation, 2026-10-30).** The repository's root holds the team's SEO/GEO research; methodologies and datasets
     get their own folders. The move is one commit of pure renames (`git mv`), so `git log --follow` reaches each
     file's earlier history; the branch is `main` (was `master`); the earlier history and tags (`team-preview-w14` to
     `w14d`) are kept and merged with the repository's first commit. At the root stay `.github/` (GitHub reads
     workflows only there; `ci.yml` now runs every step in `tools/maya-audit` and only when that folder or the
     workflow changes), `.gitleaks.toml` (allows `RELEASE-SNAPSHOT.json` at both its old and new path) and a root
     `.gitignore` for local files there. Every command, the README and the skills now run from `tools/maya-audit/`;
     `git archive` run there ships only this folder, with the same paths a release zip always had. The source commit
     in a report (`source_provenance`) and in the real-site benchmark is found in the nearest folder above a source
     tree (one with `pyproject.toml`) that holds `.git`; an installed package looks only at its own folder, so a
     virtual environment inside some other repository never lends it a commit. `tests/test_release_metadata.py` asks
     Git whether it runs in a checkout instead of looking for `.git` beside the project.

293. **Cheap CI on withmaya/seo-audit, and five tests that failed only there (owner's request, agent implementation,
     2026-10-31).** The first two runs (9 jobs each: Linux, Windows, macOS × Python 3.11–3.13) failed after about 35
     minutes. (1) Three batch tests asked for `Marka.json`/`Demo-Kafe.json`, but batch names files in lower case
     (DECISIONS 279): macOS ignores case, Linux does not. The tests now ask for `marka.json` and `demo-kafe.json`. (2)
     `test_provider_requests_keep_mayas_pace_and_cached_pages_do_not_wait` started its fake clock at 1000 s while the
     audit's deadline is on the real monotonic clock (seconds since boot, 300 s ahead): on a runner that booted minutes
     before, the deadline lay before 1000 s and no request was sent. The fake clock now starts at the audit's own start.
     (3) `tools/reassess_saved.py` found the Maya home only through `Path.home()`, which Windows reads from
     USERPROFILE, not HOME; it now also refuses the folder MAYA_AUDIT_HOME names, and the test sets both. (4) The
     wheel tests skip unless setuptools can build a wheel offline (70.1+, or the `wheel` package): the python.org 3.11
     installers ship an older one without `bdist_wheel`. (5) The 500-page responsiveness test asserts a wall-clock
     bound: marked `timing`, bound 3 s (a runner took 1.96 s against 1.5 s). CI: `.github/workflows/ci.yml` runs on
     push and pull request on one Linux machine with Python 3.12, pip and Chromium cached, `timeout-minutes: 20`, a
     newer push cancelling the older run, and the fast set `-m "not slow and not timing"`; `slow` is every test in
     `tests/slow_tests.txt` (1 s or more each locally; 130 tests, about 60% of the suite's time). The full suite, the
     installed-package smoke and pip-audit run in `.github/workflows/full.yml`, by hand and on `team-preview-*` tags,
     on Linux with Python 3.11 and 3.13, plus Windows and macOS when "all_platforms" is ticked.

294. **Speed, v0.3 stage 2: one shared site limit, Firecrawl several at a time and started when the crawl ends, a smaller
     sitemap sample, a measured time budget, and the progress box (Owner, 2026-11-02; the details marked "agent" are
     agent defaults).** Measured first (IMPLEMENTATION-STATUS, "v0.3 stage 1"): on nihan's 500 pages Firecrawl took 57.5 of
     85 minutes, one call at a time; the sitemap URL checks took 13.8.
     (1) *Shared site limit* (`maya_audit/sitelimit.py`). After the crawl, Maya's own requests to the audited site and
     the page reader's go through one `SiteLimiter`: at most `site_concurrency` (default 5, 1 to 10; `--site-concurrency`)
     in flight. The owner chose, when asked, that request **starts** stay at least the polite gap apart, Maya's and the
     reader's counted together, so the site never sees a higher rate than one crawler (docs/BOT.md, "about one request a
     second", unchanged). Agent: each slot also keeps the gap after its own last request; slot 0 is the audit's own
     thread, so its sequential requests keep exactly the old gap; while Maya's steps run the reader never takes slot 0 and
     a waiting request of Maya's goes first, while the reader may start as long as that does not push the next start of
     Maya's own thread later; the first request through the limit keeps the gap after the crawl's last request. A 429, a 5xx, a failed connection or a first byte over
     `pacing_reset_ttfb_ms` (2 s) steps the limit down to 2, then 1 (recorded in `crawl.backoff.site_limit`). A robots.txt
     Crawl-delay, a widened gap or a rate-limited crawl make the limit 1. The crawl itself stays sequential. INT-4 now
     measures the gap per slot (`crawl.requests[].slot`, schema 1.21) and between starts where requests overlapped, and
     is a violation when more of Maya's requests were in flight than the limit.
     (2) *Firecrawl concurrency.* `Options.concurrency` (default 5, 1 to 10; `MAYA_AUDIT_FIRECRAWL_CONCURRENCY`,
     `--firecrawl-concurrency`). The owner's plan is Standard (25 concurrent browsers, 100,000 credits a month).
     Requests go through the shared limit; without one (a clock made by hand) the reader reads one at a time, as before.
     Agent: one at a time until the first page is read, so a site or reader that turns everything away costs what it
     did; answers are handled in the order sent, so rows and pages do not depend on which answered first; a request
     already in flight when a stop rule fires is recorded, never a page over the cap. Back-off to 2, then 1: Firecrawl's
     own 429 (new `ProviderRateLimited`: not charged, not repeated, reading goes on), a Firecrawl 5xx, the site's 429 or
     5xx seen through Firecrawl (which also steps the site limit down), or a call over `SLOW_CALL_S` (30 s, agent: the
     saved audits averaged 4 to 11 s). Recorded in `firecrawl.concurrency` (schema 1.21). The client keeps its guard,
     reservation and records under one lock; only the request runs outside it. The plan fingerprint leaves
     `concurrency` out (it changes neither what is read nor its cost), so plans confirmed before keep theirs.
     (3) *Started when the crawl ends.* `firecrawl.reader.EarlyReading`: `run_audit(reader=...)` offers it the crawl
     right after the crawl; it reads in its own thread beside rendering, the checks and the sitemap check, and
     `reader.apply(..., early=...)` finishes it and runs the content checks as before (owner's postponement of
     2026-10-15, DECISIONS 219 part 1, is lifted). Agent: it starts only for the main page reader of a site Maya's crawler
     read (not blocked, not rate-limited, not stopped, the network answered, not a single page) and only when no
     DataForSEO panel is planned (its ranking pages would come too late; then the old order stays). Blocked and
     rate-limited sites keep the old order. In the web app the approval is marked "attempted" only when it really
     starts. When it runs early, Maya's own steps no longer leave it the reserve: both end by the one time limit.
     `firecrawl.coverage.ran_beside_maya` says so.
     (4) *Sitemap URL check.* Owner: cap 300 in Standard and 100 in Quick (were 1,000 and 200), sampled evenly across
     the sitemap files, 4 at a time, back-off on 429, the report says it is a sample and how many were checked. Owner,
     when asked: one light GET per URL, no HEAD (75 to 100% of the URLs checked on nihan, enpara and adile answered 200,
     and a 200 needs the body for meta robots, the canonical and the empty-page rule, so HEAD first would nearly double
     the requests). Agent: the files take turns, each file's URLs evenly spaced through its own order, a file with fewer
     URLs gives its turns to the others; with one sitemap file the old spread over the site's sections stays (and its
     wording). A 429 widens the gap (×`rate_limit_backoff_factor`) and the site limit steps down; the third 429
     (`rate_limit_stop_after`) stops the check as before (ACC-8's llms.txt links keep "a 429 stops", DECISIONS 52). New
     sentences, English and Turkish: "A sample was checked: {n} of the {m} sitemap URL(s) the crawl did not read, spread
     evenly over {f} sitemap file(s)." in IDX-5's summary, and the share note names the files.
     (5) *Time budget.* The plan's reserve for the reader is pages × max(gap, 8 s ÷ requests at once) (was pages ×
     (gap + 8 s)); 8 s stays only as the figure before anything is measured. While reading, after three calls a request
     is started only if 1.25 × the median call time measured so far (at least 0.5 s, agent) is left, instead of the
     fixed 5 s. Pages the time limit left unread are `firecrawl.coverage.skipped_for_time` with
     `seconds_per_page_measured`, `call_seconds_measured` and `seconds_per_page_assumed` (schema 1.21), and the coverage
     line says "{n} page(s) were not read for lack of time (the page reader measured {s} s a page)" (Turkish beside it).
     (6) *Progress box.* "Maya: {n} of up to {cap} pages read" and "Firecrawl: {n} of up to {cap} pages read ({k} at a
     time)" side by side; after the crawl the estimate is Firecrawl's measured pace × the pages left (never past the
     time limit), else "at most {m} min (the audit's time limit)". Firecrawl's progress events no longer overwrite Maya's
     counters. Not changed: what is read and checked, severities, ranking, the spending limits, the reader's flow for
     blocked sites, batch (it keeps the old order, with the concurrency setting). Tests: `tests/test_v03_speed.py`.

295. **After the live nihan Standard 500 audit of 2026-11-02: Firecrawl's own pace, a timed-out page asked for once more,
     the Mac kept awake, RND-6 on Firecrawl's HTML, and the outcome wording (Owner, 2026-11-02; the details marked
     "agent" are agent defaults).** The run on the stage-2 code: Maya's crawler was blocked after 1 page (429), Firecrawl
     read 388 of 500, 2,687 s active but 13:47-15:51 on the wall clock because the Mac slept, and the reading stopped
     after one Firecrawl `ReadTimeout`.
     (1) *Firecrawl's own pace* (`maya_audit/firecrawl/pace.py`). Owner: Maya's crawler keeps its polite gap (the
     requests come from this computer's address); Firecrawl gets its own pace: up to `Options.concurrency` in flight
     (5), request starts at least `Options.gap_s` apart (a setting: 1 s by default, 0.2 to 30; `MAYA_AUDIT_FIRECRAWL_GAP_S`,
     `--firecrawl-gap`, a plan's `gap_s`), backing off 5 -> 2 -> 1 with a longer gap only on what Firecrawl reports for
     the site: its own 429 or 5xx, the site's 429 or 5xx seen through it, and a call that timed out. This replaces 294
     (1)'s shared limit for the reader and its "slow answer" back-off: the reader no longer takes a slot of Maya's
     `SiteLimiter`, no longer keeps Maya's widened gap, and never steps Maya's limit down. Agent: each step doubles the
     gap, to at most four times the setting; a robots.txt Crawl-delay (as Maya honours it) is a floor and makes it one at
     a time; a hand-made clock gets the same pace (294's "one at a time without the shared limit" is gone); this
     computer's setting may be 0 only through the environment (the test suite sets it, so made-up readers answer at test
     speed). The plan fingerprint leaves `gap_s` out, as it does `concurrency`. `firecrawl.concurrency` records
     `own_pace`, `gap_s`, `gap_final_s`, `crawl_delay_s` and each step's gap. The progress box shows both paces: "Maya:
     N of up to M pages read · one request every {gap} s" and "Firecrawl: N of up to M pages read ({k} at a time,
     starts at least {gap} s apart)" (Turkish beside them); the crawl's progress events carry `delay_s`, the reader's
     `at_once` and `gap_s`.
     (2) *Timeouts.* Owner: a timed-out page is asked for once more after a short wait, then skipped, and the reading
     goes on; it stops only after several failures in a row (5, `Options.stop_after_unreadable`), said in the coverage
     line with counts. A timeout is an `httpx` timeout or dropped answer (`PossiblyBilled.timed_out`) or Firecrawl's own
     HTTP 408 (new `ProviderTimedOut`, not charged). Agent: the wait is `RETRY_WAIT_S` (5 s); the client itself still
     never repeats a request, the reader asks again; **the rule for possibly billed credits:** the first call keeps its
     reservation as possibly billed, the second is a new request with its own reservation, inside the audit's request
     allowance and the confirmed credits, so a page retried after a timeout may cost twice and the guard still stops at
     the confirmed amount. Every timed-out answer, a provider failure and an unreadable document count towards the 5 in a
     row (timeouts also before the first page is read); a page read resets the count. A page whose second try was never
     sent because reading had stopped is skipped too. `firecrawl.coverage.timeouts` = `timed_out`, `retried`,
     `read_on_retry`, `skipped` (schema 1.22); a page row has `retried`. When a page was skipped the coverage line adds
     "Firecrawl: {read} page(s) read, {retried} retried after a timeout, {skipped} skipped" (Turkish: "Firecrawl: {read}
     sayfa okundu, {retried} sayfa zaman aşımından sonra yeniden istendi, {skipped} sayfa atlandı"); a stop keeps
     "reading stopped early (the last 5 pages asked for came back unreadable, ...)".
     (3) *Mac sleep* (`maya_audit/keepawake.py`). Owner: while an audit runs on macOS, `caffeinate -i -w <pid>` keeps the
     Mac from idle sleep (CLI `crawl` and `batch`, and each web job); it is ended when the audit ends, and ends by itself
     if the process dies. Nothing elsewhere; `MAYA_AUDIT_KEEP_AWAKE=off` switches it off (the test suite does). A lid
     closed still sleeps. Agent: the audit records its wall-clock start beside the monotonic one (`started_wall`); the
     difference is the time the computer slept (the monotonic clock stops in sleep on macOS and Linux; on Windows it may
     not, and then nothing is said). `audit_status.timing.slept_s`, and `slept_note` from 2 min up: "The computer slept
     for about {n} min during this audit; the durations count only the time it was awake." in the Markdown duration
     line, the web page and the PDF (Turkish beside it).
     (4) *RND-6 when Maya was blocked.* Owner: when Maya's crawler was blocked (INT-1's rule, or a crawl stopped by a
     rate limit) and Firecrawl read pages, RND-6 (page and homepage HTML size, where the main content starts) is measured
     on the HTML Firecrawl returned (`rawHtml`) for the pages it read and replaces Maya's RND-6, labelled like the
     content checks ("Source: Firecrawl" as the main reader), with `evidence.measured_on` and `pages_measured`. When
     Maya read the site, its own RND-6 stands.
     (5) *Wording.* Owner: when Firecrawl read pages after Maya's crawler was stopped by 429s, the summary no longer
     says "The site could not be read properly": the outcome sentence is "Maya's crawler was blocked (429 on pages); N
     page(s) were read through Firecrawl[; what was left unread]. Genuine AI-crawler access was not measured. Findings
     cover only the pages read." and the cover label "Maya's crawler was blocked (429 on pages); read through Firecrawl:
     N pages" (Turkish "Maya'nın tarayıcısı engellendi (sayfalarda 429); …"). "Could not be read" stays for 0 pages.
     Agent: the outcome code stays DEGRADED and the exit code 1, because Maya's own requests were refused (the CLI exit
     codes keep their meaning); the owner's wording "blocked (429 on pages)" is used for every 429 stop with pages read,
     also where ACC-9 says "rate-limited" (289).
     (6) *RELEASE-SNAPSHOT.* Owner: the expected failure is resolved without a release. Agent:
     `test_snapshot_and_checkpoint_state_the_applications_version` now checks that the snapshot and the checkpoint
     describe the last release (w14d, schema 1.20), that the code's schema is not behind it and that the release's frozen
     schema is kept; on a `team-preview-*` tag (or CI run for one) the two schemas must still be equal.
     Not changed: the spending guard, the request allowance, zero data retention, the proxy rule, the cache rule (A16),
     Maya's own crawl and its pace, INT-4, what Firecrawl reads (every page, 131 and 296). Schema 1.22. Tests:
     `tests/test_v03_live_fixes.py`; updated `test_v03_speed.py`, `test_run_clock.py`, `test_firecrawl.py` (the old rules
     they asserted: the reader on Maya's limit and pace, a timeout stopping the reading), `test_release_metadata.py`.

296. **"Firecrawl only where needed" is not adopted now: Firecrawl keeps reading every page by default (Owner,
     2026-11-02).** The proposal (IMPLEMENTATION-STATUS, "Double reading") would let Firecrawl read a page only where
     Maya could not, or where the page depends on JavaScript. Measured offline on the nihan report (`b3198942…`, 499
     pages read by both), the content checks judge differently on the two copies: thin pages (STR-15) 162 on Maya's copy,
     13 on Firecrawl's; heading jumps (TSEO-1) 214 vs 47; STR-12 (declared language vs the language written, Medium) only
     on Firecrawl's copy (47 pages), none on Maya's; totals 15 S4 + 5 Info vs 1 S3 + 20 S4 + 6 Info. Which copy the
     content checks should judge on a site that reads fine without JavaScript is left open; DECISIONS 131 stands
     unchanged. In the backlog (`docs/BACKLOG.md`).

297. **Page grouping, v0.3 stage 3: template key, page type, internal link score, click depth and importance per page
     (Owner, 2026-11-02, the five values and the seven page types; every rule and number below is an agent default).**
     New `maya_audit/page_groups.py`, run in `final.settle` after `annotate_page_types`, so also again after a page
     reader. It sends no request and is Estimated throughout. **It is not read by any check, severity, confidence,
     finding order or the release gate** (`test_the_grouping_never_changes_a_finding_or_a_severity`).
     (1) *Template key.* The URL pattern, built from every same-site address the audit knew (pages read, links found,
     sitemap): the first folder (and the one after a language folder such as `/en`) stays as it is; below it a folder
     with 2+ different children, or one of the known item folders (`products`, `collections`, `pages`, `policies`,
     `blogs`, `blog`, the STR-3 product/article/category words...), becomes `*`; an id-looking segment is `*`; the query
     is not part of it. So `/products/*`, `/en/products/*`, `/collections/*/products/*`. The layout fingerprint is a
     6-character hash of og:type, the template-level structured-data types (Product, CollectionPage, BreadcrumbList,
     BlogPosting...; not FAQPage, Answer, Person, which follow the text), the main-region kinds, breadcrumbs and the
     form targets with the language folder removed. The key adds ` ~ <layout>` where one pattern holds two layouts of 2+
     pages each, and flat one-segment pages (a WordPress site's `/hikayemiz`, `/iletisim`) that share a folder and a
     layout are one template `/* ~ <layout>` (adile: 31 templates for 36 pages before, 16 after).
     (2) *Page type*: `home`, `category`, `product`, `blog_article`, `policy`, `utility` (search, cart, account,
     checkout, login, wishlist; English and Turkish address words, or SearchResultsPage/CheckoutPage/ProfilePage markup),
     `other`. Order: the homepage and its language versions (a single language folder the homepage's hreflang lists, or
     whose `<html lang>` is that language), utility, policy (a `/policies/`-type folder, a policy word in the last
     segment such as `privacy`, `kvkk`, `sozlesmesi`, `aydinlatma`, or a policy name in the title), a product inside a
     collection (`/collections/<c>/products/<p>`), an article folder (`blogs` included), then STR-3's `page_kind`.
     Whole-site rules after that: og:type=article on half or more of the pages read is a site builder's default (adile),
     so a page typed an article only by it is `other` unless it has the layout of the posts in an article folder; a
     template of 3+ typed pages, 80% one type, lends it to its `other` pages; a page with links of its own (outside menu
     and footer) to 3+ articles or products (by page, or by the pattern of the ones typed) is a `category`; a page whose
     folder holds 2+ pages read and which links to 2+ pages under it (menu links count) is a `category` (a section page:
     enpara's `/odemeler`). Every type carries `page_type_basis`. **Not changed:** STR-3's `page_kind`, which still
     calls Shopify's `/collections/<c>/products/<p>` a listing (on nihan 323 product pages); that affects `page_types`
     on findings and the release gate's content advice, and is for the owner to decide.
     (3) *Internal link score*: PageRank (damping 0.85) over the links between the pages read, redirects followed, a
     link to a duplicate counted for the page its canonical names when that page was read; a link found only in the
     footer weighs 0.25 against 1.0 (reasonable-surfer). Shown 0-100 on a log scale against the site's best-linked page;
     `inlinks` counts the pages read that link to it.
     (4) *Click depth*: fewest link steps from the homepage over the pages read, links as clicked (canonicals not
     followed); the homepage's hreflang alternates count as one step, said per page (`click_depth_basis` "links and the
     homepage's hreflang"): on nihan the language switcher is a form, so without it the whole `/en` half (241 pages)
     would have no depth. Not reached: `null` with "not reached from the homepage through the pages read", never 0. A
     depth is an upper bound: a shorter path through a page not read is not seen (said in `page_grouping.basis`).
     (5) *Importance 0-100*: 50% link score + 25% depth score (0: 100, 1: 85, 2: 70, 3: 55, 4: 40, 5: 25, deeper: 10, not
     reached: 0) + 25% type weight (home 100, category 80, product 70, blog_article 60, other 50, policy 15, utility 0),
     rounded; at most 20 for a page that is not indexable (noindex, canonical elsewhere: `indexable_pages`) and for a
     utility page however well linked (`importance_parts.capped` says which).
     (6) *Report*: `PageFetch.grouping` and `CrawlResult.page_grouping` (method, weights, counts per type and template),
     schema **1.23**: the frozen shape lists every page and crawl field (`maya_audit/schema.py`), so a new field on
     either needs a bump; additions only, 1.x readers keep working. A page not read has `{"not_scored": "redirect" | "not
     a readable HTML page"}`. A 1.22 report gets nothing invented: `tools/page_groups_saved.py <report.json>` works the
     grouping out offline and prints it, without changing the file. Tests: `tests/test_page_groups.py`.
298. **Page importance, v0.3 stage 3b: STR-3 takes a product inside a collection for a product; canonical aliases;
     footer-only policies at most 35; ties broken without the address; a citable-content flag (Owner, 2026-11-03;
     the rules below are agent defaults).**
     (1) *STR-3 `page_kind`* (`checks/structure.py`, `nested_product`): a path with a category word, then later a
     product folder with exactly one segment after it (`/collections/<c>/products/<p>`, also after a language folder,
     `/kategori/<c>/urun/<p>`) is a `product` ("path /collections/…/products/…"), before the listing rule. Not changed:
     `/collections/products/<p>` (no collection between) and anything deeper than the product. This replaces the note in
     297 that the rule was left for the owner; page grouping now uses the same rule. `product_template` is unchanged.
     *Before/after on the saved audits, offline* (page kinds rebuilt from `report.json`, release gate re-run with the new
     `page_types`): **nihan**: 323 pages `category` -> `product`; 1,322 `page_types` labels change on 25 findings (ACC-6
     x5, IDX-4, RND-3, RND-6 x2, RND-7, STR-2, STR-5, STR-14 x4, STR-16, STR-19 x2, TSEO-1 x5, PRF-1). No finding
     appears or goes, no severity or confidence changes: the STR-3 "page kind expects a type" list gains nothing, since
     all 323 pages carry Product markup; STR-6 (articles) and the maybe-product note (pages of no kind) are untouched.
     No RG-7 violation: none of the 25 findings gives content advice limited by page type. Release gate PASS before and
     after. **adile** and **enpara**: no page changes kind; nothing changes.
     (2) *Canonical aliases* (`page_groups.canonical_aliases`): a page read whose canonical names another same-site
     address is an alias of it when that address was read, or when it was not fetched at all and ends in the same item
     (last path segment) as the alias. A canonical that names another item (every page canonical to one address, a CMS
     mistake) or that was fetched and is not a readable page is not followed. Links to an alias count for its canonical;
     the alias's own links move to the canonical (moved, not copied: a duplicate passes on no more than one page). A
     canonical not read is scored like a page: its type is its aliases' type, its click depth that of its nearest alias
     unless its own links reach it sooner (`click_depth_basis` "through its alias <url>"), `inlinks` the pages read that
     link to it or to an alias of it; it is not capped (its indexability is not known: `indexable: null`, `read: false`,
     and a `basis` that says it was scored from its aliases). Those records are in `page_grouping.canonical_pages`; an
     alias carries `canonical` and `canonical_importance`, and stays capped at 20 (not indexable). nihan: 329 aliases,
     283 canonicals scored without being read; products (not capped) 24-52 (Turkish 28-52, median 40; English 24-35,
     median 33), against 8 products read at 28-46 before.
     (3) *Policies linked only from footers*: a `policy` page is capped at 35 unless a page read links to it from the
     menu or from its content. A link record says only whether *any* link to a target is in a menu or a footer, so a
     menu link that is also in the footer counts as a menu link when there are 2+ links; a single link in a `<nav>`
     inside the footer is the footer's; a footer with two links to it is still the footer's (nihan has 171 such
     records). A content link found on half or more of the pages read (4+ pages) is a sitewide block (cookie banner,
     newsletter form consent line) and counts as a footer. nihan: refund, privacy and mesafeli satış 53/41 -> 35.
     adile: `/bulten-kvkk` and `/cerez-politikasi-aydinlatma-metni` 74 -> 35 (a consent line and a cookie banner on
     every page), `/sosyal-medya-aydinlatma-metni` 54 -> 35; `/kvkk` stays 56 (one content link, from `/franchising`,
     through the redirect `/aydinlatma-metni`).
     (4) *Order* (`importance_rank`, 1 = first, over the pages read and the canonicals scored): importance, then body
     links in (pages read linking from their content), then products listed (`tie_break.products_listed`: distinct
     product pages a page links to from its content, read or not, by the pattern of the pages typed product, one per
     product whatever its `?variant=` and whether linked as `/collections/<c>/products/<p>` or `/products/<p>`), then
     the position in the sitemap, then crawl order. Never the address. nihan: the 8 categories at 91 now run kadin-ceket
     (60 products listed), kadin-pantolon (58), kadin-bluz and kadin-tunik (50)...; body links in are 0 for every
     category there (the mega-menu is all `<nav>`).
     (5) *Citable content*: `citable_content: true` on `blog_article` pages, false otherwise
     (`page_grouping.citable_content_pages` counts them). For weighting by business type later; no score changes now.
     (6) *Schema*: no bump. 1.23 has not been pushed, and `grouping` and `page_grouping` are free-form objects in it
     (`dict[str, Any]`): the new keys (`tie_break`, `importance_rank`, `citable_content`, `canonical`,
     `canonical_importance`, `aliases`, `read`, `indexable`, `basis`; summary `aliases`, `canonical_pages_scored`,
     `canonical_pages`, `citable_content_pages`, `policy_footer_cap`, `order`) do not change the frozen shape.
     `page_grouping.method_version` is 2. Tests: `tests/test_page_groups.py` (15).
299. **v0.3 speed follow-up: one clock for every wait, Firecrawl started at Maya's first 429, a large sitemap index read
     in part, the blocked sentence said once, RND-6 on Firecrawl's rendered HTML labelled (Owner, 2026-11-03; the rules
     below are agent defaults).**
     (1) *One clock* (`maya_audit/clock.py`): every wait and deadline of the engine reads `clock.monotonic()` and sleeps
     with `clock.sleep()` (the polite gap and Retry-After in the fetcher, the site limit's gap, Firecrawl's own pace and
     back-off, the timeout retry's wait, scheduled requests, the run clock, the sitemap time share, the archives and
     DataForSEO waits; 21 modules). They ask the clock in use: the system's, or a `FakeClock` a test puts in place with
     `clock.using(...)` (process-wide; tests only). A fake clock moves when something sleeps and returns at once. The
     headless browser (`render.py`) keeps the system clock: it waits for a real browser. `RunClock` and `ReaderPace`
     no longer capture `time.monotonic` at import, which is why a test's patch of the time module did not reach them
     (the coverage benchmark's 589 s). Tests: `test_coverage_phase2.py`'s benchmark fixture and
     `test_w4b_report_length.py`'s fixture run under a fake clock (589 s -> 26 s, 13 s -> 1.4 s); both stay in the fast
     suite, and `test_benchmark_more_of_the_right_pages_are_read_where_it_was_possible` leaves `slow_tests.txt`. Three
     tests that patched `client_module.time.sleep` patch `client_module._clock.sleep`. The CI failure of the status
     commit `54e85a5` (run 41585995041) was a test that looked for "55" anywhere in the counts and met a measured
     0.055 s; it now looks for 55 as a whole number. No status-only commit is pushed from now on (Owner).
     (2) *Firecrawl at Maya's first 429* (`Crawler.on_rate_limited`, `EarlyReading.start_after_rate_limit`): when the
     start page, or one of the first 3 page requests, answers 429, the crawler hands a copy of what it knows (robots.txt,
     the sitemaps, the addresses found, the pages read) to the page reader, which starts at once, before the Retry-After
     wait, reading as for a blocked site (Firecrawl's own copies, its own pace, the sitemap asked through it when Maya
     had none). It runs whether Firecrawl is the main reader or the reader of blocked sites; the web app now creates
     the early reader for both (still not with a paid panel whose ranking pages it would wait for). Beside it, Maya's
     own steps go on as before: the Retry-After wait and the one retry, the rest of the crawl when the retry is
     answered, the access, index, structure, rendering, performance and sitemap checks, the llms.txt links, and the
     robots.txt re-sample (its wait included); the reader's time reserve is no longer kept apart (both end by the one
     time limit). The report says when it started (`firecrawl.coverage.started_at_first_429`: seconds into the crawl,
     the address, the Retry-After asked, the addresses known then). A 429 later in the crawl does not start it early.
     (3) *A large sitemap index read in part* (`sitemap.discover_sitemap_urls(enough=...)`): every file robots.txt
     names (and the guessed /sitemap.xml) is read; the files of an index are read in turn by family (folder kept,
     numbers left out: `/sitemap_products_#`, `/sitemap_pages_#`, `/en/sitemap_products_#` are three), within a family
     first, last, middle, then the quarters (not only a catalog's first files), and reading
     stops once the addresses known reach the page cap plus the sitemap check's sample (`max_pages` +
     `sitemap_check_max`) and every family has had one file read. The note "sitemap index read in part: N addresses
     from F of T sitemap files ...; K file(s) were not read, so the discovered count is partial." goes into
     `crawl.sitemap_notes`; the Markdown says "N URLs discovered (partial: a large sitemap index was read in part)" and
     the web summary has `discovered_partial`. nihan (2 Nov Quick 50): 11 of 25 files, 2,419 addresses, every kind in
     both languages (26 sitemap requests -> 12, about 16 s less).
     (4) *The blocked sentence said once*: the card's and the PDF's outcome label already says "Maya's crawler was
     blocked (429 on pages); read through Firecrawl: N pages"; the reason under it (`summary.outcome_shown`) now leaves
     out its first two clauses, which said the same (English and Turkish). The status summary no longer repeats
     "N page(s) read through Firecrawl" after "We read N page(s) through Firecrawl." (new reports).
     (5) *RND-6 on Firecrawl's HTML*: Firecrawl's `rawHtml` is the page as its browser built it (after JavaScript,
     with `blockAds` on and base64 images removed), not the server's raw HTML. Measured on nihan's Standard 500
     (`b3198942`): on the 499 pages both read, Firecrawl's copy was a median 36% larger than Maya's raw copy (from 8%
     smaller to 59% larger). RND-6 measured on it (DECISIONS 295 (4)) now says so: each title ends "(rendered HTML via
     Firecrawl, not comparable with raw size)" (Turkish "(Firecrawl ile işlenmiş HTML; ham boyutla
     karşılaştırılamaz)"), each finding carries the note and `evidence.html_measured: "rendered (Firecrawl)"`, and it
     is never set beside Maya's raw sizes. Thresholds unchanged.
     (6) *nihan Quick 50, estimated* from the 2 Nov run (`50473193`, 349.5 s for every step, ~6 min wall): preflight
     ~10 s; sitemaps 30 s -> ~14 s; the homepage's 429 at ~25 s now starts Firecrawl, which read its 50 pages in 108 s
     (ending ~135 s); Maya's own steps then end on the robots.txt re-sample, due 240 s after the first robots.txt
     request (~250 s), where they ended before too. Estimated whole audit **about 4.2 min** (was 5.8-6.0), now set by
     the robots.txt re-sample wait, not Firecrawl. Not measured live.
     Tests: `tests/test_v03_speed_followup.py` (11).
300. **v0.3 stage 6: one client selection — root-cause cards, a priority score, "Teyit edin", Maya's own limits as
     coverage — a 10-page/15-card client report with an XLSX appendix, and a gate on both (Owner, 2026-11-03: the
     items, weights, page and card budget; the rules below that the owner did not name are agent defaults).**
     New `maya_audit/client_selection.py`, read by the web app's concise PDF and the `maya-audit-pro` report. It never
     changes a finding, a severity or a confidence in the report.
     (1) *Root cause.* Findings of one rule (`dedup_key`, else `rule_id`; the pro report's two empty-page rules are one
     family) are one card whatever template or language copy they were found on; findings that may be intentional,
     that need confirming first, that carry another re-test state (RG-4) or are Info stay apart. A card shows one
     example per language (`/a` and `/en/a`), the most important page of that language, never a utility page (search,
     cart) while another page is affected. nihan: the 5 TSEO-1 shared heading jumps, 4 STR-14 shared links, 3 STR-19
     blocks are one group each.
     (2) *Priority* = severity weight (Blocker 100, High 40, Medium 15, Low 5, Info 0) × confidence (measured =
     engine `verified` 1.0, estimated 0.6, inferred 0.5, unverified 0.4) × reach × business relevance (1.0 until
     stage 4's profiles). "Unverified" is a finding from a rule not yet validated on real sites (an `LG-` item),
     whatever its confidence. *Reach* (agent default): the summed page importance (DECISIONS 297/298; a page not scored
     counts 10) of the affected addresses ÷ 100, at most 5; a finding with no address reaches the homepage (1.0). A
     report saved before page grouping gets it from `page_groups.annotate` on its page records, offline. Effort is shown
     on a card, never scored. Ties: higher severity, then the report's own order. The score never changes a severity,
     and every Blocker/High group is a card however it scores (preamble 4).
     (3) *Client report budget:* at most 10 pages and 15 cards: summary, coverage, top cards, key pages scorecard (10
     most important pages read: type, importance, the cards that concern each, how many to confirm), action plan with
     quick wins (cards of small effort), appendix pointer with counts. Web concise PDF (`concise_report.render`,
     `<meta name="maya-concise" content="10">`, `to_pdf` max 10 pages) and the pro report (summary pages, ≤15 cards in
     priority order, a new last page "Kapsam ve ek"; Not cards only while there is room).
     (4) *Appendix:* `maya_audit/client_appendix.py` writes one XLSX (stdlib writer `maya_audit/xlsx.py`; no new
     dependency): every finding with its group, placement, card, score and confirm reason; every affected address; key
     pages; coverage; method. Turkish or English headers. Web: `GET /audits/{id}/downloads/xlsx` (named
     `…-appendix.xlsx`, listed among the companions); pro: `render.py` writes `<name>-ek.xlsx` / `-appendix.xlsx` in
     place of the CSV address list.
     (5) *"Teyit edin":* a group whose confidence weight is 0.5 or less, one that may be intentional, one seen only in
     Firecrawl's copy, and 403/429 to a request with Googlebot's user agent (ACC-4 `refused` pairs) goes to a
     one-line-each list, not to the cards, unless the owner's manual check confirmed it (`build_data.py --confirm
     <rule or finding id>`; `--reject` keeps it out of the PDF, "rejected" in the appendix). An Info group stays a
     note (nothing to act on), except the spoofed Googlebot and Firecrawl-only ones.
     (6) *Gate:* `release_gate.check_client_output`: RG-15 a client PDF over 10 pages, RG-16 over 15 cards, RG-17 an
     appendix that leaves out any finding of the report: all hard (BLOCKED). `check_cards` runs RG-16/17 on a pro
     data.json; `render.py` runs RG-15/16 on the printed PDF and RG-17 on the written XLSX; the web app refuses a
     concise PDF over 10 pages (`pdf_page_limit`). The other client report (`maya-audit-rapor`, `client_reports`)
     keeps its 50-page limit: not in this request.
     (7) *Nihan text fixes:* no "kontrol canlı sitelerde henüz doğrulanmadı" on a client card (those findings are in
     "Teyit edin"); IDX-5 "same lastmod" on Shopify takes the catalogue's `steps_by_platform.Shopify` (Shopify writes
     the sitemap; lastmod is the product's last update; find the apps that update everything at once), checked against
     `platform.name` (RG-11); new ACC-3 rule `acc3.utility_indexable` (Low, verified): the site's own search or cart
     page (last path segment `search`, `arama`, `ara`, `cart`, `sepet`, `sepetim`, `basket`) answers 200 with no
     noindex and no canonical elsewhere, fix: add noindex (Shopify: theme `<head>` for those templates); excluded from
     the generic noindex judgment; no empty evidence columns (evidence samples and the appendix drop a column empty in
     every row); every number labelled (scope ratios, "later" counts, saved-copy counts carry their unit).
     (8) *Maya's own limits* — page cap, time budget, parts not assessed (missing connections, logs), how the pages
     were read (`acc9.reader*` findings) — are in the coverage section, never a client problem card.
     (9) *Firecrawl-only findings* (`maya_audit/double_reading.py`): when Firecrawl read the content of a site Maya's
     crawler also read, the content checks run again on Maya's own copies (no request) only to compare; a finding with
     no counterpart (same rule, same title without numbers and example lists) gets `evidence.reading.seen_in =
     "firecrawl_only"`, confidence verified → estimated, a note; which copy the checks judge does not change. In the
     engine (`firecrawl.reader.read_blocked_site`, `firecrawl.coverage.firecrawl_only_findings`) and for saved reports
     in `reassess_rules` (with the ACC-3 rule above). STR-12 on nihan: marked Firecrawl-only and listed under "Teyit
     edin"; the owner's manual check of the `/en` pages was not given in the request (placeholder left), so it stays
     there until `--confirm str12.language` or `--reject`.
     Schema: no bump (new keys inside `evidence` and `firecrawl.coverage`, free-form; a new rule id). Tests:
     `tests/test_v03_client_report.py`.
301. **Report-quality rules for every audit: a review file for manual checks, language regions, banded ranking with
     logarithmic reach, a root-cause merge table, one source for counts, the XLSX button (Owner, 2026-11-03: the items
     and the nihan STR-12 confirmation; the rules below the owner did not name are agent defaults).**
     (1) *Review file* (`maya_audit/manual_review.py`): `review.json` beside the audit's report.json (web artifacts
     folder; a CLI report's `<report>.review.json`): per finding id `confirmed`/`rejected`, who, date, what was seen,
     an optional note shown on the card; a later entry replaces an earlier one (kept under `replaced`); the report is
     never changed, so its digest and gate are the report's. Confirmed = "measured, confirmed by manual check (who,
     date)", competes for the cards; rejected = out of the PDF, "rejected" in the appendix. Written by the web app's
     "Teyit edin" panel (`GET/POST /audits/{id}/review`, buttons on the results page) and by `build_data.py --confirm|
     --reject <finding or rule id> --by --seen [--note]` (`--review` names another file). nihan: STR-12-c792bc34
     confirmed by the owner (the `/en` pages are mostly Turkish in a normal browser; note: "Üst Giyim" translated as
     "Outerwear").
     (2) *Language regions* (`maya_audit/language_regions.py`, `evidence.regions` on `str12.language`,
     `str12.headings`, `str9.lang_mismatch`; set when a report is written and by the offline reassessment): menu,
     breadcrumbs, product/item titles, buttons/labels, banners, footer, body text. A string is in the other language
     when it has that language's letters or a stopword of only that language, or (menu, breadcrumbs, titles, buttons;
     4+ letters) when it is identical on the page's other-language version (hreflang); the brand and language-switcher
     names are never counted. A region is "in the other language" at a quarter of its strings, or 2 per page read.
     Advice from the regions found, in `rule_actions.json` (`region_steps`), with the platform's tool first
     (`platform_steps_language`: Shopify Translate & Adapt, WordPress WPML/Polylang). Filter tabs are not a region of
     their own: Maya's raw copy keeps no filter markup (they count as buttons when they are buttons). nihan `/en`: menu
     39%, item titles 70%, body 98% in Turkish.
     (3) *Ranking:* cards by severity band first, then priority within the band (a Medium is never below a Low). Reach
     = 1 + ln(1 + summed importance / 100), at most 10 (no cap is reached in practice); scores kept to 3 decimals,
     printed with one ("93,4" in Turkish). A finding with no address reaches the homepage's importance.
     (4) *Merge table* (`client_selection.MERGE_GROUPS`, `merge_table()`): rule ids -> root cause -> one title and one
     fix (tr/en); grouped findings are one card (still split by confirm-first, intent, re-test state, Info), examples
     the worst pages where the evidence measures them (`worst_by`). Groups: `html_weight` (rnd6.home_large, .large, .late
     and their `_fc` forms), `empty_pages` (idx1.empty, idx1.empty.bot, judgment.empty.repeated/.single),
     `heading_levels` (tseo1.heading_jumps, shared.heading_jump, shared.heading_jump_varied), `links_without_text`
     (str14.no_text, shared.link_no_text, shared.block_links_no_text, shared.link_no_text_pattern),
     `links_without_address` (str19.no_target, str19.lead_nowhere, shared.link_no_address, shared.links_no_address),
     `language_mismatch` (str12.language, str12.headings, str9.lang_mismatch), `sitemap_lastmod` (idx5.stamped,
     .identical, .future), `template_meta` (str1.shared, str16.shared). Every finding id stays in the appendix
     (column "Root-cause group").
     (5) *One source for counts:* `client_selection.select(...)["counts"]` (findings, problems, by severity, cards,
     confirm, notes, appendix-only, addresses) feeds the web PDF tiles and lines, the pro KPI and coverage box, and the
     XLSX; `tests/test_v03_client_report.py::test_web_pdf_pro_pdf_xlsx_and_markdown_print_the_same_counts` checks them
     and the Markdown headline against each other on two demo audits.
     (6) *maya-audit-rapor* (the third client report: `maya_audit/client_reporting`, `maya_audit_web/client_reports.py`,
     the web "client report" workspace): not changed; the agent's recommendation to the owner is to retire it (see
     IMPLEMENTATION-STATUS). Owner's decision pending.
     (7) *Web:* the results page lists the XLSX appendix among the downloads ("pdf", "xlsx", ...).
     Schema: no bump (`evidence.regions` is inside free-form evidence; the review file is not part of the report).
     Tests: `tests/test_v03_client_report.py` 23 -> 31.
302. **maya-audit-rapor deprecated now, deleted in release w15 (Owner, 2026-11-03, on the agent's recommendation in
     DECISIONS 301 (6)).** The third client report (`maya_audit/client_reporting/`, `maya_audit_web/client_reports.py`,
     the web "Client report" workspace, the `maya-audit-rapor` skill) has its own grouping, score and wording and does not
     follow the 10-page/15-card rule; the concise PDF and `maya-audit-pro` replace it, and the review file (301 (1))
     replaces its reviewer sign-off. Now: the web results page no longer shows its button (`static/app.js`); its API
     routes, `showClientReport` and its tests stay until w15 so nothing breaks in between; the skill's `SKILL.md` says
     it is deprecated and points to `maya-audit-pro`; `AGENTS.md`, `maya-judgment-validator` and `maya-audit-pro` name
     `maya-audit-pro` as the client report. In w15 (roadmap stage 9): delete the package, the web module and routes,
     the JS workspace, the skill folder and their tests (about 2,170 lines and 14 test files), in one commit with a
     note in this file.
303. **Two fixes after the owner's browser test of the restarted web app (Owner, 2026-11-03).** (1) "nullnull" under the
     "Confirm first" list: `showReview` passed its two optional parts (the "checked by hand" heading and list, absent
     until a finding is checked) to the DOM's `replaceChildren`, which prints `null` as text; it now uses `fill()`, which
     drops null, undefined and false. The same test found a second one: the plan card's market notice
     (`card.append(... ? el(...) : null, ...)`), now `add()`. `test_no_dom_call_in_the_web_page_can_print_null` scans
     `static/app.js` so a raw `replaceChildren`/`append`/`prepend` never takes a possible null again. Every audit had the
     first one (no audit had a manual check yet). (2) Empty "Key pages" for older audits: a saved report without page
     grouping already gets it computed on the fly from its page records (`client_selection.grouping`, as
     `tools/page_groups_saved.py`); what stays empty is an audit whose pages were read only through Firecrawl after Maya's
     crawler was blocked (2 Nov nihan Quick 50: one page record, no content), because the saved copies keep no links and
     importance is computed from links. The XLSX sheet, the web PDF and the pro report then say so in one line
     (`key_pages_reason`: `reader_only` or `no_pages`). New audits of a blocked site have the same gap; grouping
     Firecrawl's pages at run time is in `docs/BACKLOG.md`.
304. **The checklist's quick checks, Product fields in report.json, page importance for pages read through Firecrawl
     (Owner, 2026-11-03: the request and its items, from `docs/BACKLOG.md` and `reviews/checklist/mapping.xlsx`; the
     thresholds, severities, check placement and wording are agent defaults, LG-102).** Global rules for every audit;
     nihan, adile and enpara were only test cases.
     (1) *Firecrawl's pages get importance.* When Maya's crawler was blocked (or rate-limited) and Firecrawl read the
     pages, `page_groups.annotate` runs on Firecrawl's pages while their links are in memory
     (`firecrawl.reader.reader_page_grouping`) and the result is kept as `crawl.reader_page_grouping` (the summary keys of
     `page_grouping`, `reader`, and `pages` {url: grouping}). `client_selection.grouping` reads it first, so the key
     pages, reach and priority work for a blocked site; Maya's own scored pages fill any gap. A report saved before
     still says why it has none (DECISIONS 303).
     (2) *Ten rules* in `maya_audit/checks/quick_rules.py`, each an ordinary finding in its check, run by the access,
     index and structure runners before `settle_all` (so a page reader's content view gets the content ones), on page
     types, aliases and products listed from the page grouping; no request:
     SEO-061 `idx6.alias_links` (IDX-6, Low, verified): links to a page read whose canonical names another address (a
     canonical differing only in percent-encoding case, `%CC` / `%cc`, is the page itself);
     SEO-099 `str15.empty_collections` (STR-15, Low, estimated): an indexable category page listing 2 products or fewer
     on a site with 3+ product pages; left out: a hub with 2+ subcategories in its content, the index of all collections
     (`/collections`), a blog's list, a page with a query;
     decomposed characters `tseo1.url_decomposed` (TSEO-1, Low, verified): a known same-site address whose decoded path
     holds a combining character; the fix given per address is NFC with "i + U+0307" written "i";
     SEO-031 `acc3.robots_noindex` (ACC-3, Low, verified): a page Maya read with noindex (all, Googlebot or Bingbot)
     that robots.txt disallows for Googlebot or Bingbot;
     SEO-046 `idx7.pagination_unlinked` (IDX-7, Low): a page's `<link rel="next">` (new in the analysis, verified), or
     a page-2 address of the same list found elsewhere (estimated), is not the target of any link on it;
     SEO-093 `idx7.product_no_category` (IDX-7, Low, estimated): a product (one per canonical) with no breadcrumb trail
     of 2+ links and no content link (outside menu and footer) to a category page, on a site with 3+ category pages;
     SEO-036 `idx5.no_image_sitemap` / `idx5.no_video_sitemap` (IDX-5, Low, verified): no `<image:image>` /
     `<video:video>` in any sitemap file read, on a site with 200+ different content images / 10+ pages with a video
     (`<video>` or a YouTube/Vimeo/Wistia frame); the sitemap records count them now;
     SEO-067 `tseo1.url_slug_unclear` (TSEO-1, Low, verified): an indexable page's last segment over 100 characters,
     with a space or symbol, or only an id (digits, hex, a uuid, or digits with no run of 3 letters);
     SEO-078 `str3.article_no_author` (STR-3, Low, estimated): an indexable article page with no byline class/id
     (author, byline, yazar), rel/itemprop author, meta author, JSON-LD author or Person markup;
     SEO-097 `str3.product_no_identifier` (STR-3, Low, verified): a product page whose Product markup (the node, its
     offers or variants) has no gtin, gtin8/12/13/14, isbn or mpn; brand kept in the evidence.
     The threshold rules (SEO-099, -046, -093, -036, -067, -078) carry LG-102 ("Unverified check", so they go to
     "Teyit edin"); every new finding has its English/Turkish title, fix, expected result, "why it matters" note and
     action-plan steps.
     (3) *Product fields kept* (`analysis.structured_data.products`, at most 5 nodes a page): type, gtin {key: value},
     mpn, sku, brand, offers (price, priceCurrency, availability, any identifier; at most 5), has_variant,
     variant_identifiers, in_list. Also kept: `analysis.pagination_links`, `analysis.author_signals`.
     (4) *Schema 1.24*: `crawl.reader_page_grouping` and the sitemap document's `image_entries`, `video_entries` are new
     fields of covered records (why the version moves: a 1.23 reader would take their absence as "no grouping" or "no
     image sitemap"); the analysis keys are documented, not covered.
     (5) *Offline* (`reassess_rules._decisions_304`, `tools/reassess_saved.py`): the same functions on the saved page
     records; the Product fields and a JSON-LD author are read from the audit's saved evidence copies
     (`evidence/*.json`, `json_ld_blocks`). Not assessed offline, and said so: SEO-031 (no robots.txt text in a report),
     SEO-036 (no media counts before 1.24). Applying it twice adds nothing twice.
     (6) Found on the way, not changed: `page_groups.canonical_aliases` still takes a canonical that differs only in
     percent-encoding case for another address (nihan: `/pages/etbi%CC%87s`), which splits that page's links between
     two nodes in the importance graph; the new SEO-061 rule compares decoded addresses. Backlog.
     Schema: 1.24. Tests: `tests/test_quick_checks.py` (17).
305. **Answers and report fixes after DECISIONS 304 (Owner, 2026-11-03: items 1-4; how each is done is an agent
     default).** Global rules; nihan was the test case.
     (1) *Percent-escape case* (owner's backlog decision): `%cc` and `%CC` are the same octets (RFC 3986 6.2.2.1), so
     `urls.normalize_url` writes every escape of the path and query in upper case (`urls.upper_escapes`), and the
     canonical comparisons (`index_data.canonical_elsewhere`, `page_groups.canonical_aliases`) compare both sides that
     way, so a saved report written before still counts `/pages/etbi%cc%87s` and `/pages/etbi%CC%87s` as one page. Page
     identity, grouping and importance follow. nihan: the ETBİS pages are no longer an alias of an unread "other" page.
     (2) *Reach from pages read* (replaces DECISIONS 300 (2)'s "a page not scored counts 10"): `client_selection._reach`
     sums the importance of the affected pages that were read (scored, not a canonical scored only from its aliases);
     an address not read adds nothing and is counted apart (`addresses_not_read`; XLSX columns "Okunan sayfa (erişim)",
     "Okunmayan adres"; the pro card says "Okunmayan N adres ekte; öncelik puanına katılmadı."). A finding with no
     address, or only files (a sitemap, robots.txt), keeps the homepage's reach; one whose page addresses were all left
     unread gets the minimum (1.0). nihan: the decomposed-address card (1,689 addresses, 68 read) goes from 30.9 (3rd)
     to 18.8 (6th); the alias-links card is 3rd. Side effect: findings on sitemap files now reach the homepage instead of
     10 per file (adile IDX-5 failed files 16.4 -> 25.4; order unchanged on adile and enpara).
     (3a) *One count of the parts not assessed:* `client_selection.not_assessed_parts` (one per (part, reason), the
     parts that restate the unread addresses left out, the answer-engine panel included) feeds the coverage lines and
     `counts["not_assessed"]`; the pro report's KPI box, provenance line and last page, the web concise PDF and the XLSX
     Coverage sheet all print it. nihan: 25 on pages 1, 3 and 7 (v2 said 25, 25 and 23).
     (3b) *Merged cards everywhere:* the pro report's priorities, findings table and action plan use a merged card's
     title (`MERGE_GROUPS`) and its whole scope (every member's addresses), not the lead finding's (nihan v2: "1 sayfa"
     on page 1 and the homepage's 885 KB title over 494 pages on page 2).
     (3c) *Evidence tables:* the sample prints the engine's structured evidence (address, element, measured, limit:
     "/ · 885 KB · 500 KB") and drops any column empty in every row. Also: the alias-links scope is counted in pages
     ("141 sayfa"), and the evidence note points to the XLSX appendix.
     (4) nihan pro report v3 rebuilt offline with the maya-audit-pro skill (Turkish, STR-12 confirmation kept):
     `reviews/2026-11-03/nihan-v3/` (git-ignored).
     Schema: no bump (client-selection fields and appendix columns are not report.json). Tests:
     `tests/test_v03_report_fixes.py` (7), `test_web_pdf_pro_pdf_xlsx_and_markdown_print_the_same_counts` extended to the
     printed pro report.
306. **Client-report polish (Owner, 2026-11-03: items 1-5; wording and the rule list are agent defaults).** Global, every
     audit; nihan was the test case.
     (1) *Effort of an address rename:* a fix that renames addresses and needs a redirect for each old one
     (`recommendation_catalog.RENAMES_ADDRESSES`: `tseo1.url_decomposed`, `tseo1.url_slug_unclear`) is at least Medium
     (`note()` raises a Small entry) and is never a quick win (pro report and web concise PDF). The card's first step
     explains Shopify's handle in plain Turkish: "Ürün/sayfa adresindeki kısa adı (handle) ...".
     (2) *"Teyit edin" in client reports* (pro report, web concise PDF) says why in client words, no vendor name:
     "Doğrulama bekliyor: kontrol yeni" (an unverified check), "... farklı okuma yolunda görüldü" (seen only in the page
     reader's copy), "... tahmini ölçüm", "... bilinçli bir tercih olabilir", "... arama motoru kimliğiyle yapılan istek
     reddedildi; Search Console'da kontrol edin". The technical reason stays in the XLSX ("Teyit nedeni"). The key-pages
     note for a blocked site no longer names Firecrawl either.
     (3) *Findings table:* each row says what is wrong. A merged card's row takes its group's `finding` name
     (`MERGE_GROUPS`, e.g. "Sayfa HTML'i ağır: satır içi veri, betik ve stil"); the cards and the action plan keep the
     action titles.
     (4) *Turkish XLSX:* coverage explanations go through the engine's wording (`label`, `line`, passed by the web app and
     the pro render), page types are Turkish (ana sayfa, kategori, ürün, blog yazısı, politika sayfası, yardımcı sayfa,
     diğer), and the manual check's result word too ("teyit edildi"); who checked and what they saw stay as written.
     (5) *"Kayıtlı kopyadan okunan sayfa"* is not printed when it is 0.
     nihan pro v4: `reviews/2026-11-03/nihan-v4/` (git-ignored). Schema: no bump. Tests: `tests/test_v03_report_fixes.py`
     7 -> 11.
307. **One place for reports: the web app builds the team report (the maya-audit-pro design) and its XLSX appendix by
     itself, from one shared template and one text library (Owner, 2026-11-04: items 1-5; the library's wording, the
     page-1 templates, the lock and the plain reasons are agent defaults, seeded from the approved nihan v4 report).**
     Global for every audit; nihan was the test case.
     (1) *What the model wrote before* (investigation, nihan v4 rebuilt from its own source): `build_data.py` drafted 69
     text slots; the model wrote 19 (`assessment.headline/text`, `priorities[0-2].title/text`, `next_action.lead/text/
     caveat`, `followup.text`, the steps of the content-language and page-load Note cards, 5 `confirm[].title`) and
     shortened 2 finding titles longer than their box; the other 48 came from the catalogue and the engine's wording.
     Numbers, severities, scores, order and placement were deterministic already (`client_selection`). Of 299 rule ids,
     90 had catalogue text; none had a verification or summary phrase of its own.
     (2) *One template.* The skill's scripts, labels, owner/effort table, logo and font moved (git mv) into
     `maya_audit_web/team_report/` (`build_data.py`, `validate_data.py`, `render.py`, `refs/`, `assets/`, `inter_b64.py`);
     the skill's `scripts/*.py` are thin entries that find the engine and run those modules with the same arguments
     (`import build_data` gets the module itself, so the skill's tests are unchanged). New callable steps:
     `build_data.build_from_files`, `validate_data.check` (structured errors), `render.produce`, `render.appendix_bytes`
     (the web app's "Ek (XLSX)" and the skill's `-ek.xlsx` are the same function), and `service.build`, the whole path
     for the web app. A report that is itself an offline reanalysis (`generation.analysis`) says "no new crawl" without
     `--reanalysis`.
     (3) *Text library* (`maya_audit_web/team_report/texts/tr.json`, `en.json`, read by `texts.py`): for every rule id
     (299) a title, finding, explanation, why it matters, 2-4 steps (`steps_by_platform` where the fix differs, e.g.
     Shopify), verify line and summary; for every merge group the same fields except title and finding (those stay in
     `MERGE_GROUPS`); a step and summary for every Note-card topic (with a platform line, e.g. Shopify's managed CDN
     cache); page-1 templates (verdict by severity band of the problem cards, assessment, priority text with the manual
     check or estimate, next step, caveat, month summary, confirm title); generic last-resort words; plain reasons for a
     blocked report. No digits in library text (numbers come from report.json, the validator refuses others). The
     catalogue (`rule_actions.json`) still wins for title, steps and platform steps; a catalogue step with a condition
     (`step_when`) is never printed by the library, so the release gate keeps checking it (RG-11). Wording written by
     four agents from each rule's engine title, "why", catalogue entry and the v4 card text, then checked by script.
     (4) *Filling:* `Builder.slot` takes the engine's or catalogue's words when they fit the box, else the library's
     (`fallback`); `finish` gives any slot still marked the generic words: no report has an empty text field.
     (5) *Lock:* `build_from_files` writes `_locked`, a digest of every visible field outside `_slots` (severities,
     counts, scores, card order, addresses, KPIs). The skill may let Claude polish the text; `validate_data` refuses any
     other change ("Önem, sayı ya da sıra değişmiş").
     (6) *Web app:* `GET /audits/{id}/downloads/team?lang=tr|en` (Turkish when no language is given) runs build,
     validator, release gate, render and the PDF checks on every request, so a "Teyit edin" Confirm/Reject counts on the
     next download; blocked -> HTTP 422 `team_report_blocked` with `reasons` in plain words (the gate rule's or the
     validator's kind, in the report's language) and the technical `details`. The results page has a "Ekip raporu"
     section: TR/EN switch (TR first), "Ekip raporu (PDF)", "Ek (XLSX)", the reasons shown under the buttons. The
     concise PDF and the other downloads are unchanged.
     (7) *Parity:* `tools/team_report_parity.py` serves a saved audit's copy through an isolated web app (an `analysis-*`
     entry), downloads both files over HTTP, runs the skill's three scripts on the same copy, renders every page to PNG
     and compares them; with `--approved` it lists the text fields that differ from an approved data.json.
     nihan (v4 source, review file with the owner's STR-12 confirmation, Turkish): web 7 pages, skill 7 pages, every page
     the same pixels, XLSX the same in every cell; cards, order and severities the same as v4; 17 of 69 text fields
     worded differently from the model's v4 (listed in `reviews/2026-11-04/nihan-web/parity.md`, git-ignored): the
     library is generic where the model named the site ("dil sürümleri" for "İngilizce sayfalar", no "Translate &
     Adapt" in the priority line, confirm titles without the link count).
     Schema: no bump (report.json unchanged). Package data: `maya_audit_web.team_report` refs, assets, texts.
     Tests: `tests/test_team_report.py` (17; one slow: web vs skill PNGs and a manual check rebuilding the report).
308. **Web team report fixes: current engine first, one language per click, the short summary named apart, one review
     file (Owner, 2026-11-04: items 1-4; the derived-copy folder and key, the build-then-link flow, the file names and
     the labels are agent defaults).** Global for every audit; nihan (b3198942) was the test case.
     (1) *Current engine first* (`maya_audit_web/team_report/current.py`): `build_data.build_from_files`, the one build
     step of the web app's team report and of the maya-audit-pro skill, first re-evaluates a saved audit with the
     current engine: the steps of `tools/reassess_saved.py` (`reassess_rules.apply`: reassessment rules, the checks that
     run on saved data, the Product fields from the saved JSON-LD evidence; sockets refused), then the selection-time
     rules (reach from pages read, percent-escape case, DECISIONS 305) apply to that copy. The source report.json and
     affected-urls.json are never written: the copy is `<audit>/current-engine/` beside `artifacts/` (or
     `<report>.current-engine/` elsewhere) with `meta.json`, made again only when the source files (size, modified
     time) or the engine (a hash of the `maya_audit` package's files) change. Used as written: a report of the current
     schema with no offline record, or an offline copy this engine made. The copy's `generation.analysis.engine`
     (version, schema, commit, fingerprint, time) gives one line, in the PDF's provenance box ("Değerlendirme:") and
     under the web buttons: "Güncel motorla yeniden değerlendirildi (Maya Audit 0.2.8 · şema 1.24 · <commit>, <date>)".
     "Teyit edin" (GET/POST review), the XLSX appendix (and its gate) and the skill's `--confirm` read the same copy, so
     a finding only the current engine finds can be confirmed. `--no-reassess` builds the file as it is. A report the
     current engine cannot re-read (a hand-made fragment, a record missing a field the rules need) is used as saved and
     says so: the build notes give the error, the provenance line reads "Güncel motorla yeniden değerlendirilemedi;
     rapor kaydedildiği hâliyle kullanıldı.", and the web app shows it under the buttons.
     (2) *TR/EN switch.* Found: the server built the asked language (checked through the routes and in Chromium, with a
     Turkish and an English interface); what failed was the download. The page fetched the PDF and saved it by a
     script click 20-50 s later, which browsers treat as an automatic "multiple downloads" attempt and block after the
     first file, so the reader kept the first (Turkish) file; the XLSX had one name for both languages
     (`-appendix.xlsx`), so the second copy was saved as "(1)" beside the first; and the "İndir" section's PDF and
     XLSX, which follow the audit's language, sat under the switch with a look-alike "Ek (XLSX)". Now: GET
     `/audits/{id}/team-report?lang=` builds that language and returns two ordinary links (the PDF from a short-lived
     build token, kept only for that audit and language; the XLSX route), named with the language:
     `…-ekip-raporu-tr.pdf`, `…-team-report-en.pdf`, `…-ek-tr.xlsx`, `…-appendix-en.xlsx`; the buttons carry the chosen
     language ("Ekip raporu (PDF) · EN"); switching clears a built link; every build starts again; responses carry
     `X-Maya-Language` and `Cache-Control: no-store`. The owner's Downloads folder had one team PDF (Turkish, from the
     unreassessed report: 28 issues, 5 medium) and no English one.
     (3) *Downloads section:* "Diğer indirmeler" / "Other downloads", below the team report; the concise PDF is "Kısa
     teknik özet (PDF, <language>)" with a note that it is not the team report; its XLSX button is gone (the appendix is
     in the team report's section, in the chosen language).
     (4) *Where confirmations live:* one file per audit, `artifacts/review.json`, written by the web app's "Teyit edin"
     and by the skill's `--confirm` when the skill is pointed at that audit's report; the current-engine copy has none.
     For nihan the owner's STR-12 confirmation is only in the skill-path copies (`reviews/2026-11-03/nihan-v4/source/
     review.json`, also v3 and rebuild-301); the web audit `b3198942…/artifacts` has no review file, so the web app's
     team report keeps STR-12 under "Teyit edin" until it is confirmed there (or that file is copied in by the owner).
     nihan rebuilt through the web routes from a copy of the original audit (current engine, with and without the v4
     review file): `reviews/2026-11-04/nihan-web-v2/` (git-ignored).
     Schema: no bump (report.json unchanged; the copy is a derived file). Tests: `tests/test_team_report.py` (+5: the
     current-engine copy, one review file read through the copy, the downloads labels, each language through the real
     routes with no template text of the other, a report that cannot be re-read used as saved and said so);
     `test_v03_client_report`, `test_w4b_report_length`, `test_next_accuracy` follow the new names and buttons.
309. **Team report fixes for every audit: web confirmations, platform steps, saved-data platform, key pages, Note
     slots, read-but-unscored reach, rendered HTML, low coverage, the history list, words (Owner, 2026-11-05: items
     0-9; the signals, thresholds, neutral weight, labels and layout are agent defaults).** Test cases: nihan b3198942
     (500 pages, Shopify), nihan 50473193 (Firecrawl-only), nihan efb50ee4 (1 page), moodisthastanesi c581ff0a (hospital,
     WordPress, multilingual).
     (0) *Web confirmations.* Where: one file per audit, `<audit>/artifacts/review.json`, written by POST
     `/audits/{id}/review` and read by every build (`build_from_files(review=…)`, the appendix, "Teyit edin"). Found on
     b3198942: the owner's file holds six saves of ACC-4-17ea40ab (the Googlebot 429 row, the last of 11), every one with
     the STR-12 note, and none of STR-12-c792bc34; the build read that file correctly, so STR-12 stayed under "Teyit
     edin". With today's code a browser check on a copy (headless Chromium, the first row) posts STR-12 and writes it;
     the rows' forms were alike ("Teyit edildi / Reddedildi" eleven times, the finding named only above the form), and a
     row is a group: confirming its lead left the group's other finding (STR-9-e3f85546, "6 sayfada <html lang>…") behind
     as a new row. Now a check is recorded for every finding of the row's group; each form names its finding ID in its
     summary and its buttons' labels; the row lists the group's IDs; the save notice names the title and IDs saved; a
     checked row shows its card note; POST answers `saved: {finding_ids, result, file}`; the skill's `--confirm` /
     `--reject` cover the group the same way. A card with four or more lines under its status (a confirmed group: the
     note, the regions, one line per finding) keeps two steps, so it fits its box (nihan's English STR-12 card did not
     with three). The owner's file is not
     changed: STR-12 is confirmed there with one save in "Teyit edin" (or the ACC-4 entries rejected/kept as they wish).
     (1) *Platform steps only on that platform.* The catalogue (`maya_audit/rule_actions.json`) and the text library had
     a Shopify line in the steps every site gets (idx6.alias_links "within: collection", acc3.utility_indexable,
     str3.product_no_identifier): Moodist's card 04 printed it. Those lines moved to `steps_by_platform.Shopify` (the
     platform's list: every step, its own line in place); a card shows them only when the report's platform is
     Shopify (RG-11 checks it). A test keeps every generic step free of a platform name.
     (2) *Platform from saved data* (`site_platform.recognise_saved`): a page reader's saved copy keeps no script list,
     so a Firecrawl-only audit named no platform. When the report names none, the saved data is read: a sitemap the
     platform names (`sitemap_products_N.xml?from=`), its file CDN in the saved copies (`cdn.shopify.com`,
     `/cdn/shop/`, `.myshopify.com`), and addresses under both `/products/` and `/collections/` (3 or more each); each
     signal is said, "(saved data, DECISIONS 309)". Used by the live report (`report.py`), the offline reassessment and,
     for a report of the current schema, `reassess_rules.saved_data` in the derived copy (`current.py` reads
     `evidence/` and `evidence-firecrawl/`). Shape unchanged (name, cdn, signals): no schema bump.
     (3) *Key pages.* The rank shown is the place in the list (1, 2, 3 ...): a page not read (Moodist's `/en/en/`, rank 2
     by importance) leaves no gap. The main-language homepage (the start address's final page, else the start address)
     comes first, then the other language homepages read, then the rest by importance; the site root and a one-folder
     locale path (`/tr/`, `/en/`, `/ru/`, `/ar/`) are typed homepage. Importance stays the page's own score (Moodist's
     `/tr/` is 20: its canonical names `/tr/tr/`, the S2 card).
     (4) *Note cards:* after every problem card, only in a slot they leave free, at most `NOTES_SHOWN = 2` in the PDF;
     all notes stay in the appendix (Moodist went from 11 + 4 to 11 + 2).
     (5) *Read, importance unknown:* a page whose content was read (Maya's 2xx or the page reader's) but has no
     importance counts `NEUTRAL_IMPORTANCE = 50` in the reach and is never "not read"; the card says "Okunan, önemi
     bilinmeyen N sayfa: puana nötr ağırlıkla katıldı." / "N pages read, importance unknown: counted at a neutral
     weight." (`pages_read_unscored`, `read_unscored` in the appendix rows). Ranking only: no severity changes.
     (6) *Rendered HTML:* RND-6 measured on Firecrawl's HTML (`evidence.html_measured` "rendered …", or an older
     audit's `evidence.source.reader == "firecrawl"`) is estimated, goes to "Teyit edin" with the reason "işlenmiş HTML,
     karşılaştırılamaz" / "rendered HTML, not comparable", and an older audit's title gets the label the current engine
     writes (DECISIONS 299 (4)). Maya's own RND-6 stands as before.
     (7) *Low coverage:* `client_selection.low_coverage`: fewer than 10 pages read, or under 20% of the page cap. Page
     1 of the PDF and the top of the web results show a banner ("Düşük kapsam: planlanan 500 sayfadan yalnız 1 sayfa
     okundu …"); `client_brief_allowed(report)` returns `(False, "low_coverage")`, the gate a future client brief
     passes first. The team report itself is still built, with the banner.
     (8) *History list:* each saved audit shows date and time, mode ("Hızlı 50", "Standart 500", "Tek sayfa"), pages read
     and the reading path (Maya / Firecrawl / Maya + Firecrawl), from the evidence indexes (never report.json), cached
     while they are unchanged; without saved evidence, the progress counters.
     (9) *Words:* every label goes through one format with `{name:singular|plural}` (`texts.label`): "1 page read",
     "1 group to confirm", "The first affected address", "1 of 1 URL checked"; a name with a capital inside its first word
     keeps its case after "ve"/"and" ("JavaScript'e", not "javaScript'e"); ACC-9's scope is "1 sayfa isteği" / "1 page
     request" (not "1 dosya"); a scope whose addresses were mostly never read says "adres" / "addresses"; the finding
     IDs in a card header wrap whole to the next line instead of being cut at the card's edge.
     Tests: `tests/test_team_report_309.py` (22, one slow through the real routes: confirm with a note -> rebuild -> the
     card with "Elle kontrol: <note>" in the PDF, nothing of the group left to confirm; a rejection takes it out);
     `test_team_report` follows the group-wide save.
310. **Web app UX: one clear path for the team (Owner, 2026-11-05: the Step 1 proposal approved with changes; the
     layout, wording, cache and test pages are agent defaults).** Behaviour and data unchanged; no engine judgment
     changes; every route and download kept.
     (1) *Results, in order:* 1 Summary (the team report's own verdict and its first three numbers, plus "Teyit bekleyen"),
     2 "Neyi düzeltmeli" (the report's cards: title, why it matters, scope, owner, effort; the first five, the rest one
     click away; IDs small and grey), 3 "Önce bunları kontrol edin", 4 "İndir" (language, team report PDF, appendix XLSX,
     "Müşteri özeti — Yakında"), the suggested questions and the chat box, 5 "Teknik ayrıntılar", folded: everything the
     page showed before (outcome, coverage, Firecrawl, all problems, every page, Core Web Vitals, other downloads, the
     plan). (1) and (2) come from GET `/audits/{id}/overview`: `build_data.build_from_files` on the copy re-evaluated
     with the current engine (DECISIONS 308), cached per copy, review file and language, so the page says the PDF's
     numbers in the PDF's words (the old headline used the saved report: nihan 28 issues there, 31 in the PDF). A
     finished audit's job card is one line with its plan and steps folded.
     (2) *Check these first:* at most three items open, highest severity first, the rest under "Diğer N bulguyu göster";
     the line "İsteğe bağlı: kontrol etmezseniz bu bulgular rapora girmez, ekte kalır."; two big buttons "Doğru" /
     "Doğru değil"; the name is asked once and remembered in the browser (localStorage, asked again when it is not
     available); "Ne gördünüz" and "Kartta görünecek not" optional with an example placeholder; a missing name is said
     beside the field ("Lütfen adınızı yazın.", also from the server: 422 `invalid_review`, `details.fields.by`); a saved
     item moves to "Kontrol edilenler" with "Geri al". Undo: DELETE `/audits/{id}/review/{finding_id}` takes the group's
     entries out of review.json and keeps them in `replaced` with `undone` (`manual_review.undo`). `manual_review.entry`
     now requires only who checked; `seen` is optional (left out when empty). Each row's scope is the PDF's.
     (3) *Time estimates* from real runs: the median of the last five finished one-session audits of the mode ("yaklaşık
     6 dk (bu moddaki son 5 denetime göre)"), on the New audit cards, the plan and while it runs ("Yaklaşık 4 dk kaldı",
     the median less the time spent; past it, "her zamankinden uzun sürüyor"); with no run of that mode yet, a range from
     the plan's own bound (a quarter of it to all of it). The measured estimates stay in the progress details.
     (4) *History:* site, date and time, mode, pages read and reading path (DECISIONS 309), a plain status (Bitti, Sayfa
     sınırına ulaşıldı, Erken durduruldu, Çok az sayfa okundu; Sırada, Çalışıyor, Çalışmadı) and the short ID; revised
     analyses in their own section below (the row overlapped); search by site. "Çok az": fewer than min(10, page cap)
     pages read, or under 20% of the cap.
     (5) *New audit:* the address, three depth cards (Tek sayfa / Hızlı 50 / Standart 500) with their recent time, extra
     options folded, "Planı göster"; the plan says pages, time and cost in three lines with one Start button, its
     details folded (opened by themselves when an approval or a warning needs an answer). Progress: the steps in plain
     words with ticks, the pages read and the time left, Stop with what stopping does; counters and log folded.
     (6) "?" hints for canonical/kanonik, hreflang and noindex. Turkish by default (`create_app(default_language="tr")`
     from `python -m maya_audit_web`; tests keep English unless they ask), English through the switch. Laptop widths
     without horizontal scrolling (checked at 1280 and 1440); every action is a button or link with a visible focus.
     Tests: `tests/test_web_ux_310.py` (9: the form's validation, save and undo through the routes and in Chromium, the
     history list, recent-run times and the range, the summary = the team report's, Turkish by default);
     `test_web_firecrawl`, `test_team_report`, `test_v03_client_report` follow the new page.
311. **Business types ("İşletme türü"), v0.3 stage 4 (Owner, 2026-11-05: the plan approved with A1, 50/35/15, notes
     for the top 3, the early suggestion in the progress box, guesses marked in the signal table, check switches left
     for Stage 7; the signals, scores, thresholds, the unmatched weight and the layout are agent defaults).**
     New `maya_audit/business_types/` (profiles in `profiles/*.json`), called by `final.settle` after the page grouping
     and by `client_selection.grouping` for a saved report. It sends no request. **No check, severity, confidence or
     release-gate decision reads it**; importance orders cards (reach) and key pages only
     (`test_a_profile_changes_importance_and_key_pages_never_a_finding_or_a_severity`).
     (1) *Profiles.* One per sector of the owner's file (`docs/business-types/Maya-sektor-ve-oncelikli-sayfa-turleri.xlsx`,
     12 sectors, page types in its order), "Restoran / kafe" (owner: Menü, Şube ve konum, Rezervasyon / sipariş, Ana
     sayfa, İletişim) and "Diğer". Weights by rank 100/85/70/55/40/30 (`RANK_WEIGHTS`, per profile `weights`); the
     homepage at least 85 (added at 85 where the sector list has none: Yatırım, Kart, Otomotiv, B2B SaaS, Su arıtma,
     Güvenlik, Gıda, Seyahat); "Rehber / SSS / blog" added at 30, citable, where a sector has no guide (Otomotiv's
     "Teknik rehber" and B2B SaaS's "Rehber" keep their rank and are flagged citable). Agent defaults: a page that matches
     no type 25, policy 15, utility 0 (as Stage 3). Finance is one group in the UI (Bankacılık, Yatırım hizmetleri, Kart
     ve sadakat programları).
     (2) *Page type per profile* (`business_page_type`, Stage 3's `page_type` kept): points per kind of signal, each kind
     once: address word 4, structured-data type 3, a word in the title or H1 2, a word in the menu or link text pointing
     to the page 2, a content signal 1 (form, price, map, calculator, FAQ, table, list); a type needs 3, ties go to the
     higher rank. The homepage, utility pages and policy pages come first (a profile's help type may take policy pages:
     E-ticaret "Yardım ve güven", Güvenlik "Destek ve koşullar", Seyahat "Rezervasyon koşulları"); without a match the
     Stage 3 type maps to the profile's type that lists it, else "other". Section headings (H2+) and FAQ markup do not
     name a page (enpara: product pages with an FAQ block had become "Destek"); a structured-data type on half or more of
     the pages read is a site default and is ignored (adile: Article on 35 of 36 pages). The signals and their status
     (guess or seen on a saved audit): `docs/business-types/signals.md` and `signals.xlsx`
     (`tools/business_types_table.py`, from the profiles and `docs/business-types/seen.json`).
     (3) *Importance* = round(0.5 x profile weight + 0.35 x internal link score + 0.15 x click-depth score), with Stage
     3's caps (not indexable or utility 20, footer-only policy 35). `importance_source`: `links` ("Diğer", and every
     report before 1.25) or `profile:<id>`; Stage 3's values stay in `importance_links` / `importance_rank_links`. "Diğer"
     gives Stage 3's importance, rank, cards, priorities and key pages exactly (`test_other_gives_today_s_results_exactly`).
     A third source, `maya_top_pages` (Maya dashboard TOP PAGES, GSC clicks), is the next step (BACKLOG).
     (4) *Suggestion* (`suggest`): per profile, homepage structured data +4, platform +4, the share of the site's
     addresses with the profile's words (+4 at 10% or more, +3 at 3 or 5%, else +1), homepage menu words +1 each (at
     most 4); the best needs 4 and a lead of 1, else "Diğer" ("Net bir işaret yok (en yakın: …)"). "Offer" markup does not
     point to E-ticaret (banks and SaaS use it). The person confirms or changes it: CLI `--business-type`
     (`CrawlConfig.business_type`, "auto" by default); the web app's new-audit form ("İşletme türü", default "Otomatik
     öner"); the plan (A1: the plan requests nothing, so it shows the suggestion of this site's last audit, else
     "Önerilen tür ana sayfa okunduğunda belirlenecek", with a dropdown that makes a new plan); the progress box ("Önerilen
     işletme türü: … (neden: …)" as soon as the homepage is read: a `business_suggestion` progress event from the crawler,
     a hint only); the results summary (the type, why, "Değiştir": POST `/audits/{id}/business-type` writes
     `artifacts/business-type.json` beside review.json, `auto` removes it; report.json is never written). The report keeps
     `crawl.business_type` (schema **1.25**: id, label, chosen_by, suggestion with reason, the importance summary,
     not_found); a saved report without it gets the suggestion from its saved data. The team report's page 6 names it
     ("İşletme türü: Bankacılık (önerildi; neden: …)") and its key-pages table uses the profile's page types.
     (5) *Not found:* the profile's first three page types no page read was typed as: "Fiyat listesi sayfası okunan
     sayfalar arasında bulunamadı (sitede olmadığı anlamına gelmez)" in the team report's key-pages card and the web
     summary; none on a low-coverage audit (DECISIONS 309).
     (6) *Also:* time estimates count only finished one-session runs of the mode with the current engine's speed mark
     (`timeplan.SPEED_VERSION`, stored in the audit's `flags` when it starts; raise it when a change alters run time)
     that stopped at the page cap or ran out of pages and read enough pages (not stopped, rate-limited, robots-blocked or
     "too few"); with fewer than 3 such runs, the mode's default: Tek sayfa 1 dk, Hızlı 50 10 dk, Standart 500 25 dk (the
     v0.3 time goals), said as "varsayılan tahmin". Existing audits have no mark, so the defaults show until three new runs
     finish. History: "Gizle" per row (PUT `/audits/{id}/hidden`; a `hidden` column added by the app's own column
     migration on its next start; the files stay), "Gizlenenler (N)" lists them with "Yeniden göster".
     *Also fixed:* a language folder is two letters, optionally a region (two letters or three digits) or a script
     (`page_groups._LOCALE`): `/qr-menu/` was taken for a language and typed a homepage (adile, DECISIONS 309's key pages).
     *Not in this stage:* switching checks on or off by business type (`reviews/checklist/mapping.xlsx`, "Profiles (Stage
     4)") moves to Stage 7.
     *Offline on copies of the saved audits* (current-engine copies in a scratch folder; `tools/business_types_saved.py`):
     nihan -> E-ticaret (Shopify; 22.114 addresses with products/collections), moodist -> Sağlık (Hospital markup),
     enpara -> Bankacılık (143 addresses with kredi/mevduat; menu), adile -> Restoran (FoodEstablishment; sube/subeler);
     the card order is unchanged on all four (priorities move by a few tenths); not found: enpara "Destek", adile
     "Rezervasyon / sipariş". Details: `docs/IMPLEMENTATION-STATUS.md`.
     Tests: `tests/test_business_types_311.py` (22); `test_page_groups` pins "Diğer" for Stage 3's own values;
     `test_web_ux_310` follows the default estimate; schema literals 1.24 -> 1.25.
312. **Key pages: the language homepages as one row, a place for each profile page type; provider-free local runs
     (Owner, 2026-11-05; the reserved place per page type is an agent default, needed because merging alone left
     moodist's "Doktor ve ekip" out).**
     (1) *One homepage row* (`client_selection.key_pages`): the main homepage and its language versions read (`/tr/`,
     `/en/`, `/ru/`, `/ar/`) are one row, "Ana sayfa (4 dil)" / "Homepage (4 languages)" in the team report, the XLSX
     appendix (its cell lists every address) and the short summary; the row's cards and checks are those of every
     version, its importance the main homepage's own (moodist `/tr/` 20, its canonical issue). Replaces DECISIONS 309's
     one row per language homepage. (2) *A place per page type:* with a business type, every page type of the profile
     found among the pages read (not home, other, policy, utility) keeps a place for its best page; the other places go
     by importance and the list stays in importance order. Merging alone was not enough: moodist has 19 treatment pages
     at 87-89 above `/tr/ekibimiz/` (80). "Diğer" has no profile types, so its list is the importance order as before.
     Top 10 after, offline on the copies: moodist: homepage (4 languages), 8 treatment pages, `/tr/ekibimiz/` (Doktor ve
     ekip); enpara: homepage, 7 product pages, `/ucretler` (Ücret ve başvuru), the loan calculator (Hesaplama aracı);
     adile: + `/qr-menu/` (Menü); nihan: homepage (2 languages), 6 collections, a product, `/blogs/news`, a help page.
     Cards unchanged on all four.
     (3) *Provider-free local runs* (AGENTS.md, "Shared preamble" 8; the repository's AGENTS.md): every CLI or
     verification run is made from a temporary folder with `MAYA_AUDIT_ENV_FILE` pointing at a file that does not exist,
     its own `MAYA_AUDIT_HOME`, every provider key empty and `--no-firecrawl`, against a loopback fake site (after the
     DECISIONS 311 check run sent 5 Firecrawl requests, 0 credits). `tests/conftest.py` now also unsets the CrUX,
     PageSpeed, Bing and Search Console keys (`PROVIDER_KEYS`), with a guard test. The recipe was run once as written:
     exit 0, JSON written, no Firecrawl section, no provider ledger.
     Tests: `tests/test_key_pages_312.py` (5); `test_team_report_309` and `test_v03_client_report` follow the one row.
313. **Global UI fixes: business-type chip, exact headline counts, hints after the title, "adres" not "URL", the
     homepage's importance when a canonical problem holds it down (Owner, 2026-11-05, moodist c581ff0a as the test case;
     the wording of the reasons and the layout are agent defaults).**
     (1) *Business type* (results summary): a compact chip "İşletme türü: Sağlık / klinikler", the reason folded under
     "Neden?" ("Siteden önerildi: …" or "Sizin seçiminiz."), and "Değiştir" showing the type in use, the suggested one
     marked "(önerilen)"; there is no "Otomatik öner" there: choosing the suggested type goes back to the suggestion
     (`auto`, the choice file removed). The overview returns the reason (`business.reason`).
     (2) *Headline* (`texts.headline(counts=…)`, the web summary and PDF page 1): the problems by severity, the same
     counts as the first KPI: "1 yüksek, 7 orta ve 11 düşük önemde sorun var; önce …" (moodist). "Engelleyici" /
     "blocking" only when a Blocker is counted; English "There is 1 medium-severity issue" / "There are …".
     (3) *Hints:* a card title stays whole; one "?" per technical term it uses (canonical/kanonik, hreflang, noindex)
     follows it, in the order the terms appear.
     (4) *Units:* "URL" is gone from Turkish text: "adres" with its Turkish case endings (URL'si -> adresi, URL'lerin ->
     adreslerin …) in every Turkish value of `locales/tr.json`, `locales/findings/tr.json`, `locales/catalog/tr.json`,
     `team_report/texts/tr.json` and `etiketler.json` (230 values; English keys unchanged); pages read stay "sayfa".
     Kept as written: Google's tool name "URL Denetimi" and its English status "URL is unknown to Google" quoted.
     (5) *Key pages:* when the main homepage is capped as not indexable and a card covering it is a canonical (IDX-4) or
     redirect (IDX-2, IDX-3) problem, its importance is "önem hesaplanamadı (kanonik sorunu, bkz. kart #1)" instead of
     the capped number (moodist `/tr/`: 100 for links, depth and type, 20 because its canonical names `/tr/tr/`, card 1
     idx4.redirect_loop); the PDF row reads "Ana sayfa (4 dil) · önem hesaplanamadı (…)" across the type and
     importance cells; the appendix and the short summary say the same (`client_selection.importance_unknown`).
     Shown on moodist through an isolated copy of the web app (port 8771, provider-free; the real web home untouched).
     Tests: `tests/test_ui_313.py` (6, two in headless Chromium).
314. **One version per running app; the report column centred (Owner, 2026-11-05: raw text keys, the old headline,
     "4 URL" and an old engine commit seen on port 8770 after 03bc8ae; the layout and the notice's wording are agent
     defaults).**
     (1) *Cause.* No text key was missing (TR and EN both hold every key the page uses; the app on 8770, started at 21:45
     after 03bc8ae, serves them). The page's script and stylesheet were read from disk on every request, while the text
     table, the headline builder and the engine stay as they were when the process started: after an update without a
     restart the new script asked the old process for keys it did not have (shown raw), and the old process built the
     old headline, "URL" and its own engine commit. The derived copy itself was right: it is keyed by the engine
     fingerprint and was rebuilt with 03bc8ae on the first open after the restart.
     (2) *Fix* (`maya_audit_web/build.py`): the page, app.js and app.css are read once when the app starts and served
     from memory (`/static/app.js?v=<build>`, `Cache-Control: no-cache` with an ETag, 304 on revalidation), so a page
     always comes with the texts and engine of the process that serves it. GET `/api/v1/version` gives the build, the
     code fingerprint the process started with and the one on disk (hashed at most every 20 s); the page checks it at
     start and every 5 minutes and shows "Maya Audit bu bilgisayarda güncellendi. … yeniden başlatın" when they differ.
     A key a language lacks is said in English, a key no table has is "…": never the raw key. The derived copy's
     fingerprint now also covers the text libraries (team report texts and labels, the web translations), so a changed
     sentence rebuilds it too.
     (3) *Layout:* every item of the report column is centred in the space right of the sidebar (max 920 px, auto side
     margins that no item's own margin overrides: a finished audit's card had `margin: 0 0 …` and sat on the left); the
     chat bar was already centred. Measured on the normal app path (a copy of the owner's web home, port 8772,
     provider-free): left/right margins 32/32 at 1024 px (full width), 124/124 at 1440, 364/364 at 1920, 684/684 at
     2560, 479/479 at 1440 and 67% zoom; before: 32/216, 32/696, 32/1336.
     Tests: `tests/test_web_build_314.py` (7: every key in TR and EN, prefix keys, the fallback, the snapshot, the
     version route and 304, the derived copy rebuilt on a text change, the centred layout at five sizes in Chromium).
315. **Stage 8a: borrowed from Screaming Frog (Owner, 2026-11-06: items 1-5 of the research file's recommendations as
     planned; A = a chain is 3+ addresses (today's IDX-3 rule); B = a compact "Şablonlara göre sorunlar" page, the 10
     largest templates; C = a Fırsat badge, order unchanged; template line at 80% of a card's pages and at least 5. Each
     rule's severity, type and wording, the opportunity/warning lists and the cluster rule are agent defaults).**
     Source: `docs/research/screaming-frog-research-for-maya-audit.md`, "Recommendations" 2, 3, 5 (and 1 in part).
     (1) *Redirects.* `crawl.redirects` (schema **1.26**): every requested address that redirected, hop by hop
     ({url, status, target}), its final address and status, and whether it loops (`checks/stage8_rules.redirect_records`;
     also written into the current-engine copy of an older report, `reassess_rules._decisions_315`). New
     `idx6.links_to_redirect` (IDX-6, S4, Sorun, developer): internal links to an address that redirects, each target with
     its final address, hops and linking pages. IDX-3's chains (2+ redirects, 3+ addresses) and loops are kept.
     *One cause, one card:* findings of the redirect/canonical rules (`client_selection.CHAIN_RULES`: idx4.redirect_loop,
     idx4.redirecting, idx4.chain, the IDX-3 chain and loop rules, idx6.links_to_redirect) that name a shared address
     (their pages, canonicals and where those resolve, chain hops, link targets; not the linking pages) are merged into
     one "redirect_chain" card, its severity the highest; a cluster made only of links to a redirect is not merged; an
     unrelated chain elsewhere stays its own card. The card says the chain hop by hop, how many pages link into it and the
     address to link to, and which page names which canonical. moodist: cards 01 (idx4.redirect_loop, `/tr/` -> `/tr/tr/`),
     03 (idx4.redirecting, `/en/` -> `/en/en/`) and 09 (idx3.chain `/tr/tr/` -> `/` -> `/tr/`) and the new links-to-`/`
     finding (50 pages) are one High card: "Zincir: /tr/tr/ → / → /tr/. 50 sayfa zincire bağlanıyor; bağlantıları /tr/
     yapın." / "Kanonik: /tr/ → /tr/tr/ · /en/ → /en/en/."
     (2) *Issue type* beside severity (`maya_audit/issue_types.json`, every rule id listed; a test fails on a rule without
     one): Sorun / Kontrol edin / Fırsat (Issue / Warning / Opportunity); 217 / 40 / 46 rules. A group in "Teyit edin"
     shows Kontrol edin until checked; confirmed in review.json it takes its rule's type (a Kontrol edin rule becomes
     Sorun); review.json is read as before and never written by this. Shown on the PDF cards, in the XLSX ("Sorun türü")
     and on the web results' cards; severity, placement and order are unchanged.
     (3) *Templates (segments)*: `client_selection.templates_table`: every template with pages read, its pages, the pages
     a problem touches, the problem groups, the cards and the highest severity; a template's language folder is left out
     (`/en/collections/*/products/*` is `/collections/*/products/*`: one theme fix). PDF: "Şablonlara göre sorunlar", the
     10 largest (8 pages for moodist, 9 for nihan); XLSX: "Şablonlar", all. A card says "Tek şablon düzeltmesi: ürün
     şablonu (/collections/*/products/*): 63 sayfa" when 80% of its pages read, and at least 5, are in one template.
     (4) *Whole-site checks after the crawl*: new `idx4.chain` (S3, Sorun): a canonical naming a page whose own canonical is
     a third address; new `str9.wrong_language` (S3, Sorun): an hreflang link whose target page declares another
     language (a malformed code such as "jp" stays str9.bad_codes'). Already covered and kept: missing return link,
     target not 200, target not indexable or canonicalized elsewhere (str9.target_page), missing self-reference or
     x-default (str9.cluster), canonicals that redirect, loop or are broken/noindex (IDX-4).
     (5) *Images*: new `str7.over_100kb` (S4, Fırsat): sampled image files between 100 and 500 KB (over 500 KB stays
     str7.heavy); unknown sizes are counted apart, never as small. Missing alt and width/height stay STR-7's rules; every
     image finding is grouped by template through (3).
     *Also fixed (Stage 4's matcher):* on a tie between two page types the deeper address word names the page:
     `/collections/c/products/p` is "Ürün detayı", not "Kategori" (nihan's products had escaped it through their Product
     markup).
     Every new rule: wording frame (`wording.py`, `rule_ids.json` regenerated), Turkish title, fix, expected and note
     (`locales/findings/tr.json`), action and steps (`rule_actions.json`), team-report texts in both languages, owner and
     effort (`recommendation_catalog`), type. Thresholds in docs/LAUNCH-GATE.md (LG-102).
     Not in this stage: list mode, raw-vs-rendered diff beyond RND, near-duplicate method changes, crawl comparison,
     custom extraction (the research file's 4, 6-9).
     Tests: `tests/test_stage8a_315.py` (11, fake sites and hand-made reports); `test_normal_report_accuracy` gives its
     hand-made copies their own rule id; `test_v03_client_report` follows the new sheet; schema literals 1.25 -> 1.26.
316. **Fixes from the airastana.com audit: one page limit, one version per page, Imperva's block page, the airline type,
     four tiles, "Teyit edin" explained, headline and Turkish forms (Owner, 2026-11-06, audit d12146fb, Quick 50; tested
     offline on it and on moodist c581ff0a and nihan b3198942. Global rules; brands are only test cases. Thresholds, the
     airline signals and every wording are agent defaults: LG-103).**
     *Root cause found first:* every page Maya's own crawler read on airastana (50 of 50, the homepage included) was
     Imperva (Incapsula)'s block page: status 200, ~1 KB, `<meta name="robots" content="NOINDEX, NOFOLLOW">`, an iframe of
     `/_Incapsula_Resource` saying "Request unsuccessful. Incapsula incident ID …". The classifier knew no Imperva page, so
     the block page was read as the site's page: 49 "noindex in the sitemap" pages, "149 / 149 unsuitable sitemap
     addresses" (the 100 light requests got the same page), 50 iframes without a name, the HTML timing and the homepage's
     headers, and every key page capped at importance 20. Firecrawl, the main reader, read the real pages.
     (1) *Pages read never exceed the plan's limit, one number everywhere.* "61" was 50 pages of Maya's crawler + 11
     different pages of Firecrawl, each with its own 50-page cap (13 read, 2 the same). Now one limit: the page reader may
     read again the pages Maya read (its copy is the one the content checks judge) and reads a page Maya did not read only
     while both together stay within the plan (`firecrawl.reader._read_pages`, `over_budget`; a redirect onto a new page
     past the limit is `outcome: over_page_cap`, not counted). On airastana's saved audit the block pages are not pages
     read (below), so it counts Firecrawl's 13. The history list takes the count of the current-engine copy (its
     `meta.json` keeps `read`), so the history, the summary, the PDF and the XLSX say the same number (the XLSX prints
     no total).
     (2) *Country/language copies.* `maya_audit/locales.py`: a site's locale folders from its own addresses: a plain
     language folder (`/en`, `/tr`, `/en-us`) with a known language code, or any pair-shaped folder (`/global-en`,
     `/chn-zh`, `/kaz-kk`) when another such folder holds 2+ of the same pages or an hreflang link names it (`/how-to/`
     and `/tv/` are not locales). The root is a version only when the homepage lives there. `crawl.locales` (schema
     **1.27**): folders, main (where the homepage landed), versions, basis. The crawl frontier (`scratchpad`, new columns
     `page_key`, `locale`, `boost`; table `page_copies`) and the page reader's queue (`firecrawl.reading`) key sections
     with the folder replaced by one placeholder (`/tr/post/` and `/en/post/` are both `/_l/*`; taking the folder out
     would make every post a section of its own), read a page in no version before a second version, a page already read in 2 versions (the
     homepage: 4, for the hreflang and wrong-language checks; its versions are read like new pages, and it is always a
     key page) only when nothing else waits, and within a section round
     the business type's first three page types (by address word; the person's type, else the sitemap's suggestion) and
     then the main version first. A fake site shaped like airastana (6 pages × 5 folders, 10-page cap) reads all 6 pages
     in `/global-en/` before any second version. The report says it once: "20 country/language versions found; one
     version per page was read" (or "at most 2 versions of a page"; an older audit that read more says "up to N …
     (read by an older engine)"; the homepage's versions are said apart): on the web summary under the tiles and in the
     PDF under Maya's own limits. The per-locale checks are unchanged (they read the pages read).
     (3) *Travel split.* "Seyahat / rezervasyon" is a group of two profiles: `havayolu` "Havayolu" / "Airline" (new:
     destinations and routes 100, flight search and schedule 85, fares and campaigns 70, baggage 55, check-in and online
     services 40, booking help and terms 30; homepage 85, guide 30) and `seyahat` "Tur / otel" / "Tours / hotels" (the old
     profile, id kept). The suggestion reads address words with the locale folder left out (airastana's "tur" was
     `/tur-en/`, Turkey) and counts one address per page across folders; the airline profile adds Airline/Flight/Airport
     markup, flight/baggage/check-in/mmb words and airport-code routes (`/ala-ist`, counted when both codes appear in
     another route, from 3 addresses). Business-type version 2: a saved version-1 suggestion is worked out again.
     airastana: "Havayolu" (37 pages with 'mmb', 'baggage' …; tours 3 from 4 hotel pages); moodist "Sağlık", nihan
     "E-ticaret" unchanged (their counts now count one address per page: 58 -> 54, 22,114 -> 12,220). signals.md and
     signals.xlsx regenerated.
     (4) *The same four tiles.* PDF: recorded issues, pages read, pages with Medium+ issues, mobile lab; web: the first
     three and "waiting for a check". The sitemap tile is gone; a striking sitemap result (half or more of 10+ checked
     addresses) is said on its card in plain words, its commonest cause named when it is 80% of them: "All 149 checked
     sitemap addresses redirect to a country/language version." (`sitemap_line`, PDF card and web card). airastana's
     149/149 was not a sitemap problem: all 149 got Imperva's block page (49 read by the crawl, 100 light requests of the
     same size and robots tag).
     *Imperva:* `classify` knows the block page (the incident text, or the resource as an iframe: Imperva also injects
     `/_Incapsula_Resource` scripts into normal pages, which stay OK); a new audit marks those answers blocked and the
     reader takes the site as a blocked one. A saved audit's current-engine copy (`reassess_rules._decisions_316`)
     recognises the block page from the saved record (the iframe, 50 visible words or fewer), marks those records blocked
     and not read, removes what was measured only on them (each removal listed in the copy's changes; findings the page
     reader's own copy produced stay), sends the soft-404 probe that got the same answer to "confirm first", re-runs
     ACC-9 ("Imperva … 50 of 50 … 13 page(s) were read through Firecrawl instead") and the direct-access line, and counts
     the pages read again. report.json is never written.
     (5) *"Teyit edin" vs recorded issues.* The two count different things: "Kayıtlı sorun" counts findings with a
     severity (S1-S4); "Teyit edin" counts groups, Info notes included. On airastana 14 of the 17 were Info notes marked
     "seen only in Firecrawl's copy", compared with Maya's copy, which was the block page: a fresh audit of a blocked site
     sets no such mark (`double_reading.applies`), so the copy takes it off when every page of Maya's copy was a block
     page (an automatic check, no person needed). airastana 17 -> 3. The web tile now says what it holds: "2 sorun
     (kayıtlı sorunların içinde) ve 1 not". Duplicates per root cause were already one group (the rule and cause key);
     none remained on the three audits.
     (6) *Wording.* EN headline: "start with the certificate expiry" ("the" before each focus, also in the assessment
     line; checked against all 302 summaries); TR: "…; öncelik: sertifika süresi." (was "önce sertifika süresi."); the
     headline may be 100 characters (was 90; moodist's EN headline kept its focus). Turkish instructions use one form,
     the polite imperative ("doğrulayın", "koruyun"); impersonal statements keep "-meli" without "-dır": 488 lines of
     the team report's text library, 56 engine fix translations, 8 web strings and the client brief advice (the
     deprecated client brief's card check, `client_reporting.validate_cards`, now accepts this form beside
     "-malısınız"); "Bilinçli
     dışlamayı korumalı" is now "Bilerek dizin dışında tutulan sayfalara dokunmayın; noindex'i yalnızca aramada yer alması
     istenen sayfalardan kaldırın."
     *Before / after on airastana's saved audit (current-engine copy, offline):* tiles "Kayıtlı sorun 10 · Okunan sayfa
     61 · Uygun olmayan sitemap adresi 149/149 · Mobil lab ölçülmedi" -> "6 · 13 · Orta ve üstü sorunlu sayfa 1/13 ·
     ölçülmedi"; type "Seyahat / rezervasyon" -> "Havayolu"; card 01 "Site haritasındaki noindex'li sayfaları netleştirin
     (49 sayfa)" removed, card 01 now the TLS certificate; key pages: ten block pages at importance 20 -> the pages
     Firecrawl read, typed (Destinasyonlar ve uçuş rotaları, Uçuş arama, Check-in …), importance "not computed (read only
     through the page reader)"; "Teyit edin" 17 -> 3. moodist and nihan: the same tiles, cards, key pages and types; only
     the headline wording, the versions line and the suggestion's address counts differ.
     Not changed: nihan's English card 02 title box overflows the PDF at HEAD already (`todos[1].title`); left as it was.
     Tests: `tests/test_airastana_316.py` (17, fake sites, a made-up Firecrawl and hand-made reports); schema literals
     1.26 -> 1.27; tests that pinned the old wording, the business-type list, the hospital fixture's sections (its
     `/en/team/` and `/tr/team/` are now one section) and one empty-page split (the restaurant's `/sube/` is read first)
     follow the new rules. The demo shop's crawl is page for page the same as before.

317. **Block pages never use up the page limit; an access finding for a named bot-protection service; link data for pages
     read only through the page reader; long titles never stop the team report's PDF (Owner, 2026-11-06, follow-up to
     316; tested offline on airastana d12146fb, nihan b3198942 and moodist c581ff0a. Global rules; brands are test cases.
     The finding's wording, confidence class and steps, and the title sizes, are agent defaults: LG-104).**
     (1) *Page limit.* A block page (Imperva, Cloudflare, Akamai, DataDome, HUMAN/PerimeterX …) or a 429 is not a page read
     and never counts. Two gaps closed in `firecrawl.reader._read_pages`: when the crawl as a whole counted as blocked, Maya's
     few good pages were left out of the limit (a fake site with 4 good pages and 6 block pages on a 10-page plan counted 12
     pages read → now 10: Maya's 4, read again by Firecrawl, and 6 new); and as the main page reader, Firecrawl skipped every page Maya got a block page for (treated
     like a redirect or an error, whose status is the finding) → it now reads it, within the limit. When every page was a
     block page (airastana) a live run already left Firecrawl the whole plan; that is now recorded and said:
     `firecrawl.coverage.page_limit` (schema **1.28**: `plan`, `maya_pages_read`, `block_answers`, `block_answers_counted`
     = 0, `reader_new_pages_allowed`; a saved copy's is `worked_out_offline`). One line under Maya's own limits (PDF, web
     summary, XLSX Coverage): "Block pages did not count toward the page limit: Maya's crawler got a block page on 50
     requests; the page reader could read up to 50 pages and read 13 (the time limit came first)." *airastana:* the 50 block
     pages do not count, so Firecrawl could read up to 50; it read 13 because the audit's time ran out (Firecrawl took
     ~35 s a call there, timed out twice and backed off to one request at a time), not because of the limit. A new audit
     of airastana would read up to 50 pages if time allows; nothing was requested to show it.
     (2) *Access finding.* ACC-9 `acc9.bot_protection` when the commonest blocker is a named service and not a rate limit:
     "Maya's crawler blocked by bot protection (Imperva): 50 of 50 page request(s) got its block page. AI crawlers (GPTBot,
     ClaudeBot, PerplexityBot, Google-Extended) may be blocked the same way", S3 when the homepage or 20%+ of pages (S4
     otherwise), fix: find the rule in the service's bot settings, allow Maya's user agent and re-run, allow GPTBot,
     OAI-SearchBot, ClaudeBot and PerplexityBot by user agent with each vendor's published IP ranges, allow Googlebot
     (Google-Extended is a robots.txt setting, not a crawler), check the firewall logs. Like the 429 card (288) it stays a
     finding when Firecrawl reads the pages (`note_the_challenge` leaves it, adding `read_through`), and its PDF card has
     one line naming the service and the four crawlers. Its confidence is the classification's (Verified from a header or
     a status, Estimated from a block page's body): the block is measured, what AI crawlers get stays a "may" in its words;
     the 429 card's Inferred would have sent it to "Teyit edin". Turkish title, fix and summary; the vendor names are terms.
     A 429 keeps 288/289's cards; an unnamed 403 keeps "The site blocks or challenges automated visitors".
     (3) *Link data.* Firecrawl's `rawHtml` already holds every anchor of the rendered page, and the reader already parsed
     them (`outlinks`), so no other format is requested. What was missing: the page grouping (link score, click depth,
     importance) ran on the reader's pages only when the crawl counted as blocked. It now also runs, on one link graph with
     Maya's own pages, whenever some page was read only through the reader (Maya never asked for it, or got a block page);
     `crawl.reader_page_grouping` keeps it. *airastana's saved audit keeps no links* (neither the report nor the evidence
     copies hold the reader's outlinks), so its copy still says "not computed (read only through the page reader)"; a new
     audit computes them.
     (4) *Titles.* The team report's PDF stopped on any slot that overflowed its box. Every title slot (priorities,
     findings, action plan, to-do cards, "Teyit edin") now has `data-fit` (its smallest size): a fit step before the overflow
     check makes the letters smaller until the title fits its box; only a title that does not fit at that size is cut at
     a word with "…" (the whole title stays in the element's `title` and the XLSX), listed as "KISALTILDI", never a stop. A
     170-character title on every slot: card titles shrink to two full lines, the one-line table rows are cut. nihan's
     English PDF at HEAD prints (its card titles are short since 316's wording); it no longer depends on that.
     *Before / after on the three saved audits (current-engine copies in a scratch folder, offline):* airastana's ACC-9 note
     "Imperva challenged Maya's direct crawler … Genuine AI-crawler access was not measured." (Info) → the S3 card above
     (recorded issues 6 → 7; in "Teyit edin" without the confidence rule); the page-limit line added; the other cards, tiles
     and key pages unchanged. moodist and nihan: no block answers, no change to cards, tiles or key pages. All six PDFs (TR
     and EN) print.
     Tests: `tests/test_blocked_reader_317.py` (fake sites for the five services, a made-up Firecrawl, hand-made reports,
     and the long-title render in TR and EN); tests that pinned a named service's challenge as a note follow the new rule.

318. **A consistent 429 block is measured and a card, as ACC-9's bot-protection finding (Owner, 2026-11-06, follow-up to
     317; checked offline on nihan's three saved 429 audits 0dc805b9, 50473193, 8b872028. The rule's thresholds are agent
     defaults: LG-104).** 317 gave `acc9.bot_protection` the measured confidence of its classification; the 429 cards
     (288, 289) kept Inferred, which sends them to "Teyit edin". Now `checks.access.consistent_429`: when the 429s on Maya's
     page requests are widespread (the homepage, or the degraded share of pages, 20%) and repeated (2+ page requests, or
     the homepage again after waiting the Retry-After), `acc9.blocked_429` and `acc9.rate_limited_429` are Verified (a
     429 is an HTTP status) and so a card; when Firecrawl read the site they stay the site's finding, as 317's does. A
     single 429 (one later page, even asked again) or occasional ones keep Inferred, and a read site still shows them as
     the reader's note. A saved audit's current-engine copy applies the same rule from the finding's evidence and the
     start page's record (`reassess_rules._decisions_318`). nihan (Cloudflare, its one page request 429 twice while
     robots.txt and 26 sitemaps were served): "Teyit edin" -> card, PDFs TR and EN print (6 pages each).
     Tests: `tests/test_blocked_reader_317.py` (4 more).
319. **The client brief ("Müşteri özeti"): at most 5 pages for a business owner, Turkish and English (Owner, 2026-11-06:
     the pages, their content, the gate and the TR/EN download as asked; the wording, the layout, which problems count as
     "measured", the "already good" list, the plan's buckets and the term list are agent defaults).** Global for every
     audit; nihan b3198942, moodisthastanesi c581ff0a and airastana d12146fb were the test cases.
     (1) *One source.* `maya_audit_web/team_report/brief.py` builds the brief from the team report's data
     (`build_data.build_from_files`: the current-engine copy, `client_selection`, `artifacts/review.json`, the business
     type) and prints it in the same design family (the team report's fonts, colours, header, tabs and cards, landscape).
     `build_from_files` now also keeps each card's place in the selection (`_cards`: merge group, confidence class,
     placement, issue type, template line) and the findings waiting in "Teyit edin" (`_confirm_ids`); each key page row
     carries its page type's id (`kind_id`). report.json is unchanged: no schema bump.
     (2) *Pages.* 1 "Sitenizin durumu": a one-sentence verdict by the worst severity among the brief's problems, site
     health in plain words (pages read, the severity band, how many problems the brief covers; no score and no "pages
     with problems" count, which read as a contradiction beside a 494-page card), the first three problems, and up to
     three things that already work. 2 "En önemli sayfalarınız": the team report's key pages (at most 8: one row per page
     type first, so moodist's doctors' page is not pushed out by treatment pages), each with its business-type page
     type, one line on why it matters for customers, Google and AI assistants (a line per page type of every profile and
     Stage 3's types), and its state in brief problem numbers ("1 ve 5. sorun", "Problems 1 and 5"); a problem of the
     whole site (certificate, robots.txt, bot protection, sitemap: `SITE_RULES`) is said once under the table, not on
     each row. 3-4 "Önce düzeltilmesi gerekenler": at most 5 problems, 3 per page. 5 "Sonraki adımlar": 30/60/90 days, one
     line on what the audit could not check (speed: no lab or field data; Search Console: no IDX-9 data), and a pointer
     to the team report and its Excel appendix. Four pages when there are 3 problems or fewer.
     (3) *Which problems.* The team report's problem cards in its order, only of type "Sorun" (never "Kontrol edin" or
     "Fırsat", DECISIONS 315), severity S1-S4 (never a note), confidence class measured or estimated (agent default:
     an estimate is measured, its extent estimated; said as "Ölçüldü; kapsamı tahmini"), or confirmed by hand ("Ölçüldü
     ve elle teyit edildi"), and none of its findings waiting in "Teyit edin". Each says what is wrong and why it matters
     for the business (customers, sales, AI answers) in the brief's words, an example address from the site and the
     card's total, who fixes it (Geliştirici / İçerik ekibi; the catalogue's "SEO" owner is the developer), the effort,
     and, when one template holds most of its pages, "Tek düzeltme yeter" with the page count. The plan: S1/S2, "this
     week" and small "this month" cards in 30 days, other "this month" cards in 60, "later" in 90; the first problem always
     starts in the first 30 days; 90 ends with "the other fixes in the team report" (when the team report has more cards)
     and a re-audit.
     (4) *Words.* `texts/brief-tr.json`, `texts/brief-en.json`: words for every rule family (rule id prefix), the rules
     that need their own (specific high-impact ones), every merge group and the redirect chain, every page type, the
     "already good" checks, the verdicts and the labels. No digits, IDs, rule names or vendor names in them; a test keeps
     every rule the engine can name resolved to words. "Already good": a check that passed with no finding at all and no
     finding of a check that would contradict it (ACC-2 "AI assistants may read the site" is not said when ACC-9 found a
     block), plus "every top page type of your business type was found" when nothing was "not found"; at most 3.
     (5) *The gate* (`brief.check`, on the brief's strings and on the printed PDF's text): blocked, with the reason in
     plain words, when the brief has more than 5 pages; a finding ID, a check or gate name (ACC-9, RG-15) or a rule id;
     an item that is not measured or confirmed or that waits in "Teyit edin"; a tool, provider or platform name (Firecrawl,
     DataForSEO, Lighthouse, Shopify, WordPress, crawler user agents ...) or a protection service other than the one a
     problem in the brief names from its evidence (airastana: "Sitenizin Imperva adlı koruma hizmeti ..."); a technical
     term (robots.txt, HTML, TLS, structured data, sitemap, noindex, hreflang, canonical, meta description, JavaScript,
     parameter, redirect, alt text, llms.txt, template, Search Console, http/https) without its short explanation in the
     brief. Before any of that: `client_selection.client_brief_allowed` false (low coverage, DECISIONS 309) blocks it
     ("Bu denetimde çok az sayfa okundu (4 sayfa); müşteri özeti sitenin tamamı için konuşamaz ..."), and a team report
     that cannot be published (validator errors or a BLOCKED release gate) blocks the brief too.
     (6) *Web app.* "Müşteri özeti — Yakında" is now "Müşteri özeti (PDF)" in the Downloads card, under the same TR/EN
     switch: GET `/audits/{id}/client-brief?lang=` builds it and returns an ordinary link (`…-musteri-ozeti-tr.pdf`,
     `…-client-brief-en.pdf`); GET `/downloads/brief?lang=` builds and serves it; blocked -> HTTP 422
     `client_brief_blocked` with `reasons`, shown under the button. (7) *Skill.* `maya-audit-pro`'s
     `scripts/brief.py` (a thin entry like the others) runs the same module: `--lang tr|en --pdf … [--html] [--png]
     [--review]`; SKILL.md has the option. (8) *Also fixed (global):* when the key pages come from the page reader's
     addresses (DECISIONS 316), a page type they were given is no longer listed as "not found" (airastana: "Destinasyonlar
     ve uçuş rotaları" and "Uçuş arama" were both in the table and in the not-found list; now only "Bilet fiyatları ve
     kampanyalar"), in the team report too.
     Results offline (current-engine copies in a scratch folder, provider-free): all six briefs 5 pages, nothing blocked:
     nihan 5 problems (page code weight, language versions, links to duplicate addresses, heading order, shared titles),
     verdict S3; moodist 5 (redirect chain High, tracking parameters, duplicate-address links, heading order, brand name),
     verdict S2; airastana 4 (certificate, Imperva block page, heading order, broken markup), verdict S3.
     Tests: `tests/test_client_brief_319.py` (library, selection, plan, key pages, gate, low coverage, routes; one slow
     through the real routes in both languages); `test_team_report` follows the Downloads card.

320. **No card content ever blocks printing; the brief's "SEO" owner; a 429 block names its service and what loaded (Owner,
     2026-11-07: the three fixes as asked; the shrink floor (80%), the line floor (6.8 pt), the order lines give way and
     the words are agent defaults).** Global for every audit; nihan b3198942 (EN team report blocked: card 02's
     confirmation note was its fifth line under the status, "kutu/kart: todos[1].title") and nihan 0dc805b9 (429) were
     the test cases.
     (1) *Cards fit, never block.* A line under a card's status (the owner's confirmation note, a member, the template,
     language and sitemap lines) and the evidence/target line now wrap to two lines and shrink like a title (`data-fit`,
     floor `render.LINE_FIT` 6.8 pt; only a line that does not fit two lines even then is cut at a word, whole text in its
     `title`). Then `render.CARD_FIT_JS` runs on every fixed-height box (to-do cards, every summary card, the brief's
     cards, the priority lines): a box still too tall, or holding a part too tall for its own box, first shrinks its parts
     below the title row together (CSS zoom, down to 80%, every line kept); still too tall, the least important lines go,
     last first, each counted: lines under the status fold into "+N more" (the confirmation note last: the card carries
     it as `todos[].sub_keep`), then link rows and links, then the last steps (one stays), then list and table rows.
     A card that lost a line is listed in `shortened` ("kart: todos[i]…"); the XLSX appendix keeps everything. The
     overflow check is unchanged and still runs after the fitter. nihan EN/TR: card 02 shrinks, nothing cut, PDFs print.
     (2) *Brief owner.* The catalogue's "SEO" owner is "SEO / pazarlama ekibi" / "SEO / marketing team" in the brief
     (was "Geliştirici"/"Developer", DECISIONS 319 (3)); moodist's brief shows it, still 5 pages.
     (3) *429 words.* The team card of `acc9.blocked_429` / `acc9.rate_limited_429` gets a first line naming the service
     from the evidence (`blocked_by`, else "the site's firewall") and saying what was refused and what loaded: "Cloudflare
     refused 1 of 1 page request with 429 (too many requests); robots.txt, 26 sitemap files and llms.txt loaded." What
     loaded is read from the crawl's request log (`maya_blocked.served_files`: 200 on the start page's host, "www."
     aside), so saved audits say it too; nothing loaded and robots.txt/sitemap refused (evidence) says that instead. The
     brief's words for both rules name the service ("Sitenizin Cloudflare adlı koruma hizmeti …", as the Imperva words)
     and, when they loaded, the robots file and the sitemap with their explanations; the gate still passes. report.json is
     unchanged: no schema bump.
     Tests: `tests/test_card_fit_320.py` (a long note on every card type and issue type in TR and EN, an overfull card,
     owner words, served files, the 429 card and brief lines with and without a service and files).

321. **Fixes from reviewing the client briefs (Owner, 2026-11-07: the five fixes and the certificate bands as asked; the
     words, the "Developer + second owner" form, the coverage reasons and their order, and the sheet notes are agent
     defaults).** Global for every audit; airastana d12146fb, moodisthastanesi c581ff0a and nihan b3198942 were the test
     cases.
     (1) *Certificate expiry.* Severity by the days left at the audit (`checks.index.expiry_severity`): under 7 days
     Blocker, under 14 High, under 30 Medium; the warning window is now 30 days (`tls_expiry_warning_days`, was 14;
     strictly under: moodist's certificate at exactly 30.0 days is not a finding). A saved audit gets the same from its
     evidence (`reassess_rules._decisions_321`, also in `saved_data`, so a report of the current schema written before
     it is re-rated too): an expiry finding re-rated (its "how to verify" says the 30-day window), and a certificate the
     saved IDX-2 evidence shows inside the new window gets the finding this engine would write (same title and id). A
     certificate raised to High or Blocker carries `not_retested` ("no re-test for this rule"), as the engine's
     verification stage writes it, so RG-5 holds. The expiry date and the days left, counted from the audit's date to the
     expiry's date, are on the card's first line ("Expires 14 November 2026; 9 days left at the audit (5 November
     2026)."), in the evidence table (host, expiry date, days left, issuer; a certificate that is not valid: host and
     problem; never an empty table, never "/" for each host), in the brief's problem ("… expires on 14 November 2026;
     9 days were left when we ran our audit.") and in the web results (`certificate_line`). The brief's verdict and
     health line speak for the worst of its problems, every team-report card of High or Blocker (one the brief leaves
     out too) and a certificate under 14 days (`brief.worst_severity`); the High health line no longer says "nothing is
     urgent", so that sentence appears only when nothing is High or Blocker. airastana: 9.1 days, S3 -> High.
     (2) *Host-level findings* (`client_selection.host_level`: IDX-2, the robots.txt checks ACC-1/2/6/7, llms.txt ACC-8,
     and IDX-5 when every address is a sitemap or robots file): the card names the hosts ("Hosts: airastana.com,
     www.airastana.com"; `hosts_line`, also in the web results) instead of "addresses not read … add nothing to the
     priority score"; a certificate or https card counts hosts ("2 hosts"); the evidence table shows host names.
     (3) *Brief coverage line.* When fewer pages were read than planned (`max_pages`), page 1's first health line says how
     many and why, in place of "We checked N pages" (`brief.coverage_line`): the site's protection service (an ACC-9 block
     or rate-limit finding, or a rate-limit stop), the time limit, a site smaller than the plan (the crawl ran out of
     addresses), or some addresses that could not be read. airastana: "The site's protection service slowed our reading,
     so this brief is based on 13 pages (we planned 50)."
     (4) *Owner of merged cards* (`card_owner`): the owner of the most technical part (Developer, then SEO, then
     Content) and, when the parts need two, the next one: moodist's canonical + redirect chain card "Developer + SEO"
     (brief "Developer + SEO / marketing team"), nihan's language card "Developer + Content"; a card whose parts share
     one owner keeps it. The effort stays the lead's. Same on the to-do cards and the action plan; a test runs every merge
     group and the redirect chain with mixed owners.
     (5) *XLSX.* A sheet with no rows has one line saying why (findings, addresses, templates, coverage; key pages as
     before). Templates: no page scored (the key pages' reasons), the pages with an address pattern were all not read
     (`templates_reason` "not_read": airastana, Imperva answered Maya's 50 requests and the 13 pages read another way
     are not grouped), or no shared pattern. RG-17 ignores the note line. "Importance not computed" says why in plain
     words ("our crawler was blocked, the page was read another way and which pages link to it is not known"), in the
     XLSX and the team report's key pages.
     report.json's shape is unchanged (evidence is outside the frozen schema): no schema bump.
     Results offline (scratch copies, provider-free): all six team reports print, all six briefs 5 pages, not blocked;
     airastana certificate High with its date in card, table and brief, coverage line on p1; moodist card 1 "Developer
     + SEO"; airastana Templates sheet explains why it is empty.
     Tests: `tests/test_brief_review_321.py`; `test_idx_scenarios` (7-day certificate: High).
322. **The XLSX appendix for teammates who are not technical; "Etkilenen sayfalar" on the web cards; inclusive
     certificate bands and plain host names (Owner, 2026-11-07: items 1-7 as asked; the sheet order, the columns past
     the ones named, the measured-value words, what counts as a "problem" on a page and the dialog are agent
     defaults).** Global for every audit; nihan b3198942, moodisthastanesi c581ff0a and airastana d12146fb were the test
     cases.
     (1) *Four sheets first.* The appendix opens with "Nasıl okunur" / "How to read" (six lines: what each sheet is, how
     to filter, what importance and "Bilgi" mean; no frozen row, no filter), "Özet" / "Summary", "Sayfa bazında" / "By
     page", "Bulgu bazında" / "By finding"; the technical sheets (Bulgular, Etkilenen adresler, Kilit sayfalar,
     Şablonlar, Kapsam, Yöntem) follow unchanged. RG-17 reads the technical findings sheet by its name
     (`client_appendix.finding_ids`), so the gate is the same.
     (2) *One source for the rows* (`maya_audit/page_rows.py`): `finding_rows` is one row per finding and affected
     address (a finding with no address: one "site geneli" row), every finding except Maya's own limits and rejected
     ones; the problem name and fix are the text library's plain words (`texts.rule`: "finding", "summary",
     "explanation"; `render.plain_words`), else the engine's worded title and fix. Order: the PDF's cards in their order,
     then severity, then the more important page. `page_table` is one row per page with a Blocker-to-Low problem: page
     type, importance, the number of problems (root-cause groups, so three HTML-weight rules on one page are one),
     the worst severity and the groups' short names ("summary"); hosts, "site geneli" rows and Info notes are not page
     problems and stay in "Bulgu bazında". Sorted by importance (a page not scored last, its importance cell empty and
     explained in "Nasıl okunur", never 0), then severity.
     (3) *Measured value* (`page_rows.measured`): read from that finding's evidence for that address only: a record with
     the address (`url`, `source`, `sitemap`), a group listing it (shared description/title, copy groups), a redirect
     target linked from it, the IDX-2 certificate of that host (expiry date, days left); TSEO-1 decomposed letters are
     read from the address itself with the engine's `composed()`. Known keys become plain words (HTML size and its
     limit, heading jumps, declared vs content language and share, words, characters, first response, links,
     products, parameters, hreflang target and status, alt text, tag IDs, expected/found schema types, header values).
     A page in the evidence's plain list says "bu sayfada görüldü (bkz. Sorun)"; a page outside the evidence's sample
     says "ayrıntı kaydedilmedi (rapor yalnız örnek sayfaları saklar)" — never empty, zero or made up. Unknown keys are
     left out.
     (4) *"Özet"* has the team report's cards (`todos`: number, title, severity, issue type, owner, effort, affected
     addresses) with "Satırlara git →", a link to the card's first row in "Bulgu bazında"; rows carry the PDF card
     number in "Kart". The skill passes its data.json's todos (`render.write_appendix`); the web app builds the team
     report data once per saved state (`team_data`, cached like the overview) and passes the same todos
     (`appendix_xlsx`), falling back to the selection's cards (titles worded) if the build fails. A note card that
     names checks ("STR-2 · STR-9") is about their observations, not findings: no finding row takes its number and it
     has no link; its count is the card's own addresses.
     (5) *File.* `maya_audit/xlsx.py`: header row bold on grey, frozen, with filter buttons; every text cell wrapped and
     top-aligned; addresses are hyperlinks (external relationships, `TargetMode="External"`; only http(s), at most 2,000
     characters, at most 65,000 per sheet, else plain text); "Satırlara git" is an in-file link (`location`); column
     widths per sheet; `xlsx.links()` reads them back for tests. Headers in the file's language (TR file Turkish, EN
     file English). Checked: every XML part parses, element order per the schema; not opened in Excel or Google Sheets
     on this machine (neither is installed) — NOT RUN.
     (6) *Web.* Each problem card under "Neyi düzeltmeli" has "Etkilenen sayfalar (N)" when N > 0 (`overview` fixes carry
     `pages`); it opens a dialog with the full list (`GET /audits/{id}/cards/{n}/pages?lang=`: address, page type,
     importance, measured value, finding IDs; the rows of "Bulgu bazında" for that card, one per address), a search box
     (address, type, value, ID; first 500 drawn, the count says how many match) and "CSV indir" made in the browser
     (UTF-8 with BOM; ";" in Turkish, "," in English, DECISIONS 283 (6)). Unknown card: 404 `card_not_found`.
     (7) *Certificate.* The bands are inclusive: 30 days or fewer Medium (the warning window, `<=`), 14 or fewer High, 7
     or fewer Blocker (`checks.index`, `reassess_rules._decisions_321`, the brief's `worst_severity` through
     `expiry_severity`). moodist's certificate at exactly 30.0 days is now a Medium card (card 3; was no finding under
     321). Certificate hosts are plain host names everywhere they were addresses: the new sheets and the web list
     (`page_rows.display_address`, still linking to the host's root) and the technical "Etkilenen adresler" sheet; the
     PDF card, evidence table, brief and Markdown already named hosts.
     report.json's shape is unchanged: no schema bump (`select()` gains an internal `_importance`, appendix rows carry
     their finding).
     Results offline (scratch copies, provider-free, no provider ledger): team reports TR/EN print (nihan 9 pages / 13
     cards, moodist 8 / 10, airastana 6 / 6; gate PASS), briefs 5 pages; appendices 10 sheets, RG-17 ok. nihan TR:
     Özet 13 cards, Sayfa bazında 2,119 addresses (pages read and addresses known but not read, such as the decomposed-letter ones), Bulgu bazında
     4,902 rows; moodist 52 / 705; airastana EN 35 / 86.
     Tests: `tests/test_xlsx_pages_322.py`; `test_brief_review_321` bands (7 Blocker, 14 High, 30 a finding),
     `test_idx_scenarios` (7-day certificate: Blocker), sheet lists in `test_v03_client_report`/`test_v03_report_fixes`,
     `test_team_report` (web and skill appendix with the same todos).
323. **"Okundu mu?" in the appendix's page sheets, and a measured value for every page read; schema 1.29 (Owner,
     2026-11-08: items 1-2 as asked; the record's fields, the value per kind of finding, the order inside a card and the
     wording are agent defaults).** Global for every audit; nihan b3198942, moodisthastanesi c581ff0a and airastana
     d12146fb were the test cases.
     (1) *Read or not.* "Sayfa bazında" and "Bulgu bazında" have "Okundu mu?" / "Read?" after the address: "Evet" /
     "Yes" for a page whose content was read (`client_selection.read_set`: Maya's 2xx pages with content, the page
     reader's pages read, and every page with a stored measurement), "Hayır, okunmadı" / "No, not read" for an address
     known but not read, "—" for a host's file or the whole site. "Sayfa bazında": the pages read first (importance,
     then severity), the addresses never read after them as one group. "Bulgu bazında": the same inside each card (and
     among the rows of no card), so a card's rows stay together and "Satırlara git" still lands on its first row. The
     web list ("Etkilenen sayfalar") has the same column and order, and its CSV the column. "Nasıl okunur" has a
     seventh line saying this.
     (2) *A value for every page read* (`maya_audit/page_measures.py`). One compact record per page read: status, HTML
     size, where the main content starts, first response, cache header, title and description (text and length),
     canonical, h1 count, skipped heading levels (with examples), `<html lang>` and hreflang count, words, main content
     size, images and those without alt, blocking scripts in the head, tag IDs, structured data types, links without
     an address or used as buttons. Only what was measured; nothing is written as 0 when it was not measured.
     New audits: `crawl.page_measures` ({url: record}), written in `final.settle` for Maya's pages and in
     `firecrawl.reader.apply` for the reader's pages (a page both read keeps Maya's). *Schema 1.29* because it is a new
     field of the report's frozen `crawl` shape; it is needed because the checks' evidence keeps a sample of pages
     (often 40) and a page read only through a page reader keeps no record in the report at all, so its values would
     otherwise be lost when the audit ends. Older reports: the same records are worked out from the saved
     `crawl.pages[].analysis` (`page_measures.index`, offline).
     The appendix's value (`page_rows.measured`): the finding's own evidence for that page first (it holds what only
     the check works out, e.g. a language share), then the page record's values for that kind of finding
     (`page_rows.from_page`: RND-6 size or content start with the limit; heading rules the skipped levels; title and
     description rules; STR-2 h1 count; STR-9/12 language; STR-15, RND-3/7 words; STR-7 images; STR-3/6/10 structured
     data; IDX-3/4/6/8 canonical and status; PRF-1 first response and cache; link rules), else the page's status and
     size. An address not read says "okunmadı: bu adresin içeriği ölçülmedi"; "ayrıntı kaydedilmedi" is left only for a
     page read whose values cannot be worked out from the saved data (in old reports: pages read only through the page
     reader, and non-HTML files such as agents.md).
     Results ("Bulgu bazında", TR, scratch copies, provider-free): "ayrıntı kaydedilmedi" nihan 1,877 -> 10 (every one a
     page read only through Firecrawl or a text file), moodist 272 -> 0, airastana 15 -> 11 (pages read only through
     Firecrawl); "okunmadı" rows 103 / 2 / 4. nihan "Sayfa bazında": 498 pages read first, then 1,621 addresses not
     read. Team reports and briefs unchanged (nihan 9, moodist 8, airastana 6 pages; briefs 5). A provider-free CLI run
     on a local static site writes schema 1.29 with a record for each page read.
     Tests: `tests/test_page_values_323.py`; `tests/test_xlsx_pages_322.py` (the new column, seven lines, a page's own
     value in place of "not kept").
324. **The team's sector audit method in Maya Audit: homepage weights by rank, P0-P3 on the cards, the "Sektör audit"
     XLSX, the measured value of a finding with no value of its own (Owner, 2026-11-08: the Step 1 proposal approved
     with answers 1-4 and the scope; the rules below the owner did not name are agent defaults).** Source:
     `docs/business-types/Sektor_Bazli_SEO_Audit_Onceligi.xlsm` (İlginay, from Efsa's sector list; read with openpyxl
     only, data only; it holds no macro). Global for every audit; nihan b3198942, moodisthastanesi c581ff0a and
     airastana d12146fb were the test cases.
     (1) *Homepage weight (owner).* A homepage the sector list ranks takes its rank's weight, as the team's sheet:
     E-ticaret 70, Sağlık 55, Ev hizmetleri 55, and Restoran 55 (4th in the owner's own list); the 85 floor
     (`HOME_MIN`) is removed. A homepage added where the list has none stays 85 (`ADDED_HOME`). The importance mix
     (50% type, 35% links, 15% depth) is unchanged. `seyahat` is "Seyahat / rezervasyon (tur, otel)" / "Travel /
     booking (tours, hotels)" (id kept). `docs/business-types/signals.md` regenerated.
     (2) *P0-P3 (owner: impact from severity, effort a neutral 3, the team's thresholds, order unchanged).* New
     `maya_audit/priority_levels.py`, called by `client_selection.select` after placement: per finding of a card,
     20 × impact (Blocker 5, High 4, Medium 3, Low 2, Info 0) × page weight × spread × status factor / 3; the card takes
     its highest; P0 at 160+, P1 80+, P2 30+, P3 above 0, none at 0. Agent defaults: page weight = the profile's weight
     of the page's type / 100 ("Diğer": Stage 3's type weight); spread = the method's 1-5 scale over the pages read of
     that type (one page of several 1, a homepage 5: it is its own template); a finding with no address, a host-level
     one or one about site files only (robots.txt, sitemaps) is site-wide (weight 1, spread 5); addresses none of them
     read weigh 0.25 (spread 1 or 2); a page read with no grouping record is "other"; status factor 1 for an
     issue-type Blocker/High/Medium, else 0.5 (the method's Hatalı / Kısmen Uygun). A Low card can never be above P2.
     It never changes a severity, confidence, placement, card order, priority score or the quick wins
     (`test_p_levels_never_change_order_severity_or_score`).
     (3) *Automatic P0 (owner: yes, with the homepage).* An indexing blocker (`acc2.blocks`, `acc3.noindex`,
     `acc3.robots_noindex`, `idx1.5xx`, `idx1.empty`, `idx4.other_site/broken/different/redirect_loop`,
     `rnd1.missing`) on a homepage, or on 31%+ (spread 4) of the profile's rank 1-2 page types, or robots.txt
     blocking the whole site, is P0 whatever it scores, with the reason ("otomatik: indeksleme engeli (ana sayfa)").
     Not for a card waiting in "Teyit edin", and not for ACC-9 (Maya's crawler blocked says nothing of Google). A
     person's marks: review.json `p0` entries (`set` / `removed`, by, date, note; `manual_review.record_p0/undo_p0`;
     `confirmations()` gives them as `p0:<finding id>`); "removed" caps an automatic P0 at P1. Web: a "Kartların P0-P3
     önceliği" block in "Önce bunları kontrol edin" (each card's level and reason, "P0 yap" / "P0'ı kaldır" / "Geri
     al"), `POST /audits/{id}/review/p0`, `DELETE /audits/{id}/review/p0/{finding_id}`.
     (4) *Where it shows.* Team report cards and web cards: a chip beside the issue type (the web card says why it is P0
     and the score in its tooltip); XLSX appendix: "Öncelik (P0-P3)" in "Özet" and "Bulgular", an eighth "Nasıl okunur"
     line and a "Yöntem" row. Client brief: plain words only, P0 "Acil", P1 "Öncelikli", P2 "Planlı", P3 "Sırası
     gelince" (EN Urgent, Priority, Planned, When convenient), as a second chip beside the severity; a P0-P3 code in a
     brief is blocked by the gate (`ID_PATTERNS`). So that "Acil" means P0 only, the brief's Blocker word is now "Çok
     yüksek önem" / "Very high importance" (and its health lines say so).
     (5) *"Sektör audit" XLSX* (`GET /audits/{id}/downloads/sector`, `…-sektor-audit.xlsx`, Turkish; a card in
     Downloads; gated like the appendix). `maya_audit/sector_method.json` holds the team's rows and texts (44 CORE,
     174 SEC, 58 page types, the methodology) with Maya's mapping per check (A/K/G/P/M, rules, the report checks needed,
     covered, missing), built by `tools/sector_method_build.py` (openpyxl, not a dependency; the product reads only the
     JSON). `maya_audit/sector_audit.py` writes the five sheets with the team's columns, formulas (score, P level,
     VLOOKUP of the rank weight, COUNTIF(S) of "Audit Özeti", ranges widened to the draft rows) and dropdowns (Durum,
     1-5), plus four columns of Maya's ("Maya: Durum nedeni", "Maya kapsamı", "Maya kuralları", "Not"). The stdlib
     writer gains formula cells with their computed value, list validations and `fullCalcOnLoad`. Durum: Hatalı for an
     issue-type Blocker/High/Medium of the check's rules (on that page type for a sector row), Kısmen Uygun for Low or
     warning/opportunity ones, Uygun only for an automatic check that ran with no finding on an audit that is not
     low-coverage (a sector row also needs a page of its type read), Uygulanamaz when the needed checks were not
     applicable, else Kontrol Edilmedi with the reason; a finding waiting in "Teyit edin" leaves the row unchecked and
     says so; rejected findings, Maya's own limits and Info notes never count. Spread, effort (S 1, M 3, L 4), example
     (the most important page), evidence (finding names, pages, one measured value), action (Maya's fix, else the
     team's) and owner are filled; the team's formulas include effort (only Maya's card labels hold it at 3). Draft
     rows for Havayolu (6 types) and Restoran / kafe (5 types), 33 rows, IDs `SEC-T01`..., marked "taslak —
     İlginay/Efsa onayı bekliyor"; an airline audit fills them.
     (6) *"Ölçülen değer"* (`page_rows`): the generic fallback (the page's status and HTML size) is gone. A finding with
     no value of its kind shows the field it is about (`about`: no breadcrumb / category link for IDX-7, the blocked
     bots of ACC-6, browser vs Googlebot status of ACC-4, the field and its two values of STR-11, the brand names of
     STR-5), else "—"; IDX-1 keeps its status (that is its field).
     (7) *Left for Stage 7* (BACKLOG): the 7 checks missing but automatable (CORE-011, SEC-001, -013, -052, -097, -163,
     -172). Schema: no bump (nothing new in report.json; the P level and the workbook are worked out at selection
     time). Tests: `tests/test_sector_method_324.py` (20).
325. **"Sektör audit" XLSX precision pass: a finding answers only the check it answers; Durum by confirmed severity;
     host names; what an "Uygun" row checked; a level on every card (Owner, 2026-11-08: items 1-5 as asked; the rule
     lists, the "future problem" rule and the wording are agent defaults).** Global; nihan b3198942, moodisthastanesi
     c581ff0a and airastana d12146fb were the test cases.
     (1) *Mapping* (`tools/sector_method_build.py`, `maya_audit/sector_method.json`). A rule id matches itself and its
     sub-ids only (`acc2.blocks` -> `acc2.blocks.sample`; no longer `acc3.noindex` -> `acc3.noindex_utility`); a check id
     only where every rule of the check answers the row; every rule id is in at most one common row
     (`test_each_rule_marks_at_most_one_common_row`). Changed: CORE-001 ACC-2 -> its four robots rules; CORE-002 without
     `acc3.noindex_listed` (to CORE-004); CORE-003 IDX-9 -> its four state rules (`idx9.canonical` stays CORE-006);
     CORE-004 + `acc3.noindex_listed`, `acc3.unavailable_*`, without `acc3.sitemap_noindex` (CORE-002); CORE-005 IDX-1
     -> status/soft 404/empty rules, without `idx1.4xx.referenced` (CORE-022); CORE-006 + `idx6.alias_links`; CORE-007
     without `idx4.chain` (a canonical chain, CORE-006); CORE-008 IDX-2 -> `idx2.no_redirect`, `idx2.temporary` (the
     certificate is CORE-041 only); CORE-009 + RND-4; CORE-010 without `idx5.sitemap` (CORE-002) and `idx7.orphan`
     (CORE-018); CORE-011 without IDX-8 (CORE-030); CORE-012 STR-9 -> the hreflang rules only (`str9.lang_mismatch`,
     `no_lang`, `bad_lang` are CORE-027); CORE-015 without RND-4; CORE-016 STR-7 -> size, format, preload rules (alt text
     is CORE-026, incl. `shared.image_no_alt`); CORE-019 without `str3.crumb_no_list` (CORE-034, with `str3.url_differs`);
     CORE-021 RND-3 -> STR-19 (RND-3 is CORE-009); CORE-024 + the TSEO-1/shared heading-jump ids; CORE-031 without
     `idx5.stamped` (a sitemap date, CORE-002); CORE-032 without STR-21; CORE-035 without STR-4; CORE-037 STR-4/STR-11 ->
     `str4.differs/not_shown/other_state` (STR-11 is CORE-034); CORE-038 without STR-5 (the brand's naming is CORE-036);
     CORE-040 STR-21/STR-8 -> `str8.pricing`, `str4.price_unclear`; CORE-044 without ACC-9 (Maya's crawler blocked says
     nothing of Google); sector rows SEC-010/043/070/091/118/139 and the draft branch/contact rows without STR-5 (not
     an address or contact detail); the generic "İndeksleme & İç Link" row without the duplicate `idx1.4xx`. Inside one
     page type a finding marks one sector row: the first of the type's rows that names its rule (the specific row before
     the two generic ones). The common (whole-site) row and the page type's row stay separate layers, as in the team's
     method.
     (2) *Durum.* Only a measured finding (engine `verified`) or one a person confirmed (review.json) sets a Durum;
     estimated, inferred or unverified ones, and anything waiting in "Teyit edin", leave the row "Kontrol Edilmedi"
     with "Tahmini bulgu, teyit edilmedi: …" / "Teyit bekliyor: …". "Hatalı" = an issue-type Blocker/High/Medium; a
     problem that has not happened yet (`idx2.expires`, a valid certificate) is "Hatalı" only at High or Blocker
     (14 days or fewer), else "Kısmen Uygun".
     (3) *Units.* A host-level finding (certificate, host redirects, robots.txt, sitemaps: `host_level` or ACC-1/ACC-2/
     IDX-2/IDX-5) counts its host names, read or not ("TLS sertifikasını yenileyin (2 alan adı)"), and is site-wide
     (spread 5).
     (4) *"Uygun".* "Bulgu / Kanıt" says what was checked and on how many: "Bulgu yok: 501 sayfada meta robots ve
     X-Robots-Tag kontrol edildi.", "… 1 alan adında robots.txt erişimi ve kuralları …", "… «Kategori ve listeleme»
     türünden 101 sayfada …" (a `checked` phrase and unit per row that can be "Uygun").
     (5) *P levels.* Every problem card has one: pages that weigh 0 (search, cart) make it P3 (nihan card 11); Info
     groups have none.
     Results (current-engine copies, provider-free): nihan Uygun 12 -> 13, Kısmen 13 -> 12, Hatalı 2, Kontrol Edilmedi
     35 (3 rows changed); moodist 9 / 6 -> 4 / 5 -> 3 / 42 -> 46 (7 rows); airastana 8 / 2 -> 0 / 3 -> 1 / 49 -> 53
     (4 rows). Schema: no bump. Tests: `tests/test_sector_precision_325.py` (8).
326. **"Sektör audit" XLSX: Yaygınlık and Efor on every row (Owner, 2026-11-08: the rule as asked; the note's wording is an
     agent default).** Every row, "Uygun" and "Kontrol Edilmedi" included, has Yaygınlık (1-5) and Efor (1-5), so a
     teammate who changes Durum to Hatalı or Kısmen Uygun gets the team formula's score and P level at once. Yaygınlık:
     the measured spread when a finding gives one (also an estimated finding that sets no Durum), else 1. Efor: the
     largest catalogue default effort (`recommendation_catalog.note`, S 1, M 3, L 4) of the checks the row's rules
     belong to, else 3. An "Uygun" row now shows the team formula's own "0 / Yok". A last line on the Metodoloji sheet
     ("Ön doldurulan değerler (Maya)") says both are pre-filled and can be edited (below the VLOOKUP range A22:B27).
     Checked in Numbers (LibreOffice is not installed here) on the moodist workbook: CORE-001 Uygun -> Hatalı gave
     100 / P1; SEC-066 Uygun -> Hatalı gave 33,3 / P2 and the Audit Özeti row "Sağlık / klinikler" went Hatalı 1 -> 2,
     Uygun 2 -> 1. Schema: no bump. Tests: `tests/test_sector_prefill_326.py` (5).
327. **Akıllı ~150 (v0.3 Stage 5): a planned sample that covers every page type of the business type; Firecrawl only where
     needed in that mode; "Sektör seçilmedi" in the Sektör audit (Owner, 2026-11-08: the Step 1 proposal approved with
     answers 1-4; this updates DECISIONS 296 for the Akıllı mode only; the thresholds below the owner did not name are
     agent defaults).** New `maya_audit/sampling.py` (`Sampler`), CLI `--smart`, web mode `smart` (150 pages).
     (1) *Typing before reading.* When the first page is read (normally the homepage), every known address (the sitemap,
     that page's links with their menu texts, the key pages) is typed with the profile's own signals
     (`business_types.classify` on the address and the menu text): files (`.kml`, `.md`, `.xml`, `.pdf`, images) are
     left out; a long (5+ words) top-level slug whose only type word is in the slug is a blog post (the profile's citable
     type). A wider "folder word first" rule was tried and dropped (nihan fell from 496/498 to 24% agreement). The
     business type is the person's choice, else the one that homepage suggests. A site whose first page is blocked is
     planned from its sitemap alone.
     (2) *Budget (owner).* The homepage and its language versions (up to 4, all kept) and the key pages first; a reserve
     of 10 other pages, 3 policy pages and 2 search/cart pages; a page type with 30 known addresses or fewer is read in
     full, in rank order; a larger one gets at least 30, the rest by its rank weight (floors in rank order when the budget
     is short); budget still left fills in rank order. Inside a large type the team's split: a third importance
     (menu-linked, shallow), a third long tail (deep, not in the menu), a sixth newest by sitemap lastmod, a sixth
     exceptions (rare URL template, parameters), rotating over the URL templates (`page_groups.url_patterns`). The
     reading order rotates over the types in rank order, so a time cut still leaves every type read.
     (3) *Two waves (owner).* After 60% of the budget the pages read are typed with their content, every unread address
     of a URL template takes the template's type when 3 or more of its pages read agree (80%+), the addresses found
     meanwhile join the pool, and the rest of the budget is planned again (a type found empty gives its share back).
     (4) *Main language version (owner).* The folder the homepage redirects to is the main version (DECISIONS 316's
     `set_main_locale`, now also the plan's): another language's page is planned only when its type has none in the main
     version, or from budget left over.
     (5) *Crawl.* The frontier gets a `plan_rank` column (added to older crawl databases): in an Akıllı crawl the plan comes
     right after the start URL, key pages and redirects; every other crawl keeps its order. The resume binding leaves
     `sampling` out when it is off, so a crawl saved before this resumes. Progress events carry the pages read per type;
     the web progress box shows "Sayfa türüne göre örneklem: Tedavi ve bölüm 24/56 · Doktor ve ekip 3/4 …".
     (6) *Report (schema 1.30).* `crawl.sampling`: per type the addresses known (typed before reading, corrected after the
     first wave) and the pages planned, the waves, the re-typed count, the planned addresses. Coverage per type
     (`sampling.coverage`, pages read typed after reading from the page grouping) is a coverage line
     ("Akıllı örneklem, sayfa türleri: Tedavi ve bölüm: 30/56 okundu (örneklem) · Klinik ve konum: bulunamadı") in the
     team report's limits, the XLSX coverage sheet and, for a page type with no page read, the Sektör audit's reason.
     (7) *Firecrawl in Akıllı (owner; updates DECISIONS 296 for this mode).* Options `read_scope`: "needed" by default
     in Akıllı: the reader reads the pages Maya could not read (block page, 429, empty), every page of a URL template
     where a page Maya read shows the raw-HTML JavaScript signals (the RND-1 estimate's test; our own Chromium render
     keeps sampling those templates), and the first page of every other URL template as a cross-check (so a finding
     only the rendered copy shows, like a language mismatch, is still caught); what it decided is in the firecrawl
     section (`scope`). "Tam okuma (Firecrawl her sayfa)" on the plan (`firecrawl_full_read`) is `read_scope` "all",
     as Hızlı and Standart keep. A blocked site's reader reads the plan's addresses first, in its order.
     (8) *Modes (owner).* "Akıllı ~150 (önerilen)" is added; "Hızlı ön bakış · 50 sayfa" (renamed) stays the default
     until one live run confirms Akıllı under about 12 minutes; its default estimate is 10 minutes.
     (9) *Sektör audit (queued from Step 1).* With no business type ("Diğer"), Audit Özeti's empty row 4 and a last line
     of Metodoloji say "Sektör seçilmedi: sektörel satırlar için iş türünü seçin", and so does every sector row's reason.
     (10) *Dry runs on saved data* (`tools/sampling_dryrun.py`, no request): moodisthastanesi c581ff0a (Sağlık, main
     folder `tr`): 549 known pages; planned Tedavi ve bölüm 56/56, Doktor ve ekip 4/4, Klinik ve konum 2/2 (two
     psychologists' profiles typed by address; reading is expected to re-type them), Ana sayfa 4 of 6 versions, Randevu ve
     iletişim 3/3, Anlaşmalı kurumlar 1/1, blog 57/147, other 22/328, policy 1; fillable sector rows 9 -> 17 of 18. nihan
     b3198942 (E-ticaret): 8,059 known pages; Kategori 46/145, Ürün 39/7,844, Ana sayfa 2/2, Mağaza 3/3, Kampanya 2/2,
     Yardım ve güven 12/12, blog 33/33; 23 unread addresses re-typed after wave 1; fillable 13 -> 16 of 18.
     Not done: cutting the sitemap check (proposed in IMPLEMENTATION-STATUS, waiting for the owner). Tests:
     `tests/test_sampling_327.py` (19); schema pins 1.29 -> 1.30.
328. **The sitemap check starts right after the crawl, beside the other steps (Owner, 2026-11-08: the proposal of
     IMPLEMENTATION-STATUS "Akıllı ~150" as asked; where it is joined and the step-table row are agent defaults).**
     Every audit (all modes). The sitemap check (IDX-5's light requests to the sitemap URLs the crawl did not read,
     DECISIONS 206/294) runs on a thread of its own from the moment the crawl ends, beside access, index, structure and
     rendering, through the same shared site limit; the audit's own thread joins it before the performance rounds (their
     timings must not share the site with it), and llms.txt's links (ACC-8, which need the access data and the check's
     rows) run after the join on the audit's own thread, as before, now with their own error guard. Same requests, same
     rows, same findings; only the order of requests in the log and the wall time change. A rate limit met by the
     check widens the gap for the steps beside it too (it did for the steps after it before).
     *Step timing table:* new "lanes" in the fetcher (`set_lane`, `lanes`, `lane_row`): a thread on a lane (the check
     and the workers it starts) counts its requests, waiting and time-limit refusals on the lane, so the steps it runs
     beside keep their own counts and a refusal of the check never marks access/index/structure/render as cut. Its row
     ("sitemap_check") says `beside: [access, index, structure, render]`; a "sitemap_check_wait" row appears only when
     the audit's own thread had to wait for it.
     *Measured* (an in-memory site answering after 0.2 s, 30 sitemap URLs checked, the committed code in a scratch
     worktree against the new code): 5.7 s -> 3.7 s; the 30 rows and 14 findings identical; each step's request count
     unchanged. *Expected on the saved audits* (from their step timings, the overlap is at most the four steps it runs
     beside): moodist 200 s of 200 (they take 246 s) -> about 10.2 -> 6.9 min; airastana 43 s of 194 (no rendering on a
     blocked site); nihan Standard 500: 196 s of 806. *Fixed on the way:* a robots.txt sample (decision 12) took its send
     time from the log entry after it was asked, which the sitemap check's thread can now write; the next sample was then
     due too early (118.8 s apart in a full-suite run). It now reads its own record. Tests:
     `tests/test_sitemap_beside_328.py` (3); `test_preview16_measure` (the samples' test), `test_v03_speed` (in flight:
     within the site limit of 5, not 4), `test_time_limit` and `test_progress_stop_resume` (the phase order) follow.
329. **Fixes from the first live Akıllı runs: step times, Firecrawl only where needed (for real), profiles typed by their
     content, IDX-8's place-name groups on location pages only, High at least P2, a brief with measured problems only,
     sitemap entries for developer and content (Owner, 2026-11-09: items 1-7 as asked, worked from the saved reports
     moodisthastanesi 2d72fea0 and enpara 87f0425a with no new crawl; the person-profile test, the title words, the
     majority rule, the Blocker floor, the "already good" wording and the step labels are agent defaults).** Global for
     every audit; the two brands were the test cases.
     (1) *Time.* New `maya_audit/step_times.py`: the total (Maya's own wall time `crawl.elapsed_s` plus the time from the
     end of Maya's steps to the report, `generation.processed_at - native_finished_at`) and each step's seconds from the
     report's step timing table, the steps that run beside the audit's own thread (the sitemap check, links to other
     sites, the page reader) marked "yanında" and not added. Nothing is measured again; a report without the table shows
     nothing. Web: the results view carries `timing`; "How the audit ran" / "Denetim nasıl çalıştı" shows "Süre",
     "Toplam: 21 dk 4 sn" and one line per step. Team report: one line in "Bu denetimin sınırları" ("Denetim süresi 21 dk
     4 sn: site haritasını okuma 16 sn · sayfaları okuma 6 dk 34 sn · …; yanında: … Firecrawl ile okuma 7 dk 28 sn.").
     moodist 21 min 4 s, enpara 11 min 37 s (the web app's own start and end agree).
     (2) *Firecrawl in Akıllı.* Why moodist's reader read 150 of 150 pages and enpara's 151 requests with "Tam okuma"
     off: the plan saved Firecrawl's options with `Options.as_dict()`, which left `read_scope` out, and the web app
     rebuilds the audit's options from that copy (`fc.options_from`), so "needed" became the default "all"; the CLI's
     `--smart` never set it either. Neither site had a JavaScript template. Fixed: `as_dict` keeps `read_scope`; the CLI
     sets "needed" with `--smart` (new `--firecrawl-full-read` for "Tam okuma"). Two over-reads inside "needed" fixed
     too: a redirect or a 4xx answer counted as "Maya could not read" (enpara: 45 pages, 22 redirects and 21 404s), now
     only a block page or challenge, a 429, a failed request, a 5xx or an empty page does (`_maya_could_not_read`); and
     the cross-check took one page per URL pattern of the pages read alone, which left every top-level slug a template
     of its own (moodist: 80 templates for 149 pages), now the page grouping's template key (the pattern from every
     known address, with the layout: 33). On the saved pages: moodist 31 pages (1 failed request + 30 cross-checks)
     instead of 150; enpara 34 instead of 151 requests. Estimated from the saved timings (the reader runs beside
     Maya's steps; its copies are applied at the end, about 0.2 s and 0.33 s a page): moodist reader 7.5 -> ~1.5 min
     beside, results and report 54 -> ~30 s, total 21.1 -> ~20.7 min; enpara reader 3.3 -> ~0.9 min, 82 -> ~51 s,
     11.6 -> ~11.1 min. Firecrawl was not what made moodist slow: Maya's own steps took 20.2 min. Maya's site limit fell
     from 5 to 1 after two answers slower than 2 s (`pacing_reset_ttfb_ms`) and every later request waited ~2 s (access
     137 s for 10 requests, index 103 s, structure 89 s, llms.txt links 128 s for 50); rendering took 4.3 min (21
     pages); the crawl 6.6 min (250 requests). Not changed here (politeness and coverage choices for the owner; see
     IMPLEMENTATION-STATUS).
     (3) *Page typing by content* (`business_types`). A person's own profile page: not an article, its H1 (else its
     title before " - ") reads as a name (2-5 capitalised words after the titles, no digits, none a subject word such
     as tedavi, merkez, ekip, team), and Person or Physician markup, or a professional title (prof, doç, dr, uzm, op,
     psikolog, klinik psikolog, psikiyatrist, terapist, diyetisyen …, doctor, psychologist …) right before the name's last
     two words in the H1, the title, a description or the address, or two or more CV headings (Eğitim, Uzmanlık
     Alanları, Özgeçmiş, Education, Expertise …). It is the content signal "person", scored 5 (more than an address
     word, 4), on the profile types that list it (Sağlık "Doktor ve ekip", which also gets the folder words `team/*`,
     `ekip/*`, `uzmanlarimiz`). And on an article page (Article, BlogPosting, NewsArticle …) the publisher's and author's
     markup (Hospital, MedicalOrganization, Organization, Place, Person, LocalBusiness …) no longer types the page. Of
     moodist's 32 "Klinik ve konum" pages only 2 were profiles (`/tr/team/klinik-psikolog-…`, by the address word
     "klinik"); 30 were blog posts typed by the hospital's Hospital markup, and the live run's second wave copied that
     type to unread blog addresses of the same template (39 of the plan's 150 places went to "clinic"). Now 33 pages
     change type: 30 "Klinik ve konum" -> "Rehber / SSS / blog", 2 "Klinik ve konum" -> "Doktor ve ekip", 1 "Diğer" ->
     "Doktor ve ekip" (`/tr/team/anil-usta/`); "Klinik ve konum" 32 -> 0. enpara: 0 pages change. The sampler's
     re-typing uses the same facts.
     (4) *IDX-8 place-name groups* (`idx8.location_template`). Profiles mark their location page types
     (`"location": true`: Sağlık clinic, E-ticaret stores, Ev hizmetleri service_location, Otomotiv dealers, Restoran
     branches; `business_types.location_types`). The group stands only when the business type has one and at least
     `location_template_min_pages` of its pages, and at least half, are typed as one (`location_template_kept`). The
     engine gates it after the business type is attached (`final.settle`, so after a page reader too; a blocked site's
     reader pages count); a saved report through `reassess_rules._decisions_329`, also in `saved_data` (a current-schema
     report gets a derived copy). The check's evidence keeps what was left out (`location_templates_left_out`), its
     summary count follows, and a check left with no finding passes (partial when its coverage says so). enpara: the
     /sss/ (FAQ, "Destek") and /odemeler/ (payments) groups are gone (Bankacılık has no location type).
     (5) *P levels.* A High or Blocker card is at least P2 (`priority_levels.HIGH_FLOOR`), with the reason "yüksek önem:
     en az P2"; the score, the severity and the card order are unchanged. enpara card 2 (High, broken links whose
     targets were not read): P3 -> P2.
     (6) *Client brief.* Only measured problems (a finding confirmed by hand counts as measured): an estimated card
     ("brand named different ways", "Ölçüldü; kapsamı tahmini") is never among them (`ALLOWED_CONFIDENCE`). "Zaten iyi
     olanlar" says exactly what was fine: ACC-9 is now "Sitenizin güvenlik koruması sayfa isteklerimizi geri çevirmedi:
     incelediğimiz sayfaların hepsi açıldı." (was "… Google'ı ve kendini tanıtan otomatik ziyaretçileri engellemiyor"),
     and ACC-7's line about AI assistants is not said beside an ACC-2 or ACC-6 finding (a robots.txt rule that blocks
     them). enpara: the brand-name problem gives way to the measured hreflang one; ACC-7's line gives way to the key
     pages line.
     (7) *Owner.* A broken-link card with sitemap entries (`final.broken_link_cards` kind "sitemap") is "Geliştirici +
     İçerik" / "Developer + Content" (`card_owner`); enpara card 2 (21 sitemap entries): İçerik -> Geliştirici + İçerik.
     Results offline (scratch copies, provider-free): both team reports 9 pages, both briefs 5 pages and not blocked;
     Sektör audit rows (of 62 / 59): moodist Uygun 10 -> 9, Kısmen Uygun 8 -> 7, Hatalı 3, Kontrol Edilmedi 41 -> 43
     (SEC-071 Kısmen -> KE, SEC-072 Uygun -> KE: no clinic page was read); enpara unchanged (Uygun 10, Kısmen 12,
     Hatalı 2, Kontrol Edilmedi 35). Schema: no bump (`read_scope` is inside `firecrawl.options`, whose keys the frozen
     schema does not pin; the check's evidence is outside it). Tests: `tests/test_live_fixes_329.py` (27);
     `test_client_brief_319` (estimated cards no longer reach the brief).
330. **Speed with politeness kept: the site limit steps back up after fast answers, the audit's own thread goes first,
     access and llms.txt's links to this site on lanes (Owner, 2026-11-09: the step-up and the two steps beside as
     asked; the thresholds (10 answers under 1 s), the rung (1 -> 2 -> configured), the own-thread priority and the
     two-pass llms.txt check are agent defaults).** Every audit, every mode.
     (1) *Step back up* (`sitelimit.SiteLimiter.answered`, called by the fetcher for every answer through the limit). A
     limit that came down only for slow answers (TTFB over 2 s, DECISIONS 294) goes up one rung, 1 -> 2 -> the configured
     limit, after `STEP_UP_AFTER` (10) answers in a row with a TTFB under `FAST_S` (1 s); a slow or bad answer starts the
     count again. A limit brought down by a 429, a 5xx or no answer stays down, and one set to 1 from the start (a
     Crawl-delay, a rate-limited crawl) never goes above 1. Starts stay the polite gap apart. Recorded in
     `crawl.backoff.site_limit.stepped_up` (inside the backoff record, which the frozen schema does not pin).
     (2) *The audit's own thread first.* While it waits for its next request, the lanes beside it (the sitemap check,
     the access data, llms.txt's links) leave slot 0 to it and start nothing that would move its start later. The same
     requests and gaps, never more at once: only the order changes, so the steps on the audit's critical path go first
     and the lanes use the time it spends elsewhere (rendering in the local browser, working out data).
     (3) *Access beside* (`audit.steps_after_crawl`). The access data (user agents, soft-404 probe, llms.txt, HTTP and
     host checks, the robots.txt samples' schedule) needs only the crawl and nothing reads it before the join: it runs
     on a lane of its own beside index, structure and rendering (row `access`, `beside: [index, structure, render]`).
     The robots.txt samples are still sent by the audit's own thread when they come due (DECISIONS 219).
     (4) *llms.txt's links beside.* `ask_llms_links_on_site` asks the links to this site, in the same order, cap,
     robots.txt rules and stopping rules, on a lane that starts once the access data and the sitemap check's rows exist
     (row `llms_links`); `check_llms_links` then reuses those answers and stop state (sending nothing twice) and asks
     only the links to other sites after the other-site pool, on the audit's own thread, as before (row
     `llms_links_other_sites`): the other-site check's budget and answers are shared with the pool and are not safe to
     use beside it. Same requests and rows; only their order changes. New phase `llms_links`.
     *Estimated from the saved request logs* (a replay through a model of the limit: global 1 s gap, own thread on slot
     0, the four sitemap-check workers and the lanes on any slot, back-off and step-up on the recorded TTFBs; the
     model gives the same totals as the real runs: moodist 726 s against 716 s, enpara 330 s against 331 s). Post-crawl
     part (access through rendering plus llms.txt's links): moodist 12.1 -> ~7.6 min, enpara 5.5 -> ~3.7 min; whole
     audit with DECISIONS 329: moodist ~20.7 -> ~16 min, enpara ~11.1 -> ~9.3 min. The step-up alone barely helps
     moodist (its HTML answers take 1-2 s; a run of answers under 1 s comes only with the static files at 06:50) and
     the lanes alone do not either (at a limit of 1 everything is one at a time); the order does. Not changed: the
     crawl itself (moodist 6.6 min), rendering (4.3 min of local browser time) and the performance rounds. Tests:
     `tests/test_speed_modes_330.py`; `test_sitemap_beside_328`, `test_time_limit` (a clock that runs out as index
     starts cuts the access lane too), `test_preview16_measure` (the step order; requests compared as a multiset).
331. **Every mode reads the Akıllı selection; "Özel sayı"; "Tam tarama sırası"; time and credits on the plan (Owner,
     2026-11-09: the modes, the range 25-2000 and the advanced option as asked; the credit estimate's quarter, the
     labels and the selection line are agent defaults).** Web app.
     Modes: Tek sayfa; **Hızlı ~50**; **Akıllı ~150 (önerilen)**; **Derin ~500** (the id `standard` kept, so saved audits
     read as before); **Özel sayı** (`mode: custom`, `page_count` 25-2000, 422 `page_count_required` without it). Every
     mode but a single page runs with `--smart` (DECISIONS 327: page types of the business profile, the team's sampling
     rule, the budget split by rank), scaled to its page cap; **"Tam tarama sırası (gelişmiş)"** (`crawl_order`) reads
     in the crawl's own order as before. The page cap of a plan or an audit is `runner.page_cap` (the mode's, else the
     plan's count, else the audit's saved settings); the plan's fingerprint covers the mode, the cap and the order
     (`mode_basis`). Firecrawl reads only where needed in every sampled mode (DECISIONS 327/329; "Tam okuma" offered in
     each), at most 500 pages; a page the search data names as ranking, which Maya did not ask for, is still read
     through Firecrawl within the plan's page limit (it was left out by "needed" before). The plan says, before Start: the pages, the time (recent runs of the mode, else its
     default; for Özel sayı a range from its page count), Firecrawl's credits as "en fazla N kredi, genellikle yaklaşık
     M" (`credits_expected`: a quarter of the pages and robots.txt in a sampled plan, at least 10, from the two live runs'
     31 and 34 of 150; the pages and robots.txt otherwise; never above the confirmed maximum), and one line on how the
     pages are chosen (`selection_line`, also a row of the plan's details). The new-audit card has the Özel sayı count
     and "Tam tarama sırası" under "Ek seçenekler"; the plan editor has both; the progress line per page type
     (DECISIONS 327) now shows in every sampled mode. Hızlı stays the default. Docs: TEAM-SETUP, README, WEB-API,
     WEB-APP. The command line keeps its own order unless `--smart`. Tests: `tests/test_speed_modes_330.py`; web tests
     whose 500-page scenarios were written for the crawl order run with `crawl_order` (`test_web_app` standard
     fixture, demo, comparison); `test_sampling_327`, `test_web_ux_310` follow the new modes and labels.
332. **One Google key for Core Web Vitals and PageSpeed (Owner, 2026-11-09: what the key is and how to see it, fixed
     where needed; the fallback order is an agent default).** The web app reads Google's speed data from the Chrome UX
     Report only (field data: the origin, phones, 28 days, p75 of LCP, INP, CLS, plus FCP and TTFB; one free request an
     audit, beside the report step, a second or two); it never runs PageSpeed Insights lab tests. Its key was read only
     as `MAYA_AUDIT_CRUX_API_KEY`; the command line's `--pagespeed` (PRF-3: PageSpeed Insights mobile, 3 runs for each
     of up to 5 key pages, only on ownership-verified sites (DECISIONS 53), plus CrUX per page) read only
     `MAYA_AUDIT_GOOGLE_API_KEY` and only from the environment, never `.env`. A key written under the other name was
     silently not used. Now `crux.load_key` reads `MAYA_AUDIT_CRUX_API_KEY`, else `MAYA_AUDIT_GOOGLE_API_KEY`, and
     `crux.google_key` the other way round, each from the environment, then `.env`; the key stays in a header, never in
     an address, a log or a report. Where it shows: the plan's details ("Core Web Vitals from real Chrome visitors are
     included"), "Core Web Vitals (real visitors)" in the results, the team report's field box ("Saha verisi") instead
     of "Ölçülmedi"; the team report's lab box stays "Ölçülmedi" unless DataForSEO's Lighthouse ran. Docs: TEAM-SETUP.
     Tests: `tests/test_speed_modes_330.py` (made-up keys, a recorded answer, a refused key).
     Also written (no code, waiting for the owner): `docs/proposals/SEARCH-CONSOLE.md`, a read-only Search Console
     integration through a service account.
333. **What the plan says: Core Web Vitals shown, a paid line only for chosen paid data, one time (Owner, 2026-11-09:
     the three fixes as asked; the wording is an agent default).** Web app, every plan.
     (1) *Core Web Vitals.* The plan carried "Core Web Vitals from real Chrome visitors are included" / "... not available
     (no API key)" (`search_data.core_web_vitals`) but the page never showed it, so a key set in `.env` showed only as
     one line fewer under "Not available" (DECISIONS 332 said the details show it: they did not). The plan's details now
     have a "Core Web Vitals" row with it. The key itself was read: the owner's app (started from `tools/maya-audit`,
     no `MAYA_AUDIT_ENV_FILE`) loads `tools/maya-audit/.env` and its loader sees a non-empty key (checked with the app's
     own loader, yes/no only; the file was not opened).
     (2) *Paid line.* `paid.price` always prices the backlink calls, so the details can show what they would cost before
     they are chosen; the short plan line printed any such total as "Paid data: at most $0.0516" with backlinks and
     search data off (nothing was ever sent or charged). It now shows a paid total only for paid data the plan asks for
     (`paid.requested`), else "No paid data"; the price stays in the details.
     (3) *One time.* The short line said what recent runs of the mode took, else its default ("about 10 min"); the
     details said the uncalibrated upper estimate of `estimated_duration_s` ("up to about 20 minutes"). The details now
     say the same time and add the audit's hard time limit ("about 10 min (...). Smaller sites finish sooner; the audit
     stops at its time limit of 25 minutes."); the upper estimate stays as data (`duration.up_to_minutes`) and still
     sets the time limit and Özel sayı's range. Tests: `tests/test_speed_modes_330.py`; `test_web_app` (the plan's
     time).
334. **Core Web Vitals asked where the site really is; "Google'da yeterli ziyaretçi verisi yok"; fetched again for a saved
     audit (Owner, 2026-11-09, after the live enpara Akıllı run 2e5829fb: the three asks as asked; the order of the
     origins, the homepage record, CORE-013's Durum rules, page 1's box and the side file are agent defaults).** Every
     audit.
     *Why enpara had no field data:* the request was made, for `https://enpara.com`, the typed address, which only
     redirects; Google answered 404 (no record). Asked live on 2026-11-09 (the owner asked to try both; the key loaded
     by the app, never printed): `https://enpara.com` 404 (phone and all devices), `https://www.enpara.com` 200 (phone
     and all), the homepage `https://www.enpara.com/` 200, `https://enpara.com/` 404. Phones, 28 days to 7 November
     2026: LCP 1.4 s good, INP 322 ms needs improvement, CLS 0.02 good; the homepage alone LCP 1.6 s, INP 205 ms, CLS 0.06.
     (1) `crux.collect` asks the origin the site lands on (the crawl's origin) first, then the typed one, and the
     homepage's own record (URL level, kept as `homepage`); every request is in `attempts` (origin or address, HTTP
     status) and `origins_asked`; a `reason_code` says `no_key`, `no_data`, `error` or `time_limit`. A refused key stops
     at the first origin (the same for every origin). The runner and the CLI pass the crawl's origin and homepage.
     (2) *Where it shows.* Web results: the figures, "Google's figures for <origin>", the homepage's own figures. Team
     report page 1: with no lab score, the fourth box is "Gerçek kullanıcı (CrUX): 2/3 iyi · INP 322 ms
     (iyileştirilmeli)", or "Google'da yeterli ziyaretçi verisi yok"; page 3's field box says the same when there are no
     figures, and its limits line says the figures came from Google and only the lab test was not run. Sektör audit
     CORE-013 (which needs PRF-3, a CLI-only check): from the report's `crux` section: a poor metric Hatalı, a
     needs-improvement one Kısmen Uygun (evidence: the three values, the origin, the date), all good stays "Kontrol
     Edilmedi" with the values (a partly-automatic row is never Uygun, DECISIONS 325; no sample per page type), no data
     "Google'da yeterli ziyaretçi verisi yok (sorulan: …)", no key or a failure said as such, never "İlgili kontrol bu
     denetimde çalışmadı". The Turkish of the no-data sentences starts "Google'da yeterli ziyaretçi verisi yok".
     (3) *A saved audit.* `crux.refresh_saved` asks Google again and writes `artifacts/crux.json` beside report.json
     (never written); the web results (`load_report`), the current-engine copy (its key includes the file's stamp;
     the change is recorded) and so the team report, brief, appendix and Sektör audit read it. Web: "Google'dan yeniden
     al" in the Core Web Vitals section (`POST /audits/{id}/crux`, 409 `crux_no_key` without a key); command line:
     `tools/crux_saved.py <audit folder>`. Free; the site itself is not requested.
     Also fixed on the way: the team report's tabs ran into each other when a sixth tab (Arama ve performans) appears.
     *Schema 1.31:* `crux.reason_code`, `attempts`, `origins_asked`, `homepage`, `fetched_for_saved_audit` (the frozen
     schema pins the section's keys; `docs/report-schema-1.31.json`). Tests: `tests/test_crux_coverage_334.py`
     (recorded answers, a made-up key); the version pins follow.
335. **The coverage line of a sampled audit: "Örneklem: N sayfa okundu, M bilinen adres okunmadı" and why fewer pages
     than the limit (Owner, 2026-11-09: items 2-3 as asked; the reasons' wording is an agent default).** Every sampled
     audit (DECISIONS 331). enpara 2e5829fb said "Örneklem tamam", "Keşfedilen bütün sayfalar okundu" and 0 unread:
     Firecrawl read only where needed, and the unread count was the reader's own (0: it never asks the addresses Maya
     did not fetch), while Maya's crawl stopped at its page limit with 499 known addresses unread.
     (1) *Engine.* `report.known_unread`: with a reader that read only where needed, Maya's unread addresses less those
     the reader read (a new audit then says "partial" with "N more discovered URL(s) remain unchecked").
     (2) *One line* (`sampling.sample_line`, also for saved reports): "Örneklem: 128 sayfa okundu, 499 bilinen adres
     okunmadı." and, when fewer pages than the limit were read, why, from the saved page requests: "150 sayfalık
     sınırdan 128 sayfa okundu: 21 adres hata döndü (404 ×21); 1 adres dosyaydı, sayfa değil; sayfa sınırı her sayfa
     isteğini sayar." (also blocked, unanswered and empty pages, and "örneklem planı bitti: sayfa türleri doldu, N
     sayfalık bütçe kaldı" when the plan ran out first). For enpara it was not page types filling up: 21 sitemap
     addresses answered 404 and 1 was a spreadsheet, each a page request of the 150. The same line on page 1 (the
     pages box: "Örneklem · 499 bilinen adres okunmadı", the header chip "Örneklem"), in "Bu denetimin sınırları" (in
     place of the page-cap line), in the client brief's coverage line and in the web results' coverage row ("Örneklem"),
     when known addresses were left unread and nothing else cut the reading (`sampling.sample_shown`): with everything
     known read, "every page found was read (a sample)" is true and stays; with blocked pages or the time limit,
     "partial" and its reasons stay (the fast suite's demo of a partly read site showed why).
     Every "not read" figure of a sampled audit is the same number (`sampling.known_not_read`: the web's sentences, the
     selection's coverage, the appendix). Tests: `tests/test_crux_coverage_334.py`.
336. **"Google'dan yeniden al" reaches its route; the results say which address Google was asked about (Owner,
     2026-11-10, after pressing the button on the saved enpara audit 2e5829fb gave "There is nothing at that address";
     the wording of the asked line and the "site lands on" sentence are agent defaults).** Every audit.
     *Cause:* the results hand the button the whole address (`crux_refresh.url` = `/api/v1/audits/<id>/crux`, like
     every other address the server hands over), and the page's `api()` put `/api/v1` in front of every path, so the
     button posted to `/api/v1/api/v1/audits/<id>/crux`: no route, the generic 404. Path only: the method (POST) and
     the audit id (the full 32-character id) were right; `tools/crux_saved.py` worked because it calls
     `crux.refresh_saved` directly. The 334 test posted to a hand-written path, not the one the page receives.
     (1) `api()` uses a path that already starts with `/api/v1/` as it is; any other path is prefixed as before.
     (2) A Core Web Vitals section with no figures says, under its sentence, "Google was asked about: <addresses>."
     ("Google'a sorulan adres: …"), from `attempts`, else `origins_asked`, else (a section saved before schema 1.31)
     its `origin`; nothing when nothing was asked (no key, time limit). When the site lands on another origin (the
     crawl's origin) that was not asked: "The site lands on <origin>, which was not asked; “Ask Google again” asks
     there first." Web view only (`summary.speed_view`: `asked`, `asked_shown`); report.json and the schema unchanged.
     Tests: `tests/test_crux_coverage_334.py`, the last two: the real `app.js` in headless Chromium with every
     `/api/v1` request forwarded to the app's real routes; pressing the button posts to `/api/v1/audits/<id>/crux`
     (200) and shows Google's figures. With the old `api()` the test fails (the button's request gets the 404).
337. **Broken links split by what is to be fixed; where every problem address is pointed at; which sitemap file lists
     it (Owner, 2026-11-10/11, asked by İlginay on enpara 2e5829fb's card 2: Part 2's items 1-5 and the sitemap-only
     card, the sitemap file per address, the likely-cause line marked as inference, "kaldırın veya yönlendirin" for
     removed pages, and the same "where" columns for 5xx, redirect chains/loops and canonical/hreflang targets as asked;
     the severities of the new findings, the heading test, the column wording and the 3-row PDF box are agent
     defaults).** Every audit.
     *What enpara's card 2 was* (investigated offline first, shown to the owner): none of its 21 addresses is a link on
     a page Maya read. All 21 came from the sitemaps only (`via = sitemap`, no parent page, empty `link_sources`); each
     answers 302 to the site's error page (404). 15 of them spell a heading or FAQ question on a page read ("Kredi kartı
     aidatı yok!", "Çocuğunuz da Enparalı oluyor :)"); the other 6 look like removed pages. The Ek XLSX had no linking
     page because there is none, and because no XLSX sheet ever carried link rows (only the PDF did, DECISIONS 283).
     Maya's link extraction already followed only `<a href>` and skipped `javascript:`, `mailto:`, `tel:`, `data:` and
     `#…`; `data-href`, `onclick` and tab/accordion ids were never requested (now locked by tests).
     (1) *Split* (`checks.index.broken_link_sources`, new audits; `reassess_rules._decisions_337`, saved ones, traced
     again from the saved pages' links and redirects): IDX-1's "4xx, linked internally or listed in the sitemap" becomes
     up to three findings: the real links ("…; linked from N page(s)", the engine's severity); "N sitemap address(es)
     end at a client error (4xx); no page read links to them" (`idx1.4xx.sitemap_only`, the engine's severity,
     Developer, M; card "Site haritasındaki hata veren adresleri düzeltin ya da çıkarın"); and "N link(s) on M page(s)
     have a mistyped address (href) …" (`idx1.href_mistyped`, Low, Medium when the homepage or a key page holds one,
     Developer, S; card "Bağlantı adresi yanlış yazılmış bağlantıları düzeltin"). A mistyped href
     (`html_links.mistyped_href`) is a real `<a href>` that failed with a 4xx and holds spaces, or has no leading /, #,
     ?, . or scheme and no file name in its first part ("sekme-2", "kartlar/x"); "contact.html" and "../x" are not.
     DECISIONS 329's "Geliştirici + İçerik" now applies only to the old mixed finding.
     (2) *Likely cause* (inference, said as such): a sitemap entry whose last part spells a heading on a page read
     (Turkish letters folded, a trailing copy number left out) is listed with that page and heading
     (`evidence.sitemap_entries[].heading_match`, `likely_cause`); the card says "Olası neden (çıkarım): N adres okunan
     sayfalardaki başlıklarla aynı (örnek: …). Site haritası oluşturucuyu kontrol edin." and "Kalan N kayıt kaldırılmış
     sayfalara benziyor: kaldırın veya yönlendirin."
     (3) *Which sitemap file*: schema 1.32 adds `sitemap_doc.new_urls` (a file's addresses no earlier file listed;
     `crawl.sitemap_urls` holds them file by file), so `sitemap.file_map` gives each address's file. A report written
     before gets it only when the files' counts add up exactly to the addresses known (enpara: 278 + 137 = 415), never
     guessed otherwise. The card says "Site haritası dosyaları: /sirketim/sitemap.xml (9), /sitemap.xml (12)."
     (4) *Where* (`maya_audit.link_places`, read by `final.broken_link_cards`): one row per problem address and the page
     or entry that names it, for IDX-1 4xx (links, sitemap entries, mistyped), IDX-1 5xx, IDX-6 links to redirects,
     IDX-3 chains and loops, IDX-4 canonicals that fail or redirect, STR-9 hreflang targets that do not answer 200:
     the address, its status through its redirects ("302 → 404"), the page with the link (or "yalnızca site
     haritasında", "bağlantı bulunamadı", the page with the canonical/hreflang tag), its text, the href as written
     (`outlinks[].href`, new audits; "kaydedilmedi (eski denetim)" otherwise), its place (menü / altbilgi / gövde /
     <head>), in the sitemap and which file, and what to point to (a redirect's own working end, else "kaldırın",
     "kaldırın veya yönlendirin", "site haritası oluşturucuyu düzeltin", "döngüyü düzeltin"; never a guessed address).
     Shown as: the Ek's new reader sheet "Bağlantı yerleri" (13 columns; addresses readable, links behind them), the
     PDF card's box "NEREDE DÜZELTİLECEK" (first 3 rows, "+N satır daha (tam liste ekte: «Bağlantı yerleri»)"), the
     address-list file, and the web card's "Etkilenen sayfalar" dialog (a "Bağlantı yerleri" table above the pages).
     (5) "Nasıl okunur" adds the "Bağlantı yerleri" line and "Bağlantılar Mac'in hızlı önizlemesinde çalışmaz; dosyayı
     Numbers, Excel veya Google Sheets ile açın."
     *Other audits* (current engine on scratch copies, before vs after): moodist 2d72fea0, same 14 cards, card 1
     (canonical/chain/links-to-redirect) gains 158 "where" rows; nihan b3198942, no card changes; enpara, card 2 as
     above and card 8 (links to redirects) gains 3 rows.
     Tests: `tests/test_link_places_337.py` (a fake site with tab/accordion markup, data-href, onclick, a text href, a
     real 404 link and sitemap entries, one spelling a heading; a synthetic saved report shaped like enpara's; the web
     card's list); `tests/test_m1_broken_links.py` follows (the card rows carry the new fields; a link to a working
     redirect is now said where it is under IDX-6).
338. **The SEO team's card-by-card review of enpara 2e5829fb, each rule checked against the saved evidence and fixed for
     every audit (Owner, 2026-11-11, review by the team's SEO expert in `maya-audit-enpara.com-2026-11-09-İLGİNAY
     KONTROL.xlsx`: items 1-8 as asked; the thresholds (HSTS a year, 3 styled titles), the deliberate-path lists, the
     wording and the review file's shape are agent defaults).** Every audit; saved audits through
     `reassess_rules._decisions_338`. Her verdicts: 4 correct, 5 wrong, 1 wording, 3 incomplete
     (`docs/expert-reviews/enpara-2e5829fb.json`, the first human labels for Stage 12's accuracy measurement).
     (1) *TSEO-1, head closed early* (she: wrong; checked: partly right). `div#blueLightOverlay` sits inside <head> in the
     site's own HTML (Maya's direct copy too, 121 of 128 pages), so the head does end there; but canonical, hreflang and
     title come before it. High had come from any robots tag after the break, whose value was never recorded. Now the
     parser keeps that value (`outside_head.robots_content`); High only when a canonical, hreflang or title with no copy
     before the break, or a robots value that restricts something (noindex, nofollow, none, nosnippet, max-*,
     unavailable_after ...), comes after it; otherwise Medium, and each row says what stays in the head
     (`kept_in_head`). The card says it: "Head içinde, kırılmadan önce: canonical, title, hreflang. <div#blueLightOverlay>
     sonrasında: ikinci bir canonical kopyası, robots (değeri kaydedilmedi), description, …". enpara: High 47 → 0 pages,
     the card Medium.
     (2) *ACC-2, robots.txt* (she: wrong; right). A Disallow on query parameters ("?" or "="), old server-script files
     (.aspx, .asp, .php, .jsp, .cfm, .cgi, .ashx, .axd, .do) or form/application paths (basvuru, form, apply, signup,
     register, kayit, teklif, odeme, checkout) that reaches no homepage, key page, sitemap address or menu link is Info
     with "Reported as Info: … usually block on purpose … Confirm it is intended" (`deliberate_rule`). enpara: 18 → Info,
     no card.
     (3) *STR-5, brand names* (she: wrong; mostly right). Counted were "Enpara", "Enpara.com", "Enpara Şirketim",
     "Bankanın güzeli | Enpara" and "Homepage" on 111 pages. The domain form is the brand ("Enpara.com" = "enpara",
     `brand_key`); a section's own name (the main name and 1-4 words, only in titles and og:site_name, never on the
     homepage) is a sub-brand, listed, not counted; the pages to fix are those carrying another name, not all that name
     the brand. enpara: 3 names (the two Organization names are real), 2 pages, under "Teyit edin".
     (4) *Wording* (she: wording). The team report's Turkish says "H1 etiketi" for <h1> in every H1 rule, not "ana
     başlık"; the text checks allow the tag names H1-H6.
     (5) *STR-2, long pages without subheadings* (she: wrong; partly right). Neither copy of the 4 pages has <h2>/<h3>;
     the raw HTML was not saved, so styled titles cannot be confirmed for this audit. A listing page (page type
     "category") is left out (`drop_listing_pages`, after page types are known); new audits count section titles that
     are not heading tags (role="heading", <summary>, <dt>, accordion toggles, a class or id naming a title, outside the
     header, menu and footer: `styled_headings`), and 3 or more make it "N long page(s) … show section titles that are not
     <h2>/<h3> tags" (`str2.styled_subheadings`, "Uzun sayfalardaki bölüm başlıklarını H2/H3 olarak işaretleyin"). The
     no-subheadings card says "H2/H3 bölüm başlıkları". enpara: 4 → 3 pages.
     (6) *IDX-2, http → https* (she: wrong; partly right). The 302 is real: 4 requests (robots.txt and / on both hosts),
     one hop each to https://www.enpara.com/. The https pages send HSTS for 1,825 days: with HSTS of a year or more the
     temporary code is Info with the reason. enpara: no card.
     (7) *Note cards* (she: incomplete). A card the team report puts together from notes lists every address with what
     was seen there (`url_notes`): llms.txt with each link → where it redirects, the page and link → target for internal
     links to redirects (left out when IDX-6's "links to redirects" card says the same links), each question page with
     its count and first question; the card prints three of them; the Ek gives each address a row of the card
     (`page_rows.finding_rows`), so the web list has them too; the engine keeps every question page (was 5), and a saved
     audit's card counts the pages it did not keep.
     (8) *Accuracy data*: one record per card (rule ids, the expert's note, her verdict, the evidence check, the fix);
     `follow_up` lists the rules she marked wrong: acc2.blocks.sample, idx2.temporary, str2.no_subheadings, str5.names,
     tseo1.head_closed_lost/later. IMPLEMENTATION-STATUS "Uzman kontrolü" summarises it.
     Tests: `tests/test_expert_review_338.py` (markup with the break before plain and restricting robots tags and a
     second canonical; deliberate patterns; a synthetic saved report shaped like enpara's; a fake site with accordion
     titles and a flat long page; a listing page; a note card's rows; the review file).

339. **One card with pages of two severities says each; the head-closed card is said from its evidence; the Ek's
     Core Web Vitals and business-type lines (Owner, 2026-11-11, after enpara fee70191).** The live audit fee70191
     (Akıllı ~150, run on `fb4f070`) showed card 1 "Head'i erken kapatan öğeyi taşıyın" as High, P1, 90 pages, with the
     rule's fixed words.
     (1) *The evidence.* Maya's own crawl records (state/crawl.db) and the report agree: on 2 pages (/acentelik-bilgileri,
     /sirketim/basvuru) `<meta name="robots" content="noindex">` comes after `<div#blueLightOverlay>` and the head holds
     no robots tag; canonical and title (and hreflang on one) are before the break. On the other 88 pages canonical,
     hreflang and title stay in the head; after it come the description, Open Graph, generator and on 6 pages a plain
     "index, follow". High is right for the 2 pages (the site's noindex may not be applied), not for 90.
     (2) *Why the fix of 338 did not show.* It did apply: the engine made `tseo1.head_closed_lost` (S2, 2 pages) and
     `tseo1.head_closed_later` (S3, 88 pages). Both carry one `dedup_key` (the element, DECISIONS 278), so the client
     selection made one card of them, took the worst severity, scored it on all 90 pages' reach and printed "90 sayfa";
     the card's why, priority text, steps and check were the lost rule's fixed words ("canonical, robots ya da hreflang
     … yok sayılır", "Search Console'da canonical'ı teyit edin"), and the first example was a Medium page. Not the
     web-app vs reassess path, not an old process, no missing field.
     (3) *Fix, every card.* A card that joins findings of different severities (one cause, one fix, still one card) is
     scored on the pages of its worst severity only (`client_selection.groups`: reach from those pages,
     `severity_pages` {severity: pages}, examples from those pages); its scope says the others with their severity:
     "2 sayfa (+88 sayfa: Orta)". The severity, the band order and the P0-P3 label are unchanged (P0-P3 keeps the team
     method's "a card takes its highest-scoring finding": fee70191's P1 comes from the 88 Medium pages, 85 points).
     (4) *Fix, the head card.* Its why, priority text, steps and check come from the evidence (`Builder.head_words`):
     which tags are lost on how many pages (a canonical/hreflang/title with no copy in the head, a restricting robots
     value), and on the others what stays in the head and what comes after; the third step names Search Console's
     canonical only when a canonical is lost, the robots rule when a robots value is. Labels `head_why_*`, `head_fix*`,
     `head_step_*`, `head_verify`, `scope_split` (tr/en).
     (5) *Ek, "Kapsam".* PRF-3 is not assessed when the lab test (--pagespeed) was not run, and the line said "Core Web
     Vitals ve Lighthouse metrikleri: İsteğe bağlı panel çalıştırılmadı" though CrUX had assessed Core Web Vitals. With
     `crux.status` "assessed" the line is "Lighthouse laboratuvar metrikleri (isteğe bağlı): Laboratuvar testi
     yapılmadı (--pagespeed); Core Web Vitals, Google'ın gerçek ziyaretçi verisinden (Chrome UX Report) değerlendirildi."
     (`client_selection.not_assessed_parts`; the same count everywhere).
     (6) *Ek, "Yöntem".* "İş önemi: 1,0 (iş türü profilleri gelene kadar)" was stale since DECISIONS 311. The sheet says the
     business type used (and whether chosen or suggested), its page type weights, and how it enters: 1.0 in the score,
     through page importance (50% page type weight + 35% internal links + 15% click depth), which sets reach and the
     P0-P3 page weight; "Diğer" says no profile and Stage 3's weights (`client_appendix.method_rows`).
     Tests: `tests/test_head_card_339.py` (a fake site with one noindex page and three description/og pages after a
     body element in the head, through the engine, the selection, the team report and the Ek).
     (7) *Brand names only in structured data: "Teyit edin" (Owner, same day).* In 2e5829fb the brand card went to
     "Teyit edin" only because it was seen in Firecrawl's copy alone (`reading.seen_in`), not by a rule; fee70191 read it
     with Maya's own crawler too, so it came out a card (Düşük, P2). Rule: a brand-names finding whose visible name
     (titles, og:site_name, footer) is one name everywhere, the others being only Organization/WebSite names, waits for
     a person (`client_selection.names_in_markup`, reason "names_in_markup": "Doğrulama bekliyor: diğer adlar yalnız
     yapısal veride; işaretlemede kontrol edin"): whether "Homepage" or a slogan as an Organization name is a mistake
     is seen in the markup. A second name people see (moodist's English title name, 87f0425a's "Enpara.com" in titles)
     keeps the card.
     (8) *Note cards past the PDF's room (Owner, same day).* The PDF prints at most 2 note cards (DECISIONS 309), tried
     in a fixed order (structured data, small fixes, content, ...). fee70191's question observation (25 pages) was found
     but its card was never made, so its pages were nowhere, not even in the Ek. Every note card past that room is now
     made for the Ek and the web page list only (`notes_more`, `appendix_only`, no number; the PDF and its text fields
     unchanged; `build_data.cards_for_appendix`).
     (9) *A note card's rows in the Ek, per address.* A note card that also holds a finding (llms.txt's redirecting
     links) gave the Ek only the finding's row, "ayrıntı kaydedilmedi", and none for its other addresses (pages without
     twitter:card). Now the finding's row says what the card saw there (each link → where it goes) and every other
     address has its own row with what was seen (`hygiene_seen` labels).

340. **The SEO team's 2nd review of enpara fee70191: a sitemap entry as written and when it was read; links to
     redirects in their own columns; FAQPage only for a real Q&A block; what to do with each redirecting item; a page
     title is not a brand name (Owner, 2026-11-11).** Her file (an Ek made before `fffddad` and `1db0ddf`): 9 of 15 cards
     correct. Accuracy data: `docs/expert-reviews/enpara-fee70191.json`; per rule: `docs/expert-reviews/ACCURACY.md`
     (`scripts/expert_accuracy.py`, checked by a test).
     (1) *Cards 1 and 12 (notes on the older file).* Card 1 is "2 sayfa (+88 sayfa: Orta)" since 339. Card 12: both
     other names are page titles copied into structured data ("Homepage" is /en/homepage's <title>, "Bankanın güzeli |
     Enpara" the homepage's). An Organization or WebSite name equal to the <title> of the page it is on, and given by no
     other source, is not counted as a brand name (`page_titles_not_counted`; saved reports by `_decisions_340`).
     enpara: one name left, no brand finding.
     (2) *Card 2, sitemap entries (she: not in the sitemap).* Checked offline: all 21 are in `crawl.sitemap_urls`, each
     page record says `discovered_via: sitemap`, 12 from /sitemap.xml and 9 from /sirketim/sitemap.xml, both read at
     12:07:49-12:07:52 UTC (the sitemap step); all https://www., no trailing slash; none came from elsewhere. 10 hold
     Turkish letters the file wrote percent-encoded (Maya keeps a letter as written, so a stored %C3 was in the file), and
     the Ek showed them decoded: Cmd+F in the file could not find them. The raw <loc> text was not saved, and today's file
     cannot be fetched offline. New audits keep each listed address's <loc> exactly as written and its line
     (`sitemap.loc_lines`, `CrawlResult._sitemap_loc_of`) and when each file was read (`_sitemap_read_at`), in memory and
     in the finding's `sitemap_entries` (no schema change); "Bağlantı yerleri" gains "Site haritasındaki <loc> metni",
     "<loc> satırı" and "Site haritası okuma zamanı" (UTC and TSİ); a saved audit shows the address as Maya kept it
     (percent-encoded, "kaydedilmedi (eski denetim)") and the sitemap step's start, marked "yaklaşık".
     (3) *Card 8, links to redirects (she: confusing).* A link to an address that redirects to a working page is not a
     broken address: such rows (links, canonicals, hreflang) leave "Bağlantı yerleri" for "Yönlendiren bağlantılar":
     Bağlantının bulunduğu sayfa, Bağlantı metni, Konum, Bağlantı verilen (eski) adres, Yönlendirme, Doğrudan verilmesi
     gereken son adres, Not; when the redirect ends on the linking page itself, the note says so (enpara: "Hesap aç" on
     /kredi-musteri/ihtiyac-kredisi-hesaplama goes to /kredi-musteri/kredi-basvuru, which 302s back to that page). The
     per-page value says which link goes where and what to link instead. The web card list shows both tables.
     (4) *Card 14, FAQPage (she: wrong, these are headings).* All 16 pages re-checked from Maya's records: no accordion,
     no FAQ heading; paragraphs under "Ödeme İste" / "ATM'ye Transfer", question-shaped article headings, 51 article
     links on /bilgi-bankasi. FAQPage is now suggested only when the questions open and close their answers (<summary>,
     <dt>, and since 340 any element with aria-expanded, data-toggle="collapse" or an accordion class) or the run sits
     under a heading naming an FAQ (`FAQ_SECTION`: Sıkça/Sık sorulan sorular, SSS, FAQ, Merak edilenler, Soru ve cevap
     ...); evidence `qa_container`. A saved report kept no block record: a page stays only when one of its headings names
     an FAQ. enpara: 16 → 0, no card.
     (5) *Card 15, redirecting items (she: give the target).* Each item says what to do (`Builder.redirect_advice`):
     "bağlantıyı şu adrese verin: …" when the end answered 2xx; "hata sayfasına gidiyor (404): bağlantıyı kaldırın ya da
     doğru sayfanın adresini yazın" when it is an error page (it answered 4xx/5xx, or its path is that of an address that
     did: /404?aspxerrorpath=...); the address and "bu adresin yanıtı ölçülmedi" otherwise (no request is sent for it).
     Tests: `tests/test_expert_review_340.py` (a fake site with a multi-line sitemap, a self-ending redirect, llms.txt,
     plain/FAQ/accordion questions and a page-title Organization name; saved-report cases; the review file and summary).

341. **Each row of an early-closed <head> says its own page (Owner, 2026-11-11, enpara fee70191).** The Ek's "Bulgu
     bazında" still gave all 90 rows of card 1 the rule's fixed words ("<head> erken kapanıyor, kritik etiketler
     okunmuyor"; "… canonical, robots ve hreflang etiketlerinin head'de kalmasını sağlayın") and "Ölçülen değer" "—":
     339 had changed the card, not its rows, and the rule's evidence keeps only 40 pages. Now every row of
     tseo1.head_closed_lost/later is built from that page's own record (`page_rows.head_row_words`, from the crawl's
     page records for every page, the finding's evidence row first: `client_selection.head_rows`, `_head_rows`):
     a page that loses something (High) says which tag comes after the element with no copy before it and what the
     head keeps ("robots (noindex), <div#blueLightOverlay> sonrasında; head'de bu etiketin bir kopyası yok.
     <div#blueLightOverlay> öncesinde, head'de: canonical, title"); any other page lists what comes after (a second
     canonical, description, Open Graph, other meta, a plain robots value) and that canonical, title and hreflang are
     before it; the title and the fix follow. Every merged card of the saved audits (enpara fee70191, 2e5829fb, 87f0425a,
     moodist 2d72fea0, nihan b3198942) was checked for rows without their own value: one left, nihan's menu-language row
     of its note card, which now says the page's language and the labels in the other (`menu_seen`).
     Tests: `tests/test_head_rows_341.py`.
342. **The SEO team's 165-item checklist, visibly checked in every audit: an Ek sheet with every item and one page of
     the team report (Owner, 2026-11-12, at İlginay's request: the checklist `SEO_Audit_Checklist.xlsx`, its mapping
     `reviews/checklist/mapping.xlsx`, the five results, the evidence line with a rule ID or card number, the missing
     data source for "Veri eksik", totals per result and per group; how each item is decided, the conditions, the
     sheet layout and the page are agent defaults).** Global rules for every audit; enpara fee70191 was only the test
     case.
     (1) *The items* (`maya_audit/checklist_items.json`, made by `scripts/checklist_items.py` from the mapping, which is
     not in git): id, group, item, priority, the checklist's "Uygulanabilirlik", Maya's method (full, partial, review =
     AI+expert, manual, data = needs a connection, missing = not automated yet), the checks and rule-id prefixes the item
     reads, the data sources the whole item needs, what a partial item still needs once Maya's part is clean ("review"
     or data sources), and the site condition. INT-1..4 are the crawl's own records, not report checks: INT-3 reads as
     RND-1/RND-2, the scope and completeness items read the crawl. Every prefix matches a known rule and every check a
     known check (tested).
     (2) *How an item is decided* (`maya_audit/checklist.py`, first match wins): its site condition does not hold ->
     Uygulanmaz with the reason (shop items on a site with no product page and a non-shop business type, one language,
     no local-business signal, no category/article/PDF/video/FAQ/internal search/news page, under 10,000 addresses,
     no IndexNow key, no raw-vs-rendered gap for SPA items); a few items from the audit's own records (business type and
     page types; Core Web Vitals p75 from CrUX: "good" Geçti, else Sorun, with the value; field data kept apart; the
     crawl's start, cap and completeness; the re-asking of serious findings); a problem (S1-S4) of its rules on a card
     or in the appendix -> Sorun, the PDF's card number and title, else the finding's title, and the rule; a problem
     waiting under "Teyit edin" -> İnceleme gerekli; a manual item -> Veri eksik, "Manuel"; a source the item needs is
     not connected -> Veri eksik, that source (Search Console, GA4, PageSpeed, Merchant Center, Manuel, Bing Webmaster
     Tools, Google Business Profile, server logs, DataForSEO, CRM, IndexNow key, JS render); an expert-judgement or
     not-yet-automated item -> İnceleme gerekli; every check it reads did not run -> Veri eksik with that check's source;
     no page read is what its checks are about -> Uygulanmaz; then a full item -> Geçti, a partial one -> Geçti when
     Maya's part is the item, Veri eksik when the rest needs a source not connected, else İnceleme gerekli. Rejected
     findings and Maya's own limits count for nothing; Info notes are not issues.
     (3) *Where it is read from:* `client_selection.select` keeps `_checklist_facts` (each check's status, the
     connections as yes/no and never a key, CrUX, the site's shape), so the Ek and the team report decide from the same
     selection as the cards; nothing is stored in report.json and every saved audit gets it with no reassessment.
     (4) *Ek:* "Kontrol listesi" after the reader sheets (ID, Grup, Kontrol maddesi, Öncelik, Sonuç, Kanıt, Maya kuralı /
     kart, Eksik veri kaynağı; 165 rows) and "Kontrol listesi özeti" (Toplam, then the 20 groups: Madde and the five
     results). English: "Checklist", "Checklist totals", with English item and group names written for it (the
     checklist exists only in Turkish; `GROUP_EN`, `ITEM_EN` in the script), so the English report holds no Turkish.
     The language-mix test leaves out the checklist's own Turkish names ("Önemli URL HTTP status" is the team's
     wording, not an English template).
     (5) *Team report:* one page "SEO kontrol listesi" after "Kapsam ve ek": the five totals, the missing data sources
     with their counts, the items with an issue (14 shown, the rest "+N madde daha (ekte)") and the 20 groups' table.
     RG-15 (at most 10 pages) does not count it: the page was asked for on top of a report that may already have ten.
     Tests: `tests/test_checklist_342.py` (14); the sheet lists in `test_xlsx_pages_322`, `test_v03_client_report`;
     `checklist_items.json` in the package data.
343. **Technical issues from the SEO team's review (Efsa's enpara report, `enpara-seo-tum-bulgular-2026-11-12.xlsx`)
     as global rules (Owner, 2026-11-12: the seven issues, the four card titles, every affected page in the Ek with its
     evidence, "say so when saved data cannot confirm", the checklist mapping; the detection details, severities, the
     other two titles and the sitemap limit's wording are agent defaults).** Global rules for every audit; enpara
     fee70191 was only the test case. New module `maya_audit/checks/team_rules.py`, run with the checklist's quick checks
     (`quick_rules.findings`), so a live audit, an older saved report (`reassess_rules.apply`) and a saved report of the
     current schema (`reassess_rules.saved_data`, `_decisions_343`) get the same rules. Every evidence record carries
     `row` ({tr, en}), the line its Ek row shows (`page_rows._record_words`).
     (1) *`idx1.error_redirect`* (IDX-1, Medium, verified), card "Olmayan adreslerde 302 yerine doğrudan 404/410
     döndürün": a requested address whose redirect hops all answer 3xx and whose target is an error page (a path segment
     or file named 404/410/500/error(s)/hata/not-found/page-not-found/sayfa-bulunamadi/bulunamadi/sayfa-yok, or an
     `aspxerrorpath` query), from the crawl's redirect records (`crawl.redirects`, schema 1.26) and the missing-page probe
     (`crawl.index.soft_404`), whose verdict now says `redirect_to_error_page`. Row: "302 → /404?aspxerrorpath=… → 404".
     (2) *`idx8.self_canonical_copies`* (IDX-8, Medium, verified), card "Aynı sayfanın ikinci adreslerini asıl adrese
     301'leyin": addresses of one page, that is the same path but for a last segment naming the page above it
     (/anasayfa, /ana-sayfa, /home, /default.aspx, /index.html …) or the query (?sw=1), read with the same visible text
     (its hash), title and H1, each 200 with no canonical to another address (relative canonicals resolved) and no
     hreflang between them. Pairs apart only by a trailing slash, a file extension or the letter case stay
     `idx8.two_addresses`'s (Low); different pages that share one text stay `idx8.copies`'s (and rule 7's). The main
     address is the homepage's root when it is one of them, else the most linked, else the shortest. Rows: the main
     address ("asıl adres önerisi") and each second one ("… → / adresine 301"). The judgment layer's "compare purposes
     before consolidating" (`judgments.py`, IDX-8) does not apply: it is one page.
     (3) *`str3.product_on_article`* (STR-3, Medium, verified), card "Blog yazılarındaki Product işaretlemesini
     kaldırın": a page typed blog_article by the page grouping or carrying Article/BlogPosting/NewsArticle/TechArticle/
     Report, with Product or AggregateRating. Row: the types.
     (4) *Template variables:* STR-13 (`str13.markers`) already read JSON-LD, meta tags, the title, links and visible
     text; added: the %%…%% form (`config.TEMPLATE_MARKERS`, an SEO plugin's title variables; "100%%" is not one) and a
     rule of its own for the JSON-LD and meta-tag findings, `str13.markers_data`, with the card "JSON-LD'deki
     doldurulmamış şablon değişkenini düzeltin" (`rules.assign` gives saved findings the new id too). No second rule.
     (5) *`str1.subpage_copies_parent`* (STR-1, Medium, verified), card "Alt sayfalara kendi başlığını, H1'ini ve
     hreflang'ini verin": a page read under a parent page read (the nearest one in its address path, never the
     homepage), canonical to itself, whose hreflang names the parent (not itself) and whose title, H1 or description is
     the parent's. Row: what is shared, the title, canonical and hreflang.
     (6) *The sitemap check reads a sitemap of up to 1,000 addresses whole* (`config.SITEMAP_CHECK_ALL_UP_TO`,
     `index_data.sitemap_check_cap`): every address the crawl did not read is asked, whatever `sitemap_check_max`
     (100/300) says; above 1,000 the sample as before (DECISIONS 294); not in a fast check; off stays off. Discovery reads
     enough of the sitemap for it (`enough` in the crawler). A saved audit cannot gain the addresses it did not ask.
     (7) *`str2.h1_parent_name`* (STR-2, Low, verified), card "Alt sayfalara kendi konusunu anlatan bir H1 verin": a page
     read whose H1 is the H1 of the parent page read above it (or, when the trail's names are recorded, the breadcrumb
     step above it); the pages of rule 5 and rule 2's second addresses are left out (their fix is another).
     *Card words with HTTP status codes:* the team's titles name 301, 302, 404 and 410; the text checks accept these four
     codes (as they accept H1), the team report counts them as the card's facts, and the redirect card names the code the
     site answered (302 in the words; 301 or 307 when the evidence says so) (`build_data.status_words`). The sitemap
     limit is a setting, `sitemap_check_all_up_to` (1,000; 0 turns it off; the sample's own tests use 0).
     *Checklist:* SEO-013 (+error_redirect), -041 and -049 (+self_canonical_copies), -043 and -064 and -145
     (+subpage_copies_parent), -065 (+h1_parent_name, subpage_copies_parent), -101 (+markers_data, product_on_article),
     -106 (+product_on_article), -136 (+str13.markers).
     *enpara fee70191 from the saved data (no request):* (1) confirmed: Maya's made-up address answered 302 to
     /404?aspxerrorpath=… and 21 crawled addresses do the same (21 rows); (2) one pair,
     /bireysel-basvuru/kimlik-bilgileriniz and its ?sw=1 copy (pages such as /ucretler and /ucretler/para-transferleri
     share one text but are two pages: idx8.copies and rule 7); the review's
     /anasayfa vs / was found (linked) but not read (page cap 150) and /sss/default.aspx was not found at all: both need a
     fetch, so they are not claimed; (3) 39 blog pages with Product and AggregateRating; (4) no variable in the JSON-LD
     or meta tags of the 174 saved copies (STR-13 found markers only in link addresses and visible text, as before);
     (5) 12 sub-pages (/sss/* and /sirketim/sss/odeme-ve-transferler); (6) not confirmable: 415 sitemap addresses, 130
     read by the crawl and 100 of the other 285 asked; the next run asks all 285; (7) 20 pages (/odemeler/*,
     /transferler/*, /iletisim/*, /ucretler/kredi-karti ...).
     Tests: `tests/test_team_rules_343.py` (26); `test_answer_key` (a redirect to /tr/kampanyalar/ is "elsewhere"; /tr/hata/
     is an error page now), the sitemap sample tests set `sitemap_check_all_up_to=0`.
344. **The SEO expert's review of the enpara Ek built from the DECISIONS 343 rules, as global rules (Owner, 2026-11-12:
     İlginay's notes per card, the five fixes, the one-card title "Sayfa içindeki başlıklar/sorular ayrı adres
     oluşturuyor", type Kontrol edin, "canonical or noindex, never 301" for form steps, a 301 target per missing address
     or 410, "Bilgi" for a conditional or application redirect, how to check it; the detection details, the target
     scoring, the wording and the steps' order are agent defaults).** Global rules for every audit; enpara fee70191 was
     only the test case. Also: the stray derived copy `…/fee70191…/current-engine/report.current-engine/` (written by
     verification builds pointed at the wrong file, DECISIONS 343) was deleted at the owner's word; nothing else.
     (1) *The head-closed card says where.* The analysis records how many `<head>` and `</head>` the raw HTML writes and
     the line of each `</head>` (`analysis.head_tags`; a new audit, the saved ones keep no raw HTML: their rows say
     "kaydedilmedi (sonraki denetimde ölçülür)"). Each Ek row names the element that ends the head as tag#id.class, its
     raw HTML line, the counts and what comes after it; its fix names the element and the place ("… (head içinde, ham
     HTML satır 61) gövdeye taşıyın"). The card reads every page's record (`_head_rows`): when one element ends the head
     on all of them it says so once ("Tüm N sayfada head'i aynı şablon öğesi kapatıyor: <div#blueLightOverlay>"), its
     first step lists the element's lines per template, and its check asks for one `<head>` and one `</head>`.
     (2) *One site-wide card for sub-pages:* `str1.subpage_copies_parent` and `str2.h1_parent_name` are replaced by
     `str1.sections_as_pages` (STR-1, Medium, estimated, issue type warning = "Kontrol edin"): a page read under a parent
     page read, canonical to itself, with the parent's title, the parent's H1 or an hreflang naming the parent; left out:
     a page whose H1 is its own title (title without its brand part), unless its hreflang names the parent. The fix is a
     decision for the site: real pages (own title, H1, description, content, hreflang to itself) or one page with anchors
     or a canonical to the parent. Each Ek row gives the parent and the signs seen.
     (3) *Form steps are not told to 301:* a group of second addresses with a step of an application or form (its
     address names başvuru/application/form/kayıt/register/checkout/adım/step/kimlik-bilgi/-bilgileriniz or ends -kk, a
     step query sw/step/adim/stage, or the page holds a form whose action is not a search) is `idx8.form_step_copies`
     (IDX-8, Low): canonical to the main step or noindex, never a 301; `idx8.self_canonical_copies` (301) stays for the
     other alias addresses. The judgment layer's "compare purposes" does not apply to either. Each row has its own fix.
     (4) *The sitemap-errors card takes the redirects to an error page* (`team_rules.settle`, after the broken-link split
     live in `final.settle`, offline in `_decisions_343`): per address the status chain and a suggested 301 target (the
     live page read sharing at least a quarter of the words of the address's last segment with its own address and
     title, nearer folders first; else the nearest page read above it; else 410), as the Ek row's value and its own fix;
     when they redirect to an error page the card's first two steps say "301 to the suggested page, else 410" and "the
     server answers 404/410 itself". The separate `idx1.error_redirect` card keeps only addresses no other card lists
     (Maya's made-up address).
     (5) *Application and sign-in redirects are a note:* a link whose target's first answer is a temporary redirect
     (302, 303, 307) and whose address or end names an application, sign-in or session step (basvur, application, apply,
     login, giris, signup, kayit, register, checkout, sepet, cart, oturum, session, auth, hesap-ac, musteri-ol) is
     `idx6.links_to_flow_redirect` (Info, estimated): the chain, that Maya asked as a new visitor with no cookie, and how
     to check (DevTools > Network with "Preserve log" in a private window, or httpstatus.io). Other links to a redirect
     stay `idx6.links_to_redirect`. Offline, `_decisions_343` recomputes these from the saved pages (replacing the
     DECISIONS 343 findings) for both reassessment paths.
     *Review 3 kept:* `docs/expert-reviews/enpara-fee70191-review3.json` (15 cards: correct 9, wrong 3, incomplete 3;
     per-card note, the evidence's assessment and the fix), ACCURACY regenerated (43 cards, 51% correct).
     *Checklist:* SEO-041 and -049 add `idx8.form_step_copies`; `str1.sections_as_pages` takes the old sub-page rules'
     places (SEO-043, -064, -065, -145).
     Tests: `tests/test_expert_review_344.py` (9); updated `test_team_rules_343`, `test_head_rows_341`, `test_head_card_339`.
345. **The sitemap-errors card's 301 targets: within the section, the closest existing parent, words only when clearly
     better, "kontrol edin" when weak; the flaky sitemap-order test (Owner, 2026-11-12: the five weak enpara targets, the
     four rules, "existing" including sitemap addresses and known 200s; the shares and the firm/weak line are agent
     defaults).** Global rules for every audit; enpara fee70191 was only the test case.
     (1) *Known live addresses* (`team_rules.known_live`): pages that answered 200 (read: with their title), sitemap-check
     answers of 200 without noindex, and sitemap addresses no request showed to fail; never one of the missing
     addresses, an error page, or an address that answered anything but 200.
     (2) *The target* (`team_rules.suggest_target`): only inside the missing address's top section (its first folder:
     /sirketim stays /sirketim, /en stays /en; an address at the top stays at the top). The direct parent when it is
     known (firm, also when only the sitemap lists it: "site haritasında, bu denetimde okunmadı"), unless a page in the
     same folder shares at least 60% of the words of the address's last segment (with its own address and title).
     Without a direct parent: a page of the section sharing at least half the words (firm when this audit saw it answer,
     else "kontrol edin": a sitemap-only page may be another broken entry of the same list); else the closest known
     parent further up ("kontrol edin"); else a page sharing a quarter of the words ("kontrol edin"); else 410. A weak
     row says "önerilen hedef (kontrol edin): X (why)" and its fix "X uygunsa 301 ile oraya yönlendirin, değilse 410
     döndürün". `evidence.suggestion_rule` = 345 marks the rows made this way (an older card's are made again).
     *enpara fee70191 (21):* 15 firm, 6 "kontrol edin", no 410; the five weak ones now: /kartlar/enparacom-kredi-karti
     (direct parent), /sirketim/kartlar/kredi-karti (same section, kontrol edin), /sirketim/hesaplar/altin-hesabi,
     /odemeler/islem-kisitlari and /sirketim/hesaplar/gunluk-hesap (direct parents the sitemap lists).
     (3) *The sitemap sample test* (`test_round2_sitemap_and_llms`) compares which addresses were asked (and their
     spread over the sections, counted), not the order the four requests in flight were logged in: CI run 43241573282
     failed once on that order.
     *Also fixed:* an audit with no redirect at all (an empty `redirects` list) no longer rebuilds the records from pages.
     Tests: `tests/test_redirect_targets_345.py` (7); `test_expert_review_344` follows the direct-parent rule.
346. **"Bağlantı yerleri" gives each missing sitemap address the card's 301 target (Owner, 2026-11-12: the same target
     and reason as "Bulgu bazında", "(kontrol edin)" kept where weak; the cell's wording and keeping the generator advice
     after the target are agent defaults).** The sheet's "Önerilen hedef" for a sitemap row now reads the sitemap-errors
     card's suggestion for that address (`link_places` passes `target`, `target_basis`, `target_firm`,
     `target_known_as` from `evidence.suggestions`; `team_rules.target_words` words it): "301 → /x (üst klasör
     sayfası)", "301 → /x (kontrol edin; en yakın var olan üst sayfa)", "410 (ilgili sayfa yok)", with "; site
     haritasında, bu denetimde okunmadı" where the sitemap alone lists the target, as in "Bulgu bazında". An address the sitemap generator made from a
     heading (DECISIONS 337) keeps "; site haritası oluşturucuyu düzeltin" after its target; the heading stays in "Olası
     neden". A row with no suggestion (an older card) keeps the old words. enpara fee70191: 21 of 21 rows with a target
     (15 firm, 6 kontrol edin; 13 also "oluşturucuyu düzeltin").
     Tests: `tests/test_where_targets_346.py` (2); `test_link_places_337` follows the new cell.
347. **The review of the atasunoptik audit (Smart ~150, 149 pages read) as global rules (Owner, 2026-11-16: the six
     points; the word lists, shares and thresholds below are agent defaults).** atasunoptik f06a2129 was only the test case.
     (1) *Links to a page behind a sign-in are a note:* a link whose target's first answer is a temporary redirect (302,
     303, 307) and whose address names an account, order or membership page (`page_groups.account_segment`: /uye,
     /hesabim, /siparislerim, /PlusLogin …), or whose redirect ends at a sign-in page or carries a return address
     (?ReturnUrl=, ?next=, ?redirect= …), is `idx6.links_to_login_redirect` (Info, "(beklenen)"): no card, and its fix says
     there is nothing to change (never "kaldırın"). It is checked before the application-step note (344). The other
     links to a redirect stay `idx6.links_to_redirect`, each page's row now naming its own step with the final address
     (`page_fixes`: "Bağlantıyı doğrudan son adrese verin: /eski → /son.").
     (2) *A robots.txt block of AI training bots only is a policy check:* the title's role picks the rule
     (`acc2.training_block.sitewide` / `.sample` for training bots; `acc2.blocks.*` for search and live-fetch bots, which
     stay a problem and an automatic P0 when sitewide). The training rules are "Kontrol edin" (issue type warning), not in
     the P0 rules nor the sector method's robots check, and a card made only of them is at most P2
     (`priority_levels.POLICY_RULES`); a person may still set P0 by hand.
     (3) *A file is never a page:* an XML, feed or data address (any `.xml`, `.xml.gz`, `.rss`, `.atom`, `.json`, `.txt`,
     `/feed`), or a response whose media type is not HTML, is not a page read (`client_selection.not_a_page`), is never
     typed or scored, and is not a row of "Sayfa bazında"; its findings' rows say "—" for "Okundu mu?" and no page type.
     A host-level finding counts every such file as the site's (atasunoptik's /kurumsal.xml had been taken for a page).
     (4) *Page types from what a page is:* (a) an og:type on at least half of the pages read (four or more) is the site's
     default and no longer types a page (`page_groups.og_default`); such a page is a product only with a price and a buy
     control of its own, its own Product markup with an Offer, or a product folder (/products/…); (b) an item address with an id (a name of four or more
     words, two of them holding a digit, then `_` or `-` and four or more digits: …-0ax2034s-600087-…_82087) is a
     product; (c) a page linking, outside its menu and footer, to three or more item addresses is a category, and a page
     linking to none is not lent "category" by its template; (d) a store or branch page (place markup such as Store,
     LocalBusiness, Optician with PostalAddress, GeoCoordinates or OpeningHoursSpecification; or an embedded map with
     opening hours) is the new general type `location` ("mağaza / konum"), which each profile's place type (E-ticaret's
     stores, clinics, branches, dealers, service areas) takes; (e) the E-ticaret profile is suggested when product and
     category pages are at least 30% of the pages typed and five or more (`suggest.page_types` in its profile, +4).
     `page_groups.METHOD_VERSION` 3 and `business_types.VERSION` 3: a saved audit's grouping and suggestion are worked
     out again offline (`reassess_rules._decisions_347`, both reassessment paths).
     (5) *Misspelt addresses of a page:* an address in the same folder as a page read, its last segment one small edit
     away (up to two characters in one place, not a number, ten characters or more), answering 200 with content of its
     own and naming itself canonical, or redirecting somewhere else than that page, is `idx8.typo_copies` (Medium with a
     200 copy, else Low). The real page is the one more pages read link to (the misspelt one: under a quarter of them),
     else the one the sitemap lists; each row gives it as the 301 (or canonical) target. atasunoptik:
     /inesta-marka-gunes-gozlugu-modellerix (200, its own content) → /inesta-marka-gunes-gozlugu-modelleri;
     /cocuk-gunes-gozlugu-modelleri- answered 301 to /gunes-gozlugu in this crawl (not 200), so its row says to point the
     redirect at /cocuk-gunes-gozlugu-modelleri.
     (6) *Account pages and the homepage:* an account, sign-in or order address is utility under every profile (at most
     20); the homepage (and its language versions) is always the most important page: one scoring below another page
     takes that page's importance (`page_groups.home_first`, "raised" in its parts) and comes first in the order.
     *Also:* the AI brief's payload leaves out the per-page steps of the links to a redirect (`page_fixes`, the same as
     the evidence's targets); the recommendation catalogue has a note for each new rule.
     Tests: `tests/test_shop_review_347.py` (50, a fake shop on loopback); `test_page_groups` (method 3) and
     `test_web_app` (a training-bot title sample) updated.
348. **A site that rate-limits Maya's crawler: the reader takes the whole plan, Maya waits up to 90 s once per host,
     and each source says what it read (Owner, 2026-11-16, after naturesgarden.net's three runs 7549f7ce, f105ec3c and
     9269c4f8 each read 7 pages: the four points; the 90 s, the 1.0-1.5 jitter and the wording are as asked or agent
     defaults).** Global rules; naturesgarden was only the test case.
     *Why 7 (from the saved data, the same in all three runs):* Maya's crawler read 6 pages, then /collections/all
     answered 429 with Retry-After: 60 (over the 30 s cap) and the crawl stopped. Firecrawl was asked for 7 addresses
     and read all 7 (status 200 each; 0 × 403, 0 × 429, 0 challenge pages; `known_urls_not_requested` 0,
     `sitemap_addresses_found` 0, 368 sitemap and 390 discovered addresses known). The other addresses were never sent:
     the Akıllı plan's "needed" reading (DECISIONS 327) reads only pages Maya asked for and could not read, plus one per
     template, and Maya had asked for only those 7. Züber (2bf9b1ce, also stopped by a rate limit) read 148 because Maya
     had read only 2 pages there, so its crawl counted as blocked, and a blocked crawl skips the "needed" scope.
     (1) *The reader after a stop* (`firecrawl.reader._read_pages`): when Maya's own page requests stopped on a rate
     limit or a block (`_maya_stopped`), the "needed" scope is not applied: the plan's addresses in its order, then the
     links and the sitemap, go to the reader up to the page limit (pages Maya read count against it, DECISIONS 316),
     within robots.txt. `firecrawl.scope` says so (`mode: all`, `maya_stopped`). Firecrawl's own 429, and the site's
     429 seen through Firecrawl, now ask for that page once more after `RETRY_WAIT_S` × a jitter of 1.0-1.5 (the retry
     queue kept in time order); the reader's concurrency still steps down on each (DECISIONS 295). naturesgarden
     9269c4f8 would now hand the reader up to 144 new pages from 384 known addresses Maya did not read.
     (2) *Maya's own crawler* (`crawler.py`, `CrawlConfig.long_retry_after_s` 90): a Retry-After over 30 s and up to
     90 s is waited out once per host, then the page is asked again; a second long one on that host stops the crawl
     ("… asked Maya to wait 60s (Retry-After) again, after the one long wait of 60s allowed per host"); over 90 s stops
     at once as before. The start page keeps its 120 s (DECISIONS 286).
     (3) *Per source* (`read_sources`): a "Kaynaklar" line first in the coverage section: Maya's direct crawler (page
     requests, read, block pages, 429s, why it stopped) and Firecrawl (the same, plus known addresses not requested, or
     "kullanılmadı"). Shown in the Ek's "Kapsam", the team report's limits and the web app's audit summary (C6). The
     block-pages line now says "engel sayfası ya da 429" (it counts both). 9269c4f8: "Maya'nın doğrudan tarayıcısı: 7
     sayfa isteği, 6 okundu, 0 engel sayfası, 1 × 429 (hız sınırında durdu). Firecrawl: 7 sayfa isteği, 7 okundu, 0 engel
     sayfası, 0 × 429."
     *Not rebuilt offline:* the pages the reader would now read need Firecrawl calls (paid); only the coverage lines and
     the count of addresses it would get are made from the saved data. The team report of 9269c4f8 is refused before
     and after this change by an older check ("Teyit edin" title naming /cart, not among the report's addresses).
     Tests: `tests/test_rate_limit_handoff_348.py` (13); `test_rate_limited_start` (a later page now waits 60 s once).
349. **The appendix and sector downloads of a blocked report, and the cause of the block on naturesgarden.net (Owner,
     2026-11-16: in Chrome "Download the appendix (Turkish)" and "Download the sector audit" ended as "Site wasn't
     available" and saved "xlsx.json"; the fixes and the draft file are agent defaults).** Global rules.
     *The error* (342a0b14, reproduced with the app's own code on a copy of the audit and the app's database): both
     `GET /audits/{id}/downloads/xlsx?lang=tr` and `/downloads/sector` answered **409 `release_blocked`**: "The release
     gate blocked this report (1 hard violation). It can be downloaded only as a draft (add draft=true)", rule RG-7:
     "STR-3-58e82347 gives content advice for …/blogs/recipes/dried-cranberry-walnut-salad, a page of type unknown". The
     page's buttons are plain links, so the browser saved the JSON error as "xlsx.json". The run itself was the first
     after 4a480f9: Maya read 6 pages (429 after 7 requests), Firecrawl read 146 (DECISIONS 348).
     (1) *Blog posts with a product widget are not products* (`structure.product_template`, `BLOG_FOLDERS`): Shopify's
     /blogs/ folder joins the article folders for the price-and-buy-button rule (26 recipe and tip posts showing a
     product card with a price and ADD TO CART were "product" pages missing Product markup).
     (2) *A page only the reader read has the kind its check gave it* (`structure.annotate_page_types`,
     `evidence_page_kinds`): `Finding.page_types` took kinds from Maya's own pages only, so every reader-only page was
     "unknown" and any content advice on it a hard RG-7 violation; the kind the finding's evidence records (`page_kind`)
     is used instead of "unknown".
     (3) *Saved audits* (`reassess_rules._decisions_349`, both reassessment paths): STR-3 rows of a page in a blog or
     article folder taken for a product by its price and buy button alone are left out (a finding with none left goes;
     the count, scope and id follow), and unknown page kinds are filled from the evidence. 342a0b14: STR-3-58e82347
     (26 blog posts) removed; the gate PASSES.
     (4) *The team's working files never download as JSON:* the appendix and the sector file are served as the marked
     draft ("-draft.xlsx", `X-Maya-Release-Gate: BLOCKED`) when the gate blocks, because they come from a plain link;
     the client's report forms (PDF, Markdown, JSON, client export) stay refused without `draft=true` (DECISIONS 280).
     Tests: `tests/test_download_blocked_349.py` (7).
350. **The review of the isbank audit (Smart ~150, Bankacılık; 1b81bee4) as global rules (Owner, 2026-11-16: the
     three points; the type lists, the 80% template share and the wording are agent defaults).** isbank was only the
     test case.
     (1) *A store/location page is mainly one place* (`page_groups.location_reason`, METHOD_VERSION 4): its own place
     markup (not a type most pages read carry) with GeoCoordinates or OpeningHoursSpecification, or an embedded map with
     opening hours or coordinates; a PostalAddress alone no longer counts (any organisation's markup has one), and a
     page with product, offer, loan, account, card, service or application markup (`NOT_A_PLACE_TYPES`) is never one.
     isbank's /ihtiyac-kredisi and /ek-hesap (BankOrCreditUnion + PostalAddress beside LoanOrCredit, Offer, FAQ) and
     /?efl--edit=1 were "location" (DECISIONS 347's rule); now none; atasunoptik's three store pages stay.
     *The Ek's page types follow the profile* (`page_rows.page_kind_of`, `type_word`): with a business profile, each
     row's type is the profile's (its own label, as the sampling and the key pages use them), the general type only for
     a page the profile did not match; the same in the web app's affected-pages list. isbank "Sayfa bazında": before
     diğer 123, kategori 4, mağaza / konum 3; after Finansal ürün ve ürün listesi 42, Destek 39, diğer 32, Ücret ve
     başvuru 11, Hesaplama aracı 9, Rehber / SSS / blog 5.
     (2) *One template link, named* (`stage8_rules.template_link`): cards 7 (`idx6.alias_links`) and 8
     (`idx6.links_to_redirect`) were two different links, each a template link on (nearly) every page read, not one
     link counted twice: the footer's "Çerez Ayarları" → /?efl--edit=1 (canonical /) on 122 pages, and the menu's
     "Kredi" → /internet/MainPageEnter.aspx?…site=megamenu (301 → personalloanapp.isbank.com.tr/?amount=50000&term=24)
     on 124. When one target is linked from at least 80% of a finding's pages (5 or more), the finding's evidence holds
     `template_link` (its address, most common text, menu/footer/content, and the final address or canonical), and the
     card's first two steps say it: "Şablonda alt bilgideki “Çerez Ayarları” bağlantısını bir kez değiştirin" / "Yeni
     adresi: www.isbank.com.tr/". A saved alias-links card gets it offline (`reassess_rules._decisions_350`); the
     redirect card is made again from the saved pages (DECISIONS 343).
     (3) *The block-pages line* (`client_selection.block_pages_line`, `client_appendix.block_pages_text`): the reader's
     limit is on pages Maya did not read, so its new pages are counted apart from Maya's pages it read again: "sayfa
     okuyucu Maya'nın okumadığı en çok 2 yeni sayfa okuyabilirdi, 0 yeni sayfa okudu (ayrıca Maya'nın okuduğu 91 sayfayı
     yeniden okudu)" (before: "en çok 2 sayfa okuyabilirdi, 91 sayfa okudu").
     Tests: `tests/test_bank_review_350.py` (14); method version 4 in `test_page_groups`, `test_shop_review_347`.
351. **The follow-up on the isbank audit: entry links are kept, platform advice only on its platform, CMS edit
     addresses are not pages (Owner, 2026-11-17: the three points; the word lists, the P3 cap's wording and the Kapsam
     sentence are agent defaults).** Global rules; isbank (1b81bee4, rebuilt with f5d8066: the "690098d9" named in the
     review is not an audit id in the history; this audit's current-engine copy was used) was only the test case.
     (1) *Sign-in and application entries* (`stage8_rules._entry`, `idx6.links_to_entry_redirect`): a link to an
     address that redirects (any status) whose address, query or end names a sign-in, internet banking, application or
     sign-up entry (login, giris, internet şubesi, MainPageEnter, basvuru, application, apply, signup, register, kayıt,
     üye ol, müşteri ol, hesap aç, onboarding), or whose redirect ends on another host named like an application or a
     sign-in (app, login, online, internet, şube, secure, auth, apply, portal), is its own rule: Low, "Kontrol edin",
     at most P3 (`priority_levels.RULE_CAPS`); the fix keeps the link and only says it may point straight at the final
     address when the redirect is permanent; a template link's steps say "Şablonda menüdeki “Kredi” bağlantısını tutun;
     kaldırmayın" / "Son adresi: …". It is checked after the sign-in (347) and application-step (344) notes.
     *Never "kaldırın" for a link to a redirect:* "Bağlantı yerleri" gives such a link the address its redirect ends
     at, also when the crawl did not ask that address (another host); a broken menu or footer link is "bağlantıyı
     çalışan sayfaya verin (menü bağlantısı kalmalı)", never "kaldırın" (`link_places`, `fix_nav`).
     (2) *Platform advice only on its platform* (`quick_rules.alias_fix`): the alias-links fix gives Shopify's step
     ("within: collection") only when the platform is Shopify or the links are Shopify's /collections/…/products/…;
     else "change the links to name the canonical address; when a template builds them (a menu, a footer, a card),
     change it there, once". Saved findings are rewritten (`reassess_rules._decisions_351`). The card's links are
     rows of "Bağlantı yerleri" (`link_places.ALIAS`): page, link text, place, written href and the canonical as the
     suggested target.
     (3) *CMS edit and preview addresses* (`urls.edit_preview`: efl--edit, edit, preview, preview_theme_id,
     elementor-preview, vc_editable, et_fb, fl_builder, customize_changeset_uuid, wcmmode … and any key ending
     "--edit"/"-preview"): the crawl folds a link to one into its clean address (asked once, under that address); a
     saved one is no page read (`client_selection.not_a_page`), is not typed or scored (`page_groups` METHOD_VERSION
     5), and is no row of "Sayfa bazında"; the alias-links card still names links to it, with the clean address as
     their canonical; Kapsam says how many were read or linked ("CMS düzenleme/önizleme adresleri ayrı sayfa
     sayılmadı: 1 okunan, 2 bağlantı verilen adres (/?efl--edit=1) …").
     *isbank, before → after:* card 8 "Bağlantıları doğrudan son adrese verin" (P2, Sorun; 124 "Önerilen hedef:
     kaldırın") → "Giriş ve başvuru bağlantılarının yönlendirmesini kontrol edin" (P3, Kontrol edin; 124 rows to
     personalloanapp.isbank.com.tr/?amount=50000&term=24); card 7 keeps its place and steps, its "Ne yapılmalı" loses
     the Shopify text, and its 139 link rows are in "Bağlantı yerleri"; pages read 148 → 147; card 15 sameAs (the
     homepage and its edit copy) → "Videodaki mesajı sayfaya metin olarak yazın" (sameAs now reaches one page).
     Tests: `tests/test_bank_followup_351.py` (19); method version 5 in `test_page_groups`, `test_shop_review_347`; the
     alias fix as a run-time choice in `test_wording`.
352. **Maya data in the audit: Search Console, AI citations and competitors as appendix sheets (Owner, 2026-11-17,
     requested by Efsa, reviewed by İlginay; the sheets follow Efsa's Enpara file "0", "B1", "B2", "C1", "C2", "D1" and
     "Z"; dataset handling, word lists and the share-of-voice formula are agent defaults).** Global for every brand and
     business profile; Enpara was only the test case.
     *Input* (`maya_audit/maya_data.py`): the Maya export datasets attached to an audit (files, a folder or a zip),
     matched by the dataset name in "<domain>-<dataset>[-<from>-<to>].csv|jsonl|json" (22 known names; others listed as
     not used). The export's domain (file names and meta.json) must be the audited site's, else refused
     ("Maya verisi başka bir siteye ait …"). Large files are read as a stream (citation-mentions 1.46 M rows / 411 MB
     and result-items 326 MB in about 20 s) into one summary kept beside the report (`maya-data-summary.json`); from
     meta.json only the domain, brand names, competitors (names, domains, aliases) and prompt label names are kept,
     never a name, an e-mail address or account/integration data. Web app: an optional "Maya verisi" card in the
     downloads (each file sent as it is to `PUT /audits/{id}/maya-data/files/{name}`, the only non-JSON body the server
     accepts, still behind the cookie and the action token; `POST /audits/{id}/maya-data` reads them, `GET`/`DELETE`);
     CLI: `build_data.py --maya-data PATH … [--maya-fetch]`.
     *Search Console rules:* a 28-day snapshot row (gsc-page-scores, gsc-top-queries, gsc-query-opportunities) is never
     summed: the latest row per page or query is used; daily rows (gsc-search-performance, gsc-daily-stats) are summed;
     gsc-top-pages' weekly sample is a column of its own, never mixed in; every block names its dataset and period;
     brand vs non-brand queries from the brand's names; device and country splits when the dataset has them.
     *Sheets* (`maya_audit/maya_sheets.py`, after the reader sheets, Turkish): "Genel durum" (monthly clicks,
     impressions and position with the average weekday for months of unequal length, Monday–Friday weeks, brand share
     of AI citations per month, per provider share of voice and citation share, topic visibility brand vs leader with
     gap, most cited other domains); "Organik×AI - Özet" and "- Segmentler" (one row per page joining GSC, AI citations
     and the crawl; Efsa's segments 3, 1, 1b, 4, 2, 2b, 5, 6, 0 with thresholds from the site's own quartiles,
     importance 0–100 = 40 × impressions percentile + 40 × AI prompt percentile + page-type weight; duplicates such as
     /anasayfa or a page canonical to another merged into the clean main address and listed; "not in GSC" = not
     measured; "Satırlara git" links); "Sayfa detay" (top 40 by importance: GSC, prompts, title, meta length, H1, H2s,
     main-text words, tables, FAQ schema questions, numeric values, date signal, schema types, first sentence,
     competitor pages cited for the same prompts, rule-based findings and action, from the crawl's record and saved
     evidence); "Rakip - Konu" and "Rakip - Sayfa yapısı" (per topic: prompts, n < 10 only an indication, brand
     citation share and pages, visibility brand vs leader and gap, top domains, top competitor-brand and comparison
     page, insight, action, 2 sample prompts, sorted by gap; brand vs competitor vs comparison page structure with
     "Fark [HİPOTEZ]"). Topics: Maya's prompt labels, else the visibility topic whose name words the prompt holds;
     generic words Topic Pulse reports as competitors ("maid", "handyman", "urban" alone) are no competitor. Pages the
     crawl did not read and up to 3 external pages per topic are measured only when fetched once by `enrich`
     (polite, robots.txt, public addresses, browser identity, never counted toward the audit's page limit; the web
     app's tick or `--maya-fetch`), else "okunmadı" / "alınamadı". Each sheet whose datasets are missing is left out and
     Kapsam names the missing dataset; no Maya data: "Maya verisi eklenmedi". "Nasıl okunur" has a line per sheet, Kapsam
     the datasets and periods, Yöntem the formulas and thresholds and "korelasyon nedensellik değildir".
     *Share of voice* (result-items, optional): the brand's mentions over all brand mentions in the answers (the brand
     and each answer's comparisonBrands), per provider and month; without result-items the column is "—".
     *Not done:* the brand's position in third-party lists is "—" (not read from the pages); the per-prompt competitor
     columns keep the 40 most cited addresses per prompt.
     *Enpara (fee70191 with the exports in ~/Downloads, 15 Aug – 13 Nov) vs Efsa's file (13 Aug – 11 Nov):* GSC
     September/October and AI citation rows September/October equal (501069 / 7889507, 443676 / 5920594; 595542 /
     34407, 372611 / 22078); August and November differ by the two days the exports differ; provider citation shares
     equal within rounding (ChatGPT 0.0692); top cited domains equal (Garanti 389, İş Bankası 388, Akbank 369, Ziraat
     361; Yapı Kredi 369 vs 368); AI thresholds equal (≥ 15 prompts strong, < 7 few); AI prompts per page equal on 103
     of the 125 pages both list (±1–4 from the period). Her Monday–Friday weeks from 13 Oct are Tuesday–Saturday (a
     one-day shift); this file's are Monday–Friday. Share of voice is not hers (0.04–0.08 vs 0.09–0.19: her source is
     not in the exports). Not comparable until exported: gsc-page-scores (or gsc-search-performance), so every page is
     "GSC'de ölçülmedi" and segments 3/1/4/6 and the GSC part of the importance are empty (Sayfa detay shares 8 of her
     37 pages); topic-visibility-snapshots and competitor-mentions-daily, so the two competitor sheets are left out;
     meta.json, so no prompt labels or brand aliases.
     Tests: `tests/test_maya_data_352.py` (15, fake exports and a made-up crawl; no live request).

353. **The finding catalogue for the SEO team and a text check on every report (Owner, 2026-11-17, requested by
     İlginay, SEO reviewer: the explanation and recommendation language "reads too AI-like and is sometimes wrong";
     rule numbering, hard/soft split, the phrase list's first entries and the second reader's model are agent
     defaults).** Global for every audit; the six saved audits were only test cases.
     *Catalogue* (`maya_audit_web/finding_catalogue.py`, `scripts/finding_catalogue.py export OUT.xlsx --home
     ~/.maya-audit/web`): one XLSX ("Nasıl kullanılır", "Bulgular", "Yasaklı ifadeler") with a row per rule
     (319), per variant (Shopify/WordPress steps, region steps: 16), per merged card (9), per Note-card topic (25), the
     generic text (1) and per checklist item (165): 535 rows. Columns: key, kind, rule id, family and its Turkish name,
     severities seen, priority cap, issue type, the Turkish title, finding, "Neden önemli", "Ne yapılmalı" (sentence
     and "- " steps), verify, the engine's finding sentence in Turkish and English with its placeholders, evidence
     fields seen, business profiles (the sector method's core and sector checks), platforms, number of variants, how
     many saved audits triggered it and one real Turkish sentence (saved reports are only read, the current-engine copy
     when there is one), the source files; then empty "Yeni başlık", "Yeni açıklama", "Yeni öneri", "Yeni bulgu
     cümlesi", "Not". "Yeni bulgu cümlesi" was added to the four asked for: it is the sentence with {n}/{url}
     placeholders a rewrite could break.
     *Import* (`scripts/finding_catalogue.py import EDITED.xlsx [--dry-run] [--report diff.md]`): only rows with a
     "Yeni …" cell change anything. Yeni başlık -> the card title where it is shown (rule_actions.json when the
     approved catalogue has one, else texts/tr.json; merge_group_texts.json for merged cards; checklist_items.json for
     checklist items); Yeni açıklama -> "Neden önemli"; Yeni öneri -> first line "Ne yapılmalı", "- " lines the steps
     (to the file the shown steps come from); Yeni bulgu cümlesi -> locales/findings/tr.json. Refused (and listed, the
     rest still written): a placeholder added, dropped or renamed, unbalanced brackets, a digit where the old text had
     none, a length over the field's limit (title 80, why 170, explanation 150, step 75, 2–4 steps), a different step
     count where steps carry conditions (step_when), an unknown key. Notes are listed, never written. The diff report
     shows old -> new per file and field. Excel/Google Sheets files are read (`xlsx.read_any`: shared strings, rich
     text, relationship-named sheets). The texts were already data files except the merged cards' title, finding and
     fix, which moved from `client_selection.py` to `maya_audit/merge_group_texts.json`.
     *Text check* (`maya_audit/text_gate.py`, the release gate's RG-18 to RG-23, version text-gate-1): runs on the team
     report's data before every team PDF, client brief, XLSX appendix and sector download (provider-free):
     RG-18 hard: a placeholder left, or a number in a card that none of the card's own findings holds; RG-19 hard:
     platform advice (Shopify, WordPress, …) on a site the report does not name as that platform (WordPress counts for
     WooCommerce; evidence naming the platform allows it); RG-20 hard: "remove" for a menu/footer link or a link to a
     sign-in/application/cart entry, or a step saying so; RG-21: English in Turkish text (hard in a card's own lines,
     soft elsewhere; quoted site text, tags and addresses are not read; the appendix's untranslated sentences soft);
     RG-22 hard: two cards with one rule or one title on the same pages; RG-23 soft: a phrase from
     `maya_audit/banned_phrases.json` (the SEO team edits it: text, lang, block, why, instead; whole words, Turkish
     i/ı), hard when "block": true. BLOCKED makes the download a marked draft, never a refusal: the team PDF says
     "TASLAK" in every footer, the brief has a "TASLAK" mark on every page, file names end in "-draft", header
     `X-Maya-Text-Check`. The appendix's last sheet "Kontrol raporu" lists the result, each finding (rule, blocking,
     card, place, message, text) and the second reader's suggestions. The existing release gate (RG-1–RG-17) and its
     saved decision are unchanged.
     *Second reader* (`maya_audit_web/team_report/llm_review.py`): off by default; on only with `--llm-review`
     (`scripts/text_check.py`) or `MAYA_AUDIT_LLM_REVIEW=1`, and a key `MAYA_AUDIT_ANTHROPIC_API_KEY` (environment,
     then the .env file). Claude Opus 5.5 with structured output and the server-side refusal fallback reads each card's
     lines and its findings' evidence and flags unclear or unnatural Turkish and claims the evidence does not support;
     it only suggests ("Kontrol raporu", never blocking, never editing). The `anthropic` package is not installed in
     the venv (no install without the owner's approval): until it is, the review says "not available". Tests use a fake
     client; conftest clears the key.
     *Run on the saved audits* (copies in the scratchpad; `scripts/text_check.py` and the appendix built as the download
     builds it): Enpara fee70191 (80 findings, 15 cards) PASS; Atasun f06a2129 (55, 15) PASS; Züber 2bf9b1ce (43, 9)
     CONDITIONAL: one engine line left in English in the coverage limits and the appendix ("Cloudflare rate-limited
     Maya's direct crawler on 1 of 2 request(s). 148 page(s) were read through Firecrawl instead…", no Turkish
     entry yet); MMI 536b4b64 (56, 15) PASS; Nature's Garden 342a0b14 (49, 8) PASS; İş Bankası 1b81bee4 (63, 15) PASS.
     Planted problems in a copy of Atasun's cards (an invented number, a Shopify step, a menu link to remove, English in
     a card, a repeated card, "kritik öneme sahiptir") were all found. Catalogue on the 79 saved audits: 223 of the 319
     rules were triggered at least once.
     Tests: `tests/test_text_check_353.py` (20; made-up cards and reports, a fake second reader, the demo web app).

354. **English left in Turkish reports, swept over every saved audit (Owner, 2026-11-17, after DECISIONS 353's check
     flagged Züber; Turkish wording is agent-written for the SEO team's catalogue review).** Global for every audit.
     *Cause of the Züber line:* the Kapsam/coverage line of a page reader ("Cloudflare rate-limited Maya's direct
     crawler on 1 of 2 request(s). 148 page(s) were read through Firecrawl instead…") was worded with no check id
     (`title(None, …)` in `build_data` and `client_appendix`), so ACC-9's Turkish frames were never tried. The coverage
     line now carries its check id (`client_selection`, default ACC-9) and both readers pass it.
     *Sweep:* every saved audit on this computer (79, copies of their reports; the web home only read), the team
     report's data and the XLSX built as downloaded, every sentence shown untranslated collected. Found 16 older
     wordings, from reports an earlier engine wrote, with no Turkish entry: ACC-1 "…server error or was unreachable on
     N of M fetches", RND-4 "N page(s) embed content in an iframe; its text is not part of the page", ACC-9 "<CDN>
     challenged Maya's own crawler (an unverified bot)…", STR-14 shared-link titles that repeat their details after
     " — ", three older fixes (robots.txt 5xx or unreachable, "Nothing needs fixing for this audit…", the other-domain
     links), lines "host could not be resolved safely", robots.txt "disallows it" / "is unavailable" after an
     unexpected 301, "--check-external-links", and two current lines of the offline reassessment (a form control beside
     a grid; its label). Older titles go into `wording.SAVED_TITLES` (matched after every current frame, never a rule id;
     Turkish in the language file's new `saved_titles` section); a title with " — " details is worded by its head;
     the rest are ordinary `fixes`, `labels`, `lines` and `line_patterns` entries. After the change the sweep finds no
     English sentence in any of the 79.
     *Found on the way:* 26 older saved audits could not build a team report at all (`external_scripts` saved as a
     number, `page_measures.measure` expected a list); a number is now ignored. A date in a card's status
     ("elle teyit edildi (2026-11-05)") is no longer read as a count by RG-18. Left as found (RG-22, real): two cards
     with the same title on the same pages in three moodisthastanesi.com audits (str11.two_values, 9156e1fd, e346db8d,
     b366e1c3) and one adilehanim.com audit (idx2.no_redirect, 88aff6d1); their downloads are drafts until the cards
     are merged or told apart.
     *Catalogue:* exported to ~/Downloads/bulgu-katalogu.xlsx (535 rows: 319 rules, 16 variants, 9 merged cards, 25
     Note topics, 1 generic, 165 checklist items; 223 rules seen in the 79 audits). The second reader stays off: the
     `anthropic` package is not installed until the SEO team has rewritten the catalogue (owner).
     Tests: `tests/test_english_lines_354.py` (4).

355. **One title, one card (Owner, 2026-11-17, after DECISIONS 353/354 flagged repeated cards).** Global for every
     audit; moodisthastanesi.com and adilehanim.com were only test cases.
     *Rule* (`client_selection.same_card`, in `groups()` so the PDF, the brief, the XLSX and the sector file agree): two
     groups that would print the same card title (the approved catalogue's, else the text library's: `card_title`) on
     the same pages (paths, as RG-22 reads them) in the same state (intent, to confirm, re-test, Info) are one card when
     they are one problem: the same rule, or rules with the same steps (`card_steps`). Both findings, their evidence
     lines and every host stay on the card. Different problems (other steps) stay two cards, and each card's title adds
     its finding's short name from the text library ("<title>: <summary>"). Merge groups and redirect chains are left as
     they were. A finding whose rule id cannot be found (older reports keep none; it is read from the title with
     `rules.rule_id`) is never merged. A merged host-level card names every member's host.
     *Cause:* findings of one rule are kept apart by their dedup key (one per field, one per host) while the card title
     comes from the rule, so the cards repeated their title.
     *Before -> after* (saved audits, scratch copies; team report as built today vs the previous commit):
     moodisthastanesi.com 9156e1fd, e346db8d, b366e1c3: cards 3 and 4 "Çelişen yapısal veri değerlerini giderin" (one
     for dateModified, one for name, the same 2 pages) -> one card 3 with both findings and both lines; text check
     BLOCKED (RG-22) -> PASS; cards 15 -> 14, 15, 15 (the freed place is taken by the next card when there is one).
     adilehanim.com 88aff6d1: cards 12 and 13 "http adreslerini https adreslerine yönlendirin" (www.adilehanim.com,
     adilehanim.com) -> one card naming both domains; the three Open Graph notes on the same 51 pages (og:title,
     og:description, og:image) -> one note; text check BLOCKED -> PASS; cards 15 -> 14 (no candidate left).
     All 79 saved audits: the text check now flags nothing.
     Tests: `tests/test_same_card_355.py` (7).

356. **SaaS / Yazılım business profile and its own checks (Owner, 2026-11-17, after reviewing www.ticimax.com, Smart
     ~150: a software company typed "Diğer", 120 of 144 pages "diğer"; signal words, weights, thresholds and the rules'
     heuristics are agent defaults).** Global for every audit; Ticimax was only the test case.
     *Profile* (`business_types/profiles/saas.json`, id `saas` kept: the team's sector method maps to it): "SaaS /
     Yazılım", eleven page types with explicit weights: fiyatlandırma 100, özellik 95, karşılaştırma 90, entegrasyon 80,
     demo / deneme 75, çözüm / sektör 70, müşteri hikâyesi / referans 60, dokümantasyon / yardım 50, blog 45, iletişim
     40, politika 15 (ana sayfa 85). The sector file's five type ids (pricing, features, sales, guide, references) keep
     their ids under the new labels. Turkish word forms added ("paketleri", "fiyatları", "özellikleri", "entegrasyonları",
     "-modülü", "referanslarımız", "tercih edenler", "iş birliği"). Selectable like the others.
     *New signals* (`business_types`, VERSION 4, so saved suggestions are worked out again): "nav", a page the homepage's
     main menu links (3 points, enough alone for the profile's feature type; used before reading by Akıllı sampling,
     at typing and offline); "cta", a demo or free-trial button on a page (1 point); for the suggestion, a demo/trial
     call to action in the homepage menu or buttons (+2) and links to an app store (+2) for profiles that ask for them
     (`suggest.trial`, `suggest.app_links`; SaaS only). An article (the page grouping's blog_article) in the folder of
     the profile's article type is that type whatever its slug says ("/blog/yeni-ozellik" is a post) — all profiles.
     *Checks* (`checks/profile_rules.py`, only when the audit's business type is SaaS; live in `final.settle` after the
     business type, offline in `reassess_rules._decisions_356` with the person's choice from `business-type.json`, which
     is now part of the current-engine copy's key): rnd2.saas_pricing_text (RND-2, Kontrol edin, S3: a pricing page's
     text holds no amount with a currency or "/ay"-type period), str3.saas_offer_schema (STR-3, Sorun, S4: prices in the
     text, no Offer/AggregateOffer/Product/SoftwareApplication), str15.saas_feature_intro (STR-15, Kontrol edin, S4: no
     80+ character line in the six after the H1, or one with no purpose or reader word: için, sağlar, size, -nız, you,
     helps …), rnd4.saas_integrations_text (RND-4, Kontrol edin, S4: 6+ content images, fewer than half of their alt
     names in the text), str15.saas_story_result (STR-15, Kontrol edin, S4: a page that calls itself a story with 150+
     words and no number with %, kat, a currency, growth or saving), acc3.saas_trial_blocked (ACC-3, Sorun, S2: a demo
     page with meta robots or X-Robots-Tag noindex, or status 400+). Text lines on half of the pages or more (a promo
     banner, a cookie notice) are not a page's own text. The text comes from the page in memory or the saved evidence;
     a page with no text kept is not judged and the rule says so. Each rule has its title frame, Turkish title, fix,
     expected and note, issue type and card texts (TR/EN).
     A company page in the menu (about, hakkımızda, kurumsal, kariyer, ekip, basın, iletişim, giriş: the feature type's
     `nav_except`) gets no menu point. Each rule also has its web-catalogue explanation (`recommendation_catalog`, TR in
     `locales/catalog/tr.json`); the brief has plain words for the new page types.
     *Found on the way:* `idx8.typo_copies`' card texts said "301" (texts hold no digits): now "kalıcı yönlendirme".
     *Tests changed:* `test_ans_scenarios::test_panel_never_changes_the_site_checks` leaves the profile's findings out
     of its fresh re-run (they need the page text the report drops after `final.settle`; the panel never touches them);
     `test_ai_skills::test_the_payload_stays_small_when_the_crawl_is_large` now asserts the payload is the report
     without its crawl plus a short summary (its "a fifth of the fat report" bound was met at 99% before; the fixture,
     a SaaS-like demo site, now has two more findings).
     *Ticimax c77ebf6d before -> after* (scratch copies; previous commit vs this build): business type Diğer (closest
     E-ticaret 4, Kart 4, SaaS 3) -> SaaS / Yazılım (9: 21 addresses with pricing/integration words, menu "fiyatlar",
     "paketleri", "özellikleri", the demo/trial call "Ücretsiz Başlayın"); page types 147 untyped -> other 64, features
     19, integrations 19, blog 11, references 7, policy 7, pricing 7, sales 6, guide 2, utility 2, demo 1, comparison 1,
     home 1 (the 64 "other" are top-level news and event posts with no date, folder or article markup, and industry
     landing pages "/<sektör>-e-ticaret-sitesi/" with no type word); key pages typed Fiyatlandırma, Özellik,
     Karşılaştırma, Entegrasyon, Demo / deneme. Top cards: 15 -> 15, "Fiyat sayfasına Offer işaretlemesi ekleyin" (4
     pricing pages) new at 6, "Yer tutucu alt metinlerini değiştirin" left the 15; Teyit edin adds pricing as text (2
     pages), feature first paragraph (4), integrations as logos (3), story results (3); no demo-page problem
     (/demo is indexable). Checklist: Geçti 50 -> 48, Sorun 21 -> 23, Veri eksik 21, İnceleme gerekli 43 -> 45,
     Uygulanmaz 30 -> 28. Text check PASS.
     Tests: `tests/test_saas_profile_356.py` (11; made-up software and shop sites); `test_business_types_311` now
     exempts SaaS from the sector file's shape (owner's change) and keeps its five ids.

357. **The Maya sheets after the Ticimax review (Owner, 2026-11-17, reviewing the Ticimax Ek with Maya data; the list
     words, the name matching and the "(adresten)" mark are agent defaults).** Global for every audit and profile.
     1. *One page type everywhere:* "Organik×AI", "Sayfa detay" and "Rakip" take the selection's page records (typed for
     the business profile) and name a type with `page_rows.type_word(page_kind_of(...))`, as "Sayfa bazında" does
     (`maya_sheets.build(..., records, profile)` from `client_appendix.sheets`). A page the audit did not read is typed
     from its address with the same profile (`sampling.pre_type`), marked "(adresten)"; files are "dosya". The importance
     weight reads the same records (pricing -> ücret, guide/sales -> destek, blog, profile types -> ürün).
     2. *Competitor brands:* a cited domain is a competitor brand's own site when its registrable name equals a
     competitor's name as a key (folded, letters and digits: "T-Soft" = tsoft.com.tr, "IdeaSoft" = ideasoft.com.tr):
     the meta's competitors and aliases, the competitor-mentions names, the Topic Pulse leaders; generic words and the
     brand's own names never. A third party is a comparison site only when its domain, address or fetched title/H1/H2s
     say it lists brands (en iyi, karşılaştır, alternatif, vs, top N, liste, hangisi, …) or name two or more of the
     brands; image and CDN hosts and other third parties are neither.
     3. *The brand page of a topic* ("Rakip - Sayfa yapısı"): the brand page most cited for the topic's prompts other
     than the homepage, the homepage only when nothing else is cited.
     4. *Shares:* the per-prompt page counts are answers (runs) citing the page, each answer once however often it
     cites it (maya_data VERSION 2); a page's share is those answers over the topic's answers (never above 100%). A
     summary of version 1 is made again from the export files kept beside it (`artifacts/maya-data/`) when read, and
     saved; without the files it is not used.
     *Ticimax c77ebf6d before -> after* (scratch copies with the attached exports; previous commit vs this build):
     (1) /e-ticaret-paketleri "diğer" -> "Fiyatlandırma", /is-ortaklarimiz "ürün" -> "Entegrasyon"; pages in both
     sheets with another type 8 of 9 -> 0. (2) "Rakip marka" filled 0 of 18 topics -> 17 of 18 (ikas.com 12, shopify.com
     3, ideasoft.com.tr 2); ikas.com no longer a comparison site (it was 3 topics'); comparison sites are list pages
     ("en-iyi-10-e-ticaret-sitesi", "turkiyede-en-cok-tercih-edilen-10-eticaret-altyapisi"). (3) brand page = homepage
     16 of 18 topics -> 0 (11 different pages: posts, /e-ticaret-paketleri …). (4) highest share 329% (20 above 100%) ->
     100% (none above); e.g. "E-Ticaret Satış": ticimax.com 163% -> 74%.
     Tests: `tests/test_maya_review_357.py` (6; fake exports).

358. **The review of the carpexonline.com audit as global rules (Owner, 2026-11-18, reviewing the Smart E-ticaret audit
     5f049bf1 with Maya data; the thresholds, word lists and wording are agent defaults).** Global for every audit;
     Carpex was only the test case.
     1. *The crawl follows the site to its twin address.* Carpex's bare host answered its homepage itself (200) but sent
     144 of its other pages to www.carpexonline.com, and robots.txt named the sitemap only there. The crawl took www for
     another site: no redirect target was queued and no sitemap was read, so it ended after 32 pages of a 150-page limit
     ("exhausted"). Now, when the site's own pages answer with a redirect to its twin address (apex <-> www, http -> https;
     never down to http) three times, or once when robots.txt names a sitemap there (`crawler.TWIN_MOVE_REDIRECTS`), the
     crawl moves there as it does for a start redirect: that address's robots.txt and sitemaps are read and queued, and
     the targets met so far are queued. The earlier address stays the site's own (still requested, its links internal,
     each judged by its own robots.txt). Recorded as `crawl.host_moves` (schema 1.33). A crawl that stopped on its own
     below its limit says why in Kapsam ("Sınırın altında") and on the team report's Kapsam page
     (`sampling.below_limit_line`): error answers, files, blocks, a move to the twin, redirects to an address that was not
     followed (an audit made before this rule), a sitemap named on another address, or every address found requested.
     "Örneklem planı bitti" is said only when known addresses were left unread.
     2. *Product pages from what they show.* Carpex's product pages carry their own Product markup with an Offer,
     og:type=product and "Sepete Ekle", but category pages carry Product markup in their lists and og:type=product.group,
     so Product, Offer and og:type=product all looked like site defaults (DECISIONS 347) and 19 product pages were typed
     "diğer". Now a page is a product when its own Product markup is not inside a list and has an Offer, or it has
     og:type=product and a buy control of its own and is not a listing (`page_groups.own_item`; `METHOD_VERSION` 6, so
     saved audits are grouped again offline). Before reading (Akıllı), an address of three or more words ending in an
     item id ("-550", not "/kokular-55" nor a year) that the main menu does not link, or one listed in a sitemap file of
     products, is the profile's product page (one in a file of categories its category page); after the first wave, such
     an address linked from the body of a page read as a category is too. Only item types (product, model, detail) take
     these address rules, so a SaaS feature page does not. The Akıllı plan's first suggestion now includes the homepage's
     platform, as the report's does (Carpex was planned as "Diğer" and reported as E-ticaret).
     3. *The audited brand is never its own rival.* A competitor whose name, or its first word, is one of the brand's
     keys (the meta's name and brand tags, the domain's own name; keys of four or more characters) is the brand itself:
     dropped from the competitors, the competitor-mentions names (the brand's own products, "Carpex Maxx Tower 750 X") and
     the Topic Pulse leaders (a topic led by the brand has no rival leader, no gap, and says "markanın kendisi"). A cited
     domain whose own name is the brand's (carpex.com.tr) is the brand's own site: its pages count to the brand's share and
     it is never a competitor or comparison site. Kapsam names what was taken for the brand and those domains.
     4. *Only real topics are topics.* A prompt's topic is its first label that is one: a plain name or a "cluster:"
     value. Labels with another prefix ("intent:", "register:", "brand_status:", "vertical:", "brand:") and bare words such
     as "multiple" are not; a prompt with only such labels is grouped under "Konu dışı etiketler" (its labels listed),
     after every real topic, and no page is compared for it in "Rakip - Sayfa yapısı". `maya_data.VERSION` 3, so saved
     summaries are made again from their files (fetched pages and the download choice kept).
     5. *"Also download pages" works when the files are added and later.* Carpex's summary was made without the download
     step: the choice was read only by the "Add" button with files chosen, so ticking it afterwards did nothing, and reading
     the files again dropped pages fetched before. Now the choice is saved with the summary and read on every reading;
     ticking it once data is attached reads the attached files again and downloads (no new files needed); pages fetched
     before are kept and only the missing ones asked; each page records what it is for (Sayfa detay, rival or comparison
     page). The card says "İndirilen sayfalar: N (…), M alınamadı", and Kapsam says what was downloaded or that the choice
     was not made. An address the crawl answered itself (a redirect, a 404) is still not downloaded (DECISIONS 352).
     *Carpex 5f049bf1 before -> after* (scratch copies of the saved audit with its Maya files; previous commit vs this
     build): (2) "Sayfa bazında" diğer 19 -> ürün 19 (/micro-koku-makinesi-siyah-50ml-ginger-flowers-550,
     /leke-cikarici-sprey-500-ml "ürün"); (1) Kapsam gains "150 sayfalık sınırdan 32 sayfa okundu: … 144 adres
     www.carpexonline.com adresine yönlendirdi … site haritası başka bir adreste … okunmadı" (a new crawl is needed to read
     the ~150 pages); (3) "Lider rakip" carpex in 2 topics -> 0, carpex.com.tr in the domain column of 2 topics -> 0, Kapsam
     names «carpex», 58 product names and carpex.com.tr, carpex.si, shop.carpex.si as the brand's own; (4) topics
     "intent:discovery", "intent:comparison", "intent:branded", "intent:evaluation" -> gone (those prompts all carry a
     "cluster:" label too, so they join their cluster; no prompt was left for "Konu dışı etiketler"); (5) the saved
     summary had no download step at all; downloading needs live requests and was NOT RUN. Text check PASS before and after.
     Tests: `tests/test_carpex_review_358.py` (11; mock-transport shop, fake exports, the web app with a fake fetcher).
     *Tests changed:* the schema and grouping version pins (1.33, method 6; the frozen-shape list gains `host_moves`), and
     `test_crux_coverage_334` now expects "bulunan her adres istendi" for a Smart audit that left nothing known unread.

359. **The review of the Carpex re-audit (Owner, 2026-11-18, reviewing 1fd871f0: Smart, E-ticaret, 149 of 150 read,
     downloaded as a draft; the word lists and wording are agent defaults).** Global for every audit; Carpex was only
     the test case.
     1. *A merged card counts the union of its findings, never their counts added up.* Card 14 ("og:site_name değerini
     yalnız site adı yapın" with "Marka adı 3 farklı biçimde") said "105 sayfa": `str5.names` counts 94 pages but lists
     only 5 examples, so the card added the counts (11 + 94), a number in neither finding (not stale data from the
     32-page crawl), and RG-18 blocked the download. Now a merged card's scope is the union of its findings' addresses
     when each lists all of its own; otherwise the larger of that union and the biggest count, said as "en az 94 sayfa"
     / "at least 94 pages" (`scope_at_least`). The engine's own card count (`report.group_pages`) takes the same lower
     bound.
     2. *The site's earlier address serving pages itself is one card, and each page is read once.* After the crawl moved
     to www (DECISIONS 358), 75 bare addresses redirected but 20 answered 200 with their content (each naming its www
     address as canonical): the bare host really serves pages, inconsistently. That is a site problem, now one card,
     `idx4.twin_served` (IDX-4, S3, "N page(s) on <bare> answer with their content instead of redirecting to <www>",
     with the start page when it was one of them; "Sitenin diğer adresini ana adrese yönlendirin"), and those pages are
     no longer told again as "canonical on the www variant" (`idx4.variant`). In a new crawl such a page, met after the
     move or read before it (the start page aside), keeps only its status and canonical (`crawl.host_moves[].copies`),
     is not a page read nor counted against the limit, and the same address on www is read instead. A saved audit gets
     the card offline from its page records (`reassess_rules._decisions_359`); its other findings keep counting both
     copies until a new crawl.
     3. *Contact, about and references pages are never categories.* /bize-ulasin- and /referanslarimiz link to 12 product
     pages in a block of Ticimax's template, so the "links to item addresses" rule made them categories. A page whose
     address's last segment names a contact or about page (STR-21's words) or a references or trust page (referans,
     referanslarimiz, references, müşterilerimiz, sertifikalar, …) keeps the general type "other" and is never lent a
     category by its template (`page_groups.basic_page`, `METHOD_VERSION` 7). A profile with such a type (SaaS's
     references; Güvenlik, Ev hizmetleri and Restoran's contact) takes it; otherwise the rows name it "iletişim sayfası",
     "hakkımızda sayfası" or "referans / güven sayfası", not "diğer" (`page_rows.page_kind_of`).
     4. *Raw topic keys are shown readably.* A topic that is a slug ("makine-bakim-enerji") is shown as words with a
     capital first letter, each word spelt as the topic's prompts (then all prompts) spell it, so "bakim" is "bakım";
     a word no prompt spells keeps its letters ("koku secimi"); a Maya label with the same key is used as it is. The key
     stays the topic's identity (Topic Pulse joins on it).
     *Carpex 1fd871f0 before -> after* (scratch copies of the saved audit; 9c766e2 vs this build): text check
     "Taslak" (RG-18: card 14 "105 sayfa") -> "Geçti", card 14 "en az 94 sayfa"; a new card 3 "Sitenin diğer adresini
     ana adrese yönlendirin" (20 sayfa; the bare homepage and 19 pages), `idx4.variant` (the same 20) gone;
     /referanslarimiz and /bize-ulasin- "kategori" -> "referans / güven sayfası" and "iletişim sayfası"; topics
     "makine-bakim-enerji", "kartus-maliyet", "rakip-karsilastirma" -> "Makine bakım enerji", "Kartuş maliyet", "Rakip
     karşılaştırma". Reading each page once needs a new crawl (NOT RUN).
     Tests: `tests/test_carpex_rerun_359.py` (6; a mock-transport shop, made-up records); the grouping version pins
     (method 7).

360. **İlginay's review of the MMI Ek (www.mmihomedelivery.ae, 536b4b64, 16 Nov; source: İlginay, SEO team, card by card,
     passed on by the owner 2026-11-18; the detection rules and wording are agent defaults).** Global for every audit;
     MMI was only the test case. She found cards 2, 4, 5, 7, 9, 11 and 14 correct and 12 correct but possibly wider. No
     "Düzeltme kaydı" exists in the repository; the items are recorded here.
     1. *"Başlığı olmayan sayfalara başlık yazın" (13 pages) was wrong.* MMI is a Next.js site that prints its <title>,
     meta description and Open Graph tags in the body, after a <head> that closed normally (streamed metadata; Next.js
     serves them in <head> to crawlers it knows, Googlebot among them). The analyser read a title only inside <head>, and
     Firecrawl, MMI's main page reader, returned documents without a <title> at all, so the reader's copy replaced
     Maya's own (/shop/beer-cider/beer/top-brands had its title in Maya's copy). Now (a) a <title>, <meta name> (robots
     aside: ACC-3's note) and <meta property> printed in the body after a normally closed <head> are the page's own,
     listed in `metadata_in_body` (after a <head> broken early they stay "lost", DECISIONS 338); (b) a reader's copy with
     no <title> or meta description keeps Maya's (`firecrawl.reader._merged`); (c) STR-1 never says "no <title>" when any
     copy has one: in the body, the rendered page's, or Maya's own (`structure.title_elsewhere`); a title only after
     JavaScript stays RND-2's card. The same root cause made STR-10's "no meta description" false (13 pages).
     2. *"Gizli H1 etiketlerini görünür yapın" (5 pages) was wrong.* The raw-markup rule counted aria-hidden (it hides from
     screen readers only), sizes of 0 or 1 pixel and the hidden attribute anywhere above the <h1>, including React's
     streaming wrapper (<div hidden id="S:0">, shown by its script at once), and its evidence said only "its markup".
     Now an <h1> is hidden from the markup only by an inline display:none or visibility:hidden, or the hidden attribute
     (not on a streaming boundary), on it or an element around it (`analysis.visual_hide`); the evidence names how and
     on which element ("display:none on div.wrap"). The rendered page's computed style still decides when the page was
     rendered. A page with a visible <h1> beside a hidden duplicate is not reported. A saved record that cannot say why
     is not reported.
     3. *"Marka için sitede tek bir ad kullanın" was wrong.* Product titles ending "Absolut MMI Home Delivery", "France MMI
     Home Delivery" were read as brand names. A name given only by page titles that holds the main name as whole words,
     with the page's subject before or after it, is the page's subject: listed, not counted (the rule of DECISIONS 290,
     now both sides). The brand fields stay those of DECISIONS 221-338 (Organization and WebSite name, og:site_name, the
     header logo's alt, the title's site-name part, the footer's legal name); Product brand is never one.
     4. *"İç bağlantıları kanonik adrese yönlendirin" (148 pages) was a false positive.* It was one footer link, to
     /about-dxb, whose canonical names the homepage although its content is different (5% alike, IDX-4's
     "different content" finding): the canonical is wrong, and pointing 148 links at the homepage would mislead. A link
     target whose canonical names a page read with different content is no longer an alias (`quick_rules.alias_links`).
     The real alias links now give each page's step the link itself: «text» → /written-address (place) ⇒ /canonical.
     5. *Link cards name their links.* "Bağlantı yerleri" also lists links with no text (STR-14: the page, "(metin
     yok)", the address written, the place and block) and links to other sites with tracking parameters (the small-fixes
     card: page, link text, address, place, "adresten parametreleri kaldırın: igsh") (`link_places.NO_TEXT`,
     `parameter_rows`). The Özet links each card with such rows to its first one ("Bağlantılara git →"); the card names
     its first three links under its status (`Builder.name_links`); each page's row in "Bulgu bazında" names that page's
     links in "Ne yapılmalı" (`page_fixes`, `maya_audit.link_fixes`). The engine's "Broken links: what to edit" table
     keeps only broken links.
     6. *Sampled checks say their sample.* A card judged on the timing sample (`prf1.slow`, `prf1.timeouts`) says how many
     pages were measured: "3 sayfa (ölçülen 7 sayfadan; diğerleri de etkilenebilir)" (`pages_measured` in the finding).
     Saved audits get points 1-6 offline (`reassess_rules._decisions_360`).
     *Before -> after* (scratch copies of the saved audits; adf2478 vs this build; text check PASS in every one):
     MMI 14 -> 10 cards: gone "İç bağlantıları kanonik adrese yönlendirin" (148), "Başlığı olmayan sayfalara başlık
     yazın" (13), "Gizli H1 etiketlerini görünür yapın" (5), "Marka için sitede tek bir ad kullanın" (52); "Yavaş sayfaları
     hızlandırın" 3 sayfa -> "3 sayfa (ölçülen 7 sayfadan; …)"; "Metni olmayan bağlantılara ad verin" names
     /blog/cosmo-and-tini-…: (metin yok) → /product/absolut-raspberri-1l-8536 (gövde); the small-fixes card lists the pages
     with the instagram link and its igsh parameter; "Bağlantı yerleri" 0 -> 53 rows. İş Bankası: "Ara ara zaman aşımına
     uğrayan sayfaları düzeltin" says its 7 measured pages; its no-text card names its links. Atasun, Carpex: the
     broken-link and redirect cards name their first links. Enpara: unchanged.
     Tests: `tests/test_mmi_review_360.py` (9; a mock-transport shop and made-up records).

361. **The MMI re-check after 4d158c8 (Owner, 2026-11-18: İlginay's six points fixed; two leftovers, global; the filter's
     rules are agent defaults).**
     1. *Advice for one platform only on that platform.* MMI's Ek (www.mmihomedelivery.ae, not Shopify) said "Shopify'da
     her varyantın barkod alanını doldurun": the engine's fix sentence for `str3.product_no_identifier` names Shopify, and
     the appendix's "Ne yapılmalı" columns show fix sentences as written (Carpex, on Ticimax, had the same). The card itself
     was right (its Shopify step is a `steps_by_platform` line). Now one filter (`maya_audit.platform_text.for_platform`)
     leaves out every sentence, ";" clause or step line that names a platform the audit did not recognise for the site
     (Shopify, WordPress, WooCommerce, Magento, Shopware, PrestaShop, OpenCart, Squarespace, Webflow, Wix, ikas, Ticimax,
     IdeaSoft, T-Soft, Drupal, Joomla, BigCommerce, HubSpot; WooCommerce runs on WordPress): every card text field
     (`Builder.slot`), each row's "Ne yapılmalı" in "Bulgu bazında" and "Bulgular". The text library and the rule
     catalogue already keep platform steps under `steps_by_platform`; the web catalogue and the brief's texts name no
     platform. RG-19 (hard) now (a) judges a card against the site's own data only: a finding's advice texts
     (how_to_fix, expected, notes, judgment, page_fixes) no longer count as "the site names this platform" (the loophole
     MMI's card went through), and (b) reads the appendix's own "Ne yapılmalı" cells (`with_platform_advice`), so such a
     file is marked a draft in "Kontrol raporu". *Found on the way:* the text check read a Turkish suffix apostrophe as a
     quote ("GTIN'i … Shopify'da"), so the words between two were taken for quoted site text and not checked; a single
     quote now opens and closes only next to a non-letter.
     2. *The Ek says what the PDF says.* The technical "Bulgular" sheet showed the engine's own fix and a bare count. A
     finding on a card now shows the card's steps and the links the card names ("Ne yapılmalı"), and the card's scope in
     "Kapsam (sayı)" when it says more than a count ("3 sayfa (ölçülen 7 sayfadan; diğerleri de etkilenebilir)", "en az
     94 sayfa"); the Özet's "Etkilenen adres" shows that scope too. "Bulgu bazında" already named each page's links.
     *MMI 536b4b64 before -> after* (scratch copies; 4d158c8 vs this build): "Ne yapılmalı" cells naming another platform
     1 -> 0 (Carpex 1 -> 0, Enpara, Atasun, İş Bankası 0); "Bulgular" for "Metni olmayan bağlantılara ad verin": the generic
     fix -> the card's two steps and "/blog/cosmo-and-tini-…: (metin yok) → /product/absolut-raspberri-1l-8536 (gövde)";
     "Yavaş sayfaları hızlandırın" Kapsam "3" -> "3 sayfa (ölçülen 7 sayfadan; diğerleri de etkilenebilir)" in "Bulgular" and
     the Özet. Text check PASS in all five, before and after.
     Tests: `tests/test_platform_advice_361.py` (4).

362. **The MMI Ek with Maya data (Owner, 2026-11-18: the cards are right; three Maya-sheet points, global; the word lists
     and the nearest-topic rule are agent defaults).**
     1. *The brand's former name is the brand.* "Rakip - Konu" showed legalhomedelivery.com (MMI's former name) as the
     leader of every topic, with gaps up to 84 points. The meta's `competitor_aliases` holds alias groups
     (`competitor_key`, `alias_key`, `alias_label`), which were not read: the group "mmi" lists "mmihomedelivery" (the
     brand's domain) and "legalhomedelivery". Now a group whose key or any alias is the brand's (its names, its domains'
     own names, the domain stem) is the brand: every name in it is the brand's and its domains (legalhomedelivery.com)
     are the brand's own sites; a name written as an address is matched by its domain's own name. A short key ("mmi")
     matches names only, never a domain (mmi.io is another company). The other groups' aliases are said under the
     rival's name ("Rival Co Online" -> "Rival Co"). Topic Pulse names only its top competitor each week, so when that is
     the brand (or no rival is named) the topic's leader and gap come from the rivals' share of the topic's AI answers:
     the answers citing a rival's own sites, each answer once over all its sites, beside the brand's share from the same
     citations; the cell says so ("African + Eastern %76,8 (AI kaynak payı; Topic Pulse lideri «legalhomedelivery.com»
     markanın kendisi)") and Kapsam counts those topics. Kapsam lists the names treated as the brand.
     2. *Unrelated uploads are never named or kept.* Kapsam printed "tanınmayan dosyalar kullanılmadı: DL26_proposal.tex,
     IEEEtran.cls" (files of a zip uploaded by mistake). The summary keeps only their count ("2 tanınmayan dosya
     kullanılmadı"; a summary saved before is shown alike), and when the app reads the files it removes from the audit's
     Maya folder every upload that holds no Maya dataset (`maya_data.unused_uploads`).
     3. *Prompt categories are not topics; unlabelled prompts go to the nearest topic.* Maya's prompt categories
     ("Buying intent", "Brand", "Discovery", "Problem", "Comparison", "Competitor comparison", …) were shown as topics.
     They are now labels that are not topics. A prompt with no topic label (MMI: 541 of 595) goes to the real topic whose
     words its text and need families share most (a topic's words: its name, its labelled prompts' need families, Topic
     Pulse names; a word may take a suffix: "makine" in "makinesi"); one that shares none goes to "Konu dışı etiketler"
     when it has other labels, else to no topic; Kapsam gives the four counts. One topic under two keys (the label "Kötü
     Koku Giderici" and the cluster "kotu-koku-giderici") is one row. `maya_data.VERSION` 4 (alias groups, each cited
     domain's answers per prompt, need families, the files count), so saved summaries are made again from their files.
     *MMI 536b4b64 before -> after* ("Rakip - Konu", scratch copies; 4d0307f vs this build): 17 rows -> 12 (the six
     category rows gone); leader legalhomedelivery.com on 8 topics with gaps 23.7-83.9 -> real rivals from the AI answers
     (African + Eastern 7 topics, CityDrinks 2, uaespirits.com, licensedxb.com) with gaps -2.9 to -91.9 (MMI leads every
     topic); Kapsam: the file names -> "2 tanınmayan dosya kullanılmadı"; brand names «legalhomedelivery», «mmi», …;
     "54 prompt Maya'nın konu etiketiyle; 369 … en yakın konuya atandı; 160 … «Konu dışı etiketler» satırında (prompts in
     Russian, Arabic and Turkish with only intent labels); 12 … atanamadı". *Carpex 1fd871f0*: 20 rows -> 19 (the two
     "Kötü Koku Giderici" rows merged); the leader of 18 topics from the AI answers (Scentsan, Akscent, Atelier Rebul,
     …) where Topic Pulse named only Carpex or no rival. Text check PASS for both, before and after.
     Tests: `tests/test_maya_brand_topics_362.py` (5; fake exports, the web app).

363. **The review fix log: every issue the SEO team noted, checked on the newest saved audit, and the gaps closed
     (Owner, 2026-11-18, after Efsa and İlginay said noted issues still appeared; the item wording, the check of each item
     and the thresholds below are agent defaults).** Global for every audit; the brands are where the notes were made.
     1. *The log.* `maya_audit/fix_log.json` holds 76 items, one per note: the three Enpara reviews (İlginay's
     "İLGİNAY KONTROL" file of 9 Nov, her second check of 11 Nov, the notes relayed on 12 Nov; `docs/expert-reviews/`),
     Efsa's corrected report and her coverage comparison (`enpara-seo-tum-bulgular-2026-11-12_duzeltilmis (2).xlsx`,
     `SEO_Audit_Coverage_enpara_2026-11-12.xlsx`: the seven issues taken in 343 and every gap she marked "Yalnız bizde"
     or "Kısmen"), İlginay's MMI notes ("İLGİNAY'S NOT" in `…-ek-tr (1).xlsx`; the later copies (2)-(5) carry none), and
     every review recorded in DECISIONS (Atasun 347, Nature's Garden 349, İş Bankası 350/351, Ticimax 356/357 and the
     second review's three open items, Carpex 358/359, MMI 360-362). Plain report downloads without notes are left out;
     a note in several files is listed once with its newest file. Efsa's own Search Console cards (rank losses,
     impressions up and clicks down, noindex pages with impressions) are her analysis, not notes on Maya's report: the
     ones her comparison marks as missing are in the log (organic trend, AI share, CTR by position, title changes).
     Each item has a check that `tools/fix_log.py` runs on the newest finished audit of its domain (www and the bare name
     are one domain), rebuilt from a copy with the current engine (no request; `~/.maya-audit/web` only read), and the
     test files it names, which must pass: Durum is Düzeltildi when every check holds, Kısmen when some do, Hâlâ var when
     none do, and Yeni tarama gerekli when the saved data cannot show it (Carpex's pages read twice, its 32-page crawl, an
     Enpara page not in the newest sample). The tool writes `~/Downloads/duzeltme-kaydi.xlsx` (Nasıl okunur; Düzeltme
     kaydı: No, Kaynak, Marka, Sorun, Durum, Nasıl düzeltildi, Tarih, Commit, DECISIONS no, Kontrol) and, with
     `--write-status`, `maya_audit/fix_log_status.json`.
     2. *Every Turkish Ek has a "Düzeltme kaydı" sheet* (`fix_log.ek_sheet`): the items that are rules for every audit,
     worded with no brand, file or person (`genel`), their status, how each was fixed and its DECISIONS number, newest
     first, at most 50. An English Ek has none (the items are Turkish).
     3. *Gaps closed (Efsa's comparison):* a sitemap whose files give no address a <lastmod> (an IDX-5 note); llms.txt
     served with no charset or starting with a byte-order mark (ACC-8 note; the BOM is recorded from the next crawl); a
     directive written inside a robots.txt comment ("# Content-Signal: …", an ACC-1 note, from the next crawl); a
     FAQPage that holds fewer questions than the page's real Q&A block shows (STR-3 note); an <h1> that asks two
     questions or more where a later question has no section heading with its words (STR-2 note on the content card:
     "Temettü nedir? Nasıl alınır?"); an article whose structured data names only organizations as author
     (`str3.article_org_author`, S4 estimated; saved audits from their saved JSON-LD, which `saved_data` now receives);
     pages whose CTR is under half the median CTR of the site's own pages at the same position, with 100 impressions or
     more and three pages or more in the position band (Maya data, "Organik×AI - Segmentler": "Sırasına göre CTR"); and
     the Ek's "Önceki denetimden değişenler" sheet: the pages read in this audit and the previous finished audit of the
     same site (www and the bare name matched) whose title or meta description changed, with both values and whether it
     got worse (gone, or out of 30-60 / 70-160 characters), or a line saying none changed.
     4. *The second Ticimax review's open items:* a page with no measures says why ("alınamadı («sayfaları da indir»
     seçilmedi)", the download's error, or the download limit); a page's first sentence skips a short promotional line
     (a sale, a code, free shipping, a percentage; 20 words or fewer) and lines that open two or more measured pages of
     the same site; "Üçüncü taraf listelerde marka sırası" gives the brand's place in the list page (the number written
     before its heading, else its place among the headings that name a known brand, "listede yok", or why it was not
     read).
     *Result* (newest audits rebuilt 2026-11-18): 76 items: Düzeltildi 73, Yeni tarama gerekli 3 (Carpex 2, Enpara 1),
     Hâlâ var 0, Kısmen 0. Before the fixes above: Hâlâ var 3 (lastmod, organization author, contact pages typed by an
     unsuitable check) and 9 new-rule items not yet built. Enpara's newest audit now gets the lastmod and llms.txt notes
     and 39 articles named by an organization only; its pages read in both 9 and 11 Nov audits (127) show no title or
     description change.
     Tests: `tests/test_fix_log_363.py` (15); `test_maya_data_352` expects the reason after "alınamadı".
364. **Image and file names with spaces, accents written as combining marks, brackets or commas (Owner, 2026-11-19,
     from the MMI homepage; the sources read, the word lists and the sort order are agent defaults).** View-source of
     the MMI homepage showed empty boxes after the banner "MMIBannerWebsite(Espolòn,CelebrateDíadeMuertos,DayoftheDead)
     -01.jpg": the HTML is clean UTF-8, but the file name keeps macOS's decomposed accents (o + U+0300, i + U+0301) and
     brackets and commas, on a 320,000-character line Chrome's view-source cannot draw. Global for every audit.
     1. *The rule* (`tseo1.file_name_unsafe`, TSEO-1, S4 Düşük, issue type warning "Kontrol edin", VERIFIED; checklist
     SEO-141 "Görsel dosya adı ve bağlam" becomes partial, whether a name describes the image staying review): an image
     or file address whose file name holds a space the page did not encode, an accent written as a combining mark
     (Unicode category M), brackets or commas. The address is tested as the page writes it (`%20` is fine, a "+" is not a
     space, the query is not the file name); an image proxy (Next.js `/_next/image?url=…`, `?src=`, `?file=`) is tested
     on the file in its parameter, so the proxy's sizes are one file. `maya_audit/file_names.py` holds the test
     (`problems`), the plain name it suggests (lower-case letters, digits and hyphens, accents dropped, camel-case words
     split, an acronym kept whole: banner-website-espolon-dia-01.jpg), and the scan of a page.
     2. *Where it looks.* A new crawl records, per page, the addresses with a problem from img/source/video src and
     srcset (read as browsers read a srcset), CSS backgrounds (style attributes and <style> blocks, an unquoted url()
     with brackets read whole), links to documents (pdf, doc, xls, ppt, zip, csv…), og:image and the Product markup's
     image (`analysis.file_names`, only when a page has one; no schema change). The rule also reads what every report
     keeps: img src, og:image, PDF links, image preloads and the image sample (`crawl.structure.images`, with the pages
     that show each image). A saved audit gets it offline (`reassess_rules._decisions_364`, in `apply` and
     `saved_data`), with the Product images of its saved JSON-LD.
     3. *What it says.* One row per file (the worst names first: a combining mark before brackets alone): the file name,
     its problems, the marks' codes, where it is used and a suggested plain name; one line per page in "Bulgu bazında"
     ("dosya adı «…» (birleşik aksan işareti, parantez/virgül); önerilen ad: …", two names and "ve N dosya daha"). The
     advice: rename the files to plain lower-case names with hyphens before uploading, upload them again and point the
     pages, markup and og:image at them; ask whoever uploads to name files this way. The note says a combining mark is
     valid UTF-8 and why it still breaks (boxes in some viewers, a second spelling of the address), and why brackets,
     commas and spaces do. Owner content, effort S, not a quick-win rename of page addresses. A card of this rule never
     says "Tek şablon düzeltmesi" (`client_selection.NOT_TEMPLATE_RULES`): each page's own uploads are renamed one by
     one, whatever template shows them.
     *Result* (saved audits rebuilt 2026-11-19, no request): MMI 240 files on 40 pages (brackets or commas in all of
     them, combining marks in the Espolòn banner only, which leads the homepage row), a new card 5 "Görsel ve dosya
     adlarını düz, küçük harfli adlarla yükleyin" (Düşük, Kontrol edin; 10 cards before, 11 after; no other card
     changed; text check PASS). Elsewhere: Ticimax 26 files (25 with spaces), İş Bankası 6, Enpara 2, Atasun 1 ("Ray-Ban
     Kılıf.jpeg", written with a space in the page), Carpex and Nature's Garden none.
     Tests: `tests/test_file_names_364.py` (7).
365. **How each of the 165 checklist items is checked, and the platform (İlginay's questions; Owner, 2026-11-19; each
     item's way, reason, automation idea and effort, the Maya measures and the platform signals are agent defaults).**
     Global for every audit; the brands are only test cases.
     1. *Every item says how it is checked* (`checklist.how`): "Otomatik" when the crawl measures it; "Veri gerekir" when
     a source outside the crawl is needed (Search Console, GA4, Bing, PageSpeed, Merchant Center, Google Business
     Profile, DataForSEO, logs, IndexNow, CRM), with those sources; "Uzman incelemesi" when the decision, or the part
     Maya does not measure, needs a person (a judgement, a business decision, a real session, or a rule not built yet),
     with why (`maya_audit/checklist_how.json`, Turkish; an English Ek gives the item's mapping note). Totals: Otomatik
     55, Veri gerekir 37, Uzman incelemesi 73. The Ek's "Kontrol listesi" gains three columns (Nasıl kontrol edilir;
     Gereken veri / neden uzman; Otomatikleştirme önerisi) and three bold rows at the top with the counts; "Kontrol
     listesi özeti" counts the three ways per group. SEO-064 (meta description missing or shared) becomes automatic: the
     rule `str10.no_description` existed and was not mapped.
     2. *Maya data.* Maya's export holds Search Console performance per day, page, query, country and device (never a
     query and a page together) and no GA4, coverage, URL inspection, crawl stats, enhancement or security report
     (`ga4-traffic` is not read by the summary). So 11 of the 37 data items are measured when it is attached
     (`maya_audit/checklist_maya.py`), each with the crawl's own addresses: SEO-004 date range (13 months needed for
     seasonality), SEO-005 URL inventory (Search Console pages the crawl and sitemaps do not hold), SEO-007 property
     scope (hosts; a test or internal host with impressions is an issue: MMI's backoffice-uat), SEO-008 baselines,
     SEO-025 and SEO-054 pages with impressions or clicks the crawl did not find (review, not issue, when the crawl
     stopped at its cap), SEO-028 pages read with and without impressions, SEO-057 the most clicked product and category
     pages with fewer than 2 links from pages read, SEO-071 CTR under half of the site's own pages at the same position,
     SEO-074 performance per page, SEO-165 the weekly trend. SEO-004, -008 and -165 need the daily file (an export of
     page scores only measures the other 8). A finding of the item's own rules still comes first. Not measurable from
     the export: SEO-013, -022, -023, -024, -101, -130, -160 (Search Console reports and URL inspection), SEO-069
     (cannibalization needs query and page together), SEO-083 (history and backlinks); GA4 parts stay "Veri eksik".
     3. *Could become automatic* (64 of the 73 expert items; effort S up to a day, M 2-4 days, L a week or more; 9
     cannot: business decisions, real sessions, no API): S 21 (e.g. SEO-027 indexable internal search, SEO-105 variant
     markup, SEO-118 third-party scripts, SEO-109 identical JSON-LD blocks, SEO-117 render-blocking CSS, SEO-119
     compression and cache headers, SEO-132 raw vs rendered canonical, SEO-136 metadata per template, SEO-140 image
     paths blocked by robots.txt, SEO-142 video sitemap, SEO-017 test hosts from Search Console), M 37 (rendered-page
     measures, AI judgements, a second mobile request, PDFs), L 6 (filter clicking, mobile menus, other countries,
     search intent, factual accuracy, originality). Each is in the Ek's column; none is built here.
     4. *The platform* (`site_platform.recognise`): besides script addresses, the generator tag and X-Powered-By, now
     the image and preloaded-image addresses (/wp-content/uploads/, cdn.shopify.com and /cdn/shop/, cdn.myikas.com,
     static.wixstatic.com, /_next/image, static.ticimax.cloud), a platform the generator tag or X-Powered-By names
     (Ticimax, Shopify, ikas, IdeaSoft, T-Soft, Wix, Sitefinity, WordPress, Next.js) and the footer's credit line
     ("… ile hazırlanmıştır", "altyapısıyla", "Powered by …"; the platform named in a text without a credit is no
     signal). IdeaSoft and T-Soft are recognised only from what they declare or credit: their file hosts are not
     confirmed, and no live site was read to confirm them. Confidence: "high" when the signals are on 2 pages or more
     and the pages state the platform or are half of those looked at; "medium" on 2 pages or more or one page stating
     it (and DECISIONS 309's saved-data signals); "low" one page only. Saved audits get it again offline from their
     pages (`reassess_rules._decisions_365`, in `apply` and `saved_data`). Kapsam's first row and Özet's first row give
     the platform, its confidence, the first signal, the CDN and the rules whose advice has a line for it.
     5. *What changes per platform* (`platform_text.advice_by_platform`, read from the advice texts so it never goes
     stale): Shopify: acc3.utility_indexable, idx5.identical, idx5.stamped, idx6.alias_links, str12.headings,
     str12.language, str3.product_no_identifier and the note "HTML not cached at the CDN"; WordPress: idx1.error_text,
     str12.language. A line naming a platform is shown only on that platform (DECISIONS 361) and RG-19 blocks one left
     in; every other site, and every other platform (Ticimax, ikas, IdeaSoft, T-Soft, Wix, Next.js, Sitefinity), gets the
     general advice. The platform also feeds the business-type suggestion; no check's measure depends on it.
     *Result* (saved audits rebuilt 2026-11-19, no request; cards and text check unchanged in all 7): platform before ->
     after: MMI Next.js -> Next.js (high, 20/20), Carpex Ticimax -> Ticimax (high, X-Powered-By), Enpara none ->
     Sitefinity (medium, generator on 1 of 20), Atasun none -> none, İş Bankası none -> none, Ticimax none -> Ticimax
     (high, X-Powered-By on 20/20), Nature's Garden Shopify -> Shopify (high, 6/6). "Veri eksik" rows: MMI 26 -> 19,
     Carpex 27 -> 20, Ticimax 21 -> 16 (Maya data: 11, 11 and 8 items measured); the others unchanged.
     Tests: `tests/test_checklist_platform_365.py` (6); the checklist, Özet and P-level tests read the new rows.
366. **Every problem in the Ek's "Özet", the PDF's cards first (İlginay; Owner, 2026-11-19; the section's wording and its
     order beyond severity and priority are agent defaults).** Global for every audit. The PDF keeps its cards (at most
     15); the XLSX "Özet" keeps them first, exactly as before, and adds below them "Diğer bulgular (N): PDF'te kart
     olmayan her sorun, önem ve önceliğe göre": one row per problem group on no card shown (the PDF's cards and the
     appendix's note cards), so a group the selection made a card that the PDF has no room for is listed too; never
     an Info note, a finding a person rejected or Maya's own limit. Same columns as the cards: Başlık (the plain problem
     name of "Bulgu bazında"), Önem, Sorun türü, Öncelik (P0-P3), Sorumlu and Efor (the recommendation catalogue's, with
     the cards' words), Etkilenen adres (the group's addresses) and Satırlara git (its first row in "Bulgu bazında"); the
     Kart cell is empty. Order: severity, then priority, then title (`client_appendix.other_findings`). A line under
     the platform says "İlk N kart PDF raporundadır; diğer bulgular aşağıdadır.", N being the PDF's own number of
     cards (11 on MMI, 6 on Nature's Garden), not a fixed 15, so the line is never wrong.
     *Result* (saved audits rebuilt 2026-11-19, no request): cards identical in all 7; "Diğer bulgular" MMI 13,
     Carpex 14, Enpara 14, Atasun 12, İş Bankası 21, Ticimax 18, Nature's Garden 15; text check PASS in all.
     Tests: `tests/test_summary_others_366.py` (2); the Özet tests read the cards from the fourth row.
367. **A finding waiting for a check takes a card slot before Info cards (Owner, 2026-11-19, from the MMI Ek; the P0/P1
     line and the card's first line are agent defaults).** Global for every audit.
     *The rule until now* (DECISIONS 300, 309): a finding with a reason to confirm it first (a new check, an estimated
     measure, a finding seen only in another reading path, possible intent…) went to "Teyit edin" and never to a card,
     whatever its severity or priority; the cards were the other problems (every High and Blocker, the rest by
     priority score while there was room, at most 15), and the PDF's free slots then took up to 2 Info note cards. So
     on MMI "Ana içerik ham HTML'de yok" (High, P1) and "Yapısal veri sayfadaki bilgiyle çelişiyor" (Medium, P1)
     stayed in "Teyit edin" while cards 10 and 11 were Info.
     *Now* (`client_selection.select`): after the placements the P-levels are worked out, and a "Teyit edin" group
     that is High or Blocker, or P0/P1, joins the candidates: High and Blocker always take a card (as every High
     problem does), P0/P1 while there is room, ordered with the other cards by severity band and priority score. One
     that finds no room goes back to "Teyit edin". It stays "Kontrol edin" (`issue_type`), gets no automatic P0 (it is
     not established), its PDF card opens with the confirm reason ("Doğrulama bekliyor: kontrol yeni"), the client
     brief still leaves it out (`_confirm_ids`) and the sector sheet still says "Teyit bekliyor". Info note cards only
     take the slots the problem cards leave (unchanged). The Ek's "Özet" is made from the PDF's cards, so both match;
     a group taken out of the cards is listed under "Diğer bulgular" (DECISIONS 366).
     *Fixed on the way:* "Bağlantı yerleri" failed to sort when a note card with link rows had no PDF number (Ticimax,
     once a promoted card took the note card's slot): such rows have no card number.
     *Result* (saved audits rebuilt 2026-11-19, no request): MMI 11 -> 13 cards (+1 "Ana içeriği sunucuda oluşturun",
     +4 "Yapısal veriyi sayfadaki bilgiyle eşleyin"; the 2 Info cards are now 12 and 13); Atasun +3 "Ana içeriği
     data-nosnippet dışına çıkarın" (High), "Ayrıştırılamayan JSON-LD'yi düzeltin" (Low, P3) leaves the cards; Ticimax
     +2 "Ağır görselleri küçültüp sıkıştırın" (Medium, P1), the Info card "Küçük bağlantı ve etiket tutarsızlıklarını
     temizleyin" goes to the appendix; Carpex, Enpara, İş Bankası and Nature's Garden unchanged. PDF and Özet match in
     all 7; text check PASS in all.
     Tests: `tests/test_confirm_cards_367.py` (5).

368. **İlginay's review of "Diğer bulgular" in the MMI Ek, as global rules (İlginay, 2026-11-19; the thresholds, the
     wording of the new lines and the evidence fallback are agent defaults).** Global for every audit.
     *(1) Homepage outline* (`checks/structure.py`): "The homepage has N visible section headings" counted only visible
     <h2>/<h3>; in Firecrawl's copy of MMI's homepage an open sign-in dialog had marked the whole page aria-hidden, so
     147 <h2> counted as 0. Now every <h2>/<h3> with text counts, hidden or not, and a homepage with enough of them is
     never "too few". When at least 6 <h2> are product card names (a heading followed, within 4 text lines and before
     the next heading, by a price) and they are at least half of the <h2>, `str2.card_headings` says so instead:
     "Ürün adları başlık (H2) olarak işaretlenmiş" (Low, "Kontrol edin"), with the count, examples and the section
     headings (SEO-066).
     *(2) Headings in another language* (`language.py`, `str12_content_language`): a heading is compared with the
     page's own language, its declared one and the language its text is written in (never the report's); English
     question words (how, what, do, does, my, I...) are English evidence, and "a", "do", "as", "is", "in", "no" are not
     foreign on an English page. MMI's "How do I move up a tier?" was called Portuguese ("a", "do"). Each page's line
     names the page's language and quotes the headings. "Atlanan başlık düzeyi yok" is written only for the heading-jump
     rules (`page_rows.from_page` gave it to every rule with "heading" in its name).
     *(3) Canonical to a page with different content* (`checks/index.py canonical_readings`): every reading of the
     canonical is kept with its date (raw HTML; Maya's browser, and whether the page had finished loading; Firecrawl's
     copy). The finding is said only when the readings agree and one is final (no browser reading: the raw HTML, as
     before); readings that differ are `idx4.versions_differ` ("Ham HTML'deki ve işlenmiş sayfadaki kanonik adres
     farklı", Medium, "Kontrol edin", SEO-041) with both values; a page whose only browser reading was taken before
     the network went quiet is not assessed (said in the check's `not_assessed`). MMI's /about-dxb: raw and browser
     both said "/", but the browser read it at 3 s with the network still busy, so the final canonical is not known.
     *(4) Which content* (`example_rows.py`): each page's line (`row`) names the text, the element and the place:
     RND-1 the missing text blocks (first 80 characters, heading level / button / link / text, the section heading
     above), RND-3 the clicked controls or the scroll and the headings and text that appeared, the shared link with no
     address (its text, href and block), unclear slugs (the slug, why, a suggested slug of 3-6 words from the address
     or the page title), generic link texts (the text and target), heavy images and videos, footer heading jumps,
     articles without an author, missing or empty <h1>, copies, structured data that differs from the page, unparsed
     JSON-LD, heading jumps. Written live (`report.py`) and for saved reports (`reassess_rules._decisions_368`).
     *(5) Plain Turkish* for "Ortak alandaki bağlantının adresi yok", "Adreslerin kısa adı anlaşılır değil" and "Bazı
     bağlantılarda genel metinler kullanılıyor": the name, title, "Ne yapılmalı" (problem, why it matters, what to do)
     and steps rewritten.
     *(6) "Örnek" in the Özet* (`client_appendix.examples_of`, `other_findings`): one concrete example per row, "page:
     value", from the first "Bulgu bazında" value that quotes page text or shows an address or an element, else the
     first evidence record naming a page and a concrete thing seen there (`example_rows.evidence_example`). A problem
     with neither is not listed under "Diğer bulgular" (it stays in "Bulgular"; the line says how many) and the text
     check names it: RG-24 (soft) "Somut örneği olmayan bulgu". The cards keep their place and get the column too.
     *Result* (saved audits rebuilt 2026-11-19 from copies, no request): MMI 13 -> 14 cards (+12 "H2'yi ürün adlarına
     değil bölüm başlıklarına verin": 140 of 147 <h2> are product names); "Ana sayfada bölüm başlıkları az", "Bölüm
     başlıkları başka bir dilde" and the /about-dxb canonical are gone; "Diğer bulgular" 11 -> 8, every row with an
     example, RG-24 none. İş Bankası: one page's raw and rendered canonicals differ (new card, "Ara ara zaman aşımına
     uğrayan sayfaları düzeltin" leaves the cards), one "different content" canonical read before the page finished
     loading is not assessed. "Diğer bulgular" (before -> after; left out for no example, RG-24): Carpex 14 -> 8 (6),
     Enpara 14 -> 12 (2), Atasun 12 -> 10 (2), İş Bankası 21 -> 15 (6), Ticimax 17 -> 9 (8), Nature's Garden 15 -> 11
     (4); those left out are mostly site-wide or timing findings (sitemap dates, slow responses, rate limits) with no
     single page text. Text check PASS in all 7.
     Tests: `tests/test_review_368.py` (9); `test_summary_others_366`, `test_counts_and_shared_elements` updated.
     *Environment:* the local Playwright browser cache was missing (the PDF tests failed with "Executable doesn't
     exist"); `python -m playwright install chromium` restored it (a browser download, no audit request).

369. **Site-wide findings keep their place in the Özet with a site-level example (Owner, 2026-11-19; the wording of
     each example and the order of the fallbacks are agent defaults).** Global for every audit. 368 left a problem out
     of "Diğer bulgular" when none of its rows quoted page text, an address or an element, which dropped site-wide and
     once-measured findings (sitemap dates, slow responses, sitemaps without images or videos, blocked requests...).
     *Now* (`example_rows.site_example`, `client_appendix.other_findings`) the "Örnek" is, in this order: a concrete
     row value (368); a concrete thing in the evidence (368); the file or address measured and its value, with the
     limit when the finding has one ("sitemap.xml: 412 adresin 398 tanesinde lastmod aynı (2026-11-16)",
     "/kategori/x: yanıt 4,8 sn (3 ölçümün ortancası), eşik 2,0 sn", "site haritası (6 dosya): <image:image> yok;
     sayfalarda 505 farklı görsel", "/: HTML 1.323 KB, sınır 1.000 KB", "/all: HTTP 429 (Cloudflare), 7 istekten 1
     tanesi", sameAs status, template markers, raw vs rendered words, words without <h2>/<h3>, the html lang vs the
     text's language, two structured-data values, brand name variants); else the first measured value of its "Bulgu
     bazında" rows (anything but "—", "not kept", "not read", "seen"). Only a finding with no measured value at all
     stays out, said on the "Diğer bulgular" line ("ölçülen değeri olmayan N bulgu…") and by RG-24, now "Örneği ve
     ölçülen değeri olmayan bulgu".
     Tests: `tests/test_site_examples_369.py` (3); `test_summary_others_366`, `test_review_368` updated.

370. **A robots.txt finding only where its rule blocks (Owner, 2026-11-19, from the MMI Ek; the wording of the lines
     is an agent default).** Global for every audit. ACC-6 ("Yapay zekâ tarayıcı erişimi role göre farklı") was
     scoped to every sampled address whenever a vendor's bot was blocked on any of them, and "Ölçülen değer" read
     "engellenen botlar: GPTBot, OAI-SearchBot, ChatGPT-User" on each: on MMI 5 vendors × 30 addresses = 150 rows,
     the homepage included, while robots.txt blocks only /profile/ (1 of 30). *Now* (`checks/access.py`,
     `example_rows.robots_pages`, `robots_site_row`): an ACC-6 finding is attached only to the addresses its bots are
     blocked on, each with the rule and the bots ("robots.txt 5. satır Disallow: /profile/ → bu adreste engelli:
     GPTBot, OAI-SearchBot, ChatGPT-User"), and carries one site-wide line ("robots.txt 5. satır Disallow: /profile/ →
     30 örnek adresten 1'i engelli (…); diğer sayfalar açık"), which is its Özet example. `page_rows.about` no longer
     prints the blocked bots on any address. ACC-2's blocked addresses get the same line (they said "okunmadı"). A saved
     report is rewritten from its ACC-2 decisions (address, bot, rule) (`reassess_rules._decisions_370`); when those
     do not name the addresses, the finding is said once, on robots.txt, with the count from its title.
     Tests: `tests/test_robots_rows_370.py` (5); `test_sector_method_324` updated (the page's value is "—").

371. **İlginay's second review (Nature's Garden Ek), as global rules (İlginay, 2026-11-19; the thresholds and the
     wording of the lines are agent defaults).** Global for every audit.
     *(1) Every card's "Örnek"* (`client_appendix.reader_sheets card_example`): a robots line of its own (370), a
     concrete row value, a concrete thing in the evidence, the file or address measured and its value (369; now also a
     page's CDN cache status and first response, images without width/height, the share of WebP/AVIF), a measured row
     value, else the card's own first line (the note cards); an empty one is named by RG-24. Sitemap dates read
     "sitemap_products_1.xml: 19 adresin 18'i aynı lastmod'u taşıyor (2026-11-16)". The small-fixes card names the
     empty tag and its pages ('<meta name="theme-color"> etiketi boş (content değeri yok; 130 sayfada)').
     *(2) Hidden <h1>* (`render.H1_VISIBILITY_JS`, `str2`): a reading says whether a screen reader reads the <h1>
     (not display:none, visibility:hidden or aria-hidden) and names a visually-hidden pattern (clipped, 1px, off-screen,
     opacity 0); an <h1> read by a screen reader is the page's heading. Only a page whose <h1> no one reads is
     reported; a saved reading that does not say is not established, so not reported.
     *(3) Heading language* (`language.heading_language`): against the page's language a heading with a common word of
     that language is in it, wherever the word stands; another language needs at least 4 words and one of its common
     words (a theme's "Information for new patient" on a Turkish page is still called). Repeated headings count once. "Non-Candy Halloween Treats to Hand Out This Year" ("non" alone) is English.
     *(4) "No products"* (`quick_rules.empty_collections`): 0 products in the HTML and none linked from the rendered
     page when it was rendered; a low count is no finding.
     *(5) Account, sign-in, cart, checkout, search and order pages* (`page_groups.is_utility_address`) leave RND-1 and
     RND-3.
     *(6) Dead links and shared heading jumps* say what is wrong: '«1» <a href="#"> (li.yotpo-pagination-number-
     container): bağlantı gibi görünüyor, gidecek adresi yok (href yalnızca «#»)'; '«SHOP» başlığı H4, sayfadaki H2
     başlığından sonra geliyor; alt bilgide (footer)'.
     Saved reports: `reassess_rules._decisions_371` (hidden <h1>, collections, utility pages); the headings through 368's
     step with the new rule. Tests: `tests/test_ng_review_371.py` (7); `test_site_examples_369` updated.

372. **Bugs from Efsa's revision-compliance review, each reproduced by a test first (Efsa, 2026-11-19; the details file
     with F01-F10 was not on this machine, so the bugs were found from the review text and by searching for the same
     kinds).** Global for every audit. Missing values are "veri yok", never 0.
     *F01*: a `<lastmod>` that is not a date ("16/11/2026", "{lastmod}", "2026-13-45") left None among the parsed dates;
     "All N values are identical" then called `.isoformat()` on None and the future-date test compared None with a
     date: the sitemap check stopped. Now such values are counted and sampled (`lastmod_unparsed`) and never compared.
     *Missing as 0*: Search Console page scores without a CTR or position wrote 0; a page's average position counted
     rows without a position as position 0 (halving it); topic-visibility rates missing from the file were 0 and a gap
     was computed from them; the "top domains" heading said "(0 içinde)" when the number of prompts was unknown. Now a
     missing value is None (`maya_data._value`) and the sheets write "veri yok"; the position is averaged only over the
     rows that give one. *Brand matching*: a brand name shorter than 4 letters ("ING") matched the start of other
     words ("ingilizce"); it now matches only as a whole word (a longer name keeps Turkish suffixes: "enparalı").
     *Open, waiting for the details file*: URL merging without evidence (`maya_data.page_url` joins http/https,
     www and a trailing slash into one key) and the AI citation denominator (brand share per citation row, not per
     answer) were found but not changed: their intended form is in Efsa's proposals file.
     Tests: `tests/test_bugs_372.py` (8), each failing on 9a922d5 (two crashes, four zeros/values).

373. **Efsa's revision-compliance review: the expert lock and what it needs (Efsa, 2026-11-19; storage outside the
     repository, the label shapes, the "few 429s" threshold and the wording are agent defaults; İlginay's NG notes
     are hers).** Global for every audit; Enpara, MMI and Nature's Garden are only where the notes were made.
     *(1) The expert lock* (`maya_audit/expert_labels.py`, `scripts/real_sites_benchmark.py freeze-expert|expert`,
     `tests/test_expert_lock.py`): every note in `docs/expert-reviews/` carries labels: "wrong" -> `must_not_find`,
     "correct" and "show this detail" -> `must_find` (a "wrong" note fixed by rewriting the advice checks the
     corrected detail and says why; a note the same expert overturned later is kept, `superseded_by`, not checked).
     A label tests a finding, a card, a card's text or an Ek row. The noted audits (Enpara 2e5829fb and fee70191, MMI
     536b4b64, Nature's Garden 342a0b14) are frozen from the web app's saved pages into MAYA_AUDIT_BENCHMARK_DIR
     (outside the repository, with each report's digest), rebuilt with the current engine and every label checked.
     The test fails when the frozen set is missing unless the run says so on purpose (MAYA_AUDIT_BENCHMARK_OPTIONAL=1);
     CI downloads the set from the secret MAYA_AUDIT_BENCHMARK_URL and, until it is set, prints a warning that the
     lock did not run. 83 labels from 80 reviewed cards. Proof: with DECISIONS 368's English question words reverted
     in a scratch copy, `expert` printed "79 labels: 78 hold, 1 red" (mmi-R368-2-heading-language) and exited 1.
     *(2) Error families* (`tests/test_error_families_373.py`): the brand name (product name, section name, language
     version's title, sub-brand; a real second name still reported), link lists (broken, redirecting, text-less,
     parameterised each name their link; a clean page has none), the hidden <h1> in a real headless browser
     (visually hidden, responsive duplicate, behind an open pop-up, transparent are read; display:none is not), the
     heading language (short English headings on a Turkish page are not foreign; a real one still is). Found and
     fixed on the way: an open pop-up marks the rest of the page aria-hidden, which made its <h1> "hidden"
     (`render.H1_VISIBILITY_JS` ignores aria-hidden behind an open dialog).
     *(3) The fix log* (`fix_log.status_of`): three states. "Düzeltildi" only when every linked test passed, every
     check on the rebuilt audit held on evidence (an empty sheet, no matching card or row, a check not assessed is
     "no evidence", never a pass: F10) and the item's labels hold; "Hâlâ var" when one failed; "Doğrulanmadı"
     otherwise (no test, no evidence, a new crawl needed, labels not run). Every item has a test; the note items name
     their labels. An Ek's "Düzeltme kaydı" says "bu denetimde doğrulanmadı (genel durum: …)" for an item measured on
     another brand. Nature's Garden J5-J8 logged.
     *(4) Note import* (`tools/import_notes.py`): reads the reviewer's column of a reviewed Ek's Özet ("Doğru" ->
     correct, "Hatalı/Yanlış" -> wrong, "hangi/nerede/eksik/anlaşılmıyor…" -> incomplete) with each card's rules from
     the Ek's own rows; a note the words do not settle is asked (MMI J13 "DOĞRU AMA …": the owner said incomplete).
     MMI imported; Nature's Garden written from the review texts (its noted file is not on this machine).
     *(5) Version stamp* (`maya_audit/version_stamp.py`): the first row of every Ek's "Kapsam" and a PDF provenance
     line: "Maya Audit {version} · commit {commit} · oluşturuldu {UTC}".
     *(7) Unapproved rules* (`maya_audit/rule_approval.json`, `rule_approval.py`): a questioned rule (idx5.stamped,
     NG J6) and the checks of a draft sector profile (airline, restaurant: the 33 "taslak" checks) on an audit of that
     profile are "Kontrol edin", the card opening with "Onay bekliyor: …", until moved to "approved".
     *(8) İlginay's NG follow-ups*: a text-less link names its element and target; a collection not rendered and with
     no product in its HTML is a coverage gap in "Kapsam" (STR-15 coverage), not "no products"; tables in plain
     Turkish with the table, its size and first row; at most 5 429s to Maya's own crawler, under half its requests,
     are Maya's own limit ("Kapsam"), not a client finding. On a saved report, "long pages have no subheadings" is kept
     only where the reading counted styled titles (the older Enpara audit did not: İlginay's J10 note).
     Tests: `tests/test_expert_lock.py` (4), `tests/test_error_families_373.py` (18), `tests/test_review_compliance_373.py` (10).

374. **One value per page and metric, examples over their own threshold (Owner, 2026-11-20, from the MMI Ek; the
     wording of the lines is an agent default).** Global for every audit.
     *(1) Timing* (`example_rows.timing_row`, `site_example`, `page_rows`): a PRF-1 finding is judged on one value per
     page, the median of its measurements: the full HTML for "slow pages" (`median_total_ms`), the first byte for the
     homepage's first response (`median_ttfb_ms`). Every sheet now shows that value, how it was measured ("3 ölçümün
     ortancası; ölçümler: …") and the threshold; the crawl's single first-byte time on a page row is named "ilk yanıt
     (tek ölçüm, tarama sırasında)". Before: the Özet showed the median first byte rounded to seconds ("1,0 sn"), the
     appendix rows the crawl's single first byte (567 ms), so card 10 ("Yavaş sayfaları hızlandırın") looked as if
     its example were under the threshold: on its own metric the homepage's median is 1,714 ms over 1,500 ms.
     *(2) Examples and rows over their threshold*: the example is the slowest page over the threshold on the judged
     value (MMI: /shop/accessories/bar-accessories, 1,829 ms); a page whose judged median is not over it leaves the
     finding (`reassess_rules._decisions_374`); the first-byte fallback is never shown against a full-HTML limit.
     *(3) Text check*: RG-25 (hard) one page and timing metric shows one value across Özet, Bulgular and Bulgu bazında;
     RG-26 (hard) a value beside its own "eşik" or "sınır" must exceed it (the bracketed single measurements are not
     the value). *(4) A robots tag outside <head>* (`example_rows.robots_outside`): each page says the tag, where it
     sits and why (the <head> closed early by an element, or the tag streamed into the body after a normal <head>, as
     Next.js streams its metadata), and what Maya's Googlebot request got. The ACC-4 Googlebot probe now records the
     robots tag's place and its sample takes one page with such a tag; a tag Googlebot gets in <head> is not reported,
     nor then the same streamed tag on the other pages. Saved audits have no such request: "Googlebot isteğiyle
     doğrulanmadı". *(5) GTIN*: "Product işaretlemesinde gtin (gtin8/12/13/14) ve mpn yok; var olanlar: sku, brand".
     Tests: `tests/test_mmi_check_374.py` (6); four MMI labels (mmi-R374-*); fix log items 113-116.
375. **The version stamp is for the team, not the client (Owner, 2026-11-20).** DECISIONS 373's stamp leaves the PDFs
     (team report and brief: no "Sürüm" provenance line). The Ek says it in one short line, the last row of "Yöntem"
     ("Sürüm: 0.2.8 · commit abc1234", `version_stamp.short`), no longer the first row of "Kapsam", which starts with
     the platform again. The full stamp with the build time goes into the file's document properties
     (docProps/core.xml: creator "Maya Audit", description "Maya Audit <version> · commit <c> · built <time> UTC",
     version, created; `xlsx.workbook(properties=…)`, `version_stamp.properties`). The PDF's older "Motor" line
     (engine version and audit id, since before 373) is unchanged. Tests: `tests/test_version_stamp_375.py`.
376. **The Ek as the team's full client file (Efsa's final Enpara file; Owner, 2026-11-20; plan
     `docs/proposals/EK-FULL-FILE.md` with the owner's decisions D1-D5). Global for every audit; Enpara is only the
     test case and its file never enters the repository.** Built in phases, a commit each.
     *Phase 1, the frame* (`maya_audit/ek_frame.py`): the client Ek starts with "Kapak" and follows the team's sheet
     order (Maya's own data sheets Genel durum, Organik×AI and Sayfa detay last, D1). Every sheet has the Maya band
     above its header: "maya · <brand> SEO analizi · <sheet>", then "← Kapak" and "Kaynak: …" with each source's own
     period (the audit and its crawl date; each Maya dataset and its period, listed side by side, never summed or
     merged; "Maya dışa aktarımından hesaplandı" where Maya computes what the team took from the dashboard). The
     writer moves the header, the frozen pane, the filter, the dropdowns and every link into a banded sheet down with
     the band; `xlsx.read` leaves the band out (`band=True` keeps it). Kapak: title, the expert line (D5: "SEO uzmanı
     değerlendirmesinden geçmiştir" only when every row waiting for an expert has a decision, else "Uzman teyidi
     bekliyor: N madde", or "Uzman teyidi gereken madde yok"), the date it was made (not a measurement date), what is
     and is not covered (GA4, URL inspection, no impact estimate, no Maya data), source files, the periods table, the
     colour legend (source / computed / expert input / green Search Console header) and a linked sheet guide.
     *Internal sheets* (D1): "Kontrol raporu" and "Düzeltme kaydı" leave the client Ek for a team file
     (`client_appendix.build_files` → {"client", "team", "record"}; the skill writes `-ekip.xlsx`, the web app offers
     "Ekip dosyası (XLSX)"); a blocked text check marks the client Ek's cover "TASLAK". *PDF*: the old "Motor: Maya
     Audit <version> · denetim <id>" line is removed too. *Text check*: RG-27 (one count stated with different values
     on different sheets), RG-28 (a finding ID or a check name in an ID column that "Bulgular" does not list), RG-30
     (a link to a missing sheet or past the last row), all hard. RG-28 found Efsa's source note on the saved audits:
     a note card's observation rows carried the card's check names as finding IDs ("ACC-8-66d7edcf · ACC-8 · IDX-3 ·
     IDX-5 · STR-10", "STR-2"), and link rows of `idx6.parameters` the check name "IDX-6": such rows now carry no
     finding ID (the checks go to "Kontrol"; the rule stays in "Kural"). Tests: `tests/test_ek_frame_376.py`; fix log
     item 117; Enpara labels enp2-R376-1-*.
     *Phase 2, the Search Console data* (`maya_data`, summary version 5; an older summary is made again from the
     kept export files): the daily rows summed over the whole period and over its last 28 days, each with its own
     dates, the position weighted by impressions (`gsc.totals`); the AI Overview columns of gsc-daily-stats: absent,
     present but empty (Enpara: empty on all 88 days → "Veri yok"), or their totals (`gsc.aio`); gsc-top-pages and
     gsc-top-queries as weekly 28-day snapshots: the latest row per page or query, never summed, with the number of
     weeks it is listed in (`gsc.top_pages`, `gsc.top_queries`); gsc-page-scores (query count, authority), gsc-query-
     intents (intent, brand flag) and gsc-query-opportunities (type, pages, impressions, score, its period) kept per
     row. A page list from gsc-top-pages when no daily or score file gives one. Bug fixed on the way (Efsa's "Dikkat"
     note): the per-page "GSC haftalık tık" summed the weekly rows, each already a 28-day window, so the same clicks
     were counted several times: it is now the latest 28-day row ("GSC tık (son 28 gün, örneklem)"). Fix log item 118
     (waits for an audit with gsc-top-pages: none of the saved ones has it); item 105's check follows DECISIONS 375
     (the stamp's last row of "Yöntem"). Tests: `tests/test_maya_snapshots_376.py`.
     *Phase 3, the Search Console and AI sheets* (`maya_audit/sc_sheets.py`, Turkish as the Maya sheets): with Maya
     data attached the Ek writes "Search Console özeti" (each dataset and its period; site totals for the last 28 days
     and the file's whole period, one block when the file holds 28 days or fewer, marked "Maya dışa aktarımından
     hesaplandı"; device, country, intent shares, brand click share, AI Overview, URL inspection and GA4, each "Veri
     yok" with its reason when the export lacks it; the audit against Search Console: pages read, in the list, with
     clicks but not read, the click share of pages with a Medium or worse problem, non-brand cannibalization, pages
     cited by AI and how many were not read; notes on 28-day windows and empty cannibalization clicks), "Trafiğe göre
     öncelik" (pages read with a problem by clicks), "SC sayfaları" (every listed page with its audit status), "SC
     sorgular" (gsc-top-queries with intents; with the intent file only, its queries and "Tık ve gösterim: Veri yok"),
     "SC fırsatlar" (non-brand first; the pages with an audit problem), "AI alıntılanan sayfalar" (tracking parameters
     and #:~:text removed; citations, AIs, prompts, clicks, audit status), and green Search Console and AI columns on
     "Sayfa bazında" and "Kilit sayfalar". A sheet whose data the export lacks is left out and Kapsam says why; without
     Maya data none is made. The checklist keeps the tool's own result in "Sonuç"; what Search Console data measures
     is a proposal beside it ("Search Console eki: önerilen sonuç", "Search Console kanıtı"), and its totals end with
     the counts after and before the proposals (Efsa's file); SEO-069 (cannibalization) is measured from Maya's
     opportunity list, non-brand queries only. RG-27 compares the counts the sheets state (pages read, Search Console
     pages with clicks not read, non-brand cannibalization, AI-cited pages). Hardened on the way: an expert label or a
     fix-log check on a column the sheet lacks is no evidence (red / not verified), never a match on every cell, and a
     row shorter than the column has that cell empty. Enpara with its export (a local copy only): the last-28-day clicks and CTR within 4% of the dashboard figures Efsa
     used, the same number of Search Console pages as her sheet. Tests: `tests/test_sc_sheets_376.py`; fix log items 119-120; labels enp2-R376-2/3 (on
     MMI's frozen audit, the noted audit having no Maya data).
     *Phase 4, the action sheets* (`maya_audit/ek_actions.py`, Turkish as the team's file), built from the sheets
     already written so every link lands on a real row: "Aksiyon planı" (30 columns: T- per PDF card with the card's
     problem, advice, business reason (`why`), P0-P3, owner, effort, scope, first 3 addresses, links to its full list,
     evidence and link rows, period, the check method (`verify`) and the card's PDF page; S- per checklist item the
     Search Console data turns into a problem the tool did not see; R- per competitor topic by its gap rank, "n<10" as
     an indication; cross links to actions on the same pages; the expert and client columns SEO değerlendirmesi, Uzman
     notu, Onaylanan öncelik, Uygulama durumu, Hedef tarih empty with dropdowns (D5); the HTML column left out, no
     shared link exists (D4)), "Uzman teyidi" (every finding waiting for confirmation and every finding an expert
     already decided, with the decision from the owner's confirmations, and every Search Console proposal that changes
     a checklist result; the reason in words), "Yönetici özeti" (up to 7: the first problem cards, Search Console
     proposals, the pages with clicks the audit did not read, the largest competitor gap, the checklist before/after;
     open decisions, the expert line, units never merged; RG-29 checks each number against the row it comes from),
     "Sayfa grupları" (first path segment › address › actions, each address linked to its evidence row) and "Konum
     dizini". A sheet with nothing to list says why. Kapak's expert line reads "Uzman teyidi". The PDF page (D4): the
     skill writes the Ek again after printing the PDF; the web app uses the team report it built for the audit and
     language, if any; else "PDF oluşturulmadı". A card's page is its heading (number, title, then severity or
     "Not") in the PDF's text read without whitespace (the reader splits Turkish letters). On Enpara the T-01, T-02 and
     T-03 evidence rows are Bulgu bazında 4, 94 and 115, as in Efsa's file; Uzman teyidi 28 items, as hers.
     Tests: `tests/test_ek_actions_376.py`; fix log item 121; labels enp2-R376-4-*.
     *Phase 5, sources and competitor notes* (`maya_audit/ek_sources.py`): "Rakip yöntem notları" beside the
     competitor sheets (the "Yöntem" and Maya "Kapsam" lines that explain them, and how to read n<10 and the
     "Fark [HİPOTEZ]" column); "Kaynak eşlemesi", each client sheet with the source and period its band says, its
     rows and what it holds (Efsa's "row shift" and "change made" columns described her manual copy: not made). The
     competitor sheets already have her C1/C2 columns (the brand written "Marka"); their names stay "Rakip - Konu" and
     "Rakip - Sayfa yapısı". The action sheets name Maya's datasets in their band when S- or R- rows or Search Console
     lines come from the export. Tests: `tests/test_ek_sources_376.py`.
     *Phase 6, Enpara against Efsa's file*: the saved Enpara audit rebuilt with the skill's flow and the export
     files from her folder attached to a local copy; the remaining differences and their reasons are listed in
     `docs/proposals/EK-FULL-FILE.md` ("Result"). Aligned on the way, as global rules: a checklist item the tool marks
     "Sorun" that no card covers is a T- action of its own, "Teknik SEO (karta bağlı değil)" (her T-16; its check
     name goes to the note, never the ID column: RG-28 caught it); "Trafiğe göre öncelik" lists every page with a
     problem, read or not, with its audit status; the weekly-list column reads "İlk listede (N ölçümden)"; "Uzman
     teyidi" says "Bulgu / kanıt (kaynak)" and "Kaynakta ne yapılmalı" as hers. Fix log item 122, label
     enp2-R376-5-unlinked-action. The seven saved audits pass the text check.
     *Re-evaluation line* (owner, 2026-11-20): the PDF no longer says "Güncel motorla yeniden değerlendirildi (Maya
     Audit <version> · şema … · commit, tarih)"; the version is only in the Ek's "Yöntem" and its document
     properties. A saved report that could not be re-evaluated still says so (that line names no version); the web
     app's own results page keeps its line (the team's tool), and the skill's build notes still say it.
377. **The owner's check of the Enpara Ek built as the full client file (Owner, 2026-11-20). Global for every audit.**
     *(1) Titles*: a Search Console action in "Aksiyon planı" and "Yönetici özeti" is a plain Turkish sentence, never the
     checklist item's name (`ek_actions.sc_title`: SEO-069 "Aynı marka dışı sorguda birden fazla <Marka> sayfası
     yarışıyor; en belirgin örnek «…»" with the non-brand query of most impressions, SEO-071 "Yüksek gösterim alan bazı
     sayfalarda tıklama oranı düşük", the other Maya-measured items alike); a checklist problem no card covers says what
     was found ("INP p75 323 ms (iyileştirilmeli) · Hız ve Core Web Vitals"). RG-31 (hard): a title in those two
     sheets that is a checklist item's name or has English words. *(2) Scope*: the PDF card's "2 sayfa (+88 sayfa:
     Orta)" is written "90 (2 Yüksek + 88 Orta)" in "Özet" (`client_appendix.scope_total`) and "90 etkilenen adres (2
     Yüksek + 88 Orta)" in the action sheets; other scopes ("en az 94 sayfa") stay as they are. *(3) Topics*: a Topic
     Pulse label that is no topic (an intent "Niyet: …", "Branding", a "word:" label) is left out of the topics, so of
     every competitor sheet, and Kapsam names the labels left out (same rule as "Konu dışı etiketler"). *(4) Names*:
     a leader is shown in the competitor's own display form from competitor-mentions-daily (the key itself or a key it
     starts, the most mentioned: "garanti" → "Garanti BBVA", "i̇ş bankası" → "İş Bankası"), else with Turkish casing
     restored; the brand's own name is judged as given first (a product starting with the brand's name is not its
     display form); no combining dot (U+0307) is kept. RG-32 (hard): a combining dot in a cell other than an address.
     Maya summary version 6. *(5) Percentages*: a share or rate column (header with CTR, "payı", "oranı") holding
     fractions has the number format "0.0%" (Excel shows %17,6 in Turkish); a percent written in Turkish text is
     "(%17)", never "(17%)". Tests: `tests/test_enpara_ek_377.py`; fix log items 123-127; labels own377-* (Enpara's
     frozen audit, and MMI's for the competitor data).
378. **Accuracy first: rule maturity, the team's pass conditions and a rule-approval loop (Owner, 2026-11-26, from the
     SEO team's feedback in the SEO_AUDIT Drive folder: İlginay's reviewed Eks, Efsa's revision-compliance review
     (A1, A8) and the team checklist; plan `docs/proposals/ACCURACY-FIRST.md`; the thresholds, the policy default and
     all wording are agent defaults until the owner confirms them).** Global for every audit. Why: of the 94 cards the
     team reviewed, 31% were correct (`docs/expert-reviews/ACCURACY.md`); every client report is checked and corrected
     by hand, and the same rule families came back on new brands (Efsa A2). A finding of a rule the team has found
     wrong should not reach a client as a definite problem until the team approves the rule again.
     *(1) Rule maturity* (`maya_audit/rule_maturity.py`, register `maya_audit/rule_maturity.json` made by
     `scripts/rule_maturity.py` from `docs/expert-reviews/`): each rule is `approved` (approved in
     `rule_approval.json`, or correct on at least 3 reviewed cards on at least 2 brands with a correct or wording-only
     latest verdict: `APPROVE_MIN_CORRECT = 3`, `APPROVE_MIN_BRANDS = 2`), `disputed` (questioned in
     `rule_approval.json`, or its latest reviewed card was wrong) or `unreviewed`. An explicit approval beats
     everything; the run time reads only the packaged register (an installed package has no `docs/`).
     *(2) Teyit edin* (`client_selection.confirm_reason`): a finding of a disputed rule gets the confirm reason
     `disputed_rule`; with `rule_approval.json` `policy.unreviewed = "confirm"` a never-approved rule's finding gets
     `unreviewed_rule` (default `"card"`: today's behaviour). Nothing is deleted and no severity changes: a High or
     P0/P1 group still takes a card slot as "Kontrol edin" (DECISIONS 367); a finding a person confirmed in
     review.json is a card whatever its rule. The confirm reason is part of the group key, so in a merge group only
     the disputed member waits. Words (client-safe; the team's detail is in the team file): "Doğrulama bekliyor:
     kural SEO ekibinin incelemesinde" / "… kural henüz uzman onayından geçmedi" (en "Awaiting confirmation: the
     rule is under the SEO team's review" / "… not yet approved by an expert"), in `etiketler.json`, the web app's
     `c6.reason.*` and the Ek's "Teyit nedeni".
     *(3) The team's checklist method* (`maya_audit/checklist_method.json`, `checklist.method`,
     `checklist.items_for_rule`; builder `scripts/checklist_method.py`, columns found by header): the pass condition
     ("Beklenen / geçme koşulu") and check method of all 165 items of the team's `SEO_Audit_Checklist (1).xlsx`
     (Drive, 11 Nov), read on 2026-11-26; the sentence every pass condition ends with is kept once (`common_pass`).
     "how", "action", "tool" and "frequency" are added when the builder is run on the file itself.
     *(4) "Kural onayı" / "Rule approval"* (`maya_audit/rule_sheet.py`), in the team file only (`ek_frame.INTERNAL`):
     one row per rule behind the audit's findings, disputed first: what it found in this audit (groups, addresses,
     placements), its checklist items and the team's pass condition, its status, the expert verdicts and the latest
     one, and an empty "Karar" column with a dropdown (Onayla / Sorgula). *(5) The import*
     (`tools/import_rule_approvals.py TEAM.xlsx --by <name> [--write]`): "Onayla" moves the rule to `approved` with
     who and when, "Sorgula" to `questioned`; an unknown word or rule stops the run and writes nothing.
     Today's effect: of 51 reviewed rules 2 approved (str16.shared, str7.over_100kb), 19 disputed (18 last found wrong
     and idx5.stamped, questioned), 30 reviewed without proof; 311 of the catalogue's 332 rules never reviewed.
     Not done here: the expert lock still has no frozen set on this computer or in CI (DECISIONS 373, plan Task 0,
     the owner's step). Tests: `tests/test_rule_maturity.py` (14), `tests/test_checklist_method.py` (3),
     `tests/test_rule_sheet.py` (9).
