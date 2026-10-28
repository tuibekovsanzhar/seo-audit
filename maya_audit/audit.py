"""One audit run: crawl, collect ACC/IDX/RND/STR data, then evaluate INT gates and the checks."""

from __future__ import annotations

from dataclasses import dataclass, replace
import time
from urllib.parse import urlsplit

import httpx

from .access_data import check_llms_links, collect_access_data, key_page_urls
from .checks.access import run_access_checks
from .checks.index import run_index_checks
from .index_data import check_sitemap_urls, collect_index_data
from .render import RenderData, collect_render_data
from .checks.render import run_render_checks
from .checks.structure import run_structure_checks
from .checks.answers import run_answer_checks
from .checks.perf import run_perf_checks
from .ans_data import CitationData, collect_ans_data
from .ans_domains import CitationDomains, load_citation_domains
from .perf_data import PerfData, collect_perf_data
from .structure_data import collect_structure_data
from .checks.integrity import run_integrity_gates
from .config import CrawlConfig
from .crawler import Crawler
from .findings import CheckResult
from .models import CrawlResult, GateResult
from .progress import NO_HOOKS, Hooks
from . import other_sites, resolver, timeplan
from .robots import LOCAL_NETWORK_MESSAGE
from .urls import is_loopback_host, normalize_url


@dataclass
class AuditOutcome:
    result: CrawlResult
    gates: list[GateResult]
    checks: list[CheckResult]
    # The audit's own deadline (a monotonic time) and the pace its crawler ended on, for the steps that run after it:
    # a page reader, paid panels, archives. See maya_audit.runclock. Not part of any report.
    deadline_mono: float | None = None
    pace_s: float = 0.0
    started_mono: float | None = None


class NetworkPreflightFailed(Exception):
    """The audit was not started: this computer could not look anything up, or the address does not exist. Nothing
    was requested from the site, nothing was spent, and there are no findings. `status` is "local_network_problem"
    or "host_not_found"."""

    def __init__(self, status: str, message: str, detail: dict):
        super().__init__(message)
        self.status, self.message, self.detail = status, message, detail


def network_preflight(start_url: str) -> dict | None:
    """Look up the target, and failing that one well-known public name, before anything else happens. None for an
    address that needs no lookup (an IP address, a loopback or private name). Raises NetworkPreflightFailed."""
    import ipaddress

    parts = urlsplit(normalize_url(start_url) or start_url)
    host = (parts.hostname or "").rstrip(".").lower()
    if not host or is_loopback_host(host) or resolver.never_public(host):
        return None
    try:
        ipaddress.ip_address(host)
        return None
    except ValueError:
        pass
    found = resolver.preflight(host, parts.port or (443 if parts.scheme == "https" else 80))
    if found["status"] == "local_network_problem":
        raise NetworkPreflightFailed("local_network_problem", LOCAL_NETWORK_MESSAGE, found)
    if found["status"] == "host_not_found":
        raise NetworkPreflightFailed("host_not_found", f"The address {host} does not exist (no DNS record). Check the spelling "
                                     "and try again.", found)
    return found


def _effective_robots_sample_interval(config: CrawlConfig) -> float:
    resamples = max(1, config.robots_samples - 1)
    return max(0.0, min(config.robots_sample_interval_s, config.time_limit_s / (resamples * 4)))


