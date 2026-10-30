# The local web app

A chat-style page for running Maya Audit on this computer: paste a website, review a plan, start it, watch it,
read the findings and the action plan, download the report, and ask questions about it. The package is
`maya_audit_web/`. The audit engine (`maya_audit/`) does every measurement and makes every judgement; the web app
starts audits, remembers them, and shows what the saved report says. The command line works as before.

## Start it

```sh
cd "/Users/YOUR_USER/Desktop/maya-audit-checklist 2"
.venv/bin/python -m maya_audit_web --demo
```

Then open **http://127.0.0.1:8770**. Stop it with Ctrl+C in the terminal.

- `--demo` runs the real engine against two made-up sites and a made-up DataForSEO, all held in memory. Nothing
  real is contacted and nothing is charged. Demo history and its spending record live in their own folder.
- Without `--demo` it audits real websites, and sends real paid requests to DataForSEO only after you confirm them:
  `.venv/bin/python -m maya_audit_web`
- `--port 9000` picks another port. The app only ever listens on this computer (`127.0.0.1`); there is no option
  to listen anywhere else.

First-time setup, from the project folder:

```sh
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m playwright install chromium      # for JavaScript rendering and PDF; the app works without it and says so
```

Verified here with Python 3.13.1, FastAPI 0.142, uvicorn 0.54, httpx 0.28, Playwright 1.63.

`maya_audit_web_lite.py` is the older helper (port 8765, runs the command line and shows its Markdown). It still
works and is unchanged. It has no plan, no confirmation step for small amounts and no saved history: use
`python -m maya_audit_web` instead. The two do not share history; they do share the spending ledger.

## Where things are kept

Everything is outside the repository, under `~/.maya-audit/` (set `MAYA_AUDIT_HOME` to move it).

| Path | Holds | Written by |
|---|---|---|
| `~/.maya-audit/dataforseo-ledger.jsonl` | The spending ledger: every paid call, reserved and settled. | The engine. Shared by the command line and the web app. |
| `~/.maya-audit/dataforseo-cache.db` | Saved paid answers (7 days). | The engine. Shared. |
| `~/.maya-audit/web/web-v1.db` | History: plans, confirmations, audits, progress events, conversations, business profiles. | The web app. |
| `~/.maya-audit/web/worker.lock` | Held while the app runs, so a second copy cannot start a second worker. | The web app. |
| `~/.maya-audit/web/audits/<id>/state/crawl.db` | The saved crawl: what makes Resume possible. | The engine. |
| `~/.maya-audit/web/audits/<id>/artifacts/` | `report.json` (the authoritative record), `report.md`, `affected-urls.json`, `dataforseo.json`, `evidence/`. | The web app, from the engine's output. |
| `~/.maya-audit/web/demo/` | The same layout for demo mode, with its own ledger and cache under `paid/`. | Demo mode. |
| `~/.maya-audit/web/logs/maya-audit-web.log` | What failed on the server, with its traceback (rotated at 1 MB, three old files kept). The page shows only the error's kind. | The web app. |
| `~/.maya-audit/web/analyses/` | Revised analyses registered offline (`analysis-*`), shown read-only beside the history. | Prepared by hand. |

On macOS and Linux, files are created readable by you only (mode 0600, folders 0700). **On Windows these modes have
no effect:** Python's `chmod` can only set the read-only flag there, and access is decided by the folder's access
control list (ACL). The data folder is inside your user profile (`%USERPROFILE%\.maya-audit`), whose ACL by default
lets in only you, administrators and SYSTEM; the app does not change ACLs. Keep `MAYA_AUDIT_HOME` inside your profile,
or check the folder's ACL yourself (`icacls "%USERPROFILE%\.maya-audit"`). Reports hold the audited site's content:
nothing is uploaded or shared by the app. Deleting an audit in the sidebar removes its row (in one transaction) and its
folder; a file another program still has open stays on disk, and the answer says how many (`files_left`). There is no
automatic clean-up.

