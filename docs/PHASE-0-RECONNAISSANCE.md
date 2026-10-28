# Phase 0 reconnaissance: auditing the audit (2026-09-22)

A read of the whole `maya_audit/` package, the tests, the docs, the three live runs in
`examples/live-runs/`, and a fresh clone of OpenSEO (`every-app/open-seo` at `0ffff93`,
2026-09-19), made before any v2 change. It is the record of what was found and why each Phase 1–4
change exists. Test baseline at the time: **216 passed, 9 skipped** (the rendering tests skip
without Chromium).

**Decisions taken on this document (2026-09-22):**

1. **Status vocabulary: `partial` and `observed` are added** (report 0.3 → 0.4). A compatible option
   (coverage data with the old statuses) was rejected on purpose: it would let `pass` keep meaning
   two different things, which is the overclaiming this work exists to remove.
2. **All six P1 items are approved** for Phase 2.
3. This file is the permanent record.

**Headline.** The finding model is mostly sound: severity is never discounted for uncertainty, and
the Hypothesis cap holds everywhere. The largest real defect is one level up: **a check whose
evidence was only partly assessed reported `pass`.** The live runs show it on six checks across
three real sites.

---

## A. Architecture (from code)

```
cli.py  →  CrawlConfig (every threshold, recorded in the report)
 ↓
Crawler.run()   live-host guard + bot-info preflight (botinfo.py)
 ↓  robots.txt → sitemaps → key pages → breadth-first pages   [SQLite frontier, resume, backoff]
Fetcher.get()   one user agent, no cookies, redirects not followed, every request logged
 ↓
classify_fetch()   INT-1 per page: headers/status = Verified, body signature = Estimated
analyze_html()     one pass per page → PageFetch.analysis
 ↓
post_crawl collectors (same fetcher, audited by INT-4):
  access_data · index_data · render · structure_data · perf_data · ans_data / ans_domains
 ↓
run_integrity_gates → GateResult (no severity)
run_*_checks        → CheckResult{status, summary, findings, evidence, observations, review_items}
run_answer_checks   → reads site checks, never changes them
 ↓
report.py  text + JSON (site checks / answer_engine_panel kept apart);  build_llm_brief (ai_skills)
```

- **Severity**, **confidence** and **rationale** are literals set in each check function.
  Rationale is free text (`str`), and ANS-4 passed the enum object.
- **Not assessed** existed at two levels: whole-check (`status="not_assessed"`) and sub-part (keys in
  `evidence` such as `not_assessed`, `*_inconclusive`, `never_fetched_check`). **Nothing propagated
  the sub-part level into the status.** That is the root of P0-1.
- **Check dependencies:** STR ← RND-1 (root cause once), ACC-7 ← ACC-4, IDX-7 ← INT-2,
  IDX-1/PRF ← shared attempt history, ANS-1/ANS-4 ← site checks.

## B. The 46 checks

