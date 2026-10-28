# Local export compatibility — 23 October 2026

Source: owner's Downloads/maya-audit-pro-skill.zip, SHA-256 e5e325e01157612a81f303aa722d9550472a235a74174b3c35b0f5ae0965c9a9. No version was declared; data contract is 1.

The supplied landscape design, logo and embedded Inter font are retained. Local fixes:
- Label distinct unassessed scope items as scope items, not a count of whole checks; preserve the original calculation.
- Label IDX-5 per-URL scope as URLs, rather than content pages; counts remain unchanged.
- Read saved affected-urls.json alongside report.json to extend capped scope URL lists, never shrink the original review scope. Count omitted URL examples deterministically, without editing audit totals.
- Render the supplied per-card evidence status (previously calculated but not printed). Reclaim two points of section spacing to fit that status and complete URL-count lines without changing fonts, content or the four-card grid. Actual first-pass overflow logs are retained with the reports.
- Show missing Lighthouse/CrUX evidence explicitly rather than discussing an absent lab run as measured.
- Fall back to installed pypdf for PDF checks and macOS sips/Quartz for every-page previews when PyMuPDF is unavailable. No dependency installation.
- Block HTTP/HTTPS/WebSocket requests in the rendering browser.

No application audit rules or judgments changed. Not connected to the application's existing PDF button. Use the scripts directly. All report generation must use isolated storage, absent environment-file lookup and a credential-free child environment.

Focused checks: existing .venv/bin/python -m unittest discover -s .agents/skills/maya-audit-pro/tests -v.

## Integration onto the 22 October skill (26 October 2026)

Base: the owner's 22 October skill (yapısal veri, küçük düzeltmeler and içerik-dil Note cards, DECISIONS 250–252).
The 23 October changes above were applied on top of it with a three-way merge against the 20 October zip; the only
conflict (the `Builder(...)` call in `build_data.py`) keeps both `affected` and `meta.source`. `build_data.py` now
prints the path of the `affected-urls.json` it read, so a companion left over from another audit is visible.
The Note cards now print their status line too; a filled Arjava report rendered at 11 pages without overflow.
Preview fallback without PyMuPDF uses macOS `sips`; on Windows install PyMuPDF for `--png`.

## Client text corrections (26 October 2026, DECISIONS 257)

- "+N more" no longer promises a JSON file the client never receives: `render.py` writes `<name>-addresses.csv`
  (`-adresler.csv` in Turkish) next to the HTML with every card's full address list; it is sent with the PDF.
- Internal launch-gate codes (`LG-xx`) are not printed; the status says "check not yet validated on live sites".
  The codes stay in `todos[].launch_gated`.
- The page KPI is "Pages with page-level issues" and its sub-line names the site-wide problems
  (`problem_summary.whole_site`) it does not count, so a shared-header card listing every page no longer
  contradicts it.

## Cards from the rule catalogue (27 October 2026, DECISIONS 270–271)

Cards are filled from Maya Audit's rule catalogue (`maya_audit/rule_actions.json`, keyed by the finding's `rule_id`,
schema 1.18; older reports get the id from `maya_audit/rules.py`), the engine's own translated fix and expected
sentences, and fixed Note-card texts; the model writes ~15 fields instead of ~100. Each card shows an evidence line
from `evidence.facts` (computed for older reports by `maya_audit/facts.py`). `validate_data.py` refuses a site address
in a text field that is neither among the card's addresses nor in its finding's record (`known_paths`).

## The second look and the engine's claims (27 October 2026, DECISIONS 276)

A card's status line adds the engine's re-test when there is one (`verification.state`, schema 1.19): "checked again:
confirmed / changed / not reproduced"; a report without the field, or "not_retested", shows nothing. The IDX-5 ratio is
read from every title form the engine writes, including the judged "N sitemap URL observation(s) require
differentiated review (M checked)", which an older pattern missed. What SKILL.md says about the engine ("Motorun
bilinen tuzakları") is tested against the engine in `tests/test_w12_skill_claims.py` of the Maya Audit repository.
