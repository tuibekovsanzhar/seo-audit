"""Round 3 of the external review, run 1 (team-preview-17; DECISIONS 229 to 231; FA-032, FA-033; LG-93, LG-101).

- STR-3's page kinds read Turkish folders, and a product page is told by one price of its own and a buy button (229).
- The Organization types take in banks, food, health and hotels (FA-032); a page typed Restaurant or CollectionPage is
  not an article because its og:type says so (FA-033).
- A page's encoding is read as a browser reads it: byte-order mark, header, <meta charset>, else UTF-8 (230).
- The three file locks work where Python has no fcntl (Windows), through maya_audit.filelock (231).

Every site is made up and held in memory or on a local fake server; nothing is fetched from the internet.
"""
import sys
import threading
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from maya_audit import filelock, page_words
from maya_audit.analysis import analyze_html
from maya_audit.checks import small_site
from maya_audit.checks.structure import KIND_NOTE, page_kind, product_template, str3_structured_data
from maya_audit.config import CrawlConfig
from maya_audit.html_links import decode_body, detect_charset, extract_link_edges
from maya_audit.models import StopReason

ROOT = "https://demo-magaza.test"
CFG = CrawlConfig()
TEXT = ("Bu sayfa, örnek bir mağazanın ürününü anlatan uzun bir metindir ve yalnızca deneme için yazılmıştır. "
        "Ürün pamuktan yapılmıştır, her mevsim kullanılabilir ve kolayca yıkanır. ")


def page(title, body="", *, og_type=None, jsonld=None, head=""):
    meta = f'<meta property="og:type" content="{og_type}">' if og_type else ""
    script = f'<script type="application/ld+json">{jsonld}</script>' if jsonld else ""
    return (f'<!doctype html><html lang="tr"><head><title>{title}</title>{meta}{script}{head}</head><body>'
            f'<header><nav><a href="/">Ana Sayfa</a></nav></header>'
            f'<main><h1>{title}</h1><p>{TEXT}</p>{body}</main><footer><p>Demo Mağaza</p></footer></body></html>')


def site(pages_html):
    """(result, pages) as the checks see them, from made-up HTML by path. Nothing is fetched."""
    pages = [SimpleNamespace(url=ROOT + path, analysis=analyze_html(text, ROOT + path), body_truncated=False, status=200,
                             headers={}, depth=0 if path == "/" else 1,
                             outlinks=[e for e in extract_link_edges(text, ROOT + path) if e["target"].startswith(ROOT)])
             for path, text in pages_html.items()]
    return SimpleNamespace(origin=ROOT, start_url=ROOT + "/", pages=pages, stop_reason=StopReason.EXHAUSTED,
                           not_fetched_urls=[]), pages


ORG = '{"@context": "https://schema.org", "@type": "Organization", "name": "Demo Mağaza"}'
HOME = page("Demo Mağaza", jsonld=ORG)


def str3(pages_html):
    result, pages = site({"/": HOME, **pages_html})
    return str3_structured_data(result, CFG, pages, set())


def expected_rows(check):
    return {row["url"].removeprefix(ROOT): row for f in check.findings if "expected for their page kind" in f.title
            for row in f.evidence["pages"]}


def by_title(check, words):
    return [f for f in check.findings if words in f.title]


def product(price, button='<button type="button">Sepete Ekle</button>'):
    return f"<p>Fiyat: {price}</p>{button}"


# -- item 6: Turkish page kinds and the product template (DECISIONS 229) ----------------------------------------------
def test_two_root_level_pages_with_one_price_and_a_buy_button_are_product_pages():
    check = str3({"/pamuk-tisort": page("Pamuk Tişört", product("149,90 TL")),
                  "/keten-gomlek": page("Keten Gömlek", product("249,90 TL"))})
    rows = expected_rows(check)
    assert set(rows) == {"/pamuk-tisort", "/keten-gomlek"}
    assert all(r["page_kind"] == "product" and "buy control (Sepete Ekle)" in r["classified_by"] for r in rows.values())
    [finding] = by_title(check, "expected for their page kind")
    assert KIND_NOTE in finding.notes and "(English and Turkish words)" in KIND_NOTE
    assert not by_title(check, "no buy button")


