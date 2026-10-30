"""Offline acceptance regressions: real app routes, qualified source, retained defects."""
from copy import deepcopy
import pytest
from test_web_app import web, error, API  # noqa: F401
from test_report_agreement import demo_app  # noqa: F401
from test_client_report_app import synthetic, endpoint, card_body, request_ok
from maya_audit_web import client_reports as C, pdf

NAV = {'sec-fetch-site': 'cross-site', 'sec-fetch-mode': 'navigate', 'sec-fetch-dest': 'document'}


def test_linked_top_level_landing_is_allowed_but_api_assets_and_frames_are_not(web):
    c = web()
    assert c.get('/', headers=NAV).status_code == 200
    for path in ('/api/v1/audits', '/api/v1/session', '/api/v1/health', '/static/app.js', '/api/v1/audits/anything/downloads/pdf'):
        error(c.get(path, headers=NAV), 403, 'cross_site_request')
    for headers in (dict(NAV, **{'sec-fetch-dest': 'iframe'}), dict(NAV, **{'sec-fetch-mode': 'cors'}),
                    dict(NAV, origin='https://foreign.example'), dict(NAV, host='foreign.example:8770')):
        error(c.get('/', headers=headers), 403, 'host_not_allowed' if 'host' in headers else 'cross_site_request')
    error(c.post('/', headers=NAV), 403, 'cross_site_request')
    assert c.get('/static/app.js', headers={'sec-fetch-site': 'same-origin'}).status_code == 200
    assert c.site.requests == [] and c.provider.requests == []


@pytest.mark.parametrize('claim,field,expected', [
    ('Sayfa hiç kimse tarafından okunamaz', 'title', 'universal access'),
    ('Site tüm kullanıcılara kapalıdır.', 'explanation', 'universal access'),
    ('2 sayfa erişilemiyor', 'title', 'affected-page count'),
    ('2 adresi düzenlemelisiniz.', 'steps', 'affected-page count'),
])
def test_review_cannot_approve_unsupported_scope_or_universal_claim(demo_app, monkeypatch, claim, field, expected):
    one, path, rep = synthetic(demo_app)
    # A number in unrelated page content used to license a changed affected-page count.
    rep['crawl']['pages'][0]['analysis']['title'] = 'Örnek 2 hizmet'
    path.write_text(__import__('json').dumps(rep))
    original = path.read_bytes()
    base = endpoint(demo_app, one)
    work = request_ok(demo_app.post(base, json={}))
    body = card_body(work)
    body[field] = [claim] if field == 'steps' else claim
    work = request_ok(demo_app.put(base + '/cards/f0', json=body))
    work = request_ok(demo_app.post(base + '/review', json={'revision': work['revision'], 'reviewer': 'QA', 'reason': 'Checked'}))
    assert not work['validation']['valid']
    assert any(expected in e for e in work['validation']['errors'])
    called = []
    monkeypatch.setattr(pdf, 'to_pdf', lambda *a, **kw: called.append(True))
    for fmt in ('html', 'pdf'):
        r = demo_app.get(base + '/export/' + fmt + '?mode=final')
        assert r.status_code == 422 and expected in r.text
    assert not called
    draft = demo_app.get(base + '/preview')
    assert draft.status_code == 200 and 'TASLAK' in draft.text
    assert 'Kayıtlı kaynak yargısı' in draft.text
    assert path.read_bytes() == original
    assert demo_app.get(f'{API}/audits/{one["id"]}/downloads/json').content == original


def test_inferred_judgment_keeps_uncertainty_and_critical_measured_defect_survives():
    from test_client_reporting import finding, report
    f = finding(); f.update(confidence='inferred', severity='S1')
    work = C.generate(report('findings', f), 'synthetic')
    c = C.all_cards(work['data'])[0]; values = C.editorial(c); values['references'] = []
    values.update(title='Başlık kesinlikle eksik', explanation='Kesin teknik hata.')
    C.edit(work, c['id'], fields=values); C.review(work, 'QA', 'Checked')
    assert any('preserve source uncertainty' in e for e in C.validation(work)['errors'])
    values.update(title='Başlık incelenmelidir', explanation='Kayıtlı gözlem değerlendirilmelidir.')
    C.edit(work, c['id'], fields=values); C.review(work, 'QA', 'Checked')
    assert not C.judgment_errors(work)
    assert C.validation(work)['verified_findings'] == 0
    f.update(confidence='verified')
    measured = C.generate(report('findings', f), 'measured')
    C.review(measured, 'QA', 'Checked')
    assert not C.judgment_errors(measured)
    assert C.all_cards(measured['data'])[0]['maya']['severity'] == 'S1'
    assert 'Kayıtlı kaynak yargısı' in C.html(measured, draft=True)


def test_healthy_summary_cannot_contradict_retained_findings():
    from test_client_reporting import finding, report
    work = C.generate(report('findings', finding()), 'synthetic')
    C.edit(work, summary={'one_read': 'Site sorunsuz, hiçbir sorun yok.', 'bullets': []})
    C.review(work, 'QA', 'Checked')
    assert any('healthy conclusion' in e for e in C.validation(work)['errors'])
    healthy = C.generate(report(), 'healthy')
    C.edit(healthy, summary={'one_read': 'İncelenen örneklemde hiçbir sorun yok.', 'bullets': []})
    C.review(healthy, 'QA', 'Checked')
    assert not C.judgment_errors(healthy)