A download saves a copy wherever your browser puts downloads, on the computer the browser runs on. Another
computer needs its own installation; there is no hosted version yet.

The report file that can be downloaded holds file names, not this computer's folder paths.

## Jobs, recovery and resume

- One audit runs at a time, in a worker thread outside any request. Up to five more wait in a queue kept in the
  database.
- Each audit stores its plan and a snapshot of its settings. The engine also binds the saved crawl to its site and
  settings, and refuses to resume a crawl that does not match.
- Progress comes from the engine's own hooks. Nothing is animated or guessed.
- Files are written beside their target and swapped in, `report.json` last: a crash cannot leave half a report
  that looks whole.
- On start-up, any audit still marked waiting, running or stopping belonged to a process that is gone. It becomes
  **Interrupted**. Nothing is resumed and no provider is called until you press Resume.
- Resume continues the saved crawl. Pages already read are not read again. robots.txt and the sitemap are read
  again and the checks after the page reading run again over all pages, because the engine resumes the crawl, not
  each later step. The page limit covers all sittings together.

## Spending

- Backlinks are off unless you turn them on.
- The limit is $20 per day (`MAYA_AUDIT_DATAFORSEO_DAILY_USD` in `.env` changes it), and a plan above $2 needs its exact amount confirmed (`MAYA_AUDIT_DATAFORSEO_CONFIRM_ABOVE_USD`); below that it shows its cost and runs. One audit never spends more than $5 (`MAYA_AUDIT_DATAFORSEO_AUDIT_CAP_USD`), whatever was confirmed: a plan above it says which checks would be left out, and the report lists what was not requested. The plan card also shows the cost of each DataForSEO service, "SERP API calls: 0" and these three limits. The day is the UTC calendar day, as the ledger has always counted it; the page shows
  when it resets in your local time. The command line and the web app use one ledger file under one lock, so the
  limit is shared.
- Before any request that can cost money you see each request, its purpose, its maximum price, whether it is
  already saved (and how old), and what is left of today's limit. You must press **Confirm up to $X**. That
  approval is for that plan only, expires with it after 30 minutes, and does not survive a stop: resuming an audit
  whose paid data was not yet fetched asks again.
- Paid requests are never retried automatically. A request with no usable answer keeps its estimate counted,
  because it may have been charged.
- The app never raises the limit and never buys credit.

### Firecrawl (reading a blocked site's content)

> **Partly out of date since 8 Oct 2026.** Firecrawl now reads the pages of every audit when a key is set, with the
> basic proxy and no separate confirmation; the daily guard is 10,000 credits (an agent default, not an approved
> policy: decision 134); saved page copies last 1 day (7 days only for resuming an audit). The README's Firecrawl
> section is current. What follows still describes the stronger-proxy and retention flows correctly.

Off unless ticked on the plan card for that audit, and offered only when a Firecrawl key is set
(`MAYA_AUDIT_FIRECRAWL_API_KEY` in the environment or `.env`; the page is told only "set" or "not set").

- Maya's own crawler runs first and stays the access test. Firecrawl is asked for pages only if that crawl was
  blocked. Access results, robots.txt, headers, redirects, timings and the audit's outcome are never replaced.
- The plan card shows the most pages (default 50, adjustable), the most credits (2 a page with zero data retention,
  plus robots.txt and, from a cap of 10 pages, the two sitemap documents a challenged site may need), today's credits, and a dollar figure only when `MAYA_AUDIT_FIRECRAWL_USD_PER_CREDIT` is set.
  One Confirm button approves the exact maximum; when backlinks are on too it approves both, each exact.
- Daily limit: 200 credits per UTC day (`MAYA_AUDIT_FIRECRAWL_DAILY_CREDITS`), in its own ledger
  (`~/.maya-audit/firecrawl-ledger.jsonl`), shared with the command line. Pages read are cached for 7 days.
- Proxy `basic` unless "The site owner has approved bypassing bot protection" is ticked for that audit; the tick is
  stored with the audit and shown in the results and the PDF. It never carries over to the next audit.
