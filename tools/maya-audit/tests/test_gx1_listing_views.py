"""urls.listing_view_of (review G01): a filtered, sorted or paged view of a list that names the list as canonical is
ordinary consolidation, so IDX-4 does not call it "canonicalized to a URL with different content" (S2)."""

import pytest

from maya_audit.urls import listing_view_of

B = "https://site.example"


@pytest.mark.parametrize("page, target, view", [
    ("/blog/?filter=best", "/blog/", "parameters"),
    ("/blog/?sort=yeni", "/blog", "parameters"),
    ("/kadin?renk=siyah&sort=price", "/kadin", "parameters"),
    ("/kadin?renk=siyah&sort=price", "/kadin?renk=siyah", "parameters"),
    ("/collections/tisort?sort_by=price-ascending", "/collections/tisort", "parameters"),
    ("/blog/page/2/", "/blog/", "pagination"),
    ("/shop/page/3", "/shop", "pagination"),
    ("/collections/tisort?page=2", "/collections/tisort", "pagination"),
    ("/kategori?sayfa=4&sort=price", "/kategori?sort=price", "pagination"),
    ("/blog/page/2/", "/blog/page/2/", "pagination"),
])
def test_views_of_a_list(page, target, view):
    assert listing_view_of(B + page, B + target) == view


@pytest.mark.parametrize("page, target", [
    ("/blog/?filter=best", "/blog/?filter=new"),         # another filter, not a subset
    ("/blog/?filter=best", "/hakkimizda"),               # another path
    ("/kadin", "/erkek"),
    ("/urun-a", "/urun-b"),
    ("/blog/page/2/", "/iletisim"),                      # page 2 canonical to an unrelated page
    ("/blog/?filter=best", "https://other.example/blog/"),
    ("/blog/", "/blog/"),                                 # self, no parameter: not a view
])
def test_other_targets_are_not_views(page, target):
    target = target if target.startswith("http") else B + target
    assert listing_view_of(B + page, target) is None
