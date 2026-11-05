# How Screaming Frog SEO Spider Works: Architecture, Audit Process and What Maya Audit Should Borrow

Screaming Frog SEO Spider is a desktop Java crawler that works like a search-engine bot. It fetches pages, extracts dozens of on-page elements into a local database, can render pages in headless Chromium, and then runs a separate "crawl analysis" pass over the link graph (link score, orphans, sitemaps, canonicals, pagination, hreflang) before reporting prioritised issues. For Maya Audit, the parts most worth copying are the two-phase design (crawl first, then graph analysis), the issue/warning/opportunity taxonomy with priorities, list mode, segmentation, crawl comparison and raw-vs-rendered diffing. The parts not worth copying are its desktop-first, single-machine storage model and its reliance on a person using a GUI.

## TL;DR
- **Architecture:** a configurable single-machine Java crawler. It discovers URLs from links, sitemaps, hreflang, canonicals and pagination. It stores results in memory or in an embedded on-disk database, can render JavaScript with headless Chromium, and runs from a GUI, a scheduler or a headless CLI.
- **Audit process:** configure → crawl (raw HTML and optionally rendered HTML) → extract → post-crawl "crawl analysis" (link score, orphan pages, sitemap/canonical/pagination/hreflang checks) → Issues tab (Issue / Warning / Opportunity, each High / Medium / Low priority) → exports, bulk reports and Looker Studio. Integrations (GSC, GA4, PSI, Ahrefs, Majestic, Moz and, since 2024, OpenAI/Gemini/Ollama-style AI APIs) add data per URL.
- **Borrow for Maya Audit:** the post-crawl graph analysis, the issue taxonomy with priority, list mode, segments, crawl comparison, raw-vs-rendered diffing, near-duplicate hashing and custom extraction. Then go beyond it where Screaming Frog is weak: per-AI-bot robots.txt/WAF access testing, llms.txt, server-log/AI-bot evidence and client-facing narrative reporting.

## Important note on sourcing
This report was written without live access to screamingfrog.co.uk. Its architecture and feature descriptions come from long-standing, well-documented Screaming Frog behaviour. Version numbers, dates, prices and API quotas change over time and are marked as version-dependent; verify them against the current user guide and release notes before relying on them. One data point comes from Maya's own tracking: over the last 90 days, AI answers in the Maya project cited screamingfrog.co.uk 66 times (ChatGPT 48, Gemini 9, Claude 6, Google AI Mode 3), mostly the /seo-spider/ page. AI assistants treat Screaming Frog as *the* reference crawler, so clients will compare Maya Audit's output to it.

## 1. Architecture

**Desktop Java application.** Runs on Windows, macOS and Ubuntu/Linux. All crawling happens on the user's machine and IP address; there is no cloud crawler. Scale is limited by local RAM, disk and bandwidth. A bundled Chromium handles JavaScript rendering.

**Crawl modes.**
- **Spider mode:** starts from a seed URL and follows links within the configured scope (start subdomain by default; optionally all subdomains, or only the start folder and below).
- **List mode:** you upload or paste a fixed list of URLs (or a sitemap URL), and only those are crawled (depth 0, links not followed). Used for migrations, redirect mapping, sitemap checks, template audits.
- **SERP mode** (preview title/description lengths, no crawling) and **Compare mode** (diff two saved crawls).

**How URLs are discovered.**
- `<a href>` links in the HTML (and in the rendered DOM when JavaScript rendering is on).
- Optional link-like sources, each switchable: canonicals (HTML and HTTP headers), `rel="next/prev"`, hreflang (HTML, HTTP header, XML sitemap), AMP links, meta refresh, iframes, resources (images, CSS, JS, media).
- XML sitemaps: auto-discovered via robots.txt or supplied manually; crawled as a URL source and compared with the link graph after the crawl.
- robots.txt: fetched first and obeyed by default; modes *respect*, *ignore*, or *ignore but report*; a custom robots.txt can be tested without changing the live file.

