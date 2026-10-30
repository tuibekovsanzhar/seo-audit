"""DECISIONS 258: homepage items an expert audit rates High are High here too, and the homepage's own HTML size is judged
against a lower bar. Offline: made-up pages, nothing is fetched."""
from test_false_alarms import CFG, ROOT, TR, html, site

from maya_audit.checks.render import rnd6_payload
from maya_audit.checks.structure import str2_headings
from maya_audit.severity import apply as apply_severity

QA = "".join(f"<div class=faq><span>Soru {n} nedir?</span><p>{TR}</p></div>" for n in range(3))


def outline(body):
    result, pages = site({"/": html(body, title="Örnekmağaza | Ana Sayfa"), "/hakkimizda": html("<h1>Hakkımızda</h1><p>Biz.</p>")})
    check = str2_headings(result, CFG, pages, set(), set())
    apply_severity([check], result)  # the owner policy the report applies (255): a heuristic would be capped here
    return [f for f in check.findings if "visible section heading" in f.title]


def test_a_homepage_with_text_but_almost_no_section_headings_is_high():
    [finding] = outline("<h1>Örnekmağaza</h1><h2>Ürünler</h2>" + TR * 12)
    assert finding.severity.value == "S2" and finding.confidence.value == "verified"
    assert finding.title.startswith("The homepage has 1 visible section heading(s) for ")


def test_a_question_block_written_as_plain_text_counts_even_on_a_short_homepage():
    [finding] = outline("<h1>Örnekmağaza</h1>" + QA)
    assert finding.evidence["pages"][0]["questions_not_headings"]


def test_a_homepage_with_an_outline_is_not_reported():
    body = "<h1>Örnekmağaza</h1>" + "".join(f"<h2>Bölüm {n}</h2><p>{TR * 3}</p>" for n in range(3))
    assert outline(body) == []


def test_a_short_homepage_without_questions_is_not_reported():
    assert outline("<h1>Örnekmağaza</h1><p>Hoş geldiniz.</p>") == []


def test_the_homepage_hidden_h1_is_medium_after_the_severity_policy():
    """DECISIONS 284: never re-tested (no re-test exists for it), so at most Medium; the policy does not raise it."""
    result, pages = site({"/": html('<h1 style="display:none">Örnekmağaza</h1><h2>A</h2><h2>B</h2><h2>C</h2>' + TR * 3),
                          "/a": html("<h1>A</h1>")})
    check = str2_headings(result, CFG, pages, set(), set())
    apply_severity([check], result)
    [hidden] = [f for f in check.findings if f.title == "The homepage's only <h1> is hidden"]
    assert hidden.severity.value == "S3"
    assert any(n.startswith("Medium: one reading of the homepage, not re-tested") for n in hidden.notes)


def payload(home_bytes):
    result, pages = site({"/": html("<h1>Ana</h1>"), "/a": html("<h1>A</h1>")})
    for page in pages:
        page.readable_document = lambda: True
        page.content_type = "text/html; charset=utf-8"
        page.body_bytes = home_bytes if page.url == ROOT + "/" else 40_000
    return [f for f in rnd6_payload(result, CFG).findings if "homepage's HTML" in f.title]


def test_a_homepage_above_its_own_lower_bar_is_medium():
    [finding] = payload(652_000)
    assert finding.severity.value == "S3" and finding.title == "The homepage's HTML is 652 KB, above 500 KB"


def test_a_homepage_under_the_bar_or_already_over_the_site_bar_is_not_said_twice():
    assert payload(400_000) == [] and payload(1_200_000) == []


def homepage_ttfb(limit_ms):
    from fakeserver import FakeServer
    from fakeserver.prf_scenarios import PRF_SCENARIOS
    from maya_audit.audit import run_audit
    from maya_audit.config import CrawlConfig

    scenario = PRF_SCENARIOS["prf_mixed"]
    with FakeServer(scenario.build()) as fake:
        options = {**scenario.config, "key_pages": tuple(fake.base_url + p for p in scenario.config["key_pages"]),
                   "homepage_ttfb_max_ms": limit_ms}
        outcome = run_audit(fake.base_url + "/", CrawlConfig(**options))
    [prf1] = [c for c in outcome.checks if c.check_id == "PRF-1"]
    return [f for f in prf1.findings if f.title.startswith("The homepage takes")]


def test_a_slow_homepage_is_medium_from_its_own_samples_and_a_fast_one_is_not_reported():
    [slow] = homepage_ttfb(-1)  # any measured homepage is "slow" against a negative bar
    # DECISIONS 283 (4): one measurement from Maya's network, never re-tested, is at most Medium (258 had it High).
    assert slow.severity.value == "S3" and slow.confidence.value == "verified"
    assert (slow.verification or {}).get("state") != "confirmed"
    assert any("not re-tested" in note for note in slow.notes)
    assert slow.evidence["pages"][0]["successful_samples"] >= 3 and slow.importance_tier == 0
    assert homepage_ttfb(800) == []  # the fake homepage answers in a few milliseconds
