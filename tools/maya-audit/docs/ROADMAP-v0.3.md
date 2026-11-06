# Roadmap v0.3

The owner's plan for v0.3 (2026-11-03). Each stage records its status here; the details of finished stages are in
`docs/IMPLEMENTATION-STATUS.md` and their decisions in `docs/DECISIONS.md`.

## Goals

- **Client report:** at most 10 pages, with the top 10-15 issues.
- **Business-type profiles:** checks switched on or off by the kind of business (e-commerce, local business, finance,
  SaaS, other).
- **Time:** a normal audit in under 10 minutes; a Standard 500 audit in under 25 minutes.

## Stages

| Stage | What | Status |
|---|---|---|
| 0 | w14d release | Done |
| 1 | Measure where an audit's time goes | Done (IMPLEMENTATION-STATUS, "v0.3 stage 1") |
| 2 | Speed | Done (`762ac12`, `8015f0d`; DECISIONS 294-296, 299) |
| 3 | Page types and importance | Done (`f338bb5`, `ecad113`; DECISIONS 297, 298) |
| 4 | Business-type field and profiles | Done, not pushed (DECISIONS 311): 14 profiles from `docs/business-types/`, page types per profile, importance 50/35/15, suggestion, "not found" notes, time estimates from current-engine runs, hide in history. Next: dashboard TOP PAGES as importance (BACKLOG) |
| 5 | Smart sampling (about 150 pages, under 10 minutes) | Planned |
| 6 | Priority score, 10-page client report, XLSX appendix, release-gate rule | Done, not pushed (DECISIONS 300-302); team report from the web app, one template (DECISIONS 307); current engine first, one language per click (DECISIONS 308); confirmations, platform steps, key pages, low coverage, history list, words (DECISIONS 309); web app UX: one clear path (DECISIONS 310); the client brief "Müşteri özeti", at most 5 pages, TR/EN, web download and skill option (DECISIONS 319, not pushed) |
| 7 | Type-specific checks | Planned; includes switching checks on or off by business type (the "Profiles (Stage 4)" sheet of `reviews/checklist/mapping.xlsx`, moved here from Stage 4, owner 2026-11-05). Done ahead: the checklist's quick checks (DECISIONS 304; mapping 61% -> 66% done) |
| 8 | Screaming Frog borrowings: redirect chains, image weight and size, mixed content, URL parameters, rich-result schema rules, key-pages list mode, PageSpeed key | 8a done, not pushed (DECISIONS 315): redirect hops and links to redirects, one card per redirect/canonical chain, issue type (Sorun / Kontrol edin / Fırsat), problems per template, canonical chains, hreflang target language, images over 100 KB. Left: mixed content, URL parameters, rich-result rules, list mode, PageSpeed key |
| 9 | Benchmark and release w15; delete the deprecated `maya-audit-rapor` report (DECISIONS 302) | Planned |

## Inputs

- The 165-item checklist mapped to Maya's rules (offline, not in git): `reviews/checklist/mapping.xlsx`, with the
  missing-automatable items, their size, the Stage 8 column and the business-type profile switches.
- The nihan scorecard against the same checklist: `reviews/checklist/nihan-checklist-scorecard.xlsx`.
- Backlog items found on the way: `docs/BACKLOG.md`.
