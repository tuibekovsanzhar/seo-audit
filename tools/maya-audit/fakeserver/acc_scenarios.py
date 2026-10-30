"""Scripted websites for the ACC checks.

`probe_user_agents_expected` says whether AI-bot user agents may reach the
server at all (only on ownership-verified sites), checked from the server's own
request log.
"""

from __future__ import annotations

from .scenarios import CLOUDFLARE_CHALLENGE_BODY, Scenario, page, robots, sitemap
from .server import RequestSeen, Response, Site

TOKEN = "maya-verify-7f3a"
VERIFY_META = f'<meta name="maya-site-verification" content="{TOKEN}">'
FILLER = "<p>" + " ".join(["Maya audits whether AI answer engines can reach and read this page."] * 12) + "</p>"
APP_HEADERS = {"X-Powered-By": "FakeApp/1.0"}

FAST_ACC = {
    "request_delay_s": 0.0,
    "request_timeout_s": 2.0,
    "robots_sample_interval_s": 0.05,
    "probe_retry_cooldown_s": 0.0,
    "refetch_delay_s": 0.0, "prf_round_gap_s": 0.0,
    "render_enabled": False,
}


def _content_site(extra_routes: dict | None = None, verify: bool = True, intercept=None) -> Site:
    head = VERIFY_META if verify else ""
    routes = {
        "/robots.txt": robots("User-agent: *\nAllow: /\n\nSitemap: {base}/sitemap.xml\n"),
        "/sitemap.xml": sitemap("/", "/pricing", "/docs/a"),
        "/": page("Home", "/pricing", "/docs/a", "/docs/b", extra=FILLER, head=head, headers=APP_HEADERS),
        "/pricing": page("Pricing", "/", extra=FILLER, headers=APP_HEADERS),
        "/docs/a": page("Doc A", "/docs/b", extra=FILLER, headers=APP_HEADERS),
        "/docs/b": page("Doc B", "/", extra=FILLER, headers=APP_HEADERS),
    }
    routes.update(extra_routes or {})
    return Site(routes, intercept=intercept)


def _robots_rules() -> Site:
    text = (
        "User-agent: *\n"               # 1
        "Disallow: /admin/\n"           # 2
        "\n"                            # 3
        "User-agent: GPTBot\n"          # 4
        "User-agent: ClaudeBot\n"       # 5
        "User-agent: Google-Extended\n" # 6
        "User-agent: CCBot\n"           # 7
        "Disallow: /\n"                 # 8
        "\n"                            # 9
        "User-agent: OAI-SearchBot\n"   # 10
        "Disallow: /pricing\n"          # 11
        "Crawl-delay: 120\n"            # 12
        "\n"                            # 13
        "User-agent: PerplexityBot\n"   # 14
        "Disallow: /\n"                 # 15
        "\n"                            # 16
        "User-agent: ChatGPT-User\n"    # 17
        "Disallow: /docs/\n"            # 18
        "\n"                            # 19
        "Sitemap: {base}/sitemap.xml\n" # 20
    )
    return _content_site({
        "/robots.txt": robots(text),
        "/": page("Home", "/pricing", "/docs/a", "/admin/panel", "/blog/post-1", "/blog/post-2", extra=FILLER),
        "/admin/panel": page("Admin"),
        "/blog/post-1": page("Post 1", extra=FILLER),
        "/blog/post-2": page("Post 2", extra=FILLER),
    }, verify=False)


