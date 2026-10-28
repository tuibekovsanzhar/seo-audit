"""Brand-independent acceptance suite: eight made-up sites (fakeserver/neutral_scenarios.py), one audit each.

The engine's newer rules were tuned on one Turkish Ticimax shop. Review G ("Aşırı uyum", section 4) lists the sites
where those rules must still hold; each site below is one of them, and each test is one line of that list:
"must find" (the audit reports it) or "must not flag" (the audit stays quiet about it).

The sites
- shop-de     German shop (Shopware-like) behind Akamai; an embedded WordPress magazine; "In den Warenkorb".
- saas-spa    Next.js SaaS on Vercel: menu, titles and text are drawn by JavaScript, every raw page is the same shell.
- tarif-sube  Turkish recipe blog with branches; filtered, sorted and paged blog lists canonical to the first page.
- bank-multi  Multilingual bank behind CloudFront: hreflang (en-GB, de-DE on its own ccTLD, ar-AE, es-419, zh-Hant-TW),
              OneTrust in <head>, noindex legal pages in the sitemap.
- local-wp    WordPress dentist behind Sucuri: jQuery in <head>, alt == title, no twitter:card, /iletisim twice.
- shopify     Shopify store: WebP behind .jpg names, sort_by/page parameters, gtag beside GTM, "Add to bag".
- draft-real  The positive control: real drafts left published, a placeholder alt, GTM twice, mixed content.
- news-video  French news site behind Fastly: a video uploaded today, a default "Video", dates only in <time>/text.

How to read a result
- Each site is audited once per module (`audit`), over HTTPS with a plain-HTTP twin that redirects (a plain-HTTP run
  adds an IDX-2 finding to every site), render off, external links off. saas-spa has a second, rendered run; its tests
  are skipped when Playwright or its Chromium is missing (PLAYWRIGHT_BROWSERS_PATH is used when set).
- Findings are matched by words of their title and by check id, never by finding id.
- `xfail(strict=True, raises=AssertionError, reason="G0x: ...")` marks what the engine gets wrong today, naming the
  review row (G01..G27) whose fix makes it pass. Strict: a fix that makes a test pass must remove its marker.
- Every site has two noise guards. (1) The S1-S3 findings equal an explicit expected set, written from the spec, not
  copied from a run. (2) The number of Info findings stays at or under a cap. The cap counts Info findings (each one
  is a line of the report's "Notes"), not rendered lines.

Adding a site
1. Write `_<name>() -> Site` in fakeserver/neutral_scenarios.py with `Kit` (healthy pages by default), and add a
   Scenario to NEUTRAL_SCENARIOS. Keep it small (8-20 pages) and give each trap a one-line comment.
2. Add a module fixture here (`<name> = site("<name>")`), one test per "must find" / "must not flag" line, the S1-S3
   set and the Info cap. Run it, and mark each test that fails today with the review row that fixes it.
3. Run scripts/fixture_matrix.py: test names that say a check id feed docs/FIXTURE-MATRIX.md.
"""

from __future__ import annotations

import contextlib
import ipaddress
import os
import socket

import pytest

from fakeserver.neutral_scenarios import NEUTRAL_SCENARIOS, https_pair
from maya_audit.audit import run_audit
from maya_audit.config import CrawlConfig
from maya_audit.report import build_report


