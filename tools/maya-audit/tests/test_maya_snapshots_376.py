"""DECISIONS 376, phase 2: the Search Console datasets the client Ek's sheets read, from synthetic Maya export files:
daily totals over the whole period and its last 28 days, the AI Overview columns (absent, empty, filled), weekly
28-day page and query snapshots (latest per page or query, never summed, weeks present), page scores, query intents
and query opportunities, each with its own period. No client file, no network."""
from __future__ import annotations

from datetime import date, timedelta

from maya_audit import maya_data

SITE = "https://www.demo.test"


def _write(folder, name, header, rows):
    path = folder / name
    path.write_text(",".join(header) + "\n" + "".join(",".join(str(c) for c in r) + "\n" for r in rows), encoding="utf-8")
    return path


def _days(n=40, start=date(2026, 9, 1)):
    return [(start + timedelta(days=i)).isoformat() for i in range(n)]


def test_daily_totals_are_the_whole_period_and_its_last_28_days_each_with_its_dates(tmp_path):
    rows = [[d, 10, 100, 0.1, 5, "", "", "", ""] for d in _days()]
    _write(tmp_path, "demo.test-gsc-daily-stats-2026-09-01-2026-10-10.csv",
           ["date", "clicks", "impressions", "ctr", "position", "aio_clicks", "aio_impressions", "aio_ctr", "aio_position"], rows)
    gsc = maya_data.prepare([tmp_path], SITE + "/")["gsc"]
    whole, last = gsc["totals"]["whole"], gsc["totals"]["last28"]
    assert whole == {"period": ["2026-09-01", "2026-10-10"], "days": 40, "clicks": 400, "impressions": 4000, "ctr": 0.1,
                     "position": 5.0}
    assert last["days"] == 28 and last["period"] == ["2026-09-13", "2026-10-10"] and last["clicks"] == 280
    assert gsc["aio"] == {"columns": True, "days": 0, "period": None, "clicks": 0, "impressions": 0}  # empty: "Veri yok"


def test_ai_overview_columns_absent_or_filled(tmp_path):
    _write(tmp_path, "demo.test-gsc-daily-stats-2026-09-01-2026-09-03.csv", ["date", "clicks", "impressions", "ctr", "position"],
           [[d, 1, 10, 0.1, 3] for d in _days(3)])
    assert maya_data.prepare([tmp_path], SITE + "/")["gsc"]["aio"] == {"columns": False}
    other = tmp_path / "b"
    other.mkdir()
    _write(other, "demo.test-gsc-daily-stats-2026-09-01-2026-09-03.csv",
           ["date", "clicks", "impressions", "ctr", "position", "aio_clicks", "aio_impressions"],
           [["2026-09-01", 1, 10, 0.1, 3, 2, 50], ["2026-09-02", 1, 10, 0.1, 3, "", ""], ["2026-09-03", 1, 10, 0.1, 3, 1, 25]])
    aio = maya_data.prepare([other], SITE + "/")["gsc"]["aio"]
    assert aio == {"columns": True, "days": 2, "period": ["2026-09-01", "2026-09-03"], "clicks": 3, "impressions": 75}


def test_weekly_snapshots_keep_the_latest_row_never_a_sum_and_count_the_weeks(tmp_path):
    _write(tmp_path, "demo.test-gsc-top-pages-2026-08-15-2026-11-13.csv", ["week_start", "page", "clicks", "impressions", "ctr", "position"],
           [["2026-10-03", SITE + "/a", 900, 9000, 0.1, 2.0], ["2026-10-10", SITE + "/a/", 1000, 10000, 0.1, 2.1],
            ["2026-10-10", SITE + "/b?utm_source=x", 5, 50, 0.1, 9.0]])
    _write(tmp_path, "demo.test-gsc-top-queries-2026-08-15-2026-11-13.csv", ["week_start", "query", "clicks", "impressions", "ctr", "position"],
           [["2026-10-03", "demo kredi", 50, 500, 0.1, 1.0], ["2026-10-10", "demo kredi", 60, 600, 0.1, 1.0]])
    gsc = maya_data.prepare([tmp_path], SITE + "/")["gsc"]
    pages = gsc["top_pages"]
    assert pages["weeks"] == ["2026-10-03", "2026-10-10"] and pages["period"] == ["2026-08-15", "2026-11-13"]
    assert pages["rows"][SITE + "/a"] == {"week": "2026-10-10", "clicks": 1000, "impressions": 10000, "ctr": 0.1,
                                         "position": 2.1, "weeks_listed": 2}  # the latest 28 days, not 1,900 clicks
    assert pages["rows"][SITE + "/b"]["weeks_listed"] == 1  # tracking parameters off
    assert gsc["top_queries"]["rows"]["demo kredi"]["clicks"] == 60


