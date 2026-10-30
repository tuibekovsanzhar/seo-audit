"""End-to-end acceptance on the Arjava-like shop (fakeserver/arjava_scenarios.py).

Each test is one thing a correct audit says about that site. Tests marked xfail(strict=True) name the fix in the
review's plan (H09..H34) that makes them pass; strict means a fix that starts passing must remove its marker, so the
file always states exactly what the engine does today.

Findings are matched by words in their title, not by check id, so a fix may live in whichever check owns it.
"""

from __future__ import annotations

import pytest

from fakeserver import FakeServer
from fakeserver.arjava_scenarios import ARJAVA_SCENARIOS
from maya_audit.audit import run_audit
from maya_audit.config import CrawlConfig
from maya_audit.report import build_report

TEST_PAGES = {"/test-marka", "/arjava-2", "/arjava-3", "/test-22222", "/test-sayfaaaa"}


class Run:
    def __init__(self, outcome, requests, base):
        self.outcome, self.requests, self.base = outcome, requests, base
        self.checks = {c.check_id: c for c in outcome.checks}
        self.findings = [f for c in outcome.checks for f in c.findings]
        self.report = build_report(outcome.result, outcome.gates, outcome.checks)

    def paths(self, finding) -> set[str]:
        urls = finding.scope.get("_all_urls") or finding.scope.get("urls") or []
        return {u.replace(self.base, "") or "/" for u in urls}

    def titled(self, *words: str, check: str | None = None) -> list:
        """Findings whose title holds every word (case-insensitive), optionally from one check."""
        return [f for f in self.findings if all(w.lower() in f.title.lower() for w in words)
                and (check is None or f.check_id == check)]


@pytest.fixture(scope="module")
def arjava() -> Run:
    scenario = ARJAVA_SCENARIOS["arjava"]
    with FakeServer(scenario.build()) as server:
        config = CrawlConfig(**{"request_delay_s": 0.0, "robots_sample_interval_s": 0.05, "probe_retry_cooldown_s": 0.0,
                                "refetch_delay_s": 0.0, "render_enabled": False, "prf_round_gap_s": 0.0, **scenario.config})
        outcome = run_audit(server.base_url + "/", config)
        return Run(outcome, list(server.requests), server.base_url)


# -- what the engine already says correctly -----------------------------------------------------------------------
def test_unfilled_template_markers_on_the_signup_page_are_found(arjava):
    [finding] = arjava.titled("unfilled template markers")
    assert arjava.paths(finding) == {"/UyeOl"} and "{{IsValidUyeOlSifreStrengthShowMessage}}" in finding.title


def test_every_sitemap_url_carrying_the_same_lastmod_is_found(arjava):
    assert arjava.titled("lastmod", check="IDX-5")


def test_og_site_name_holding_the_page_title_is_found(arjava):
    assert arjava.titled("og:site_name holds the page title")


def test_links_a_crawler_cannot_follow_on_product_pages_are_found(arjava):
    [finding] = arjava.titled("no address a crawler can follow")
    assert "/arjava-koku-difuzoru-bej-13" in arjava.paths(finding)


def test_legal_pages_without_a_title_are_found(arjava):
    [finding] = arjava.titled("have no <title>")
    assert {"/mesafeli-satis-sozlesmesi", "/teslimat-ve-iade"} <= arjava.paths(finding)


def test_the_disallowed_checkout_is_never_requested(arjava):
    assert not [r for r in arjava.requests if r.route_path.startswith("/checkout")]


# -- what the review found wrong, by fix --------------------------------------------------------------------------
def test_cloudflare_email_obfuscation_is_a_note_not_a_broken_link(arjava):
    broken = [f for f in arjava.findings if f.check_id in ("IDX-1", "IDX-6") and "cdn-cgi" in (f.title + str(f.evidence))]
    assert broken == []
    [note] = [f for f in arjava.findings if "cloudflare" in f.title.lower() and "mail" in f.title.lower()]
    assert note.severity.value == "Info"


def test_a_broken_organization_block_is_reported_as_broken_not_missing(arjava):
    assert arjava.titled("has no Organization") == []
    [broken] = [f for f in arjava.findings if f.check_id == "STR-3" and "organization" in f.title.lower()]
    text = str(broken.evidence).lower()
    assert "line" in text and "column" in text and ("newline" in text or "control character" in text)
    assert "add organization json-ld" not in broken.how_to_fix.lower()


