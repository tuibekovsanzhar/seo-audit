# Local web API, version 1

All routes are under `/api/v1` on `http://127.0.0.1:<port>` (default port 8770). The machine-readable description
is `GET /api/v1/openapi.json`. The API has its own version (`api_version: "1"`); the saved report has another
(`schema_version`, see `docs/REPORT-SCHEMA.md`). Neither redefines the other.

This is a single-user API for one computer. It is not built to be exposed to a network; see
`docs/DASHBOARD-INTEGRATION.md` for what a hosted version needs.

Start it: `.venv/bin/python -m maya_audit_web` (add `--demo` for made-up data).

## Rules for every request

| Rule | Detail |
|---|---|
| Host | `Host` must be `127.0.0.1:<port>` or `localhost:<port>`; otherwise 403 `host_not_allowed`. |
| Other sites | An `Origin` that is not this server's, or `Sec-Fetch-Site` other than `same-origin` / `none`: 403 `cross_site_request`. Only GET `/` top-level `navigate`/`document` navigation is allowed to open the app from a link; foreign Origins, frames, assets and all API routes remain refused. No CORS header is ever sent. |
| Session | Everything except `GET /health` needs the `maya_session` cookie, which the server sets (HttpOnly, SameSite=Strict) when `GET /` is opened. Without it: 401 `not_authenticated`. This covers reads, the event stream and evidence. |
| Changes | `POST`, `PUT`, `DELETE` also need the header `X-Maya-Token` (from `GET /session`). `POST` and `PUT` need `Content-Type: application/json`, a `Content-Length`, and a body of at most 64 KiB. Other methods: 405. |
| No Origin | A local program (curl, a script) sends no `Origin`. It is held to the same rules: fetch `/` for the cookie, `/session` for the token. Nothing is trusted for being local. |
| Secrets | No credential, cookie value or token ever appears in an address. |
| Ids | 32 lower-case hexadecimal characters. |

A script can use the API like this (demo mode shown):

```sh
curl -s -c jar http://127.0.0.1:8770/ >/dev/null
TOKEN=$(curl -s -b jar http://127.0.0.1:8770/api/v1/session | python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])')
curl -s -b jar -H "X-Maya-Token: $TOKEN" -H 'Content-Type: application/json' \
     -d '{"url": "demo-shop.localhost", "mode": "quick"}' http://127.0.0.1:8770/api/v1/plans
```

## Errors

Every error has one shape, with a stable `code`, a sentence for a person, and safe details. No raw exception text
and no file path is returned.

```json
{"error": {"code": "confirmation_required", "message": "This plan may cost up to $0.0516. Confirm that amount first.",
           "details": {"total_usd": 0.051636}}}
```

| Status | Codes |
|---|---|
| 401 | `not_authenticated` |
| 402 | `confirmation_required` |
| 403 | `host_not_allowed`, `cross_site_request`, `bad_action_token` |
| 404 | `not_found`, `audit_not_found`, `plan_not_found`, `finding_not_found`, `evidence_not_found`, `download_not_found`, `project_not_found`, `no_previous_audit` |
| 405, 411, 413, 415 | `method_not_allowed`, `length_required`, `request_too_large`, `json_required` |
| 409 | `plan_changed`, `nothing_to_confirm`, `daily_limit_reached`, `credentials_not_configured`, `ledger_unreadable`, `no_price`, `audit_not_running`, `audit_not_resumable`, `audit_running`, `report_not_ready`, `report_version_unsupported`, `report_unreadable`, `not_comparable` |
| 410 | `plan_expired` |
| 422 | `invalid_request` (details list the fields), `invalid_url`, `private_address`, `invalid_key_pages`, `invalid_brand_family_domains`, `amount_mismatch`, `demo_sites_only`, `storage_not_accepted`, `owner_approval_required`, `firecrawl_options`, `unknown_language` |
| 429 | `queue_full` |
| 500 | `internal_error` (details hold the error's class name only) |
| 503 | `pdf_unavailable` (details hold `print_url`) |

## Routes

| Route | What it does |
|---|---|
| `GET /health` | `{"status": "ok", "api_version": "1"}`. No cookie needed. Nothing else is revealed. |
| `GET /audits/{id}/practical` | The practical report as data (see Results). |
| `GET /session` | `{api_version, token, language, demo}`. |
| `GET /strings?language=en` | Every sentence the page shows. Without `language`, the chosen one. A sentence not translated yet comes back in English. |
| `GET /settings` | Safe public settings: modes, limits, demo sites, whether credentials are set (yes or no, never a value). |
| `GET /budget` | Today's local allowance from the ledger, and the last known provider balance. Asks no provider. |
| `POST /budget/provider-balance` | Asks DataForSEO's free account endpoint for the balance, now, because a person pressed the button. |
| `POST /plans` | Validates the input and makes a plan. Contacts no site. Sends no paid request. With backlinks or search data ticked, credentials set and not in demo mode, it asks DataForSEO's free account endpoint for the balance when the last answer is older than ten minutes (decision 180). 201. |
| `GET /plans/{plan_id}` | The plan as it was made. |
| `POST /plans/{plan_id}/confirm` | Records approval of a paid plan's exact maximum (dollars, Firecrawl credits, or both). Starts nothing. |
| `POST /audits/{id}/firecrawl/read` | On a finished audit the site blocked: read its content through Firecrawl now (switch it on afterwards, accept storage after a refusal, or retry with a stronger proxy). |
| `POST /audits/{id}/firecrawl/without-zero-data-retention` | The older form of the storage decision; same rules as `/firecrawl/read`. |
| `PUT /session/language` | `{"language": "en" \| "tr"}`: sets the `maya_language` cookie. `GET /session` then reports it, with `languages` (`id`, `label`, `note`). |
| `POST /audits` | Starts the audit a plan describes: 201. The same plan again: 200 with the same audit. |
| `GET /audits?q=&domain=&status=&limit=&offset=` | History, newest first, with `total`. |
| `GET /audits/{id}` | Lifecycle, outcome, steps, counters, settings. |
| `DELETE /audits/{id}` | Removes the audit (one transaction) and its saved files: `{deleted}`, plus `files_left` and `note` when a file another program holds open could not be removed. 409 while it runs. |
| `GET /audits/{id}/events` | Progress as server-sent events (below). |
| `POST /audits/{id}/stop` | Asks for a cooperative stop. |
| `POST /audits/{id}/resume-plan` | What a resume would do and whether it needs a new approval. Requests nothing. |
| `POST /audits/{id}/resume` | Continues a stopped or interrupted audit from its saved crawl. |
| `GET /audits/{id}/result` | The saved JSON report itself: the authoritative record. |
| `GET /audits/{id}/summary` | The results card, built from the report. |
| `GET /audits/{id}/action-plan?role=` | Fix now, fix next, improve later; optionally for `developer`, `content` or `seo`. |
| `GET /audits/{id}/findings?severity=&check_id=&area=&owner=&q=&limit=&offset=` | Filters and pages. Changes no finding. |
| `GET /audits/{id}/findings/{finding_id}/pages?q=&limit=&offset=` | Every page a finding affects. |
| `GET /audits/{id}/evidence/{evidence_id}` | A finding's evidence (`evidence_id` = the finding's id), or one saved page record (`page-<n>`). |
| `GET /audits/{id}/downloads/{format}?full=&lang=` | `pdf`, `markdown`, `json`, `evidence` (a zip; its `index.json` names the evidence folder, never a path on this computer). The PDF is the concise report unless `full=true`. |
| `POST /plans` mode `smart` | Akıllı ~150 (DECISIONS 327): a planned sample of 150 pages covering every page type of the business type; with Firecrawl on, it reads only where needed unless `firecrawl_full_read` is true ("Tam okuma (Firecrawl her sayfa)"). |
| `GET /audits/{id}/downloads/sector` | The team's sector audit workbook filled from the audit (DECISIONS 324): five sheets in the team's format, formulas and dropdowns kept, Turkish. Gated like the appendix (`-draft` in the name when blocked). |
| `POST /audits/{id}/review/p0` | `{finding_id, action: "set" \| "removed", by, note?}`: a person sets a card to P0 or takes its automatic P0 off (DECISIONS 324); written to the audit's review.json under `p0`. `GET /audits/{id}/review` lists every card's level under `p0`. |
| `DELETE /audits/{id}/review/p0/{finding_id}` | Undo that mark (kept under `replaced`). |
| `GET /audits/{id}/print?full=&lang=` | The PDF's content as a printable HTML page: the concise report by default, the full technical report with `full=true`. Both are written in the audit's language (the one it was started in); `lang=en` or `lang=tr` asks for another. |
| `GET /audits/{id}/comparison?with=` | Against the previous audit of the same site, or the one named. |
| `GET /audits/{id}/conversation` | Saved messages and cards. |
| `POST /audits/{id}/messages` | A supported question; returns the question and the answer. |
| `GET`, `PUT /projects/{project_id}/profile` | Confirmed business context and important pages. `project_id` is the site's host without `www.`. |