def test_the_same_layout_under_a_category_folder_is_not_a_product_page():
    check = str3({"/kategori/pamuk-tisort": page("Pamuk Tişört", product("149,90 TL")),
                  "/kategori/keten-gomlek": page("Keten Gömlek", product("249,90 TL"))})
    assert expected_rows(check) == {} and not by_title(check, "no buy button")


def test_one_such_page_alone_or_two_prices_on_a_page_is_not_a_product_page():
    alone = str3({"/pamuk-tisort": page("Pamuk Tişört", product("149,90 TL")), "/hakkimizda": page("Hakkımızda")})
    assert expected_rows(alone) == {}
    two_prices = str3({"/pamuk-tisort": page("Pamuk Tişört", product("149,90 TL") + "<p>Eski fiyat: 199,90 TL</p>"),
                       "/keten-gomlek": page("Keten Gömlek", product("249,90 TL"))})
    assert expected_rows(two_prices) == {}


def test_a_form_posting_to_the_cart_and_an_input_button_are_buy_controls():
    form = '<form action="/sepet/ekle" method="post"><input type="hidden" name="id" value="1"></form>'
    submit = '<input type="submit" value="Satın Al">'
    check = str3({"/pamuk-tisort": page("Pamuk Tişört", product("149,90 TL", form)),
                  "/keten-gomlek": page("Keten Gömlek", product("249,90 TL", submit))})
    rows = expected_rows(check)
    assert set(rows) == {"/pamuk-tisort", "/keten-gomlek"}
    assert "(/sepet/ekle)" in rows["/pamuk-tisort"]["classified_by"] and "(Satın Al)" in rows["/keten-gomlek"]["classified_by"]


def test_a_buy_button_in_the_header_is_not_the_pages_own():
    header_button = '<header><button>Hemen Al</button></header>'
    check = str3({"/pamuk-tisort": page("Pamuk Tişört", "<p>Fiyat: 149,90 TL</p>").replace("<header>", header_button + "<header>"),
                  "/keten-gomlek": page("Keten Gömlek", "<p>Fiyat: 249,90 TL</p>").replace("<header>", header_button + "<header>")})
    assert expected_rows(check) == {}


def test_product_markup_is_not_evidence_and_a_typed_product_page_lacks_nothing():
    typed = '{"@context": "https://schema.org", "@type": "Product", "name": "Pamuk Tişört", "offers": {"@type": "Offer", "price": "149.90", "priceCurrency": "TRY"}}'
    check = str3({"/pamuk-tisort": page("Pamuk Tişört", product("149,90 TL"), jsonld=typed),
                  "/keten-gomlek": page("Keten Gömlek", product("249,90 TL")),
                  "/sadece-isaretli": page("Sadece İşaretli", jsonld=typed.replace("149.90", "99"))})
    assert set(expected_rows(check)) == {"/keten-gomlek"}  # the marked-up page lacks nothing; markup alone makes no kind


def test_a_price_without_a_buy_button_is_at_most_an_info_note():
    check = str3({"/danismanlik": page("Danışmanlık", "<p>Ücret: 1.500 TL</p>"),
                  "/egitim": page("Eğitim", "<p>Ücret: 2.500 TL</p>")})
    assert expected_rows(check) == {}
    [note] = by_title(check, "no buy button")
    assert note.title == "2 page(s) show one price and no buy button: they may be product pages, check"
    assert note.severity.value == "Info" and note.confidence.value == "estimated"
    assert [r["url"].removeprefix(ROOT) for r in note.evidence["pages"]] == ["/danismanlik", "/egitim"]
    one = str3({"/danismanlik": page("Danışmanlık", "<p>Ücret: 1.500 TL</p>"), "/egitim": page("Eğitim")})
    assert not by_title(one, "no buy button")


def test_turkish_folders_name_products_articles_faq_and_pricing():
    check = str3({"/urunler/pamuk-tisort": page("Pamuk Tişört"), "/haberler/yeni-sube": page("Yeni Şube"),
                  "/rehber/nasil-yikanir": page("Nasıl Yıkanır"), "/sss": page("Sıkça Sorulan Sorular"),
                  "/fiyatlar": page("Fiyatlar"), "/etiket/yaz": page("Yaz", og_type="article")})
    kinds = {path: row["page_kind"] for path, row in expected_rows(check).items()}
    assert kinds == {"/urunler/pamuk-tisort": "product", "/haberler/yeni-sube": "article", "/rehber/nasil-yikanir": "article",
                     "/sss": "faq", "/fiyatlar": "pricing"}  # a tag page is never an article, whatever its og:type