def test_severity_and_cap_note_agree(arjava):
    contradictory = [f for f in arjava.findings if "Capped at S4" in " ".join(f.notes) and f.severity.value in ("S1", "S2", "S3")]
    assert contradictory == []


def test_draft_pages_are_reported_once_with_the_right_advice(arjava):
    [drafts] = [f for f in arjava.findings if TEST_PAGES <= arjava.paths(f) and "noindex" in f.how_to_fix.lower()]
    assert drafts.severity.value in ("S3", "S4")
    for finding in arjava.findings:
        if finding.check_id == "IDX-7" and arjava.paths(finding) & TEST_PAGES:
            raise AssertionError("IDX-7 still tells the owner to link to draft pages")


def test_a_shop_is_not_told_it_has_no_product_page(arjava):
    assert [f for f in arjava.findings if f.check_id == "STR-21" and "product" in f.title.lower()] == []


def test_a_hidden_h1_is_reported(arjava):
    [hidden] = arjava.titled("h1", "hidden")
    assert "/" in arjava.paths(hidden)


def test_placeholder_alt_text_is_reported(arjava):
    [placeholder] = arjava.titled("placeholder alt")
    assert "/" in arjava.paths(placeholder)


def test_an_ungrouped_robots_rule_is_reported(arjava):
    assert [f for f in arjava.findings if "robots.txt" in f.title.lower() and "/cdn-cgi/" in (f.title + str(f.evidence))]


def test_one_page_at_two_addresses_is_reported(arjava):
    assert [f for f in arjava.findings if {"/UyeGiris", "/UyeGiris.aspx"} <= arjava.paths(f) and "address" in f.title.lower()]


def test_an_hreflang_target_with_an_empty_title_is_reported(arjava):
    assert [f for f in arjava.findings if f.check_id == "STR-9" and "/en" in arjava.paths(f)]


def test_html_not_cached_at_the_cdn_is_recorded(arjava):
    assert "DYNAMIC" in str(arjava.report)
    assert [f for f in arjava.findings if "cache" in f.title.lower()]


def test_heavy_media_is_reported(arjava):
    text = " ".join(f.title + str(f.evidence) for f in arjava.findings)
    assert "banner1.jpg" in text and "promo.mp4" in text and "image/png" in text


def test_loading_behaviour_is_reported(arjava):
    assert arjava.titled("width") and arjava.titled("script")


def test_a_placeholder_video_object_is_reported(arjava):
    [video] = [f for f in arjava.findings if "videoobject" in f.title.lower()]
    assert "uploaddate" in str(video.evidence).lower()


def test_social_preview_gaps_are_reported(arjava):
    # Review G13 (lead's instruction, gx2): a missing twitter:card is recorded as an STR-10 observation, not a finding,
    # because nothing tells this shop apart from the healthy sites where it is noise. The gap is still recorded.
    assert any("twitter" in str(o.get("metric", "")).lower() and o.get("pages") for o in arjava.checks["STR-10"].observations)
    assert arjava.titled("og:description")  # the og: gaps themselves are still findings


def test_duplicate_analytics_tags_are_reported(arjava):
    assert [f for f in arjava.findings if "GTM-N7M2FVGL" in f.title + str(f.evidence)]


def test_the_platform_is_recognised(arjava):
    platform = arjava.report.get("platform") or {}
    assert "Ticimax" in str(platform) and "Cloudflare" in str(platform)


# -- seen on the live site after the generalisation round ------------------------------------------------------------
def test_an_image_placeholder_that_points_at_the_page_is_not_an_image_that_fails(arjava):
    """src="#" resolves to the page itself; the live run reported such pages as "image files that do not load"."""
    for finding in arjava.titled("do not load"):
        assert not any(row.get("image") == row.get("shown_on", [None])[0] for row in finding.evidence.get("images", []))
        assert not any(arjava.base + "/UyeGiris" == row.get("image") for row in finding.evidence.get("images", []))


def test_a_draft_word_last_in_the_slug_still_names_a_draft(arjava):
    [drafts] = [f for f in arjava.findings if TEST_PAGES <= arjava.paths(f) and "noindex" in f.how_to_fix.lower()]
    assert "/sss-test" in arjava.paths(drafts)


def test_the_same_broken_organization_block_on_another_page_is_one_finding(arjava):
    [broken] = [f for f in arjava.findings if f.check_id == "STR-3" and "organization block" in f.title.lower()]
    assert "/en" in arjava.paths(broken)
    assert not [f for f in arjava.findings if f.check_id == "STR-3" and "does not parse" in f.title and "/en" in arjava.paths(f)
                and f is not broken]
