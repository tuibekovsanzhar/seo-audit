# Offline calibration cases

Use these when calibrating the reasoning procedure, not as a new application rule set.
All records below are synthetic: URL `https://judgment.example/service`, check `IDX-3`.
Native collection time: `2026-10-18T09:00:00+00:00`; no real website was requested.
Reproducer calls the existing `maya_audit.index_data.observed_cycle` and `redirect_verdict(entry, 3)`.
Expected results below describe the current Python contract, not universal SEO thresholds.

## A — Unsupported false-positive conclusion

- **Observation:** proposed output says “The hop limit proves a persistent redirect cycle.” Three attempts
  contain only `/service/1 → /service/2 → /service/3`; no destination repeats. Cookie walk also ends at the cap.
- **Evidence:** case A `entry.attempts[*].hops` and `entry.cookie_walk`, native time above;
  `cycle_observed: false`. A cap is recorded, not a completed cycle or readable-page response.
- **Interpretation:** the proposal mistakes an incomplete traversal for proof of a loop.
- **Alternative:** a finite redirect chain, possibly with state transitions, could exceed the cap.
  This does not establish that the chain is harmless or that the page ultimately loads.
- **Supported conclusion:** REMOVE the proven-cycle conclusion; retain the observed cutoff and uncertainty.
- **Severity/confidence:** no supported persistent-loop Blocker; high confidence that these records do not prove
  a cycle, unknown confidence about the final destination. Do not downgrade an independently evidenced defect.
- **Recommendation:** inspect the recorded path and missing termination evidence; prescribe no server/CDN fix.
- **Verification:** `observed_cycle=False`; `redirect_verdict=unchecked`, expected and actual agree.
  Regression: `test_idx3_hop_limit_without_repeated_state_is_not_a_cycle`.
  Contrasting completed repeated-state cycles return `always` and remain detectable.
- **Gaps:** destination after cutoff and any separate chain-impact evidence remain unavailable.

## B — Genuine defect retained

- **Observation:** the tested native client repeatedly receives a self-redirect, including a completed cookie walk.
- **Evidence:** case B `entry.attempts[0:3]` and `entry.cookie_walk`; each records
  `service → service`, HTTP 301, native time above, with a proven repeated state.
- **Interpretation:** sufficient recorded native cycles plus a cyclic cookie walk support scoped persistence.
- **Alternative:** cookie-dependent access is plausible, but the completed cookie walk also cycles;
  there is no readable success in these synthetic observations. This says nothing about every possible client.
- **Supported conclusion:** RETAIN the persistent-cycle defect for the tested URL/client/attempts.
- **Severity/confidence:** retain current engine S1/verified for the demonstrated access failure, not a
  universal outage or a diagnosis of nginx/WAF/CDN configuration. Scope is one URL, not a site-wide page count.
- **Recommendation:** inspect matching request logs, identify the supported cause and retest relevant contexts.
- **Verification:** `observed_cycle=True`; `redirect_verdict=always`, expected and actual agree.
  Regression: `test_idx3_proven_cycle_in_both_contexts_is_persistent_but_not_universal`;
  `test_idx3_collector_keeps_native_cookie_context_and_request_times` also asserts engine S1 remains.
  Contrast: add a native readable HTTP 200 attempt → `intermittent`; cookie-backed success retains engine S3.
- **Gaps:** technical cause, other clients and later behavior are not established.

## C — Conflicting/insufficient evidence stays uncertain

- **Observation:** proposed output says “Cached Firecrawl HTML proves the newer native failure is fixed.”
  Three newer native attempts cycle; the native cookie walk is missing.
- **Evidence:** case C `entry.attempts[*]`, native time above; `firecrawl` records cached HTTP 200
  at `2026-10-17T09:00:00+00:00`, a different source and collection time. Cookie verification is absent.
- **Interpretation:** the proposal treats historical reader success as equivalent newer native resolution.
- **Alternative:** differences in client/state/time could explain both observations. Provider/native conflict
  is not itself proof of a website defect or crawler misbehavior.
- **Supported conclusion:** QUALIFY: native cycles observed, persistence and resolution unknown; do not say fixed.
- **Severity/confidence:** current engine incomplete-verification behavior retains S3/inferred;
  observation confidence must not become confidence in a universal access or configuration claim.
- **Recommendation:** preserve both sources and identify the missing comparable evidence; no new live call
  follows from this review. A cached reader response cannot erase the native observation.
- **Verification:** `observed_cycle=True`; `redirect_verdict=unchecked`, expected and actual agree.
  Regression: `test_idx3_missing_or_incomplete_cookie_walk_is_uncertain` and the collector regression above.
  Contrast: supply a completed native cyclic cookie walk → `always`, so genuine defects are not suppressed.
- **Gaps:** matched native cookie result, equivalent provider/client conditions and current readable-page evidence.

## Installation exercise, 18 October 2026

Reviewed the three records using SKILL.md's observation → interpretation → alternative → supported conclusion
→ verification procedure. The raw synthetic inputs, actual results and contrasts were executed locally against
Python at base commit `61af28f` plus the preserved unfinished working tree; no application files were changed.
All three expected outcomes and all three contrasting outcomes matched. This is a self-review exercise,
not an independent agent evaluation or proof of semantic correctness on other audits.

The temporary calibration driver used an environment allowlist, a nonexistent MAYA_AUDIT_ENV_FILE,
fresh audit/home/cache/config/temp/bytecode/pytest paths, no provider credentials and no network calls.
It then ran the existing regressions with `.venv/bin/python -m pytest -q -ra -p no:cacheprovider` and isolated
`--basetemp`/JUnit output, selecting the four named regressions above plus
`test_idx3_real_page_success_has_the_correct_cookie_context` from `tests/test_normal_report_accuracy.py`.
Result: **13 passed, 0 failed, 0 skipped in 2.33 seconds**, with one existing Starlette/httpx deprecation warning.
No full suite, real audit, provider request, PDF generation or release verification was run for this skill installation.
