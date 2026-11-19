"""T1 rendering for the RND checks: headless Chromium via Playwright (optional dependency).

Safety rules enforced on every request the browser tries to make:
- only GET requests leave the browser (anything else is aborted);
- the page cannot navigate away (later document navigations are aborted);
- resources on other origins are not loaded unless `render_third_party` is on;
- same-origin resources must be allowed by robots.txt for Maya's user agent.

Every request, allowed or aborted, is recorded. Allowed ones are appended to the
crawl's request log so INT-4 audits them like any other request.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from html import escape
from dataclasses import dataclass, field
from typing import Any

from .analysis import analyze_html
from .config import CrawlConfig
from .directives import noindex_directives
from .fetcher import Fetcher, utc_now
from .models import CrawlResult, FetchClass
from .crawler import load_robots
from .html_links import decode_body, extract_link_edges
from .urls import UnsafeTargetError, detect_templates, normalize_url, origin_of, same_origin, validate_public_target

# Clicks that may reveal content without changing state (RND-3). Links that navigate, submit buttons, and
# anything inside a form are never clicked.
INTERACT_JS = """
(maxClicks) => {
  const re = /\\b(load|show|see|view|read)\\s+more\\b|\\bexpand\\b/i;
  const seen = new Set(); const clicked = [];
  const nodes = document.querySelectorAll('[role="tab"], [aria-expanded="false"], button, [role="button"]');
  for (const el of nodes) {
    if (clicked.length >= maxClicks) break;
    if (seen.has(el) || el.closest('form')) continue;
    if (el.tagName === 'A' && el.getAttribute('href') && !el.getAttribute('href').startsWith('#')) continue;
    if (el.tagName === 'BUTTON' && (el.getAttribute('type') || 'submit').toLowerCase() === 'submit' && el.form) continue;
    const text = (el.innerText || el.getAttribute('aria-label') || '').trim();
    const role = el.getAttribute('role');
    const eligible = (role === 'tab' && el.getAttribute('aria-selected') !== 'true')
      || el.getAttribute('aria-expanded') === 'false' || re.test(text);
    if (!eligible) continue;
    seen.add(el);
    try { el.click(); clicked.push({tag: el.tagName.toLowerCase(), role: role, text: text.slice(0, 60)}); } catch (e) {}
  }
  window.scrollTo(0, document.body ? document.body.scrollHeight : 0);
  return clicked;
}
"""


# Each <h1> of the rendered page with whether it is shown: computed display and visibility of it and every element
# around it, and a box of some size (H15).
# DECISIONS 371: `accessible` says whether a screen reader reads the <h1> (not display:none, visibility:hidden or
# aria-hidden on it or around it); `pattern` names a visually-hidden one ("visually-hidden": clipped, 1px or off-screen;
# "transparent": opacity 0), which is read.
H1_VISIBILITY_JS = """() => Array.from(document.querySelectorAll('h1')).slice(0, 20).map(h => {
  const box = h.getBoundingClientRect();
  let shown = box.width > 0 && box.height > 0, accessible = true, pattern = null;
  for (let e = h; e; e = e.parentElement) {
    const s = getComputedStyle(e);
    if (s.display === 'none' || s.visibility === 'hidden' || s.visibility === 'collapse' || e.getAttribute('aria-hidden') === 'true') { shown = false; accessible = false; }
    if (Number(s.opacity) === 0) { shown = false; pattern = pattern || 'transparent'; }
  }
  const s = getComputedStyle(h);
  const clipped = (s.clip && s.clip !== 'auto') || (s.clipPath && s.clipPath !== 'none');
  if (accessible && (clipped || box.width <= 1 || box.height <= 1 || box.right < 0 || box.bottom < 0)) { shown = false; pattern = 'visually-hidden'; }
  return {text: (h.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 200), visible: shown, accessible: accessible, pattern: pattern};
})"""


def chromium_safety_args() -> list[str]:
    """Keep Chromium's native network resolver from bypassing the Fetcher proxy."""
    return ["--host-resolver-rules=MAP * ~NOTFOUND"]


# The network counts as idle once nothing has been requested or answered for this long (the same
# quiet period Playwright's own "networkidle" uses).
NETWORK_IDLE_QUIET_MS = 500
# Resource types that add nothing to the DOM or its text. They are not fetched; INT-3 counts them.
SKIPPED_RESOURCE_TYPES = frozenset({"image", "media", "font"})
# Sub-resources of one page are fetched by at most this many workers at a time.
RENDER_FETCH_CONCURRENCY = 4
# How often the render loop hands finished fetches back to the browser.
PUMP_MS = 25

