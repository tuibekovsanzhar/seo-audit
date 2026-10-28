# Testing: how this build is checked

The test suite is designed to use scripted local websites only. An automatic loopback-only socket
guard now fails any test that tries to open a non-loopback connection. This is separate from the
saved live-run reports, which are dated examples rather than repeatable tests. See
[`LAUNCH-GATE.md`](LAUNCH-GATE.md) for the history and limits of real-site checks.

```sh
.venv/bin/python -m pytest -q          # full suite; rendering needs Chromium
```

## The three layers

**1. Fake websites (`fakeserver/`).** A small threaded HTTP server plays a scripted site on
127.0.0.1: routes can be functions, so a page can fail on its first request and work on its third,
delay past a timeout, drop the connection, or serve a different body to a bot user agent. TLS
scenarios use a local test CA. Fake Google and Bing APIs are served the same way.

**2. The server keeps its own request log.** Tests assert against *what the site actually
received*, not only against what Maya reported. This is how robots.txt compliance, probe tagging,
politeness, and "nothing was fetched outside the audited site" are checked — a bug in Maya's own
bookkeeping cannot hide a violation, because the check does not go through Maya's bookkeeping.

**3. Mutation checks.** For every rule that matters, the rule was deliberately broken and the suite
re-run to prove a test fails. A rule with no failing test is not protected, whatever the coverage
number says. Roughly 60 mutations were run across the categories; each round's misses were real
test gaps and were fixed. Two documented exceptions:

- one IDX-6 guard is an *equivalent mutant* — the code it protects cannot be reached with today's
  data flows, so no test can see a difference;
- an early "the ANS panel never changes site findings" test compared two runs of the same code and
  could not catch in-place mutation. It now re-runs every site check from the same crawl and
  compares against fresh objects.

The mutation scripts themselves are not in the repo (they were run ad hoc). If you change a rule,
break it on purpose once and confirm a test fails.

## How to add a check

1. Put the rule in the spec first, with its severity, confidence, cost tier, and rationale.
2. Add a scenario to the matching `fakeserver/*_scenarios.py` that shows the failure **and** a
   near-miss that must not fire.
3. Write the check so that anything it cannot judge is `not_assessed` with a reason, never a pass.
   If the check can judge part of its question but not all of it, record the unjudged part in its
   evidence and add a rule for it in `maya_audit/coverage.py`, so a clean result on the rest reads as
   `partial`, not `pass`. `tests/test_evidence_integrity.py` has the pattern: one row per gap, plus
   a test that complete evidence adds no gap.
4. Add the test, then break the rule on purpose and confirm the test fails.
5. Record any decision the spec did not make in [`DECISIONS.md`](DECISIONS.md), and anything
   unverified in [`LAUNCH-GATE.md`](LAUNCH-GATE.md).

## Demo scripts

Each prints a full report for its category, then the server's own request log.

```sh
.venv/bin/python scripts/demo_int.py     # 12 integrity scenarios
.venv/bin/python scripts/demo_acc.py     # 13 access runs
.venv/bin/python scripts/demo_idx.py     # 16 indexability runs, incl. HTTPS and fake Google/Bing APIs
.venv/bin/python scripts/demo_rnd.py     # 3 rendering runs (one with real headless Chromium)
.venv/bin/python scripts/demo_str.py     # 6 structure runs (two with a second origin)
.venv/bin/python scripts/demo_prf.py     # 5 performance runs (two with fake PageSpeed/CrUX APIs)
.venv/bin/python scripts/demo_ans.py     # 3 answer-engine panel runs
```

Add `--json-dir reports` to any of them to write the full evidence JSON.

## Scenario reference

### INT scenarios (`fakeserver/scenarios.py`)

| Scenario | What the fake site does |
|---|---|
| `healthy` | Normal site with a robots.txt-disallowed path and a sitemap-only page |
| `cloudflare_challenge` | Every page returns 403 with `cf-mitigated: challenge` |
| `forbidden_mix` | One plain 403, and one 200 whose body is a challenge page (signature only) |
| `rate_limited` | 429 with `Retry-After: 120` from the fourth page on |
| `rate_limited_transient` | One 429 with `Retry-After: 0`, then success |
| `robots_block` | `Disallow: /` for all user agents |
| `robots_503` | robots.txt returns 503 (RFC 9309: complete disallow) |
| `robots_maya_group` | `*` is blocked, but `Maya-Audit` has its own narrower group |
| `page_cap` | 31 pages crawled with a 10-page cap |
| `transport_errors` | One timeout, one dropped connection |
| `time_limit` | Slow pages against a 1 s limit |
| `start_redirect` | Start URL 301s to `/home` |