@contextlib.contextmanager
def hermetic(home: str):
    """What tests/conftest.py's autouse fixtures do, for a module-scoped audit (they are function-scoped, so they are
    not active yet when a module fixture runs): no connection leaves loopback, no public name is looked up, and no
    real credentials or home folder are read."""
    import httpx
    from maya_audit import resolver

    mp = pytest.MonkeyPatch()
    real_connect = socket.socket.connect

    def connect(sock, address):
        if isinstance(address, tuple) and address:
            host = str(address[0]).strip("[]").lower()
            try:
                local = ipaddress.ip_address(host).is_loopback
            except ValueError:
                local = host == "localhost" or host.endswith(".localhost")
            if not local:
                raise RuntimeError(f"test blocked non-loopback network connection to {host}")
        return real_connect(sock, address)

    def lookup(host, port):
        if host == "localhost" or host.endswith(".localhost"):  # IPv4 only: the fake servers listen on 127.0.0.1
            return ["127.0.0.1"]
        raise socket.gaierror(socket.EAI_NONAME, "tests do not look up public names")

    def unreachable(request):
        raise httpx.ConnectError("tests do not reach public resolvers")

    try:
        mp.setattr(socket.socket, "connect", connect)
        mp.setattr(resolver, "system_lookup", lookup)
        mp.setattr(resolver, "doh_transport", httpx.MockTransport(unreachable))
        mp.setattr(resolver, "sleep", lambda seconds: None)
        mp.delenv(resolver.DOH_VAR, raising=False)
        mp.setenv("MAYA_AUDIT_HOME", home)
        mp.setenv("MAYA_AUDIT_ENV_FILE", os.path.join(home, "no-such.env"))
        for name in ("MAYA_AUDIT_DATAFORSEO_LOGIN", "MAYA_AUDIT_DATAFORSEO_PASSWORD", "MAYA_AUDIT_FIRECRAWL_API_KEY"):
            mp.delenv(name, raising=False)
        mp.setenv("MAYA_AUDIT_FIRECRAWL", "off")
        resolver.reset()
        yield
    finally:
        mp.undo()
        resolver.reset()


class Run:
    def __init__(self, outcome, requests, base):
        self.outcome, self.requests, self.base = outcome, requests, base
        self.checks = {c.check_id: c for c in outcome.checks}
        self.findings = [f for c in outcome.checks for f in c.findings]
        self.report = build_report(outcome.result, outcome.gates, outcome.checks)

    def paths(self, finding) -> set[str]:
        urls = finding.scope.get("_all_urls") or finding.scope.get("urls") or []
        return {u.replace(self.base, "") or "/" for u in urls}

    def titled(self, *words: str, check: str | None = None) -> list:
        """Findings whose title holds every word (case-insensitive), optionally from one check."""
        return [f for f in self.findings if all(w.lower() in f.title.lower() for w in words)
                and (check is None or f.check_id == check)]

    def text(self, finding) -> str:
        return f"{finding.title} {finding.evidence} {finding.how_to_fix}"

    def page(self, path: str):
        return next(p for p in self.outcome.result.pages if p.url == self.base + path)


def audit(name: str, home: str, **overrides) -> Run:
    scenario = NEUTRAL_SCENARIOS[name]
    with hermetic(home), https_pair(scenario.build()) as (server, plain, ca_bundle):
        options = {"request_delay_s": 0.0, "robots_sample_interval_s": 0.05, "probe_retry_cooldown_s": 0.0,
                   "refetch_delay_s": 0.0, "render_enabled": False, "prf_round_gap_s": 0.0, **scenario.config,
                   "ca_bundle": ca_bundle, "http_port": plain.port, **overrides}
        outcome = run_audit(server.base_url + "/", CrawlConfig(**options))
        return Run(outcome, list(server.requests), server.base_url)


def site(name: str, **overrides):
    """A module-scoped fixture `<name with underscores>` holding that site's audit."""
    @pytest.fixture(scope="module", name=name.replace("-", "_") + overrides.pop("suffix", ""))
    def _audited(tmp_path_factory) -> Run:
        return audit(name, str(tmp_path_factory.mktemp("maya-audit-home")), **overrides)
    return _audited


def g(row: str, why: str):
    """Expected to fail today, until review row `row` is fixed."""
    return pytest.mark.xfail(strict=True, raises=AssertionError, reason=f"{row}: {why}")


SERIOUS = ("S1", "S2", "S3")


def assert_serious_set(run: Run, expected: tuple[tuple[str, str, str], ...]) -> None:
    """The S1-S3 findings are exactly `expected`: (check id, severity, a word of the title), one finding each."""
    actual = [(f.check_id, f.severity.value, f.title) for f in run.findings if f.severity.value in SERIOUS]

    def fits(found, want) -> bool:
        return found[0] == want[0] and found[1] == want[1] and want[2].lower() in found[2].lower()

    extra = [a for a in actual if not any(fits(a, e) for e in expected)]
    missing = [e for e in expected if not any(fits(a, e) for a in actual)]
    assert not extra and not missing and len(actual) == len(expected), f"extra={extra} missing={missing}"


