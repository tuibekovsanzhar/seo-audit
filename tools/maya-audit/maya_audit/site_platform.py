"""The platform a site is built on and the CDN in front of it, from what the pages already read show (H34, G06).

Signatures: where a platform's own scripts are served from, the folder its themes use, the generator meta tag it
prints, or an X-Powered-By header; a CDN from the response headers it adds, Cloudflare also from the /cdn-cgi/ paths it
adds to pages. Nothing is requested for this. The answer is a hint for whoever acts on the report (a Ticimax shop changes
its theme in the Ticimax panel, a WordPress site in a plugin); it is not used to judge any check. A platform that is
not on the list is not named: no guess.

The first match is not the answer (G06): every page read votes, and the platform seen on the most pages wins. A more
specific platform beats the one it is built on when both are seen (WooCommerce over WordPress), and a tie goes to the
one listed first (the more specific), so a shop with one embedded WordPress magazine page is not named WordPress.
"""

from __future__ import annotations

from collections import Counter
import re
from typing import Any, Iterable

# (name, substrings looked for in script addresses, the generator meta tag and X-Powered-By, lower case). Each list
# is short on purpose: a host or a folder only that platform uses, never a loose word that would misname sites.
SIGNATURES = (
    ("Ticimax", ("static.ticimax.cloud",)),
    ("Shopify", ("cdn.shopify.com",)),
    ("WooCommerce", ("/plugins/woocommerce/", "woocommerce")),
    ("Magento", ("/static/version", "/mage/", "magento")),
    ("Shopware", ("/js/storefront/", "/bundles/storefront/", "shopware")),
    ("PrestaShop", ("prestashop", "/modules/ps_")),
    ("OpenCart", ("catalog/view/javascript/", "opencart")),
    ("Squarespace", ("static1.squarespace.com", "squarespace")),
    ("Webflow", ("website-files.com", "webflow")),
    ("Wix", ("static.wixstatic.com", "static.parastorage.com", "wix.com website builder")),
    ("ikas", ("cdn.myikas.com",)),
    ("Drupal", ("/core/misc/drupal", "/sites/all/modules/", "drupal")),
    ("WordPress", ("/wp-content/", "/wp-includes/", "wordpress")),
    ("Next.js", ("/_next/static/", "next.js")),
)  # IdeaSoft and T-Soft are not listed: their script hosts were not confirmed, and a loose word would misname sites.
# DECISIONS 365: more signals, each one only that platform makes. "assets": a host or folder in the page's image and
# preloaded-image addresses (a theme bundles its scripts, but uploads stay at the platform's file address); "declared":
# a word the generator meta tag or X-Powered-By header writes (never looked for in a script address, where a short word
# would misname sites); "credit": the platform named in the footer's credit line ("… ile hazırlanmıştır", "Powered by
# …"). IdeaSoft, T-Soft and Sitefinity are recognised only from what they declare or credit (their file hosts are not
# confirmed).
EXTRA = {
    "Ticimax": {"assets": ("static.ticimax.cloud", ".ticimax.cloud/"), "declared": ("ticimax",), "credit": r"ticimax"},
    "Shopify": {"assets": ("cdn.shopify.com", "/cdn/shop/"), "declared": ("shopify",), "credit": r"shopify"},
    "WooCommerce": {"assets": ("/plugins/woocommerce/",), "declared": ("woocommerce",), "credit": r"woocommerce"},
    "ikas": {"assets": ("cdn.myikas.com",), "declared": ("ikas",), "credit": r"ikas"},
    "IdeaSoft": {"assets": (), "declared": ("ideasoft",), "credit": r"idea ?soft"},
    "T-Soft": {"assets": (), "declared": ("t-soft",), "credit": r"t-?soft"},
    "Wix": {"assets": ("static.wixstatic.com",), "declared": ("wix.com",), "credit": r"wix(?:\.com)?"},
    "Sitefinity": {"assets": (), "declared": ("sitefinity",), "credit": None},
    "WordPress": {"assets": ("/wp-content/uploads/", "/wp-content/themes/"), "declared": ("wordpress",), "credit": r"wordpress"},
    "Next.js": {"assets": ("/_next/image", "/_next/static/"), "declared": ("next.js",), "credit": None},
}
CREDIT = (r"(?:ile|tarafından) hazırlan|altyapısı(?:yla|dır)?|alt ?yapısıyla|sistemleriyle|paketleri ile|"
          r"powered by|built with|made with")