@pytest.mark.parametrize('overlap', [False, True])
def test_grouped_page_counts_and_occurrence_units_stay_consistent(overlap):
    from test_client_reporting import finding
    from maya_audit_web import summary, practical
    rows = []
    for name, urls in [('a', ['https://other.test/a']), ('b', ['https://other.test/a' if overlap else 'https://other.test/b'])]:
        f = finding(); f.update(id=name, check_id='STR-14', confidence='verified', title='Repeated block: 1 link(s) have no text')
        f['scope'] = {'kind': 'template', 'count': 1, 'urls': urls}
        f['evidence'] = {'shared_element': {'block': 'footer', 'href': '/target', 'links': 1, 'pages': 1},
                         'links': [{'source': urls[0], 'target': '/target', 'links': 2}]}
        rows.append(summary.item(f))
    row = practical.merged(rows)[0]
    count = 1 if overlap else 2
    assert row['pages_total'] == row['counting']['affected_pages'] == count
    assert row['counting']['listed_unique_pages'] == count
    assert row['counting']['occurrences'] == (None if overlap else 4)
    assert row['counting']['occurrences_per_template'] == 2
    assert row['affects'] == __import__('maya_audit_web.strings', fromlist=['t']).t('result.affects.pages', count=count)
    assert 'unique affected pages: '+str(count) in row['details'][-1]
    # Same title with a different semantic target is a distinct defect.
    rows[1]['semantic_group'] = ('different target',)
    assert len(practical.merged(rows)) == 2


def test_explicit_verification_sample_is_not_a_changed_total_or_live_verification():
    from test_client_reporting import report, finding
    f = finding(); f['scope']['count'] = 3
    work = C.generate(report('findings', f), 'synthetic')
    card = C.all_cards(work['data'])[0]; values = C.editorial(card); values['references'] = []
    values['verify'] = 'Örnek olarak 2 adresi yeniden kontrol etmelisiniz.'
    C.edit(work, card['id'], fields=values); C.review(work, 'QA', 'Checked')
    assert not C.judgment_errors(work)
    assert C.validation(work)['verified_findings'] == 0


def test_group_counts_reach_real_summary_action_plan_and_normal_download(demo_app, monkeypatch):
    import json
    from test_report_agreement import audit
    from maya_audit_web import demo
    from maya_audit.report import problem_summary
    one = audit(demo_app, demo.SHOP)
    path = demo_app.app.state.runner.artifacts(one['id']) / 'report.json'
    rep = json.loads(path.read_text(encoding="utf-8"))
    seed = deepcopy(next(f for c in rep['checks'] for f in c['findings']))
    added = []
    urls = [p['url'] for p in rep['crawl']['pages'][:2]]
    for index, url in enumerate(urls):
        f = deepcopy(seed)
        f.update(id='acceptance-'+str(index), check_id='STR-14', confidence='verified', severity='S4',
                 title='Repeated block: 1 link(s) have no text', how_to_fix='Add a meaningful link label.')
        f['scope'] = {'kind': 'template', 'count': 1, 'urls': [url]}
        f['evidence'] = {'shared_element': {'block': 'footer', 'href': '/target', 'pages': 1, 'links': 1},
                         'links': [{'source': url, 'target': '/target', 'links': 2}]}
        added.append(f)
    rep['checks'][0]['findings'].extend(added)
    findings = [f for c in rep['checks'] for f in c['findings']]
    rep['problem_summary'] = problem_summary(findings, pages_checked=len(rep['crawl']['pages']))
    path.write_text(json.dumps(rep)); original = path.read_bytes()
    base = f'{API}/audits/{one["id"]}'
    view = request_ok(demo_app.get(base+'/practical'))
    rows = [r for r in view['issues'] if 'acceptance-0' in r.get('merged_ids', [r['id']])]
    # Detailed issues retain individual evidence; the action timeline groups it.
    assert rows and rows[0]['pages_total'] == 1
    grouped = next(r for g in view['timeline'] for r in g['items'] if r['id']=='acceptance-0')
    assert grouped['pages_total'] == 2 and '2' in grouped['where']
    plan = request_ok(demo_app.get(base+'/action-plan'))
    row = next(r for g in plan['groups'] for r in g['items'] if r['id']=='acceptance-0')
    assert row['counting']['affected_pages'] == 2 and row['counting']['occurrences'] == 4
    captured = []
    monkeypatch.setattr(pdf, 'to_pdf', lambda html, **kw: captured.append(html) or b'%PDF-fixture')
    downloaded = demo_app.get(base+'/downloads/pdf?full=true')
    assert downloaded.status_code == 200 and captured
    printed = __import__('html').unescape(captured[0])
    assert grouped['what'] in printed and grouped['where'] in printed
    # Individual evidence cards remain one-page records, rather than being rewritten.
    assert 'unique affected pages: 1' in printed
    assert path.read_bytes() == original


def test_old_workspace_gets_visible_source_context_without_rewriting_data():
    from test_client_reporting import report, finding
    work = C.generate(report('findings', finding()), 'old-synthetic')
    card = C.all_cards(work['data'])[0]; card.pop('_source_context')
    before = deepcopy(work)
    assert 'Kayıtlı kaynak yargısı' in C.html(work, draft=True)
    assert work == before