def info_count(run: Run) -> int:
    return sum(f.severity.value == "Info" for f in run.findings)


def mentions(run: Run, needle: str, checks: tuple[str, ...] | None = None) -> list:
    """Findings whose title, evidence or advice holds `needle`, optionally only from some checks."""
    return [f for f in run.findings if needle in run.text(f) and (checks is None or f.check_id in checks)]


def basic_pages(run: Run) -> dict[str, list[str]]:
    from maya_audit.checks.small_site import basic_pages_found
    pages = [p for p in run.outcome.result.pages if p.analysis]
    return {kind: sorted(u.replace(run.base, "") for u in urls) for kind, urls in basic_pages_found(pages).items()}


def str21_missing(run: Run) -> str:
    """The kinds STR-21 says are missing, as its title words ("About / Contact"), or "" when it says nothing."""
    return " ".join(f.title for f in run.findings if f.check_id == "STR-21")


def _no_browser() -> str | None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return "Playwright is not installed"
    try:
        with sync_playwright() as p:
            path = p.chromium.executable_path
    except Exception as exc:  # noqa: BLE001
        return f"Playwright could not start: {exc}"
    return None if os.path.exists(path) else f"Chromium is not installed ({path})"


NO_BROWSER = _no_browser()
needs_browser = pytest.mark.skipif(NO_BROWSER is not None, reason=NO_BROWSER or "")

shop_de = site("shop-de")
saas_spa = site("saas-spa")
saas_spa_rendered = site("saas-spa", render_enabled=True, suffix="_rendered")
tarif_sube = site("tarif-sube")
bank_multi = site("bank-multi")
local_wp = site("local-wp")
shopify = site("shopify")
draft_real = site("draft-real")
news_video = site("news-video")


# == 1. shop-de ==================================================================================================
def test_shop_de_in_den_warenkorb_beside_a_price_makes_it_a_shop_str21(shop_de):
    assert "Product" not in str21_missing(shop_de)
    assert not shop_de.titled("no buy button")


def test_shop_de_in_den_warenkorb_is_a_buy_control(shop_de):
    from maya_audit.checks.structure import _buy_texts
    assert _buy_texts(shop_de.page("/produkt/laufschuh-alpen"))


def test_shop_de_kontakt_impressum_ueber_uns_are_basic_pages_str21(shop_de):
    missing = str21_missing(shop_de)
    assert "About" not in missing and "Contact" not in missing


def test_shop_de_png_under_a_jpg_name_is_noted_str7(shop_de):
    notes = shop_de.titled("format", check="STR-7")
    assert len(notes) == 1 and notes[0].severity.value == "Info"
    assert "banner.jpg" in str(notes[0].evidence) and "image/png" in str(notes[0].evidence)


def test_shop_de_heavy_hero_image_is_reported_once_str7(shop_de):
    heavy = shop_de.titled("over 500 KB", check="STR-7")
    assert len(heavy) == 1 and "hero.jpg" in str(heavy[0].evidence) and "banner.jpg" not in str(heavy[0].evidence)


def test_shop_de_akamai_pixel_is_not_a_broken_link(shop_de):
    assert mentions(shop_de, "/akam/") == []


def test_shop_de_webp_behind_vary_accept_is_not_a_format_mismatch_str7(shop_de):
    notes = " ".join(str(f.evidence) for f in shop_de.titled("format", check="STR-7"))
    assert "laufschuh-alpen.jpg" not in notes and "sneaker-stadt.jpg" not in notes


def test_shop_de_sorted_category_canonical_is_not_idx4_s2(shop_de):
    assert [f for f in shop_de.findings if f.check_id == "IDX-4" and f.severity.value == "S2"] == []


def test_shop_de_platform_is_not_named_wordpress(shop_de):
    assert "WordPress" not in str((shop_de.report.get("platform") or {}).get("name"))


def test_shop_de_s1_s3_findings_are_exactly_the_expected_set(shop_de):
    assert_serious_set(shop_de, (("STR-7", "S3", "over 500 KB"),))  # the 1.4 MB hero on the homepage


