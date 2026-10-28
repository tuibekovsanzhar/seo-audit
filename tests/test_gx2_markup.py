"""Review G, worker gx2: markup signals most healthy sites show are observations, not findings (G10-G13, section 2),
and STR-18 reads a brand behind a leading article (item 11)."""

from __future__ import annotations

from maya_audit.checks.page_markup import page_markup_findings
from maya_audit.checks.structure import image_loading_findings
from test_false_alarms import ROOT, html, site

ONETRUST = '<script src="https://cdn.cookielaw.org/scripttemplates/otSDKStub.js"></script>'
JQUERY = '<script src="/wp-includes/js/jquery/jquery.min.js"></script><script src="/wp-includes/js/jquery-migrate.min.js"></script>'


def markup(head="", body="<p>x</p>", pages=1):
    _, read = site({("/" if n == 0 else f"/p{n}"): html(body, head=head) for n in range(pages)})
    observations: list = []
    return page_markup_findings(read, set(), observations), observations, read


def test_a_consent_manager_is_never_told_to_defer_and_two_theme_scripts_are_an_observation():
    findings, observations, _ = markup(ONETRUST + JQUERY)
    assert not [f for f in findings if "defer" in f.title]
    [seen] = observations
    assert seen["scripts"] == 2 and seen["sync_required_left_out"] == 1
    assert "cookielaw" not in str(seen)


def test_three_of_the_sites_own_blocking_scripts_on_most_pages_are_one_sitewide_finding():
    head = "".join(f'<script src="/js/{n}.js"></script>' for n in range(3))
    findings, _, read = markup(head, pages=4)
    [blocking] = [f for f in findings if "defer" in f.title]
    assert blocking.scope["kind"] == "sitewide" and blocking.scope["count"] == len(read)


def test_a_gtm_preload_beside_its_snippet_is_one_loader():
    preload = '<link rel="preload" as="script" href="https://www.googletagmanager.com/gtm.js?id=GTM-K4P7Q2X">'
    snippet = "<script>(function(w,d,s,l,i){})(window,document,'script','dataLayer','GTM-K4P7Q2X');</script>"
    findings, _, _ = markup(preload + snippet)
    assert not [f for f in findings if "analytics" in f.title]


def test_gtm_beside_a_google_tag_is_observed_not_reported():
    gtag = '<script async src="https://www.googletagmanager.com/gtag/js?id=GT-ABCD12"></script>'
    snippet = "<script>(function(w,d,s,l,i){})(window,document,'script','dataLayer','GTM-K4P7Q2X');</script>"
    findings, observations, _ = markup(gtag + snippet)
    assert not [f for f in findings if "analytics" in f.title]
    assert [o for o in observations if "Tag Manager" in o["metric"]][0]["pages"] == 1


def test_images_sized_by_css_picture_or_a_lazy_loader_are_not_unsized():
    body = ('<img src="/a.jpg" alt="A" class="w-full aspect-video">'
            '<img src="/b.jpg" alt="B" style="object-fit: cover">'
            '<picture><source srcset="/c.webp" width="800" height="600"><img src="/c.jpg" alt="C"></picture>'
            '<img src="/spacer.gif" data-src="/d.jpg" alt="D">'
            '<img src="/e.jpg" alt="E" style="width:100%;height:auto">')
    _, pages = site({"/": html(body)})
    [unsized] = image_loading_findings(pages, set())
    assert unsized.evidence["pages"][0]["examples"] == [ROOT + "/e.jpg"]


def test_the_homepage_title_names_a_brand_written_with_a_leading_article():
    from maya_audit.checks.small_site import str18_homepage_title_brand
    from test_false_alarms import CFG
    head = '<meta property="og:site_name" content="Le Courrier du Rhône">'
    result, pages = site({"/": html("<p>x</p>", title="Courrier du Rhône | Actualités de Lyon", head=head)})
    assert str18_homepage_title_brand(result, CFG, pages, set()).status == "pass"
