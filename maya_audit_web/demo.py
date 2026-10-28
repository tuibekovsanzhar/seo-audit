"""Demo mode: made-up sites and made-up backlink figures, served from memory.

`python -m maya_audit_web --demo` runs the real engine against these. No socket is opened to any
website and no request reaches DataForSEO: both go to in-memory transports defined here. The demo
keeps its own history, ledger and cache in a `demo` folder, apart from real audits.

The shop has more than 500 pages, English and Turkish, with planted problems (missing descriptions,
noindex pages, broken links, a redirect, a JavaScript-only page, and a title containing HTML) so that
the results page has something of every kind to show.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from maya_audit.dataforseo import insights, panel, pricing
from maya_audit.dataforseo.cache import CACHE_NAME, Cache
from maya_audit.dataforseo.credentials import Credentials
from maya_audit.dataforseo.ledger import LEDGER_NAME, Ledger

from maya_audit.firecrawl import settings as firecrawl_settings
from maya_audit.firecrawl.settings import FirecrawlKey

from .fc import FirecrawlServices
from .paid import PaidServices

SHOP = "demo-shop.localhost"
CAFE = "demo-kafe.localhost"
BANK = "demo-bank.localhost"
VAULT = "demo-vault.localhost"
FORTRESS = "demo-fortress.localhost"
PARTIAL = "demo-partial.localhost"
APP = "demo-app.localhost"
SITES = {SHOP: "English and Turkish shop, more than 500 pages, with planted problems",
         CAFE: "Small Turkish café site, 12 pages",
         BANK: "A site whose bot protection challenges every automated visitor",
         VAULT: "Blocked like the bank, and the made-up Firecrawl refuses zero data retention for it",
         FORTRESS: "Blocked like the bank, and it turns Firecrawl's basic proxy away as well",
         PARTIAL: "Blocked like the bank; the reader reads part of it (one page challenged, one sent elsewhere), and its "
                  "search data comes back with measurements missing",
         APP: "A site built with JavaScript: the raw HTML is an empty shell, and its search data holds true zeros"}
# The made-up sites that answer every visitor with a challenge page.
CHALLENGED = (BANK, VAULT, FORTRESS, PARTIAL)
# What the search data panels are asked about for two demo sites: reserved names whose made-up answers have gaps
# (measurements missing) or true zeros. Every other demo site is asked about the backlink target below.
SEARCH_TARGETS = {PARTIAL: "https://www.demo-gaps.example/", APP: "https://www.demo-zero.example/"}
# What the backlink panel is asked about in demo mode: a reserved name that belongs to nobody.
BACKLINK_TARGET = "https://www.demo-shop.example/"
CATEGORIES, PRODUCTS, TURKISH = 12, 540, 30

# Settings laid over the command line's own so a demo audit takes seconds, not most of an hour.
OVERRIDES = dict(request_delay_s=0.0, robots_samples=1, robots_sample_interval_s=0.0, refetch_delay_s=0.0,
                 prf_round_gap_s=0.0, render_enabled=False, probes_enabled=False, probe_retry_cooldown_s=0.0,
                 # The made-up sites link to no real one, and demo mode contacts nothing else (DECISIONS 211).
                 check_external_links=False)

HOSTILE_TITLE = 'Sale "50%" <b>off</b> <script>alert("maya")</script>'


def _html(lang: str, title: str | None, heading: str, body: str, *, description: str | None = "", head: str = "") -> str:
    from html import escape

    meta = f'<meta name="description" content="{escape(description)}">' if description else ""
    title_tag = f"<title>{escape(title)}</title>" if title is not None else ""
    return (f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8">{title_tag}{meta}{head}</head>'
            f"<body><header><a href=\"/\">Home</a></header><main><h1>{escape(heading)}</h1>{body}</main></body></html>")


def _page(text: str, status: int = 200, content_type: str = "text/html; charset=utf-8", **headers: str) -> httpx.Response:
    return httpx.Response(status, content=text.encode("utf-8"), headers={"content-type": content_type, **headers})


def _product(n: int) -> httpx.Response:
    if n == 5:
        return httpx.Response(301, headers={"location": "/item/6"})
    name = f"Walnut desk organiser {n}"
    # Every 13th product shares one title, and that title holds HTML: the report quotes it, so the page must show it as text.
    title = HOSTILE_TITLE if n % 13 == 0 else f"{name} | Demo Shop"
    # Every 9th product reuses one description (STR-16), every 7th has none (STR-10).
    description = (None if n % 7 == 0 else "Hand-made walnut desk furniture from Demo Shop." if n % 9 == 0
                   else f"{name}: solid walnut, three trays, made to order in about two weeks.")
    head = '<meta name="robots" content="noindex">' if n % 11 == 0 else ""
    head += ('<script type="application/ld+json">' + json.dumps(
        {"@context": "https://schema.org", "@type": "Product", "name": name,
         "offers": {"@type": "Offer", "price": str(20 + n), "priceCurrency": "EUR"}}) + "</script>")
    broken = f'<p><a href="/missing-{n}">Care guide</a></p>' if n % 17 == 0 else ""
    body = (f"<p>{name} is cut from one board of European walnut and finished with hard-wax oil. "
            f"It holds A4 paper, pens and a phone, and weighs {900 + n} grams.</p>"
            f"<p>Price: €{20 + n}. Delivery takes about {7 + n % 5} working days inside the EU.</p>"
            f'{broken}<p><a href="/c/{n % CATEGORIES + 1}">Back to the category</a> '
            f'<a href="/item/{n % PRODUCTS + 1}">Next product</a></p>')
    return _page(_html("en", title, name, body, description=description, head=head))


def _shop(path: str) -> httpx.Response:
    if path == "/robots.txt":
        return _page("User-agent: *\nAllow: /\nDisallow: /cart\nSitemap: http://demo-shop.localhost/sitemap.xml\n",
                     content_type="text/plain")
    if path == "/sitemap.xml":
        urls = ["/", "/about", "/tr/"] + [f"/c/{n}" for n in range(1, CATEGORIES + 1)] + [f"/item/{n}" for n in range(1, 61)]
        return _page('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                     + "".join(f"<url><loc>http://{SHOP}{u}</loc></url>" for u in urls) + "</urlset>",
                     content_type="application/xml")
    if path == "/":
        links = "".join(f'<li><a href="/c/{n}">Category {n}</a></li>' for n in range(1, CATEGORIES + 1))
        return _page(_html("en", "Demo Shop: walnut desk furniture", "Walnut desk furniture, made to order",
                           f'<p>Demo Shop makes desk organisers, monitor stands and trays from European walnut.</p><ul>{links}</ul>'
                           '<p><a href="/about">About</a> <a href="/tr/">Türkçe</a> <a href="/app">Order tracker</a> '
                           '<a href="/cart">Cart</a></p>',
                           description="Walnut desk organisers, monitor stands and trays, made to order and shipped in the EU."))
    if path == "/about":
        return _page(_html("en", "About Demo Shop", "About Demo Shop",
                           "<p>Demo Shop is a two-person workshop. Every piece is made after it is ordered.</p>",
                           description="Who makes Demo Shop's furniture and how an order is made."))
    if path == "/app":  # content exists only after JavaScript runs
        return _page('<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Order tracker</title></head>'
                     '<body><div id="root"></div><script src="/static/app.js"></script></body></html>')
    if path.startswith("/c/") and path[3:].isdigit() and 1 <= int(path[3:]) <= CATEGORIES:
        c = int(path[3:])
        items = "".join(f'<li><a href="/item/{n}">Walnut desk organiser {n}</a></li>'
                        for n in range(1, PRODUCTS + 1) if n % CATEGORIES + 1 == c)
        return _page(_html("en", f"Category {c} | Demo Shop", f"Category {c}",
                           f"<p>Everything in category {c}, newest first.</p><ul>{items}</ul>",
                           description=f"All walnut desk furniture in category {c}."))
    if path.startswith("/item/") and path[6:].isdigit() and 1 <= int(path[6:]) <= PRODUCTS:
        return _product(int(path[6:]))
    if path == "/tr/":
        links = "".join(f'<li><a href="/tr/urun-{n}">Ceviz masa düzenleyici {n}</a></li>' for n in range(1, TURKISH + 1))
        return _page(_html("tr", "Demo Shop: ceviz masa mobilyaları", "Sipariş üzerine ceviz masa mobilyaları",
                           f"<p>Demo Shop, Avrupa cevizinden masa düzenleyiciler, monitör standları ve tepsiler üretir.</p><ul>{links}</ul>",
                           description="Sipariş üzerine üretilen ceviz masa düzenleyiciler ve monitör standları."))
    if path.startswith("/tr/urun-") and path[9:].isdigit() and 1 <= int(path[9:]) <= TURKISH:
        n = int(path[9:])
        name = f"Ceviz masa düzenleyici {n}"
        return _page(_html("tr", f"{name} | Demo Shop", name,
                           f"<p>{name}, tek parça Avrupa cevizinden kesilir ve doğal yağ ile işlenir. "
                           f"Ağırlığı {900 + n} gramdır; İstanbul içi teslimat yaklaşık üç iş günü sürer.</p>"
                           '<p><a href="/tr/">Tüm ürünler</a></p>',
                           description=f"{name}: tek parça ceviz, üç bölmeli, sipariş üzerine üretilir."))
    return _page(_html("en", "Page not found", "Page not found", "<p>There is nothing at this address.</p>"), status=404)


def _cafe(path: str) -> httpx.Response:
    pages = {"/": "Kafe Demo: Kadıköy'de üçüncü dalga kahve", "/menu": "Menü", "/hakkimizda": "Hakkımızda",
             "/iletisim": "İletişim", **{f"/kahve-{n}": f"Çekirdek {n}" for n in range(1, 9)}}
    if path == "/robots.txt":
        return _page("User-agent: *\nAllow: /\n", content_type="text/plain")
    if path not in pages:
        return _page(_html("tr", "Sayfa bulunamadı", "Sayfa bulunamadı", "<p>Bu adreste bir şey yok.</p>"), status=404)
    links = "".join(f'<li><a href="{p}">{title}</a></li>' for p, title in pages.items())
    return _page(_html("tr", pages[path] + " | Kafe Demo", pages[path],
                       f"<p>Kafe Demo, Kadıköy'de çekirdeklerini kendi kavuran küçük bir kahve dükkânıdır. "
                       f"Her gün 08.00 ile 20.00 arasında açıktır.</p><ul>{links}</ul>",
                       description=f"{pages[path]}: Kafe Demo, Kadıköy, İstanbul."))


APP_PAGES = {"/": ("Demo App: plan your week", "Demo App is a made-up planning tool. It shows the week as one list, moves unfinished "
                                                 "tasks forward, and works without an account."),
             "/features": ("Features", "Weekly list, repeating tasks, shared lists for a household, and a quiet mode that hides "
                                       "everything but today. Every feature here is invented for demonstration."),
             "/pricing": ("Pricing", "Demo App is free for one person. A made-up household plan costs 4 a month for up to six people.")}


def _app_shell(path: str) -> httpx.Response:
    """What a crawler that runs no JavaScript receives from a client-rendered site: a title and an empty mount point."""
    if path == "/robots.txt":
        return _page("User-agent: *\nAllow: /\nSitemap: http://demo-app.localhost/sitemap.xml\n", content_type="text/plain")
    if path == "/sitemap.xml":
        return _page('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                     + "".join(f"<url><loc>http://{APP}{p}</loc></url>" for p in APP_PAGES) + "</urlset>", content_type="application/xml")
    if path not in APP_PAGES:
        return _page("<!doctype html><html><head><title>Not found</title></head><body><div id=\"root\"></div></body></html>", status=404)
    return _page('<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Demo App</title></head>'
                 '<body><div id="root"></div><script src="/static/app.js"></script></body></html>')


def _app_rendered(path: str) -> str:
    """The same page after its script ran: what a reader that renders pages hands back."""
    title, text = APP_PAGES[path]
    links = "".join(f'<li><a href="http://{APP}{p}">{name}</a></li>' for p, (name, _text) in APP_PAGES.items())
    return _html("en", f"{title} | Demo App", title, f"<p>{text}</p><ul>{links}</ul>", description=text[:150])


PARTIAL_PAGES = {"/": ("Demo Clinic", "Demo Clinic is a made-up clinic used to show an audit that could read only part of a site."),
                 "/services": ("Services", "General practice, vaccinations and travel medicine. Every service here is invented."),
                 "/contact": ("Contact", "Call the made-up front desk between nine and five on weekdays.")}


def _partial(asked: dict, url: str, path: str) -> httpx.Response:
    """A reader that gets part of a challenged site: three pages read (one with no HTTP status reported), one page
    challenged for the reader too, one sent to another site, and more addresses than it was asked to read."""
    if path == "/robots.txt":
        return httpx.Response(200, json={"success": True, "data": {"rawHtml": "User-agent: *\nAllow: /\n", "metadata": {"statusCode": 200, "url": url}}})
    if path == "/pricing":
        return httpx.Response(200, json={"success": True, "data": {
            "rawHtml": "<!doctype html><html><head><title>Just a moment...</title></head><body>Checking your browser (made-up demonstration page).</body></html>",
            "metadata": {"statusCode": 403, "url": url}}})
    if path == "/booking":
        return httpx.Response(200, json={"success": True, "data": {
            "rawHtml": _html("en", "Made-up booking service", "Book", "<p>Another company's page.</p>"),
            "metadata": {"statusCode": 200, "sourceURL": url, "url": "https://made-up-booking.example/demo-clinic"}}})
    if path not in PARTIAL_PAGES:
        return httpx.Response(200, json={"success": True, "data": {"rawHtml": _html("en", "Not found", "Not found", "<p>Nothing here.</p>"),
                                                                    "metadata": {"statusCode": 404, "url": url}}})
    title, text = PARTIAL_PAGES[path]
    every = [*PARTIAL_PAGES, "/pricing", "/booking", *(f"/doctor-{n}" for n in range(1, 4))]
    links = "".join(f'<li><a href="http://{PARTIAL}{p}">{p.strip("/") or "home"}</a></li>' for p in every)
    # The contact page comes back with no HTTP status: its document is read, and its status is reported as unknown.
    meta = {"url": url, "contentType": "text/html; charset=utf-8", **({} if path == "/contact" else {"statusCode": 200})}
    return httpx.Response(200, json={"success": True, "data": {
        "rawHtml": _html("en", f"{title} | Demo Clinic", title, f"<p>{text}</p><ul>{links}</ul>", description=text[:150]), "metadata": meta}})


def site_transport(page_delay_s: float = 0.03) -> httpx.MockTransport:
    """Answers for the demo sites only. Any other host gets a transport error, never the network."""
    def respond(request: httpx.Request) -> httpx.Response:
        host = request.url.host.removeprefix("www.")
        if host not in SITES:
            raise httpx.ConnectError(f"demo mode has no site called {host}")
        if page_delay_s:
            time.sleep(page_delay_s)  # so progress, Stop and Resume can be seen with the eye
        if host in CHALLENGED:  # the shape of a managed challenge page: what a blocked audit looks like
            return httpx.Response(403, headers={"content-type": "text/html; charset=UTF-8", "server": "cloudflare",
                                                "cf-mitigated": "challenge", "cf-ray": "demo0000-IST"},
                                  text="<!doctype html><html><head><title>Just a moment...</title></head><body>"
                                       "Checking your browser before accessing the site (made-up demonstration page).</body></html>")
        return _app_shell(request.url.path) if host == APP else (_shop if host == SHOP else _cafe)(request.url.path)
    return httpx.MockTransport(respond)


def _backlinks(request: httpx.Request) -> httpx.Response:
    """Made-up figures in DataForSEO's response shape, with a made-up cost below the estimate."""
    path = request.url.path
    if path == pricing.BACKLINKS_SUMMARY:
        cost, result = 0.02403, {"target": "demo-shop.example", "rank": 212, "backlinks": 1840, "referring_domains": 96,
                                 "referring_main_domains": 88, "referring_domains_nofollow": 21, "backlinks_spam_score": 7,
                                 "broken_backlinks": 12, "referring_ips": 90, "referring_subnets": 84,
                                 "first_seen": "2021-03-14 00:00:00 +00:00"}
    elif path == pricing.BACKLINKS_REFERRING_DOMAINS:
        items = [{"type": "backlinks_referring_domain", "domain": f"made-up-referrer-{n}.example", "rank": 400 - 3 * n,
                  "backlinks": 60 - n, "first_seen": "2023-01-01 00:00:00 +00:00",
                  "backlinks_spam_score": 70 if n % 9 == 0 else 5} for n in range(1, 41)]
        cost, result = 0.02544, {"target": "demo-shop.example", "total_count": 96, "items_count": len(items), "items": items}
    else:
        made_up = search_data(path, json.loads(request.content or b"[{}]"))
        if made_up is None:
            return httpx.Response(404, json={"status_code": 40400, "status_message": "Not Found."})
        cost, result = made_up
    task = {"status_code": 20000, "status_message": "Ok.", "cost": cost, "result": [result]}
    return httpx.Response(200, json={"status_code": 20000, "status_message": "Ok.", "cost": cost, "tasks": [task]})


