# Baseline: call map and test state (stage 00)

Source: `maya-audit-0.2.8-w13-2026-10-28.zip`, committed as `a40500b` ("w13 baseline"). Package 0.2.8.
Interpreter: `.venv/bin/python` (CPython 3.13.1, macOS, Darwin 27.2). Built from the zip on 2026-10-28; not the
owner's historical `stage1-integration` branch. `HANDOVER.md` not available.

This map comes from `rg` over `maya_audit/`, `maya_audit_web/`, `maya_audit_web_lite.py`, `.agents/skills/*/scripts`,
`scripts/` and `tools/` (tests excluded). Line numbers are for `a40500b`; search by name, not by line.

## 1. Who runs an audit

| Entry point | Call | After the engine |
|---|---|---|
| CLI `crawl` | `cli.py:635` `run_audit(args.url, config)` | optional `firecrawl.reader.apply` (`cli.py:670`), then `build_report` (`cli.py:716`), `write_json` (`:733`), `affected_urls` companion (`:743`), `render_text` (`:675`) |
| CLI `batch` | `cli.py:566` → `batch.run` → `batch.py:163` `run_audit(brand.url, config)` | optional `fc_reader.apply` (`batch.py:174`), `build_report` (`:198`), `render_markdown` (`:199`), `write_json` (`:225`) to `<brand.slug>.json` |
| Web worker | `maya_audit_web/runner.py:369/380` `run_audit(..., Hooks(on_progress, should_stop))` | `firecrawl_reader.apply` (`runner.py:550`), `build_report` (`:434`), `render_markdown` (`:435`), `affected_urls` → `AFFECTED_JSON` (`:494`) |
| Lite web helper | `maya_audit_web_lite.py:66` spawns `python -m maya_audit crawl ... --json report.json` | CLI path above; "Save as PDF" is the browser's own print |
| Scripts (dev only) | `scripts/demo_*.py`, `stage1_preview.py`, `coverage_benchmark.py`, `real_sites_benchmark.py` | `build_report` + `write_json` directly; `real_sites_benchmark.py` is the only one that reaches real sites |

Three adapters (CLI, batch, web) each repeat the same tail: `run_audit` → optional provider `apply` → `build_report`
→ Markdown → files. There is no shared service between them yet (guide stage 05).

## 2. Inside `run_audit` (`audit.py:85`), the finalization order

Site checks, in this order (`audit.py:~253-283`):

1. `single_page.settle` → `root_cause.group` → `launch_gate.apply` → `severity.apply` (`apply_severity`)
2. `checks.index.broken_link_sources` — the pages to edit for IDX-6, after severity
3. answer-engine checks (ANS) built from the final site checks; `launch_gate.apply` + `apply_severity` on them
4. `rules.assign` (rule ids, from title patterns in `rule_ids.json`)
5. `facts.attach` → `facts.contract` (claims + `remediation` from `rule_actions.json`)
6. `checks.structure.annotate_page_types` (page kind per affected URL, for the release gate)
7. `verification.run(...)` — the controlled re-test I/O (`audit.py:279`), stored in `result.verification`

## 3. After a provider replaces checks: `firecrawl/reader.py::apply` (`:735-753`)

Re-runs: `coverage.restate_crawl_gap`, `single_page.settle`, (if replaced) `root_cause.group` + `launch_gate.apply`,
`apply_severity`, `rules.assign`, `facts.attach`.

**Not re-run:** `broken_link_sources`, `annotate_page_types`, `verification.run`. A check the reader replaces keeps the
verification record and page types computed for the version it replaced (or none). This is the guide's §2 finding;
confirmed in this source. Fix belongs to stage 04 (one shared finalization), not to stage 00/01.

## 4. Report building re-decides findings

`report.build_report` (`report.py:25`) and `_markdown_head` (`report.py:2338`, used by `render_markdown` and the short
Markdown) each call `judgments.qualify_checks` (`report.py:33`, `:2342`). `qualify_checks` (`judgments.py:320-350`)
deep-copies, runs `related_evidence.objects`, calls `qualify()` per finding — which may rewrite title, how_to_fix,
evidence, confidence and scope — then `apply_severity` and `rules.assign` again (not `facts.attach`, so remediation is the
engine's while the title may be the qualified one). So the JSON and the Markdown
each run their own qualification pass over the engine's checks. Other `qualify()` callers: `maya_audit_web/summary.py:122`,
`client_reporting/from_maya_report.py:203`; `judgments.py:288-300` (saved-report reprocessing: `apply_severity`,
`rules.assign`, `facts.attach` over dicts).

`release_gate.run` is called once, last, inside `build_report` (`report.py:76`) and stored as `report["release_gate"]`.
It never changes a finding.

## 5. Output and download paths vs the release gate

| Path | Code | Uses `release_gate` decision? |
|---|---|---|
| CLI `--json` | `cli.py:733-738` | prints a notice from `report["release_gate"]`; does not block writing |
| Web report PDF/MD/JSON download | `maya_audit_web/app.py:1316` `download` → `printable_html` (`:1280`) → `pdf.to_pdf` (`:1327`); MD/JSON served from saved files | **No.** Loads the report, renders, returns; the stored decision is not checked |
| Web print view | `app.py:1287` `printable` | No |
| Web client report export (html/pdf/json) | `app.py:1474` `export_client_report` → `client_reports.html` → `pdf.to_pdf` (`:1484`) | No central gate; `client_reports.py:284` runs `validate_cards.validate` (editorial check) |
| Client report CLI | `client_reporting/render_report.py:340` `to_pdf` | `validate_cards.validate` (`render_report.py:24`), not `release_gate` |
| Skill `maya-audit-pro` | `.agents/skills/maya-audit-pro/scripts/validate_data.py:56-81` loads `maya_audit.release_gate` and runs `gate.run(report, affected, data=d)`; refuses the PDF if the gate cannot load (`GATE_MISSING`) | **Yes** (only path that does) |
| Web comparison | `comparison.py:194` imports `release_gate.checklist` | reads the checklist only |

## 6. Data files the engine reads at run time

`rules._table` → `maya_audit/rule_ids.json` (raises `FileNotFoundError` when absent).
`facts._catalogue` → `maya_audit/rule_actions.json` (returns `{}` when absent or unreadable — a silent "no actions").
Both were missing from the 0.2.8 wheel (stage 01). `rule_ids.json` has 56 checks; `rule_actions.json` 73 actions.
`idx6.broken` (broken internal link) has a rule id but **no action entry**; `str2.no_h1`, `str2.empty_h1`,
`str2.home_hidden_h1` have actions. Relevant to M1.

## 7. Test baseline

See `docs/IMPLEMENTATION-STATUS.md`, stage 00.
