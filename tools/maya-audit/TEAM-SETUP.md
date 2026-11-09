# Maya Audit: setting it up on your Mac

This guide is for colleagues who are not developers. It takes about ten minutes. You will type a few commands
into the Terminal app; copy them exactly, one line at a time, and press Return after each.

Maya Audit runs on your own Mac. Nothing is installed system-wide, and nothing is shared with anyone: each
person's audits and reports stay on their own computer.

## What you need

- A Mac with macOS 12 or newer and about 1 GB of free disk space.
- **Python 3.11 or newer.** Check: open **Terminal** (press Cmd+Space, type `Terminal`, press Return) and run

  ```sh
  python3 --version
  ```

  If it prints `Python 3.11`, `3.12`, `3.13` or higher, you are set. If it prints a lower number, or says the
  command is not found, install Python from https://www.python.org/downloads/ (the "macOS 64-bit universal2
  installer"), then close Terminal, open it again and re-check.
- An internet connection for the installation steps only.

**On Windows** the steps are the same in PowerShell, with three substitutions: check Python with `py --version`,
create the environment with `py -m venv .venv`, and write `.venv\Scripts\pip.exe` and `.venv\Scripts\python.exe`
wherever this guide says `.venv/bin/pip` and `.venv/bin/python`. Native Windows behaviour is less verified than macOS
(see the release notes at the end of this guide).

## 1. Unzip

Double-click `maya-audit-team-preview-23.zip`. It creates a folder called `maya-audit-team-preview-23`. Move that
folder somewhere you will find it again, for example your Documents folder. Do not put it in iCloud Drive.

## 2. Open Terminal in that folder

In Terminal, type `cd ` (the letters c, d and a space), then drag the `maya-audit-team-preview-23` folder from
Finder into the Terminal window and press Return. For a folder in Documents the line looks like this:

```sh
cd ~/Documents/maya-audit-team-preview-23
```

Every command below is run from inside this folder.

## 3. Create the virtual environment

This makes a private copy of Python inside the folder, so nothing else on your Mac is touched.

```sh
python3 -m venv .venv
```

It prints nothing when it works.

## 4. Install Maya Audit

```sh
.venv/bin/pip install -e ".[team]"
```

This downloads what the app needs and takes a minute or two. Near the end you will see a line starting
`Successfully installed`. A notice after it about a newer version of pip is harmless; ignore it.

## 5. Install the browser component

Maya Audit uses its own copy of the Chromium browser to see what a page looks like after JavaScript runs, and to
make PDF reports.

**Do not skip this step. Without it the PDF button says “A PDF could not be made on this computer because the browser
component is missing.” and pages are not rendered with JavaScript.**

```sh
.venv/bin/python -m playwright install chromium
```

This downloads about 300 MB once and shows its progress. (If it prints nothing and returns at once, the browser was
already on this Mac from an earlier installation.) Run it again after every reinstall or update (step 4).

## 6. Try the demonstration first

```sh
.venv/bin/python -m maya_audit_web --demo
```

Terminal prints a few lines, including `Open: http://127.0.0.1:8770`. Open that address in your browser
(Chrome, Safari or Firefox). Leave the Terminal window open while you use the app.

The demonstration uses made-up websites and made-up figures. It contacts no real website and costs nothing, so it
is a safe place to learn the steps: click the `demo-shop.localhost` suggestion, press Return, read the plan, press
**Start audit**.

## 7. Real audits

Stop the demonstration first (see "Stopping" below), then:

```sh
.venv/bin/python -m maya_audit_web
```

Open http://127.0.0.1:8770, paste a website address, read the plan, and press **Start audit**.

- **How many pages** (DECISIONS 331): **Hızlı ~50**, **Akıllı ~150 (önerilen)**, **Derin ~500**, or **Özel sayı**
  (type 25 to 2000). Every one chooses its pages the same way: by your business type's page types, the homepage and
  key pages first, each page type a share by its rank, large types by the team's sampling rule (important, long tail,
  newest, exceptions). The plan says this in one line, with the time and Firecrawl's credits (the most it may use,
  and about how many it usually uses) before you start. **Tam tarama sırası** under "Ek seçenekler" reads pages in
  the order their links are found instead (the old way). Hızlı usually takes about 10 minutes, Akıllı 10-20, Derin
  30-50.
  **Single page** reads only the address you enter (no links are followed) and takes about a minute; its report is
  titled "Single-page audit" and says that other pages were not checked. What it reports about the whole site
  (robots.txt, redirects, HTTP to HTTPS) is labelled "Site-level".
  The site is read slowly on purpose, about one page a second, and its robots.txt rules are obeyed.
