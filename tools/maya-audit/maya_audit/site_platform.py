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
from typing import Any

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
# A platform built on another: when both are seen, the specific one is the answer whatever the page counts.
BUILT_ON = {"WooCommerce": "WordPress"}
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
    """Each platform this page shows, with the first signal of it ("script …", "generator …", "X-Powered-By …")."""
    analysis = page.analysis
    texts = [("script", s.get("src") or "") for s in analysis.get("external_scripts") or []]
    texts += [("generator", m.get("content") or "") for m in analysis.get("meta") or [] if m.get("name") == "generator"]
    texts.append(("X-Powered-By", _headers(page).get("x-powered-by", "")))
    hits: dict[str, str] = {}
    for name, needles in SIGNATURES:
        hit = next(((kind, text) for kind, text in texts if text for needle in needles if needle in text.lower()), None)
        if hit:
            hits[name] = f"{name}: {hit[0]} {hit[1][:120]} on {page.url}"
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
    """{"name", "cdn", "signals"} for the platform and CDN the pages show, or None when neither is recognised."""
    pages = [p for p in getattr(result, "pages", None) or [] if getattr(p, "analysis", None)][:PAGES_READ]
    votes: Counter = Counter()
    first: dict[str, str] = {}
    cdn, cdn_signal = None, None
    for page in pages:
        for name, signal in _platform_hits(page).items():
            votes[name] += 1
            first.setdefault(name, signal)
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
    order = [name for name, _ in SIGNATURES]
    name = min(votes, key=lambda n: (-votes[n], order.index(n))) if votes else None
    if name is None and cdn is None:
        return None
    signals = ([first[name] + (f" ({votes[name]} of {len(pages)} pages read)" if votes[name] > 1 else "")]
               if name else []) + ([cdn_signal] if cdn_signal else [])
    return {"name": name, "cdn": cdn, "signals": signals}
