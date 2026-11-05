"""Stage 8a rules borrowed from Screaming Frog (DECISIONS 315, docs/research/screaming-frog-research-for-maya-audit.md):
whole-crawl checks over data the crawl already holds. None sends a request. They run through `quick_rules.findings`,
so both a live audit and a saved report re-read offline get them.

| Rule id | Check | What it reports | Severity | Type |
|---|---|---|---|---|
| idx6.links_to_redirect | IDX-6 | internal links to an address that redirects, with the final address to link to | S4 | Sorun |
| idx4.chain | IDX-4 | a canonical naming a page whose own canonical is a third address | S3 | Sorun |
| str9.wrong_language | STR-9 | an hreflang link whose target page declares another language than the link says | S3 | Sorun |
| str7.over_100kb | STR-7 | sampled image files between 100 and 500 KB (over 500 KB is str7.heavy) | S4 | Fırsat |

Redirect chains and loops (IDX-3), canonicals that redirect (IDX-4), hreflang return links, x-default, self-reference
and non-200 / non-canonical targets (STR-9), missing alt and width/height (STR-7) already exist and are kept.
"""
from __future__ import annotations

from collections import defaultdict

from ..findings import Finding, Severity, scope_for
from ..models import Confidence

GOOGLE = "Google AI Overviews / AI Mode"
COPILOT = "Microsoft Copilot (Bing index)"
DOCUMENTED = "Documented (Google Search Central)"
MEASURED = "Measured"
IMAGE_LIGHT_BYTES = 100 * 1024   # Screaming Frog's default "over 100 KB" (owner, Stage 8a)
IMAGE_HEAVY_BYTES = 500 * 1024   # str7.heavy's threshold: files above it are reported there, not here
MAX_HOPS = 10


def _tier(urls, key_urls) -> int:
    return 0 if any(u in key_urls for u in urls) else 2


def _bare(url: str) -> str:
    return (url or "").split("#", 1)[0]


def redirect_map(pages) -> dict[str, tuple[int, str]]:
    """{address: (status, target)} for every response that redirected."""
    return {p.url: (p.status, p.redirect_location) for p in pages
            if p.redirect_location and p.status and 300 <= p.status < 400}


def follow(url: str, redirects: dict[str, tuple[int, str]], statuses: dict[str, int | None]) -> dict:
    """The hops from `url` to where its redirects end: [{url, status, target}], the final address and its status, and
    whether the walk came back to an address already passed (a loop)."""
    hops, seen = [], set()
    while url in redirects and url not in seen and len(hops) < MAX_HOPS:
        seen.add(url)
        status, target = redirects[url]
        hops.append({"url": url, "status": status, "target": target})
        url = target
    return {"hops": hops, "final": url, "final_status": statuses.get(url), "loop": url in seen}


def redirect_records(pages) -> list[dict]:
    """Every requested address that redirected, with every hop (status, target), the final address and its status
    (`crawl.redirects`, schema 1.26)."""
    redirects = redirect_map(pages)
    statuses = {p.url: p.status for p in pages}
    return [{"url": url, **follow(url, redirects, statuses)} for url in redirects]


# -- idx6.links_to_redirect -------------------------------------------------------------------------------------------

LINKS_TO_REDIRECT_EXPECTED = "internal links point straight at the page they end on"
LINKS_TO_REDIRECT_FIX = ("Change each link to the final address its redirect ends at (the evidence gives it for every "
                         "target); when a template writes the link, change it there.")


def links_to_redirect(pages, read, key_urls=frozenset()) -> list[Finding]:
    redirects = redirect_map(pages)
    if not redirects:
        return []
    statuses = {p.url: p.status for p in pages}
    links, sources, targets = 0, [], defaultdict(set)
    for p in read:
        found = 0
        for edge in p.outlinks or []:
            target = _bare(edge.get("target") or "")
            if target in redirects and target != p.url:
                found += int(edge.get("links") or 1)
                targets[target].add(p.url)
        if found:
            links += found
            sources.append(p.url)
    if not sources:
        return []
    rows = []
    for t in sorted(targets, key=lambda t: (-len(targets[t]), t)):
        walk = follow(t, redirects, statuses)
        rows.append({"url": t, "final": walk["final"], "final_status": walk["final_status"], "loop": walk["loop"],
                     "hops": [h["url"] for h in walk["hops"]] + [walk["final"]], "statuses": [h["status"] for h in walk["hops"]],
                     "linked_from_pages": len(targets[t]), "linked_from": sorted(targets[t])[:10]})
    return [Finding("IDX-6", f"{links} internal link(s) on {len(sources)} page(s) point to an address that redirects",
                    Severity.S4, Confidence.VERIFIED, DOCUMENTED, [GOOGLE, COPILOT], scope_for(sources),
                    {"link_count": links, "page_count": len(sources), "redirecting_targets": len(targets), "targets": rows[:40],
                     "rule": "a link (menu, content or footer) on a page read to an address that answered with a redirect "
                             "in this crawl; link to the final address instead"},
                    LINKS_TO_REDIRECT_EXPECTED, LINKS_TO_REDIRECT_FIX, importance_tier=_tier(sources, key_urls))]


# -- idx4.chain ---------------------------------------------------------------------------------------------------------

