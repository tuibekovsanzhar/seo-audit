"""Stage 1 regressions: all network traffic uses MockTransport, never sockets."""
from dataclasses import replace
import json
import time

import httpx
import pytest

from maya_audit.audit import run_audit
from maya_audit.config import CrawlConfig
from maya_audit.dataforseo.client import DataForSEOClient
from maya_audit.dataforseo.credentials import Credentials
from maya_audit.dataforseo.ledger import Ledger
from maya_audit.dataforseo import panel
from maya_audit.evidence_store import save_evidence
from maya_audit.fetcher import Fetcher
from maya_audit.findings import CheckResult
from maya_audit.index_data import inspect_tls, _gsc_inspect, _bing_url_info
from maya_audit.models import GateResult, Confidence
from maya_audit.progress import Hooks
from maya_audit.report import build_report, render_markdown, run_outcome
from maya_audit.scratchpad import Scratchpad

QUIET = dict(request_delay_s=0, robots_samples=1, render_enabled=False, prf_enabled=False,
             probes_enabled=False, refetch_delay_s=0, soft_404_probe=False, time_limit_s=120)


from fakeserver.stage1 import mock_site


def audit(count=3, **settings):
    transport, seen = mock_site(count)
    outcome = run_audit('http://127.0.0.1/', CrawlConfig(**{**QUIET, **settings}), transport=transport)
    return outcome, seen


def test_int4_violation_degrades_cli_verdict():
    outcome, _ = audit()
    gate = GateResult('INT-4', 'Politeness', 'violation', Confidence.VERIFIED, 'wrong identity')
    assert run_outcome(outcome.result, [gate])[0:2] == (1, 'DEGRADED')
    assert 'integrity violation' in render_markdown(outcome.result, [gate], outcome.checks)


def test_markdown_includes_answer_results_without_inventing_visibility():
    outcome, _ = audit()
    answers = [CheckResult('ANS-1', 'Citations', 'observed', 'Zero citations in supplied sample',
                           observations=[{'engine': 'Example', 'citations': 0}]),
               CheckResult('ANS-2', 'Claims', 'not_assessed', 'No claims supplied')]
    md = render_markdown(outcome.result, outcome.gates, answers)
    assert 'ANS-1' in md and 'ANS-2' in md and 'Zero citations in supplied sample' in md
    assert '"citations": 0' in md and 'No claims supplied' in md
    report = build_report(outcome.result, outcome.gates, answers)
    assert report['checks'] == [] and len(report['answer_engine_panel']) == 2


@pytest.mark.parametrize('failure', ['billed', 'timeout', 'invalid', 'disconnect', 'server'])
def test_failed_paid_calls_are_displayed_and_not_retried(tmp_path, failure):
    seen = []
    def respond(request):
        seen.append(request)
        if failure == 'timeout':
            raise httpx.ReadTimeout('synthetic')
        if failure == 'disconnect':
            raise httpx.ReadError('synthetic')
        if failure == 'invalid':
            return httpx.Response(200, text='invalid JSON')
        if failure == 'server':
            return httpx.Response(503, text='unavailable')
        return httpx.Response(200, json={'status_code': 40501, 'status_message': 'refused', 'cost': .01})
    plan = panel.audit_plan('https://example.com')[:1]
    client = DataForSEOClient(Credentials('synthetic', 'synthetic'), Ledger(tmp_path / 'ledger'), None,
                             transport=httpx.MockTransport(respond))
    try:
        result = panel.run_checks(plan, client)
        assert result['status'] == 'not_assessed' and len(seen) == 1
        assert result['cost_usd'] == client.ledger.spent_today() > 0
        assert result['cost_usd'] == (.01 if failure == 'billed' else result['estimated_usd'])
        assert 'spend or reserved estimate' in panel.render_markdown(result)
    finally:
        client.close()


@pytest.mark.parametrize('stopped', [True, False])
def test_tls_and_apis_obey_stop_and_deadline(monkeypatch, stopped):
    import socket
    monkeypatch.setattr(socket, 'create_connection', lambda *a, **k: pytest.fail('TLS must not connect'))
    transport = httpx.MockTransport(lambda r: pytest.fail('API must not send'))
    cfg = CrawlConfig(**QUIET, gsc_access_token='synthetic', gsc_site_url='http://127.0.0.1/',
                      bing_api_key='synthetic', bing_site_url='http://127.0.0.1/')
    fetcher = Fetcher(cfg.user_agent, 1, 0, transport)
    if stopped:
        fetcher.stop_check = lambda: True
    else:
        fetcher.deadline_mono = time.monotonic() - 1
    try:
        assert inspect_tls('127.0.0.1', 443, 1, None, fetcher=fetcher)['checked'] is False
        assert _gsc_inspect(cfg, ['http://127.0.0.1/'], fetcher)['results'][0]['error'] == 'TimeoutException'
        assert _bing_url_info(cfg, ['http://127.0.0.1/'], fetcher)['results'][0]['error'] == 'TimeoutException'
        assert fetcher.log == []
    finally:
        fetcher.close()