- A website can block or slow an audit. The report then says so and covers only the pages that were read.
- An audit of 50 or 500 pages tells you about those pages. It is not proof about every page of the site.
- You can press **Stop** at any time and **Resume** later.

## Stopping

Click the Terminal window and press **Ctrl+C** (hold Control, press C). An audit that was running is stopped
politely and can be resumed next time. Closing the browser tab does not stop the app; closing the Terminal window does.

To start again later: open Terminal, do step 2, then step 6 or 7. Steps 3 to 5 are needed only once.

## Where your reports and history are kept

On your Mac only, in a hidden folder in your home folder:

| What | Where |
|---|---|
| Your audit history and saved reports | `~/.maya-audit/web/` |
| Demonstration history (kept apart) | `~/.maya-audit/web/demo/` |

To look at it in Finder: press Cmd+Shift+G and type `~/.maya-audit`. Nothing is uploaded anywhere. The **Download**
buttons in the app save a PDF, Markdown or JSON copy to your browser's usual Downloads folder. To remove an audit,
hover over it in the app's sidebar and click the ✕.

Reports contain text from the audited website. Treat a client's report as you would any client document.

## Backlinks and DataForSEO

**Backlinks are off by default, and the app works fully without them.** You do not need to do anything.

Backlink figures come from DataForSEO, a paid service. They can be switched on only if DataForSEO credentials are
set up on your Mac. Please read this before doing that:

- **Only set this up if you have been told you may**, and with credentials given to you for that purpose.
- If so, create a plain-text file called `.env` in the `maya-audit-team-preview-23` folder with these two lines,
  using your own values:

  ```
  MAYA_AUDIT_DATAFORSEO_LOGIN=your-login
  MAYA_AUDIT_DATAFORSEO_PASSWORD=your-password
  ```

- **Never share credentials**: not in chat, not in email, not in a screenshot, and never by sending someone your
  folder or your `.env` file. The zip you received does not contain one, and you should not add one to a zip you pass on.
- Paid data is used only when you press its button for that audit. The plan card then shows each request and the
  maximum cost (about $0.05 for backlinks, about $0.29 for search data) before you start, what each DataForSEO
  service costs, and "SERP API calls: 0". Up to $2 an audit it runs without a separate Confirm step; above that it
  waits for you to confirm the exact amount. One audit never spends more than $5, whatever was confirmed: the
  requests that would pass it are not sent and the report lists them. There is a limit of $20 per day on each Mac.
  `.env.example` shows the three settings that change these (`MAYA_AUDIT_DATAFORSEO_CONFIRM_ABOVE_USD`,
  `MAYA_AUDIT_DATAFORSEO_AUDIT_CAP_USD`, `MAYA_AUDIT_DATAFORSEO_DAILY_USD`). Every request is recorded
  in `~/.maya-audit/dataforseo-ledger.jsonl`. The app never buys credit.

## Firecrawl reads the pages

**If a Firecrawl key is set up on your Mac, Firecrawl reads the pages of every audit.** Without a key the app works
as before: Maya's own crawler reads the pages, and you do not need to do anything.

- **Setting it up.** Add this line to the `.env` file in the project folder (ask the team lead for a key, and never
  paste a key into a chat):

  ```
  MAYA_AUDIT_FIRECRAWL_API_KEY=your-key
  ```

- **What it does.** Firecrawl is a paid outside service that reads web pages. The checks about page content rest
  on its reading and say "Source: Firecrawl". Maya's own crawler still asks the site directly for robots.txt, the
  sitemap, redirects, headers and timing, and still tests whether an automated visitor is let in.
