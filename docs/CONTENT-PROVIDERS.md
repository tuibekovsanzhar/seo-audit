# Commercial content providers

`maya_audit/content_provider.py` is the small adapter contract: provider identity, explicit consent,
HTML page, guarded `scrape`, request accounting and close. Typed exceptions distinguish a website-load
failure (continue with other known URLs), a request cap (keep partial content), a retention decision,
and other failures (stop). `FirecrawlClient` implements it. `firecrawl.reader.read_blocked_site` consumes
the protocol and labels shared engine checks using the provider identity. It does not duplicate check logic.
The Firecrawl-specific `apply` wrapper retains its billing and rendering report integration.

No second provider is installed, registered or selectable. There is no automatic provider failover.
A future Bright Data or other commercial adapter must supply its own documented API contract and pricing;
this interface is not permission to enable it.

Required adapter/integration rules:

- A new provider is off by default and selected explicitly per audit; `ProviderConsent` defaults to disabled. Firecrawl's
  basic reader is the one exception, by the owner's decision of 2026-10-08 (DECISIONS 131): on when its key is set.
- A provider that unblocks must call `consent.require(unblocking=True)` before cache or network use.
  Firecrawl uses this for enhanced/auto; even direct client calls now refuse missing owner approval.
- Price every permitted request option, bind target/options/maximum to the plan, confirm the exact web-plan
  amount, and revalidate it before starting. Unknown pricing prevents requests. CLI ceilings remain explicit.
- Use the existing locked Ledger reservation and Cache facilities with a separate provider namespace/unit.
  Reserve before network access; enforce the audit ceiling, daily budget and hard request cap. No automatic
  paid retry; retain reservations when delivery/billing is uncertain. Cache hits cost zero and are logged.
- Redact credentials before errors reach reports, ledgers or UI. Surface provider refusals separately from
  target-site blocks. New report fields require a schema bump and frozen-schema tests.
- A provider page keeps its identity (DECISIONS 139): address asked for, address reached, status known or not,
  observation time, cached or not. Requests share the audit's deadline, stop and pace (`maya_audit/runclock.py`).
- Fetch content only under the robots policy. Run the existing content checks and label every affected finding
  `Source: <provider>`. Maya's own crawl remains the only source for live access, headers, redirects and timing.
- Add mocked contract tests for opt-out, missing consent, exact confirmation, expired/cache-changed plans,
  budget exhaustion, cache isolation, ambiguous billing, full errors, request caps and source labels.

Maya implements no stealth browser, fingerprint spoofing, CAPTCHA solving or proxy rotation. Unblocking is
only the explicitly approved commercial provider mode. Archives in the next phase have separate provenance
and must not be presented as live provider reads.
