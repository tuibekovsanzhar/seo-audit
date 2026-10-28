"""Client (Turkish) report: severity, draft score, one card per check, compact appendix (review items H25, B01, CR-04,
CR-09..CR-12, CR-20..CR-22, CR-35, H40, D-26). Synthetic findings only."""
from __future__ import annotations

import copy
import json
import subprocess
import sys

from maya_audit.client_reporting import from_maya_report as F
from maya_audit.client_reporting import render_report as R
from maya_audit_web import client_reports as C
from test_client_reporting import ROOT, SCRIPTS, report, valid_cards
from test_judgment_consistency import finding

RULES = F.load_json(F.REFS / "onem_kurallari.json")
SITE = "https://bakery.example"


def h1_findings(count, check="STR-2", **extra):
    return [finding(check, id=f"{check}-h{i}", title="1 page(s) have no <h1>", how_to_fix="Add one meaningful <h1> naming the page topic.",
                    expected="one meaningful main heading", scope={"kind": "page", "count": 1, "urls": [f"{SITE}/branch/{i}"]},
                    evidence={"pages": [{"url": f"{SITE}/branch/{i}", "headings": []}]}, **extra) for i in range(count)]


def work_of(findings):
    rep = report("findings", findings[0])
    rep["checks"][0]["check_id"] = findings[0]["check_id"]
    rep["checks"][0]["findings"] = findings
    return C.generate(rep, "synthetic-w4b"), rep


def test_a_report_rule_only_lowers_the_engines_severity():
    title = {"id": "t", "check_id": "STR-1", "title": "3 page(s) have no <title>", "severity": "S4", "scope": {"urls": []}}
    assert F.apply_rules(title, RULES["rules"])[0] == "S4"  # R9 used to raise this to S3 (B01)
    llms = {"id": "l", "check_id": "ACC-8", "title": "llms.txt does not open with a “# ” title line", "severity": "Info", "scope": {}}
    sev, rule, _, scored = F.apply_rules(llms, RULES["rules"])
    assert sev == "Info" and rule is None and scored is False  # R11 used to raise to S4 and score it (CR-35)
    raising = [{"match": {"check_ids": ["STR-1"]}, "set_severity": "S1", "min_severity": "S2", "label": "x"}]
    assert F.apply_rules(title, raising)[:2] == ("S4", None)
    lowering = [{"match": {"check_ids": ["STR-1"]}, "set_severity": "Info", "label": "down", "scored": False}]
    assert F.apply_rules(title, lowering) == ("Info", "down", False, False)
    assert not any("min_severity" in r or "missing_llms_title" in r for r in RULES["rules"])


def test_the_draft_score_counts_a_check_once_over_its_unique_addresses_and_leaves_out_unverified_findings():
    cfg = RULES["score"]
    cov = {"score_status": "assessed_sample", "pages_read": 10, "assessed_checks": 1, "check_denominators": {"IDX-6": 10, "STR-1": 10}}
    # Eight cards of one check on the same two pages: one deduction for the check, not eight (CR-20).
    cards = [{"id": f"c{i}", "_scored": True, "maya": {"check_id": "IDX-6", "severity_report": "S3", "launch_gated": []},
              "where": {"count": 2, "affected_urls": [f"{SITE}/a", f"{SITE}/b"]}} for i in range(8)]
    value, per_check = F.score(cards, cov, cfg)
    assert per_check == {"IDX-6": cfg["weights"]["S3"] * (cfg["share_floor"] + (1 - cfg["share_floor"]) * 0.2)}
    assert value == round(cfg["start"] - per_check["IDX-6"]) and cards[0]["points"] and all(c["points"] is None for c in cards[1:])
    # Integration keeps the local required-evidence safety contract, rather than excluding known uncertainty.
    gated = {"id": "g", "_scored": True, "maya": {"check_id": "STR-1", "severity_report": "S2", "launch_gated": ["LG-9"]},
             "where": {"count": 1, "affected_urls": [f"{SITE}/a"]}}
    assert F.score(cards + [gated], cov, cfg)[0] is None and F.unverified_scored(cards + [gated]) == [gated]
    assert F.score(cards, cov, cfg)[0] == value  # fully assessed contrast still uses one deduction per check


