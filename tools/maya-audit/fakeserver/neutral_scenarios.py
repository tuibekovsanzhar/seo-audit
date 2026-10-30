"""Eight made-up sites for the brand-independent acceptance suite (tests/test_brand_neutral.py).

Each site is a common kind of website the engine's rules must hold on beyond the one shop they were tuned on
(review G, "Marka bağımsız kabul paketi"): a German shop behind Akamai, a Next.js SaaS whose menu is drawn by
JavaScript, a Turkish recipe blog with branches, a multilingual bank behind CloudFront, a WordPress dentist behind
Sucuri, a Shopify store, a small site with real leftover drafts (the positive control) and a French news site behind
Fastly. Names, domains and text are invented. Every page is healthy by default (title, description, one <h1>,
self-canonical, viewport, lang, followable links); each site then adds only the traps its tests name.

The sites are served over HTTPS (`https_pair`), with a plain-HTTP twin that redirects, as real sites are: a plain-HTTP
run would add an IDX-2 finding to every site. Registered in tests/conftest.py's run_audit_scenario too, which serves
them over plain HTTP.
"""

from __future__ import annotations

import contextlib
import json
import random
import tempfile
from datetime import datetime, timezone

from .scenarios import Scenario, robots, sitemap
from .server import FakeServer, RequestSeen, Response, Site

SELF = "<self>"  # the canonical points at the page's own address
AUTO = "<auto>"  # the description is built from the title


# -- building blocks ---------------------------------------------------------------------------------------------

# Short function words mixed into each site's filler, so the engine's stopword language guess can read the page.
GLUE = {"en": " the and of to with for is in our your", "tr": " ve bir bu için ile çok daha gibi olarak her",
        "de": " und der die das mit für ist auf ein eine", "fr": " le la les et des pour avec est dans une",
        "es": " el la los y que para con es del una"}


def filler(words: str, seed: str, n: int = 140) -> str:
    """Text of its own for each page (from a site's word list), so pages are not copies of each other."""
    rng, pool = random.Random(seed), words.split()
    sentences = []
    for start in range(0, n, 12):
        chunk = [rng.choice(pool) for _ in range(min(12, n - start))]
        sentences.append(" ".join(chunk).capitalize() + ".")
    return " ".join(sentences)


def ld(obj: dict) -> str:
    return f'<script type="application/ld+json">{json.dumps(obj, ensure_ascii=False)}</script>'


def jpeg(size: int) -> Response:
    return Response(body=b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + b"\0" * (size - 11), content_type="image/jpeg")


def png(size: int, content_type: str = "image/png") -> Response:
    return Response(body=b"\x89PNG\r\n\x1a\n" + b"\0" * (size - 8), content_type=content_type)


def webp(size: int, headers: dict | None = None) -> Response:
    body = b"RIFF" + (size - 8).to_bytes(4, "little") + b"WEBPVP8 " + b"\0" * (size - 16)
    return Response(body=body, content_type="image/webp", headers=dict(headers or {}))


def links(*pairs: tuple[str, str]) -> str:
    return " ".join(f'<a href="{href}">{text}</a>' for href, text in pairs)


class Kit:
    """One site's look: language, response headers, header and footer, word list, head extras."""

    def __init__(self, *, lang: str, brand: str, words: str, headers: dict, nav: str, footer: str, head: str = "",
                 twitter: bool = True, dir_rtl: bool = False) -> None:
        self.lang, self.brand, self.words, self.headers = lang, brand, words, headers
        self.nav, self.footer, self.head, self.twitter, self.dir_rtl = nav, footer, head, twitter, dir_rtl

    def page(self, path: str, title: str | None, body: str, *, h1: str | None = AUTO, desc: str | None = AUTO,
             canonical: str | None = SELF, head: str = "", viewport: bool = True, lang: str | None = None,
             words: int = 200, robots_meta: str | None = None, headers: dict | None = None, rtl: bool | None = None,
             site_head: bool = True) -> Response:
        full_title = f"{title} | {self.brand}" if title else (title or "")
        title_tag = f"<title>{full_title}</title>" if title is not None else ""
        if desc is AUTO:
            desc = f"{title}: {filler(self.words, 'd' + path, 12)}" if title else None
        parts = ['<meta charset="utf-8">', title_tag]
        if viewport:
            parts.append('<meta name="viewport" content="width=device-width, initial-scale=1">')
        if desc is not None:
            parts.append(f'<meta name="description" content="{desc}">')
        if canonical is not None:
            parts.append(f'<link rel="canonical" href="{{base}}{path if canonical is SELF else canonical}">')
        if robots_meta:
            parts.append(f'<meta name="robots" content="{robots_meta}">')
        if title:
            parts.append(f'<meta property="og:title" content="{title}"><meta property="og:type" content="website">'
                         f'<meta property="og:url" content="{{base}}{path}">'
                         f'<meta property="og:description" content="{desc or title}">'
                         '<meta property="og:image" content="{base}/og.jpg">')
            if self.twitter:
                parts.append('<meta name="twitter:card" content="summary">')
        parts += [self.head if site_head else "", head]
        heading = (title if h1 is AUTO else h1) or ""
        text = f"<p>{filler(self.words, path, words)}</p>" if words else ""
        direction = ' dir="rtl"' if (self.dir_rtl if rtl is None else rtl) else ""
        html = (f'<!doctype html><html lang="{lang or self.lang}"{direction}><head>{"".join(parts)}</head><body>'
                f'<header><nav>{self.nav}</nav></header><main>{f"<h1>{heading}</h1>" if heading else ""}{body}{text}'
                f'</main><footer>{self.footer}</footer></body></html>')
        return Response(body=html, headers={**self.headers, **(headers or {})})


def organization(name: str, kind: str = "Organization", **extra) -> str:
    handle = name.lower().replace(" ", "")
    return ld({"@context": "https://schema.org", "@type": kind, "name": name, "url": "{base}/", "logo": "{base}/logo.png",
               "sameAs": [f"https://www.linkedin.com/company/{handle}", f"https://www.instagram.com/{handle}"], **extra})