## Plans and confirmation

`POST /plans` body: `{"url": "example.com", "mode": "quick" | "standard", "backlinks": false, "key_pages": ["/pricing"]}`.
Unknown fields are refused. A plan is never changed: other options mean another plan.

A plan holds:

| Field | Meaning |
|---|---|
| `id`, `fingerprint`, `created_at`, `expires_at`, `expired` | A plan lives 30 minutes. The fingerprint covers the target, the settings and every priced request with its price. |
| `target` | `url` (normalised; `https://` unless typed otherwise), `host`, `domain`, `http_fallback` (the `http://` address tried if `https://` does not answer at all, or null), `note`. |
| `business` | `brand_name`, `country`, `brand_confirmed`, `country_confirmed`, `suggested_from`, `note`: what was sent with the plan (`brand_name`, `country`), else the saved values for this site, else suggestions to edit. `suggested_from` names where a suggested country comes from ("the last audit's homepage language (tr)", "the address ending (.tr)"), else null. Save them with `PUT /projects/{id}/profile`. |
| `cannot_start` | null, or `{code, message}` when the plan's own content stops it: `market_unknown` (search data with a country that is missing or not recognised, and no "Use United States figures" tick). |
| `balance_warning` | null, or `{level, message, balance_usd, total_usd, choices}` when the DataForSEO balance may not cover the plan: `level` is `zero`, `low` or `unknown`; `choices` are `{id, label}` with `id` = `without_search_data` or `run_anyway` (not offered at zero). Read from the stored balance each time the plan is read. |
| `mode`, `page_cap`, `key_pages`, `rendering`, `time_limit_minutes`, `request_delay_s` | The settings. |
| `duration` | `{known, up_to_minutes, label}`: a rough upper estimate, labelled as one. The number of pages is not known before the audit runs. It includes (delay + 0.3) s for each light request the sitemap check may send (200 in Quick, 1,000 in Standard, 0 in Single page; DECISIONS 206), and `time_limit_minutes` grows with it. |
| `included`, `optional`, `unavailable`, `limitations` | Sentences: what is checked, what can be added, what this app cannot check, what to bear in mind. |
| `paid` | Below. Present whether or not backlinks were asked for, so the cost is visible before choosing. |
| `needs_confirmation`, `confirmation`, `can_start`, `audit_id` | Where the plan stands. |

`paid`: `requested`, `available`, `calls` (each with `check_id`, `purpose`, `endpoint`, `target`, `state` = `paid` \|
`cached` \| `not_sent` \| `refused`, `estimate_usd`, `cache_age_s`), `total_usd`, `needs_confirmation`, `blocked`
(null or `{code, message}`), `by_service` (one row per DataForSEO API the plan names, in the plan's order:
`service` = `Backlinks` \| `Labs` \| `AI Optimization` \| `OnPage (Lighthouse)` \| `Business Data`, `requests` = how
many would be paid for, `usd` = their estimate; a service whose answers are all saved has 0 and 0), `serp_api_calls`
(always 0: Maya never calls the SERP API, and the client refuses it), `limits` (`confirm_usd`, `audit_cap_usd`,
`daily_usd`), `over_audit_cap` (null, or `{cap_usd, total_usd, left_out, message}` when the total is above the limit
for one audit: a warning, not a refusal; `left_out` holds the check ids that would not be requested), `budget` (`daily_cap_usd`, `day`, `day_is`, `resets_at`, `spent_today_usd`,
`remaining_today_usd`), `provider_balance` (`{known: false, message}` until it has been read: by the button, or by a
plan with paid data).

The flow, and what is enforced:

1. `POST /plans` with `"backlinks": true`. If `paid.needs_confirmation`, the plan cannot start yet.
2. `POST /plans/{id}/confirm` with `{"approved_max_usd": <paid.total_usd>}`. The amount must equal the plan's total
   exactly (`amount_mismatch` otherwise). `paid.needs_confirmation` is true only when the plan's total is above the
   per-audit confirmation limit (`limits.confirm_usd`, $2 unless configured); at or below it the plan can start at once, `confirm` answers 409 `nothing_to_confirm`,
   and the audit is given exactly the plan's total as its ceiling. Confirming twice records it once. Confirming starts nothing.