def test_shop_de_info_notes_stay_under_the_cap(shop_de):
    assert info_count(shop_de) <= 4  # the PNG-in-JPG note, Akamai's TCP_MISS, missing security headers (262), one slack


# == 2. saas-spa =================================================================================================
SPA_NOT_DRAFTS = {"/request-demo", "/demo", "/plan-2", "/blog/ab-test-nedir"}


def drafts(run: Run) -> set[str]:
    """Pages IDX-5 calls drafts or tests left published."""
    return {p for f in run.titled("draft or test", check="IDX-5") for p in run.paths(f)}


def test_saas_spa_rnd1_rendering_gap_is_found_from_raw_html(saas_spa):
    gaps = [f for f in saas_spa.findings if f.check_id == "RND-1"]
    assert gaps and {"/", "/pricing", "/demo"} <= saas_spa.paths(gaps[0])


@needs_browser
def test_saas_spa_rnd1_rendering_gap_is_confirmed_by_rendering(saas_spa_rendered):
    gaps = saas_spa_rendered.titled("only after JavaScript", check="RND-1")
    assert gaps and {"/", "/pricing", "/demo"} <= saas_spa_rendered.paths(gaps[0])


def test_saas_spa_print_page_without_viewport_is_found_tseo1(saas_spa):
    found = saas_spa.titled("viewport", check="TSEO-1")
    assert len(found) == 1 and saas_spa.paths(found[0]) == {"/legal/print"}
    assert found[0].severity.value in ("S3", "S4")


def test_saas_spa_demo_and_test_slugs_are_not_drafts_idx5(saas_spa):
    assert drafts(saas_spa) & SPA_NOT_DRAFTS == set()


@needs_browser
def test_saas_spa_rendered_demo_pages_are_not_drafts_idx5(saas_spa_rendered):
    assert drafts(saas_spa_rendered) & SPA_NOT_DRAFTS == set()


def test_saas_spa_plan_2_is_not_a_numbered_copy_idx5(saas_spa):
    assert "/plan-2" not in drafts(saas_spa)


def test_saas_spa_shared_shell_hash_is_not_two_addresses_idx8(saas_spa):
    assert [f for f in saas_spa.findings if f.check_id == "IDX-8"] == []


def test_saas_spa_gtm_preload_beside_its_snippet_is_not_analytics_twice_tseo1(saas_spa):
    assert saas_spa.titled("analytics tag more than once") == []


def test_saas_spa_vercel_insights_404_is_not_a_broken_link(saas_spa):
    assert mentions(saas_spa, "/_vercel/") == []


def test_saas_spa_s1_s3_findings_are_exactly_the_expected_set(saas_spa):
    # The raw HTML is an empty shell (RND-1, from raw-HTML heuristics) and the print view has no viewport.
    # Owner policy: a raw-HTML heuristic without browser corroboration is at most Medium.
    assert_serious_set(saas_spa, (("RND-1", "S3", "client-rendered"), ("TSEO-1", "S3", "viewport")))


def test_saas_spa_info_notes_stay_under_the_cap(saas_spa):
    assert info_count(saas_spa) <= 2  # the expected-type note for shells without their JSON-LD, one slack


# == 3. tarif-sube ===============================================================================================
LIST_VIEWS = {"/blog/?filter=best", "/blog/?sort=yeni", "/blog/page/2/"}


def test_tarif_sube_recipe_without_image_misses_a_required_property_str3(tarif_sube):
    found = tarif_sube.titled("Google-required", check="STR-3")
    assert found and "/tarifler/mercimek-corbasi" in tarif_sube.paths(found[0]) and "image" in str(found[0].evidence)


def test_tarif_sube_heavy_hero_off_the_key_pages_is_at_most_s4_str7(tarif_sube):
    heavy = tarif_sube.titled("over 500 KB", check="STR-7")
    assert heavy and "mercimek-hero.jpg" in str(heavy[0].evidence)
    assert all(f.severity.value in ("S4", "Info") for f in heavy)


def test_tarif_sube_branches_page_is_the_contact_page_str21(tarif_sube):
    assert "/subelerimiz" in basic_pages(tarif_sube)["Contact"] and "Contact" not in str21_missing(tarif_sube)


