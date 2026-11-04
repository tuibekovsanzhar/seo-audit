"""The team report: Maya's pro report design (summary pages, to-do cards, "Kapsam ve ek") and its XLSX appendix, built
from report.json with no model in the loop (DECISIONS 307).

One template and one text library for both callers: the web app's "Ekip raporu (PDF)" button (`maya_audit_web.app`,
through `service.build`) and the `maya-audit-pro` skill (whose scripts import these modules). The skill may let Claude
polish wording; it can never change a severity, a count or the order (`validate_data.locked_digest`).

- `build_data`: report.json -> data.json (numbers, cards, order from `maya_audit.client_selection`).
- `texts`: the text library (`texts/tr.json`, `texts/en.json`) and the page-1 sentences built from the top cards.
- `validate_data`: the data checks and Maya Audit's release gate.
- `render`: data.json -> HTML -> PDF, the XLSX appendix, page previews.
- `service`: the whole path in one call, for the web app.
"""
