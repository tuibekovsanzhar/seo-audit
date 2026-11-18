"""Akıllı ~150: a read of about 150 well-chosen pages that covers every important page type of the business profile
(v0.3 Stage 5, DECISIONS 327; the team's sampling rule, `docs/business-types/Sektor_Bazli_SEO_Audit_Onceligi.xlsm`).

Before reading, every known address (the sitemap, then the homepage's links with their menu texts) is typed with the
profile's own signals (`business_types.classify` on the address and the menu text; files are left out; a long,
article-like top-level slug whose only type word is in the slug is a blog post). The budget is split by the team's
rule: the homepage and its language versions and the key pages first; a reserve of 10 other pages, 3 policy pages and
2 search/cart pages; a page type with 30 known addresses or fewer is read in full, in rank order; a larger one gets at
least 30, the rest by its rank weight; inside a large type a third most important (in the menu, shallow), a third long
tail (deep, not in the menu), a sixth newest by sitemap date, a sixth exceptions (rare URL template, parameters),
rotating over the URL templates. The reading order rotates over the types, so a time cut still leaves every type read.

Two waves: after 60% of the budget the pages read are typed with their content, and every unread address of a URL
template takes the template's type when 3 or more of its pages read agree (80% or more); the rest of the budget is
split again (a type found empty gives its share back). It sends no request: the crawler asks for the pages.
"""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from typing import Iterable
from urllib.parse import urlsplit

BUDGET = 150
SMALL = 30                          # a page type with this many known addresses or fewer is read in full
RESERVE = {"other": 10, "policy": 3, "utility": 2}
WAVE_ONE = 0.6                      # share of the budget read before the pages are typed again
SLOTS = (("importance", 1 / 3), ("long_tail", 1 / 3), ("newest", 1 / 6), ("exception", 1 / 6))
FILES = (".kml", ".md", ".xml", ".pdf", ".txt", ".json", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".gz", ".zip")
ARTICLE_WORDS = 5
RETYPE_MIN, RETYPE_SHARE = 3, 0.8
# DECISIONS 358 (agent defaults): before reading, an address of three or more words ending in an item id
# ("/big-boss-50ml-383", not "/kokular-55" nor a year) that the main menu does not link is the profile's product page,
# and so is an address listed in a sitemap file of products ("/sitemap/products/0.xml"); one in a file of categories is
# its category page. After the first wave, such an address linked from the body of a page read as a category is too.
ITEM_ID = re.compile(r"^(?:[^\W_]+[-_]){3,}\d{2,7}$")
YEAR_END = re.compile(r"[-_](?:19|20)\d\d$")
ITEM_FILE = re.compile(r"(?<![a-z])(?:products?|urun|urunler|items?)(?![a-z])")
LIST_FILE = re.compile(r"(?<![a-z])(?:categor(?:y|ies)|kategori|kategoriler|collections?)(?![a-z])")


# The profile types that are one item each (a product, a car model, a travel listing's detail); a SaaS feature page is
# typed product in the page grouping but is not one item, so the address rules leave it alone.
ITEM_TYPE_IDS = ("product", "model", "detail")


def _profile_type(prof: dict, generic: str) -> str | None:
    for t in prof["page_types"]:
        if generic in (t.get("generic") or []) and (generic != "product" or t["id"] in ITEM_TYPE_IDS):
            return t["id"]
    return None


def item_address(segment: str) -> bool:
    """DECISIONS 358: a slug of three or more words ending in an item id."""
    from .page_words import fold
    seg = fold(segment or "")
    return bool(ITEM_ID.match(seg)) and not YEAR_END.search(seg)
VERSION = 1
SLOT_WORDS = {"tr": {"fixed": "ana sayfa / kilit sayfa", "all": "hepsi", "importance": "önem (menüde, sığ)",
                     "long_tail": "uzun kuyruk (derin, menüde yok)", "newest": "en yeni (sitemap tarihi)",
                     "exception": "istisna (nadir şablon, parametre)", "fill": "kalan bütçe"},
              "en": {"fixed": "homepage / key page", "all": "all", "importance": "importance (menu, shallow)",
                     "long_tail": "long tail (deep, not in the menu)", "newest": "newest (sitemap date)",
                     "exception": "exception (rare template, parameters)", "fill": "remaining budget"}}