def run_audit(start_url: str, config: CrawlConfig, transport: httpx.BaseTransport | None = None,
              hooks: Hooks | None = None) -> AuditOutcome:
    """`hooks` (maya_audit.progress) lets a job runner follow the audit and ask it to stop. Optional."""
    hooks = hooks or NO_HOOKS
    # Bound the cumulative resampling wait to 25% of the run budget so later
    # rendering/performance checks retain time even on short audits.
    config = replace(config, robots_sample_interval_s=_effective_robots_sample_interval(config))
    # The URL the operator supplied is the crawl boundary. No separate host
    # allowlist entry should be needed for that exact site; extra hosts remain
    # opt-in for redirects and optional cross-origin checks.
    normalized_start = normalize_url(start_url)
    start_host = urlsplit(normalized_start).hostname if normalized_start else None
    if start_host:
        config = replace(config, allowed_live_hosts=config.allowed_live_hosts | frozenset({start_host}))

    # Before anything is requested or spent: can this computer look the site up at all? Only for real network runs;
    # an injected transport (tests, demonstrations) reaches no network. Raises NetworkPreflightFailed.
    preflight = None
    if transport is None:
        resolver.reset()
        preflight = network_preflight(start_url)

    shared: dict[str, float | None] = {"deadline_mono": None, "pace_s": config.request_delay_s}
    started_mono = time.monotonic()

    # Time is divided before anything runs: Maya's own crawl and data collection get the limit less the reader's
    # reserve, so a long crawl cannot leave a page reader with nothing. A stop ends everything at once.
    reserve = max(0.0, min(config.reader_reserve_s, config.time_limit_s * 0.9))
    crawl_config = replace(config, time_limit_s=config.time_limit_s - reserve) if reserve else config

    def post_crawl(fetcher, crawl):
        whole = fetcher.deadline_mono if fetcher.deadline_mono is None or fetcher.stopped else fetcher.deadline_mono + reserve
        shared.update(deadline_mono=whole, pace_s=fetcher.delay_s)

        def out_of_time():
            return fetcher.deadline_mono is not None and time.monotonic() >= fetcher.deadline_mono

        def collect(name, target, function, when_cut=None):
            """Run one data collector. `when_cut` builds a safe stand-in when the time limit stops it before it starts.

            A collector given `when_cut` copes with running out of time itself (it marks what it could not
            request as not checked), so what it did collect is kept. Without `when_cut`, a collector the time
            limit interrupts is dropped whole, because half its answers would read as failures.
            """
            hooks.emit(name, pages_fetched=len(crawl.pages))
            fetcher.begin_step(name)
            fetcher.poll_stop()
            if out_of_time():
                crawl.collector_errors[name] = "overall audit deadline reached before this data collection started"
                setattr(crawl, target, when_cut() if when_cut else None)
                return
            hits_before = fetcher.own_deadline_hits  # the other-site pool's refusals are not this step's
            try:
                value = function()
                # A collector that watches the clock itself stops without a refused request, and says so in its data.
                own_note = str(getattr(value, "reason", None) or getattr(value, "skipped_reason", None) or "")
                if fetcher.own_deadline_hits > hits_before or (when_cut and "deadline" in own_note):
                    crawl.collector_errors[name] = (
                        "overall audit deadline reached during this data collection; " + (
                            "what was collected before it is used, the rest is reported as not checked" if when_cut
                            else "results are incomplete"))
                    setattr(crawl, target, value if when_cut else None)
                else:
                    setattr(crawl, target, value)
            except Exception as exc:  # a collector failure should not erase the crawl evidence
                crawl.collector_errors[name] = f"{type(exc).__name__}: {str(exc)[:300]}"
                setattr(crawl, target, None)

        # The requests to other sites run in a pool beside the steps below (DECISIONS 219 part 2), from a queue built
        # now, in the order those steps asked before; joined after the sitemap check (and, whatever happens, before
        # this function returns).
        pool = other_sites.start(fetcher, crawl, config)
        try:
            steps_after_crawl(fetcher, crawl, collect, pool)
        finally:
            if pool is not None:
                pool.join()
                crawl._other_sites = None  # threads and locks: never kept on the result (a saved snapshot pickles it)
            fetcher.end_step()

    def steps_after_crawl(fetcher, crawl, collect, pool):
        collect("access", "access", lambda: collect_access_data(fetcher, crawl, config))
        collect("index", "index", lambda: collect_index_data(fetcher, crawl, config, key_page_urls(crawl, config)))
        # Before rendering: the structure checks read the pages already fetched and need only a few link checks
        # of their own, while rendering and the performance rounds are slow. On the first real 40-page run the
        # time limit fell during this step, after rendering, and all thirteen structure checks were lost.
        # Run past the deadline too: every request is then refused unsent and recorded as "not checked", which
        # leaves the checks that need no request at all free to run.
        collect("structure", "structure", lambda: collect_structure_data(fetcher, crawl, config),
                when_cut=lambda: collect_structure_data(fetcher, crawl, config))
        collect("render", "render", lambda: collect_render_data(fetcher, crawl, config, key_page_urls(crawl, config)),
                when_cut=lambda: RenderData("raw_html_only", "overall audit deadline reached before rendering started"))
        # Last, so the extra rounds are spaced from the crawl by all the collection above.
        collect("performance", "perf", lambda: collect_perf_data(fetcher, crawl, config),
                when_cut=lambda: PerfData(enabled=config.prf_enabled, egress_region=config.egress_region,
                                          skipped_reason="overall audit deadline reached before the performance rounds"))
        # Last of Maya's own requests: every sitemap URL the crawl did not read, one light request each (IDX-5,
        # DECISIONS 206), and the links of llms.txt that nothing else read (ACC-8, DECISIONS 208). Run past the
        # deadline too, like the structure data: what it could not ask is reported as not checked.
        def sitemap_check():
            try:
                check = check_sitemap_urls(fetcher, crawl, config)
            finally:
                if pool is not None:
                    pool.join()  # the answers from other sites are written into the data now
            fetcher.begin_step("llms_links")  # its own row of the step timing table (DECISIONS 219)
            check_llms_links(fetcher, crawl, config, check)
            return check

        collect("sitemap_check", "_sitemap_check", sitemap_check, when_cut=sitemap_check)
        if crawl.structure is not None and crawl._external is not None:  # llms.txt's links to other sites came last
            crawl.structure.external = crawl._external.summary()
        if crawl.index is not None:
            crawl.index.sitemap_check = crawl._sitemap_check
        if config.citations_file:
            collect("citations", "citations", lambda: collect_ans_data(fetcher, crawl, config))
        else:
            crawl.citations = CitationData()
        # Reads a file only: the cited-domain export names third-party domains, and ANS-4/ANS-5
        # never fetch them. Nothing off-site is requested on the strength of a citation.
        if config.citation_domains_file:
            collect("citation_domains", "citation_domains",
                    lambda: load_citation_domains(config.citation_domains_file, crawl.origin))
        else:
            crawl.citation_domains = CitationDomains()
        # Maya's last step has ended: a robots.txt sample still not due is waited for now, and only now (DECISIONS 219).
        if fetcher.due_waiting:
            fetcher.begin_step("robots_wait")
            fetcher.finish_due()
        fetcher.end_step()

    result = Crawler(crawl_config, transport, hooks=hooks).run(start_url, post_crawl=post_crawl)
    # What the time limit cut, named once (DECISIONS 219).
    result.skipped_for_time = timeplan.skipped_for_time(result)
    hooks.emit("checks", pages_fetched=len(result.pages))
    # INT gates run over the complete request log, including the ACC and IDX requests.
    gates = run_integrity_gates(result, config)
    site_checks: list[CheckResult] = []

    def unavailable(name: str, check_ids: list[str], title: str) -> list[CheckResult]:
        error = result.collector_errors.get(name, "overall audit deadline reached")
        return [CheckResult(check_id, title, "not_assessed",
                            f"Not assessed because the {name} data collector failed: {error}",
                            evidence={"collector_error": error}) for check_id in check_ids]

    if result.access is None:
        site_checks += unavailable("access", [f"ACC-{n}" for n in range(1, 10)], "AI crawler access")
    else:
        site_checks += run_access_checks(result, config)
    if result.index is None:
        site_checks += unavailable("index", [f"IDX-{n}" for n in range(1, 11)], "Crawl and indexability")
    else:
        site_checks += run_index_checks(result, config)
    if result.render is None:
        render_checks = unavailable("render", [f"RND-{n}" for n in range(1, 8)], "JavaScript rendering")
    else:
        render_checks = run_render_checks(result, config)
    site_checks += render_checks
    if result.structure is None:
        site_checks += unavailable("structure", [*(f"STR-{n}" for n in range(1, 24)), "TSEO-1"],
                                   "Page structure and technical SEO")
    else:
        site_checks += run_structure_checks(result, config, render_checks)
    if result.perf is None:
        site_checks += unavailable("performance", [f"PRF-{n}" for n in range(1, 4)], "Performance")
    else:
        site_checks += run_perf_checks(result, config)
    from . import single_page, launch_gate, root_cause
    from .severity import apply as apply_severity
    single_page.settle(site_checks, result)
    root_cause.group(site_checks, result)
    launch_gate.apply(site_checks)
    apply_severity(site_checks, result)
    from .checks.index import broken_link_sources
    broken_link_sources(site_checks, result)  # the pages to edit, after severity so it stays the engine's (DECISIONS 278)
    # The ANS panel copies final site priorities, never raw constructor ceilings.
    # The ANS panel reads the site checks but never changes them (spec §5 ANS).
    if result.citations is None or result.citation_domains is None:
        name = "citations" if result.citations is None else "citation_domains"
        answer_checks = unavailable(name, [f"ANS-{n}" for n in range(1, 6)], "AI answer observations")
    else:
        answer_checks = run_answer_checks(result, config, site_checks)
    hooks.emit("done", pages_fetched=len(result.pages), stopped=result.stopped,
               stop_reason=result.stop_reason.value if result.stop_reason else None)
    launch_gate.apply(answer_checks)
    apply_severity(answer_checks, result)
    from .rules import assign as assign_rules
    assign_rules(site_checks + answer_checks)  # titles settled above may have been reworded (DECISIONS 269)
    from .facts import attach as attach_facts
    attach_facts(site_checks + answer_checks)  # structured evidence for the most frequent rules (DECISIONS 271)
    from .checks.structure import annotate_page_types
    annotate_page_types(site_checks, result)  # each affected page's kind, for the release gate (DECISIONS 278)
    # Last: the most serious findings asked again, recorded beside them, severities untouched (DECISIONS 272).
    from . import verification
    result.verification = verification.run(site_checks + answer_checks, result, config, transport, hooks,
                                           shared["pace_s"])
    if transport is None:
        result.network = {"preflight": {k: v for k, v in (preflight or {"status": "not_needed"}).items() if k != "addresses"},
                          "dns": resolver.summary()["hosts"]}
    return AuditOutcome(result, gates, site_checks + answer_checks, deadline_mono=shared["deadline_mono"],
                        pace_s=float(shared["pace_s"] or 0.0), started_mono=started_mono)