| ID | What it actually does | Confidence / severity | Weakness | Action |
|---|---|---|---|---|
| INT-1 | Fetch classification | Verified iff Verified-only classifications give the same state | Body signatures unvalidated (LG-25) | keep |
| INT-2 | Stop reason, sessions, sitemap coverage | Verified | sound | keep |
| INT-3 | Render sample disclosure | Verified | sound | keep |
| INT-4 | UA, robots-first, disallowed, probes, gaps per session | Verified | sound | keep |
| ACC-1 | 3 robots.txt samples | S1/S3/Info Verified | 429 on every sample read as PASS ("4xx = no restrictions") while Maya itself stops on 429 | P0-1 |
| ACC-2 | robots decision per bot × sampled URL | by role, Verified | title states bot behaviour; provisional roles (Amazonbot, Applebot) drive S1 | P0-8 provenance |
| ACC-3 | meta + X-Robots-Tag, data-nosnippet share | spec, Verified | only readable 2xx HTML; PDFs' X-Robots-Tag missed | P2 |
| ACC-4 | browser vs bot UA with retries | by role, Verified | a finding could rest on one unretried attempt when the probe cap cut retries (`confirmed` ignored); `different_content` needed body **and** title to differ; no location / final URL / text hash; one baseline | P0-5, P1 |
| ACC-5 | logs + IP ranges | observations; S4 never fetched | PASS when the only judged part was not assessed (no search-bot ranges) | P0-1 |
| ACC-6 | vendor line | Info Inferred | sound | keep |
| ACC-7 | crawl-delay | S4 | sound | keep |
| ACC-8 | llms.txt | Info | sound | keep |
| IDX-1 | persistent vs intermittent failure | spec; timeouts Inferred | failures never refetched (cap) became an observation; check could PASS | P0-1 |
| IDX-2 | TLS, HTTP→HTTPS, www variant | Verified | sound | keep |
| IDX-3 | chains, loops | Verified | sound | keep |
| IDX-4 | canonicals | Verified / Estimated | unfetched targets hidden in evidence while summary said "All N … consistent" | P0-1 |
| IDX-5 | sitemap health | Verified / Estimated-if-partial | "46 of 415 checked" PASS not presented as a sample; "0 checked" passes | P0-1 |
| IDX-6 | broken links | S3 | sound | keep |
| IDX-7 | orphans (complete crawl), depth | S4/Info | sound (live-runs README wrongly says it needs Search Console) | doc fix |
| IDX-8 | duplicates | Verified / Estimated | sound | keep |
| IDX-9 | GSC | Verified | LG-12 handled | keep |
| IDX-10 | Bing, IndexNow | — | PASS when connected though index status is structurally unassessable | P0-1 |
| RND-1 | rendered ratio, T0 elsewhere | Verified / Estimated | word counts only, no content delta; "visible" includes CSS-hidden text; PASS could rest wholly on absence of heuristic signals | P0-2, P1 |
| RND-2 | declared facts, candidates | Verified / Estimated | sound | keep |
| RND-3 | word delta after clicks | Verified | no no-click control; English "load more" fallback had **no language guard** | P0-4, P1 |
| RND-4 | iframe, canvas, banner images | S4 | sound | keep |
| RND-5 | walls, English guard | spec | **PASSED on 1 of 48 pages** (Enpara) | P0-1 |
| RND-6 | payload, offset | S4 | regex offset can match inside script | minor |
| RND-7 | main share | S4 Estimated | sound | keep |
| STR-1 | titles | S4 | sound | keep |
| STR-2 | headings | S4 | sound | keep |
| STR-3 | SD parse / Org / required / expected | spec | no `@id` graph checks, no `url` vs canonical | P2 |
| STR-4 | markup vs visible | S2/S3 by field | multi-price "conflict" labelled Verified; no markup-vs-markup comparison; **Moodist PASS "values match on 46 pages" with 40 of 60 date comparisons not assessed** | P0-7, P1 STR-11, P0-1 |
| STR-5 | name variants, sameAs | S4 Estimated | sameAs never checked by default yet PASS (Midas 5/5) | P0-1, P2 |
| STR-6 | date signals | S4 | "Date signals agree" vacuous when few pages carry 2+ signals (Enpara 11/36) | P0-2, P2 |
| STR-7 | alt | S4/Info | sound | keep |
| STR-8 | div grids | Estimated | sound | keep |
| STR-9 | lang, hreflang | S4/Info | PASS with lang check not assessed on 9 pages (Midas) | P0-1 |
| STR-10 | previews | Info/S4 | og:image unchecked by default, PASS | P0-1 |
| PRF-1 | median of 3+ | S4 | sound | keep |
| PRF-2 | reliability | S4 | sound (already not_assessed without rounds) | keep |
| PRF-3 | CrUX/PSI metrics | Info | sound | keep |
| ANS-1 | cited URL health | copies site severity | zero on-site records → PASS even on a paged export; canonical from HTML only (IDX-4 also reads Link header); an unfetched cited URL reported as a "failing" finding; Moodist: 16/16 "failing", all trailing-slash canonicals / redirects at Info | P0-6, P1 |
| ANS-2 | claims vs cited page | Estimated, Self-evident harm | "page shows no price" and "page shows a different price" merged; rendered view not consulted; not assessed on real data (LG-18) | P1 |
| ANS-3 | cut | — | — | keep |
| ANS-4 | per-engine coverage | Info | sound | keep |
| ANS-5 | domain classes | observations | status always `"pass"` | P0-1 (`observed`) |

## C. Confidence / severity audit

**Inconsistencies found:**

1. **PASS with partial evidence** (systemic). `CheckResult` had no coverage and a PASS carried no
   basis. Confirmed on live data (Moodist STR-4; Enpara RND-5, STR-6, STR-9; Midas STR-5, STR-9)
   and in code (ACC-5, IDX-1, IDX-4, IDX-5, IDX-10, STR-10, RND-1/3 on heuristics only).
2. **STR-4 multi-price conflict marked Verified.** The non-match is Verified; that the visible
   prices refer to the same offer is Inferred.
3. **RND-3 causation marked Verified** without a no-click control (Phase 2).
4. **ACC-4 could raise S1 from one unconfirmed observation** when the probe cap cut retries.
5. **ANS-1 took the lower severity because a comparison was not made** (canonical target not
   compared → Info). That discounts severity for uncertainty; resolving the comparison is cheap
   (Phase 2).
6. **`ai_skills/rules.py` SEVERITY_LADDER contradicted spec §2.1.** It called "content exists but
   the engine cannot see it" S3, which is S2 (RND-1), and reframed S2 around canonicals. Every
   generated client document was taught the wrong scale.
7. **Rationale is an untyped string** mixing strengths; ANS-4 passed the enum object; there is no
   field for the fix's own rationale (§2.3 wants Self-evident-harm fixes labelled Hypothesis).

**Already correct:** severity independent of confidence and key-page status; Hypothesis cap;
INT-1 gate-confidence rule; IDX-1 timeouts Inferred; ACC-6 Inferred; Estimated labels on
RND-2/STR-5/STR-8/IDX-8; ANS-4 truncation guard; null vs zero in ANS-4/5; ANS panel isolation.

