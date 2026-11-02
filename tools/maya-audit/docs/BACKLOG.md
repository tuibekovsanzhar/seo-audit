# Backlog

Decided later, by the owner. Each item names where its evidence is; nothing here is implemented.

## Firecrawl only where needed (DECISIONS 296, 2026-11-02)

Firecrawl reads a page only when Maya could not read it (blocked, challenged, 429, empty, no answer), or when its
template depends on JavaScript (the render sample shows rendered text well above raw, or the raw page is an app shell);
every other page keeps Maya's own reading. On the three saved audits that is 0 Firecrawl pages and 0 credits a run.

Open question for the owner: which copy the content checks judge on a site that reads fine without JavaScript. On
nihan (offline comparison, 499 pages read by both): thin pages 162 (Maya's copy) vs 13 (Firecrawl's); heading jumps 214
vs 47; STR-12 (Medium) only on Firecrawl's copy. Evidence: `docs/IMPLEMENTATION-STATUS.md`, "Double reading".
