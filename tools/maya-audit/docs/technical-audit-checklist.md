# Maya Technical Audit Checklist — Spec

**Status:** Draft for review · **Date:** 2026-09-13 · **Scope:** Content of the checklist only (what to check, why, how to verify). No implementation.

This spec defines the checks for Maya's technical audit. Maya is an AI-visibility / GEO dashboard, so every check is judged by one question: **does this affect whether an AI answer engine can reach, read, understand, and cite the site?** Traditional SEO checks are kept only when they pass that test, and the reason is written down.

---

## Contents

0. [Research basis: what OpenSEO actually does](#0-research-basis-what-openseo-actually-does)
1. [Principles: evidence first](#1-principles-evidence-first)
2. [Finding model: severity, confidence, and the rest kept separate](#2-finding-model-severity-confidence-and-the-rest-kept-separate)
3. [Cost tiers: which checks need what](#3-cost-tiers-which-checks-need-what)
4. [AI user-agent registry](#4-ai-user-agent-registry)
5. [The checklist](#5-the-checklist)
   - [INT: Audit integrity (can this report be trusted?)](#int--audit-integrity)
   - [ACC: AI-engine access](#acc--ai-engine-access)
   - [IDX: Crawlability & indexability](#idx--crawlability--indexability)
   - [RND: Rendering & content extractability](#rnd--rendering--content-extractability)
   - [STR: Content structure & semantics](#str--content-structure--semantics)
   - [PRF: Performance & fetch reliability](#prf--performance--fetch-reliability)
   - [ANS: Answer-engine observations (kept separate from site facts)](#ans--answer-engine-observations)
6. [Check index (summary table)](#6-check-index)
7. [What OpenSEO covers that is NOT relevant to AI-answer visibility](#7-what-openseo-covers-that-is-not-relevant-to-ai-answer-visibility)
8. [Review decisions](#8-review-decisions)
9. [Sources](#9-sources)

---

## 0. Research basis: what OpenSEO actually does

I read OpenSEO's README, marketing pages, docs, strategy library, blog, roadmap, and the source files that define its audit and AI-search behavior. Nothing below is guessed. Where a claim comes from source code, the file is named.

### 0.1 Site Audit

- **Pipeline:** robots.txt + sitemap discovery → plain HTTP crawl (no JavaScript rendering; the roadmap lists JS rendering as "Not planned") → per-page checks + cross-page checks → issues grouped by severity. The crawler identifies as `OpenSEO-Audit/1.0` and only queues links that robots.txt allows (checked with `robots-parser` without passing a UA, so the `*` group applies). (`src/server/lib/audit/discovery.ts`, `specs/0009-site-audit-crawl-architecture.md`)
- **Data pulled from each page** (`src/server/lib/audit/page-analyzer.ts`): status code, redirect target, response time, title, meta description, canonical (HTML + `Link` header), robots meta + `X-Robots-Tag`, OG title/description/image, H1 texts, heading order, visible word count, images with alt attributes, links (anchor text, internal/external, nofollow), whether a JSON-LD block exists, hreflang values. Some of these fields are collected but never raised as issues: OG tags, structured data, hreflang.
- **Issue registry: exactly 27 types** (`src/shared/audit-issues.ts`). Each carries `severity`, `explanation`, and `howToFix`:

| Severity | Issue types |
|---|---|
| **critical** (4) | `blocked-page` (WAF/bot challenge/403), `server-error` (5xx), `broken-internal-link`, `missing-title` |
| **warning** (14) | `rate-limited-page` (429), `crawl-rate-limited` (crawl stopped early), `broken-page` (4xx), `duplicate-title`, `duplicate-meta-description`, `duplicate-content` (byte-identical visible text hash), `missing-meta-description`, `missing-h1`, `multiple-h1`, `redirect-chain`, `redirect-loop`, `canonical-conflict` (HTML vs header), `thin-content` (<150 words), `images-missing-alt`, `orphan-page`, `no-outgoing-links` |
| **info** (9) | `title-too-long` (>60), `title-too-short` (<10), `meta-description-too-long` (>160), `meta-description-too-short` (<70), `heading-order-skip`, `slow-response` (>1500 ms), `noindex-page`, `canonicalized-page`, `deep-page` (≥5 clicks) |

- **Fetch classification** (`src/shared/audit-fetch-class.ts`): every page gets `ok | blocked | rate_limited | error`. If a page is blocked or rate-limited, no content checks run on it. The page is reported as "could not audit," not as broken. The strategy library says to check this before reading anything else: *"This is the check that invalidates every other check when it fails."*
- **Guards against false positives:** orphan findings only fire when the crawl actually finished. Broken-link findings only fire for targets that were really fetched. Pages that are noindexed or canonicalized elsewhere are left out of duplicate groups. (`docs/site-audit-pm-research.md`, `multipage-checks.ts`)
- **Optional Lighthouse pass** (`src/server/lib/audit/lighthouse.ts`): runs through **DataForSEO's paid Lighthouse API**, mobile or desktop. It samples the homepage plus one page per URL template, **capped at 10 pages**. It stores four 0–100 category scores (performance, accessibility, best practices, SEO) and LCP, CLS, INP, TTFB.
- **Stated philosophy:** "Simple reports that expose page-level signals … instead of relying only on a generic score." Their MCP prompt template ends with *"Do not give me a score."* Their audit skill says: *"Verify every finding … against the live page HTML … Report nothing you have not seen evidence for"* and *"Separate what the tools reported from what you verified yourself."* Their UI still shows Lighthouse's 0–100 category scores, though.

### 0.2 AI Visibility (framed separately from the audit)

- **Separate product area.** In the nav, "AI visibility" (Brand Lookup, Prompt Explorer) sits in its own group, apart from "Domain research" where Site Audit lives. The marketing copy says AI visibility *"sits beside classic SEO research instead of replacing it"* and *"focuses on concrete sources and mentions, not vague AI hype."*
- **Brand Lookup** (`src/server/features/ai-search/services/brandLookup.ts`): uses DataForSEO's **LLM Mentions API** (paid, gated to paid plans) for exactly two platforms, **ChatGPT (US/English only) and Google AI Overview**. It returns mention counts, "AI search volume," cited pages, top queries, a monthly trend, and share of voice against competitors. Results are cached for 24h; the upstream data refreshes monthly.
- **Prompt Explorer** (`promptExplorer.ts`): sends one prompt to up to 4 models through DataForSEO (gpt-5, claude-sonnet-4-5, gemini-2.5-pro, sonar-reasoning-pro), optionally with web search. It shows the answers side by side with citations and whether a brand was mentioned. Results are cached for 7 days.
- **Framing details worth copying:**
  - A failure on one platform never hides the others.
  - `null` ("no data") is kept distinct from `0` ("known zero"), including in share-of-voice math (`shareOfVoice.ts`).
  - ChatGPT numbers are left out of totals when the user's locale doesn't match ChatGPT's US-only data.
- **What is missing:** the Site Audit has **no AI-crawler checks**. None of the 27 issue types look at GPTBot, OAI-SearchBot, ClaudeBot, PerplexityBot, etc. The only link between the two areas is a manual workflow in their blog post "Two Surfaces, Two Timelines". The author found their own site returning **429 to GPTBot while returning 200 to a browser from the same IP**, at the LiteSpeed edge, with nothing in robots.txt. The fix: *"Curl your site with each AI crawler's user agent and with a browser user agent, from the same IP, interleaved. Compare headers as well as status codes."* Their roadmap lists "Agent readiness checks in site audits" as *Soon*. Their internal PM doc ranks an "AI-crawler accessibility audit" as P1 and says *"Skip llms.txt as a headline; no major LLM vendor consumes it."*

### 0.3 What Maya takes from this

1. **Take:** fetch classification before anything else; findings that carry evidence and a fix; grouping by issue type and template, not by URL; gating checks on crawl completeness; null ≠ 0; separating per-platform AI data.
2. **Add (OpenSEO's gap, Maya's core):** a first-class **AI-engine access** category, **raw-HTML vs rendered-content parity**, and joining site facts to answer-engine citation data.
3. **Leave behind:** SERP-presentation checks and link-equity rationales (see §7), and 0–100 composite scores, Lighthouse's included.

---

## 1. Principles: evidence first

1. **Every finding points to a stored observation.** An HTTP status, a header value, a quoted HTML tag or robots.txt line (with line number), a measured millisecond value, a word count. Record the exact request too: URL, user agent, timestamp, egress region. A user should be able to reproduce any finding with one `curl` command, and the finding should show that command.
2. **No composite 0–100 scores.** Not per page, not per site, not per category. Counts are fine because a count is a fact ("41 of 318 pages return 404"). Ratios are fine when numerator and denominator are both shown. Third-party tools that only produce a score (Lighthouse categories) show their underlying metric values instead (§7).
3. **A pass needs evidence too.** "OAI-SearchBot allowed" must show the robots.txt group that matched (or "no matching group; `*` group permits `/`") and the fetch result. A check that could not run is **Not assessed**. It is never shown as a pass.
4. **Label estimates.** Heuristics, lab measurements, sampled data, LLM-assisted comparisons, and third-party modeled numbers are marked **Estimated**. They are shown with their method and, where it exists, sample size or range. They never get the same visual weight as verified facts (§2.2).
5. **Keep "is it true" apart from "does it matter" and "why we think it matters."** Three separate labels (§2): **Confidence** in the observation, **Severity** of the consequence, and **Rationale strength** of the claim that it affects AI answers.
6. **Report root causes, not rows.** Group findings by check and by URL template before counting. "26 pages missing H1" from one template is one task.
7. **Intent-aware.** Some blocks are deliberate. Two separate mechanisms record intent, and findings matching either drop to Info, with the severity they would otherwise have kept visible:
   - **Declared bot policy** (onboarding, §4): which bot roles are welcome sitewide, e.g., "block training crawlers." Search bots default to allowed.
   - **Intent markings** (§2.5): "this specific condition, on this page or path pattern, is intended," e.g., "`noindex` on `/tag/*` is intended." This is a separate capability, not part of the bot policy.
8. **Name the engine.** Every finding lists which AI surfaces it affects (§4 groups). "Blocked" is meaningless without saying *for whom*.

---

## 2. Finding model: severity, confidence, and the rest kept separate

Each finding carries these fields. They are independent, and none is derived from another.

### 2.1 Severity: how much it matters *if true*

Severity is defined by the effect on AI-answer eligibility, not on Google rankings.

| Level | Definition | Example |
|---|---|---|
| **S1 Blocker** | An answer engine cannot retrieve the page(s), or is told not to use them. | robots.txt returns 503 (compliant bots treat that as "disallow all"); OAI-SearchBot gets a Cloudflare challenge; page is `noindex` (removes it from Google AI Overviews). |
| **S2 High** | The page is retrieved, but content an engine would cite is missing, wrong, or can't be attributed. | Pricing table only exists after JavaScript runs; cited URL now 404s; JSON-LD price contradicts the visible price. |
| **S3 Medium** | Degrades discovery, extraction, or understanding without preventing it. | HTML and HTTP-header canonicals disagree; sitemap lists >10% non-200 URLs. |
| **S4 Low** | Hygiene with a plausible but weakly evidenced effect. | Duplicate titles across different pages; slow TTFB (1.5–5 s). |
| **Info** | A recorded fact, possibly intentional; no action implied. | GPTBot (training) disallowed and the owner declared that policy; `noindex` on `/tag/*` marked intended (§2.5); `llms.txt` absent. |

Two things change *priority order*, never severity (§8, F1: decided). **Severity comes only from what is actually broken.** No severity rule may depend on whether a page is a key page:
- **Scope:** sitewide / template (N pages) / single page.
- **Page importance:** the page is a **confirmed** key page (user-marked, or auto-suggested and then confirmed by the user). In v2, AI engines already citing the page will also count (§8, Q3).

**Priority order in the UI** (§8, F1):
1. Audit-integrity problems (INT).
2. Severity.
3. Importance, in three tiers: **confirmed key pages** → **auto-suggested key pages not yet confirmed** → **all other pages**.
4. Scope, as the tie-break **within** an importance level. A real problem on one confirmed key page sorts above the same severity across 200 other pages.
5. Confidence (Verified, then Inferred, then Estimated).

### 2.2 Confidence: how sure we are the observation is true

| Level | Meaning | Display rule |
|---|---|---|
| **Verified** | Maya observed it directly in this run. Raw evidence is stored and reproducible. | Plain statement: "Returned 403 to UA `OAI-SearchBot/1.0` at 14:02 UTC." |
| **Inferred** | A deterministic conclusion from verified evidence that depends on a **named assumption** we can't observe. | Must state the assumption: "robots.txt disallows `/pricing` for `PerplexityBot` → PerplexityBot will not fetch it *(assumes vendor honors robots.txt, which Perplexity documents)*." |
| **Estimated** | A heuristic, lab measurement, sample, LLM-assisted judgement, or third-party modeled figure. Could be wrong for a given page. | Visually distinct ("≈", "estimate" tag, muted style). Shows method and sample size. Never phrased as a fact. |
| **Not assessed** | The check could not run (blocked, timed out, needs a connection the user hasn't set up, crawl incomplete). | Shown as its own state with the reason. Never counted as a pass or a fail. |

**Rules that keep the axes independent:**
- An *Estimated S1* stays S1. It gets labeled "estimate" plus a "verify" action (e.g., "connect server logs to confirm"). Severity is not discounted for uncertainty.
- A *Verified S4* stays S4. Certainty does not make something important.
- There is **no combined "risk score"** (severity × confidence). The UI may sort by the two fields; it must never multiply them.

### 2.3 Rationale strength: how well-supported the "why it matters for AI" claim is

This labels the *check*, not an individual finding. It keeps the checklist honest about GEO folklore.

| Level | Meaning |
|---|---|
| **Documented** | An AI engine vendor's own documentation states the mechanism (e.g., OpenAI: allow OAI-SearchBot to be eligible for ChatGPT search). |
| **Measured** | Published third-party measurement (e.g., Vercel/MERJ log analysis showing GPTBot/ClaudeBot/PerplexityBot don't execute JavaScript). |
| **Hypothesis** | Practitioner belief with a plausible mechanism but no published measurement. |
| **Self-evident harm** | The observed condition *is* the harm to how the brand appears in AI answers, so no claim about how engines work is needed to say it matters (e.g., an AI answer states a price the brand doesn't charge). **Only the proposed fix is unproven.** The how-to-fix text always carries its own **Hypothesis** label. |

**Policy:**
- **Cap.** Hypothesis-backed checks default to **S4 Low or Info**, never higher, unless the owner opts in. This is the one place where rationale strength constrains the *default* severity, and it's stated openly here rather than hidden.
- **Mixed rationale** (§8, F2). When a check's rationale is part Documented/Measured and part Hypothesis, the cap applies only to severities that rest on the Hypothesis part.
- **Self-evident harm.** The cap does not apply to severity, because severity rests on the harm, which is observed rather than hypothesized. The fix is labeled Hypothesis instead. Confidence stays a separate axis: a self-evident harm observed only through an estimate (e.g., LLM-extracted claims) is still **Estimated**.
- **Qualifying test** (so this level can't become a way around the cap). A check qualifies only if the harm can be read straight from the evidence, with no statement of the form "engines use X to decide Y." If explaining why it matters needs any mechanism claim, the check is Documented, Measured, or Hypothesis instead.
  - *Passes:* ANS-2. The answer's wrong price is quoted in the evidence.
  - *Fails:* RND-5 walls. Why they matter depends on "these crawlers can't click through," so they are Measured.
  - *Fails:* STR-1. Why it matters depends on "citation cards use the title," so it is Hypothesis.

### 2.4 Other fields on every finding

- **Check ID** and **engine applicability** (§4 groups)
- **Evidence** (raw values plus the reproduce command) and the **expected** value/rule
- **Scope** (sitewide/template/page, affected URL count, sample URLs)
- **How to fix** (specific to the issue type, as OpenSEO does)
- **Cost tier** (§3) and data source
- **Observed at** timestamp; findings from different runs are never merged silently
- **Intent status:** none / matches declared bot policy / matches an intent marking (with the marking's ID and the severity the finding would otherwise have)

### 2.5 Intent markings (page / path level)

**Status:** design approved in principle (§8, F1). Specification only; nothing is built.

A separate capability from the declared bot policy. The declared bot policy answers "which kinds of bots are welcome on this site." An intent marking answers **"this specific condition, on this page or these pages, is deliberate."**

**What a marking contains:**

| Field | Meaning |
|---|---|
| **Check ID** | The one check it applies to (e.g., ACC-3). A marking never covers "everything on a path": a `noindex` marked intended does not hide a 5xx on the same pages. |
| **Condition** | The exact condition as observed when marked, e.g., `noindex` from `<meta name="robots">`. If the condition changes (e.g., `noindex` becomes `nosnippet`, or moves from meta tag to header), the marking no longer matches and the finding comes back. |
| **Scope** | One exact URL, **or** a path pattern using robots.txt matching (`*` wildcard, `$` end anchor), on the same origin. |
| **Bot token** (optional, ACC checks only) | Limits the marking to one user agent, e.g., "`Perplexity-User` challenged on `/app/*` is intended." Roles as a whole stay in the declared bot policy. |
| **Who / when / note** | The user who marked it, the timestamp, and an optional free-text reason. Stored as evidence. |

**Effect on findings:**
- A matching finding's severity becomes **Info**. The finding stays listed, and shows the severity it would otherwise have ("S1, marked intended by <user> on <date>, pattern `/tag/*`"). Nothing is deleted or hidden.
- **Confidence is unchanged.** A marking records the owner's intent; it doesn't change what was observed.
- **Without a marking, a finding keeps the severity its check specifies.** That severity never depends on key-page status (§2.1).

**Guardrails:**
1. **Patterns never silently cover key pages, confirmed or not.**
   - When a pattern marking is created, Maya lists every confirmed key page and every **auto-suggested key page not yet confirmed** that the pattern covers.
   - *Confirmed key pages* are left out of the marking unless the user names that exact URL in a marking of its own.
   - *Auto-suggested, unconfirmed pages:* the user is asked one question per page: **Confirm as key page** (left out of the marking) / **Not a key page** (the marking applies) / **Decide later** (left out until answered).
   - Default is "left out." The costs are lopsided: wrongly keeping a finding visible costs one more click, while wrongly hiding an accident on a pricing page costs citations.
2. **Coverage is re-counted on every run.** New URLs matching a pattern are covered automatically; that's the point for `/tag/*`. Each marking shows "covered 200 pages last run → 212 this run." If coverage grows sharply (proposed: more than 50%) or the pattern starts matching a newly suggested key page, the report calls it out.
3. **Only choices can be marked, not defects.** A check is markable only if its condition can be a deliberate owner decision:
   - **Markable:** ACC-2 (path disallow for a specific search bot or live fetcher; training bots stay in the declared policy), ACC-3 (`noindex`, `nosnippet`, `max-snippet`, `data-nosnippet`, `noarchive`, `nocache`), ACC-4 (block, challenge, or rate limit for a specific user agent on a path; ownership-verified sites only, like ACC-4 itself), ACC-7 (crawl-delay), IDX-4 (page canonicalized to another URL), IDX-7 (orphan pages such as campaign landing pages), RND-5 (login, age, or paywall gates).
   - **Not markable:** INT-\*, ACC-1, ACC-5, ACC-8, IDX-1/2/3/5/6/8, RND-1/2/3/4/6/7, STR-\*, PRF-\*, ANS-\*. Nobody intends a 5xx, a redirect loop, content missing from raw HTML, or a wrong fact in an AI answer.
4. **No automatic markings.** Maya may *suggest* a marking when signals point to intent (e.g., `noindex` + left out of the sitemap + `/tag/` in the path). That's an **Estimated** hint shown next to the finding. Only a user action creates a marking (§2.2: estimates never change severity).
5. **Revocable, and visible in one place.** All markings are listed in a settings view with coverage counts. Removing a marking brings its findings back at their original severity on the next run. No automatic expiry.
6. **Non-owned sites.** Markings are allowed, since they record the user's own triage decision. They're labeled "marked by <user>; site ownership not verified."

---

## 3. Cost tiers: which checks need what

Every check carries one tier. Anything above T1 is a visible product tradeoff, not a hidden dependency.

| Tier | Needs | Vendor cost | Notes |
|---|---|---|---|
| **T0 Crawl** | Plain HTTP fetches (robots.txt, sitemap, pages, HEAD requests). | None | The default audit must be fully useful at T0. |
| **T1 Self-hosted compute** | Headless Chromium for rendering; Lighthouse CLI. | None (infra cost only) | Slower and heavier; sample pages rather than rendering everything. |
| **T2 Free API, user connection** | Google Search Console (URL Inspection API), PageSpeed Insights / CrUX API, Bing Webmaster Tools. | None, but quota-limited and needs the site owner's OAuth or API key | Only works for sites the user owns. |
| **T3 Customer data** | Server / CDN access logs (Cloudflare, Fastly, Vercel, nginx). | None | The only source of **Verified** data on what *real* AI bots receive. |
| **T4 Paid third-party API** | e.g., DataForSEO LLM Mentions / LLM Responses / SERP / Lighthouse; any metered LLM calls. | **Yes, metered** | OpenSEO's Lighthouse and all of its AI Visibility data live here. Maya's own prompt tracking, if it exists, has the same cost profile. |

---

## 4. AI user-agent registry

The access checks (ACC) run against this registry. **It must be stored as versioned data with a "last verified" date per row,** because vendors add and rename bots often. Tokens marked † were checked on 2026-09-13: OpenAI, Perplexity, and Google against their own docs; Anthropic through press coverage of its doc update, not the doc itself — **since re-checked against Anthropic's own support article on 2026-09-22** (see §9). The rest need checking before implementation.

| Engine group | Token | Purpose | Honors robots.txt? | Published IPs? |
|---|---|---|---|---|
| **OpenAI search** | `OAI-SearchBot` † | Surfaces sites in ChatGPT search. OpenAI: to be eligible, allow OAI-SearchBot. | Yes | `openai.com/searchbot.json` |
| **OpenAI live fetch** | `ChatGPT-User` † | User-initiated fetches in ChatGPT / Custom GPTs. | "robots.txt rules may not apply" | `openai.com/chatgpt-user.json` |
| **OpenAI training** | `GPTBot` † | Content that may be used for foundation model training. | Yes | `openai.com/gptbot.json` |
| **Anthropic search** | `Claude-SearchBot` † | Indexes content to improve search result quality. | Yes, incl. Crawl-delay (Anthropic docs) | `claude.com/crawling/bots.json` (shared by all three) |
| **Anthropic live fetch** | `Claude-User` † | Retrieves content when a user directs Claude to a website. | Yes, incl. Crawl-delay (Anthropic docs) | `claude.com/crawling/bots.json` (shared) |
| **Anthropic training** | `ClaudeBot` † | Collects web content for AI model training and development. | Yes, incl. Crawl-delay (Anthropic docs) | `claude.com/crawling/bots.json` (shared) |
| **Perplexity search** | `PerplexityBot` † | Surfaces and links sites in Perplexity search; "not used to crawl content for AI foundation models." | Yes | `perplexity.com/perplexitybot.json` |
| **Perplexity live fetch** | `Perplexity-User` † | User-initiated fetches during answers. | "generally ignores robots.txt" | `perplexity.com/perplexity-user.json` |
| **Google AI Overviews / AI Mode** | `Googlebot` † | AI Overviews / AI Mode use the regular Search index. No additional requirements beyond being indexed and eligible for a snippet. | Yes | Google-published |
| **Gemini apps / Vertex grounding + training** | `Google-Extended` † (robots token only, not a separate crawler) | Controls use for Gemini training and grounding. "Does not impact a site's inclusion in Google Search." Does not affect AI Overviews. | Yes (token) | n/a |
| **Microsoft Copilot** | `Bingbot` | Bing index grounds Copilot; OpenAI says ChatGPT search sends rewritten queries to third-party search providers. | Yes | Bing-published |
| **Apple** | `Applebot` / `Applebot-Extended` | Siri/Spotlight search / training opt-out token. | Yes | not checked |
| **Meta** | `meta-externalagent` | AI training / product features. | not checked | not checked |
| **Common Crawl** | `CCBot` | Open corpus widely used in model training. | Yes | not checked |
| **Amazon** | `Amazonbot` | Alexa / AI features. | not checked | not checked |
| **DuckDuckGo** | `DuckAssistBot` | DuckAssist answers. | not checked | not checked |
| **Mistral** | `MistralAI-User` | Le Chat user-initiated fetches. | not checked | not checked |

Each token belongs to one of three **roles**, which drive default severity:
- **Search/index bots** (OAI-SearchBot, Claude-SearchBot, PerplexityBot, Googlebot, Bingbot): blocking them removes you from live answers. **Default S1.**
- **Live fetchers** (ChatGPT-User, Claude-User, Perplexity-User): blocking them at the network level breaks citations users request directly. **Default S2.** Robots.txt may not apply to them, so WAF behavior is what matters.
- **Training bots** (GPTBot, ClaudeBot, Google-Extended, CCBot, Applebot-Extended): effect is long-horizon and often deliberate. OpenSEO's blog argues training inclusion is "a multi-year brand problem" while retrieval is "a finite list you can work this month." **Default S4**, or Info if it matches the declared policy.

**Launch gate (§8, Q6 / F6).** Nothing below ships unverified. Each item must be checked against the vendor's own documentation, with the date recorded, before launch:
- Every cell marked "not checked" above.
- The **role** of: Applebot vs Applebot-Extended (split the mixed row), Amazonbot, meta-externalagent, DuckAssistBot, MistralAI-User. Role sets default severity, so these may move between S1, S2, and S4.
- ~~All three Anthropic rows~~ **Resolved 2026-09-22** against Anthropic's support article (roles, robots.txt, IP ranges). Their full user-agent strings are still unverified: the article gives tokens only.
- The Bing `noarchive` / `nocache` controls behind ACC-3's Bing default.

A named owner for the registry is required before launch (to be confirmed).

---

## 5. The checklist

Each check lists: **Measures** · **Why it matters for AI answers** · **How to verify** · a tag line with Confidence, default Severity, Cost tier, Rationale strength, and the OpenSEO equivalent.

---

### INT — Audit integrity

*These run first and are shown above all other findings. If they fail, the rest of the report describes the edge (the CDN/WAF), not the site. This lesson comes straight from OpenSEO's `fetchClass`.*

#### INT-1 · Fetch classification per page
- **Measures:** Whether each fetch returned the real page (`ok`), a bot challenge or denial (`blocked`), a 429 (`rate_limited`), or a network/timeout failure (`error`).
- **Why (AI):** A report built on challenge pages will show false "missing title / thin content" findings. Blocking also hints that AI bots may hit the same wall. That hint gets tested properly in ACC-4.
- **Verify:** Classify from status (401/403/429/503), explicit headers (`cf-mitigated: challenge`), and body signatures (Cloudflare "Just a moment…", `challenge-platform` scripts, Vercel Security Checkpoint, DataDome/Akamai/PerimeterX markers). Header-based classifications are Verified. Body-signature-only ones are Estimated.
- **Rule:** If ≥20% of fetched URLs, or the start URL, are `blocked`/`rate_limited`, mark the audit **degraded**: suppress content checks on those pages and show the fix (allowlist Maya's UA) before anything else. (The threshold is OpenSEO's PM-doc definition; treat it as tunable policy.)
- `Confidence: Verified (header/status) / Estimated (body signature) · Severity: n/a (integrity gate) · Cost: T0 · Rationale: n/a · OpenSEO: blocked-page, rate-limited-page`

#### INT-2 · Crawl completeness
- **Measures:** Whether the crawl ran out of URLs before hitting the page cap, time limit, or rate limit.
- **Why (AI):** Several checks (orphans, "no internal links point here," sitewide counts) are only true on a complete crawl. On a partial crawl nearly everything looks orphaned.
- **Verify:** Record the stop reason (`exhausted | page_cap | time_limit | rate_limit | error`), URLs discovered vs fetched, and sitemap URLs vs fetched. Checks that need a complete crawl become **Not assessed** otherwise.
- `Confidence: Verified · Severity: n/a · Cost: T0 · OpenSEO: crawl-rate-limited + orphan gating`

#### INT-3 · Rendering mode disclosure
- **Measures:** Whether the audit used raw HTML only (T0) or also rendered pages (T1), and on which sample.
- **Why (AI):** Most AI crawlers read raw HTML (see RND-1). Google renders. Findings must say which view they describe.
- **Verify:** Stamp every content finding with `view: raw | rendered`.
- `Confidence: Verified · Severity: n/a · Cost: T0/T1`

#### INT-4 · Maya crawler identity and robots.txt compliance
- **Measures:** That Maya's own crawl used its documented UA and followed robots.txt for that UA. Any URLs skipped because of robots.txt are listed.
- **Why:** Without this, "page not audited" gets confused with "page broken." It also keeps Maya's own behavior defensible (see §8, Q1, on sending AI-bot user agents in probes).
- **Politeness, per host** *(amended 2026-10-15, decision 219 part 2, owner; amends decision 82)*: the gap between requests is measured between one request to a host and the next request to that same host, since requests to other sites run in parallel (at most 4 sites at a time, one request at a time each). The audited site's required gap is the floor in use: the configured delay or its Crawl-delay, or, when adaptive pacing narrowed it on a fast, error-free site (×0.75 after 20 clean answers in a row, never below 0.5 s nor the Crawl-delay), the narrowest gap it used. Another site's is the configured delay or its own Crawl-delay. Evidence: `politeness.by_host`, `narrowed` (`from_s`, `to_s`, `after_requests`), `floor_s`.
- `Confidence: Verified · Severity: n/a · Cost: T0`

---

### ACC — AI-engine access

*The category OpenSEO's audit lacks and Maya's main differentiator. Every finding names the affected token(s) and engine group from §4.*

#### ACC-1 · robots.txt availability
- **Measures:** HTTP result for `/robots.txt` (following up to 5 redirects), content type, size, and whether it parses.
- **Why (AI):** Under RFC 9309, a **4xx** robots.txt means "no restrictions." A **5xx or unreachable** robots.txt means compliant crawlers should assume **complete disallow**. An intermittent 503 on robots.txt can therefore silently remove a site from every robots-compliant AI search bot. An HTML page served at `/robots.txt` parses as empty (allow all), which is usually harmless but worth recording.
- **Verify:** Fetch with Maya's UA. On **ownership-verified sites only**, also fetch with each search-bot UA, tagged `X-Maya-Probe` (same gate as ACC-4; differences are handled there). On non-owned sites, use Maya's UA only. Record status, redirect hops, `Content-Type`, and byte size. Parsers may ignore anything past 500 KiB, per RFC 9309 and Google's behavior. Fetch 3 times a few minutes apart to catch intermittent 5xx.
- **Severity:** 5xx/timeout **S1** (sitewide, all compliant bots). >500 KiB **S3**. HTML-at-robots.txt **Info**.
- `Confidence: Verified (the response) / Inferred (bot behavior; assumes RFC 9309 compliance) · Cost: T0 · Rationale: Documented (RFC 9309, vendor robots docs) · OpenSEO: none (fetched, not reported)`

#### ACC-2 · robots.txt rules evaluated per AI user agent
- **Measures:** For every registry token × a URL sample (homepage, one URL per template, all key pages, sitemap sample), whether the URL is allowed. Also records **which group matched and which rule line decided it.**
- **Why (AI):** This is the documented gate. OpenAI: to be eligible for ChatGPT search, allow OAI-SearchBot. PerplexityBot and Claude-SearchBot likewise honor robots.txt. Common mistakes:
  - a blanket `User-agent: *` / `Disallow: /` left over from staging;
  - "block all AI" snippets copied from blog posts that include search bots along with training bots;
  - **group-precedence bugs:** under RFC 9309 a crawler obeys *only* its most specific matching group. Adding `User-agent: GPTBot` with a single rule means GPTBot ignores every `*` rule. That can accidentally *unblock* private paths, or leave a search bot blocked when the author thought `*` covered it.
- **Verify:** Parse per RFC 9309: case-insensitive product-token match, most specific group wins, longest path match wins, `Allow` wins ties, `*` and `$` wildcards. Evaluate each (token, URL) pair. Show the matched group and the rule line with its line number.
- **Severity:** by role (§4). Search bot disallowed from any sampled URL → **S1**, or **Info** if marked intended (§2.5). Live fetcher disallowed → **S3** (robots.txt may not apply to them; check ACC-4 for real effect). Training bot → **S4**, or **Info** if it matches the declared policy. Also flag "declared policy says allow, robots.txt says block" (and the reverse) as a **policy mismatch**. Search bots count as "allowed" unless the declared policy says otherwise.
- `Confidence: Verified (what the file says) / Inferred (what the bot will do; assumes documented compliance) · Cost: T0 · Rationale: Documented · OpenSEO: none`

#### ACC-3 · Page-level AI controls (meta robots, X-Robots-Tag, snippet controls)
- **Measures:** Per page, in both the HTML `<meta name="robots">` / bot-specific meta names (e.g., `googlebot`, `bingbot`) and the `X-Robots-Tag` header (including bot-scoped variants like `X-Robots-Tag: googlebot: nosnippet`): `noindex`, `nosnippet`, `max-snippet:N`, `data-nosnippet` coverage of main content, `noarchive`, `nocache`.
- **Why (AI):**
  - **Google** documents that pages must be indexed and eligible to show a snippet to appear as AI Overviews / AI Mode supporting links. It also says `nosnippet`, `data-nosnippet`, `max-snippet`, and `noindex` limit what appears in AI features. There is no lever that removes content from AI features while keeping the normal snippet.
  - **Bing** has documented `noarchive` / `nocache` as controls for use in its chat answers (Bing Webmaster Blog, 2023; not re-verified; **launch-gated**, §4).
  - For OpenAI, Anthropic, and Perplexity, how they treat `noindex` is **not documented** in the pages reviewed.
- **Verify:** Extract from raw HTML and response headers. Measure what fraction of visible main-content text sits inside `data-nosnippet` elements. Flag `max-snippet` values below ~50 characters as effectively suppressing AI use. *(v2 Phase 3)* Non-HTML documents the crawl fetched (PDFs, for example) are checked too: their only control is the `X-Robots-Tag` header.
- **Severity:** `noindex` on a user-marked key page or sitemap-listed page is **S1**; on other pages it is **Info** until a person confirms the page was meant to be searchable. Internal links alone do not raise severity because navigation commonly links to utility pages such as cart, login, and search. `nosnippet` on any page is **S1** for Google AI Overviews. `max-snippet:0` **S1** (Google). `max-snippet` below ~50 characters **S2**. Main content fully in `data-nosnippet` **S2**. Bing `noarchive` **S2** (Copilot; launch-gated). Any of these → **Info** if marked intended (§2.5).
- `Confidence: Verified (directive present) / Inferred (effect on non-Google engines) · Cost: T0 · Rationale: Documented (Google, Bing) / Hypothesis (others) · OpenSEO: noindex-page (info)`

#### ACC-4 · User-agent differential response test
- **Measures:** Whether the server responds differently to AI-bot user agents than to a browser, for the same URL, from the same IP, in interleaved order.
- **Ownership gate (§8, Q1):**
  - Runs **only on ownership-verified sites** (DNS, meta tag, or GSC).
  - Every probe carries `X-Maya-Probe: ua-differential`, and probe volume is capped per audit.
  - On non-owned sites the full check does not run, and ACC-2 (plus ACC-5 if logs exist) is the fallback. They must never present a clean access result, because robots.txt checks can't see WAF or edge blocks. *(Amended 2026-10-14, decision 205.)* Instead a small check runs: at most 3 URLs (homepage, an empty page if any, the first page of the largest template), each fetched **once** with a browser UA and **once** with Googlebot's UA, tagged `X-Maya-Probe: ua-differential`, never retried, and the Googlebot request only where robots.txt allows Googlebot and Maya. Googlebot 5xx where the browser got 2xx → **S2**; Googlebot 403/429/challenge → **S3**; same status but body under half or over twice the browser's → **Info**; all **Estimated**, with the note to confirm in Google Search Console. The report says **"Firewall blocking was only partly assessed … Other AI crawlers were not tested (ownership not verified)."** and the check is at best partial. Where nothing could be compared it still says **"Firewall blocking was not assessed."**
- **Why (AI):** This catches blocks that robots.txt can't show: WAF bot rules, CDN "block AI scrapers" toggles, host-level rate limits, edge rules. OpenSEO's founder found their own site returning **429 to GPTBot** and 200 to a browser. The block was at the LiteSpeed edge ("PHP never ran"), not in robots.txt. *"You cannot be selected from a set you were never admitted to. This is the one part of the stack that is binary, cheap to test, and almost never tested."*
- **Verify:**
  1. Pick a sample: homepage, robots.txt, sitemap, one URL per template, key pages (cap ~10–20 URLs).
  2. For each URL, fetch with a current browser UA, then each search-bot and live-fetcher UA, interleaved, with polite spacing.
  3. Record: status; `Server`, `cf-mitigated`, `cf-ray`, `X-Powered-By`, `Retry-After`, `Content-Type`, `Content-Length`; body hash; visible word count; `<title>`.
  4. Classify each (UA, URL) pair as `same | blocked | challenged | rate_limited | degraded (200 but <50% of browser word count) | redirected | different_content`. *(v2, 2026-09-22)* A 4xx/5xx to the bot while the browser gets 2xx is `blocked` (it cannot retrieve the page, §2.1). A bot-only redirect is `redirected` (review item, Location recorded). "Same" is judged on the visible-text hash, not the body bytes; the same title with estimated text similarity below the IDX-4 threshold is `different_content`. Each attempt records status, Location, content type, bytes, visible-text hash and word count; a non-`same` result carries a word-level text delta.
  5. Retry any non-`same` result at least twice after a cooldown, so a transient rate limit isn't reported as a block. *(v2)* The browser baseline is re-taken before every retry and the retry is judged against it, so a page that changed between loads is not read as cloaking. A difference the probe cap left unretried is reported Estimated, at the same severity.
  6. A missing application header (like `X-Powered-By`) on the bot response is evidence the block happened at the edge. Show it.
- **Critical caveat, which must be displayed:** Maya sends *a request with the AI bot's UA string from Maya's IP*. It does not send *a request from the real bot*. WAFs that verify bots by IP (Cloudflare Verified Bots, reverse DNS) may:
  - **block Maya's spoofed request while allowing the real bot** (false positive), or
  - rarely, the reverse.

  So "Maya's GPTBot-UA request got 403" is **Verified**. "Real GPTBot gets 403" is **Inferred**, and the finding must suggest ACC-5 (logs) to confirm.
- **Baseline guard:** If the *browser* UA is also blocked from Maya's IP, the test is **Not assessed**. We can't separate "blocks AI" from "blocks datacenters."
- **Severity:** by role. Search bot blocked/challenged → **S1**. Live fetcher blocked → **S2**. Degraded content → **S2**. Training bot → **S4/Info**.
- `Confidence: Verified (Maya's observation) / Inferred (real-bot behavior) · Cost: T0 · Rationale: Documented (vendors require access) + practitioner case study · OpenSEO: none in product (manual method in blog)`

#### ACC-5 · Real AI-bot traffic from access logs
- **Measures:** From server/CDN logs: requests per AI bot **verified against the vendor's published IP ranges** (or reverse DNS for Google/Bing), the status-code split per bot, last-seen date, top URLs fetched, share of non-2xx, and requests from spoofed UAs (UA claims a bot, IP doesn't match).
- **Why (AI):** The only **Verified** view of what real bots receive. It confirms or overturns ACC-4, and shows which pages search bots actually visit.
- **Verify:** Ingest logs (Cloudflare Logpush, Fastly, Vercel log drains, nginx/Apache files). Match UA tokens from §4, then check source IPs against the published JSON ranges (OpenAI: `searchbot.json`, `chatgpt-user.json`, `gptbot.json`; Perplexity: `perplexitybot.json`, `perplexity-user.json`), refreshed daily.
- **Findings:**
  - Verified search bot receiving ≥X% non-2xx → **S1/S2**.
  - Search bot not seen in N days despite being allowed → **Info**. Absence of visits is not proof of blocking; it is an observation.
  - Crawled page that search bots are allowed to fetch, but that no verified search bot fetched in the log window → **S4**, grouped by template.
- `Confidence: Verified · Cost: T3 (requires log access) · Rationale: Documented · OpenSEO: none`

#### ACC-6 · Google-Extended and training-token scope clarity
- **Measures:** Whether `Google-Extended`, `Applebot-Extended`, `GPTBot`, `ClaudeBot`, `CCBot` are disallowed, and whether the site *also* blocks the corresponding search bot, perhaps unintentionally.
- **Why (AI):** This check exists to **prevent false alarms and false comfort.** Blocking `Google-Extended` does **not** remove a site from AI Overviews / AI Mode; those use Googlebot and the Search index (Google docs). Blocking `GPTBot` does not block `OAI-SearchBot`. Owners often believe the opposite in both directions.
- **Verify:** Derived from ACC-2 results. Produce one plain-language line per vendor: "Training: blocked · Search: allowed · Live fetch: allowed."
- **Severity:** **Info** for the training decision. **S1** if a search bot is blocked alongside a training bot, unless the declared policy says search bots should be blocked (search bots default to allowed). This is the same root cause as the ACC-2 finding, so it's reported once.
- `Confidence: Inferred · Cost: T0 · Rationale: Documented`

#### ACC-7 · Crawl-delay and rate-limit posture toward AI bots
- **Measures:** `Crawl-delay` values in AI-bot groups; 429 responses and `Retry-After` values seen in ACC-4 or ACC-5.
- **Why (AI):** Anthropic documents honoring `Crawl-delay`. Very large values (e.g., ≥60 s) cap how many pages a search bot can refresh per day. Aggressive rate limits hit live fetchers mid-answer.
- **Severity:** 429 to a search bot or live fetcher on first request **S1/S2** (this overlaps with ACC-4; report the root cause once). Very high crawl-delay **S4**.
- `Confidence: Verified (values) / Estimated (effect on refresh rate) · Cost: T0 (T3 for logs) · Rationale: Documented (directive) / Hypothesis (magnitude)`

#### ACC-8 · `llms.txt` presence (recorded, not scored)
- **Measures:** Whether `/llms.txt` (and `/llms-full.txt`) exist, their status, and whether the files are Markdown.
- **Why (AI):** **No major answer engine documents consuming it.** Google says you "don't need to create new machine readable files, AI text files, or markup" for AI features. OpenSEO's PM research reached the same conclusion. It is listed only because customers will ask. It must never raise severity or appear as a "missing" warning.
- `Confidence: Verified · Severity: Info only · Cost: T0 · Rationale: Hypothesis (no vendor documentation)`
- *(Round 2, decision 208)* The file is read whole (up to 1 MB) and its Markdown links `[text](url)` are followed: a link to this site is judged from the crawl, then from the IDX-5 sitemap check, otherwise with the same light request (at most 64 KB, no redirect followed), at most 50 more requests. One or more links leading to an empty page, a redirect, a 4xx or a 5xx is **S4**; a first line that is not a `# ` title is **Info** with the line quoted. *(Run 4, decision 211)* A link to another site goes through IDX-6's other-site check (one HEAD within its cap): 404 or 410 counts as not found, a redirect works, anything else is not checked with its reason. A missing file is still a pass. Single-page audit: presence and the first line only, site-level, no link requests. LG-80.

---

### IDX — Crawlability & indexability

*These are traditional checks, kept because search/index bots and live fetchers need a URL that resolves to a real, indexable page. Google AI Overviews depend directly on Google indexing.*

#### IDX-1 · HTTP status of crawled URLs
- **Measures:** Status code per URL: 2xx, 3xx (with target), 4xx, 5xx, plus transport errors (DNS, TLS, timeout).
- **Why (AI):** A 4xx/5xx page can't be retrieved or cited. Answer engines that cached a citation will send users to an error page. Repeated 5xx reduce crawl rate.
- **Verify:** Record the status from Maya's crawl. For 5xx, refetch once after a delay to separate persistent from transient errors, and record both results.
- **Severity:**
  - Persistent 5xx (fails again on refetch) **S1**. A 5xx that succeeds on refetch is a PRF-2 finding instead.
  - **Persistent transport error** (DNS failure, TLS handshake failure, connection refused/reset, or no response within Maya's 15 s timeout on every attempt) **S1**. Timeout-only failures are **Inferred**, with the stated assumption that engine fetch timeouts are no longer than 15 s; vendors don't document them. Intermittent timeouts are PRF-1 findings.
  - 4xx on a URL linked internally or listed in the sitemap **S2**.
  - 4xx that nothing references **Info**.
  - Cited URLs appear in the ANS-1 panel whatever their severity here.
- `Confidence: Verified (timeout-only failures: Inferred) · Cost: T0 · Rationale: Documented · OpenSEO: server-error, broken-page`

#### IDX-2 · TLS / HTTPS validity
- **Measures:** Certificate validity (expiry, hostname match, chain), protocol, and whether HTTP→HTTPS redirects cleanly for apex and `www`.
- **Why (AI):** An expired or mismatched certificate fails *every* automated fetcher. OpenSEO's audit skill singles out "an expired certificate" as a case that changes the whole recommendation.
- **Severity:** invalid cert **S1** sitewide. Expiry within 14 days **S3**. Missing HTTP→HTTPS redirect **S4**.
- `Confidence: Verified · Cost: T0 · Rationale: Documented (fetch fails) · OpenSEO: none (surfaced only via agent skill)`

#### IDX-3 · Redirect chains and loops
- **Measures:** Hops from the requested URL to the final 200, including loops. Also internal links pointing at redirecting URLs.
- **Why (AI):** Each hop adds latency to live fetches, and fetchers cap redirect hops (limits aren't documented by most AI vendors). A loop never resolves. Citations and internal links should point at the final URL. (The "link equity leak" rationale is dropped; see §7.)
- **Severity:** loop **S1** (the URL never resolves). Chain of 2 or more hops **S4** (capped: a chain's severity rests on the latency effect, which is Hypothesis).
- `Confidence: Verified · Cost: T0 · Rationale: Documented (loops) / Hypothesis (latency effect of chains) · OpenSEO: redirect-chain, redirect-loop`

#### IDX-4 · Canonical signals
- **Measures:** HTML `rel=canonical` vs `Link: rel=canonical` header (conflict); canonical pointing to a non-200, redirecting, or noindexed URL; canonical pointing to another URL, compared by content.
- **Why (AI):** Search-index-backed engines (Google, Bing) consolidate to the canonical, which becomes the URL that gets cited. A canonical pointing at a broken URL can drop a page from the index.
- **Verify:** Extract both declarations. Fetch the canonical target and record its status and indexability.
- **Severity:**
  - Canonical → 4xx/5xx/noindex **S2**.
  - HTML/header conflict **S3**.
  - Canonicalized to a URL with **different content** **S2**: engines that honor the canonical drop this page's own content. Exact-hash comparison is Verified; similarity comparison is Estimated. Whether the engine honors the canonical is **Inferred**, since Google documents canonical as a hint.
  - Canonicalized to a URL with the **same content** **Info** (normal consolidation).
  - **Info** if marked intended (§2.5).
- `Confidence: Verified (signals, exact-hash comparison) / Estimated (similarity comparison) / Inferred (engine's chosen canonical; T2 GSC can verify for Google) · Cost: T0 · Rationale: Documented (Google/Bing) / Hypothesis (other engines) · OpenSEO: canonical-conflict, canonicalized-page`

#### IDX-5 · XML sitemap health
- **Measures:** Sitemap discovered (robots.txt `Sitemap:` or `/sitemap.xml`); parses; URL count; share of listed URLs that return 200 and are indexable and self-canonical; `<lastmod>` present and plausible (not all identical, not in the future).
- **Why (AI):** Sitemaps are how search indexers (Bing → Copilot, Google → AI Overviews) find new and updated pages. Accurate `lastmod` is how they prioritize recrawls. Stale content in an index means stale facts in AI answers. Listing non-200 or noindexed URLs wastes crawl.
- **Severity:** no sitemap on a >50-page site **S4**. >10% of listed URLs non-200/noindex **S3**. All `lastmod` identical or future-dated **S4**. *(v2 Phase 3)* A sitemap document giving (nearly) every URL the same `lastmod` to the second — its generation time — **S4** (Verified values; the reading as a generation time is Inferred).
- *(Round 2, decision 206)* **Every** sitemap URL is judged, not only the ones the crawl read: those are reused free, files (nested sitemaps, images, PDFs) are left out, robots.txt-disallowed URLs are counted as disallowed and not asked, and every other one gets one light request (GET, at most 64 KB read, no redirect followed, the usual pace, time limit and URL safety; status, Location, size, X-Robots-Tag, meta robots, canonical, the empty-page rule, the error-message rule). At most 200 (Quick, the CLI default) or 1,000 (Standard, `--max-pages` 500 or more), set with `--sitemap-check-max N`; 0 in a single-page audit. Above the cap one URL of each top-level section in turn, in sitemap order, the same every run. A 429 stops the requests, so do 3 blocked answers in a row; the rest is said as not checked. The share counts redirects, 4xx, 5xx, empty pages and noindex; canonical-elsewhere and disallowed URLs are listed beside it. Threshold (>10%) and **S3** unchanged; a sampled share is Estimated, carries the sample note and LG-78. An empty page found here is also IDX-1's. **S3** for a sitemap file named in robots.txt or a sitemap index that answered 4xx/5xx, did not arrive or could not be read (the `/sitemap.xml` guess never, unless named). **S3** for an address with a `?` where a letter was lost (a query without `=`/`&` of letters, digits, `-` and `?`, with a `-` or `?`) or with a space, naming the word it probably is (each `?` replaced with ç, ğ, ı, ö, ş or ü and found in the pages read); **Info** for letters that are not percent-encoded. LG-79.
- `Confidence: Verified · Cost: T0 · Rationale: Documented (Google/Bing use sitemaps) / Hypothesis (lastmod effect on AI freshness) · OpenSEO: none (used for discovery only)`

#### IDX-6 · Broken internal links
- **Measures:** Internal `<a href>` targets that returned 4xx/5xx *when actually fetched*.
- **Why (AI):** Crawlers discover pages through links. Broken links to important pages hide them from discovery and dead-end live fetchers that follow links. Reported only for targets Maya really fetched (OpenSEO guard).
- **Verify:** Store the edge (source, target, anchor text) and the target's status. Group by target: "4 dead URLs linked from 11 pages" is 4 tasks, not 35.
- **Severity:** **S3** (degrades discovery). If the target itself should exist, that's the IDX-1 finding on the target.
- `Confidence: Verified · Cost: T0 · Rationale: Documented (discovery) · OpenSEO: broken-internal-link (critical)`
- *(Round 2, decision 211)* **Links to other sites are checked by default** (`--no-external-links` turns it off; off in the web app's demo mode). Each address is asked once with a HEAD (a 405 or 501 once more as a GET of at most 4 KB), after that site's robots.txt, which is obeyed and counts toward the cap: at most 20 + pages read and 100 requests (70 in Quick, 100 in Standard, 20 in a single-page audit) and 25 other sites. Order: sameAs profile links (asked even with the check off, at most 10), og:image, hreflang, STR-7's image files on other sites, then the other links, most-linked first. Only **404 and 410** are broken (**S4**, Verified, one grouped finding: "{links} link(s) to other sites on {pages} page(s) return 404 or 410"); a redirect works; 401, 403, 429, 999, 5xx, a timeout or a host that does not exist is "could not be checked", never broken, and a site that answered 429 or did not answer is asked nothing more. The site's own other hosts and brand-family domains are not asked. Maya's own fetcher, user agent, pace, time limit and URL safety; never Firecrawl or DataForSEO. Requests: none to the audited site. LG-83.

#### IDX-7 · Discoverability: orphans and depth
- **Measures:** Pages found only via the sitemap with no internal inlinks (**complete crawls only**, INT-2), and click depth from the homepage.
- **Why (AI):** Search indexers and link-following fetchers find pages through links. Orphaned or deep pages get discovered and refreshed less. (Rationale limited to discovery; see §7.)
- **Severity:** orphan **S4**, or **Info** if marked intended (§2.5); depth ≥5 **Info**. (Capped: Hypothesis.)
- `Confidence: Verified (complete crawl) / Not assessed (partial) · Cost: T0 · Rationale: Hypothesis (for AI engines) · OpenSEO: orphan-page, deep-page`

#### IDX-8 · Duplicate and near-duplicate pages
- **Measures:** Exact duplicate visible text (content hash) and duplicate `<title>` across indexable, self-canonical pages. Near-duplicate detection (shingling/simhash) is optional and labeled Estimated.
- **Why (AI):** When several URLs carry the same content, engines pick one, maybe not the one you want cited, and facts can be attributed to the wrong URL. Reframed from OpenSEO's "ranking signals split" rationale.
- **Severity:** duplicate group **S4**. (Capped: Hypothesis.)
- `Confidence: Verified (exact hash) / Estimated (near-duplicate) · Cost: T0 · Rationale: Hypothesis · OpenSEO: duplicate-content, duplicate-title`

#### IDX-9 · Google index status of key pages
- **Measures:** For key pages: Google's coverage state, Google-selected vs user-declared canonical, last crawl time, and whether a page reported "indexed" is actually eligible for snippets.
- **Why (AI):** AI Overviews / AI Mode require indexing (Documented). This turns IDX-4 / ACC-3 inferences into verified facts *for Google*. OpenSEO's index-bloat guide shows why: crawl-based suspicions were often wrong ("URL is unknown to Google").
- **Verify:** Google Search Console URL Inspection API (owner OAuth, quota-limited, free).
- **Severity:** "Crawled/Discovered – currently not indexed" or "Excluded by noindex" **S1** (Google AIO). Google chose a different canonical **S3**. The check runs on key pages because of API quota; the severity would be the same on any page.
- `Confidence: Verified (for Google) · Cost: T2 · Rationale: Documented · OpenSEO: inspect_urls MCP tool (not in audit)`

#### IDX-10 · Bing index status of key pages
- **Measures:** Whether key pages are in Bing's index, their crawl errors, and IndexNow submissions if configured.
- **Why (AI):** Bing grounds Microsoft Copilot. OpenAI documents that ChatGPT search sends rewritten queries to third-party search providers, but doesn't name them in the docs reviewed, so relevance to ChatGPT is **Inferred**.
- **Verify:** Bing Webmaster Tools API (owner API key). IndexNow can only be verified if the owner provides the key location.
- **Severity:** not indexed **S2** (Copilot). **Info** for IndexNow absence. The check runs on key pages because of API quota; the severity would be the same on any page.
- `Confidence: Verified (Bing) / Inferred (ChatGPT relevance) · Cost: T2 · Rationale: Documented (Copilot) / Hypothesis (ChatGPT)`

---

### RND — Rendering & content extractability

*Much of the AI gap lives here. Googlebot renders JavaScript; the major AI crawlers measured so far do not.*

#### RND-1 · Client-side rendering gap (raw vs rendered)
- **Measures:** Visible word count, headings, and main text in the **raw HTML response** compared with the **rendered DOM**, for a sample of pages (homepage + one per template + key pages).
- **Why (AI):** Vercel and MERJ analyzed crawler logs and found GPTBot, ClaudeBot, and PerplexityBot fetch HTML without executing JavaScript. Some downloaded JS files but never ran them. A page that ranks in Google (which renders) can be nearly empty to ChatGPT, Claude, and Perplexity. OpenSEO's roadmap explicitly doesn't plan JS rendering, so it can't measure this gap; at most it can flag thin raw HTML.
- **Verify:**
  - **With rendering (T1):** fetch raw HTML; render the same URL in headless Chromium (network idle, no interaction). Extract visible text from both views, and report `raw_words`, `rendered_words`, the ratio, and headings present only after render. The two counts are **Verified**. The threshold is policy: flag when raw < 50% of rendered, or raw < 50 words while rendered > 200.
  - **Without rendering (T0 fallback):** heuristic shell detection — empty mount node (`<div id="root|__next|app">` with no text), `<noscript>` "enable JavaScript" text, script bytes ≫ text bytes. Result is **Estimated**, and wording must say "may be client-rendered."
- **Severity:** main content missing from raw HTML (below the flag threshold) **S2** for non-rendering engines (OpenAI, Anthropic, Perplexity), per the §2.1 definition "retrieved, content missing"; **Info** for Google. Partial gap (ratio 50–80%) **S3**.
- `Confidence: Verified (T1) / Estimated (T0 heuristic) · Cost: T1 (preferred) / T0 · Rationale: Measured (Vercel/MERJ) · OpenSEO: thin-content (partial, raw-only)`

#### RND-2 · Critical facts present in raw HTML
- **Measures:** Whether the facts most likely to be quoted in answers exist in raw HTML text: product/plan names, prices, key specs, FAQ answers, company name and description, contact/location details.
- **Why (AI):** A page can pass RND-1 overall (lots of text) while the one thing people ask about (the price) is injected by JavaScript or hidden in a client-side tab.
- **Verify:** The owner lists critical facts per key page (e.g., "Pro plan $49/mo"); otherwise the check uses elements that only appear after render (from RND-1). Report found/not found in raw HTML with the matched snippet. Also check whether the fact appears in text or only in an image, `<canvas>`, SVG, or iframe (RND-4).
- **Severity:** critical fact absent from raw HTML **S2**.
- `Confidence: Verified (exact string) / Estimated (automatic candidate selection) · Cost: T0 (+T1 for auto-detection) · Rationale: Measured (via RND-1 finding) · OpenSEO: none`

#### RND-3 · Content behind interaction
- **Measures:** Content that only loads after a click, scroll, or expand (tabs, accordions filled by fetch, "load more," infinite scroll). Content that is present in HTML but visually collapsed is fine.
- **Why (AI):** Non-rendering fetchers never interact, and even rendering crawlers don't click.
- **Verify:** T1: compare the rendered DOM before and after scripted interaction on a sample. *(v2)* Before clicking, the page is left alone for the same wait (a control snapshot); only text beyond the control counts as revealed, and text that appeared with no click is recorded as late loading. T0: detect accordion/tab containers with empty panels in raw HTML (Estimated); the "load more" wording is English only, so non-English unrendered pages are not assessed for it.
- **Severity:** **S3**.
- `Confidence: Verified (T1) / Estimated (T0) · Cost: T1 / T0 fallback · Rationale: Measured (by extension of RND-1)`

#### RND-4 · Text locked in non-text formats
- **Measures:** Images with text-like dimensions and no or empty alt text inside main content; iframes carrying main content (embedded pricing widgets, docs); PDF-only content (key facts only in a linked PDF); `<canvas>` charts with no text equivalent.
- **Why (AI):** Text inside images or cross-origin iframes is not part of the page's extractable text. Engines that fetch the page don't get it. (Image alt text in general is covered in STR-7.)
- **Verify:** Raw-HTML inspection. Classifying an image as "contains text" without OCR is **Estimated**. With OCR (T1) it's Verified.
- **Severity:** **S4**. (Capped: Hypothesis.)
- `Confidence: Verified (iframe/PDF structure) / Estimated (image-of-text) · Cost: T0 / T1 (OCR) · Rationale: Hypothesis`

#### RND-5 · Interstitials, consent walls, and gated content in raw HTML
- **Measures:** Whether the raw HTML served to a fresh, cookie-less client is the content or a wall: a cookie-consent page replacing the body, a login or age gate, a geo-redirect, or a paywall with no `isAccessibleForFree` / paywalled-content structured data.
- **Why (AI):** Bots don't accept cookies or log in. If the wall *replaces* the content (instead of overlaying it), the engine indexes the wall.
- **Verify:** Compare browser-UA raw HTML to rendered content. Look for consent/login/paywall text signatures and redirects to `/login`, `/consent`, or country selectors. **Estimated** unless the wall is a redirect (Verified).
- **Severity** (split by the §2.1 definitions):
  - Wall reached **by redirect**, so the page itself is never served: **S1** ("cannot retrieve").
  - Wall served **in place of** the content: **S2** ("retrieved, content missing").
  - Paywall without structured data: **S4** (capped; see rationale).
  - Any of these → **Info** if marked intended (§2.5).
- `Confidence: Verified (redirect) / Estimated (signature) · Cost: T0 · Rationale: wall findings rest on what Maya's cookie-less fetch observed, plus the Measured fact that GPTBot/ClaudeBot/PerplexityBot don't execute JavaScript and so can't click through a consent wall. Not Hypothesis-backed, so the cap doesn't apply. Paywall structured data: Google's guidance concerns Search, and the AI-engine benefit is Hypothesis, so it is capped.`

#### RND-6 · HTML payload size
- **Measures:** Uncompressed HTML bytes, and the byte offset where main content starts (e.g., after 800 KB of inlined JSON state or CSS).
- **Why (AI):** Fetchers truncate large documents. Most AI vendors don't publish their limits. If main content starts late in a huge document, it may fall past the cutoff.
- **Verify:** Record size and main-content offset. Default flag above 1 MB, or main content starting past 500 KB. **These thresholds are policy, and vendor limits are undocumented.**
- **Severity:** **S4** (Hypothesis cap).
- `Confidence: Verified (bytes) / Estimated (effect) · Cost: T0 · Rationale: Hypothesis`

#### RND-7 · Main-content-to-boilerplate ratio
- **Measures:** Share of visible text in the main content region (`<main>`, `<article>`, or a readability-style extraction) vs navigation, footer, cookie banners, and repeated template blocks.
- **Why (AI):** Passage extraction and chunking work better when the main content is clearly delimited. Pages where boilerplate outweighs content produce poor passages.
- **Verify:** Readability-style extraction. The region detection is **Estimated**; presence of `<main>`/`<article>` is Verified.
- **Severity:** **S4 / Info**.
- `Confidence: Estimated · Cost: T0 · Rationale: Hypothesis`

---

### STR — Content structure & semantics

*The HTML facts are Verified. How much they matter for AI is mostly Hypothesis, so default severities are low and the labels say so.*

#### STR-1 · Title present and distinctive
- **Measures:** `<title>` presence, emptiness, and exact duplicates across different indexable pages.
- **Why (AI):** Answer UIs that show source cards (ChatGPT search, Perplexity, AI Overviews) display a page label, usually derived from the title. A missing or generic title ("Home") makes a citation unrecognizable to users. Character-length heuristics are in TSEO-1; they are not ranking limits.
- **Severity:** missing **S4** (capped: Hypothesis; see §8 Q5 for the evidence that could re-evaluate this). Duplicate across different pages **S4**. Generic (the site name alone, or "Home" / "Untitled") **S4**.
- `Confidence: Verified · Cost: T0 · Rationale: Hypothesis (observable in citation UIs, not documented as a selection factor) · OpenSEO: missing-title (critical), duplicate-title`

#### STR-2 · Heading structure for passage extraction
- **Measures:** Exactly one H1 that matches the page topic; H2/H3 present on long pages (e.g., >800 words with no subheadings); share of H2/H3 phrased as questions (recorded, not judged).
- **Why (AI):** Engines rewrite and expand queries into sub-queries ("query fan-out," per OpenAI and Google docs) and retrieve passages. Clear sectioning plausibly helps a passage get matched to a sub-question. This is a mechanism argument, not a measured effect. Heading-level jumps are handled separately as a low-severity technical hygiene heuristic in TSEO-1.
- **Severity:** missing H1 **S4**. Long page with no subheadings **S4**. Multiple H1s **Info**.
- `Confidence: Verified · Cost: T0 · Rationale: Hypothesis · OpenSEO: missing-h1, multiple-h1`

#### STR-3 · Structured data: present, parseable, and typed
- **Measures:** JSON-LD / Microdata / RDFa blocks; **JSON parse errors**; `@type`s present; expected types by page kind (Organization/WebSite on the homepage; Product/Offer, SoftwareApplication, Article with `author` / `datePublished` / `dateModified`, FAQPage, BreadcrumbList, LocalBusiness where relevant). Also required properties per type.
- **Why (AI):** Structured data gives unambiguous entity facts: names, prices, dates, authorship. Evidence is mixed and should be stated plainly:
  - Google says there's **no special structured data needed** for AI features, and it must match visible content.
  - Microsoft has said publicly (conference statements, 2025) that schema helps its LLMs understand content. That's a statement, not documentation.
  - OpenSEO extracts `hasStructuredData` but never reports on it.
- **Verify:** Parse every block. Report parse errors with the offending snippet. List types and missing properties. Presence and parse errors are Verified; "expected type for this page kind" relies on page-type classification, which is Estimated. *(v2 Phase 3)* Graph integrity across the crawl: an `@id` reference no crawled page defines (Info), one `@id` given different types (Info), a page-level node whose `url` names another same-origin URL than the canonical (Info) or a URL that returned an error (S4). `@id` values keep their fragments: `/#org` and `/#jane` are different entities.
- **Severity:** invalid JSON-LD (parse error) **S4** (the block is silently ignored; capped because the AI benefit is Hypothesis). Missing Organization on homepage **S4**. Missing type on a classified page **Info**.
- `Confidence: Verified (parse) / Estimated (page-kind expectation) · Cost: T0 · Rationale: Documented (Google: not required; match visible content) / Hypothesis (benefit) · OpenSEO: extracted, not reported`

#### STR-4 · Structured data vs visible content consistency
- **Measures:** Conflicts between structured-data values and visible text on the same page: price, currency, availability, rating, product name, dates, author.
- **Why (AI):** Google explicitly requires markup to match visible content. For answer engines, a conflict gives two "facts," and the wrong one may get quoted. This is the on-site version of OpenSEO's "present-but-wrong" finding (*"the fastest fix and nobody looks for it"*).
- **Verify:** For machine-comparable fields (price, currency, dates), normalize and string-match against visible text: Verified when the value is clearly absent or different. Fuzzy fields (names, descriptions) need LLM-assisted comparison, which is **Estimated** and **T4** if a metered model is used.
- **Severity:** price, currency, or availability conflict **S2** (content an engine would quote is wrong); conflicts in other fields (names, dates, author, rating) **S3**.
- `Confidence: Verified (exact fields) / Estimated (fuzzy) · Cost: T0 / T4 (LLM compare) · Rationale: Documented (Google) / Hypothesis (answer quality)`

#### STR-5 · Entity identity consistency
- **Measures:** Whether the brand/organization name is used consistently across `<title>` suffixes, `og:site_name`, Organization `name`, footer legal name, and logo alt text. Also whether `sameAs` links in Organization schema point to live, matching profiles (LinkedIn, Wikipedia/Wikidata, Crunchbase, GitHub, social).
- **Why (AI):** Brand mentions in AI answers depend on the engine resolving "which entity is this." Inconsistent names and missing or dead `sameAs` links make that harder. This is especially relevant for Maya, which tracks brand mentions.
- **Verify:** Extract the name variants and show the distinct set. Fetch each `sameAs` URL (status only, T0). *(v2 Phase 3)* The WebSite `name` is a source too. One brand `@id` given different names on different pages is its own finding (S4, Verified: no spelling judgement involved). The variant finding separates what is Verified (these values differ, as written) from what is Estimated (that they name one entity).
- **Severity:** `sameAs` URL 404 **S4**. More than 2 distinct brand-name variants **S4**. Missing Organization schema **S4**.
- `Confidence: Verified (values, statuses) / Estimated (whether variants are "the same entity") · Cost: T0 · Rationale: Hypothesis`

#### STR-6 · Freshness signals are present and agree
- **Measures:** Visible "published/updated" date on content pages; `dateModified` / `datePublished` in schema; sitemap `<lastmod>`; `Last-Modified` HTTP header. Also whether these **agree** (within a few days) and whether any are future-dated or clearly auto-stamped (every page "updated today").
- **Why (AI):** Time-sensitive queries ("best X in 2026," pricing) favor current sources, and engines need a date to judge that. Conflicting dates make freshness ambiguous. Evidence that dates affect AI citation is practitioner-level, not documented.
- **Verify:** Extract all four signals per page and show them side by side. Auto-stamping (all pages share today's `lastmod` or `dateModified`) is detected across the whole site. *(v2 Phase 3)* The `Last-Modified` header is stampable too (a CDN or page-cache time set minutes to hours before each request, seen on two real client sites), and so is one identical non-today date on nearly every page. A stamped signal is reported once, sitewide, and left out of the per-page comparison.
- **Severity:** conflicting dates >30 days apart **S4**. Sitewide auto-stamping **S4**. No date on article-type pages **Info**.
- `Confidence: Verified (values) / Estimated (page-type classification) · Cost: T0 · Rationale: Hypothesis`

#### STR-7 · Image alt text on meaningful images
- **Measures:** Images inside main content with no `alt` attribute (decorative `alt=""` is acceptable); coverage as `missing / total`.
- **Why (AI):** Minor for text answers. Relevant where images carry information (charts, diagrams, product photos) and for multimodal answers. Mostly an accessibility requirement, and fixing it for that reason is still worthwhile.
- **Severity:** **S4** when meaningful images carry information; else **Info**.
- `Confidence: Verified (missing attribute) / Estimated ("meaningful") · Cost: T0 · Rationale: Hypothesis · OpenSEO: images-missing-alt (warning)`

#### STR-8 · Semantic HTML for comparative and structured facts
- **Measures:** Whether tabular facts (pricing tiers, spec comparisons) use `<table>`, and whether steps and lists use `<ol>`/`<ul>`, vs `<div>` grids that look like tables.
- **Why (AI):** Comparison and "which plan" answers draw on tabular data. Real table markup keeps row/column relationships when HTML is converted to text. The extraction benefit is a plausible mechanism, not a measured effect.
- **Severity:** pricing or spec comparisons built from div grids **S4** (content type is an Estimated classification, not importance); other div-grid tables **Info**.
- `Confidence: Estimated (detecting "looks like a table") · Cost: T0 / T1 · Rationale: Hypothesis`

#### STR-9 · Language and locale declaration
- **Measures:** `<html lang>` presence and validity; whether it matches the detected content language (Estimated); hreflang reciprocity for multi-locale sites.
- **Why (AI):** Engines answer in the user's language and locale. A wrong or missing `lang`, or broken hreflang, can surface the wrong locale's page (and prices) in answers.
- **Severity:** `lang` mismatched with content **S4**. hreflang non-reciprocal or pointing to non-200 **S4**.
- `Confidence: Verified (attributes, statuses) / Estimated (language detection) · Cost: T0 · Rationale: Documented (Google hreflang) / Hypothesis (AI engines) · OpenSEO: hreflang extracted, not reported`

#### STR-10 · Link-preview metadata
- **Measures:** `og:title`, `og:description`, `og:image` (and whether the image URL returns 200), `meta description`.
- **Why (AI):** Some answer and chat interfaces build source cards or link unfurls from OG tags or the meta description. The benefit is presentation of a citation, not selection. Kept at Info because it's cheap and the data is already extracted.
- **Severity:** **Info** (`og:image` 404 → **S4**).
- `Confidence: Verified · Cost: T0 · Rationale: Hypothesis · OpenSEO: missing-meta-description (warning); OG extracted, not reported`
- *(Round 2, decision 209)* An og:image that is the site icon (an address ending in `.ico`, or an `image/x-icon` / `image/vnd.microsoft.icon` answer) is **S4**, told from the address with no request needed. The og:image request (GET, at most 64 KB) also reads the image's width and height from its header (PNG, GIF, JPEG, WebP, ICO); under 200 × 200 is **S4**; an unknown size gives nothing. Same-site redirects of an og:image are followed, at most 3 hops. Both fixes ask for at least 1200 × 630. LG-81.

---

#### STR-11 · Structured data contradicts itself *(added 2026-09-22, v2 Phase 2)*
- **Question:** Does the page's structured data describe the same entity twice with different values?
- **Measures:** Top-level structured-data descriptions on one page (JSON-LD, Microdata, RDFa) that share an `@id`, or share a type family (product, article, organization) and a name/headline. For each pair, the values of `price` (including offers, `lowPrice`, `priceSpecification`), `priceCurrency`, `availability`, `datePublished`, `dateModified`, and (for a shared `@id`) `name`.
- **Why (AI):** Google requires markup to be a true representation of the page. Two descriptions of one entity that disagree give an engine two "facts", and at least one of them is stale. Unlike STR-4 this needs no reading of visible text, so it works in any language.
- **Scope:** every indexable page; within one page (the same `@id` across pages is not compared yet).
- **Pass:** no entity is described twice with different values.
- **Finding:** two descriptions of one entity give non-overlapping values for a field.
- **Not assessed:** a page whose JSON-LD does not parse (listed in coverage; STR-3 reports the parse error).
- **Confidence:** Verified when the descriptions share an `@id`; Inferred when grouped by type and name (assumption stated: same type and name on one page is the same entity).
- **Severity:** price, currency or availability **S2** (as STR-4: content an engine would quote is wrong); dates and name **S3**.
- **Root cause once:** a field STR-4 already reports as conflicting with the visible page on the same page is left to STR-4.
- **Reproduce:** fetch the page with Maya's user agent and read its JSON-LD blocks and `itemprop` attributes (the command is on each row).
- `Confidence: Verified / Inferred · Cost: T0 · Rationale: Documented (Google: markup must match the page) / Hypothesis (answer quality) · OpenSEO: none`

#### STR-13 · Invisible characters in the main text *(Round 2, decision 210)*
- **Measures:** U+200B, U+200C, U+2060, U+FEFF and U+00AD in the page's own text (header, menu, footer and sidebars left out), and apart those inside a word. U+200D is not counted (emoji need it). (STR-13 also reports unfilled template markers.)
- **Why (AI):** a zero-width space or soft hyphen inside a word splits it in two for a search engine; they usually come pasted in from a word processor or a design tool.
- **Severity:** **S4** from 10 on one page, Verified, owner content. LG-82.

---

### TSEO — Traditional SEO hygiene

*This add-on complements IDX, STR, and PRF. It does not repeat status, redirect, broken-link, image-alt, or response-time checks already owned by those categories.*

#### TSEO-1 · Metadata length and heading-order heuristics
- **Measures:** Character counts for the first non-empty `<title>` and meta description; heading-level jumps such as H2 directly followed by H4. Scope is readable, indexable raw HTML pages.
- **Guidance bands:** Title 10–60 characters; meta description 70–160 characters. These are editorial heuristics, not Google requirements, pixel-width calculations, or ranking guarantees. The counts are Unicode code points from raw HTML, after whitespace trimming and NFC normalisation (a letter and its combining accent count once).
- **Severity:** **Info** for the title and description bands, **S4** for skipped heading levels (a page whose first heading is an H3 or lower counts as one skip): any SEO effect is a hypothesis and the bands are policy. Confidence in the observed lengths/order is **Verified**; rationale is **Hypothesis**. Fix text asks the owner to review and improve the snippet/structure rather than asserting a ranking loss.
- **Not assessed:** raw-vs-rendered gap pages; truncated response bodies; discovered URLs not fetched before a page/time cap. Those gaps appear in coverage and prevent a clean pass.
- **Root cause once:** absent titles, absent descriptions, missing H1, and long pages without subheadings remain in STR-1/STR-2/STR-10. TSEO-1 handles length and hierarchy only.
- `Confidence: Verified · Cost: T0 · Rationale: Hypothesis · OpenSEO: title/meta length bands and heading-order skip checks (adapted as heuristics, not copied code)`

---

### PRF — Performance & fetch reliability

*Framed around bots fetching within a time budget, not around user experience metrics that a non-rendering bot never experiences.*

#### PRF-1 · Server response time (HTML)
- **Measures:** Time to first byte and total HTML download time for the document request, from Maya's crawler. For key pages and one page per template, the **median and p90 over ≥3 fetches**.
- **Why (AI):** Live fetchers (ChatGPT-User, Claude-User, Perplexity-User) retrieve pages *while generating an answer*, so a slow page risks being skipped. **The timeout budgets are not documented by the vendors**, so the magnitude is a hypothesis. Slow responses also reduce how much search bots crawl.
- **Verify:** A single measurement is a **Verified** fact about that request. Calling "this page is slow" from one sample is **Estimated**, so require ≥3 samples before raising a finding, and show all values plus the egress region.
- **Severity:** median >1.5 s, or an intermittent timeout (some attempts succeed): **S4**. A URL that times out on every attempt is an IDX-1 transport error. (Capped: the above-S4 default rested on the undocumented live-fetch budget. Thresholds are policy.)
- `Confidence: Verified (samples) / Estimated (generalization) · Cost: T0 · Rationale: Hypothesis (live fetch budget) / Documented (crawl rate, Google) · OpenSEO: slow-response (>1.5 s, info)`

#### PRF-2 · Fetch reliability
- **Measures:** Share of fetches that failed (timeout, connection reset, intermittent 5xx) across repeated fetches of the same URLs during the audit.
- **Why (AI):** An engine fetching once and failing doesn't retry the way a person would. Flaky origins lose citations unpredictably.
- **Verify:** Refetch sampled URLs 3× spaced over the crawl. Report `failures / attempts` per URL.
- **Severity:** ≥1 failure in 3 attempts on a URL **S4**; sitewide failure rate >5% **S4**. (Capped: Hypothesis. Persistent failures are IDX-1 findings.)
- `Confidence: Verified · Cost: T0 · Rationale: Hypothesis`

#### PRF-3 · Core Web Vitals and Lighthouse metrics (optional)
- **Measures:** Metric values only, never category scores:
  - **lab** (Lighthouse): LCP, CLS, TBT, TTFB;
  - **field** (Chrome UX Report): LCP, INP, CLS at p75, when the URL/origin has enough traffic.
- **Why (AI):** **Weak for AI answers.** Non-rendering AI crawlers never paint the page, so LCP/CLS/INP don't exist for them. Google lists "optimize page experience" among general best practices on its AI features page, which is an indirect link through Search, not a documented AI-citation factor. Kept as an optional, clearly separated panel because customers expect it, and field TTFB supports PRF-1.
- **Verify:**
  - PageSpeed Insights API (free, API key, quota) returns both lab and CrUX field data: **T2**.
  - Lighthouse CLI self-hosted: **T1**.
  - DataForSEO Lighthouse (OpenSEO's route): **T4, paid**. Not recommended since free routes exist.
  - Lab values vary run to run → **Estimated** (show the run count, or the median of 3). CrUX field data is aggregated real-user data, so it's a **Verified** statistic about users but says nothing about bots.
- **Severity:** **Info** by default; never above S4.
- `Confidence: Estimated (lab) / Verified (field aggregate) · Cost: T1 / T2 (T4 via DataForSEO) · Rationale: Hypothesis (for AI) · OpenSEO: Lighthouse pass (scores + LCP/CLS/INP/TTFB, via paid API)`

---

### ANS — Answer-engine observations

*Kept visibly separate from the site findings above, following OpenSEO's split between Site Audit and AI Visibility.*

- **Site findings** (INT–PRF) are facts about the site, reproducible with a `curl`.
- **Answer-engine observations** are *samples of engine behavior*. They are non-deterministic, locale-dependent, time-dependent, and often from paid sources.

They appear in a separate panel, and **never change a site finding's severity or confidence.** In v2, cited status can raise a site finding's *priority* through page importance. In v1 it can't: cited-URL key pages are deferred (§8, Q3). All ANS checks need citation or answer data, which is **T4** (paid API such as DataForSEO LLM Mentions, or Maya's own prompt tracking, which has the same metered cost).

Framing rules carried over from OpenSEO's AI-search code:
- Report per engine/platform. A failure on one engine never hides the others.
- Keep "no data" (`null`) distinct from "zero mentions" (`0`).
- **v1: per-engine display only, no cross-engine totals.** Maya's citation data doesn't expose locale (§8, Q7), so the rule "never sum engines whose data covers different locales" can't be checked. Revisit once the team confirms whether locale exists in the database.
- Always show data freshness (fetch date; upstream refresh cadence, e.g., "updated monthly").
- Any count derived from sampled prompts is **Estimated** and shows the sample size.

#### ANS-1 · Health of URLs AI engines cite
- **Measures:** For each URL on the site that any tracked engine cited: current status, redirect target, indexability, robots/AI-bot access (run ACC-2 against it, plus ACC-4 on ownership-verified sites only), and raw-HTML content presence (RND-1).
- **Why (AI):** Citations already earned are the most valuable pages to protect. A cited URL that now 404s, redirects, or blocks the engine's bot is a direct, observable loss.
- **Verify:** Join citation data (T4) with a T0 fetch of each URL. **The site-side result is Verified; that the engine "cites" the URL is an Estimated observation from sampled answers** (show engine and `citedAt`). *(v2)* A cited URL that only redirects or declares a canonical is followed to where it lands (same origin, robots.txt obeyed, the same fetch cap) and judged there: a live, indexable landing page (for a canonical, with the same visible text) is *consolidated*, not a failure; an error or noindexed landing page, or a canonical to different content, is a failure at the site checks' own severity; a hop that was not fetched is *unresolved* (not assessed). Each healthy URL lists the site checks actually applied to it.
- **Panel rule (§8, F3):** the ANS panel lists **every cited URL whose site-side check fails**, whatever that finding's severity in the site report. It doesn't rely on site-finding severity to surface them.
  - Example: a cited URL returning 404 with no internal links or sitemap entry is **Info** under IDX-1, but still appears at the top of this panel.
  - Sort order: failure type, then most recent `citedAt`, shown per engine.
- **Severity:** comes from the underlying site check, unchanged. ANS adds the citation evidence; it doesn't raise severity (and in v1 doesn't raise priority either).
- `Confidence: Verified (site) + Estimated (citation observation) — shown separately · Cost: T4 + T0 · Rationale: Documented (inaccessible pages can't be retrieved)`

#### ANS-2 · Stale or wrong facts in answers vs the live site
- **Measures:** Where an engine's answer states a fact about the brand (price, plan names, features, founding date, location) that conflicts with the current live page it cited or with the owner's declared facts.
- **Why (AI):** OpenSEO's "present-but-wrong" class: *"where your pricing or description is stale, is the fastest fix and nobody looks for it."* The fix may be on-site (update or clarify the page, fix STR-4 conflicts, fix `lastmod`) or off-site (a third-party page the engine cited).
- **Verify:** Extract claims from the answer and compare with the cited page's current raw HTML and the declared facts. Extracting claims needs an LLM → **Estimated**, **T4**. Always quote the answer sentence and the page sentence side by side so the user can judge. *(v2)* Each claim gets a verdict — *matches*, *contradicted* (the page states a different value), or *absent* (the page does not state it) — and the comparison mode. Prices and numbers are compared deterministically (T0) against the page sentence sharing the claim's words; other claims by text containment; a comparison supplied upstream is used as given and labelled model-assisted. Only *contradicted* is a finding; *absent* is a review item. When the raw HTML lacks the claim, a rendered view of the page is consulted and the row says so.
- **Severity:** price/plan conflict **S2**; other factual conflict **S3**. (Severity describes the consequence *if* the conflict is real; confidence is labeled Estimated separately.) The Hypothesis cap doesn't apply: under §2.3, Self-evident harm puts only the fix under a Hypothesis label.
- **How to fix:** always labeled **Hypothesis**. Updating the cited page is expected to correct retrieval-backed answers, but that effect is unproven and the fix text must say so.
- `Confidence: Estimated · Cost: T4 · Rationale: Self-evident harm (§2.3). The wrong statement in the answer is itself the harm. Fix: Hypothesis (that fixing the page fixes the answer).`

#### ANS-3 · Retrieval vs training attribution note — **cut from v1 scope**

> **v1 status: cut (§8, F7).** This check compares answers that mentioned the brand *with* citations to answers that mentioned it *without* any. Citation-only data holds, by construction, only mentions that came with a citation, so there's nothing to compare against. Building it would mean faking the "without" side. Revisit in v2 only if Maya stores full answer records, including answers that mention the brand but return zero citations.

- **Measures:** Whether an observed mention came with citations (web-retrieved) or without (likely model knowledge).
- **Why (AI):** OpenSEO's "two surfaces" point: retrieved mentions can be affected by site fixes *this month*. Uncited mentions come from training data on a multi-year horizon. Technical audit fixes should be connected to retrieved mentions only. This is a labeling rule, not a finding.
- `Confidence: Estimated (a cited answer may still use model knowledge) · Severity: Info · Cost: T4 · Rationale: Documented (vendors describe retrieval) / Hypothesis (per-answer attribution)`

#### ANS-4 · Answer-engine coverage of this site

- **Measures:** For each engine present in the cited-domain export, how many times it cited this site, and how that splits across engines. Raises one Info finding per engine that cited the topic and never this site.
- **Input:** `--citation-domains`, the ranked cited-domain export (Maya's `get_citations` output). This is a **different file** from `--citations`: that one holds citations *of this site*, this one holds *every domain* the engines cited on this brand's prompts.
- **Why (AI):** An engine that cites a topic heavily and never this site is somewhere to look. It is not evidence of a defect: the engine may not cover the language or market, and this tool cannot see that. Hence Info and Hypothesis, never more.
- **One report per root cause:** when ACC-2 or ACC-6 already reports that engine's crawler as disallowed, ANS-4 links to that finding and adds what the block cost. It never re-reports the block.
- **Two refusals, both deliberate:**
  - A **truncated export yields no per-engine share.** The export carries totals for every domain but not per engine, so a per-engine denominator built from the listed rows alone would overstate this site on every engine. The check reports the site's own counts and says why the share is absent.
  - **No row for this site is Not assessed, never "zero citations."** A truncated export can omit a site that is in fact cited.
- **Never called Share of Voice.** Maya's product SoV counts brand mentions in answer text across a curated competitor set; this counts cited source domains including image CDNs and reference sites. On a real project the two differed by about 5x — both correct, measuring different things. Every result carries this disclaimer.
- `Confidence: Estimated · Severity: Info only · Cost: T4 · Rationale: Hypothesis`

#### ANS-5 · Where this brand is cited away from its own site

- **Measures:** The other domains cited on this brand's prompts, sorted into site / infrastructure / reference / directory / public / other, and which commercial domains are cited more often than the site itself.
- **Why (AI):** A brand's presence in answers often lives on directory and profile pages rather than its own site. That is visible only in citation data, and it is context for the site findings rather than a defect in the site.
- **Produces observations, not findings.** No severity: the spec sets no threshold for "too many citations on someone else's page," and inventing one would be a composite score by another name (§2).
- **The classification list is a hand-written starting point (LG-29),** not a validated taxonomy. Every result says so, and the rows are reported so a reader can judge them directly.
- `Confidence: Estimated · Severity: none (observations) · Cost: T4 · Rationale: Measured`

---

## 6. Check index

How to read this table:
- **Severity is set only by what is broken (§2.1).** No cell depends on key-page status. Importance and scope affect sort order only.
- **Markable** means an intent marking (§2.5) can move a matching finding to Info.
- **Declared bot policy** (training bots; search bots default to allowed) is a separate mechanism, noted where it applies.
- **Gate** = audit-integrity check, shown above all findings; it has no severity.

| ID | Check | Default severity | Confidence | Cost | Rationale | Markable |
|---|---|---|---|---|---|---|
| INT-1 | Fetch classification | gate | Verified / Estimated | T0 | — | — |
| INT-2 | Crawl completeness | gate | Verified | T0 | — | — |
| INT-3 | Rendering mode disclosure | gate | Verified | T0 / T1 | — | — |
| INT-4 | Maya crawler identity & robots compliance | gate | Verified | T0 | — | — |
| ACC-1 | robots.txt availability | 5xx/timeout **S1** · >500 KiB S3 · HTML at robots.txt Info | Verified / Inferred | T0 (AI-UA fetches: verified sites only) | Documented | No |
| ACC-2 | robots.txt rules per AI UA | search bot disallowed **S1** · live fetcher S3 · training bot S4 (Info per declared policy) | Verified / Inferred | T0 | Documented | Yes (path, per search/live bot) |
| ACC-3 | Meta robots / X-Robots-Tag / snippet controls | `noindex` **S1** on user-marked key or sitemap-listed pages; otherwise Info pending intent · `nosnippet` **S1** · `max-snippet:0` **S1** · `max-snippet` <50 S2 · content in `data-nosnippet` S2 · Bing `noarchive` S2 *(launch-gated)* | Verified / Inferred | T0 | Documented (Google, Bing) / Hypothesis (others) | Yes |
| ACC-4 | UA differential response test | search bot blocked **S1** · live fetcher blocked S2 · degraded content S2 · training bot S4 (Info per policy) · non-owned site: browser vs Googlebot once each on ≤3 URLs (Googlebot 5xx S2, 403/429/challenge S3, size Info; Estimated; partial) | Verified / Inferred | T0, **ownership-verified sites only** | Documented + case study | Yes (verified sites) |
| ACC-5 | Real AI-bot traffic from logs | search bot ≥X% non-2xx **S1**/S2 · allowed page never fetched S4 · bot not seen Info | Verified | **T3** | Documented | No |
| ACC-6 | Training vs search token scope | training decision Info · search bot also blocked **S1** (reported once with ACC-2) | Inferred | T0 | Documented | No (declared policy) |
| ACC-7 | Crawl-delay / rate limits to AI bots | 429 to search/live bot **S1**/S2 · very high crawl-delay S4 | Verified / Estimated | T0 (T3) | Documented / Hypothesis | Yes |
| ACC-8 | llms.txt presence | Info · links leading nowhere S4 | Verified | T0 | Hypothesis | No |
| IDX-1 | HTTP status & transport errors | persistent 5xx **S1** · persistent transport error **S1** · referenced 4xx S2 · unreferenced 4xx Info | Verified (timeouts: Inferred) | T0 | Documented | No |
| IDX-2 | TLS / HTTPS validity | invalid cert **S1** · expiry ≤14 days S3 · no HTTP→HTTPS redirect S4 | Verified | T0 | Documented | No |
| IDX-3 | Redirect chains & loops | loop **S1** · chain ≥2 hops S4 | Verified | T0 | Documented / Hypothesis | No |
| IDX-4 | Canonical signals | target 4xx/5xx/noindex S2 · canonicalized to different content S2 · HTML/header conflict S3 · canonicalized to same content Info | Verified / Inferred / Estimated | T0 | Documented (Google, Bing) / Hypothesis | Yes |
| IDX-5 | XML sitemap health | >10% of sitemap URLs not live/indexable S3 · failed named file S3 · malformed address S3 · no sitemap (>50 pages) S4 · lastmod identical/future S4 | Verified | T0 | Documented / Hypothesis | No |
| IDX-6 | Broken internal links | S3 | Verified | T0 | Documented | No |
| IDX-7 | Orphans & depth | orphan S4 · depth ≥5 Info | Verified / Not assessed (partial crawl) | T0 | Hypothesis | Yes |
| IDX-8 | Duplicate pages | S4 | Verified / Estimated | T0 | Hypothesis | No |
| IDX-9 | Google index status (key pages, quota) | not indexed / excluded by noindex **S1** · different Google canonical S3 | Verified | **T2** | Documented | No |
| IDX-10 | Bing index status (key pages, quota) | not indexed S2 · no IndexNow Info | Verified / Inferred | **T2** | Documented / Hypothesis | No |
| RND-1 | Raw vs rendered content gap | main content missing S2 (non-rendering engines; Google Info) · partial gap S3 | Verified (T1) / Estimated (T0) | T1 (≤20 pages) / T0 | Measured | No |
| RND-2 | Critical facts in raw HTML | S2 | Verified / Estimated | T0 (+T1) | Measured | No |
| RND-3 | Content behind interaction | S3 | Verified / Estimated | T1 / T0 | Measured | No |
| RND-4 | Text in non-text formats | S4 | Verified / Estimated | T0 / T1 (OCR) | Hypothesis | No |
| RND-5 | Interstitials & walls | wall via redirect **S1** · wall in place of content S2 · paywall without structured data S4 | Verified / Estimated | T0 | Measured (walls) / Hypothesis (paywall SD) | Yes |
| RND-6 | HTML payload size | S4 | Verified / Estimated | T0 | Hypothesis | No |
| RND-7 | Main content vs boilerplate | S4 / Info | Estimated | T0 | Hypothesis | No |
| STR-1 | Title present & distinctive | missing S4 · duplicate S4 · generic S4 | Verified | T0 | Hypothesis | No |
| STR-2 | Heading structure | missing H1 S4 · long page without subheadings S4 · multiple H1 Info | Verified | T0 | Hypothesis | No |
| STR-3 | Structured data parse & types | invalid JSON-LD S4 · missing Organization on homepage S4 · missing type Info | Verified / Estimated | T0 | Documented / Hypothesis | No |
| STR-4 | Structured data vs visible content | price/currency/availability conflict S2 · other field conflict S3 | Verified / Estimated | T0 / **T4** (fuzzy fields) | Documented (Google) / Hypothesis | No |
| STR-5 | Entity identity consistency | S4 | Verified / Estimated | T0 | Hypothesis | No |
| STR-6 | Freshness signals agree | S4 / Info | Verified / Estimated | T0 | Hypothesis | No |
| STR-7 | Image alt on meaningful images | S4 / Info | Verified / Estimated | T0 | Hypothesis | No |
| STR-8 | Semantic tables & lists | pricing/spec comparison in div grids S4 · other Info | Estimated | T0 / T1 | Hypothesis | No |
| STR-9 | Language & hreflang | S4 | Verified / Estimated | T0 | Documented / Hypothesis | No |
| STR-10 | Link-preview metadata | Info · `og:image` 404 S4 | Verified | T0 | Hypothesis | No |
| STR-11 | Structured data contradicts itself | price/currency/availability S2 · dates/name S3 | Verified (@id) / Inferred (type + name) | T0 | Documented (Google) / Hypothesis | No |
| TSEO-1 | Traditional metadata/heading hygiene | advisory Info for title/meta character bands; advisory S4 for skipped heading levels | Verified | T0 | Hypothesis | No |
| PRF-1 | Server response time | median >1.5 s S4 · intermittent timeout S4 | Verified / Estimated | T0 | Hypothesis / Documented | No |
| PRF-2 | Fetch reliability | S4 | Verified | T0 | Hypothesis | No |
| PRF-3 | CWV / Lighthouse metrics (optional) | Info (never above S4) | Estimated / Verified | T1 / **T2** (T4 alternative) | Hypothesis | No |
| ANS-1 | Health of cited URLs | severity from the site check; the panel lists **every** failing cited URL | Verified (site) + Estimated (citation) | **T4** + T0 | Documented | No |
| ANS-2 | Stale/wrong facts in answers | price/plan conflict S2 · other conflict S3 | Estimated | **T4** | **Self-evident harm** (fix: Hypothesis) | No |
| ~~ANS-3~~ | ~~Retrieval vs training attribution~~ | **Cut from v1**: can't be built from citation-only data | — | — | — | — |
| ANS-4 | Answer-engine coverage of this site | Info only | Estimated | **T4** | Hypothesis | No |
| ANS-5 | Where the brand is cited off-site | none (observations only) | Estimated | **T4** | Measured | No |

**Checks with a dependency beyond a plain crawl:**
- **Ownership-verified sites only:** the full ACC-4, and the AI-UA fetches in ACC-1. Non-owned site reports get the small browser/Googlebot check (decision 205) and say "Firewall blocking was only partly assessed."
- **T1 (self-hosted rendering, ≤20 pages per audit, §8 F8 order):** RND-1 (Verified mode), RND-3, OCR for RND-4. Each has a labeled T0 Estimated fallback.
- **T2 (free, needs owner connection):** IDX-9 (GSC), IDX-10 (Bing WMT), PRF-3 (PSI/CrUX).
- **T3 (customer logs):** ACC-5, optionally ACC-7.
- **T4 (paid/metered):** ANS-1, ANS-2, ANS-4, ANS-5, and the fuzzy-field half of STR-4. PRF-3 only if run through DataForSEO, which is not recommended.
- **Launch-gated (§4):** ACC-3's Bing default and every registry role/row still unverified.

**Totals:** 49 checks (4 integrity gates + 45 finding checks; STR-11 and TSEO-1 included; ANS-3 cut). **7 markable:** ACC-2, ACC-3, ACC-4, ACC-7, IDX-4, IDX-7, RND-5.

---

## 7. What OpenSEO covers that is NOT relevant to AI-answer visibility

**Test used:** an AI-specific severity is not inferred when a check's only causal path runs through SERP appearance, link equity, or Google-specific crawl-budget systems. A separate traditional-SEO hygiene check may record the directly measured condition as an S4 hypothesis, clearly labeled and not presented as an AI-access failure or ranking fact.

One honest caveat: Google AI Overviews draw on Google's index, and the citation-to-organic-ranking overlap was measured at 38–56% in studies OpenSEO cites (Ahrefs, Surfer, seoClarity), and that overlap is moving. So ranking factors are *not zero* for search-backed AI engines. They're **indirect**, and they belong to Maya's broader SEO context, not to a technical audit about AI access.

| OpenSEO check / component | Why it's not AI-relevant (as framed) | Maya disposition |
|---|---|---|
| `title-too-long` (>60), `title-too-short` (<10) | Character counts do not prove pixel truncation or a ranking loss. | **TSEO-1 advisory heuristic**, separate from AI findings. |
| `meta-description-too-long` / `too-short` (70–160) | Display and CTR effects vary; these are not search-engine limits. | **TSEO-1 advisory heuristic**, separate from AI findings. |
| `duplicate-meta-description` | Rationale is identical SERP snippets confusing searchers. | **Excluded.** |
| `missing-meta-description` (warning) | Answer engines generate answers from page content, not meta descriptions. The only plausible use is a source-card preview. | **Downgraded to Info** (STR-10). |
| `heading-order-skip` (H2→H4) | A structural observation; no evidence here that a skip itself harms retrieval. | **TSEO-1 advisory heuristic**, not a retrieval claim. |
| `multiple-h1` (warning) | "Dilutes the main-topic signal" is a ranking-factor rationale. | **Downgraded to Info** (STR-2). |
| `no-outgoing-links` | Rationale is link equity pooling ("equity that flows into it stops there"). | **Excluded.** |
| `deep-page` (5+ clicks) — equity & crawl-budget rationale | Link equity doesn't apply. Crawl budget matters mainly for very large sites under Googlebot. | **Kept as Info, discovery-only rationale** (IDX-7). |
| `orphan-page` — "no internal link equity" half | Equity half not relevant; discoverability half is. | **Kept, reframed** (IDX-7). |
| `redirect-chain` — "leaks link equity" half | Equity half not relevant; latency/hop-limit half is. | **Kept, reframed** (IDX-3). |
| `thin-content` (<150 words) as a quality / Panda-style signal | A page's length is not an AI citation criterion; short, precise pages get cited. The useful signal hiding in it is "content missing from raw HTML." | **Replaced** by RND-1 / RND-2 (raw vs rendered). No standalone word-count threshold. |
| `images-missing-alt` (warning) — image-search rationale | Image search ranking isn't AI-answer visibility. | **Downgraded to S4/Info**, meaningful images only (STR-7). |
| Index-bloat workflow (noindex/410 decisions) | About Google's sitewide quality assessment and crawl allocation on large sites. | **Excluded** from AI audit. |
| Lighthouse **Performance / Accessibility / Best Practices / SEO category scores (0–100)** | Opaque composite scores, exactly what §1 prohibits. The SEO category checks things like tap-target sizing and legible font size, which don't affect bots. | **Excluded.** Show metric values only (PRF-3). |
| Lighthouse **LCP, CLS, INP** | Paint, layout-shift, and interaction metrics. Non-rendering AI crawlers never paint or interact. | **Optional Info panel only** (PRF-3). |
| Lighthouse via DataForSEO (paid) | Same data available free via PageSpeed Insights API or self-hosted Lighthouse. | **Not used** (T4 alternative noted only). |
| Title rationale "strongest on-page relevance signal" / keyword-in-title framing | A ranking-factor claim. | **Rationale replaced** (citation labeling, STR-1). |

Parts of OpenSEO that are **highly relevant and kept**: `blocked-page` / `rate-limited-page` / fetch classification (→ INT-1, and extended to AI user agents in ACC-4), `server-error`, `broken-page`, `broken-internal-link`, `redirect-loop`, `canonical-conflict`, `noindex-page` (raised to S1 for user-marked key and sitemap-listed pages, ACC-3), `duplicate-content` (reframed), `slow-response` (reframed around live fetchers), and the per-issue `howToFix` payload pattern.

---

## 8. Review decisions

**Review of 2026-09-14.** §0–§2 and the ACC category are approved as specified. IDX, RND, STR, PRF, ANS, §6, and §7 have not been signed off yet.

### 8.1 Resolved questions

**Q1 · Sending AI-bot user agents (ACC-4): approved as proposed.**
- ACC-4 runs **only on ownership-verified sites** (DNS, meta tag, or GSC).
- Every probe request carries `X-Maya-Probe: ua-differential`, and probe volume is capped per audit.
- On non-owned sites the full ACC-4 does not run, and ACC-2 + ACC-5 are the fallback.
- *Amended 2026-10-14 (decision 205, owner):* on non-owned sites a browser and Googlebot's user agent are compared on at most 3 URLs, one request each, tagged, never retried, and only where robots.txt allows Googlebot and Maya (at most 6 requests; INT-4 checks it). No other AI-bot user agent is sent to a non-owned site.

**Q2 · Training-bot policy: approved.**
- Onboarding asks whether AI training crawlers should be allowed. ACC-2 and ACC-6 use the answer to mark intended training-bot blocks as Info.
- If the question is skipped, no policy is recorded and §4's defaults apply (training-bot blocks stay S4).

**Q3 · Key pages in v1: user-marked pages plus auto-suggested homepage, pricing, and product pages.**
- Cited-URL-based key pages (T4) are **deferred to v2**, so v1 can ship without waiting on ANS data quality.
- Auto-suggestion is a page-type classification, so its result is **Estimated**.

**Q4 · Rendering budget: approved.**
- T1 rendering is capped at **~20 pages per audit**: homepage + one page per URL template + key pages.
- Every other page gets raw-HTML checks with the T0 Estimated fallback (RND-1, RND-3).

**Q5 · Hypothesis cap: kept.**
- Hypothesis-backed checks default to S4 or Info, **including STR-1**.
- **Future evidence source, for STR-1 only:** Maya's own citation data could show whether AI citation cards use the page's `<title>` text as the citation label. That would be a Measured observation Maya can make itself, with no need to wait for a vendor doc. It requires storing, for each citation, the label the engine actually displayed. Whether Maya's data holds that has not been checked. If it becomes available, re-evaluate STR-1's rationale strength. This is **not** a reason to raise STR-1's severity now.

**Q6 · Registry maintenance: needs a named owner before launch.**
- The owner will be confirmed separately.
- **Launch gate:** every §4 row marked "not checked" must be resolved first.

**Q7 · ANS data source: checked against Maya's real citation data.**
- **Available and reliable:** per-engine (`model`) and freshness (`citedAt`).
- **Not available:** locale. It isn't exposed anywhere in the visible data.
- **Mostly empty:** `sourceType` / `kind` are null on most records. This is a known gap.
- **Working assumption:** per-engine and freshness framing is available now; locale-specific framing is not.
- **Action:** confirm with the team whether missing locale is a gap in the database or only in what the MCP exposes, **before** deciding whether a paid source is needed.

### 8.2 Follow-ups raised by these answers

| # | Topic | Status |
|---|---|---|
| F1 | Key-page status vs §2.1 | **Decided, applied.** Severity comes only from what's broken; importance is sort-only (three tiers); path-level intent markings (§2.5). Severity rules rewritten; §6 rebuilt. |
| F2 | Hypothesis-cap violations (incl. RND-5 split, PRF-1 timeouts, IDX-1 transport-error gap) | **Approved, applied**; the IDX-1 gap is filled in the post-F1 pass |
| F3 | ANS panel surfaces failing cited URLs | **Approved, applied** (ANS-1) |
| F4 | Ownership gate knock-ons | **Approved, applied** (ACC-1, ACC-4, ANS-1) |
| F5 | Search bots default to allowed | **Approved, applied** (ACC-2, ACC-6) |
| F6 | Registry launch gate | **Approved, applied** (§4) |
| F7 | ANS per-engine only; ANS-3 feasibility | **Approved, applied**; ANS-3 cut from v1 |
| F8 | Rendering order within the ~20-page cap | **Approved** |
| F9 | Fourth rationale level for ANS-2-type checks | **Approved, applied** (§2.3 "Self-evident harm"; ANS-2) |

**F1 · Key-page status and severity. DECIDED, APPLIED.**

*Background.* §2.1 says page importance changes priority, never severity. Yet ACC-2, ACC-3, ACC-5, IDX-1, IDX-3, IDX-4, IDX-6, RND-1, RND-5, STR-4, and STR-8 still name key pages inside their severity rules (a drafting error). Declared bot policy couldn't express page-level intent, which is why a new mechanism was needed.

*Decided (owner, this review):*
- **Path-level intent markings:** a new capability, separate from the declared bot policy. Designed in **§2.5**.
- **No blanket downgrade for non-key pages.** Without a marking, a finding keeps the severity its check specifies. It drops to Info only when a matching marking exists.
- **Sort order:** importance (confirmed key page) sorts above scope; scope is the tie-break within an importance level. Written into §2.1.

*Worked example, redone with §2.5.* Site `example.com`:
- Homepage: user-marked (confirmed).
- `/pricing` and `/product/api`: **auto-suggested, not confirmed**.
- Declared bot policy: "block training bots." It affects none of the rows below, because these are page directives, not bot choices.

Five `noindex` findings (ACC-3):
- (a) 200 `/tag/*` archive pages: **intended**
- (b) `/pricing`: **accident**
- (c) `/integrations/sso` (not key, not suggested): **accident**
- (d) 40 discontinued `/product/*` pages: **intended**
- (e) `/product/api`: **accident**, and it sits under (d)'s pattern

ACC-3 currently states no severity for non-key pages. The table uses **S1**, the level the §2.1 definition gives to "told not to use it." Filling that value in properly is part of the post-F1 pass.

| Step | (a) `/tag/*` ×200 | (b) `/pricing` | (c) `/integrations/sso` | (d) `/product/*` ×40 | (e) `/product/api` | Sort order |
|---|---|---|---|---|---|---|
| **1 · First run, no markings** | S1 | S1 | S1 | S1 | S1 | (b), (e) → (a) → (d) → (c) |
| **2 · Owner marks ACC-3 `noindex` intended on `/tag/*` and `/product/*`.** The `/product/*` pattern covers the unconfirmed suggestion `/product/api`, so Maya asks about it. Owner picks "Decide later." | **Info** (shows "S1, marked intended") | S1 | S1 | **Info** ×40 | **S1** (left out of the marking until answered) | (b), (e) → (c) → Info rows |
| **3 · Owner confirms `/pricing` and `/product/api` as key pages** | Info | S1 | S1 | Info | S1, now permanently left out of `/product/*` | (b), (e) *(confirmed tier)* → (c) → Info rows |
| *3′ · Instead, owner answers "Not a key page" for `/product/api`* | Info | S1 | S1 | Info | **Info** (shows "S1, marked intended"; listed among the marking's covered pages) | (b) → (c) → Info rows |
| **4 · Next run: a new `/tag/new` page appears, and `/product/enterprise` is newly auto-suggested** | new page covered → Info; coverage "200 → 201" | S1 | S1 | Info | as in step 3 | `/product/enterprise` is left out of `/product/*` by default and called out in the report |

*How this handles auto-suggested, unconfirmed key pages (the case that broke A and B):*
- **Severity is never lowered for being unconfirmed.** Old option B under-rated (b) until a click; here (b) is S1 from the first run.
- **A pattern can't absorb them without an answer.** (e) stays visible until the owner decides. Only an explicit "Not a key page" (step 3′) lets a marking cover it. That is the owner's own call, and it's recorded as evidence.
- **The one noise cost left:** each intentional pattern is S1 on the first run, until it is marked once. After that it is Info and stays Info as the pattern grows (step 4).
- **Sort order uses the middle tier** (approved). Without it, unconfirmed suggestions sort with ordinary pages until confirmed. In step 1 the order would become (a) 200 → (d) 40 → (b), (e), (c), putting the `/pricing` accident below 240 intended pages. That's the ordering the owner ruled out.

*Decided (owner, follow-up review):*
1. **Severity comes only from what is actually broken.** Key-page status never raises or lowers a severity; it only changes sort order.
2. **Middle sort tier approved:** confirmed key pages → auto-suggested key pages not yet confirmed → all other pages. Scope is the tie-break within each tier.

*Applied.* Every severity rule was rewritten without key-page conditions, the missing severities were filled in, and §6 was rebuilt. Default severities that changed:

| Check | Before | After | Why |
|---|---|---|---|
| ACC-2 | search bot disallowed: S1 on key page or `/`; other pages unstated | **S1** on any sampled URL | cannot retrieve |
| ACC-3 | `noindex`/`nosnippet`: S1 on key page; other pages unstated | **S1** on any page | told not to use it (Google AIO) |
| ACC-3 | `max-snippet` <50 characters: flagged, no severity | **S2** | same effect class as `data-nosnippet` covering content |
| ACC-5 | key page never fetched: S4 | any allowed page never fetched: **S4**, grouped by template | observation, not importance |
| IDX-1 | persistent 5xx: S1 key / S2 elsewhere | **S1** | cannot retrieve |
| IDX-1 | transport errors: measured, no severity | persistent: **S1** (timeout-only failures Inferred: assumes engine timeouts are no longer than 15 s) | cannot retrieve |
| IDX-3 | loop: S1 key / S2 elsewhere | **S1** | never resolves |
| IDX-4 | key page canonicalized elsewhere: S3 | canonical points to **different content: S2** · same content: **Info** | the page's own content drops out; same content is normal consolidation |
| IDX-6 | S2 key/cited target / S3 elsewhere | **S3** | degrades discovery; a target that should exist is IDX-1's finding |
| RND-1 | main content missing: S1 on key page | **S2** | §2.1: "retrieved, content missing" (same logic as RND-5) |
| RND-5 | wall S1/S2 "on a key page" | redirect wall **S1** · in-place wall **S2** on any page | cannot retrieve / content missing |
| STR-4 | price/availability conflict: S2 key / S3 elsewhere | price/currency/availability **S2** · other fields **S3** | severity now by *field*, not page |
| STR-8 | S4 only on a key pricing page | pricing/spec comparisons in div grids **S4** (content type, Estimated) | severity by content type, not importance |
| PRF-1 | any timeout S4 | intermittent timeout **S4**; timeouts on every attempt → IDX-1 | splits cleanly with IDX-1 |

IDX-7, IDX-8, RND-4, and PRF-2 already had the same level on key and other pages (S4 after F2). Only the key-page wording was removed. IDX-9 and IDX-10 still run only on key pages, because of API quota; their severities don't depend on that.

**F2 · Hypothesis-cap violations. APPROVED, APPLIED.**
- **Lowered to S4:**
  - STR-1 missing title
  - IDX-7 orphaned key page
  - IDX-8 duplicates of a key page
  - RND-4 text locked in non-text formats
  - PRF-2 fetch reliability
- **Rule adopted:** the cap applies only when the severity rests specifically on the Hypothesis-backed claim. Applied to the four checks with mixed rationale:
  - **IDX-3:** chains of 2+ hops **S4**; loops unchanged.
  - **STR-3:** invalid JSON-LD **S4**.
  - **PRF-1:** median >1.5 s or timeout **S4**.
  - **RND-5:**
    - Paywall without structured data **S4**.
    - Walls are not Hypothesis-backed: they rest on what Maya's cookie-less fetch observed, plus the Measured fact that the major AI crawlers don't execute JavaScript. So the cap doesn't apply to them.
    - Separately, by the §2.1 definitions, the old single S1 splits in two: a wall reached by redirect is **S1** ("cannot retrieve"), and a wall served in place of content is **S2** ("retrieved, content missing").
- **ANS-2:** not capped. It now uses the fourth rationale level, **Self-evident harm** (F9, §2.3). Severity stays **S2 / S3**, and the fix is labeled Hypothesis.
- **RND-5 walls** stay **Measured**. They fail the Self-evident harm test in §2.3, because why they matter depends on a mechanism claim (these crawlers can't click through).

**F3 · APPROVED, APPLIED.**
- ANS-1 now lists every cited URL whose site-side check fails, whatever that finding's site-report severity.
- Cited status is not an importance input in v1.

**F4 · APPROVED, APPLIED.**
- ACC-1 sends search-bot user agents only on ownership-verified sites.
- ACC-4 carries the ownership gate.
- Reports on non-owned sites must say **"Firewall blocking was not assessed."**
- ANS-1 runs ACC-4 only on verified sites.

**F5 · APPROVED, APPLIED.**
- Search bots default to allowed unless the declared policy says otherwise (ACC-2 policy mismatch, ACC-6).

**F6 · APPROVED, APPLIED.**
- §4 now has a launch gate. Correction: the earlier text said "two" Anthropic rows; there are **three** (Claude-SearchBot, Claude-User, ClaudeBot), all sourced from press coverage, and all three are gated.
- The gate also covers the roles of Applebot/Applebot-Extended, Amazonbot, meta-externalagent, DuckAssistBot, and MistralAI-User, plus the Bing `noarchive`/`nocache` controls.

**F7 · APPROVED, APPLIED.**
- ANS shows per-engine data only, with no cross-engine totals, in v1.
- **ANS-3 is cut from v1.** It can't be built from citation-only data: every record is a mention that came with a citation, so there are no uncited mentions to compare against. It returns only if Maya stores full answer records, including answers with zero citations.

**F8 · Rendering order within the ~20-page cap. APPROVED.** (Specification only.)

Budget: **20 rendered pages per audit.** Slot counts are tunable policy.

1. **Homepage:** 1 slot, always.
2. **User-marked key pages:** up to **10 slots**. Order: the user's own ranking if given, else most internal inlinks first (a Verified crawl count).
3. **Auto-suggested key pages** (pricing, product): up to **3 slots**. Order: most internal inlinks first.
4. **One page per URL template:** the remaining slots, at least **6** guaranteed.
   - Templates are ordered by number of crawled pages in the template, most first.
   - Each template is represented by its page with the most internal inlinks.
   - A template already represented by a page chosen in steps 1–3 is skipped.
   - Template grouping collapses numeric IDs, UUIDs, dates, and slug-like path segments into placeholders. That grouping is **Estimated**. (OpenSEO samples Lighthouse per URL template the same way; I did not read its template-detection rules.)
5. **Backfill:** slots left unused by any step go first to further user-marked key pages, then to further templates.

Why reserve slots instead of a strict priority list: under a strict list, a user who marks 25 key pages would use the whole budget, leaving no template coverage. Template coverage is what lets RND-1 catch sitewide client-side rendering.

Pages not rendered:
- They get RND-1 and RND-3 raw-HTML heuristics (**Estimated**) and no OCR (RND-4).
- INT-3 lists the rendered set, and names every key page and template that wasn't rendered, so nothing reads as a pass.

**F9 · Fourth rationale level. APPROVED, APPLIED.**
- §2.3 now defines **Self-evident harm**: the observed condition is itself the harm, and only the fix is unproven.
- The Hypothesis cap doesn't apply to severity for these checks; the fix text is labeled Hypothesis. Confidence stays separate.
- A qualifying test keeps the level from becoming a way around the cap: if explaining why it matters needs any "engines use X to decide Y" claim, the check doesn't qualify.
- Applied to ANS-2.

§6 was rebuilt after F1 was decided. Check count: 45 in the body, 44 in v1 (ANS-3 cut). An earlier summary said 47; that was a miscount.

---

## 9. Sources

**OpenSEO (primary reference)**
- README: https://github.com/every-app/open-seo
- Issue registry (27 types, severities, copy): `src/shared/audit-issues.ts`
- Page analyzer (extracted fields): `src/server/lib/audit/page-analyzer.ts`
- Per-page and cross-page checks, thresholds: `src/server/lib/audit/issues/page-reporters.ts`, `multipage-checks.ts`
- Fetch classes: `src/shared/audit-fetch-class.ts`
- robots.txt / sitemap discovery: `src/server/lib/audit/discovery.ts`
- Lighthouse via DataForSEO, 10-page sample: `src/server/lib/audit/lighthouse.ts`
- Audit PM research (AI-crawler audit as P1, llms.txt skepticism, completeness gating): `docs/site-audit-pm-research.md`
- Crawl architecture: `specs/0009-site-audit-crawl-architecture.md`
- AI search (DataForSEO LLM Mentions, ChatGPT + Google AIO, null vs zero, locale gating): `src/server/features/ai-search/services/brandLookup.ts`, `brandLookupShaping.ts`, `shareOfVoice.ts`, `promptExplorer.ts`
- Audit agent skill ("verify every finding against live HTML"): `.agents/skills/seo-audit/SKILL.md`
- https://openseo.so/features/site-audit
- https://openseo.so/features/ai-brand-visibility
- https://openseo.so/features/ai-search-prompts
- https://openseo.so/docs/skills/seo-audit
- https://openseo.so/library/site-audit/technical-seo-audit-checklist
- https://openseo.so/library/site-audit/index-bloat
- https://openseo.so/blogs/two-surfaces-two-timelines (UA-differential 429 case; citation-overlap studies)
- https://openseo.so/roadmap ("Agent readiness checks in site audits" — Soon; JS rendering — Not planned)

**AI engine vendor documentation (checked 2026-09-13)**
- OpenAI crawlers: https://developers.openai.com/api/docs/bots
- Perplexity crawlers: https://docs.perplexity.ai/guides/bots
- Google AI features and your website: https://developers.google.com/search/docs/appearance/ai-features
- Google crawlers / Google-Extended: https://developers.google.com/search/docs/crawling-indexing/google-common-crawlers
- Anthropic crawlers: https://support.claude.com/en/articles/8896518 ("Does Anthropic crawl data from the web, and how can site owners block the crawler?", last updated 2026-04-07; read 2026-09-22). IP ranges: https://claude.com/crawling/bots.json. Earlier press coverage: https://searchengineland.com/anthropic-claude-bots-470171

**Standards and measurements**
- RFC 9309, Robots Exclusion Protocol (group matching, 4xx/5xx handling, 500 KiB limit)
- Vercel + MERJ, "The rise of the AI crawler" (AI crawlers don't execute JavaScript): https://vercel.com/blog/the-rise-of-the-ai-crawler

**Not re-verified (verify before implementation):** Microsoft conference statements on schema and LLMs (2025). Bing `noarchive`/`nocache` controls, the Anthropic rows, and every registry row marked "not checked" are covered by the §4 launch gate.
