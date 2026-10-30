# Traditional technical SEO integration

This patch adds a small traditional on-page hygiene layer to Maya's existing audit. It deliberately
does not port OpenSEO's app, crawler, MCP server, paid research features, or Cloudflare infrastructure.

## What changed

- `TSEO-1` measures title and meta-description character lengths and detects skipped heading levels.
  Findings use Maya's `Finding` model: severity, confidence, rationale, evidence, scope, and a plain
  language fix. Length bands are editorial heuristics, not Google limits. The observation is Verified;
  the impact rationale is Hypothesis, so severity stays at S4.
- Maya's existing IDX checks continue to own HTTP status, redirect chains, and broken internal links.
  STR continues to own title/description presence, H1 and section checks, and image-alt coverage. PRF
  continues to own repeated response-time measurement and the optional PSI/CrUX panel. These paths
  were not duplicated.
- The HTML analyzer now keeps exact image counts even when it stores only 200 image details. STR-7
  reports incomplete coverage for the unclassified remainder and ambiguous empty-alt images instead
  of implying that those images passed.
- `TSEO-1` excludes pages with a raw-vs-rendered content gap and truncated HTML. If a crawl is partial,
  unvisited discovered URLs are listed in coverage. A clean result with these gaps becomes `partial`,
  never `pass`.

## OpenSEO references and adaptation

The implementation was read from OpenSEO commit
[`0ffff93101043aad7600a3b6a499a0cd2887ef49`](https://github.com/every-app/open-seo/tree/0ffff93101043aad7600a3b6a499a0cd2887ef49).

- The title/meta guidance bands correspond to constants in
  [`page-reporters.ts`](https://github.com/every-app/open-seo/blob/0ffff93101043aad7600a3b6a499a0cd2887ef49/src/server/lib/audit/issues/page-reporters.ts#L27-L30).
- The heading-order check corresponds to OpenSEO's
  [`heading-order-skip` issue definition](https://github.com/every-app/open-seo/blob/0ffff93101043aad7600a3b6a499a0cd2887ef49/src/shared/audit-issues.ts).
- OpenSEO's per-page analyzer, multi-page checks, and scratchpad implement direct crawl extraction,
  redirect, and link-graph ideas. Maya already had corresponding IDX/STR/PRF coverage, so that code
  was not ported. Maya's own status/refetch and crawl-completeness behavior remains the source of truth.
- OpenSEO records issue severity and fix text but has no confidence field. Its issue objects were not
  copied; Maya's confidence, evidence, rationale, and coverage conventions are used instead.
- The Cloudflare Durable Object scratchpad is a good solution for resumable Workflow chunks. Maya is
  a single-process Python crawler, so that infrastructure is not useful to transplant.

## Paid services and performance

The new check has no external service and no API key requirement. OpenSEO's optional Lighthouse path
uses DataForSEO's paid `/v3/on_page/lighthouse/live/json` endpoint and is not included. Maya already
has an optional PSI/CrUX panel in PRF-3 that uses Google's quota-limited API; it remains separate and
is not required for TSEO-1.

Keyword research, rank tracking, AI Search research, and Local SEO provider lookups remain out of
scope because OpenSEO calls paid DataForSEO endpoints for those features.

Backlinks are the exception, added later as Maya's own optional panel (`--dataforseo`, checks `DFS-1`
and `DFS-2`; see the README). It is a re-implementation in Python: no OpenSEO or claude-seo code was
copied. Two ideas were taken from them: reserving an estimate and settling on the billed cost
(OpenSEO), and the per-request plus per-row shape of the backlink price estimate. The price figures
themselves are upper bounds to be checked against the account, not either project's table.

## Testing and live-site status

The integration adds fake-server scenarios for short/long metadata, valid near misses, skipped heading
levels, partial crawls, meaningful images with empty alt text, and the 200-image extraction cap.
Coverage rules are also tested to ensure incomplete inputs do not pass silently.

Run in the Maya project:

```sh
.venv/bin/python -m pytest -q
```

The package's local test suite was run after these fixes: **303 passed, 11 skipped**. Ten skipped
tests require a browser; this Mac's installed Chromium exits with SIGTRAP before launch, so the new
real WebSocket browser test could not execute here. One other skipped test needs a saved live-run
example. Focused checks for deadline skipping, short-budget robots sampling, loopback blocking,
output preflight, cross-process locking, render-collector failure, citation wording, and Markdown
heading order passed.

The full CLI was also run against a localhost fixture with deliberately known problems. It fetched
six pages and made 18 requests, all to `127.0.0.1`. INT-1 was OK, INT-2 complete, and INT-4 compliant.
The report correctly found a 404, a broken internal link, a two-hop redirect, a missing image alt,
two short titles, two short descriptions, and an H2-to-H4 jump. TSEO-1 produced three grouped
findings with evidence and fixes. Response timings from localhost are only plumbing checks, not
representative web performance.

**Rendering did not run in this environment:** Playwright Chromium exited with SIGTRAP. INT-3
disclosed that limitation; it was not presented as a successful render. GSC, Bing, citation, and
PageSpeed/CrUX data were not configured, so their checks reported Not assessed and made no API calls.

TSEO-1 was also applied offline to captured crawl evidence from Midas (Sep 22, 2026), withmaya.ai
(Sep 22), Moodist (Sep 17), and Carpex (Sep 22). The first three had readable page snapshots; Carpex
had been blocked and correctly returned Not assessed. These are older saved snapshots, not fresh
visits and not a substitute for a current live-site usability review.

The configured public bot-information URL, `https://withmaya.ai/maya-audit-bot`, returned HTTP 404
in the historical check. The current code no longer makes that page a start-up requirement: it
records a missing or unavailable page in the report and continues with the site entered by the
operator. The entered starting host is allowed automatically. The bot-information page is still
recommended so site owners can identify the crawler, but it is not needed to run an audit.

The live-site runs listed above are earlier runs and do not verify this new startup behavior. A
focused offline regression check for both “no bot page configured” and “bot page returns 404” passed
after the change. The normal live runbook still applies: audit only sites you own or are authorized
to check, follow `robots.txt`, and stop if the site blocks or rate-limits the crawler.

The implementation has 49 named checks/gates: 40 site checks, five separate answer-engine checks,
and four integrity gates. The answer-engine checks remain separate from site findings.

## License and attribution

The source itself describes the crawl-throttle pattern, SQLite scratchpad pattern, and agent-skill
editorial approach as ported or adapted from OpenSEO. The earlier claim that this package contained
no copied/adapted material was too broad and has been withdrawn. The OpenSEO MIT notice is included
at `licenses/OPENSEO-MIT-LICENSE.txt` to preserve the notice with the package. The implementation
should still receive a human license review before external redistribution, to confirm whether the
adaptations include substantial copied portions and whether further source attribution is needed.
