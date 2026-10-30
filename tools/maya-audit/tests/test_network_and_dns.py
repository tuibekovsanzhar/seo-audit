"""A lookup that fails on this computer is this computer's problem, never the website's.

The system resolver, a retry, then DNS over HTTPS (Cloudflare, then Google); private addresses stay refused; a local
failure is never "unsafe target", never RFC 9309's disallow-all and never a finding; Firecrawl reads robots.txt itself
when Maya could not; a pre-flight stops an audit this computer cannot run before anything is spent. No network here:
the resolver and the DNS-over-HTTPS transport are made up.
"""
import json
import socket

import httpx
import pytest

from maya_audit import resolver
from maya_audit.audit import NetworkPreflightFailed, network_preflight, run_audit
from maya_audit.classify import classify_fetch
from maya_audit.config import CrawlConfig
from maya_audit.dataforseo import insights
from maya_audit.fetcher import Fetcher
from maya_audit.firecrawl import Options, panel, reader
from maya_audit.models import StopReason
from maya_audit.report import audit_status, run_outcome
from maya_audit.robots import LOCAL_NETWORK_MESSAGE, failure_cause, policy_from_response
from maya_audit.urls import HostNotFoundError, LocalDnsError, UnsafeTargetError, public_addresses
from test_firecrawl import SITE, Firecrawl, client_for, no_lookups  # noqa: F401
from test_review_fixes import QUIET
from test_web_app import web  # noqa: F401

HOST = "shop.example.com"


class Doh:
    """A made-up public resolver. `table`: host -> addresses, or "nxdomain". `down`: providers that cannot be reached."""

    def __init__(self, table=None, down=()):
        self.table, self.down, self.seen = table or {}, set(down), []

    def __call__(self, request):
        provider = request.headers["host"]
        self.seen.append((request.url.host, provider, request.url.path, request.url.params["name"], request.url.params["type"],
                          request.extensions.get("sni_hostname")))
        if provider in self.down:
            raise httpx.ConnectTimeout("no route")
        assert request.headers["accept"] == "application/dns-json"
        found = self.table.get(request.url.params["name"])
        if found is None or found == "nxdomain":
            return httpx.Response(200, json={"Status": 3})
        kind = 1 if request.url.params["type"] == "A" else 28
        wanted = [a for a in found if (":" in a) == (kind == 28)]
        # A real answer lists the alias first; only address records of the asked type are taken.
        return httpx.Response(200, json={"Status": 0, "Answer": [{"type": 5, "data": "alias.example.net."},
                                                                  *({"type": kind, "data": a} for a in wanted)]})


def system(answers=None, error=None, hang=False, calls=None):
    def lookup(host, port):
        if calls is not None:
            calls.append(host)
        if hang:
            import time
            time.sleep(1.0)
        if error is not None:
            raise error
        return (answers or {})[host]
    return lookup


@pytest.fixture
def dns(monkeypatch):
    def use(lookup, doh):
        monkeypatch.setattr(resolver, "system_lookup", lookup)
        monkeypatch.setattr(resolver, "doh_transport", httpx.MockTransport(doh))
        resolver.reset()
        return doh
    return use


# -- 1. the lookup ----------------------------------------------------------------------------------------------------
def test_the_system_resolver_answers_first_and_no_public_resolver_is_asked(dns):
    doh = dns(system({HOST: ["93.184.216.34", "93.184.216.34"]}), Doh())
    found = resolver.resolve(HOST)
    assert (found.method, found.addresses, doh.seen) == ("system", ["93.184.216.34"], [])
    assert resolver.record()[-1]["answered_by"] == "system" and resolver.summary()["hosts"][0]["system_resolver_failed"] is False


