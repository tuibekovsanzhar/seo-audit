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
| 6 | Priority score, 10-page client report, XLSX appendix, release-gate rule | Done, not pushed (DECISIONS 300-302); team report from the web app, one template (DECISIONS 307); current engine first, one language per click (DECISIONS 308); confirmations, platform steps, key pages, low coverage, history list, words (DECISIONS 309); web app UX: one clear path (DECISIONS 310); the client brief "Müşteri özeti", at most 5 pages, TR/EN, web download and skill option (DECISIONS 319); cards never block printing, brief SEO owner, 429 service words (DECISIONS 320); fixes from reviewing the briefs: certificate expiry, host-level cards, coverage line, merged owners, XLSX notes (DECISIONS 321); the XLSX appendix for non-technical teammates (Nasıl okunur, Özet, Sayfa bazında, Bulgu bazında), "Etkilenen sayfalar" on the web cards, inclusive certificate bands (DECISIONS 322); "Okundu mu?" and a measured value for every page read, schema 1.29 (DECISIONS 323, not pushed); the team's sector method: P0-P3 on the cards (impact from severity, effort 3, automatic P0 for an indexing blocker, P0 marks in review.json), plain words in the brief, the "Sektör audit" XLSX in the team's five-sheet format, homepage weights by the sector's rank (DECISIONS 324, not pushed) |
| 7 | Type-specific checks | Planned; the 7 checks of the team's sector method that are missing but automatable (BACKLOG, DECISIONS 324); includes switching checks on or off by business type (the "Profiles (Stage 4)" sheet of `reviews/checklist/mapping.xlsx`, moved here from Stage 4, owner 2026-11-05). Done ahead: the checklist's quick checks (DECISIONS 304; mapping 61% -> 66% done) |
| 8 | Screaming Frog borrowings: redirect chains, image weight and size, mixed content, URL parameters, rich-result schema rules, key-pages list mode, PageSpeed key | 8a done, not pushed (DECISIONS 315): redirect hops and links to redirects, one card per redirect/canonical chain, issue type (Sorun / Kontrol edin / Fırsat), problems per template, canonical chains, hreflang target language, images over 100 KB. Left: mixed content, URL parameters, rich-result rules, list mode, PageSpeed key |
| 9 | Benchmark and release w15; delete the deprecated `maya-audit-rapor` report (DECISIONS 302) | Planned |

## Inputs

- The 165-item checklist mapped to Maya's rules (offline, not in git): `reviews/checklist/mapping.xlsx`, with the
  missing-automatable items, their size, the Stage 8 column and the business-type profile switches.
- The nihan scorecard against the same checklist: `reviews/checklist/nihan-checklist-scorecard.xlsx`.
- The team's sector audit method (İlginay, from Efsa's sector list): `docs/business-types/Sektor_Bazli_SEO_Audit_Onceligi.xlsm`,
  its 218 checks mapped to Maya's rules in `maya_audit/sector_method.json`; Step 1 analysis `reviews/sector-method/`
  (offline, not in git).
- Backlog items found on the way: `docs/BACKLOG.md`.
