# What was taken from OpenSEO, and what was not

OpenSEO (https://github.com/every-app/open-seo, MIT, Ben Senescu) was a reference for this project. Its licence
notice is kept at `licenses/OPENSEO-MIT-LICENSE.txt`. `INTEGRATION.md` records the earlier adaptation, read from
commit `0ffff93101043aad7600a3b6a499a0cd2887ef49`. A later review of OpenSEO, done before this stage, looked at
commit `deb44913c2e345ec29ce6fb066a94ca428ebc681`; its conclusions were given to this stage as requirements.

**In this stage no OpenSEO source was fetched, read, copied or run.** The work below was done from the review's
written conclusions and from Maya's own code. Nothing in OpenSEO's repository was installed, no OpenSEO skill was
executed, and its hosted service was not connected.

## Ideas adopted, in Maya's own form

| Idea | Where it landed | How it differs |
|---|---|---|
| Duplicate meta descriptions | Engine check `STR-16` | Indexable pages only; noindex, canonicalised, paginated, truncated and JavaScript-dependent pages and language versions are left out and counted; S4 with a "hypothesis" rationale, because shared snippets are not shown to harm ranking. |
| Dead-end pages | Engine check `STR-17` | A note (Info), not a failure. Pages with a form, pages that end by design, and scripted pages that were not rendered are left out and counted. |
| A fixture matrix per check | `docs/FIXTURE-MATRIX.md`, generated from Maya's own tests | Maya's fixtures were reused; OpenSEO's test application was not copied. |
| Confirmed business context (from `seo-project-setup`) | `PUT /projects/{id}/profile` and the plan card | Optional, never an interview before an audit, and it cannot change a finding. |
| Short summary, concrete recommendation, visible evidence, stated limits (from `seo-report`) | The results card, the action plan, the PDF | Built from Maya's JSON, with no MCP calls; the full findings always remain. |
| Skill data-readiness | `maya_audit/ai_skills/prompts.py` | A named check must be assessed and hold data; a measured zero counts. |

## Deliberately not adopted

- Word-count penalties, a universal single-H1 rule, and title-length rules presented as ranking facts.
- OpenSEO's simpler versions of checks Maya already does in more depth (structured data, language, rendered
  content, integrity, confidence, coverage).
- Its application infrastructure, hosted service, MCP tools, keyword research, competitor crawling and Maps tracking.
- **Its consent rules for paid research.** OpenSEO's rules were not imported. When this page was written Maya's rule
  was an explicit confirmation of the exact maximum before every new charge and a $2 daily limit. The owner changed
  Maya's own limits on 2026-10-08 and 2026-10-09 (decisions 131 to 135 in `docs/DECISIONS.md`) and again on
  2026-10-14 (decision 192): $20 a day, confirmation above $2 an audit and never more than $5 an audit for
  DataForSEO, and the Firecrawl basic reader without a separate confirmation.

## Upstream limits recorded by the review (not re-checked here)

- OpenSEO's prompt-research workflow is US English only, and its questions come largely from Google's "People also
  ask". It does not measure what people actually ask ChatGPT.
- Its skill-evaluation harness can make real paid requests. Only its ideas (repeated runs, held-out cases) are of
  use here, with offline reports and mocks.

## Phase 2 (2026-10-09): discovery, pacing and reading order

**What was read.** No copy of OpenSEO was attached to this checkout. Its public source was read at commit
`deb44913c2e345ec29ce6fb066a94ca428ebc681` through a page-fetch tool, which returns a summary of each file rather
than a guaranteed verbatim copy: `crawl-window.ts`, `rendered-page.ts` and `discovery.ts`. Nothing was run, and its
hosted service was not contacted.

**What was reused.** Ideas only. No OpenSEO code was copied or translated line by line, so no file in Maya carries
OpenSEO's copyright header. The MIT notice is kept at `licenses/OPENSEO-MIT-LICENSE.txt` and credited in the module
that holds the adapted shape.

| OpenSEO pattern | Where it landed in Maya | How it differs |
|---|---|---|
| Discovery from several sources merged into one bounded list (sitemap, links, known pages) | `maya_audit/firecrawl/reading.py`: `discover_through_reader`, `ReadingQueue` | Maya asks for a sitemap through the reader only when its own crawler was challenged; two documents at most; robots.txt is obeyed; every request is inside the confirmed credit maximum. |
| A crawl window: a fixed budget of time shared out before work starts | `CrawlConfig.reader_reserve_s`, `runclock.reader_allowance_s` | Maya keeps one deadline for the whole audit (Phase 1B) and reserves part of it for the reader; the per-page figure is adjustable. |
| Stop a source that keeps failing rather than draining the budget | `Options.stop_after_unreadable` | Maya counts only answers that are a challenge or unusable, never the site's own 404s, and reports the unasked pages as unchecked. |
| Persistent crawl state for resume | Not adopted | Maya already has checkpoints (`--resume`), a seven-day saved copy for a resumed audit and a spending ledger; a second mechanism would duplicate them. |
| Rendered-page capture | Not adopted | Maya already keeps raw, rendered (its own browser) and provider documents apart (`PageFetch.view`); nothing was added. |

## team-preview-7 (2026-10-09): lookups and bot-check detection

**What was read.** The owner's local copy at `~/Desktop/open-seo-evaluation` (commit
`89e5a00717cdf049b7c2b4e29646edb3a7d4995b`), read-only: `src/server/lib/audit/classify-fetch.ts` in full, and the
DNS-over-HTTPS lines of `src/server/lib/audit/url-policy.ts`. Nothing was run.

**What was reused.** Ideas and two short lists; no code was copied or translated line by line.

| OpenSEO pattern | Where it landed in Maya | How it differs |
|---|---|---|
| Destination safety through a JSON DNS-over-HTTPS query (A and AAAA, 2.5 s), where a lookup that returns nothing does not block the audit and only private or reserved addresses are refused | `maya_audit/resolver.py`, `maya_audit/urls.py` | Maya asks the system resolver first and retries it once; DNS over HTTPS is the fallback, with Google after Cloudflare, each reached by IP address. Maya then connects to the checked addresses. A name no resolver can look up is not connected to at all. |
| `classify-fetch`: 202 is a challenge; `cf-mitigated`; 429 before `cf-mitigated`; Cloudflare titles and body markers; SiteGround's captcha path | `maya_audit/classify.py` | Expressed as rows of Maya's existing signature table with its Verified/Estimated confidence. Maya already had the two Cloudflare titles, `cf-mitigated: challenge` and the challenge-platform script. |