def test_a_resolver_that_gives_no_answer_is_retried_then_dns_over_https_answers_and_the_method_is_recorded(dns, monkeypatch):
    monkeypatch.setattr(resolver, "SYSTEM_TIMEOUT_S", 0.05)
    waits, calls = [], []
    monkeypatch.setattr(resolver, "sleep", waits.append)
    doh = dns(system(hang=True, calls=calls), Doh({HOST: ["93.184.216.34", "2606:2800:220:1::1"]}))
    found = resolver.resolve(HOST)
    assert found.method == "doh:cloudflare" and found.addresses == ["93.184.216.34", "2606:2800:220:1::1"]  # A and AAAA
    assert calls == [HOST, HOST] and waits == [resolver.BACKOFF_S]                          # asked twice, with a pause between
    assert [a["outcome"] for a in found.attempts] == ["timeout", "timeout", "answered"]
    # Reached by its published address, with its own name for TLS: the fallback needs no working resolver.
    assert doh.seen == [("1.1.1.1", "cloudflare-dns.com", "/dns-query", HOST, "A", "cloudflare-dns.com"),
                        ("1.1.1.1", "cloudflare-dns.com", "/dns-query", HOST, "AAAA", "cloudflare-dns.com")]
    row = resolver.summary()["hosts"][0]
    assert row["answered_by"] == "doh:cloudflare" and row["system_resolver_failed"] and row["system_resolver_said"] == "timeout"
    # For the next minute the failed system resolver is not waited on again, and an answer is reused.
    calls.clear()
    assert resolver.resolve(HOST).method == "doh:cloudflare" and calls == []
    doh.table["other.example.com"] = ["93.184.216.35"]
    assert resolver.resolve("other.example.com").method == "doh:cloudflare" and calls == []


def test_google_is_asked_when_cloudflare_cannot_be_reached(dns):
    doh = dns(system(error=socket.gaierror(socket.EAI_AGAIN, "temporary failure")), Doh({HOST: ["93.184.216.34"]}, down={"cloudflare-dns.com"}))
    found = resolver.resolve(HOST)
    assert found.method == "doh:google" and found.addresses == ["93.184.216.34"]
    assert [(ip, name) for ip, name, *_ in doh.seen] == [("1.1.1.1", "cloudflare-dns.com"), ("1.0.0.1", "cloudflare-dns.com"),
                                                          ("8.8.8.8", "dns.google"), ("8.8.8.8", "dns.google")]
    assert doh.seen[-1][2] == "/resolve"


def test_three_different_failures_are_three_different_things(dns):
    gone = socket.gaierror(socket.EAI_NONAME, "nodename nor servname provided")
    # A public resolver says the name does not exist: that is about the name.
    dns(system(error=gone), Doh({HOST: "nxdomain"}))
    with pytest.raises(resolver.LookupFailed) as not_found:
        resolver.resolve(HOST)
    assert not_found.value.kind == "not_found" and "has no address (answered by the cloudflare public resolver)" in not_found.value.detail
    with pytest.raises(HostNotFoundError):
        public_addresses(f"https://{HOST}/")
    # Nothing can be looked up at all: that is about this computer. "No such name" from an offline computer is not believed.
    dns(system(error=gone), Doh(down={"cloudflare-dns.com", "dns.google"}))
    with pytest.raises(LocalDnsError, match="DNS lookup failed on this computer") as local:
        public_addresses(f"https://{HOST}/")
    assert "neither public resolver could be reached" in str(local.value) and isinstance(local.value, UnsafeTargetError)  # still refuses to connect
    # A name that is never public is not sent to a public resolver.
    doh = dns(system(error=gone), Doh())
    for private in ("intranet", "printer.local", "db.internal", "shop.test"):
        with pytest.raises(resolver.LookupFailed) as kept:
            resolver.resolve(private)
        assert kept.value.kind == "unresolved"
    assert doh.seen == []


def test_dns_over_https_can_be_switched_off(dns, monkeypatch):
    monkeypatch.setenv(resolver.DOH_VAR, "off")
    doh = dns(system(error=socket.gaierror(socket.EAI_AGAIN, "x")), Doh({HOST: ["93.184.216.34"]}))
    with pytest.raises(resolver.LookupFailed) as failed:
        resolver.resolve(HOST)
    assert failed.value.kind == "unresolved" and doh.seen == []


