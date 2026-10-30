"""IDX-8 "reachable at two addresses" (review G04): a trailing-slash pair says so, and a pair the site has already
settled (one address names the other as canonical, or redirects to it) is not reported."""

from types import SimpleNamespace

from maya_audit.index_data import address_pairs

B = "https://ex.com"


def page(path, digest="a", canonical=None, location=None):
    analysis = {"text_sha256": digest, "canonicals": [B + canonical] if canonical else []}
    return SimpleNamespace(url=B + path, analysis=analysis, headers={}, redirect_location=location and B + location)


def test_a_trailing_slash_pair_is_labelled_trailing_slash():
    [pair] = address_pairs([page("/iletisim/"), page("/iletisim")])
    assert pair["differs_in"] == "trailing slash" and pair["kept"] == B + "/iletisim/"


def test_differences_are_all_named():
    [pair] = address_pairs([page("/UyeGiris.aspx"), page("/uyegiris")])
    assert pair["differs_in"] == "file extension and letter case" and pair["kept"] == B + "/uyegiris"
    [pair] = address_pairs([page("/About"), page("/about")])
    assert pair["differs_in"] == "letter case" and pair["kept"] == B + "/about"


def test_a_pair_settled_by_a_canonical_is_not_reported():
    assert address_pairs([page("/UyeGiris.aspx", canonical="/UyeGiris"), page("/UyeGiris")]) == []
    assert address_pairs([page("/en/"), page("/en", canonical="/en/")]) == []


def test_a_pair_settled_by_a_redirect_is_not_reported():
    assert address_pairs([page("/blog", location="/blog/"), page("/blog/")]) == []