3. `POST /audits` with `{"plan_id": ...}`. The plan is priced again first. If anything the fingerprint covers has
   moved (a price, or saved data that is no longer saved) the answer is 409 `plan_changed` and a new plan is needed;
   a zero-cost plan never becomes a paid one silently. An expired plan is 410. A second identical request returns
   the same audit, so a double click cannot buy the same data twice.
4. The paid requests are made once, after the page reading and checks have finished. A stopped audit pays for
   nothing. The engine's client is given exactly the plan's total (confirmed when above the threshold) as its ceiling, the limit for one audit ($5, or `MAYA_AUDIT_DATAFORSEO_AUDIT_CAP_USD`) and the daily limit ($20, or `MAYA_AUDIT_DATAFORSEO_DAILY_USD`). Every request is recorded in the ledger.
   The limit for one audit holds whatever was confirmed and across a resume (the audit keeps its id): the request that
   would pass it is not sent, nor any after it. The report's `dataforseo.stopped.code` is then `audit_cap_reached`,
   each check left out has `refusal.code` `audit_cap_reached`, and the audit itself finishes.

### Firecrawl in a plan

`POST /plans` takes `firecrawl` (true, false, or left out), `firecrawl_max_pages`, `firecrawl_proxy`,
`firecrawl_owner_approved` and `firecrawl_render`. Left out, Firecrawl is on when a key is set on the computer
(and `MAYA_AUDIT_FIRECRAWL` is not `off`): it is the page reader of every audit. `false` switches it off for that
plan. `firecrawl_max_pages` left out is the plan's own page cap (Quick 50, Standard 500).

The plan's `firecrawl` object holds `requested`, `main_reader`, `available`, `options` (with `read_always`),
`max_pages`, `max_credits`, `credits_per_page`, `max_usd`, `cost_line`, `lines`, `blocked` and `needs_confirmation`.
With the basic proxy `needs_confirmation` is false: the plan can start at once, `POST /plans/{id}/confirm` answers
409 `nothing_to_confirm`, and the credits are recorded in the ledger under the daily guard. A stronger proxy needs
`firecrawl_owner_approved` and then the exact `approved_max_credits`, as before. A resume of an audit that has not
used Firecrawl yet needs no `approved_max_credits` for the basic proxy either.

When Firecrawl read the pages, `GET /audits/{id}/summary` has `blocked: null` even if the site challenged Maya's
own crawler; `pages_stat` is `{"label": "Pages read", "detail": "via Firecrawl", "line": "Pages read: 6 (via
Firecrawl)", "reader": true}`; the outcome is `COMPLETED` (or `INCOMPLETE` when the reading stopped early); ACC-9 is
an Info row; `firecrawl.main_reader` is true; and the coverage list has one row "Needs Maya’s own direct requests".
`blocked` and `firecrawl_offer` appear only when Firecrawl could not read the site either.

### Firecrawl from the result card

The summary's `firecrawl_offer` is null, or what a finished, blocked audit may still do: `kind` (`not_requested`,
`zero_data_retention`, `also_blocked`, or `stronger_blocked` when nothing more is offered), `title`, `lines`,
`available` (a key is set), `blocked`, `consent` (`storage` and `owner`: which ticks are needed, with their labels),
`choices` (each `proxy`, `max_credits`, `max_usd`, `cost_line` and the button's `label`), and `offline` (true when
the audit's own saved result will be reused, so the website is asked for nothing more).

`POST /audits/{id}/firecrawl/read` takes `{"proxy", "owner_approved_bypass", "accept_content_may_be_stored",
"approved_max_credits"}`. `proxy` must be one of the offer's choices (`firecrawl_options`, 422); a stronger proxy
needs `owner_approved_bypass` (`owner_approval_required`, 422); when zero data retention will not be applied,
`accept_content_may_be_stored` must be true (`storage_not_accepted`, 422); `approved_max_credits` must equal the
choice's maximum exactly (`confirmation_required`, 402). With no offer: `firecrawl_not_offered` (409). While it
runs, the audit's `firecrawl.continuing` is true and its results stay readable. The summary's `firecrawl` has
`also_blocked`, `attempts` (one row per use: `at`, `proxy`, `owner_approved_bypass`, `zero_data_retention`,
`credits`, `pages_read`, `result`) and `spent_line`.

Also in the summary: `pages_stat` (`value`, `label`, `detail`, `blocked`, `line` on a blocked audit, and `also`),
`block_pointer`, `technical` (`title`, `note`), `blocked.blocked_requests`, `blocked.sections`, and
`in_block_card` on the rows of `top`.

In the summary and in `/findings`, an item's `source` is null, or `{reader: "firecrawl", label, notice}` when the
finding rests on what Firecrawl read.

The four messages a person can meet, and their codes:

| Situation | Code | Says |
|---|---|---|
| Local allowance used up | `daily_limit_reached` | "Daily spending limit reached…" It is Maya's own limit, counted per UTC day in the ledger, and resets at midnight UTC. It never suggests buying anything. |
| The provider says the account cannot pay | `provider_credits_insufficient` | "DataForSEO account credits are insufficient…" Only ever from a provider response. |
| The balance has not been read | (in `provider_balance`) | "Account balance is unknown: it has not been checked." |
| The balance is zero, low or did not answer, before a run | `balance_decision_required` (409 from `POST /audits`), and `balance_warning` on the plan | "DataForSEO balance $0.00 — search data will be empty." / "DataForSEO balance $X is below this plan's maximum of $Y: some panels may come back empty." / "DataForSEO balance unknown (the account did not answer); this plan's maximum is $Y." |
| No credentials on this computer | `credentials_not_configured` | "Credentials are not configured…" |

Other refusal codes on a backlink check: `provider_subscription_missing`, `confirmation_required`, `possibly_billed`
(no usable answer; the estimate stays counted and the call is not sent again), `stopped`, `provider_error`,
`not_requested_no_credit` (an earlier request of this audit was refused for no credit, so this one was not sent),
`not_requested_balance` (the audit was started without paid data because of the balance) and `audit_cap_reached`
(this audit reached its own DataForSEO limit, so this request was not sent).

### The market and the balance (team-preview-11, decisions 179 and 180)

- `POST /plans` also takes `brand_name` and `country` (what is typed on the plan card; they win over the saved
  profile) and `market_default_accepted` (the "Use United States figures" tick; kept only with search data and a
  country that is not recognised). The country is matched without regard to case, Turkish letters or punctuation:
  "Turkey", "Türkiye", "TÜRKİYE", "TR" and "Türkiye (TR)" are one country.
- A plan's `search_data` holds `market`, `market_known`, `market_code`, `market_language`,
  `market_default_accepted`, `market_unknown`, `market_block` (null or `{code: "market_unknown", message}`),
  `market_default_label` and `markets`: the lines the card shows, each `{kind, text}` with `kind` = `search`
  ("Search data market: Turkey, Turkish."), `chatgpt` ("ChatGPT mentions: United States, English only (the one
  market DataForSEO offers)."), `backlinks` ("Backlinks: no market (worldwide).") or `suggestion` ("Suggested from
  the address ending (.tr): Turkey. Confirm or change it."). `market_warning` is kept for older pages.
- The fingerprint of a plan with paid data covers the market (location, language, brand, the tick).
- `POST /audits` and `POST /plans/{id}/confirm` answer 409 `plan_changed` (details `{changed: "business"}`) when
  the country or brand saved for the site differs from the plan's, and 409 `market_unknown` for a plan that
  cannot start for that reason.
- `POST /audits` takes `balance_choice`: `without_search_data` or `run_anyway`. With a `balance_warning` and no
  choice it answers 409 `balance_decision_required` (details: `level`, `choices`, `balance_usd`, `total_usd`); a
  choice that is not offered is 422 `balance_choice_not_offered`. `without_search_data` starts the audit with
  `paid.state = "skipped"` (`paid.skipped: true`): DataForSEO is sent nothing, the "backlinks" step of the
  timeline is `skipped` with its reason, and the report's `dataforseo` section says why.
- The summary's `backlinks` gains `note`, `note_shown` (the same sentence in the reader's language) and `stopped`
  (`{code, after, not_requested}`) when requests were left out because of the balance.

