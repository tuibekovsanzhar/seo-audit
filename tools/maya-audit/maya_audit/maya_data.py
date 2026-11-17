"""Maya export data in an audit (DECISIONS 352): Search Console, AI citations and competitor visibility.

Maya exports a project as up to 22 datasets, one file each, named "<domain>-<dataset>[-<from>-<to>].<csv|jsonl|json>"
(several files, a folder or a zip). This module finds them by dataset name, refuses another site's export, reads the
large files as a stream (citation-mentions can be 400 MB; result-items is optional) and keeps one small summary
(`prepare`). The appendix's sheets are made from that summary and the audit's own crawl (`maya_sheets`).

Rules (owner, from the review of Efsa's Enpara file):
- a 28-day snapshot row (gsc-page-scores, gsc-top-queries, gsc-query-opportunities) is never summed: the latest
  snapshot per page or query is used; daily rows (gsc-search-performance, gsc-daily-stats) are summed; every number
  keeps the dataset and the period it comes from;
- brand and non-brand queries from the brand's names (meta.json's project name, brand tags and the domain's name);
- device and country splits when the dataset has them;
- nothing personal from meta.json (names, e-mail addresses, account or integration data) is kept: only the domain,
  the brand names, competitor names and domains, and prompt label names.

Sends no request. A page fetch for the sheets is done by `enrich` with a fetch function the caller gives (the web app
and the CLI give the engine's polite fetcher; tests a fake; a rebuild from saved data none).
"""
from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator
from urllib.parse import unquote, urlsplit, urlunsplit

VERSION = 1
SUMMARY_FILE = "maya-data-summary.json"
FOLDER = "maya-data"

# The datasets Maya exports, by the name in the file name (longest names first when matching).
DATASETS = (
    "prompts", "citation-mentions", "result-items", "meta", "gsc-search-performance", "gsc-page-scores",
    "gsc-daily-stats", "gsc-top-queries", "gsc-top-pages", "gsc-query-intents", "gsc-query-opportunities",
    "topic-visibility-snapshots", "competitor-mentions-daily", "url-rank-history", "prompt-runs", "visibility-daily",
    "share-of-voice-daily", "sentiment-daily", "domain-citations", "fanout-queries", "brand-mentions", "ga4-traffic")
SNAPSHOT_DATASETS = frozenset({"gsc-page-scores", "gsc-top-queries", "gsc-query-opportunities"})
DAILY_DATASETS = frozenset({"gsc-search-performance", "gsc-daily-stats"})
# What each group of sheets needs (any one of a tuple; all of the list).
NEEDS = {
    "overview": [("gsc-daily-stats", "gsc-search-performance", "citation-mentions")],
    "organic_ai": [("gsc-search-performance", "gsc-page-scores", "citation-mentions"), ("prompts",)],
    "page_detail": [("gsc-search-performance", "gsc-page-scores", "citation-mentions"), ("prompts",)],
    "competitors": [("prompts",), ("citation-mentions",), ("topic-visibility-snapshots",), ("competitor-mentions-daily",)],
}
_RANGE = re.compile(r"-(\d{4}-\d{2}-\d{2})-(\d{4}-\d{2}-\d{2})$")
_COPY = re.compile(r"\s*\(\d+\)$")
_TRACKING = re.compile(r"^(utm_|gclid$|fbclid$|msclkid$|srsltid$|ref$|ref_src$)", re.I)
# Words Topic Pulse can report as a "competitor" that are no brand on their own (owner: "maid", "handyman", "urban").
GENERIC_COMPETITORS = frozenset({
    "maid", "maids", "handyman", "urban", "cleaner", "cleaners", "cleaning", "plumber", "electrician", "bank", "banka",
    "kredi", "insurance", "sigorta", "delivery", "shop", "store", "market", "home", "service", "services", "company",
    "app", "online", "digital", "dijital", "other", "others", "diğer", "none", "n/a"})


class MayaDataError(ValueError):
    """An export that cannot be used for this audit (another site's, or unreadable): said in plain Turkish."""


# ---------------------------------------------------------------- files


