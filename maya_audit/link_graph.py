"""The site's internal link graph: click depth from the homepage and inbound links per page.

Built from the links of every fetched page. A link that exists only in a page's rendered view counts too
(the crawl's discovery renders and the rendering sample), and a link to a URL that redirects counts for
the page the redirect ends on. Depth is the smallest number of clicks from the homepage, found by a
breadth-first walk, not the depth at which the crawl happened to meet the page: the crawl visits pages
in an order chosen to sample the site, so its own depth figure can be larger than the true one.

With an incomplete crawl both figures are lower bounds on what a full crawl would show for inbound links
and upper bounds for depth: a shorter path may run through a page that was not fetched.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from .access_data import homepage_url
from .models import CrawlResult
from .render_discovery import clearly_more


@dataclass
class LinkGraph:
    homepage: str
    depth: dict[str, int] = field(default_factory=dict)             # url -> clicks from the homepage
    inbound: dict[str, set[str]] = field(default_factory=dict)      # url -> pages that link to it
    rendered_only: int = 0                                          # links known only from a rendered view
    js_linked: bool = False                                         # the site writes its links with JavaScript
    js_linked_why: str = ""

    def inbound_count(self, url: str) -> int:
        return len(self.inbound.get(url, ()))


def _final(url: str, redirects: dict[str, str]) -> str:
    seen = set()
    while url in redirects and url not in seen:
        seen.add(url)
        url = redirects[url]
    return url


def build_link_graph(result: CrawlResult) -> LinkGraph:
    redirects = {p.url: p.redirect_location for p in result.pages
                 if p.status and 300 <= p.status < 400 and p.redirect_location}
    out: dict[str, set[str]] = {}
    graph = LinkGraph(homepage=_final(homepage_url(result), redirects))
    raw_counts: dict[str, int] = {}
    for page in result.pages:
        targets = out.setdefault(page.url, set())
        raw_counts[page.url] = sum(1 for edge in page.outlinks if not edge.get("rendered"))
        for edge in page.outlinks:
            targets.add(_final(edge["target"], redirects))
            graph.rendered_only += bool(edge.get("rendered"))
    render = getattr(result, "render", None)
    sample_js = []
    for url, entry in (getattr(render, "pages", None) or {}).items():
        if not entry.get("ok") or url not in out:
            continue
        raw = {edge["target"] for edge in next(p for p in result.pages if p.url == url).outlinks if not edge.get("rendered")}
        new = [edge["target"] for edge in entry.get("rendered_links") or [] if edge["target"] not in raw and edge["target"] != url]
        for target in new:
            final = _final(target, redirects)
            if final not in out[url]:
                graph.rendered_only += 1
                out[url].add(final)
        if clearly_more(len(raw), len(new)):
            sample_js.append(url)
    discovery = getattr(result, "render_discovery", None) or {}
    if discovery.get("used"):
        used = [row["url"] for row in discovery["pages"] if row.get("used")]
        graph.js_linked, graph.js_linked_why = True, (
            f"{len(used)} page(s) rendered during the crawl had clearly more links than their raw HTML")
    elif sample_js:
        graph.js_linked, graph.js_linked_why = True, (
            f"{len(sample_js)} page(s) of the rendering sample had clearly more links than their raw HTML")
    for source, targets in out.items():
        for target in targets:
            if target != source:
                graph.inbound.setdefault(target, set()).add(source)
    graph.depth[graph.homepage] = 0
    queue = deque([graph.homepage])
    while queue:
        url = queue.popleft()
        for target in sorted(out.get(url, ())):
            if target not in graph.depth:
                graph.depth[target] = graph.depth[url] + 1
                queue.append(target)
    return graph