### Search data, archives and ownership in a plan (team-preview-5)

`POST /plans` also takes `search_data`, `local_business`, `archives` and `verify_ownership` (all false by default).

- `search_data` adds the DataForSEO search data calls (DFS-3 to DFS-11; DFS-12 with `local_business`) to
  `paid.calls`, each with `purpose`, `state` and `estimate_usd`, and to `paid.total_usd`. The one confirmation covers
  backlinks and search data together, to the exact dollar. The plan's `paid_options` records what was asked, with the
  `brand` and `country` used; `search_data` holds `requested`, `market`, `market_known` and a sentence about Core
  Web Vitals. With neither `backlinks` nor `search_data`, `paid.calls` still lists the backlink calls so their
  price is known before it is chosen (`paid.requested` is false).
- `archives` is recorded as `archives: true`. Archived copies are read only if neither Maya's crawler nor Firecrawl
  could read the site.
- `ownership` is always present: `domain`, `token`, `meta_tag`, `txt_record`, `instructions`, and `requested`
  (true with `verify_ownership`). The token is the same for a site on one computer.

Each of these changes the plan's fingerprint.

## Audits

`state` is the job's lifecycle. `outcome` is what the audit concluded, in the engine's own words. One does not imply
the other: a job can be `finished` with an outcome of `INCOMPLETE` or `DEGRADED`.

| `state` | Meaning |
|---|---|
| `queued` | Waiting. One audit runs at a time; up to 5 more wait. |
| `running`, `stopping` | In progress; a stop has been asked for. |
| `stopped` | Stopped on request. A partial report exists. Resumable. |
| `interrupted` | The app closed while it ran or waited. Nothing restarts by itself. Resumable. |
| `finished` | The engine produced its report. Read `outcome`. |
| `failed` | No audit was produced; `error` has a code and a sentence. |

`outcome`: `{code: COMPLETED | INCOMPLETE | DEGRADED, label, reason, crawl_stop}`. `crawl_stop` is the engine's stop
reason: `exhausted`, `page_cap`, `time_limit`, `rate_limit`, `error`, `robots_disallowed`, `stopped`.

Also on an audit: `timeline` (seven steps: access, sitemap, crawling, rendering, checks, backlinks, report; each
`pending`, `active`, `done`, `skipped`, `unavailable` or `not_reached`, with a `reason` when skipped or unavailable),
`counters` (`pages_checked`, `page_cap`, `redirects`, `other_fetches`, `requests_sent`, `discovered`), `elapsed_s`,
`eta` (`kind`: `calculating`, `estimate` with `max_seconds`, `waiting`, `unknown`, `none`), `sessions`, `settings`,
`paid` (`requested`, `state`: `none`, `pending`, `attempted`, `done`), `has_report`, `last_event_id`.

`pages_checked` counts what the engine's page cap counts. Redirect hops and repeats are in `other_fetches` and
`redirects`, beside it. "38 of up to 50" is about the limit, not the size of the site.

### Events

`GET /audits/{id}/events` is a server-sent event stream. Each event has an `id` (growing), an `event` name and JSON
`data` with `v` (the event version, 1) and `ts`.

| Event | Data |
|---|---|
| `snapshot` | `{audit}`: the audit as it is now. Always the first event. |
| `state` | `{state}` and sometimes `session`, `resumed`, `note`. |
| `step` | `{step, phase}`: a step of the timeline became active. `phase` is the engine's own phase name. |
| `progress` | `{pages_checked, page_cap, other_fetches, requests_sent, discovered, url, elapsed_s}`. At most four a second. |
| `log` | `{message}`: a short safe line. |
| `done` | `{state, outcome, reason, pages_checked}` or `{state: "failed", error_code, message}`. |
| `end` | `{audit}`: the stream closes after this. |

A comment line (`: heartbeat`) is sent every 10 seconds of silence. After a disconnect, send `Last-Event-ID`: the
stream answers with a fresh `snapshot` and then only the events after that id. Events are bounded: no page body
and no report travels in them, each is under 2 KB, and at most 1,500 are kept per audit (older counter updates go
first).

### Stop and resume

- Stop lets the request in progress finish and starts nothing new. The pages read are kept and a report of them is
  written. If a paid request was already sent it may still be charged; its reservation is kept.
- After a restart, unfinished audits are `interrupted`. Nothing is resumed or requested until a person chooses Resume.
- `POST /resume-plan` reports `pages_saved`, `pages_left`, what is kept, what runs again (robots.txt, the sitemap,
  and the checks after the page reading), and `paid`. If the paid data was not yet requested and would cost
  anything, `paid.needs_confirmation` is true and `POST /resume` needs `{"approved_max_usd": <paid.total_usd>}`
  again: an earlier approval does not carry over a stop.
- Resume uses the saved site and settings. The engine refuses a saved crawl that does not match (`resume_mismatch`).
  The page limit covers all sittings together.
- If the app died while a paid request was in flight (`paid.state: "attempted"`), it is not sent again; the report
  says the figures are unavailable and why.

## Results

`GET /summary` is built from the saved report by `maya_audit_web/summary.py`. It arranges what the report decided.