def dataset_of(filename: str) -> tuple[str | None, str | None, tuple[str, str] | None]:
    """(dataset, domain, (from, to) in the name) for a Maya export file name; (None, None, None) for another file."""
    name = Path(filename).name
    stem, dot, ext = name.rpartition(".")
    if not dot or ext.lower() not in ("csv", "jsonl", "json"):
        return None, None, None
    stem = _COPY.sub("", stem)
    period = None
    m = _RANGE.search(stem)
    if m:
        period, stem = (m.group(1), m.group(2)), stem[:m.start()]
    for ds in sorted(DATASETS, key=len, reverse=True):
        if stem.endswith("-" + ds) and len(stem) > len(ds) + 1:
            return ds, stem[: -(len(ds) + 1)].lower(), period
    return None, None, None


class Source:
    """One export file, opened as text each time it is read (a file on disk or a zip member)."""

    def __init__(self, name: str, opener: Callable[[], io.TextIOBase]):
        self.name, self._open = name, opener
        self.dataset, self.domain, self.period = dataset_of(name)

    def open(self) -> io.TextIOBase:
        return self._open()


def sources(paths: Iterable[str | Path]) -> tuple[dict[str, Source], list[str]]:
    """({dataset: source}, other files) from files, folders and zips. Two files of one dataset: the later name wins
    (a re-export "(2)" over the first)."""
    found: dict[str, Source] = {}
    other: list[str] = []

    def add(src: Source) -> None:
        if src.dataset:
            found[src.dataset] = src
        else:
            other.append(Path(src.name).name)
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            for f in sorted(p.iterdir()):
                if f.is_file() and f.suffix.lower() == ".zip":
                    for s in _zip_sources(f):
                        add(s)
                elif f.is_file():
                    add(Source(f.name, lambda f=f: f.open(encoding="utf-8-sig", newline="")))
        elif p.suffix.lower() == ".zip":
            for s in _zip_sources(p):
                add(s)
        elif p.is_file():
            add(Source(p.name, lambda p=p: p.open(encoding="utf-8-sig", newline="")))
    return found, other


def _zip_sources(path: Path) -> list[Source]:
    out = []
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if not n.endswith("/") and not Path(n).name.startswith(".")]
    for n in names:
        def opener(n=n):
            z = zipfile.ZipFile(path)
            return io.TextIOWrapper(z.open(n), encoding="utf-8-sig", newline="")
        out.append(Source(Path(n).name, opener))
    return out


def _rows(src: Source) -> Iterator[dict]:
    """A CSV file's rows as dicts, read as a stream."""
    with src.open() as fh:
        yield from csv.DictReader(fh)


def _lines(src: Source) -> Iterator[dict]:
    with src.open() as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    yield json.loads(line)
                except ValueError:
                    continue


# ---------------------------------------------------------------- small helpers


def host_of(url: str) -> str:
    try:
        return (urlsplit(url if "://" in url else "https://" + url).hostname or "").lower().removeprefix("www.")
    except ValueError:
        return ""


def page_url(raw: str, origin: str | None = None) -> str | None:
    """An address as one key: scheme added, host lower-case without "www.", tracking parameters off, no fragment, no
    trailing slash but on the root. A brand address is written on the audited origin (`origin`)."""
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        parts = urlsplit(raw if "://" in raw else "https://" + raw)
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    if not host:
        return None
    query = "&".join(q for q in parts.query.split("&") if q and not _TRACKING.match(q.split("=", 1)[0]))
    path = unquote(parts.path or "/")
    if len(path) > 1:
        path = path.rstrip("/") or "/"
    if origin:
        o = urlsplit(origin)
        if host.removeprefix("www.") == (o.hostname or "").lower().removeprefix("www."):
            return urlunsplit((o.scheme or "https", o.netloc.lower(), path, query, ""))
    return urlunsplit(("https", host.removeprefix("www."), path, query, ""))


def _num(value) -> float:
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


def _day(value) -> str | None:
    text = str(value or "")[:10]
    return text if re.match(r"^\d{4}-\d{2}-\d{2}$", text) else None


def _fold(text: str) -> str:
    table = str.maketrans("çğıöşüâîûÇĞİÖŞÜ", "cgiosuaiucgiosu")
    return re.sub(r"\s+", " ", (text or "").translate(table).lower()).strip()


# ---------------------------------------------------------------- meta.json


