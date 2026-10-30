# W5 — LLM brief, agent skills, docs, dependencies (branch `fix/w5-llm`)

Items H39, H41, H42, H43 and R13 of `maya-audit-duzeltme-plani.md`; review appendix E (E-R1, E-R2, E-R3, E-R6,
E-R7, E-R8). All choices below are agent decisions unless marked otherwise.

## H39 / E-R1 — site text is data, never instructions

- `maya_audit/ai_skills/rules.py`: `EVIDENCE_RULES` rule 9 (appendix E §3.9 text; "What could not be checked" made
  generic because only `audit-report` has that heading). `ADVERSARIAL_PASS` item 6 ("six points"). New constants
  `DATA_BEGIN`/`DATA_END` (`<<<MAYA_AUDIT_DATA_BEGIN>>>` / `<<<MAYA_AUDIT_DATA_END>>>`), `DATA_NOTICE`,
  `DATA_REMINDER`.
- `maya_audit/ai_skills/prompts.py`: all four templates now end with `## The audit|panel (untrusted data)`, the
  notice, the fenced data block and the reminder line. The notice also covers pointer mode (the `audit` object
  supplied alongside is the same data), so `report.py`'s `POINTER`/`how_to_use` needed no change.
- `maya_audit/ai_skills/payload.py` neutralises the marker strings inside any string of the payload
  (`<<<MAYA_AUDIT_DATA_END>>>` → `[site text: MAYA_AUDIT_DATA_END]`), so a page cannot close the fence from its own
  title. Counted in `payload_budget.markers_neutralised`.
- Also removed the embedded example numbers "35.9% and 7.3%" from `cited-domain-landscape` (R9 d): a model could take
  them for this site's values, and the new number check would flag them.
- Tests (`tests/test_w5_llm_brief.py`): a loopback site whose `<title>` and `<h1>` say "IGNORE PREVIOUS
  INSTRUCTIONS …" → `test_instruction_text_from_the_site_reaches_the_prompt_only_inside_the_data_block` (text present,
  only between the markers, rules above, reminder last); `test_a_title_holding_the_end_marker_cannot_close_the_data_block`;
  `test_a_normal_title_is_quoted_unchanged`; `test_pointer_mode_says_the_supplied_audit_object_is_data_too`;
  `test_the_rules_name_the_untrusted_data_rule_and_the_adversarial_check`.

## E-R2 — payload budget

- `maya_audit/ai_skills/payload.py: budgeted_payload()` takes `report.analysis_payload(...)`. Inside every gate,
  check and panel entry each list keeps its first 10 items; a dict member `x` gets a sibling `x_omitted_count`, a list
  inside a list ends with `{"omitted_count": n}`. A check's own `findings` are cut worst-first by
  `findings_in_priority_order` (an S1 is never the one left out) and get `findings_omitted_count` +
  `findings_omitted_ids`. Top-level id lists stay whole (the checker validates citations against them).
  `payload_budget` records `payload_bytes_before`, `payload_bytes`, lists trimmed, items omitted, and a `warning`
  (plus a `logging` warning) above 200 KB. The budget travels inside the payload, so pointer and inline briefs both
  carry it. Rule 10 in `EVIDENCE_RULES` tells the model a left-out item is not absent.