- If Firecrawl refuses zero data retention, nothing more is sent. The card at the top of the results says so and
  holds the decision: a tick confirming that client page content may be stored by Firecrawl, and a button that is
  disabled until ticked and carries the exact credits (and dollars when a rate is set).
- If every page Firecrawl was asked for came back as a challenge page, an error or no document, the card says
  "Firecrawl basic was also blocked" and reading stops after three such pages. It offers a retry with the
  `enhanced` or `auto` proxy behind the owner-approval tick and a new exact confirmation; nothing stronger is ever
  used automatically. If that is blocked too, the card says so and offers nothing more.
- On a blocked audit that ran without Firecrawl, the same card offers "Read content via Firecrawl" afterwards.
- None of these three runs the audit again. A blocked audit keeps its own result in its state folder
  (`outcome.snapshot`, read back through an allow-list of the engine's data classes), so only Firecrawl is
  contacted and the website is asked for nothing more. An audit saved by an earlier version has no such file: the
  card says its last steps (robots.txt, the sitemap, the checks) will run again first.
- A stopped audit that has not used Firecrawl yet needs the credits confirmed again on Resume. An audit that
  already used it sends no new request on Resume.
- Results: a notice above the outcome says what was read and that AI crawlers may not see it; each finding that
  rests on it carries "Source: Firecrawl (Maya's crawler was blocked)", on the page and in the PDF. What Firecrawl
  read is saved apart from the evidence of Maya's own crawl, in `evidence-firecrawl`.
- When the local browser cannot start, the same box offers rendering through Firecrawl, under the same rules.

## The demonstration

`--demo` offers five sites:

| Site | What it shows |
|---|---|
| `demo-shop.localhost` | More than 500 English and Turkish pages with planted problems: noindex pages, broken links, a redirect, a JavaScript-only page, pages sharing a title that contains HTML, pages sharing a description, missing descriptions. Made-up citation data fills the AI-answer panel; made-up backlink figures fill the backlink panel. Quick ends "incomplete" at 50 pages; Standard at 500. |
| `demo-kafe.localhost` | Twelve Turkish pages that audit as "complete". |
| `demo-bank.localhost` | A site whose bot protection challenges every automated visitor: the audit is blocked, and the results lead with who blocked it and what to do. Tick **Read content via Firecrawl** on its plan to see a made-up Firecrawl read four made-up pages (no real Firecrawl is contacted and no real credit is spent). |

| `demo-vault.localhost` | Blocked like the bank, and the made-up Firecrawl refuses zero data retention: tick Firecrawl on the plan to see the consent step in the result card. |
| `demo-fortress.localhost` | Blocked like the bank, and the made-up Firecrawl's basic proxy is challenged too: tick Firecrawl on the plan to see "Firecrawl basic was also blocked" and the enhanced retry behind the owner tick. |

Rendering is off in demo mode (a browser cannot load a site held in memory), so the results also show a
"could not be checked" state. Everything is labelled as a demonstration, on the page and in the PDF.

## Manual checklist (demo mode)

1. **Banner.** An orange bar says this is a demonstration.
2. **Plan first.** Click "Try the demonstration: demo-shop.localhost", choose **Standard 500**, switch **Backlinks**
   on, press Enter. A plan appears: scope, time, what is checked, what is not available, things to know, and cost.
3. **Confirm.** Start is greyed out. Press **Confirm up to $0.0516**; it shows "Confirmed" and Start becomes usable.
4. **Options.** Press "Change options", add `/item/13` and `/tr/urun-7` as important pages, "Update plan". The new
   plan needs confirming again.
5. **Progress.** Start. Seven steps (Access … Report), "N of up to 500 pages checked", elapsed time, an estimate,
   and a Live log you can open.
6. **Stop and Resume.** Press Stop. It says Stopped, shows partial results, and says backlink figures are not
   available yet. Press Resume: it lists what is kept and what runs again and asks for the paid confirmation again.
7. **Results.** Outcome and reason, pages checked, rendering status, five severity counts with words and colours,
   the top five issues. Open "Details" on one: what, why, fix, confidence, suggested owner and effort (marked as
   estimates), all affected pages with a filter, and an Evidence button.
8. **Website text stays text.** Open "Problems by page" and find a row that says "Shares its title … with … other
   pages". The title reads `Sale "50%" <b>off</b> <script>alert("maya")</script>` as plain characters. No pop-up,
   nothing bold. (Until team-preview-12 the same text stood in an IDX-8 finding's title; a shared title is STR-1's
   finding only now, and its title holds a count.)
9. **Turkish.** Search `urun` in a finding's pages, or open the evidence for a `/tr/` page: ç, ğ, ı, ş, ö, ü read correctly.
10. **Follow-ups.** Use the chips: Show the action plan (switch between Everyone, Developer, Content, SEO), Only
    critical issues, Explain the top issue. Type `what is our ranking?`: it says the audit does not measure that.
11. **Downloads.** PDF, Markdown, JSON and the evidence zip each save a file named `maya-audit-demo-shop.localhost-<date>`.
    The PDF has a cover, a summary, the action plan, findings by area, what could not be checked, the two separate
    panels, a method page, and page numbers.
12. **History and comparison.** New audit → `demo-shop.localhost` with Quick 50 → Start. Both audits are in the
    sidebar with a status dot and words. In the new one press "Compare with the previous audit": it lists what
    differs between the two runs and does not call anything fixed that it did not look at again.
13. **A clean site.** Audit `demo-kafe.localhost`: "Audit complete", 12 pages.
    **A blocked site.** Audit `demo-bank.localhost`: the results open with "The site blocked this audit: Cloudflare (bot
    challenge)", three next steps, no "first action", and one line under "What could not be checked" for everything the
    block prevented. The plan card's Brand name and Country are prefilled; change them and they appear on the PDF cover.
