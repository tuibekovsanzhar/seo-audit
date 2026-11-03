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
| 4 | Business-type field and profiles | Next week. Input: the "Uygulanabilirlik" mapping in `reviews/checklist/mapping.xlsx` (sheet "Profiles (Stage 4)", and the profile columns of "Mapping") |
| 5 | Smart sampling (about 150 pages, under 10 minutes) | Planned |
| 6 | Priority score, 10-page client report, XLSX appendix, release-gate rule | Done, not pushed (DECISIONS 300) |
| 7 | Type-specific checks | Planned |
| 8 | Screaming Frog borrowings: redirect chains, image weight and size, mixed content, URL parameters, rich-result schema rules, key-pages list mode, PageSpeed key | Planned |
| 9 | Benchmark and release w15 | Planned |

## Inputs

- The 165-item checklist mapped to Maya's rules (offline, not in git): `reviews/checklist/mapping.xlsx`, with the
  missing-automatable items, their size, the Stage 8 column and the business-type profile switches.
- The nihan scorecard against the same checklist: `reviews/checklist/nihan-checklist-scorecard.xlsx`.
- Backlog items found on the way: `docs/BACKLOG.md`.
