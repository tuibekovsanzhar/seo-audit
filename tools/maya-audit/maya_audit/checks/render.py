"""RND-1 to RND-7: rendering and content extractability (spec §5 RND).

T1 results (a page actually rendered in headless Chromium) are Verified; T0
heuristics on raw HTML are Estimated and worded as "may". Severity never
depends on key-page status.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from urllib.parse import parse_qsl, unquote, urlsplit

from ..access_data import homepage_url, key_page_urls
from ..directives import noindex_directives
from ..config import (ACCOUNT_PATHS, DECORATIVE_CANVAS_HINT, LOGIN_RETURN_PARAMS, SITEWIDE_SHARE, TRACKING_IFRAME_HOSTS,
                      TRACKING_IFRAME_PATTERN, CrawlConfig)
from ..coverage import settle_all
from ..findings import CheckResult, Finding, Rationale, ReviewItem, Severity, scope_for
from ..main_content import appears_on_most
from ..language import english_text_assessable, text_assessable, turkish_fold
from ..models import Confidence, CrawlResult, FetchClass
from ..urls import normalize_url
from .access import _status, _tier, _with_intent
from .index import _readable_html

NON_RENDERING = ["ChatGPT search / GPTBot (OpenAI)", "Claude (Anthropic)", "Perplexity"]
GOOGLE_NOTE = ("Google renders JavaScript, so for Google AI Overviews this is Info; the severity applies to the "
               "engines measured not to execute JavaScript (Vercel/MERJ).")
PRICE = re.compile(r"(?:[$€£¥]\s?\d[\d,.]*|\d[\d,.]*\s?(?:USD|EUR|GBP)|/\s?(?:mo|month|yr|year)\b)", re.I)
# Where a login page lives, in English and Turkish.
_LOGIN = r"login|log-in|signin|sign-in|auth|account/login|giris|giris-yap|uye-girisi|oturum-ac"
LOGIN_PATH = re.compile(rf"/({_LOGIN})(/|$|\?)", re.I)
WALL_PATH = re.compile(rf"/({_LOGIN}|consent|cookie[s-]?(consent|wall)?|"
                       r"age(-gate|-verification)?|verify-age|country|region|choose-country|select-country|geo)(/|$|\?)", re.I)
_PATH_FOLD = str.maketrans("çğıöşüâîû", "cgiosuaiu")


def _fold_segment(segment: str) -> str:
    """A path segment without case, Turkish letter marks or a file extension: "Hesabım.aspx" -> "hesabim"."""
    folded = unquote(segment).replace("İ", "i").replace("I", "i").lower().replace("\u0307", "").translate(_PATH_FOLD)
    return re.sub(r"\.[a-z0-9]{2,5}$", "", folded)


_ACCOUNT_SEGMENTS = frozenset(_fold_segment(name) for name in ACCOUNT_PATHS)


def account_page(url: str) -> bool:
    """Whether an address is a page of one signed-in customer: an account, a cart, a checkout, a sign-in page."""
    return any(_fold_segment(segment) in _ACCOUNT_SEGMENTS for segment in urlsplit(url).path.split("/") if segment)


def login_target(location: str) -> bool:
    """Whether a redirect leads to a login page: by its path, or by a parameter that carries the address to come back
    to ("?ReturnUrl=%2Fsepet"). The parameter counts only when its value is an address, so "?next=2" does not."""
    parts = urlsplit(location)
    if LOGIN_PATH.search(parts.path + ("?" + parts.query if parts.query else "")):
        return True
    return any(name.lower() in LOGIN_RETURN_PARAMS and value.strip().lower().startswith(("/", "http://", "https://", "%2f"))
               for name, value in parse_qsl(parts.query, keep_blank_values=True))
WALL_SIGNATURES = {
    "cookie consent": re.compile(r"accept (all )?cookies|we use cookies|cookie (consent|preferences|settings)|manage cookies", re.I),
    "login": re.compile(r"(sign|log) ?in to (continue|view|read|access)|please (sign|log) ?in|you must be (logged|signed) in", re.I),
    "age gate": re.compile(r"are you (over |at least )?(18|19|21)|verify your age|confirm your age", re.I),
    "geo block": re.compile(r"not available in your (country|region)|choose your (country|region)", re.I),
}
PAYWALL = re.compile(r"subscribe to (continue|keep) reading|for subscribers only|subscribers? only|"
                     r"this (article|story) is (only )?(available )?(to|for) subscribers|to continue reading,? subscribe", re.I)
# The same walls in Turkish. Matched against `turkish_fold(text)`, so they are written in lower case. Like the
# English ones they need the wording of a wall ("... için giriş yap"), not a bare menu label ("Giriş Yap").
_TR_GATE = r"(giriş yap|oturum aç|üye ol|üye girişi yap|kayıt ol|abone ol)"
WALL_SIGNATURES_TR = {
    "cookie consent": re.compile(r"çerezleri kabul e[td]|çerez (politikası|tercihleri|ayarları|bildirimi)|"
                                 r"çerez\w* kullan(ıyoruz|ılmaktadır|maktayız)|çerezlere izin ver"),
    "login": re.compile(r"(devam etmek|görüntülemek|görmek|okumak|erişmek|ulaşmak|incelemek) için (lütfen )?[^.!?]{0,40}"
                        + _TR_GATE + r"|lütfen (giriş yap|oturum aç)|(giriş yap|üye ol|oturum aç)manız gerek|"
                        r"bu (sayfa|içerik) (sadece|yalnızca) üyeler"),
    "age gate": re.compile(r"18 yaşından (büyük|küçük)|yaşınızı (doğrulayın|onaylayın)|18 yaşını doldur"),
    "geo block": re.compile(r"(ülkenizde|bölgenizde) (kullanılamıyor|kullanılamamaktadır|mevcut değil|erişilemiyor)|"
                            r"(ülkenizi|bölgenizi) seçin"),
}
PAYWALL_TR = re.compile(r"devamını (okumak|görmek) için|okumaya devam etmek için " + _TR_GATE + r"|abonelere özel|"
                        r"(sadece|yalnızca) aboneler|bu (haber|yazı|içerik) (sadece |yalnızca )?abonelerimize|"
                        r"(haberin|yazının|içeriğin) devamı için " + _TR_GATE)
WALL_TEXT_LANGUAGES = frozenset({"en", "tr"})
_TRACKING_IFRAME = re.compile(TRACKING_IFRAME_PATTERN, re.I)
_DECORATIVE_CANVAS = re.compile(DECORATIVE_CANVAS_HINT, re.I)


def tracking_iframe(frame: dict) -> str | None:
    """Why an iframe is not content: it sits in <noscript>, is hidden, or comes from a tracker, consent tool or bot check."""
    src = frame.get("src") or ""
    host = (urlsplit(src if "//" in src else "//" + src).hostname or "").lower()
    if frame.get("in_noscript"):
        return "inside <noscript> (a tag-manager fallback)"
    if frame.get("hidden"):
        return "hidden, or sized 0 or 1 pixel"
    if any(host == known or host.endswith("." + known) for known in TRACKING_IFRAME_HOSTS):
        return f"served by {host}, a tracking, consent or verification service"
    if _TRACKING_IFRAME.search(src):
        return "its address is a tag-manager, pixel or verification endpoint"
    return None


def decorative_canvas(canvas: dict) -> str | None:
    """Why a canvas needs no text alternative: it is hidden from assistive technology, or named as an effect."""
    if canvas.get("hidden"):
        return "hidden or aria-hidden"
    if canvas.get("role") in ("presentation", "none"):
        return f'role="{canvas["role"]}"'
    if canvas.get("hint") and _DECORATIVE_CANVAS.search(canvas["hint"]):
        return f"its id or class ({canvas['hint']!r}) names an animation or background effect"
    return None


ENABLE_JS = re.compile(r"enable javascript|javascript (is )?(required|disabled)|requires javascript", re.I)
LOAD_MORE = re.compile(r"\b(load|show|see|view|read)\s+more\b", re.I)
# Consent and cookie UI is injected by JavaScript on most sites. It is rendered-only by design and is
# not content anyone asks a question about, so it is left out of RND-2's automatic candidate list
# (seen on the first live audit of a real site, where "A little about cookies" was the top finding).
CONSENT_UI = re.compile(r"\bcookies?\b|\bconsent\b|privacy (preferences|settings|choices)|\bgdpr\b|"
                        r"manage (your )?(preferences|choices)|tracking preferences", re.I)


def _norm(text: str) -> str:
    return " ".join(text.casefold().split())


def _render(result: CrawlResult):
    return getattr(result, "render", None)


def citable(page) -> bool:
    """A page the site tells engines not to index cannot be cited, so a content gap on it is not a
    citation problem. ACC-3 already reports the directive itself (one report per root cause). Seen on
    a 50-page live audit, where an app's noindexed /onboarding page was reported as an S2 gap."""
    return not noindex_directives(page.analysis, page.headers)


