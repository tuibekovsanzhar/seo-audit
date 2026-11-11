"""DECISIONS 341: each "Bulgu bazında" row of an early-closed <head> is built from that page's own record (enpara
fee70191: 90 rows said "kritik etiketler okunmuyor … canonical, robots ve hreflang" with "Ölçülen değer" "—").

The fake site is DECISIONS 339's (tests/test_head_card_339.py): /form carries robots noindex after <div id="overlay">;
/a, /b, /c carry a description and og:title after it; canonical and title stay before it everywhere.
"""
from __future__ import annotations

import pytest

from maya_audit import client_selection, final, page_rows
from maya_audit.page_rows import head_row_words
from test_head_card_339 import routes
from test_m1_broken_links import audit
from test_firecrawl import no_lookups  # noqa: F401  (fixture)

DIV = {"tag": "div", "id": "blueLightOverlay", "class": "", "line": 1}


def test_a_high_row_names_the_tag_after_the_break_and_what_the_head_keeps():
    row = {"closed_by": DIV, "robots_after": ["robots"], "robots_content": ["noindex"], "canonical_after": 0,
           "hreflang_after": 0, "title_after": 0, "meta_after": ["generator"], "properties_after": ["og:title"],
           "kept_in_head": ["canonical", "title"]}
    words = head_row_words(row, "tr")
    assert words["title"] == "<head> erken kapanıyor: robots (noindex) bu öğeden sonra kalıyor"
    assert words["value"] == ("robots (noindex), <div#blueLightOverlay> sonrasında; head'de bu etiketin bir kopyası yok. "
                              "<div#blueLightOverlay> öncesinde, head'de: canonical, title")
    assert words["fix"] == "<div#blueLightOverlay> öğesini gövdeye taşıyın; robots (noindex) head'de, bu öğeden önce kalmalı."


def test_a_medium_row_lists_what_comes_after_and_what_is_before_it():
    row = {"closed_by": DIV, "robots_after": ["robots"], "robots_content": ["index, follow"], "canonical_after": 1,
           "hreflang_after": 0, "title_after": 0, "meta_after": ["description", "generator"],
           "properties_after": ["og:image"], "kept_in_head": ["canonical", "hreflang", "title"]}
    words = head_row_words(row, "tr")
    assert words["title"] == "<head> erken kapanıyor: yalnız meta ve Open Graph etiketleri sonra geliyor"
    assert words["value"] == ("<div#blueLightOverlay> sonrasında: ikinci bir canonical kopyası, description, Open Graph, "
                              "generator, robots (index, follow); canonical, title, hreflang ondan önce, head'de")
    assert "canonical, robots ve hreflang" not in words["fix"]


def test_a_canonical_with_no_copy_before_the_break_is_said_lost():
    row = {"closed_by": {"tag": "img"}, "canonical_after": 1, "kept_in_head": ["title"]}
    assert head_row_words(row, "en")["value"].startswith("canonical after <img>, with no copy in the head")


@pytest.fixture(scope="module")
def rows():
    outcome, base = audit(routes())
    sealed = final.seal(outcome)
    sel = client_selection.select(sealed.report, sealed.affected, {})
    out = page_rows.finding_rows(sel, sealed.affected, "tr")
    return {r["url"].removeprefix(base): r for r in out if (r["rule_id"] or "").startswith("tseo1.head_closed")}


def test_every_row_of_the_card_says_its_own_page(rows):
    assert set(rows) == {"/form", "/a", "/b", "/c"}
    assert rows["/form"]["severity"] == "S2" and rows["/form"]["value"].startswith("robots (noindex), <div#overlay> sonrasında")
    for path in ("/a", "/b", "/c"):
        assert rows[path]["value"] == "<div#overlay> sonrasında: description, Open Graph; canonical, title ondan önce, head'de"
    assert not any(r["value"] in ("", "—") or "kritik etiketler okunmuyor" in r["title"] for r in rows.values())


def test_the_selection_reads_every_page_not_only_the_evidence_sample():
    report = {"crawl": {"pages": [{"url": f"https://b.test/{i}", "analysis": {
        "title": "T", "canonicals": ["x"], "outside_head": {"closed_early_by": DIV, "meta": ["description"], "properties": []}}}
        for i in range(60)]}, "checks": []}
    rows_ = client_selection.head_rows(report)
    assert len(rows_) == 60 and rows_["https://b.test/59"]["kept_in_head"] == ["canonical", "title"]