def _segments(url: str, folders: Iterable[str]) -> list[str]:
    from .locales import strip_folder
    return [s for s in urlsplit(strip_folder(url, folders)).path.split("/") if s]


def is_file(url: str) -> bool:
    return urlsplit(url).path.lower().endswith(FILES)


def pre_type(prof: dict, url: str, menu: Iterable[str] = (), folders: Iterable[str] = (), analysis: dict | None = None,
             nav: bool = False, sitemap_file: str | None = None) -> tuple[str, str]:
    """(page type, why) of one address before (or, with `analysis`, after) it is read. `sitemap_file`: the sitemap file
    that listed it (DECISIONS 358)."""
    from . import business_types as bt
    from . import page_groups
    if is_file(url):
        return "file", "a file, not a page"
    segs = _segments(url, folders)
    if not segs:
        return "home", "the homepage address"
    if any(s.lower() in page_groups.UTILITY_SEGMENTS for s in segs):
        return "utility", "a search, cart or account address"
    last = page_groups._words(segs[-1])
    generic = "policy" if segs[0].lower() in page_groups.POLICY_FOLDERS or (last & page_groups.POLICY_WORDS) else None
    facts = bt.page_facts(url, analysis, menu=list(menu), generic=generic, folders=folders, nav=nav)
    tid, basis, hits = bt.classify(prof, facts)
    if analysis is None and generic is None and not any(h["kind"] == "url" for h in hits):  # the address names no type
        product, category = _profile_type(prof, "product"), _profile_type(prof, "category")
        file_path = (urlsplit(sitemap_file).path.lower() if sitemap_file else "")
        if product and file_path and ITEM_FILE.search(file_path):
            return product, f"listed in a sitemap file of products ({file_path})"
        if category and file_path and LIST_FILE.search(file_path):
            return category, f"listed in a sitemap file of categories ({file_path})"
        if product and not nav and len(segs) == 1 and item_address(segs[-1]):
            return product, "an address of three or more words ending in an item id"
    if analysis is None:
        url_hits = [h for h in hits if h["kind"] == "url"]
        top = len(facts["segments"]) - 1
        slug_only = all((h.get("depth") or 0) >= top for h in url_hits)
        words = len([w for w in re.split(r"[-_]+", segs[-1]) if w])
        if (words >= ARTICLE_WORDS and len(segs) == 1 and (not url_hits or slug_only)
                and not any(h["kind"] == "menu" for h in hits)):
            guide = next((t["id"] for t in prof["page_types"] if t.get("citable")), "other")
            return guide, "a long, article-like address"
    return tid, basis


def _depth(url: str, folders) -> int:
    return len(_segments(url, folders))


def allocate(counts: dict[str, int], prof: dict, budget: int) -> dict[str, int]:
    """Pages per type for `budget` pages beyond the fixed ones: reserve, small types in full, large ones 30 + weight."""
    from . import business_types as bt
    order = [t["id"] for t in sorted(prof["page_types"], key=lambda t: (t.get("rank") or 50, -(t.get("weight") or 0)))
             if t["id"] != "home"]
    order += [t for t in counts if t not in order and t not in RESERVE and t not in ("home", "file")]
    reserve = {k: min(n, counts.get(k, 0)) for k, n in RESERVE.items()}
    left = max(0, budget - sum(reserve.values()))
    alloc: dict[str, int] = {}
    small = [t for t in order if 0 < counts.get(t, 0) <= SMALL]
    large = [t for t in order if counts.get(t, 0) > SMALL]
    for t in small:
        take = min(counts[t], left)
        alloc[t], left = take, left - take
    if large:
        floors = {t: min(SMALL, counts[t]) for t in large}
        if sum(floors.values()) >= left:
            for t in large:  # not enough for every floor: in rank order
                alloc[t] = min(floors[t], left)
                left -= alloc[t]
        else:
            extra = left - sum(floors.values())
            weights = {t: max(1, bt.weight(prof, t)) for t in large}
            total = sum(weights.values())
            for t in large:
                alloc[t] = min(counts[t], floors[t] + int(extra * weights[t] / total))
            left -= sum(alloc[t] for t in large)
    for k in RESERVE:  # what is left goes to "other" (and, past it, to the large types)
        alloc[k] = min(counts.get(k, 0), reserve[k] + (left if k == "other" else 0))
    left = budget - sum(alloc.values())
    for t in large:
        if left <= 0:
            break
        more = min(left, counts[t] - alloc[t])
        alloc[t] += more
        left -= more
    return {t: n for t, n in alloc.items() if n > 0}


