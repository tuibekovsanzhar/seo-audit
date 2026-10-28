"""Reasoning frameworks that turn a finished audit report into a document a person can act on.

The audit produces evidence. These turn evidence into prose without losing what the evidence model
was careful about — see `rules.py` for the part that cannot be negotiated, and `prompts.py` for the
four skills and what each one needs.

Nothing here calls a language model. A brief is a prompt and a payload, handed to whatever model
the caller chooses; keeping the audit itself free of model calls is what makes a report
reproducible.
"""

from .prompts import (
    AUDIT_REPORT,
    CITED_DOMAIN_LANDSCAPE,
    CITED_PAGE_MAPPING,
    EXPLAIN_AND_NEXT_STEPS,
    SKILLS,
    Skill,
    SkillBrief,
    skill_names,
)
from .rules import ADVERSARIAL_PASS, ATTRIBUTION, EDITORIAL_RULES, EVIDENCE_RULES, SEVERITY_LADDER

__all__ = [
    "ADVERSARIAL_PASS", "ATTRIBUTION", "AUDIT_REPORT", "CITED_DOMAIN_LANDSCAPE", "CITED_PAGE_MAPPING",
    "EDITORIAL_RULES", "EVIDENCE_RULES", "EXPLAIN_AND_NEXT_STEPS", "SEVERITY_LADDER", "SKILLS",
    "Skill", "SkillBrief", "skill_names",
]
