"""DECISIONS 378 (accuracy first): rule maturity from the SEO team's reviews, and what a disputed rule's finding becomes.

The register is generated from docs/expert-reviews/*.json (scripts/rule_maturity.py). Levels on today's reviews:
str16.shared and str7.over_100kb are correct on enpara and mmi (approved); str5.names and tseo1.head_closed_later were
last found wrong (disputed); str14.no_text was last "incomplete" (unreviewed); idx5.stamped is questioned in
rule_approval.json (disputed). Offline: no site, no provider.
"""
from __future__ import annotations

import json

import pytest

from maya_audit import client_appendix, rule_approval, rule_maturity
from maya_audit import client_selection as cs
from maya_audit_web import strings
from scripts import rule_maturity as builder
from test_v03_client_report import SITE, finding, report

LABELS = json.loads((cs.Path(cs.__file__).parents[1] / "maya_audit_web" / "team_report" / "refs" / "etiketler.json")
                    .read_text(encoding="utf-8"))


@pytest.fixture
def approval(monkeypatch):
    """Patch rule_approval.json's content for one test."""
    def use(data: dict):
        monkeypatch.setattr(rule_approval, "_data", lambda: data)
    return use


# ---------------------------------------------------------------- Task 1: the register and the levels

def test_register_matches_the_expert_reviews():
    assert builder.build() == json.loads(rule_maturity.FILE.read_text(encoding="utf-8"))


def test_levels_on_todays_reviews():
    assert rule_maturity.level("str16.shared") == rule_maturity.level("str7.over_100kb") == "approved"
    assert rule_maturity.level("str5.names") == rule_maturity.level("tseo1.head_closed_later") == "disputed"
    assert rule_maturity.level("str14.no_text") == "unreviewed"      # latest verdict "incomplete"
    assert rule_maturity.level("idx5.stamped") == "disputed"         # questioned in rule_approval.json
    assert rule_maturity.level(None) == rule_maturity.level("no.such_rule") == "unreviewed"


def test_three_correct_on_one_brand_is_not_enough():
    row = rule_maturity.stats("str14.no_text")
    assert row["correct"] >= 3 and row["latest"]["verdict"] == "incomplete"
    assert rule_maturity.level("str14.no_text") != "approved"


def test_explicit_approval_beats_a_wrong_verdict(approval):
    approval({"approved": {"str5.names": {"by": "İlginay", "on": "2026-11-26"}}, "questioned": {}})
    assert rule_maturity.level("str5.names") == "approved"


def test_works_without_the_docs_folder(monkeypatch, tmp_path):
    monkeypatch.setattr(builder, "FOLDER", tmp_path)                 # an installed package has no docs/
    assert builder.build()["rules"] == {}
    assert rule_maturity.level("str16.shared") == "approved"


def test_policy_default_and_invalid_value(approval):
    approval({"approved": {}, "questioned": {}})
    assert rule_maturity.policy() == "card"
    approval({"approved": {}, "questioned": {}, "policy": {"unreviewed": "maybe"}})
    with pytest.raises(ValueError, match="rule_approval.json"):
        rule_maturity.policy()


# ---------------------------------------------------------------- Task 2: a disputed rule waits in "Teyit edin"

def _by_id(sel: dict) -> dict:
    return {fid: g for g in sel["groups"] for fid in g["finding_ids"]}


def test_a_disputed_rule_is_confirm_not_a_card():
    sel = cs.select(report([finding("A", "str5.names", "S4", urls=[SITE + "/a"], check="STR-5"),
                            finding("B", "str16.shared", "S4", urls=[SITE + "/a"], check="STR-16")]))
    by = _by_id(sel)
    assert by["A"]["placement"] == "confirm" and by["A"]["confirm_reason"] == "disputed_rule"
    assert by["B"]["placement"] == "card" and by["B"]["confirm_reason"] is None


def test_a_high_disputed_finding_still_takes_a_card_slot():
    sel = cs.select(report([finding("A", "str5.names", "S2", urls=[SITE + "/a"], check="STR-5")]))
    g = _by_id(sel)["A"]
    assert g["placement"] == "card" and g["card"] and g["issue_type"] == "warning"   # DECISIONS 367: confirm first
    assert g["confirm_reason"] == "disputed_rule" and g["severity"] == "S2"          # nothing S1/S2 disappears


def test_a_person_confirmed_disputed_finding_is_a_card():
    r = report([finding("A", "str5.names", "S4", urls=[SITE + "/a"], check="STR-5")])
    g = _by_id(cs.select(r, confirmations={"A": {"result": "confirmed"}}))["A"]
    assert g["placement"] == "card" and g["confirm_reason"] is None