def choose(pool: list[str], n: int, *, folders, menu_linked: set[str], lastmods: dict[str, str],
           patterns: dict[str, str]) -> list[tuple[str, str]]:
    """`n` addresses of one type, by the team's split, rotating over URL templates: [(url, slot)]."""
    if n >= len(pool):
        return [(u, "all") for u in pool]
    used: set[str] = set()
    picks: list[tuple[str, str]] = []

    def take(cands: list[str], k: int, slot: str) -> None:
        by_tpl: dict[str, list[str]] = defaultdict(list)
        for u in cands:
            if u not in used:
                by_tpl[patterns.get(u, "?")].append(u)
        got = 0
        while got < k and any(by_tpl.values()):
            for tpl in list(by_tpl):
                if by_tpl[tpl] and got < k:
                    u = by_tpl[tpl].pop(0)
                    used.add(u)
                    picks.append((u, slot))
                    got += 1
    sizes = [max(1, math.floor(n * share)) for _, share in SLOTS]
    sizes[0] += n - sum(sizes)
    rare = Counter(patterns.get(u, "?") for u in pool)
    take(sorted(pool, key=lambda u: (u not in menu_linked, _depth(u, folders), u)), sizes[0], "importance")
    take(sorted(pool, key=lambda u: (u in menu_linked, -_depth(u, folders), u)), sizes[1], "long_tail")
    take(sorted((u for u in pool if lastmods.get(u)), key=lambda u: lastmods[u], reverse=True), sizes[2], "newest")
    take(sorted(pool, key=lambda u: (rare[patterns.get(u, "?")], "?" not in u, -len(u), u)), sizes[3], "exception")
    if len(picks) < n:
        take(sorted(pool), n - len(picks), "fill")
    return picks[:n]


