"""How the audit's time is shared once the pages are read, and the step timing table (DECISIONS 219).

Page reading is never cut to make room for the checks (`CrawlConfig.crawl_time_share` is 1.0). When time runs short,
the later steps lose their optional requests instead, in this order: links to other sites first, then the links of
llms.txt, the sitemap check, the performance rounds and, last, rendering. The steps already run in that order of
importance except the links to other sites, which the structure step asks before rendering: those are asked only while
the time left is more than the steps after them are estimated to need (`short_of_time`). With adaptive pacing on
(DECISIONS 219 part 2) they run in a pool beside the other steps instead and are cut only by the time limit itself
(maya_audit.other_sites); `short_of_time` then holds back only what is still asked in turn. What the time limit cut is
named once, in `skipped_for_time`, and the report says it in one sentence.

The step timing table (`crawl.steps`) is measured by the fetcher (`Fetcher.begin_step`); the report adds the Firecrawl
page reader's row (`step_rows`).
"""

from __future__ import annotations

from typing import Any
from . import clock as _clock

# The engine's speed mark (DECISIONS 311 (6)): stored on each web audit when it starts. Only finished runs with the
# current mark set the time the web app shows. Raise it when a change makes audits notably faster or slower (DECISIONS
# 294-296, 299 were such changes); runs with an older mark then stop counting, and the mode's default is shown until
# three new runs have finished.
SPEED_VERSION = 1

# The optional steps, in the order they give way to the time limit (the first is lost first).
SKIP_ORDER = ("other_site_links", "llms_links", "sitemap_check", "performance", "rendering")
SKIP_LABELS = {"other_site_links": "links to other sites", "llms_links": "llms.txt links", "sitemap_check": "the sitemap check",
               "performance": "performance rounds", "rendering": "rendering"}
SKIPPED_NOTE = ("Skipped because the time limit was reached: {steps}. Run again with Fast check off or a larger time "
                "limit.")
# The step timing table: the steps' names, as the Markdown report shows them (the web app has them in both languages).
STEP_LABELS = {"sitemap": "robots.txt and sitemaps", "crawl": "Reading pages", "access": "AI crawler access",
               "index": "Indexing checks", "structure": "Page structure and links", "render": "Rendering",
               "performance": "Performance rounds", "sitemap_check": "Sitemap check", "llms_links": "llms.txt links",
               "citations": "Citation data", "citation_domains": "Cited domains",
               "robots_wait": "Waiting for the last robots.txt sample", "page_reader": "Firecrawl page reader",
               # The other-site pool's own row, and the wait for it at the join (DECISIONS 219 part 2).
               "other_sites": "Links to other sites (in parallel)", "other_sites_wait": "Waiting for the links to other sites"}
STEPS_TITLE = "Step timing"
STEPS_COLUMNS = ("Step", "Time", "Requests", "Of which waiting")
# A rendered page, in seconds: the figure `config.estimated_duration_s` uses.
RENDER_PAGE_S = 8.0
# A light request's own time when none has been measured yet, in seconds (beside the gap between requests).
DEFAULT_REQUEST_S = 0.3


def pace_s(fetcher) -> float:
    """What one more request is likely to cost: the gap between requests plus the mean time of the last 50 answers."""
    paced = [r.elapsed_ms for r in fetcher.log[-50:] if r.purpose != "render_subresource" and r.elapsed_ms]
    own = (sum(paced) / len(paced) / 1000) if paced else DEFAULT_REQUEST_S
    return max(0.0, fetcher.delay_s) + own


def later_need_s(fetcher, result, cfg) -> float:
    """Seconds the steps still to come after the structure step are estimated to need: rendering, the performance
    rounds, the sitemap check and the llms.txt links. Upper estimates; nothing is counted for a step that ran."""
    pace = pace_s(fetcher)
    readable = sum(1 for p in result.pages if getattr(p, "analysis", None) is not None)
    need = 0.0
    if cfg.render_enabled and getattr(result, "render", None) is None:
        need += min(cfg.render_budget, readable) * RENDER_PAGE_S
    if cfg.prf_enabled and getattr(result, "perf", None) is None:
        need += max(0, cfg.prf_extra_rounds) * (cfg.prf_round_gap_s + min(cfg.prf_max_urls, readable) * pace)
    if getattr(result, "_sitemap_check", None) is None and not cfg.single_page:
        read = {p.url for p in result.pages}
        unread = sum(1 for url in result.sitemap_urls if url not in read)
        need += min(max(0, cfg.sitemap_check_max), unread) * pace
        llms = sum(len(entry.get("_links") or []) for entry in (getattr(getattr(result, "access", None), "llms", None) or []))
        need += min(max(0, cfg.llms_link_checks_max), llms) * pace
    return need


