# Maya Audit review: implementation status

This note records changes made after `Maya-Audit-Review-2026-09-28.docx`. It is not a claim that
the package is fully production-ready. The complete local fake-server suite was run after these
changes: 303 passed, 11 skipped. Ten skips were browser-render cases because this Mac's installed
Chromium exited with SIGTRAP; one saved-live-report fixture is absent.

## Changes made in this package

- **Private-network request protection:** HTTP requests resolve hostnames and reject non-public IP
  addresses. Redirects are fetched one hop at a time, so each destination is checked. The optional
  bot-information request now also validates every redirect. Rendering no longer lets Chromium
  resolve hosts itself: browser requests are fetched through the guarded HTTP client, redirect
  targets are checked, external resources require the opt-in flag and their own robots policy, and
  each rendered page has a 100-request cap.
- **Incomplete-crawl reporting:** page-dependent checks now include an explicit coverage gap when
  the crawl stops early or leaves URLs unchecked. A clean result for the pages fetched is therefore
  shown as partial, not as a site-wide pass. Truncated HTML bodies are disclosed on structure checks.
- **Page selection:** a URL already queued from a sitemap is upgraded to its link-discovered depth
  and priority. Linked content pages are no longer left behind solely because the sitemap queued
  them first.
- **Sitemaps:** same-origin redirects are followed one hop at a time, and gzip sitemaps are safely
  decompressed within the configured size cap.
- **Time and failures:** the time limit now applies to page fetches, waits, collection requests,
  and render waits; the report records elapsed time including post-crawl collection. A failed data
  collector is recorded and its check family becomes `not_assessed`, while available crawl evidence
  is retained. Requests that cannot begin before the deadline are skipped without a fabricated
  timeout record, excluded from INT-4, and affected collector checks are `not_assessed`. The robots
  re-sampling interval is shortened to use no more than one quarter of the configured time limit.
- **Hosted-use protections:** `--block-loopback` / `CrawlConfig(block_loopback=True)` rejects
  localhost destinations. Rendering disables Chromium's native name resolution and promptly
  abandons routed WebSocket connections, keeping browser traffic from bypassing the guarded fetcher.
- **Concurrency and reports:** per-origin OS file locks now coordinate processes on the same host
  and lock-capable filesystem. The readable Markdown report lists unfinished checks before the fix
  list, and the missing render-check collector append was corrected.
- **Rendering disclosure:** failed render samples and blocked third-party resources create a visible
  coverage gap for the render comparison.
- **Noindex severity:** S1 is reserved for user-marked key pages and sitemap-listed pages. Internal
  links alone do not make utility pages such as carts, login, or search into blockers.
- **Output preflight and citation wording:** existing output paths and path collisions are rejected
  before the crawl starts. If citation inputs are absent, the readable report says no citation data
  was supplied, and the citation collector is not listed as a failure when the deadline expires.
- **Other report fixes:** sitewide `Disallow: /` rules are labelled sitewide; malformed
  `--critical-fact` arguments are rejected; outputs create their parent folder, refuse to overwrite
  by default, and can be replaced explicitly with `--overwrite`; the CLI returns a non-zero status
  for degraded or incomplete runs.
- **Readable reports:** `--markdown PATH` now creates a human-readable Markdown summary alongside
  the full JSON evidence. JSON, Markdown, and model-brief files are generated from the same audit
  result.
- **Tests and documentation:** obsolete “live host must be pre-allowlisted” assertions were
  updated for the current start-URL behavior; invalid optional bot-page tests now check graceful
  continuation; the flaky numeric-substring assertion was removed; and the test harness blocks
  non-loopback socket connections. Package/version and OpenSEO license claims were corrected.

## Still requires work or human review

- **No Maya Dashboard integration is included.** There is no Maya Dashboard source, API, queue,
  authentication, or database in this package. Integration needs Maya engineering access. For
  multiple machines, the host application must provide a distributed per-origin lock; this lock
  covers processes sharing one host and filesystem.
- **The DNS check is not a network firewall.** A DNS answer could change between validation and
  connection (DNS rebinding), and system DNS resolution itself is outside the Python request timer.
  Run the crawler in a worker/container with outbound rules that block loopback, private, link-local,
  reserved, and cloud-metadata ranges. The browser is routed through the Python client, but the same
  deployment egress rule should remain in place as defense in depth.
- **Remaining launch-gate work:** additional open items are listed in
  `docs/LAUNCH-GATE.md`; a successful fetch or technical-readiness result does not establish that a
  brand appears in AI-generated answers.
- **License review remains open.** This package now includes OpenSEO's MIT notice because its own
  source comments describe some patterns and prompts as ported/adapted. A person should compare the
  exact material against the OpenSEO source before external redistribution. This package does not
  include OpenSEO's application source tree.
- **The complete raw JSON can still be large.** Markdown is the readable summary; the current JSON
  remains a full evidence document rather than a split findings/evidence pair.
- **URL query parameters are not normalized.** Removing or reordering arbitrary parameters can
  merge distinct pages, so this needs an explicit configurable policy before changing crawl identity.