def _rendered_ok(result: CrawlResult) -> dict[str, dict]:
    render = _render(result)
    return {u: e for u, e in (render.pages if render else {}).items() if e.get("ok")}


# -- RND-1 -------------------------------------------------------------------

DELTA_STATEMENT = "This text was absent from the initial HTML response and appeared only after client-side rendering."
# A rendered fragment is quoted when it has three or more words or any digit: that keeps short facts such as
# "Pro plan $49/mo" and drops one- and two-word UI labels ("Menu", "Sign in").
DATA_REQUEST_TYPES = ("xhr", "fetch")


def content_delta(raw: dict, entry: dict, limit: int = 10) -> dict:
    """Which text the rendered view has that the raw HTML does not, quoted, and what the browser fetched meanwhile.

    Each missing block is checked against the raw <noscript> text and, for key pages, the raw markup, because
    "missing from visible text" and "missing from the response" are different facts. Requests are listed, not
    matched to blocks: which request supplied which text is not determined.
    """
    raw_text = _norm(raw.get("_visible_text", ""))
    noscript = _norm(raw.get("noscript_text", ""))
    markup = _norm(raw["_raw_html"]) if raw.get("_raw_html") else None
    missing, seen = [], set()
    for block in entry["rendered"].get("_text_blocks", []):
        norm = _norm(block)
        if not (len(norm.split()) >= 3 or any(c.isdigit() for c in norm)) or norm in seen or norm in raw_text:
            continue
        seen.add(norm)
        also = ("raw <noscript> only" if norm in noscript else
                "raw markup only (script data or attributes)" if markup is not None and norm in markup else
                None if markup is not None else "not checked (raw markup kept for key pages only)")
        missing.append({"text": block.strip()[:200], "chars": len(block.strip()), "in_raw_response": also})
    requests = [{"url": r["url"], "type": r["type"], "status": r.get("status")}
                for r in entry.get("requests", []) if r["type"] in DATA_REQUEST_TYPES and r["action"] == "allowed"]
    # DECISIONS 368: each missing block's element and the section it sits in (the heading above it in the page)
    from ..example_rows import locate_blocks
    rendered = entry["rendered"]
    located = locate_blocks([m["text"] for m in missing[:limit]], rendered.get("headings"), rendered.get("buttons"),
                            [x.get("anchor") for x in entry.get("rendered_links") or [] if isinstance(x, dict)],
                            rendered.get("_text_blocks"))
    return {"statement": DELTA_STATEMENT,
            "missing_text_blocks": missing[:limit], "missing_text_block_count": len(missing), "located": located,
            "missing_chars": sum(m["chars"] for m in missing),
            "data_requests_during_render": requests[:limit],
            "iframes_in_rendered_dom": len(entry["rendered"].get("iframes", [])),
            "attribution": "Requests made while the page rendered are listed; which one supplied which text is "
                           "not determined. Text hidden by CSS in either view is counted as text (styles are "
                           "not read)."}


def _missing_line(delta: dict) -> dict:
    """{"row": ...}: the page's line naming the text that arrives with JavaScript (DECISIONS 368), or {}."""
    from ..example_rows import missing_row
    return {"row": missing_row(delta["located"])} if delta.get("located") else {}


def t0_shell_signals(analysis: dict) -> list[str]:
    signals = []
    empty_mounts = [m["id"] for m in analysis["mount_nodes"] if m["chars"] == 0]
    if empty_mounts:
        signals.append(f"empty framework mount node(s): {', '.join('#' + m for m in empty_mounts)}")
    if ENABLE_JS.search(analysis["noscript_text"]):
        signals.append(f"<noscript> says: {analysis['noscript_text'][:80]!r}")
    if analysis["inline_script_chars"] > 10 * max(analysis["visible_chars"], 1) and analysis["inline_script_chars"] > 2000:
        signals.append(f"inline script ({analysis['inline_script_chars']} chars) dwarfs visible text "
                       f"({analysis['visible_chars']} chars)")
    return signals


