"""Before and after: how many of the right pages an audit reads, on made-up sites and a made-up reader.

    .venv/bin/python scripts/coverage_benchmark.py            # print the tables
    .venv/bin/python scripts/coverage_benchmark.py --write    # and write docs/COVERAGE-BENCHMARK.md

Nothing here reaches a network: every site is an in-memory transport and the reader is a function. "Before" is the
reader as it was after Phase 1 (first come, first served; no sitemap through the reader; no stop when it keeps
failing; no time kept for it). "After" is the reader as it is now. Maya's own crawler is the same in both.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
import tracemalloc
from dataclasses import dataclass, field
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from maya_audit.audit import run_audit  # noqa: E402
from maya_audit.config import CrawlConfig  # noqa: E402
from maya_audit.dataforseo.cache import Cache  # noqa: E402
from maya_audit.dataforseo.ledger import Ledger  # noqa: E402
from maya_audit.firecrawl import FirecrawlClient, FirecrawlKey, Options, panel, reader, settings  # noqa: E402
from maya_audit.report import audit_status, run_outcome  # noqa: E402
from maya_audit.runclock import RunClock, reader_allowance_s  # noqa: E402

OUT = ROOT / "docs" / "COVERAGE-BENCHMARK.md"
# The audit's own waits are switched off (as in the test suite): this measures what is read, not how long a real site takes.
FAST = dict(request_delay_s=0.0, robots_samples=1, robots_sample_interval_s=0.0, refetch_delay_s=0.0, prf_round_gap_s=0.0,
            render_enabled=False, probes_enabled=False, probe_retry_cooldown_s=0.0, prf_enabled=False)
HOST = "https://site.test"
WORDS = ("This made-up page describes one thing the made-up business offers, in enough plain sentences to be worth "
         "reading: what it is, who it is for, how much it costs, and how to get it. ") * 3
CHALLENGE = "<!doctype html><html><head><title>Just a moment...</title></head><body>Checking your browser</body></html>"
BEFORE = dict(spread_by_section=False, sitemap_discovery=False, stop_after_unreadable=0)
AFTER = dict(spread_by_section=True, sitemap_discovery=True, stop_after_unreadable=5)


@dataclass
class Scenario:
    name: str
    about: str
    pages: dict[str, tuple[str, list[str]]]          # path -> (title, links in the body)
    nav: list[str] = field(default_factory=list)     # links in the menu of every page
    sitemap: list[str] | None = None                 # paths listed in /sitemap.xml; None: there is none
    key_pages: tuple[str, ...] = ()
    cap: int = 50
    javascript: bool = False                         # the raw HTML is an empty shell; only a reader sees the content
    direct_challenged: bool = False
    reader_challenged: bool = False
    reader_fails_after: int | None = None            # the reader is turned away after this many pages
    language: str = "en"
    healthy: bool = False                            # nothing is wrong with access or coverage: findings must not grow

    def html(self, path: str) -> str:
        title, links = self.pages[path]
        menu = "".join(f'<a href="{p}">{self.pages[p][0]}</a> ' for p in self.nav)
        body = "".join(f'<li><a href="{p}">{self.pages.get(p, (p, []))[0]}</a></li>' for p in links)
        return (f'<!doctype html><html lang="{self.language}"><head><meta charset="utf-8"><title>{title} | Made-up Site</title>'
                f'<meta name="description" content="{title}: a made-up page for a coverage benchmark, with its own description.">'
                f'</head><body><header><nav>{menu}</nav></header><main><h1>{title}</h1><p>{WORDS}</p><ul>{body}</ul></main></body></html>')

    def shell(self) -> str:
        return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Made-up Site</title></head>'
                '<body><div id="root"></div><script src="/app.js"></script></body></html>')

    def sitemap_xml(self) -> str:
        return ('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                + "".join(f"<url><loc>{HOST}{p}</loc></url>" for p in self.sitemap or []) + "</urlset>")

    def direct(self) -> httpx.MockTransport:
        def respond(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if self.direct_challenged:
                return httpx.Response(403, headers={"content-type": "text/html", "server": "cloudflare", "cf-mitigated": "challenge"}, text=CHALLENGE)
            if path == "/robots.txt":
                extra = f"Sitemap: {HOST}/sitemap.xml\n" if self.sitemap is not None else ""
                return httpx.Response(200, headers={"content-type": "text/plain"}, text="User-agent: *\nAllow: /\n" + extra)
            if path == "/sitemap.xml":
                return (httpx.Response(200, headers={"content-type": "application/xml"}, text=self.sitemap_xml()) if self.sitemap is not None
                        else httpx.Response(404, headers={"content-type": "text/plain"}, text=""))
            if path not in self.pages:
                return httpx.Response(404, headers={"content-type": "text/html"}, text="<html><title>Not found</title></html>")
            return httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"}, text=self.shell() if self.javascript else self.html(path))
        return httpx.MockTransport(respond)

    def reader(self, sent: list[str]) -> httpx.MockTransport:
        """A made-up Firecrawl: it renders the page (so a JavaScript site has content) and can be turned away."""
        def respond(request: httpx.Request) -> httpx.Response:
            url = json.loads(request.content)["url"]
            sent.append(url)
            path = url.removeprefix(HOST) or "/"
            pages_so_far = sum(1 for u in sent if (u.removeprefix(HOST) or "/") in self.pages)
            turned_away = self.reader_challenged or (self.reader_fails_after is not None and pages_so_far > self.reader_fails_after)
            if turned_away and path != "/robots.txt":
                return httpx.Response(200, json={"success": True, "data": {"rawHtml": CHALLENGE, "metadata": {"statusCode": 403, "url": url}}})
            if path == "/sitemap.xml" and self.sitemap is not None:
                return httpx.Response(200, json={"success": True, "data": {"rawHtml": self.sitemap_xml(), "metadata": {"statusCode": 200, "url": url}}})
            if path not in self.pages:
                return httpx.Response(200, json={"success": True, "data": {"rawHtml": "<html><title>Not found</title></html>", "metadata": {"statusCode": 404, "url": url}}})
            return httpx.Response(200, json={"success": True, "data": {"rawHtml": self.html(path), "metadata": {"statusCode": 200, "url": url}}})
        return httpx.MockTransport(respond)


def _site(sections: dict[str, int], extra: dict[str, tuple[str, list[str]]] | None = None, hub_links: bool = True) -> dict[str, tuple[str, list[str]]]:
    """A site of hub pages (/products) each listing its own pages (/products/item-1 ...), plus any extra pages."""
    pages: dict[str, tuple[str, list[str]]] = {}
    for section, count in sections.items():
        children = [f"/{section}/item-{n}" for n in range(1, count + 1)]
        pages[f"/{section}"] = (section.replace("-", " ").title(), children if hub_links else [])
        for n, child in enumerate(children, 1):
            pages[child] = (f"{section.replace('-', ' ').title()} {n}", [])
    pages.update(extra or {})
    pages["/"] = ("Home", [f"/{s}" for s in sections])
    return pages


def scenarios() -> list[Scenario]:
    info = {"/about": ("About", []), "/contact": ("Contact", []), "/shipping-returns": ("Shipping and returns", []), "/faq": ("Questions", [])}
    shelves = ["kettles", "teapots", "mugs", "plates", "bowls", "cutlery", "glasses", "trays", "lamps", "rugs", "chairs", "tables"]
    shop = _site({name: 42 for name in shelves}, info)                                 # 12 x 43 + 5 = 521 pages
    shop["/"] = ("Home", [f"/{name}" for name in shelves] + list(info))                # the information pages are linked last, in the footer
    clinic = _site({"doctors": 18, "services": 14}, {"/appointments": ("Appointments", []), "/about": ("About", []), "/contact": ("Contact", [])})
    clinic_posts = [f"/blog/post-{n}" for n in range(1, 13)]
    clinic.update({p: (f"Health article {n}", []) for n, p in enumerate(clinic_posts, 1)})  # in the sitemap only: nothing links to them
    saas = _site({"docs": 120, "blog": 30, "integrations": 24}, {"/pricing": ("Pricing", []), "/features": ("Features", []), "/security": ("Security", [])})
    saas["/"] = ("Home", ["/docs", "/blog", "/integrations", "/pricing", "/features", "/security"])
    restaurant = {"/": ("Home", ["/menu", "/hours", "/reservations", "/about"]), "/menu": ("Menu", []), "/hours": ("Opening hours", []),
                  "/reservations": ("Reservations", []), "/about": ("About", [])}
    static = _site({"guides": 8}, {"/about": ("About", []), "/contact": ("Contact", [])})
    static["/"] = ("Home", ["/guides", "/about", "/contact"])
    app = {"/": ("Home", []), **{f"/{p}": (p.title(), []) for p in ("features", "pricing", "customers", "security", "docs", "changelog", "about", "contact")}}
    tr_en = {"/": ("Home", ["/tr", "/en"]), "/tr": ("Ana sayfa", [f"/tr/hizmet-{n}" for n in range(1, 16)]), "/en": ("Home (English)", [f"/en/service-{n}" for n in range(1, 16)]),
             **{f"/tr/hizmet-{n}": (f"Hizmet {n}: çağrı, şikâyet, öğüt", []) for n in range(1, 16)}, **{f"/en/service-{n}": (f"Service {n}", []) for n in range(1, 16)}}
    orphans = {"/": ("Home", ["/a", "/b", "/c", "/d", "/e"]), **{f"/{c}": (c.upper(), []) for c in "abcde"}, **{f"/landing/offer-{n}": (f"Offer {n}", []) for n in range(1, 13)}}
    return [
        Scenario("static", "Static site, 12 pages, everything linked", static, nav=["/guides", "/about", "/contact"], cap=50, healthy=True),
        Scenario("restaurant", "Restaurant, 5 pages", restaurant, nav=["/menu", "/hours", "/reservations"], cap=50, healthy=True),
        Scenario("tr_en", "Turkish and English site, 33 pages", tr_en, nav=["/tr", "/en"], cap=50, healthy=True, language="tr"),
        Scenario("sitemap_only", "Open site: 6 linked pages and 12 only in the sitemap", orphans, sitemap=list(orphans), cap=50, healthy=True),
        Scenario("javascript", "JavaScript site: raw HTML is a shell, the menu exists only after rendering", app, nav=[p for p in app if p != "/"], javascript=True, cap=50),
        Scenario("clinic_challenged", "Clinic behind a challenge; 12 articles are in the sitemap only", clinic, nav=["/doctors", "/services", "/appointments", "/contact"],
                 sitemap=list(clinic), key_pages=("/appointments",), cap=50, direct_challenged=True),
        Scenario("both_challenged", "Both Maya and the reader are challenged", restaurant, direct_challenged=True, reader_challenged=True, cap=50),
        Scenario("reader_turned_away", "Challenged site; the reader is turned away after 8 pages", clinic, nav=["/doctors", "/services"], cap=50,
                 direct_challenged=True, reader_fails_after=8),
        Scenario("shop_50_challenged", "Shop of 521 pages behind a challenge, cap 50; the returns page is a key page", shop, nav=["/kettles", "/teapots", "/mugs", "/plates", "/bowls", "/cutlery", "/glasses", "/trays", "/lamps", "/rugs", "/chairs", "/tables"],
                 key_pages=("/shipping-returns",), cap=50, direct_challenged=True),
        Scenario("saas_50_challenged", "SaaS site of 181 pages behind a challenge, cap 50", saas, nav=["/docs", "/pricing", "/features"], cap=50, direct_challenged=True),
        Scenario("shop_50_open", "The same shop, open, cap 50", shop, nav=["/kettles", "/teapots", "/mugs", "/plates", "/bowls", "/cutlery", "/glasses", "/trays", "/lamps", "/rugs", "/chairs", "/tables"], key_pages=("/shipping-returns",), cap=50),
        Scenario("shop_500_open", "The same shop, open, cap 500", shop, nav=["/kettles", "/teapots", "/mugs", "/plates", "/bowls", "/cutlery", "/glasses", "/trays", "/lamps", "/rugs", "/chairs", "/tables"], key_pages=("/shipping-returns",), cap=500),
        Scenario("shop_500_challenged", "The same shop behind a challenge, cap 500", shop, nav=["/kettles", "/teapots", "/mugs", "/plates", "/bowls", "/cutlery", "/glasses", "/trays", "/lamps", "/rugs", "/chairs", "/tables"],
                 sitemap=list(shop), key_pages=("/shipping-returns",), cap=500, direct_challenged=True),
    ]


def run(scenario: Scenario, flags: dict, folder: Path) -> dict:
    """One audit of one made-up site: Maya's own crawl, then the reader, exactly as the command line runs them."""
    config = CrawlConfig(**{**FAST, "max_pages": scenario.cap, "key_pages": tuple(HOST + p for p in scenario.key_pages)})
    sent: list[str] = []
    tracemalloc.start()
    began = time.perf_counter()
    outcome = run_audit(HOST + "/", config, scenario.direct())
    # One request at a time: the benchmark measures which pages are read and what they cost, not concurrency, and its
    # figures stay comparable with those measured before Firecrawl had its own pace (DECISIONS 295).
    options = Options(read_always=True, max_pages=min(scenario.cap, settings.MAX_PAGES_LIMIT), **{"concurrency": 1, **flags})
    estimate = options.estimate(config.max_pages)
    client = FirecrawlClient(FirecrawlKey("fc-made-up-key"), Ledger(folder / "ledger.jsonl"), None, approved_credits=estimate["max_credits"],
                             max_pages=options.max_pages, transport=scenario.reader(sent))
    client.clock = RunClock()  # no deadline here: coverage is measured, time is measured apart (see `time_split`)
    info = reader.apply(outcome, config, client, options)
    client.close()
    seconds = time.perf_counter() - began
    _now, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    section = panel.section(info)
    status = audit_status(outcome.result, outcome.gates, outcome.checks, section)
    read = {p.url for p in outcome.result.pages if p.readable_document()} | {r["url"] for r in section.get("pages", []) if r["outcome"] == "read"}
    view = info.get("view_pages") or []
    worded = {p.url for p in [*view, *outcome.result.pages] if p.analysis and len((p.analysis.get("_content_blocks") or p.analysis.get("_text_blocks") or [""])) and
              sum(len(str(b).split()) for b in (p.analysis.get("_content_blocks") or p.analysis.get("_text_blocks") or [])) >= 40}
    from maya_audit.urls import section_key
    sections = {section_key(u) for u in read}  # kinds of page: /kettles (a list) and /kettles/{id} (a product) are two
    findings = [f for c in outcome.checks if not c.check_id.startswith("ANS") for f in c.findings]
    cover = section.get("coverage") or {}
    return {"readable": len(read), "of": len(scenario.pages), "key_read": sum(1 for p in scenario.key_pages if HOST + p in read), "key_total": len(scenario.key_pages),
            "pending": status["content_coverage"]["known_urls_not_read"], "usable": len(worded & read), "parts_of_site": len(sections),
            "requests": client.requests_sent, "credits": sum(c["credits"] for c in client.calls), "max_credits": estimate["max_credits"],
            "outcome": run_outcome(outcome.result, outcome.gates, section)[1], "seconds": round(seconds, 2), "peak_mb": round(peak / 1e6, 1),
            "problems": sum(1 for f in findings if f.severity.value != "Info"), "notes": sum(1 for f in findings if f.severity.value == "Info"),
            "stopped": section.get("stopped_because"), "causes": cover.get("causes") or {}, "why_pending": cover.get("not_requested_because"),
            "sitemap_found": cover.get("sitemap_addresses_found", 0), "direct": status["direct_access"]["state"], "level": status["content_coverage"]["level"]}


