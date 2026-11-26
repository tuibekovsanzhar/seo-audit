# Accuracy first: rule maturity, the team's pass conditions, and a rule-approval loop — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. In this repository the project workflow also applies: `maya-implementer` handoff format per task, `maya-verifier` at the end (`tools/maya-audit/AGENTS.md`).

**Goal:** A client card comes only from a rule the SEO team has not found wrong; every rule can be approved or questioned by the team from one sheet; each rule shows the team's own pass condition beside Maya's verdict.

**Architecture:** A generated register (`rule_maturity.json`, built from `docs/expert-reviews/`) gives each rule a level — `approved`, `disputed` or `unreviewed` — combined at run time with the team's explicit decisions in `rule_approval.json`. `client_selection.confirm_reason` sends a finding of a `disputed` rule (and, under the strict policy, an `unreviewed` one) to "Teyit edin"; nothing is deleted and no severity changes. The team file gets a "Kural onayı" sheet (one row per rule in the audit, with the team's pass condition from the 165-item checklist), and a tool writes the team's decisions from that sheet back into `rule_approval.json`.

**Tech Stack:** Python 3.11+, pytest, the project's own `maya_audit.xlsx` (read and write; no openpyxl).

**Spec:** Research and diagnosis in this conversation's plan (owner, 2026-11-26): 94 expert-reviewed cards, 31% correct (`docs/expert-reviews/ACCURACY.md`); 333 rules in 56 checks, 51 reviewed, 0 approved (`rule_approval.json`); 168 "agent default" choices in `docs/DECISIONS.md`; the team checklist's "NASIL KONTROL EDİLİR?", "Beklenen / geçme koşulu" and "Hata varsa yapılacak aksiyon" columns are not in the repository (`checklist_items.json` holds id, name, priority and mapping only); Efsa's review `Maya_Audit_Revision_Compliance_and_Architecture_2026-11-19_EN.md` (A1, A8). Recorded as DECISIONS 378 in Task 6.

## Global Constraints

