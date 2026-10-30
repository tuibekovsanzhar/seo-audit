"""Review G17/G18, worker gx2: STR-9 compares hreflang addresses as one page (scheme, www, trailing slash), and a
language version on another domain with links to other sites off is outside the audit, not "not assessed"."""

from __future__ import annotations

from dataclasses import replace

import pytest

from maya_audit.checks.structure import str9_language
from maya_audit.structure_data import same_page as _same_page
from maya_audit.coverage import settle
from maya_audit.structure_data import StructureData
from test_false_alarms import CFG, ROOT, TR, html, site

LONG = " ".join([TR] * 6)


@pytest.mark.parametrize("a, b", [("https://x.test/en/", "https://x.test/en"), ("http://www.x.test/en", "https://x.test/en/"),
                                  ("https://x.test", "https://x.test/")])
def test_scheme_www_and_trailing_slash_do_not_make_two_pages(a, b):
    assert _same_page(a, b)


@pytest.mark.parametrize("a, b", [("https://x.test/en", "https://x.test/de"), ("https://x.test/?l=en", "https://x.test/"),
                                  ("https://x.test/en", "https://y.test/en"), (None, "https://x.test/")])
def test_other_paths_queries_and_hosts_are_other_pages(a, b):
    assert not _same_page(a, b)


def head(*pairs):
    return "".join(f'<link rel="alternate" hreflang="{c}" href="{h if h.startswith("http") else ROOT + h}">' for c, h in pairs)


def run(pages_html, extra=None, cfg=CFG):
    result, pages = site(pages_html)
    data = StructureData()
    for page in pages:
        data.links[page.url] = {"source": "crawl", "status": 200, "hreflang": page.analysis["hreflang"]}
    data.links.update(extra or {})
    check = str9_language(result, cfg, pages, set(), data)
    settle(check)
    return check


def test_a_self_link_and_a_return_link_without_the_slash_count():
    pairs = (("tr", "/"), ("en", "/en"), ("x-default", "/"))
    en = html(f"<p>{LONG}</p>", head=head(*pairs) + f'<link rel="canonical" href="{ROOT}/en/">')
    check = run({"/": html(f"<p>{LONG}</p>", head=head(*pairs)), "/en/": en},
                {ROOT + "/en": {"source": "crawl", "status": 200, "hreflang": [{"hreflang": "tr", "href": ROOT + "/"}]}})
    titles = [f.title for f in check.findings]
    assert not [t for t in titles if "lack x-default" in t or "not returned" in t], titles
    rows = [row for f in check.findings for row in f.evidence.get("links", [])]
    assert not [p for row in rows for p in row.get("problems", []) if p.startswith("canonical")], rows


def test_a_version_on_its_own_domain_is_out_of_scope_with_other_sites_off():
    pairs = (("tr", "/"), ("de", "https://www.ornek.de/"), ("x-default", "/"))
    cfg = replace(CFG, check_external_links=False)
    check = run({"/": html(f"<p>{LONG}</p>", head=head(*pairs))},
                {"https://www.ornek.de/": {"source": "not_fetched", "reason": "external link checks are off"}}, cfg)
    assert check.evidence["hreflang_targets_out_of_scope_count"] == 1
    assert check.evidence["hreflang_targets_not_assessed_count"] == 0
    assert "outside this audit" in check.summary and check.status == "pass"


def test_with_other_sites_on_an_unasked_version_is_still_not_assessed():
    pairs = (("tr", "/"), ("de", "https://www.ornek.de/"), ("x-default", "/"))
    cfg = replace(CFG, check_external_links=True)
    check = run({"/": html(f"<p>{LONG}</p>", head=head(*pairs))},
                {"https://www.ornek.de/": {"source": "not_fetched", "reason": "cap"}}, cfg)
    assert check.evidence["hreflang_targets_not_assessed_count"] == 1 and check.status != "pass"