def _keyword(word: str, searches: int, position: int, page: str) -> dict:
    return {"keyword_data": {"keyword": word, "keyword_info": {"search_volume": searches}},
            "ranked_serp_element": {"serp_item": {"rank_group": position, "rank_absolute": position, "url": f"https://demo-shop.example{page}"}}}


def search_data(path: str, payload: list) -> tuple[float, dict] | None:
    """Made-up answers for the search data panels, in the response shapes DataForSEO documents. Not real figures."""
    task = (payload or [{}])[0]
    asked = task.get("target")
    about = json.dumps(asked if asked is not None else task.get("url") or task.get("keyword") or "")
    if "demo-gaps.example" in about:
        return _search_data_with_gaps(path, task)
    if "demo-zero.example" in about:
        return _search_data_with_zeros(path, task)
    if path == pricing.LABS_DOMAIN_OVERVIEW:
        return 0.01212, {"target": "demo-shop.example", "total_count": 1, "items_count": 1, "items": [{"metrics": {"organic": {
            "pos_1": 4, "pos_2_3": 9, "pos_4_10": 31, "pos_11_20": 58, "pos_21_30": 40, "pos_31_40": 22, "etv": 1840.5, "count": 164,
            "is_new": 6, "is_up": 20, "is_down": 14, "is_lost": 3}}}]}
    if path == pricing.LABS_RANKED_KEYWORDS:
        quick = bool(task.get("filters"))
        words = ([("made-up kettle reviews", 2400, 6, "/kettles"), ("demo teapot sale", 1300, 12, "/teapots"), ("example tea set", 880, 17, "/sets")]
                 if quick else [("demo shop", 5400, 1, "/"), ("made-up kettle reviews", 2400, 6, "/kettles"), ("demo teapot sale", 1300, 12, "/teapots"),
                                ("example tea set", 880, 17, "/sets"), ("made-up mug", 320, 34, "/mugs")])
        return 0.0126, {"target": "demo-shop.example", "total_count": 58 if quick else 164, "items_count": len(words),
                        "metrics": {"organic": {"etv": 1840.5, "count": 164}}, "items": [_keyword(*word) for word in words]}
    if path == pricing.LABS_COMPETITORS:
        # DataForSEO lists the domain asked about among its own competitors; the report leaves it out.
        rivals = [("demo-shop.example", 164, 8.1, 164, 1840.5), ("made-up-rival-one.example", 61, 14.2, 2300, 9100.0),
                  ("made-up-rival-two.example", 44, 19.8, 980, 2650.4)]
        return 0.01224, {"target": "demo-shop.example", "total_count": 37, "items_count": 3, "items": [
            {"domain": domain, "intersections": shared, "avg_position": position, "full_domain_metrics": {"organic": {"count": count, "etv": visits}}}
            for domain, shared, position, count, visits in rivals]}
    if path == pricing.LLM_MENTIONS_AGGREGATED:
        platform = task.get("platform", "google")
        mentions = 38 if platform == "google" else 0
        return 0.101, {"total": {"platform": [{"type": "group_element", "key": platform, "mentions": mentions, "ai_search_volume": 12400 if mentions else 0}],
                                 "sources_domain": [{"type": "group_element", "key": "made-up-review-site.example", "mentions": 21, "ai_search_volume": 8200},
                                                    {"type": "group_element", "key": "demo-shop.example", "mentions": 17, "ai_search_volume": 6100}] if mentions else []},
                       "items": None}
    if path == pricing.LIGHTHOUSE:
        return 0.005, {"categories": {"performance": {"score": 0.62}, "seo": {"score": 0.92}, "accessibility": {"score": 0.88}, "best-practices": {"score": 0.96}},
                       "audits": {"largest-contentful-paint": {"numericValue": 3900.0, "displayValue": "3.9 s"},
                                  "cumulative-layout-shift": {"numericValue": 0.04, "displayValue": "0.04"},
                                  "total-blocking-time": {"numericValue": 410.0, "displayValue": "410 ms"},
                                  "first-contentful-paint": {"numericValue": 1800.0, "displayValue": "1.8 s"},
                                  "speed-index": {"numericValue": 3300.0, "displayValue": "3.3 s"}}}
    if path == pricing.BUSINESS_INFO:
        return 0.0054, {"keyword": task.get("keyword"), "items_count": 1, "items": [{
            "type": "google_business_info", "title": "Demo Cafe (made-up)", "category": "Cafe", "address": "1 Example Street, Demo Town",
            "phone": None, "url": "https://demo-cafe.example/", "domain": "demo-cafe.example", "rating": {"value": 4.4, "votes_count": 212},
            "is_claimed": False, "total_photos": 37}]}
    return None