def time_split(per_page_assumed: float, answer_s: float, pages: int = 50, delay_s: float = 1.0, crawl_takes_s: float = 0.0,
               kept_for_reader: bool = True, limit_s: float | None = None) -> dict:
    """How many pages a reader reads before the audit's deadline, with a made-up clock: each answer takes `answer_s`,
    requests keep `delay_s` apart, and the reader has the time the assumption set aside (`per_page_assumed` a page)."""
    clock = {"now": 0.0}
    reserve = reader_allowance_s(pages, delay_s, per_page_assumed)
    # Kept for the reader: the deadline is the end of Maya's own work plus the reserve. Not kept (as before Phase 2): one
    # limit for everything, so whatever Maya's crawl used is gone.
    deadline = crawl_takes_s + reserve if kept_for_reader else (limit_s if limit_s is not None else crawl_takes_s + reserve)
    run_clock = RunClock(deadline_mono=deadline, pace_s=delay_s, clock=lambda: clock["now"],
                         sleep=lambda s: clock.__setitem__("now", clock["now"] + s), started_mono=0.0)
    clock["now"] = crawl_takes_s
    read = 0
    while read < pages and run_clock.wait_for_turn() is None:
        run_clock.site_was_asked()
        clock["now"] += answer_s
        if run_clock.remaining() is not None and run_clock.remaining() < 0:
            break  # cut off: its answer came after the deadline
        read += 1
    return {"assumed_s_per_page": per_page_assumed, "answer_s": answer_s, "reserve_s": reserve, "pages_read": read, "of": pages,
            "used_s": round(clock["now"] - crawl_takes_s, 1), "kept_for_reader": kept_for_reader, "crawl_takes_s": crawl_takes_s}