def test_tarif_sube_filter_sort_and_page_canonicals_are_not_idx4_s2(tarif_sube):
    s2 = [f for f in tarif_sube.findings if f.check_id == "IDX-4" and f.severity.value == "S2"]
    assert not [f for f in s2 if tarif_sube.paths(f) & LIST_VIEWS]


def test_tarif_sube_titled_linked_kek_2_is_not_a_draft_idx5(tarif_sube):
    assert "/tarifler/kek-2" not in drafts(tarif_sube)


def test_tarif_sube_titled_ornek_menu_is_not_a_draft_idx5(tarif_sube):
    assert "/ornek-menu" not in drafts(tarif_sube)


def test_tarif_sube_s1_s3_findings_are_exactly_the_expected_set(tarif_sube):
    assert_serious_set(tarif_sube, ())  # a healthy blog: the recipe's missing image is Info, the heavy hero S4


def test_tarif_sube_info_notes_stay_under_the_cap(tarif_sube):
    assert info_count(tarif_sube) <= 2  # the Recipe's missing image, one slack


# == 4. bank-multi ===============================================================================================
LEGAL = {"/en/legal/privacy", "/en/legal/cookies"}


def malformed_codes(run: Run) -> set[str]:
    return {item["hreflang"] for f in run.titled("malformed hreflang", check="STR-9")
            for item in f.evidence.get("items", [])}


def test_bank_multi_en_uk_is_a_malformed_hreflang_str9(bank_multi):
    assert "en-UK" in malformed_codes(bank_multi)


def test_bank_multi_jp_is_a_malformed_hreflang_str9(bank_multi):
    assert "jp" in malformed_codes(bank_multi)


def test_bank_multi_es_419_and_zh_hant_tw_are_not_malformed_str9(bank_multi):
    assert malformed_codes(bank_multi) & {"es-419", "zh-Hant-TW", "ar-AE", "de-DE", "x-default"} == set()


def test_bank_multi_login_without_viewport_is_s3_tseo1(bank_multi):
    found = bank_multi.titled("viewport", check="TSEO-1")
    assert len(found) == 1 and bank_multi.paths(found[0]) == {"/login"} and found[0].severity.value == "S3"


def test_bank_multi_noindex_in_the_sitemap_is_one_s3_finding_acc3(bank_multi):
    on_legal = [f for f in bank_multi.findings if f.severity.value in SERIOUS and bank_multi.paths(f) & LEGAL]
    assert len(on_legal) == 1 and on_legal[0].severity.value == "S3"


def test_bank_multi_sitemap_listing_noindex_pages_is_not_s2_acc3(bank_multi):
    assert [f for f in bank_multi.findings if f.severity.value == "S2" and bank_multi.paths(f) & LEGAL] == []


def test_bank_multi_en_without_slash_is_not_a_missing_self_or_return_link_str9(bank_multi):
    assert [f for f in bank_multi.findings if f.check_id == "STR-9" and "/en/" in bank_multi.paths(f)] == []


def test_bank_multi_unread_cctld_target_does_not_leave_str9_partial(bank_multi):
    parts = [p["part"] for p in bank_multi.checks["STR-9"].coverage.get("not_assessed", [])]
    assert "hreflang targets" not in parts


def test_bank_multi_trailing_slash_canonical_is_not_canonical_points_elsewhere_str9(bank_multi):
    rows = [row for f in bank_multi.findings if f.check_id == "STR-9" for row in f.evidence.get("links", [])
            if row.get("target") == bank_multi.base + "/en"]
    assert [p for row in rows for p in row.get("problems", []) if p.startswith("canonical")] == []


def test_bank_multi_en_and_en_slash_sharing_one_canonical_are_not_two_addresses_idx8(bank_multi):
    assert [f for f in bank_multi.findings if f.check_id == "IDX-8" and {"/en", "/en/"} <= bank_multi.paths(f)] == []


def test_bank_multi_onetrust_is_not_told_to_add_defer_tseo1(bank_multi):
    assert mentions(bank_multi, "cookielaw", ("TSEO-1",)) == []


def test_bank_multi_s1_s3_findings_are_exactly_the_expected_set(bank_multi):
    assert_serious_set(bank_multi, (("ACC-3", "S3", "noindex"), ("TSEO-1", "S3", "viewport")))