def _search_data_with_gaps(path: str, task: dict) -> tuple[float, dict] | None:
    """Answers that came back with measurements missing: each must be shown as not assessed or partial, never as zero or healthy."""
    if path == pricing.LABS_DOMAIN_OVERVIEW:
        return 0.01212, {"total_count": 1, "items": [{"metrics": {"organic": {"count": 40, "pos_1": 2}}}]}  # no visits, no other bands
    if path == pricing.LABS_RANKED_KEYWORDS:
        return 0.0126, {"total_count": 40, "items": [_keyword("made-up clinic opening hours", 320, 5, "/contact")]}
    if path == pricing.LABS_COMPETITORS:
        return 0.012, {"items": None}  # no list and no total: unreadable
    if path == pricing.LLM_MENTIONS_AGGREGATED:
        platform = task.get("platform", "google")
        rows = [{"type": "group_element", "key": platform}] if platform == "google" else []  # a row with no count; an empty sample
        return 0.1, {"total": {"platform": rows, "sources_domain": []}, "items": None}
    if path == pricing.LIGHTHOUSE:
        return 0.005, {"categories": {"performance": {"score": 0.88}}, "audits": {}}  # a score, and no timing at all
    return None


def _search_data_with_zeros(path: str, task: dict) -> tuple[float, dict] | None:
    """Answers that are real zeros and empty samples: each is a valid observation, said as what it is."""
    if path == pricing.LABS_DOMAIN_OVERVIEW:
        return 0.012, {"total_count": 0, "items": []}
    if path in (pricing.LABS_RANKED_KEYWORDS, pricing.LABS_COMPETITORS):
        return 0.012, {"total_count": 0, "items": []}
    if path == pricing.LLM_MENTIONS_AGGREGATED:
        platform = task.get("platform", "google")
        return 0.1, {"total": {"platform": [{"type": "group_element", "key": platform, "mentions": 0, "ai_search_volume": 0}], "sources_domain": []}, "items": None}
    if path == pricing.LIGHTHOUSE:
        return 0.005, {"categories": {"performance": {"score": 0.97}, "seo": {"score": 1.0}, "accessibility": {"score": 0.95}, "best-practices": {"score": 1.0}},
                       "audits": {"largest-contentful-paint": {"numericValue": 1400.0, "displayValue": "1.4 s"},
                                  "cumulative-layout-shift": {"numericValue": 0.0, "displayValue": "0"},
                                  "total-blocking-time": {"numericValue": 0.0, "displayValue": "0 ms"}}}
    return None


