"""structure_data.same_page (review G17): scheme, www and trailing-slash variants of one page are the same page."""

import pytest

from maya_audit.structure_data import same_page


@pytest.mark.parametrize("a, b", [
    ("https://bank.example/en", "https://bank.example/en/"),
    ("https://bank.example/en/", "http://bank.example/en"),
    ("https://www.bank.example/en/", "https://bank.example/en"),
    ("https://bank.example", "https://bank.example/"),
    ("https://bank.example:443/en", "https://bank.example/en/"),
    ("https://bank.example/en#top", "https://bank.example/en/"),
])
def test_variants_of_one_address_are_the_same_page(a, b):
    assert same_page(a, b) and same_page(b, a)


@pytest.mark.parametrize("a, b", [
    ("https://bank.example/en", "https://bank.example/de"),
    ("https://bank.example/en", "https://bank.example/En"),
    ("https://bank.example/blog", "https://bank.example/blog?page=2"),
    ("https://bank.example/en", "https://bank.example.de/en"),
    ("https://bank.example/en", "https://shop.bank.example/en"),
    ("https://bank.example:8443/en", "https://bank.example/en"),
    ("https://bank.example/en", None),
    ("not a url", "not a url"),
])
def test_other_pages_are_not_the_same_page(a, b):
    assert not same_page(a, b)