# A platform built on another: when both are seen, the specific one is the answer whatever the page counts.
BUILT_ON = {"WooCommerce": "WordPress"}
CONFIDENCE = ("high", "medium", "low")
# (CDN, ((header, substring of its value, lower case; "" = the header being there is enough), ...)). Only headers the
# crawler keeps on a page record are seen (crawler.KEPT_HEADERS); the others are listed so they count once kept.
CDN_SIGNATURES = (
    ("Cloudflare", (("server", "cloudflare"), ("cf-ray", ""), ("cf-cache-status", ""), ("cf-mitigated", ""))),
    ("Akamai", (("server", "akamaighost"), ("x-cache", "akamai"), ("x-akamai-transformed", ""))),
    ("CloudFront", (("x-cache", "cloudfront"), ("via", "cloudfront"), ("x-amz-cf-id", ""), ("x-amz-cf-pop", ""))),
    ("Fastly", (("x-fastly-request-id", ""), ("x-served-by", "cache-"), ("server", "fastly"))),
    ("Sucuri", (("server", "sucuri"), ("x-sucuri-id", ""), ("x-sucuri-cache", ""))),
    ("Imperva", (("x-iinfo", ""), ("x-cdn", "imperva"), ("x-cdn", "incapsula"))),
    ("Vercel", (("server", "vercel"), ("x-vercel-id", ""), ("x-vercel-cache", ""))),
    ("Netlify", (("server", "netlify"), ("x-nf-request-id", ""))),
)
CLOUDFLARE_HEADERS = ("cf-ray", "cf-cache-status", "cf-mitigated")
PAGES_READ = 20  # pages looked at; signatures sit in the template, so a few pages are enough


def _headers(page) -> dict[str, str]:
    """A page's kept response headers, lower-cased; an empty dict when the record keeps none."""
    headers = getattr(page, "headers", None) or {}
    return {str(k).lower(): str(v) for k, v in headers.items()} if isinstance(headers, dict) else {}


def _platform_hits(page) -> dict[str, str]:
    """Each platform this page shows, with the first signal of it ("script …", "generator …", "X-Powered-By …",
    "image …", "footer credit …")."""
    return {name: hit[0] for name, hit in _hits(page).items()}


def _hits(page) -> dict[str, tuple[str, bool]]:
    """{platform: (signal, declared)}: `declared` when the page states it (generator, X-Powered-By, a footer credit)."""
    analysis = page.analysis
    texts = [("script", s.get("src") or "") for s in analysis.get("external_scripts") or []]
    declared = [("generator", m.get("content") or "") for m in analysis.get("meta") or [] if m.get("name") == "generator"]
    declared.append(("X-Powered-By", _headers(page).get("x-powered-by", "")))
    assets = [("image", i.get("src") or "") for i in analysis.get("images") or [] if isinstance(i, dict)]
    assets += [("preloaded image", i.get("href") or "") for i in analysis.get("image_preloads") or [] if isinstance(i, dict)]
    footer = (analysis.get("footer_text") or "").lower()
    hits: dict[str, tuple[str, bool]] = {}
    for name, needles in SIGNATURES:
        hit = next(((kind, text) for kind, text in texts + declared if text for needle in needles if needle in text.lower()), None)
        if hit:
            hits[name] = (f"{name}: {hit[0]} {hit[1][:120]} on {page.url}", hit[0] != "script")
    for name, sig in EXTRA.items():
        if name in hits and hits[name][1]:
            continue
        said = next(((kind, text) for kind, text in declared if text for w in sig["declared"] if w in text.lower()), None)
        credit = None
        if sig["credit"] and footer:
            credit = re.search(rf"(?<![\w-])(?:{sig['credit']})(?![\w-]).{{0,60}}?(?:{CREDIT})|(?:{CREDIT}).{{0,40}}?(?<![\w-])(?:{sig['credit']})(?![\w-])",
                               footer)
        if said or credit:
            what = f"{said[0]} {said[1][:120]}" if said else f"footer credit «{credit.group(0)[:80]}»"
            hits[name] = (f"{name}: {what} on {page.url}", True)
            continue
        if name in hits:
            continue
        asset = next(((kind, text) for kind, text in assets if text for a in sig["assets"] if a in text.lower()), None)
        if asset:
            hits[name] = (f"{name}: {asset[0]} {asset[1][:120]} on {page.url}", False)
    return hits


def _cdn(page) -> tuple[str, str] | None:
    headers = _headers(page)
    for name, rules in CDN_SIGNATURES:
        for header, needle in rules:
            if header in headers and needle in headers[header].lower():
                shown = f"{header}: {headers[header][:60]}" if needle else header
                return name, f"{name}: response header {shown} on {page.url}"
    return None