def paid_services(folder: Path) -> PaidServices:
    """Made-up credentials, a made-up DataForSEO, and a ledger and cache of the demo's own."""
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    return PaidServices(credentials=lambda: Credentials("demo-login", "demo-password"),
                        stores=lambda: (Ledger(folder / LEDGER_NAME), Cache(folder / CACHE_NAME)),
                        transport=httpx.MockTransport(_backlinks),
                        plan=lambda url: panel.audit_plan(BACKLINK_TARGET),
                        search_plan=lambda url, options: insights.audit_plan(
                            SEARCH_TARGETS.get((urlsplit(url).hostname or "").removeprefix("www."), BACKLINK_TARGET),
                            country=options.get("country"), brand=options.get("brand") or "Demo Cafe",
                            local_business=bool(options.get("local_business"))))


def _crux(request: httpx.Request) -> httpx.Response:
    """A made-up Chrome UX Report answer, in Google's documented shape."""
    return httpx.Response(200, json={"record": {"metrics": {
        "largest_contentful_paint": {"percentiles": {"p75": 2900}}, "interaction_to_next_paint": {"percentiles": {"p75": 160}},
        "cumulative_layout_shift": {"percentiles": {"p75": "0.05"}}, "first_contentful_paint": {"percentiles": {"p75": 1700}}},
        "collectionPeriod": {"lastDate": {"year": 2026, "month": 10, "day": 1}}}})


