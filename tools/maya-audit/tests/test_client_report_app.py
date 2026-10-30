"""Normal app client-report lifecycle; synthetic saved evidence and no provider traffic."""
from copy import deepcopy
import json
from pathlib import Path

import pytest
from test_report_agreement import demo_app, audit  # noqa: F401
from test_web_app import API
from test_client_reporting import report, finding, valid_cards, WHEN, URL
from test_keyword_actions import lab
from maya_audit_web import client_reports as C, demo, pdf
from maya_audit.client_reporting import from_maya_report as F


def endpoint(client, one):
    return f'{API}/audits/{one["id"]}/client-report'


def synthetic(client, findings=1):
    one = audit(client, demo.SHOP)
    path = client.app.state.runner.artifacts(one['id']) / 'report.json'
    rep = report('findings', finding())
    # A real synthetic missing heading, not a missing-title claim contradicted by page_facts.title.
    rep['checks'][0]['check_id']='STR-2'
    rep['crawl']['pages'][0]['analysis']['headings']=[]
    rep['checks'][0]['findings'] = [dict(finding(), id=f'f{i}', check_id='STR-2',
        title='The homepage has no meaningful <h1> text', confidence='verified',
        how_to_fix="Add one <h1> that names the page's topic.",
        evidence={'pages':[{'url':URL,'source':'native','requested_at':WHEN,'method':'GET','headings':[]}]}) for i in range(findings)]
    path.write_text(json.dumps(rep))
    return one, path, rep


def card_body(work, card=None):
    card = card or C.all_cards(work['data'])[0]
    result = C.editorial(card)
    result['references'] = []
    return {'revision': work['revision'], **result}


def request_ok(response):
    assert response.status_code == 200, response.text
    return response.json()


def test_profile_confirmed_names_roundtrip_bounds_and_omitted_fields(demo_app):
    url = f'{API}/projects/fiction.example/profile'
    body = {'brand_name': 'Açık Kart', 'brand_aliases': [' AÇIKKART ', 'AÇIKKART'],
            'related_organizations': ['Örnek İş Kurumu']}
    saved = request_ok(demo_app.put(url, json=body))
    assert saved['brand_aliases'] == ['AÇIKKART']
    assert saved['related_organizations'] == ['Örnek İş Kurumu']
    assert demo_app.get(url).json() == saved
    kept = request_ok(demo_app.put(url, json={'brand_name': 'New'}))
    assert kept['related_organizations'] == saved['related_organizations']
    for field, value in [('brand_aliases', ['x']*31), ('related_organizations', ['x'*121]), ('brand_aliases', [''])]:
        assert demo_app.put(url, json={field: value}).status_code == 422
    cleared = request_ok(demo_app.put(url, json={'brand_aliases': [], 'related_organizations': []}))
    assert not cleared['brand_aliases'] and not cleared['related_organizations']