def test_addresses_from_a_public_resolver_get_the_same_private_address_check_and_the_connection_goes_to_them(dns, monkeypatch):
    from maya_audit.network import PublicTransport
    dns(system(error=socket.gaierror(socket.EAI_AGAIN, "x")), Doh({HOST: ["10.0.0.7"], "mixed.example.com": ["93.184.216.34", "192.168.1.5"],
                                                                 "fine.example.com": ["93.184.216.34"]}))
    for host in (HOST, "mixed.example.com"):
        with pytest.raises(UnsafeTargetError, match="non-public destination") as refused:
            public_addresses(f"https://{host}/")
        assert not isinstance(refused.value, LocalDnsError)
    connected = []

    def record(self, request):
        connected.append((request.url.host, request.extensions.get("sni_hostname")))
        return httpx.Response(200, text="ok")
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", record)
    with httpx.Client(transport=PublicTransport()) as client:
        assert client.get("https://fine.example.com/").text == "ok"
    assert connected == [("93.184.216.34", "fine.example.com")]  # the address that was checked, under the site's own name


# -- 2. local failure, the site's failure, and what each is called ------------------------------------------------------
def test_the_fetcher_names_a_local_dns_failure_apart_from_an_unsafe_address_and_a_name_that_does_not_exist(dns):
    gone = socket.gaierror(socket.EAI_NONAME, "x")
    cases = [(Doh(down={"cloudflare-dns.com", "dns.google"}), "local_dns_failure (DNS lookup failed on this computer"),
             (Doh({HOST: "nxdomain"}), "host_not_found ("), (Doh({HOST: ["127.0.0.1"]}), "unsafe_target (refusing non-public destination")]
    for doh, expected in cases:
        dns(system(error=gone), doh)
        fetcher = Fetcher("Maya-Test", 1, 0, block_loopback=True)
        try:
            response = fetcher.get(f"https://{HOST}/robots.txt", "robots", 1000)
        finally:
            fetcher.close()
        assert response.status is None and response.error.startswith(expected), response.error
    assert [failure_cause(e) for e in ("local_dns_failure (x)", "unresolved_host (x)", "host_not_found (x)", "unsafe_target (x)", "timeout (ReadTimeout)",
                                       "connect_error (refused)")] == ["local_network", "local_network", "host_not_found", "refused_address", "no_answer", "no_answer"]


def test_only_a_5xx_the_site_sent_is_rfc_9309_disallow_all():
    url = f"https://{HOST}/robots.txt"
    for status in (500, 502, 503):
        policy = policy_from_response(url, status, None, b"", 500, [])
        assert policy.mode == "disallow_all" and "RFC 9309: assume complete disallow" in policy.reason and policy.cause is None
    local = policy_from_response(url, None, "local_dns_failure (DNS lookup failed on this computer for shop.example.com)", b"", 500, [])
    assert local.mode == "not_checked" and local.cause == "local_network" and local.stops_requests
    assert "network problem on this computer" in local.reason and "says nothing about the site" in local.reason
    for policy in (local, policy_from_response(url, None, "timeout (ConnectTimeout)", b"", 500, [])):
        assert "RFC 9309" not in policy.reason and "disallow" not in policy.reason and "unsafe" not in policy.reason


def local_failure(request):
    raise LocalDnsError(f"DNS lookup failed on this computer for {request.url.host}: the system resolver gave no answer (2 attempt(s)), "
                        "and neither public resolver could be reached")


def audit_with_no_network(**options):
    return run_audit("https://bank.test/", CrawlConfig(**{**QUIET, "max_pages": 10, **options}), httpx.MockTransport(local_failure))


