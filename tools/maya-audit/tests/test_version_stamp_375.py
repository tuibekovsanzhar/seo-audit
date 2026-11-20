"""DECISIONS 375: the version stamp is for the team, not the client. No PDF shows it; the Ek says it in one short line,
the last row of "Yöntem", and in the file's document properties with the build time; "Kapsam" starts with the audit's
own rows again. Fake data only."""
from __future__ import annotations

import io
import re
import zipfile

import pytest

from maya_audit import client_appendix, version_stamp, xlsx
from maya_audit import client_selection as cs

from test_v03_client_report import SITE, finding, report


def _ek() -> bytes:
    return client_appendix.build(cs.select(report([finding("A", "str1.shared", "S4", urls=[SITE + "/a"])])), "tr")


def test_the_stamp_is_one_short_line_at_the_end_of_yontem_and_not_in_kapsam():
    book = xlsx.read(_ek())
    assert re.fullmatch(r"Sürüm: \S+ · commit (\w{7}|kaydedilmedi)", book["Yöntem"][-1][0])
    assert len([c for c in book["Yöntem"][-1] if c]) == 1
    assert not any("Sürüm" in str(c) or "Maya Audit " in str(c) for r in book["Kapsam"] for c in r)


def test_the_stamp_is_in_the_document_properties_with_the_build_time():
    with zipfile.ZipFile(io.BytesIO(_ek())) as z:
        core = z.read("docProps/core.xml").decode()
        assert "docProps/core.xml" in z.read("_rels/.rels").decode()
        assert "/docProps/core.xml" in z.read("[Content_Types].xml").decode()
    assert "<dc:creator>Maya Audit</dc:creator>" in core
    assert re.search(r"<dc:description>Maya Audit \S+ · commit \S+ · built \d{4}-\d\d-\d\d \d\d:\d\d UTC</dc:description>", core)
    assert re.search(r"<dcterms:created xsi:type=\"dcterms:W3CDTF\">\d{4}-\d\d-\d\dT", core)


def test_a_workbook_without_properties_has_no_core_part():
    with zipfile.ZipFile(io.BytesIO(xlsx.workbook([{"name": "A", "header": ["x"], "rows": [["1"]]}]))) as z:
        assert "docProps/core.xml" not in z.namelist()


@pytest.mark.parametrize("lang", ["tr", "en"])
def test_no_pdf_data_carries_the_stamp(tmp_path, lang):
    from test_team_report import built, synthetic, visible_strings
    data = built(tmp_path, synthetic([("STR-1", "str1.shared")]), lang)
    shown = [v for _, v in visible_strings(data)]
    assert shown and not [v for v in shown if " · commit " in v or v.startswith(("Sürüm:", "Version:"))]
    assert version_stamp.short("en").startswith("Version: ")
