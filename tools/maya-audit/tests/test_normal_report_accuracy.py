"""Normal web/print/download safeguards: synthetic evidence, never customer data or live sites."""
import copy
import json
from types import SimpleNamespace

import httpx
import pytest

from maya_audit.config import CrawlConfig
from maya_audit.index_data import _walk_again, redirect_verdict
from maya_audit.checks.index import idx3_redirects
from maya_audit.report import build_report
from maya_audit_web import demo, pdf, practical, strings, summary, wording
from test_false_alarms import no_lookups  # noqa: F401
from test_preview16_false_alarms import cookie_site
from test_report_agreement import demo_app, audit  # noqa: F401
from test_web_app import API

URL = 'https://synthetic.test/ticari'


def cycle():
    return {'outcome': 'loops', 'hops': [{'url': URL, 'status': 301, 'location': URL,
                                         'requested_at': '2026-10-15T06:30:56+00:00'}]}


def entry(cookie=None):
    value = {'attempts': [cycle() for _ in range(3)]}
    if cookie is not None:
        value['cookie_walk'] = cookie
    return value


@pytest.mark.parametrize('walk', [None, {}, {'outcome': 'not_checked', 'reason': 'timeout'},
                                  {'outcome': 'answered', 'final_status': 403},
                                  {'outcome': 'not_checked', 'reason': 'hop limit'},
                                  {'outcome': 'loops', 'hops': [], 'reason': 'no end within 10 hops'},
                                  {'outcome': 'loops', 'cycle_observed': True, 'hops': []}])
def test_idx3_missing_or_incomplete_cookie_walk_is_uncertain(walk):
    assert redirect_verdict(entry(walk), 3) == 'unchecked'


def test_idx3_proven_cycle_in_both_contexts_is_persistent_but_not_universal():
    assert redirect_verdict(entry(cycle()), 3) == 'always'
    assert redirect_verdict({'attempts': [cycle()], 'cookie_walk': cycle()}, 3) == 'unchecked'


@pytest.mark.parametrize('cookies,expected', [(True, 'cookie'), (False, 'intermittent')])
def test_idx3_real_page_success_has_the_correct_cookie_context(cookies, expected):
    walk = {'outcome': 'resolves', 'readable_html': True, 'hops': [{'cookie_sent': cookies}]}
    assert redirect_verdict(entry(walk), 3) == expected
    newer = entry()
    newer['attempts'][-1] = walk
    assert redirect_verdict(newer, 3) == 'intermittent'


def walk_response(status, body=b'', headers=None):
    return SimpleNamespace(status=status, body=body, headers=headers or {}, error=None,
                           set_cookies=[], started_at='2026-10-15T19:50:24+00:00', truncated=False)


def run_walk(responses, **options):
    responses = iter(responses)
    fetcher = SimpleNamespace(deadline_mono=None, get=lambda *a, **kw: next(responses))
    policy = SimpleNamespace(decide=lambda *a: SimpleNamespace(allowed=True))
    return _walk_again(fetcher, URL, CrawlConfig(**options), policy, 'https://synthetic.test')


def test_idx3_hop_limit_without_repeated_state_is_not_a_cycle():
    walk = run_walk([walk_response(301, headers={'location': '/next'}),
                     walk_response(301, headers={'location': '/another'})], redirect_recheck_max_hops=2)
    assert walk['outcome'] == 'not_checked' and walk['cycle_observed'] is False
    assert 'hop limit' in walk['reason']
    assert redirect_verdict(entry(walk), 3) == 'unchecked'


@pytest.mark.parametrize('body,headers', [(b'', {'content-type': 'text/html'}),
    (b'<title>Just a moment...</title>' + b' ' * 600, {'content-type': 'text/html'}),
    (b'not an html page' * 100, {'content-type': 'application/json'})])
def test_idx3_status_200_without_readable_page_is_not_success(body, headers):
    walk = run_walk([walk_response(200, body, headers)])
    assert walk['outcome'] == 'answered' and walk['readable_html'] is False
    assert redirect_verdict(entry(walk), 3) == 'unchecked'


def test_idx3_walk_records_genuine_cycle_and_healthy_html():
    walk = run_walk([walk_response(301, headers={'location': '/ticari'})])
    assert walk['outcome'] == 'loops' and walk['cycle_observed'] is True
    good = run_walk([walk_response(200, b'<html><main>' + b'Useful text ' * 100 + b'</main></html>', {'content-type': 'text/html'})])
    assert good['outcome'] == 'resolves' and good['readable_html'] is True


