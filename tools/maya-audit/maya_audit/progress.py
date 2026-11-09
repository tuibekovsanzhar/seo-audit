"""Progress and stop hooks for a running audit.

An audit run from the command line needs neither. A job runner (the web interface) passes a `Hooks` to
`run_audit` to hear what the audit is doing and to ask it to stop. The hooks never change what is
checked: an audit run with hooks that are never used gives the same report as one run without.

Stopping is a request, honoured between two requests to the site. The crawl ends, the pages already
fetched are checked, and everything that would have needed another request is reported as not checked,
exactly as when the time limit is reached. With a crawl database (`db_path`) the audit can be resumed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable
from . import clock as _clock

# In the order an audit goes through them. DECISIONS 328: the sitemap check starts right after the crawl, beside access,
# index, structure and rendering. DECISIONS 330: access and llms.txt's links to this site run beside them too.
PHASES = ("starting", "sitemap", "crawl", "sitemap_check", "access", "llms_links", "index", "structure", "render", "performance", "citations",
          "citation_domains", "checks", "done")


@dataclass
class Hooks:
    # Called with one event: {"phase", "elapsed_s", and for the crawl "pages_fetched", "pages_discovered",
    # "max_pages", "url", "other_fetches" (redirect hops and repeats, not pages), "requests_sent"}. Called from the audit's own thread; it must return quickly and must not raise.
    on_progress: Callable[[dict[str, Any]], None] | None = None
    # Asked before every request. True means: stop as soon as possible.
    should_stop: Callable[[], bool] | None = None
    _t0: float = field(default_factory=_clock.monotonic, repr=False)

    def emit(self, phase: str, **fields: Any) -> None:
        if self.on_progress is None:
            return
        try:
            self.on_progress({"phase": phase, "elapsed_s": round(_clock.monotonic() - self._t0, 1), **fields})
        except Exception:  # noqa: BLE001  a listener's failure must never fail the audit
            pass

    def stop_requested(self) -> bool:
        try:
            return bool(self.should_stop and self.should_stop())
        except Exception:  # noqa: BLE001
            return False


NO_HOOKS = Hooks()
