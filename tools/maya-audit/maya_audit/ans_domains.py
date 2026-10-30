"""The cited-domain export that ANS-4 and ANS-5 read (spec §5 ANS).

This is a *different* export from the one `ans_data.py` loads. `--citations` carries one
record per citation of **this site** (engine, URL, when). `--citation-domains` carries the
ranked list of **every domain** an engine cited while answering prompts about this brand,
which is what Maya's `get_citations` tool returns.

Two things about this file are easy to get wrong, so they are enforced here rather than
left to the checks:

**It is a truncated list.** The upstream tool returns the top N rows of what can be
thousands of domains (a real export: 20 rows of 4,306). The payload carries its own
totals, so a site-level share has an honest denominator — but there are no per-engine
totals, so a *per-engine* share cannot be computed from the returned rows without
silently dividing by a truncated number. `engine_totals_complete` records which case
we are in, and ANS-4 refuses the per-engine share when it is False.

**It is not Maya's Share of Voice.** Maya's product SoV counts brand mentions in answer
text across a curated competitor set. This export counts cited source domains, including
image CDNs, Wikipedia and government sites. On a real project the two differ by ~5x
(35.9% vs 7.3%) — both correct, measuring different things. Nothing here is ever labelled
"share of voice"; see `docs/DECISIONS.md`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from .urls import registrable_domain

# Hosts that serve an engine's own assets rather than anyone's content. They appear high in a
# cited-domain list (one real export had images.openai.com third overall) and are not competitors,
# publishers, or anything a site owner can act on. Suffix match on the registrable domain.
INFRASTRUCTURE = ("openai.com", "googleusercontent.com", "gstatic.com", "ggpht.com", "bing.net",
                  "cloudfront.net", "akamaized.net", "fbcdn.net", "cdninstagram.com", "licdn.com",
                  "twimg.com", "ytimg.com", "wp.com", "shopifycdn.com", "cloudflare.com")
# General knowledge and authority sources. A brand losing ground to these is a content question,
# not a technical defect, so ANS-5 separates them from commercial domains.
REFERENCE = ("wikipedia.org", "wikimedia.org", "who.int", "nih.gov", "ncbi.nlm.nih.gov", "europa.eu",
             "un.org", "oecd.org", "worldbank.org", "britannica.com", "merriam-webster.com")
# Profile, listing and social surfaces. These carry a brand's presence *instead of* its own site,
# which is the actionable observation in ANS-5.
DIRECTORY = ("instagram.com", "facebook.com", "linkedin.com", "x.com", "twitter.com", "youtube.com",
             "tiktok.com", "reddit.com", "quora.com", "medium.com", "yelp.com", "tripadvisor.com",
             "trustpilot.com", "glassdoor.com", "crunchbase.com", "g2.com", "capterra.com")
# Government and public-institution suffixes, checked on the full host so "saglik.gov.tr" matches.
PUBLIC_SUFFIXES = (".gov", ".gov.tr", ".gov.uk", ".gob.es", ".gouv.fr", ".edu", ".edu.tr", ".ac.uk")

CLASSES = ("site", "infrastructure", "reference", "directory", "public", "other")


def classify_domain(domain: str, site_domain: str) -> str:
    """One of CLASSES. The lists above are a judgment call, not a validated taxonomy (LG-29)."""
    host = domain.strip().lower().rstrip(".")
    if not host:
        return "other"
    registrable = registrable_domain(host) or host
    if site_domain and registrable == registrable_domain(site_domain):
        return "site"
    for group, name in ((INFRASTRUCTURE, "infrastructure"), (REFERENCE, "reference"), (DIRECTORY, "directory")):
        if any(registrable == known or host.endswith("." + known) for known in group):
            return name
    if any(host == suffix.lstrip(".") or host.endswith(suffix) for suffix in PUBLIC_SUFFIXES):
        return "public"
    return "other"


@dataclass
class CitationDomains:
    path: str | None = None
    loaded: bool = False
    error: str | None = None
    source: str | None = None
    fetched_at: str | None = None
    period_days: int | None = None
    site_domain: str | None = None
    # Totals as reported by the export, covering every domain — not only the returned rows.
    total_mentions: int | None = None
    unique_domains: int | None = None
    rows_returned: int = 0
    rows_total: int | None = None
    rows: list[dict[str, Any]] = field(default_factory=list)
    invalid_rows: list[dict[str, Any]] = field(default_factory=list)

    @property
    def truncated(self) -> bool:
        """True when the export lists fewer domains than it says exist."""
        return self.rows_total is not None and self.rows_returned < self.rows_total

    @property
    def engine_totals_complete(self) -> bool:
        """Whether a per-engine denominator can be built from the rows we actually have.

        Only true for an untruncated export. With truncation the per-engine sums cover the
        listed rows alone, and dividing by them would overstate the site's standing on every
        engine — the exact mistake this flag exists to prevent.
        """
        return self.loaded and not self.truncated

    def site_row(self) -> dict[str, Any] | None:
        return next((row for row in self.rows if row["class"] == "site"), None)

    def freshness(self) -> str:
        return (f"cited-domain data from {self.source or 'an unnamed source'}, fetched "
                f"{self.fetched_at or 'at an unknown time'}"
                + (f", covering {self.period_days} day(s)" if self.period_days else ""))


def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def load_citation_domains(path: str | None, origin: str) -> CitationDomains:
    """Read the export. Accepts Maya's `get_citations` payload as returned, unmodified."""
    data = CitationDomains(path=path)
    if not path:
        return data
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, ValueError) as exc:
        data.error = f"{type(exc).__name__}: {exc}"
        return data
    if not isinstance(raw, dict) or not isinstance(raw.get("domains"), list):
        data.error = "expected a JSON object with a 'domains' list"
        return data

    data.loaded = True
    project = raw.get("project") if isinstance(raw.get("project"), dict) else {}
    period = raw.get("period") if isinstance(raw.get("period"), dict) else {}
    page = raw.get("page") if isinstance(raw.get("page"), dict) else {}
    data.source = raw.get("source") if isinstance(raw.get("source"), str) else "Maya get_citations"
    data.fetched_at = next((raw[k] for k in ("fetched_at", "fetchedAt") if isinstance(raw.get(k), str)), None)
    data.period_days = _int_or_none(period.get("sinceDays"))
    # The site's own domain: from the export when it names one, else the audited origin.
    declared = project.get("domain") if isinstance(project.get("domain"), str) else None
    # registrable_domain, not a "www." strip: `"web.com".lstrip("www.")` returns "eb.com".
    data.site_domain = registrable_domain(declared or urlsplit(origin).netloc or "") or None
    data.total_mentions = _int_or_none(raw.get("totalMentions"))
    data.unique_domains = _int_or_none(raw.get("uniqueDomains"))
    data.rows_total = _int_or_none(page.get("total")) or _int_or_none(raw.get("uniqueDomains"))

    for index, row in enumerate(raw["domains"]):
        if not isinstance(row, dict) or not isinstance(row.get("domain"), str) or not row["domain"].strip():
            data.invalid_rows.append({"index": index, "reason": "missing or non-string 'domain'"})
            continue
        mentions = _int_or_none(row.get("mentions"))
        if mentions is None:
            data.invalid_rows.append({"index": index, "reason": f"missing or non-integer 'mentions' on {row['domain']!r}"})
            continue
        by_model_raw = row.get("byModel") if isinstance(row.get("byModel"), dict) else {}
        by_model = {str(k): v for k, v in by_model_raw.items() if _int_or_none(v) is not None}
        domain = row["domain"].strip().lower()
        data.rows.append({"domain": domain, "mentions": mentions, "by_model": by_model,
                          "class": classify_domain(domain, data.site_domain or "")})
    data.rows.sort(key=lambda r: r["mentions"], reverse=True)
    data.rows_returned = len(data.rows)
    return data
