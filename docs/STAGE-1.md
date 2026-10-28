# Stage 1: engine and report repairs

Stage 1 changed the existing engine and its reports. It added no web app (that is Stage 2, `docs/STAGE-2.md`).
The changes were drafted in a separate working copy (Codex, 2026-10-07), whose sandbox could not open local
test servers, and then brought into this repository and tested here against the real loopback fake servers.

## What changed

| Area | Before | Now |
|---|---|---|
| INT-4 | A politeness `violation` did not affect the overall verdict. | It makes the audit DEGRADED (exit code 1) and the report says why. |
| Paid-call accounting | A failed paid call was missing from the report's call list; some uncertain failures were recorded as $0; a paid call that got HTTP 5xx was sent again. | Every attempted paid call is listed with a `billing_status`. A call whose outcome is unknown (timeout, dropped connection, unusable answer) keeps its estimate reserved and is never sent again. A call that never connected costs $0. |
| ANS in Markdown | The ANS checks were in the JSON and terminal reports only. | The Markdown report has its own "Answer-engine observations" section. It changes no site finding and states what it does not measure. |
| Network safety | The address that was validated and the address connected to could differ; TLS probes and the optional GSC, Bing, PSI and CrUX calls skipped some safety and deadline checks. | Connections go to a validated address while keeping the original Host and TLS name. Those probes and calls obey stop and the time limit, and their responses are size-capped. |
| Resume | A saved crawl could be resumed for another site or other settings. | The saved crawl remembers its target and settings; a mismatch is refused before any request. A crawl saved before this change must be started fresh. Reports say when pages come from several sessions. |
| 500 pages | Evidence saving stopped at 300 pages; writing the JSON copied working data it then threw away. | Evidence covers 500 pages (still 20 MiB in all); the copy is gone. |
| Lite helper | A quote in a link from a website could become an HTML attribute. | Quotes are escaped. |

## Two defects found when the draft was tested here

The draft's own environment could not run these tests, so they surfaced only in this repository.

1. **Sites that list an unreachable address first could not be read.** The new transport connected only to the
   first address a name resolved to. `localhost` resolves to IPv6 first and the fake servers listen on IPv4, so
   the crawl read nothing; a real site with a broken IPv6 record would have behaved the same. The transport and
   the TLS probe now try each validated address in turn. Test: `test_transport_falls_back_to_the_next_validated_address`.
2. **A paid call that never connected was counted as possibly charged.** It is now recorded as failed at $0,
   because nothing reached the provider. Test: `test_a_paid_call_that_never_connected_costs_nothing`.

One decision changed two older tests: a paid call answered with HTTP 503 and no usable body used to count as $0
and be retried twice. It now keeps its reserved estimate and is not retried (`tests/test_batch.py`,
`tests/test_dataforseo_backlinks.py`). This over-counts rather than under-counts against the $2 daily allowance.

## Tests

Run from the project folder: `.venv/bin/python -m pytest -q -ra`

| Run | Passed | Failed | Skipped |
|---|---:|---:|---:|
| Before Stage 1 (this repository) | 578 | 0 | 1 |
| Draft applied as it came | 601 | 6 | 1 |
| After the fixes above | 609 | 0 | 1 |

The skip is a test that needs live-run example reports, which are not kept in git. Every test uses local fake
servers or in-memory transports; a guard in `tests/conftest.py` blocks any connection that is not loopback.

## Offline preview

`.venv/bin/python scripts/stage1_preview.py`, then open `output/stage1-preview/index.html`: a 500-page report
from an in-memory test site. No port is opened, no real site is contacted and no paid service is called.

## Limits that remain

- Looking up a host name and an already-blocked read cannot be interrupted instantly; the time limit and stop are
  checked after the lookup and between chunks.
- The 500-page test site is small static pages. It shows that counts, exports and accounting work at that size,
  not how long a real 500-page JavaScript site takes or how much memory it needs.
- The command line still asks for approval only above $0.50 per audit. The web app (Stage 2) asks every time.
