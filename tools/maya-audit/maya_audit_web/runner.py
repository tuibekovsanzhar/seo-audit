"""The worker: runs queued audits one at a time, outside any request, and records what happens.

The audit itself is `maya_audit.audit.run_audit`, called with the settings the command line would build
for the same request. This module is the adapter around it: a durable queue (the audits table), progress
events derived from the engine's own hooks, a cooperative stop, a resume from the saved crawl, and the
files the results page and the downloads read.

One audit runs at a time. A lock file in the data folder keeps a second copy of the app from starting a
second worker over the same queue.
"""

from __future__ import annotations

import inspect
import json
import logging
import os
import shutil
import threading
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable

import httpx

from maya_audit import allowlist, archives, cli, crux, evidence_store, filelock, ownership
from maya_audit import brand as brand_module
from maya_audit.access_data import homepage_url
from maya_audit.audit import NetworkPreflightFailed, run_audit
from maya_audit.botinfo import BotInfoPageNotReady
from maya_audit.config import CrawlConfig, estimated_duration_s, external_link_cap
from maya_audit.crawler import ConcurrentCrawlError, HostNotAllowed
from maya_audit.dataforseo import insights, panel
from maya_audit.firecrawl import panel as firecrawl_panel
from maya_audit.firecrawl import reader as firecrawl_reader
from maya_audit.progress import Hooks
from maya_audit import final
from maya_audit.report import duration_line, render_markdown, run_outcome, timing
from maya_audit.keepawake import KeepAwake
from maya_audit.runclock import for_outcome
from maya_audit.scratchpad import Scratchpad

from . import fc, paid, snapshot
from .store import ACTIVE, RESUMABLE, Store, now
from .strings import set_language, t

# The server's own record of what went wrong (D-13): app.create_app sends it to a rotating file under the web home.
log = logging.getLogger("maya_audit_web")

# "single": one address is read and checked, nothing is followed (maya_audit.single_page).
MODES = {"single": 1, "quick": 50, "standard": 500}
SINGLE = "single"
MAX_KEY_PAGES = 20
MAX_QUEUED = 5
REPORT_JSON, REPORT_MD, BACKLINKS_JSON, AFFECTED_JSON, CRAWL_DB = (
    "report.json", "report.md", "dataforseo.json", "affected-urls.json", "crawl.db")
# The steps a person sees, in the order they are listed. The engine's own phases map onto them; it runs its
# data collection before and after rendering, so "checks" can be active on both sides of "rendering".
STEPS = ("access", "sitemap", "crawling", "rendering", "checks", "backlinks", "report")
PHASE_STEP = {"starting": "access", "sitemap": "sitemap", "crawl": "crawling", "render": "rendering", "access": "checks",
              "index": "checks", "structure": "checks", "performance": "checks", "sitemap_check": "checks", "citations": "checks",
              "citation_domains": "checks", "checks": "checks", "firecrawl": "checks", "backlinks": "backlinks", "report": "report"}
PROGRESS_EVERY_S = 0.25
MAX_URL_CHARS = 300


class WorkerAlreadyRunning(RuntimeError):
    """Another copy of the app holds this data folder's worker lock."""


@dataclass
class Engine:
    """How this app runs audits. The defaults are the real thing; tests and demo mode replace the transports."""
    paid: paid.PaidServices = field(default_factory=paid.PaidServices.real)
    firecrawl: fc.FirecrawlServices = field(default_factory=fc.FirecrawlServices.real)
    # Called once per audit run. None, or a factory returning None, means the real network.
    transport_factory: Callable[[], httpx.BaseTransport | None] | None = None
    # Test-only permission: loopback targets (the local fake sites). Never set by the real launcher.
    allow_loopback: bool = False
    # CrawlConfig fields laid over what the command line would choose (demo mode and tests only).
    overrides: dict[str, Any] = field(default_factory=dict)
    # More fields for one site, by its address (demo mode gives its shop made-up citation data).
    overrides_for: Callable[[str], dict[str, Any]] | None = None
    # Core Web Vitals (Google's Chrome UX Report): the key, and a transport for tests and demo mode.
    crux_key: Callable[[], str | None] = crux.load_key
    crux_transport: httpx.BaseTransport | None = None
    # The web archives (Wayback Machine, Common Crawl): a transport for tests and demo mode. None is the real network.
    archives_transport: httpx.BaseTransport | None = None
    demo: bool = False