**Queue, threads, speed and politeness.** URLs go into a frontier queue (essentially breadth-first, so "crawl depth" = clicks from the start URL). Default **5 threads**; thread count or "Max URI/s" can be changed. Timeout and retry settings handle slow servers. Aggressive speeds can overload servers or trigger WAF blocks; politeness is left to the user.

**User agents.** Default identifies as Screaming Frog SEO Spider; presets include Googlebot (desktop/smartphone), Bingbot, browsers and AI crawlers; custom strings allowed. robots.txt rules are matched against the chosen token. Changing the user agent does not change the source IP, so a site that verifies Googlebot or GPTBot by IP or reverse DNS treats the crawl differently from the real bot. This is a key limitation for AI-bot access testing.

**Storage.**
- *Memory storage:* fast, limited by RAM allocated to the app.
- *Database storage:* embedded on-disk database (recommended on SSDs), handles millions of URLs, saves crawls automatically so they can be reopened without re-crawling; default on suitable machines in recent versions.

**Main configuration options.**
- Include/Exclude regex filters on URLs.
- Limits: total URLs, crawl depth, folder depth, query strings, redirects to follow, URL length, page size.
- URL rewriting: remove parameters, regex replacements, force lowercase.
- Authentication: Basic/Digest/NTLM and forms-based login via an embedded browser.
- Custom HTTP headers, cookies, proxy, CDN settings.
- Extraction toggles, including storing raw and rendered HTML.
- Content area: which HTML elements count as "content" for word count, near duplicates and spelling.
- Saved configuration profiles, reusable by the CLI.

**Crawl comparison and scheduling.**
- *Compare mode* (database storage only) classifies URLs and issues as Added, New, Removed or Missing; *change detection* flags changes in titles, descriptions, H1s, word count, internal links, structured data; *URL mapping* compares staging vs production or old vs new URL structures.
- *Scheduling:* daily/weekly/monthly crawls with a saved configuration; each run can save the crawl, export tabs/reports, write to Google Drive/Sheets, and feed a Looker Studio crawl report.

**CLI / headless mode.** Runs without a GUI on Windows, macOS and Linux. Typical flags: `--crawl <url>`, `--crawl-list <file>`, `--headless`, `--config <file.seospiderconfig>`, `--save-crawl`, `--output-folder`, `--timestamped-output`, `--export-tabs`, `--bulk-export`, `--save-report`, `--export-format`. This is how teams build it into pipelines; it is the closest thing to an API. Licence required.

## 2. The audit process, step by step

```
[1] CONFIGURE
    mode (spider/list) · scope · include/exclude · limits · user-agent
    robots.txt handling · rendering (text vs JavaScript) · auth · speed
    extraction (custom search/XPath/CSS/regex, custom JS) · API connections
        │
        ▼
[2] CRAWL (fetch)
    robots.txt → seed/list → queue → HTTP fetch (status, headers, timing)
    follow redirects (records each hop) · obey directives
        │
        ▼
[3] RENDER (optional, JavaScript mode)
    headless Chromium executes JS · waits (AJAX timeout, default ~5s)
    stores raw HTML + rendered DOM + screenshot · links from rendered DOM
    → compares raw vs rendered (content, links, titles, canonicals, noindex)
        │
        ▼
[4] EXTRACT (per URL, during crawl)
    titles, metas, H1/H2, canonicals, directives, hreflang, images,
    structured data (JSON-LD/Microdata/RDFa → validate), word count,
    hashes for exact duplicates, inlinks/outlinks, custom extraction,
    API data per URL (GSC, GA4, PSI, Ahrefs/Moz/Majestic, AI prompts)
        │
        ▼
[5] CRAWL ANALYSIS (post-crawl, over the whole dataset)
    Link Score · near-duplicates · orphan URLs (sitemaps, GA4, GSC)
    sitemap vs crawl reconciliation · canonical chains/unlinked
    pagination checks · hreflang return links · semantic similarity
        │
        ▼
[6] ISSUES & REPORTS
    Issues tab: Issue / Warning / Opportunity × High / Medium / Low
    Overview & tabs with filters · Site structure · visualisations
        │
        ▼
[7] EXPORT
    CSV/XLSX/Google Sheets · bulk exports (all inlinks, chains...)
    reports (redirect chains, canonical chains, hreflang, insecure content)
    Looker Studio crawl report · saved .dbseospider crawl · compare later
```

