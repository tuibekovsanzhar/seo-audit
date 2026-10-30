import subprocess
import sys
import time

import httpx
import pytest

from maya_audit.audit import _effective_robots_sample_interval, run_audit
from maya_audit.config import CrawlConfig
from maya_audit.crawler import ConcurrentCrawlError, HostNotAllowed, _shared_site_lock
from maya_audit.fetcher import Fetcher
from maya_audit.checks.integrity import int3_rendering_disclosure
from maya_audit.render import RenderData, _render_one, chromium_safety_args, configure_websocket_blocking
from maya_audit.report import render_markdown


def test_deadline_skips_request_without_recording_a_fake_timeout():
    fetcher = Fetcher("Maya-Audit-test", 1, 0, httpx.MockTransport(lambda request: httpx.Response(200)))
    fetcher.deadline_mono = time.monotonic() - 1
    response = fetcher.get("https://example.com/", "page", 1024)
    try:
        assert response.error == "audit_deadline_skipped"
        assert fetcher.deadline_hits == 1
        assert fetcher.log == []  # skipped requests are excluded from INT-4's evidence
    finally:
        fetcher.close()


def test_deadline_makes_unfinished_audit_checks_not_assessed_and_logs_no_skip():
    config = CrawlConfig(max_pages=1, time_limit_s=0, request_delay_s=0, robots_samples=1,
                         render_enabled=False, prf_enabled=False, probes_enabled=False)
    outcome = run_audit("https://example.com/", config,
                        httpx.MockTransport(lambda request: httpx.Response(200)))
    assert outcome.result.deadline_hit
    assert outcome.result.requests == []
    checks = {check.check_id: check for check in outcome.checks}
    assert checks["ACC-1"].status == "not_assessed"
    assert checks["RND-1"].status == "not_assessed"
    int4 = next(gate for gate in outcome.gates if gate.check_id == "INT-4")
    assert int4.state == "not_assessed"
    assert "excluded from INT-4" in int4.summary
    markdown = render_markdown(outcome.result, outcome.gates, outcome.checks)
    assert markdown.index("## Cut short by the time limit") < markdown.index("## What to fix first")
    assert "citations data collector failed" not in markdown
    assert "No citation data supplied" in markdown
    assert "citations" not in outcome.result.collector_errors
    assert "citation_domains" not in outcome.result.collector_errors


def test_robots_resampling_interval_scales_to_time_budget():
    cfg = CrawlConfig(time_limit_s=12, robots_samples=4, robots_sample_interval_s=120)
    assert _effective_robots_sample_interval(cfg) == 1.0
    assert _effective_robots_sample_interval(CrawlConfig(robots_samples=1, robots_sample_interval_s=0)) == 0


def test_hosted_setting_rejects_loopback_start_url():
    from maya_audit.crawler import Crawler

    with pytest.raises(HostNotAllowed, match="loopback targets are blocked"):
        Crawler(CrawlConfig(block_loopback=True)).run("http://127.0.0.1/")


def test_render_disables_chromium_native_resolution_for_websockets():
    assert "--host-resolver-rules=MAP * ~NOTFOUND" in chromium_safety_args()


def test_render_does_not_close_websocket_routes_when_supported():
    captured = {}

    class FakeRoute:
        def close(self, **kwargs):
            captured["closed"] = kwargs

    class FakeContext:
        def route_web_socket(self, pattern, handler):
            captured["pattern"] = pattern
            captured["handler"] = handler

    assert configure_websocket_blocking(FakeContext())
    assert captured["handler"](FakeRoute()) is None
    assert captured["pattern"] == "**/*"
    assert "closed" not in captured


