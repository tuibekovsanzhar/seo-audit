"""Report length guard across site types (gx3): a regression net, not a style rule.

For each neutral fixture site (fakeserver/neutral_scenarios.py) and the Arjava regression shop, the full Markdown report
and the concise (client) HTML print are measured:
- words: at most a cap set from the measured size of this fixture set plus headroom (WORDS);
- repeated lines: no line over 40 characters is said more than twice (addresses and numbers masked, so "the same line
  about another page" counts as the same; table rows of "Problems by page" are one row per page by design and the
  appendices hold one record per page, so both are left out);
- the first action: within the first 40 lines, the reader meets the first thing to fix (or the sentence that says
  there is none).
A failure here means a change made a report longer or more repetitive on some kind of site: look at that output first,
and raise a cap only with a reason."""

from __future__ import annotations

import html as markup
import json
import re
from collections import Counter

import pytest

from fakeserver import FakeServer
from fakeserver.arjava_scenarios import ARJAVA_SCENARIOS
from fakeserver.neutral_scenarios import NEUTRAL_SCENARIOS
from maya_audit import report as R
from maya_audit.audit import run_audit
from maya_audit.config import CrawlConfig
from maya_audit.report import build_report
from tests.test_brand_neutral import audit, hermetic

SITES = sorted(NEUTRAL_SCENARIOS) + ["arjava"]
# (Markdown, concise) word caps per site: measured on 2026-10-22 (gx3) plus about 30% headroom. Measured then:
# bank-multi 3988/2000, draft-real 3688/1570, local-wp 3425/1205, news-video 2672/852, saas-spa 4232/2028,
# shop-de 3357/1310, shopify 3113/1051, tarif-sube 3490/1417, arjava 6945/3823.
WORDS = {"bank-multi": (5200, 2600), "draft-real": (4800, 2100), "local-wp": (4500, 1600), "news-video": (3500, 1100),
         "saas-spa": (5500, 2600), "shop-de": (4400, 1700), "shopify": (4000, 1400), "tarif-sube": (4500, 1850),
         "arjava": (9000, 5000)}
REPEATS = 2
FIRST_ACTION_LINE = 40
# Sections that list one row per page or per record by design (their rows differ only by address).
PER_PAGE_SECTIONS = ("Problems by page", "Coverage and checks", "Appendix", "Pages crawled", "Evidence")


class Outputs:
    def __init__(self, site: str, markdown: str, concise: str):
        self.site, self.markdown, self.concise = site, markdown, concise


def _arjava(home: str):
    scenario = ARJAVA_SCENARIOS["arjava"]
    with hermetic(home), FakeServer(scenario.build()) as server:
        config = CrawlConfig(**{"request_delay_s": 0.0, "robots_sample_interval_s": 0.05, "probe_retry_cooldown_s": 0.0,
                                "refetch_delay_s": 0.0, "render_enabled": False, "prf_round_gap_s": 0.0, **scenario.config})
        return run_audit(server.base_url + "/", config)


def _concise(report: dict) -> str:
    from maya_audit_web import pdf, practical, summary
    view = summary.build(report, outcome="COMPLETE", reason="")
    rows = summary.search(report, limit=100_000)["items"]
    return pdf.render_html(view, rows=rows, plan=summary.action_plan(report), generated_at="2026-10-22",
                           practical=practical.build(view, rows, report, None), concise=True)


@pytest.fixture(scope="module", params=SITES)
def outputs(request, tmp_path_factory) -> Outputs:
    home = str(tmp_path_factory.mktemp("gx3-length"))
    outcome = _arjava(home) if request.param == "arjava" else audit(request.param, home).outcome
    markdown = R.render_markdown(outcome.result, outcome.gates, outcome.checks)
    report = json.loads(json.dumps(build_report(outcome.result, outcome.gates, outcome.checks), default=str))
    return Outputs(request.param, markdown, _concise(report))


def html_lines(page: str) -> list[str]:
    """The concise page as the lines a reader sees: one per block element (heading, paragraph, list item, table row)."""
    page = re.sub(r"<(style|script)\b.*?</\1>", " ", page, flags=re.S)
    page = re.sub(r"</?(?:h[1-6]|p|li|tr|div|section|ul|ol|table|thead|tbody|br)\b[^>]*>", "\n", page)
    text = markup.unescape(re.sub(r"<[^>]+>", " ", page))
    return [" ".join(line.split()) for line in text.splitlines() if line.strip()]