- **Step 1 – Configuration.** Scope, mode, user agent, robots.txt behaviour, rendering, extraction and API connections are decided before the crawl. Near duplicates, spelling, link score and custom extraction must be switched on before crawling.
- **Step 2 – Crawl.** robots.txt first, then URLs from the queue. For each URL: status code, headers, response time, content type, size, redirect target. Redirects are followed hop by hop (enables chain/loop reports). Blocked URLs are reported as "Blocked by robots.txt", not silently skipped.
- **Step 3 – JavaScript rendering.** Each HTML page is loaded in headless Chromium; after the AJAX timeout the rendered DOM (and optionally a screenshot) is taken; links found there join the queue. The **JavaScript tab** flags differences: content only after rendering, links only in rendered HTML, titles/metas/H1s/canonicals changed by JavaScript, noindex only in the original HTML, console errors.
- **Step 4 – Extraction.** Standard elements fill the tabs. **Custom Search** (string/regex present or absent), **Custom Extraction** (XPath, CSS, regex: prices, authors, schema fields, analytics IDs), **Custom JavaScript** (since v20: run a snippet in the rendered page, e.g. call an LLM).
- **Step 5 – Crawl analysis.** Checks that need the full link graph run after the crawl: **Link Score** (PageRank-style 0–100), **near duplicates** (minhash-style, default 90%), **orphan URLs** (in sitemaps/GA4/GSC but not linked), **sitemap checks**, **canonical chains/unlinked/non-indexable targets**, **pagination** errors, **hreflang** return links, **semantic similarity / low relevance** (v22+). Until it runs, these filters show as incomplete. Key design lesson: separate per-URL checks from site-graph checks.
- **Step 6 – Issues and reports.** Each flagged filter has a **type** (Issue = likely problem; Warning = check, may be intended; Opportunity = improvement), a **priority** (High/Medium/Low), the number of URLs affected, and "how to fix" guidance. Overview pane with totals; site structure and link visualisations.
- **Step 7 – Exports.** Any tab or filter; **Bulk Export** for relationships (e.g. all inlinks to 4xx pages); **Reports** (Crawl Overview, Redirect Chains, Canonical Chains, Hreflang, Insecure Content, Orphan Pages); Google Sheets and Looker Studio for scheduled crawls.

## 3. What it checks

