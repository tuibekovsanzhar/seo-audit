# How to publish the bot info page (launch gate LG-02)

Hand this to whoever can put a static page on a Maya-controlled domain. It takes about ten
minutes. **No live audit of any site can run until this is done** — the crawler refuses to start.

Checked on 2026-09-16: `https://withmaya.ai/maya-audit-bot` returns **404**, so this is still open.

---

## Why this page exists

The crawler identifies itself as `Maya-Audit/0.2 (+<url of this page>)`. When a site owner or a
security team sees an unknown bot in their logs, that URL is how they find out in seconds what it
is, what it does, and how to block it. A bank's security team will look. Publishing this is what
makes it acceptable to point the crawler at a customer's site.

---

## Step 0 — the file to publish is already generated

**Publishing on withmaya.ai? Use `for-withmaya.ai/index.html` and hand over [`HANDOVER.md`](HANDOVER.md)
instead of this file** — it is the same page without the "test deployment" disclosure, which would be
untrue on Maya's own domain, and the instructions are written for someone outside this project.
The rest of this file is for the test deployment.

**Publish `published/index.html` in this folder.** It is generated from `index.html` by
`scripts/prepare_bot_page.py`, a test proves it stays in sync with the template, and the crawler's
own verifier accepts it. The only value to confirm is the contact address, currently
`crawler@withmaya.ai` — if that mailbox does not exist, regenerate with:

```sh
.venv/bin/python scripts/prepare_bot_page.py --contact someone@withmaya.ai
```

Skip to Step 2. Steps 1a/1b below record what the generator changes, for anyone who would rather
edit by hand.

## Step 1 — (reference) the two edits the generator makes to `index.html`

**Line 91** — replace the contact placeholder with a real, monitored address:

```html
<!-- before -->
<p>REPLACE-BEFORE-PUBLISHING: add a real contact address for crawler questions and complaints.</p>

<!-- after (use an address that is actually read) -->
<p>Questions or complaints about this crawler: <a href="mailto:crawler@withmaya.ai">crawler@withmaya.ai</a></p>
```

**Lines 19–28** — delete the whole publishing-checklist HTML comment block, from `<!--` through
`-->`. It contains the words `REPLACE-BEFORE-PUBLISHING`, and the crawler refuses to run while that
text appears anywhere on the page.

Change nothing else. The rest of the page describes exactly what the crawler does, and it must stay
accurate.

## Step 2 — host it

- **HTTPS**, on a real public domain Maya controls. Suggested URL: `https://withmaya.ai/maya-audit-bot`
- Must return **status 200** (redirects are followed, so a redirect to the final page is fine)
- Must be a **stable URL** — it goes inside the user agent string on every request the crawler ever
  makes, so it should not move
- It is a single self-contained HTML file: no images, no CSS files, no JavaScript. Any static host
  or CMS page will do
- The page sets `<meta name="robots" content="noindex">`, which is intended — it does not need to
  rank

## Step 3 — verify it before anyone runs an audit

```sh
.venv/bin/python -c "
from maya_audit.botinfo import check_bot_info_page
print(check_bot_info_page('https://withmaya.ai/maya-audit-bot',
                          'Maya-Audit/0.2 (+https://withmaya.ai/maya-audit-bot)', 'Maya-Audit'))
"
```

It must print evidence with `'status': 200`, `'mentions_product_token': True` and
`'contains_unpublished_marker': False`. Anything else raises `BotInfoPageNotReady` with the reason.

The same check runs automatically before every live crawl, **before a single request reaches the
audited site**, and the result is recorded in the report's INT-4 evidence.

---

## What the guard checks, exactly

| Requirement | Why |
|---|---|
| URL uses `https` | The page is quoted to third parties |
| Host is a real public domain (not localhost, `.invalid`, `.example`, `.test`, `.local`) | It has to be reachable by whoever finds the bot in their logs |
| Returns 200 | A 404 is worse than no URL at all |
| Page text contains `Maya-Audit` | Confirms the right page was published |
| Page text does **not** contain `REPLACE-BEFORE-PUBLISHING` | Catches a half-finished publish |

## After publishing

1. Tell the team the final URL — every live run needs `--bot-info-url <that URL>`.
2. First live crawl goes to **withmaya.ai** (launch gate LG-01), 10 pages, reviewed by hand.
3. Keep the page in step with the crawler. It currently describes: robots.txt first and obeyed,
   one request at a time ≥1s apart (≥0.5s on a fast, error-free site, never below `Crawl-delay`), `Crawl-delay` honored up to 90s, no cookies (a self-redirect's own cookies kept for one re-check only, never stored), GET only, headless
   rendering of a small sample, repeated fetches of a sample for timing, ownership-verified-only bot
   user-agent probes tagged `X-Maya-Probe`, opt-in status checks of linked URLs on other sites, and
   opt-in PageSpeed Insights runs. If the crawler's behavior changes, this page changes with it.
