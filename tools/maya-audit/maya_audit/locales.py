"""Country and language copies of the same page (DECISIONS 316).

A site with country-language folders (`/global-en/`, `/uk-ru/`, `/jp-ja/`, `/en-us/`, `/tr/`) holds the same page
many times. airastana.com lists 179 pages in each of 20 folders; a 50-page audit read the same about-us page 20 times,
then the same raffle page 20 times, and so on, because each folder looked like a part of the site of its own.

`detect` finds the site's locale folders from the addresses it knows (sitemap, links, hreflang); `page_key` names a
page without its folder, so the crawl can read one version of each page before a second one (`scratchpad`,
`firecrawl.reading`), and the report can say how many versions were found and how many of each page were read
(`summary`). Rule-based; no request is sent. A folder counts only on the site's own evidence:

- a plain language folder (`/en`, `/tr`, `/en-us`, `/zh-hans`: `page_groups.is_locale`), as everywhere in the engine;
- a country-language pair (`/global-en`, `/chn-zh`, `/kaz-kk`) only when another such folder holds at least two of the
  same pages, or when an hreflang link names it: `/how-to/` is not a locale because no `/faq-en/` mirrors it.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Iterable
from urllib.parse import unquote, urlsplit

# How many versions of one page a capped crawl reads before it reads a page it has not seen (owner: "at most 1-2
# copies of the same page across locales"; agent default 2: the main version and one other, so the per-locale checks
# have something to compare). A third version is read only when nothing else is waiting.
COPIES = 2
# The homepage's versions are what the per-locale checks (hreflang return links, wrong language) compare, so the
# homepage may be read in up to this many versions (agent default); every other page in COPIES.
HOME_COPIES = 4
HOME_KEY = "/"
# Region or language words that stand for "every country" in a pair (/global-en, /intl-fr, /ww-en).
_WIDE = r"global|intl|int|international|ww|world|worldwide|row|eu|latam|apac|mena|emea"
_PAIR = re.compile(rf"^(?:[a-z]{{2,3}}|{_WIDE})[-_](?:[a-z]{{2,3}}|{_WIDE})$", re.IGNORECASE)
# Pages two candidate folders must share before a pair-shaped folder counts as a locale.
SHARED_MIN = 2
# Language codes a lone folder (/en, /de-at) is taken for without other evidence; any other two-letter folder (/tv,
# /go) needs an hreflang link or shared pages.
LANGUAGES = frozenset("""en tr de fr es it pt ru uk kk uz az ky tk tg ar fa he ur hi bn zh ja ko vi th id ms tl nl pl cs
sk hu ro bg el sr hr bs sl mk sq lt lv et fi sv no nb nn da is ga cy ka hy mn ne si ta te ml kn mr gu pa sw am ca eu gl
lb mt""".split())


def _first(url: str) -> tuple[str, str]:
    """(first path segment, lowercased; the rest of the path with its query)."""
    parts = urlsplit(url)
    segs = [unquote(s) for s in parts.path.split("/") if s]
    if not segs:
        return "", "/" + (("?" + parts.query) if parts.query else "")
    rest = "/" + "/".join(segs[1:]) + ("/" if parts.path.endswith("/") and len(segs) > 1 else "")
    return segs[0].lower(), rest + (("?" + parts.query) if parts.query else "")


def _strict(segment: str) -> bool:
    from .page_groups import is_locale
    return bool(segment) and is_locale(segment)


def detect(urls: Iterable[str], hreflang_urls: Iterable[str] = (), start_url: str | None = None) -> dict[str, Any]:
    """{"folders": [...], "main": folder | "" (the root) | None, "versions": n, "root_is_version": bool, "basis"}.

    `main` is the folder of the start address's page (after its redirect) when it is a locale folder, "" when the root
    holds a version of the site's pages, else None. `versions` counts the folders and the root when it is one."""
    rests: dict[str, set[str]] = defaultdict(set)
    root: set[str] = set()
    for url in dict.fromkeys(u for u in urls if isinstance(u, str)):
        seg, rest = _first(url)
        if _strict(seg) or _PAIR.match(seg):
            rests[seg].add(rest)
        else:
            root.add(urlsplit(url).path.rstrip("/") or "/")
    named = {_first(u)[0] for u in hreflang_urls if isinstance(u, str)}
    folders, basis = set(), {}
    root_rests = {r if r == "/" else "/" + r.strip("/") for r in root}
    for seg, have in rests.items():
        trimmed = {r if r == "/" else "/" + r.split("?")[0].strip("/") for r in have}
        if seg in named:
            folders.add(seg)
            basis[seg] = "named by hreflang"
        elif any(other != seg and len(have & theirs) >= SHARED_MIN for other, theirs in rests.items()):
            folders.add(seg)
            basis[seg] = "the same pages as another country-language folder"
        elif _strict(seg) and (re.split(r"[-_]", seg)[0] in LANGUAGES or len((trimmed - {"/"}) & root_rests) >= SHARED_MIN):
            folders.add(seg)
            basis[seg] = "language folder"
    # The root is a version too when it holds pages a folder also holds (/hakkimizda and /en/hakkimizda are not the same
    # address, but /about and /en/about are the same page).
    shared_root = {r.rstrip("/") or "/" for f in folders for r in rests[f]} & root
    # ... and only when the homepage itself lives at the root: moodist's root addresses are old links to its /tr/ pages.
    home_seg = _first(start_url)[0] if start_url else ""
    root_is_version = bool(folders) and home_seg not in folders and len(shared_root - {"/"}) >= SHARED_MIN
    main = None
    if folders and start_url:
        main = home_seg if home_seg in folders else ("" if root_is_version or not home_seg else None)
    return {"folders": sorted(folders), "main": main, "versions": len(folders) + (1 if root_is_version else 0),
            "root_is_version": root_is_version, "basis": {f: basis[f] for f in sorted(folders)}}