class Sampler:
    """The plan of one Akıllı audit. `known` is every address known before the first page is read beyond the
    homepage; `anchors` the menu texts of the homepage's links; `fixed` the start, homepages and key pages."""

    def __init__(self, profile_id: str | None, *, budget: int = BUDGET, folders: Iterable[str] = (), main: str | None = None,
                 lastmods: dict[str, str] | None = None) -> None:
        from . import business_types as bt
        self.pid = profile_id if profile_id and bt.valid(profile_id) else bt.DEFAULT
        self.prof = bt.profile(self.pid)
        self.budget = budget
        self.folders = tuple(folders or ())
        self.main = main
        self.lastmods = {k: str(v) for k, v in (lastmods or {}).items() if v}
        self.types: dict[str, tuple[str, str]] = {}
        self.anchors: dict[str, list[str]] = {}
        self.menu_linked: set[str] = set()
        self.fixed: list[str] = []
        self.waves: list[dict] = []
        self.retyped = 0
        self.planned: dict[str, list[tuple[str, str]]] = {}
        self.order: list[str] = []
        self.history: list[list[str]] = []  # each wave's order, for the page reader (DECISIONS 327)
        self.files: dict[str, str] = {}  # the sitemap file that listed each address (DECISIONS 358)

    # -------------------------------------------------------------- the pool
    def add(self, urls: Iterable[str], anchors: dict[str, list[str]] | None = None, menu: Iterable[str] = (),
            files: dict[str, str] | None = None) -> None:
        """Known addresses (one version per page: the main folder's, DECISIONS 316) with their menu texts; `files`: the
        sitemap file that listed each (DECISIONS 358)."""
        if files:
            self.files.update(files)
        from .locales import HOME_KEY, locale_of, page_key
        for u, texts in (anchors or {}).items():
            self.anchors.setdefault(u, []).extend(texts)
        self.menu_linked.update(menu)
        keep: dict[str, str] = {page_key(u, self.folders): u for u in self.types}
        for u in urls:
            if not u or u in self.types:
                continue
            key = page_key(u, self.folders)
            if key == HOME_KEY:  # every language version of the homepage is kept (DECISIONS 316: up to HOME_COPIES)
                key = u
            held = keep.get(key)
            if held is not None:
                if self.main is not None and locale_of(u, self.folders) == self.main and locale_of(held, self.folders) != self.main:
                    del self.types[held]
                else:
                    continue
            keep[key] = u
            self.types[u] = pre_type(self.prof, u, self.anchors.get(u, ()), self.folders, nav=u in self.menu_linked,
                                     sitemap_file=self.files.get(u))

    def counts(self) -> dict[str, int]:
        return dict(Counter(t for t, _ in self.types.values() if t not in ("file", "home")))

    # -------------------------------------------------------------- the plan
    def plan(self, fixed: Iterable[str] = (), read: dict[str, str] | None = None) -> list[str]:
        """The reading order of the addresses not read yet. `read` ({url: type after reading}) counts against each type."""
        from . import page_groups
        read = read or {}
        self.fixed = list(dict.fromkeys(fixed))
        left = self.budget - len(set(self.fixed) | set(read))
        counts = self.counts()
        done = Counter(t for t in read.values())
        alloc = allocate({t: counts.get(t, 0) + done.get(t, 0) for t in set(counts) | set(done)}, self.prof,
                         max(0, self.budget - len(self.fixed)))
        patterns = page_groups.url_patterns(list(self.types) + list(read))
        planned: dict[str, list[tuple[str, str]]] = {}
        from .locales import locale_of
        for t, n in alloc.items():
            pool = [u for u, (tt, _) in self.types.items() if tt == t and u not in read and u not in self.fixed]
            if self.folders and self.main is not None:
                # one version of each page: other language versions only when the type has none in the main version
                mains = [u for u in pool if locale_of(u, self.folders) == self.main]
                pool = mains or pool
            need = max(0, n - done.get(t, 0))
            planned[t] = choose(pool, min(need, len(pool)), folders=self.folders, menu_linked=self.menu_linked,
                                lastmods=self.lastmods, patterns=patterns)
        total = sum(len(v) for v in planned.values())
        if total < left:
            # budget left (a type's main-language pool ran out): fill in rank order, the main version first
            taken = {u for v in planned.values() for u, _ in v}
            ranks0 = {x["id"]: x.get("rank") or 50 for x in self.prof["page_types"]}
            for t in sorted(alloc, key=lambda t: (ranks0.get(t, 60), t)):
                if total >= left:
                    break
                spare = [u for u, (tt, _) in self.types.items()
                         if tt == t and u not in read and u not in self.fixed and u not in taken]
                spare.sort(key=lambda u: (self.folders and self.main is not None and locale_of(u, self.folders) != self.main, u))
                more = [(u, "fill") for u in spare[:left - total]]
                planned.setdefault(t, []).extend(more)
                total += len(more)
        if total > left:  # never past the budget
            for t in sorted(planned, key=lambda t: -len(planned[t])):
                cut = min(total - left, max(0, len(planned[t]) - 1))
                planned[t] = planned[t][:len(planned[t]) - cut]
                total -= cut
                if total <= left:
                    break
        self.planned = planned
        self.done = dict(done)
        # rotate over the types in rank order, so a time cut still leaves every type read
        ranks = {t["id"]: t.get("rank") or 50 for t in self.prof["page_types"]}
        lists = [list(planned[t]) for t in sorted(planned, key=lambda t: (ranks.get(t, 60), t))]
        order: list[str] = [u for u in self.fixed if u not in read]
        while any(lists):
            for lst in lists:
                if lst:
                    order.append(lst.pop(0)[0])
        self.order = list(dict.fromkeys(order))
        self.history.append(list(self.order))
        self.waves.append({"wave": len(self.waves) + 1, "after_pages": len(read), "planned": len(self.order)})
        return self.order

    def wave_one_size(self) -> int:
        return max(1, int(self.budget * WAVE_ONE))

    def retype(self, read_pages: dict[str, dict | None], links: dict[str, list[str]] | None = None) -> dict[str, str]:
        """After wave 1: the pages read typed with their content ({url: analysis}), and every unread address of a URL
        template taking the template's type when RETYPE_MIN or more of its pages read agree (RETYPE_SHARE). Returns
        {url: type after reading}."""
        from . import page_groups
        real = {u: pre_type(self.prof, u, self.anchors.get(u, ()), self.folders, analysis=a or {}, nav=u in self.menu_linked)[0]
                for u, a in read_pages.items() if not is_file(u)}
        patterns = page_groups.url_patterns(list(self.types) + list(real))
        votes: dict[str, Counter] = defaultdict(Counter)
        for u, t in real.items():
            votes[patterns.get(u, "?")][t] += 1
        n = 0
        for u, (t, why) in list(self.types.items()):
            if u in real or t in ("home", "file"):
                continue
            v = votes.get(patterns.get(u, "?"))
            if v:
                best, k = v.most_common(1)[0]
                if k >= RETYPE_MIN and k / sum(v.values()) >= RETYPE_SHARE and best != t:
                    self.types[u] = (best, f"its URL template {patterns.get(u)}: {k} pages read are {best}")
                    n += 1
        # DECISIONS 358: an unread item-id address linked from the body of a page read as a category is a product page
        product, category = _profile_type(self.prof, "product"), _profile_type(self.prof, "category")
        if product and category:
            for src, targets in (links or {}).items():
                if real.get(src) != category:
                    continue
                for u in targets:
                    segs = _segments(u, self.folders)
                    if (u in self.types and u not in real and self.types[u][0] != product and segs
                            and item_address(segs[-1]) and u not in self.menu_linked):
                        self.types[u] = (product, f"an item-id address linked from the category page {src}")
                        n += 1
        for u, t in real.items():
            if u in self.types:
                self.types[u] = (t, "typed after reading")
        self.retyped += n
        return real

    # -------------------------------------------------------------- the record
    def record(self) -> dict:
        """`crawl.sampling` (schema 1.30): the plan, per type: known addresses and planned pages; the waves."""
        from . import business_types as bt
        counts = self.counts()
        types = {}
        homes = [u for u, (tt, _) in self.types.items() if tt == "home"]
        for t in [x["id"] for x in self.prof["page_types"]] + ["other", "policy", "utility"]:
            planned = [u for u in self.fixed if u in homes] if t == "home" else [u for u, _ in self.planned.get(t, [])]
            already = 0 if t == "home" else (getattr(self, "done", {}) or {}).get(t, 0)  # read in wave 1
            label = bt.type_label(self.pid, t, "tr") if t not in ("other", "policy", "utility") else None
            types[t] = {"rank": next((x.get("rank") for x in self.prof["page_types"] if x["id"] == t), None),
                        "known": len(homes) if t == "home" else counts.get(t, 0),
                        "planned": len(planned) + already, "examples": planned[:5], "label": label}
        return {"mode": "smart", "version": VERSION, "budget": self.budget, "profile": self.pid, "folders": list(self.folders),
                "main": self.main, "types": types, "waves": self.waves, "retyped": self.retyped, "known": len(self.types),
                "files_left_out": sum(1 for t, _ in self.types.values() if t == "file"),
                "planned_urls": list(dict.fromkeys(self.fixed + [u for v in self.history for u in v]))[:self.budget * 2],
                "method": "team sampling rule (DECISIONS 327): small types in full, large at least 30, reserve 10/3/2, "
                          "two waves with re-typing"}