- Paths below are relative to `tools/maya-audit/`. Run everything from there with `.venv/bin/python`; never create or upgrade the venv.
- Tests never use the real `.env`, a live site or a paid provider (`tests/conftest.py` already isolates this). No CLI or web run in this plan needs a network.
- Severity is the engine's: nothing here raises or lowers a severity, and nothing S1/S2 is ever cut (AGENTS.md preamble 3, 4). Moving a group to "Teyit edin" is not a cut: DECISIONS 367 still gives a High or P0/P1 confirm group a card slot ("confirm first").
- `report.json` does not change shape: no schema bump. All new behaviour is in the client selection and the team file.
- A person's manual check wins: a finding confirmed in `review.json` ("Teyit edildi") is a card whatever its rule's level.
- Turkish and English labels are added together (`tests/test_team_report.py` rejects a missing language).
- Approval thresholds are agent defaults until the owner confirms them: `APPROVE_MIN_CORRECT = 3`, `APPROVE_MIN_BRANDS = 2`, policy for unreviewed rules `"card"` (today's behaviour). Say so in DECISIONS 378.
- No brand name, address or fixed title in engine code (global rules, as every DECISIONS entry since 337).

## Review Focus

- A merged group (MERGE_GROUPS) with one disputed member and one approved member: the whole group goes to "Teyit edin" (conservative). Test in Task 2.
- A finding with no `rule_id`, or a rule id that appears in no review: level `unreviewed`, no exception. Test in Task 1.
- A disputed rule's finding that a person confirmed in `review.json`: stays a card. Test in Task 2.
- An installed package without the `docs/` folder: maturity still works from the packaged `rule_maturity.json`. Test in Task 1 (monkeypatch the reviews folder away).
- The client Ek never contains "Kural onayı" (team file only), in either language. Test in Task 4.

---

### Task 0: Wire the expert lock (owner, on the computer that holds the saved audits)

No code. The lock exists (DECISIONS 373) but has never run here: `tests/test_expert_lock.py` errors with "the frozen expert set is missing", and `~/.maya-audit/web` on this computer holds no audits. Everything later is measured against it.

- [ ] **Step 1: Freeze the four noted audits** (reads `~/.maya-audit/web` only; sends nothing)

```sh
cd tools/maya-audit
export MAYA_AUDIT_BENCHMARK_DIR=~/maya-expert-set
.venv/bin/python -m scripts.real_sites_benchmark freeze-expert
```
Expected: a JSON manifest listing 2e5829fb, fee70191, 536b4b64, 342a0b14.

- [ ] **Step 2: Check every label on the current engine**

Run: `.venv/bin/python -m scripts.real_sites_benchmark expert`
Expected last line: `83 labels: 83 hold, 0 red` (any RED line is a regression to fix before Task 1 is merged).

- [ ] **Step 3: Make CI run it.** `tar -czf maya-expert-set.tgz -C ~/maya-expert-set .`, upload to private storage the owner chooses (no public link; it holds client pages), and set the repository secret `MAYA_AUDIT_BENCHMARK_URL` to its download address. Expected: the next CI run has no "Expert lock not run" warning.

---

### Task 1: Rule maturity register

**Files:**
- Create: `scripts/rule_maturity.py`, `maya_audit/rule_maturity.py`, `maya_audit/rule_maturity.json` (generated, committed)
- Modify: `maya_audit/rule_approval.json` (add `"policy": {"unreviewed": "card"}`), `pyproject.toml` (package-data: add `"rule_maturity.json"`)
- Test: `tests/test_rule_maturity.py`

**Interfaces:**
- Produces:
  - `scripts/rule_maturity.py`: `build() -> dict` and `__main__` writing `maya_audit/rule_maturity.json` as `{"_about": str, "rules": {rule_id: {"correct": int, "wrong": int, "incomplete": int, "wording": int, "brands_correct": [str], "latest": {"verdict": str, "review": str, "on": "YYYY-MM-DD"}}}}`. Reviews are read from `docs/expert-reviews/*.json`, ordered by `reviewed_on` then file name; a card counts once per id in its `rule_ids`; the brand is the file name before its first `-`.
  - `maya_audit/rule_maturity.py`:
    - `APPROVE_MIN_CORRECT = 3`, `APPROVE_MIN_BRANDS = 2`
    - `stats(rule_id: str | None) -> dict | None` (the register row)
    - `level(rule_id: str | None) -> str` — `"approved"` if the rule is in `rule_approval.json` `approved`, or `correct >= 3`, `len(brands_correct) >= 2` and latest verdict in (`correct`, `wording`); else `"disputed"` if it is in `questioned` or its latest verdict is `wrong`; else `"unreviewed"`. Explicit `approved` beats everything.
    - `policy() -> str` — `rule_approval.json` `policy.unreviewed`, `"card"` when absent; only `"card"` or `"confirm"` are valid (anything else raises `ValueError` naming the file).
  - Reads only packaged JSON at run time (never `docs/`).

- [ ] **Step 1: Write the failing tests** in `tests/test_rule_maturity.py`:
  - `test_register_matches_the_expert_reviews`: `scripts.rule_maturity.build() == json.load(maya_audit/rule_maturity.json)` (same pattern as `tests/test_expert_review_340.py`).
  - `test_levels_on_todays_reviews`: `level("str16.shared") == level("str7.over_100kb") == "approved"`; `level("str5.names") == level("tseo1.head_closed_later") == "disputed"`; `level("str14.no_text") == "unreviewed"` (latest incomplete); `level("idx5.stamped") == "disputed"` (questioned); `level(None) == level("no.such_rule") == "unreviewed"`.
  - `test_explicit_approval_beats_a_wrong_verdict(monkeypatch)`: with `rule_approval._data` patched to `{"approved": {"str5.names": {...}}}`, `level("str5.names") == "approved"`.
  - `test_works_without_the_docs_folder(monkeypatch, tmp_path)`: point `scripts.rule_maturity.FOLDER` at an empty `tmp_path`; `maya_audit.rule_maturity.level("str16.shared") == "approved"` still.
  - `test_policy_default_and_invalid_value(monkeypatch)`: absent → `"card"`; `"maybe"` → `ValueError`.

- [ ] **Step 2: Run them to see them fail**
Run: `.venv/bin/python -m pytest tests/test_rule_maturity.py -q`
Expected: FAIL (`No module named 'maya_audit.rule_maturity'`).

- [ ] **Step 3: Implement** the two modules, run `.venv/bin/python scripts/rule_maturity.py` to write the JSON, add the policy key and the package-data entry. Clear `lru_cache`s in tests that monkeypatch (`rule_approval._data.cache_clear()`).

- [ ] **Step 4: Run the tests and the distribution contract**
Run: `.venv/bin/python -m pytest tests/test_rule_maturity.py tests/test_distribution_contract.py tests/test_expert_review_340.py -q`
Expected: all pass.

- [ ] **Step 5: Commit** — `git commit -m "Rule maturity register from the expert reviews: approved, disputed, unreviewed (DECISIONS 378)"`

---

### Task 2: A disputed rule goes to "Teyit edin"

**Files:**
- Modify: `maya_audit/client_selection.py:163-184` (`confirm_reason`), `maya_audit_web/team_report/refs/etiketler.json` (`confirm_reasons`, tr ~line 370 and en ~line 880), `maya_audit/client_appendix.py:128-135` and `:177-184` (`reason` words, tr and en)
- Test: `tests/test_rule_maturity.py` (append)

**Interfaces:**
- Consumes: `rule_maturity.level`, `rule_maturity.policy` (Task 1).
- Produces: two new confirm reasons, `"disputed_rule"` and `"unreviewed_rule"`, placed in `confirm_reason` right after the manual-check line (a confirmed finding returns None first).

Exact wording (agent default, owner may edit):
- etiketler tr: `"disputed_rule": "Doğrulama bekliyor: SEO ekibi bu kuralın önceki bir sonucunu hatalı buldu"`, `"unreviewed_rule": "Doğrulama bekliyor: kural SEO ekibince henüz onaylanmadı"`
- etiketler en: `"disputed_rule": "Awaiting confirmation: the SEO team found an earlier result of this rule wrong"`, `"unreviewed_rule": "Awaiting confirmation: the SEO team has not approved this rule yet"`
- client_appendix tr: `"disputed_rule": "SEO ekibi kuralın önceki sonucunu hatalı buldu (onay bekliyor)"`, `"unreviewed_rule": "kural henüz onaylanmadı"`; en: `"disputed_rule": "the SEO team found an earlier result of this rule wrong (awaiting approval)"`, `"unreviewed_rule": "rule not approved yet"`

- [ ] **Step 1: Write the failing tests** (helpers `report`, `finding`, `SITE` from `tests/test_v03_client_report.py`):
  - `test_a_disputed_rule_is_confirm_not_a_card`: `cs.select(report([finding("A", "str5.names", "S4", urls=[SITE + "/a"], check="STR-5"), finding("B", "str16.shared", "S4", urls=[SITE + "/a"], check="STR-16")]))` → group A `placement == "confirm"` and `confirm_reason == "disputed_rule"`; group B `placement == "card"`.
  - `test_a_high_disputed_finding_still_takes_a_card_slot`: same with A at `"S2"` → A has `card` set and `issue_type == "warning"` (DECISIONS 367 path), so nothing S1/S2 disappears.
  - `test_a_person_confirmed_disputed_finding_is_a_card`: pass `confirmations` marking A confirmed (use the shape `client_selection.manual` reads; see `tests/test_review_compliance_373.py`) → A `placement == "card"`.
  - `test_a_merged_group_with_one_disputed_member_waits`: two findings of one merge group (`client_selection.MERGE_GROUPS`, e.g. `template_meta`: `str1.shared` + a `str16.shared`) where one rule is patched disputed → the group's placement is `"confirm"`.
  - `test_strict_policy_sends_unreviewed_rules_to_confirm(monkeypatch)`: patch `rule_maturity.policy` to return `"confirm"` → an `str14.no_text` S4 finding gets `confirm_reason == "unreviewed_rule"`; with `"card"` it is a card.
  - `test_every_confirm_reason_has_words_in_both_languages`: for `"disputed_rule"` and `"unreviewed_rule"`, present and non-empty in both `etiketler.json` tables and both `client_appendix` `reason` dicts.

- [ ] **Step 2: Run to see them fail**
Run: `.venv/bin/python -m pytest tests/test_rule_maturity.py -q -k "confirm or card or merged or strict or words"`
Expected: FAIL (reason is None / missing key).

- [ ] **Step 3: Implement** the two branches in `confirm_reason` and the four word tables.

- [ ] **Step 4: Run the new tests, then the client-report suites that read placements**
Run: `.venv/bin/python -m pytest tests/test_rule_maturity.py tests/test_v03_client_report.py tests/test_review_compliance_373.py tests/test_team_report.py -q`
Expected: all pass. A failure in an older test that pinned a disputed rule (`str5.names`, `tseo1.head_closed_*`, `str2.hidden_h1`, `prf1.*` …) as a card is expected: update that assertion to the confirm placement and name it in the commit message; never change the rule's level to make it pass.

- [ ] **Step 5: Commit** — `git commit -m "A finding of a rule the SEO team found wrong waits in Teyit edin; strict policy option for unreviewed rules (DECISIONS 378)"`

---

### Task 3: The team's checklist method in the repository

**Files:**
- Create: `scripts/checklist_method.py`, `maya_audit/checklist_method.json` (generated, committed)
- Modify: `maya_audit/checklist.py` (add the accessor), `pyproject.toml` (package-data: add `"checklist_method.json"`)
- Test: `tests/test_checklist_method.py`

**Interfaces:**
- Produces:
  - `scripts/checklist_method.py <path to SEO_Audit_Checklist.xlsx>`: reads sheet `Sayfa1` with `maya_audit.xlsx.read`; header row `ID | İş grubu | Kontrol maddesi | NASIL KONTROL EDİLİR? | Beklenen / geçme koşulu | Hata varsa yapılacak aksiyon | Araç / veri | Uygulanabilirlik | Varsayılan öncelik | Önerilen sıklık` (columns located by header text, not position); writes `{"source": "<file name>, <date>", "items": {"SEO-001": {"how": str, "pass": str, "action": str, "tool": str, "frequency": str}}}`.
  - `maya_audit.checklist.method(item_id: str) -> dict | None`
  - `maya_audit.checklist.items_for_rule(rule_id: str | None, check_id: str | None) -> list[dict]` — every checklist item whose `rules` has a prefix of `rule_id`, or whose `rules` is empty and whose `checks` holds `check_id`; each as `{"id", "item", "pass"}`, in item-id order.
- Source file: the team's `SEO_Audit_Checklist (1).xlsx` from the SEO_AUDIT Drive folder (11 Nov). Its 165 ids, names and priorities equal `checklist_items.json` (checked on 2026-11-26), so only the method columns are new.

- [ ] **Step 1: Write the failing tests:**
  - `test_every_checklist_item_has_the_teams_method`: for every id in `checklist_items.json`, `method(id)` is not None and `method(id)["pass"]` is non-empty.
  - `test_items_for_rule`: `items_for_rule("idx2.temporary", "IDX-2")` contains `SEO-009` with item `"Tek tercih edilen host"`; `items_for_rule(None, None) == []`.
  - `test_the_builder_reads_columns_by_header(tmp_path)`: write a two-row workbook with `maya_audit.xlsx.workbook` whose columns are in a different order → `build(path)["items"]["SEO-001"]["pass"]` is the value under the "Beklenen / geçme koşulu" header.

- [ ] **Step 2: Run to see them fail**
Run: `.venv/bin/python -m pytest tests/test_checklist_method.py -q`
Expected: FAIL (`method` not defined).

- [ ] **Step 3: Implement**, then generate: `.venv/bin/python scripts/checklist_method.py "<path>/SEO_Audit_Checklist (1).xlsx"`.

- [ ] **Step 4: Run the tests and the distribution contract**
Run: `.venv/bin/python -m pytest tests/test_checklist_method.py tests/test_distribution_contract.py -q`
Expected: all pass.

- [ ] **Step 5: Commit** — `git commit -m "The SEO team's checklist method (how to check, pass condition, action) in the repository (DECISIONS 378)"`

---

### Task 4: "Kural onayı" sheet in the team file

**Files:**
- Create: `maya_audit/rule_sheet.py`
- Modify: `maya_audit/client_appendix.py` (~line 945: append the sheet to `team`, beside the fix log), `maya_audit/ek_frame.py:56` (`INTERNAL`: add `"Kural onayı"`, `"Rule approval"`)
- Test: `tests/test_rule_sheet.py`

**Interfaces:**
- Consumes: `rule_maturity.level`, `rule_maturity.stats` (Task 1), `checklist.items_for_rule` (Task 3), the selection's `groups` (`client_selection.select(...)["groups"]`, each with `members`, `placement`, `urls`).
- Produces: `rule_sheet.sheet(selection: dict, lang: str = "tr") -> dict | None` — one row per distinct `rule_id` among the groups' members (None when there is none), ordered disputed, unreviewed, approved, then rule id. Header tr: `["Kural", "Kontrol", "Bu denetimde", "Kontrol listesi maddesi", "Ekibin geçme koşulu", "Durum", "Uzman sonuçları", "Son uzman kararı", "Karar", "Not"]`; en: `["Rule", "Check", "In this audit", "Checklist item", "Team's pass condition", "Status", "Expert results", "Latest expert verdict", "Decision", "Note"]`. "Bu denetimde": `"{groups} grup · {addresses} adres · {placement words}"`. "Durum" words tr `{"approved": "Onaylı", "disputed": "Tartışmalı", "unreviewed": "İncelenmedi"}`, en `{"approved": "Approved", "disputed": "Disputed", "unreviewed": "Not reviewed"}`. "Uzman sonuçları": `"3 doğru · 1 yanlış · 0 eksik"` (en `"3 correct · 1 wrong · 0 incomplete"`), empty when never reviewed. "Karar" is empty with a dropdown `["Onayla", "Sorgula"]` (en `["Approve", "Question"]`) over its column (`validations` as in DECISIONS 324). Sheet name `"Kural onayı"` / `"Rule approval"`.

- [ ] **Step 1: Write the failing tests:**
  - `test_one_row_per_rule_with_the_teams_pass_condition`: a selection from `report([...str5.names..., ...idx2.temporary...])` → two rows; the `idx2.temporary` row's "Kontrol listesi maddesi" starts with `"SEO-009"` and its "Ekibin geçme koşulu" equals `checklist.method("SEO-009")["pass"]`; the `str5.names` row is first with "Durum" `"Tartışmalı"`.
  - `test_decision_column_has_the_dropdown`: the sheet's `validations` has one entry whose `list == ["Onayla", "Sorgula"]` and whose `ref` starts at column I.
  - `test_the_client_ek_never_holds_the_rule_sheet`: build the appendix for both `lang="tr"` and `"en"` (as `tests/test_review_compliance_373.py` does) → `"Kural onayı"` and `"Rule approval"` are not sheet names of `xlsx.read(result["client"])` and one of them is in `xlsx.read(result["team"])`.

- [ ] **Step 2: Run to see them fail**
Run: `.venv/bin/python -m pytest tests/test_rule_sheet.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement** `rule_sheet.sheet` and the two one-line wirings.

- [ ] **Step 4: Run the tests and the appendix suites**
Run: `.venv/bin/python -m pytest tests/test_rule_sheet.py tests/test_review_compliance_373.py tests/test_v03_client_report.py -q`
Expected: all pass.

- [ ] **Step 5: Commit** — `git commit -m "Kural onayı: every rule of the audit with the team's pass condition, its status and a decision column, in the team file (DECISIONS 378)"`

---

### Task 5: Import the team's rule decisions

**Files:**
- Create: `tools/import_rule_approvals.py`
- Test: `tests/test_rule_sheet.py` (append)

**Interfaces:**
- Consumes: the "Kural onayı" / "Rule approval" sheet of a team file a reviewer saved (Task 4 layout; columns found by header text).
- Produces: `.venv/bin/python tools/import_rule_approvals.py TEAM.xlsx --by "<name>" [--write]` and an importable `decisions(path) -> tuple[list[dict], list[str]]` (rows `{"rule", "decision": "approve"|"question", "note"}`, and the problems: an unknown decision word or a rule id `rule_ids.json` does not hold). With `--write`: "Onayla"/"Approve" puts the rule under `approved` as `{"by", "on": today, "note"}` and removes it from `questioned`; "Sorgula"/"Question" the reverse. A blank decision changes nothing. Without `--write` it prints what would change. Exit 1 when a problem was found (nothing written).

- [ ] **Step 1: Write the failing tests:**
  - `test_decisions_are_read_by_header`: a sheet with Karar "Onayla" on `str16.shared`, "Sorgula" on `str2.no_h1`, blank on a third → two decisions, no problems.
  - `test_an_unknown_word_or_rule_is_a_problem`: Karar "Belki" and rule `no.such_rule` → two problems; `main([... "--write"])` returns 1 and `rule_approval.json` is unchanged (point the tool's `FILE` at a `tmp_path` copy).
  - `test_write_moves_a_rule_between_approved_and_questioned(tmp_path)`: on a copy where `idx5.stamped` is questioned, an "Onayla" row → it is under `approved` with `by` and `on`, and no longer under `questioned`; `rule_maturity.level("idx5.stamped") == "approved"` after clearing caches.

- [ ] **Step 2: Run to see them fail**
Run: `.venv/bin/python -m pytest tests/test_rule_sheet.py -q -k "decisions or problem or write"`
Expected: FAIL.

- [ ] **Step 3: Implement** the tool (load it in tests with `importlib.util.spec_from_file_location`, as `tests/test_review_compliance_373.py` loads `tools/import_notes.py`).

- [ ] **Step 4: Run**
Run: `.venv/bin/python -m pytest tests/test_rule_sheet.py tests/test_rule_maturity.py -q`
Expected: all pass.

- [ ] **Step 5: Commit** — `git commit -m "tools/import_rule_approvals.py: the team's Onayla/Sorgula decisions into rule_approval.json (DECISIONS 378)"`

---

### Task 6: Decision record, roadmap and verification

**Files:**
- Modify: `docs/DECISIONS.md` (append 378), `docs/ROADMAP-v0.3.md` (one row: "Accuracy first"), `docs/expert-reviews/ACCURACY.md` (regenerate only if reviews changed)

- [ ] **Step 1: Write DECISIONS 378** in the file's style: who asked (owner, 2026-11-26, from the SEO team's feedback that the same errors recur), "Global for every audit", the three levels and their rule, the policy switch, the new confirm reasons and their words, the sheet and the import tool, the files and tests; and which values are agent defaults (`APPROVE_MIN_CORRECT = 3`, `APPROVE_MIN_BRANDS = 2`, policy `"card"`, all wording). State today's effect: 2 approved, 18 disputed, 31 reviewed-not-proven, 282 never reviewed.

- [ ] **Step 2: Full suite and platform check** (AGENTS.md preamble 5 and 8)

Run: `.venv/bin/python -m pytest -q -m "not slow and not timing"`
Expected: no failures. `tests/test_expert_lock.py` errors unless Task 0 was done on this computer: report it as "NOT RUN (frozen set missing)", never as passed.

Run: `ruff check --select E9,F821,F841 maya_audit maya_audit_web scripts tools`
Expected: `All checks passed!` Ruff is not installed on this computer (checked 2026-11-26) and the venv must not be changed without the owner's approval: if it is still missing, write "ruff: NOT RUN" in the handoff and ask the owner, never imply it passed.

Run the provider-free CLI check from AGENTS.md preamble 8 against a `fakeserver` site, then build the team report and Ek from its `report.json` with `maya_audit_web/team_report` (no network) and confirm the team file has "Kural onayı" and the client Ek does not.

- [ ] **Step 3: Commit** — `git commit -m "DECISIONS 378 and roadmap: accuracy first"`

## Owner decisions this plan leaves open (defaults in brackets)

1. Policy for never-reviewed rules: keep them as cards, or send them to "Teyit edin" until approved [card]. Strict mode would leave most audits with very few cards until the team works through the "Kural onayı" sheet.
2. Automatic approval: 3 correct verdicts on 2 brands with no later "wrong" [yes, 3 and 2].
3. Who may approve in the sheet [İlginay and Efsa; the tool records the name given with `--by`].
4. Where the frozen expert set is stored for CI (Task 0) [owner's private storage].

## Result (2026-11-26, DECISIONS 378)

Tasks 1-6 built on branch `accuracy-first`; Task 0 is the owner's. Where the build differs from the plan above:

- **Confirm-reason wording is client-safe.** "Teyit edin" lines reach the client report, so they do not say the team
  found the rule wrong: "Doğrulama bekliyor: kural SEO ekibinin incelemesinde" / "… kural henüz uzman onayından
  geçmedi". The team's detail (verdicts, latest review) is in "Kural onayı".
- **A merge group with one disputed member:** the confirm reason is part of `group_key`, so only the disputed member
  waits; the other member keeps its card (the plan expected the whole group to wait). This is how every other confirm
  reason already behaves.
- **Checklist method source:** the team's xlsx could not be downloaded in this session; the pass condition and check
  method of all 165 items were read from the Drive file's view and written to `checklist_method.json`. The builder
  (`scripts/checklist_method.py`) adds how/action/tool/frequency when run on the file.
- **Levels today:** 2 approved, 19 disputed (18 last found wrong + idx5.stamped, questioned), 30 reviewed without
  proof, 311 of 332 catalogue rules never reviewed.

### Owner decisions (2026-11-26)

1. Never-reviewed rules: stay cards for now (`"card"`); tighten once the team has approved the rules most audits show. The middle policy `"confirm_below_high"` (Medium and Low wait, High and Blocker stay cards) is built for that step.
2. Automatic approval: 3 correct on 2 brands, as planned.
3. Who approves: the name given with `--by` is recorded (unchanged).
4. Where the frozen expert set is stored for CI: open.