def test_bank_multi_info_notes_stay_under_the_cap(bank_multi):
    # The wrong hreflang codes, CloudFront's Miss, the footer's link to the canonicalized /en (IDX-4), one slack.
    assert info_count(bank_multi) <= 4


# == 5. local-wp =================================================================================================
def contact_pairs(run: Run) -> list[dict]:
    return [pair for f in run.titled("two addresses", check="IDX-8") for pair in f.evidence.get("pairs", [])
            if {run.base + "/iletisim", run.base + "/iletisim/"} == set(pair["urls"])]


def test_local_wp_dentist_without_address_misses_a_required_property_str3(local_wp):
    found = local_wp.titled("Google-required", check="STR-3")
    assert found and "/" in local_wp.paths(found[0]) and "address" in str(found[0].evidence)


def test_local_wp_iletisim_with_and_without_slash_is_found_s4_idx8(local_wp):
    found = local_wp.titled("two addresses", check="IDX-8")
    assert contact_pairs(local_wp) and all(f.severity.value == "S4" for f in found)


def test_local_wp_iletisim_pair_is_labelled_trailing_slash_idx8(local_wp):
    assert [p["differs_in"] for p in contact_pairs(local_wp)] == ["trailing slash"]


def test_local_wp_platform_is_wordpress(local_wp):
    assert (local_wp.report.get("platform") or {}).get("name") == "WordPress"


def test_local_wp_cdn_is_sucuri(local_wp):
    assert "Sucuri" in str((local_wp.report.get("platform") or {}).get("cdn"))


def test_local_wp_alt_equal_to_title_is_not_a_placeholder_str7(local_wp):
    assert local_wp.titled("placeholder alt") == []


def test_local_wp_jquery_in_head_is_not_a_finding_tseo1(local_wp):
    assert local_wp.titled("without defer or async") == []


def test_local_wp_missing_twitter_card_is_not_a_notes_line_str10(local_wp):
    assert local_wp.titled("twitter") == []


def test_local_wp_s1_s3_findings_are_exactly_the_expected_set(local_wp):
    assert_serious_set(local_wp, ())  # the contact pair is S4, the Dentist's missing address Info


def test_local_wp_info_notes_stay_under_the_cap(local_wp):
    assert info_count(local_wp) <= 3  # the Dentist's missing address, missing security headers (262), one slack


# == 6. shopify ==================================================================================================
def test_shopify_product_without_offers_misses_a_required_property_str3(shopify):
    found = shopify.titled("Google-required", check="STR-3")
    assert found and "/products/tisort-3" in shopify.paths(found[0]) and "offers" in str(found[0].evidence)


def test_shopify_platform_is_shopify(shopify):
    assert (shopify.report.get("platform") or {}).get("name") == "Shopify"


def test_shopify_add_to_bag_is_a_buy_control(shopify):
    from maya_audit.checks.structure import _buy_texts
    assert _buy_texts(shopify.page("/products/tisort-1"))


def test_shopify_sort_by_and_page_canonicals_are_not_idx4_s2(shopify):
    assert [f for f in shopify.findings if f.check_id == "IDX-4" and f.severity.value == "S2"] == []


def test_shopify_titled_numbered_products_are_not_drafts_idx5(shopify):
    assert drafts(shopify) & {"/products/tisort-1", "/products/tisort-2"} == set()


def test_shopify_gtm_beside_gtag_is_not_a_finding_tseo1(shopify):
    assert shopify.titled("analytics tag more than once") == []


def test_shopify_webp_in_jpg_from_the_image_cdn_is_not_a_format_mismatch_str7(shopify):
    assert shopify.titled("format", check="STR-7") == []


def test_shopify_without_cf_cache_status_no_cdn_cache_finding_prf1(shopify):
    assert [f for f in shopify.findings if f.check_id == "PRF-1" and "cache" in f.title.lower()] == []


def test_shopify_s1_s3_findings_are_exactly_the_expected_set(shopify):
    assert_serious_set(shopify, ())


def test_shopify_info_notes_stay_under_the_cap(shopify):
    assert info_count(shopify) <= 3  # the product's missing offers, missing security headers (262), one slack