def rnd1_rendering_gap(result: CrawlResult, cfg: CrawlConfig) -> CheckResult:
    title = "Client-side rendering gap (raw vs rendered)"
    key_urls = set(key_page_urls(result, cfg))
    rendered = _rendered_ok(result)
    readable = [p for p in result.pages if _readable_html(p) and p.content_checks_eligible]
    pages = [p for p in readable if citable(p)]
    noindexed = [p.url for p in readable if not citable(p)]
    missing, partial, suspected, compared = [], [], [], []

    from ..page_groups import is_utility_address
    for page in pages:
        if is_utility_address(page.url):  # DECISIONS 371: an account, sign-in or cart page is not content
            continue
        raw = page.analysis
        entry = rendered.get(page.url)
        if entry:
            r = entry["rendered"]
            raw_words, rendered_words = raw["visible_words"], r["visible_words"]
            ratio = raw_words / rendered_words if rendered_words else None
            raw_heads = {_norm(h["text"]) for h in raw["headings"]}
            row = {"url": page.url, "raw_words": raw_words, "rendered_words": rendered_words,
                   "ratio": None if ratio is None else round(ratio, 3),
                   "headings_only_after_render": [h for h in r["headings"] if _norm(h["text"]) not in raw_heads][:20]}
            compared.append(row)
            if ratio is None:
                continue
            if ratio < cfg.raw_missing_ratio or (raw_words < cfg.raw_min_words and rendered_words > cfg.rendered_min_words):
                delta = content_delta(raw, entry)
                missing.append({**row, "content_delta": delta, **_missing_line(delta)})
            elif ratio < cfg.raw_partial_ratio:
                delta = content_delta(raw, entry)
                partial.append({**row, "content_delta": delta, **_missing_line(delta)})
        else:
            signals = t0_shell_signals(raw)
            if signals and (len(signals) >= 2 or raw["visible_words"] < cfg.raw_min_words):
                suspected.append({"url": page.url, "raw_words": raw["visible_words"], "signals": signals})

    findings = []
    common = dict(rationale=Rationale.MEASURED.value + " (Vercel/MERJ)", engines=NON_RENDERING)
    if missing:
        urls = [r["url"] for r in missing]
        findings.append(Finding(
            "RND-1", f"Main content is missing from the raw HTML of {len(urls)} page(s): it appears only after JavaScript runs",
            Severity.S2, Confidence.VERIFIED, common["rationale"], common["engines"], scope_for(urls),
            {"pages": missing[:40], "thresholds": {"raw_below_ratio": cfg.raw_missing_ratio,
                                                   "or_raw_below_words": cfg.raw_min_words,
                                                   "while_rendered_above_words": cfg.rendered_min_words}},
            "the main content is in the HTML the server sends",
            "Server-render or pre-render these pages (SSR, static generation, or prerendering) so the text is in the "
            "initial HTML response.",
            cost_tier="T1", notes=[GOOGLE_NOTE, DELTA_STATEMENT + " Each page's content_delta quotes that text."],
            importance_tier=_tier(urls, key_urls),
        ))
    if partial:
        urls = [r["url"] for r in partial]
        findings.append(Finding(
            "RND-1", f"Part of the content ({cfg.raw_missing_ratio:.0%}–{cfg.raw_partial_ratio:.0%} present) is missing "
                     f"from the raw HTML of {len(urls)} page(s)",
            Severity.S3, Confidence.VERIFIED, common["rationale"], common["engines"], scope_for(urls),
            {"pages": partial[:40]}, "the main content is in the HTML the server sends",
            "Server-render the sections quoted in each page's content_delta (and headings_only_after_render).",
            cost_tier="T1", notes=[GOOGLE_NOTE, DELTA_STATEMENT + " Each page's content_delta quotes that text."],
            importance_tier=_tier(urls, key_urls),
        ))
    if suspected:
        urls = [r["url"] for r in suspected]
        findings.append(Finding(
            "RND-1", f"{len(urls)} page(s) that were not rendered may be client-rendered (raw-HTML heuristics)",
            Severity.S2, Confidence.ESTIMATED, common["rationale"], common["engines"], scope_for(urls),
            {"pages": suspected[:40], "method": "T0 heuristics: empty mount node, <noscript> JavaScript notice, "
                                                 "script-heavy markup"},
            "the main content is in the HTML the server sends",
            "Render one of these pages to confirm (it was outside the render sample), then server-render if confirmed.",
            notes=[GOOGLE_NOTE, "Estimated: these pages were not rendered, so the gap is inferred from raw-HTML signals."],
            importance_tier=_tier(urls, key_urls),
        ))
    render = _render(result)
    evidence = {"compared": compared[:40], "rendered_pages": len(rendered),
                "excluded_noindex": noindexed[:40],
                "render_mode": render.mode if render else "raw_html_only",
                "render_reason": render.reason if render else None,
                "render_failed_pages": sum(1 for item in (render.pages.values() if render else [])
                                            if not item.get("ok")),
                "third_party_resources_blocked": sum(1 for item in (render.pages.values() if render else [])
                                                      for req in item.get("requests", [])
                                                      if req.get("action") == "aborted"
                                                      and "third-party" in (req.get("reason") or "")),
                "english_only_heuristics": "the <noscript> 'enable JavaScript' signal (mount-node and script-size "
                                           "signals, and every rendered comparison, are language independent)"}
    if not pages:
        return CheckResult("RND-1", title, "not_assessed", "No readable HTML pages.", evidence=evidence)
    summary = (f"{len(findings)} finding(s); {len(rendered)} page(s) rendered and compared, others checked with T0 heuristics."
               if findings else f"No rendering gap on {len(rendered)} rendered page(s); no client-rendering signals elsewhere.")
    return CheckResult("RND-1", title, _status(findings), summary, findings, evidence)


# -- RND-2 -------------------------------------------------------------------