def read_meta(src: Source | None) -> dict:
    """Only what the report may use: the domain, the brand's names, competitors (names, domains, aliases) and the
    prompt label names. Never a person's name, an e-mail address or account/integration data."""
    if src is None:
        return {}
    try:
        with src.open() as fh:
            data = json.load(fh)
    except (ValueError, OSError):
        return {}
    project = (data.get("project") or [{}])
    project = project[0] if isinstance(project, list) and project else (project if isinstance(project, dict) else {})
    names = [project.get("name")] + list(project.get("brand_tags") or [])
    competitors = []
    for c in ((project.get("brand_facts") or {}).get("competitors") or []) + [
            {"name": r.get("competitor_name"), "domain": r.get("competitor_domain")} for r in data.get("radar_brands") or []
            if isinstance(r, dict)]:
        if isinstance(c, dict) and (c.get("name") or c.get("domain")):
            competitors.append({"name": str(c.get("name") or ""), "domain": host_of(str(c.get("domain") or ""))})
    aliases = []
    for a in data.get("competitor_aliases") or []:
        if isinstance(a, dict):
            aliases.extend(str(v) for k, v in a.items() if k in ("alias", "name", "competitor_name", "canonical") and v)
        elif isinstance(a, str):
            aliases.append(a)
    labels = {str(x.get("id")): str(x.get("name")) for x in data.get("prompt_labels") or []
              if isinstance(x, dict) and x.get("id") and x.get("name")}
    domains = [host_of(project.get("domain") or "")] + [host_of(str(d)) for d in project.get("additional_domains") or []
                                                        if isinstance(d, str)]
    return {"domain": host_of(project.get("domain") or project.get("websiteUrl") or ""),
            "domains": [d for d in domains if d],
            "brand_names": [str(n) for n in names if n],
            "competitors": competitors, "aliases": aliases, "labels": labels}


# ---------------------------------------------------------------- prepare


def prepare(paths: Iterable[str | Path], audited_url: str) -> dict:
    """The summary the sheets are made from. MayaDataError when the export belongs to another site."""
    found, other = sources(paths)
    site = host_of(audited_url)
    meta = read_meta(found.get("meta"))
    domains = {s.domain.removeprefix("www.") for s in found.values() if s.domain}
    if meta.get("domain"):
        domains.add(meta["domain"])
    wrong = sorted(d for d in domains if d and d != site and not d.endswith("." + site) and not site.endswith("." + d))
    if wrong:
        raise MayaDataError(f"Maya verisi başka bir siteye ait ({', '.join(wrong)}); bu denetim {site} için. "
                            "Aynı projenin (aynı alan adının) export dosyalarını ekleyin.")
    origin = "https://" + (urlsplit(audited_url).hostname or site)
    brand_domains = sorted({site} | set(meta.get("domains") or []))
    brand_names = sorted({n for n in (meta.get("brand_names") or []) if n} | {site.split(".")[0]}, key=str.lower)
    out: dict[str, Any] = {
        "version": VERSION, "domain": site, "origin": origin, "brand_domains": brand_domains, "brand_names": brand_names,
        "competitors": meta.get("competitors") or [], "aliases": meta.get("aliases") or [],
        "datasets": [], "other_files": sorted(other)}
    for ds, src in sorted(found.items()):
        out["datasets"].append({"dataset": ds, "file": src.name, "period": list(src.period) if src.period else None})
    out["missing"] = {sheet: [" / ".join(g) for g in groups if not any(d in found for d in g)]
                      for sheet, groups in NEEDS.items()}
    out["gsc"] = _gsc(found, origin, brand_names)
    out["ai"] = _ai(found, origin, brand_domains, brand_names, meta.get("labels") or {})
    out["visibility"] = _visibility(found, meta, brand_names)
    out["mentions"] = _mentions(found, meta)
    counts = {**(out["gsc"].get("rows") or {}), **(out["ai"].get("rows") or {})}
    if out["visibility"]:
        counts["topic-visibility-snapshots"] = out["visibility"]["rows"]
    if out["mentions"]:
        counts["competitor-mentions-daily"] = out["mentions"]["rows"]
    for d in out["datasets"]:
        d["rows"] = counts.get(d["dataset"])
    return out


# ---------------------------------------------------------------- Search Console


def _is_brand(query: str, brand_names: list[str]) -> bool:
    q = _fold(query)
    return any(_fold(n) and re.search(rf"(?<![a-z0-9]){re.escape(_fold(n))}", q) for n in brand_names)


