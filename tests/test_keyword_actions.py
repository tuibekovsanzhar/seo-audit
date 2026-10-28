"""General keyword evidence and shared normal-export actions; synthetic sites/providers only."""
import copy
import json
from types import SimpleNamespace

import pytest

from maya_audit.dataforseo import insights
from maya_audit_web import demo, practical, summary, strings, pdf, wording, paid
from maya_audit_web.action_priority import performance_rows, ordered
from test_report_agreement import demo_app, audit  # noqa: F401
from test_web_app import API, get
from test_practical_report import row

DOMAIN = 'kart.example'
STAMP = '2026-10-16T10:00:00+00:00'


def keywords(rows, brand='Northcard', **options):
    original = [[q, 230, 8, url] for q, url in rows]
    section = {'checks': [{'check_id': 'DFS-3', 'status': 'observed', 'summary': 'Provider totals: 9000.',
                           'evidence': {'data': {'metrics': {'Ranked keywords': 9000}}}},
                          {'check_id': 'DFS-4', 'status': 'observed', 'summary': f'{len(rows)} keyword(s) listed of 9000 the domain ranks for, most searched first; {len(rows)} of those listed are in the top 10.',
                           'evidence': {'data': {'total_count': 9000, 'table': {'columns': ['Keyword','Searches a month','Position','Ranking page'], 'rows': original}}}}]}
    insights.apply_relevance(section, brand=brand, domain=DOMAIN, texts=['Kart yükleme ve ödeme'], **options)
    return section, section['checks'][1]['evidence']['data']


def page(url, title, description='', readable=True):
    return SimpleNamespace(url=url, analysis={'title':title, 'meta':[{'name':'description','content':description}]},
                           requested_at=STAMP, readable_document=lambda: readable)


@pytest.mark.parametrize('query', ['hgs yükleme','hgs yukleme','HGS YÜKLEME','hgs yüklemesi'])
def test_service_acronym_and_turkish_variants_are_supported_without_brand_exceptions(query):
    url='https://kart.example/hgs-yukleme'
    section,data=keywords([(query,url)],pages=[page(url,'HGS yükleme', 'HGS bakiye sorgulama ve ödeme')])
    assessment=data['keyword_assessments'][0]
    assert assessment['category']=='relevant'
    assert any(s['url']==url for s in assessment['sources'])
    assert data['provider_table']['rows']==[[query,230,8,url]]
    assert data['table']['rows'][0][:4]==[query,230,8,url]
    assert section['checks'][0]['summary']=='Provider totals: 9000.'


@pytest.mark.parametrize('query', ['qr ödeme','QR ODEME','api entegrasyon','API ENTEGRASYON'])
def test_other_brands_short_acronyms_use_their_page_context(query):
    url='https://kart.example/services'
    _,data=keywords([(query,url)],pages=[page(url,'QR ödeme ve API entegrasyon')])
    assert data['keyword_assessments'][0]['category']=='relevant'


@pytest.mark.parametrize('query', ['isbankasi','iş bankası','İŞBANKASI'])
def test_related_organization_requires_confirmed_name_not_host_ranking(query):
    url='https://kart.example/'
    _,unknown=keywords([(query,url)])
    assert unknown['keyword_assessments'][0]['category']=='ambiguous'
    _,data=keywords([(query,url)],related_organizations=['İş Bankası'])
    assert data['keyword_assessments'][0]['category']=='related_organization'
    assert data['keyword_assessments'][0]['sources'][0]['kind']=='related_organization'
    assert data['relevance']['branded']==0 and data['relevance']['related_organization']==1


@pytest.mark.parametrize('query', ['açık kart giriş','acikkart giris','AÇIKKART'])
def test_explicit_aliases_are_names_and_original_provider_query_is_unchanged(query):
    _,data=keywords([(query,'https://kart.example/')], aliases=['Açık Kart'])
    assert data['keyword_assessments'][0]['category']=='branded'
    assert data['provider_table']['rows'][0][0]==query


def test_short_brand_name_is_not_discarded_and_common_word_is_ambiguous():
    _,data=keywords([('xy','https://kart.example/')],brand='XY')
    assert data['keyword_assessments'][0]['category']=='branded'
    _,data=keywords([('maximum','https://kart.example/')],brand='Maximum')
    assert data['keyword_assessments'][0]['category']=='ambiguous'


def test_ranking_on_domain_alone_is_not_relevance_and_mixed_intent_is_uncertain():
    url='https://kart.example/hgs-yukleme'
    _,data=keywords([('hgs casino',url),('galaxy cooking','https://kart.example/unknown'),
                     ('galaxy cooking','https://another.example/gaming')], pages=[page(url,'HGS yükleme')])
    # An external ranking host alone is no more evidence of unrelated intent than our host is of relevance.
    assert [a['category'] for a in data['keyword_assessments']]==['ambiguous','ambiguous','ambiguous']
    assert len(data['ambiguous']['rows'])==3 and len(data['unrelated']['rows'])==0