def test_healthy_english_product_and_blog_paths_still_count():
    check = str3({"/products/cotton-shirt": page("Cotton Shirt"), "/blog/how-to-wash": page("How to Wash")})
    kinds = {path: row["page_kind"] for path, row in expected_rows(check).items()}
    assert kinds == {"/products/cotton-shirt": "product", "/blog/how-to-wash": "article"}
    assert expected_rows(check)["/products/cotton-shirt"]["classified_by"] == "path /products/…"


def test_str21_word_lists_and_folding_moved_unchanged():
    assert small_site.BASIC_PAGES is page_words.BASIC_PAGES and small_site.ADDRESS_ONLY is page_words.ADDRESS_ONLY
    assert small_site._fold("İLETİŞİM") == page_words.fold("İletişim") == "iletisim"
    assert small_site._segments(ROOT + "/Hakkımızda.html") == ["hakkimizda"]
    assert page_words.says(page_words.RESTAURANT_WORDS, page_words.fold("Paket Servis ve Rezervasyon"))
    assert not page_words.says(page_words.RESTAURANT_WORDS, page_words.fold("Menülerimiz"))


# -- FA-032: the Organization types widened (DECISIONS 229) -----------------------------------------------------------
def test_a_homepage_typed_only_bank_or_credit_union_has_organization_markup():
    bank = '{"@context": "https://schema.org", "@type": "BankOrCreditUnion", "name": "Demo Kart"}'
    result, pages = site({"/": page("Demo Kart", jsonld=bank)})
    check = str3_structured_data(result, CFG, pages, set())
    assert not by_title(check, "no Organization")
    result, pages = site({"/": page("Demo Kart")})
    assert by_title(str3_structured_data(result, CFG, pages, set()), "no Organization")  # still said when there is none


def test_a_bank_typed_beside_its_parent_on_one_id_is_no_type_clash():
    both = ('{"@context": "https://schema.org", "@graph": [{"@type": "BankOrCreditUnion", "@id": "/#bank", "name": "Demo Kart"},'
            '{"@type": "FinancialService", "@id": "/#bank", "name": "Demo Kart"}]}')
    result, pages = site({"/": page("Demo Kart", jsonld=both)})
    assert not by_title(str3_structured_data(result, CFG, pages, set()), "different types")


# -- FA-033: Restaurant and CollectionPage pages are not articles by og:type alone (DECISIONS 229) ------------------
def test_a_branch_typed_restaurant_and_a_listing_with_og_type_article_are_not_articles():
    restaurant = '{"@context": "https://schema.org", "@type": "Restaurant", "name": "Demo Kafe Kadıköy", "servesCuisine": "Kahve"}'
    listing = '{"@context": "https://schema.org", "@type": "CollectionPage", "name": "Şubeler"}'
    check = str3({"/subeler/kadikoy": page("Kadıköy Şubesi", og_type="article", jsonld=restaurant),
                  "/subeler": page("Şubeler", og_type="article", jsonld=listing),
                  "/duyuru": page("Duyuru", og_type="article"),
                  "/blog/liste": page("Liste", og_type="article", jsonld=listing)})
    rows = expected_rows(check)
    assert set(rows) == {"/duyuru", "/blog/liste"}  # og:type alone still makes an article; a path word still does
    assert rows["/blog/liste"]["classified_by"] == "path /blog/…"


def test_page_kind_and_template_read_saved_analyses_without_the_new_keys():
    result, pages = site({"/pamuk-tisort": page("Pamuk Tişört", product("149,90 TL")), "/keten-gomlek": page("Keten Gömlek", product("249,90 TL"))})
    for p in pages:
        for key in ("input_buttons", "form_actions"):
            p.analysis.pop(key)
    assert set(product_template(pages, ROOT + "/")["products"]) == {p.url for p in pages}
    assert page_kind(pages[0], ROOT + "/", {})[0] is None