14. **Restart.** Start a Standard audit, press Ctrl+C in the terminal, start the app again, reload. The audit is
    there as Stopped (or Interrupted after a crash) with a Resume button. Nothing restarted by itself.
15. **Dark mode.** The button at the bottom of the sidebar; the choice survives a reload.
16. **Keyboard.** Tab reaches every control with a visible outline; Enter sends; Esc closes the evidence panel and
    returns to the button that opened it.

## What a real audit can and cannot tell you

A real website may block or slow the audit. When it does, the outcome is "The site could not be read properly" or
"Audit incomplete", and the results cover only what was read. An audit of 50 or 500 pages is evidence about those
pages; it is not proof about every page of the site. The audit does not measure rankings, mentions in AI answers,
sentiment or traffic.

## Tests

`.venv/bin/python -m pytest -q -ra`

See "Results" at the end of this file for the last full run. `tests/test_web_app.py` runs every audit against
in-memory sites and an in-memory provider; `tests/conftest.py` blocks any connection that is not loopback, so a
test that tried to reach a real site would fail.

Measured on the synthetic 500-page demo site (2026-10-07, this computer): 3.2 seconds, peak memory 110 MB for the
whole app process, a 3.6 MB report, 0.7 MB of page evidence, a 34 KB results card and 60 KB for all findings, each
returned in about 0.03 s; other requests answered within 1.5 s while the audit ran. These are small static pages
read from memory. They show that counts, exports and the API hold up at 500 pages. They say nothing about how long
a real site takes (roughly 30 to 50 minutes at one request a second) or how much memory a real site needs.

## Not verified

- **A real website through the web app.** Only in-memory sites were used. The engine has been run on real sites
  before (`docs/RUNBOOK-LIVE.md`); this path to it has not.
- **A real DataForSEO request or balance check through the web app.** The provider was always a stand-in. The
  "insufficient credits" and "no subscription" wording relies on DataForSEO's codes 40200, 40210 and 40204. The
  automatic balance check of a paid plan, the balance warning and its choices, and the stop after a refusal for no
  credit (decision 180) have only run against stand-ins too (LG-65).