def rnd2_critical_facts(result: CrawlResult, cfg: CrawlConfig) -> CheckResult:
    title = "Critical facts present in raw HTML"
    key_urls = set(key_page_urls(result, cfg))
    rendered = _rendered_ok(result)
    by_url = {p.url: p for p in result.pages}
    only_after_js, only_in_markup, found, not_found, not_assessed = [], [], [], [], []

    for page_ref, fact in cfg.critical_facts:
        url = normalize_url(page_ref, result.origin)
        page = by_url.get(url) if url else None
        row = {"url": url or page_ref, "fact": fact}
        if page is None or not _readable_html(page):
            not_assessed.append({**row, "reason": "page not fetched or not readable"})
            continue
        needle = _norm(fact)
        raw_text = _norm(page.analysis.get("_visible_text", ""))
        if needle in raw_text:
            i = raw_text.index(needle)
            found.append({**row, "where": "raw HTML visible text", "snippet": raw_text[max(0, i - 40): i + len(needle) + 40]})
            continue
        raw_markup = page.analysis.get("_raw_html")
        entry = rendered.get(url)
        rendered_text = _norm(entry["rendered"].get("_visible_text", "")) if entry else ""
        if raw_markup is not None and needle in _norm(raw_markup):
            only_in_markup.append({**row, "where": "raw HTML markup only (script data or attributes), not visible text"})
        elif entry and needle in rendered_text:
            only_after_js.append({**row, "where": "rendered view only (appears after JavaScript)"})
        elif entry is None and raw_markup is None:
            not_assessed.append({**row, "reason": "not in raw visible text; page not rendered and markup not kept "
                                                  "(mark it as a key page to keep its markup)"})
        else:
            not_found.append({**row, "pdf_links": [l["href"] for l in page.analysis["pdf_links"]][:5]})

    findings, review_items = [], []
    for rows, label, why in ((only_after_js, "appear only after JavaScript runs", "rendered view"),
                             (only_in_markup, "exist only inside markup (script data or attributes), not as visible text",
                              "raw markup")):
        if rows:
            urls = sorted({r["url"] for r in rows})
            findings.append(Finding(
                "RND-2", f"{len(rows)} declared critical fact(s) {label}", Severity.S2, Confidence.VERIFIED,
                Rationale.MEASURED.value + " (via RND-1)", NON_RENDERING, scope_for(urls),
                {"facts": rows, "matching": "case-insensitive exact text, whitespace normalized"},
                "critical facts are visible text in the HTML the server sends",
                "Put these facts in server-rendered visible text (not only in JavaScript, JSON state, or attributes).",
                cost_tier="T1" if label.startswith("appear") else "T0", notes=[GOOGLE_NOTE],
                importance_tier=_tier(urls, key_urls),
            ))
    if not_found:
        urls = sorted({r["url"] for r in not_found})
        review_items.append(ReviewItem(
            "RND-2", f"{len(not_found)} declared critical fact(s) were not found on their page at all",
            "The exact text is in neither the raw HTML nor the rendered view. The wording may have changed, the fact "
            "may live elsewhere (for example a linked PDF), or it may be missing from the page.",
            Confidence.VERIFIED, NON_RENDERING, scope_for(urls), {"facts": not_found},
            "Check the page and update either the page or the declared fact.", importance_tier=_tier(urls, key_urls),
        ))

    # Automatic candidates (Estimated): headings and prices present only after render.
    candidates, consent_ui, live_prices = [], [], []
    declared_pages = {normalize_url(p, result.origin) for p, _ in cfg.critical_facts}
    for url, entry in rendered.items():
        page = by_url.get(url)
        if page is None or page.analysis is None or url in declared_pages or not citable(page):
            continue
        raw_text = _norm(page.analysis.get("_visible_text", ""))
        r = entry["rendered"]
        headings = [h["text"] for h in r["headings"]
                    if _norm(h["text"]) not in raw_text and not CONSENT_UI.search(h["text"])]
        consent_only = [h["text"] for h in r["headings"]
                        if _norm(h["text"]) not in raw_text and CONSENT_UI.search(h["text"])]
        if consent_only:
            consent_ui.append({"url": url, "headings": consent_only[:5]})
        prices = sorted({m.group(0).strip() for m in PRICE.finditer(r.get("_visible_text", ""))
                         if _norm(m.group(0)) not in raw_text})
        raw_count = len(PRICE.findall(page.analysis.get("_visible_text", "")))
        rendered_count = len(PRICE.findall(r.get("_visible_text", "")))
        if prices and raw_count >= 0.8 * rendered_count:
            # The raw HTML shows about as many prices as the rendered view: the values changed between the two
            # fetches (live quotes), the prices are not missing. Seen live on 2026-09-22 (Midas /canli-kripto/: 272
            # prices in the raw text, reported S2 because each live value differed by the time of the render).
            live_prices.append({"url": url, "prices_in_raw_text": raw_count, "prices_in_rendered_view": rendered_count,
                                "differing_values_sample": prices[:5]})
            prices = []
        if headings or prices:
            candidates.append({"url": url, "headings_only_after_render": headings[:10], "prices_only_after_render": prices[:10]})
    if candidates:
        urls = [c["url"] for c in candidates]
        findings.append(Finding(
            "RND-2", f"{len(urls)} rendered page(s) have headings or prices that appear only after JavaScript (automatic "
                     "candidates)",
            Severity.S2, Confidence.ESTIMATED, Rationale.MEASURED.value + " (via RND-1)", NON_RENDERING, scope_for(urls),
            {"pages": candidates[:40], "method": "rendered-only headings and price patterns; no facts were declared "
                                                 "for these pages",
             "consent_ui_ignored": consent_ui[:20]},
            "facts people ask about are visible text in the HTML the server sends",
            "Confirm these are facts people ask about; declare them as critical facts for exact checking, and "
            "server-render them.",
            cost_tier="T1", notes=[GOOGLE_NOTE, "Estimated: candidates are selected automatically."],
            importance_tier=_tier(urls, key_urls),
        ))

    evidence = {"declared_facts": len(cfg.critical_facts), "found_in_raw_html": found, "not_assessed": not_assessed,
                "consent_ui_ignored": consent_ui[:20],
                "live_values_not_missing": live_prices[:20]}
    if not cfg.critical_facts and not rendered:
        return CheckResult("RND-2", title, "not_assessed",
                           "No critical facts were declared and no pages were rendered, so there is nothing to check.",
                           evidence=evidence)
    summary = (f"{len(findings)} finding(s), {len(review_items)} review item(s); {len(found)} declared fact(s) found in raw HTML."
               if findings or review_items else f"All {len(found)} declared fact(s) are in raw HTML; no rendered-only candidates.")
    return CheckResult("RND-2", title, _status(findings, review_items), summary, findings, evidence, [], review_items)


# -- RND-3 -------------------------------------------------------------------

RND3_CHECK_NOTE = ("Low, a check: these pages were not opened in a browser, and the 'load more' button wording is matched "
                   "in English only. Open one page in a browser to see whether content is really behind the button.")