def test_conflicting_common_brand_search_remains_unrelated_and_totals_are_not_extrapolated():
    section,data=keywords([('maximum heart rate','https://kart.example/unknown'),
                            ('maximum kettle temperature','https://kart.example/unknown')],brand='Maximum')
    assert all(a['category']=='unrelated' for a in data['keyword_assessments'])
    assert section['checks'][0]['summary']=='Provider totals: 9000.'
    assert section['checks'][0]['evidence']['data']['metrics']['Ranked keywords']==9000
    assert 'no classification of provider totals' in section['checks'][1]['summary']
    assert 'not proof of search intent' in section['checks'][1]['summary']


def test_matched_unread_page_does_not_supply_context():
    url='https://kart.example/unknown'
    _,data=keywords([('galaxy cooking',url)],pages=[page(url,'galaxy cooking',readable=False)])
    assert data['keyword_assessments'][0]['category']=='ambiguous'
    assert not any(s['source']=='saved page title/headings/description' for s in data['keyword_assessments'][0]['sources'])
    assert insights.page_texts([page(url,'galaxy cooking',readable=False)])==[]


def lab(*,bad=True,status='observed',date=STAMP):
    return {'checks':[{'check_id':'DFS-9','status':status,'target':'https://kart.example/',
                       'evidence':{'data_from':date,'data':{'device':'mobile','metrics':{'Performance score (0–100)':8},
                         'past_good_threshold':['Largest Contentful Paint'] if bad else [],
                         'within_good_threshold':[]}}}]}


def test_measured_lab_enters_first_actions_after_real_blockers_without_invented_cause():
    rows=[dict(row('S4','S',f'Editorial {n}',f'Edit {n}.'),check_id=f'TSEO-{n}') for n in range(7)]
    rows.insert(0,dict(row('S1','L','Access blocker','Investigate observed cycle.'),check_id='IDX-3'))
    actions=practical.executive(rows,lab(),None,withheld=None)['actions']
    assert 'cycle' in actions[0]['text'] and 'Lighthouse' in actions[1]['text']
    assert 'https://kart.example/' in actions[1]['text'] and STAMP in actions[1]['text'] and 'mobile' in actions[1]['text']
    assert 'not real-user' in performance_rows(lab())[0]['why']
    assert not any(cause in actions[1]['text'] for cause in ['nginx','WAF','image compression'])
    assert len(actions)==5
    assert practical.executive(rows,lab(),None,withheld=None)['problems_total']==8


@pytest.mark.parametrize('section',[None,lab(bad=False),lab(status='not_assessed')])
def test_missing_or_healthy_performance_is_not_a_remediation(section):
    assert performance_rows(section)==[]


def test_incomplete_and_field_measurements_keep_their_scope_and_unknown_date():
    missing=lab(bad=False,date=None)
    missing['checks'][0]['evidence']['data']['missing_measurements']=['LCP']
    [candidate]=performance_rows(missing)
    assert candidate['severity']=='S4' and 'Unavailable' in candidate['fix']
    field={'status':'assessed','origin':'https://kart.example','form_factor':'PHONE','data_until':'2026-10-15',
           'source':'Chrome UX Report','metrics':[{'label':'LCP','rating':'poor','shown':'4 s'}]}
    candidates=performance_rows(lab(),field)
    assert len(candidates)==2 and candidates[1]['pages_total']==0
    assert 'aggregate' in candidates[1]['why'] and '2026-10-15' in candidates[1]['fix']
    assert performance_rows(None,{'status':'not_available'})==[]


@pytest.mark.parametrize('language',['en','tr'])
def test_normal_summary_plan_timeline_print_and_download_share_diagnostics_and_classification(demo_app,monkeypatch,language):
    one=audit(demo_app,demo.BANK,search_data=True,market_default_accepted=True)
    path=demo_app.app.state.runner.artifacts(one['id'])/'report.json'
    report=json.loads(path.read_text(encoding="utf-8"))
    synthetic=lab()['checks'][0]
    report['dataforseo']['checks']=[c for c in report['dataforseo']['checks'] if c['check_id'] not in ('DFS-9','DFS-10','DFS-11')]+[dict(synthetic,title='Lighthouse lab test (mobile): https://kart.example/',summary='Synthetic lab observation.',endpoint='synthetic')]
    # The same sample enters the normal provider panel; no direct helper-only export.
    section,data=keywords([('hgs yukleme','https://kart.example/hgs-yukleme'),('isbankasi','https://kart.example/')],related_organizations=['İş Bankası'])
    for c in report['dataforseo']['checks']:
        if c['check_id']=='DFS-4':
            c['evidence']['data']=data;c['summary']=section['checks'][1]['summary']
    before=copy.deepcopy(report)
    path.write_text(json.dumps(report))
    from maya_audit_web.app import LANGUAGE_COOKIE
    demo_app.cookies.set(LANGUAGE_COOKIE,language)
    brief=get(demo_app,one,'/summary')
    full=get(demo_app,one,'/practical')
    plan=get(demo_app,one,'/action-plan')
    actions=brief['practical']['executive']['actions']
    assert any('Lighthouse' in a['text'] and STAMP in a['text'] for a in actions)
    candidates=[r for group in plan['groups'] for r in group['items'] if r.get('action_kind')]
    assert len(candidates)==1
    assert any(r['check_id']=='DFS-9' for step in full['timeline'] for r in step['items'])
    assert full['executive']['problems_total']==sum(1 for r in full['issues'] if r['severity']!='Info')
    printed=demo_app.get(f'{API}/audits/{one["id"]}/print?full=true&lang={language}')
    assert printed.status_code==200 and STAMP in printed.text and 'hgs yukleme' in printed.text and 'isbankasi' in printed.text
    related='related organization' if language=='en' else 'ilişkili kuruluş'
    assert related in printed.text
    category_panel = next(c for c in brief['backlinks']['checks'] if c['check_id']=='DFS-4')
    assert category_panel['data_shown']['labels']['related_organization']==related
    assert 'related_organization (İngilizce)' not in printed.text
    captured=[]
    monkeypatch.setattr(pdf,'to_pdf',lambda html,**kwargs: captured.append(html) or b'%PDF-test')
    response=demo_app.get(f'{API}/audits/{one["id"]}/downloads/pdf')
    assert response.status_code==200 and response.content==b'%PDF-test'
    assert len(captured)==1 and STAMP in captured[0] and 'hgs yukleme' in captured[0]
    assert json.loads(path.read_text(encoding="utf-8"))==before