| Field | Meaning |
|---|---|
| `outcome` | `code`, `label`, `reason`, `complete`, `resumable`, `stop_reason`, `note`. |
| `counts` | `pages_checked`, `redirects`, `page_cap`, `discovered`, `not_fetched`, `problems` (S1 to S4), `notes` (Info), `by_severity`, `needs_review`, `not_checked`, `findings_total`. Site findings only. |
| `rendering` | `mode`, `available`, `pages_rendered`, `reason`, `label`. |
| `first_action`, `first_action_withheld`, `top`, `more_findings` | The first problem and the first five findings in the engine's priority order. With fewer than three pages read, `first_action` is null and `first_action_withheld` says why. |
| `blocked` | Null, or who blocked the audit: `who`, `name`, `kind`, `blocked_by`, `pages_read`, `pages_requested`, `headline`, `lines`, `next_steps`. |
| `redirected` | Null, or `{from, to, to_host, message, offer}` when the start address redirects to another site. |
| `pages_read` | Pages whose content could be read (answered, not a redirect, not blocked). |
| `coverage` | `read_only_note` (one sentence when not every page found was read), `gaps` (each `part`, `reason`, `checks`, `checks_label`, `count`, `whole_check`, and `blocked: true` on the single row that stands for everything a block prevented), `not_fetched`, `time_limit_cuts`, `sessions`, `resumed_note`, `sampled_note`. |
| `gates`, `areas`, `review` | The integrity gates, checks by area, and items for a person to look at. |
| `answers` | The ANS panel, apart, with `assessed` and a `note` saying what it is not. Never added into `counts`. |
| `backlinks` | Null when not asked for. Otherwise `available`, `checks` (each with `summary`, `data`, `refusal`), `cost_usd`, `calls`, `spent_line`. Unavailable is said as unavailable, never as zero. |
| `brand` | `{name, confirmed, label, country}`: the name confirmed for this site (typed or saved), else the report's own `brand` (the site's own name, labelled `result.brand.from_site` with where it was read; or the address split into the site's words), else the host; anything not confirmed carries a label saying where it came from (DECISIONS 201). |
| `method` | Scope, dates, limit, pace, rendering, optional sources, how the page reading ended. |
| `downloads`, `print_url`, `has_previous`, `follow_ups`, `suggested_key_pages` | |

A finding row (`top`, `findings`, `action-plan`): `id`, `check_id`, `area`, `title`, `severity`, `severity_label`,
`severity_meaning`, `confidence`, `confidence_label`, `rationale`, `affects`, `pages_total`, `sample_pages`, `what`,
`why`, `fix`, `expected`, `notes`, `engines`, `requires_fix` (false for Info), and `estimates` (`owner`, `effort`,
with a `label` saying they are estimates). `why`, `owner` and `effort` come from `maya_audit_web/catalog.py`;
everything else is the report's. Since 2026-10-12 a finding row and a row of `review` also carry `details`: the values
behind the title, one sentence each in the reader's language, read from the finding's own evidence
(`maya_audit.report.detail_lines`): for an STR-4 price "/pricing: Markup: 89 USD / Shown: “$99”" (or what the page
shows and why it could not be relied on), for STR-5 each name of the brand with its sources and page counts. Empty for
any other finding. A finding row also has `names_line` (the brand's names in one line, or null), which the "Whole
site" row of "Problems by page" prints after the finding's title; a practical-report issue has the same `details`.
Since 2026-10-14 a finding row (and a practical-report issue) also carries `unverified`: null, or `{label, note, items}`
for a finding of a rule not yet validated on real sites (`launch_gated` in the report; `maya_audit.launch_gate`,
DECISIONS 203): `label` is the string `result.unverified.label` ("Unverified check"), `note` the string
`result.unverified.note` with the launch-gate items ("This check has not yet been validated on real sites (LG-16,
LG-23). Confirm the finding by hand before acting on it."), `items` the item numbers (or the bot registry's reasons,
for an ACC finding). The card shows it as a chip and its sentence; the printed report as a line under the title.

### Status, coverage and timing (report schema 1.6)

- `GET /audits/{id}/summary` has `status`: `title`, `rows` (three: `direct_access`, `content_coverage`,
  `vendor_crawler_evidence`, each with `label`, `state`, `state_label`, `note`), `summary`, `coverage`, `cache_note`,
  `timing` and `duration_line`. It is null for a report made before schema 1.6; nothing is reconstructed.
  `spend` has `dataforseo` and `firecrawl` (credits, estimated maximum, possibly billed and cached requests; dollars
  for Firecrawl only when a price per credit is configured, else `usd_known: false`).
- The audit's `outcome` is `INCOMPLETE` when a reader left anything unread. `COMPLETED` after a direct challenge
  reads "We read N page(s) through Firecrawl … Genuine AI-crawler access was not measured."
- Progress events during the reader step carry `step: "firecrawl"` with `attempted`, `read`, `failed`, `from_cache`
  and `page_cap`. The estimate of time left is given only while Maya's own crawl runs; other steps say it is unknown.
- A paid check may have `status: "partial"` (`data.missing_measurements` names what the answer did not hold); the
  panel is then `partly_assessed`. New refusal codes: `unsupported_request`, `provider_unreachable`.
- A plan's `search_data.market_warning` is a sentence when the country is not one the tool can ask DataForSEO about.
  Since team-preview-11 such a plan also cannot start until the country is recognised or United States figures are
  accepted (see "The market and the balance").
- When the audit's time limit passes before the reader or the paid step starts, nothing is sent and the approval is
  kept: `firecrawl.state` stays `pending` and `paid.state` stays `pending`.

### Changes in team-preview-6

- `backlinks.checks[].data` for DFS-4 and DFS-5: `table` now holds only branded and relevant keywords and ends with a
  `Relevance` column; `unrelated` (`title`, `note`, `columns`, `rows`) holds the rest; `relevance` has the three counts,
  the `method` and `common_word_brand`. DFS-6: the audited domain is removed (`own_domain_removed`), and
  `possibly_generic_overlap` is true when the shared keywords are mostly unrelated searches. The report's
  `dataforseo.relevance` has `brand_words`, `common_word_brand` and `warning`.
- A plan's `search_data.brand_warning` is a sentence when the brand name is an ordinary word (also in `limitations`), else null.
- A paid check that could not reach DataForSEO has `refusal.code` `provider_unreachable`. Nothing was sent or charged.
- STR-1 may report titles that share their first 50 characters; STR-19 recognises a link to nowhere after a reader made
  its address absolute; STR-23 reports a careers page that describes several openings inline without JobPosting data.