def test_a_merged_group_keeps_its_disputed_member_waiting():
    """language_mismatch joins str12.language (never reviewed) and str12.headings (last found wrong): the disputed
    member waits in "Teyit edin"; the other one is not held back by it."""
    sel = cs.select(report([finding("L", "str12.language", "S4", urls=[SITE + "/en/a"], check="STR-12"),
                            finding("H", "str12.headings", "S4", urls=[SITE + "/en/a"], check="STR-12")]))
    by = _by_id(sel)
    assert by["H"]["placement"] == "confirm" and by["H"]["confirm_reason"] == "disputed_rule"
    assert by["L"]["placement"] == "card"


def test_strict_policy_sends_unreviewed_rules_to_confirm(monkeypatch):
    r = report([finding("A", "str14.no_text", "S4", urls=[SITE + "/a"], check="STR-14"),
                finding("B", "str16.shared", "S4", urls=[SITE + "/a"], check="STR-16")])
    monkeypatch.setattr(rule_maturity, "policy", lambda: "confirm")
    by = _by_id(cs.select(r))
    assert by["A"]["placement"] == "confirm" and by["A"]["confirm_reason"] == "unreviewed_rule"
    assert by["B"]["placement"] == "card"                                            # approved rules are not held
    monkeypatch.setattr(rule_maturity, "policy", lambda: "card")
    assert _by_id(cs.select(r))["A"]["placement"] == "card"


def test_severity_is_never_changed_by_maturity():
    f = finding("A", "str5.names", "S3", urls=[SITE + "/a"], check="STR-5")
    r = report([f])
    assert _by_id(cs.select(r))["A"]["severity"] == "S3" and r["checks"][0]["findings"][0]["severity"] == "S3"


@pytest.mark.parametrize("reason", ["disputed_rule", "unreviewed_rule"])
def test_every_confirm_reason_has_words_in_both_languages(reason):
    assert reason in cs.CONFIRM_REASONS
    assert LABELS["tr"]["confirm_reasons"][reason] and LABELS["en"]["confirm_reasons"][reason]
    assert client_appendix.WORDS["tr"]["reason"][reason] and client_appendix.WORDS["en"]["reason"][reason]
    for lang in ("tr", "en"):
        assert strings.t(f"c6.reason.{reason}", lang) != f"c6.reason.{reason}"


def test_a_reason_that_says_what_to_look_at_comes_before_the_rules_maturity():
    """str5.names is disputed, but a brand name seen only in structured data keeps DECISIONS 339's reason: it tells the
    reader what to check."""
    f = finding("A", "str5.names", "S4", urls=[SITE + "/a"], check="STR-5",
                evidence={"variants": [{"name": "Demo", "by_source": {"title": 3}},
                                       {"name": "Homepage", "by_source": {"Organization name": 1}}]})
    assert cs.names_in_markup(f) and cs.confirm_reason(f) == "names_in_markup"
    assert cs.confirm_reason({**f, "intent": {"kind": "intent_marking"}}) == "intent"


def test_the_middle_policy_holds_only_medium_and_low_findings_of_unreviewed_rules(monkeypatch):
    """Owner, 2026-11-26: "confirm_below_high" sends a never-approved rule's Medium and Low findings to "Teyit edin";
    its High and Blocker findings stay cards, and approved rules are never held."""
    r = report([finding("L", "str14.no_text", "S4", urls=[SITE + "/a"], check="STR-14"),
                finding("M", "str19.no_target", "S3", urls=[SITE + "/a"], check="STR-19"),
                finding("H", "str2.no_h1", "S2", urls=[SITE + "/a"], check="STR-2"),
                finding("B", "str16.shared", "S4", urls=[SITE + "/a"], check="STR-16")])
    assert rule_maturity.level("str2.no_h1") == "unreviewed"
    monkeypatch.setattr(rule_maturity, "policy", lambda: "confirm_below_high")
    by = _by_id(cs.select(r))
    assert by["L"]["confirm_reason"] == by["M"]["confirm_reason"] == "unreviewed_rule"
    assert by["L"]["placement"] == by["M"]["placement"] == "confirm"
    assert by["H"]["confirm_reason"] is None and by["H"]["placement"] == "card"
    assert by["B"]["placement"] == "card"


def test_the_owners_choice_is_today_s_behaviour():
    assert rule_maturity.policy() == "card"                      # owner, 2026-11-26: until the team approves more rules
    assert (rule_maturity.APPROVE_MIN_CORRECT, rule_maturity.APPROVE_MIN_BRANDS) == (3, 2)
