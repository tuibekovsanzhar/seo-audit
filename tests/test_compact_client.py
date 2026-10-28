"""Compact delivery preserves evidence identity; exhaustive sources remain explicit."""
from copy import deepcopy
from html import escape
import pytest
from test_client_report_app import synthetic, endpoint
from test_report_agreement import demo_app  # noqa: F401
from maya_audit_web import client_reports as C, pdf


def test_compact_preserves_all_findings_actions_and_companion(demo_app):
    one, path, report = synthetic(demo_app, findings=13)
    base = endpoint(demo_app, one)
    demo_app.post(base, json={})
    work = C.generate(report, one['id'])
    original = deepcopy(work)
    # A long native/provider extract previously reprinted without a delivery boundary.
    work['data']['page_facts']['https://fiction.example/'] = {
        'observations': [{'source':'native', 'read_at':'2026-10-01T12:00:00Z',
                          'text_sample': 'EXHAUSTIVE_ONLY '*30000}]}
    compact = C.html(work)
    assert 'EXHAUSTIVE_ONLY' not in compact
    assert 'EXHAUSTIVE_ONLY' in C.html(work, full=True)
    assert 'maya-client-compact' in compact
    for card in C.all_cards(work['data']):
        assert card['id'] in compact
        assert card['verify'] in compact
        assert escape(card['steps'][0]) in compact
    assert work['data']['cards'] == original['data']['cards']
    assert work['data']['appendix_cards'] == original['data']['appendix_cards']
    response = demo_app.get(base+'/export/json')
    assert response.status_code == 200
    assert len(C.all_cards(response.json()['data'])) == 13
    assert response.json()['validation']['verified_findings'] == 0
    assert demo_app.get(base+'/export/html?mode=final').status_code == 422
    assert demo_app.get(base+'/export/html?mode=draft&full=true').status_code == 200
    assert demo_app.get(f'/api/v1/audits/{one["id"]}/downloads/json').json() == report


def test_compact_pdf_requires_page_limit_and_reports_actionable_failure(demo_app, monkeypatch):
    one, _, _ = synthetic(demo_app)
    base = endpoint(demo_app, one)
    demo_app.post(base,json={})
    def oversized(html, **options):
        assert options['max_pages'] == 50
        assert 'maya-client-compact' in html
        raise pdf.PdfPageLimit('Concise PDF has 51 pages; maximum 50. No incomplete PDF was returned.')
    monkeypatch.setattr(pdf,'to_pdf',oversized)
    result=demo_app.get(base+'/export/pdf?mode=draft')
    assert result.status_code==503
    assert '51 pages' in result.text and 'JSON' in result.text


def test_compact_urls_are_clickable_and_unknown_role_not_a_pass(demo_app):
    one, _, report = synthetic(demo_app)
    work=C.generate(report, one['id'])
    card=C.all_cards(work['data'])[0]
    card['where']['examples']=['https://bakery.example/menu']
    work['provenance']['image_role_gaps']=[{'src':'unknown.png'}]
    text=C.html(work)
    assert 'href="https://bakery.example/menu"' in text
    assert 'görsel rolü kayıtları: 1' in text
    assert 'kusur olarak sayılmaz' in text
    assert 'canlı doğrulanmış bulgu: 0' in text


def test_table_title_uses_explicit_units_without_singular_plural_error():
    from maya_audit_web import wording
    from maya_audit_web.strings import set_language
    set_language('en')
    title,_=wording.title('STR-8', '13 data table(s) on 1 page(s) lack supported header associations', 'en')
    assert 'affected pages: 1' in title and '1 pages' not in title


def test_iframe_advice_does_not_claim_unmeasured_extraction_failure():
    from maya_audit_web import catalog, strings
    for language in ('en','tr'):
        strings.set_language(language)
        why=catalog.note('RND-4','2 pages embed iframes')['why']
        assert 'do not see' not in why and 'görmez' not in why
    strings.set_language('en')


def test_compact_retains_numeric_lab_measurements(demo_app):
    one, _, report=synthetic(demo_app)
    work=C.generate(report,one['id'])
    work['performance_evidence']={'lighthouse':[{'check_id':'DFS-9','data':{
        'device':'mobile','measurement_at':'2026-10-01T12:00:00Z',
        'metrics':{'Largest Contentful Paint':'7.4 s','Total Blocking Time':'1770 ms'}}}]}
    text=C.html(work)
    assert '7.4 s' in text and '1770 ms' in text and '2026-10-01' in text


def test_companion_links_resolve_to_the_app_not_private_files(demo_app):
    one,_,_=synthetic(demo_app)
    base=endpoint(demo_app,one)
    demo_app.post(base,json={})
    page=demo_app.get(base+'/export/html').text
    # D-08: the companions are named by file name; a link into the owner's local app does not open for a client.
    assert f"maya-client-{one['id']}-evidence.json" in page and '127.0.0.1' not in page
    assert 'file://' not in page
    full=demo_app.get(base+'/export/html?full=true')
    assert '-full-evidence.html' in full.headers['content-disposition']
