"""Link discovery through the browser, for sites that build their links with JavaScript.

A crawl that reads only the HTML the server sends finds no links on a page whose menu and lists are
written by a script. Such a site looks like a homepage and nothing else, and every page in its sitemap
looks like an orphan. So the homepage and the key pages are also opened in the headless browser during
the crawl. When the rendered page has clearly more links to this site than its raw HTML, the extra links
go into the crawl queue, and the report says that discovery used rendering.

"Clearly more" is a policy (config.RENDER_DISCOVERY_MIN_NEW_LINKS, RENDER_DISCOVERY_MIN_GROWTH): a handful
of links a widget adds do not make a site JavaScript-built. Only the pages named above are rendered, at
most `render_discovery_budget` of them: links that exist only in the rendered view of other pages stay
unseen, which is why IDX-7 does not call a page an orphan on a site where discovery needed rendering.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from .config import RENDER_DISCOVERY_MIN_GROWTH, RENDER_DISCOVERY_MIN_NEW_LINKS, CrawlConfig
from .fetcher import Fetcher


def clearly_more(raw_links: int, new_links: int) -> bool:
    """Whether a rendered page that adds `new_links` targets to `raw_links` raw ones is built with JavaScript."""
    return new_links >= RENDER_DISCOVERY_MIN_NEW_LINKS and new_links >= RENDER_DISCOVERY_MIN_GROWTH * raw_links


class LinkDiscovery:
    def __init__(self, fetcher: Fetcher, cfg: CrawlConfig, earlier: dict[str, Any] | None = None) -> None:
        self.fetcher, self.cfg = fetcher, cfg
        self.rows: list[dict[str, Any]] = list((earlier or {}).get("pages") or [])
        self.reason: str | None = None
        if not cfg.render_enabled:
            self.reason = "rendering is off"
        elif not cfg.render_discovery:
            self.reason = "render-assisted link discovery is off"
        self._manager = self._browser = self._error = None

    def wanted(self, url: str) -> bool:
        return (self.reason is None and len(self.rows) < self.cfg.render_discovery_budget
                and url not in {row["url"] for row in self.rows})

    def _start(self) -> bool:
        if self._browser is not None:
            return True
        try:
            from playwright.sync_api import Error, sync_playwright
        except ImportError:
            self.reason = "Playwright is not installed (pip install playwright; playwright install chromium)"
            return False
        from .render import chromium_safety_args

        self._error = Error
        self._manager = sync_playwright().start()
        try:
            self._browser = self._manager.chromium.launch(channel=self.cfg.render_browser_channel, headless=True,
                                                          args=chromium_safety_args())
        except Error as exc:
            self.reason = f"headless browser could not be launched: {str(exc).splitlines()[0]}"
            self.close()
            return False
        return True

    def extra_links(self, url: str, why: str, raw_targets: set[str], policy) -> list[dict[str, Any]]:
        """Render `url` and return the links to this site that only its rendered view has, when there are
        clearly more of them. Otherwise an empty list. Every attempt is recorded in `rows`."""
        if not self.wanted(url) or not self._start():
            return []
        from .render import _render_one

        entry = _render_one(self._browser, self.fetcher, replace(self.cfg, render_interactions=False), policy, url,
                            self._error)
        row: dict[str, Any] = {"url": url, "why": why, "raw_links": len(raw_targets)}
        self.rows.append(row)
        if not entry.get("ok"):
            row.update(used=False, error=str(entry.get("error") or "the page could not be rendered")[:200])
            return []
        rendered = entry.get("rendered_links") or []
        new = [edge for edge in rendered if edge["target"] not in raw_targets and edge["target"] != url]
        used = clearly_more(len(raw_targets), len(new))
        row.update(rendered_links=len(rendered), links_only_after_rendering=len(new), used=used,
                   sample=[edge["target"] for edge in new[:10]])
        return [{**edge, "rendered": True} for edge in new] if used else []

    def close(self) -> None:
        for thing, method in ((self._browser, "close"), (self._manager, "stop")):
            try:
                if thing is not None:
                    getattr(thing, method)()
            except Exception:  # noqa: BLE001  a browser that is already gone is closed enough
                pass
        self._browser = self._manager = None

    def summary(self) -> dict[str, Any]:
        used = [row for row in self.rows if row.get("used")]
        return {"enabled": self.reason is None, "reason": self.reason, "used": bool(used),
                "pages_rendered": len(self.rows), "pages": self.rows,
                "links_added": sum(row.get("links_only_after_rendering", 0) for row in used),
                "rule": f"used when the rendered page adds at least {RENDER_DISCOVERY_MIN_NEW_LINKS} link targets and at "
                        f"least {RENDER_DISCOVERY_MIN_GROWTH:.0%} on top of the raw HTML's",
                "limit": f"only the homepage and key pages are rendered for discovery, at most "
                         f"{self.cfg.render_discovery_budget} page(s)"}