def test_context_without_route_web_socket_is_disclosed_in_int3(run_audit_scenario):
    """Playwright before 1.48 cannot intercept WebSockets. The render still runs; INT-3 says so."""

    class FakePage:
        main_frame = object()
        url = ""

        def __init__(self): self.handlers = {}
        def route(self, pattern, handler): pass
        def on(self, event, handler): self.handlers[event] = handler
        def wait_for_timeout(self, ms): time.sleep(ms / 1000)
        def content(self): return "<html><body><main><h1>Rendered</h1><p>Some text.</p></main></body></html>"

        def goto(self, url, **kwargs):
            self.url = url
            self.handlers["domcontentloaded"](self)

    class ContextWithoutRouteWebSocket:
        def new_page(self): return FakePage()
        def close(self): pass

    class FakeBrowser:
        def new_context(self, **kwargs): return ContextWithoutRouteWebSocket()

    run = run_audit_scenario("acc_ai_friendly")
    assert run.gates["INT-3"].evidence["websocket_blocking"] is None  # nothing was rendered in that run
    url = run.result.origin + "/"
    cfg = CrawlConfig(request_delay_s=0, render_interactions=False)
    fetcher = Fetcher(cfg.user_agent, 1, 0, httpx.MockTransport(lambda request: httpx.Response(200)))
    try:
        entry = _render_one(FakeBrowser(), fetcher, cfg, run.result.robots_policy_by_origin[run.result.origin],
                            url, RuntimeError)
    finally:
        fetcher.close()
    assert entry["ok"] and entry["websocket_blocking"] == "unavailable"

    run.result.render = RenderData(mode="raw_plus_sampled_render", reason=None, pages={url: entry})
    int3 = int3_rendering_disclosure(run.result, cfg)
    assert int3.evidence["websocket_blocking"].startswith("WebSocket blocking unavailable")
    assert int3.evidence["rendered_pages"][0]["websocket_blocking"] == "unavailable"
    assert "WebSocket blocking unavailable" in int3.summary


def test_cli_passes_render_browser_channel_to_the_config(monkeypatch):
    from maya_audit import cli

    seen = {}

    class Stop(Exception):
        pass

    def capture(start_url, config, *args, **kwargs):
        seen["channel"] = config.render_browser_channel
        raise Stop

    monkeypatch.setattr(cli, "run_audit", capture)
    with pytest.raises(Stop):
        cli.main(["crawl", "https://example.com/", "--render-browser-channel", "chrome"])
    assert seen["channel"] == "chrome"
    with pytest.raises(Stop):
        cli.main(["crawl", "https://example.com/"])
    assert seen["channel"] is None


@pytest.mark.parametrize("option", ["--json", "--markdown"])
def test_existing_output_is_rejected_before_any_crawl(tmp_path, monkeypatch, capsys, option):
    from maya_audit import cli

    output = tmp_path / "existing-report"
    output.write_text("keep me", encoding="utf-8")

    def crawl_must_not_start(*args, **kwargs):
        raise AssertionError("the audit started before output preflight")

    monkeypatch.setattr(cli, "run_audit", crawl_must_not_start)
    assert cli.main(["crawl", "https://example.com/", option, str(output)]) == 2
    assert "output already exists" in capsys.readouterr().err
    assert output.read_text(encoding="utf-8") == "keep me"


