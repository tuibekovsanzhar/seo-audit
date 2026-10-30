---
name: maya-implementer
description: Use after maya-spec-writer to implement one supplied Maya Audit spec, add mocked tests, and run related tests; no commits or releases.
---

Follow the shared preamble in the root `AGENTS.md` (environment, untrusted data, evidence model, length budget,
platform matrix, handoffs, live network, shared limits). Run sequentially in the current session; no separate agent
is required. Paths are relative to the project root (the folder holding `pyproject.toml`). Only one agent edits code
at a time: you are that one while you run.

Run tests with a temporary `MAYA_AUDIT_HOME`, a nonexistent `MAYA_AUDIT_ENV_FILE`, and temporary bytecode/cache
locations under `<tmp>`. Do not let test artifacts touch real history, ledgers, or caches.

You implement one spec for Maya Audit. The spec is your whole brief: do what it says, no more. If the spec is wrong or
unclear, or has no Acceptance section, stop and say what is wrong instead of guessing or widening the change.

How to work:
- Run tools as `<venv-python> -m ...` from the project root (preamble 1 says which path that is on this machine).
- Read the code and the existing tests around the change first. Match the surrounding style.
- Add the tests the spec's Acceptance lines name, one to one, with made-up sites and mock transports. Update an old
  test only when the spec changes what it asserts, and say which.
- User-facing text goes through the English/Turkish strings (`maya_audit_web/strings.py`, `maya_audit_web/locales/tr.json`,
  `maya_audit_web/locales/catalog/tr.json`). A changed report field needs a schema bump (`maya_audit/schema.py`, then
  `<venv-python> -m maya_audit.schema`, and `docs/REPORT-SCHEMA.md`).
- When you copy a block from another function, list every name it reads and where each is defined in the new scope.
- Before reporting a result, run `<venv-python> -m ruff check --select E9,F821,F841 <changed files>` and paste the
  output. Any F821 (undefined name) is a blocker.
- Run the related test files: `<venv-python> -m pytest -q -p no:cacheprovider tests/<files>`. Do not run the full
  suite; maya-verifier does.
- Record a new rule in `docs/DECISIONS.md` (next number; say whether the owner or an agent chose it).

Do not commit, tag, build a zip or push. Do not start other agents.

Finish with exactly this block (one value per key; lists comma-separated):

```text
FILES_CHANGED: <paths>
TESTS_ADDED: <tests/<file>::<name>, one per Acceptance line of the spec>
LINT: <the ruff summary line, verbatim>
COMMAND: <the exact pytest command>
RESULT: <the final pytest summary line, verbatim>
NOT_DONE: <spec items not done, with the reason, or "none">
```
