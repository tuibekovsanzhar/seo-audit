"""A made-up Turkish shop modelled on a real Ticimax + Cloudflare audit (arjava.com.tr, October 2026).

Every defect a manual audit found on that site, and every place Maya's own report on it went wrong, has a page here.
tests/test_arjava_regression.py states what a correct audit says about each one. Nothing here is the real site's
content: names, prices and text are invented; only the shapes of the problems are kept.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from .scenarios import Scenario, robots
from .server import Response, Site

TODAY = datetime.now(timezone.utc).date().isoformat()  # the engine compares with the UTC day of the audit
CF_HEADERS = {"server": "cloudflare", "cf-cache-status": "DYNAMIC", "cache-control": "private, max-age=0",
              "strict-transport-security": "max-age=31536000"}
SITE_TITLE = "Arjava | Premium Koku Difüzörleri ve Ev Kokuları"
TEXT = ("Arjava koku difüzörleri evinize uzun süre kalıcı ve dengeli bir koku verir. Kartuşlar kolayca değişir, "
        "difüzör sessiz çalışır ve uygulama ile yoğunluk ayarlanır. ")

# Platform signatures as a Ticimax storefront prints them (script host and the theme's own folder).
TICIMAX_HEAD = ('<meta name="viewport" content="width=device-width, initial-scale=1">'
                '<script src="https://static.ticimax.cloud/js/jquery.min.js"></script>'
                '<script src="https://static.ticimax.cloud/js/ticimax.core.js"></script>'
                '<script src="/Scripts/theme.js"></script><script src="/Scripts/cart.js"></script>'
                '<script src="/Scripts/menu.js"></script><script src="/Scripts/slider.js"></script>'
                '<script src="/Scripts/efilli.js"></script><script src="/Scripts/search.js"></script>'
                '<script src="/Scripts/lazy.js" defer></script>')
# The same container printed twice, plus a direct gtag for the same property: likely double counting.
ANALYTICS = ('<script async src="https://www.googletagmanager.com/gtag/js?id=G-8W55STRKEZ"></script>'
             '<script>gtag("config", "G-8W55STRKEZ");</script>')
GTM_NOSCRIPT = ('<noscript><iframe src="https://www.googletagmanager.com/ns.html?id=GTM-N7M2FVGL" height="0" '
                'width="0" style="display:none;visibility:hidden"></iframe></noscript>')
HEADER = ('<header><a href="/"><img src="/uploads/logo.png" alt=""></a>'
          '<a href="/difuzor">Difüzörler</a> <a href="/kokular">Kokular</a> <a href="/sikca-sorulan-sorular">SSS</a> '
          '<a href="/iletisim.aspx">İletişim</a> <a href="/UyeGiris">Üye Girişi</a> '
          '<a href="/Hesabim.aspx#/Favorilerim"><i class="icon-heart"></i></a></header>')
EMAIL_LINK = ('<a href="/cdn-cgi/l/email-protection#7a1b0815" class="__cf_email__" '
              'data-cfemail="7a1b0815">[email&#160;protected]</a>')
FOOTER = (f'<footer>{GTM_NOSCRIPT}<a href="/kvkk">KVKK</a> <a href="/mesafeli-satis-sozlesmesi">Mesafeli Satış</a> '
          f'<a href="/teslimat-ve-iade">Teslimat ve İade</a> <a href="/gizlilik-ve-cerez-politikasi">Gizlilik</a> '
          f'<a href="/house-of-arjava">House of Arjava</a> <a href="/UyeGiris.aspx">Giriş</a> '
          f'<a href="/Hesabim">Hesabım</a> Bize yazın: {EMAIL_LINK}</footer>')


WORDS = ("koku", "difüzör", "kartuş", "teslimat", "iade", "sipariş", "müşteri", "ürün", "gizlilik", "çerez", "veri",
         "sözleşme", "ödeme", "kargo", "garanti", "ev", "oda", "yoğunluk", "uygulama", "bakım", "hizmet", "destek",
         "adres", "fatura", "taksit", "kampanya", "mağaza", "stok", "renk", "tasarım", "enerji", "süre")


def filler(seed: str, words: int) -> str:
    """Text of its own for each page, so pages that are not copies of each other do not read as copies."""
    import random

    rng = random.Random(seed)
    return " ".join(rng.choice(WORDS) for _ in range(words)) + "."


AUTO = "<auto>"  # each page gets its own description unless a test page needs it absent or empty


def ld(obj: dict) -> str:
    return f'<script type="application/ld+json">{json.dumps(obj, ensure_ascii=False)}</script>'


def page(title: str | None, body: str, *, description: str | None = AUTO,
         head: str = "", robots_meta: str | None = None, og_title: str | None = None,
         headers: dict | None = None) -> Response:
    title_tag = f"<title>{title}</title>" if title is not None else ""
    if description is AUTO:  # each page its own description unless a test page needs it absent or empty
        description = f"{title.split(' | ')[0]} sayfası: Arjava koku difüzörleri ve ev kokuları." if title else None
    desc = f'<meta name="description" content="{description}">' if description is not None else ""
    meta_robots = f'<meta name="robots" content="{robots_meta}">' if robots_meta else ""
    og = (f'<meta property="og:site_name" content="{title or SITE_TITLE}">'
          f'<meta property="og:title" content="{og_title if og_title is not None else (title or "")}">')
    html = (f'<!doctype html><html lang="tr"><head><meta charset="utf-8">{title_tag}{desc}{meta_robots}{og}'
            f'{TICIMAX_HEAD}{ANALYTICS}{head}</head><body>{GTM_NOSCRIPT}{HEADER}<main>{body}</main>{FOOTER}</body></html>')
    return Response(body=html, headers={**CF_HEADERS, **(headers or {})})


# The Organization block a theme printed with the street address on two lines: a raw newline inside a JSON
# string, so the whole block does not parse (the manual audit: "Invalid control character at char 471").
BROKEN_ORGANIZATION = ('<script type="application/ld+json">{"@context":"https://schema.org","@type":"Organization",'
                       '"name":"Arjava","url":"{base}/","address":{"@type":"PostalAddress",'
                       '"streetAddress":"Tem Yan Yolu\n1 No\'lu Cadde","addressLocality":"İstanbul"},'
                       '"contactPoint":{"@type":"ContactPoint","contactOption":"TollFree","faxNumber":""}}</script>')
VIDEO = ld({"@context": "https://schema.org", "@type": "VideoObject", "name": "Video",
            "thumbnailUrl": "{base}/uploads/videoposter.jpg", "uploadDate": TODAY,
            "contentUrl": "{base}/uploads/promo.mp4"})
HOME_HEAD = ('<link rel="canonical" href="{base}/">'
             '<link rel="alternate" hreflang="tr" href="{base}">'
             '<link rel="alternate" hreflang="en" href="{base}/en">'
             '<meta property="og:image" content="{base}/uploads/og.jpg">'
             '<link rel="preload" as="image" href="{base}/uploads/hero.jpg" type="image/jpg">'
             + BROKEN_ORGANIZATION + VIDEO)
HOME_BODY = (
    '<section class="resimblok_2 hide-mobile"><a href="/difuzor"><img src="/uploads/hero.jpg" alt=""></a></section>'
    '<img src="/uploads/banner1.jpg" alt="Banner"> <img src="/uploads/banner2.jpg" alt="Banner">'
    '<h2>Difüzörler</h2>'
    + "".join(f'<a href="/arjava-koku-difuzoru-{c}"><img src="/uploads/{c}.jpg" alt="image title"> Işıklı difüzör</a>'
              for c in ("bej-13", "siyah-8", "taba-14", "vizon-12"))
    + f'<div class="sss"><span>Difüzör nasıl çalışır?</span><span>{TEXT}</span>'
      f'<span>Kartuş ne kadar dayanır?</span><span>{TEXT}</span></div>'
    + '<video src="/uploads/promo.mp4" autoplay muted></video>'
    + f'<p>{TEXT * 3}</p>'
    + f'<h1 style="display:none">{SITE_TITLE}</h1>'
)

PRODUCTS = {"bej-13": "Bej", "siyah-8": "Siyah", "taba-14": "Taba", "vizon-12": "Vizon"}
CARTRIDGES = {"anatolian-breeze-koku-kartusu-40-ml": "Anatolian Breeze", "golden-harem-koku-kartusu-40-ml": "Golden Harem"}


def product(name: str, price: str) -> Response:
    body = (f'<h1>{name}</h1><p class="price">{price} TL</p><button class="sepete-ekle">Sepete Ekle</button>'
            f'<p>{TEXT * 4}</p><a href="javascript:void(0)">Yorumlar</a><a href="javascript:void(0)">Paylaş</a>'
            '<a href="javascript:void(0)">Taksit</a><a href="/Hesabim.aspx#/Favorilerim"></a>')
    schema = ld({"@context": "https://schema.org", "@type": "Product", "name": name, "image": "{base}/uploads/p.jpg",
                 "offers": {"@type": "Offer", "price": price.replace(".", "").replace(",", "."),
                            "priceCurrency": "TRY", "availability": "https://schema.org/InStock"}})
    return page(f"{name} | Arjava", body, head=schema)


def category(name: str, items: dict[str, str]) -> Response:
    cards = "".join(f'<div class="urun-kart"><a href="/{slug}">{label}</a><span class="price">1.299,00 TL</span>'
                    f'<button class="sepete-ekle">Sepete Ekle</button></div>' for slug, label in items.items())
    return page(f"{name} | Arjava", f'<div class="urun-listesi">{cards}</div><p>{TEXT}</p>', og_title="")


def legal(title: str | None, seed: str, words: int = 120) -> Response:
    return page(title, f"<p>{filler(seed, words)}</p><p>Bize yazın: {EMAIL_LINK}</p>", description=None)


SITEMAP_PATHS = ("/", "/en", "/difuzor", "/kokular", "/sikca-sorulan-sorular", "/house-of-arjava", "/iletisim.aspx",
                 "/kvkk", "/mesafeli-satis-sozlesmesi", "/teslimat-ve-iade", "/gizlilik-ve-cerez-politikasi",
                 *(f"/arjava-koku-difuzoru-{c}" for c in PRODUCTS), *(f"/{c}" for c in CARTRIDGES),
                 "/test-marka", "/arjava-2", "/arjava-3", "/test-22222", "/test-sayfaaaa", "/sss-test")


def _sitemap() -> Response:
    # The generator stamps every URL with the day the file was built.
    urls = "".join(f"<url><loc>{{base}}{p}</loc><lastmod>2026-10-21</lastmod></url>" for p in SITEMAP_PATHS)
    return Response(body=f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/'
                         f'sitemap/0.9">{urls}</urlset>', content_type="application/xml")


def _png(size: int) -> Response:
    """A PNG signature followed by padding: served under a .jpg name, the way the theme's banners were."""
    return Response(body=b"\x89PNG\r\n\x1a\n" + b"\0" * (size - 8), content_type="image/png")


