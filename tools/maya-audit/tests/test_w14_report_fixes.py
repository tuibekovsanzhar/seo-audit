"""Report fixes before w14 (DECISIONS 283). Hand-written pages; expected values come from the pages, not from output.

Offline: in-memory pages or a loopback fake site only.
"""
from __future__ import annotations

from maya_audit import release_gate
from maya_audit.checks.structure import BRAND_NAME_KEY, str5_entity
from maya_audit.models import to_jsonable
from maya_audit.structure_data import StructureData
from test_false_alarms import CFG, ROOT, TR, html, ld, site


# ------------------------------------------------------------------ (3) one cause: the site's name


def brand_pages(static_suffix: str):
    """10 product pages titled "… | Ornek" with og:site_name "ORNEK SHOP"; 7 static pages whose og:site_name is their
    own title ("KVKK | <static_suffix>"); a homepage whose Organization is named by its domain."""
    pages = {f"/urun-{n}": html(f"<h1>Sayfa {n}</h1><p>{TR}</p>", title=f"Sayfa {n} | Ornek",
                                head='<meta property="og:site_name" content="ORNEK SHOP">') for n in range(10)}
    for name in ("KVKK", "Gizlilik", "Hakkimizda", "Iletisim", "Kampanya", "Iade", "Sorular"):
        title = f"{name} | {static_suffix}"
        pages["/" + name.lower()] = html(f"<h1>{name}</h1><p>{TR}</p>", title=title,
                                         head=f'<meta property="og:site_name" content="{title}">')
    pages["/"] = html(f"<h1>Ornek</h1><p>{TR}</p>", title="Ornek", head=ld({"@type": "Organization", "name": "ornek.example.test",
                                                                            "url": ROOT + "/"}) + '<meta property="og:site_name" content="ORNEK SHOP">')
    result, made = site(pages)
    return str5_entity(result, CFG, made, set(), StructureData())


def test_brand_name_count_and_og_site_name_title_share_one_key():
    check = brand_pages("Ornek")
    names, pasted = check.findings
    assert names.title.startswith("The brand is named ") and pasted.title.startswith("og:site_name holds the page title")
    assert names.dedup_key == pasted.dedup_key == BRAND_NAME_KEY


def test_the_gate_reports_the_two_on_the_same_pages_as_one_cause_said_twice():
    """The seven static pages give the name "Ornek" in their titles and hold their title in og:site_name: both
    findings list them, so RG-9 reports the double count."""
    check = brand_pages("Ornek")
    names, pasted = to_jsonable(check.findings)
    assert set(pasted["scope"]["urls"]) <= set(names["scope"]["urls"])
    report = {"checks": [to_jsonable(check)]}
    rg9 = [v for v in release_gate.check_report(report) if v["rule"] == "RG-9" and BRAND_NAME_KEY in v["message"]]
    assert len(rg9) == 1 and not rg9[0]["hard"]
    assert {names["id"], pasted["id"]} <= set(rg9[0]["message"].replace(" and ", " ").split())


def test_the_gate_says_nothing_when_the_two_are_on_different_pages():
    """Counter-example: the static pages' title suffix ("Ornekk") is no name of the brand, so the name count does not
    list them; the same key, no overlap, no RG-9."""
    check = brand_pages("Ornekk")
    names, pasted = to_jsonable(check.findings)
    assert not set(pasted["scope"]["urls"]) & set(names["scope"]["urls"])
    report = {"checks": [to_jsonable(check)]}
    assert not [v for v in release_gate.check_report(report) if v["rule"] == "RG-9" and BRAND_NAME_KEY in v["message"]]


# ------------------------------------------------------------------ (8) section headings on a cut-off page

from test_m1_h1 import FILLER, LIMIT, PAGES, str2_of, site as h1_site  # noqa: E402
from test_review_fixes import page  # noqa: E402

SECTIONS = "".join(f"<h2>Bölüm {n}</h2><p>{TR}</p>" for n in range(4))
NAV = " ".join(f'<a href="{p}">{p}</a>' for p in PAGES)
OUTLINE = "The homepage has "
LONG = "long page(s)"


def cut_part(check):
    return [p for p in check["coverage"]["not_assessed"]
            if p["part"] == "pages whose HTML was cut off before their section headings could be counted"]


def test_a_cut_off_homepage_is_not_said_to_lack_section_headings():
    """The homepage's <h2>s come after the fetch-size limit: the cut body has none, the page has four."""
    routes = h1_site("<h1>Ana sayfa</h1>")
    routes["/"] = page("<h1>Ana sayfa</h1>" + FILLER + SECTIONS + NAV, nav="")
    check, base = str2_of(routes, **LIMIT)
    titles = [f["title"] for f in check["findings"]]
    assert not [t for t in titles if t.startswith(OUTLINE) and "section heading" in t]
    assert not [t for t in titles if LONG in t]
    assert base + "/" in check["evidence"]["sections_cut_off"]
    [cut] = cut_part(check)
    assert cut["count"] >= 1 and "may have them" in cut["reason"]
    assert check["status"] != "pass"


def test_a_long_page_cut_off_before_its_subheadings_is_not_assessed():
    routes = h1_site("<h1>Ana sayfa</h1>")
    routes["/tamam"] = page("<h1>Tamam</h1>" + FILLER + SECTIONS, nav="")
    check, base = str2_of(routes, **LIMIT)
    assert not [f for f in check["findings"] if LONG in f["title"] and base + "/tamam" in f["scope"]["urls"]]
    assert base + "/tamam" in check["evidence"]["sections_cut_off"]


def test_without_the_limit_the_same_long_flat_homepage_is_still_reported():
    """Counter-example: a whole page with long text and no subheadings is still a finding."""
    routes = h1_site("<h1>Ana sayfa</h1>")
    routes["/"] = page("<h1>Ana sayfa</h1>" + FILLER + NAV, nav="")
    check, base = str2_of(routes)
    titles = [f["title"] for f in check["findings"]]
    assert [t for t in titles if t.startswith(OUTLINE) and "section heading" in t]
    assert check["evidence"]["sections_cut_off"] == []
