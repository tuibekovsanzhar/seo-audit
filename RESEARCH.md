# Maya Audit: current tools worth considering

**Research checked:** 28 September 2026. Repository features and licenses can change; confirm them again before adopting code.

## Recommendation

Maya does not need another complete crawler. It already has a Python crawler and an evidence-based audit model. The useful additions are: (1) an automatic plain-language Markdown report generated from the same JSON findings; (2) reliable browser rendering for pages whose content appears only after JavaScript runs; and (3) a separate, carefully measured AI-answer citation monitor. Keep citation measurement separate from technical site checks so a page that is crawlable is not mistakenly reported as cited.

## Candidate tools and projects

| Candidate | What it could add | Fit for Maya | Cost, license, and cautions |
|---|---|---|---|
| [Playwright for Python](https://github.com/microsoft/playwright-python) | Run a real browser to compare raw HTML with content after JavaScript, inspect rendered headings/text, and save screenshots for evidence. | **Best next engineering component.** Maya is Python-based, and this addresses a known gap in its reports. Use only when configured; keep a per-page timeout and report “not assessed” on failure. | Playwright is open source under Apache-2.0. The library itself has no per-audit API charge; browser downloads and runtime need disk/CPU. It can still fail in constrained or headless environments, so test it in Maya’s actual deployment. |
| [Google Lighthouse](https://github.com/GoogleChrome/lighthouse) and [Lighthouse CI](https://github.com/GoogleChrome/lighthouse-ci) | Standard lab measurements for page performance, accessibility, and technical SEO; CI can catch regressions over time. | **Useful optional performance module.** Run locally against a small representative set of URLs and store the raw Lighthouse evidence. It overlaps with Maya’s existing optional PageSpeed Insights/CrUX checks, so decide whether the goal is lab testing or Google field data before building both. | Lighthouse runs locally and reports are not sent to a remote server by Lighthouse itself. No per-run API fee, but it needs Chrome/Node and compute. Lab measurements vary with device and network; they are not field-user experience. Lighthouse CI is Apache-2.0. |
| [Habibi](https://github.com/moaljumaa/habibi) | Repeated prompts against AI answer products, with brand mentions, cited URLs, competitor presence, and trends. | **Promising separate pilot for actual AI-answer visibility**, not a replacement for Maya’s crawler. Compare its results with manually repeated prompts before using them in Maya. Its README explicitly distinguishes API-based search-grounded answers from logged-in consumer UI behavior. | API runs use an OpenRouter key and are charged by model usage; there is no single fixed cost. Browser-based runs avoid per-call API charges but require logged-in accounts and can break or require a visible browser. The repo currently uses a Sustainable Use License, not MIT; it restricts offering the software as managed hosting. GitHub currently shows a very small project history, so review code, dependencies, data handling, and license with Maya’s team before adapting it. |
| [SiteOne Crawler](https://github.com/janreges/siteone-crawler) | Broad crawler checks, detailed reports, JSON, and standalone HTML output; useful as an independent comparison when validating Maya’s findings and improving report presentation. | **Use as a comparison tool, not a Maya dependency.** It substantially overlaps with Maya’s crawling. Its standalone HTML report is a good usability reference. | MIT-licensed and available as a local binary. Its README describes a 0–10 quality score; Maya should not adopt that score because it is not part of Maya’s evidence model and can overstate precision. |
| [CrawlSEO](https://github.com/crawlseo/crawlseo) | A self-hosted SEO dashboard combining crawling, Google Search Console, Core Web Vitals, and an MCP server. | **Architecture reference only.** It is a complete Next.js/Postgres product, not a small Python library to plug into Maya. Review how it presents crawl status and integrates GSC, but do not import the app. | MIT according to its repository. GSC requires Google OAuth and verified property access; optional keyword/backlink lookups use DataForSEO. The README states the crawler is capped at 2,000 pages. |
| [SEOnaut](https://github.com/StJudeWasHere/seonaut) | Open-source crawler and dashboard covering common on-page problems such as broken links, redirects, metadata, and headings. | **Secondary benchmark only.** The checks overlap with Maya’s current checks; compare a few outputs if validating coverage, rather than adding a second crawler stack. | MIT-licensed, but it is a Go/MySQL web application, so bringing it into a Python integration adds substantial deployment and maintenance work. |

## What to build next, in order

1. **Generate a readable Markdown report automatically.** Use the existing JSON report as the single source of truth. Include the audit date, page coverage, top verified findings, cautious/estimated findings, suggested fixes, and explicit “not assessed” items. Link to detailed JSON/TXT evidence. Do not manually rewrite findings in a way that can diverge from the data. The separate Live Reports ZIP contains human-readable examples; they do not implement this feature.
2. **Stabilize rendered-page checks.** Add Playwright behind a setting, capture the final rendered DOM, and compare it with raw HTML. Keep results partial/not-assessed when the browser cannot start or timeouts occur. Pilot on authorized sites and in the intended hosting environment before relying on it.
3. **Improve coverage before claiming a site-wide result.** Support a configurable page cap and crawl budget, sitemap progress, resume/continuation, and explicit counts for discovered, visited, blocked, skipped, and still-unchecked pages. A cap increase still cannot guarantee every URL is accessible or useful.
4. **Add actual visibility data as a separate module.** First ask Maya’s team whether it can connect Google Search Console and whether any internal AI-visibility source already exists. If not, run a small prompt-monitor pilot: fixed customer questions, repeated runs, named engine/model, date/locale, saved raw answers and cited URLs, and a rate such as “cited in 3 of 10 runs.” Do not blend that result into a technical SEO pass/fail score.
5. **Only add Lighthouse if the team needs lab measurements.** Prefer a local runner for repeatable small samples; keep it distinct from PSI/CrUX field data. Avoid running expensive browser audits across every URL by default.

## What not to add yet

- Do not port another full crawler or dashboard into Maya; duplicate systems make results conflict and increase upkeep.
- Do not treat presence of `llms.txt`, a Lighthouse score, or a single AI answer as proof that a brand is visible or invisible in AI search.
- Do not copy Habibi code into a hosted Maya service until legal review clears its non-MIT license and the team accepts browser-session/API-key handling.
- Do not include keyword, backlink, or rank data without a product decision and explicit paid-provider budget. These are separate features from this patch.

## Sources

- Playwright Python repository and Apache-2.0 license: https://github.com/microsoft/playwright-python
- Lighthouse repository and local execution notes: https://github.com/GoogleChrome/lighthouse
- Lighthouse CI repository: https://github.com/GoogleChrome/lighthouse-ci
- Habibi repository, engine behavior, setup, and license: https://github.com/moaljumaa/habibi
- SiteOne Crawler repository and MIT license: https://github.com/janreges/siteone-crawler
- CrawlSEO repository and MIT license: https://github.com/crawlseo/crawlseo
- SEOnaut repository and MIT license: https://github.com/StJudeWasHere/seonaut