TEST_COPY = f"<p>{TEXT}</p>"


def _arjava() -> Site:
    login = page("Üye Girişi | Arjava | Premium Koku Difüzörleri ve Ev Kokuları",
                 f"<h2>Giriş</h2><form><input name='email'><button>Giriş</button></form><p>{TEXT}</p>"
                 '<img src="#" alt="">'  # a theme's empty image placeholder: resolves to the page itself"
                 '<a href="/UyeOl">Üye ol</a>', description="Arjava hesabınıza giriş yapın.")
    return Site({
        # The first Disallow comes before any User-agent line, so RFC 9309 ties it to no group: it is ignored.
        "/robots.txt": robots("Disallow: /cdn-cgi/\n\nUser-agent: *\nDisallow: /checkout\n\n"
                              "Sitemap: {base}/sitemap.xml\n"),
        "/sitemap.xml": _sitemap(),
        "/llms.txt": Response(body="Arjava – LLM Guidance File\n\n- [Difüzörler]({base}/difuzorler): koku difüzörleri\n",
                              content_type="text/plain; charset=utf-8"),
        "/difuzorler": Response(301, "", headers={"location": "/difuzor"}),
        "/": page(SITE_TITLE, HOME_BODY, head=HOME_HEAD,
                  description="Arjava premium koku difüzörleri ve ev kokuları ile evinize kalıcı koku."),
        # The English version: listed by hreflang and indexable, with an empty title and description.
        "/en": page("", f"<p>{TEXT}</p>", description="",
                    head='<link rel="alternate" hreflang="tr" href="{base}/"><link rel="alternate" hreflang="en" href="{base}/en">'
                         + BROKEN_ORGANIZATION),  # the template prints the same broken block on the language version
        "/difuzor": category("Difüzörler", {f"arjava-koku-difuzoru-{c}": f"Arjava Koku Difüzörü {label}"
                                            for c, label in PRODUCTS.items()}),
        "/kokular": category("Kokular", {slug: label for slug, label in CARTRIDGES.items()}),
        **{f"/arjava-koku-difuzoru-{c}": product(f"Arjava Koku Difüzörü {label}", "1.299,00") for c, label in PRODUCTS.items()},
        **{f"/{slug}": product(f"{label} Koku Kartuşu 40 ml", "349,00") for slug, label in CARTRIDGES.items()},
        "/sikca-sorulan-sorular": page("Sıkça Sorulan Sorular | Arjava", f"<h2>Sorular</h2><p>{filler('sss', 200)}</p>"),
        "/house-of-arjava": page("House of Arjava", f"<p>{filler('house', 160)}</p>", description="Kısa."),
        "/iletisim.aspx": legal("İletişim | Arjava", "iletisim", 60),
        "/kvkk": legal("KVKK | Arjava", "kvkk"),
        "/mesafeli-satis-sozlesmesi": legal(None, "mesafeli"),
        "/teslimat-ve-iade": legal(None, "teslimat"),
        "/gizlilik-ve-cerez-politikasi": legal(None, "gizlilik", 900),
        "/cdn-cgi/l/email-protection": Response(404, "<html><title>404</title></html>"),
        # Account pages: the same page at two addresses, and redirects to the login page when signed out.
        "/UyeGiris": login,
        "/UyeGiris.aspx": login,
        "/Hesabim": Response(302, "", headers={"location": "/UyeGiris?ReturnUrl=%2fHesabim"}),
        "/Hesabim.aspx": Response(302, "", headers={"location": "/UyeGiris?ReturnUrl=%2fHesabim.aspx"}),
        "/UyeOl": page("Üye Ol | Arjava", "<h2>Üye Ol</h2><p>{{IsValidUyeOlSifreStrengthShowMessage}}</p>"
                                          f"<p>Şifreniz en az {{{{n}}}} karakter olmalı.</p><p>{TEXT}</p>"),
        "/checkout": page("Ödeme | Arjava", "<p>Sepet</p>", robots_meta="noindex, nofollow"),
        # Draft pages the theme left published: listed only in the sitemap, empty titles, copies of each other.
        "/test-marka": page("", TEST_COPY + "<p>Marka testi.</p>"),
        "/arjava-2": page(None, TEST_COPY),
        "/arjava-3": page(None, TEST_COPY),
        "/test-22222": page(None, "<p>Deneme sayfası içeriği.</p>"),
        "/test-sayfaaaa": page(None, "<p>Deneme sayfası içeriği.</p>"),
        "/sss-test": page(None, "<p>SSS deneme.</p>"),  # the draft word last in the slug (seen live)
        # Media: banners are PNG files under .jpg names, about 2 MB each; the promotional video is about 10 MB.
        "/uploads/banner1.jpg": _png(2_000_000),
        "/uploads/banner2.jpg": _png(1_700_000),
        "/uploads/hero.jpg": _png(210_000),
        "/uploads/logo.png": _png(4_000),
        "/uploads/og.jpg": Response(301, "", headers={"location": "/uploads/og-200.png"}),
        "/uploads/og-200.png": _png(3_600),
        "/uploads/promo.mp4": Response(body=b"\0" * 10_334_412, content_type="video/mp4"),
        **{f"/uploads/{c}.jpg": _png(60_000) for c in PRODUCTS},
    })


ARJAVA_SCENARIOS: dict[str, Scenario] = {s.name: s for s in [
    Scenario("arjava", "A Ticimax + Cloudflare shop with every defect of the October 2026 manual audit.", _arjava,
             config={"max_pages": 60, "image_checks_max": 30}),
]}