def short_of_time(fetcher, result, cfg) -> bool:
    """Whether a link to another site should give way: the time left is no more than the later steps need."""
    if fetcher.deadline_mono is None:
        return False
    return fetcher.deadline_mono - _clock.monotonic() <= later_need_s(fetcher, result, cfg)


def _cut(result, name: str) -> bool:
    return "deadline" in str((getattr(result, "collector_errors", None) or {}).get(name) or "")


def skipped_for_time(result) -> list[str]:
    """The optional steps that lost requests to the time limit, in SKIP_ORDER. Empty for a stopped audit."""
    if getattr(result, "stopped", False):
        return []
    config = getattr(result, "config", None) or {}
    found: set[str] = set()
    external = getattr(result, "_external", None)
    if external is not None and external.not_asked.get("time_limit"):
        found.add("other_site_links")
    for entry in getattr(getattr(result, "access", None), "llms", None) or []:
        held = (entry.get("links") or {}).get("not_checked") or {}
        if held.get("time_limit") or held.get("external_time_limit"):
            found.add("llms_links")
    check = getattr(result, "_sitemap_check", None)
    if config.get("sitemap_check_max", 1) and not config.get("single_page") and (
            (check is not None and (check.not_checked or {}).get("time_limit")) or _cut(result, "sitemap_check")):
        found.add("sitemap_check")
    perf = getattr(result, "perf", None)
    if config.get("prf_enabled", True) and (_cut(result, "performance")
                                            or "deadline" in str(getattr(perf, "skipped_reason", None) or "")):
        found.add("performance")
    render = getattr(result, "render", None)
    if config.get("render_enabled", True) and (_cut(result, "render")
                                               or "deadline" in str(getattr(render, "reason", None) or "")):
        found.add("rendering")
    return [name for name in SKIP_ORDER if name in found]


def skipped_note(keys: list[str] | None) -> str | None:
    """The one sentence that names what the time limit cut, or None."""
    names = [SKIP_LABELS[key] for key in keys or [] if key in SKIP_LABELS]
    return SKIPPED_NOTE.format(steps=", ".join(names)) if names else None


def reader_row(firecrawl: dict | None) -> dict[str, Any] | None:
    """The Firecrawl page reader's row of the step timing table, when it read pages for this audit."""
    if not firecrawl or not firecrawl.get("used"):
        return None
    coverage = firecrawl.get("coverage") or {}
    seconds = coverage.get("elapsed_s")
    if seconds is None:
        return None
    requests = firecrawl.get("requests_sent")
    if requests is None:
        requests = coverage.get("page_requests")
    return {"step": "page_reader", "started_at": None, "seconds": round(float(seconds), 1),
            "requests": int(requests or 0), "waiting_s": None}


def step_rows(steps: list[dict] | None, firecrawl: dict | None = None) -> list[dict[str, Any]]:
    """The rows of the step timing table: Maya's own steps, then the page reader's when it ran."""
    rows = [dict(row) for row in steps or [] if row.get("step") != "page_reader"]
    extra = reader_row(firecrawl)
    return rows + ([extra] if extra else [])


def seconds_text(value: Any) -> str:
    """A step's time as the table shows it: "12.5 s", "4 min 10 s", "—" when not measured."""
    if value is None:
        return "—"
    value = float(value)
    if value < 60:
        return f"{value:.1f} s"
    minutes, seconds = divmod(int(round(value)), 60)
    return f"{minutes} min {seconds} s"


def markdown_lines(steps: list[dict] | None, firecrawl: dict | None = None) -> list[str]:
    """The Markdown appendix: one table, "Step | Time | Requests | Of which waiting"."""
    rows = step_rows(steps, firecrawl)
    if not rows:
        return []
    lines = [f"## {STEPS_TITLE}", "", "| " + " | ".join(STEPS_COLUMNS) + " |", "|---|---|---|---|"]
    for row in rows:
        lines.append(f"| {STEP_LABELS.get(row['step'], row['step'])} | {seconds_text(row.get('seconds'))} | "
                     f"{row.get('requests') if row.get('requests') is not None else '—'} | {seconds_text(row.get('waiting_s'))} |")
    return lines + [""]
