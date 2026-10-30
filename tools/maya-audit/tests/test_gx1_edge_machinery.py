"""index_data.edge_machinery (review G06 link side, G27): a CDN's own addresses are not pages of the site, so a link to
one that answers 404 is not a broken link. The site-level cases are shop-de (Akamai) and saas-spa (Vercel) in
tests/test_brand_neutral.py, each with an <a> to the path."""

import pytest

from maya_audit.index_data import edge_machinery


@pytest.mark.parametrize("path, vendor", [
    ("/cdn-cgi/l/email-protection", "Cloudflare"), ("/akam/13/pixel_2e5f8a1b?a=1", "Akamai"),
    ("/_vercel/insights/script.js", "Vercel"), ("/.netlify/functions/x", "Netlify"),
    ("/_Incapsula_Resource?SWJIYLWA=1", "Imperva"), ("/CDN-CGI/challenge-platform/h/b", "Cloudflare"),
])
def test_edge_paths(path, vendor):
    assert edge_machinery("https://site.example" + path) == vendor


@pytest.mark.parametrize("path", ["/api/v1/x", "/admin/", "/blog/akam/", "/akamai", "/vercel", "/", ""])
def test_site_paths_are_not_edge_machinery(path):
    assert edge_machinery("https://site.example" + path) is None