def recognise(result) -> dict[str, Any] | None:
    """{"name", "cdn", "signals", "confidence", "pages_seen", "pages_looked"} for the platform and CDN the pages show, or
    None when neither is recognised. DECISIONS 365: `confidence` is "high" when its signals are on 2 pages or more and
    either the pages state it (generator, X-Powered-By, a footer credit) or they are half the pages looked at or more;
    "medium" on 2 pages or more, or one page stating it; "low" on one page only."""
    pages = [p for p in getattr(result, "pages", None) or [] if getattr(p, "analysis", None)][:PAGES_READ]
    votes: Counter = Counter()
    first: dict[str, str] = {}
    stated: set[str] = set()
    cdn, cdn_signal = None, None
    for page in pages:
        for name, (signal, said) in _hits(page).items():
            votes[name] += 1
            first.setdefault(name, signal)
            if said:
                stated.add(name)
        if cdn is None:
            found = _cdn(page)
            sources = [s.get("src") or "" for s in page.analysis.get("external_scripts") or []]
            if found:
                cdn, cdn_signal = found
            elif any("/cdn-cgi/" in (edge.get("target") or "") for edge in getattr(page, "outlinks", None) or []) \
                    or any("/cdn-cgi/" in src for src in sources):
                cdn, cdn_signal = "Cloudflare", f"Cloudflare: a /cdn-cgi/ address in the markup of {page.url}"
    for child, parent in BUILT_ON.items():
        if child in votes:
            votes.pop(parent, None)
    order = [name for name, _ in SIGNATURES] + [n for n in EXTRA if n not in dict(SIGNATURES)]
    name = min(votes, key=lambda n: (-votes[n], order.index(n))) if votes else None
    if name is None and cdn is None:
        return None
    signals = ([first[name] + (f" ({votes[name]} of {len(pages)} pages read)" if votes[name] > 1 else "")]
               if name else []) + ([cdn_signal] if cdn_signal else [])
    out = {"name": name, "cdn": cdn, "signals": signals}
    if name:
        seen = votes[name]
        out.update(confidence="high" if seen >= 2 and (name in stated or seen * 2 >= len(pages)) else
                   "medium" if seen >= 2 or name in stated else "low", pages_seen=seen, pages_looked=len(pages))
    return out


# ---------------------------------------------------------------- from saved data (DECISIONS 309)
# A page reader's saved copy (Firecrawl) keeps no script list, so `recognise` finds nothing when only the reader read the
# pages. What the audit saved still shows some platforms: the names of the sitemaps the platform writes, the folders its
# addresses use and the address of its file CDN inside the saved markup (JSON-LD, og:image, canonicals). Each signal is
# one only that platform makes; nothing is requested.
SAVED_SIGNATURES = (
    ("Shopify", {
        "sitemap": re.compile(r"/sitemap_(?:products|collections|pages|blogs)_\d+\.xml\?from=\d+", re.IGNORECASE),
        "text": ("cdn.shopify.com", "/cdn/shop/", ".myshopify.com"),
        # Both folders, each on several addresses: /products/<handle> and /collections/<handle> together.
        "paths": ("/products/", "/collections/"),
    }),
)
PATHS_AT_LEAST = 3  # addresses under each folder before the pair counts


def _addresses(report: dict) -> list[str]:
    crawl = report.get("crawl") or {}
    urls = [u for key in ("sitemap_urls", "discovered_urls") for u in crawl.get(key) or [] if isinstance(u, str)]
    urls += [p.get("url") for p in crawl.get("pages") or [] if isinstance(p, dict) and isinstance(p.get("url"), str)]
    urls += [p.get("url") for p in (report.get("firecrawl") or {}).get("pages") or []
             if isinstance(p, dict) and isinstance(p.get("url"), str)]
    return urls


def recognise_saved(report: dict, texts: Iterable[str] = ()) -> dict[str, Any] | None:
    """{"name", "cdn", "signals"} (the shape `recognise` returns) for a platform the saved data shows when the report
    names none, or None. `texts`: the saved page copies (the audit's evidence files) as text. The CDN stays the
    report's. Each signal says it comes from the saved data."""
    from urllib.parse import urlsplit
    texts = list(texts)
    sitemaps = [d.get("url") for d in (report.get("crawl") or {}).get("sitemap_docs") or []
                if isinstance(d, dict) and isinstance(d.get("url"), str)]
    paths = [urlsplit(u).path.lower() for u in _addresses(report)]
    for name, sig in SAVED_SIGNATURES:
        signals = []
        hit = next((u for u in sitemaps if sig["sitemap"].search(u)), None)
        if hit:
            signals.append(f"{name}: sitemap {hit[:120]} (the platform's own sitemap names)")
        needle = next((n for n in sig["text"] for t in texts if n in t.lower()), None)
        if needle:
            seen = sum(1 for t in texts if needle in t.lower())
            signals.append(f"{name}: {needle} in {seen} saved page cop{'y' if seen == 1 else 'ies'}")
        counts = [sum(1 for p in paths if folder in p) for folder in sig["paths"]]
        if all(n >= PATHS_AT_LEAST for n in counts):
            signals.append(f"{name}: addresses under " + " and ".join(f"{f} ({n})" for f, n in zip(sig["paths"], counts)))
        if signals:
            return {"name": name, "cdn": (report.get("platform") or {}).get("cdn"), "confidence": "medium",
                    "signals": [f"{s} (saved data, DECISIONS 309)" for s in signals]
                               + list((report.get("platform") or {}).get("signals") or [])}
    return None