# == 7. draft-real (positive control) ============================================================================
DRAFTS = {"/taslak", "/test", "/hakkimizda-2"}


def test_draft_real_three_drafts_are_one_idx5_s3_finding(draft_real):
    found = draft_real.titled("draft or test", check="IDX-5")
    assert len(found) == 1 and draft_real.paths(found[0]) == DRAFTS and found[0].severity.value == "S3"


def test_draft_real_untitled_page_count_leaves_out_the_drafts_str1(draft_real):
    found = draft_real.titled("no <title>", check="STR-1")
    assert len(found) == 1 and draft_real.paths(found[0]) == {"/kampanya"}


def test_draft_real_camera_file_name_alt_is_a_placeholder_str7(draft_real):
    found = draft_real.titled("placeholder alt")
    assert found and "IMG_2034" in str(found[0].evidence)


def test_draft_real_gtm_loaded_twice_is_noted_tseo1(draft_real):
    found = mentions(draft_real, "GTM-ABC1234", ("TSEO-1",))
    assert found and all(f.severity.value == "Info" for f in found)


def test_draft_real_http_script_is_mixed_content_s3_tseo1(draft_real):
    found = draft_real.titled("mixed content", check="TSEO-1")
    assert len(found) == 1 and draft_real.paths(found[0]) == {"/projeler"} and found[0].severity.value == "S3"


def test_draft_real_hakkimizda_itself_is_not_a_draft_idx5(draft_real):
    assert "/hakkimizda" not in drafts(draft_real)


def test_draft_real_s1_s3_findings_are_exactly_the_expected_set(draft_real):
    assert_serious_set(draft_real, (("IDX-5", "S3", "draft"), ("TSEO-1", "S3", "mixed content")))


def test_draft_real_info_notes_stay_under_the_cap(draft_real):
    # GTM twice, and the drafts' missing og:title / og:description / og:image / description (four STR-10 lines).
    assert info_count(draft_real) <= 6


# == 8. news-video ===============================================================================================
def default_videos(run: Run) -> set[str]:
    return {p for f in run.findings if "videoobject" in f.title.lower() and "default" in f.title.lower()
            for p in run.paths(f)}


def dates_read(run: Run, path: str) -> set[str]:
    from maya_audit.checks.structure import visible_dates
    return {d["date"].isoformat() for d in visible_dates(run.page(path).analysis)}


def test_news_video_video_named_video_is_an_unfilled_default_str3(news_video):
    assert "/videos/conseil-municipal" in default_videos(news_video)


def test_news_video_publish_date_is_read_from_the_time_element_str6(news_video):
    assert "2026-03-03" in dates_read(news_video, "/actualites/tramway-ligne-c")


def test_news_video_publish_date_is_read_from_french_text_str6(news_video):
    assert "2026-02-14" in dates_read(news_video, "/actualites/budget-2026")


def test_news_video_todays_named_video_is_not_a_default_str3(news_video):
    assert "/videos/crue-de-la-saone" not in default_videos(news_video)


def test_news_video_fastly_miss_hit_with_no_cache_is_not_uncached_prf1(news_video):
    assert [f for f in news_video.findings if f.check_id == "PRF-1" and "not cached" in f.title] == []


def test_news_video_a_propos_is_an_about_page_str21(news_video):
    assert "/a-propos" in basic_pages(news_video)["About"]


def test_news_video_s1_s3_findings_are_exactly_the_expected_set(news_video):
    assert_serious_set(news_video, ())


def test_news_video_info_notes_stay_under_the_cap(news_video):
    # The default "Video" and STR-21 (a news site has no product page or FAQ), one slack.
    assert info_count(news_video) <= 3


# == every finding has a stable rule id (DECISIONS 269) ===========================================================

@pytest.mark.parametrize("fixture", ["shop_de", "saas_spa", "saas_spa_rendered", "tarif_sube", "bank_multi", "local_wp",
                                     "shopify", "draft_real", "news_video"])
def test_every_finding_of_every_site_has_a_rule_id(fixture, request):
    run = request.getfixturevalue(fixture)
    items = run.findings + [r for c in run.outcome.checks for r in c.review_items]
    assert items and [(f.check_id, f.title) for f in items if not f.rule_id] == []
