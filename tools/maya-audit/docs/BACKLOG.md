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

Done in DECISIONS 304: SEO-031, -036, -046, -061, -067, -078, -093, -097, -099, the Product JSON-LD fields in
report.json and the decomposed "İ" in addresses. Left from the quick-checks batch:

| Item | Rule | Data it uses |
|---|---|---|
| SEO-027 | An internal search page that is indexable (200, no noindex, self-canonical, allowed by robots.txt); ACC-3's `acc3.utility_indexable` covers `/search` and `/cart` by name only | page_grouping `utility`, meta robots, canonicals |

Parts of done items that stay open: SEO-031 when robots.txt blocks every crawler (nobody can read the noindex); SEO-036
news sitemaps; SEO-046 infinite scroll with no `rel=next` and no page-2 address; SEO-067 mixed-language slugs; SEO-093
products with too few links from categories.

## Percent-encoding case in canonical aliases (DECISIONS 304 (6), 2026-11-03)

`page_groups.canonical_aliases` compares the canonical and the page's address as written, so `/pages/etbi%CC%87s` with
the canonical `/pages/etbi%cc%87s` is an alias of an unread "other" page; its links are split between two nodes in the
importance graph (nihan: the ETBİS pages, linked from about 250 pages each). Compare decoded addresses there too; this
changes importance figures, so it waits for the owner.

## Key pages for sites that blocked Maya's crawler — done (DECISIONS 304)

Firecrawl's pages are grouped while the audit runs and kept as `crawl.reader_page_grouping` (schema 1.24). Saved
audits from before stay without importance (their copies keep no links).
