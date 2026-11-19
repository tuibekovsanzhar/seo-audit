"""DECISIONS 372: bugs from Efsa's revision-compliance review (F01-F10 as far as the review text names them), each
reproduced here first. A value the data does not give is None ("veri yok"), never 0. Fake data only."""
from __future__ import annotations

import pytest

from maya_audit import maya_data


@pytest.fixture
def idx(run_audit_scenario):
    def _run(name):
        return run_audit_scenario(name)
    return _run


# ---------------------------------------------------------------- F01: a malformed <lastmod> stopped the sitemap check

def test_a_malformed_lastmod_is_counted_and_the_check_still_reports_the_future_one(idx):
    run = idx("idx_sitemap_bad_lastmod")
    check = run.checks["IDX-5"]
    assert check.status != "error"
    assert check.evidence["lastmod_unparsed"] == 3 and check.evidence["lastmod_present"] == 2
    assert set(check.evidence["lastmod_unparsed_sample"].values()) == {"16/11/2026", "{lastmod}", "2026-13-45"}
    [future] = [f for f in run.findings("IDX-5") if "future" in f.title]
    assert list(future.evidence["future_lastmod"]) == [run.url("/b")]


def test_lastmods_that_are_all_the_same_bad_value_are_not_called_identical_dates(idx):
    run = idx("idx_sitemap_only_bad_lastmod")
    assert not [f for f in run.findings("IDX-5") if "identical" in f.title]
    assert run.checks["IDX-5"].evidence["lastmod_unparsed"] == 3


# ---------------------------------------------------------------- missing values are None, never 0

def test_a_missing_rate_or_position_is_none_not_zero():
    assert maya_data._value("") is None and maya_data._value(None) is None and maya_data._value("n/a") is None
    assert maya_data._value("0") == 0.0 and maya_data._value("3,5") == 3.5
    assert maya_data._num("") == 0.0  # a count to add up: a missing cell adds nothing


def test_topic_visibility_with_a_missing_rate_has_no_made_up_gap(tmp_path):
    from maya_audit.maya_data import _visibility
    rows = [{"topic": "kredi", "week_start": "2026-11-02", "brand_rate": "", "top_competitor_name": "Rival",
             "top_competitor_rate": "40", "total": ""},
            {"topic": "kredi", "week_start": "2026-11-09", "brand_rate": "", "top_competitor_name": "Rival",
             "top_competitor_rate": "42", "total": "12"}]
    out = _visibility({"topic-visibility-snapshots": _source(rows)}, {}, [], keys=set())
    [t] = out["topics"]
    assert t["brand_first"] is None and t["brand_last"] is None and t["gap"] is None
    assert t["leader_last"] == 42.0 and t["answers"] == 12


def test_a_page_score_without_ctr_or_position_says_so():
    out = maya_data._gsc({"gsc-page-scores": _source([{"page": "https://s.test/a", "clicks": "5", "impressions": "100",
                                                         "ctr": "", "position": ""}])}, "https://s.test", ["Shop"])
    page = out["pages"]["https://s.test/a"]
    assert page["ctr"] is None and page["position"] is None and page["clicks"] == 5.0


def test_a_position_is_averaged_only_over_rows_that_give_one():
    rows = [{"date": "2026-11-01", "page": "https://s.test/a", "clicks": "1", "impressions": "100", "position": "4"},
            {"date": "2026-11-02", "page": "https://s.test/a", "clicks": "1", "impressions": "100", "position": ""}]
    out = maya_data._gsc({"gsc-search-performance": _source(rows)}, "https://s.test", ["Shop"])
    assert out["pages"]["https://s.test/a"]["position"] == 4.0  # not 2.0 from a missing position read as 0


def test_the_sheet_writes_veri_yok_for_a_value_it_does_not_have():
    from maya_audit.maya_sheets import NO_DATA, _or_none
    assert _or_none(None) == NO_DATA == "veri yok" and _or_none(0) == 0


# ---------------------------------------------------------------- brand matching

def test_a_short_brand_name_matches_only_as_a_whole_word():
    assert maya_data._is_brand("ing bank giriş", ["ING"])
    assert not maya_data._is_brand("ingilizce kurs", ["ING"])
    assert maya_data._is_brand("enparalı kart", ["Enpara"])  # a longer name keeps its Turkish suffixes


def _source(rows):
    import csv
    import io
    keys = list(dict.fromkeys(k for r in rows for k in r))
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=keys)
    writer.writeheader()
    writer.writerows(rows)
    text = buf.getvalue()
    return maya_data.Source("data.csv", lambda: io.StringIO(text))
