"""DECISIONS 346: the Ek's "Bağlantı yerleri" sheet gives each missing sitemap address the same 301 target and reason as
"Bulgu bazında" (DECISIONS 344, 345), not the generic "kaldırın veya yönlendirin" / "site haritası oluşturucuyu düzeltin".
The fake site is DECISIONS 344's (tests/test_expert_review_344.py)."""
from __future__ import annotations

from maya_audit import xlsx
from maya_audit.checks.team_rules import target_words
from maya_audit_web.team_report import render
from test_expert_review_344 import site  # noqa: F401  (fixture)
from test_firecrawl import no_lookups  # noqa: F401  (fixture)


def test_target_words_firm_weak_and_410():
    assert target_words({"target": "https://b.test/kartlar/x", "target_basis": "parent", "target_firm": True,
                         "target_known_as": "read"}, "tr") == "301 → /kartlar/x (üst klasör sayfası)"
    assert target_words({"target": "https://b.test/sirketim", "target_basis": "far_parent", "target_firm": False,
                         "target_known_as": "read"}, "tr") == "301 → /sirketim (kontrol edin; en yakın var olan üst sayfa)"
    assert target_words({"target": "https://b.test/o/i", "target_basis": "parent", "target_firm": True,
                         "target_known_as": "sitemap"}, "en") == "301 → /o/i (the folder's page above it; in the sitemap, not read in this audit)"
    assert target_words({"target": None, "target_basis": "none"}, "tr") == "410 (ilgili sayfa yok)"


def test_the_sheet_shows_each_sitemap_addresss_target(site):  # noqa: F811
    sealed, _, base = site
    content, _ = render.appendix_bytes(sealed.report, sealed.affected, {}, "tr")
    rows = xlsx.read(content)["Bağlantı yerleri"]
    col = rows[0].index("Önerilen hedef")
    said = {r[1].removeprefix(base): r[col] for r in rows[1:] if len(r) > col}
    assert said["/odemeler/eski-fatura"] == "301 → /odemeler (üst klasör sayfası)"
    assert said["/kampanya-yok"] == "410 (ilgili sayfa yok)"
    assert not any(v in ("kaldırın veya yönlendirin", "site haritası oluşturucuyu düzeltin") for v in said.values())
    # an address made from a heading keeps the generator advice after its target (tests/test_link_places_337.py)