def rnd3_interaction(result: CrawlResult, cfg: CrawlConfig) -> CheckResult:
    title = "Content behind interaction"
    key_urls = set(key_page_urls(result, cfg))
    rendered = _rendered_ok(result)
    revealed, suspected, text_not_assessed, late_loading, another_article, chrome_expanded = [], [], [], [], [], []
    from ..page_groups import is_utility_address
    for page in result.pages:
        if not (_readable_html(page) and page.content_checks_eligible and citable(page)):
            continue
        if is_utility_address(page.url):  # DECISIONS 371: an account, sign-in or cart page is not content
            continue
        entry = rendered.get(page.url)
        if entry and entry.get("interaction"):
            first, after = entry["rendered"], entry["interaction"]["after"]
            # Judge the click against the no-click control when there is one (renders before v2 had none).
            before = entry["interaction"].get("control") or first
            late = before["visible_words"] - first["visible_words"]
            if late > 0:
                late_loading.append({"url": page.url, "words_at_first_snapshot": first["visible_words"],
                                     "words_after_waiting_without_clicking": before["visible_words"],
                                     "wait_ms": entry["interaction"].get("control_wait_ms")})
            new_words = after["visible_words"] - before["visible_words"]
            h1_before = sum(1 for h in before["headings"] if h["level"] == 1)
            h1_after = sum(1 for h in after["headings"] if h["level"] == 1)
            if new_words > 0 and h1_after > h1_before:
                # A new <h1> arrived with the text: an infinite scroll loaded another article, not this page's own
                # hidden content. Seen live on 2026-09-22 (Midas): scrolling a news page fetched the next article
                # (a "loadmore" request) and was reported as S3 content behind interaction.
                another_article.append({"url": page.url, "words_added": new_words,
                                        "new_h1": [h["text"][:120] for h in after["headings"] if h["level"] == 1
                                                   and h not in before["headings"]][:3],
                                        "clicked": entry["interaction"]["clicked"]})
                continue
            grew = after["visible_chars"] - before["visible_chars"]
            main_grew = after["main_region_chars"] - before["main_region_chars"]
            if (grew > 0 and before["has_main_region"] and after["has_main_region"]
                    and main_grew < 0.2 * grew):
                # The text appeared outside <main>/<article>: a navigation menu or other page chrome opened. Seen
                # live on 2026-09-22 (withmaya.ai): "Open menu" / "Product" clicks added 47 words to 8 docs pages,
                # all in the menus, while the main content stayed at exactly the same length.
                chrome_expanded.append({"url": page.url, "chars_added": grew, "chars_added_to_main_content": main_grew,
                                        "clicked": entry["interaction"]["clicked"]})
                continue
            if new_words >= cfg.interaction_min_new_words or (
                    before["visible_words"] and new_words / before["visible_words"] >= cfg.interaction_min_growth and new_words > 0):
                before_text = set(_norm(before.get("_visible_text", "")).split())
                added = [w for w in _norm(after.get("_visible_text", "")).split() if w not in before_text][:30]
                # DECISIONS 368: which content: the headings and text blocks that appeared, as the page writes them
                from ..example_rows import revealed_row
                had = {_norm(h["text"]) for h in before["headings"]}
                new_headings = [h["text"][:120] for h in after["headings"] if _norm(h["text"]) not in had][:10]
                had_blocks = {_norm(b) for b in before.get("_text_blocks") or []}
                new_blocks = [b.strip()[:200] for b in after.get("_text_blocks") or [] if _norm(b) not in had_blocks
                              and len(b.split()) >= 3][:5]
                clicked = entry["interaction"]["clicked"]
                revealed.append({"url": page.url, "words_before": before["visible_words"],
                                 "words_after": after["visible_words"], "clicked": clicked,
                                 "new_headings": new_headings, "new_text_blocks": new_blocks,
                                 "row": revealed_row(clicked, new_headings, new_blocks[0] if new_blocks else " ".join(added)),
                                 "new_text_sample": " ".join(added),
                                 "compared_against": "control snapshot (same wait, no click)"
                                 if entry["interaction"].get("control") else "first rendered snapshot (no control)"})
        elif entry is None:
            a = page.analysis
            empty_panels = [t["id"] for t in a["tabpanels"] if t["chars"] == 0]
            load_more = [b["text"] for b in a["buttons"] if LOAD_MORE.search(b["text"]) and not b["in_form"]]
            if empty_panels or load_more:
                suspected.append({"url": page.url, "empty_tabpanels": empty_panels, "load_more_buttons": load_more})
            else:
                # The "load more" wording is English only (tab panels are not). On a page that is not English,
                # finding no such button means nothing, so it is listed rather than counted as clean (as RND-5).
                assessable, why = english_text_assessable(a)
                if not assessable:
                    text_not_assessed.append({"url": page.url, "reason": why})

    findings = []
    if revealed:
        urls = [r["url"] for r in revealed]
        findings.append(Finding(
            "RND-3", f"{len(urls)} page(s) show more content only after a click or scroll", Severity.S3, Confidence.VERIFIED,
            Rationale.MEASURED.value + " (by extension of RND-1)", NON_RENDERING + ["Google (does not click)"],
            scope_for(urls), {"pages": revealed[:40]}, "content that should be cited is in the page without interaction",
            "Include the tab, accordion, or 'load more' content in the initial HTML (it can stay visually collapsed).",
            cost_tier="T1", importance_tier=_tier(urls, key_urls),
            notes=["Interactions were limited to tabs, collapsed sections, and 'load/show/read more' controls; no forms, "
                   "no navigation, and no non-GET requests."],
        ))
    if suspected:
        urls = [r["url"] for r in suspected]
        findings.append(Finding(
            "RND-3", f"{len(urls)} page(s) that were not rendered may hide content behind interaction (raw-HTML heuristics)",
            # Low, a check (DECISIONS 290): a guess from raw HTML on pages no browser opened, and the "load more" wording
            # is matched in English only.
            Severity.S4, Confidence.ESTIMATED, Rationale.MEASURED.value + " (by extension of RND-1)",
            NON_RENDERING + ["Google (does not click)"], scope_for(urls), {"pages": suspected[:40]},
            "content that should be cited is in the page without interaction",
            "Render one of these pages to confirm, then include the hidden content in the initial HTML.",
            importance_tier=_tier(urls, key_urls), notes=["Estimated: empty tab panels or 'load more' buttons in raw HTML.",
                                                          RND3_CHECK_NOTE],
        ))
    summary = (f"{len(findings)} finding(s)." if findings else
               f"No content found behind interaction on {len(rendered)} rendered page(s); other pages checked with "
               "raw-HTML heuristics.")
    observations = ([{"metric": "text that appeared with no click while waiting (late loading, not credited to "
                                "interaction)", "pages": late_loading[:20]}] if late_loading else [])
    if chrome_expanded:
        observations.append({"metric": "clicks opened menus or other page chrome outside <main>/<article>; the main "
                                       "content did not grow, so this is not content behind interaction",
                             "pages": chrome_expanded[:20]})
    if another_article:
        observations.append({"metric": "another article loaded on scroll or click (a new <h1> arrived with the text); "
                                       "not this page's hidden content (Estimated)", "pages": another_article[:20]})
    if text_not_assessed:
        summary += (f" The 'load more' heuristic is English only: {len(text_not_assessed)} unrendered non-English "
                    "page(s) were not assessed for it.")
    return CheckResult("RND-3", title, _status(findings), summary, findings,
                       {"interactions_enabled": cfg.render_interactions, "rendered_pages": len(rendered),
                        "text_heuristics_not_assessed": text_not_assessed[:40],
                        "text_heuristics_not_assessed_count": len(text_not_assessed),
                        "control_snapshot": "the page is left alone for the same wait before clicking; only text "
                                            "beyond that control counts as revealed by interaction",
                        "english_only_heuristics": "'load/show/see/view/read more' button text (tabs and "
                                                   "aria-expanded controls are language independent)"},
                       observations)


# -- RND-4 -------------------------------------------------------------------

def banner_shaped_without_alt(img: dict) -> bool:
    """Banner-shaped (wide) image with no or empty alt: a guess that it may carry text (RND-4; STR-7 skips these)."""
    w, h = img["width"], img["height"]
    return not img["alt"] and bool(w and h and w >= 300 and w / h >= 2.5)


