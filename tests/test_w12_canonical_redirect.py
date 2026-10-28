"""DECISIONS 263: a canonical that names an address which redirects (seen live: a homepage whose canonical /tr/tr/
redirects back to /). Offline fake site, the real audit, the severity policy as in a report."""
from dataclasses import replace

from fakeserver import FakeServer, Response, Site
from maya_audit.audit import run_audit
from maya_audit.config import CrawlConfig
from test_deadline_hosted_hardening import QUIET
from test_review_fixes import TR, links, page


def idx4():
    routes = {"/robots.txt": Response(body="User-agent: *\nAllow: /\n", content_type="text/plain"),
              "/": page(f"<h1>Ana sayfa</h1><p>{TR}</p>" + links(["/hakkimizda/", "/urun/"]),
                        head='<link rel="canonical" href="/tr/tr/">'),
              "/tr/tr/": Response(301, "", headers={"Location": "/"}),
              "/hakkimizda/": page(f"<h1>Hakkımızda</h1><p>{TR}</p>", head='<link rel="canonical" href="/eski-hakkimizda/">'),
              "/eski-hakkimizda/": Response(301, "", headers={"Location": "/hakkimizda-yeni/"}),
              "/hakkimizda-yeni/": page(f"<h1>Hakkımızda</h1><p>{TR}</p>"),
              "/urun/": page(f"<h1>Ürün</h1><p>{TR}</p>", head='<link rel="canonical" href="/urun/">')}
    with FakeServer(Site(routes)) as fake:
        outcome = run_audit(fake.base_url + "/", replace(CrawlConfig(), **QUIET))
    [check] = [c for c in outcome.checks if c.check_id == "IDX-4"]
    return {f.title: f for f in check.findings}, fake.base_url


def test_a_canonical_that_redirects_back_to_the_page_is_high_and_one_elsewhere_is_medium():
    found, base = idx4()
    loop = found["1 page(s) declare a canonical that redirects back to the page itself"]
    assert loop.severity.value == "S2" and loop.scope["urls"] == [base + "/"]
    assert loop.evidence["pages"][0]["resolved_via"][-1].rstrip("/") == base
    away = found["1 page(s) declare a canonical that redirects to another address"]
    assert away.severity.value == "S3" and away.evidence["pages"][0]["redirects_to"] == base + "/hakkimizda-yeni/"
    # The looping homepage is not also called "canonicalized to the same content".
    assert not any("same content" in t and base + "/" in f.scope.get("urls", []) for t, f in found.items())
