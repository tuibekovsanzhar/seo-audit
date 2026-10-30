"""IDX-5 draft/test pages (review G02, G03): the address names a draft, the page has no title or a CMS placeholder title,
and it was found only through the sitemap. The site-level cases are in tests/test_brand_neutral.py (saas-spa, tarif-sube,
draft-real) and tests/test_arjava_regression.py."""

import pytest

from maya_audit.config import DRAFT_PATH_WORDS, DRAFT_PATH_WORDS_OTHER
from maya_audit.index_data import _draft_word, _own_content, _segments, _shell_page, placeholder_title

WORDS = DRAFT_PATH_WORDS | DRAFT_PATH_WORDS_OTHER


@pytest.mark.parametrize("path, word", [
    ("/test", "test"), ("/taslak/", "taslak"), ("/test/sayfa", "test"), ("/test-marka", "test"),
    ("/test-22222", "test"), ("/entwurf", "entwurf"), ("/brouillon-2", "brouillon"), ("/borrador", "borrador"), ("/sss-test", "test"),
])
def test_addresses_named_by_a_draft_word(path, word):
    assert _draft_word(_segments("https://x.example" + path), WORDS) == word


@pytest.mark.parametrize("path", ["/request-demo", "/blog/ab-test-nedir", "/blog/covid-test-nedir", "/latest",
                                  "/contest", "/dilekce-ornek", "/demo-day-istanbul-2026", "/"])
def test_a_draft_word_inside_a_longer_name_is_not_one(path):
    assert _draft_word(_segments("https://x.example" + path), WORDS) is None


@pytest.mark.parametrize("title", ["Başlıksız – Mavi Atölye", "Untitled | Shop", "Sans titre", "Sin título",
                                   "Ohne Titel - Firma", "Yeni sayfa", "بدون عنوان"])
def test_cms_placeholder_titles(title):
    assert placeholder_title(title)


@pytest.mark.parametrize("title", [None, "", "Untitled Goose Game review", "Hakkımızda", "Demo | Flowdeck",
                                   "Request a demo"])
def test_real_titles_are_not_placeholders(title):
    assert not placeholder_title(title)


def test_an_empty_mount_node_makes_a_shell_whose_missing_title_says_nothing():
    assert _shell_page({"mount_nodes": [{"id": "__next", "chars": 0}]})
    assert not _shell_page({"mount_nodes": [{"id": "__next", "chars": 900}]})
    assert not _shell_page({})


def test_own_content_leaves_out_chrome_and_is_none_for_a_shell():
    assert _own_content({"_content_blocks": ["Hakkımızda", "Biz  bir atölyeyiz."]}) == "hakkımızda biz bir atölyeyiz."
    assert _own_content({"_content_blocks": []}) is None