def test_tls_rejects_private_address_before_connect(monkeypatch):
    import socket
    monkeypatch.setattr(socket, 'create_connection', lambda *a, **k: pytest.fail('unsafe TLS connection'))
    assert inspect_tls('10.0.0.1', 443, 1, None)['checked'] is False


def test_resume_rejects_wrong_target_settings_and_missing_database_before_requests(tmp_path):
    path = str(tmp_path / 'crawl.db')
    first, _ = audit(5, max_pages=2, db_path=path)
    with Scratchpad.read_only(path) as pad:
        sessions_before = pad.sessions()
    transport = httpx.MockTransport(lambda r: pytest.fail('invalid resume must not request'))
    for url, settings in [('http://127.0.0.1/other', {}), ('http://127.0.0.1/', {'max_body_bytes': 100})]:
        with pytest.raises(ValueError, match='Resume target or audit settings'):
            run_audit(url, CrawlConfig(**{**QUIET, 'db_path': path, 'resume': True, **settings}), transport)
    with Scratchpad.read_only(path) as pad:
        assert pad.sessions() == sessions_before
    with pytest.raises(ValueError, match='existing crawl database'):
        audit(db_path=str(tmp_path / 'missing.db'), resume=True)
    resumed, seen = audit(5, max_pages=10, db_path=path, resume=True)
    assert len(resumed.result.pages) == 5
    assert 'http://127.0.0.1/' not in seen
    assert 'Earlier pages were not fetched again' in render_markdown(resumed.result, resumed.gates, resumed.checks)


def test_500_page_audit_and_evidence_caps(tmp_path):
    outcome, seen = audit(500, max_pages=500)
    assert len(outcome.result.pages) == 500
    index = save_evidence(outcome.result, CrawlConfig(), tmp_path / 'evidence', 'all')
    assert len(index['pages']) == 500 and index['not_saved'] == []
    assert index['total_bytes'] <= index['limits']['total_bytes']
    report = build_report(outcome.result, outcome.gates, outcome.checks)
    assert report['page_counts']['pages_checked'] == 500
    assert len(json.dumps(report)) < 30_000_000


def test_transport_pins_ip_preserves_host_and_tls_name(monkeypatch):
    import socket
    from maya_audit.network import PublicTransport
    calls, sent = [], []
    def resolve(host, port, **kwargs):
        calls.append(host)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', port))]
    def send(self, request):
        sent.append(request)
        return httpx.Response(200, content=b'ok')
    monkeypatch.setattr(socket, 'getaddrinfo', resolve)
    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', send)
    with httpx.Client(transport=PublicTransport(allow_loopback=False)) as client:
        response = client.get('https://example.test/path')
    assert calls == ['example.test']
    assert sent[0].url.host == '93.184.216.34'
    assert sent[0].headers['host'] == 'example.test'
    assert sent[0].extensions['sni_hostname'] == 'example.test'
    assert str(response.url) == 'https://example.test/path'


@pytest.mark.parametrize('address', ['10.0.0.1', '169.254.169.254', '127.0.0.1', '::1'])
def test_transport_rejects_mixed_dns_answers(monkeypatch, address):
    import socket
    from maya_audit.network import PublicTransport
    from maya_audit.urls import UnsafeTargetError
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', (ip, 443)) for ip in ['93.184.216.34', address]])
    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', lambda *a: pytest.fail('unsafe connection'))
    with httpx.Client(transport=PublicTransport(allow_loopback=False)) as client:
        with pytest.raises(UnsafeTargetError):
            client.get('https://example.test/')


def test_stop_during_stream_discards_partial_page():
    stopped = False
    class Body(httpx.SyncByteStream):
        def __iter__(self):
            nonlocal stopped
            yield b'<html>'
            stopped = True
            yield b'incomplete'
    fetcher = Fetcher('Maya-Test', 1, 0, httpx.MockTransport(lambda r: httpx.Response(200, stream=Body())))
    fetcher.stop_check = lambda: stopped
    try:
        response = fetcher.get('http://127.0.0.1/', 'page', 1000)
        assert fetcher.stopped and response.status is None and response.body == b''
        assert fetcher.deadline_hits == 1
    finally:
        fetcher.close()


