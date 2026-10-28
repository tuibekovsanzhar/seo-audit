"""Scripted websites for the RND checks (rendering and content extractability)."""

from __future__ import annotations

import json

from .scenarios import Scenario, robots
from .server import RequestSeen, Response, Site

FAST_RND = {"request_delay_s": 0.0, "request_timeout_s": 5.0, "robots_sample_interval_s": 0.05,
            "probe_retry_cooldown_s": 0.0, "refetch_delay_s": 0.0, "prf_round_gap_s": 0.0, "render_timeout_s": 10.0, "render_settle_ms": 1500}


def words(prefix: str, n: int) -> str:
    return " ".join(f"{prefix}{i}" for i in range(n))


def html(title: str, body: str, head: str = "") -> Response:
    return Response(body=f"<!doctype html><html><head><title>{title}</title>{head}</head><body>{body}</body></html>")


def js(source: str) -> Response:
    return Response(body=source, content_type="application/javascript")


NAV = '<nav><a href="/">Home</a> <a href="/pricing">Pricing</a> <a href="/partial">Partial</a> <a href="/ssr">About</a> ' \
      '<a href="/third-party">Widget</a> <a href="/interactive">Specs</a> <a href="/hidden-asset">Data</a> ' \
      '<a href="/zz-shell">Dashboard</a> <a href="/onboarding">Onboarding</a></nav>'


def csr_site(third_party_base: callable) -> Site:
    """third_party_base() returns the base URL of a second fake server (a different origin) at request time."""

    def third_party_page(site: Site, request: RequestSeen) -> Response:
        return html("Widget", NAV + f'<main><h1>Widget page</h1><p>{words("static", 40)}</p><div id="w"></div></main>'
                    f'<script src="{third_party_base()}/widget.js"></script>')

    return Site({
        "/robots.txt": robots("User-agent: *\nDisallow: /private/\n"),
        "/": html("Acme", NAV + '<div id="root"></div><script src="/app.js"></script>'),
        "/app.js": js("document.getElementById('root').innerHTML = '<main><h1>Acme Analytics</h1><p>"
                      + words("home", 300) + "</p></main>';"),
        "/pricing": html("Pricing", NAV + '<div id="root"></div><script src="/pricing.js"></script>'
                         '<script type="application/json" id="state">{"enterprise": "Enterprise: contact sales"}</script>'),
        "/pricing.js": js("document.getElementById('root').innerHTML = '<main><h1>Plans</h1><p>Pro plan $49/mo</p>"
                          "<h2>Team plan</h2><p>Team plan $99/mo</p><p>" + words("plans", 250) + "</p></main>';"),
        "/partial": html("Partial", NAV + f'<main><h1>Partial</h1><p>{words("server", 300)}</p><div id="extra"></div></main>'
                         '<script src="/partial.js"></script>'),
        # The extra section arrives from a data request, so RND-1 can name the request made while it rendered.
        "/partial.js": js("fetch('/api/extra.json').then(r => r.json()).then(d => { "
                          "document.getElementById('extra').innerHTML = '<h2>Loaded later</h2><p>' + d.text + '</p>'; });"),
        "/api/extra.json": Response(body=json.dumps({"text": words("client", 150)}), content_type="application/json"),
        "/ssr": html("About", NAV + f'<main><h1>About Acme</h1><p>Founded in 2012. {words("about", 200)}</p></main>'
                     '<img src="/slow-image.png" alt="A slow image" width="80" height="80">'
                     "<script>fetch('/slow-data.json').catch(() => {});</script>"),
        "/third-party": third_party_page,
        "/interactive": html("Specs", NAV + (
            f'<main><h1>Specs</h1><p>{words("intro", 60)}</p>'
            '<div role="tablist"><button role="tab" aria-selected="true">Overview</button>'
            '<button role="tab" aria-selected="false" id="t2">Specifications</button></div>'
            '<div role="tabpanel" id="panel2"></div>'
            '<div id="late"></div><div id="list"></div><button id="more">Load more</button>'
            '<form action="/search"><button type="button">Load more results</button><button>Search</button></form>'
            '<a href="/elsewhere">Read more</a></main>'
            '<script>'
            "fetch('/track', {method: 'POST', body: 'x'}).catch(() => {});"
            # Late-loading text with no click at all: RND-3's control snapshot must not credit it to a click.
            "setTimeout(() => { document.getElementById('late').innerHTML = '<p>" + words("late", 70) + "</p>'; }, 900);"
            "document.getElementById('t2').addEventListener('click', () => fetch('/tab2.json').then(r => r.json())"
            ".then(d => { document.getElementById('panel2').innerHTML = '<p>' + d.text + '</p>'; }));"
            "document.getElementById('more').addEventListener('click', () => fetch('/more.json').then(r => r.json())"
            ".then(d => { document.getElementById('list').insertAdjacentHTML('beforeend', '<p>' + d.text + '</p>'); }));"
            "document.querySelector('form button').addEventListener('click', e => { e.preventDefault(); "
            "document.getElementById('list').insertAdjacentHTML('beforeend', '<p>FORMCLICKED</p>'); });"
            '</script>')),
        # A resource that never finishes within the settle window: the network never goes idle, and the
        # render must still produce a DOM rather than failing outright.
        # The image is never fetched (images are skipped while rendering); the data request is.
        "/slow-image.png": Response(body="PNG", content_type="image/png", delay_s=3.0),
        "/slow-data.json": Response(body="{}", content_type="application/json", delay_s=3.0),
        "/tab2.json": Response(body=json.dumps({"text": words("spec", 80)}), content_type="application/json"),
        "/more.json": Response(body=json.dumps({"text": words("more", 50)}), content_type="application/json"),
        "/hidden-asset": html("Data", NAV + f'<main><h1>Data</h1><p>{words("data", 80)}</p><div id="d"></div></main>'
                              '<script src="/private/data.js"></script>'),
        "/private/data.js": js("document.getElementById('d').innerHTML = '<p>" + words("secret", 100) + "</p>';"),
        # Noindexed and client-rendered: no render slot, and no content-gap finding.
        "/onboarding": Response(body="<!doctype html><html lang='en'><head><title>Onboarding</title>"
                                "<meta name='robots' content='noindex'></head><body>" + NAV +
                                "<div id='root'></div><script src='/app.js'></script></body></html>"),
        "/zz-shell": html("Dashboard", NAV + '<div id="__next"></div>'
                          '<noscript>You need to enable JavaScript to run this app.</noscript><script src="/app.js"></script>'),
    })