- **A real Firecrawl request, anywhere.** Every Firecrawl answer in development and in the tests came from a
  stand-in. The parameter names are from Firecrawl's public documentation. Credit prices, the wording of a
  zero-data-retention refusal, and what the `basic` proxy returns from a protected site are unconfirmed.
- **JavaScript rendering through the web app.** Off in demo mode and in the web tests. On a real site the app uses
  the engine's rendering with the engine's own network rules, as the command line does; the engine's rendering
  tests ran and passed in the full suite.
- **Browsers other than Chromium, and screen readers.** The page was driven in headless Chromium, including by
  keyboard only. No screen reader was used and no Safari or Firefox run was made.
- **Private-address refusal on a live redirect through the web app.** The app refuses private and loopback
  addresses at the plan and passes `--block-loopback` to the engine; the redirect and DNS cases are covered by the
  engine's own tests (`tests/test_stage1.py`, `tests/test_urls.py`), not repeated through the web layer.

## Blocked sites, addresses and brand

- **Blocked audits.** When the site's protection answers instead of the site, the engine names it where the response
  says who it is (Cloudflare, Akamai, DataDome, Imperva, Vercel, HUMAN) and otherwise describes it (a 403 from "the site
  or its firewall", a rate limit). Check ACC-9 reports it as an access finding: Maya's own crawler was turned away, and AI
  crawlers may be too, which was not tested. The audit never retries under another identity and never tries to get past
  protection. With fewer than three pages read, no "first action" is offered.
- **https first.** An address typed with `http://` or with no scheme is audited over `https://`. Only if `https://` does
  not answer at all is `http://` tried, once, and the audit says so. An address typed with `https://` is used as typed.
- **A redirect to another site.** When the start address sends visitors to a different domain, the audit stays where it
  was sent, says so, and offers "Audit <that site> instead?".
- **Brand and country.** The plan card suggests a brand name from the address, and a country from the language of
  the homepage in the last audit of the site or, failing that, from the address ending; it says where the
  suggestion comes from. Both are editable. Changing either saves it for that site and makes the plan again at
  once (Start waits for the new plan), so the country on the card is the market the search data is asked for. The
  card lists the market of each paid panel: search data (the country), ChatGPT (always United States, English),
  backlinks (none). A country the tool does not know stops a plan with search data until it is corrected or
  **Use United States figures** is ticked. Neither field ever changes a finding.
- **DataForSEO balance.** A plan with backlinks or search data reads the account's balance by itself (a free
  request, at most once in ten minutes; **Check account balance** reads it at once). When it is zero, below the
  plan's maximum, or the account did not answer, the card says so above Start, and Start asks once: **Run without
  search data**, **Run anyway** (not at zero) or **Cancel**. Run without it and DataForSEO is sent nothing; the
  report's data section says why. If the account runs out during an audit, the first refusal stops the remaining
  requests, and the report says which panels were not requested.

## Known limits

- **Design.** There is no `design-reference/` folder in this project, so the look is a restrained default. Every
  colour, radius and font is a variable at the top of `static/app.css`.
- **Turkish interface.** The interface is English. A Turkish table can be added to `strings.py` without code
  changes. Finding titles and fixes are written by the engine in English.
- **Questions are answered by rules, not a model.** A fixed set of questions and topic words is recognised.
- **Resume repeats the steps after the page reading.** The engine resumes the crawl only.
- **Saved page evidence stops at 500 records**, and a redirect counts as a record. The report states how many were
  not saved.
- **PDF needs Chromium.** Without it the app says so and offers a printable page. Fonts are the system's.
- **No hreflang in headers or sitemaps, no concurrent fetching.** Neither was added: nothing measured here showed
  the need, and both would change how the engine reads a site.
- **One user, no login.** See `docs/DASHBOARD-INTEGRATION.md`.
- **After restarting the app, the page reloads itself once** to pick up the new session.
- **The command line and the web app ask for approval above the same $2 per audit, and stop one audit at the same $5.**

## Results

