# Proposal: read-only Google Search Console through a service account

Status: **proposal only, nothing built** (owner, 2026-11-09: "wait for my OK before building it"). Written after
DECISIONS 332. Builds on what exists: IDX-9 (URL Inspection with a short-lived OAuth access token,
`MAYA_AUDIT_GSC_TOKEN` and `--gsc-site-url`, at most 20 inspections, command line only).

## 1. Access

- **One Google service account for the team**, created once in Google Cloud with the *Search Console API* enabled.
  Its JSON key lives **outside the repository**, e.g. `~/.maya-audit/secrets/gsc-service-account.json` (folder 0700,
  file 0600). `.env` holds only the path: `MAYA_AUDIT_GSC_SERVICE_ACCOUNT=~/.maya-audit/secrets/gsc-service-account.json`.
  The key is never read into a report, a log, an error message or a test; tests use a made-up key file and recorded
  answers.
- **Per client**, the client adds the service account's address (`…@….iam.gserviceaccount.com`) as a *restricted*
  user of their property in Search Console. Restricted is enough for everything below; nothing is ever written.
- Scope `https://www.googleapis.com/auth/webmasters.readonly` only. Tokens are signed locally (JWT) and kept in memory
  for their hour; no refresh token is stored.
- The existing OAuth token (`MAYA_AUDIT_GSC_TOKEN`) stays as a second way in for a one-off run.

## 2. Matching a site to its property

`sites.list` returns the properties the account may read. For the audited address, in order:

1. a **domain property** `sc-domain:example.com` for the registrable domain (covers every host and both protocols);
2. else the **URL-prefix property** that is the longest prefix of the start address (`https://www.example.com/`,
   then `https://example.com/`, then `http://…`); a language folder property (`https://example.com/tr/`) is used only
   for addresses under it;
