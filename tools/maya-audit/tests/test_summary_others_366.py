"""DECISIONS 366: İlginay wants every problem in the Ek's "Özet", not only the PDF's cards. The cards stay first, as in the
PDF; below them "Diğer bulgular" lists every other problem group (Sorun, Kontrol edin, Fırsat; never Info notes,
rejected findings or Maya's own limits) with the cards' columns, by severity and then priority; a line at the top says
the first cards are in the PDF. Fake selections only."""
from __future__ import annotations

from maya_audit import client_appendix, xlsx
from maya_audit import client_selection as cs

from test_xlsx_pages_322 import _report


def group(fid, severity, placement, level, title, issue_type="issue", check="STR-1", urls=1):
    lead = {"id": fid, "check_id": check, "title": title, "severity": severity, "rule_id": "x.y"}
    return {"finding_ids": [fid], "severity": severity, "placement": placement, "p_level": {"level": level, "score": 1},
            "issue_type": issue_type, "lead": lead, "members": [lead], "title": title,
            "urls": [f"https://s.test/{i}" for i in range(urls)]}


def test_every_problem_that_is_no_card_is_listed_by_severity_then_priority():
    sel = {"groups": [group("A", "S3", "card", "P2", "on a card"),
                      group("A2", "S3", "card", "P2", "a card the PDF has no room for"),
                      group("B", "S4", "appendix", "P1", "low but urgent", urls=3),
                      group("C", "S2", "confirm", "P3", "high, to confirm", issue_type="warning"),
                      group("D", "S4", "appendix", "P3", "low later", issue_type="opportunity"),
                      group("E", "S2", "appendix", "P1", "high and urgent"),
                      group("F", "Info", "note", None, "a note"),
                      group("G", "S2", "rejected", "P0", "rejected by a person"),
                      group("H", "S3", "own_limit", "P2", "Maya's own limit")]}
    rows = [{"finding_id": f, "title": f"{f} name"} for f in ("A", "B", "C", "D", "E", "A2")]
    out = client_appendix.other_findings(sel, rows, {"A": 1}, [{"n": 1, "finding_ids": ["A"]}], "tr", "'Bulgu bazında'")
    assert [r[1] for r in out] == ["E name", "C name", "A2 name", "B name", "D name"]
    e = out[0]
    assert e[:5] == ["", "E name", "Yüksek", "Sorun", "P1"] and e[7] == 1
    assert e[5] in client_appendix.OWNER_WORDS["tr"].values() and e[6] in client_appendix.EFFORT_WORDS["tr"].values()
    assert e[8] == {"text": "Satırlara git →", "location": "'Bulgu bazında'!A6"}
    assert out[1][3] == "Kontrol edin" and out[4][3] == "Fırsat" and out[3][7] == 3


def test_the_cards_stay_first_and_the_line_on_top_says_where_they_are():
    todos = [{"n": 1, "title": "Renew the TLS certificate", "severity": "S2", "issue_type": "issue", "finding_ids": ["IDX-2-c"],
              "all_urls": []}]
    book = xlsx.read(client_appendix.build(cs.select(_report()), "tr", todos=todos))
    rows = book["Özet"]
    assert rows[2][1] == "İlk 1 kart PDF raporundadır; diğer bulgular aşağıdadır."
    assert rows[3][:2] == ["1", "Renew the TLS certificate"]
    others = rows[4]
    assert others[0] == "" and others[1].startswith("Diğer bulgular (")
    listed = rows[5:]
    assert len(listed) == 2  # the two cards the PDF (one card here) has no room for; the Info note is left out
    assert all(r[0] == "" and r[2] in ("Kritik", "Yüksek", "Orta", "Düşük") for r in listed)
    order = {"Kritik": 0, "Yüksek": 1, "Orta": 2, "Düşük": 3}
    assert [order[r[2]] for r in listed] == sorted(order[r[2]] for r in listed)