Full suite on 2026-10-07: **677 passed, 0 failed, 1 skipped** in about 6 minutes.

- The skip is `tests/test_evidence_integrity.py`, which needs live-run example reports that are not kept in git.
- 55 of the tests are for the web app (`tests/test_web_app.py`, `tests/test_fixture_matrix.py`), 9 for the two new
  engine checks, 3 new ones for the skill readiness gate.
- The headless-browser tests (JavaScript rendering, PDF) ran: Chromium launches on this computer.
- One deprecation warning comes from the test client library, not from this code.
- Before this stage's work the suite stood at 643 passed, 1 skipped.

Checked by hand in headless Chromium against the running demo server, with no console errors: the checklist above
from step 1 to step 16 except step 9 (Turkish text was checked in the automated tests and in the PDF) and the
crash half of step 14 (a hard kill was exercised against the first version of the app, not repeated on this one;
the automated restart test covers the same code path).

## Blocked results, language and look (team-preview-4)

- **One card.** A blocked audit's results start with one card: who blocked it, what it means for AI crawlers, what
  to do next, the Firecrawl choice, and the audit's status. The separate outcome box is not shown beside it. The
  block's own finding (ACC-9) stays in the report, the PDF, the action plan and "All findings"; in the top list it
  is one line that points to the card.
- **Counter.** On a blocked audit the counter is "Readable pages" with the number of blocked requests beside it
  ("Readable pages: 0 (1 blocked request)"). An audit the site let in keeps "Pages checked".
- **Technical details.** The integrity gates (INT-1 to INT-4) and the checks by area are in one collapsed section.
- **Language.** `maya_audit_web/locales/tr.json` holds the Turkish interface and `locales/catalog/tr.json` the
  "why it can matter" notes. The switch is in the sidebar; the choice is a cookie (`maya_language`). An audit's
  progress lines are written in the language it was started in. What the engine writes about a site is English in
  the saved report and in the Markdown and JSON downloads. On the page and in the PDF, finding titles, "What to
  do", expected results, notes, the outcome sentence and the coverage sentences are shown in the reader's language
  by `maya_audit_web/wording.py` from `locales/findings/tr.json` (decision 165): a finding row keeps `title` and
  `fix` as the engine wrote them and adds `title_shown`, `fix_shown`, `expected_shown`, `notes_shown` and
  `untranslated`; English titles say "1 page", not "1 page(s)". A sentence with no translation is shown in English
  followed by "(İngilizce)". Check and gate titles and summaries, "What could not be checked" (each part and its
  reason), the DataForSEO panels (titles, sentences, figure and column names), the Firecrawl section, the Core Web
  Vitals summary, the archived-copies panel and the allow-list steps are shown the same way (decision 166, frames in
  `maya_audit_web/sentences.py`): each row keeps the report's own field and adds `title_shown`, `summary_shown`,
  `part_shown`, `reason_shown`, `lines_shown`, `notice_shown`, `state_label` or `data_shown` (a map of labels, not a
  second copy of a table). English shows every one of these with "1 page", not "1 page(s)". What knowingly stays
  English in the Turkish view (addresses, code, quoted site text, a provider's table cells, Google's metric names,
  and a few free-text errors that take the mark) is listed under LG-59. The Turkish is a machine-made draft to be
  reviewed by a native speaker (LG-59); the Turkish PDF's cover says so. A test fails when a sentence or a
  placeholder is missing from the interface strings, or when a title, a fix, an expected result, a check or gate
  summary, a reason or a panel line the engine can write has no Turkish entry and is not named in an allow-list
  (`tests/test_wording.py`, `tests/test_turkish_report.py`).
- **Look.** `static/app.css` follows the Maya dashboard: white cards with hairline borders, upper-case grey
  labels, black primary buttons, and one accent colour (orange) for what needs a decision. No font or other file
  is fetched from the network.

Not verified: the Turkish wording; Safari and Firefox; the card against a real Firecrawl answer (every Firecrawl in
the tests and the demonstration is made up).