# -- item 7: the charset order (DECISIONS 230) ------------------------------------------------------------------------
TURKISH = "ğüşıöç ĞÜŞİÖÇ"


def cp1254_page(meta='<meta charset="windows-1254">'):
    return (f'<!doctype html><html lang="tr"><head>{meta}<title>Türkçe</title></head><body><main><h1>{TURKISH}</h1>'
            f"<p>{TEXT * 3}</p></main></body></html>").encode("cp1254")


def test_a_cp1254_page_with_only_a_meta_charset_decodes():
    text = decode_body(cp1254_page(), "text/html")
    assert TURKISH in text and "�" not in text
    assert detect_charset(cp1254_page('<meta http-equiv="Content-Type" content="text/html; charset=ISO-8859-9">'), None) == "cp1254"
    assert {detect_charset(b"", f"text/html; charset={label}") for label in ("windows-1254", "iso-8859-9", "latin5", "x-cp1254")} == {"cp1254"}
    assert {detect_charset(b"", f"text/html; charset={label}") for label in ("iso-8859-1", "US-ASCII")} == {"cp1252"}


def test_bom_beats_header_and_header_beats_meta():
    assert decode_body(b"\xef\xbb\xbf" + "ğü".encode("utf-8"), "text/html; charset=windows-1254") == "ğü"
    assert decode_body(b"\xff\xfe" + "ğü".encode("utf-16-le"), "text/html; charset=windows-1254") == "ğü"
    body = '<meta charset="utf-8"><p>ğüş</p>'.encode("cp1254")
    assert detect_charset(body, "text/html; charset=windows-1254") == "cp1254" and "ğüş" in decode_body(body, "text/html; charset=windows-1254")
    late = b"<!--" + b" " * 4100 + b'--><meta charset="windows-1254">'
    assert detect_charset(late, None) == "utf-8"  # a meta after the first 4,096 bytes is not read


def test_an_unknown_label_is_passed_over_and_healthy_utf8_is_unchanged():
    assert detect_charset(b'<meta charset="windows-1254">', "text/html; charset=nonsense") == "cp1254"
    assert detect_charset(b"", "text/html; charset=rot13") == "utf-8" and detect_charset(b"", None) == "utf-8"
    healthy = f"<html><head><title>Türkçe</title></head><body>{TURKISH}</body></html>".encode("utf-8")
    assert decode_body(healthy, "text/html; charset=utf-8") == healthy.decode("utf-8")
    assert decode_body(healthy, "text/html") == healthy.decode("utf-8")


def _browser_available() -> str | None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return "Playwright is not installed"
    try:
        with sync_playwright() as p:
            p.chromium.launch(headless=True).close()
    except Exception as exc:  # noqa: BLE001
        return f"headless Chromium unavailable: {exc}"
    return None


def test_a_rendered_cp1254_page_shows_the_same_words_as_the_raw_html():
    reason = _browser_available()
    if reason:
        pytest.skip(f"the cp1254 render test needs a headless browser: {reason}")
    from fakeserver import FakeServer, Response, Site
    from fakeserver.scenarios import robots
    from maya_audit.audit import run_audit

    routes = {"/robots.txt": robots("User-agent: *\nAllow: /\n"), "/sitemap.xml": Response(404, "", content_type="text/plain"),
              "/": Response(body=cp1254_page(), content_type="text/html")}
    options = {"max_pages": 1, "time_limit_s": 20, "request_timeout_s": 3, "request_delay_s": 0, "robots_samples": 1,
               "robots_sample_interval_s": 0, "render_enabled": True, "render_budget": 1, "render_timeout_s": 6,
               "render_settle_ms": 100, "render_control_wait_ms": 0, "render_interactions": False,
               "probes_enabled": False, "prf_enabled": False}
    with FakeServer(Site(routes)) as server:
        result = run_audit(server.base_url + "/", CrawlConfig(**options)).result
    [raw] = [p for p in result.pages if p.analysis]
    [entry] = result.render.pages.values()
    assert entry["ok"]
    raw_h1 = [h["text"] for h in raw.analysis["headings"] if h["level"] == 1]
    rendered_h1 = [h["text"] for h in entry["rendered"]["headings"] if h["level"] == 1]
    assert raw_h1 == rendered_h1 == [TURKISH]


