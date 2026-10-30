"""Finding model (spec §2): severity, confidence, and rationale kept separate."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from urllib.parse import urlsplit

from .fetcher import utc_now
from .models import Confidence


class Severity(str, Enum):
    S1 = "S1"
    S2 = "S2"
    S3 = "S3"
    S4 = "S4"
    INFO = "Info"


# Spec §2.1, word for word in meaning. Anything that explains severity to a person or a model (the
# ai_skills prompts) is built from this, so it cannot drift from the definitions the checks use.
SEVERITY_DEFINITIONS = {
    "S1": "Blocker: an answer engine cannot retrieve the page(s), or is told not to use them.",
    "S2": "High: the page is retrieved, but content an engine would cite is missing, wrong, or cannot be "
          "attributed.",
    "S3": "Medium: degrades discovery, extraction, or understanding without preventing it.",
    "S4": "Low: hygiene with a plausible but weakly evidenced effect.",
    "Info": "A recorded fact, possibly intentional; no action implied.",
}

SEVERITY_ORDER = {Severity.S1: 0, Severity.S2: 1, Severity.S3: 2, Severity.S4: 3, Severity.INFO: 4}
CONFIDENCE_ORDER = {Confidence.VERIFIED: 0, Confidence.INFERRED: 1, Confidence.ESTIMATED: 2, Confidence.NOT_ASSESSED: 3}


class Rationale(str, Enum):
    """Spec §2.3."""

    DOCUMENTED = "Documented"
    MEASURED = "Measured"
    HYPOTHESIS = "Hypothesis"
    SELF_EVIDENT = "Self-evident harm"


@dataclass
class Finding:
    check_id: str
    title: str
    severity: Severity
    confidence: Confidence
    rationale: str
    engines: list[str]
    scope: dict[str, Any]  # {"kind": "sitewide"|"template"|"page", "count": n, "urls": [...]}
    evidence: dict[str, Any]
    expected: str
    how_to_fix: str
    cost_tier: str = "T0"
    # Spec §2.4 intent status: None, or {"kind": "declared_policy"|"intent_marking", ..., "severity_otherwise": "S1"}
    intent: dict[str, Any] | None = None
    launch_gated: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    # Spec §2.1 importance tier: 0 confirmed key page, 1 unconfirmed suggestion, 2 other.
    importance_tier: int = 2
    observed_at: str = field(default_factory=utc_now)
    id: str = ""
    # The stable kind of finding (DECISIONS 269): the key of the title frame it matches, e.g. "str2.home_hidden_h1".
    rule_id: str | None = None
    # What a second request saw before the report was written (DECISIONS 272); None when the rule has no re-test.
    verification: dict[str, Any] | None = None
    # The finding contract the release gate reads (DECISIONS 278, schema 1.20); None when not established, never
    # guessed. `page_types`: {url: kind} for the affected pages ("unknown" allowed). `measurement`: {"claims": [{"element",
    # "state", "urls"}]}: what the finding says about which element on which page. `remediation`: {"task_id", "content",
    # "page_types"}: the catalogue task that fixes it and, for content advice, the page kinds it may be given for.
    # `dedup_key`: the cause the finding reports, shared by any other finding that reports the same cause.
    page_types: dict[str, str] | None = None
    measurement: dict[str, Any] | None = None
    remediation: dict[str, Any] | None = None
    dedup_key: str | None = None

    def __post_init__(self) -> None:
        if self.rule_id is None:
            from .rules import rule_id
            self.rule_id = rule_id(self.check_id, self.title)
        if not self.id:
            basis = f"{self.check_id}|{self.title}|{sorted(self.scope.get('urls', []))}"
            shared = self.evidence.get('shared_element')
            if shared:
                # Equal titles/pages can describe different post targets or components.
                basis += '|' + json.dumps(shared, sort_keys=True, ensure_ascii=False)
            self.id = f"{self.check_id}-{hashlib.sha1(basis.encode()).hexdigest()[:8]}"


@dataclass
class ReviewItem:
    """Something a person should look at that has no severity (spec §2.1 has no level for it).

    Shown prominently, never folded into Info: e.g. a bot served different content
    than a browser, where harm cannot be shown but the difference itself matters.
    """

    check_id: str
    title: str
    why_review: str
    confidence: Confidence
    engines: list[str]
    scope: dict[str, Any]
    evidence: dict[str, Any]
    suggested_action: str
    launch_gated: list[str] = field(default_factory=list)
    importance_tier: int = 2
    observed_at: str = field(default_factory=utc_now)
    id: str = ""
    rule_id: str | None = None  # DECISIONS 269

    def __post_init__(self) -> None:
        if self.rule_id is None:
            from .rules import rule_id
            self.rule_id = rule_id(self.check_id, self.title)
        if not self.id:
            basis = f"review|{self.check_id}|{self.title}|{sorted(self.scope.get('urls', []))}"
            self.id = f"{self.check_id}-R{hashlib.sha1(basis.encode()).hexdigest()[:7]}"


STATUSES = ("findings", "needs_review", "pass", "partial", "observed", "not_assessed", "not_applicable")
# What each status means, written into every report so a reader never has to guess (report 0.4).
STATUS_MEANINGS = {
    "findings": "at least one finding; see coverage for any part that was not assessed",
    "needs_review": "no severity-ranked finding, but at least one item a person must look at",
    "pass": "every part of the check's question was assessed and nothing was found",
    "partial": "nothing was found in what was assessed, but part of the question was NOT assessed; "
               "this is not a pass (see coverage)",
    "observed": "the check records measurements only; there is no pass condition to meet",
    "not_assessed": "the check could not run; the reason is in its summary and evidence",
    "not_applicable": "none of the pages read is what the check is about (no news page, no job page); neither a pass nor a gap, "
                      "and coverage lists any part of the site not read",
}


@dataclass
class CheckResult:
    check_id: str
    title: str
    status: str  # one of STATUSES
    summary: str
    findings: list[Finding] = field(default_factory=list)
    # Evidence behind a pass or a Not assessed (spec §1.3).
    evidence: dict[str, Any] = field(default_factory=dict)
    # Measured values whose threshold the spec has not set yet (no severity).
    observations: list[dict[str, Any]] = field(default_factory=list)
    # Visible items for a person to review; no severity (see ReviewItem).
    review_items: list[ReviewItem] = field(default_factory=list)
    # Which parts of the check's question the evidence did not cover (maya_audit.coverage). A pass
    # with any part not assessed is reported as "partial", never as "pass" (DECISIONS §99).
    coverage: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"unknown check status {self.status!r}")
        self.settle_status()

    def settle_status(self) -> None:
        """A pass is only a pass when nothing was left unassessed."""
        if self.status == "pass" and self.coverage.get("not_assessed"):
            self.status = "partial"


# What a finding stands in the way of, for ordering findings of one severity (Owner, 2026-10-12: "by severity, then by
# impact, not by page count"). 0: whether a crawler can reach, read or index the page at all. 1: what it then finds and
# trusts (links, duplicates, sitemaps, structured data, speed). 2: how the content is put (titles, headings, names,
# dates): the default. 3: guidance and tidiness (length bands, share of main content, alt text, link wording).
# Which rank a check has is an agent default.
IMPACT_RANK = {
    **{check: 0 for check in ("ACC-1", "ACC-2", "ACC-3", "ACC-4", "ACC-9", "IDX-1", "IDX-2", "IDX-3", "IDX-4", "RND-1", "RND-2", "RND-5")},
    **{check: 1 for check in ("ACC-5", "ACC-6", "ACC-7", "ACC-8", "IDX-5", "IDX-6", "IDX-7", "IDX-8", "IDX-9", "IDX-10", "RND-3",
                              "STR-3", "STR-4", "STR-9", "STR-11", "PRF-1", "PRF-2", "PRF-3")},
    **{check: 3 for check in ("TSEO-1", "RND-4", "RND-6", "RND-7", "STR-7", "STR-8", "STR-14", "STR-19")},
}
DEFAULT_IMPACT = 2


def impact_rank(check_id: str) -> int:
    return IMPACT_RANK.get(check_id, DEFAULT_IMPACT)


def evidence_quality(finding: Any) -> int:
    """How far a finding's evidence is from a verified observation, for ordering within a severity: 0 verified, 1 inferred
    or estimated, 2 a rule not yet validated on real sites (launch-gated), 3 not assessed. The web's
    `action_priority.ordered` sorts its rows by the same tiers (CR-23)."""
    if getattr(finding, "launch_gated", None):
        return 2
    confidence = getattr(finding, "confidence", None)
    confidence = getattr(confidence, "value", confidence)
    return {"verified": 0, "inferred": 1, "estimated": 1, "not_assessed": 3}.get(confidence, 1)


def is_hygiene(finding: Any) -> bool:
    """An Info finding that carries a fix but is site-wide hygiene seen on most healthy sites (HSTS, image width and
    height, the Twitter card, scripts in <head>, the CDN cache: config.HYGIENE_FINDINGS). Reports list these once, short
    and capped, after the Notes (G25). A finding object, its saved dictionary or a web row."""
    from .config import HYGIENE_FINDINGS
    get = finding.get if isinstance(finding, dict) else (lambda key, default=None: getattr(finding, key, default))
    severity = get("severity")
    if getattr(severity, "value", severity) != "Info":
        return False
    check, title = get("check_id"), str(get("title") or "").lower()
    return any(check == c and words in title for c, words in HYGIENE_FINDINGS)


def is_homepage_url(url: str) -> bool:
    """The site's root address ("https://host/" or "https://host"), with no query: the page an audit starts from."""
    parts = urlsplit(str(url))
    return bool(parts.netloc) and parts.path in ("", "/") and not parts.query


