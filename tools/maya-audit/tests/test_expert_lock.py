"""DECISIONS 373: the expert lock. Every SEO-expert note is a label (docs/expert-reviews/*.json); this test rebuilds the
noted audits from their frozen saved pages (outside the repository, MAYA_AUDIT_BENCHMARK_DIR, made with
`scripts/real_sites_benchmark.py freeze-expert`) with the current engine and checks every label. It is never skipped
silently: without the frozen set it fails, unless the run says on purpose that the set is not on this machine
(MAYA_AUDIT_BENCHMARK_OPTIONAL=1, which CI sets only while no private copy of the set is wired to it)."""
from __future__ import annotations

import os

import pytest

from maya_audit import expert_labels, fix_log
from scripts import real_sites_benchmark as bench


def test_every_note_of_every_review_is_a_well_formed_label():
    reviews = expert_labels.reviews()
    assert {r["_file"] for r in reviews} >= {"enpara-2e5829fb.json", "enpara-fee70191.json", "mmi-536b4b64.json",
                                            "naturesgarden-342a0b14.json"}
    for review in reviews:
        for card in review["cards"]:
            assert card.get("labels"), f"{review['_file']} card {card['card']}: the note has no label"
            verdicts = {"wrong": "must_not_find", "correct": "must_find"}
            if card["verdict"] in verdicts and not any(x.get("superseded_by") or x.get("why") for x in card["labels"]):
                # a "wrong" note fixed by rewriting the advice checks the corrected detail, and says why
                assert any(x["kind"] == verdicts[card["verdict"]] for x in card["labels"]), (review["_file"], card["card"])
    items = expert_labels.labels()
    assert expert_labels.validate(items) == []
    assert len(expert_labels.active(items)) >= 60


def test_every_fix_log_item_of_a_noted_audit_names_its_labels_and_every_item_a_test():
    known = {x["id"] for x in expert_labels.labels()}
    for item in fix_log.items():
        check = item.get("check") or {}
        assert fix_log.tests_of(check), f"item {item['no']}: no test linked"
        assert set(check.get("labels") or []) <= known, f"item {item['no']}: unknown label"
    noted = [i for i in fix_log.items() if "İlginay" in i["kaynak"] and i.get("brand_key") in ("mmi", "naturesgarden")]
    assert noted and all((i.get("check") or {}).get("labels") for i in noted
                         if not (i.get("check") or {}).get("crawl")), [i["no"] for i in noted if not i["check"].get("labels")]


def frozen_set_present() -> bool:
    return (bench.expert_dir() / "manifest.json").exists()


@pytest.fixture(scope="module")
def lock_rows(tmp_path_factory):
    if not frozen_set_present():
        if os.environ.get("MAYA_AUDIT_BENCHMARK_OPTIONAL") == "1":
            pytest.skip("the frozen expert set is not on this machine, and this run says so on purpose "
                        "(MAYA_AUDIT_BENCHMARK_OPTIONAL=1)")
        pytest.fail("the frozen expert set is missing: set MAYA_AUDIT_BENCHMARK_DIR to the folder made by "
                    "`scripts/real_sites_benchmark.py freeze-expert` (DECISIONS 373)")
    return bench.run_expert(tmp_path_factory.mktemp("expert"))


def test_every_expert_label_holds_on_the_rebuilt_noted_audits(lock_rows):
    red = [f"{r['id']} ({r['kind']}): {r['seen']}" for r in lock_rows if r["ok"] is False]
    missing = [r["id"] for r in lock_rows if r["ok"] is None]
    assert not red, "expert labels broken: " + "; ".join(red)
    assert not missing, "labels whose audit is not frozen: " + ", ".join(missing)
    assert len(lock_rows) >= 60


def test_a_label_turns_red_when_what_it_guards_comes_back():
    ctx = {"report": {"checks": [{"check_id": "STR-2", "status": "findings", "findings": [
        {"id": "STR-2-x", "rule_id": "str2.hidden_h1", "severity": "S4"}]}]}, "cards": [], "book": {}}
    label = {"id": "t", "kind": "must_not_find", "on": "finding", "rules": ["str2.hidden_h1"]}
    assert expert_labels.check(label, ctx)["ok"] is False
    ctx["report"]["checks"][0]["findings"] = []
    assert expert_labels.check(label, ctx)["ok"] is True
    found = {"id": "u", "kind": "must_find", "on": "row", "sheet": "Özet", "column": "Örnek", "regex": "lastmod"}
    assert expert_labels.check(found, {**ctx, "book": {"Özet": [["Kart", "Örnek"], ["1", "x.xml: 19 adresin 18'i aynı lastmod'u"]]}})["ok"]
    assert expert_labels.check(found, {**ctx, "book": {}})["ok"] is False  # no sheet is not a pass