- **No confirmation for a normal run.** The plan card shows the most credits the audit can use (1 per page, 2 with
  zero data retention; Hızlı is 50 pages, Akıllı 150, Derin 500, Özel sayı its own count; Firecrawl reads at most 500). Every request is recorded in
  `~/.maya-audit/firecrawl-ledger.jsonl`. To run one audit without Firecrawl, untick **Read the pages through
  Firecrawl** on the plan card. `MAYA_AUDIT_FIRECRAWL=off` in `.env` switches it off for this Mac.
- **A site that challenges Maya's crawler** (many banks and large retailers, through Cloudflare for example) is
  read through Firecrawl and reported normally: the counter says "Pages read: 6 (via Firecrawl)", and the challenge
  is one note under AI crawler access. The site is called blocked only if Firecrawl could not read it either.
- **Zero data retention.** The app asks Firecrawl not to keep the pages it reads. If the account does not have
  that, Firecrawl refuses, and the card at the top of the results says so: tick the box confirming that page content
  may be stored by Firecrawl and continue (the audit is not run again). To stop being asked on this Mac, add
  `MAYA_AUDIT_FIRECRAWL_ZERO_DATA_RETENTION=off` to `.env`; page content may then be stored by Firecrawl.
- **"Firecrawl basic was also blocked."** Then the card offers a retry with a stronger proxy. It needs the tick
  "The site owner has approved bypassing bot protection" and a confirmation of the exact credits, and both are
  written in the report. Never tick it without the owner's documented approval.
- **Maya's own copy of pages.** A page read through Firecrawl is kept on your Mac for one day, so auditing the same
  site again the same day re-uses it at no cost. From the next day the site is read again, so fixes show.
- **The Info note about a challenge** says verified search and AI crawlers are normally not affected, and that this
  was not measured: Maya's crawler is an unverified bot, so a challenge to it shows nothing about them.

## Reading a result: "What this audit covers"

Under the result's headline is a box with three lines. Read them before the findings:

