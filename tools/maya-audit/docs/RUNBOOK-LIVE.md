# Runbook: the first two live audits

Read [`LAUNCH-GATE.md`](LAUNCH-GATE.md) for known limits. The crawler-information page is optional:
if it is missing or returns an error, Maya records that and continues the site audit.

---

## Optional — publish the bot info page (LG-02)

The file to publish is **`site/maya-audit-bot/published/index.html`**, generated from the template
by `scripts/prepare_bot_page.py` and verified by a test. The only judgement call in it is the
contact address, currently `crawler@withmaya.ai`; regenerate with a different one if that mailbox
does not exist:

```sh
.venv/bin/python scripts/prepare_bot_page.py --contact someone@withmaya.ai
```

For clearer crawler identification, host it at a stable HTTPS URL — suggested
`https://withmaya.ai/maya-audit-bot` — then verify:

```sh
.venv/bin/python -c "from maya_audit.botinfo import check_bot_info_page as c; \
print(c('https://withmaya.ai/maya-audit-bot', 'Maya-Audit/0.2 (+https://withmaya.ai/maya-audit-bot)', 'Maya-Audit'))"
```

Expect `'status': 200`, `'mentions_product_token': True`, `'contains_unpublished_marker': False`.

---

## Step 1 — withmaya.ai, 10 pages (LG-01)

Maya's own site goes first, because this is where the tool meets a real CDN for the first time and
any defect is Maya's problem, not a customer's.

```sh
.venv/bin/python -m maya_audit crawl https://withmaya.ai/ \
  --max-pages 10 --delay 1 \
  --json reports/live-withmaya-01.json
```

**Read the INT gates before anything else.** They decide whether the rest of the report means
anything:

| Gate | What to look for | If it is wrong |
|---|---|---|
| **INT-1** | `ok`. If `degraded`, the CDN served challenges instead of pages | Everything below is about the CDN, not the site |
| **INT-2** | `incomplete` is expected at a 10-page cap; check the stop reason says `page_cap` | A stop reason of `rate_limit` or `error` means back off |
| **INT-3** | Says whether rendering ran; `raw_html_only` means Chromium is missing | RND-1/2/3 are fallback guesses only |
| **INT-4** | **Must be `compliant`.** One user agent, robots.txt first, no disallowed URL, politeness honored | Anything else is a defect in this tool. Stop and fix it before any client site |

Then repeat at `--max-pages 50` and read the findings against the site by hand. Only after that
should a customer domain be audited.

---

## Getting the two citation files

Both ANS inputs are Maya exports, and both are accepted **exactly as Maya returns them** — save the
response to a file and pass it. No rewrapping.

`--citations` (ANS-1, ANS-2) comes from `get_citation_examples`. **Pass the `domain` filter**, or
you get every domain the engines cited on this brand's prompts rather than this site's own
citations — on one real project the unfiltered call reported 314,846 rows:

```
get_citation_examples(projectId=..., domain="example.com", sinceDays=30, limit=50)
```

`--citation-domains` (ANS-4, ANS-5) comes from `get_citations` with **no** domain filter, because
the whole point is the other domains cited alongside this site:

```
get_citations(projectId=..., sinceDays=30, limit=50)
```

Save each to a file, then:

```sh
  --citations reports/<site>-citations.json \
  --citation-domains reports/<site>-citation-domains.json
```

Without them ANS-1, ANS-2, ANS-4 and ANS-5 report **Not assessed** with the reason — which is the
correct result for a site that is not a Maya project, not a gap to work around.

---

## Step 2 — enpara.com, 10 pages

A client site. Use a small page cap, obey its robots.txt rules, and stop at the first sign of strain.
The optional bot info page describes Maya's crawler but is not a permission check.

```sh
.venv/bin/python -m maya_audit crawl https://www.enpara.com/ \
  --max-pages 10 --delay 3 \
  --key-page https://www.enpara.com/ \
  --key-page https://www.enpara.com/ucretler \
  --key-page https://www.enpara.com/bilgi-bankasi/masrafsiz-bankacilik \
  --key-page https://www.enpara.com/bilgi-bankasi/eft-ve-havale-ucretleri \
  --key-page https://www.enpara.com/bilgi-bankasi/katilim-bankaciligi-nedir \
  --json reports/live-enpara-01.json
```