def _no_archives(request: httpx.Request) -> httpx.Response:
    """The web archives in demo mode: reachable, and holding no copy of a made-up site."""
    if request.url.path.endswith("collinfo.json"):
        return httpx.Response(200, json=[])
    if request.url.path.endswith("/cdx/search/cdx"):
        return httpx.Response(200, json=[["original"]])
    return httpx.Response(200, json={"archived_snapshots": {}})


NO_DNS_RECORDS = httpx.MockTransport(lambda request: httpx.Response(200, json={"Status": 0, "Answer": []}))
CRUX_TRANSPORT, ARCHIVES_TRANSPORT = httpx.MockTransport(_crux), httpx.MockTransport(_no_archives)


BANK_PAGES = {"/": ("Demo Bank: everyday banking", "Demo Bank is a made-up bank used to show a blocked audit. It offers current "
                                                       "accounts, savings accounts and personal loans to residents of a made-up country."),
              "/accounts": ("Current and savings accounts", "A current account at Demo Bank has no monthly fee. A savings account pays "
                                                            "a made-up rate of 3.1% a year on balances up to 50,000."),
              "/loans": ("Personal loans", "Personal loans from 1,000 to 25,000 over one to five years, at a made-up fixed rate of 9.4%."),
              "/about": ("About Demo Bank", "Demo Bank does not exist. Every figure on these pages is invented for demonstration.")}