def locale_of(url: str, folders: Iterable[str]) -> str:
    """The address's locale folder, or "" when it has none."""
    seg, _ = _first(url)
    return seg if seg in set(folders) else ""


def page_key(url: str, folders: Iterable[str]) -> str:
    """The page without its locale folder: /global-en/information/about-us and /uk-ru/information/about-us are both
    /information/about-us. An address with no locale folder is its own path (and query)."""
    seg, rest = _first(url)
    if seg and seg in set(folders):
        return rest
    parts = urlsplit(url)
    return (parts.path or "/") + (("?" + parts.query) if parts.query else "")


def strip_folder(url: str, folders: Iterable[str]) -> str:
    """The same address with its locale folder taken out (for a section key that does not split by country)."""
    seg, rest = _first(url)
    if not seg or seg not in set(folders):
        return url
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}{rest}"


def section_url(url: str, folders: Iterable[str]) -> str:
    """The address with its locale folder replaced by one placeholder, for the crawl's section key: /tr/blog-post/ and
    /en/blog-post/ are one section (/_l/*), as /global-en/information/x and /uk-ru/information/x are (/_l/information/*).
    Taking the folder out instead would make every /tr/<post>/ a top-level section of its own."""
    seg, rest = _first(url)
    if not seg or seg not in set(folders):
        return url
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}/_l{rest}"


def summary(info: dict | None, read_urls: Iterable[str]) -> dict[str, Any] | None:
    """What the report says about the versions: how many were found, how many pages were read in how many versions.
    None when the site has fewer than two versions (nothing to say)."""
    if not info or int(info.get("versions") or 0) < 2:
        return None
    folders = info.get("folders") or []
    by_key: dict[str, set[str]] = defaultdict(set)
    for url in read_urls:
        by_key[page_key(url, folders)].add(locale_of(url, folders))
    home = len(by_key.get(HOME_KEY) or ())
    rest = [v for k, v in by_key.items() if k != HOME_KEY]
    most = max((len(v) for v in rest), default=0)
    return {"versions": int(info["versions"]), "main": info.get("main"), "pages_read": sum(len(v) for v in by_key.values()),
            "distinct_pages": len(by_key), "most_versions_of_one_page": most, "homepage_versions": home,
            "pages_with_more_than_one": sum(1 for v in rest if len(v) > 1)}


HOME_LINE = {"tr": " (ana sayfa {h} sürümde)", "en": " (the homepage in {h} versions)"}
LINE = {
    "tr": {"one": "{n} ülke/dil sürümü bulundu; her sayfanın bir sürümü okundu.",
           "few": "{n} ülke/dil sürümü bulundu; bir sayfanın en çok {k} sürümü okundu.",
           "many": "{n} ülke/dil sürümü bulundu; aynı sayfanın {k} sürümüne kadar okundu (eski motorla yapılan okuma)."},
    "en": {"one": "{n} country/language versions found; one version per page was read.",
           "few": "{n} country/language versions found; at most {k} versions of a page were read.",
           "many": "{n} country/language versions found; up to {k} versions of the same page were read (read by an older engine)."},
}


def line(s: dict | None, lang: str) -> str | None:
    """"20 country/language versions found; one version per page was read." None without versions."""
    if not s:
        return None
    k = int(s.get("most_versions_of_one_page") or 0)
    words = LINE["en" if lang == "en" else "tr"]
    key = "one" if k <= 1 else "few" if k <= COPIES else "many"
    text = words[key].format(n=s["versions"], k=k)
    h = int(s.get("homepage_versions") or 0)
    if h > 1:
        text = text[:-1] + HOME_LINE["en" if lang == "en" else "tr"].format(h=h) + "."
    return text
