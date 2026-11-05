"""DECISIONS 312: the key pages list counts the homepage's language versions as one row, and with a business type every
page type of its profile found among the pages read keeps a place for its best page. "Diğer" keeps the importance
order."""
from __future__ import annotations

from maya_audit.client_appendix import WORDS
from maya_audit.client_selection import key_pages
from maya_audit_web import strings
from maya_audit_web.team_report.render import LABELS

SITE = "https://h.example"


def _rows():
    rows = {f"{SITE}/tr/": {"importance": 20, "importance_rank": 40, "page_type": "home",
                            "page_type_basis": "the start address's final page"},
            f"{SITE}/en/": {"importance": 30, "importance_rank": 30, "page_type": "home"},
            f"{SITE}/ru/": {"importance": 91, "importance_rank": 1, "page_type": "home"},
            f"{SITE}/ar/": {"importance": 85, "importance_rank": 2, "page_type": "home"}}
    for i in range(15):
        rows[f"{SITE}/tr/tedavi/{i}/"] = {"importance": 89 - i // 5, "importance_rank": 3 + i, "page_type": "category",
                                          "business_page_type": "treatment"}
    rows[f"{SITE}/tr/ekibimiz/"] = {"importance": 80, "importance_rank": 20, "page_type": "other", "business_page_type": "doctors"}
    rows[f"{SITE}/tr/hakkimizda/"] = {"importance": 80, "importance_rank": 21, "page_type": "other", "business_page_type": "doctors"}
    rows[f"{SITE}/tr/kariyer/"] = {"importance": 40, "importance_rank": 22, "page_type": "other", "business_page_type": "other"}
    return rows


def test_the_language_homepages_are_one_row_with_the_cards_of_every_version():
    rows = [{"placement": "card", "card": 2, "urls": [f"{SITE}/ru/"], "severity": "S3"},
            {"placement": "card", "card": 5, "urls": [f"{SITE}/tr/"], "severity": "S4"},
            {"placement": "confirm", "urls": [f"{SITE}/ar/", f"{SITE}/en/"], "severity": "S4"}]
    pages = key_pages({"crawl": {"start_url": SITE + "/"}}, rows, _rows())
    home = pages[0]
    assert home["url"] == f"{SITE}/tr/" and home["main_homepage"] and home["importance"] == 20
    assert home["languages"] == [f"{SITE}/tr/", f"{SITE}/ru/", f"{SITE}/ar/", f"{SITE}/en/"]
    assert home["cards"] == [2, 5] and home["worst"] == "S3" and home["confirm"] == 1
    assert sum(1 for p in pages if p["page_type"] == "home") == 1 and len(pages) == 10


def test_every_profile_page_type_found_keeps_a_place_for_its_best_page():
    pages = key_pages({"crawl": {"start_url": SITE + "/"}}, [], _rows())
    urls = [p["url"] for p in pages]
    assert f"{SITE}/tr/ekibimiz/" in urls and f"{SITE}/tr/hakkimizda/" not in urls  # the best of its type only
    assert f"{SITE}/tr/kariyer/" not in urls  # "other" keeps no place
    assert [p["business_page_type"] for p in pages[1:]] == ["treatment"] * 8 + ["doctors"]  # importance order kept
    assert [p["rank"] for p in pages] == list(range(1, 11))


def test_without_a_business_type_the_list_is_the_importance_order():
    rows = {u: {k: v for k, v in g.items() if k != "business_page_type"} for u, g in _rows().items()}
    pages = key_pages({"crawl": {"start_url": SITE + "/"}}, [], rows)
    assert f"{SITE}/tr/ekibimiz/" not in [p["url"] for p in pages]
    assert [p["importance"] for p in pages[1:]] == sorted((p["importance"] for p in pages[1:]), reverse=True)


def test_the_row_is_labelled_with_its_number_of_languages_everywhere():
    assert LABELS["tr"]["home_languages"].format(n=4) == "Ana sayfa (4 dil)"
    assert LABELS["en"]["home_languages"].format(n=4) == "Homepage (4 languages)"
    assert WORDS["tr"]["home_languages"].format(n=4) == "ana sayfa (4 dil)"
    assert strings.t("c6.type.home_languages", "tr", n=4) == "ana sayfa (4 dil)"


def test_no_test_can_reach_the_real_env_file_or_a_provider_key():
    """AGENTS.md (DECISIONS 312): every test runs with the env file pointed at a file that does not exist, in its own
    audit home, and with every provider key unset, so neither the shell nor the project's .env reaches a provider."""
    import os
    from pathlib import Path
    from conftest import PROVIDER_KEYS
    from maya_audit import crux
    from maya_audit.dataforseo import credentials
    from maya_audit.firecrawl import settings as firecrawl_settings
    env_file = Path(os.environ["MAYA_AUDIT_ENV_FILE"])
    assert not env_file.exists() and env_file.name == "no-such.env"
    assert Path(os.environ["MAYA_AUDIT_HOME"]) != Path.home() / ".maya-audit"
    assert all(not os.environ.get(name) for name in PROVIDER_KEYS)
    assert crux.load_key() is None and credentials.load_credentials() is None and firecrawl_settings.load_key() is None
