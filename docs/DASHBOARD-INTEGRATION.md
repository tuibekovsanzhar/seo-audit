# Moving this into the Maya dashboard

The local app is single-user software for one computer. Binding to `127.0.0.1`, a session cookie and an action
token keep other websites out of it. None of that is security for a hosted, multi-user service, and it should not
be presented as such. This note lists what a hosted version has to add, and where the seams are.

| Need | Local app today | Hosted version |
|---|---|---|
| Authentication | None. Whoever uses this computer's browser is the user. | The dashboard's own sign-in on every route, including the event stream and downloads. Replace `security.Guard`. |
| Tenant isolation | One data folder, one history. | A tenant id on every row and every query in `store.py`, and in every storage path. A request must never be able to name another tenant's audit, plan, evidence file or profile. Test it as a security property. |
| Jobs | One worker thread in the web process; a queue in SQLite; a lock file. | A managed queue with separate workers. The contract to keep is `runner.Runner`: claim a queued audit atomically, emit events, honour stop, mark unfinished work interrupted and never auto-resume. Per-tenant and global concurrency limits. |
| Storage | Files under `~/.maya-audit/web/audits/<id>/`. | Object storage with per-tenant prefixes, signed short-lived download links, encryption at rest. Reports hold the audited site's content. |
| Database | SQLite (`web-v1.db`). | The dashboard's database. `store.Store` is the only module that speaks SQL. |
| Spending | One ledger file under a file lock; a daily limit for the machine ($20 by default) and a limit for one audit ($5 by default), both DECISIONS 192. | A ledger table with the same reserve-then-settle steps in one transaction; limits per tenant and per plan; the same rule that every new charge needs a confirmation tied to a priced plan. |
| Provider credentials | Read by the engine from the environment or a local `.env`; never shown. | A secrets manager; per-tenant keys if tenants bring their own; never in logs, reports or API answers. |
| Quotas | A page cap per mode and a five-audit queue. | Audits per day, pages per month, concurrent audits, per tenant. |
| Retention | Nothing is deleted until the user deletes it. | A stated retention period, deletion on request, and deletion that reaches the saved crawl, the evidence and the cache. |
| Crawling from a server | The user's own network; private addresses refused; loopback allowed only for tests. | `block_loopback` always on, egress through addresses that are published for site owners, the bot-information page live, per-origin rate limits across tenants (two tenants auditing one site must not double the load). |
| Rendering | Local Chromium. | Sandboxed browsers with the engine's network rules; no access to the service's own network. |
| Abuse | Not applicable. | Proof of a relationship with the site before deep audits (the engine already has ownership verification for probes), and limits on auditing third-party sites. |

What can be reused as it is: the engine; the API's shapes and error codes (`docs/WEB-API.md`); `summary`,
`comparison`, `followups`, `catalog`, `pdf`; the strings catalog; the page, if the dashboard wants it.