def rnd4_non_text(result: CrawlResult, cfg: CrawlConfig) -> CheckResult:
    title = "Text locked in non-text formats"
    key_urls = set(key_page_urls(result, cfg))
    iframes, canvases, images, pdfs = [], [], [], []
    ignored_iframes, ignored_canvases = [], []
    unnamed_frames, frame_names_unknown = [], []
    canvas_marks: list[set] = []  # per page read: which unlabelled canvases it has, to tell a layout's from a page's own
    for page in result.pages:
        if not (_readable_html(page) and page.content_checks_eligible):
            continue
        a = page.analysis
        # Accessible frame names matter independently of search indexability or main-region placement.
        for frame in a.get('iframes') or []:
            if not frame.get('src') or tracking_iframe(frame) or frame.get('role') in ('presentation','none'):continue
            frame_row={"url":page.url,"iframe_src":frame['src'],"element_id":frame.get('element_id'),
                "requested_at":getattr(page,'requested_at',None),
                "observed_at":(a.get('content_observation')or{}).get('observed_at')or getattr(page,'requested_at',None),
                "source":(a.get('content_observation')or{}).get('source')or getattr(page,'view','saved HTML'),"name_evidence":dict(frame)}
            if frame.get('name_assessed') is True:
                if not frame.get('accessible_name'):unnamed_frames.append(frame_row)
            elif not (frame.get('title')or'').strip():frame_names_unknown.append(frame_row)
        if not citable(page):continue
        marks: Counter = Counter()
        canvas_marks.append(set())
        in_content = (lambda item: item["in_main"]) if a["has_main_region"] else (lambda item: True)
        frames_seen: set[str] = set()
        for frame in a["iframes"]:
            if in_content(frame) and frame["src"]:
                if frame["src"] in frames_seen:
                    continue  # the same embed twice on one page (a video shown for two screen sizes) is one row
                frames_seen.add(frame["src"])
                why = tracking_iframe(frame)
                if why:
                    ignored_iframes.append({"url": page.url, "iframe_src": frame["src"], "why": why})
                else:
                    iframes.append({"url": page.url, "iframe_src": frame["src"], "title": frame["title"]})
        for canvas in a["canvases"]:
            if in_content(canvas) and not canvas["aria_label"] and canvas["fallback_chars"] == 0:
                why = decorative_canvas(canvas)
                if why:
                    ignored_canvases.append({"url": page.url, "canvas": canvas.get("hint"), "why": why})
                else:
                    # The same canvas on another page has the same id or class and the same place in the order.
                    marks[canvas.get("hint")] += 1
                    mark = (canvas.get("hint"), marks[canvas.get("hint")])
                    canvas_marks[-1].add(mark)
                    canvases.append({"url": page.url, "canvas": canvas.get("hint"), "_mark": mark})
        for img in a["images"]:
            w, h = img["width"], img["height"]
            if in_content(img) and banner_shaped_without_alt(img):
                images.append({"url": page.url, "src": img["src"], "width": w, "height": h, "alt": img["alt"]})
        for link in a["pdf_links"]:
            if in_content(link):
                pdfs.append({"url": page.url, "pdf": link["href"]})

    findings = []
    if unnamed_frames:
        urls=sorted({r['url']for r in unnamed_frames})
        findings.append(Finding("RND-4", f"{len(unnamed_frames)} iframe(s) lack an accessible name on {len(urls)} page(s)",
            Severity.S4,Confidence.VERIFIED,Rationale.MEASURED.value,['screen readers'],scope_for(urls),
            {'items':unnamed_frames,'assessment':'complete captured naming attributes and resolved label references',
             'source_collection_times':sorted({r['observed_at']for r in unnamed_frames if r.get('observed_at')})},
            'each applicable iframe has a descriptive accessible name',
            'Add a descriptive title attribute to each unnamed iframe, or supply a valid aria-label or resolvable aria-labelledby. Verify its name in the accessibility tree; iframe presence alone establishes no SEO extraction failure.',
            importance_tier=_tier(urls,key_urls)))
    # A canvas found on most pages belongs to the site's layout (a background animation, a cursor effect), not to
    # any one page's content: one note for the site, instead of a finding listing every page. A canvas only some
    # pages have (a chart, a diagram) is still reported page by page. Seen live on 2026-10-07: one layout canvas
    # with no id or class produced a 43-page finding.
    layout_marks = appears_on_most(canvas_marks)
    layout_canvases = [row for row in canvases if row["_mark"] in layout_marks]
    canvases = [row for row in canvases if row["_mark"] not in layout_marks]
    for row in layout_canvases + canvases:
        row.pop("_mark")
    if layout_canvases:
        urls = sorted({row["url"] for row in layout_canvases})
        findings.append(Finding(
            "RND-4", f"The same <canvas> is on {len(urls)} of {len(canvas_marks)} page(s): part of the site's layout, "
                     "with no text equivalent",
            Severity.INFO, Confidence.INFERRED, Rationale.HYPOTHESIS.value, ["all answer engines that extract page text"],
            scope_for(urls, sitewide=True),
            {"pages_with_it": len(urls), "pages_read": len(canvas_marks), "share_needed": SITEWIDE_SHARE,
             "canvas": sorted({str(row["canvas"] or "(no id or class)") for row in layout_canvases}), "items": layout_canvases[:20]},
            "a canvas that only decorates is marked as decoration; one that shows content has a text equivalent",
            'If it is decoration (a background animation), nothing needs fixing; adding aria-hidden="true" says so. '
            "If it shows something readers need, add a text equivalent.",
            importance_tier=2,
            notes=["Inferred: a canvas on most pages is taken to be part of the layout, not page content. That it carries no "
                   "content is not verified; what it draws was not looked at."]))
    groups = (
        (iframes, "iframe", Confidence.INFERRED, "embed content in an iframe; essential content and accessibility are not established",
         "Review the embedded content and its text alternative; add equivalent page text only if essential information is otherwise unavailable."),
        (canvases, "canvas", Confidence.VERIFIED, "draw content on a <canvas> with no text equivalent",
         "Add a text equivalent (a table, aria-label, or fallback content) for what the canvas shows."),
        (images, "image-of-text", Confidence.ESTIMATED, "show banner-shaped images with no alt text in main content "
                                                        "(may contain text)",
         "If these images contain text, put that text in the HTML or in descriptive alt text."),
    )
    for rows, kind, confidence, label, fix in groups:
        if rows:
            urls = sorted({r["url"] for r in rows})
            findings.append(Finding(
                "RND-4", f"{len(urls)} page(s) {label}", Severity.INFO if kind == "iframe" else Severity.S4, confidence, Rationale.HYPOTHESIS.value,
                ["all answer engines that extract page text"], scope_for(urls), {"items": rows[:60]},
                "key text is present as HTML text", fix, importance_tier=_tier(urls, key_urls),
                notes=["Capped at S4: Hypothesis."] + (["Estimated: OCR is not built, so 'contains text' is a guess from "
                                                        "the image's dimensions and missing alt."] if kind == "image-of-text" else []),
            ))
    observations = ([{"metric": "PDF links in main content (facts only in PDFs are not checked)", "value": len(pdfs),
                      "sample": pdfs[:20]}] if pdfs else [])
    summary = f"{len(findings)} finding(s)." if findings else "No iframe, canvas, or image-of-text content found in main content."
    if frame_names_unknown:
        observations.append({'metric':'iframe accessible names not assessed: naming evidence unavailable','value':len(frame_names_unknown),'sample':frame_names_unknown})
    if ignored_iframes or ignored_canvases:
        summary += (f" Left out as not content: {len(ignored_iframes)} tracking, consent or hidden iframe(s) and "
                    f"{len(ignored_canvases)} decorative canvas(es).")
    return CheckResult("RND-4", title, _status(findings), summary, findings,
                       {"ocr": "not built", "iframe_names_unassessed":frame_names_unknown,
                        "ignored_tracking_iframes_count": len(ignored_iframes), "ignored_tracking_iframes": ignored_iframes[:40],
                        "ignored_decorative_canvases_count": len(ignored_canvases),
                        "ignored_decorative_canvases": ignored_canvases[:40]}, observations)


# -- RND-5 -------------------------------------------------------------------