def _gsc(found: dict[str, Source], origin: str, brand_names: list[str]) -> dict:
    out: dict[str, Any] = {"rows": {}}
    days: dict[str, dict] = {}
    day_source = None
    perf = found.get("gsc-search-performance")
    pages: dict[str, dict] = {}
    page_source = None
    brand = {"brand": Counter(), "non_brand": Counter()}
    devices: dict[str, Counter] = defaultdict(Counter)
    countries: dict[str, Counter] = defaultdict(Counter)
    if perf is not None:
        n = 0
        pos_w: dict[str, float] = defaultdict(float)
        for r in _rows(perf):
            n += 1
            d = _day(r.get("date"))
            clicks, impr = _num(r.get("clicks")), _num(r.get("impressions"))
            if r.get("page"):
                u = page_url(r["page"], origin)
                if u:
                    rec = pages.setdefault(u, {"clicks": 0.0, "impressions": 0.0})
                    rec["clicks"] += clicks
                    rec["impressions"] += impr
                    pos_w[u] += _num(r.get("position")) * impr
            if r.get("query"):
                brand["brand" if _is_brand(r["query"], brand_names) else "non_brand"].update(clicks=clicks, impressions=impr)
            if r.get("device"):
                devices[r["device"]].update(clicks=clicks, impressions=impr)
            if r.get("country"):
                countries[r["country"]].update(clicks=clicks, impressions=impr)
            if d and not r.get("query") and not r.get("page") and not r.get("device") and not r.get("country"):
                rec = days.setdefault(d, {"clicks": 0.0, "impressions": 0.0, "pos_w": 0.0})
                rec["clicks"] += clicks
                rec["impressions"] += impr
                rec["pos_w"] += _num(r.get("position")) * impr
        for u, rec in pages.items():
            rec["position"] = round(pos_w[u] / rec["impressions"], 1) if rec["impressions"] else None
            rec["ctr"] = round(rec["clicks"] / rec["impressions"], 4) if rec["impressions"] else None
        out["rows"]["gsc-search-performance"] = n
        if pages:
            page_source = "gsc-search-performance"
        if days:
            day_source = "gsc-search-performance"
    scores = found.get("gsc-page-scores")
    if scores is not None and not pages:
        # A 28-day snapshot: never summed; a page listed twice keeps its latest row (the file's order).
        n = 0
        for r in _rows(scores):
            n += 1
            u = page_url(r.get("page") or "", origin)
            if u:
                pages[u] = {"clicks": _num(r.get("clicks")), "impressions": _num(r.get("impressions")),
                            "ctr": round(_num(r.get("ctr")), 4), "position": round(_num(r.get("position")), 1)}
        out["rows"]["gsc-page-scores"] = n
        page_source = "gsc-page-scores"
    daily = found.get("gsc-daily-stats")
    if daily is not None and not days:
        n = 0
        for r in _rows(daily):
            n += 1
            d = _day(r.get("date"))
            if d:
                impr = _num(r.get("impressions"))
                days[d] = {"clicks": _num(r.get("clicks")), "impressions": impr, "pos_w": _num(r.get("position")) * impr}
        out["rows"]["gsc-daily-stats"] = n
        day_source = "gsc-daily-stats"
    weekly = found.get("gsc-top-pages")
    sample: dict[str, float] = defaultdict(float)
    if weekly is not None:
        n = 0
        weeks = set()
        for r in _rows(weekly):
            n += 1
            u = page_url(r.get("page") or "", origin)
            if u:
                sample[u] += _num(r.get("clicks"))  # weekly rows: disjoint weeks, summed only within this dataset
                weeks.add(r.get("week_start"))
        out["rows"]["gsc-top-pages"] = n
        out["weekly_sample"] = {"source": "gsc-top-pages", "weeks": len(weeks),
                                "period": [min(weeks), max(weeks)] if weeks else None, "clicks": dict(sample)}
    intents = found.get("gsc-query-intents")
    if intents is not None and not (brand["brand"] or brand["non_brand"]):
        out["rows"]["gsc-query-intents"] = sum(1 for _ in _rows(intents))
    top_queries = found.get("gsc-top-queries")
    if top_queries is not None and not (brand["brand"] or brand["non_brand"]):
        # snapshot rows: the latest per query, then split
        latest: dict[str, dict] = {}
        n = 0
        for r in _rows(top_queries):
            n += 1
            q = r.get("query") or ""
            key = r.get("week_start") or r.get("date") or ""
            if q and (q not in latest or key >= latest[q]["key"]):
                latest[q] = {"key": key, "clicks": _num(r.get("clicks")), "impressions": _num(r.get("impressions"))}
        for q, rec in latest.items():
            brand["brand" if _is_brand(q, brand_names) else "non_brand"].update(clicks=rec["clicks"], impressions=rec["impressions"])
        out["rows"]["gsc-top-queries"] = n
        if latest:
            out["brand_source"] = "gsc-top-queries"
    if brand["brand"] or brand["non_brand"]:
        out.setdefault("brand_source", "gsc-search-performance")
        out["brand"] = {k: dict(v) for k, v in brand.items()}
    if devices:
        out["devices"] = {k: dict(v) for k, v in devices.items()}
    if countries:
        out["countries"] = {k: dict(sorted(v.items())) for k, v in sorted(countries.items(), key=lambda kv: -kv[1]["clicks"])[:10]}
    if pages:
        out["pages"] = pages
        out["page_source"] = page_source
        out["page_kind"] = "snapshot" if page_source in SNAPSHOT_DATASETS else "daily"
        src = found.get(page_source)
        out["page_period"] = list(src.period) if src is not None and src.period else None
    if days:
        out["day_source"] = day_source
        out["monthly"], out["weeks"] = _months(days)
        out["day_period"] = [min(days), max(days)]
    return out