- The default daily DataForSEO limit is $20 (`budget.daily_cap_usd`; it was $100 until decision 192).

### Changes in team-preview-14 (DataForSEO cost, decisions 192 and 193)

- A plan's `paid` has four new fields: `by_service`, `serp_api_calls` (0), `limits` and `over_audit_cap`.
- `paid.needs_confirmation` is true above $2 (it was $10). `POST /plans/{id}/confirm` and `POST /resume` accept an
  `approved_max_usd` up to 10000 (it was 2, which no plan needing a confirmation could pass); it must still equal the
  plan's total exactly.
- A new refusal code on a paid check, `audit_cap_reached`, and the same value in `backlinks.stopped.code`.
- AI mentions are estimated at $0.101 a request (it was $0.20), so a plan's `total_usd` is lower.

### The practical report (team-preview-5)

`GET /audits/{id}/practical` returns the practical report as data, built from the saved report and page evidence:

| Field | What it holds |
|---|---|
| `executive` | `problems` (up to five: `severity`, `title`, `where`), `problems_total`, `opportunities` (sentences from the data panels and the smallest fixes), `actions` (up to five: `text`, `for`, `owner`, `effort`, `when`), and `withheld` when too few pages were read to rank anything. |
| `scorecard` | One row per area: `checks`, `in_order`, `by_severity`, `problems`, `notes`, `not_checked`. Counts, not a score. |
| `timeline` | `week`, `month`, `later`, each with `label`, `note` and its `items`. |
| `issues` | Every problem: `what`, `where`, `pages`, `pages_total`, `why`, `fix`, `example` (fixed text chosen by the finding's wording, or null), `owner`, `effort`, `source`, `confidence`. |
| `pages` | `rows` (`url`, `status`, `title`, `h1`, `h1_count`, `words`, `words_cut`, `schema`, `issues`, `read_by`), `total`, `with_issues`, `note`. Read from the saved evidence: Firecrawl's copy where it read the page. |
| `passed` | By area, the checks that ran and found nothing to fix. Beside the checks that passed stand the ones that found nothing on the pages read and are `partial` only because pages were found and not read: each has `read_only: true`, `read_only_shown` ("No problem found on the 50 pages read (9 not read)", in the reader's language) and that sentence in front of its `summary` and `summary_shown`. They are not counted in the scorecard's `in_order` and stay listed in `coverage` (DECISIONS 189). The same check's row in `areas[].checks` carries `read_only`, `read_only_shown` and `read_only_english` too; its `summary` there is unchanged. |
| `sources` | Every source of data in the report: `source`, `what`, `date`. |

`GET /audits/{id}/summary` carries a short form under `practical` (`executive`, `scorecard`, `sources`, and the
timeline with counts and the first ten items of each step) and the `url` of the full one. The summary also has:

- `crux`: Core Web Vitals (`status`, `summary`, `metrics`, `data_until`), or `status: "not_available"` with the
  sentence "Core Web Vitals not available (no API key)".
- `archives`: null, or `notice`, `pages_read` and `sources` (each with `pages`, `findings`, `notes`).
- `ownership`: the report's `ownership` section when verification was asked for; `verification`: the site's token
  and instructions, always.
- `blocked.allowlist`: `title`, `note` and `blocks` (`id`, `title`, `steps`, `copy`), present only on the card of a
  site nothing could read.
- `backlinks.checks[]`: now also the search data checks, each with `endpoint`, `data_from`, `from_cache` and
  `data` (`metrics`, `table: {columns, rows}`).

### Comparison

Findings are matched by check and by title with the numbers replaced, not by id (ids change with counts and pages).
The result has `differences` (target, pages, scope, rendering, important pages, optional sources), a `caution` when
any exist, and five lists: `still_reported`, `no_longer_reported`, `new`, `first_seen`, `cannot_tell`. A problem is
`no_longer_reported` only when the newer audit ran that check and read at least one page the older finding named;
otherwise it is `cannot_tell`. The word "fixed" is never used.

### Questions

`POST /messages` with `{"text": "..."}` returns `{"messages": [question, answer]}`. The answer body has `intent`,
`text`, `items`, and sometimes `finding_ids`, `suggestions`, and `card` (`{"type": "action_plan", "role"}`,
`{"type": "comparison"}` or `{"type": "findings", "severity"}`: the page fetches and shows the matching view).

Intents: `plan`, `critical`, `severity`, `top`, `check`, `pages`, `coverage`, `compare`, `summary`, `cost`,
`downloads`, `area:<ACC|IDX|RND|STR|PRF>`, `match`, `unknown`, `not_measured`, `running`, `no_report`. Answers are
rule-based and repeatable. `not_measured` is the answer to anything about rankings, mention rates, sentiment,
traffic or a visibility score.

## Downloads

`pdf`, `markdown`, `json`, `evidence`. Names are `maya-audit-<host>-<date>.<ext>`. The format comes from a fixed
list and never becomes part of a path. The evidence zip holds only files the audit's own index lists; a link
planted in the folder is not followed. A download is saved by the browser on the computer where the browser runs.

### Provider-load diagnostics (report schema 1.3)

`GET /audits/{id}/result` may contain `firecrawl.errors` (see REPORT-SCHEMA.md).
The summary's existing `firecrawl.lines` includes each complete redacted provider message,
engines tried and the explanation “Firecrawl could not load the page as a website”.
The same lines appear in printable PDF content and Markdown. No new route is required.
A provider engine failure does not set `also_blocked` or offer enhanced as a proven block remedy;
a fresh explicitly confirmed plan can request basic again, or enhanced with owner approval.

### Readable content after Firecrawl (reports made before Firecrawl became the page reader)

A report whose `firecrawl.purpose` is `content reader for a blocked site` keeps the earlier presentation: the block
card stays, `pages_stat.line` reads “Readable pages: 6 (read through Firecrawl; Maya’s own crawler was blocked)”,
and the fourth sentence of `blocked.lines` says the content checks ran on Firecrawl’s reading. New audits use
`main page reader` and are described under “Firecrawl in a plan”. Every list of check IDs is in natural order.

### Reading order, sitemap and causes (report schema 1.7)

- The plan's `firecrawl.max_requests` and `max_credits` count the page cap, robots.txt and, from a cap of 10 pages,
  two sitemap documents. `requested.sitemap_discovery` (default true) switches the sitemap request off for one plan.
- The report's `firecrawl` section gains `sitemap` (`documents`, `addresses_found`, `note`), and its `coverage` gains
  `not_requested_because`, `causes`, `sections_sampled` and `sitemap_addresses_found`. Each row of `pages` has a
  `cause` (null when the page was read). The status box's coverage row already carries these as its reasons; no new
  endpoint or screen was added.

### Lookups and local failures (report schema 1.8)

- An audit that this computer could not start ends in state `failed` with `error.code` `local_network_problem` or
  `host_not_found` and a message to show as it is. It has no result and no spend.
- `crawl.network` in the report: `preflight` and, per host, which lookup method answered.
- `crawl.stop_reason` may be `network_problem`. ACC-1 then reads `not_assessed` with "Not checked (network problem on
  this computer)". Search data keyword panels may hold an `ambiguous` list beside `unrelated`.

### One page count, one stop sentence, files apart, shared elements once (report schema 1.11, second change)

- Pages are counted as documents read, not addresses (decision 170). `/summary` `pages_read`, `pages_stat.value`,
  `counts.pages_checked`, `method.pages_checked` and the headline all show the report's
  `audit_status.content_coverage.pages_read`. A PDF Maya's crawler fetched, and an address the page reader saw
  redirect to a page that was read, are not pages: `pages_stat.also` says them ("Also fetched: 5 files (PDF or
  other documents) and 7 addresses that lead to a page already read.", strings `result.pages.also.both`, `.files`,
  `.same`; null when there are none) and `pages_stat.sentence` is the whole sentence ("43 pages read. Also fetched:
  …", string `result.pages.sentence`). `status.coverage` holds `pages_read`, `read_by` (`maya_only`,
  `firecrawl_only`, `both`, which add up to `total`; `firecrawl` is kept) and `other_addresses` (`files`,
  `same_page`).