def _firecrawl(request: httpx.Request) -> httpx.Response:
    """A made-up Firecrawl in its response shape. It "gets past" the demo bank's challenge so the reader has something to show."""
    asked = json.loads(request.content)
    url = asked.get("url", "")
    parts = urlsplit(url)
    host = (parts.hostname or "").removeprefix("www.")
    if host == PARTIAL:
        return _partial(asked, url, parts.path)
    if host == APP:
        if parts.path not in APP_PAGES:
            return httpx.Response(200, json={"success": True, "data": {"rawHtml": _app_shell(parts.path).text, "metadata": {"statusCode": 404, "url": url}}})
        return httpx.Response(200, json={"success": True, "data": {"rawHtml": _app_rendered(parts.path), "metadata": {
            "statusCode": 200, "url": url, "contentType": "text/html; charset=utf-8"}}})
    if host not in CHALLENGED:
        if host not in SITES:
            return httpx.Response(200, json={"success": True, "data": {"rawHtml": "", "metadata": {"statusCode": 404, "url": url}}})
        own = (_shop if host == SHOP else _cafe)(parts.path)  # an open demo site: the reader sees the page a visitor sees
        return httpx.Response(200, json={"success": True, "data": {"rawHtml": own.text, "metadata": {
            "statusCode": own.status_code, "url": url, "contentType": own.headers.get("content-type", "text/html")}}})
    if host == VAULT and asked.get("zeroDataRetention"):  # an account on which zero data retention was never enabled
        return httpx.Response(403, json={"success": False, "error": "Zero Data Retention is not enabled for this team (made-up demonstration answer)."})
    if host == FORTRESS and asked.get("proxy") == "basic" and parts.path != "/robots.txt":  # the basic proxy is challenged too
        return httpx.Response(200, json={"success": True, "data": {
            "rawHtml": "<!doctype html><html><head><title>Just a moment...</title></head><body>Checking your browser (made-up demonstration page).</body></html>",
            "metadata": {"statusCode": 403, "url": url}}})
    if parts.path == "/robots.txt":
        return httpx.Response(200, json={"success": True, "data": {"rawHtml": "User-agent: *\nDisallow: /internet-banking/\n",
                                                                    "metadata": {"statusCode": 200, "url": url, "contentType": "text/plain"}}})
    if parts.path not in BANK_PAGES:
        return httpx.Response(200, json={"success": True, "data": {"rawHtml": _html("en", "Not found", "Not found", "<p>Nothing here.</p>"),
                                                                    "metadata": {"statusCode": 404, "url": url}}})
    title, text = BANK_PAGES[parts.path]
    links = "".join(f'<li><a href="{path}">{name}</a></li>' for path, (name, _text) in BANK_PAGES.items())
    body = f'<p>{text}</p><ul>{links}<li><a href="/internet-banking/login">Internet banking</a></li></ul>'
    return httpx.Response(200, json={"success": True, "data": {
        "rawHtml": _html("en", f"{title} | Demo Bank", title, body, description=None if parts.path == "/loans" else text[:150]),
        "metadata": {"statusCode": 200, "url": url, "contentType": "text/html; charset=utf-8"}}})


