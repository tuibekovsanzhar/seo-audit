# Real-site benchmark (on demand only)

This corpus is separate from pytest. It does **not** run when an owner starts Maya or runs ordinary tests.
The runner uses the current shared engine, native guarded requests and Chromium when available. No Firecrawl,
DataForSEO, Search Console or paid performance client is constructed. No `.env` is loaded. Each worker gets a
new private home/config/cache/audit directory and an allowlisted environment. Original owner history is unused.

## Commands

From the project root, using the existing environment:

```sh
.venv/bin/python -m scripts.real_sites_benchmark collect --live
.venv/bin/python -m scripts.real_sites_benchmark collect --live --site arjava
.venv/bin/python -m scripts.real_sites_benchmark score output/real-sites/RUN
.venv/bin/python -m scripts.real_sites_benchmark replay output/real-sites/RUN
.venv/bin/python -m scripts.real_sites_benchmark compare output/real-sites/BEFORE --after output/real-sites/AFTER
```

Collection explicitly makes public website requests. It never runs in the normal offline suite. Run sites sequentially
by default; a 50-page cap and 720-second engine budget apply per site, with a 780-second outer worker wall. Existing
robots, redirect, SSRF, backoff and timeout protections remain in force. Robots restrictions are not bypassed. The
configuration uses the engine's Fast optional-request caps; this is **native Quick 50 without the paid page reader**,
not a claim that Firecrawl was tested for free. The budget is a ceiling, not evidence of 50 successful content reads.

Output is a new `output/real-sites/<run>/` directory with per-site reports, complete captured native response records,
source hashes, phase events, source collection dates, elapsed seconds and `scorecard.json`. Files are local evidence;
do not put website bodies, cookies, customer data or real provider responses in Git or preview archives. The capture
retains selected response headers and streamed response bytes, not authentication/cookie values. It reads no more
body data than the engine requests. Incomplete streams are marked and cannot be silently replayed as complete pages.

## Golden labels require human evidence review

`expected.yaml` uses JSON syntax, a valid YAML 1.2 subset parsed with the standard library. No dependency installation
is required. Each file has `must_find` and `must_not_find`. The initial owner allegations and healthy contrasts are
**provisional**, not independently verified facts. Do not call a corpus golden merely because those files exist.

Before promoting a label to `verified`, independently inspect the captured request/markup, not just the engine's
conclusion. Record under `verification`:

```json
{
  "reviewer": "reviewer identity and method",
  "observed_at": "timezone-aware source collection time",
  "evidence_reference": "run/site/responses/000123.body and requests.json record",
  "evidence_sha256": "SHA-256 of the independently inspected evidence",
  "collection_digest": "digest from site/collection.json",
  "observation": "Exact observed markup/status and the supported interpretation"
}
```

Select exact affected `urls`, `check_id` and, when needed, `severity` or `title_contains` so a different conclusion
under the same check cannot satisfy the assertion. Define the interpretation and a plausible alternative in `reason`.
Use negative labels only for genuinely assessed cases. A page not read or a partial check cannot establish a pass.
Scope differences are legitimate: a sitemap probe is not a full content assessment. A query-string question mark
is not by itself evidence of URL corruption. Colour variants need actual distinguishing product evidence.

The scorecard counts labelled **hits**, **misses**, **false alarms**, **correct negatives**, **provisional** and
**unassessed** assertions. Unlabelled findings are reported separately; they are not automatically false alarms.
This fixed, purposively selected corpus is a regression set, not an independently sampled accuracy percentage.

## Before/after rules

Freeze one collection and its independently verified expectations before changing engine rules. Offline replay uses
only captured method/URL/client/attempt responses; absent requests produce explicit gaps and no network fallback.
Cookie values are deliberately not retained. A cookie walk requiring them cannot be reconstructed as fresh proof.
Browser rendering and OS-level TLS checks are **not replayed** from HTTP bytes; they remain unassessed in a replay.
Replays have new processing times and retain original source collection times. Do not call them fresh website checks.
The replay's generated crawl/request clock values describe replay execution; original request times remain in the
source `requests.json`, and the report carries an explicit timestamp warning. Replay outputs are benchmark artifacts,
not client-delivery audits. Collection/replay gaps must be inspected alongside the scorecard. Matching a few labelled
cases does not establish that every request or unlabelled finding was reproduced.

Only compare matching collection digests and expectation digests. A previously passing labelled case becoming missing
or unassessed is a regression. Changed live content or amended labels require a new baseline, not a claimed engine
improvement. Review new misses/false alarms and all significant unlabelled findings; do not optimize the engine to
these domains. Production rules must use evidence contracts, never these domain/brand/path literals as exceptions.

Each staged preview note must give the fixed-evidence before/after scorecard and its gaps. If hand review, current
tests or package verification is blocked, do not advertise a verified/golden release or bypass those gates.

The current scorecard also records readable content pages and per-phase timing rows separately from the 50-page
request cap. Unavailable measurements remain null. A worker completing its attempt is not proof that it read the site.