# ------------------------------------------------------------------ coverage, for the reports

def coverage(report: dict, records: dict[str, dict] | None = None, lang: str = "tr") -> list[dict]:
    """Per page type of the plan: known, read (typed after reading, from the page grouping), and whether all were read,
    a sample, or none was found. [] for an audit that was not an Akıllı one."""
    from . import business_types as bt
    s = (report.get("crawl") or {}).get("sampling")
    if not isinstance(s, dict) or s.get("mode") != "smart":
        return []
    if records is None:
        from .client_selection import grouping
        records, _ = grouping(report)
    read = Counter(r.get("business_page_type") for r in records.values() if r.get("read") is not False and r.get("business_page_type"))
    out = []
    for t, row in (s.get("types") or {}).items():
        if t in ("other", "policy", "utility"):
            continue
        known = max(int(row.get("known") or 0), read.get(t, 0))
        n = read.get(t, 0)
        state = "none" if known == 0 else "all" if n >= known else "sample"
        out.append({"type": t, "profile": s.get("profile"), "rank": row.get("rank"), "known": known, "read": n, "state": state})
    return sorted(out, key=lambda r: (r["rank"] or 50, r["type"]))


LINE = {"tr": {"all": "{label}: {read}/{known} okundu", "sample": "{label}: {read}/{known} okundu (örneklem)",
               "none": "{label}: bulunamadı", "head": "Akıllı örneklem, sayfa türleri: "},
        "en": {"all": "{label}: {read}/{known} read", "sample": "{label}: {read}/{known} read (sample)",
               "none": "{label}: not found", "head": "Smart sample, page types: "}}