### ACC scenarios (`fakeserver/acc_scenarios.py`)

| Scenario | What the fake site does |
|---|---|
| `acc_ai_friendly` | Ownership-verified, open robots.txt, no page controls, no WAF |
| `acc_robots_rules` | robots.txt blocks training bots, PerplexityBot, OAI-SearchBot on `/pricing`, ChatGPT-User on `/docs/`; Crawl-delay 120 |
| `acc_meta_controls` | `noindex`, `nosnippet` header, `max-snippet:0`/`:20`, `data-nosnippet`, bingbot `noarchive` |
| `acc_waf_verified` | Verified site whose WAF challenges, rate-limits, or degrades specific bot user agents |
| `acc_waf_not_owned` | Same WAF, ownership not verified: no probes may be sent |
| `acc_robots_flaky` | robots.txt answers 200, 503, 200 |
| `acc_robots_html` / `acc_robots_huge` | robots.txt is an HTML page / larger than 500 KiB |
| `acc_llms_txt` | An llms.txt file exists |
| `acc_crawl_delay_capped` | robots.txt asks Maya for a Crawl-delay above the cap |
| `acc_waf_v2` | ACC-4 v2: a 404 only for MistralAI-User, a redirect only for Amazonbot, same title but different text for Applebot, and a page that changes after the first probe (only a fresh browser baseline tells change from cloaking) |

`demo_acc.py` also runs three variants: a declared training-bot policy plus an
intent marking, a `/tag/*` marking that must not cover a key page, and ACC-5
with a sample access log and IP-range file.

### IDX scenarios (`fakeserver/idx_scenarios.py`)

| Scenario | What the fake site does |
|---|---|
| `idx_status_codes` | 404s (linked, sitemap-only, behind a redirect), a persistent 500, a transient 500, an always-timing-out page, a dropped connection |
| `idx_start_404` | The start URL is a 404 nothing links to |
| `idx_redirects` | A 2-hop chain, a two-URL loop, a self-redirect |
| `idx_canonicals` | Self, conflicting (HTML vs `Link` header), broken, noindexed, identical, near-identical, different, redirecting, and off-site canonicals |
| `idx_sitemap_health` / `idx_sitemap_future` | 3 of 11 sitemap URLs broken or noindex with identical lastmods / a lastmod in 2099 |
| `idx_no_sitemap_large` / `_small` | No sitemap on 61 pages / on 11 pages |
| `idx_orphans_depth` | Two sitemap-only pages and a page 5 clicks deep |
| `idx_duplicates` | Identical text, shared titles, near-identical text, plus noindex and canonicalized copies that must be excluded |
| `idx_gsc_bing` | Key pages checked against a fake Search Console URL Inspection API and a fake Bing GetUrlInfo API, plus an IndexNow key |
| `idx_tls_*` (5 runs) | HTTPS on `localhost` and `www.localhost` with a local test CA: valid, expiring in 7 days, expired, hostname mismatch, and no HTTP→HTTPS redirect |

### RND scenarios (`fakeserver/rnd_scenarios.py`)

| Scenario | What the fake site does |
|---|---|
| `rnd_csr_app` (rendered) | Client-rendered homepage and pricing page, a partly rendered page, a server-rendered page, a script on another origin, a robots-disallowed script, a page with tabs / "load more" / a form button / a POST beacon, and a client-rendered page left outside a 7-page render budget |
| `rnd_walls` | Redirect to a login page, a cookie wall in place of content, an age gate, paywalls with and without structured data, and a normal page with a cookie banner that must not be flagged |
| `rnd_nontext_payload` | Canvas, iframe, wide images without alt, a 1 MB+ page whose main content starts late, a boilerplate-heavy page, a page without `<main>`, and a PDF link |

`rnd_walls` also has a Turkish cookie wall (`lang="tr"`) that the English signatures cannot see: it must be
reported as **not assessed**, never as "no wall".

### STR scenarios (`fakeserver/str_scenarios.py`)