WEBSOCKET_BLOCKING_UNAVAILABLE = (
    "WebSocket blocking unavailable: the installed Playwright has no route_web_socket (added in 1.48), so "
    "WebSocket connections opened by a rendered page were not intercepted. Chromium's own name resolver "
    "was still switched off, so a socket could not connect to the site or anywhere else."
)


def configure_websocket_blocking(context: Any) -> bool:
    """Intercept WS/WSS handshakes without waiting for a connection or server response."""
    route_web_socket = getattr(context, "route_web_socket", None)
    if route_web_socket is None:
        # Older supported Playwright builds still get Chromium's resolver rule. The caller records
        # this on the page's render entry so INT-3 can disclose it.
        return False

    # A routed websocket is blocked unless connect_to_server() is called. The handler
    # must return immediately; synchronous close() can wait indefinitely on some servers.
    route_web_socket("**/*", lambda route: None)
    return True


@dataclass
class RenderData:
    mode: str  # "raw_plus_sampled_render" | "raw_html_only"
    reason: str | None
    browser: str | None = None
    budget: int = 0
    order: list[dict[str, Any]] = field(default_factory=list)  # sample with why each URL was chosen
    pages: dict[str, dict[str, Any]] = field(default_factory=dict)
    third_party_loaded: bool = False
    interactions_enabled: bool = True