def test_api_deadline_mid_sequence_prevents_further_requests(monkeypatch):
    import maya_audit.index_data as module
    real_client = httpx.Client
    stopped, sent = False, []
    def respond(request):
        nonlocal stopped
        sent.append(request)
        stopped = True
        return httpx.Response(200, json={})
    monkeypatch.setattr(module.httpx, 'Client', lambda **kw: real_client(transport=httpx.MockTransport(respond)))
    cfg = CrawlConfig(**QUIET)
    fetcher = Fetcher(cfg.user_agent, 1, 0, httpx.MockTransport(respond))
    fetcher.stop_check = lambda: stopped
    try:
        result = _gsc_inspect(cfg, ['http://127.0.0.1/a', 'http://127.0.0.1/b'], fetcher)
        assert len(sent) == 1 and result['results'][-1]['error'] == 'TimeoutException'
    finally:
        fetcher.close()


def test_lite_report_does_not_turn_quotes_into_link_attributes():
    from html.parser import HTMLParser
    from maya_audit_web_lite import inline
    class Links(HTMLParser):
        attrs = []
        def handle_starttag(self, tag, attrs):
            if tag == 'a':
                self.attrs.append(dict(attrs))
    parser = Links()
    parser.feed(inline('[text](https://example.test/"onmouseover="alert(1)) <script>bad()</script>'))
    assert parser.attrs and all('onmouseover' not in attrs for attrs in parser.attrs)
    assert '<script>' not in inline('<script>bad()</script>')
    assert '<a ' not in inline('[bad](javascript:alert(1))')


def test_cli_uses_existing_engine_with_mock_transport(monkeypatch, tmp_path, capsys):
    from maya_audit import cli
    transport, _ = mock_site(3)
    monkeypatch.setattr(cli, 'run_audit', lambda url, cfg: run_audit(url, replace(cfg, **QUIET), transport))
    json_path, md_path = tmp_path / 'report.json', tmp_path / 'report.md'
    code = cli.main(['crawl', 'http://127.0.0.1/', '--json', str(json_path), '--markdown', str(md_path)])
    assert code == 0
    assert json.loads(json_path.read_text(encoding="utf-8"))['page_counts']['pages_checked'] == 3
    assert 'ANS-1' in md_path.read_text(encoding="utf-8")


def test_api_private_endpoint_is_refused_before_http_transport(monkeypatch):
    from maya_audit.urls import UnsafeTargetError
    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', lambda *a: pytest.fail('private API sent'))
    fetcher = Fetcher('Maya-Test', 1, 0, block_loopback=True)
    try:
        with httpx.Client() as client:
            with pytest.raises(UnsafeTargetError):
                fetcher.api_request(client, 'GET', 'http://10.0.0.1/')
    finally:
        fetcher.close()


def test_transport_checks_stop_again_after_dns(monkeypatch):
    import socket
    from maya_audit.network import PublicTransport
    stopped = False
    def resolve(*args, **kwargs):
        nonlocal stopped
        stopped = True
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443))]
    fetcher = Fetcher('Maya-Test', 1, 0, httpx.MockTransport(lambda r: httpx.Response(200)))
    fetcher.stop_check = lambda: stopped
    monkeypatch.setattr(socket, 'getaddrinfo', resolve)
    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', lambda *a: pytest.fail('sent after stop'))
    try:
        with httpx.Client(transport=PublicTransport(before_connect=fetcher.remaining_timeout)) as client:
            with pytest.raises(httpx.TimeoutException):
                client.get('https://example.test/')
    finally:
        fetcher.close()


def test_performance_api_helpers_do_not_send_after_stop():
    from maya_audit.perf_data import _crux, _psi_runs
    transport = httpx.MockTransport(lambda r: pytest.fail('performance API sent after stop'))
    cfg = CrawlConfig(**QUIET)
    fetcher = Fetcher(cfg.user_agent, 1, 0, transport)
    fetcher.stop_check = lambda: True
    try:
        with httpx.Client(transport=transport) as client:
            assert all(r['error'] == 'TimeoutException' for r in _psi_runs(client, cfg, 'http://127.0.0.1/', fetcher)['runs'])
            assert all(r['error'] == 'TimeoutException' for r in _crux(client, cfg, 'http://127.0.0.1/', fetcher)['attempts'])
    finally:
        fetcher.close()


