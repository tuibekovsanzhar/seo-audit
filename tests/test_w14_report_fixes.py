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