@pytest.mark.parametrize('cookie_opens,severity', [(False, 'S1'), (True, 'S3')])
def test_idx3_collector_keeps_native_cookie_context_and_request_times(no_lookups, cookie_opens, severity):
    outcome = cookie_site(cookie_opens=cookie_opens)
    [finding] = outcome.by_id['IDX-3'].findings
    assert finding.severity.value == severity
    ev = finding.evidence
    assert ev['cookie_walks'] and ev['rechecks']
    assert all(h['requested_at'] for attempts in ev['rechecks'].values() for a in attempts for h in a['hops'])
    assert 'never' not in finding.title and 'crawlers keep no cookies' not in finding.how_to_fix
    # Losing a cookie check must retain the observed issue with explicit uncertainty, not a blocker.
    for value in outcome.result.index.redirect_rechecks.values():
        value.pop('cookie_walk', None)
    [incomplete] = idx3_redirects(outcome.result, CrawlConfig()).findings
    assert incomplete.severity.value == 'S3' and 'verification is incomplete' in incomplete.title


@pytest.mark.parametrize('lang', ['en', 'tr'])
def test_ordinary_summary_print_and_download_share_safe_advice_for_saved_reports(demo_app, monkeypatch, no_lookups, lang):
    outcome = cookie_site(cookie_opens=False)
    report = json.loads(json.dumps(build_report(outcome.result, outcome.gates, outcome.checks), default=str))
    # Legacy saved assertions must be qualified without rewriting evidence or silently hiding the finding.
    finding = next(c for c in report['checks'] if c['check_id'] == 'IDX-3')['findings'][0]
    finding['title'] = '1 redirect loop(s): the URL never resolves'
    finding['how_to_fix'] = 'Fix the redirect rules so each chain ends at a real 200 page.'
    # Add synthetic copies of measured checks to exercise ordinary practical recommendations.
    prototype = copy.deepcopy(finding)
    for check_id,title,fix in [
        ('TSEO-1', '1 page title(s) above the 60-character guidance band', 'A concise, page-specific title around 50–60 characters, where that fits.'),
        ('STR-14', '1 link(s) on 1 page(s) name their target only with generic text: "details" (1)',
         'Use the page\'s topic as the link text ("Şizofreni tedavisi" instead of "Devamı"), or add the topic to the link with a visually hidden label.'),
        ('RND-7', '1 page(s) have less than 30% of their text in the main content',
         "Mark the page's own content with one <main> element, so the menu, footer and sidebars sit outside it. This is page structure: no JavaScript change is needed."),
    ]:
        # Copies of the redirect loop: not the loop's rule (DECISIONS 315 merges a redirect chain's findings by rule).
        f = {**copy.deepcopy(prototype), 'rule_id': None, 'dedup_key': None, 'check_id': check_id, 'id': check_id + '-synthetic', 'title': title, 'how_to_fix': fix,
             'severity': 'S4', 'evidence': {'pages': [{'url': URL, 'basis': '<main>/<article> text'}]}}
        next(c for c in report['checks'] if c['check_id'] == check_id)['findings'].append(f)
    for check in (report['checks']):
        for f in check['findings']:
            if f['check_id'] == 'IDX-3':
                f['evidence'].pop('cookie_walks', None)
    one = audit(demo_app, demo.BANK)
    path = demo_app.app.state.runner.artifacts(one['id']) / 'report.json'
    reader = json.loads(path.read_text(encoding="utf-8"))['firecrawl']
    reader['pages'][0].update(url='https://demo-kart.test/ticari', from_cache=True,
                              observed_at='2026-10-15T06:43:23+00:00')
    report['firecrawl'] = reader
    before = copy.deepcopy(report)
    path.write_text(json.dumps(report))
    from maya_audit_web.app import LANGUAGE_COOKIE
    demo_app.cookies.set(LANGUAGE_COOKIE, lang)
    view = demo_app.get(f'{API}/audits/{one["id"]}/summary')
    assert view.status_code == 200
    printed = demo_app.get(f'{API}/audits/{one["id"]}/print?full=true&lang={lang}')
    assert printed.status_code == 200
    captured = []
    def capture(html, **kw):
        captured.append(html)
        return b'%PDF-synthetic-route-check'
    monkeypatch.setattr(pdf, 'to_pdf', capture)
    downloaded = demo_app.get(f'{API}/audits/{one["id"]}/downloads/pdf?lang={lang}')
    assert downloaded.status_code == 200 and downloaded.content.startswith(b'%PDF')
    assert captured and 'text/html' in printed.headers['content-type']
    for text in [printed.text, captured[0]]:
        for banned in ('Şizofreni', 'Kettles', 'kettles', 'cannot be read by anyone', 'the URL never resolves', 'the address never resolves', 'crawlers keep no cookies'):
            assert banned not in text
        assert ('persistence is not established' if lang == 'en' else 'sürekliliği kanıtlamıyor') in text
        assert ('Google limits' if lang == 'en' else 'Google sınırı') in text
        assert ('Low content ratio' if lang == 'en' else 'Düşük içerik oranı') in text
    assert json.loads(path.read_text(encoding="utf-8")) == before  # presentation never rewrites historical evidence/severity
    assert view.json()['counts']['by_severity']['S1'] == 1



