"""DECISIONS 367: a finding waiting in "Teyit edin" that is High (or Blocker), or P0/P1, takes a card slot like any
problem, before any Info note card; it stays "Kontrol edin", the PDF card says it is waiting for a check, and the client
brief still leaves it out. Info note cards only fill the slots left. Fake reports only."""
from __future__ import annotations

from maya_audit import client_selection as cs
from maya_audit import priority_levels

from test_v03_client_report import SITE, finding, report


def levels(monkeypatch, by_id: dict[str, str]):
    """Give each group the P-level its first finding is listed with (the formula is tested in DECISIONS 324)."""
    real = priority_levels.annotate

    def fake(rows, *args, **kw):
        real(rows, *args, **kw)
        for g in rows:
            fid = g["finding_ids"][0]
            if fid in by_id:
                g["p_level"] = {**(g.get("p_level") or {}), "level": by_id[fid]}
    monkeypatch.setattr(priority_levels, "annotate", fake)


def waiting(monkeypatch, ids):
    monkeypatch.setattr(cs, "confirm_reason", lambda f, c=None: "low_confidence" if f.get("id") in ids else None)


def test_a_high_or_p1_finding_waiting_for_a_check_takes_a_card_slot(monkeypatch):
    waiting(monkeypatch, {"H", "M1", "M2"})
    levels(monkeypatch, {"M1": "P1", "M2": "P2"})
    r = report([finding("A", "str1.shared", "S3", urls=[SITE + "/a"]),
                finding("H", "rnd1.main_missing", "S2", check="RND-1", urls=[SITE + "/a"]),
                finding("M1", "str11.contradicts", "S3", check="STR-11", urls=[SITE + "/a"]),
                finding("M2", "str9.wrong_language", "S3", check="STR-9", urls=[SITE + "/a"]),
                finding("N", "str2.questions", "Info", check="STR-2", urls=[SITE + "/a"])])
    sel = cs.select(r)
    card_ids = [g["finding_ids"][0] for g in sel["cards"]]
    assert card_ids[0] == "H" and "M1" in card_ids and "A" in card_ids
    assert [g["finding_ids"][0] for g in sel["confirm"]] == ["M2"]  # P2: still under "Teyit edin"
    h = next(g for g in sel["cards"] if g["finding_ids"][0] == "H")
    assert h["confirm_card"] and h["issue_type"] == "warning" and h["confirm_reason"] == "low_confidence"
    assert [g["finding_ids"][0] for g in sel["notes"]] == ["N"]


def test_with_no_room_left_a_p1_waits_but_a_high_still_takes_a_card(monkeypatch):
    waiting(monkeypatch, {"H", "M1"})
    levels(monkeypatch, {"M1": "P1"})
    full = [finding(f"F{i}", f"str1.shared{i}", "S4", urls=[SITE + "/a"]) for i in range(cs.MAX_CARDS)]
    r = report(full + [finding("H", "rnd1.main_missing", "S2", check="RND-1", urls=[SITE + "/a"]),
                       finding("M1", "str11.contradicts", "S3", check="STR-11", urls=[SITE + "/a"])])
    sel = cs.select(r)
    ids = {g["finding_ids"][0] for g in sel["cards"]}
    assert len(sel["cards"]) == cs.MAX_CARDS and "H" in ids
    # M1 is Medium: it outranks the Low cards by severity, so it takes a slot too; one more Low goes to the appendix
    assert "M1" in ids and len([g for g in sel["appendix_only"] if g["finding_ids"][0].startswith("F")]) == 2
    assert not sel["confirm"]


def test_a_p1_that_finds_no_room_goes_back_to_confirm(monkeypatch):
    waiting(monkeypatch, {"L1"})
    levels(monkeypatch, {"L1": "P1"})
    full = [finding(f"F{i}", f"str1.shared{i}", "S3", urls=[SITE + "/a"]) for i in range(cs.MAX_CARDS)]
    sel = cs.select(report(full + [finding("L1", "str7.over_100kb", "S4", check="STR-7", urls=[SITE + "/a"])]))
    assert [g["finding_ids"][0] for g in sel["confirm"]] == ["L1"] and not sel["confirm"][0].get("confirm_card")
    assert sel["confirm"][0]["issue_type"] == "warning"


def test_the_pdf_card_says_it_waits_and_the_brief_leaves_it_out(monkeypatch, tmp_path):
    import json
    from maya_audit_web.team_report import build_data
    waiting(monkeypatch, {"H"})
    r = report([finding("H", "rnd1.main_missing", "S2", check="RND-1", urls=[SITE + "/a"]),
                finding("A", "str1.shared", "S3", urls=[SITE + "/a"])])
    (tmp_path / "report.json").write_text(json.dumps(r), encoding="utf-8")
    data, _ = build_data.build_from_files(tmp_path / "report.json", "tr", reassess=False)
    card = next(t for t in data["todos"] if "H" in (t.get("finding_ids") or []))
    assert card["n"] == 1 and card["sub"][0] == "Doğrulama bekliyor: tahmini ölçüm"
    assert "H" in data["_confirm_ids"]


def test_link_rows_of_a_note_card_the_pdf_has_no_room_for_have_no_card_number():
    from maya_audit import client_appendix
    places = {"N1": [{"kind": "link", "source": SITE + "/a", "links_to": SITE + "/x", "status": 404, "href": "/x"}],
              "F1": [{"kind": "link", "source": SITE + "/b", "links_to": SITE + "/y", "status": 404, "href": "/y"}]}
    todos = [{"n": 1, "finding_ids": ["F1"]}, {"n": None, "appendix_only": True, "finding_ids": ["N1"]}]
    rows = client_appendix.where_rows(places, todos, "tr")  # an unnumbered card once made the sort fail
    assert [r[0] for r in rows] == [1, ""]
