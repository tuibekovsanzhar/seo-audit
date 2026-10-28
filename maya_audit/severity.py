"""One ordinal impact × observed reach × certainty policy. See docs/SEVERITY.md.

Checks declare their maximum supported impact with their source severity. This policy
cannot promote it. The product is a priority convention, not a calibrated probability.
"""
from __future__ import annotations

from .findings import Severity, is_homepage_url

VERSION = "impact-reach-certainty-v1"
IMPACT = {"S1": 4, "S2": 3, "S3": 2, "S4": 1, "Info": 0}
ORDER = {"S1": 0, "S2": 1, "S3": 2, "S4": 3, "Info": 4}
CERTAINTY = {"verified": 3, "inferred": 2, "estimated": 1, "not_assessed": 0}


def get(value, key, default=None):
    return value.get(key, default) if isinstance(value, dict) else getattr(value, key, default)


def value(item):
    return getattr(item, "value", item)


def assess(finding, context=None, check=None):
    evidence = get(finding, "evidence", {}) or {}
    previous = evidence.get("severity_assessment") or {}
    source = previous.get("source_severity") or value(get(finding, "severity"))
    confidence = value(get(finding, "confidence", "not_assessed"))
    scope = get(finding, "scope", {}) or {}
    urls = list(dict.fromkeys(scope.get("_all_urls") or scope.get("urls") or []))
    config = get(context, "config", {}) or {}
    keys = set(get(config, "key_pages", ()) or ())
    start = get(context, "start_url")
    if start:
        keys.add(start)
    known_important = get(finding, "importance_tier", 2) == 0 or any(is_homepage_url(u) or u in keys for u in urls)
    assessed_scope = (get(check, "evidence", {}) or {}).get("assessment_scope") or {}
    population = assessed_scope.get("eligible_content_pages")
    count = scope.get("count")
    share = count / population if (isinstance(count, int) and isinstance(population, int)
                                   and population > 0 and 0 <= count <= population) else None
    factor, kind = (3, "homepage_or_key_page") if known_important else (
        (2, "large_assessed_share") if share is not None and share >= .5 else (1, "other_or_unestablished_reach"))
    certainty = CERTAINTY.get(confidence, 0)
    impact = IMPACT.get(source, 0)
    risk = impact * factor * certainty if certainty else None
    # Keep a verified source check's genuine severe defect. Broader reach can never
    # manufacture a higher impact than the check's evidence actually supports.
    calculated = ("Info" if not impact else "S1" if risk is not None and risk >= 12
                  else "S2" if risk is not None and risk >= 9 else "S3" if risk is None or risk >= 2 else "S4")
    caps = [source, value(get(finding, "severity")), calculated]
    rationale = str(get(finding, "rationale", ""))
    heuristic = confidence in ("estimated", "not_assessed") or rationale.strip().casefold() == "hypothesis"
    if heuristic:
        caps.append("S3")
    judgment = evidence.get("judgment") or {}
    if judgment.get("status") in ("diagnostic_concern", "contradictory_evidence", "not_assessed"):
        caps.append("S3")
    # Template membership is not proof of cosmetic impact. The check must supply
    # that classification; functional/accessibility defects are not made cosmetic.
    cosmetic = evidence.get("impact_type") == "cosmetic"
    shared = scope.get("kind") in ("template", "sitewide") or bool(evidence.get("shared_element"))
    if cosmetic and shared:
        caps.append("Info")
    severity = max(caps, key=lambda s: ORDER[s])
    return {"policy": VERSION, "source_severity": source, "severity": severity, "impact": impact,
            "reach": {"factor": factor, "kind": kind, "affected_pages": count,
                      "assessed_pages": population, "assessed_share": share},
            "certainty": {"factor": certainty, "observation_confidence": confidence, "heuristic": heuristic},
            "risk_score": risk, "cosmetic_shared_template": bool(cosmetic and shared),
            "limitation": "Ordinal priority policy, not calibrated harm/probability. Missing reach is not zero reach."}


def apply(checks, context=None):
    """Idempotent for native/provider objects and explicitly copied saved reports."""
    for check in checks:
        for finding in get(check, "findings", []) or []:
            decision = assess(finding, context, check)
            evidence = get(finding, "evidence", {}) or {}
            action = (evidence.get("judgment") or {}).get("action")
            if isinstance(action, dict) and isinstance(action.get("priority"), dict):
                action["priority"]["severity"] = decision["severity"]
            if isinstance(finding, dict):
                finding.setdefault("evidence", {})["severity_assessment"] = decision
                finding["severity"] = decision["severity"]
            else:
                finding.evidence["severity_assessment"] = decision
                finding.severity = Severity(decision["severity"])
    return checks