def test_profile_confirmed_names_survive_ordinary_profile_updates_and_reach_runner(demo_app):
    one=audit(demo_app,demo.BANK,search_data=True,market_default_accepted=True)
    project=one['project_id']
    endpoint=f'{API}/projects/{project}/profile'
    saved=demo_app.put(endpoint,json={'brand_name':'Northcard','brand_aliases':['Açık Kart'],'related_organizations':['İş Bankası']})
    assert saved.status_code==200,saved.text
    updated=demo_app.put(endpoint,json={'brand_name':'Northcard','industry':'payments'})
    assert updated.json()['brand_aliases']==['Açık Kart'] and updated.json()['related_organizations']==['İş Bankası']
    section,_=keywords([('isbankasi','https://kart.example/')])
    data=section['checks'][1]['evidence']['data']
    data.pop('relevance');data['table']=data.pop('provider_table')
    section['target']=DOMAIN
    demo_app.app.state.runner._relevance(one,{'search_data':True},section,[],{'name':'Northcard','source':'typed','confirmed':True})
    assert data['keyword_assessments'][0]['category']=='related_organization'


def test_lighthouse_preserves_measurement_timestamp_and_no_missing_data_becomes_good():
    measured={'categories':{'performance':{'score':.08}},'audits':{},'fetchTime':STAMP}
    _,data=insights._lighthouse({'tasks':[{'result':[measured]}]})
    assert data['measurement_at']==STAMP and data['missing_measurements']
    report=lab(bad=False,date='2026-10-17T00:00:00+00:00')
    report['checks'][0]['evidence']['data']=data
    [candidate]=performance_rows(report)
    assert STAMP in candidate['fix'] and '2026-10-17T00:00:00+00:00' in candidate['fix']
    assert candidate['severity']=='S4'  # Unmeasured timings are a diagnostic gap, not evidence of a slow cause.


def test_all_three_lab_urls_and_field_evidence_remain_distinct_and_blockers_take_precedence():
    panel=lab()
    for n in (10,11):
        extra=copy.deepcopy(panel['checks'][0]);extra['check_id']=f'DFS-{n}';extra['target']=f'https://kart.example/page-{n}'
        panel['checks'].append(extra)
    candidates=performance_rows(panel)
    assert len(candidates)==3 and len({r['affects'] for r in candidates})==3
    blockers=[dict(row(level,'L',f'Access {n}'),check_id=f'IDX-{n}') for n,level in enumerate(['S1','S2','S2','S2','S2'])]
    assert not any('Lighthouse' in a['text'] for a in practical.first_actions(candidates+blockers))
    assert ordered(candidates+blockers)[:5]==blockers


def test_related_organizations_are_not_offered_as_keyword_quick_wins():
    section,data=keywords([('isbankasi','https://kart.example/'),('hgs yukleme','https://kart.example/hgs-yukleme')],related_organizations=['İş Bankası'],pages=[page('https://kart.example/hgs-yukleme','HGS yükleme')])
    view={'checks':[{'check_id':'DFS-5','status':'observed','data':data}]}
    opportunities=practical.opportunities(view,None,[])
    assert 'hgs yukleme' in opportunities[0] and 'isbankasi' not in opportunities[0] and '9000' not in opportunities[0]


def test_advisory_first_action_never_creates_a_broken_finding_link():
    from maya_audit_web import followups
    [candidate]=performance_rows(lab())
    def unavailable(identity):
        raise AssertionError('Provider diagnostic is not an engine finding')
    ctx=followups.AssistantContext({'first_action':candidate}, {}, lambda: None, unavailable)
    reply=followups._top(ctx)
    assert reply['finding_ids']==[] and any(STAMP in text for text in reply['items'])
