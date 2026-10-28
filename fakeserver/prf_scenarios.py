"""Scripted websites and fake Google APIs for the PRF checks (performance and fetch reliability)."""

from __future__ import annotations

import json

from .scenarios import CLOUDFLARE_CHALLENGE_BODY, Scenario, robots
from .server import RequestSeen, Response, Site

FAST_PRF = {"request_delay_s": 0.0, "request_timeout_s": 1.0, "robots_sample_interval_s": 0.05,
            "probe_retry_cooldown_s": 0.0, "refetch_delay_s": 0.0, "prf_round_gap_s": 0.0, "render_enabled": False,
            # Scaled down so the test runs in seconds: 0.3 s instead of the spec's 1.5 s (same rule).
            "prf_slow_median_s": 0.3}

PAGES = ["/", "/slow", "/slow-once", "/flaky", "/fails-twice", "/hang-once", "/reset-once", "/always-500", "/blocked",
         "/blog/a", "/blog/b", "/blog/c"]


def html(title: str, head: str = "") -> str:
    links = " ".join(f'<a href="{p}">{p}</a>' for p in PAGES)
    return (f"<!doctype html><html lang='en'><head><title>{title}</title>{head}</head><body><nav>{links}</nav>"
            f"<main><h1>{title}</h1><p>Content for {title}.</p></main></body></html>")


def _nth(site: Site, request: RequestSeen) -> int:
    """1-based count of GET requests for this path, as the server saw them."""
    counts = site.state.setdefault("counts", {})
    counts[request.route_path] = counts.get(request.route_path, 0) + 1
    return counts[request.route_path]


def prf_site(verification_token: str | None = None) -> Site:
    verify = f'<meta name="maya-site-verification" content="{verification_token}">' if verification_token else ""

    def slow(site, request):
        return Response(body=html("Slow"), delay_s=0.45)

    def slow_once(site, request):  # one slow sample must not make a page "slow": the median decides
        return Response(body=html("Slow once"), delay_s=0.45 if _nth(site, request) == 1 else 0.0)

    def flaky(site, request):  # 200, 500, 200
        return Response(500, "error") if _nth(site, request) == 2 else Response(body=html("Flaky"))

    def fails_twice(site, request):  # the crawl fetch and the IDX-1 refetch fail; the PRF rounds work
        return Response(503, "busy") if _nth(site, request) <= 2 else Response(body=html("Fails twice"))

    def hang_once(site, request):  # the crawl fetch times out (1 s limit); every later attempt works
        return Response(body=html("Hang once"), delay_s=1.5 if _nth(site, request) == 1 else 0.0)

    def reset_once(site, request):
        return Response(drop_connection=True) if _nth(site, request) == 1 else Response(body=html("Reset once"))

    return Site({
        "/robots.txt": robots("User-agent: *\nAllow: /\n"),
        "/": Response(body=html("Home", verify)),
        "/slow": slow,
        "/slow-once": slow_once,
        "/flaky": flaky,
        "/fails-twice": fails_twice,
        "/hang-once": hang_once,
        "/reset-once": reset_once,
        "/always-500": Response(500, "error"),
        "/blocked": Response(403, CLOUDFLARE_CHALLENGE_BODY, {"cf-mitigated": "challenge"}),
        "/blog/a": Response(body=html("A")),
        "/blog/b": Response(body=html("B")),
        "/blog/c": Response(body=html("C")),
    })


def healthy_site() -> Site:
    return Site({
        "/robots.txt": robots("User-agent: *\nAllow: /\n"),
        "/": Response(body="<html><body><a href='/a'>a</a> <a href='/b'>b</a></body></html>"),
        "/a": Response(body="<html><body>a</body></html>"),
        "/b": Response(body="<html><body>b</body></html>"),
    })


def psi_api(key: str = "psi-test-key-123") -> Site:
    """Fake PageSpeed Insights v5 runPagespeed. Lab values change per run so the median is exercised."""

    def run(site: Site, request: RequestSeen) -> Response:
        if request.headers.get("x-goog-api-key") != key:  # A26: the key comes in a header, never the address
            return Response(400, json.dumps({"error": {"message": "API key not valid"}}), content_type="application/json")
        n = _nth(site, request)
        lcp = [3000.0, 2000.0, 2500.0][(n - 1) % 3]
        body = {"lighthouseResult": {
            "lighthouseVersion": "12.0.0", "fetchTime": "2026-09-14T10:00:00.000Z", "finalUrl": request.query.get("url"),
            "audits": {"largest-contentful-paint": {"numericValue": lcp},
                       "cumulative-layout-shift": {"numericValue": 0.02},
                       "total-blocking-time": {"numericValue": 150.0},
                       "server-response-time": {"numericValue": 420.0}},
            # Present in real responses; Maya must never read or show it.
            "categories": {"performance": {"score": 0.42}}}}
        return Response(body=json.dumps(body), content_type="application/json")

    return Site({"/pagespeedonline/v5/runPagespeed": run})


def crux_api(base_of_site: callable, key: str = "psi-test-key-123") -> Site:
    """Fake CrUX API queryRecord: /slow has no URL-level record (origin fallback); / has its own record."""

    def query(site: Site, request: RequestSeen) -> Response:
        if request.headers.get("x-goog-api-key") != key:  # A26: the key comes in a header, never the address
            return Response(400, "{}", content_type="application/json")
        body = json.loads(request.body or b"{}")
        base = base_of_site()
        good = {"largest_contentful_paint": {"percentiles": {"p75": 1800}},
                "interaction_to_next_paint": {"percentiles": {"p75": 120}},
                "cumulative_layout_shift": {"percentiles": {"p75": "0.05"}},
                "experimental_time_to_first_byte": {"percentiles": {"p75": 600}}}
        poor = {"largest_contentful_paint": {"percentiles": {"p75": 4600}},
                "interaction_to_next_paint": {"percentiles": {"p75": 180}},
                "cumulative_layout_shift": {"percentiles": {"p75": "0.31"}},
                "experimental_time_to_first_byte": {"percentiles": {"p75": 1900}}}
        period = {"firstDate": {"year": 2026, "month": 8, "day": 15}, "lastDate": {"year": 2026, "month": 9, "day": 11}}
        if body.get("url") == base + "/":
            return Response(body=json.dumps({"record": {"key": body, "metrics": good, "collectionPeriod": period}}),
                            content_type="application/json")
        if body.get("origin") == base:
            return Response(body=json.dumps({"record": {"key": body, "metrics": poor, "collectionPeriod": period}}),
                            content_type="application/json")
        return Response(404, json.dumps({"error": {"code": 404, "message": "chrome ux report data not found"}}),
                        content_type="application/json")

    return Site({"/v1/records:queryRecord": query})


PRF_SCENARIOS: dict[str, Scenario] = {s.name: s for s in [
    Scenario("prf_mixed", "A slow key page, a page slow only once, a key page that fails once in three, a page that "
             "fails on the crawl and the refetch but then works, one that times out once, one that drops the connection "
             "once, a persistent 500, a challenge page, and a template.",
             prf_site, {**FAST_PRF, "key_pages": ("/slow", "/slow-once", "/flaky"), "prf_template_slots": 1}),
    Scenario("prf_healthy", "Three fast pages and no failures.", healthy_site, FAST_PRF),
]}
