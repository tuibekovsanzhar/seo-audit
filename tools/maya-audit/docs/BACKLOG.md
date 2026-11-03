# Backlog

Decided later, by the owner. Each item names where its evidence is; nothing here is implemented.

## Firecrawl only where needed (DECISIONS 296, 2026-11-02)

Firecrawl reads a page only when Maya could not read it (blocked, challenged, 429, empty, no answer), or when its
template depends on JavaScript (the render sample shows rendered text well above raw, or the raw page is an app shell);
every other page keeps Maya's own reading. On the three saved audits that is 0 Firecrawl pages and 0 credits a run.

Open question for the owner: which copy the content checks judge on a site that reads fine without JavaScript. On
nihan (offline comparison, 499 pages read by both): thin pages 162 (Maya's copy) vs 13 (Firecrawl's); heading jumps 214
vs 47; STR-12 (Medium) only on Firecrawl's copy. Evidence: `docs/IMPLEMENTATION-STATUS.md`, "Double reading".

## From the 165-item checklist mapping (2026-11-03, `reviews/checklist/mapping.xlsx`, offline)

### (a) A "quick checks" batch

The nine missing-automatable items sized S, plus SEO-061, each a rule over data Maya already reads (sheet
"Missing-automatable"):

| Item | Rule | Data it uses |
|---|---|---|
| SEO-027 | An internal search page that is indexable (200, no noindex, self-canonical, allowed by robots.txt) | page_grouping `utility`, meta robots, canonicals |
| SEO-031 | Pages meant to leave the index that robots.txt blocks (their noindex cannot be seen) | skipped_robots, sitemap, links |
| SEO-036 | No image/video/news sitemap on a media or news site | sitemap documents, media, page types |
| SEO-046 | List pages whose next pages are not linked (only `<link rel>` or JavaScript) | pagination signals, links |
| SEO-067 | Unclear slugs: ids, very long, encoded characters | URLs, URL patterns |
| SEO-078 | Article pages with no author byline or Person markup (expertise content) | page types, JSON-LD types |
| SEO-093 | Products with too few links from categories; categories listing few products | inlinks (aliases merged), products listed |
| SEO-097 | Product markup without gtin / mpn / brand | Product JSON-LD fields (see (b)) |
| SEO-099 | Indexable collections that list no product | products listed, indexability |
| SEO-061 | Internal links to a URL whose canonical is another page (nihan: 825 links on 498 pages) | canonical aliases, links |

### (b) Keep the key Product JSON-LD fields in report.json

A saved report keeps the JSON-LD types of a page, not their fields, so GTIN and price checks cannot be run offline on
it (nihan's scorecard row SEO-097 is "Veri eksik" for this reason). Keep, per page with Product/ProductGroup markup:
`gtin*`, `mpn`, `sku`, `brand`, and for each offer `price`, `priceCurrency`, `availability` (and `hasVariant` count).
A change to the report's shape: needs a schema bump.

### (c) A decomposed Unicode "İ" in URLs as a TSEO finding

No check reports it today (the page-word folding only removes U+0307 for matching). nihan: 68 page addresses carry
`i` + `%CC%87` (a combining dot), e.g. `/pages/etbi%CC%87s`, where the slug was meant as "etbis"/"etbiş". Proposed
TSEO-1 finding: addresses with a combining character (not in NFC), with the NFC or plain-ASCII form as the fix.

## Key pages for sites that blocked Maya's crawler (DECISIONS 303, 2026-11-03)

Page grouping (DECISIONS 297) runs on Maya's own page records. When Maya's crawler is blocked and Firecrawl reads the
pages, those records hold no content, so no page gets an importance and the client reports' key pages say why instead
of listing them (2 Nov nihan Quick 50). Firecrawl's pages do carry their links while the audit runs (`view_pages`):
run `page_groups.annotate` on them and keep the result with the report (a change to the report's shape: schema bump).