def markdown_lines(markdown: str) -> list[str]:
    return [line.strip() for line in markdown.splitlines() if line.strip()]


def _without_per_page(lines: list[str], heading: re.Pattern) -> list[str]:
    kept, skipping = [], False
    for line in lines:
        found = heading.match(line)
        if found:
            skipping = any(found.group(1).startswith(name) for name in PER_PAGE_SECTIONS)
        if not skipping:
            kept.append(line)
    return kept


# A card's field row ("**Check:** STR-7 · **Confidence:** verified · **Affected pages:** 3") is a label row like a table
# row: with numbers masked every card of one check reads the same, and it is not a sentence said again.
FIELD_ROW = "**Check:**"


def repeated(lines: list[str]) -> dict[str, int]:
    masked = [re.sub(r"\d+", "N", re.sub(r"https?://\S+|`[^`]*`", "URL", line)) for line in lines
              if not line.startswith(FIELD_ROW)]
    said = Counter(line for line in masked if len(line) > 40 and not set(line) <= set("|-: "))
    return {line: n for line, n in said.items() if n > REPEATS}


def words(text: str) -> int:
    return len(text.split())


def test_the_markdown_report_stays_short(outputs):
    assert words(outputs.markdown) <= WORDS[outputs.site][0]


def test_the_concise_print_stays_short(outputs):
    assert words(" ".join(html_lines(outputs.concise))) <= WORDS[outputs.site][1]


def test_no_markdown_line_is_said_more_than_twice(outputs):
    lines = _without_per_page(markdown_lines(outputs.markdown), re.compile(r"^#+ (.+)$"))
    assert repeated(lines) == {}


def test_no_concise_line_is_said_more_than_twice(outputs):
    lines = html_lines(outputs.concise)
    headings = set(re.findall(r"<h2>(.*?)</h2>", outputs.concise))
    kept, skipping = [], False
    for line in lines:
        if line in headings:
            skipping = line.startswith(("Problems by page", "Sayfa bazında"))
        if not skipping:
            kept.append(line)
    assert repeated(kept) == {}


def test_the_first_action_comes_within_the_first_lines_of_the_markdown(outputs):
    # The first row of the first-fixes table (a fix, with its effort and owner), or the sentence that says there is none.
    lines = markdown_lines(outputs.markdown)
    first = next((i for i, line in enumerate(lines) if re.match(r"^\| \d+ \|", line)
                  or line.startswith("No problems were identified")), None)
    assert first is not None and first < FIRST_ACTION_LINE, first


def test_the_first_action_comes_within_the_first_lines_of_the_concise_print(outputs):
    from maya_audit_web.strings import t
    lines = html_lines(outputs.concise)
    # The executive summary's "First five actions": the line after its heading is the first action, or the sentence
    # that says there is none.
    heading = lines.index(t("pdf.exec.actions"))
    assert heading + 1 < FIRST_ACTION_LINE, lines[:FIRST_ACTION_LINE]
    assert lines[heading + 1] != "" and not lines[heading + 1].startswith(t("pdf.exec.opps"))


def test_the_repeat_counter_finds_a_line_said_three_times_about_different_pages():
    line = "- `{}`: og:site_name is the same long page title on this page"
    assert repeated([line.format(f"/p{n}") for n in range(3)]) and not repeated([line.format(f"/p{n}") for n in range(2)])


def test_pages_with_the_same_detail_value_are_one_line():
    from maya_audit.report import DETAIL_KINDS, merged_detail_sentences
    assert "og_site_name" in DETAIL_KINDS
    lines = [{"kind": "og_site_name", "url": f"https://e.com/{p}", "values": {"value": "Shop | Home"}} for p in "abc"]
    lines.append({"kind": "og_site_name", "url": "https://e.com/d", "values": {"value": "Other"}})
    assert merged_detail_sentences(lines, "https://e.com") == ["`/a`, `/b`, `/c`: og:site_name is “Shop | Home”",
                                                               "`/d`: og:site_name is “Other”"]