def benchmark() -> dict:
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        for number, scenario in enumerate(scenarios()):
            before = run(scenario, BEFORE, Path(tmp) / f"b{number}")
            after = run(scenario, AFTER, Path(tmp) / f"a{number}")
            rows.append({"name": scenario.name, "about": scenario.about, "cap": scenario.cap, "healthy": scenario.healthy, "before": before, "after": after})
    splits = [time_split(assumed, answer) for assumed in (8.0, 20.0) for answer in (2.0, 8.0, 20.0)]
    # A slow site: Maya's own crawl and checks use a whole 840-second limit (the default for 50 pages plus the reader's 450).
    slow_site = [time_split(8.0, 4.0, crawl_takes_s=840.0, kept_for_reader=False, limit_s=840.0),
                 time_split(8.0, 4.0, crawl_takes_s=390.0, kept_for_reader=True)]
    return {"rows": rows, "time": splits, "slow_site": slow_site}


def markdown(result: dict) -> str:
    lines = ["# Coverage benchmark: before and after Phase 2", "",
             "Generated by `scripts/coverage_benchmark.py` from made-up sites and a made-up reader. No network is used. "
             "\"Before\" is the reader as Phase 1 left it; \"after\" is the reader now. Maya's own crawler is unchanged, so open sites "
             "that Maya reads completely show the same figures on both sides: that is the check that nothing was made worse.", "",
             "| Case | Cap | Pages read (of site) | Key pages read | Kinds of page sampled | Known URLs left unread | Pages with real text | Reader requests | Credits used (max) | Result |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for row in result["rows"]:
        b, a = row["before"], row["after"]
        change = lambda key: f"{b[key]} → {a[key]}" if b[key] != a[key] else f"{a[key]}"  # noqa: E731
        lines.append(f"| {row['about']} | {row['cap']} | {change('readable')} (of {a['of']}) | "
                     + (f"{b['key_read']} → {a['key_read']} of {a['key_total']}" if b['key_read'] != a['key_read'] else f"{a['key_read']} of {a['key_total']}")
                     + f" | {change('parts_of_site')} | {change('pending')} | {change('usable')} | {change('requests')} | "
                     f"{b['credits']} → {a['credits']} ({a['max_credits']}) | {change('outcome')} |")
    lines += ["", "## Why pages were not read (after)", "", "| Case | Direct access | Coverage | Not requested because | Requested but not read |", "|---|---|---|---|---|"]
    for row in result["rows"]:
        a = row["after"]
        causes = ", ".join(f"{count} {name.replace('_', ' ')}" for name, count in sorted(a["causes"].items())) or "none"
        lines.append(f"| {row['about']} | {a['direct'].replace('_', ' ')} | {a['level'].replace('_', ' ')} | {(a['why_pending'] or 'nothing was left').replace('_', ' ')} | {causes} |")
    lines += ["", "## Healthy sites: no new findings", "", "| Case | Problems before | Problems after | Notes before | Notes after |", "|---|---|---|---|---|"]
    lines += [f"| {row['about']} | {row['before']['problems']} | {row['after']['problems']} | {row['before']['notes']} | {row['after']['notes']} |"
              for row in result["rows"] if row["healthy"]]
    lines += ["", "## Time and memory (this computer, waits switched off)", "", "| Case | Seconds before | Seconds after | Peak memory before (MB) | Peak memory after (MB) |", "|---|---|---|---|---|"]
    lines += [f"| {row['about']} | {row['before']['seconds']} | {row['after']['seconds']} | {row['before']['peak_mb']} | {row['after']['peak_mb']} |" for row in result["rows"]]
    lines += ["", "## The time kept for the reader", "",
              "A made-up clock, 50 pages, 1 second between requests. The audit keeps `pages × (delay + assumed seconds)` for the reader. "
              "The default assumption is 8 seconds a page (`MAYA_AUDIT_READER_SECONDS_PER_PAGE`, `--reader-seconds-per-page`).", "",
              "| Assumed seconds a page | Reader really takes | Time kept (s) | Pages read before the deadline | Time used (s) |", "|---|---|---|---|---|"]
    lines += [f"| {s['assumed_s_per_page']:g} | {s['answer_s']:g} s | {s['reserve_s']:g} | {s['pages_read']} of {s['of']} | {s['used_s']:g} |" for s in result["time"]]
    before, after = result["slow_site"]
    lines += ["", "On a slow site, where Maya's own crawl and checks need all the time they are given:", "",
              "| | Time Maya's own work may use | Left for the reader | Pages the reader reads |", "|---|---|---|---|",
              f"| Before: one limit for everything | all {before['crawl_takes_s']:g} s | 0 s | {before['pages_read']} of {before['of']} |",
              f"| After: the reader's share is kept | {after['crawl_takes_s']:g} s | {after['reserve_s']:g} s | {after['pages_read']} of {after['of']} |"]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true", help="write docs/COVERAGE-BENCHMARK.md")
    parser.add_argument("--json", action="store_true", help="print the raw figures")
    args = parser.parse_args()
    result = benchmark()
    text = markdown(result)
    print(json.dumps(result, indent=1) if args.json else text)
    if args.write:
        OUT.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {OUT}")
