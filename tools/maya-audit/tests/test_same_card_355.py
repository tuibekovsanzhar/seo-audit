"""DECISIONS 355: two cards with one title on the same pages are one card (one problem) or say how they differ."""
from __future__ import annotations

from maya_audit import client_selection as cs, text_gate

SITE = "https://site.test"


def finding(fid, rule, field, pages=("/a", "/b"), severity="S3", check="STR-11", **more):
    return {"id": fid, "rule_id": rule, "check_id": check, "severity": severity, "dedup_key": f"{rule}:{field}",
            "title": f"2 page(s) describe the same entity twice in structured data with a different {field}",
            "evidence": {"field": field}, "scope": {"urls": [SITE + p for p in pages]}, **more}


def groups(*findings):
    return cs.groups({"checks": [{"check_id": "STR-11", "findings": list(findings)}]}, None, {}, importance={})


def test_one_problem_twice_on_the_same_pages_is_one_card_with_both_findings():
    rows = groups(finding("F1", "str11.two_values", "dateModified"), finding("F2", "str11.two_values", "name"))
    assert len(rows) == 1 and rows[0]["finding_ids"] == ["F1", "F2"]
    assert [m["evidence"]["field"] for m in rows[0]["members"]] == ["dateModified", "name"]  # both kept


def test_other_pages_or_another_state_stay_apart():
    apart = groups(finding("F1", "str11.two_values", "dateModified"),
                   finding("F2", "str11.two_values", "name", pages=("/c",)))
    assert len(apart) == 2
    state = groups(finding("F1", "str11.two_values", "dateModified"),
                   finding("F2", "str11.two_values", "name", intent=True))
    assert len(state) == 2


def test_hosts_of_one_problem_are_one_card():
    a = {"id": "H1", "rule_id": "idx2.no_redirect", "check_id": "IDX-2", "severity": "S4", "dedup_key": "idx2:www",
         "title": "No HTTP to HTTPS redirect on www.site.test", "scope": {"urls": ["http://www.site.test/"]}}
    b = {**a, "id": "H2", "dedup_key": "idx2:apex", "title": "No HTTP to HTTPS redirect on site.test",
         "scope": {"urls": ["http://site.test/"]}}
    rows = cs.groups({"checks": [{"check_id": "IDX-2", "findings": [a, b]}]}, None, {}, importance={})
    assert len(rows) == 1 and rows[0]["finding_ids"] == ["H1", "H2"]


def test_different_problems_under_one_title_keep_their_cards_and_say_which(monkeypatch):
    monkeypatch.setattr(cs, "card_title", lambda rule: "Aynı başlık")
    monkeypatch.setattr(cs, "card_steps", lambda rule: (rule,))
    rows = groups(finding("F1", "str11.two_values", "dateModified"), finding("F2", "str11.other", "name"))
    assert len(rows) == 2 and [r["title_detail"] for r in rows] == ["str11.two_values", "str11.other"]


def test_a_finding_without_a_rule_id_is_never_merged():
    a = finding("F1", None, "x")
    b = finding("F2", None, "y")
    a["title"] = b["title"] = "something no frame names"
    assert len(groups(a, b)) == 2


def test_the_card_title_and_steps_come_from_the_reports_texts():
    assert cs.card_title("idx2.no_redirect") == "http adreslerini https adreslerine yönlendirin"
    assert len(cs.card_steps("str11.two_values")) >= 2 and cs.card_title("nope.nothing") == "nope.nothing"


def test_the_text_check_finds_no_repeat_after_the_merge():
    rows = groups(finding("F1", "str11.two_values", "dateModified"), finding("F2", "str11.two_values", "name"))
    card = {"n": 1, "finding_ids": rows[0]["finding_ids"], "title": "Çelişen yapısal veri değerlerini giderin",
            "rule_id": "str11.two_values", "all_urls": rows[0]["urls"]}
    report = {"checks": [{"check_id": "STR-11", "findings": [m for m in rows[0]["members"]]}]}
    assert [v for v in text_gate.check({"lang": "tr", "todos": [card]}, report) if v["rule"] == "RG-22"] == []