- For a report saved before these fields existed, the same engine functions count them from the report's own
  `crawl` and `firecrawl` sections when it is shown (`maya_audit.report.content_coverage_shown`); the saved files are
  not rewritten. Its `status.rows` then also show one stop sentence instead of up to three reasons.
- `status.coverage.reasons` holds at most one sentence about why reading stopped. A reading that used its request
  allowance says "the page reader used all 51 page requests this audit allows and read 43 pages; 8 requests led to
  pages already read or to missing pages" (no "credit": that word is kept for a credit or budget refusal). The
  page cap of Maya's own crawl is not repeated beside it when the page reader is the main reader.
- One "not read" figure: `coverage.read_only_note`, `status.coverage.known_urls_not_read` and every check's "pages
  found but not read" part (`/checks/{id}` `not_assessed`, `coverage.gaps`) carry the same number, also for a saved
  report. When addresses were left out of it, `read_only_note` adds "(+12 addresses left out: disallowed by
  robots.txt or not a page)" (string `result.coverage.left_out`).
- `problem_summary.files` and `practical.by_page.files` (`title`, `columns`, `rows`): sitemaps, robots.txt and
  documents with a problem, listed under the table as "Files (sitemaps, robots.txt, documents)". A row has the shape
  of a page row; its `lines` are the problems' titles. Such an address is never in `rows`.
- `problem_summary.whole_site.shared_elements`: each `{finding_id, kind, element, pages}` (decision 171). The
  finding's title is the line to print in the "Whole site" row, for example "Shared header/footer: link to
  /account#/favourites has no text (on 50 pages)"; the element is named so it can be found.
- The Firecrawl section's `lines` may hold "Sitemap: 273 addresses known from Maya's own crawl; the reader was not
  asked for the sitemap." (`firecrawl.coverage.sitemap_addresses_known`).

### Page checks that could run, and sentences with no open hole (report schema 1.11)

- `POST /plans` takes `brand_family_domains` (a list of host names such as `other-shop.example`, at most 20; left
  out: the ones saved for this site). The plan holds `brand_family_domains` (cleaned: lower case, each once) and
  `max_brand_family_domains`; the list is part of the plan's fingerprint. `PUT /projects/{id}/profile` takes and
  `GET` returns `brand_family_domains` (left out of a PUT: what is saved stays; `[]` clears it). Anything that is not
  a host name (a scheme, a path, a port, an IP address, spaces, markup) is refused with 422
  `invalid_brand_family_domains` (message `plan.brand_family.bad`). A link to one of these domains is not reported by
  IDX-6 as a link to another site and is never requested (DECISIONS 196).
- `problem_summary.start_address` (`entered`, `status`, `audited_from`; schema 1.14): only when the start address
  answered 400-599 and the audit ran from another page. `/summary` then holds `start_address` (the same three values
  and `message`, string `result.headline.start_failed`), its `headline` starts with that message, and the printed
  report says it on the cover. `start_address` is `null` otherwise, and for a report saved before 1.14.
- The report's top-level `brand` (`name`, `source`, `confirmed`, `found_in`, `pages`; schema 1.14): the brand the audit
  used (DECISIONS 201). `POST /plans` puts a brand in `paid_options.brand` only when it was typed on the card or saved
  for the site; a name suggested from the address stays in `business.brand_name` with `brand_confirmed: false` and is
  not used, so DFS-12 (the Business Profile) is not requested until a name is typed. A `brand_name` sent or saved
  that equals that suggestion (spaces, case and Turkish letters aside) is not a typed name either (DECISIONS 220): it
  is shown with `brand_confirmed: false`, and the web page sends `brand_name` only when the person edited it. With no brand at all, DFS-4 and
  DFS-5 keep their plain table and say so; `dataforseo.relevance` holds `sorted`, `brand_source` and `brand_confirmed`.
- `problem_summary.page_checks` (`total`, `could_run`, `limited`): how many of the report's page checks could run.
- Single-page audits: `POST /plans` accepts `mode: "single"` (page cap 1; `key_pages` are ignored; the plan holds `single_page: true` and `scope_label`, for example "Single page: 1 page, ~2 Firecrawl credits. Only this address is read; no links are followed"). The summary of such an audit holds `single_page` (`url`, `title` "Single-page audit: <URL>", `note`), and a site-wide finding's row holds `site_level: true` with `affects` "Site-level: also affects this page".
  It is counted from the report's own checks whenever a report is shown (a check whose own evidence says it looked
  at no page could not run, even where an older report saved it as `partial`); the saved files are not rewritten. When `limited` is true (fewer than half could run), `headline` in `/summary` starts with the string
  `result.headline.limited` ("Only 16 of 41 page checks could run, so this is not a clean result.") and, with no
  problem, continues with `result.headline.limited.none` ("The 16 that ran found no problems on 50 pages").
- A sentence from `/strings` is never shown with an unfilled placeholder. When a value is missing, the page's `T()`
  and the server's `strings.t()` use the sentence's `.plain` form if there is one, else write "…" in its place.
- `practical.by_page.rows[].lines` name a language in the reader's language ("English", "İngilizce"; strings
  `language.en` … `language.nl`). `problem_summary.by_page[].items[].values` keep the code ("en").
