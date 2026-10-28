"""Maya Audit local web app: a JSON API and a chat page around the existing audit engine.

Nothing here checks a website. Every check, the crawl, the cost guard and the report come from
`maya_audit`; this package starts audits, remembers them, and shows what the report says.
"""

API_VERSION = "1"