def test_page_scores_intents_and_opportunities_keep_their_fields_and_periods(tmp_path):
    _write(tmp_path, "demo.test-gsc-page-scores.csv", ["page", "clicks", "impressions", "ctr", "position", "query_count",
                                                      "position_score", "click_score", "impression_score", "ctr_score",
                                                      "query_diversity_score", "authority_score"],
           [[SITE + "/a", 10, 100, 0.1, 3, 387, 1, 1, 1, 1, 1, 90]])
    _write(tmp_path, "demo.test-gsc-query-intents.csv", ["query", "intent", "confidence", "is_brand", "classifier_source"],
           [["demo", "brand_search", 0.9, "yes", "llm"], ["kredi hesaplama", "informational", 0.7, "no", "llm"]])
    _write(tmp_path, "demo.test-gsc-query-opportunities.csv",
           ["query", "page", "impressions", "clicks", "ctr", "position", "opportunity_score", "opportunity_type",
            "recommended_action", "period_start", "period_end"],
           [["faizsiz kredi", f"{SITE}/x | {SITE}/y", 188295, 0, 0, 0, 70, "cannibalization", "2 pages compete", "2026-10-10", "2026-11-07"],
            ["kredi", "", 5000, 10, 0.002, 4.1, 92, "high_impression_low_ctr", "Improve title", "2026-10-10", "2026-11-07"]])
    summary = maya_data.prepare([tmp_path], SITE + "/")
    gsc = summary["gsc"]
    assert gsc["page_scores"]["rows"][SITE + "/a"]["query_count"] == 387 and gsc["page_scores"]["rows"][SITE + "/a"]["authority_score"] == 90
    assert gsc["intents"]["rows"]["demo"] == {"intent": "brand_search", "brand": True, "confidence": 0.9}
    assert gsc["intents"]["rows"]["kredi hesaplama"]["brand"] is False
    opps = gsc["opportunities"]
    assert opps["period"] == ["2026-10-10", "2026-11-07"]
    first = opps["rows"][0]
    assert first["query"] == "kredi" and first["score"] == 92  # by score
    canni = opps["rows"][1]
    assert canni["pages"] == [SITE + "/x", SITE + "/y"] and canni["type"] == "cannibalization" and canni["impressions"] == 188295
    counts = {d["dataset"]: d["rows"] for d in summary["datasets"]}
    assert counts["gsc-query-opportunities"] == 2 and counts["gsc-query-intents"] == 2 and counts["gsc-page-scores"] == 1


def test_an_older_summary_is_made_again_from_the_kept_files(tmp_path):
    files = tmp_path / maya_data.FOLDER
    files.mkdir()
    _write(files, "demo.test-gsc-query-intents.csv", ["query", "intent", "confidence", "is_brand", "classifier_source"],
           [["demo", "brand_search", 0.9, "yes", "llm"]])
    (tmp_path / maya_data.SUMMARY_FILE).write_text('{"version": 4, "origin": "https://www.demo.test"}', encoding="utf-8")
    again = maya_data.load_for(tmp_path)
    assert again["version"] == maya_data.VERSION >= 5 and "demo" in again["gsc"]["intents"]["rows"]