def choose_render_sample(result: CrawlResult, cfg: CrawlConfig, key_urls: list[str]) -> list[dict[str, Any]]:
    """Spec §8 F8: homepage → user-marked key pages (≤10) → auto-suggested (none yet) → one per template (≥6)
    → backfill with remaining key pages, then remaining templates."""
    # A page the site marks noindex cannot be cited, so it is not worth a render slot (RND skips it too).
    readable = [p for p in result.pages if p.fetch_class == FetchClass.OK and p.status and 200 <= p.status < 300
                and p.analysis is not None and not noindex_directives(p.analysis, p.headers)]
    by_url = {p.url: p for p in readable}
    inlinks: dict[str, int] = {}
    for page in result.pages:
        for edge in page.outlinks:
            inlinks[edge["target"]] = inlinks.get(edge["target"], 0) + 1

    chosen: list[dict[str, Any]] = []
    picked: set[str] = set()

    def add(url: str, why: str) -> bool:
        if url in picked or url not in by_url or len(chosen) >= cfg.render_budget:
            return False
        picked.add(url)
        chosen.append({"url": url, "why": why})
        return True

    home = next((p.url for p in readable if p.depth == 0), None)
    if home:
        add(home, "homepage")
    keys = [u for u in key_urls if u in by_url]
    key_slots = min(cfg.render_key_page_slots, max(0, cfg.render_budget - len(chosen) - cfg.render_template_slots))
    for url in keys[:key_slots]:
        add(url, "user-marked key page")

    templates = detect_templates(list(by_url))
    ranked = sorted(templates.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    represented = {t for t, urls in ranked if any(u in picked for u in urls)}
    remaining_templates = []
    for template, urls in ranked:
        if template in represented:
            continue
        best = max(urls, key=lambda u: (inlinks.get(u, 0), -len(u)))
        remaining_templates.append((template, best))
    for template, url in remaining_templates:
        add(url, f"template {template} ({len(templates[template])} page(s))")

    for url in keys[key_slots:]:  # backfill
        add(url, "user-marked key page (backfill)")
    return chosen


def collect_render_data(fetcher: Fetcher, result: CrawlResult, cfg: CrawlConfig, key_urls: list[str]) -> RenderData:
    data = RenderData(mode="raw_html_only", reason=None, budget=cfg.render_budget,
                      third_party_loaded=cfg.render_third_party, interactions_enabled=cfg.render_interactions)
    if not cfg.render_enabled:
        data.reason = "rendering disabled in configuration"
        return data
    data.order = choose_render_sample(result, cfg, key_urls)
    if not data.order:
        data.reason = "no readable HTML pages to render"
        return data
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError:
        data.reason = "Playwright is not installed (pip install playwright; playwright install chromium)"
        return data

    policy = result.robots_policy_by_origin[result.origin]
    with sync_playwright() as playwright:
        try:
            # HTTP is fulfilled through Fetcher; deny Chromium's native resolver so
            # WebSocket and other non-routed connections cannot leave the process.
            browser = playwright.chromium.launch(
                channel=cfg.render_browser_channel, headless=True,
                args=chromium_safety_args(),
            )
        except PlaywrightError as exc:
            data.reason = f"headless browser could not be launched: {str(exc).splitlines()[0]}"
            return data
        data.mode, data.browser = "raw_plus_sampled_render", f"chromium {browser.version}"
        # Leaving the pool waits for fetches still in flight, so every request is in the log before
        # the render phase ends.
        try:
            with ThreadPoolExecutor(RENDER_FETCH_CONCURRENCY, thread_name_prefix="render-fetch") as pool:
                for item in data.order:
                    fetcher.poll_stop()
                    if fetcher.deadline_mono is not None and time.monotonic() >= fetcher.deadline_mono:
                        data.reason = "overall audit deadline reached before all render samples completed"
                        break
                    data.pages[item["url"]] = _render_one(browser, fetcher, cfg, policy, item["url"],
                                                          PlaywrightError, pool)
        finally:
            browser.close()
    # Videos a page's script loaded (live gap 2): sized like the ones its markup names, for STR-7.
    from .media_sample import size_rendered_videos

    size_rendered_videos(fetcher, result, cfg, data)
    return data


def _render_one(browser, fetcher: Fetcher, cfg: CrawlConfig, policy, url: str, playwright_error,
                pool: ThreadPoolExecutor | None = None) -> dict[str, Any]:
    own_pool = pool is None
    if pool is None:
        pool = ThreadPoolExecutor(RENDER_FETCH_CONCURRENCY, thread_name_prefix="render-fetch")
    fetcher.wait_politely()
    origin = origin_of(url)
    requests: list[dict[str, Any]] = []
    statuses: dict[str, int] = {}
    failures: dict[str, str] = {}
    navigations = {"count": 0}
    request_budget = {"remaining": 100}
    pending: list[tuple[Any, dict[str, Any], Any]] = []  # (route, request row, future) awaiting a response
    activity = {"last": time.monotonic(), "dom_ready": False}
    policies = {origin: policy}
    started_at, t0 = utc_now(), time.monotonic()
    entry: dict[str, Any] = {"url": url, "started_at": started_at}

    context = browser.new_context(user_agent=cfg.user_agent, locale="en-US", service_workers="block",
                                  viewport={"width": 1280, "height": 1600})
    entry["websocket_blocking"] = "blocked" if configure_websocket_blocking(context) else "unavailable"
    page = context.new_page()

    def route(route, request):
        activity["last"] = time.monotonic()
        target, kind, method = request.url, request.resource_type, request.method
        normalized = normalize_url(target) or target
        main_document = request.is_navigation_request() and request.frame == page.main_frame
        if not target.startswith(("http://", "https://")):
            action, reason = "aborted", "only HTTP(S) requests are allowed during rendering"
        elif method != "GET":
            action, reason = "aborted", f"{method} requests are never sent while rendering"
        elif main_document and navigations["count"] >= 1:
            action, reason = "aborted", "navigation away from the audited page"
        elif not same_origin(normalized, origin) and not cfg.render_third_party:
            action, reason = "aborted", "third-party resource not loaded (render_third_party is off)"
        else:
            try:
                validate_public_target(normalized, allow_loopback=not cfg.block_loopback)
                resource_origin = origin_of(normalized)
                if resource_origin not in policies:
                    policies[resource_origin] = load_robots(fetcher, resource_origin, cfg)
                if not policies[resource_origin].decide(cfg.product_token, normalized).allowed:
                    action, reason = "aborted", "robots.txt disallows it for Maya's user agent"
                elif kind in SKIPPED_RESOURCE_TYPES and not main_document:
                    action, reason = "aborted", f"{kind} resources are not fetched while rendering (not needed to read the page's text)"
                elif request_budget["remaining"] <= 0:
                    action, reason = "aborted", "per-page rendering request budget (100) reached"
                else:
                    action, reason = "allowed", None
            except UnsafeTargetError as exc:
                action, reason = "aborted", str(exc)
        if request.is_navigation_request() and request.frame == page.main_frame:
            navigations["count"] += 1
        row = {"url": normalized, "type": kind, "method": method, "action": action, "reason": reason,
               "at": utc_now(), "main_document": main_document}
        if action == "aborted" and kind in SKIPPED_RESOURCE_TYPES and reason.startswith(kind):
            row["skipped_type"] = kind
        requests.append(row)
        if action != "allowed":
            route.abort()
            return
        request_budget["remaining"] -= 1
        # Browser traffic never resolves hosts itself. Every request, including redirect hops, goes
        # through Fetcher, which validates DNS and refuses to follow a redirect automatically.
        if not main_document:
            # Fetched off this thread, a few at a time; answer() hands the response to the browser.
            pending.append((route, row, pool.submit(fetcher.get, normalized, "render_subresource", cfg.max_body_bytes)))
            return
        answer(route, row, fetcher.get(normalized, "render", cfg.max_body_bytes), normalized, True)

    def answer(route, row, response, normalized, main_document):
        row["status"] = response.status
        if response.error or response.status is None:
            row["error"] = response.error or "request failed"
            route.abort()
            return
        if 300 <= response.status < 400 and response.headers.get("location"):
            if main_document:
                current = normalized
                for _ in range(5):
                    next_url = normalize_url(response.headers["location"], current)
                    if not next_url or not same_origin(next_url, origin):
                        row["error"] = "cross-origin redirect blocked by the render safety policy"
                        route.abort()
                        return
                    current = next_url
                    if not policies[origin].decide(cfg.product_token, current).allowed:
                        row["error"] = "redirect target is disallowed by robots.txt"
                        route.abort()
                        return
                    response = fetcher.get(current, "render", cfg.max_body_bytes)
                    if response.error or response.status is None or not (300 <= response.status < 400):
                        break
                if response.status is not None and 300 <= response.status < 400:
                    row["error"] = "too many or unsafe redirects; render stopped"
                    route.abort()
                    return
                final_url = current
            else:
                row["error"] = "resource redirect not followed by safe renderer"
                route.abort()
                return
        else:
            final_url = normalized
        row["final_url"] = final_url
        if main_document and response.body:
            content = decode_body(response.body, response.headers.get("content-type"))
            if final_url != normalized:
                base = f'<base href="{escape(final_url, quote=True)}">'
                lower = content.lower()
                index = lower.find("<head")
                if index >= 0:
                    end = content.find(">", index)
                    content = content[:end + 1] + base + content[end + 1:]
                else:
                    content = base + content
            body = content
        else:
            body = response.body
        safe_headers = {key: response.headers[key] for key in ("content-type", "content-language")
                        if key in response.headers}
        if isinstance(body, str):
            # The page was decoded here (in whatever encoding it came in) and the browser is given text, which it
            # receives as UTF-8 bytes: it is told so, or a page in Windows-1254 would be read in the wrong encoding.
            safe_headers["content-type"] = "text/html; charset=utf-8"
        route.fulfill(status=response.status, headers=safe_headers, body=body)

    def drain() -> None:
        """Give the browser every response that has arrived. Runs on this thread only."""
        for item in [p for p in pending if p[2].done()]:
            pending.remove(item)
            pending_route, row, future = item
            activity["last"] = time.monotonic()
            try:
                answer(pending_route, row, future.result(), row["url"], False)
            except playwright_error:
                row["error"] = "the page had dropped this request before the response arrived"

    def left_ms(limit_ms: float) -> float:
        """`limit_ms`, shortened so a wait never crosses the audit-wide deadline."""
        if fetcher.deadline_mono is None:
            return limit_ms
        return min(limit_ms, max(1, int((fetcher.deadline_mono - time.monotonic()) * 1000)))

    def run_until(done, timeout_ms: float) -> bool:
        """Keep the page running, answering requests as they complete, until done() or the timeout."""
        end = time.monotonic() + timeout_ms / 1000
        while True:
            drain()
            if done():
                return True
            remaining = (end - time.monotonic()) * 1000
            if remaining <= 0:
                return False
            page.wait_for_timeout(min(PUMP_MS, remaining))

    def idle() -> bool:
        return not pending and (time.monotonic() - activity["last"]) * 1000 >= NETWORK_IDLE_QUIET_MS

    page.route("**/*", route)
    page.on("domcontentloaded", lambda _page: activity.__setitem__("dom_ready", True))
    page.on("response", lambda response: statuses.__setitem__(normalize_url(response.url) or response.url, response.status))
    page.on("requestfailed", lambda request: failures.__setitem__(normalize_url(request.url) or request.url,
                                                                   request.failure or "failed"))
    try:
        # Navigate, then *try* to let the network settle. Waiting for "networkidle" as the navigation
        # condition loses the whole render on a resource-heavy site: the first client site with ~100
        # same-origin resources per page timed out on all five renders and produced no rendered view at
        # all. The DOM after scripts have run is worth having even when the network never goes quiet.
        try:
            navigation_ms = left_ms(cfg.render_timeout_s * 1000)
            navigation_end = time.monotonic() + navigation_ms / 1000
            # goto returns once the document has arrived; DOM-ready is waited for below, where the
            # scripts it depends on can be answered as their fetches complete.
            response = page.goto(url, wait_until="commit", timeout=navigation_ms)
            entry["status"] = response.status if response else None
            final_url = normalize_url(page.url) or page.url
            if not same_origin(final_url, origin):
                entry.update(ok=False, error="browser navigation redirected outside the audited origin; render discarded",
                             redirected_to=final_url)
                return entry
            if not run_until(lambda: activity["dom_ready"], (navigation_end - time.monotonic()) * 1000):
                # Even DOM-ready can be out of reach on a heavy page within the timeout. Whatever the
                # browser has built is still worth reading; discarding it loses the rendered view entirely.
                entry["navigation_timed_out"] = (f"Page.goto: Timeout {round(navigation_ms)}ms exceeded "
                                                 "waiting for the DOM to be ready")
        except playwright_error as exc:
            entry["navigation_timed_out"] = str(exc).splitlines()[0][:160]
            entry["status"] = statuses.get(url)
        if run_until(idle, left_ms(cfg.render_settle_ms)):
            entry["network_idle"] = True
        else:
            entry["network_idle"] = False
            entry["settle_note"] = (f"the network had not gone idle after {cfg.render_settle_ms} ms; the DOM was "
                                    "read at that point, so a late-loading part of the page may be missing")
        built = page.content()
        before = analyze_html(built)
        try:
            # Whether each <h1> is shown, as the browser computed it (H15): a class that hides it is seen only here.
            entry["h1_visibility"] = page.evaluate(H1_VISIBILITY_JS)
        except (playwright_error, AttributeError) as exc:  # AttributeError: a page object that cannot run script
            entry["h1_visibility_error"] = str(exc).splitlines()[0][:160]
        # Links to this site in the rendered DOM: what the crawl follows on a site that writes its links with a
        # script (maya_audit.render_discovery), and what IDX-7 counts as a link when it looks for orphans.
        entry["rendered_links"] = [edge for edge in extract_link_edges(built, normalize_url(page.url) or url,
                                                                         cfg.max_anchor_texts_per_target)
                                   if same_origin(edge["target"], origin)][:cfg.max_outlinks_per_page]
        if entry.get("navigation_timed_out") and not before["visible_words"]:
            # Nothing had been built yet: an empty rendered view says nothing and would only muddy the
            # comparison against the raw HTML, so this counts as a failed render.
            entry.update(ok=False, error=entry["navigation_timed_out"] + " (no content had been built yet)")
            return entry
        entry["rendered"] = before
        entry["ok"] = True
        if (cfg.render_interactions and
                (fetcher.deadline_mono is None or time.monotonic() < fetcher.deadline_mono)):
            # Control: the same wait, no click. Without it, text that loads late by itself (timers, lazy
            # sections) would be credited to the click that happened to precede it.
            run_until(lambda: False, left_ms(cfg.render_control_wait_ms))
            control = analyze_html(page.content())
            clicked = page.evaluate(INTERACT_JS, cfg.render_max_clicks)
            activity["last"] = time.monotonic()  # a click's requests have not reached this side yet
            run_until(idle, left_ms(cfg.render_settle_ms))
            run_until(lambda: False, left_ms(cfg.render_control_wait_ms))
            after = analyze_html(page.content())
            entry["interaction"] = {"clicked": clicked, "control": control, "after": after,
                                    "control_wait_ms": cfg.render_control_wait_ms}
    except playwright_error as exc:
        entry.update(ok=False, error=str(exc).splitlines()[0][:300])
    finally:
        entry["elapsed_ms"] = round((time.monotonic() - t0) * 1000, 1)
        for _route, row, _future in pending:
            row["error"] = "still loading when the render ended; the page was read without it"
        for req in requests:
            req["status"] = req.get("status", statuses.get(req["url"]))
            if req["action"] == "allowed" and req["url"] in failures:
                req.setdefault("error", failures[req["url"]])
        entry["requests"] = requests
        context.close()
        if own_pool:
            pool.shutdown(wait=True)
    return entry