def test_serialization_does_not_deepcopy_private_working_data():
    from maya_audit.models import to_jsonable
    class WorkingData:
        def __deepcopy__(self, memo):
            pytest.fail('serialization must not copy private working data')
    outcome, _ = audit()
    outcome.result.pages[0].analysis['_scratch'] = WorkingData()
    outcome.result.robots_policy_by_origin = {'private': WorkingData()}
    report = to_jsonable(outcome.result)
    assert 'robots_policy_by_origin' not in report
    assert '_scratch' not in report['pages'][0]['analysis']


def test_evidence_total_byte_limit_discloses_omissions(tmp_path, monkeypatch):
    from maya_audit import evidence_store
    outcome, _ = audit(3)
    monkeypatch.setattr(evidence_store, 'EVIDENCE_MAX_TOTAL_BYTES', 1000)
    index = save_evidence(outcome.result, CrawlConfig(), tmp_path / 'evidence', 'all')
    assert index['total_bytes'] <= 1000
    assert index['not_saved'] and len(index['pages']) + len(index['not_saved']) == 3
    assert all('size limit' in row['reason'] for row in index['not_saved'])


@pytest.mark.parametrize('stop', [True, False])
def test_paid_plan_stops_before_reserving_or_sending(tmp_path, stop):
    client = DataForSEOClient(Credentials('synthetic', 'synthetic'), Ledger(tmp_path / 'ledger'), None,
                             transport=httpx.MockTransport(lambda r: pytest.fail('paid request sent')),
                             should_stop=(lambda: True) if stop else None,
                             deadline_mono=None if stop else time.monotonic() - 1)
    try:
        result = panel.run_checks(panel.audit_plan('https://example.com'), client)
        assert result['requests_sent'] == 0 and result['cost_usd'] == 0
        assert client.ledger.calls() == []
        assert all(c['status'] == 'not_assessed' for c in result['checks'])
    finally:
        client.close()


def test_stop_during_connection_dns_is_not_logged_as_a_sent_request(monkeypatch):
    import socket
    calls = 0
    def resolve(*args, **kwargs):
        nonlocal calls
        calls += 1
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443))]
    monkeypatch.setattr(socket, 'getaddrinfo', resolve)
    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', lambda *a: pytest.fail('sent after DNS stop'))
    fetcher = Fetcher('Maya-Test', 1, 0)
    fetcher.stop_check = lambda: calls >= 1  # one lookup serves the safety check and the connection (maya_audit.resolver)
    try:
        response = fetcher.get('https://example.test/', 'page', 100)
        assert response.error == 'audit_deadline_skipped'
        assert fetcher.log == [] and fetcher.stopped
    finally:
        fetcher.close()


def test_transport_falls_back_to_the_next_validated_address(monkeypatch):
    """A host listing an unreachable address first (IPv6 on an IPv4-only network) must still be fetched."""
    import socket
    from maya_audit.network import PublicTransport
    tried = []
    def resolve(host, port, **kwargs):
        return [(socket.AF_INET6, socket.SOCK_STREAM, 6, '', ('2606:2800:220:1:248:1893:25c8:1946', port, 0, 0)),
                (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', port))]
    def send(self, request):
        tried.append(request.url.host)
        if ':' in request.url.host:
            raise httpx.ConnectError('unreachable')
        return httpx.Response(200, content=b'ok')
    monkeypatch.setattr(socket, 'getaddrinfo', resolve)
    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', send)
    with httpx.Client(transport=PublicTransport(allow_loopback=False)) as client:
        assert client.get('https://example.test/').content == b'ok'
    assert tried == ['2606:2800:220:1:248:1893:25c8:1946', '93.184.216.34']


def test_a_paid_call_that_never_connected_costs_nothing(tmp_path):
    def respond(request):
        raise httpx.ConnectError('synthetic')
    client = DataForSEOClient(Credentials('synthetic', 'synthetic'), Ledger(tmp_path / 'ledger'), None,
                             transport=httpx.MockTransport(respond))
    try:
        result = panel.run_checks(panel.audit_plan('https://example.com')[:1], client)
        assert result['status'] == 'not_assessed' and result['cost_usd'] == 0 == client.ledger.spent_today()
        assert result['calls'][0]['billing_status'] == 'failed'
    finally:
        client.close()
