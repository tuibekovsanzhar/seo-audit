# Live validation checklist: reading a real website (Phase 2)

For a person, on a website whose owner has agreed to the audit. Nothing here is run by the automated tests, and
nothing here was run while this checklist was written. Every step spends real Firecrawl credits and sends real
requests to the site.

What the made-up benchmark cannot tell us, and this checklist can: how the real Firecrawl service answers a sitemap
request, how long it really takes per page, and whether "stop after five unreadable answers" behaves sensibly on a
real protected site. These are launch-gate items LG-46 and LG-50 to LG-52.

## Before you start

| | |
|---|---|
| Owner's agreement | Written agreement from the site owner for this audit, with the date. Keep it with the report. |
| Site | One you are allowed to audit. Start with a small open site, then one protected site. |
| Keys | Already in your own `.env`. Do not paste a key into a chat, a ticket or this file. |
| Retention | Whatever you have set (`MAYA_AUDIT_FIRECRAWL_ZERO_DATA_RETENTION`). The checklist does not change it. |
| Limits | Unchanged: Firecrawl daily guard 10,000 credits (an unapproved default, LG-49); DataForSEO $20 a day, confirmation above $2 an audit, never more than $5 an audit (decision 192). |

## Options selected for these runs, and what they can cost

The basic proxy, no stronger proxy, no owner-approval tick, no DataForSEO search data. With these options the only
paid service is Firecrawl.

| Run | Page cap | Reader | Most requests | Most credits, retention off (1 a page) | Most credits, zero retention on (2 a page) |
|---|---|---|---|---|---|
| A. Small open site | 10 | Firecrawl, basic | 13 | 13 | 26 |
| B. Protected site, first look | 10 | Firecrawl, basic | 13 | 13 | 26 |
| C. Protected site, standard | 50 | Firecrawl, basic | 53 | 53 | 106 |
| D. Large site (optional) | 500 | Firecrawl, basic | 503 | 503 | 1,006 |

"Most requests" is the page cap, plus robots.txt, plus at most two sitemap documents. Maya shows its own maximum
before anything is sent: **the figure on your screen is the one that counts; if it is higher than this table, stop
and tell the developer.** Maya shows dollars only if you have set the price of a credit on your plan
(`MAYA_AUDIT_FIRECRAWL_USD_PER_CREDIT`); otherwise multiply the credits by your plan's price yourself.

To see a plan without spending anything (no request is sent, nothing is crawled):

```
.venv/bin/python -m maya_audit crawl https://SITE/ --max-pages 50 --firecrawl-dry-run
```

## Run A: a small open site (about 13 to 26 credits)

```
.venv/bin/python -m maya_audit crawl https://SITE/ --max-pages 10 --key-page /pricing
```

or in the app (`.venv/bin/python -m maya_audit_web`, then http://127.0.0.1:8770): Quick audit, 10 pages, one
important page.

Check and write down:

- [ ] The maximum credits shown before the run, and the credits recorded after it. Recorded must not exceed shown.
- [ ] Result is COMPLETED, and the three status lines read: direct access readable, coverage complete, AI crawlers
      not tested (unless you verified ownership).
- [ ] No "Sitemap through Firecrawl" line: on an open site Maya reads the sitemap itself and must not pay for it.
- [ ] The important page was read.
- [ ] Time taken, start to finish, and the number of pages. Divide: that is the real seconds per page. Write it
      down; it is the figure LG-46 needs.
- [ ] Findings look like the same site audited before Phase 2 (if you have an older report): no new problems that
      are not real.

## Run B: a protected site, 10 pages (about 13 to 26 credits)

A site that shows Maya a challenge page. Same command with the protected site's address.

- [ ] Direct access reads "challenged". The report does not say AI crawlers are unaffected or were tested.
- [ ] If pages were read: a line "Sitemap through Firecrawl: N address(es) found in …". Note N, and whether the
      note says the sitemap was refused or unreadable. Either answer is useful: it is what LG-50 asks.
- [ ] If the reader was challenged too: at most one request was spent, the result is DEGRADED, and the report shows
      the owner's allowlist steps. **Do not switch to a stronger proxy** unless the owner has approved it in
      writing; that is a separate run with the approval tick.
- [ ] If the reader was turned away part-way: the reading stopped after five unreadable answers, the result is
      INCOMPLETE, and the report says how many discovered pages remain unchecked and why.

## Run C: the same protected site, 50 pages (about 53 to 106 credits)

Only if run B read pages. Mark two or three important pages.

- [ ] Every important page is in the pages read.
- [ ] The pages read are a spread of the site (home, menu pages, one of each kind) and not fifty of one kind.
      "Kinds of page sampled" in the Firecrawl section of the report is the count.
- [ ] If the site has more than 50 pages: the result is INCOMPLETE, with "N more discovered URL(s) remain unchecked
      (the page cap)". That is correct, not a fault.
- [ ] Time taken. If the audit ran out of time before the reader finished, note how many pages were read; run it
      again later with `--reader-seconds-per-page` set to your measured figure from run A, rounded up.
- [ ] Open the PDF: long addresses wrap inside the page, Turkish letters (ç ğ ı İ ö ş ü) are correct, and the
      first page names the source ("via Firecrawl") and the coverage limits.

## Run D: a large site, 500 pages (optional; about 503 to 1,006 credits)

Only on a site whose owner expects that many requests. At one second between requests, plus the reader's own time,
expect well over an hour.

- [ ] The run finishes or stops at its time limit with a plain statement of how many pages were read.
- [ ] Stop it once on purpose (Stop in the app, or Ctrl+C): nothing more is sent after the stop, and the report
      says it was stopped on request.

## What to send back

For each run: the site's size, the page cap, maximum credits shown, credits recorded, pages read, minutes taken,
the sitemap line (or its absence), the result word, and anything in the report you believe is untrue. Do not send
keys, the `.env` file or the spending ledger.

## Not part of this checklist

- A stronger Firecrawl proxy. It needs the owner's recorded approval for that audit and is never chosen
  automatically.
- DataForSEO search data: separate cost, shown and confirmed in the app above $2; one audit stops at $5.
- Any other rendering service. None is installed, and none is recommended at present (decision 152).