def test_a_local_dns_failure_is_not_a_finding_not_a_blocker_and_not_a_statement_about_the_site(no_lookups):
    outcome = audit_with_no_network()
    result = outcome.result
    assert result.stop_reason == StopReason.NETWORK and result.pages == [] and "network problem on this computer" in result.stop_detail
    assert all(r.error.startswith("local_dns_failure") for r in result.requests) and not any("unsafe_target" in (r.error or "") for r in result.requests)
    by_id = {check.check_id: check for check in outcome.checks}
    acc1 = by_id["ACC-1"]
    assert acc1.status == "not_assessed" and acc1.findings == [] and acc1.summary.startswith("Not checked (network problem on this computer)")
    assert "Nothing is reported against the site" in acc1.summary and acc1.evidence["applied_policy"]["mode"] == "not_checked"
    assert not [f for check in outcome.checks for f in check.findings]            # no finding of any kind against the site
    assert by_id["ACC-2"].status == by_id["ACC-6"].status == "not_assessed" and "Not checked" in by_id["ACC-2"].summary
    text = json.dumps([[c.summary, c.status] for c in outcome.checks] + [[g.summary, g.how_to_fix] for g in outcome.gates])
    assert "RFC 9309: assume complete disallow" not in text and "unsafe_target" not in text and "does not allow Maya" not in text
    code, word, sentence = run_outcome(result, outcome.gates, None)
    assert word == "DEGRADED" and sentence.startswith("The audit could not reach the site from this computer")
    assert "Nothing is reported against the site" in sentence
    status = audit_status(result, outcome.gates, outcome.checks, None)
    assert status["direct_access"]["state"] == "unknown" and status["direct_access"]["note"].startswith("Direct access was not measured")
    int2 = next(g for g in outcome.gates if g.check_id == "INT-2")
    assert "VPN, iCloud Private Relay, Wi-Fi" in int2.how_to_fix


def test_a_real_5xx_robots_answer_is_still_the_blocker(no_lookups):
    def broken(request):
        return httpx.Response(503, text="down") if request.url.path == "/robots.txt" else httpx.Response(200, text="<html></html>")
    outcome = run_audit("https://bank.test/", CrawlConfig(**{**QUIET, "max_pages": 10}), httpx.MockTransport(broken))
    acc1 = next(check for check in outcome.checks if check.check_id == "ACC-1")
    assert outcome.result.stop_reason == StopReason.ROBOTS_DISALLOWED and "RFC 9309: assume complete disallow" in outcome.result.stop_detail
    assert [f.severity.value for f in acc1.findings] == ["S1"] and "robots.txt returned a server error on" in acc1.findings[0].title


# -- 4. a local failure never stops the reader ---------------------------------------------------------------------------
def test_firecrawl_reads_robots_itself_and_then_the_site_when_mayas_own_lookup_failed(tmp_path, no_lookups):
    outcome = audit_with_no_network()
    cfg = CrawlConfig(**{**QUIET, "max_pages": 10})
    api = Firecrawl(SITE)
    info = reader.apply(outcome, cfg, client_for(tmp_path, api), Options(read_always=True))
    section = panel.section(info)
    assert api.urls[0] == "https://bank.test/robots.txt" and section["used"] and section["pages_read"] == 4
    assert section["robots"]["source"] == "Firecrawl" and section["robots"]["mode"] == "parsed"
    assert "network problem on this computer" in section["robots"]["mayas_own_attempt"]
    assert "https://bank.test/private/accounts" not in api.urls                    # the site's own rules, read through the reader, are obeyed
    assert section["crawl_blocked"]["direct_not_reached"] is True and section["crawl_blocked"]["blocked"] is False
    code, word, sentence = run_outcome(outcome.result, outcome.gates, section)
    assert word == "COMPLETED" and "We read 4 page(s) through Firecrawl" in sentence
    assert "Maya's own requests got no answer on this computer, so direct access was not measured" in sentence and "challenged" not in sentence
    acc1 = next(check for check in outcome.checks if check.check_id == "ACC-1")
    assert acc1.status == "not_assessed" and not [f for c in outcome.checks if c.check_id.startswith("ACC") for f in c.findings]