def third_party_site() -> Site:
    return Site({
        "/widget.js": js("document.getElementById('w').innerHTML = '<p>" + words("widget", 300) + "</p>';"),
    })


def walls_site() -> Site:
    cookie_banner = '<div class="banner">We use cookies. <button>Accept all cookies</button></div>'
    return Site({
        "/robots.txt": robots("User-agent: *\nAllow: /\n"),
        "/": html("Home", '<a href="/members-only">Members</a> <a href="/article">Article</a> <a href="/story">Story</a> '
                  '<a href="/story-sd">Story SD</a> <a href="/wine-shop">Wine shop</a> <a href="/normal">Normal</a> <a href="/tr-cerez">TR</a> <a href="/en-plain">EN</a>'
                  f'<main><p>{words("home", 100)}</p></main>'),
        "/members-only": Response(302, "", {"Location": "/login?next=/members-only"}),
        "/login": html("Log in", "<main><h1>Log in</h1><p>Please sign in to continue.</p></main>"),
        "/article": html("Article", "<div><h1>Before you continue</h1><p>We use cookies to improve your experience. "
                         "Accept all cookies to continue reading.</p><button>Accept all cookies</button></div>"),
        "/story": html("Story", f'<main><h1>Big story</h1><p>{words("lede", 60)}</p><p>Subscribe to continue reading.</p></main>'),
        "/story-sd": html("Story SD",
                          f'<main><h1>Big story</h1><p>{words("lede", 60)}</p><p>Subscribe to continue reading.</p></main>',
                          head='<script type="application/ld+json">{"@type": "NewsArticle", "isAccessibleForFree": false, '
                               '"hasPart": {"@type": "WebPageElement", "isAccessibleForFree": false, '
                               '"cssSelector": ".paywall"}}</script>'),
        "/wine-shop": html("Wine shop", "<main><h1>Are you over 18?</h1><p>Verify your age to enter.</p></main>"),
        "/normal": html("Normal", cookie_banner + f'<main><h1>Normal page</h1><p>{words("body", 400)}</p></main>'),
        # A Turkish cookie wall: the English signatures cannot see it, so it must be "not assessed", not "no wall".
        "/tr-cerez": Response(body='<!doctype html><html lang="tr"><head><title>Çerezler</title></head><body>'
                              '<div><h1>Devam etmeden önce</h1><p>Deneyiminizi geliştirmek için çerezleri kullanıyoruz. '
                              'Okumaya devam etmek için tüm çerezleri kabul edin.</p><button>Tümünü kabul et</button>'
                              '</div></body></html>'),
        # An English page with enough text for a confident language guess and no wall.
        "/en-plain": Response(body='<!doctype html><html lang="en"><head><title>Guide</title></head><body><main><h1>Guide</h1>'
                              + "<p>" + " ".join(["This is the guide to our product and how you can use it with your team "
                                                  "for the best results in the first week."] * 6) + "</p></main></body></html>"),
    })