def _months(days: dict[str, dict]) -> tuple[list[dict], list[dict]]:
    """Monthly totals (daily rows summed) with the average weekday (Mon-Fri) per month, for months of unequal length;
    and Monday-Friday weeks, to compare like with like."""
    by_month: dict[str, list[tuple[date, dict]]] = defaultdict(list)
    for d, rec in days.items():
        dt = date.fromisoformat(d)
        by_month[d[:7]].append((dt, rec))
    months = []
    for m, items in sorted(by_month.items()):
        clicks = sum(r["clicks"] for _, r in items)
        impr = sum(r["impressions"] for _, r in items)
        pos = sum(r["pos_w"] for _, r in items) / impr if impr else None
        weekdays = [r for dt, r in items if dt.weekday() < 5]
        months.append({"month": m, "days": len(items), "clicks": round(clicks), "impressions": round(impr),
                       "position": round(pos, 1) if pos else None,
                       "weekday_clicks": round(sum(r["clicks"] for r in weekdays) / len(weekdays), 1) if weekdays else None,
                       "weekday_impressions": round(sum(r["impressions"] for r in weekdays) / len(weekdays), 1) if weekdays else None})
    weeks: dict[str, list[tuple[date, dict]]] = defaultdict(list)
    for d, rec in days.items():
        dt = date.fromisoformat(d)
        if dt.weekday() < 5:
            monday = date.fromordinal(dt.toordinal() - dt.weekday())
            weeks[monday.isoformat()].append((dt, rec))
    full = []
    for monday, items in sorted(weeks.items()):
        if len(items) == 5:
            impr = sum(r["impressions"] for _, r in items)
            full.append({"week": f"{monday[5:]} – {max(dt for dt, _ in items).isoformat()[5:]}",
                         "clicks": round(sum(r["clicks"] for _, r in items)), "impressions": round(impr),
                         "position": round(sum(r["pos_w"] for _, r in items) / impr, 1) if impr else None})
    return months, full


# ---------------------------------------------------------------- AI citations


def _provider(name: str) -> str:
    return (name or "").strip().lower() or "—"


