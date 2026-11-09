"""DECISIONS 328: the sitemap check starts right after the crawl, beside access, index, structure and rendering, and is
joined before the performance rounds: the same requests and the same rows, only earlier; its own row of the step
timing table (a lane), so the steps it runs beside keep their own counts. Offline: an in-memory site."""
from __future__ import annotations

import threading

import httpx

from maya_audit.audit import run_audit
from maya_audit.config import CrawlConfig
from maya_audit.fetcher import Fetcher
from test_deadline_hosted_hardening import QUIET

H = "https://slow.test"
HTML = {"content-type": "text/html; charset=utf-8"}
LISTED = [f"/p{i}" for i in range(30)]


def _respond(request):
    path = request.url.path
    if path == "/robots.txt":
        return httpx.Response(200, text=f"User-agent: *\nAllow: /\nSitemap: {H}/sitemap.xml\n")
    if path == "/sitemap.xml":
        return httpx.Response(200, headers={"content-type": "application/xml"}, text=(
            '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            + "".join(f"<url><loc>{H}{u}</loc></url>" for u in LISTED) + "</urlset>"))
    links = "".join(f'<a href="/p{i}">p{i}</a>' for i in range(4))
    return httpx.Response(200, headers=HTML, text=(f'<!doctype html><html lang="en"><head><title>{path}</title></head><body>'
                                                    f'<main><h1>{path}</h1><p>{"Some text. " * 40}</p>{links}</main></body></html>'))


def _audit():
    cfg = CrawlConfig(**{**QUIET, "max_pages": 5, "sitemap_check_max": 25})
    return run_audit(H + "/", cfg, httpx.MockTransport(_respond))


def test_the_sitemap_check_runs_beside_the_other_steps_with_its_own_row():
    out = _audit()
    log = out.result.requests
    checks = [r for r in log if r.purpose == "sitemap_check"]
    assert len(checks) == 25  # the same requests as before: the cap, every one asked
    rows = out.result._sitemap_check.rows
    assert sorted(r["url"] for r in rows) == sorted(r.url for r in checks)
    steps = {s["step"]: s for s in out.result.steps}
    row = steps["sitemap_check"]
    assert row["requests"] == 25 and row["beside"] == ["access", "index", "structure", "render"]
    # the steps it ran beside count only their own requests
    own = sum(s["requests"] for s in out.result.steps if s["step"] not in ("sitemap_check",))
    assert own + 25 >= len([r for r in log if r.purpose not in ("render_subresource",)]) - 1
    order = [s["step"] for s in out.result.steps]
    # joined before performance; DECISIONS 330: llms.txt's links to this site on a lane before it, other sites after it
    assert order.index("sitemap_check") < order.index("performance") < order.index("llms_links_other_sites")
    assert order.index("llms_links") < order.index("performance")


def test_the_check_starts_before_the_audits_own_steps_end():
    out = _audit()
    log = out.result.requests
    first_check = min(r.started_mono for r in log if r.purpose == "sitemap_check")
    crawl_done = max(r.ended_mono for r in log if r.purpose == "page")
    later_own = [r for r in log if r.purpose not in ("page", "sitemap_check", "render_subresource", "robots", "sitemap")
                 and r.started_mono >= crawl_done]
    assert first_check >= crawl_done
    assert later_own and first_check <= max(r.started_mono for r in later_own)  # it did not wait for them to end


def test_a_lane_counts_its_own_requests_waiting_and_time_limit_refusals():
    fetcher = Fetcher("Maya-Audit/test", 5.0, 0.0, transport=httpx.MockTransport(lambda r: httpx.Response(200, text="ok")))
    fetcher.get("https://a.test/", "page", 1000)

    def side():
        fetcher.set_lane("sitemap_check")
        fetcher.get("https://a.test/x", "sitemap_check", 1000)
        fetcher.hit_deadline()
        fetcher.set_lane(None)
    thread = threading.Thread(target=side)
    thread.start()
    thread.join()
    assert fetcher.own_requests == 1 and fetcher.own_deadline_hits == 0
    assert fetcher.lanes["sitemap_check"]["requests"] == 1 and fetcher.lanes["sitemap_check"]["deadline_hits"] == 1
    row = fetcher.lane_row("sitemap_check", "2026-11-08T00:00:00+00:00", 0.0, ["access"], ended_mono=1.5)
    assert row["seconds"] == 1.5 and row["requests"] == 1 and fetcher.steps[-1] is row