def test_file_lock_is_shared_across_processes():
    origin = "https://lock-test.invalid"
    code = (
        "import sys,time; from maya_audit.crawler import _shared_site_lock; "
        "lock=_shared_site_lock(sys.argv[1]); lock.__enter__(); print('LOCKED', flush=True); time.sleep(3); lock.__exit__(None,None,None)"
    )
    child = subprocess.Popen([sys.executable, "-c", code, origin], stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == "LOCKED"
        with pytest.raises(ConcurrentCrawlError):
            with _shared_site_lock(origin):
                pass
    finally:
        child.terminate()
        child.wait(timeout=5)


def test_render_collector_failure_adds_not_assessed_checks(run_audit_scenario, monkeypatch):
    import maya_audit.audit as audit_module

    def fail(*args, **kwargs):
        raise RuntimeError("browser crashed")

    monkeypatch.setattr(audit_module, "collect_render_data", fail)
    run = run_audit_scenario("acc_ai_friendly")
    assert run.result.render is None
    assert all(run.checks[f"RND-{n}"].status == "not_assessed" for n in range(1, 8))


def _cli_exit(monkeypatch, capsys, audit, argv=(), url="http://127.0.0.1/"):
    from maya_audit import cli

    monkeypatch.setattr(cli, "run_audit", lambda start_url, config, *args, **kwargs: audit())
    code = cli.main(["crawl", url, *argv])
    return code, capsys.readouterr()


QUIET = dict(request_delay_s=0, robots_samples=1, render_enabled=False, prf_enabled=False, probes_enabled=False,
             refetch_delay_s=0)


def _linked_site(pages, robots_txt="User-agent: *\nAllow: /\n"):
    from fakeserver import Response, Site

    links = "".join(f'<a href="/p{i}">p{i}</a>' for i in range(pages))
    page = Response(body=f"<html><head><title>T</title></head><body><main><h1>T</h1>{links}</main></body></html>")
    return Site({"/robots.txt": Response(body=robots_txt, content_type="text/plain"),
                 "/sitemap.xml": Response(404, "", content_type="text/plain"),
                 "/": page, **{f"/p{i}": page for i in range(pages)}})


def _audit_site(site, **options):
    from fakeserver import FakeServer

    with FakeServer(site) as server:
        return run_audit(server.base_url + "/", CrawlConfig(**{**QUIET, **options}))


def test_exit_0_when_the_audit_completes(monkeypatch, capsys):
    code, out = _cli_exit(monkeypatch, capsys, lambda: _audit_site(_linked_site(2)))
    assert "Result      COMPLETED" in out.out
    assert code == 0


def test_exit_3_when_the_page_cap_leaves_the_audit_incomplete(monkeypatch, capsys, tmp_path):
    markdown = tmp_path / "report.md"
    code, out = _cli_exit(monkeypatch, capsys, lambda: _audit_site(_linked_site(6), max_pages=2),
                          ["--markdown", str(markdown)])
    assert code == 3
    # Stopped by the page limit only: a partial audit, with its figures (DECISIONS 226). Exit code 3 stays.
    assert "Result      INCOMPLETE: Partial audit: 2 of " in out.out and "(the page limit of 2)" in out.out
    assert "**Result:** INCOMPLETE" in markdown.read_text(encoding="utf-8")


def test_exit_3_when_the_time_limit_leaves_the_audit_incomplete(monkeypatch, capsys):
    transport = httpx.MockTransport(lambda request: httpx.Response(200))
    code, out = _cli_exit(monkeypatch, capsys, lambda: run_audit(
        "https://example.com/", CrawlConfig(max_pages=5, time_limit_s=0, **QUIET), transport))
    assert code == 3
    assert "Result      INCOMPLETE" in out.out and "time limit" in out.out


def test_exit_1_when_the_site_blocks_the_crawl(monkeypatch, capsys):
    from fakeserver import Response, Site

    challenge = Response(403, "<html><title>Just a moment...</title></html>",
                         headers={"cf-mitigated": "challenge", "server": "cloudflare"})
    site = Site({"/robots.txt": Response(body="User-agent: *\nAllow: /\n", content_type="text/plain")}, fallback=challenge)
    code, out = _cli_exit(monkeypatch, capsys, lambda: _audit_site(site, max_pages=2))
    assert code == 1
    assert "Result      DEGRADED" in out.out


def test_exit_1_when_robots_txt_disallows_the_crawl(monkeypatch, capsys):
    code, out = _cli_exit(monkeypatch, capsys,
                          lambda: _audit_site(_linked_site(2, robots_txt="User-agent: *\nDisallow: /\n")))
    assert code == 1
    assert "Result      DEGRADED" in out.out and "robots_disallowed" in out.out


def test_exit_2_for_a_refused_target(capsys):
    from maya_audit import cli

    assert cli.main(["crawl", "http://127.0.0.1/", "--block-loopback"]) == 2
    assert "error:" in capsys.readouterr().err