| Tab | Examples |
|---|---|
| Internal / External | All URLs with status, indexability, content type, depth, inlinks, link score |
| Security | HTTP URLs, mixed content, missing HSTS/CSP/X-Frame-Options/X-Content-Type-Options, unsafe cross-origin links |
| Response Codes | Blocked by robots.txt, no response, 2xx/3xx/4xx/5xx, redirect chains/loops, JS and meta-refresh redirects |
| URL | Non-ASCII, underscores, uppercase, parameters, duplicates, over 115 characters, multiple slashes, internal search URLs |
| Page Titles | Missing, duplicate, too long/short (characters and pixels), same as H1, multiple, outside `<head>` |
| Meta Description / Keywords | Missing, duplicate, too long/short, multiple, outside `<head>` |
| H1 / H2 | Missing, duplicate, over 70 characters, multiple, non-sequential |
| Content | Exact duplicates, near duplicates, low word count, readability, spelling/grammar, lorem ipsum; semantic similarity and low relevance |
| Images | Over 100KB, missing alt text/attribute, alt over 100 characters, missing size attributes, incorrectly sized |
| Canonicals | Missing, self-referencing, canonicalised, non-indexable target, multiple/conflicting, relative, outside `<head>`, unlinked |
| Pagination | rel next/prev issues, non-200 targets, loops, sequence errors |
| Directives | noindex, nofollow, none, noarchive, nosnippet, max-snippet, unavailable_after, X-Robots-Tag, meta refresh |
| Hreflang | Missing return links, inconsistent language, non-canonical/noindex/non-200 targets, missing self-reference, missing x-default |
| JavaScript | Content/links only in rendered HTML, JS-modified titles/canonicals/directives, noindex only in original HTML, console errors |
| Links | High crawl depth, no internal outlinks, nofollow internal links, non-descriptive anchor text |
| AMP | Missing/invalid AMP elements, non-200, missing canonical |
| Structured Data | JSON-LD/Microdata/RDFa; validation against Schema.org and Google rich-result requirements |
| Sitemaps | URLs not in sitemap, orphan URLs, non-indexable in sitemap, in multiple sitemaps, over 50k URLs or 50MB |
| PageSpeed | PSI/Lighthouse metrics, CrUX field data, opportunities |
| Mobile | Lighthouse mobile-usability checks (v20+) |
| Accessibility | axe-core rule violations by WCAG level (v21+) |
| Custom Search / Extraction / JavaScript | User-defined checks and fields |
| Analytics / Search Console | GA4 and GSC data per URL; URL Inspection API (index status, Google canonical, rich results) |
| Link Metrics | Ahrefs, Majestic or Moz backlink data per URL |
| Validation | Invalid `<head>` elements, multiple `<head>`/`<body>`, missing `<head>` |

**Issue classification:** fixed type and priority per filter (e.g. "Internal Client Error (4xx)" = Issue, High; "Missing Meta Description" = Opportunity, Low; "Canonicalised" = Warning). Generic defaults without site context; the docs tell users to interpret them.

## 4. Integrations and API keys

All are paid-licence features (*Configuration > API Access*); data is pulled per URL during the crawl.

| Integration | Auth type | What it adds | Limits / cost notes (verify) |
|---|---|---|---|
| Google Search Console | Google OAuth | Clicks, impressions, CTR, position per URL; URL Inspection API | URL Inspection ~2,000/day per property; row limits |
| Google Analytics 4 | Google OAuth | Sessions, engagement, conversions; orphan detection | Free; GA4 API quotas |
| PageSpeed Insights (Lighthouse + CrUX) | Google API key (free) | Lab metrics, Core Web Vitals field data, opportunities | Daily/per-minute quotas; slow for large crawls |
| Ahrefs | API key (API v3) | Backlinks, referring domains, UR/DR, keywords/traffic | Needs Ahrefs plan with API; API units cost |
| Majestic | Account / API access | Trust Flow, Citation Flow, backlinks | Majestic subscription with API |
| Moz | Access ID + Secret Key | PA/DA, linking root domains, spam score | Free tier very limited |
| OpenAI | API key | Prompts per page; embeddings for semantic similarity | Pay-per-token |
| Google Gemini | API key | Prompts and embeddings | Pay-per-token / free tier |
| Ollama (local LLM) | Local endpoint | Prompts and embeddings on local models | Free; hardware-limited |
| Anthropic | API key (version-dependent) | Prompts per page | Uncertain which version added it |
| Custom JavaScript snippets | Key inside snippet | Any API callable from JS | Provider costs |

Also Google Sheets/Drive (OAuth, exports/scheduling) and Looker Studio (via scheduled Sheets export).

## 5. Licensing
- **Free:** up to **500 URLs** per crawl; most configuration locked; no saving/opening crawls, JavaScript rendering, custom search/extraction/JS, API integrations, crawl comparison, scheduling, CLI, near duplicates, spelling, Looker Studio, AI features.
- **Paid:** annual per-user licence, historically **£199/year** (~$259), volume discounts; removes the URL limit and unlocks everything. Reverts to free limits when expired. Check current pricing.