CANONICAL_CHAIN_EXPECTED = "a canonical names a page that is its own canonical"
CANONICAL_CHAIN_FIX = ("Point each canonical straight at the final page (the canonical of the page it names now); search "
                       "engines may not follow a canonical of a canonical.")


def canonical_chain(read, key_urls=frozenset()) -> list[Finding]:
    from ..index_data import canonical_target
    from ..structure_data import same_page
    by_url = {p.url: p for p in read}
    canon = {}
    for p in read:
        try:
            target = canonical_target(p)
        except Exception:  # a saved record without the fields the canonical reader needs
            continue
        if target and not same_page(target, p.url):
            canon[p.url] = target
    rows = []
    for url, target in canon.items():
        page = by_url.get(target)
        second = canon.get(target) if page is not None else None
        if second and not same_page(second, url):
            rows.append({"url": url, "canonical": target, "canonical_of_canonical": second})
    if not rows:
        return []
    urls = [r["url"] for r in rows]
    return [Finding("IDX-4", f"{len(rows)} page(s) declare a canonical to a page whose own canonical is another address",
                    Severity.S3, Confidence.VERIFIED, DOCUMENTED, [GOOGLE, COPILOT], scope_for(urls),
                    {"pages": rows[:60], "count": len(rows),
                     "rule": "the canonical names a page read whose own canonical names a third address"},
                    CANONICAL_CHAIN_EXPECTED, CANONICAL_CHAIN_FIX, importance_tier=_tier(urls, key_urls))]


# -- str9.wrong_language -----------------------------------------------------------------------------------------------

WRONG_LANGUAGE_EXPECTED = "each hreflang link names a page in the language its code says"
WRONG_LANGUAGE_FIX = ("Correct the hreflang code, or point the link at the page in that language; check the target "
                      "page's <html lang> too.")


def _primary(code: str | None) -> str:
    return (code or "").strip().lower().replace("_", "-").split("-")[0]


def hreflang_wrong_language(read, key_urls=frozenset()) -> list[Finding]:
    from ..structure_data import same_page
    by_url = {p.url: p for p in read}
    rows = []
    for p in read:
        for link in (p.analysis or {}).get("hreflang") or []:
            code, href = _primary(link.get("hreflang")), link.get("href")
            if not code or code == "x" or code == "x-default" or not href:
                continue
            from ..language import hreflang_code_problem
            if hreflang_code_problem(link.get("hreflang") or ""):
                continue  # a malformed code ("jp", "en-UK") is str9.bad_codes' finding, not this one
            target = by_url.get(href) or next((q for u, q in by_url.items() if same_page(u, href)), None)
            if target is None:
                continue
            declared = _primary((target.analysis or {}).get("html_lang"))
            if declared and declared != code:
                rows.append({"page": p.url, "hreflang": link.get("hreflang"), "target": target.url,
                             "target_lang": (target.analysis or {}).get("html_lang")})
    if not rows:
        return []
    urls = sorted({r["page"] for r in rows})
    return [Finding("STR-9", f"{len(urls)} page(s) have hreflang links whose target page declares another language",
                    Severity.S3, Confidence.VERIFIED, DOCUMENTED, [GOOGLE, COPILOT], scope_for(urls),
                    {"links": rows[:60], "count": len(rows),
                     "rule": "the hreflang code's language (en of en-gb) differs from the target page's <html lang>"},
                    WRONG_LANGUAGE_EXPECTED, WRONG_LANGUAGE_FIX, importance_tier=_tier(urls, key_urls))]


# -- str7.over_100kb ---------------------------------------------------------------------------------------------------

OVER_100KB_EXPECTED = "content images under 100 KB each where they can be"
OVER_100KB_FIX = ("Resize each image to the largest size it is shown at and compress it, or serve WebP/AVIF; replace "
                  "the file at the same address.")


def _images(structure) -> list[dict]:
    if structure is None:
        return []
    images = structure.get("images") if isinstance(structure, dict) else getattr(structure, "images", None)
    return list((images or {}).values())


def images_over_100kb(structure, key_urls=frozenset()) -> list[Finding]:
    from .structure import media_size
    ok = [row for row in _images(structure) if row.get("source", "fetched") == "fetched" and row.get("status")
          and 200 <= row["status"] < 300]
    rows = sorted(({"image": row["url"], "bytes": media_size(row), "shown_on": row.get("pages") or []} for row in ok
                   if IMAGE_LIGHT_BYTES < (media_size(row) or 0) <= IMAGE_HEAVY_BYTES), key=lambda r: -r["bytes"])
    if not rows:
        return []
    urls = sorted({page for row in rows for page in row["shown_on"]})
    return [Finding("STR-7", f"{len(rows)} sampled image file(s) are between 100 and 500 KB", Severity.S4,
                    Confidence.VERIFIED, MEASURED, ["page speed for every reader", "Google Images"], scope_for(urls),
                    {"images": rows[:60], "sampled": len(ok), "unknown_size": sum(media_size(r) is None for r in ok),
                     "thresholds_bytes": {"from": IMAGE_LIGHT_BYTES, "to": IMAGE_HEAVY_BYTES}},
                    OVER_100KB_EXPECTED, OVER_100KB_FIX, importance_tier=_tier(urls, key_urls),
                    notes=["Sizes are the Content-Length the server sent for a sample of image files; files over 500 KB "
                           "are in their own finding."])]
