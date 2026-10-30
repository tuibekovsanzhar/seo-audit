# DataForSEO fixtures

`backlinks_summary.json` and `backlinks_referring_domains.json` are the answers the test suite's mock
DataForSEO gives for `/v3/backlinks/summary/live` and `/v3/backlinks/referring_domains/live`.

They were written by hand, with an invented domain, invented numbers and invented `cost` values
(0.02003 and 0.023). They hold no account name, login or client domain.

On 2026-10-06 their structure was compared, key by key and type by type, with the answers of the
first real audit. The envelope, the task and the result rows matched; the referring-domain items
were missing seven fields the real answer carries (`referring_links_*` and
`referring_main_domains_nofollow`), which were then added here. The parser reads none of those
seven, so it needed no change.

Never store a real response in this folder: it names the audited domain and the sites linking to it.