def test_saved_audit_draft_edit_review_validate_html_pdf_and_technical_download(demo_app, monkeypatch):
    one, path, rep = synthetic(demo_app)
    original = path.read_bytes()
    base = endpoint(demo_app, one)
    # All generation must remain offline, even with already-configured providers.
    monkeypatch.setattr('socket.socket.connect', lambda *a, **kw: pytest.fail('client generation connected to network'))
    work = request_ok(demo_app.post(base, json={}))
    assert work['audit_id'] == one['id'] and not work['validation']['valid']
    assert work['validation']['verified_findings'] == 0
    assert work['references'] and work['data']['page_facts'][URL]['text_sample'] is None
    assert demo_app.get(base).json() == work
    repeated = request_ok(demo_app.post(base, json={}))
    assert repeated['revision'] == 1
    # Explicitly edit every supported client field through the normal API.
    body = card_body(work)
    body.update(title='Başlık eksik', explanation='Kayıtlı sayfa başlığı incelenmelidir.',
                steps=['Başlığı düzenlemelisiniz.'], decision='Karar vermelisiniz: Başlığı belirlemelisiniz.',
                owner='İçerik', effort='Küçük', verify='Başlığı yeniden kontrol etmelisiniz.')
    work = request_ok(demo_app.put(base + '/cards/f0', json=body))
    work = request_ok(demo_app.put(base + '/summary', json={'revision': work['revision'],
                      'one_read': 'Kayıtlı başlık incelenmelidir.', 'bullets': ['Başlık için karar gereklidir.']}))
    work = request_ok(demo_app.post(base + '/review', json={'revision': work['revision'], 'reviewer': 'Owner',
                       'reason': 'Tüm bulgular ve kayıtlı kanıtlar incelendi.'}))
    assert work['validation']['valid'], work['validation']['errors']
    assert work['validation']['editorial_status'] == 'reviewed' and work['validation']['verified_findings'] == 0
    assert request_ok(demo_app.post(base + '/validate', json={}))['valid']
    # HTML and PDF share content; freeze the explicitly recorded export clock for byte equality.
    exported_at = C.now()
    monkeypatch.setattr(C, 'now', lambda: exported_at)
    final = demo_app.get(base + '/export/html?mode=final')
    assert final.status_code == 200 and 'Başlık eksik' in final.text and 'TASLAK — DOĞRULANMADI' not in final.text
    assert 'source_digest' in final.text and 'İçerik incelemesi canlı doğrulama değildir' in final.text
    captured = []
    monkeypatch.setattr(pdf, 'to_pdf', lambda html, **kw: captured.append(html) or b'%PDF-synthetic')
    response = demo_app.get(base + '/export/pdf?mode=final')
    assert response.status_code == 200 and response.content == b'%PDF-synthetic'
    assert captured == [final.text]
    assert demo_app.get(f'{API}/audits/{one["id"]}/downloads/json').content == original
    assert path.read_bytes() == original
    # Reviewed is not verified; any subsequent save invalidates the whole review.
    next_work = request_ok(demo_app.put(base + '/cards/f0', json=card_body(work)))
    assert next_work['review'] is None and not next_work['validation']['valid']
    assert demo_app.get(base + '/export/html?mode=final').status_code == 422
    assert 'TASLAK — DOĞRULANMADI' in demo_app.get(base + '/preview').text


@pytest.mark.parametrize('change', ['number', 'forged', 'stale', 'source', 'unsupported', 'assertion'])
def test_final_rejects_unsupported_claims_and_revision_conflicts(demo_app, change):
    one, path, rep = synthetic(demo_app)
    base = endpoint(demo_app, one)
    work = request_ok(demo_app.post(base, json={}))
    body = card_body(work)
    if change == 'forged':
        body['evidence'] = {'verified_live': WHEN}
        assert demo_app.put(base + '/cards/f0', json=body).status_code == 422
        return
    if change == 'stale':
        request_ok(demo_app.put(base + '/cards/f0', json=body))
        assert demo_app.put(base + '/cards/f0', json=body).status_code == 409
        return
    if change == 'source':
        rep['crawl']['config']['max_pages'] = 1
        path.write_text(json.dumps(rep))
        response = demo_app.get(base)
        assert response.status_code == 409 and 'preserved' in response.text
        return
    if change == 'number': body['explanation'] = 'Ücret 99 TL olmalıdır.'
    if change == 'assertion': body['explanation'] = 'Sorun giderildi.'
    if change == 'unsupported': body['proposed_text'] = 'Ücret 99 TL'; body['references'] = [0]
    work = request_ok(demo_app.put(base + '/cards/f0', json=body))
    work = request_ok(demo_app.post(base + '/review', json={'revision': work['revision'], 'reviewer': 'Owner', 'reason': 'Checked'}))
    assert not work['validation']['valid']
    response = demo_app.get(base + '/export/html?mode=final')
    assert response.status_code == 422
    assert 'new numeric claim' in response.text or 'sayısal' in response.text or 'unsupported verification' in response.text