| Scenario | What the fake site does |
|---|---|
| `str_pages` | Missing, duplicate (plus noindex and canonicalized copies that must not count), and generic titles; no `<h1>`, two `<h1>`s, a long page without subheadings, question headings; a client-rendered shell (RND-1's root cause); no `lang`; missing preview tags and a 404 `og:image` |
| `str_structured_data` | JSON-LD and Microdata whose price, currency, availability, rating, product name, author, and dates disagree with the page; a price not shown at all; a JSON-LD parse error; missing Google-required properties and expected types; a Turkish product and post; stale, future-dated, and missing dates; a `Last-Modified` header generated per request |
| `str_autostamp` | Every sitemap `<lastmod>` is the audit day |
| `str_markup_contradictions` | STR-11: JSON-LD vs Microdata price, one `@id` with two availabilities, an article with two publication dates, plus agreeing descriptions, two different products, a conflict STR-4 already owns, and an unparseable block |
| `str_images_grids` | Images with and without alt in and out of `<main>` (chart, figure, icon, banner), pricing and other `<div>` grids, footer link columns, prose cards, a real `<table>`, numbered paragraphs |
| `str_entity_links` / `_external` | Two origins: brand-name variants, `sameAs` links (live, 404, robots-blocked), `og:image` on the other origin, hreflang with a one-way link, a 404 target, a robots-disallowed target, a target on the other origin, and a Turkish page declared `lang="en"`. Run once with external link checks off (`check_external_links=False`: the other origin receives only its robots.txt and the sameAs requests, DECISIONS 211) and once with the default (on) |
| `traditional_seo_quality` | Short/long title and meta-description examples plus a skipped heading level; in-band metadata and sequential headings are near misses |
| `str_images_over_cap` | 205 main-content images; exact missing-alt totals remain visible past the 200-detail cap and the check becomes `partial` for unclassified images |

### PRF scenarios (`fakeserver/prf_scenarios.py`)

| Scenario | What the fake site does |
|---|---|
| `prf_mixed` | A slow key page (every fetch), a page slow only on its first fetch (the median must not flag it), a key page that returns 500 once in three, a page that fails on the crawl **and** the IDX-1 refetch but then works (must not be an IDX-1 S1), a page that times out once, one that drops the connection once, a persistent 500, a challenge page (not counted), and a `/blog/` template |
| `prf_healthy` | Three fast pages and no failures (too few attempts to judge a sitewide rate) |
| `prf_rate_limited` | The INT `rate_limited` site: the crawl stops on a long `Retry-After`, so PRF must send **no** extra requests |
| `prf_pagespeed` / `_verified` | PRF-3 against fake PageSpeed Insights and CrUX APIs. The PSI response includes a Lighthouse category score that must never be read. Unverified site: CrUX only, and the PSI API receives zero requests. Verified: 3 lab runs per key page (median) plus CrUX with an origin fallback |

The thresholds in these runs are scaled down so the tests take seconds (0.3 s instead of 1.5 s, a 1 s timeout instead
of 15 s). The rules are the same.

### ANS runs (`fakeserver/ans_scenarios.py`)

| Run | What it covers |
|---|---|
| `ans_cited_pages` | Cited pages that 404 (never crawled), redirect, are noindexed, are client-rendered, are disallowed for a search bot or for everyone, plus healthy ones. Two engines, one cited page on another site, two invalid records, and answers quoting a stale price, a matching price, a price with no claims supplied, and a wrong founding year |
| `ans_zero_citations` | A citation file with zero records: reads as **0 citations**, not as "no data" |
| `ans_no_citation_data` | No `--citations` at all: the panel reads **Not assessed** |

### Evidence integrity (`tests/test_evidence_integrity.py`)

Unit tests for the report 0.4 status model and the Phase 1 fixes from
[`PHASE-0-RECONNAISSANCE.md`](PHASE-0-RECONNAISSANCE.md): every coverage rule with enough,
insufficient, capped and missing evidence; the 0.3 → 0.4 migration, including a test that rebuilds
the 0.3 view of a live run and requires the migration to reach the same statuses; the severity ladder
the `ai_skills` prompts teach, checked against the spec's own §2.1 table; RND-3's English-only
fallback on a Turkish page; an ACC-4 difference the probe cap left unretried; STR-4 price conflicts
with one vs several visible prices; ANS-1 on a paged or all-invalid citation export; registry
provenance. A regression pin on the Moodist live report runs when `examples/` is present.
Eight mutations (one per rule) were run on 2026-09-22 and all eight were caught.

### Phase 2 additions (2026-09-22)

`rnd_csr_app`'s partial page now loads its extra section with `fetch()`, so RND-1's content delta can
name the data request; `/interactive` inserts 70 words on a 0.9 s timer with no click, so RND-3's
control snapshot has something to exclude. `ans_cited_pages` gained a same-content canonical, a
canonical to different content, a redirect into a 404, and ANS-2 claims that match, are absent, or
were compared upstream. Ten mutations (one per Phase 2 rule) were run and all ten were caught. The
rendering tests were run three times in a row to check the timer-based control is not flaky.

### Phase 3 additions (2026-09-22)

`str_stamped_headers` (a Last-Modified cache time 40 minutes old on every page, one identical
`dateModified`, real sitemap dates), `idx_sitemap_stamped_docs` (a sitemap document whose six URLs
share one timestamp beside one with real dates), `str_entity_graph` (an `@id` named two ways, a dangling
reference, a markup url that 404s, a url naming another page, one `@id` typed two ways, a clean page),
two PDFs on `acc_meta_controls` (one with `X-Robots-Tag: noindex`), and a `/two-ids` page on
`str_markup_contradictions` (two entities told apart only by `@id` fragments). Ten mutations, one per
Phase 3 rule, all caught. Run full suites with `--tb=long` into a file (LG-36).
# Deadline and hosted-use regression cases

`tests/test_deadline_hosted_hardening.py` covers deadline-skipped requests (including their exclusion from INT-4), short-budget robots.txt sampling, the hosted loopback block, Chromium/WebSocket network restrictions, existing-output preflight, the cross-process per-origin lock, render-collector failure handling, citation wording, and Markdown heading order. `tests/test_rnd_scenarios.py` contains a real browser test for a page that opens a WebSocket; it must run on a host where Playwright Chromium launches. `tests/test_urls.py` also pins the actual request order: robots.txt, sitemap discovery, then page fetches.

# Status, deadline, provider semantics and report agreement (2026-10-09)

- `tests/test_status_and_identity.py`: a direct challenge with a readable provider sample keeps the challenge and
  claims nothing about real crawlers; a capped or failed sample is incomplete; mixed sources are counted once; an
  unknown status stays unknown; redirects are recorded and another site's document is never analysed; INT-4 still
  degrades; privacy prose is not a placeholder; natural check order.
- `tests/test_run_clock.py`: fake clocks. Nothing is sent after the deadline or a stop; pacing; timeouts fit the time
  left; a cut-off request stays possibly billed and nothing follows it; the unspent approval survives.
- `tests/test_provider_semantics.py`: offline DataForSEO fixtures for a measured zero, an empty sample, missing, null
  and wrong-typed figures, partial Lighthouse answers, refusals by kind, and a profile that is not the business.
- `tests/test_report_agreement.py`: the demonstration app. The card, Markdown, printable page and JSON agree; the two
  demonstration sites added for this phase (`demo-partial.localhost`, `demo-app.localhost`) show partial coverage,
  missing provider data, a JavaScript site and true zeros.

The demonstration found one crash that no unit test had: a page Maya found only in the sitemap has no click depth,
and following its links through the reader raised a TypeError. Fixed, with a regression test.

# Coverage benchmark and reading order (2026-10-09, Phase 2)

`tests/test_coverage_phase2.py` covers the reader's queue order, sitemap parsing and its bounds, the sitemap being
asked for only after a first page was read, stopping after five unreadable answers, the cause on each unread page,
the time kept for the reader, and the claims of the benchmark on eleven of its thirteen cases (the two 500-page
cases are run by the script only, because they take about half a minute each).

`PYTHONPATH=. .venv/bin/python scripts/coverage_benchmark.py --write` rebuilds `docs/COVERAGE-BENCHMARK.md`. It uses
in-memory sites and a made-up reader; the network guard stays on. Its time and memory columns are from the computer
it ran on and change from run to run; the page, request and credit columns do not.

# Lookups, local failures, bot checks and the ambiguous brand word (2026-10-09)

`tests/test_network_and_dns.py`: the lookup order and its record; private addresses from a public resolver stay
refused; the three failure kinds; "not checked" in place of RFC 9309's disallow-all and of the ACC-1 Blocker when no
answer reached this computer; Firecrawl reading robots.txt itself; the pre-flight in the engine, the command line and
the web app; the added bot-check markers, for Maya's fetches and for a reader's pages; the ambiguous keyword group.
`tests/conftest.py` gives every test a resolver that looks up loopback names only and a DNS-over-HTTPS transport that
cannot connect, so no test reaches a real resolver.