def coverage_text(rows: list[dict], lang: str = "tr") -> str:
    """"Akıllı örneklem, sayfa türleri: Tedavi ve bölüm: 30/56 okundu (örneklem) · Klinik ve konum: bulunamadı"."""
    from . import business_types as bt
    W = LINE.get(lang, LINE["tr"])
    return W["head"] + " · ".join(W[r["state"]].format(label=bt.type_label(r.get("profile"), r["type"], lang) or r["type"], **r)
                                  for r in rows)


def type_line(report: dict, type_id: str, records: dict[str, dict] | None = None, lang: str = "tr") -> str | None:
    """The coverage of one page type ("Klinik ve konum: bulunamadı") for an Akıllı audit, else None."""
    row = next((r for r in coverage(report, records, lang) if r["type"] == type_id), None)
    return coverage_text([row], lang).split(": ", 1)[1] if row else None


# ---------------------------------------------------------------- the coverage line of a sampled audit (DECISIONS 335)

SAMPLE = {"tr": {"line": "Örneklem: {read} sayfa okundu, {unread} bilinen adres okunmadı.",
                 "fewer": " {cap} sayfalık sınırdan {read} sayfa okundu: {why}.",
                 "error_status": "{n} adres hata döndü ({codes})", "files": "{n} adres dosyaydı, sayfa değil",
                 "blocked": "{n} adres engellendi ya da sınırlandı", "failed": "{n} isteğe yanıt alınamadı",
                 "empty": "{n} sayfa boş döndü", "plan_done": "örneklem planı bitti: sayfa türleri doldu, {left} sayfalık bütçe kaldı",
                 "counts": "sayfa sınırı her sayfa isteğini sayar", "and": "; ",
                 # DECISIONS 358: why a crawl ended below its limit, from what it met
                 "off_site_redirects": "{n} adres {host} adresine yönlendirdi ve bu adres sitenin kendi adresi sayılmadığı için "
                                       "izlenmedi (bu denetim eski kuralla yapıldı; yeni taramada izlenir)",
                 "sitemap_elsewhere": "robots.txt'nin gösterdiği site haritası başka bir adreste ({url}) olduğu için okunmadı",
                 "moved_host": "site sayfalarını {to} adresine yönlendiriyor; tarama {after} sayfadan sonra oraya geçti ve "
                               "oradaki site haritasını okudu",
                 "found_all": "bulunan her adres istendi ({found} adres); sitede bağlantı ya da site haritasıyla bulunan "
                              "sayfa sayısı sınırdan az"},
          "en": {"line": "Sample: {read} {read_pages} read, {unread} known {unread_addresses} not read.",
                 "fewer": " {read} of the {cap}-page limit read: {why}.",
                 "error_status": "{n} {addresses} answered an error ({codes})", "files": "{n} {addresses} {were} a file, not a page",
                 "blocked": "{n} {addresses} were blocked or rate-limited", "failed": "{n} {requests} got no answer",
                 "empty": "{n} {pages} came back empty", "plan_done": "the sample plan ran out: every page type filled, "
                 "{left} pages of the budget left", "counts": "the page limit counts every page request", "and": "; ",
                 "off_site_redirects": "{n} {addresses} redirected to {host}, which was not taken as the site's own address "
                                       "and was not followed (an audit made under the earlier rule; a new crawl follows it)",
                 "sitemap_elsewhere": "the sitemap robots.txt names is on another address ({url}) and was not read",
                 "moved_host": "the site redirects its pages to {to}; the crawl moved there after {after} pages and read "
                               "the sitemap there",
                 "found_all": "every address found was requested ({found}); the site's links and sitemap name fewer pages "
                              "than the limit"}}


def _plural(n: int, one: str, many: str) -> str:
    return one if n == 1 else many


def sampled(report: dict) -> bool:
    """An audit that read the Akıllı selection (any web mode but a single page or "Tam tarama sırası", DECISIONS 331)."""
    s = (report.get("crawl") or {}).get("sampling")
    return isinstance(s, dict) and s.get("mode") == "smart"