def page_importance(finding: Any) -> int:
    """The importance tier used to order findings (spec §2.1), with the homepage counted as a key page: 0 when a confirmed
    key page or the homepage is among the finding's pages, else its own tier. A finding object or its saved dictionary.
    Ordering only: the saved `importance_tier` keeps its meaning (0 = a confirmed key page)."""
    get = finding.get if isinstance(finding, dict) else (lambda key, default=None: getattr(finding, key, default))
    tier = get("importance_tier", 2)
    tier = 2 if tier is None else int(tier)
    if tier == 0:
        return 0
    scope = get("scope") or {}
    urls = scope.get("_all_urls") or scope.get("urls") or []
    return 0 if any(is_homepage_url(url) for url in urls) else tier


def priority_key(finding: Finding) -> tuple:
    """Severity, then how well the finding is evidenced (a launch-gated or estimated finding comes after a verified one of
    the same severity, whatever its reach: CR-23), then importance (a key page or the homepage first: `page_importance`),
    impact (what the finding stands in the way of), and only then how many pages it is on. A finding on many pages does
    not outrank a weightier one of the same severity."""
    return (
        SEVERITY_ORDER[finding.severity],
        evidence_quality(finding),
        page_importance(finding),
        impact_rank(finding.check_id),
        -int(finding.scope.get("count", 0)),
        CONFIDENCE_ORDER[finding.confidence],
    )


def scope_for(urls: list[str], sitewide: bool = False) -> dict[str, Any]:
    kind = "sitewide" if sitewide else ("page" if len(urls) == 1 else "template")
    # "_all_urls" is working data (keys starting with "_" are never written to the report): the report keeps the
    # first 25, and `report.affected_urls` hands the whole list to whoever needs every page.
    return {"kind": kind, "count": len(urls), "urls": urls[:25], "_all_urls": list(urls)}


def check_id_key(check_id: str) -> tuple[str, int]:
    """Natural order within each check family (STR-2 before STR-10)."""
    family, _, number = check_id.partition("-")
    return family, int(number) if number.isdigit() else 0
