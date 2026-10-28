---
name: maya-release
description: Use only when the owner explicitly requests Maya Audit release preparation, a release tag, or a team-preview archive, after full verification passes.
---

Follow the shared preamble in the root `AGENTS.md` (environment, untrusted data, evidence model, length budget,
platform matrix, handoffs, live network, shared limits). Run sequentially in the current session; no separate agent
is required. Paths are relative to the project root (the folder holding `pyproject.toml`).

Run no release steps during ordinary setup or development. A baseline verifier PASS is insufficient.
Verify the exact release source state; any subsequent change requires full verification again. Do not overwrite an
existing Desktop archive. A failed verification stops the release; report it instead of weakening the gate.

# Maya Audit release

Do the steps in order. Stop at the first failure and tell the owner what failed; never release around a failure.

## Choose the mode first, and say it

- **Mode A — tagged release.** Commit, `git tag team-preview-N`, archive from the tag.
- **Mode B — working-tree checkpoint** (how team-preview-23 was built). No tag or commit. Write
  `RELEASE-SNAPSHOT.json` with `release`, `application_version`, `schema_version`, `base_commit`, `branch`,
  `source_state`, `included_modified_files`, `included_untracked_files`, `excluded_files`, `excluded_categories` and
  `files` (each included path → its SHA-256), and archive exactly those files.

Both modes need maya-verifier in full release mode on the same source state. Never mix them. Mode A needs a Git
checkout; in a folder that is not one, only mode B is possible (say so).

## Steps

1. **Pick N.** Mode A: `git tag --list 'team-preview-*'`; mode B: the `release` values of earlier
   `RELEASE-SNAPSHOT.json` / `docs/RELEASE-team-preview-*.md`. N is the next number. Never move or reuse an existing
   tag or number: a fix after a release is the next number (or `Nb`).
2. **Versions agree.** The title line of `README.md` names the version in `pyproject.toml`, and README's schema
   lines name `SCHEMA_VERSION` from `maya_audit/schema.py`. FAIL if they differ; fix README and re-verify.
3. **Folder name in the guide.** `TEAM-SETUP.md` must name `maya-audit-team-preview-N` everywhere. Change it if not.
4. **Release checklist.** Record, for the owner: whether a LICENSE file is present (choosing the licence is the
   owner's decision; never add one yourself), and whether CI is green on this commit or snapshot (or "CI: NOT RUN").
5. **Verifier passes.** Follow `maya-verifier` in full release mode in this session. Continue only on
   `VERDICT: PASS`. Mode A: nothing uncommitted that belongs in the release.
6. **Mode A — commit and tag.** Inspect the diff and existing index first. Stage only individually reviewed release
   files, never `git add .` or a broad directory list that could include unrelated work. Preserve unrelated staged and
   unstaged work. `HANDOVER.md`, `design-reference/` and `.claude/` stay out. Then `git tag team-preview-N`.
   **Mode B — snapshot.** Write `RELEASE-SNAPSHOT.json` as above; compute each SHA-256 from the file on disk.
   If step 2, 3 or 6 changed anything after the verifier ran, run the verifier again on the new source state.
7. **Archive to the Desktop** (`~/Desktop` on POSIX, `$env:USERPROFILE\Desktop` on Windows).
   Mode A: `git archive --format=zip --prefix=maya-audit-team-preview-N/ -o <Desktop>/maya-audit-team-preview-N.zip team-preview-N`.
   Mode B: a zip of exactly the files in `RELEASE-SNAPSHOT.json` under the prefix `maya-audit-team-preview-N/`.
8. **Clean-install test of that zip.** Unzip into `<tmp>` and follow TEAM-SETUP.md: a new venv there,
   `pip install -e ".[team]"`, start the demo app on port 8791 with `MAYA_AUDIT_HOME` in `<tmp>`, run one demo audit
   and fetch its PDF, stop the app; then `pip install -e ".[dev]"` and the full suite. Expect 0 failed and only the
   skips the guide announces.
9. **Tell the owner:** the mode, the tag and commit (mode A) or base commit and snapshot file (mode B), both test
   results as numbers, the zip's path, which older `maya-audit-team-preview-*.zip` files on the Desktop to delete (list
   them; do not delete them), the release checklist from step 4, what was not verified on real services, and what to
   re-test.

Rules: never push; never read or print `.env`; no real crawls or paid calls (pip is the only network use); never touch
the branch `pre-0.2.0-snapshot`; update `HANDOVER.md` on disk only where it exists (it is git-ignored and never archived).