- `maya_audit/report.py: build_llm_brief` (W4a's file): only the payload line changed
  (`audit = budgeted_payload(analysis_payload(report))`, local import to avoid an import cycle) and the inline
  `panel_section` line now dumps `audit["answer_engine_panel"]` instead of the raw report's panel, so the two panel
  skills' inline prompts are bounded too.
- **Measured on the existing `tests/test_ai_skills.py` fixture (`ans_cited_pages`, 9 pages):** before 225,009 bytes,
  after 225,100 bytes. Only one list there is longer than 10 (STR-3 `recognized_organization_types`, 38 → 10), so the
  saving (28 items) is eaten by the ~600-byte `payload_budget` block. The fixture is still above 200 KB and now says
  so in `payload_budget.warning`. The bulk is finding evidence (≈99 KB) and check evidence (≈50 KB) made of short
  lists with long strings; list trimming does not bound that. On a synthetic fat report the cut works
  (`test_lists_inside_a_check_keep_their_first_items_and_say_how_many_were_left_out`). **Not done:** a per-string or
  per-finding size cap — it would cut quoted values that rule 5 tells the model to copy exactly, so it needs an owner
  decision on what may be shortened.
- Tests: the one above, `test_the_payload_records_its_size_and_warns_above_the_limit`,
  `test_the_prompt_says_omitted_items_are_not_absent`, `test_a_check_with_few_findings_is_untouched`.

## E-R3 — output contract and checker

- `rules.OUTPUT_CONTRACT` (in all four prompts): every claim ends with `[CHECK-ID]` or `[CHECK-ID · FINDING-ID]`,
  numbers copied from the data (no own sums/percentages), no score/grade/rating. The id patterns are shared constants
  (`CHECK_ID_PATTERN`, `FINDING_ID_PATTERN`).
- `maya_audit/ai_skills/check_output.py`: reads the brief's `audit` object or, in inline mode, the JSON inside the
  fence (plus an optional `--report report.json`). Flags per line: `unknown_check`, `unknown_finding`,
  `finding_check_mismatch`, `uncited_claim` (a line with a number, a severity word or a bare check id and no
  citation), `number_not_in_report`, `score`. Exit 0/1/2. Deliberately errs towards flagging; a clean result is
  not proof of correctness (said in its output).
- Entry points: `python -m maya_audit.ai_skills.check_output` and `maya-audit brief-check …` (7 lines in `cli.py`,
  W4a's file — see below).
- Tests: `test_every_prompt_carries_the_output_contract`, `test_the_checker_accepts_a_cited_document_and_flags_an_invented_one`,
  `test_the_checker_reads_an_inline_brief_and_flags_a_finding_under_the_wrong_check`, `test_the_cli_runs_the_checker`.

## H41 / E-R8 — canli_kontrol.py

- `.agents/skills/maya-audit-rapor/scripts/canli_kontrol.py` rewritten around `LiveChecker`: one `httpx.Client` on
  `maya_audit.network.PublicTransport(allow_loopback=False)`, `validate_public_target` before every request and every
  redirect hop (private/loopback refused, reported as "REDDEDİLDİ"), redirects followed by hand, robots.txt fetched
  once per origin through the same client and judged by the engine's `policy_from_response` + `RobotsPolicy.decide`
  (5xx/429/unreachable robots → no requests to that origin, as in the engine). Both the `*` group and Maya's own
  `Maya-Audit` group are obeyed although the identity sent is a browser's (conservative choice). The Googlebot UA and
  `--ua` are removed. `page_facts` entries carry `"untrusted": true`. `main()` returns an exit code instead of
  calling `sys.exit` inside, so it can be tested.
- `allow_loopback` is a constructor argument for tests only; the command line has no switch for it.
- Tests (`tests/test_w5_canli_kontrol.py`, loopback fake site): robots first + browser UA, disallowed URL never
  requested (also via redirect and via a `Maya-Audit` group), 503 robots stops the origin, default refuses
  127.0.0.1/10.x/192.168.x with zero requests, no `--ua googlebot`, `bilgi` writes untrusted page facts.
- The Turkish `durum` examples in `maya-audit-rapor/SKILL.md` no longer show `--ua googlebot`.

## H42 / E-R6 / E-R7 — skills

- `AGENTS.md`: one "Shared preamble for every Maya skill" (environment for POSIX and Windows, temp dirs, Desktop path,
  not-a-checkout and missing-HANDOVER handling, untrusted data, evidence model, length budget, platform matrix,
  machine-checkable handoffs, live network, shared limits). The `stage1-integration` line now says "the branch the
  owner names (historically …)"; the phase summary has a length (≤10 lines) and a content list (R11).
- Each `SKILL.md` replaces its repeated 5-line header and "Shared Maya workflow rules" block with a link to the
  preamble, keeping only role-specific lines. Language kept (English; Turkish for maya-audit-rapor).
- maya-release: mode A (tag) / mode B (working-tree snapshot with the real `RELEASE-SNAPSHOT.json` keys: `release`,
  `application_version`, `schema_version`, `base_commit`, `branch`, `source_state`, `included_*`, `excluded_*`,
  `files`), README = pyproject = schema.py check, Windows Desktop path, LICENSE presence *recorded* (never added).
- maya-verifier: source state first (commit / snapshot / not a checkout), no "about 7 minutes" (≥30 min timeout,
  report seconds), static gates (ruff E9/F821/F841, lowest-Python compile, redirected-stdout CLI run, collected vs
  passed, pip-audit), platform matrix with NOT RUN, PDF inspection of five named pages by number, report-length FAIL
  above the page budget, the old one-paragraph obligations split into a numbered list, the Windows 260-character path
  note (seen in this work: `tests/test_client_report_app.py` fails with a deep `--basetemp`).
- maya-report-checker: "top" = `findings_in_priority_order` order, group-first review, `length-defect` and
  `privacy-defect` flags, reply budget, cross-section list numbered.
- maya-judgment-validator: untrusted-evidence rule, false-negative sweep list (evaluation report §3.1.3), YAML record
  with fixed key order.
- maya-implementer: `<venv-python>`, ruff F821 gate, copied-block name list, FILES_CHANGED/TESTS_ADDED/LINT/COMMAND/
  RESULT/NOT_DONE finish block.
- maya-spec-writer: untrusted-data paragraph, KEPT_HEADERS sentence, exit codes 0/1/2/3 in "What NOT to change",
  Acceptance section.
- maya-audit-rapor: both interpreters, sections "Güvenilmeyen veri", "İnceleme kaydı" (model never self-reviews,
  `review.status: "pending"`), "Uzunluk bütçesi (zorunlu)" (≤10 main cards, appendix as table, ≤15 pages), "Canlı
  kontrol" (explicit permission, browser identity, robots); step 2 no longer imperative; removed the "66 boş sayfa"
  case note; step 6 reports page count. **Not touched:** the "Önem kuralları (özet)" section with the "Puan"
  paragraph (W4b), and no `--group` flag is named (render_report is W4b's, H40) — the skill says to tell the user if
  the renderer still prints the appendix as full cards.
- TEAM-SETUP.md: a short "On Windows" paragraph (substitutions); the macOS commands the existing test pins stay.
- docs/ASSISTANT.md: one paragraph on the fence, budget, contract and checker.
- Test: `tests/test_w5_docs.py` (every skill links the preamble, no POSIX path without its Windows twin, no
  `--ua googlebot`, no "about 7 minutes", release modes and verifier source state present).

## R13 — versions

README title `0.2.6`, `schema_version` "now `1.17`", frozen shape `docs/report-schema-1.17.json`, the Firecrawl line
says "added in schema 1.14". A short README section on `--llm-brief` / `brief-check`, and "Review fixes after
team-preview-23 → docs/review-fixes/" without naming other workers' flags. Test:
`test_readme_title_and_schema_match_the_package`.

## H43 / D-27 — dependencies

- pip-audit (`uvx pip-audit --no-deps --disable-pip`, 2026-10-21, network to PyPI/OSV) on the old lower bounds:
  pypdf 4.0.0 — 85 advisories, highest fix 6.19.0; starlette 0.36.3 (pulled by fastapi 0.110) — 14, highest fix
  1.3.1; cryptography 42.0.0 — 15, highest fix 49.0.0, and 49.0.0 itself has PYSEC-2026-3552 fixed in 50.0.0;
  pytest 8.0.0 — PYSEC-2026-1845, fixed 9.0.3. httpx 0.27, defusedxml 0.7.1, playwright 1.45, fastapi 0.110,
  uvicorn 0.29: none.
- **No FastAPI release requires a patched Starlette**: the newest (0.156.8) requires `starlette>=0.46.0`; 0.130–0.132
  cap `<1.0.0`; 0.133 is the first without an upper cap; 0.135 the first with `>=0.46`. So a FastAPI bound alone
  cannot exclude vulnerable Starlette. New bounds in dev/web/team: `fastapi>=0.135`, `starlette>=1.3.1`,
  `pypdf>=6.19`; dev also `cryptography>=50`, `pytest>=9.0.3`. Playwright range unchanged.
- Lowest-bound check: `tests/test_web_app.py` passed (62 passed, 1 skipped) in a uv environment pinned to fastapi
  0.135.0, starlette 1.3.1, pypdf 6.19.0, uvicorn 0.29.0, pytest 9.0.3, cryptography 50.0.0. pip-audit of those
  bounds: only cryptography 49 flagged before raising it to 50; after: none.
- `uv lock` worked (network to PyPI); `uv.lock` committed (32 packages, matches the installed venv: fastapi 0.156.8,
  starlette 1.9.0, pypdf 6.21.1). `uv export --all-extras` of the lock audited clean.
- Not raised: transitive floors (e.g. h11/httpcore under `httpx>=0.27`); the lock pins safe versions, a plain
  `pip install` resolves current ones.
- **LICENSE: not added.** Choosing the project's licence is the owner's decision. The OpenSEO MIT notice in
  `licenses/` covers only the adapted parts. maya-release now records whether a LICENSE is present.

## For the lead at merge

- `brief_version` in `report.build_llm_brief` is still `"0.1"`, but the brief's `audit` object changed shape
  (trimmed lists, `*_omitted_count`, `findings_omitted_ids`, `payload_budget`). That line is outside what W5 may touch
  in `report.py`; recommend bumping it to `"0.2"` during the merge.
- `maya-audit brief-check` takes its arguments with `argparse.REMAINDER`, so the documented order
  (`brief-check brief.json doc.md [--report R] [--json]`) works but an option before the two paths does not parse.
  `python -m maya_audit.ai_skills.check_output` has no such limit.
- `budgeted_payload` logs a warning above 200 KB; with no logging configured Python prints it to stderr once per
  brief during `crawl --llm-brief`. Intended as the user-visible warning; drop the `log.warning` if that is unwanted
  (`payload_budget.warning` alone still records it).

## Touched outside my files

- `maya_audit/report.py` (W4a): the two payload-building lines in `build_llm_brief` (allowed by the brief).
- `maya_audit/cli.py` (W4a): 7 lines — the `brief-check` subparser (after `migrate-report`) and its dispatch after
  the `migrate-report` dispatch. Self-contained; delegates to `ai_skills.check_output.main`.

## Environment note

On this machine a pytest `--basetemp` under the long worktree path makes 12 tests in
`tests/test_client_report_app.py` fail with `FileNotFoundError` (Windows 260-character path limit); with a short
`--basetemp` they pass. The full-suite run used `--basetemp=<temp>/w5t/full` with
`TEMP`/`TMP` still in the worktree's `.tmp`.