def test_full_critical_appendix_is_not_hidden_and_empty_score_unavailable(demo_app):
    one, path, rep = synthetic(demo_app, 12)
    for f in rep['checks'][0]['findings']:
        f.update(severity='S1', check_id='ACC-1')
    rep['checks'][0]['check_id'] = 'ACC-1'
    rep['audit_status']['content_coverage']['pages_read'] = 0
    path.write_text(json.dumps(rep))
    base = endpoint(demo_app, one)
    work = request_ok(demo_app.post(base, json={}))
    assert len(C.all_cards(work['data'])) == 12
    assert work['data']['score']['value'] is None
    html = demo_app.get(base + '/preview').text
    # CR-04: one main card for ACC-1; the other eleven are named in the appendix and counted, never hidden.
    assert 'Ana bölüm dışında önemli bulgular: 11' in html
    assert all(f'id="finding-{c["id"]}"' in html for c in C.all_cards(work['data']))
    assert 'Puan hesaplanamadı' in html


def test_performance_context_and_saved_cache_scope_are_retained(demo_app):
    one, path, rep = synthetic(demo_app)
    rep['dataforseo'] = lab()
    rep['dataforseo']['used'] = True
    rep['dataforseo']['checks'][0].update(title='Lab', summary='Saved observation', endpoint='synthetic')
    rep['firecrawl'] = {'used': True, 'pages': [{'url': URL, 'outcome': 'read', 'status': 200,
        'observed_at': WHEN, 'from_cache': True}]}
    path.write_text(json.dumps(rep))
    base = endpoint(demo_app, one)
    work = request_ok(demo_app.post(base, json={}))
    assert work['performance'] and 'Lighthouse' in work['performance'][0]['fix']
    html = demo_app.get(base + '/preview').text
    assert 'mobile' in html and '2026-10-16' in html
    assert 'gerçek kullanıcı' in html and 'from_cache' in html


def test_skills_and_application_share_hardened_implementation_and_assets():
    import from_maya_report, validate_cards, render_report
    from maya_audit.client_reporting import validate_cards as V, render_report as R
    assert from_maya_report.score is F.score
    assert validate_cards.validate is V.validate
    assert render_report.build is R.build
    root = Path(__file__).resolve().parents[1]
    for folder in ('references', 'assets'):
        for source in (root / '.agents/skills/maya-audit-rapor' / folder).rglob('*'):
            if source.is_file():
                assert source.read_bytes() == (Path(F.__file__).parent / folder / source.relative_to(root / '.agents/skills/maya-audit-rapor' / folder)).read_bytes()


def test_direct_renderer_does_not_bypass_final_validation():
    data = valid_cards()
    data['cards'][0]['what_to_write'] = {'text': 'Ücret 99 TL'}
    from maya_audit.client_reporting.render_report import build
    with pytest.raises(ValueError, match='Final rapor reddedildi'):
        build(data)


def test_notices_editing_cannot_change_comparison_status_or_hide_missing_data(demo_app):
    one, path, rep = synthetic(demo_app)
    base = endpoint(demo_app, one)
    rep['checks'].append({'check_id': 'STR-2', 'title': 'Unavailable check', 'status': 'not_assessed',
                          'summary': 'Missing evidence', 'findings': []})
    path.write_text(json.dumps(rep))
    work = request_ok(demo_app.post(base, json={}))
    bad = {'revision': work['revision'], 'not_measured': [], 'comparison_titles': []}
    assert demo_app.put(base + '/notes', json=bad).status_code == 422
    body = {'revision': work['revision'], 'not_measured': [{'what': 'Değerlendirilmeyen alan',
            'why': 'Kayıtlı kanıt yok.', 'how_to_enable': 'Ayrıca değerlendirmelisiniz.'}], 'comparison_titles': []}
    saved = request_ok(demo_app.put(base + '/notes', json=body))
    assert len(saved['data']['not_measured']) == 1 and not saved['review']
    assert saved['data']['score'] == work['data']['score']
    body['revision'] = saved['revision'];body['fixed'] = ['fake']
    assert demo_app.put(base + '/notes', json=body).status_code == 422