def unread_count(report: dict) -> int:
    """Known addresses not read: the addresses Maya's crawl knew and did not fetch, less those a page reader read. (A
    reader that read only where needed, DECISIONS 327/329, counts no unread address of its own.)"""
    crawl = report.get("crawl") or {}
    reader = report.get("firecrawl") or {}
    read_by_reader = {row.get("url") for row in reader.get("pages") or [] if isinstance(row, dict) and row.get("outcome") == "read"}
    return sum(1 for u in crawl.get("not_fetched_urls") or [] if u not in read_by_reader)


def fewer_reasons(report: dict) -> list[tuple[str, dict]]:
    """Why fewer pages than the limit were read, from the saved page requests (redirect hops are not page requests)."""
    crawl = report.get("crawl") or {}
    cap = int((crawl.get("config") or {}).get("max_pages") or 0)
    pages = [p for p in crawl.get("pages") or [] if isinstance(p, dict)
             and not (isinstance(p.get("status"), int) and 300 <= p["status"] < 400)]
    out: list[tuple[str, dict]] = []
    errors = Counter(p["status"] for p in pages if p.get("fetch_class") == "ok" and isinstance(p.get("status"), int) and p["status"] >= 400)
    if errors:
        out.append(("error_status", {"n": sum(errors.values()), "codes": ", ".join(f"{c} ×{n}" if n > 1 else str(c) for c, n in sorted(errors.items()))}))
    files = sum(1 for p in pages if p.get("fetch_class") == "ok" and isinstance(p.get("status"), int) and 200 <= p["status"] < 300
                and "html" not in str(p.get("content_type") or "").lower())
    if files:
        out.append(("files", {"n": files}))
    blocked = sum(1 for p in pages if p.get("fetch_class") in ("blocked", "rate_limited"))
    if blocked:
        out.append(("blocked", {"n": blocked}))
    failed = sum(1 for p in pages if p.get("fetch_class") == "error")
    if failed:
        out.append(("failed", {"n": failed}))
    empty = sum(1 for p in pages if ((p.get("analysis") or {}).get("empty_response")))
    if empty:
        out.append(("empty", {"n": empty}))
    out += _discovery_reasons(crawl)
    if crawl.get("stop_reason") == "exhausted" and cap and len(pages) < cap and not any(
            k in ("off_site_redirects", "sitemap_elsewhere") for k, _ in out):
        if sampled({"crawl": crawl}) and unread_count({"crawl": crawl}):
            out.append(("plan_done", {"left": cap - len(pages)}))
        else:
            out.append(("found_all", {"found": len(crawl.get("discovered_urls") or []) or len(pages)}))
    elif out and crawl.get("stop_reason") == "page_cap":
        out.append(("counts", {}))
    return out


_OTHER_ADDRESS_SITEMAP = re.compile(r"robots\.txt names \d+ sitemap file\(s\) on another address, which were not read: (\S+?)[,.]?(?:\s|$)")


def _discovery_reasons(crawl: dict) -> list[tuple[str, dict]]:
    """DECISIONS 358: what kept addresses from the crawl: redirects of the site's own pages to an address it did not take
    as the site's (an audit made before the twin move), a sitemap named on another address, and a move to the twin."""
    from urllib.parse import urlsplit
    out: list[tuple[str, dict]] = []
    origin = str(crawl.get("origin") or "")
    moves = [m for m in crawl.get("host_moves") or [] if isinstance(m, dict)]
    for m in moves:
        out.append(("moved_host", {"to": urlsplit(str(m.get("to") or "")).hostname or m.get("to"), "after": m.get("after_pages")}))
    own = {origin} | {str(m.get("from")) for m in moves}
    hosts: Counter = Counter()
    for r in crawl.get("redirects") or []:
        if not isinstance(r, dict) or not r.get("final"):
            continue
        parts = urlsplit(str(r["final"]))
        if f"{parts.scheme}://{parts.netloc}" not in own and (parts.hostname or "").removeprefix("www.") == (
                urlsplit(origin).hostname or "").removeprefix("www."):
            hosts[parts.hostname] += 1
    if hosts:
        host, n = hosts.most_common(1)[0]
        out.append(("off_site_redirects", {"n": n, "host": host}))
    for note in crawl.get("sitemap_notes") or []:
        m = _OTHER_ADDRESS_SITEMAP.search(str(note))
        if m:
            out.append(("sitemap_elsewhere", {"url": m.group(1).rstrip(".,")}))
            break
    return out