def crawl_config(engine: Engine, audit: dict[str, Any], db_path: Path, *, resume: bool, pages_already: int = 0) -> CrawlConfig:
    """The settings for one run: exactly what `maya-audit crawl` builds for the same arguments."""
    cap = MODES[audit["mode"]]
    argv = ["crawl", audit["url"], "--max-pages", str(cap), "--db-path", str(db_path)]
    if audit["mode"] == SINGLE:
        argv.append("--single-page")  # the address given and nothing else: important pages are not added
    for page in ([] if audit["mode"] == SINGLE else audit["key_pages"]):
        argv += ["--key-page", page]
    if resume:
        argv.append("--resume")
    # Other domains of the same brand, from the plan: validated when the plan was made, and again by the command line.
    for domain in audit.get("brand_family_domains") or []:
        argv += ["--brand-family-domain", domain]
    # The plan's two switches (DECISIONS 219): Fast check, and whether links to other sites are checked.
    switches = audit.get("switches") or {}
    if switches.get("fast_check"):
        argv.append("--fast")
    if switches.get("external_links") is False:
        argv.append("--no-external-links")
    verification = audit.get("verification") or {}
    if verification.get("requested") and verification.get("token"):
        # The owner's token, as a meta tag on the homepage or a DNS TXT record: either lets ACC-4 run.
        argv += ["--site-verification-token", verification["token"], "--verify-dns"]
    # The business type (DECISIONS 311): "auto" unless the plan named one.
    business = audit.get("business_type") or ((audit.get("document") or {}).get("business_type") or {}).get("chosen")
    if business and business != "auto":
        argv += ["--business-type", business]
    if not engine.allow_loopback:
        argv.append("--block-loopback")
    extra = engine.overrides_for(audit["url"]) if engine.overrides_for else {}
    args = cli._parser().parse_args(argv)
    # One time limit for the whole audit: when Firecrawl will read the pages too, the limit has room for that.
    reader = audit.get("firecrawl") or (audit.get("document") or {}).get("firecrawl") or {}
    args.reader_planned = bool(reader.get("requested") or reader.get("state") not in (None, "", "none"))
    config = replace(cli._crawl_config(args), **{**engine.overrides, **extra})
    if resume:
        # The engine's page cap is per session; the mode's cap is for the whole audit.
        config = replace(config, max_pages=max(0, cap - pages_already))
    return config


def plan_shape(engine: Engine, mode: str, key_pages: list[str], switches: dict[str, Any] | None = None) -> dict[str, Any]:
    """What a plan can say before anything runs: the page cap, the hard time limit, a rough upper duration. `switches`
    are the plan's Fast check and other-site links (DECISIONS 219): the estimate takes the caps they give."""
    config = crawl_config(engine, {"url": "https://example.invalid/", "mode": mode, "key_pages": key_pages,
                                   "switches": switches or {}}, Path("unused.db"), resume=False)
    # Requests to other sites (DECISIONS 211): none in demo mode, where they are off.
    cap = external_link_cap(config.external_link_checks_max, config.external_link_checks_base, config.max_pages,
                            config.single_page)
    external = cap if config.check_external_links else 0
    estimate = estimated_duration_s(config.max_pages, len(key_pages), config.request_delay_s, config.render_enabled,
                                    config.render_budget, config.prf_enabled, config.sitemap_check_max, external)
    return {"page_cap": config.max_pages, "time_limit_minutes": max(1, round(config.time_limit_s / 60)),
            "up_to_minutes": max(1, round(estimate / 60)), "rendering_enabled": config.render_enabled,
            "render_budget": config.render_budget if config.render_enabled else 0,
            "request_delay_s": config.request_delay_s, "fast_check": config.fast_check,
            "external_links": config.check_external_links, "external_cap": cap}


def pages_saved(db_path: Path) -> int:
    """Pages (not redirect hops) already in a saved crawl: what the mode's page cap has left to cover."""
    if not db_path.is_file():
        return 0
    with Scratchpad.read_only(str(db_path)) as pad:
        return sum(1 for page in pad.saved_pages() if not (page.get("status") is not None and 300 <= page["status"] < 400))


def write_file(path: Path, text: str) -> None:
    """Write beside the target, then swap it in: a reader never sees half a file, and a crash leaves the old one."""
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