def test_client_draft_reuses_normal_historical_redirect_uncertainty():
    rep = report('findings', dict(finding(), check_id='IDX-3', severity='S1', title='Redirect loop',
                                 evidence={'attempts_per_url': 4, 'rechecks': {}}, notes=[]))
    rep['checks'][0]['check_id'] = 'IDX-3'
    work = C.generate(rep, 'synthetic-audit')
    card = C.all_cards(work['data'])[0]
    assert 'sürekliliği kanıtlamıyor' in card['why']['text']
    assert not card['evidence']['verification'] and C.validation(work)['verified_findings'] == 0


def test_supported_proposed_text_keeps_exact_evidence_and_review(demo_app):
    one, path, rep = synthetic(demo_app)
    base = endpoint(demo_app, one)
    work = request_ok(demo_app.post(base, json={}))
    body = card_body(work)
    ref = next(i for i, r in enumerate(work['references']) if r['reference']['field'] == 'title')
    body.update(title='Başlık gözlemi', proposed_text='Örnek ücret 10 TL', references=[ref])
    work = request_ok(demo_app.put(base + '/cards/f0', json=body))
    work = request_ok(demo_app.post(base + '/review', json={'revision': work['revision'], 'reviewer': 'Owner', 'reason': 'Kayıtlı başlıkla karşılaştırıldı.'}))
    assert work['validation']['valid'], work['validation']['errors']
    assert work['validation']['verified_findings'] == 0
    saved = C.all_cards(work['data'])[0]['what_to_write']
    assert saved['derived_from'] == [work['references'][ref]['reference']]
    assert demo_app.get(base + '/export/html?mode=final').status_code == 200


def test_draft_escapes_editorial_markup_and_pdf_unavailable_is_explicit(demo_app, monkeypatch):
    one, path, rep = synthetic(demo_app)
    base = endpoint(demo_app, one)
    work = request_ok(demo_app.post(base, json={}))
    body = card_body(work);body['explanation'] = '<script>alert("unsafe")</script>'
    request_ok(demo_app.put(base + '/cards/f0', json=body))
    html = demo_app.get(base + '/preview')
    assert '<script>' not in html.text and '&lt;script&gt;' in html.text
    assert "default-src 'none'" in html.headers['Content-Security-Policy']
    def unavailable(*a, **kw): raise pdf.PdfUnavailable('Synthetic unavailable browser')
    monkeypatch.setattr(pdf, 'to_pdf', unavailable)
    response = demo_app.get(base + '/export/pdf?mode=draft')
    assert response.status_code == 503 and 'use HTML' in response.text


def test_client_provenance_never_copies_configuration_secrets():
    rep = report()
    # Deliberately synthetic sentinel, not a credential read from environment or disk.
    rep['crawl']['config'].update(google_api_key='SYNTHETIC-NEVER-EXPORT', gsc_access_token='SYNTHETIC-NEVER-EXPORT',
                                  max_pages=7, redirect_recheck_attempts=3)
    work = C.generate(rep, 'synthetic-audit')
    assert 'SYNTHETIC-NEVER-EXPORT' not in json.dumps(work)
    assert work['provenance']['crawl']['config']['max_pages'] == 7
    assert work['provenance']['crawl']['config']['redirect_recheck_attempts'] == 3


def test_source_times_are_not_replaced_with_report_generation_time():
    rep = report('findings', dict(finding(), observed_at='2026-10-15T09:15:00+00:00'))
    rep['crawl']['pages'] = []
    rep['dataforseo'] = {'checks': [{'check_id': 'DFS-9', 'status': 'observed',
                         'evidence': {'data_from': 1720000000, 'from_cache': True}}]}
    work = C.generate(rep, 'synthetic-audit')
    assert C.all_cards(work['data'])[0]['evidence']['read_at'] == '2026-10-15T09:15:00+00:00'
    assert work['data']['meta']['content_dates']['pages'] == 'Mevcut değil'
    assert '2024-' in work['data']['meta']['content_dates']['search_data']
    assert 'kayıtlı kopya' in work['data']['meta']['content_dates']['search_data']
