# Firecrawl website-engine diagnosis — 2026-10-08

The owner reported maximum.com failing with HTTP 500, engines `[pdf, document, image]`, and zero credits.
No paid request or real crawl was made during this investigation.

## Likely cause and correction

Maya sent `blockAds: false`. Firecrawl’s public source maps that to `disableAdblock` (priority 10).
Browser engines declare this unsupported, while file engines support it; the selection threshold can
therefore exclude browsers. With cache disabled, the reported file-only list fits this path.
This is a source-based diagnosis, not proof of the hosted deployment’s exact revision.

Sources: [feature flags](https://github.com/firecrawl/firecrawl/blob/main/apps/api/src/scraper/scrapeURL/index.ts),
[engine selection](https://github.com/firecrawl/firecrawl/blob/main/apps/api/src/scraper/scrapeURL/engines/index.ts).

The request now explicitly uses `blockAds: true`. This leaves Firecrawl’s browser/HTML routing eligible;
no undocumented engine selector is sent. Ad/cookie filtering may affect returned content, which remains
third-party content evidence, never Maya’s live access evidence.

## Request audit

Checked against the [v2 scrape reference](https://docs.firecrawl.dev/api-reference/endpoint/scrape):

| Option | Maya request and decision |
|---|---|
| `formats` | Keep `rawHtml`, a supported output. |
| `onlyMainContent` | Keep false to retain head tags. |
| `parsers` | Set `[]`: disable optional PDF extraction and its per-page charges; not an engine selector. |
| `maxAge`, `storeInCache` | Keep 0 / false: fresh fetch, no provider caching. |
| `zeroDataRetention` | True unless waived per audit; omitted after waiver. |
| `timeout` | Keep 85,000 ms, within documented bounds. |
| `waitFor` | Omitted for content; 1,500 ms for rendering fallback. Adds a wait, not a browser-enable switch. |
| `proxy` | Explicit basic; enhanced/auto require owner approval. |
| `mobile` | Explicit false: desktop. |
| `skipTlsVerification` | Keep false: validate TLS. |
| `blockAds` | Change false to documented default true. |
| `removeBase64Images` | Keep true; affects Markdown, not rawHtml. |

No fast mode, forced engine, actions, cache-only mode, custom fingerprint or CAPTCHA option is sent.

## Failure behavior

Schema 1.3 adds optional `firecrawl.errors`: URL, HTTP status, full credential-redacted provider message,
engines tried, classification, meaning and caveat. The existing 12 MiB response bound still applies;
within that bound error text is not shortened for display. Text, Markdown, printable PDF content and
web results include the message. The UI escapes provider strings.

A provider 500/no-document engine failure is not proof of a protection block. Maya moves to other already-known
URLs, once per URL, subject to the same request cap, confirmed credits, daily budget, stop control and robots
policy. No automatic retry or proxy escalation occurs. If only the homepage is known, there is nothing else
to read. Three unreadable target responses still stop the initial blocked-page sequence. Account, budget,
rate-limit, ZDR and ambiguous-billing errors stop immediately. Partial content survives a later request cap.

## Owner validation

1. Restart the local app from a normal Terminal and create a fresh maximum.com audit.
2. Select Firecrawl basic; leave owner approval unticked. If needed, explicitly waive ZDR in its decision card,
   and confirm the displayed credits. The code must no longer request `blockAds: false`.
3. Content may now load or a real challenge may remain. If an engine failure remains, the full message and engines
   should appear in the result, Markdown and PDF. Keep that error for provider support; do not call it a confirmed block.
4. Only if the team lead approves: create one fresh plan with the owner-approval tick **and enhanced selected**,
   confirm its displayed maximum, and handle ZDR separately. The tick alone does not change basic to enhanced.

Actual browser selection, maximum.com success and provider billing remain to be verified by the owner.

## Owner confirmation and reporting correction

The owner reported a successful basic run on 2026-10-08: six pages, six credits, with ZDR waived and no owner-bypass approval. Saved evidence showed a false STR-12 High finding: ordinary privacy-policy prose mentioned “your company name and job title”. Company-name phrases now require an explicit template slot or instruction, rather than matching ordinary prose. No live request was made to investigate. Saved historical findings remain unchanged; newly evaluated content uses the corrected rule. Summary counters now include Firecrawl content while preserving the live access block.