@pytest.mark.parametrize('lang', ['en', 'tr'])
def test_normal_legacy_date_and_character_advice_does_not_claim_unmeasured_causes(lang):
    fixed, ok = wording.fix("Set Last-Modified header from the content's real last edit.", lang)
    assert ok and ('Verify' if lang == 'en' else 'doğrulayın') in fixed
    from maya_audit_web.catalog import note
    strings.set_language(lang)
    try:
        why = note('STR-13', '1 page(s) have invisible characters in the main text (10 in all)')['why']
        assert ('does not prove' if lang == 'en' else 'kanıtlamaz') in why
    finally:
        strings.set_language('en')


def test_idx3_legacy_cookie_hop_cutoff_cannot_confirm_a_cycle():
    walk = cycle()
    walk['hops'][0].update(cookie_sent=False, set_cookie=True)
    walk['hops'].append({'url': URL, 'status': 301, 'location': URL, 'cookie_sent': True})
    walk['reason'] = 'no end within 2 hops'
    assert redirect_verdict(entry(walk), 3) == 'unchecked'


def test_idx3_legacy_200_is_status_evidence_not_proof_of_readable_page():
    legacy = entry()
    legacy['attempts'][-1] = {'outcome': 'resolves', 'final_status': 200, 'hops': [{'url': URL, 'status': 200}]}
    assert redirect_verdict(legacy, 3) == 'unchecked'
    row = summary.item({'id': 'legacy', 'check_id': 'IDX-3', 'severity': 'S3', 'confidence': 'verified',
                        'title': '1 URL(s) intermittently redirect to themselves; the page loads on another try',
                        'evidence': {'rechecks': {URL: legacy['attempts']}}, 'scope': {'urls': [URL], 'count': 1}})
    assert 'page content not verified' in row['title_shown']
    assert 'HTTP status only' in row['why']


def test_idx3_readable_crawl_success_before_cyclic_retries_is_retained(no_lookups):
    from test_false_alarms import audited, answer, to_itself
    outcome = audited({'/': lambda n: answer() if n == 1 else to_itself('/')})
    [finding] = outcome.by_id['IDX-3'].findings
    assert finding.severity.value == 'S3'
    assert finding.evidence['native_success_in_crawl'][0]['readable_html'] is True
    assert finding.evidence['native_success_in_crawl'][0]['requested_at']
    report = json.loads(json.dumps(build_report(outcome.result, outcome.gates, outcome.checks), default=str))
    row = next(row for row in summary.search(report,limit=1000)['items'] if row['check_id']=='IDX-3')
    assert 'page loads on another try' in row['title_shown']
    assert 'page content not verified' not in row['title_shown']


@pytest.mark.parametrize('title,kind', [
    ('1 URL(s) have observed redirect cycles; verification is incomplete', 'redirect_self_once'),
    ("1 URL(s) loop in Maya's cookie-less checks; with the cookie the site sets, the page loads", 'redirect_loop'),
])
def test_idx3_page_briefs_preserve_observed_issue_without_universal_claim(title,kind):
    from maya_audit.report import page_item,page_sentence
    finding={'id':'case','check_id':'IDX-3','title':title,'evidence':{},'scope':{'urls':[URL]}}
    item=page_item(finding,URL)
    assert item['kind']==kind
    assert 'never' not in page_sentence(item)


@pytest.mark.parametrize('kind', ['title_long','title_short','description_long','description_short'])
def test_tseo1_normal_page_length_labels_are_guidance_not_technical_limits(kind):
    from maya_audit.report import page_sentence
    for values in ({'characters': 75, 'limit': 60}, {'limit':60}):
        text=page_sentence({'kind':kind,'values':values})
        assert 'editorial guidance band' in text and 'too long' not in text and 'too short' not in text


def test_first_actions_selects_the_new_inspection_instruction_not_an_inferred_cause():
    assert practical.action_sentence('The cause is not established. Inspect the recorded request logs before changing settings.', 'en') == 'Inspect the recorded request logs before changing settings.'
