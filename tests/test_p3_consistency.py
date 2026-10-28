"""P3 (kör nokta planı, 22 Oct): links and tags that disagree with the page, for any site.

Live, on a Ticimax shop: llms.txt listed its pages as "* https://…" and Maya read it as having no links, so an old
address that now redirects was never reported; a footer LinkedIn link carried ?viewAsMember=true; the homepage had an
empty <meta name="keywords">. The hand audit also said og:url "https://site" differs from the canonical
"https://site/": the two are the same URL (RFC 3986), so that must NOT be reported."""

from __future__ import annotations

import pytest

from fakeserver import FakeServer
from fakeserver.scenarios import robots
from fakeserver.server import Response, Site
from maya_audit.access_data import llms_links
from maya_audit.audit import run_audit
from maya_audit.config import CrawlConfig

FAST = {"request_delay_s": 0.0, "robots_sample_interval_s": 0.05, "probe_retry_cooldown_s": 0.0, "refetch_delay_s": 0.0,
        "render_enabled": False, "prf_round_gap_s": 0.0, "image_checks_max": 0, "check_external_links": False}
ALLOW = robots("User-agent: *\nAllow: /\n")
LONG = "<p>" + "Words about the shop and what it sells to its customers. " * 20 + "</p>"


def page(body: str = "", head: str = "") -> Response:
    return Response(body=f'<!doctype html><html lang="en"><head><title>Shop page</title>{head}</head><body><main>'
                         f'<h1>Shop</h1>{LONG}{body}</main></body></html>')


def audit(routes: dict, home_head: str = "", home_body: str = ""):
    links = "".join(f'<a href="{path}">{path}</a>' for path in routes if not path.endswith(".txt"))
    site = Site({"/robots.txt": ALLOW, "/": page(links + home_body, home_head), **routes})
    with FakeServer(site) as server:
        base = server.base_url
        for path, response in list(site.routes.items()):
            if isinstance(response.body, str):
                response.body = response.body.replace("{base}", base)
            if "Location" in response.headers:
                response.headers["Location"] = response.headers["Location"].replace("{base}", base)
        if "{base}" in site.routes["/"].body:
            site.routes["/"].body = site.routes["/"].body.replace("{base}", base)
        outcome = run_audit(base + "/", CrawlConfig(**{**FAST, "max_pages": 10}))
    return {c.check_id: c for c in outcome.checks}, base


def observed(check, metric: str):
    return next((o for o in check.observations if o.get("metric") == metric), None)


# -- llms.txt: bare addresses are links too -----------------------------------------------------------------------------
def test_llms_links_reads_bare_addresses_and_autolinks():
    text = ("# Shop\n\nAuthoritative Pages\n* https://s.test/\n* https://s.test/old-category\n"
            "- [Docs](https://s.test/docs)\n<https://s.test/q>\nSee (https://s.test/p).\n")
    urls = [link["url"] for link in llms_links(text, "https://s.test/llms.txt")]
    assert urls == ["https://s.test/docs", "https://s.test/", "https://s.test/old-category", "https://s.test/q",
                    "https://s.test/p"]


@pytest.mark.parametrize("text", [
    "Write to mailto:team@s.test for help.",
    "An example: `https://s.test/example` is not a page we list.",
    "token=abchttps://s.test/z",
])
def test_llms_links_leaves_out_what_is_not_a_link(text):
    assert llms_links(text, "https://s.test/llms.txt") == []


def test_a_bare_llms_address_that_redirects_is_reported():
    routes = {"/llms.txt": Response(body="# Shop\n\n* {base}/\n* {base}/difuzorler\n", content_type="text/plain"),
              "/difuzorler": Response(status=301, headers={"Location": "{base}/difuzor"}),
              "/difuzor": page()}
    checks, base = audit(routes)
    titles = [f.title for f in checks["ACC-8"].findings]
    assert any("redirects" in t for t in titles), titles


# -- og:url against the canonical ---------------------------------------------------------------------------------------
OG_URL = "pages whose og:url names another address than their canonical"


def test_og_url_without_the_root_slash_is_the_same_address():
    checks, _ = audit({}, home_head='<link rel="canonical" href="{base}/"><meta property="og:url" content="{base}">')
    assert observed(checks["STR-10"], OG_URL) is None


def test_og_url_naming_another_path_is_observed():
    head = '<link rel="canonical" href="{base}/kokular/"><meta property="og:url" content="{base}/kokular">'
    checks, _ = audit({"/kokular/": page(head=head)})
    row = observed(checks["STR-10"], OG_URL)
    assert row and row["pages"] == 1 and row["examples"][0]["og:url"].endswith("/kokular")


# -- empty meta tags ----------------------------------------------------------------------------------------------------
EMPTY = "pages with an empty <meta name> tag"


def test_an_empty_keywords_tag_is_observed_and_a_filled_one_is_not():
    checks, _ = audit({}, home_head='<meta name="keywords"><meta name="author" content="Shop">')
    assert observed(checks["STR-10"], EMPTY)["names"] == {"keywords": 1}
    checks, _ = audit({}, home_head='<meta name="keywords" content="diffuser, fragrance">')
    assert observed(checks["STR-10"], EMPTY) is None


# -- parameters on links to other sites ---------------------------------------------------------------------------------
PARAMS = "links to other sites that carry tracking or logged-in view parameters"


def test_a_profile_link_with_a_logged_in_view_parameter_is_observed():
    footer = ('<a href="https://www.linkedin.com/company/shop/?viewAsMember=true">LinkedIn</a>'
              '<a href="https://www.facebook.com/shop?fbclid=IwAR0abc">Facebook</a>'
              '<a href="https://www.instagram.com/shop/">Instagram</a>')
    checks, _ = audit({}, home_body=footer)
    row = observed(checks["IDX-6"], PARAMS)
    assert row["links"] == 2 and sorted(p for e in row["examples"] for p in e["parameters"]) == ["fbclid=IwAR0abc", "viewAsMember=true"]


def test_clean_links_to_other_sites_are_not_observed():
    clean = ('<a href="https://www.instagram.com/shop/?hl=tr">Instagram</a>'
             '<a href="https://platform.example/?utm_source=footer_shop&utm_medium=referral">Powered by</a>')
    checks, _ = audit({}, home_body=clean)  # referral tagging on an outbound link is on purpose
    assert observed(checks["IDX-6"], PARAMS) is None
