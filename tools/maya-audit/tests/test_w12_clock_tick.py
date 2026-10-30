"""DECISIONS 274: an empty page asked twice is two observations even when the clock gave both requests one timestamp
(Windows ticks in ~16 ms steps; on a fast site the crawl and the IDX-1 refetch can share one). Seen as a flaky test
in three files; here the clock is fixed so it fails every time without the fix."""
from unittest import mock

import test_round2_sitemap_and_llms as sitemap_tests
from test_brand_and_launch_gate import no_lookups  # noqa: F401
from test_false_alarms import audited


def test_two_empty_answers_with_one_timestamp_are_still_repeated(no_lookups):
    routes, paths = sitemap_tests.thirty()
    with mock.patch("maya_audit.fetcher.utc_now", return_value="2026-10-27T12:00:00.000000+00:00"):
        outcome = audited(routes, sitemap=paths)
    empty = [f for f in outcome.by_id["IDX-1"].findings if "empty page" in f.title]
    repeated = [f for f in empty if f.evidence["observation_strength"] == "repeated_empty_same_client_only"]
    assert [p["url"].rsplit("/", 2)[-2:] for f in repeated for p in f.evidence["pages"]] == [["urun", "4"]]
    # The sitemap's light requests stay one observation each.
    single = [f for f in empty if f.evidence["observation_strength"] == "single_probe_or_missing_corroboration"]
    assert sorted(p["url"][-7:] for f in single for p in f.evidence["pages"]) == ["/urun/8", "urun/12"]
