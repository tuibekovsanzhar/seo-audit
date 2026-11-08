# Backlog

Decided later, by the owner. Each item names where its evidence is; nothing here is implemented.

## Next: Maya dashboard TOP PAGES as importance (after DECISIONS 311, owner 2026-11-05)

Page importance has a source field (`importance_source`: `links`, `profile:<id>`). The next source is
`maya_top_pages`: the pages with the most Google Search Console clicks from the Maya dashboard's TOP PAGES.

- First a CSV upload per audit (address, clicks, impressions, period), kept beside the audit like review.json; later the
  dashboard's API.
- Addresses merged before matching: `http`/`https`, with and without `www.`, a trailing slash, and the canonical
  aliases of DECISIONS 298, so one page's clicks are never split.
- To decide: how clicks combine with the profile weight and link score (for example a share of the 50% type weight, or
  a floor for the top 10 by clicks); pages with clicks that were not read are listed apart, never scored as read.

## Stage 7: the sector method's checks Maya cannot fill yet (DECISIONS 324, owner 2026-11-08)

Seven of the team's 218 checks (`docs/business-types/Sektor_Bazli_SEO_Audit_Onceligi.xlsm`) are missing in Maya but can
be automated; until then their "Durum" stays "Kontrol Edilmedi" with "Maya bunu henüz otomatik denetlemiyor (Stage 7)".
The mapping and every check's partial gaps: `maya_audit/sector_method.json` (built by `tools/sector_method_build.py`)
and the Step 1 analysis `reviews/sector-method/mapping.xlsx` (offline, not in git).

| Check | Sector / page type | What to add | Size |
|---|---|---|---|
| CORE-011 URL parametreleri ve filtre indekslemesi | all | parameter/filter combinations per template (counts per pattern and parameter, indexable combinations) | M |
| SEC-001 Filtre URL'leri ve indeksleme | E-ticaret / Kategori ve listeleme | the same rule on category templates | M |
| SEC-163 Arama/filtre URL mimarisi | Seyahat / Destinasyon, otel ve tur listeleri | date/guest/price parameter combinations, pagination, canonical per template | M |
| SEC-013 Süresi biten kampanyalar | E-ticaret / Kampanya | campaign pages past their end date (Offer `validThrough`, dates in the text) still 200 and linked | M |
| SEC-052 Kampanya tarihi ve yaşam döngüsü | Kart / Kampanya | the same rule | M |
| SEC-172 Kampanya tarihi ve uygunluk | Seyahat / Kampanyalar | the same rule | M |
| SEC-097 Karar destek içeriği | Otomotiv / Teknik rehber | guides that link to no rank-1 page (model detail) | S |

The draft Havayolu rows hold two more of these (flight search parameters, expired fares), awaiting İlginay/Efsa.

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

## Key pages for sites that blocked Maya's crawler — done (DECISIONS 304)

Firecrawl's pages are grouped while the audit runs and kept as `crawl.reader_page_grouping` (schema 1.24). Saved
audits from before stay without importance (their copies keep no links).
