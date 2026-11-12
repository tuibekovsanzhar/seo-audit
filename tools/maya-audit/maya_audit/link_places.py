"""Where each problem address is pointed at (DECISIONS 337): one row per address and the page, sitemap entry, canonical or
hreflang link that names it, built from a report alone (a new one or a saved one), no request.

A row says: the address in question (`links_to`) and how it answers (`status`, through its redirects to `ends_at` and
`final_status`); the page that holds the link (`source`, None for a sitemap entry), its text, the value as the page
wrote it (`href`, only for crawls that recorded it), where it sits (`position`: menu, footer, body, or head for a
canonical or hreflang tag); whether the address is in the sitemap and which file lists it; and what to point at
instead (`suggested`: the final address when the redirect ends at a page that answers 200, else what to do).

Rules covered: broken links (IDX-1 4xx, the sitemap-only entries, mistyped hrefs), server errors (IDX-1 5xx), links to
redirects (IDX-6), redirect chains and loops (IDX-3), canonicals that fail or redirect (IDX-4) and hreflang targets that
do not answer 200 (STR-9). The suggested address is never guessed: only a redirect's own end is offered.
"""
from __future__ import annotations

from collections import defaultdict

LINK_4XX = ("idx1.4xx.referenced", "idx1.4xx.referenced.linked", "idx1.4xx.sitemap_only", "idx1.href_mistyped")
SERVER = ("idx1.5xx", "idx1.5xx.once")
TO_REDIRECT = ("idx6.links_to_redirect", "idx6.links_to_flow_redirect")  # DECISIONS 344: the note too, to check
CHAINS = ("idx3.chain", "idx3.loop", "idx3.cookie", "idx3.intermittent", "idx3.self_once")
CANONICAL = ("idx4.broken", "idx4.redirecting", "idx4.redirect_loop")
HREFLANG = ("str9.status",)
WHERE_RULES = LINK_4XX + SERVER + TO_REDIRECT + CHAINS + CANONICAL + HREFLANG
MAX_ROWS = 500  # per finding; the appendix says when more were cut


def _bare(url: str | None) -> str:
    return (url or "").split("#", 1)[0]


class _Crawl:
    """What the rows need from a report's crawl, read once."""

    def __init__(self, report: dict):
        from .sitemap import file_map
        crawl = report.get("crawl") or {}
        pages = [p for p in crawl.get("pages") or [] if isinstance(p, dict)]
        self.status = {p.get("url"): p.get("status") for p in pages}
        self.redirect = {p.get("url"): p.get("redirect_location") for p in pages
                         if p.get("redirect_location") and isinstance(p.get("status"), int) and 300 <= p["status"] < 400}
        self.listed = set(crawl.get("sitemap_urls") or [])
        self.files = file_map(crawl.get("sitemap_docs"), crawl.get("sitemap_urls"))
        # DECISIONS 340: when the sitemaps were read, for a report that kept no time per file: the crawl's sitemap step
        step = next((x for x in crawl.get("steps") or [] if isinstance(x, dict) and x.get("step") == "sitemap"), None)
        self.sitemap_step = (step or {}).get("started_at")
        self.inbound: dict[str, list[dict]] = defaultdict(list)
        self.edge: dict[tuple[str, str], dict] = {}
        for p in pages:
            for e in p.get("outlinks") or []:
                target = _bare(e.get("target"))
                if not target:
                    continue
                self.edge.setdefault((p["url"], target), e)
                self.inbound[target].append({"source": p["url"], "anchor": e.get("anchor") or "", "href": e.get("href"),
                                             "nav": bool(e.get("nav")), "footer": bool(e.get("footer"))})
            if p.get("redirect_location"):
                self.inbound[p["redirect_location"]].append({"source": p["url"], "anchor": "(redirect)"})

    def walk(self, url: str) -> tuple[str, int | None, bool]:
        """(where the redirects from `url` end, that address's status, whether they loop)."""
        seen, at = {url}, url
        for _ in range(20):
            nxt = self.redirect.get(at)
            if not nxt:
                return at, self.status.get(at), False
            if nxt in seen:
                return nxt, self.status.get(nxt), True
            seen.add(nxt)
            at = nxt
        return at, self.status.get(at), False

    def position(self, source: str | None, target: str) -> str | None:
        e = self.edge.get((source or "", target)) or {}
        if not e:
            return None
        return "menu" if e.get("nav") else "footer" if e.get("footer") else "body"

    def row(self, finding: dict, kind: str, links_to: str, source: str | None = None, *, text: str | None = None,
            href: str | None = None, position: str | None = None, ends_at: str | None = None, suggested: str | None = None,
            **extra) -> dict:
        end, final_status, loop = self.walk(links_to)
        if ends_at:
            end, final_status = ends_at, self.status.get(ends_at, final_status)
        recorded = extra.pop("status", None)  # a check's own answer for an address the crawl did not read
        first = self.status[links_to] if links_to in self.status else recorded
        if suggested is None:
            suggested = (end if end != links_to and isinstance(final_status, int) and 200 <= final_status < 300 and not loop
                         else "fix_loop" if loop else "remove")
        edge = self.edge.get((source or "", links_to)) or {}
        return {"finding_id": finding.get("id"), "rule_id": finding.get("rule_id"), "kind": kind,
                "links_to": links_to, "status": first, "ends_at": end, "final_status": final_status, "loop": loop,
                "source": source, "link_text": text if text is not None else (edge.get("anchor") or None),
                "href": href or edge.get("href"), "position": position or self.position(source, links_to),
                "in_sitemap": links_to in self.listed, "sitemap_file": self.files.get(links_to), "suggested": suggested,
                **extra}

    def linked(self, finding: dict, targets, kind_if_none: str = "sitemap", direct_only: bool = False) -> list[dict]:
        """Rows for each target: every link that reaches it (through redirects unless `direct_only`); a target no link
        reaches is a sitemap row when the sitemap lists it, else a row with no page ("not linked")."""
        from .checks.index import trace_to_links
        rows = []
        for target in targets:
            if direct_only:
                found = [{"source": r["source"], "anchor": r["anchor"], "href": r.get("href"), "links_to": target,
                          "position": "menu" if r.get("nav") else "footer" if r.get("footer") else "body"}
                         for r in self.inbound.get(target, []) if r["anchor"] != "(redirect)"]
                only = [] if found else ([target] if target in self.listed else [])
            else:
                found, only = trace_to_links([target], self.inbound, self.listed)
            for r in found:
                rows.append(self.row(finding, "link", r["links_to"], r["source"], text=r.get("anchor") or None,
                                     href=r.get("href"), position=r.get("position")))
            for u in only:
                rows.append(self.row(finding, "sitemap", u))
            if not found and not only:
                rows.append(self.row(finding, "not_linked", target))
        return rows