- **Direct access (Maya's own crawler):** whether the site let Maya's crawler in, or challenged it.
- **Content coverage:** how many pages were actually read, and whether that is every page found or only part.
  "Partial" lists why (the page cap, a page that could not be read, the time limit, a stop).
- **Real AI crawlers:** almost always "Not measured". Reading a site through Firecrawl shows the content is readable
  through Firecrawl; it does not show that ChatGPT's or Google's crawlers are let in.

"Audit complete" now means every page found was read. If Firecrawl stopped at its page cap or could not read some
pages, the result says "Audit incomplete" and names what is left. The box also says how old any saved page copies
are, how long the whole audit took, and (under "What it cost") the credits and dollars spent.

In the demonstration, `demo-partial.localhost` shows a partly read site with missing search data, and
`demo-app.localhost` shows a site built with JavaScript and search data that is truly zero.

## Search data (paid) and Core Web Vitals (free)

Under the address box, and again under **Change** on the plan card, are four buttons. All are off until you press
them, and a plan that would cost money always shows its exact maximum before you start it.

- **Search data on (paid).** Adds what Google and AI assistants already show for the site, from DataForSEO: how
  many keywords it ranks for, the most searched ones, "quick wins" (keywords in positions 4 to 20), the sites that
  compete for the same searches, mentions in Google's AI answers and in ChatGPT, and a Lighthouse speed test of the
  homepage and up to two key pages. About $0.29 for a new site; nothing for the same site again inside a week. It
  runs without a Confirm step, under the $2 confirmation limit, the $5 per-audit limit and the $20 per-day limit. The AI mentions need the "AI Optimization"
  subscription on the DataForSEO account; without it those two rows say so and the rest still run.
- **Local business: Google profile on** (appears once search data is on). Looks up the Google Business Profile
  under the brand name on the plan card. Check the brand name and country on the card first.
- **Verify ownership.** See the next section.
- **Other domains of the same brand** (on the plan card, under the brand name and country). Type the brand's other
  sites, separated by commas, for example `other-shop.example, group.example`, without `https://`. A link from the
  audited site to one of them is then not reported as "a link to another site" and Maya does not request it. Saved
  for the site, like the brand name.
- **Links to other sites are now checked:** each one is asked once, politely (that site's robots.txt first, at most 70
  small requests in a Quick audit and 100 in Standard), only a page that is gone (404 or 410) is reported, and
  `--no-external-links` on the command line turns this off.
- **Fast check** and **Links to other sites** (two switches on the plan card). Fast check is off by default: switched
  on, the audit renders 6 pages instead of 20 and checks fewer sitemap addresses (50), llms.txt links (20) and images
  (10), so it finishes sooner; the pages it reads, the page reader and paid data stay the same. Links to other sites is
  on by default; switch it off to send nothing to other sites (except the few sameAs profile links). Changing either
  makes a new plan. If the time limit still runs short, the report says which checks were skipped, and the "Step
  timing" table under "What could not be checked" shows how long each step took.
- **Archived copies if unreadable (free).** Only used when neither Maya's crawler nor Firecrawl could read the
  site: it then reads the newest copies kept by the Wayback Machine and Common Crawl. They are shown apart, each
  with its date, because the live site may have changed since.

The market for the search data is the **country on the plan card**. Type it in any spelling ("Turkey", "Türkiye",
"TR"); changing it makes the plan again, and the card then says "Search data market: Turkey, Turkish." If the
country is empty or one the tool does not know, a plan with search data will not start until you correct it or
tick **Use United States figures** (the panel titles then say "default market"). The ChatGPT panel is always
United States, English; backlinks have no market.

A plan with backlinks or search data also reads the **DataForSEO balance** by itself (a free request). When the
balance is zero, too low for the plan, or the account did not answer, the card says so above **Start**, and Start
asks once whether to **Run without search data** (DataForSEO is then sent nothing; Firecrawl reads the pages as
usual), to **Run anyway** (not offered at a balance of zero) or to **Cancel**.

**Core Web Vitals** (how fast the site felt to real Chrome visitors over the last 28 days) are added to every audit,
free, when this line is in `.env` (a Google API key with the "Chrome UX Report API" enabled; ask the team lead):

```
MAYA_AUDIT_CRUX_API_KEY=your-google-key
```

Without it the result says "Core Web Vitals not available (no API key)". Small sites often have no figures at all:
Google publishes them only for sites with enough visits. The same key may be written as
`MAYA_AUDIT_GOOGLE_API_KEY` (the name the command line's `--pagespeed` uses): either name works for both (DECISIONS
332). The web app does not run PageSpeed Insights lab tests; to see that the key is picked up, the plan's details say
"Core Web Vitals from real Chrome visitors are included", Google's figures appear under "Core Web Vitals (real
visitors)" in the results, and the team report's "Saha verisi" box shows them instead of "Ölçülmedi".

**Which searches are about the business.** The keyword tables are sorted into *branded* (the name itself, or the
name with company words such as "login" or "reviews"), *relevant* (about what the site offers) and *unrelated*
(they only share a word). Top opportunities and quick wins use the first two; the unrelated ones are listed
separately with a note. When the brand name is an ordinary word, like "Maximum", the plan card and the report say
so: most searches for the word are then not about the company, and the "competitors" may be sites about the word.
The sorting is word matching against the brand name and the site's own titles, headings and descriptions. It is
not a judgement of meaning, so look through the unrelated list before discarding it. Setting the **brand name** and
**industry** under Change → About this business makes it more accurate.

If a paid panel says "DataForSEO could not be reached from this computer", it was a connection problem (the app
tries twice): nothing was sent or charged. Run the audit again; the panels that did run are saved and are free.

## A site nothing could read, and proving ownership

When neither Maya's crawler nor Firecrawl could read a site, the results start with a single card: who blocked it,
what that means, and what to do next. The counter reads "Readable pages: 0 (1 blocked request)". New in this
version, the card has two folded sections to hand to whoever runs the site:

- **How to let the audit in.** Copy-paste steps for Cloudflare, Akamai and other firewalls. The same steps are in
  the PDF and the Markdown report. `docs/BOT.md` describes the crawler; its contact address and public page are
  still marked "to be confirmed", so do not send it to a client before the team lead has filled them in.