## 6. Recent versions (verify against release notes)
- **v19 (2023):** Segments (tag URLs by regex/rules, issue counts per segment).
- **v20 (2024):** Custom JavaScript snippets (incl. OpenAI examples), Mobile usability via Lighthouse, N-grams, aggregated anchor text.
- **v21 (late 2024):** direct AI API integrations (OpenAI, Gemini, Ollama); accessibility auditing with axe-core.
- **v22 (2025):** semantic similarity via embeddings, low-relevance content, content cluster diagram.
- Later releases: check for additional AI providers and AI crawler user-agent presets.

AI-visibility takeaway: Screaming Frog has moved towards content understanding (embeddings, LLM prompts) but does not measure brand presence in AI answers and cannot truly test AI-bot access from the bots' own IPs or WAF rules.

## 7. Strengths and limitations vs a custom Python tool

**Strengths:** mature HTML/redirect/canonical/hreflang parsing; pixel-width title truncation; rich inlink/outlink data (anchor, position, follow, alt); raw + rendered HTML; post-crawl graph analysis; per-URL integrations; crawl comparison and change detection; cheap per seat.

**Limitations (where Maya Audit can win):** single machine and IP, heavy RAM/disk; GUI-first (CLI but no API, no multi-tenant portal, spreadsheet-style reports); generic priorities ignoring business context; simulates AI user agents but cannot prove real AI-bot access (IP allow-lists, Cloudflare "block AI bots", WAF challenges); no llms.txt, AI-bot log or AI-answer citation checks; regex/XPath/JS instead of full Python; AI features need your own keys and get costly per URL.

## Recommendations: what Maya Audit should borrow
1. **Two-phase engine:** per-URL facts into a store, then whole-crawl graph analyses (link score, orphans from sitemap ∪ GSC ∪ GA4 ∪ logs, canonical/redirect chains, hreflang reciprocity, pagination), marked pending until they run.
2. **Record every redirect hop** for chain/loop reports and "internal links pointing to redirects".
3. **Issue taxonomy** (issue/warning/opportunity × high/medium/low, description, how to fix), improved with segment/traffic weighting and AI-visibility rule types.
4. **List mode** as a first-class input (migrations, sitemaps, top GSC pages, pages AI engines cite).
5. **Segments:** report every issue per template/section.
6. **Raw vs rendered diff** (httpx + Playwright); flag critical content only in the rendered DOM as a high-priority AI-visibility issue.
7. **Near-duplicate detection** (MinHash/SimHash, ~90%), optionally embeddings for semantic similarity.
8. **Crawl comparison:** Added/New/Removed/Missing per issue, change detection, "what changed since last month".
9. **Custom extraction:** XPath/CSS/regex extractors plus pluggable Python checks.
10. **Politeness and scope controls:** per-host limits, include/exclude, URL rewriting, depth/URL limits, robots modes, headers/cookies, auth.
11. **Go beyond on AI access:** robots.txt per AI user-agent token; request key pages per user agent and detect 403s, challenges and different content; llms.txt; real AI-bot hits from Cloudflare/server logs; pair with Maya's AI-answer citation data.
12. **Headless and scheduled by default:** the report is the product.

## Caveats
- Version numbers and the feature-to-version mapping (v19–v22+) may be off by a release; 2026 releases not covered.
- Prices (£199 / ~$259 per year historically) should be checked on screamingfrog.co.uk/seo-spider/licence/.
- API quotas are set by Google, Ahrefs, Moz and Majestic, and change.
- Default thresholds (title pixel widths, 115-character URLs, 100KB images, 90% near duplicates, 5 threads) are configurable and may differ between versions.
- Native Anthropic/Claude support is uncertain; confirm in the current API Access docs.
