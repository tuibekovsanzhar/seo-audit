# Compact client delivery — 2026-10-20

Problem: r7 normal PDFs are 28 pages in each language but the client draft is 540 pages.
Confirmed root cause: `maya_audit_web/client_reports.py:html` appends all page text,
provider payloads and per-finding raw evidence after already rendering every card.
The renderer also repeats appendix cards as an inventory and full cards. This is an
export defect, not proof that any website finding should be deleted or downgraded.

Change: default client preview/HTML/PDF renders existing qualified cards, every distinct
finding ID, source context, short evidence, actions/owner/effort, verification, sampled
clickable URLs, scope and separate timestamps. Raw records stay in an explicitly named
JSON companion and opt-in exhaustive HTML (`full=true`); existing technical exports stay.
Do not mutate source/workspace or alter validation/review/verification. Enforce 50 pages
on compact client PDF, with actionable oversize failure. Keep an explicit full-evidence
choice in the existing editor. English/Turkish UI labels and technical language choices
remain available; generated editorial client content follows its Turkish contract.

Regression: fake cafe with repeated large evidence/page extracts keeps every ID/action
in compact output, complete raw records in companion, and full HTML remains exhaustive.
Contrast: an unreviewed/unsupported final still fails; unknown roles remain gaps;
51-page output is refused, not cut. Replay r7 unchanged into r8 with original observations
and new processing identity. Check normal/client PDFs, links and browser downloads.
No new acquisition, severity or schema changes, no packages installed in existing venv.