- **Site ownership.** A token for that site, as a meta tag for the homepage or a DNS TXT record. Once the owner has
  published either, press **Verify ownership** before the next audit. If the token is found, the audit also tests
  what named AI and search crawlers receive (check ACC-4), which it never does on a site that is not verified.
  The DNS record is looked up through Google's public DNS service. On a site that challenges every visitor, use
  the DNS record: the audit cannot read a meta tag on a page it is not shown.

## The report

The PDF now opens with a one-page **executive summary** (top problems, top opportunities, the first five actions),
then a **scorecard** by area, the **action plan as a timeline** (this week, this month, later), **every issue** with
what, where, why, the fix and a short example, who usually does it and how big it is, a table of **every page**
(status, title, H1, words, schema, issues), the **data panels**, **what else we checked**, and a **technical
appendix** listing every source of data and its date. The result page shows the same opportunities, timeline,
scorecard and page table; the last three open when you click them.

The examples are fixed text chosen by the kind of problem: adapt them to the site before sending them on.

**"Unverified check" and the brand name.** A finding marked **Unverified check** (a small label on the result card,
a line in the PDF, "Unverified check:" in the Markdown) comes from a rule that has not yet been tried on enough real
sites: a word list, a threshold or a guess written from made-up pages or from one or two sites. The finding is
reported as it was found, at its usual severity, and the label names the open items in docs/LAUNCH-GATE.md it rests
on. Look at the page yourself before passing such a finding on or acting on it. Separately, type the **brand name**
on the plan card (or save it under Change → About this business): only a name you typed is used for the Google
Business Profile, and without one the keyword tables count brand searches by the name the site gives itself, or not
at all when no name can be found. A name the card suggests from the address is never used until you confirm it.

## Turkish

The sidebar has a **Language** switch: English or Türkçe. It changes the buttons, labels, cards, plan text, the
"why it can matter" notes and the PDF's headings. Finding titles and fix instructions are written by the audit
engine in English and stay in English. **The Turkish text is a draft, to be reviewed by a native speaker**; tell
the person who sent you this folder about any wording that reads wrong.

## If something goes wrong

**"command not found: python3"**, or a version below 3.11. Install Python from python.org (see "What you need"),
then close and reopen Terminal.

**"No such file or directory: .venv/bin/…"**. You are not inside the project folder, or step 3 was skipped. Do
step 2 again, then step 3.

**"Operation not permitted", or the app cannot open its port.** Run the commands in the normal **Terminal** app
that comes with macOS (Applications → Utilities → Terminal). Terminals built into other tools (coding assistants,
editors, remote sessions) can be restricted and may refuse to let the app start. Also avoid keeping the folder in
iCloud Drive or on a network drive.

**"Port 8770 is already in use"**. Maya Audit is probably already running in another Terminal window: use that
one, or stop it there with Ctrl+C. Otherwise start it on another port and open that address instead:

```sh
.venv/bin/python -m maya_audit_web --demo --port 8771
```

**"Maya Audit is already running on this computer"**. Same cause: find the other Terminal window and use it or
stop it.

**The page says "The local Maya Audit server is not answering"**. The Terminal window was closed or the app was
stopped. Start it again (step 6 or 7) and reload the page.

**Chromium will not start, or PDF says it is unavailable.** Run step 5 again. If it still fails, the app remains
usable: reports note that JavaScript rendering was not available, and instead of a PDF you can open the
**Printable page** link and use your browser's Print → Save as PDF.

**"Network problem on this computer (DNS lookup failed)".** The audit did not start: your computer could not look
up the site or any other public name. Nothing was requested and nothing was spent. Turn a VPN or iCloud Private Relay
off (or on, if your network needs it), check the Wi-Fi, and start the audit again. This message is about your
computer, not about the website.

**A report says "not checked (network problem on this computer)" or "no answer reached this computer".** One of
Maya's own requests got no answer part-way through. It is not counted against the website. If Firecrawl is on it
read the pages anyway; otherwise run the audit again.

**"The address … does not exist".** A public DNS service says there is no such website name. Check the spelling.

**The install step fails with a network or certificate error.** Check your connection or VPN and run the same
command again; it continues where it stopped.