def _meta_controls() -> Site:
    def meta(name, content):
        return f'<meta name="{name}" content="{content}">'

    nosnippet_body = "<main><div data-nosnippet>" + FILLER + "</div></main>"
    return _content_site({
        "/": page("Home", "/noindex", "/nosnippet-header", "/maxsnippet0", "/maxsnippet20", "/datanosnippet",
                  "/bing-noarchive", "/tag/a", "/tag/b", "/tag/featured", "/cart", "/terms.pdf", "/brochure.pdf", extra=FILLER),
        "/pricing": page("Pricing", "/cart", extra=FILLER),
        "/noindex": page("Noindex", extra=FILLER, head=meta("robots", "noindex, follow")),
        "/nosnippet-header": page("Nosnippet", extra=FILLER, headers={"X-Robots-Tag": "googlebot: nosnippet"}),
        "/maxsnippet0": page("Max snippet 0", extra=FILLER, head=meta("robots", "max-snippet:0")),
        "/maxsnippet20": page("Max snippet 20", extra=FILLER, head=meta("googlebot", "max-snippet:20")),
        "/datanosnippet": page("Data nosnippet", extra=nosnippet_body),
        "/bing-noarchive": page("Bing noarchive", extra=FILLER, head=meta("bingbot", "noarchive")),
        "/tag/a": page("Tag A", extra=FILLER, head=meta("robots", "noindex")),
        "/tag/b": page("Tag B", extra=FILLER, head=meta("robots", "noindex")),
        "/tag/featured": page("Featured tag", extra=FILLER, head=meta("robots", "noindex")),
        "/cart": page("Cart", extra=FILLER, head=meta("robots", "noindex")),
        # A PDF can only be withheld through its response header.
        "/terms.pdf": Response(200, "%PDF-1.4 fake", {"X-Robots-Tag": "noindex"}, content_type="application/pdf"),
        "/brochure.pdf": Response(200, "%PDF-1.4 fake", content_type="application/pdf"),
    }, verify=False)


def _waf(site: Site, request: RequestSeen) -> Response | None:
    ua = request.user_agent
    if "OAI-SearchBot" in ua or "PerplexityBot" in ua:
        return Response(403, CLOUDFLARE_CHALLENGE_BODY, {"cf-mitigated": "challenge", "server": "cloudflare"})
    if "ChatGPT-User" in ua:
        return Response(429, "Too Many Requests", {"Retry-After": "3600"}, content_type="text/plain")
    if "Claude-SearchBot" in ua and request.path not in ("/robots.txt", "/sitemap.xml"):
        return Response(200, "<html><head><title>Home</title></head><body><p>Hello</p></body></html>")
    if "bingbot" in ua.lower() and request.path not in ("/robots.txt", "/sitemap.xml"):
        # Same amount of text, different page: a bot-specific version of the site.
        return page("Welcome, crawler", extra=FILLER.replace("Maya audits", "This crawler edition"))
    if "Perplexity-User" in ua:
        seen = site.state.setdefault("perplexity_user", set())
        if request.path not in seen:
            seen.add(request.path)
            return Response(429, "slow down", {"Retry-After": "0"}, content_type="text/plain")
    return None


OTHER_TEXT = "<p>" + " ".join(["Completely different wording served only to one crawler, about other things."] * 12) + "</p>"
BEFORE_TEXT = "<p>" + " ".join(["The spring collection launched this week with new colours and sizes."] * 12) + "</p>"
AFTER_TEXT = "<p>" + " ".join(["Winter pricing now applies across every plan we sell today."] * 12) + "</p>"


def _waf_v2(site: Site, request: RequestSeen) -> Response | None:
    """ACC-4 v2 cases: a bot-only 404, a bot-only redirect, same title with different text, and a page that
    changes after the first probe (so only a fresh browser baseline tells change from cloaking)."""
    ua, path = request.user_agent, request.path
    if path == "/changing":
        if request.headers.get("x-maya-probe"):
            seen = site.state.setdefault("changing_probes", 0)
            site.state["changing_probes"] = seen + 1
            return page("Changing", extra=BEFORE_TEXT if seen == 0 else AFTER_TEXT, headers=APP_HEADERS)
        return page("Changing", extra=BEFORE_TEXT, headers=APP_HEADERS)
    if path in ("/robots.txt", "/sitemap.xml"):
        return None
    if "MistralAI-User" in ua and path == "/pricing":
        return Response(404, "<html><head><title>Not found</title></head><body>Not found</body></html>")
    if "Amazonbot" in ua:
        return Response(301, "", {"Location": "/bot-landing"})
    if "Applebot" in ua and path == "/docs/a":
        return page("Doc A", extra=OTHER_TEXT, headers=APP_HEADERS)
    return None