class Runner:
    def __init__(self, store: Store, engine: Engine) -> None:
        self.store = store
        self.engine = engine
        self._closing = threading.Event()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._current: str | None = None
        self._lock_file = open(store.folder / "worker.lock", "a+")
        try:
            filelock.lock(self._lock_file, blocking=False)
        except OSError:
            self._lock_file.close()
            raise WorkerAlreadyRunning("another Maya Audit app is already running on this data folder") from None
        self.recovered = self._recover()
        self._thread = threading.Thread(target=self._loop, name="maya-audit-worker", daemon=True)
        self._thread.start()

    # -- folders ---------------------------------------------------------------------------------

    def state_folder(self, audit_id: str) -> Path:
        return self.store.audit_folder(audit_id) / "state"

    def artifacts(self, audit_id: str) -> Path:
        return self.store.audit_folder(audit_id) / "artifacts"

    # -- control ---------------------------------------------------------------------------------

    def _recover(self) -> int:
        """At start-up, every unfinished audit belonged to a process that is gone. None is restarted by itself."""
        rows = self.store.unfinished()
        for audit in rows:
            self.store.update_audit(audit["id"], state="interrupted", finished_at=now())
            self.emit(audit["id"], "state", {"state": "interrupted"})
        return len(rows)

    def submit(self) -> None:
        self._wake.set()

    def stop(self, audit_id: str) -> str | None:
        """Ask for a stop. Returns the new state, or None when the audit is not queued or running."""
        if self.store.move_audit(audit_id, ("queued",), "stopped"):
            self.store.update_audit(audit_id, finished_at=now())
            self.emit(audit_id, "state", {"state": "stopped", "note": t("job.stopped.before_start")})
            return "stopped"
        if self.store.move_audit(audit_id, ("running",), "stopping"):
            if self._current == audit_id:
                self._stop.set()
            self.emit(audit_id, "state", {"state": "stopping"})
            self.emit(audit_id, "log", {"message": t("log.stop_requested")})
            return "stopping"
        return None

    def resume(self, audit_id: str, approved_usd: float, *, also_finished: bool = False) -> bool:
        """Queue a stopped or interrupted audit again. `also_finished` is for the one case where a finished audit runs
        its last steps again: the person's decision on zero data retention."""
        if not self.store.move_audit(audit_id, (*RESUMABLE, "finished") if also_finished else RESUMABLE, "queued"):
            return False
        self.store.update_audit(audit_id, approved_usd=approved_usd, finished_at=None)
        self.store.requeue(audit_id)
        self.emit(audit_id, "state", {"state": "queued", "resumed": True})
        self.submit()
        return True

    def wait(self, audit_id: str, timeout: float = 60.0) -> dict[str, Any]:
        """Block until the audit is no longer queued or running (tests and scripts)."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            audit = self.store.audit(audit_id)
            if audit is None or audit["state"] not in ACTIVE:
                return audit
            time.sleep(0.02)
        return self.store.audit(audit_id)

    def shutdown(self, timeout: float = 30.0) -> None:
        """Stop the running audit politely (it becomes resumable), end the worker, release the folder."""
        self._closing.set()
        self._stop.set()
        self._wake.set()
        self._thread.join(timeout)
        try:
            filelock.unlock(self._lock_file)
            self._lock_file.close()
        except (OSError, ValueError):
            pass

    @property
    def closing(self) -> bool:
        return self._closing.is_set()

    # -- events ----------------------------------------------------------------------------------

    def emit(self, audit_id: str, type_: str, data: dict[str, Any]) -> None:
        try:
            self.store.add_event(audit_id, type_, data)
        except Exception:  # noqa: BLE001  losing a progress line must never lose the audit
            pass

    # -- the loop --------------------------------------------------------------------------------

    def _loop(self) -> None:
        while not self._closing.is_set():
            audit = self.store.next_queued()
            if audit is None:
                self._wake.wait(0.5)
                self._wake.clear()
                continue
            stop = self._stop = threading.Event()
            self._current = audit["id"]
            try:
                set_language(audit.get("language"))  # the worker writes its lines in the language the audit was started in
                if self.store.move_audit(audit["id"], ("queued",), "running"):
                    if self._closing.is_set():
                        stop.set()
                    with KeepAwake():  # a Mac stays awake while the audit runs (DECISIONS 295)
                        self._audit(self.store.audit(audit["id"]), stop)
            except Exception as exc:  # noqa: BLE001  a job must always end in a state the page can show
                # The person sees the class name only (an exception's text can hold a file path or a fragment of a
                # page); the whole traceback goes to the server log, the only place it can be read from later.
                self._fail(audit["id"], "internal_error", t("job.failed.internal", kind=type(exc).__name__))
                # Terminal state must survive a slow or unavailable diagnostic sink.
                try:
                    log.exception("audit %s failed", audit["id"])
                except Exception:  # noqa: BLE001  logging must not kill the job worker
                    pass
            finally:
                self._current = None

    def _fail(self, audit_id: str, code: str, message: str) -> None:
        self.store.update_audit(audit_id, state="failed", error_code=code, outcome_reason=message, finished_at=now())
        self.emit(audit_id, "done", {"state": "failed", "error_code": code, "message": message})

    def _audit(self, audit: dict[str, Any], stop: threading.Event) -> None:
        store, engine, audit_id = self.store, self.engine, audit["id"]
        state_dir, out_dir = self.state_folder(audit_id), self.artifacts(audit_id)
        for folder in (state_dir, out_dir):
            folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        db_path = state_dir / CRAWL_DB
        # Resume only what exists: an audit interrupted before its first request starts from the beginning.
        resume = audit["sessions"] > 0 and db_path.is_file()
        if not resume and db_path.exists():
            db_path.unlink()
        already = pages_saved(db_path) if resume else 0
        planned = (store.plan(audit["plan_id"]) or {}).get("document") or {}
        audit = {**audit, "verification": planned.get("ownership"), "brand_family_domains": planned.get("brand_family_domains") or [],
                 "switches": planned.get("switches") or {},
                 "business_type": (planned.get("business_type") or {}).get("chosen") or "auto"}
        config = crawl_config(engine, audit, db_path, resume=resume, pages_already=already)
        cap = MODES[audit["mode"]]
        progress: dict[str, Any] = {"phase": "starting", "step": "access", "steps_seen": ["access"], "page_cap": cap,
                                    "pages_checked": already, "session_pages_start": already, "other_fetches": 0,
                                    "requests_sent": 0, "at": now(), "elapsed_s": 0.0}
        session = audit["sessions"] + 1
        store.update_audit(audit_id, started_at=audit["started_at"] or now(), sessions=session, progress=progress,
                           outcome=None, outcome_reason=None, error_code=None)
        self.emit(audit_id, "state", {"state": "running", "session": session, "resumed": resume})
        self.emit(audit_id, "step", {"step": "access", "phase": "starting"})
        last_write = [0.0]

        def enter(phase: str) -> None:
            step = PHASE_STEP.get(phase, "checks")
            changed = step != progress.get("step")
            progress.update(phase=phase, step=step, at=now())
            if step not in progress["steps_seen"]:
                progress["steps_seen"].append(step)
            if changed:
                self.emit(audit_id, "step", {"step": step, "phase": phase})
            self.emit(audit_id, "log", {"message": t(f"phase.{phase}")})
            store.update_audit(audit_id, progress=progress)

        def on_progress(event: dict[str, Any]) -> None:
            phase = event.get("phase")
            if phase == "done":
                return
            if event.get("business_suggestion"):
                # DECISIONS 311: the business type the homepage suggests, shown in the progress box at once.
                progress["business_suggestion"] = event["business_suggestion"]
                store.update_audit(audit_id, progress=progress)
                self.emit(audit_id, "business", {"business_suggestion": event["business_suggestion"]})
                return
            progress["elapsed_s"] = event.get("elapsed_s", progress["elapsed_s"])
            if phase != progress.get("phase"):
                if phase == "crawl":
                    progress["crawl_started_s"] = progress["elapsed_s"]
                enter(phase)
            if phase != "crawl":
                return
            progress.update(pages_checked=event.get("pages_fetched", progress["pages_checked"]),
                            other_fetches=event.get("other_fetches", 0), requests_sent=event.get("requests_sent", 0),
                            discovered=event.get("pages_discovered"), url=(event.get("url") or "")[:MAX_URL_CHARS] or None,
                            maya_gap_s=event.get("delay_s", progress.get("maya_gap_s")), at=now())
            if time.monotonic() - last_write[0] >= PROGRESS_EVERY_S:
                last_write[0] = time.monotonic()
                store.update_audit(audit_id, progress=progress)
                self.emit(audit_id, "progress", {k: progress.get(k) for k in (
                    "pages_checked", "page_cap", "other_fetches", "requests_sent", "discovered", "url", "elapsed_s")})

        # A finished audit that is only being read through Firecrawl now: its own result was kept, so the website is
        # asked for nothing again. Without a kept result (an audit from an earlier version) the last steps run again.
        use = audit.get("firecrawl") or {}
        kept = snapshot.load(state_dir) if use.get("continue") else None
        if kept is not None:
            store.update_audit(audit_id, sessions=audit["sessions"], progress={**audit["progress"], "continuing": True, "at": now()})
            progress.update({**audit["progress"], "continuing": True})
            # The kept result's deadline belongs to the run that made it. This step gets its own, of the same length.
            kept[0].deadline_mono = time.monotonic() + kept[1].time_limit_s
            kept[0].started_mono, kept[0].started_wall = time.monotonic(), time.time()
            return self._finish(audit, kept[0], kept[1], stop=stop, enter=enter, progress=progress, out_dir=out_dir)
        if use.get("continue"):
            self.emit(audit_id, "log", {"message": t("log.firecrawl.no_snapshot")})
        # Firecrawl starts the moment Maya's crawl ends, beside Maya's own later steps, when it would read the same pages
        # anyway (DECISIONS 294).
        early = self._early_reader(audit, stop, progress)
        transport = engine.transport_factory() if engine.transport_factory else None
        try:
            outcome = run_audit(audit["url"], config, transport, Hooks(on_progress=on_progress, should_stop=stop.is_set),
                                reader=early)
            fallback = self._http_fallback(audit, outcome, resume)
            if fallback and not stop.is_set():
                # https:// did not answer at all. The address was typed without https://, so http:// is tried once.
                self.emit(audit_id, "log", {"message": t("log.http_fallback", url=fallback)})
                progress.update(address_note=t("job.http_fallback", https=audit["url"], http=fallback))
                store.update_audit(audit_id, url=fallback, progress=progress)
                audit = store.audit(audit_id)
                db_path.unlink(missing_ok=True)
                config = crawl_config(engine, audit, db_path, resume=False)
                transport = engine.transport_factory() if engine.transport_factory else None
                outcome = run_audit(audit["url"], config, transport, Hooks(on_progress=on_progress, should_stop=stop.is_set),
                                    reader=early if early is not None and not early.started else None)
        except ConcurrentCrawlError:
            self._close_early(early)
            return self._fail(audit_id, "site_busy", t("job.busy"))
        except NetworkPreflightFailed as exc:
            # Before anything was requested or spent: this computer could not look anything up, or the address does not
            # exist. The audit has no report and no findings.
            self._close_early(early)
            host = (exc.detail or {}).get("host") or ""
            return self._fail(audit_id, exc.status, t("job.failed.network") if exc.status == "local_network_problem"
                              else t("job.failed.no_such_host", host=host))
        except HostNotAllowed as exc:
            self._close_early(early)
            return self._fail(audit_id, "host_not_allowed", str(exc)[:300])
        except BotInfoPageNotReady as exc:
            self._close_early(early)
            return self._fail(audit_id, "bot_info_page", str(exc)[:300])
        except ValueError as exc:  # the engine's own refusals: a resume that does not match the saved crawl
            self._close_early(early)
            return self._fail(audit_id, "resume_mismatch" if resume else "invalid_settings", str(exc)[:300])

        # Kept before Firecrawl touches anything: what Maya's own crawl found, for a later decision about a blocked site.
        if not outcome.result.stopped and firecrawl_reader.crawl_was_blocked(outcome.result, config)[0]:
            snapshot.save(state_dir, outcome, config)
        else:
            snapshot.remove(state_dir)
        return self._finish(audit, outcome, config, stop=stop, enter=enter, progress=progress, out_dir=out_dir, early=early)

    def _reading(self, audit_id: str, progress: dict[str, Any]) -> Callable[[dict[str, Any]], None]:
        """Firecrawl's progress, for the progress box: pages read by Firecrawl beside Maya's own (DECISIONS 294), and its
        own pace (requests at once, gap between starts; DECISIONS 295)."""
        def reading(event: dict[str, Any]) -> None:
            progress.update(firecrawl={k: event.get(k) for k in ("attempted", "read", "failed", "from_cache", "page_cap",
                                                                  "in_flight", "seconds_per_page", "at_once", "gap_s")},
                            firecrawl_at=now(), at=now())
            self.store.update_audit(audit_id, progress=progress)
            self.emit(audit_id, "progress", {"step": "firecrawl", **progress["firecrawl"], "url": event.get("url")})
        return reading

    def _early_reader(self, audit: dict[str, Any], stop: threading.Event, progress: dict[str, Any]):
        """An EarlyReading for this audit, or None: only Firecrawl's first, approved run (as the main page reader, which
        starts when Maya's crawl ends, DECISIONS 294, or at Maya's first 429, 299; or as the reader of a blocked site,
        which starts at the first 429), and only without a paid panel whose ranking pages it would wait for. Nothing is
        sent or marked until it starts."""
        state = audit.get("firecrawl") or {}
        if state.get("state") != "pending" or state.get("continue") or audit.get("backlinks"):
            return None
        options = fc.options_from(state.get("options") or {})
        if not (options.read_always or options.read_blocked):
            return None

        def mark() -> None:  # marked before the first request: a resume must not spend the approval twice
            self.store.update_audit(audit["id"], firecrawl={**state, "state": "attempted"})

        client = fc.open_client(self.engine.firecrawl, options, approved_credits=float(state.get("approved_credits") or 0),
                                audit_id=audit["id"][:12], should_stop=stop.is_set)
        return firecrawl_reader.EarlyReading(client, options, progress=self._reading(audit["id"], progress), on_start=mark)

    @staticmethod
    def _close_early(early) -> None:
        if early is not None:
            early.client.close()

    def _finish(self, audit: dict[str, Any], outcome: Any, config: CrawlConfig, *, stop: threading.Event,
                enter: Callable[[str], None], progress: dict[str, Any], out_dir: Path, early=None) -> None:
        """Everything after Maya's own crawl and checks: Firecrawl when asked for, the paid figures, the report files."""
        store, audit_id = self.store, audit["id"]
        result = outcome.result
        # After Maya's own crawl, which stays the access test, and before anything is judged or written.
        # One deadline, one stop request and one pace for every step that follows (maya_audit.runclock).
        clock = for_outcome(outcome, stop.is_set)
        reading = self._reading(audit_id, progress)

        # The already-approved search sample chooses reader coverage, not site judgments.
        # Same calls, credits, deadline and resume ledger; no supplementary reader phase.
        business = ((store.plan(audit["plan_id"]) or {}).get("document") or {}).get("business") or {}
        native_brand = brand_module.resolve(result, business.get("brand_name") if business.get("brand_confirmed") else None)
        dfs_panel = self._backlinks(audit, out_dir, stopped=result.stopped, stop=stop, enter=enter,
            pages=result.pages, clock=clock, home=homepage_url(result), brand=native_brand)
        reader_cap = ((audit.get("firecrawl") or {}).get("options") or {}).get("max_pages", config.max_pages)
        ranking_urls = insights.ranking_landing_pages(dfs_panel, result.origin, min(reader_cap, config.max_pages))
        firecrawl_section, firecrawl_pages = self._firecrawl(store.audit(audit_id), outcome, config, stop=stop, enter=enter,
                                                             clock=clock, reading=reading, ranking_urls=ranking_urls, early=early)
        # The stored sentence counts the checks that could not run (H18), when the engine's run_outcome takes them (W4a).
        counted = {"checks": outcome.checks} if "checks" in inspect.signature(run_outcome).parameters else {}
        _code, label, sentence = run_outcome(result, outcome.gates, firecrawl_section, **counted)
        # The brand: the name typed or saved for this site, else the site's own name, else the address in the site's words.
        business = ((store.plan(audit["plan_id"]) or {}).get("document") or {}).get("business") or {}
        audit_brand = brand_module.resolve(result, business.get("brand_name") if business.get("brand_confirmed") else None,
                                           firecrawl_pages or None)
        # One sealed result: the report, its gate and its full address lists, as the CLI builds it (DECISIONS 280).
        sealed = final.seal(outcome, firecrawl=firecrawl_section, brand=audit_brand)
        report = sealed.report
        markdown = render_markdown(result, outcome.gates, outcome.checks, firecrawl=firecrawl_section)
        markdown += final.cards_markdown(report)

        evidence_folder = out_dir / "evidence"
        shutil.rmtree(evidence_folder, ignore_errors=True)  # a resumed audit saves its evidence afresh
        index = evidence_store.save_evidence(result, config, evidence_folder, "all")
        report["evidence_saved"] = {key: index[key] for key in ("mode", "total_bytes", "limits")} | {
            # The folder's name, not its place on this computer: the report may be downloaded and passed on.
            "folder": "evidence", "pages": len(index["pages"]), "not_saved": len(index["not_saved"])}
        # The crawl database's place on this computer stays out of a file that may be passed on.
        settings = report["crawl"]["config"]
        settings["db_path"] = CRAWL_DB
        for key in ("citations_file", "citation_domains_file", "ca_bundle"):
            if settings.get(key):
                settings[key] = Path(str(settings[key])).name

        if firecrawl_section is not None:
            report["firecrawl"] = firecrawl_section
            markdown += firecrawl_panel.render_markdown(firecrawl_section)
            if firecrawl_pages:  # what Firecrawl read, kept apart from the evidence of Maya's own crawl
                folder = out_dir / "evidence-firecrawl"
                shutil.rmtree(folder, ignore_errors=True)
                evidence_store.save_evidence(replace(result, pages=firecrawl_pages), config, folder, "all")
        document = (store.plan(audit["plan_id"]) or {}).get("document") or {}
        # Archived copies: asked for on the plan, and used only when neither Maya's crawler nor Firecrawl read the site.
        if (document.get("archives") and not result.stopped and firecrawl_reader.crawl_was_blocked(result, config)[0]
                and not (firecrawl_section or {}).get("used")):
            archived = archives.collect(result, config, wayback=True, common_crawl=True, transport=self.engine.archives_transport,
                                        should_stop=stop.is_set, clock=clock)
            report["archives"] = archived
            markdown += archives.markdown(archived)
        verification = document.get("ownership") or {}
        if verification.get("requested") and getattr(result, "access", None) is not None:
            report["ownership"] = ownership.section(result.access.ownership, verification["domain"], verification["token"], now())
            markdown += "\n".join(["", "## Site ownership", "", report["ownership"]["summary"], "",
                                   *(f"- {line}" for line in report["ownership"]["instructions"]), ""])
        if firecrawl_reader.crawl_was_blocked(result, config)[0] and not (firecrawl_section or {}).get("used"):
            # Nothing could read the site: the steps its owner can take, to copy and hand over.
            from maya_audit.classify import describe_blockers, identify_blocker

            named = describe_blockers([b for b in (identify_blocker(p.status, p.headers, p.classification_evidence, p.fetch_class.value)
                                                   for p in result.pages) if b])
            markdown += allowlist.markdown(config.product_token, result.user_agent, named[0]["name"] if named else None)
        if not result.stopped and self.engine.crux_key():  # free; one request to Google about the site's origin
            report["crux"] = crux.collect(audit["url"], self.engine.crux_key(), transport=self.engine.crux_transport, clock=clock)
            markdown += crux.markdown(report["crux"])
        if dfs_panel is not None:
            insights.refresh_relevance(dfs_panel)
            options = document.get("paid_options")
            self._relevance(audit, options, dfs_panel, insights.relevance_pages(firecrawl_pages, result.pages), audit_brand)
            write_file(out_dir / BACKLINKS_JSON, json.dumps(dfs_panel, ensure_ascii=False))
        if dfs_panel is not None:
            report["dataforseo"] = dfs_panel
            markdown += panel.render_markdown(dfs_panel)

        enter("report")
        if report.get('generation'):
            from datetime import datetime, timezone
            report['generation']['processed_at'] = datetime.now(timezone.utc).isoformat()
            report['generation']['whole_job_finished_at'] = report['generation']['processed_at']
        write_file(out_dir / AFFECTED_JSON, json.dumps(sealed.affected, ensure_ascii=False))
        # A report may be downloaded and passed on: where its input files sit on this computer is replaced by their names.
        local = sorted({str(value) for value in (config.db_path, config.citations_file, config.citation_domains_file) if value},
                       key=len, reverse=True)

        def portable(text: str) -> str:
            for path in local:
                text = text.replace(json.dumps(path)[1:-1], Path(path).name).replace(path, Path(path).name)
            return text

        # The whole job, every step included: known only now, when nothing is left but writing the files.
        whole, slept = clock.elapsed_s(), clock.slept_s()
        report["audit_status"]["timing"] = timing(result, firecrawl_section, whole, slept)
        markdown = markdown.replace(duration_line(result, None), duration_line(result, whole, slept), 1)
        write_file(out_dir / REPORT_MD, portable(markdown))
        write_file(out_dir / REPORT_JSON, portable(json.dumps(report, ensure_ascii=False, indent=2)))  # last: its presence means "ready"
        counts = report["page_counts"]
        rendered = report["crawl"].get("render") or {}
        progress.update(render_mode=rendered.get("mode"), render_reason=(rendered.get("reason") or "")[:300] or None)
        progress.pop("continuing", None)
        # DECISIONS 311: the business type the audit used, small, so the plan of this site's next audit can suggest it
        # without reading report.json.
        chosen = report["crawl"].get("business_type") or {}
        if chosen.get("id"):
            sug = chosen.get("suggestion") or {}
            progress["business_type"] = {"id": chosen["id"], "chosen_by": chosen.get("chosen_by"), "version": chosen.get("version"),
                                         "suggestion": {k: sug.get(k) for k in ("id", "label", "reason", "version")}}
        progress.update(phase="done", pages_checked=counts["pages_checked"], redirects=counts["redirects"],
                        requests_sent=len(report["crawl"]["requests"]) or progress["requests_sent"], url=None, at=now())
        state = "stopped" if result.stopped else "finished"
        store.update_audit(audit_id, state=state, outcome=label, outcome_reason=sentence, progress=progress,
                           crawl_stop=result.stop_reason.value if result.stop_reason else None, finished_at=now())
        self.emit(audit_id, "done", {"state": state, "outcome": label, "reason": sentence[:600],
                                     "pages_checked": counts["pages_checked"]})

    def _firecrawl(self, audit: dict[str, Any], outcome: Any, config: CrawlConfig, *, stop: threading.Event,
                   enter: Callable[[str], None], clock=None, reading=None, ranking_urls=(), early=None) -> tuple[dict[str, Any] | None, list]:
        """The Firecrawl step: only when switched on for this audit, only with the credits confirmed for this run.

        "pending" spends up to the confirmed credits. "done" (a resumed audit that already used it) is given no credits
        at all, so it can only re-read its pages from Maya's own cache. A stopped audit does not start it.
        """
        state = audit.get("firecrawl") or {}
        status = state.get("state", "none")
        if early is not None and early.started:
            # Already reading beside Maya's own steps (DECISIONS 294): its approval was marked when it started.
            return self._firecrawl_apply(audit, outcome, config, early.client, early.options, state, "pending",
                                         float(state.get("approved_credits") or 0), enter, reading, ranking_urls, early)
        self._close_early(early)
        if status == "none" or outcome.result.stopped:
            return None, []
        if status == "needs_decision":
            # Firecrawl refused zero data retention and the person has not decided. Nothing is sent; the report keeps saying so.
            try:
                kept = json.loads((self.artifacts(audit["id"]) / REPORT_JSON).read_text(encoding="utf-8")).get("firecrawl")
            except (OSError, ValueError):
                kept = None
            return kept, []
        options = fc.options_from(state.get("options") or {})
        # "attempted" is a run that died part-way: like "done", it may only re-read what Maya's cache already holds.
        approved = float(state.get("approved_credits") or 0) if status == "pending" else 0.0
        if status == "pending":
            # Marked before the first request: if the app dies mid-way, a resume must not spend the approval twice.
            self.store.update_audit(audit["id"], firecrawl={**state, "state": "attempted"})
        client = fc.open_client(self.engine.firecrawl, options, approved_credits=approved, audit_id=audit["id"][:12],
                                should_stop=stop.is_set, clock=clock)
        return self._firecrawl_apply(audit, outcome, config, client, options, state, status, approved, enter, reading,
                                     ranking_urls, None)

    def _firecrawl_apply(self, audit, outcome, config, client, options, state, status, approved, enter, reading, ranking_urls,
                         early) -> tuple[dict[str, Any] | None, list]:
        enter("firecrawl")
        try:
            info = firecrawl_reader.apply(outcome, config, client, options, progress=reading, ranking_urls=ranking_urls, early=early)
        finally:
            client.close()
        never_started = (status == "pending" and client.requests_sent == 0 and not client.calls
                         and (info.get("reason") or "").startswith("Firecrawl was not started"))
        pages = info.pop("view_pages", [])
        section = firecrawl_panel.section(info)
        waiting = section.get("needs_decision") == "zero_data_retention"
        # One line per use, kept with the audit: a later attempt replaces the report's section, not the record of this one.
        attempt = {"at": now(), "proxy": section.get("proxy"), "owner_approved_bypass": bool(section.get("owner_approved_bypass")),
                   "zero_data_retention": (section.get("zero_data_retention") or {}).get("status"),
                   "credits": (section.get("credits") or {}).get("used_or_reserved", 0), "pages_read": section.get("pages_read", 0),
                   "result": "read" if section.get("used") else "needs_decision" if waiting
                   else "also_blocked" if firecrawl_reader.also_blocked(section) else "not_used"}
        self.store.update_audit(audit["id"], firecrawl={**{k: v for k, v in state.items() if k != "continue"},
                                                        # Stopped by the deadline before anything was reserved or sent: the approval is
                                                        # unspent, so a resume may still use it (once).
                                                        "state": "needs_decision" if waiting else "pending" if never_started else "done",
                                                        "approved_credits": approved if never_started else 0.0,
                                                        "attempts": [*(state.get("attempts") or []), attempt][-20:]})
        self.emit(audit["id"], "log", {"message": t("log.firecrawl.used", pages=section.get("pages_read", 0)) if section.get("used")
                                       else t("log.firecrawl.not_used")})
        return section, pages

    def _http_fallback(self, audit: dict[str, Any], outcome: Any, resume: bool) -> str | None:
        """The http:// address to try instead, when the plan allows it and https:// failed before any answer."""
        plan = self.store.plan(audit["plan_id"])
        plain = ((plan or {}).get("document") or {}).get("target", {}).get("http_fallback")
        if resume or not plain or not audit["url"].startswith("https://"):
            return None
        # "Did not answer at all": no https:// request of this run got any HTTP status back, robots.txt included.
        https_answered = any(r.status is not None for r in outcome.result.requests if r.url.startswith("https://"))
        page_answered = any(page.status is not None for page in outcome.result.pages)
        return plain if not https_answered and not page_answered else None

    def _backlinks(self, audit: dict[str, Any], out_dir: Path, *, stopped: bool, stop: threading.Event,
                   enter: Callable[[str], None], pages: list | None = None, clock=None, home: str | None = None,
                   brand: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """The paid panel: at most once per audit, only with the approval given for this run.

        `home` is where the crawl found the homepage: the lab test is run on it, not on a typed address that redirects."""
        saved = out_dir / BACKLINKS_JSON
        if saved.is_file():
            return json.loads(saved.read_text(encoding="utf-8"))
        state = self.store.audit(audit["id"])["paid_state"]
        if audit["backlinks"] and not stopped and state == "skipped":
            return self._paid_skipped(audit, saved, home, pages, brand)
        if not audit["backlinks"] or stopped or state != "pending":
            return None
        if clock is not None and clock.why_not():
            # Out of time before the paid step began: nothing is reserved or sent, and the approval stays for a resume.
            self.emit(audit["id"], "log", {"message": t("log.paid.out_of_time")})
            return None
        # Marked before the first request: if the app dies mid-call, a resume must not pay a second time.
        self.store.update_audit(audit["id"], paid_state="attempted")
        enter("backlinks")
        client = paid.open_client(self.engine.paid, approved_usd=self.store.audit(audit["id"])["approved_usd"],
                                  audit_id=audit["id"][:12], should_stop=stop.is_set,
                                  deadline_mono=clock.deadline_mono if clock is not None else None)
        try:
            options = ((self.store.plan(audit["plan_id"]) or {}).get("document") or {}).get("paid_options")
            dfs_panel = panel.run_checks(paid.calls(self.engine.paid, audit["url"], self._with_home(options, home)), client)
        finally:
            client.close()
        self._relevance(audit, options, dfs_panel, pages, brand)
        if stop.is_set():
            self.emit(audit["id"], "log", {"message": t("log.stop_during_paid")})
        write_file(saved, json.dumps(dfs_panel, ensure_ascii=False))
        self.store.update_audit(audit["id"], paid_state="done")
        return dfs_panel


    @staticmethod
    def _with_home(options: dict[str, Any] | None, home: str | None) -> dict[str, Any] | None:
        return options if options is None or not home else {**options, "home": home}

    def _relevance(self, audit: dict[str, Any], options: dict[str, Any] | None, dfs_panel: dict[str, Any], pages: list | None,
                   brand: dict[str, Any] | None = None) -> None:
        if (options or {}).get("search_data"):
            # Which of these searches are about this business: sorted by the audit's brand (typed, the site's own name,
            # or the address in the site's words; none: not sorted) and the site's own words.
            profile = (self.store.profile(audit["project_id"]) or {}).get("profile") or {}
            insights.apply_relevance(dfs_panel, brand=(options or {}).get("brand"), domain=dfs_panel.get("target"),
                                     texts=[*insights.page_texts(pages or []), str(profile.get("industry") or "")], brand_info=brand,
                                     pages=pages or [], aliases=profile.get("brand_aliases") or [],
                                     related_organizations=profile.get("related_organizations") or [])

    def _paid_skipped(self, audit: dict[str, Any], saved: Path, home: str | None, pages: list | None,
                      brand: dict[str, Any] | None = None) -> dict[str, Any]:
        """The person chose to run without paid data because of the account's balance. Nothing is approved, reserved or
        sent: the client is given no money at all, and only answers Maya's own cache already holds are read. The
        report's section says why, check by check."""
        reason = (audit.get("flags") or {}).get("paid_skipped") or panel.balance_reason(None)
        client = paid.open_client(self.engine.paid, approved_usd=0.0, audit_id=audit["id"][:12])
        try:
            options = ((self.store.plan(audit["plan_id"]) or {}).get("document") or {}).get("paid_options")
            dfs_panel = panel.run_checks(paid.calls(self.engine.paid, audit["url"], self._with_home(options, home)), client,
                                         not_requested=str(reason))
        finally:
            client.close()
        self._relevance(audit, options, dfs_panel, pages, brand)
        write_file(saved, json.dumps(dfs_panel, ensure_ascii=False))
        self.emit(audit["id"], "log", {"message": t("log.paid.skipped")})
        return dfs_panel


def is_active(audit: dict[str, Any]) -> bool:
    return audit["state"] in ACTIVE