**Anything else.** Copy the last few lines Terminal printed and send them to whoever gave you the zip. Do not
include your `.env` file.

## For the curious: checking the installation

The project includes its own tests, which run entirely on your Mac against made-up websites. They need a few extra
tools and about six minutes:

```sh
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest -q
```

Three tests are expected to be skipped in an unzipped folder: one needs example reports that are not included, and
two ask Git which files it ignores, which an unzipped folder cannot answer. Everything else should pass. Use the first command exactly as written: it installs the test tools. Without it (for
example with only `pytest` added by hand) the seven tests that build their own HTTPS certificates are skipped too, with
a line saying which tool is missing.

## Preview 21: current working snapshot

Application 0.2.5, schema 1.16. RELEASE-SNAPSHOT.json identifies the base commit and each included file.
This ZIP includes reviewed working-tree features, not just the last Git commit. Private audit history, provider
responses and the owner's revised analyses are intentionally absent. Existing installations keep their own
project folder and data; do not replace a running installation with this archive.

The normal PDF is a concise report with a hard 50-page limit. An oversized report returns an explicit error;
use the full technical printable view and companion JSON/evidence downloads instead. Turkish client reports
are a separate editable draft/validation/export flow; their full appendix is not subject to the concise limit
and may be long. Generating or approving a draft does not verify its findings. No runtime language model is
required. No provider requests are made merely by exporting saved results.

Saved copied-evidence analyses appear under **Revised analyses / Yeniden işlenen analizler** when a valid local
registry is present. A clean recipient installation has no private registered analyses. Source observations,
processing time and export time are different events. Historical reports are never automatically rewritten.

The profile's **About this business** editor supports confirmed brand aliases and related organizations.
Confirm relationships only from evidence. Uncertain image roles, missing landing-page content, one-off empty
responses and contradictory requests still require manual review. Native Windows locking (LG-101), live-provider
compatibility and every possible PDF layout are not certified by this offline Mac release check.

## Preview 22 — compact client delivery

Application 0.2.6. The normal Client report PDF/preview is compact (hard maximum 50 PDF pages).
Every finding retains its ID, source qualification, action and verification instructions. Complete
raw evidence, full URL lists and page text are separate **Complete evidence JSON (companion)**
and **Exhaustive evidence HTML (long draft)** downloads in the existing client editor. Send the
companion file with the PDF; localhost hyperlinks work only while the recipient has that app/data.
Previous statements above about an unlimited default client appendix describe preview 21 only.
The exhaustive export remains available explicitly; ordinary client exports never select it silently.
Editorial approval remains required for final exports and never establishes live verification.
Private revised analyses are not bundled. Existing users continue using their original project/history.


## Preview 23 — verified working-source checkpoint

Application 0.2.6 / schema 1.16. This is a testable preview, not production or client-delivery approval.
RELEASE-SNAPSHOT.json records the base commit, included working-tree files and exact SHA-256 digests.
The completed accuracy improvements distinguish image URL references from observed response formats,
empty/absent H1 evidence, content/probe coverage, host outcomes and conditional owner-intent actions.
No live audit, paid-provider compatibility or general accuracy percentage is certified by offline tests.

Private audits, r11 and other revised analyses, reports, provider responses and credentials are not bundled.
They stay in the owner's existing installation, which continues using its original folder on port 8770.
A fresh extraction starts without that private history. Do not replace a running installation with this ZIP.
The normal technical/client PDF limit is 50 pages; full evidence is available separately.
Drafts remain unapproved until validation and editorial review pass. The owner's current draft still needs
editorial review and sitemap check-code wording review; no approval gate was bypassed for this checkpoint.
See docs/RELEASE-team-preview-23.md and CHECKPOINT-VERIFICATION.md.

For a first offline test when another app occupies 8770, use the supported demo command on a free test port:
`.venv/bin/python -m maya_audit_web --demo --port 8791`. Do not stop someone else's server.
Use a fresh MAYA_AUDIT_HOME and point MAYA_AUDIT_ENV_FILE at a nonexistent file for isolated verification.
Native Windows locking LG-101, live-provider behavior and every possible PDF layout remain unverified.