def below_limit_line(report: dict, lang: str = "tr") -> str | None:
    """DECISIONS 358: for the Kapsam sheet, why a crawl that stopped on its own read fewer pages than its limit
    ("150 sayfalık sınırdan 32 sayfa okundu: …"). None when it read its limit or stopped on the limit or the time."""
    W = SAMPLE.get(lang, SAMPLE["tr"])
    crawl = report.get("crawl") or {}
    cap = int((crawl.get("config") or {}).get("max_pages") or 0)
    if not cap or crawl.get("stop_reason") in ("page_cap", "time_limit", "stopped"):
        return None
    read = sum(1 for p in crawl.get("pages") or [] if isinstance(p, dict) and isinstance(p.get("status"), int)
               and 200 <= p["status"] < 300)
    if read >= cap:
        return None
    parts = []
    for kind, values in fewer_reasons(report):
        n = values.get("n", 0)
        parts.append(W[kind].format(**values, addresses=_plural(n, "address", "addresses"), were=_plural(n, "was", "were each"),
                                    requests=_plural(n, "request", "requests"), pages=_plural(n, "page", "pages")))
    return W["fewer"].format(read=read, cap=cap, why=W["and"].join(parts) if parts else "—").strip()


def sample_line(report: dict, lang: str = "tr") -> str | None:
    """DECISIONS 335: one line for a sampled audit, said the same on page 1, in the limits and in the client brief:
    "Örneklem: 128 sayfa okundu, 499 bilinen adres okunmadı. 150 sayfalık sınırdan 128 sayfa okundu: 21 adres hata
    döndü (404 ×21), 1 adres sayfa değil, dosya, sayfa sınırı her sayfa isteğini sayar." None for any other audit."""
    if not sampled(report):
        return None
    W = SAMPLE.get(lang, SAMPLE["tr"])
    cov = ((report.get("audit_status") or {}).get("content_coverage")) or {}
    read = int(cov.get("pages_read") or 0)
    unread = unread_count(report)
    cap = int(((report.get("crawl") or {}).get("config") or {}).get("max_pages") or 0)
    text = W["line"].format(read=read, unread=unread, read_pages=_plural(read, "page", "pages"),
                            unread_addresses=_plural(unread, "address", "addresses"))
    if cap and read < cap:
        parts = []
        for kind, values in fewer_reasons(report):
            n = values.get("n", 0)
            parts.append(W[kind].format(**values, addresses=_plural(n, "address", "addresses"), were=_plural(n, "was", "were each"),
                                        requests=_plural(n, "request", "requests"), pages=_plural(n, "page", "pages")))
        if parts:
            text += W["fewer"].format(read=read, cap=cap, why=W["and"].join(parts))
    return text


def known_not_read(report: dict) -> int | None:
    """DECISIONS 335: the known-and-unread figure every sentence uses: the sample's for a sampled audit (`unread_count`),
    else the report's own `known_urls_not_read` (None when it has none)."""
    if sampled(report):
        return unread_count(report)
    known = ((report.get("audit_status") or {}).get("content_coverage") or {}).get("known_urls_not_read")
    return known if isinstance(known, int) else None


_UNREAD_REASON = re.compile(r"^\d+ more discovered URL\(s\) remain unchecked$|^Maya's crawl stopped: page_cap\b")


def sample_shown(report: dict, lang: str = "tr") -> str | None:
    """DECISIONS 335: the sample line where a sampled audit's coverage is shown (page 1, the limits, the brief, the web
    results): only when known addresses were left unread and nothing else cut the reading. Everything read: "every
    page found was read" is true and stays; another problem (blocked pages, the time limit): "partial" with its
    reasons stays. The unread figure is the same everywhere either way (`known_not_read`)."""
    if not sampled(report) or not unread_count(report):
        return None
    reasons = ((report.get("audit_status") or {}).get("content_coverage") or {}).get("reasons") or []
    if any(not _UNREAD_REASON.search(str(r)) for r in reasons):
        return None
    return sample_line(report, lang)
