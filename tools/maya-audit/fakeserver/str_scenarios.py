"""Scripted websites for the STR checks (content structure and semantics)."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from email.utils import format_datetime

from .scenarios import Scenario, robots
from .server import RequestSeen, Response, Site

FAST_STR = {"request_delay_s": 0.0, "request_timeout_s": 5.0, "robots_sample_interval_s": 0.05,
            "probe_retry_cooldown_s": 0.0, "refetch_delay_s": 0.0, "prf_round_gap_s": 0.0, "render_enabled": False}

EN = ("Our team builds tools that help you understand how your customers use the product and where they get stuck. "
      "You can see every step of the journey, and we will show you what to fix first. ")
TR = ("Bu ürün, ekibinizin müşterilerini daha iyi anlaması için tasarlandı ve her gün daha fazla şirket tarafından "
      "kullanılıyor. Ama bu kadar değil, çok daha fazlası var ve bunu sizin için bir rehber olarak hazırladık. ")


def en(sentences: int = 4) -> str:
    return EN * sentences


def tr(sentences: int = 4) -> str:
    return TR * sentences


def ld(*objects: dict) -> str:
    return "".join(f'<script type="application/ld+json">{json.dumps(o)}</script>' for o in objects)


def human(d: date) -> str:
    return f"{d:%B} {d.day}, {d.year}"


def doc(title: str | None, body: str, head: str = "", lang: str | None = "en", og: bool = True,
        description: bool = True, og_image: str = "/og/home.png", headers: dict | None = None) -> Response:
    lang_attr = f' lang="{lang}"' if lang else ""
    tags = ""
    if og:
        tags += (f'<meta property="og:title" content="{title or "Page"}">'
                 '<meta property="og:description" content="A page about product analytics.">'
                 f'<meta property="og:image" content="{og_image}">')
    if description:
        tags += '<meta name="description" content="A page about product analytics.">'
    title_tag = f"<title>{title}</title>" if title is not None else ""
    return Response(body=f"<!doctype html><html{lang_attr}><head>{title_tag}{tags}{head}</head><body>{body}</body></html>",
                    headers=dict(headers or {}))


def nav(*paths: str) -> str:
    return "<nav>" + " ".join(f'<a href="{p}">{p}</a>' for p in paths) + "</nav>"


# -- STR-1 / STR-2 / STR-9 (lang) / STR-10 ------------------------------------------

PAGES_NAV = nav("/", "/features", "/no-title", "/dup-a", "/dup-b", "/dup-canonical", "/noindex-copy", "/welcome",
                "/brand", "/no-h1", "/long", "/multi-h1", "/faq", "/csr-shell", "/no-lang")


def pages_site() -> Site:
    def main(h1: str | None, text: str = en(), extra: str = "") -> str:
        return PAGES_NAV + "<main>" + (f"<h1>{h1}</h1>" if h1 else "") + extra + f"<p>{text}</p></main>"

    return Site({
        "/robots.txt": robots("User-agent: *\nAllow: /\n"),
        "/": doc("Acme Analytics", main("Acme Analytics"), head='<meta property="og:site_name" content="Acme Analytics">'),
        "/og/home.png": Response(body="PNG", content_type="image/png"),
        "/features": doc("Features | Acme", main("Features"), og_image="/og/missing.png"),
        "/no-title": doc(None, main("Untitled page"), description=False),
        "/dup-a": doc("Product analytics | Acme", main("Funnels", en(3))),
        "/dup-b": doc("Product analytics | Acme", main("Retention", EN + "Retention cohorts show who comes back.")),
        "/dup-canonical": doc("Product analytics | Acme", main("Funnels copy"), head='<link rel="canonical" href="/dup-a">'),
        "/noindex-copy": doc("Product analytics | Acme", main("Print version"), head='<meta name="robots" content="noindex">'),
        "/welcome": doc("Home", main("Welcome")),
        "/brand": doc("Acme Analytics", main("About the brand")),
        "/no-h1": doc("No heading | Acme", PAGES_NAV + f"<main><h2>Section</h2><p>{en()}</p></main>", og=False),
        "/long": doc("Long guide | Acme", main("The long guide", en(28))),
        "/multi-h1": doc("Two headings | Acme", main("First", extra="<h1>Second</h1>")),
        "/faq": doc("FAQ | Acme", main("Questions", extra="<h2>How much does it cost?</h2><h2>Can I cancel?</h2>"
                                                          "<h2>Support</h2><h3>Is there a free trial?</h3>")),
        "/csr-shell": doc("Dashboard | Acme", PAGES_NAV + '<div id="root"></div><script src="/app.js"></script>'),
        "/app.js": Response(body="document.getElementById('root').innerHTML='<h1>App</h1>';",
                            content_type="application/javascript"),
        "/no-lang": doc("No language | Acme", main("No language"), lang=None),
    })


# -- STR-3 / STR-4 / STR-6 ------------------------------------------------------

def structured_site() -> Site:
    today = date.today()
    modified, stale_lastmod = today - timedelta(days=100), today - timedelta(days=200)
    future = today.replace(year=today.year + 5)
    launch_schema, launch_shown = today - timedelta(days=250), today - timedelta(days=190)
    links = ["/", "/products/pro-widget", "/products/euro-widget", "/products/ok-widget", "/products/sold-widget",
             "/products/tr-widget", "/products/rated-widget", "/products/renamed", "/products/micro",
             "/products/no-price-shown", "/products/incomplete", "/products/broken-json", "/pricing", "/blog/launch",
             "/blog/byline", "/blog/undated", "/blog/tr-yazi", "/blog/stale", "/blog/future", "/testimonials"]
    menu = nav(*links)

    def product(name, price, currency="USD", availability="InStock", **extra):
        return {"@context": "https://schema.org", "@type": "Product", "name": name,
                "offers": {"@type": "Offer", "price": price, "priceCurrency": currency,
                           "availability": f"https://schema.org/{availability}"}, **extra}

    def page(title, body, schema=(), lang="en", headers=None, raw_head=""):
        return doc(title, menu + f"<main>{body}</main>", head=ld(*schema) + raw_head, lang=lang, headers=headers)

    def stale(site: Site, request: RequestSeen) -> Response:
        # Last-Modified generated at request time: must be recognized as such and not compared.
        now = format_datetime(datetime.now(timezone.utc), usegmt=True)
        return page("Stale post | Acme", f"<h1>Stale post</h1><p>Updated {human(modified)}</p><p>{en()}</p>",
                    [{"@context": "https://schema.org", "@type": "BlogPosting", "headline": "Stale post",
                      "datePublished": (modified - timedelta(days=10)).isoformat(), "dateModified": modified.isoformat()}],
                    headers={"Last-Modified": now})

    sitemap_xml = ('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                   f"<url><loc>{{base}}/blog/stale</loc><lastmod>{stale_lastmod.isoformat()}</lastmod></url>"
                   "<url><loc>{base}/blog/undated</loc></url></urlset>")
    return Site({
        "/robots.txt": robots("User-agent: *\nAllow: /\nSitemap: {base}/sitemap.xml\n"),
        "/sitemap.xml": Response(body=sitemap_xml, content_type="application/xml"),
        "/og/home.png": Response(body="PNG", content_type="image/png"),
        "/": page("Shop | Acme Store", f"<h1>Acme Store</h1><p>{en()}</p>",
                  [{"@context": "https://schema.org", "@type": "WebSite", "name": "Acme Store", "url": "{base}/"}]),
        "/products/pro-widget": page("Pro Widget | Acme Store",
                                     f"<h1>Pro Widget</h1><p>Only $49 today. In stock.</p><p>{en()}</p>",
                                     [product("Pro Widget", "59.00")]),
        "/products/euro-widget": page("Euro Widget | Acme Store",
                                      f"<h1>Euro Widget</h1><p>Price: $49. In stock.</p><p>{en()}</p>",
                                      [product("Euro Widget", "49", "EUR")]),
        "/products/ok-widget": page("OK Widget | Acme Store",
                                    f"<h1>OK Widget</h1><p>$19.00 · In stock · Rated 4.5/5 by 20 buyers</p><p>{en()}</p>",
                                    [product("OK Widget", 19, aggregateRating={"@type": "AggregateRating", "ratingValue": 4.5,
                                                                              "ratingCount": 20})]),
        "/products/sold-widget": page("Sold Widget | Acme Store",
                                      f"<h1>Sold Widget</h1><p>$15. Sold out.</p><p>{en()}</p>",
                                      [product("Sold Widget", 15)]),
        "/products/tr-widget": page("Türk Widget | Acme", f"<h1>Türk Widget</h1><p>₺1.299,00 — Tükendi</p><p>{tr()}</p>",
                                    [product("Türk Widget", "1299.00", "TRY")], lang="tr"),
        "/products/rated-widget": page("Rated Widget | Acme Store",
                                       f"<h1>Rated Widget</h1><p>$25. In stock. Customers rate it 4.2/5.</p><p>{en()}</p>",
                                       [product("Rated Widget", 25, aggregateRating={"@type": "AggregateRating",
                                                                                   "ratingValue": "4.8", "ratingCount": 31})]),
        "/products/renamed": page("Nova Speaker | Acme Store", f"<h1>Nova Speaker</h1><p>$80. In stock.</p><p>{en()}</p>",
                                  [product("Legacy Gadget 3000", 80)]),
        "/products/micro": page("Micro Lamp | Acme Store",
                                '<div itemscope itemtype="https://schema.org/Product"><h1 itemprop="name">Micro Lamp</h1>'
                                '<div itemprop="offers" itemscope itemtype="https://schema.org/Offer">'
                                '<meta itemprop="price" content="30"><meta itemprop="priceCurrency" content="USD">'
                                f'<span>$25</span></div></div><p>{en()}</p>'),
        "/products/no-price-shown": page("Hidden Price | Acme Store", f"<h1>Hidden Price</h1><p>{en()}</p>",
                                         [product("Hidden Price", 99)]),
        "/products/incomplete": page("Bare Thing | Acme Store", f"<h1>Bare Thing</h1><p>{en()}</p>",
                                     [{"@context": "https://schema.org", "@type": "Product", "name": "Bare Thing"}]),
        "/products/broken-json": page("Broken | Acme Store", f"<h1>Broken</h1><p>$10</p><p>{en()}</p>",
                                      raw_head='<script type="application/ld+json">{"@type": "Product", "name": "Broken",}</script>'),
        "/pricing": page("Pricing | Acme Store", f"<h1>Pricing</h1><p>Plans from $9.</p><p>{en()}</p>"),
        # Published and updated dates both differ from the markup (STR-4); STR-6 must not report the same dates again.
        "/blog/launch": page("Launch | Acme", f"<h1>Launch</h1><p>By Jane Doe · Published {human(launch_shown)} · "
                                              f"Updated {human(today - timedelta(days=10))}</p><p>{en()}</p>",
                             [{"@context": "https://schema.org", "@type": "BlogPosting", "headline": "Launch",
                               "author": {"@type": "Person", "name": "Jane Doe"},
                               "datePublished": launch_schema.isoformat(),
                               "dateModified": (today - timedelta(days=150)).isoformat()}]),
        "/blog/byline": page("Byline | Acme", f"<h1>Byline</h1><p>By Maria Garcia · Published {human(launch_shown)}</p><p>{en()}</p>",
                             [{"@context": "https://schema.org", "@type": "BlogPosting", "headline": "Byline",
                               "author": {"@type": "Person", "name": "John Smith"},
                               "datePublished": launch_shown.isoformat()}]),
        "/blog/undated": page("Undated | Acme", f"<h1>Undated</h1><p>{en()}</p>"),
        # Only unlabelled dates on the page (customer testimonials): nothing to compare a schema date to.
        "/testimonials": page("Testimonials | Acme", f"<h1>What customers say</h1><p>Great service. 06.06.2026</p>"
                              f"<p>Recommended. 30.05.2026</p><p>{en()}</p>",
                              [{"@context": "https://schema.org", "@type": "WebPage", "name": "Testimonials",
                                "datePublished": "2018-05-09T12:43:26+03:00",
                                "dateModified": (today - timedelta(days=2)).isoformat()}]),
        "/blog/tr-yazi": page("Yazı | Acme", f"<h1>Yazı</h1><p>{tr()}</p>", lang="tr"),
        "/blog/stale": stale,
        "/blog/future": page("Future | Acme", f"<h1>Future</h1><p>Published {human(future)}</p><p>{en()}</p>",
                             [{"@context": "https://schema.org", "@type": "BlogPosting", "headline": "Future",
                               "datePublished": future.isoformat()}]),
    })


def autostamp_site() -> Site:
    today = date.today().isoformat()
    paths = ["/", "/a", "/b", "/c", "/d", "/e"]
    urls = "".join(f"<url><loc>{{base}}{p}</loc><lastmod>{today}</lastmod></url>" for p in paths)
    routes = {p: doc(f"Page {p} | Acme", nav(*paths) + f"<main><h1>Page {p}</h1><p>{en()}</p></main>") for p in paths}
    return Site({
        "/robots.txt": robots("User-agent: *\nAllow: /\nSitemap: {base}/sitemap.xml\n"),
        "/sitemap.xml": Response(body=f'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>',
                                 content_type="application/xml"),
        "/og/home.png": Response(body="PNG", content_type="image/png"),
        **routes,
    })


def stamped_headers_site() -> Site:
    """Seen on a real client (Midas, 2026-09-17): a Last-Modified set by a page cache 0-73 minutes before each
    request, on every page, beside sitemap dates months older. Plus one identical dateModified on every page."""
    cached = format_datetime(datetime.now(timezone.utc) - timedelta(minutes=40), usegmt=True)
    paths = ["/", "/a", "/b", "/c", "/d", "/e"]
    # Real, different sitemap dates, 90-95 days old: only the header and dateModified are stamped.
    urls = "".join(f"<url><loc>{{base}}{p}</loc><lastmod>{(date.today() - timedelta(days=90 + i)).isoformat()}"
                   "</lastmod></url>" for i, p in enumerate(paths))
    schema = ld({"@type": "WebPage", "datePublished": "2023-06-01", "dateModified": "2024-01-15"})
    routes = {p: doc(f"Page {p} | Acme", nav(*paths) + f"<main><h1>Page {p}</h1><p>{en()}</p></main>", head=schema,
                     headers={"Last-Modified": cached}) for p in paths}
    return Site({
        "/robots.txt": robots("User-agent: *\nAllow: /\nSitemap: {base}/sitemap.xml\n"),
        "/sitemap.xml": Response(body=f'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>',
                                 content_type="application/xml"),
        "/og/home.png": Response(body="PNG", content_type="image/png"),
        **routes,
    })


# -- STR-7 / STR-8 --------------------------------------------------------------

def images_grids_site() -> Site:
    menu = nav("/", "/gallery", "/pricing", "/integrations", "/table-pricing", "/cards", "/steps")
    footer = ('<footer><div class="cols"><div class="col"><span>Company</span><span>About</span><span>Jobs</span></div>'
              '<div class="col"><span>Help</span><span>Docs</span><span>Status</span></div>'
              '<div class="col"><span>Legal</span><span>Terms</span><span>Privacy</span></div></div></footer>')

    def page(title, body):
        return doc(title, '<header><img src="/logo.png" class="logo"></header>' + menu + f"<main>{body}</main>" + footer)

    def grid(rows):
        return ('<div class="plans">' + "".join('<div class="plan-row">' + "".join(f"<div>{c}</div>" for c in r) + "</div>"
                                                for r in rows) + "</div>")

    return Site({
        "/robots.txt": robots("User-agent: *\nAllow: /\n"),
        "/og/home.png": Response(body="PNG", content_type="image/png"),
        "/": page("Home | Acme", f"<h1>Acme</h1><p>{en()}</p>"),
        "/gallery": page("Gallery | Acme", f"<h1>Gallery</h1><p>{en()}</p>"
                         '<figure><img src="/img/q3.png" width="800" height="400"><figcaption>Chart of quarterly results</figcaption></figure>'
                         '<figure><img src="/img/revenue-chart.png"><figcaption>Chart of revenue</figcaption></figure>'
                         '<figure><img src="/img/product-detail.jpg" width="500" height="350" alt=""><figcaption>Diagram of product connections</figcaption></figure>'
                         '<img src="/img/unknown.jpg" alt="">'
                         '<img src="/icons/check.svg" width="16" height="16">'
                         '<img src="/img/x1.jpg">'
                         '<img src="/img/divider.png" alt="">'
                         '<img src="/img/team.jpg" alt="The team at the 2026 offsite" width="900" height="600">'
                         '<figure><img src="/img/f.png"><figcaption>Diagram of setup</figcaption></figure>'
                         '<img src="/img/banner.png" width="1200" height="300">'),
        "/pricing": page("Pricing | Acme", "<h1>Pricing</h1>" + grid([["Plan", "Starter", "Pro"], ["Price", "$9/mo", "$49/mo"],
                                                                     ["Seats", "1", "10"]]) + f"<p>{en()}</p>"),
        "/integrations": page("Integrations | Acme", "<h1>Integrations</h1>" + grid(
            [["Slack", "Chat", "Live"], ["Jira", "Issues", "Live"], ["Zapier", "Automation", "Beta"]]) + f"<p>{en()}</p>"),
        "/table-pricing": page("Plans table | Acme", "<h1>Plans</h1><table><tr><th>Plan</th><th>Price</th></tr>"
                               "<tr><td>Starter</td><td>$9/mo</td></tr><tr><td>Pro</td><td>$49/mo</td></tr></table>"
                               f"<p>{en()}</p>"),
        "/cards": page("Why Acme | Acme", "<h1>Why Acme</h1><div class='cards'>" + "".join(
            f"<div class='card'><h3>Reason {i}</h3><p>{EN}</p></div>" for i in range(3)) + "</div>"),
        "/steps": page("Setup steps | Acme", "<h1>Setup</h1><div><p>1. Install the snippet</p><p>2. Verify events</p>"
                       f"<p>3. Invite your team</p></div><p>{en()}</p>"),
    })


# -- STR-5 / STR-9 (hreflang, lang mismatch) / STR-10 (og:image) with a second origin --------------

def entity_site(external_base) -> Site:
    """external_base() returns the base URL of a second fake server (another origin) at request time."""
    menu = nav("/", "/about", "/pricing", "/customers/globex", "/en/guide", "/tr/rehber")

    def home(site: Site, request: RequestSeen) -> Response:
        ext = external_base()
        org = {"@context": "https://schema.org", "@type": "Organization", "name": "Acme Analytics",
               "legalName": "Acme Analytics, Inc.", "url": "{base}/", "logo": "{base}/logo.png",
               "sameAs": [f"{ext}/company/acme", f"{ext}/gone", f"{ext}/blocked/profile", "{base}/about"]}
        return doc("Acme Analytics", '<header><a class="logo" href="/"><img src="/logo.png" alt="AcmeHQ logo"></a></header>'
                   + menu + f"<main><h1>Acme Analytics</h1><p>{en()}</p>"
                   # A "trusted by" strip: customer logos in main content are not the site's own logo.
                   '<div class="brand-logos"><img src="/brands/volkswagen.png" alt="Volkswagen">'
                   '<img src="/brands/isbank.png" alt="Türkiye İş Bankası"></div></main>'
                   # The © line is its own text node; the links after it must not run into the name.
                   "<footer><p>© 2026 Acme Analytics, Inc. All rights reserved.</p>"
                   '<a href="#top">Back to top</a><p>Built for what comes next</p></footer>',
                   head=ld(org) + '<meta property="og:site_name" content="Acme">', og_image=f"{ext}/img/og.png")

    def about(site: Site, request: RequestSeen) -> Response:
        return doc("About | Acme", menu + f"<main><h1>About</h1><p>{en()}</p></main>",
                   og_image=f"{external_base()}/img/missing.png")

    def guide(site: Site, request: RequestSeen) -> Response:
        alternates = [("en", "{base}/en/guide"), ("tr", "{base}/tr/rehber"), ("de", "{base}/de/anleitung"),
                      ("es", "{base}/private/es-guia"), ("fr", f"{external_base()}/fr/guide"), ("x-default", "{base}/en/guide")]
        head = "".join(f'<link rel="alternate" hreflang="{c}" href="{h}">' for c, h in alternates)
        head += '<link rel="alternate" hreflang="en_US" href="/en/guide">'  # malformed code, relative URL (self)
        return doc("Guide | Acme", menu + f"<main><h1>Guide</h1><p>{en()}</p></main>", head=head)

    rehber_head = '<link rel="alternate" hreflang="tr" href="{base}/tr/rehber">'
    return Site({
        "/robots.txt": robots("User-agent: *\nDisallow: /private/\n"),
        "/": home,
        "/logo.png": Response(body="PNG", content_type="image/png"),
        "/og/home.png": Response(body="PNG", content_type="image/png"),
        "/about": about,
        "/pricing": doc("Pricing | Acme", menu + f"<main><h1>Pricing</h1><p>{en()}</p></main>"),
        # A customer story marks up the CUSTOMER's organization. It is not this site's brand name.
        "/customers/globex": doc("Globex case study | Acme", menu + f"<main><h1>Globex</h1><p>{en()}</p></main>",
                                 head=ld({"@context": "https://schema.org", "@type": "Organization",
                                          "name": "Globex Sigorta A.Ş.", "url": "https://globex.example/"})),
        "/en/guide": guide,
        # Declared English, written in Turkish, and no hreflang link back to /en/guide. Six sentences: STR-9 needs 150
        # words of main text (DECISIONS 224).
        "/tr/rehber": doc("Rehber | Acme", menu + f"<main><h1>Rehber</h1><p>{tr(6)}</p></main>", head=rehber_head),
        "/private/es-guia": doc("Guía | Acme", "<main><h1>Guía</h1></main>", lang="es"),
    })


def external_site(site_base) -> Site:
    def fr_guide(site: Site, request: RequestSeen) -> Response:
        head = (f'<link rel="alternate" hreflang="fr" href="{{base}}/fr/guide">'
                f'<link rel="alternate" hreflang="en" href="{site_base()}/en/guide">')
        return doc("Guide (FR)", "<main><h1>Guide</h1></main>", head=head, lang="fr")

    return Site({
        "/robots.txt": robots("User-agent: *\nDisallow: /blocked/\n"),
        "/company/acme": doc("Acme on a profile site", "<main><h1>Acme</h1></main>"),
        "/blocked/profile": doc("Blocked", "<main>x</main>"),
        "/img/og.png": Response(body="PNG", content_type="image/png"),
        "/fr/guide": fr_guide,
    })


# -- STR-11 ----------------------------------------------------------------------

MARKUP_NAV = nav("/", "/two-prices", "/same-id", "/article", "/consistent", "/two-products", "/left-to-str4", "/broken",
                 "/two-ids")


def _offer(price, availability="InStock", currency="USD"):
    return {"@type": "Offer", "price": price, "priceCurrency": currency,
            "availability": f"https://schema.org/{availability}"}


def _microdata_product(name, price, currency="USD"):
    return (f'<div itemscope itemtype="https://schema.org/Product"><span itemprop="name">{name}</span>'
            f'<div itemprop="offers" itemscope itemtype="https://schema.org/Offer">'
            f'<meta itemprop="price" content="{price}"><meta itemprop="priceCurrency" content="{currency}"></div></div>')


def markup_site() -> Site:
    def body(extra=""):
        return MARKUP_NAV + f"<main><h1>Widget</h1><p>{en(2)}</p>{extra}</main>"

    widget = {"@type": "Product", "name": "Widget"}
    return Site({
        "/robots.txt": robots("User-agent: *\nAllow: /\n"),
        "/": doc("Acme", body()),
        # JSON-LD says 49, Microdata says 59, the page shows no price: STR-11's own finding (Inferred: by name).
        "/two-prices": doc("Widget", body(_microdata_product("Widget", "59")),
                           head=ld({**widget, "offers": _offer("49")})),
        # Two JSON-LD nodes sharing an @id disagree on availability: Verified.
        "/same-id": doc("Widget", body(), head=ld(
            {**widget, "@id": "#widget", "offers": _offer("49", "InStock")},
            {**widget, "@id": "#widget", "offers": _offer("49", "OutOfStock")})),
        # An article described twice with different publication dates.
        "/article": doc("Launch notes", body(), head=ld(
            {"@type": "Article", "headline": "Launch notes", "datePublished": "2026-01-05"},
            {"@type": "BlogPosting", "headline": "Launch notes", "datePublished": "2025-11-20"})),
        # Near misses that must not fire: two descriptions that agree, and two different products.
        "/consistent": doc("Widget", body(_microdata_product("Widget", "49")), head=ld({**widget, "offers": _offer("49")})),
        "/two-products": doc("Widgets", body(), head=ld({**widget, "offers": _offer("49")},
                                                        {"@type": "Product", "name": "Gadget", "offers": _offer("99")})),
        # The page shows $59, so STR-4 already reports the stale JSON-LD price: STR-11 leaves it to STR-4.
        "/left-to-str4": doc("Widget", body("<p>Price: $59</p>" + _microdata_product("Widget", "59")),
                             head=ld({**widget, "offers": _offer("49")})),
        "/broken": doc("Broken", body(), head='<script type="application/ld+json">{"@type": "Product",</script>'),
        # Two entities told apart only by their @id fragments: never one entity (fragments are identity).
        "/two-ids": doc("Widgets", body(), head=ld({**widget, "@id": "#widget", "offers": _offer("49")},
                                                   {**widget, "@id": "#gadget", "offers": _offer("99")})),
    })


# -- STR-3 graph / STR-5 entity ----------------------------------------------------

GRAPH_NAV = nav("/", "/about", "/post", "/old-post", "/product", "/product-variant", "/clean", "/person-page")


def entity_graph_site() -> Site:
    def body(h1):
        return GRAPH_NAV + f"<main><h1>{h1}</h1><p>{en(2)}</p></main>"

    org = {"@type": "Organization", "@id": "/#org", "name": "Acme", "url": "/"}
    return Site({
        "/robots.txt": robots("User-agent: *\nAllow: /\n"),
        "/": doc("Acme", body("Acme"), head=ld({"@context": "https://schema.org", "@graph": [
            org, {"@type": "WebSite", "@id": "/#site", "name": "Acme", "publisher": {"@id": "/#org"}},
            {"@type": "WebPage", "url": "/", "isPartOf": {"@id": "/#site"}}]})),
        # The same @id with another name: the markup contradicts itself about the brand.
        "/about": doc("About | Acme", body("About"), head=ld({**org, "name": "Acme Analytics Ltd"})),
        # A reference nothing defines, and a url that returns 404.
        "/post": doc("Post | Acme", body("Post"), head=ld({"@type": "Article", "headline": "Post", "url": "/old-post",
                                                         "author": {"@id": "/#jane"}, "publisher": {"@id": "/#org"}})),
        "/old-post": Response(404, "gone"),
        # A url naming another live page.
        "/product": doc("Widget | Acme", body("Widget"), head=ld({"@type": "Product", "name": "Widget",
                                                                "url": "/product-variant"})),
        "/product-variant": doc("Widget variant | Acme", body("Widget variant")),
        # The same @id typed as a Person here and an Organization elsewhere.
        "/person-page": doc("Team | Acme", body("Team"), head=ld({"@type": "Person", "@id": "/#org", "name": "Acme"})),
        # Near miss: self url, and references that resolve.
        "/clean": doc("Clean | Acme", body("Clean"), head=ld({"@type": "WebPage", "url": "/clean",
                                                            "publisher": {"@id": "/#org"}})),
    })


def traditional_quality_site() -> Site:
    paths = ["/", "/short", "/long", "/clean"]
    menu = nav(*paths)

    def page(title: str, description: str, headings: str) -> Response:
        return Response(body=(f'<!doctype html><html lang="en"><head><title>{title}</title>'
                              f'<meta name="description" content="{description}"></head>'
                              f'<body>{menu}<main>{headings}<p>{en()}</p></main></body></html>'),
                        content_type="text/html; charset=utf-8")

    return Site({
        "/robots.txt": robots("User-agent: *\nAllow: /\n"),
        "/": page("Acme Product Guide", "A practical guide to choosing the right product for a growing team, with clear steps and examples.",
                   "<h1>Product guide</h1><h2>How to compare</h2><h3>Next steps</h3>"),
        "/short": page("FAQ", "Short description.", "<h1>Frequently asked questions</h1><h2>Billing</h2>"),
        "/long": page("The Complete Product Analytics Implementation Guide for Growing Organizations 2026",
                      "This unusually long description provides secondary details and supporting context beyond a concise summary. "
                      "It continues with material that is better placed on the page itself and does not need to appear in a search snippet.",
                      "<h1>Implementation guide</h1><h2>Setup</h2><h4>Advanced setup</h4>"),
        "/clean": page("Product setup guide | Acme", "Follow these clear product setup steps to configure your workspace and invite your team.",
                       "<h1>Setup guide</h1><h2>Prepare</h2><h3>Configure</h3>"),
    })


def image_cap_site() -> Site:
    paths = ["/", "/gallery"]
    images = "".join(f'<img src="/assets/{i}.jpg" alt="A descriptive image of item {i}">' for i in range(205))
    home = ("<!doctype html><html><head><title>Acme home</title><meta name=description content=\"A useful home page description for teams choosing a product.\"></head>"
            f"<body>{nav(*paths)}<main><h1>Acme</h1>{en()}{images}</main></body></html>")
    gallery = ("<!doctype html><html><head><title>Gallery | Acme</title><meta name=description content=\"A useful gallery description for product images.\"></head>"
               f"<body>{nav(*paths)}<main><h1>Gallery</h1>{en()}</main></body></html>")
    return Site({"/robots.txt": robots("User-agent: *\nAllow: /\n"),
                 "/": Response(body=home, content_type="text/html; charset=utf-8"),
                 "/gallery": Response(body=gallery, content_type="text/html; charset=utf-8")})


STR_SCENARIOS: dict[str, Scenario] = {s.name: s for s in [
    Scenario("str_pages", "Missing, duplicate, and generic titles; missing, multiple, and absent subheadings; a "
             "client-rendered shell; a missing lang; missing preview tags and a 404 og:image.", pages_site, FAST_STR),
    Scenario("str_structured_data", "Structured data with price, currency, availability, rating, name, author, and date "
             "conflicts (JSON-LD and Microdata), a parse error, missing required properties and types, a Turkish page, "
             "and stale, future, and missing dates.", structured_site, FAST_STR),
    Scenario("str_autostamp", "Every sitemap <lastmod> is the audit day.", autostamp_site, FAST_STR),
    Scenario("str_entity_graph", "Structured-data graph: an @id named two ways, a dangling reference, a url that "
             "404s, a url naming another page, one @id typed two ways, and a clean page.", entity_graph_site, FAST_STR),
    Scenario("str_stamped_headers", "Every page's Last-Modified is a cache time 40 minutes old, every dateModified is "
             "one identical date, and the sitemap dates are 90 days old.", stamped_headers_site, FAST_STR),
    Scenario("str_markup_contradictions", "Structured data that contradicts itself: JSON-LD vs Microdata price, one "
             "@id with two availabilities, an article with two publication dates, plus agreeing descriptions, two "
             "different products, a conflict STR-4 already owns, and a JSON-LD block that does not parse.",
             markup_site, FAST_STR),
    Scenario("str_images_grids", "Images with and without alt text in and out of main content, pricing and other "
             "<div> grids, a real <table>, cards, and numbered paragraphs.", images_grids_site, FAST_STR),
    Scenario("traditional_seo_quality", "Title and meta-description guidance bands; heading hierarchy near misses.",
             traditional_quality_site, FAST_STR),
    Scenario("str_images_over_cap", "More than 200 main-content images to verify exact coverage and partial status.",
             image_cap_site, FAST_STR),
]}