def test_rfc_9309_is_applied_to_the_answer_firecrawl_got(tmp_path, no_lookups):
    outcome = audit_with_no_network()
    down = Firecrawl(responder=lambda body: httpx.Response(200, json={"success": True, "data": {"rawHtml": "error", "metadata": {"statusCode": 503}}}))
    info = reader.apply(outcome, CrawlConfig(**QUIET), client_for(tmp_path, down), Options(read_always=True))
    assert down.urls == ["https://bank.test/robots.txt"] and not info["used"]
    assert info["robots"]["mode"] == "disallow_all" and "robots.txt returned 503; RFC 9309: assume complete disallow" in info["robots"]["reason"]


# -- 3. the pre-flight --------------------------------------------------------------------------------------------------
def test_the_preflight_stops_an_audit_this_computer_cannot_run_before_anything_is_requested(dns, monkeypatch):
    gone = socket.gaierror(socket.EAI_NONAME, "x")
    monkeypatch.setattr("maya_audit.audit.Crawler", lambda *a, **k: pytest.fail("nothing may be crawled"))
    doh = dns(system(error=gone), Doh(down={"cloudflare-dns.com", "dns.google"}))
    with pytest.raises(NetworkPreflightFailed) as failed:
        run_audit(f"https://{HOST}/", CrawlConfig(**QUIET))
    assert failed.value.status == "local_network_problem" and failed.value.message == LOCAL_NETWORK_MESSAGE
    assert failed.value.message == "Network problem on this computer (DNS lookup failed). Check VPN / iCloud Private Relay / Wi-Fi and try again."
    assert {name for _ip, _host, _path, name, *_ in doh.seen} == {HOST, resolver.PUBLIC_CHECK_HOST}  # the target, then one public name
    # A name that does not exist is said as that, and is not a network problem.
    dns(system(error=gone), Doh({HOST: "nxdomain"}))
    with pytest.raises(NetworkPreflightFailed) as missing:
        run_audit(f"https://{HOST}/", CrawlConfig(**QUIET))
    assert missing.value.status == "host_not_found" and "does not exist" in missing.value.message and "spelling" in missing.value.message
    # A working lookup passes, whoever answered; addresses that need no lookup are not checked.
    dns(system(hang=False, error=socket.gaierror(socket.EAI_AGAIN, "x")), Doh({HOST: ["93.184.216.34"]}))
    assert network_preflight(f"https://{HOST}/")["answered_by"] == "doh:cloudflare"
    assert network_preflight("http://127.0.0.1:8000/") is None and network_preflight("http://demo-shop.localhost/") is None


def test_the_command_line_says_it_is_this_computer_writes_no_report_and_spends_nothing(dns, monkeypatch, tmp_path, capsys):
    from maya_audit import cli
    dns(system(error=socket.gaierror(socket.EAI_NONAME, "x")), Doh(down={"cloudflare-dns.com", "dns.google"}))
    out = tmp_path / "report.json"
    assert cli.main(["crawl", f"https://{HOST}/", "--max-pages", "5", "--json", str(out), "--no-firecrawl"]) == 2
    printed = capsys.readouterr()
    assert "Network problem on this computer (DNS lookup failed). Check VPN / iCloud Private Relay / Wi-Fi and try again." in printed.err
    assert "nothing was spent" in printed.err and not out.exists() and "Blocker" not in printed.out + printed.err


def test_the_web_app_ends_the_audit_with_the_same_message_and_no_findings(monkeypatch, web):
    import test_web_app as T
    from maya_audit_web import runner as runner_module

    def no_network(*args, **kwargs):
        raise NetworkPreflightFailed("local_network_problem", LOCAL_NETWORK_MESSAGE, {"host": "demo-shop.localhost"})
    monkeypatch.setattr(runner_module, "run_audit", no_network)
    client = web()
    audit = T.start(client, T.plan(client))
    assert audit["state"] == "failed"
    assert "Network problem on this computer (DNS lookup failed)" in json.dumps(audit) and "there are no findings" in json.dumps(audit)
    assert "local_network_problem" in json.dumps(audit)
    assert client.get(f"{T.API}/audits/{audit['id']}/result").status_code != 200 and client.provider.requests == []