def _robots_flaky() -> Site:
    def handler(site: Site, request: RequestSeen) -> Response:
        site.state["robots"] = site.state.get("robots", 0) + 1
        if site.state["robots"] == 2:
            return Response(503, "Service Unavailable", content_type="text/plain")
        return robots("User-agent: *\nAllow: /\n")
    return _content_site({"/robots.txt": handler}, verify=False)


def _robots_html() -> Site:
    return _content_site({"/robots.txt": Response(200, "<!doctype html><html><title>Home</title></html>")}, verify=False)


def _robots_huge() -> Site:
    filler = "# padding line to push robots.txt past 500 KiB\n" * 13000
    return _content_site({"/robots.txt": robots("User-agent: *\nAllow: /\n" + filler)}, verify=False)


def _llms() -> Site:
    return _content_site({
        "/llms.txt": Response(200, "# Example Co\n\n> What we do, for language models.\n", content_type="text/markdown"),
    }, verify=False)


def _crawl_delay_capped() -> Site:
    return _content_site({"/robots.txt": robots("User-agent: Maya-Audit\nCrawl-delay: 2\n")}, verify=False)


ACC_SCENARIOS: dict[str, Scenario] = {s.name: s for s in [
    Scenario("acc_ai_friendly", "Verified site, open robots.txt, no page controls, no WAF.",
             lambda: _content_site(), {**FAST_ACC, "site_verification_token": TOKEN, "key_pages": ("/pricing",)}),
    Scenario("acc_robots_rules", "robots.txt blocks training bots, PerplexityBot, OAI-SearchBot on /pricing, "
             "ChatGPT-User on /docs/, with Crawl-delay: 120 for OAI-SearchBot.",
             _robots_rules, FAST_ACC, must_not_request=("/admin/",)),
    Scenario("acc_meta_controls", "Pages with noindex, nosnippet, max-snippet, data-nosnippet, and bingbot noarchive.",
             _meta_controls, {**FAST_ACC, "key_pages": ("/tag/featured",)}),
    Scenario("acc_waf_verified", "Ownership-verified site whose WAF challenges, rate-limits, and degrades bot user agents.",
             lambda: _content_site(intercept=_waf), {**FAST_ACC, "site_verification_token": TOKEN, "key_pages": ("/pricing",)}),
    Scenario("acc_waf_v2", "Verified site: a 404 only for MistralAI-User, a redirect only for Amazonbot, same "
             "title but different text for Applebot, and a page that changes after the first probe.",
             lambda: _content_site({"/changing": page("Changing", extra=BEFORE_TEXT, headers=APP_HEADERS),
                                    "/bot-landing": page("Bot landing", extra=FILLER)}, intercept=_waf_v2),
             {**FAST_ACC, "site_verification_token": TOKEN, "key_pages": ("/changing",), "max_probe_requests": 400}),
    Scenario("acc_waf_not_owned", "Same WAF, but ownership is not verified: probes must not run.",
             lambda: _content_site(verify=False, intercept=_waf), FAST_ACC),
    Scenario("acc_robots_flaky", "robots.txt answers 200, then 503, then 200.", _robots_flaky, FAST_ACC),
    Scenario("acc_robots_html", "robots.txt returns an HTML page.", _robots_html, FAST_ACC),
    Scenario("acc_robots_huge", "robots.txt is larger than 500 KiB.", _robots_huge, FAST_ACC),
    Scenario("acc_llms_txt", "An llms.txt file exists.", _llms, FAST_ACC),
    Scenario("acc_crawl_delay_capped", "robots.txt asks Maya-Audit for Crawl-delay: 2 against a 0.3 s cap.",
             _crawl_delay_capped, {**FAST_ACC, "max_crawl_delay_s": 0.3, "robots_samples": 1}),
]}