def _dicts(values) -> list[dict]:
    return [v for v in values or [] if isinstance(v, dict)]


def _rows_for(f: dict, c: _Crawl) -> list[dict]:
    rule, ev = f.get("rule_id"), f.get("evidence") or {}
    if rule in LINK_4XX:
        rows = []
        for r in _dicts(ev.get("link_sources")):
            rows.append(c.row(f, "link", r.get("links_to") or r.get("target"), r.get("source"), text=r.get("anchor") or None,
                              href=r.get("href"), position=r.get("position"), mistyped=r.get("mistyped")))
        entries = {e.get("url"): e for e in _dicts(ev.get("sitemap_entries"))}
        for u in ev.get("sitemap_only") or []:
            e = entries.get(u) or {}
            row = c.row(f, "sitemap", u, suggested=e.get("suggested") or "remove_or_redirect", heading=e.get("heading_match"))
            # DECISIONS 340: the <loc> as the file writes it and its line (recorded since 340; before, the address as
            # Maya kept it), and when the file was read (else when the sitemap step began, `sitemap_read_approx`)
            row.update({"sitemap_loc": e.get("sitemap_loc"), "sitemap_line": e.get("sitemap_line"),
                        "sitemap_read_at": e.get("sitemap_read_at") or c.sitemap_step,
                        "sitemap_read_approx": not e.get("sitemap_read_at") and bool(c.sitemap_step)})
            # DECISIONS 346: the card's 301 target for this address (DECISIONS 344, 345), for "Önerilen hedef"
            s = next((x for x in _dicts(ev.get("suggestions")) if x.get("url") == u), None)
            if s is not None:
                row.update({"target": s.get("target"), "target_basis": s.get("target_basis"),
                            "target_firm": s.get("target_firm", True), "target_known_as": s.get("target_known_as")})
            rows.append(row)
        return rows
    if rule in SERVER:
        urls = [p.get("url") if isinstance(p, dict) else p for p in ev.get("pages") or []]
        return c.linked(f, [u for u in urls if isinstance(u, str) and u])
    if rule in TO_REDIRECT:
        return c.linked(f, [t.get("url") for t in _dicts(ev.get("targets")) if t.get("url")], direct_only=True)
    if rule in CHAINS:
        starts = [ch["hops"][0] for ch in _dicts(ev.get("chains")) if ch.get("hops")]
        starts += [loop[0] for key in ("loops", "loops_in_the_crawl") for loop in ev.get(key) or [] if isinstance(loop, list) and loop]
        return c.linked(f, list(dict.fromkeys(starts)), direct_only=True)
    if rule in CANONICAL:
        return [c.row(f, "canonical", p.get("canonical"), p.get("url"), href=p.get("canonical"), position="head",
                      ends_at=p.get("redirects_to"),
                      suggested=None if rule == "idx4.redirecting" else p.get("url"))
                for p in _dicts(ev.get("pages")) if p.get("canonical")]
    if rule in HREFLANG:
        # The hreflang check asked the target itself: its own answer when the crawl did not read that address.
        return [c.row(f, "hreflang", link.get("target"), link.get("url"), text=link.get("hreflang"), href=link.get("target"),
                      position="head", ends_at=link.get("location") or None, status=link.get("status"))
                for link in _dicts(ev.get("links")) if link.get("target")]
    return []


def places(report: dict) -> dict[str, list[dict]]:
    """{finding id: rows} for every finding of a rule in WHERE_RULES (DECISIONS 337)."""
    findings = [f for chk in report.get("checks") or [] for f in chk.get("findings") or []
                if isinstance(f, dict) and f.get("rule_id") in WHERE_RULES]
    if not findings:
        return {}
    c = _Crawl(report)
    out = {}
    for f in findings:
        rows = _rows_for(f, c)
        if rows:
            out[f["id"]] = rows[:MAX_ROWS]
    return out