def faq(question: str, answer: str) -> str:
    """An FAQ section and its FAQPage block."""
    block = ld({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": question, "acceptedAnswer": {"@type": "Answer", "text": answer}}]})
    return f"<h2>{question}</h2><p>{answer}</p>{block}"


def posting(headline: str, kind: str = "BlogPosting") -> str:
    return ld({"@context": "https://schema.org", "@type": kind, "headline": headline, "image": "{base}/og.jpg",
               "datePublished": "2026-06-02", "author": {"@type": "Person", "name": "Editör"}})


def media() -> dict:
    """The logo and the share image every site's pages name."""
    return {"/logo.png": png(4_000), "/og.jpg": jpeg(60_000)}


def _robots(*disallow: str) -> Response:
    rules = "".join(f"Disallow: {d}\n" for d in disallow)
    return robots(f"User-agent: *\n{rules}\nSitemap: {{base}}/sitemap.xml\n")


@contextlib.contextmanager
def https_pair(site: Site):
    """Serve `site` over HTTPS on localhost with a throwaway CA, plus a plain-HTTP twin that redirects every request.
    Yields (https_server, http_server, ca_bundle_path); pass ca_bundle and http_port=http.port to CrawlConfig."""
    from .tls import TestCA

    with tempfile.TemporaryDirectory() as directory:
        ca = TestCA(directory)
        cert = ca.issue("site", hostnames=("localhost", "www.localhost"))
        with FakeServer(site, tls=(cert.cert, cert.key), host="localhost") as secure:
            def to_https(_site: Site, request: RequestSeen) -> Response:
                host = (request.headers.get("host") or "localhost").split(":")[0]
                return Response(301, "", {"Location": f"https://{host}:{secure.port}{request.path}"})

            with FakeServer(Site({}, fallback=to_https), host="localhost") as plain:
                yield secure, plain, ca.files.cert


# -- 1. shop-de: a German shop (Shopware-like) behind Akamai -------------------------------------------------------

DE_WORDS = ("schuh laufen wandern leder sohle größe versand lieferung rückgabe qualität komfort material pflege "
            "garantie kunde bestellung zahlung farbe saison outdoor" + GLUE["de"])
AKAMAI = {"server": "AkamaiGHost", "x-cache": "TCP_MISS from a23-45-67-89.deploy.akamaitechnologies.com (AkamaiGHost/22.1.0-1) (-)",
          "cache-control": "max-age=0, no-cache, no-store", "strict-transport-security": "max-age=31536000"}
# Akamai Bot Manager prints its sensor script and a pixel in every page; both paths answer 404 to a crawler.
AKAMAI_SENSOR = ('<script type="text/javascript" src="/akam/13/2e5f8a1b" defer></script>'
                 '<noscript><img src="/akam/13/pixel_2e5f8a1b?a=dD0xNzA" style="visibility:hidden;position:absolute"></noscript>')
DE_NAV = links(("/", "Start"), ("/kategorie/schuhe", "Schuhe"), ("/ueber-uns", "Über uns"), ("/kontakt", "Kontakt"),
               ("/blog/", "Magazin"))
DE_FOOT = links(("/impressum", "Impressum"), ("/datenschutz", "Datenschutz"), ("/agb", "AGB"), ("/versand", "Versand"),
                ("/faq", "FAQ"))
DE_SHOES = {"laufschuh-alpen": ("Laufschuh Alpen", "89,95"), "wanderschuh-berg": ("Wanderschuh Berg", "129,00"),
            "sneaker-stadt": ("Sneaker Stadt", "74,50")}


def _de_product(slug: str, kit: Kit) -> Response:
    name, price = DE_SHOES[slug]
    body = (f'<img src="/media/{slug}.jpg" alt="{name} in Braun" width="800" height="600">'
            f'<div class="product-detail-price">{price} €*<meta itemprop="price" content="{price.replace(",", ".")}"></div>'
            f'<form action="/checkout/line-item/add" method="post"><button class="btn btn-buy">In den Warenkorb</button></form>')
    return kit.page(f"/produkt/{slug}", name, body)


def _de_category(path: str, kit: Kit, order: tuple[str, ...]) -> Response:
    cards = "".join(f'<div class="card"><a href="/produkt/{s}">{DE_SHOES[s][0]}</a> <span>{DE_SHOES[s][1]} €</span>'
                    f'<p>{filler(DE_WORDS, "card" + s + path, 30)}</p></div>' for s in order)
    return kit.page(path, "Schuhe", cards, canonical="/kategorie/schuhe", words=120)


def _shop_de() -> Site:
    kit = Kit(lang="de", brand="Nordwerk Schuhe", words=DE_WORDS, headers=AKAMAI, nav=DE_NAV, footer=DE_FOOT,
              head='<link rel="stylesheet" href="/theme/9f2c/css/all.css">'
                   '<script src="/theme/9f2c/js/storefront/storefront.js" defer></script>' + AKAMAI_SENSOR)
    home_body = ('<img src="/media/hero.jpg" alt="Wanderer im Gebirge" width="1600" height="700">'
                 '<img src="/media/banner.jpg" alt="Herbstkollektion" width="1200" height="400">'
                 + links(*((f"/produkt/{s}", n) for s, (n, _) in DE_SHOES.items()))
                 + links(("/kategorie/schuhe?sortierung=preis", "Nach Preis sortieren")))
    # The shop's magazine runs on an embedded WordPress (FishPig-style): /wp-content/ assets on one page only.
    blog = kit.page("/blog/", "Magazin", '<p>Tipps rund um den Schuh.</p>',
                    head='<script src="/blog/wp-content/themes/nordwerk/main.js" defer></script>' + posting("Magazin"))
    return Site({
        "/robots.txt": _robots("/checkout/"),
        "/sitemap.xml": sitemap("/", "/kategorie/schuhe", *(f"/produkt/{s}" for s in DE_SHOES), "/ueber-uns", "/kontakt",
                                "/impressum", "/datenschutz", "/agb", "/versand", "/faq", "/blog/"),
        "/": kit.page("/", "Schuhe für jeden Weg", home_body, head=organization("Nordwerk Schuhe")),
        "/kategorie/schuhe": lambda site, req: (
            _de_category("/kategorie/schuhe?sortierung=preis", kit, ("sneaker-stadt", "laufschuh-alpen"))
            if req.query.get("sortierung") else _de_category("/kategorie/schuhe", kit, tuple(DE_SHOES))),
        **{f"/produkt/{s}": _de_product(s, kit) for s in DE_SHOES},
        "/ueber-uns": kit.page("/ueber-uns", "Über uns", "<p>Seit 1998 in Bremen.</p>"),
        "/kontakt": kit.page("/kontakt", "Kontakt", '<p><a href="tel:+494211234567">0421 1234567</a> · '
                                                    '<a href="mailto:hallo@nordwerk.invalid">E-Mail</a></p>'),
        "/impressum": kit.page("/impressum", "Impressum", "<p>Nordwerk GmbH, Bremen.</p>"),
        # The consent text links Akamai's sensor path (a 404 to a crawler): edge machinery, not a page of the site.
        "/datenschutz": kit.page("/datenschutz", "Datenschutz", '<p>Wir schützen Ihre Daten. '
                                 '<a href="/akam/13/2e5f8a1b">Bot-Schutz</a></p>'),
        "/agb": kit.page("/agb", "AGB", "<p>Allgemeine Geschäftsbedingungen.</p>"),
        "/versand": kit.page("/versand", "Versand und Rückgabe", "<p>Versand in 2 Tagen.</p>"),
        "/faq": kit.page("/faq", "Häufige Fragen", faq("Wie fallen die Schuhe aus?", "Normal, wählen Sie Ihre Größe.")),
        "/blog/": blog,
        "/akam/13/2e5f8a1b": Response(404, "", content_type="text/plain"),
        "/media/hero.jpg": jpeg(1_400_000),
        # A real PNG under a .jpg name, sent as image/png: the format the name promises is not the one served.
        "/media/banner.jpg": png(240_000),
        # A .jpg address the image service answers with WebP, saying so with Vary: Accept.
        **{f"/media/{s}.jpg": webp(60_000, {"vary": "Accept"}) for s in DE_SHOES},
        **media(),
    })


# -- 2. saas-spa: a Next.js SaaS whose pages are drawn by JavaScript ----------------------------------------------

EN_WORDS = ("team workflow dashboard report integration pipeline customer onboarding automation analytics seat "
            "invoice export security support roadmap template insight sprint" + GLUE["en"])
TR_WORDS = ("deney varyant dönüşüm ziyaretçi ölçüm sonuç örneklem hipotez kampanya sayfa buton test grup oran "
            "anlamlılık süre trafik hedef karar" + GLUE["tr"])
GTM_SPA = "GTM-K4P7Q2X"
VERCEL = {"server": "Vercel", "x-vercel-id": "fra1::iad1::7xk2p-1729500000000-abc", "x-vercel-cache": "HIT",
          "cache-control": "public, max-age=0, must-revalidate", "age": "120", "strict-transport-security": "max-age=63072000"}
SPA_ROUTES = (("/", "Flowdeck – Workflow analytics for teams"), ("/pricing", "Pricing"), ("/plan", "Team plan"),
              ("/plan-2", "Business plan"), ("/demo", "Product demo video"), ("/request-demo", "Request a demo"),
              ("/features", "Features"), ("/blog", "Blog"), ("/blog/ab-test-nedir", "A/B test nedir?"),
              ("/legal/terms", "Terms of service"), ("/about", "About us"), ("/contact", "Contact"), ("/faq", "FAQ"))
# The app draws the menu, the title and the text from the page's __NEXT_DATA__; the raw HTML holds none of them.
SPA_APP_JS = """(function(){var d=JSON.parse(document.getElementById('__NEXT_DATA__').textContent).props.pageProps;
document.title=d.title+' | Flowdeck';if(d.lang)document.documentElement.lang=d.lang;
var nav=d.nav.map(function(r){return '<a href="'+r[0]+'">'+r[1]+'</a>';}).join(' ');
document.getElementById('__next').innerHTML='<header><nav>'+nav+'</nav></header><main><h1>'+d.title+'</h1><p>'+d.text+'</p></main>';
})();"""


def _spa_page(path: str, title: str) -> Response:
    lang = "tr" if path.startswith("/blog/") and path != "/blog" else None
    props = {"title": title, "lang": lang, "text": filler(TR_WORDS if lang else EN_WORDS, path, 160),
             "nav": [[p, t.split(" – ")[0]] for p, t in SPA_ROUTES[:8]]}
    data = json.dumps({"props": {"pageProps": props}, "page": path, "buildId": "b7Qx2"}, ensure_ascii=False)
    gtm = (f"<script>(function(w,d,s,l,i){{w[l]=w[l]||[];w[l].push({{'gtm.start':new Date().getTime(),event:'gtm.js'}});"
           f"var f=d.getElementsByTagName(s)[0],j=d.createElement(s);j.async=true;"
           f"j.src='https://www.googletagmanager.com/gtm.js?id='+i;f.parentNode.insertBefore(j,f);"
           f"}})(window,document,'script','dataLayer','{GTM_SPA}');</script>")
    # The server sends the page's meta tags (and the homepage's Organization block); the title is set by the app.
    meta = (f'<meta name="description" content="{title}: {filler(EN_WORDS, "d" + path, 9)}">'
            f'<link rel="canonical" href="{{base}}{path}"><meta property="og:title" content="{title}">'
            f'<meta property="og:description" content="{title}"><meta property="og:image" content="{{base}}/og.jpg">'
            '<meta name="twitter:card" content="summary">' + (organization("Flowdeck") if path == "/" else ""))
    html = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">' + meta +
            f'<link rel="preload" as="script" href="https://www.googletagmanager.com/gtm.js?id={GTM_SPA}">{gtm}'
            '<script src="/_next/static/chunks/app-7f3c.js" defer></script>'
            '<script defer src="/_vercel/insights/script.js"></script></head>'
            f'<body><div id="__next"></div><script id="__NEXT_DATA__" type="application/json">{data}</script>'
            '</body></html>')
    return Response(body=html, headers=VERCEL)


def _saas_spa() -> Site:
    # A static print view outside the app: titled, but its template has no viewport tag.
    printable = ('<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Terms of service (print) | Flowdeck</title>'
                 '<meta name="description" content="Flowdeck terms of service: the printable version of the agreement, to keep for your records.">'
                 '<meta property="og:title" content="Terms of service"><meta property="og:description" content="Terms">'
                 '<meta property="og:image" content="{base}/og.jpg"><meta name="twitter:card" content="summary">'
                 '<link rel="canonical" href="{base}/legal/print">'
                 f'</head><body><main><h1>Terms of service</h1><p>{filler(EN_WORDS, "print", 300)}</p>'
                 # A link into Vercel's own /_vercel/ path (a 404 here): edge machinery, not a page of the site.
                 '<p><a href="/_vercel/insights/script.js">Analytics notice</a></p></main></body></html>')
    return Site({
        "/robots.txt": _robots("/app/"),
        "/sitemap.xml": sitemap(*(p for p, _ in SPA_ROUTES), "/legal/print"),
        **{p: _spa_page(p, t) for p, t in SPA_ROUTES},
        "/legal/print": Response(body=printable, headers=VERCEL),
        "/_next/static/chunks/app-7f3c.js": Response(body=SPA_APP_JS, content_type="application/javascript", headers=VERCEL),
        "/_vercel/insights/script.js": Response(404, "Not found", content_type="text/plain", headers=VERCEL),
        **media(),
    })


# -- 3. tarif-sube: a Turkish recipe blog with branches ------------------------------------------------------------

TARIF_WORDS = ("tarif mercimek çorba kek fırın un şeker tereyağı yumurta soğan pişirme dakika porsiyon lezzet "
               "sofra kahvaltı sos baharat tencere" + GLUE["tr"])
TARIF_NAV = links(("/", "Ana sayfa"), ("/blog/", "Blog"), ("/tarifler/kek", "Kek"), ("/menumuz", "Menümüz"),
                  ("/subelerimiz", "Şubelerimiz"), ("/hakkimizda", "Hakkımızda"), ("/sss", "SSS"))
TARIF_FOOT = links(("/tarifler/kek-2", "Limonlu kek"))
POSTS = {"pratik-kahvalti": "Pratik kahvaltı fikirleri", "bayram-sofrasi": "Bayram sofrası önerileri",
         "kis-corbalari": "Kış çorbaları", "firin-yemekleri": "Fırın yemekleri"}


def _blog_list(path: str, kit: Kit, slugs: tuple[str, ...], pager: bool = True) -> Response:
    items = "".join(f'<article><h2><a href="/blog/{s}/">{POSTS[s]}</a></h2><p>{filler(TARIF_WORDS, "ex" + s, 90)}</p>'
                    '</article>' for s in slugs)
    tools = links(("/blog/?filter=best", "En sevilenler"), ("/blog/?sort=yeni", "En yeniler"),
                  *((("/blog/page/2/", "Sonraki sayfa"),) if pager else ()))
    return kit.page(path, "Blog", f"<div>{tools}</div>{items}", canonical="/blog/", words=0)


def _recipe(path: str, name: str, kit: Kit, image: str | None, hero: str = "") -> Response:
    recipe = {"@context": "https://schema.org", "@type": "Recipe", "name": name, "author": {"@type": "Person", "name": "Ayşe Usta"},
              "recipeIngredient": ["2 su bardağı un", "3 yumurta"], "recipeInstructions": "Karıştırın ve pişirin.",
              **({"image": f"{{base}}{image}"} if image else {})}
    figure = f'<img src="{hero or image}" alt="{name} servis tabağında" width="1200" height="800">' if (hero or image) else ""
    return kit.page(path, name, figure, head=ld(recipe))


def _tarif_sube() -> Site:
    kit = Kit(lang="tr", brand="Lezzet Defteri", words=TARIF_WORDS, nav=TARIF_NAV, footer=TARIF_FOOT,
              headers={"server": "nginx", "cache-control": "max-age=600", "strict-transport-security": "max-age=31536000"})
    branches = ('<h2>Kadıköy</h2><p>Moda Cad. 12, İstanbul · <a href="tel:+902161234567">0216 123 45 67</a></p>'
                '<h2>Çankaya</h2><p>Tunalı Hilmi Cad. 40, Ankara · <a href="tel:+903121234567">0312 123 45 67</a></p>')
    posts = {f"/blog/{s}/": kit.page(f"/blog/{s}/", t, "<p>Afiyet olsun.</p>", head=posting(t)) for s, t in POSTS.items()}
    return Site({
        "/robots.txt": _robots("/wp-admin/"),
        "/sitemap.xml": sitemap("/", "/blog/", *posts, "/tarifler/mercimek-corbasi", "/tarifler/kek", "/tarifler/kek-2",
                                "/menumuz", "/subelerimiz", "/hakkimizda", "/sss", "/ornek-menu"),
        "/": kit.page("/", "Ev yemekleri ve tarifler", links(*((p, "Tarif") for p in posts),
                                                             ("/tarifler/mercimek-corbasi", "Mercimek çorbası")),
                      head=organization("Lezzet Defteri")),
        # The blog list: filtered, sorted and paged views all name the first page as canonical (Google's advice for
        # a filter or a sort; the list's content naturally differs from it).
        "/blog/": lambda site, req: (
            _blog_list("/blog/?filter=best", kit, ("kis-corbalari", "pratik-kahvalti")) if req.query.get("filter")
            else _blog_list("/blog/?sort=yeni", kit, ("firin-yemekleri", "kis-corbalari")) if req.query.get("sort")
            else _blog_list("/blog/", kit, ("pratik-kahvalti", "bayram-sofrasi"))),
        "/blog/page/2/": _blog_list("/blog/page/2/", kit, ("kis-corbalari", "firin-yemekleri"), pager=False),
        **posts,
        # A Recipe without an image (a required property); its 1.2 MB hero is not on a key page.
        "/tarifler/mercimek-corbasi": _recipe("/tarifler/mercimek-corbasi", "Mercimek çorbası", kit, None,
                                              hero="/img/mercimek-hero.jpg"),
        "/tarifler/kek": _recipe("/tarifler/kek", "Kakaolu kek", kit, "/img/kek.jpg"),
        # A second cake that got the slug "kek-2": titled, linked, its own recipe.
        "/tarifler/kek-2": _recipe("/tarifler/kek-2", "Limonlu kek", kit, "/img/kek-limon.jpg"),
        "/menumuz": kit.page("/menumuz", "Menümüz", "<p>Günün çorbası ve ana yemekler.</p>"),
        "/subelerimiz": kit.page("/subelerimiz", "Şubelerimiz", branches),
        "/hakkimizda": kit.page("/hakkimizda", "Hakkımızda", "<p>2009'dan beri ev yemekleri.</p>"),
        "/sss": kit.page("/sss", "Sıkça sorulan sorular", faq("Şubelerde paket servis var mı?", "Evet, iki şubede de var.")),
        # A real page whose address has "ornek": a sample weekly menu, titled, listed only in the sitemap.
        "/ornek-menu": kit.page("/ornek-menu", "Örnek haftalık menü", "<p>Pazartesiden pazara bir hafta.</p>"),
        "/img/mercimek-hero.jpg": jpeg(1_200_000),
        "/img/kek.jpg": jpeg(90_000),
        "/img/kek-limon.jpg": jpeg(85_000),
        **media(),
    })


# -- 4. bank-multi: a multilingual bank behind CloudFront ----------------------------------------------------------

BANK_EN = ("account savings card loan mortgage interest rate branch transfer deposit online secure customer "
           "service fee business personal mobile banking" + GLUE["en"])
BANK_AR = "حساب بطاقة قرض توفير فرع تحويل خدمة عميل مصرف رقمي آمن فائدة"
BANK_ES = "cuenta ahorro tarjeta préstamo hipoteca interés sucursal transferencia cliente seguro banca móvil" + GLUE["es"]
BANK_ZH = "帳戶 儲蓄 信用卡 貸款 利率 分行 轉帳 客戶 服務 網上 銀行 安全"
BANK_JA = "口座 預金 カード ローン 金利 支店 振込 お客様 サービス 安全 銀行 オンライン"
CCTLD_DE = "https://www.nordhafen-bank.de/"  # the German version lives on its own domain: never crawled
CLOUDFRONT = {"server": "nginx", "x-cache": "Miss from cloudfront", "via": "1.1 3f2a9c.cloudfront.net (CloudFront)",
              "x-amz-cf-pop": "FRA56-P4", "x-amz-cf-id": "kq3Z0x-AbCdEf==", "cache-control": "private, no-store",
              "strict-transport-security": "max-age=31536000; includeSubDomains"}
# OneTrust's banner must load synchronously in <head> (its own documentation): never "add defer".
ONETRUST = ('<script src="https://cdn.cookielaw.org/scripttemplates/otSDKStub.js" type="text/javascript" '
            'charset="UTF-8" data-domain-script="0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b"></script>'
            '<script>function OptanonWrapper(){}</script>')
BANK_NAV = links(("/en/", "Home"), ("/en/services/accounts/", "Accounts"), ("/en/cards/", "Cards"),
                 ("/en/about/", "About us"), ("/en/help/", "Help"), ("/en/contact/", "Contact"), ("/login", "Log in"))
# The footer's "English" link names "/en" without the slash, so that address is crawled as a page too.
BANK_FOOT = links(("/en", "English"), ("/ar/", "العربية"), ("/es/", "Español"), ("/zh/", "繁體中文"), ("/ja/cards/", "日本語"),
                  ("/", "International"), ("/en/legal/privacy", "Privacy"), ("/en/legal/cookies", "Cookies"))


def _alternates(*pairs: tuple[str, str]) -> str:
    return "".join(f'<link rel="alternate" hreflang="{code}" href="{href if href.startswith("http") else "{base}" + href}">'
                   for code, href in pairs)


# The home group: en-GB names "/en" (no slash) while the page itself answers at "/en/" and names that as canonical.
HOME_GROUP = _alternates(("en-GB", "/en"), ("de-DE", CCTLD_DE), ("ar-AE", "/ar/"), ("es-419", "/es/"),
                         ("zh-Hant-TW", "/zh/"), ("x-default", "/"))
# The cards group uses two wrong codes: "en-UK" (the region is GB) and "jp" (a country, not the language "ja").
CARDS_GROUP = _alternates(("en-UK", "/en/cards/"), ("jp", "/ja/cards/"), ("x-default", "/en/cards/"))


def _bank_multi() -> Site:
    kit = Kit(lang="en", brand="Nordhafen Bank", words=BANK_EN, headers=CLOUDFRONT, nav=BANK_NAV, footer=BANK_FOOT,
              head=ONETRUST)
    org = organization("Nordhafen Bank")
    en_home = kit.page("/en/", "Banking for people and business", "<p>Open an account in minutes.</p>", head=HOME_GROUP + org)

    def home(path: str, title: str, lang: str, words: str, rtl: bool = False) -> Response:
        text = f"<p>{filler(words, path, 220)}</p>"
        return kit.page(path, title, text, lang=lang, rtl=rtl, head=HOME_GROUP, words=0)

    def legal(path: str, title: str) -> Response:  # kept out of the index on purpose
        return kit.page(path, title, "<p>Policy text.</p>", robots_meta="noindex, follow")

    login = kit.page("/login", "Online banking log in", '<form action="/login" method="post"><input name="user">'
                     '<input name="pin" type="password"><button>Log in</button></form>', viewport=False)
    return Site({
        "/robots.txt": _robots("/secure/"),
        "/sitemap.xml": sitemap("/", "/en/", "/ar/", "/es/", "/zh/", "/en/services/accounts/", "/en/cards/", "/ja/cards/",
                                "/en/about/", "/en/help/", "/en/contact/", "/login", "/en/legal/privacy",
                                "/en/legal/cookies"),
        "/": kit.page("/", "Nordhafen Bank International", "<p>Choose your country and language.</p>",
                      head=HOME_GROUP + org),
        "/en/": en_home,
        "/en": en_home,  # the same page without the slash: canonical names "/en/"
        "/ar/": home("/ar/", "مصرف للأفراد والشركات", "ar", BANK_AR, rtl=True),
        "/es/": home("/es/", "Banca para personas y empresas", "es-419", BANK_ES),
        "/zh/": home("/zh/", "個人與企業銀行", "zh-Hant-TW", BANK_ZH),
        "/en/services/accounts/": kit.page("/en/services/accounts/", "Current and savings accounts", "<p>Compare accounts.</p>"),
        "/en/cards/": kit.page("/en/cards/", "Credit and debit cards", "<p>Cards for every day.</p>", head=CARDS_GROUP),
        "/ja/cards/": kit.page("/ja/cards/", "クレジットカード", f"<p>{filler(BANK_JA, 'ja', 220)}</p>", lang="ja",
                               head=CARDS_GROUP, words=0),
        "/en/about/": kit.page("/en/about/", "About Nordhafen Bank", "<p>Founded in 1952.</p>"),
        "/en/help/": kit.page("/en/help/", "Help and FAQ", faq("How do I block my card?", "In the app, under Cards.")),
        "/en/contact/": kit.page("/en/contact/", "Contact us", '<p><a href="tel:+442071234567">+44 20 7123 4567</a></p>'),
        "/login": login,
        # Legal pages kept out of the index on purpose, which the CMS lists in its sitemap anyway.
        "/en/legal/privacy": legal("/en/legal/privacy", "Privacy notice"),
        "/en/legal/cookies": legal("/en/legal/cookies", "Cookie policy"),
        **media(),
    })


# -- 5. local-wp: a WordPress dentist behind Sucuri ----------------------------------------------------------------

DIS_WORDS = ("diş beyazlatma implant kanal tedavi muayene randevu hekim ağız sağlık gülüş fırçalama diş ipi "
             "dolgu protez ortodonti çekim bakım hasta" + GLUE["tr"])
SUCURI = {"server": "Sucuri/Cloudproxy", "x-sucuri-id": "18012", "x-sucuri-cache": "HIT",
          "cache-control": "max-age=300", "strict-transport-security": "max-age=31536000"}
WP_HEAD = ('<meta name="generator" content="WordPress 6.6.2">'
           '<link rel="stylesheet" href="/wp-content/themes/dentale/style.css?ver=2.1">'
           '<script src="/wp-includes/js/jquery/jquery.min.js?ver=3.7.1" id="jquery-core-js"></script>'
           '<script src="/wp-includes/js/jquery/jquery-migrate.min.js?ver=3.4.1" id="jquery-migrate-js"></script>')
WP_NAV = links(("/", "Ana sayfa"), ("/hakkimizda/", "Hakkımızda"), ("/tedaviler/", "Tedaviler"), ("/blog/", "Blog"),
               ("/sss/", "SSS"), ("/iletisim/", "İletişim"))
WP_FOOT = links(("/iletisim", "Bize ulaşın"), ("/tedaviler/implant/", "İmplant"))
TREATMENTS = {"dis-beyazlatma": "Diş Beyazlatma", "implant": "İmplant", "kanal-tedavisi": "Kanal Tedavisi"}


def _local_wp() -> Site:
    kit = Kit(lang="tr", brand="Parlak Diş Kliniği", words=DIS_WORDS, headers=SUCURI, nav=WP_NAV, footer=WP_FOOT,
              head=WP_HEAD, twitter=False)

    def figure(slug: str, name: str) -> str:  # the theme prints the same text as alt and title
        return f'<img src="/wp-content/uploads/2026/05/{slug}.jpg" alt="{name}" title="{name}" width="900" height="600">'

    # A Dentist (LocalBusiness) block without its address.
    dentist = organization("Parlak Diş Kliniği", "Dentist", telephone="+90 232 123 45 67",
                           image="{base}/wp-content/uploads/2026/05/klinik.jpg")
    contact = kit.page("/iletisim/", "İletişim", '<p><a href="tel:+902321234567">0232 123 45 67</a></p>', canonical=None)
    return Site({
        "/robots.txt": _robots("/wp-admin/"),
        "/sitemap.xml": sitemap("/", "/hakkimizda/", "/tedaviler/", *(f"/tedaviler/{s}/" for s in TREATMENTS),
                                "/blog/", "/blog/dis-fircalama-rehberi/", "/sss/", "/iletisim/"),
        "/": kit.page("/", "İzmir'de diş kliniği", figure("klinik", "Klinik Bekleme Salonu"), head=dentist),
        "/hakkimizda/": kit.page("/hakkimizda/", "Hakkımızda", figure("ekip", "Hekim Kadromuz")),
        "/tedaviler/": kit.page("/tedaviler/", "Tedaviler", links(*((f"/tedaviler/{s}/", n) for s, n in TREATMENTS.items()))),
        **{f"/tedaviler/{s}/": kit.page(f"/tedaviler/{s}/", n, figure(s, n)) for s, n in TREATMENTS.items()},
        "/blog/": kit.page("/blog/", "Blog", links(("/blog/dis-fircalama-rehberi/", "Diş fırçalama rehberi"))),
        "/blog/dis-fircalama-rehberi/": kit.page("/blog/dis-fircalama-rehberi/", "Diş fırçalama rehberi", "<p>Günde iki kez.</p>",
                                                 head=posting("Diş fırçalama rehberi")),
        "/sss/": kit.page("/sss/", "Sıkça sorulan sorular", faq("Beyazlatma kalıcı mı?", "Bakıma bağlı olarak yıllarca sürer.")),
        # The same contact page at two addresses, with and without the trailing slash, neither naming a canonical.
        "/iletisim/": contact,
        "/iletisim": contact,
        **{f"/wp-content/uploads/2026/05/{s}.jpg": jpeg(70_000) for s in (*TREATMENTS, "klinik", "ekip")},
        **media(),
    })


# -- 6. shopify: a Shopify store ----------------------------------------------------------------------------------

SHOP_WORDS = ("cotton tee organic fit relaxed fabric wash colour size shipping returns stitch soft everyday "
              "layer crew neck sleeve dye" + GLUE["en"])
SHOPIFY = {"powered-by": "Shopify", "x-shopid": "58213477", "x-shardid": "214", "server-timing": "processing;dur=48",
           "cache-control": "private, max-age=0", "strict-transport-security": "max-age=7889238"}
GA4, GTM_SHOP = "G-7QK2M9XW1L", "GTM-P8R3T5V"
# The Google & YouTube channel adds gtag with the store's GA4 property; the merchant added their own GTM container.
SHOP_HEAD = ('<script src="https://cdn.shopify.com/s/files/1/0582/1347/7/t/3/assets/theme.js?v=1712345678" defer></script>'
             f'<script async src="https://www.googletagmanager.com/gtag/js?id={GA4}"></script>'
             f"<script>window.dataLayer=window.dataLayer||[];function gtag(){{dataLayer.push(arguments);}}"
             f"gtag('js',new Date());gtag('config','{GA4}');</script>"
             f"<script>(function(w,d,s,l,i){{w[l]=w[l]||[];w[l].push({{'gtm.start':new Date().getTime(),event:'gtm.js'}});"
             f"var f=d.getElementsByTagName(s)[0],j=d.createElement(s);j.async=true;"
             f"j.src='https://www.googletagmanager.com/gtm.js?id='+i;f.parentNode.insertBefore(j,f);"
             f"}})(window,document,'script','dataLayer','{GTM_SHOP}');</script>")
SHOP_NAV = links(("/", "Home"), ("/collections/tisortler", "Tees"), ("/pages/about-us", "About"),
                 ("/pages/faq", "FAQ"), ("/pages/contact", "Contact"))
SHOP_FOOT = links(("/collections/tisortler?sort_by=price-ascending", "Price: low to high"),
                  ("/blogs/news/how-we-dye", "Journal"))
TEES = {"tisort-1": ("Organic Tee White", "28.00"), "tisort-2": ("Organic Tee Sand", "32.00"),
        "tisort-3": ("Heavyweight Tee", "38.00")}


def _shop_product(slug: str, kit: Kit) -> Response:
    name, price = TEES[slug]
    image = f"/cdn/shop/files/{slug}.jpg?v=1712345678&width=800"
    product = {"@context": "https://schema.org", "@type": "Product", "name": name, "image": f"{{base}}{image}",
               "brand": {"@type": "Brand", "name": "Kettle Cove"}}
    if slug != "tisort-3":  # the third product's block has no offers (a required property)
        product["offers"] = {"@type": "Offer", "price": price, "priceCurrency": "USD", "availability": "https://schema.org/InStock"}
    body = (f'<img src="{image}" alt="{name} in white, front" width="800" height="1000"><p class="price">${price}</p>'
            f'<form method="post" action="/cart/add"><button type="submit" name="add">Add to bag</button></form>')
    return kit.page(f"/products/{slug}", name, body, head=ld(product))


def _shop_collection(path: str, kit: Kit, order: tuple[str, ...]) -> Response:
    cards = "".join(f'<div class="card"><a href="/products/{s}">{TEES[s][0]}</a> <span>${TEES[s][1]}</span>'
                    f'<p>{filler(SHOP_WORDS, "c" + s + path, 30)}</p></div>' for s in order)
    more = links(("/collections/tisortler?page=2", "Next page")) if path == "/collections/tisortler" else ""
    return kit.page(path, "Tees", cards + more, canonical="/collections/tisortler", words=120)


def _shopify() -> Site:
    kit = Kit(lang="en", brand="Kettle Cove", words=SHOP_WORDS, headers=SHOPIFY, nav=SHOP_NAV, footer=SHOP_FOOT,
              head=SHOP_HEAD)

    def collection(site: Site, req: RequestSeen) -> Response:
        if req.query.get("sort_by"):
            return _shop_collection("/collections/tisortler?sort_by=price-ascending", kit, ("tisort-1", "tisort-2"))
        if req.query.get("page"):
            return _shop_collection("/collections/tisortler?page=2", kit, ("tisort-3",))
        return _shop_collection("/collections/tisortler", kit, ("tisort-2", "tisort-1"))

    return Site({
        "/robots.txt": _robots("/cart", "/checkout"),
        "/sitemap.xml": sitemap("/", "/collections/tisortler", *(f"/products/{s}" for s in TEES), "/pages/about-us",
                                "/pages/faq", "/pages/contact", "/blogs/news/how-we-dye"),
        "/": kit.page("/", "Organic cotton tees", links(*((f"/products/{s}", n) for s, (n, _) in TEES.items())),
                      head=organization("Kettle Cove")),
        "/collections/tisortler": collection,
        **{f"/products/{s}": _shop_product(s, kit) for s in TEES},
        "/pages/about-us": kit.page("/pages/about-us", "About us", "<p>Made in small batches.</p>"),
        "/pages/faq": kit.page("/pages/faq", "FAQ", faq("How do the tees fit?", "True to size, with a relaxed cut.")),
        "/pages/contact": kit.page("/pages/contact", "Contact", '<p><a href="mailto:hi@kettlecove.invalid">Email us</a></p>'),
        "/blogs/news/how-we-dye": kit.page("/blogs/news/how-we-dye", "How we dye our tees",
                                            '<p>Published <time datetime="2026-06-02">June 2, 2026</time>. Plant dyes only.</p>',
                                            head=posting("How we dye our tees")),
        # The image CDN answers a .jpg address with WebP (the URL carries its width parameter).
        **{f"/cdn/shop/files/{s}.jpg": webp(70_000) for s in TEES},
        **media(),
    })


# -- 7. draft-real: a small site with real leftover drafts (the positive control) --------------------------------

ATOLYE_WORDS = ("tasarım marka logo kurumsal kimlik web sitesi ambalaj baskı proje müşteri süreç fikir renk "
                "tipografi sunum katalog afiş ekip" + GLUE["tr"])
GTM_DRAFT = "GTM-ABC1234"
GTM_LOADER = (f"<script>(function(w,d,s,l,i){{w[l]=w[l]||[];w[l].push({{'gtm.start':new Date().getTime(),event:'gtm.js'}});"
              f"var f=d.getElementsByTagName(s)[0],j=d.createElement(s);j.async=true;"
              f"j.src='https://www.googletagmanager.com/gtm.js?id='+i;f.parentNode.insertBefore(j,f);"
              f"}})(window,document,'script','dataLayer','{GTM_DRAFT}');</script>")
DRAFT_NAV = links(("/", "Ana sayfa"), ("/hakkimizda", "Hakkımızda"), ("/hizmetler", "Hizmetler"),
                  ("/projeler", "Projeler"), ("/iletisim", "İletişim"))
DRAFT_FOOT = links(("/kampanya", "Kampanya"), ("/sss", "SSS"))
ABOUT_TEXT = filler(ATOLYE_WORDS, "hakkimizda", 160)


def _draft_real() -> Site:
    # The theme and a plugin both print the same GTM container: the tag loads twice.
    kit = Kit(lang="tr", brand="Mavi Atölye", words=ATOLYE_WORDS, nav=DRAFT_NAV, footer=DRAFT_FOOT,
              head=GTM_LOADER + GTM_LOADER + '<script src="/wp-content/themes/mavi/app.js" defer></script>',
              headers={"server": "nginx", "cache-control": "max-age=300", "strict-transport-security": "max-age=31536000"})
    about = f"<p>{ABOUT_TEXT}</p>"
    return Site({
        "/robots.txt": _robots("/wp-admin/"),
        "/sitemap.xml": sitemap("/", "/hakkimizda", "/hizmetler", "/projeler", "/iletisim", "/sss", "/kampanya",
                                "/taslak", "/test", "/hakkimizda-2"),
        "/": kit.page("/", "Marka ve web tasarımı", '<img src="/uploads/IMG_2034.jpg" alt="IMG_2034" width="1200" height="800">',
                      head=organization("Mavi Atölye")),
        "/hakkimizda": kit.page("/hakkimizda", "Hakkımızda", about, words=0),
        "/hizmetler": kit.page("/hizmetler", "Hizmetler", "<p>Logo, kimlik ve web.</p>"),
        # The projects page loads a gallery script over plain http: mixed content on an https page.
        "/projeler": kit.page("/projeler", "Projeler", '<div class="galeri"></div>',
                              head='<script src="http://cdn.galerikit.invalid/v2/galeri.min.js" defer></script>'),
        "/iletisim": kit.page("/iletisim", "İletişim", '<p><a href="tel:+902121234567">0212 123 45 67</a></p>'),
        "/sss": kit.page("/sss", "Sıkça sorulan sorular", faq("Süreç ne kadar sürer?", "Ortalama üç hafta sürer.")),
        # A real page that lost its title in a theme update: linked from the footer, not a draft.
        "/kampanya": kit.page("/kampanya", None, "<h2>Ekim kampanyası</h2>", h1=None, desc=None, canonical=SELF),
        # Drafts left published, listed only in the sitemap: Elementor's default title, no title, and a copy.
        "/taslak": kit.page("/taslak", None, "<p>Yeni sayfa.</p>", h1=None, desc=None,
                            head="<title>Başlıksız – Mavi Atölye</title>"),
        "/test": kit.page("/test", None, "<p>deneme deneme</p>", h1=None, desc=None),
        "/hakkimizda-2": kit.page("/hakkimizda-2", None, about, h1="Hakkımızda", desc=None, words=0),
        "/uploads/IMG_2034.jpg": jpeg(120_000),
        **media(),
    })


# -- 8. news-video: a French news site behind Fastly --------------------------------------------------------------

FR_WORDS = ("ville conseil municipal transport tramway habitants budget quartier école météo pluie rivière "
            "crue pompiers mairie projet travaux élus vote" + GLUE["fr"])
FASTLY = {"server": "Varnish", "via": "1.1 varnish", "x-served-by": "cache-fra-etou8220123-FRA, cache-par-lfpg1960045-PAR",
          "x-cache": "MISS, HIT", "x-cache-hits": "0, 3", "cache-control": "no-cache", "age": "41",
          "strict-transport-security": "max-age=31536000"}
ES_NEWS = "noticias ciudad semana tranvía presupuesto ayuntamiento vecinos lluvia río obras escuela" + GLUE["es"]
NEWS_NAV = links(("/", "À la une"), ("/actualites/", "Actualités"), ("/videos/", "Vidéos"), ("/a-propos", "À propos"),
                 ("/contact", "Contact"))
NEWS_FOOT = links(("/mentions-legales", "Mentions légales"), ("/es/", "Español"))


def _news_article(path: str, title: str, published: str | None, label: str, kit: Kit, extra: str = "",
                  head: str = "") -> Response:
    """NewsArticle without dates in JSON-LD: the date is only in <time datetime> and the French byline, or (published
    None) only in the byline's French words."""
    article = {"@context": "https://schema.org", "@type": "NewsArticle", "headline": title,
               "author": {"@type": "Person", "name": "Claire Martin"}, "image": "{base}/img/une.jpg"}
    when = f'<time datetime="{published}">{label}</time>' if published else label
    byline = f'<p class="byline">Publié le {when} par Claire Martin</p>'
    return kit.page(path, title, byline + extra, head=ld(article) + head, words=220)


def _video(name: str, uploaded: str) -> str:
    return ld({"@context": "https://schema.org", "@type": "VideoObject", "name": name, "description": name,
               "thumbnailUrl": "{base}/img/une.jpg", "uploadDate": uploaded, "contentUrl": "{base}/media/clip.mp4"})


def _news_video() -> Site:
    today = datetime.now(timezone.utc).date().isoformat()  # the audit day as the engine counts it (UTC)
    kit = Kit(lang="fr", brand="Courrier du Rhône", words=FR_WORDS, headers=FASTLY, nav=NEWS_NAV, footer=NEWS_FOOT)
    clip = '<video src="/media/clip.mp4" controls preload="none" width="640" height="360"></video>'
    return Site({
        "/robots.txt": _robots("/admin/"),
        "/sitemap.xml": sitemap("/", "/actualites/", "/videos/", "/actualites/tramway-ligne-c", "/actualites/budget-2026",
                                "/videos/crue-de-la-saone", "/videos/conseil-municipal", "/a-propos", "/contact",
                                "/mentions-legales", "/es/"),
        "/": kit.page("/", "L'actualité de Lyon et du Rhône", links(("/actualites/tramway-ligne-c", "Tramway"),
                      ("/videos/crue-de-la-saone", "Crue")), head=organization("Courrier du Rhône")),
        "/actualites/": kit.page("/actualites/", "Actualités", links(("/actualites/tramway-ligne-c", "Tramway"),
                                 ("/actualites/budget-2026", "Budget"))),
        "/videos/": kit.page("/videos/", "Vidéos", links(("/videos/crue-de-la-saone", "Crue"),
                             ("/videos/conseil-municipal", "Conseil"))),
        "/actualites/tramway-ligne-c": _news_article("/actualites/tramway-ligne-c", "La ligne C du tramway prolongée",
                                                     "2026-03-03", "3 mars 2026", kit),
        "/actualites/budget-2026": _news_article("/actualites/budget-2026", "Le budget 2026 voté en conseil",
                                                 None, "14 février 2026", kit),
        # Published today, with a real name: uploadDate is the audit day because the video is new.
        "/videos/crue-de-la-saone": _news_article("/videos/crue-de-la-saone", "Crue de la Saône en images",
                                                  today, "aujourd'hui", kit, clip,
                                                  _video("Crue de la Saône : les images du matin", today)),
        # A theme's default VideoObject: named just "Video".
        "/videos/conseil-municipal": _news_article("/videos/conseil-municipal", "Le conseil municipal en vidéo",
                                                   "2026-09-12", "12 septembre 2026", kit, clip,
                                                   _video("Video", "2026-09-12")),
        "/a-propos": kit.page("/a-propos", "À propos", "<p>Quotidien régional fondé en 1946.</p>"),
        "/contact": kit.page("/contact", "Contact", '<p><a href="mailto:redaction@courrier-rhone.invalid">Rédaction</a></p>'),
        "/mentions-legales": kit.page("/mentions-legales", "Mentions légales", "<p>Éditeur : SAS Courrier du Rhône.</p>"),
        "/es/": kit.page("/es/", "Noticias de Lyon en español", f"<p>{filler(ES_NEWS, 'es', 200)}</p>", lang="es",
                         words=0),
        "/img/une.jpg": jpeg(80_000),
        "/media/clip.mp4": Response(body=b"\0" * 2_000_000, content_type="video/mp4"),
        **media(),
    })


NEUTRAL_SCENARIOS: dict[str, Scenario] = {s.name: s for s in [
    Scenario("shop-de", "German shop (Shopware-like) behind Akamai, with an embedded WordPress magazine.", _shop_de),
    Scenario("saas-spa", "Next.js SaaS: menu, titles and text drawn by JavaScript; Vercel.", _saas_spa),
    Scenario("tarif-sube", "Turkish recipe blog with branches; filtered, sorted and paged blog lists.", _tarif_sube),
    Scenario("bank-multi", "Multilingual bank behind CloudFront: hreflang groups, a ccTLD version, OneTrust.", _bank_multi),
    Scenario("local-wp", "WordPress dentist behind Sucuri.", _local_wp),
    Scenario("shopify", "Shopify store: image CDN, sort and page parameters, gtag beside GTM.", _shopify),
    Scenario("draft-real", "Small agency site with real drafts left published (positive control).", _draft_real),
    Scenario("news-video", "French news site behind Fastly with VideoObject and NewsArticle pages.", _news_video),
]}
for _scenario in NEUTRAL_SCENARIOS.values():
    _scenario.config.update({"max_pages": 40, "image_checks_max": 30, "check_external_links": False})
