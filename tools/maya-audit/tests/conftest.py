import os
import sys
import ipaddress
import socket
from dataclasses import replace

import pytest


@pytest.fixture(autouse=True)
def block_non_loopback_network(monkeypatch):
    """Keep the suite hermetic: fake servers may use loopback, but tests never contact the internet."""
    original_connect = socket.socket.connect

    def guarded_connect(sock, address):
        if isinstance(address, tuple) and address:
            host = str(address[0]).strip("[]").lower()
            try:
                is_local = ipaddress.ip_address(host).is_loopback
            except ValueError:
                is_local = host == "localhost" or host.endswith(".localhost")
            if not is_local:
                raise RuntimeError(f"test blocked non-loopback network connection to {host}")
        return original_connect(sock, address)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)


_REAL_GETADDRINFO = socket.getaddrinfo


@pytest.fixture(autouse=True)
def no_public_dns(monkeypatch):
    """No test asks a public resolver: the DNS-over-HTTPS fallback gets a transport that cannot connect, pauses are
    skipped and nothing is remembered from one test to the next. Tests of the fallback put their own transport in."""
    import httpx
    from maya_audit import resolver

    def unreachable(request):
        raise httpx.ConnectError("tests do not reach public resolvers")

    real = socket.getaddrinfo

    def system(host, port):
        # A test that replaced socket.getaddrinfo is asking for its own answers; loopback names are looked up for
        # real; every other name fails at once, so no test waits on, or reaches, a real resolver.
        if socket.getaddrinfo is not _REAL_GETADDRINFO:
            return [item[4][0] for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)]
        if host == "localhost" or host.endswith(".localhost"):
            return [item[4][0] for item in real(host, port, type=socket.SOCK_STREAM)]
        raise socket.gaierror(socket.EAI_NONAME, "tests do not look up public names")

    monkeypatch.setattr(resolver, "system_lookup", system)
    monkeypatch.setattr(resolver, "doh_transport", httpx.MockTransport(unreachable))
    monkeypatch.setattr(resolver, "sleep", lambda seconds: None)
    monkeypatch.delenv(resolver.DOH_VAR, raising=False)
    resolver.reset()
    yield
    resolver.reset()


# Credentials of the paid or third-party providers (AGENTS.md): never in a test, whatever the shell or .env holds.
PROVIDER_KEYS = ("MAYA_AUDIT_DATAFORSEO_LOGIN", "MAYA_AUDIT_DATAFORSEO_PASSWORD", "MAYA_AUDIT_FIRECRAWL_API_KEY",
                 "MAYA_AUDIT_CRUX_API_KEY", "MAYA_AUDIT_GOOGLE_API_KEY", "MAYA_AUDIT_BING_API_KEY", "MAYA_AUDIT_GSC_TOKEN")


@pytest.fixture(autouse=True)
def isolate_dataforseo(monkeypatch, tmp_path_factory):
    """No test reads real DataForSEO credentials or touches the real ledger and cache in ~/.maya-audit."""
    home = tmp_path_factory.mktemp("maya-audit-home")
    monkeypatch.setenv("MAYA_AUDIT_HOME", str(home))
    monkeypatch.setenv("MAYA_AUDIT_ENV_FILE", str(home / "no-such.env"))
    monkeypatch.delenv("MAYA_AUDIT_DATAFORSEO_LOGIN", raising=False)
    monkeypatch.delenv("MAYA_AUDIT_DATAFORSEO_PASSWORD", raising=False)
    # Firecrawl reads every audit's pages when a key is set: a key exported in the shell must never reach a test.
    for name in ("MAYA_AUDIT_DATAFORSEO_DAILY_USD", "MAYA_AUDIT_DATAFORSEO_CONFIRM_ABOVE_USD", "MAYA_AUDIT_DATAFORSEO_AUDIT_CAP_USD",
                 "MAYA_AUDIT_FIRECRAWL_API_KEY", "MAYA_AUDIT_FIRECRAWL", "MAYA_AUDIT_FIRECRAWL_ZERO_DATA_RETENTION",
                 "MAYA_AUDIT_FIRECRAWL_DAILY_CREDITS", "MAYA_AUDIT_FIRECRAWL_USD_PER_CREDIT",
                 # Every other provider key (DECISIONS 312): CrUX is read from the environment or the env file by
                 # itself; PageSpeed, Bing and Search Console when asked for. None of them may reach a test.
                 *PROVIDER_KEYS):
        monkeypatch.delenv(name, raising=False)
    # Firecrawl's own gap between request starts (DECISIONS 295) is 0 here, so a made-up reader answers at test speed;
    # the tests of the gap set it themselves. No test keeps a real Mac awake.
    monkeypatch.setenv("MAYA_AUDIT_FIRECRAWL_GAP_S", "0")
    monkeypatch.setenv("MAYA_AUDIT_KEEP_AWAKE", "off")
    # A made-up Firecrawl that times out is asked again at once, not after the real five seconds.
    from maya_audit.firecrawl import settings as firecrawl_settings
    monkeypatch.setattr(firecrawl_settings, "RETRY_WAIT_S", 0)