3. else none: the audit runs without Search Console and says why ("this site is not shared with Maya's Search Console
   account").

Several matching properties (domain + prefix): the domain one is used, the others are listed on the plan. The person
may pick another on the plan; the choice is saved per site (as the business type is).

## 3. What is read (all read-only, all from Google's documented API)

| Data | API | Default size | Used for |
|---|---|---|---|
| Clicks, impressions, CTR, position **per page** | Search Analytics `searchanalytics.query`, dimension `page`, last **28** and **90** days (data ends ~2-3 days before the audit) | up to 25,000 rows (one request per 25k) | importance, sampling, findings, Sektör rows |
| **Queries per page** | same, dimensions `page,query`, last 28 days, top 20 queries per page for the pages read | one request per 25k rows | intent and cannibalization rows |
| Search appearance / device / country | same, optional dimensions | off by default | country/device notes |
| **URL Inspection** for key pages | `urlInspection.index.inspect` | the key pages + one page per page type, at most **40** an audit (Google: 2,000 a day and 600 a minute per property) | indexed or not, Google's canonical vs ours, last crawl, robots/noindex as Google saw it, mobile usability, rich results |
| **Sitemaps** | `sitemaps.list` / `sitemaps.get` | every sitemap of the property | submitted vs indexed counts, last read, errors |

Not available through the API (said, not guessed): the Pages (coverage) report's reasons for every URL, the Core Web
Vitals report (CrUX stays the field data), Removals, manual actions and security issues, and URL Inspection's live
test.

## 4. Where it feeds in

- **Page importance** (DECISIONS 297/311): a fourth part, *search demand*: impressions of the last 28 days on a log
  scale (0-100). Proposed mix with Search Console: 40% page type, 25% internal links, 10% click depth, 25% search
  demand; without it, today's 50/35/15. Stored apart (`importance_parts.search_demand`), so the old value can be shown.
- **Akıllı sampling** (DECISIONS 327/331): a new share in the plan, **high-impression pages**: the top 10% of the budget
  goes to the pages with the most impressions that the plan would not read anyway, spread over page types; and inside
  a large type, the "importance" third ranks by impressions. A page with impressions that no crawl found becomes a
  known address (an orphan candidate).
- **Findings** (all *verified*, source "Google Search Console", with the date range):
  - IDX-9 as today, on more pages: indexed / not indexed with Google's reason, **Google-chosen canonical ≠ ours**
    (a canonical Google ignored), blocked by robots.txt or noindex as Google saw it.
  - *Pages with impressions that Maya's crawl never linked to* (orphans with demand, CORE-018).
  - *Two or more pages ranking for the same query* (cannibalization, CORE-029: same query, both with ≥10% of its
    impressions, over 28 days).
  - *Important pages with no impressions in 90 days* (a key page Google does not show).
  - *Sitemap submitted, few indexed* (sitemaps' submitted vs indexed counts).
  - Trends only as context, never as a severity (a drop is not proof of a fault).
- **Sektör audit** (DECISIONS 324-326): the rows whose gap is Search Console (below) get their Durum from these
  findings, the "Uygun" text says what was checked ("Search Console: 412 sayfanın 28 günlük gösterimleri ve 40 sayfanın
  dizin durumu kontrol edildi"), and "GSC sayfa tipi performans segmenti" (CORE-043) becomes a table per page type
  (clicks, impressions, CTR, average position).
- **Reports**: the team report gets a "Search Console" box (date range, property, per page type); the client brief may
  name a measured Search Console finding like any other; the XLSX appendix gets a "Search Console" sheet.

## 5. What the plan screen shows

- Key set and the site matched: "Search Console: sc-domain:example.com (alan adı mülkü), son 28/90 gün ve 40 sayfa
  incelemesi eklenir" with a switch to leave it out for one audit.
- Key set, no property: "Search Console: bu site Maya'nın Search Console hesabıyla paylaşılmamış. Müşteriden
  `…@….iam.gserviceaccount.com` adresini 'Kısıtlı' kullanıcı olarak eklemesini isteyin." with a copy button.
- No key: today's line "Search Console not available" with a pointer to TEAM-SETUP.
- Access refused during the audit (403, revoked): the audit goes on without it and the results say so.

## 6. Caching and quotas

- One local cache per property under `~/.maya-audit/gsc/` (SQLite, 0600): Search Analytics answers keyed by
  (property, dimensions, date range), kept 24 h (Google's data moves daily); URL Inspection answers kept 24 h; sitemaps
  1 h. A re-run the same day costs no request.
- A per-property daily ledger (like Firecrawl's): URL Inspections counted against Google's 2,000/day; the audit's own
  cap (40) is configurable; a 429 stops Search Console for that audit, never the audit.
- Time added: Search Analytics 2-4 requests (~5-10 s), URL Inspection 40 × ~1 s at Google's pace (beside the crawl, on
  its own lane), sitemaps 1-3 requests. About 1 minute in all, beside the other steps.

## 7. Privacy

Client data stays on the team member's computer: the cache, the report and the evidence are local, as today; nothing
is sent anywhere but Google's API. The report keeps aggregates and the pages Maya read; query rows are kept only for the
pages read and only in the local report (queries can hold personal data: they are never in the client brief, and the
XLSX shows at most the top 10 per page). The key file path is never written to a report.

## 8. What it moves in the team's 218 checks

Counted from `maya_audit/sector_method.json` (team rows, draft rows left out), today: 74 automatic (A), 116 partly
(K), 7 need data (G), 14 a person (P), 7 missing (M).

| Today | Rows | With Search Console |
|---|---|---|
| G, Search Console is the whole gap | 6: CORE-003, CORE-029, CORE-043, SEC-022, SEC-061, SEC-148 | 3 filled (index state, cannibalization, performance per page type); 3 to partly (queries vs topics still need a look) |
| G, also a search-results sample | 1: CORE-028 | to partly |
| K, Search Console is the whole gap | 9: CORE-006, -009, -013, -018, -023, -044, SEC-103, -124, -151 | 7 filled; CORE-009 (live test is not in the API) and CORE-013 (the CWV report is not in the API; CrUX stays) stay partly |
| K, also a search-results sample ("arama niyeti ve sayfa şablonu", one per page type) | 58 | stay partly with Search Console alone (the query side is filled); filled with Search Console + a DataForSEO SERP sample (paid, already integrated) |
| A, Search Console optional ("en iyi performanslı sayfa örneklemi") | 60 | already filled; gain the top-pages sample as extra evidence |

So with Search Console alone: **10 rows move to filled** (3 from "needs Search Console", 7 from "partly") and **4 move
from "needs Search Console" to "partly"**; **58 more** become fillable once a SERP sample is added; 60 automatic rows
get better evidence.

## 9. Build plan (after OK)

1. `maya_audit/gsc/` (auth from the key file, property matching, the three APIs, cache, ledger), tests with a made-up
   key and recorded answers; 2. plan line and switch, the lane beside the crawl; 3. IDX-9 on the new data and the four
   new findings; 4. importance and sampling; 5. Sektör rows, team report box, XLSX sheet; 6. TEAM-SETUP section for the
   service account. Schema bump (new `gsc` section). Estimated 2-3 working sessions.