def _ai(found: dict[str, Source], origin: str, brand_domains: list[str], brand_names: list[str],
        labels: dict[str, str]) -> dict:
    out: dict[str, Any] = {"rows": {}}
    prompts = found.get("prompts")
    info: dict[str, dict] = {}
    if prompts is not None:
        n = 0
        for r in _rows(prompts):
            n += 1
            pid = r.get("id")
            if not pid:
                continue
            try:
                ids = json.loads(r.get("labels") or "[]")
            except ValueError:
                ids = []
            names = [labels[i] for i in ids if i in labels]
            info[pid] = {"text": (r.get("text") or "")[:300], "topic": names[0] if names else None,
                         "active": str(r.get("is_active") or "1") not in ("0", "false", "False")}
        out["rows"]["prompts"] = n
    out["prompts"] = info
    cites = found.get("citation-mentions")
    if cites is None:
        return out
    brand_set = set(brand_domains)

    def is_brand(domain: str) -> bool:
        return any(domain == b or domain.endswith("." + b) for b in brand_set)
    monthly_rows: Counter = Counter()
    monthly_brand: Counter = Counter()
    prov_rows: Counter = Counter()
    prov_brand: Counter = Counter()
    domain_prompts: dict[str, set] = defaultdict(set)
    pages: dict[str, dict] = {}
    prompt_urls: dict[str, Counter] = defaultdict(Counter)   # non-brand addresses per prompt (runs)
    prompt_brand_pages: dict[str, Counter] = defaultdict(Counter)
    prompt_runs: dict[str, set] = defaultdict(set)
    prompt_brand_runs: dict[str, set] = defaultdict(set)
    first = last = None
    n = 0
    for r in _rows(cites):
        n += 1
        domain = host_of(r.get("domain") or r.get("url") or "")
        if not domain or "." not in domain:
            continue  # not an address ("goto", an empty cell)
        model = _provider(r.get("model"))
        pid = r.get("prompt_id") or ""
        run = r.get("run_id") or r.get("id") or str(n)
        month = (r.get("created_at") or "")[:7]
        day = _day(r.get("created_at"))
        if day:
            first = day if first is None or day < first else first
            last = day if last is None or day > last else last
        brand = is_brand(domain)
        monthly_rows[month] += 1
        prov_rows[model] += 1
        domain_prompts[domain].add(pid)
        prompt_runs[pid].add(run)
        if brand:
            monthly_brand[month] += 1
            prov_brand[model] += 1
            prompt_brand_runs[pid].add(run)
            u = page_url(r.get("url") or domain, origin)
            if u:
                rec = pages.setdefault(u, {"prompts": set(), "runs": set(), "by_provider": Counter()})
                rec["prompts"].add(pid)
                rec["runs"].add(run)
                rec["by_provider"][model] += 1
                prompt_brand_pages[pid][u] += 1
        else:
            u = page_url(r.get("url") or domain)
            if u:
                prompt_urls[pid][u] += 1
    out["rows"]["citation-mentions"] = n
    out["period"] = [first, last] if first else None
    out["monthly"] = [{"month": m, "rows": monthly_rows[m], "brand_rows": monthly_brand[m]} for m in sorted(monthly_rows) if m]
    out["providers"] = {p: {"rows": prov_rows[p], "brand_rows": prov_brand[p]} for p in sorted(prov_rows)}
    out["top_domains"] = [[d, len(ps)] for d, ps in sorted(domain_prompts.items(), key=lambda kv: (-len(kv[1]), kv[0]))
                          if not is_brand(d)][:20]
    out["prompts_cited"] = len(prompt_runs)
    out["pages"] = {u: {"prompts": len(rec["prompts"]), "runs": len(rec["runs"]), "by_provider": dict(rec["by_provider"]),
                        "prompt_ids": sorted(rec["prompts"])[:400]} for u, rec in pages.items()}
    out["prompt_urls"] = {pid: dict(c.most_common(40)) for pid, c in prompt_urls.items()}
    out["prompt_brand_pages"] = {pid: dict(c.most_common(10)) for pid, c in prompt_brand_pages.items()}
    out["prompt_runs"] = {pid: len(v) for pid, v in prompt_runs.items()}
    out["prompt_brand_runs"] = {pid: len(v) for pid, v in prompt_brand_runs.items()}
    out["sov"] = _sov(found.get("result-items"), brand_names, out["rows"])
    return out


def _sov(src: Source | None, brand_names: list[str], rows: dict) -> dict | None:
    """Share of voice per provider and month from the answers (result-items, optional): the brand's mentions over all
    brand mentions in the answers (the brand and the brands each answer compares it with)."""
    if src is None:
        return None
    mine: Counter = Counter()
    every: Counter = Counter()
    n = 0
    for r in _lines(src):
        n += 1
        if str(r.get("success", "1")) in ("0", "false", "False"):
            continue
        key = (_provider(r.get("provider")), (r.get("createdAt") or "")[:7])
        brands = r.get("comparisonBrands")
        if isinstance(brands, str):
            brands = re.findall(r"'([^']+)'|\"([^\"]+)\"", brands)
            brands = [a or b for a, b in brands]
        others = len({_fold(b) for b in brands or [] if not any(_fold(x) in _fold(b) for x in brand_names)})
        hit = str(r.get("matched")) in ("1", "True", "true")
        mine[key] += int(hit)
        every[key] += int(hit) + others
    rows["result-items"] = n
    return {f"{p}|{m}": round(mine[(p, m)] / every[(p, m)], 4) for (p, m) in every if every[(p, m)] and m}


# ---------------------------------------------------------------- competitors


