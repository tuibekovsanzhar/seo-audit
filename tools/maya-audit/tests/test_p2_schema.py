"""P2 (kör nokta planı, 22 Oct): STR-3 asks what is missing, from what the page shows, not only what is broken.

Live, on a Ticimax shop: the homepage had no WebSite node, showed seven questions with answers and no FAQPage, and
its Organization block (which did not parse) also lacked logo and sameAs; Maya said only that the block did not
parse. Each rule below is written for any site, with a test of what it must find and one of what it must not."""

from __future__ import annotations

import json

import pytest

from fakeserver import FakeServer
from fakeserver.scenarios import robots
from fakeserver.server import Response, Site
from maya_audit.analysis import analyze_html
from maya_audit.audit import run_audit
from maya_audit.checks.structure import qa_block
from maya_audit.config import CrawlConfig
from maya_audit.findings import Severity

FAST = {"request_delay_s": 0.0, "robots_sample_interval_s": 0.05, "probe_retry_cooldown_s": 0.0, "refetch_delay_s": 0.0,
        "render_enabled": False, "prf_round_gap_s": 0.0, "image_checks_max": 0}
ALLOW = robots("User-agent: *\nAllow: /\n")
LONG = "<p>" + "Words about the shop and what it sells to its customers. " * 20 + "</p>"
ORG = {"@context": "https://schema.org", "@type": "Organization", "name": "Shop", "url": "/",
       "logo": "/logo.png", "sameAs": ["https://www.instagram.com/shop"]}
SITE = {"@context": "https://schema.org", "@type": "WebSite", "name": "Shop", "url": "/"}


def ld(*nodes) -> str:
    return "".join(f'<script type="application/ld+json">{json.dumps(n)}</script>' for n in nodes)


def page(body: str, head: str = "", title: str = "Shop page") -> Response:
    return Response(body=f'<!doctype html><html lang="en"><head><title>{title}</title>{head}</head><body><main>'
                         f'<h1>Shop</h1>{LONG}{body}</main></body></html>')


def audit(home: Response, **routes) -> dict:
    links = "".join(f'<a href="{path}">{path}</a>' for path in routes)
    home.body = home.body.replace("</main>", links + "</main>")
    site = Site({"/robots.txt": ALLOW, "/": home, **routes})
    with FakeServer(site) as server:
        outcome = run_audit(server.base_url + "/", CrawlConfig(**{**FAST, "max_pages": 10}))
    str3 = next(c for c in outcome.checks if c.check_id == "STR-3")
    titles = {f.title: f for f in str3.findings}
    titles.update({f"observation: {o['metric']}": o for o in str3.observations})
    return titles


def qa(n: int, answer: str = "This is the answer, with enough words to be one.", mark: str = "?",
       tag: str = "span") -> str:
    return "".join(f"<div><{tag}>Question number {k}{mark}</{tag}><p>{answer}</p></div>" for k in range(n))


# -- WebSite on the homepage: an observation (most healthy sites lack it, as twitter:card, G13) -----------------------
WEBSITE = "observation: homepage with no WebSite structured data"


def test_a_homepage_without_website_is_observed_and_one_with_it_is_not():
    missing = audit(page("", ld(ORG)))
    assert missing[WEBSITE]["examples"][0].endswith("/")
    assert not [t for t in missing if "WebSite" in t and not t.startswith("observation:")]  # never a finding
    assert WEBSITE not in audit(page("", ld(ORG, SITE)))


def test_a_website_node_inside_a_block_that_does_not_parse_is_not_called_missing():
    broken = '<script type="application/ld+json">{"@type":"WebSite","name":"Sh\rop","url":"/"}</script>'
    assert WEBSITE not in audit(page("", ld(ORG) + broken))


# -- the broken Organization also says what it lacks -------------------------------------------------------------------
def test_a_broken_organization_without_logo_or_sameas_says_so():
    broken = ('<script type="application/ld+json">{"@type":"Organization","name":"Shop","address":{"streetAddress":'
              '"Line one \r\nline two"}}</script>')
    finding = audit(page("", ld(SITE) + broken))["The homepage's Organization block does not parse"]
    assert finding.evidence["recommended_still_lacking"] == ["logo", "sameAs"]


def test_a_broken_organization_with_logo_and_sameas_lacks_nothing():
    broken = ('<script type="application/ld+json">{"@type":"Organization","name":"Shop","logo":"/l.png","sameAs":'
              '["https://x.example/shop"],"address":{"streetAddress":"Line one \r\nline two"}}</script>')
    finding = audit(page("", ld(SITE) + broken))["The homepage's Organization block does not parse"]
    assert finding.evidence["recommended_still_lacking"] == []


# -- questions and answers --------------------------------------------------------------------------------------------
def test_questions_and_answers_on_the_homepage_without_faqpage_are_noted():
    titles = audit(page(qa(5), ld(ORG, SITE)))
    [finding] = [f for t, f in titles.items() if "questions and answers" in t]
    assert finding.severity == Severity.INFO and finding.evidence["pages"][0]["questions"] == 5


def test_questions_and_answers_described_by_faqpage_are_not_noted():
    faq = {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": []}
    assert not [t for t in audit(page(qa(5), ld(ORG, SITE, faq))) if "questions and answers" in t]


@pytest.mark.parametrize("html", [
    qa(2),                                                       # two pairs are not a block
    qa(4, answer="x" * 1600, tag="h2"),                          # question subheadings opening long sections
    "".join(f"<p>Why does this matter so much{k}?</p><p>Is it really?</p>" for k in range(4)),  # questions answering questions
])
def test_what_is_not_a_question_and_answer_block(html):
    assert qa_block(analyze_html(f"<main>{html}</main>")) == []


def test_the_question_rule_reads_punctuation_in_any_script():
    arabic = "".join(f"<h3>ما هو السؤال رقم {k}؟</h3><p>هذا هو الجواب على السؤال بكلمات كافية.</p>" for k in range(3))
    assert len(qa_block(analyze_html(f"<main>{arabic}</main>"))) == 3


def test_a_faq_page_by_its_address_is_reported_once():
    titles = audit(page("", ld(ORG, SITE)), **{"/sikca-sorulan-sorular": page(qa(4))})
    expected = next(f for t, f in titles.items() if "expected for their page kind" in t)
    assert [r["page_kind"] for r in expected.evidence["pages"]] == ["faq"]
    assert not [t for t in titles if "questions and answers" in t]


# -- breadcrumbs ------------------------------------------------------------------------------------------------------
CRUMB = '<ul class="breadcrumb"><li><a href="/">Home</a></li><li>Diffusers</li></ul>'


def test_a_visible_breadcrumb_without_breadcrumblist_is_noted():
    titles = audit(page("", ld(ORG, SITE)), **{"/difuzor": page(CRUMB)})
    [finding] = [f for t, f in titles.items() if "breadcrumb trail" in t]
    assert finding.evidence["pages"][0]["trail"].startswith("Home")


@pytest.mark.parametrize("body", [
    CRUMB + ld({"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": []}),
    '<ul class="breadcrumb" style="display:none"><li><a href="/">Home</a></li><li>Diffusers</li></ul>',
    '<div class="breadcrumb"><a href="/">Home</a></div>',                       # one step is not a trail
    '<nav class="breadcrumbs-wrapper-x"><span>Diffusers</span><span>All</span></nav>',  # no link at all
])
def test_what_is_not_a_breadcrumb_without_markup(body):
    titles = audit(page("", ld(ORG, SITE)), **{"/difuzor": page(body)})
    assert not [t for t in titles if "breadcrumb trail" in t]