## D. OpenSEO delta

**Already borrowed:** fetch classes (`audit-fetch-class.ts`), crawl throttle / backoff
(`crawl-throttle.ts`), SQLite frontier (`AuditScratchpad.ts`, adapted), null-vs-zero and
per-platform caps (`shareOfVoice.ts`, `citedSources.ts`), four agent skills, the UA-differential
method (their "Two Surfaces" post).

**Newly read:**

| Component | Classification |
|---|---|
| `badseo/` — a public, deliberately broken site used as an end-to-end fixture, with a harness enforcing every issue type is exercised | useful to the technical audit: a Maya "bad-AEO" site gives Level-3 regression without client data (P2) |
| `.agents/skills/evaluate-skill` — isolated sessions, skill hashes, locked tool list, holdout site | broader product: the method to close LG-32 (P3) |
| `seo-audit` skill (rewritten 2026-09-19): "a failed lookup is unknown, not absent"; "one snapshot is not a baseline"; record query/country/date | wording for `ai_skills` evidence rules |
| `brandLookupShaping.aggregatesAreDomainLevel` — discloses a metric computed at a broader scope than asked | useful: same pattern as sample-vs-sitewide disclosure |
| `safeUrl.ts` — rejects `user:pass@host` and non-http | useful, small: `ans_data.read_url` accepts userinfo (P2) |
| `promptExplorer.ts`, `brandLookup.ts`, share of voice | broader GEO; paid (DataForSEO) |
| `sam/`, `lib/scrape.ts` | not worth porting |
| MCP server | not worth porting now (CLI + evidence JSON workflow) |
| keywords, rank tracking, backlinks, GA4, local SEO | classic SEO / paid; outside the core audit |
| `audit-issues.ts` (27 types; DECISIONS §86 says 30), `page-analyzer.ts` (`hasStructuredData` boolean only) | nothing new |

## E. Candidates (engineering prioritisation, not a user-facing score)

| Priority | Item | Evidence | Difficulty | Paid |
|---|---|---|---|---|
| P0 | Coverage on every check; no PASS with unassessed parts; `partial` / `observed` | Verified | Medium | No |
| P0 | Severity ladder in `ai_skills` matches §2.1, test-bound | — | Low | No |
| P0 | RND-3 language guard for the English fallback | — | Low | No |
| P0 | ACC-4 unconfirmed pair is not a finding at full confidence | Verified | Low | No |
| P0 | ANS-1: paged/empty data not "zero"; canonical from HTML + header; unfetched URL is coverage, not a failure | Verified | Low | No |
| P0 | STR-4 multi-price conflicts Inferred, assumption named | — | Low | No |
| P0 | Registry per-field provenance; re-verify Anthropic rows without silent upgrade | Documented | Low | No |
| P1 | ACC-4 differential v2 (location, final URL, content type, bytes, text hash/length, delta, per-bot re-baseline, 3xx/4xx outcome) | Verified | Medium | No |
| P1 | RND-1 content delta (quoted blocks, XHR/fetch attribution, iframe/noscript) | Verified | Medium | No |
| P1 | RND-3 no-click control snapshot | Verified | Low | No |
| P1 | ANS-1 v2: resolve redirects/canonicals, consolidated vs failing, list checks applied to "healthy" | Verified | Low–Med | No |
| P1 | ANS-2 v2: contradicted vs absent, rendered view, comparison mode recorded | Estimated + Verified | Low | No |
| P1 | STR-11 (new): contradictions inside the markup | Verified | Low–Med | No |
| P2 | STR-5 entity view; STR-3 graph integrity; STR-6 additions; ACC-3 on PDFs; bad-AEO fixture site | Verified / Estimated | Low–Med | No |
| P3 | `--compare-with prev.json`; skill-evaluation harness | — | Medium | No |

Not for the core audit: MCP, Prompt Explorer, share of voice, DataForSEO, keyword/backlink/SERP
data, numeric confidence.

## F. TypeSafe AI

TypeSafe AI is not an SEO/AEO tool. Jev returns typed decisions with a confidence value it claims is
calibrated; the announcement publishes no calibration metrics
([announcement](https://typesafe.ai/blog/introducing-system-one-models-and-jev),
[docs](https://docs.typesafe.ai/introduction)). Maya borrows the philosophy only: a confidence
label should predict correctness and decide automate-vs-escalate. **Numeric confidence is not
justified now.** Maya's escalation channel already exists (`ReviewItem`, "needs review"), and a
second "decision confidence" axis would duplicate it. The prerequisite is a labelled corpus — the
16 live-run defects plus hand-checked live findings — measuring precision per Estimated heuristic
(RND-1 T0 signals, STR-5 variants, STR-8 grids, LG-20…24), reported categorically.

## G. Phases

1. **Evidence integrity** (the P0 rows). No new checks.
2. **The six approved P1 items.**
3. **Entity / freshness / structure** (P2).
4. **Optional:** calibration harness, fixture site, `--compare-with`.

The live re-run of `withmaya.ai` stays blocked on LG-02 (the bot page on a Maya domain).