def rnd5_walls(result: CrawlResult, cfg: CrawlConfig) -> CheckResult:
    title = "Interstitials, consent walls, and gated content in raw HTML"
    key_urls = set(key_page_urls(result, cfg))
    redirects, expected_logins, in_place, paywalls, paywall_ok, not_assessed = [], [], [], [], [], []
    assessed_pages = 0
    for page in result.pages:
        if page.status and 300 <= page.status < 400 and page.redirect_location:
            target_path = urlsplit(page.redirect_location).path + ("?" + urlsplit(page.redirect_location).query
                                                                   if urlsplit(page.redirect_location).query else "")
            to_login = login_target(page.redirect_location)
            if (WALL_PATH.search(target_path) or to_login) and not WALL_PATH.search(urlsplit(page.url).path):
                row = {"url": page.url, "status": page.status, "location": page.redirect_location}
                # An account, cart or checkout page that asks a signed-out visitor to sign in does what it should:
                # a note. A content page that does the same, and any consent, age or country wall, is a wall.
                (expected_logins if to_login and account_page(page.url) else redirects).append(row)
            continue
        if not (_readable_html(page) and page.content_checks_eligible) or WALL_PATH.search(urlsplit(page.url).path):
            continue
        a = page.analysis
        text = a.get("_visible_text", "")
        folded = turkish_fold(text)
        matched = sorted({name for name, rx in WALL_SIGNATURES.items() if rx.search(text)}
                         | {name for name, rx in WALL_SIGNATURES_TR.items() if rx.search(folded)})
        if matched and a["visible_words"] <= cfg.wall_max_words:
            in_place.append({"url": page.url, "visible_words": a["visible_words"], "signatures": matched,
                             "text_start": text[:200]})
        paywall = PAYWALL.search(text) or PAYWALL_TR.search(folded)
        if paywall:
            (paywall_ok if a["accessible_for_free"] else paywalls).append(
                {"url": page.url, "isAccessibleForFree": a["accessible_for_free"], "snippet": paywall.group(0)})
        # The signatures are English and Turkish. A page they did not match is only a "no wall" result when its
        # text is in one of those; otherwise it is listed as not assessed instead of silently passing.
        if not (matched and a["visible_words"] <= cfg.wall_max_words) and not paywall:
            assessable, why = text_assessable(a, WALL_TEXT_LANGUAGES)
            if assessable:
                assessed_pages += 1
            else:
                not_assessed.append({"url": page.url, "reason": why})

    findings = []

    def add(rows, condition, severity, confidence, label, rationale, fix):
        if not rows:
            return
        by_url = {r["url"]: r for r in rows}

        def build(its, sev, intent):
            urls = [u for u, _ in its]
            return Finding(
                "RND-5", f"{len(urls)} page(s) {label}", sev, confidence, rationale, NON_RENDERING + ["Google AI Overviews / AI Mode"],
                scope_for(urls), {"pages": [by_url[u] for u in urls][:40]}, "bots receive the content, not a wall", fix,
                intent=intent, importance_tier=_tier(urls, key_urls),
            )
        findings.extend(_with_intent("RND-5", condition, [(r["url"], None) for r in rows], severity, key_urls, cfg, build))

    add(redirects, "wall_redirect", Severity.S1, Confidence.VERIFIED,
        "redirect a cookie-less visitor to a login, consent, age, or country page",
        "Measured (crawlers can't pass walls) + observed redirect",
        "Serve the content to cookie-less visitors and overlay the wall instead of redirecting, or mark it intended.")
    add(in_place, "wall_in_place", Severity.S2, Confidence.ESTIMATED,
        "serve a short page that looks like a consent, login, age, or geo wall instead of the content",
        "Measured (crawlers can't pass walls) + text signature",
        "Put the content in the HTML and show the wall as an overlay, or mark it intended.")
    add(paywalls, "paywall_without_structured_data", Severity.S4, Confidence.ESTIMATED,
        "look paywalled but have no isAccessibleForFree structured data",
        "Hypothesis (paywall structured data benefit for AI engines)",
        "Add paywalled-content structured data (isAccessibleForFree: false with hasPart) so engines can tell a "
        "paywall from cloaking.")
    if expected_logins:
        urls = [row["url"] for row in expected_logins]
        findings.append(Finding(
            "RND-5", f"{len(urls)} account, cart or checkout page(s) send a signed-out visitor to the login page (expected)",
            Severity.INFO, Confidence.VERIFIED, "Observed redirect", NON_RENDERING + ["Google AI Overviews / AI Mode"],
            scope_for(urls), {"pages": expected_logins[:40], "kind": "expected", "account_paths": sorted(ACCOUNT_PATHS)},
            "a page that belongs to one signed-in customer asks a visitor to sign in",
            "Nothing to fix. A page that belongs to one signed-in customer has nothing for a crawler to read.",
            notes=["A note, not a problem: recognised by the page's address (account, cart, checkout and sign-in names in "
                   "English and Turkish) and a redirect to a sign-in address, or to one that carries the address to come "
                   "back to. A content page that redirects to the login page is still reported as a wall."],
            importance_tier=_tier(urls, key_urls)))
    for f in findings:
        if f.title.endswith("structured data"):
            f.notes.append("Capped at S4: Hypothesis.")
        if f.confidence == Confidence.ESTIMATED:
            f.notes.append("Estimated: detected by text signatures on a cookie-less fetch with Maya's user agent.")
    gap = (f" Consent, login, age, geo, and paywall text signatures are English and Turkish only: {len(not_assessed)} page(s) "
           "without a match were NOT assessed (another language, or language unknown), so no wall found there means nothing."
           if not_assessed else "")
    if findings:
        summary = f"{len(findings)} finding(s)." + gap
        status = _status(findings)
    elif not_assessed and not assessed_pages:
        summary = "Redirect walls: none found. In-page walls and paywalls: not assessed." + gap
        status = "not_assessed"
    else:
        summary = (f"No walls or unmarked paywalls detected on {assessed_pages} English or Turkish page(s); "
                   "redirect walls checked on every page." + gap)
        status = _status(findings)
    return CheckResult("RND-5", title, status, summary, findings,
                       {"paywalls_with_structured_data": paywall_ok,
                        "text_signatures_language": "English and Turkish",
                        "text_signatures_not_assessed": not_assessed[:100],
                        "text_signatures_not_assessed_count": len(not_assessed),
                        "fetched_as": "Maya's user agent, cookie-less (not a browser user agent; see README)"})


# -- RND-6 -------------------------------------------------------------------

# Said on every RND-6 finding measured on Firecrawl's copy of the pages (DECISIONS 299).
RENDERED_VIA_FIRECRAWL = " (rendered HTML via Firecrawl, not comparable with raw size)"
RENDERED_NOTE = ("Measured on the HTML Firecrawl returned: the page as its browser built it after JavaScript, with ads "
                 "blocked and embedded base64 images removed, not the HTML the server sends. It is not compared with "
                 "Maya's own raw measurement (on nihan.com.tr the same 499 pages were a median 36% larger this way, from 8% "
                 "smaller to 59% larger).")