The five key pages are the URLs Maya's citation data shows AI engines actually quoting, so they are
the pages worth protecting. `--delay 3` is deliberate: three seconds between requests, one request
at a time, 10 pages — about 30 seconds of traffic in total.

**Stop immediately if** INT-1 reports `blocked` or `rate_limited`, or the crawl stops with
`rate_limit`. That is the site telling us to go away, and the answer is to stop, not to retry.

Add the ANS panel once a citation export exists (see `maya_audit/ans_data.py` for the shape):

```sh
  --citations reports/enpara-citations.json
```

---

## What will read "Not assessed" on the Enpara run, and why

This matters for reading the report honestly: **"Not assessed" is not a pass and not a failure.** It
means the check could not be performed, and every one of these prints its own reason.

### Because Enpara has no site-verification tag

| Check | Effect |
|---|---|
| **ACC-4** — user-agent differential (WAF/edge blocking) | **Not assessed entirely.** No probes are sent to an unverified site. For a bank behind a WAF this is the most valuable check, and it is the one the gap costs. |
| **PRF-3** — lab metrics | **Lab half not assessed.** PageSpeed runs make Google's servers load their pages. (The whole check is off anyway without `--pagespeed` and an API key.) |
| **ACC-1** — robots.txt availability | **Assessed, with less evidence.** robots.txt is fetched only with Maya's user agent; the per-bot fetches are skipped. |
| **ANS-1** — cited-page health | **Assessed, minus one failure type.** `bot_blocked_by_edge` comes from ACC-4, so a cited page that is served to browsers but blocked to GPTBot will not be caught. Status, robots rules, noindex, raw-HTML gaps and walls all still work. |

To close the gap, Enpara adds one tag to the homepage and the audit is re-run with
`--site-verification-token`:

```html
<meta name="maya-site-verification" content="TOKEN">
```

### For unrelated reasons, on this run

| Check | Why |
|---|---|
| **ACC-5** — real AI bot traffic | No access logs, and no Cloudflare integration on the Enpara project |
| **IDX-9** — Google index status | Needs a Search Console token for their property |
| **IDX-10** — Bing index status | Needs a Bing key, and is code-gated until the endpoint is verified (LG-09) |
| **PRF-3** — field metrics | Needs `--pagespeed` and `$MAYA_AUDIT_GOOGLE_API_KEY` |
| **ANS-1 / ANS-2** | Need `--citations`. ANS-2 also needs answer text, which Maya's export does not carry (LG-18) |
| **RND-2** — critical facts | Needs owner-declared `--critical-fact` values; otherwise it lists Estimated candidates instead |
| **STR** off-site links | `og:image` and hreflang targets and links on other sites are asked by default (DECISIONS 211) and stay unchecked with `--no-external-links`; `sameAs` profile links are asked either way |

### Partial because only 10 pages are crawled

INT-2 will say `incomplete` (stop reason `page_cap`). These checks need more pages before they mean
anything: **IDX-5** (sitemap coverage), **IDX-7** (orphans and depth), **IDX-8** (duplicates),
**STR-6** (sitewide auto-stamped dates), **PRF-2** (sitewide failure rate needs ≥20 attempts).

### Full results on 10 pages

Everything else is a real result, subject to the usual confidence labels: **ACC-1, ACC-2, ACC-3,
ACC-6, ACC-7, ACC-8, IDX-1, IDX-2, IDX-3, IDX-4, IDX-6, all of RND, all of STR, PRF-1, and PRF-2
per URL.**

Based on what Maya already recorded for Enpara, two findings are likely to appear straight away:
**STR-3** (two of the four homepage JSON-LD blocks fail to parse) and **STR-8** (the `/ucretler`
fee table is built from `div` elements rather than a `<table>`). The second one comes with a caveat
worth repeating to the client: İş Bankası's equivalent page also has no `<table>` and is cited more
often, so the div markup is unlikely to be the reason for the citation gap. That is exactly why
every STR finding is capped at S4 and labelled Hypothesis.