# -- item 8: the Windows locks (DECISIONS 231) ------------------------------------------------------------------------
class FakeMsvcrt(types.ModuleType):
    LK_UNLCK, LK_LOCK, LK_NBLCK = 0, 1, 2

    def __init__(self, fail=0, error=OSError):
        super().__init__("msvcrt")
        self.calls, self.fail, self.error = [], fail, error

    def locking(self, fd, mode, nbytes):
        self.calls.append((mode, nbytes))
        if mode != self.LK_UNLCK and self.fail:
            self.fail -= 1
            raise self.error("locked by another process")


@pytest.fixture
def windows(monkeypatch):
    """No fcntl (an import of it fails, as on Windows) and a stand-in msvcrt that records its calls."""
    fake = FakeMsvcrt()
    monkeypatch.setitem(sys.modules, "fcntl", None)
    monkeypatch.setitem(sys.modules, "msvcrt", fake)
    return fake


class Tracked:
    def __init__(self, path):
        self.handle = open(path, "a+")
        self.seeks = []

    def seek(self, offset, whence=0):
        self.seeks.append(offset)
        return self.handle.seek(offset, whence)

    def fileno(self):
        return self.handle.fileno()


def test_on_windows_the_lock_seeks_to_the_start_and_locks_one_byte_without_waiting(windows, tmp_path):
    f = Tracked(tmp_path / "worker.lock")
    f.handle.write("held")
    filelock.lock(f, blocking=False)
    filelock.unlock(f)
    assert f.seeks == [0, 0] and windows.calls == [(FakeMsvcrt.LK_NBLCK, 1), (FakeMsvcrt.LK_UNLCK, 1)]


def test_on_windows_a_held_lock_gives_worker_already_running(windows, tmp_path):
    from maya_audit_web.runner import Runner, WorkerAlreadyRunning

    windows.fail = 1
    with pytest.raises(WorkerAlreadyRunning):
        Runner(SimpleNamespace(folder=tmp_path), engine=None)
    assert windows.calls == [(FakeMsvcrt.LK_NBLCK, 1)]


def test_on_windows_a_blocking_lock_asks_again_until_it_has_it(windows, tmp_path):
    windows.fail = 3
    with open(tmp_path / "ledger.lock", "a+") as f:
        filelock.lock(f, blocking=True)
    assert windows.calls == [(FakeMsvcrt.LK_LOCK, 1)] * 4


def test_on_windows_the_ledger_and_the_site_lock_use_msvcrt(windows, tmp_path):
    from maya_audit.crawler import ConcurrentCrawlError, _shared_site_lock
    from maya_audit.dataforseo.ledger import Ledger

    with Ledger(tmp_path / "ledger.jsonl")._locked():
        pass
    assert windows.calls == [(FakeMsvcrt.LK_LOCK, 1), (FakeMsvcrt.LK_UNLCK, 1)]
    windows.calls.clear()
    with _shared_site_lock("https://demo-kafe.test"):
        pass
    assert windows.calls == [(FakeMsvcrt.LK_NBLCK, 1), (FakeMsvcrt.LK_UNLCK, 1)]
    windows.fail = 1
    with pytest.raises(ConcurrentCrawlError):
        with _shared_site_lock("https://demo-kafe.test"):
            pass


def test_runner_and_ledger_no_longer_import_fcntl():
    root = Path(__file__).resolve().parent.parent
    for name in ("maya_audit_web/runner.py", "maya_audit/dataforseo/ledger.py", "maya_audit/crawler.py"):
        assert "fcntl" not in (root / name).read_text(encoding="utf-8"), name


def test_healthy_fcntl_lock_still_keeps_a_second_holder_out(tmp_path):
    first, second = open(tmp_path / "x.lock", "a+"), open(tmp_path / "x.lock", "a+")
    try:
        filelock.lock(first, blocking=False)
        with pytest.raises(OSError):
            filelock.lock(second, blocking=False)
        got = threading.Event()
        waiter = threading.Thread(target=lambda: (filelock.lock(second, blocking=True), got.set()))
        waiter.start()
        assert not got.wait(0.2)
        filelock.unlock(first)
        assert got.wait(5)
        waiter.join(5)
        filelock.unlock(second)
    finally:
        first.close()
        second.close()