def nontext_site() -> Site:
    padding = "x" * 620_000
    return Site({
        "/robots.txt": robots("User-agent: *\nAllow: /\n"),
        "/": html("Home", '<a href="/chart">Chart</a> <a href="/embed">Embed</a> <a href="/banner">Banner</a> '
                  '<a href="/big">Big</a> <a href="/boilerplate">Boilerplate</a> <a href="/no-main">No main</a> '
                  f'<a href="/docs">Docs</a> <a href="/onboarding">Onboarding</a><main><p>{words("home", 100)}</p></main>'),
        "/chart": html("Chart", f'<main><h1>Revenue</h1><p>{words("chart", 50)}</p><canvas id="c"></canvas>'
                       '<canvas aria-label="Revenue by quarter"></canvas></main>'),
        "/embed": html("Embed", f'<main><h1>Pricing</h1><iframe src="https://widgets.example/pricing" title="Pricing widget">'
                       f'</iframe><p>{words("embed", 50)}</p></main>'),
        "/banner": html("Banner", f'<main><img src="/banner.png" width="1200" height="300">'
                        f'<img src="/banner2.png" alt="" width="900" height="200">'
                        f'<img src="/photo.jpg" alt="Team photo" width="1200" height="300">'
                        f'<img src="/square.png" width="400" height="400"><p>{words("banner", 80)}</p></main>'),
        "/big": html("Big", f'<script>window.__DATA__ = "{padding}";</script><main><h1>Big</h1><p>{words("big", 100)}</p></main>'
                     + f"<!-- {'y' * 450_000} -->"),
        "/boilerplate": html("Boilerplate", f'<nav>{words("nav", 400)}</nav><main><p>{words("main", 60)}</p></main>'
                             f'<footer>{words("foot", 300)}</footer>'),
        "/no-main": html("No main", f'<div><p>{words("para", 200)}</p></div>'),
        "/docs": html("Docs", f'<main><h1>Docs</h1><p>{words("docs", 80)}</p><a href="/manual.pdf">Manual (PDF)</a></main>'),
        # Noindexed and client-rendered: it cannot be cited, so RND reports no content gap on it.
        "/onboarding": Response(body="<!doctype html><html lang='en'><head><title>Onboarding</title>"
                                "<meta name='robots' content='noindex'></head><body>"
                                "<div id='root'></div><canvas id='c'></canvas>"
                                "<script src='/app.js'></script></body></html>"),
    })


def slow_navigation_site() -> Site:
    """A page whose parser-blocking script never returns in time: DOM-ready is not reached."""
    return Site({
        "/robots.txt": robots("User-agent: *\nAllow: /\n"),
        # Content first, then a script that never returns in time: the DOM holds the content, but the
        # page never reaches DOM-ready. This is the shape seen on a real client homepage.
        "/": html("Slow", f'<main><h1>Slow page</h1><p>{words("slow", 60)}</p></main>'
                          '<script src="/blocking.js"></script>'),
        "/blocking.js": Response(body="window.x = 1;", content_type="application/javascript", delay_s=4.0),
    })


RND_SCENARIOS: dict[str, Scenario] = {s.name: s for s in [
    Scenario("rnd_slow_navigation", "A page that does not reach DOM-ready within the render timeout.",
             slow_navigation_site, {**FAST_RND, "render_enabled": True, "render_timeout_s": 1.0,
                                    "render_budget": 1, "render_settle_ms": 200}),
    Scenario("rnd_walls", "Redirect to login, cookie wall in place of content, age gate, paywalls with and without "
             "structured data, and a normal page with a cookie banner.", walls_site, {**FAST_RND, "render_enabled": False}),
    Scenario("rnd_nontext_payload", "Canvas, iframe, banner images without alt, 1 MB+ HTML with late main content, "
             "boilerplate-heavy and <main>-less pages, and a PDF link.", nontext_site, {**FAST_RND, "render_enabled": False}),
]}