# -- 6. a challenge page is never content ---------------------------------------------------------------------------------
def test_bot_checks_are_recognised_by_title_marker_header_and_202():
    blocked = lambda status, headers, body: classify_fetch(status, headers, body.encode(), None)  # noqa: E731
    assert blocked(200, {}, "<title>Just a moment...</title>").fetch_class.value == "blocked"
    assert blocked(200, {}, "<title>Attention Required! | Cloudflare</title>").fetch_class.value == "blocked"
    assert blocked(403, {}, "<script src='/cdn-cgi/challenge-platform/h/b/orchestrate'></script>").fetch_class.value == "blocked"
    assert blocked(503, {}, "<p>Verifying you are human. This may take a few seconds.</p>").fetch_class.value == "blocked"
    assert blocked(503, {}, "<div id='cf-browser-verification'></div>").fetch_class.value == "blocked"
    assert blocked(200, {"cf-mitigated": "challenge"}, "<html></html>").fetch_class.value == "blocked"
    assert blocked(200, {}, "<meta http-equiv='refresh' content='0;/.well-known/sgcaptcha/?r=%2F'>").fetch_class.value == "blocked"
    accepted = blocked(202, {}, "<html><body></body></html>")
    assert accepted.fetch_class.value == "blocked" and accepted.confidence.value != "verified" and "202" in accepted.evidence[0]
    # A rate limit stays a rate limit even when Cloudflare marks it; an ordinary page that mentions these words stays a page.
    assert blocked(429, {"cf-mitigated": "challenge"}, "").fetch_class.value == "rate_limited"
    assert blocked(200, {}, "<title>How Cloudflare works</title><p>You may see verifying you are human, or challenge-platform scripts.</p>").fetch_class.value == "ok"
    assert blocked(503, {}, "<h1>Maintenance</h1>").fetch_class.value == "ok"


@pytest.mark.parametrize("answer", [{"rawHtml": "<html><title>Just a moment...</title><body>Checking</body></html>", "metadata": {"statusCode": 200}},
                                    {"rawHtml": "<html><body><h1>Real looking page</h1><p>" + "words " * 80 + "</p></body></html>", "metadata": {"statusCode": 202}},
                                    {"rawHtml": "<html><body>Verifying you are human</body></html>", "metadata": {"statusCode": 503}}])
def test_a_challenge_page_handed_back_by_the_reader_is_never_audited_as_content(tmp_path, no_lookups, answer):
    from test_firecrawl import blocked_audit

    def challenge(body):
        if body["url"].endswith("robots.txt"):
            return None
        return httpx.Response(200, json={"success": True, "data": answer})
    api = Firecrawl(SITE, challenge)
    outcome = blocked_audit()
    info = reader.apply(outcome, CrawlConfig(**{**QUIET, "max_pages": 10}), client_for(tmp_path, api), Options(read_always=True))
    assert not info["used"] and not info.get("pages_read") and all(row["outcome"] != "read" for row in info["pages"])
    assert info["pages"][0]["outcome"] == "blocked" and not info["checks_from_firecrawl"]


# -- 7. the ordinary word on its own ---------------------------------------------------------------------------------------
def test_the_bare_ordinary_word_is_ambiguous_and_the_name_with_a_qualifier_stays_branded():
    names = insights.brand_words("Maximum", "maximum.com")
    common = insights.common_word_brand("Maximum", "maximum.com")
    vocabulary = insights.site_vocabulary(["Maximum is an operating system for banks", "Careers"], names)
    sort = lambda keyword: insights.classify_keyword(keyword, names, vocabulary, common)  # noqa: E731
    assert common == "maximum" and sort("maximum") == "ambiguous" and sort("Maximum ") == "ambiguous"
    assert sort("maximum login") == "branded" and sort("maximum bank") == "branded" and sort("maximum careers") == "branded"
    assert sort("maximum heart rate") == "unrelated" and sort("banks operating system") == "relevant"
    # A specific name is never ambiguous.
    specific = insights.brand_words("Moodist", "moodist.example")
    assert insights.classify_keyword("moodist", specific, set(), insights.common_word_brand("Moodist", "moodist.example")) == "branded"
