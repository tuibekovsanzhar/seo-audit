"""Scripted websites, one per case the INT gates must handle.

Each scenario declares what the site owner forbids (`must_not_request`), written
independently of Maya's robots.txt parser, so the server-side check is not
circular.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .server import RequestSeen, Response, Site


def page(title: str, *links: str, extra: str = "", head: str = "", headers: dict | None = None) -> Response:
    anchors = "".join(f'<a href="{href}">{href}</a>\n' for href in links)
    return Response(
        body=f"<!doctype html><html><head><title>{title}</title>{head}</head><body><h1>{title}</h1>\n{anchors}{extra}</body></html>",
        headers=dict(headers or {}),
    )


def robots(text: str, status: int = 200) -> Response:
    return Response(status=status, body=text, content_type="text/plain; charset=utf-8")


def sitemap(*paths: str) -> Response:
    urls = "".join(f"<url><loc>{{base}}{p}</loc></url>" for p in paths)
    return Response(
        body=f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>',
        content_type="application/xml",
    )


CLOUDFLARE_CHALLENGE_BODY = (
    "<!DOCTYPE html><html><head><title>Just a moment...</title></head><body>"
    "<noscript>Enable JavaScript and cookies to continue</noscript>"
    '<script src="/cdn-cgi/challenge-platform/h/b/orchestrate/chl_page/v1"></script>'
    "</body></html>"
)


@dataclass
class Scenario:
    name: str
    description: str
    build: Callable[[], Site]
    config: dict = field(default_factory=dict)
    start_path: str = "/"
    must_not_request: tuple[str, ...] = ()


def _healthy() -> Site:
    return Site({
        "/robots.txt": robots("User-agent: *\nDisallow: /private/\n\nSitemap: {base}/sitemap.xml\n"),
        "/sitemap.xml": sitemap("/", "/about", "/landing-orphan"),
        "/": page("Home", "/about", "/blog/post-1", "/blog/post-2", "/private/admin"),
        "/about": page("About", "/"),
        "/blog/post-1": page("Post 1", "/blog/post-2"),
        "/blog/post-2": page("Post 2", "/"),
        "/private/admin": page("Admin"),
        "/landing-orphan": page("Campaign landing page"),
    })


def _cloudflare_challenge() -> Site:
    challenge = Response(
        status=403,
        body=CLOUDFLARE_CHALLENGE_BODY,
        headers={"cf-mitigated": "challenge", "server": "cloudflare", "cf-ray": "8c1a2b3c4d5e6f70-LHR"},
    )
    return Site({"/robots.txt": robots("User-agent: *\nAllow: /\n")}, fallback=challenge)


def _forbidden_mix() -> Site:
    jsd = '<script src="/cdn-cgi/challenge-platform/scripts/jsd/main.js"></script>'
    return Site({
        "/robots.txt": robots("User-agent: *\nAllow: /\n"),
        "/": page("Home", "/members", "/docs", "/pricing"),
        "/members": Response(status=403, body="<html><title>Forbidden</title><body>Forbidden</body></html>"),
        "/docs": page("Docs", "/docs/a", "/docs/b"),
        "/docs/a": page("Doc A", extra=jsd),  # normal page with an injected script marker: must stay ok
        "/docs/b": page("Doc B"),
        # Challenge page body served with 200 and no header: only a signature gives it away.
        "/pricing": Response(status=200, body=CLOUDFLARE_CHALLENGE_BODY),
    })


def _rate_limited() -> Site:
    def limited(path_title: str, *links: str):
        def handler(site: Site, request: RequestSeen) -> Response:
            site.state["pages"] = site.state.get("pages", 0) + 1
            if site.state["pages"] > 3:
                return Response(status=429, body="Too Many Requests", headers={"Retry-After": "120"}, content_type="text/plain")
            return page(path_title, *links)
        return handler

    routes = {"/robots.txt": robots("User-agent: *\nAllow: /\n"), "/": limited("Home", *[f"/p{i}" for i in range(1, 7)])}
    routes.update({f"/p{i}": limited(f"P{i}") for i in range(1, 7)})
    return Site(routes)


def _rate_limited_then_recovers() -> Site:
    """Two pages refuse with 429 (including on retry), then the rest of the site is fine.

    Exercises adaptive backoff: the gap between requests must widen once per rate-limited page and
    stay widened afterwards, rather than snapping back to the configured pace once the site
    recovers. Each flaky path refuses twice so that Maya's single retry also fails and the page is
    classified rate-limited, which is what triggers a widening.
    """
    def flaky(path: str):
        def handler(site: Site, request: RequestSeen) -> Response:
            key = f"hits{path}"
            site.state[key] = site.state.get(key, 0) + 1
            if site.state[key] <= 2:
                return Response(status=429, body="slow down", headers={"Retry-After": "0"},
                                content_type="text/plain")
            return page("Recovered")
        return handler

    return Site({
        "/robots.txt": robots("User-agent: *\nAllow: /\n"),
        "/": page("Home", "/a", "/b", "/c"),
        "/a": flaky("/a"),
        "/b": flaky("/b"),
        "/c": page("C"),
    })


def _rate_limited_slow_drip() -> Site:
    """Every page refuses with a 1-second Retry-After, forever.

    Each refusal is individually short enough to honour, so neither the Retry-After ceiling nor the
    consecutive-refusal count stops the crawl. Only the cumulative cooldown budget does — the case
    where a site refuses politely but relentlessly.
    """
    def refuse(site: Site, request: RequestSeen) -> Response:
        return Response(status=429, body="slow down", headers={"Retry-After": "1"},
                        content_type="text/plain")

    return Site({
        "/robots.txt": robots("User-agent: *\nAllow: /\n"),
        "/": page("Home", "/a", "/b", "/c"),
        "/a": refuse,
        "/b": refuse,
        "/c": refuse,
    })


def _rate_limited_transient() -> Site:
    def flaky(site: Site, request: RequestSeen) -> Response:
        site.state["flaky"] = site.state.get("flaky", 0) + 1
        if site.state["flaky"] == 1:
            return Response(status=429, body="slow down", headers={"Retry-After": "0"}, content_type="text/plain")
        return page("Flaky but fine")

    return Site({
        "/robots.txt": robots("User-agent: *\nAllow: /\n"),
        "/": page("Home", "/flaky"),
        "/flaky": flaky,
    })


def _robots_block() -> Site:
    return Site({
        "/robots.txt": robots("User-agent: *\nDisallow: /\n"),
        "/": page("Home", "/about"),
        "/about": page("About"),
    })


def _robots_503() -> Site:
    return Site({
        "/robots.txt": robots("Service Unavailable", status=503),
        "/": page("Home", "/about"),
        "/about": page("About"),
    })


def _robots_maya_group() -> Site:
    return Site({
        "/robots.txt": robots(
            "User-agent: *\nDisallow: /\n\n# Maya gets its own group, so the * group no longer applies to it\n"
            "User-agent: Maya-Audit\nDisallow: /private/\n"
        ),
        "/": page("Home", "/public", "/private/x"),
        "/public": page("Public"),
        "/private/x": page("Private"),
    })


def _page_cap() -> Site:
    routes = {"/robots.txt": robots("User-agent: *\nAllow: /\n"), "/": page("Home", *[f"/item/{i}" for i in range(1, 31)])}
    routes.update({f"/item/{i}": page(f"Item {i}", f"/item/{i + 1}" if i < 30 else "/") for i in range(1, 31)})
    return Site(routes)


def _transport_errors() -> Site:
    return Site({
        "/robots.txt": robots("User-agent: *\nAllow: /\n"),
        "/": page("Home", "/ok", "/slow", "/drop"),
        "/ok": page("OK"),
        "/slow": Response(body="<html>too late</html>", delay_s=3.0),
        "/drop": Response(drop_connection=True),
    })


def _time_limit() -> Site:
    routes = {"/robots.txt": robots("User-agent: *\nAllow: /\n"), "/": page("Home", *[f"/s{i}" for i in range(1, 11)])}
    routes.update({f"/s{i}": Response(body=f"<html><title>S{i}</title></html>", delay_s=0.4) for i in range(1, 11)})
    return Site(routes)


def _start_redirect() -> Site:
    return Site({
        "/robots.txt": robots("User-agent: *\nAllow: /\n"),
        "/": Response(status=301, headers={"Location": "/home"}, body=""),
        "/home": page("Home", "/about"),
        "/about": page("About"),
    })


FAST = {"request_delay_s": 0.0, "request_timeout_s": 2.0}

SCENARIOS: dict[str, Scenario] = {s.name: s for s in [
    Scenario("healthy", "Normal site: one robots.txt-disallowed path, one sitemap-only page.",
             _healthy, {**FAST, "key_pages": ("/", "/about")}, must_not_request=("/private/",)),
    Scenario("cloudflare_challenge", "Every page returns a Cloudflare-style 403 challenge with cf-mitigated: challenge.",
             _cloudflare_challenge, FAST),
    Scenario("forbidden_mix", "One plain 403 page and one 200 page whose body is a challenge (signature only).",
             _forbidden_mix, FAST),
    Scenario("rate_limited", "The fourth page request onward gets 429 with Retry-After: 120.",
             _rate_limited, FAST),
    Scenario("rate_limited_transient", "One 429 with Retry-After: 0, then the page succeeds on retry.",
             _rate_limited_transient, FAST),
    Scenario("rate_limited_then_recovers", "Two 429s with Retry-After: 0, then the site recovers.",
             _rate_limited_then_recovers, FAST),
    Scenario("rate_limited_slow_drip", "Every page 429s with a short Retry-After, indefinitely.",
             _rate_limited_slow_drip, FAST),
    Scenario("robots_block", "robots.txt disallows everything for all user agents.",
             _robots_block, FAST, must_not_request=("/about", "/sitemap.xml")),
    Scenario("robots_503", "robots.txt returns 503, which RFC 9309 treats as complete disallow.",
             _robots_503, FAST, must_not_request=("/about", "/sitemap.xml")),
    Scenario("robots_maya_group", "robots.txt blocks * but gives Maya-Audit its own group that only blocks /private/.",
             _robots_maya_group, FAST, must_not_request=("/private/",)),
    Scenario("page_cap", "31 linked pages, crawled with a 10-page cap.",
             _page_cap, {**FAST, "max_pages": 10}),
    Scenario("transport_errors", "One page times out, one drops the connection.",
             _transport_errors, {**FAST, "request_timeout_s": 1.0}),
    Scenario("time_limit", "Ten slow pages (0.4 s each) against a 1 s time limit.",
             _time_limit, {**FAST, "time_limit_s": 1.0}),
    Scenario("start_redirect", "The start URL 301-redirects to /home.",
             _start_redirect, FAST),
]}