- `firecrawl.coverage` in the report gains `indexability_disagreements` and `indexability_disagreements_count`.

### What is wrong on each page (report schema 1.10)

- `problem_summary.by_page[]` gains `items` (`finding_id`, `check_id`, `severity`, `kind`, `values`), in the order of
  `finding_ids`. For a report saved before 1.10 the engine derives them from the report's findings
  (`maya_audit.report.with_page_items`); the saved files are not rewritten.
- `practical.by_page.rows[]` gains `lines`: one sentence per problem, in the reader's language, saying what is wrong
  on that page with that page's own numbers ("Title too long (71 characters)"). Print `lines`; `titles` stays (the
  site-wide titles) and the "Whole site" row's `lines` are its `titles`. The fourth entry of `columns` reads "What is
  wrong on this page". The sentences are the strings `bypage.<kind>` and `bypage.<kind>.plain` (the plain form is
  used when the report holds no number for the page).
- `practical.executive.actions` holds five distinct actions: problems of the same check with the same fix are one
  entry, whose `for` names every one ("; " between them) and whose `titles` lists them.
- `/summary` gains `gaps_line` ("3 parts could not be checked; see “What could not be checked”.", null when nothing
  was left out). `summary_line` stays. `coverage.sampled_note` no longer repeats the page count.
- Sentences from `/strings` may hold a placeholder with the word for one and for many: `{count:page|pages}` is
  "1 page" or "3 pages". Give the count as a number.

### Headline and problems by page (report schema 1.9)

- `GET /audits/{id}/summary` gains `headline` (one sentence: "15 problems found on 50 pages (1 high, 5 medium,
  9 low) + 12 notes", in the reader's language), `top_title` ("Top 5 of 15 problems", or "All 3 problems") and
  `problem_summary` (the report's own section; for a report saved before 1.9 the same engine function is applied to
  the report and `affected-urls.json`, and the saved files are not rewritten).
- `summary_line` no longer names blockers and high: it reads "50 pages checked. 3 parts could not be checked."
- `practical.by_page` (in `/summary` and in `/practical`): `title`, `columns`, `rows` (`whole_site`, `url`, `label`,
  `problems`, `worst_severity`, `worst_severity_label`, `finding_ids`, `titles`), `not_listed` (`finding_id`,
  `title`, `pages`, `line`) and `note`. It is null when there is no problem. The "Whole site" row is first.
- `practical.executive` gains `problems_title` and `more`. The `issues` figure of each row of `practical.pages`
  is the same per-page count: a site-wide problem is under "Whole site", not on every page.

### Fast check, links to other sites and the step timing table (team-preview-16, DECISIONS 219)

- `POST /plans` takes `fast_check` (false by default) and `external_links` (true by default). Fast check runs the
  audit with `--fast` (6 rendered pages, at most 50 sitemap addresses, 20 llms.txt links, 10 images and 30 requests to
  other sites); `external_links: false` runs it with `--no-external-links`. Both are in the plan's fingerprint (a
  changed switch needs a new plan; at their defaults the fingerprint is what it was before), and the plan's minutes
  and time limit take the smaller caps.
- The plan holds `switches`: `fast_check`, `external_links`, `external_cap`, and the shown `fast_label`, `fast_help`,
  `external_label`, `external_help` (strings `plan.fast.*`, `plan.external.*`).
- The report's `crawl.steps` (`step`, `started_at`, `seconds`, `requests`, `waiting_s`; the Firecrawl reader's row is
  `page_reader`) and `crawl.skipped_for_time`. `/summary` gains `coverage.steps` (`title`, `columns`, `rows` of
  `step`, `label`, `time`, `requests`, `waiting`; null for an older report) and `coverage.skipped_note` (string
  `steps.skipped`, or null). The printed report shows both.

## Saved-audit client workspace (workspace contract 1, cards contract 2)

All routes inherit the existing local host/origin/session/action-token/body-size guards. Base:
`/api/v1/audits/{audit_id}/client-report`. They operate on inactive saved audits only.

- `POST` base: create an evidence-only draft, or return existing edits unchanged. No provider calls.
- `GET` base: load workspace, provenance, evidence reference choices, and validation results.
- `PUT /summary`: `{revision, one_read, bullets}` (at most four bullets).
- `PUT /cards/{finding_id}`: `{revision, title, explanation, steps, proposed_text, proposed_code,
  decision, owner, effort, verify, references}`. References are nonnegative indices into GET's immutable
  reference choices; no arbitrary evidence, score, comparison or verification input is accepted.
- `POST /review`: `{revision, reviewer, reason}` records editorial attestation for all findings including
  appendix. This never records live verification. Any save invalidates review.
- `POST /validate`: errors/warnings and final readiness; no fixes or audit activity.
- `GET /preview`: explicitly labeled saved draft, static HTML.
- `GET /export/{html|pdf}?mode={draft|final}`: final validates before output; drafts are marked on every page.

Stale revisions or changed source evidence return 409 and preserve edits. Invalid/unsupported final claims
return 422 with actionable errors. Missing PDF capability returns 503; HTML remains available. Workspace data
is `artifacts/client-report.json`, separate from report.json, and follows the existing audit folder lifecycle.
The audit JSON schema is unchanged. Source digest identifies the saved evidence, not a new verification.
Profile confirmed-name lists remain the same optional API fields; omitted lists preserve existing values.
- `PUT /client-report/notes` (under the same audit base): `{revision, not_measured, comparison_titles}`.
  Notices keep their count; comparison edits are only `{group, index, title}`. Status/evidence cannot be edited.

### Saved-evidence revised analyses

Normal source history remains unchanged. `GET /api/v1/analyses` lists offline-prepared, digest-checked entries; `GET /api/v1/analyses/{id}` gives their identity/provenance. A registered `analysis-*` ID uses the existing `/audits/{id}/summary`, `/practical`, `/action-plan`, `/findings`, `/print`, `/downloads/*` and client-report routes. Lifecycle, chat and paid-provider mutations return409; client drafts/edits are confined to the separate artifact directory. No upload/import or arbitrary path parameter is exposed.

Exports carry `X-Maya-Analysis-ID`, `X-Maya-Source-Audit-ID`, `X-Maya-Report-SHA256` and `X-Maya-Exported-At`. Canonical JSON bytes remain stable; export time is not observation/processing time. The normal UI supports `/#analysis=<registered-id>` and a separate Revised analyses sidebar section. Registry data under project `output/revised-analyses` is private, ignored by Git and not a release resource. Tests pass `analysis_folder` explicitly; isolated MAYA_AUDIT_HOME entrypoints never read the owner registry.