def firecrawl_services(folder: Path) -> FirecrawlServices:
    """A made-up key, a made-up Firecrawl, and a credit ledger and cache of the demo's own."""
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    return FirecrawlServices(key=lambda: FirecrawlKey("fc-demo-made-up-key"),
                             stores=lambda: (Ledger(folder / firecrawl_settings.LEDGER_NAME), Cache(folder / firecrawl_settings.CACHE_NAME)),
                             transport=httpx.MockTransport(_firecrawl))


def write_citations(folder: Path) -> Path:
    """Made-up answer-engine citations of the demo shop, in the form `--citations` reads, so the ANS panel has data."""
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    base = f"http://{SHOP}"
    cited = [("/", "Where can I buy a walnut desk organiser?"), ("/item/6", "Best walnut desk organisers"),
             ("/item/5", "Walnut desk organiser 5 price"), ("/item/11", "Is Demo Shop's organiser 11 in stock?"),
             ("/missing-17", "Demo Shop care guide"), ("/tr/", "Ceviz masa düzenleyici nereden alınır?")]
    records = [{"engine": "made-up-engine", "model": "demo", "cited_at": "2026-10-01T09:00:00Z", "url": base + path,
                "prompt": prompt, "answer_excerpt": "Demo Shop sells walnut desk organisers made to order."}
               for path, prompt in cited]
    path = folder / "demo-citations.json"
    path.write_text(json.dumps({"source": "made-up demonstration data", "fetched_at": "2026-10-01T09:00:00Z",
                                "refresh_cadence": "none", "sample": {"prompts": len(cited), "answers": len(cited)},
                                "records": records}, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def is_demo_site(url: str) -> bool:
    return (urlsplit(url).hostname or "").removeprefix("www.") in SITES