@pytest.fixture(autouse=True)
def no_automatic_balance_request(monkeypatch):
    """A plan with paid data asks the provider's free account endpoint for the balance by itself (DECISIONS 180). Tests
    of other things count the requests their made-up provider receives, so the automatic one is off for them; the tests
    of the balance rule (tests/test_market_and_balance.py) switch it back on."""
    try:
        from maya_audit_web import paid
    except ImportError:  # the web app's own dependencies are optional
        return
    monkeypatch.setattr(paid, "AUTOMATIC_BALANCE", False)


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from fakeserver import SCENARIOS, FakeServer  # noqa: E402
from maya_audit.checks.integrity import run_integrity_gates  # noqa: E402
from maya_audit.config import CrawlConfig  # noqa: E402
from maya_audit.crawler import Crawler  # noqa: E402


class Run:
    def __init__(self, result, gates, server_paths, scenario, config):
        self.result = result
        self.gates = {g.check_id: g for g in gates}
        self.server_paths = server_paths
        self.scenario = scenario
        self.config = config

    def page(self, path):
        return next(p for p in self.result.pages if p.url == self.result.origin + path)


@pytest.fixture
def run_scenario():
    def _run(name, **overrides):
        scenario = SCENARIOS[name]
        with FakeServer(scenario.build()) as server:
            # These scenarios count the crawl's own requests; the homepage render that link discovery adds
            # (maya_audit.render_discovery, tested in test_engine_gaps.py) would be one more.
            options = {"render_discovery": False, **scenario.config, **overrides}
            if "key_pages" in options:
                options["key_pages"] = tuple(server.base_url + p for p in options["key_pages"])
            config = CrawlConfig(**options)
            result = Crawler(config).run(server.base_url + scenario.start_path)
            gates = run_integrity_gates(result, config)
            return Run(result, gates, server.paths(), scenario, config)

    return _run


class AuditRun:
    def __init__(self, outcome, server_requests, scenario, config, base_url):
        self.result = outcome.result
        self.gates = {g.check_id: g for g in outcome.gates}
        self.checks = {c.check_id: c for c in outcome.checks}
        self.requests = server_requests
        self.scenario = scenario
        self.config = config
        self.base = base_url

    def findings(self, check_id, severity=None):
        found = self.checks[check_id].findings
        return [f for f in found if severity is None or f.severity.value == severity]

    def url(self, path):
        return self.base + path


@pytest.fixture
def run_audit_scenario():
    from fakeserver.acc_scenarios import ACC_SCENARIOS
    from fakeserver.arjava_scenarios import ARJAVA_SCENARIOS
    from fakeserver.idx_scenarios import IDX_SCENARIOS
    from fakeserver.neutral_scenarios import NEUTRAL_SCENARIOS
    from fakeserver.rnd_scenarios import RND_SCENARIOS
    from fakeserver.str_scenarios import STR_SCENARIOS
    from fakeserver.prf_scenarios import PRF_SCENARIOS
    from maya_audit.audit import run_audit

    def _run(name, **overrides):
        scenario = ARJAVA_SCENARIOS.get(name) or NEUTRAL_SCENARIOS.get(name) or ACC_SCENARIOS.get(name) or IDX_SCENARIOS.get(name) or RND_SCENARIOS.get(name) or STR_SCENARIOS.get(name) or PRF_SCENARIOS.get(name) or SCENARIOS[name]
        with FakeServer(scenario.build()) as server:
            options = {"request_delay_s": 0.0, "robots_sample_interval_s": 0.05, "probe_retry_cooldown_s": 0.0,
                       "refetch_delay_s": 0.0, "render_enabled": False, "prf_round_gap_s": 0.0,
                       **scenario.config, **overrides}
            if "key_pages" in options:
                options["key_pages"] = tuple(p if p.startswith("http") else server.base_url + p for p in options["key_pages"])
            if "intent_markings" in options:  # exact-URL scopes may use {base} for the per-run port
                options["intent_markings"] = tuple(
                    replace(m, scope=m.scope.replace("{base}", server.base_url)) for m in options["intent_markings"]
                )
            config = CrawlConfig(**options)
            outcome = run_audit(server.base_url + scenario.start_path, config)
            return AuditRun(outcome, list(server.requests), scenario, config, server.base_url)

    return _run


@pytest.fixture
def confirm_every_paid_plan(monkeypatch):
    """The web app's confirmation and daily-limit mechanics, tested at limits a five-cent plan reaches: every paid
    plan asks, and the day's limit is $2. The shipped defaults (confirmation above $2 an audit, never more than $5 an
    audit, $20 a day) have their own tests (tests/test_cost_limits.py)."""
    from maya_audit.dataforseo import pricing

    monkeypatch.setattr(pricing, "APPROVAL_THRESHOLD_USD", 0.0)
    monkeypatch.setenv("MAYA_AUDIT_DATAFORSEO_DAILY_USD", "2")


@pytest.fixture
def small_cli_limits(monkeypatch):
    """The command line's approval and budget mechanics, tested at $0.50 an audit and $2 a day."""
    from maya_audit.dataforseo import pricing

    monkeypatch.setattr(pricing, "APPROVAL_THRESHOLD_USD", 0.50)
    monkeypatch.setenv("MAYA_AUDIT_DATAFORSEO_DAILY_USD", "2")


_SLOW_LIST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "slow_tests.txt")


def pytest_collection_modifyitems(config, items):
    """Mark the tests named in tests/slow_tests.txt as "slow": the fast CI set runs `-m "not slow and not timing"`."""
    with open(_SLOW_LIST, encoding="utf-8") as fh:
        slow = {line.strip() for line in fh if line.strip() and not line.startswith("#")}
    for item in items:
        if item.nodeid in slow:
            item.add_marker(pytest.mark.slow)