def is_generic(name: str) -> bool:
    words = _fold(name).split()
    return not words or (len(words) == 1 and words[0] in GENERIC_COMPETITORS)


def _visibility(found: dict[str, Source], meta: dict, brand_names: list[str]) -> dict | None:
    src = found.get("topic-visibility-snapshots")
    if src is None:
        return None
    by_topic: dict[str, list[dict]] = defaultdict(list)
    n = 0
    for r in _rows(src):
        n += 1
        if r.get("topic"):
            by_topic[r["topic"]].append(r)
    topics = []
    for topic, rows in sorted(by_topic.items()):
        rows.sort(key=lambda r: r.get("week_start") or "")
        first, last = rows[0], rows[-1]
        leader = last.get("top_competitor_name") or ""
        generic = is_generic(leader)
        lead_first = next((_num(r.get("top_competitor_rate")) for r in rows if r.get("top_competitor_name") == leader), None)
        topics.append({"topic": topic, "first_week": first.get("week_start"), "last_week": last.get("week_start"),
                       "brand_first": _num(first.get("brand_rate")), "brand_last": _num(last.get("brand_rate")),
                       "leader": None if generic else leader, "leader_ignored": leader if generic else None,
                       "leader_first": None if generic else lead_first,
                       "leader_last": None if generic else _num(last.get("top_competitor_rate")),
                       "gap": None if generic else round(_num(last.get("top_competitor_rate")) - _num(last.get("brand_rate")), 1),
                       "answers": int(_num(last.get("total")))})
    return {"rows": n, "topics": topics}


def _mentions(found: dict[str, Source], meta: dict) -> dict | None:
    src = found.get("competitor-mentions-daily")
    if src is None:
        return None
    total: Counter = Counter()
    domains: dict[str, str] = {}
    n = 0
    for r in _rows(src):
        n += 1
        name = r.get("displayName") or r.get("competitorKey") or ""
        if name and not is_generic(name):
            total[name] += int(_num(r.get("mentions")))
            if r.get("domain"):
                domains[name] = host_of(r["domain"])
    return {"rows": n, "top": [[name, count, domains.get(name)] for name, count in total.most_common(15)]}


# ---------------------------------------------------------------- the audit's folder


def save(summary: dict, folder: Path) -> Path:
    path = Path(folder) / SUMMARY_FILE
    path.write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")
    return path


def load_for(folder: Path | str | None) -> dict | None:
    """The summary saved beside an audit's report (`<artifacts>/maya-data-summary.json`), or None."""
    if not folder:
        return None
    path = Path(folder) / SUMMARY_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("version") == VERSION else None


# ---------------------------------------------------------------- a polite fetcher for `maya_sheets.enrich`


def polite_fetcher(gap_s: float = 1.0, timeout_s: float = 15.0, transport=None) -> Callable[[str], str | None]:
    """fetch(url) -> HTML or None: public addresses only (the engine's guarded transport), robots.txt obeyed per host,
    a browser's identity, one request at a time with `gap_s` between them, HTML answers only. Used only where the
    owner asked for live pages (the web app's Maya upload, the CLI's --maya-fetch); never in tests."""
    import time
    import httpx
    from urllib.robotparser import RobotFileParser
    from .network import PublicTransport
    from .probes import BROWSER_USER_AGENT
    client = httpx.Client(transport=transport or PublicTransport(allow_loopback=False), timeout=timeout_s,
                          follow_redirects=True, headers={"User-Agent": BROWSER_USER_AGENT})
    robots: dict[str, RobotFileParser | None] = {}
    last = [0.0]

    def wait() -> None:
        pause = gap_s - (time.monotonic() - last[0])
        if pause > 0:
            time.sleep(pause)
        last[0] = time.monotonic()

    def allowed(url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in robots:
            rp = RobotFileParser()
            try:
                wait()
                r = client.get(origin + "/robots.txt")
                rp.parse(r.text.splitlines() if r.status_code == 200 else [])
                robots[origin] = rp
            except httpx.HTTPError:
                robots[origin] = None
        rp = robots[origin]
        return rp is None or rp.can_fetch(BROWSER_USER_AGENT, url)

    def fetch(url: str) -> str | None:
        if not allowed(url):
            return None
        wait()
        r = client.get(url)
        kind = r.headers.get("content-type", "")
        return r.text if r.status_code == 200 and "html" in kind.lower() else None
    return fetch