def test_the_score_is_on_the_cover_as_a_draft_and_not_in_a_kpi_box():
    d = valid_cards()
    assert not R.validate(copy.deepcopy(d))[0]
    page = R.build(d)
    kpis = page.split('<div class="kpis">')[1].split("</div></div>")[0]
    assert "puan" not in kpis.lower() and "Taslak puan (ağırlıklar kalibre edilmedi): 96/100" in page
    d["kpis"][0] = {"label": "Genel puan (taslak)", "value": "96/100 (taslak)"}
    assert any("KPI" in e for e in R.validate(d)[0])


def test_the_main_section_holds_one_card_per_check_and_names_the_rest():
    work, _ = work_of(h1_findings(4) + [finding("STR-1", id="STR-1-t", title="1 page(s) have no <title>", how_to_fix="Add a title.",
                                                scope={"kind": "page", "count": 1, "urls": [f"{SITE}/x"]})])
    data = work["data"]
    assert [c["maya"]["check_id"] for c in data["cards"]] == ["STR-2", "STR-1"] or \
        sorted(c["maya"]["check_id"] for c in data["cards"]) == ["STR-1", "STR-2"]
    assert len(data["appendix_cards"]) == 3
    page = C.html(work)
    assert "Aynı kontrolden 3 bulgu daha ekte" in page
    # Three cards that share one repair are one block in the appendix, whatever the total (CR-10); every ID stays.
    assert page.count('data-remediation-group="true"') == 1 and all(f"STR-2-h{i}" in page for i in range(4))
    assert 'data-subtype="STR-2:missing-h1"' in page and "Ortak uygulama: STR-2" not in page  # CR-09: no internal code in the heading
    assert "Sayım birimleri: {" not in page and "{'" not in page and "<pre>[" not in page


def test_two_cards_of_one_repair_stay_rows_and_the_address_is_said_once_per_card():
    work, _ = work_of(h1_findings(3))
    page = C.html(work)
    assert page.count('data-remediation-group="true"') == 0  # one main card, two appendix rows
    assert page.count("<tr id=\"finding-STR-2-h") == 2
    card = C.all_cards(work["data"])[0]
    assert f"{SITE}/branch/0" in " ".join(card["steps"]) and f"{SITE}/branch/0" not in card["verify"]  # CR-11


def test_the_skill_command_groups_by_default_and_no_group_prints_every_card(tmp_path):
    work, _ = work_of(h1_findings(5))
    cards = tmp_path / "cards.json"
    cards.write_text(json.dumps(work["data"], ensure_ascii=False), encoding="utf-8")
    compact, full = tmp_path / "compact.html", tmp_path / "full.html"
    for out, extra in ((compact, []), (full, ["--no-group"])):
        subprocess.run([sys.executable, str(SCRIPTS / "render_report.py"), str(cards), "-o", str(out), "--draft", *extra],
                       check=True, capture_output=True, cwd=ROOT)
    compact_text, full_text = compact.read_text(encoding="utf-8"), full.read_text(encoding="utf-8")
    assert 'data-remediation-group="true"' in compact_text and compact_text.count('<section class="card ') == 1  # H40
    assert full_text.count('<section class="card ') == 5 and "data-remediation-group" not in full_text
    # The same compact output as the web app's draft export of the same cards.
    assert compact_text.count('<section class="card ') == C.html(work).count('<section class="card ')


def test_an_exported_page_carries_its_own_content_security_policy():
    page = R.build(valid_cards())
    assert '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'' in page  # D-26
    assert "script-src" not in page.split("Content-Security-Policy")[1].split(">")[0]