def rnd6_payload(result: CrawlResult, cfg: CrawlConfig, *, rendered_via_firecrawl: bool = False) -> CheckResult:
    """RND-6 on the pages of `result`. `rendered_via_firecrawl`: the pages are Firecrawl's rendered copies (DECISIONS
    299), so every title and note says so and nothing is set beside Maya's raw sizes."""
    title = "HTML payload size"
    rendered = rendered_via_firecrawl
    key_urls = set(key_page_urls(result, cfg))
    large, late, home_heavy = [], [], []
    home = homepage_url(result)
    for page in result.pages:
        if not _readable_html(page):
            continue
        if page.body_bytes > cfg.payload_max_bytes:
            large.append({"url": page.url, "bytes": page.body_bytes, "truncated_at_read_cap": page.body_truncated})
        elif page.url == home and page.body_bytes > cfg.homepage_payload_max_bytes:
            home_heavy.append({"url": page.url, "bytes": page.body_bytes, "truncated_at_read_cap": page.body_truncated})
        offset = page.analysis["main_offset_bytes"]
        if offset is not None and offset > cfg.main_offset_max_bytes:
            late.append({"url": page.url, "main_offset_bytes": offset, "basis": page.analysis["main_offset_basis"]})
    findings = []
    if large:
        urls = [r["url"] for r in large]
        findings.append(Finding(
            "RND-6", f"{len(urls)} page(s) have HTML larger than {cfg.payload_max_bytes // 1000} KB", Severity.S4,
            Confidence.VERIFIED, Rationale.HYPOTHESIS.value, ["all answer engines (fetch size limits undocumented)"],
            scope_for(urls), {"pages": large[:40], "threshold_bytes": cfg.payload_max_bytes},
            "compact HTML", "Move inlined JSON state, CSS, and SVG out of the HTML.", importance_tier=_tier(urls, key_urls),
            notes=["Capped at S4: Hypothesis. Vendor fetch-size limits are not published; the threshold is policy."],
        ))
    if home_heavy:
        # The homepage's own, lower bar (DECISIONS 258): every visit and crawl starts here.
        row = home_heavy[0]
        findings.append(Finding(
            "RND-6", f"The homepage's HTML is {row['bytes'] // 1000} KB, above {cfg.homepage_payload_max_bytes // 1000} KB",
            Severity.S3, Confidence.VERIFIED, Rationale.HYPOTHESIS.value, ["all answer engines (fetch size limits undocumented)"],
            scope_for([row["url"]]), {"pages": home_heavy, "threshold_bytes": cfg.homepage_payload_max_bytes},
            "compact homepage HTML", "Move inlined JSON state, CSS, scripts and SVG out of the homepage HTML; remove unused "
            "blocks and templates from the theme (on a hosted platform, ask the platform).", importance_tier=0,
            notes=["Medium on the homepage by the owner's decision (DECISIONS 258); the threshold is policy."]))
    if late:
        urls = [r["url"] for r in late]
        estimated = any(r["basis"] != "main/article element" for r in late)
        findings.append(Finding(
            "RND-6", f"{len(urls)} page(s) start their main content more than {cfg.main_offset_max_bytes // 1000} KB into "
                     "the HTML", Severity.S4, Confidence.ESTIMATED if estimated else Confidence.VERIFIED,
            Rationale.HYPOTHESIS.value, ["all answer engines (fetch size limits undocumented)"], scope_for(urls),
            {"pages": late[:40], "threshold_bytes": cfg.main_offset_max_bytes},
            "main content early in the document",
            "Move large inline scripts, styles, and data after the main content or into external files.",
            importance_tier=_tier(urls, key_urls), notes=["Capped at S4: Hypothesis."],
        ))
    summary = f"{len(findings)} finding(s)." if findings else "No oversized HTML and no late-starting main content."
    if rendered:
        for finding in findings:
            finding.title += RENDERED_VIA_FIRECRAWL  # every title says what was measured
            finding.notes.append(RENDERED_NOTE)
            finding.evidence = {**finding.evidence, "html_measured": "rendered (Firecrawl)"}
    return CheckResult("RND-6", title, _status(findings), summary, findings)


# -- RND-7 -------------------------------------------------------------------

def rnd7_main_share(result: CrawlResult, cfg: CrawlConfig, rnd1: CheckResult | None = None) -> CheckResult:
    title = "Main-content-to-boilerplate ratio"
    key_urls = set(key_page_urls(result, cfg))
    # Root cause once: a page whose main content is missing from raw HTML (RND-1) is not reported again here.
    rendering_gap = {u for f in (rnd1.findings if rnd1 else []) if f.severity in (Severity.S2, Severity.S3)
                     for u in f.scope["urls"]}
    low, no_region = [], []
    for page in result.pages:
        if not (_readable_html(page) and page.content_checks_eligible and citable(page)) or not page.analysis["visible_chars"]:
            continue
        if page.url in rendering_gap:
            continue
        a = page.analysis
        if a["has_main_region"]:
            share, basis = a["main_region_chars"] / a["visible_chars"], "native or ARIA main-region text"
        else:
            share, basis = a["paragraph_chars"] / a["visible_chars"], "<p> text (no <main> or <article>)"
            no_region.append(page.url)
        if share < cfg.main_content_min_share:
            low.append({"url": page.url, "main_share": round(share, 3), "basis": basis, "visible_chars": a["visible_chars"]})
    findings = []
    if low:
        urls = [r["url"] for r in low]
        findings.append(Finding(
            "RND-7", f"{len(urls)} page(s) have less than {cfg.main_content_min_share:.0%} of their text in the main content",
            Severity.INFO, Confidence.ESTIMATED, Rationale.HYPOTHESIS.value, ["all answer engines that extract passages"],
            scope_for(urls), {"pages": low[:40], "threshold": cfg.main_content_min_share},
            "main content dominates the page text",
            'Inspect the measured content region and repeated navigation. A low text ratio does not establish that main is missing. Adjust existing boundaries or content only where the saved page supports it.',
            importance_tier=_tier(urls, key_urls),
            notes=["Estimated: region detection is heuristic, and the threshold is an uncalibrated round number.",
                   "Capped at S4: Hypothesis."],
        ))
    if no_region:
        findings.append(Finding(
            "RND-7", f"{len(no_region)} page(s) have no <main> or <article> element", Severity.INFO, Confidence.VERIFIED,
            Rationale.HYPOTHESIS.value, ["all answer engines that extract passages"], scope_for(no_region),
            {"pages": no_region[:40]}, "the main content is marked up", "Wrap the main content in <main> or <article>.",
            importance_tier=_tier(no_region, key_urls),
        ))
    summary = f"{len(findings)} finding(s)." if findings else "Main content is marked up and dominates page text."
    return CheckResult("RND-7", title, _status(findings), summary, findings,
                       {"excluded_as_rnd1_root_cause": sorted(rendering_gap)})


def run_render_checks(result: CrawlResult, cfg: CrawlConfig) -> list[CheckResult]:
    rnd1 = rnd1_rendering_gap(result, cfg)
    return settle_all([
        rnd1,
        rnd2_critical_facts(result, cfg),
        rnd3_interaction(result, cfg),
        rnd4_non_text(result, cfg),
        rnd5_walls(result, cfg),
        rnd6_payload(result, cfg),
        rnd7_main_share(result, cfg, rnd1),
    ], result)
