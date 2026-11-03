"""Qualifying counts, contextual image roles and budget-neutral ranking coverage."""
import copy
from types import SimpleNamespace
import pytest
from maya_audit.analysis import analyze_html
from maya_audit.checks.content_quality import str14_anchor_text
from maya_audit.html_links import extract_link_edges
from maya_audit.models import to_jsonable
from maya_audit.report import page_item, finding_counts
from maya_audit.dataforseo import insights
from maya_audit.firecrawl.reading import ReadingQueue
from maya_audit_web import practical, strings
from test_false_alarms import site, html, CFG, images_check, no_lookups
from test_report_agreement import demo_app
from test_keyword_actions import keywords, page


def test_generic_occurrences_are_not_all_anchors_in_source_target_group():
    body='<a href="/guide">Read more</a><a href="/guide"><img src="a.jpg" alt=""></a>'
    result,pages=site({'/':html(body)})
    f=to_jsonable(str14_anchor_text(result,CFG,pages,set()).findings)[0]
    assert f['evidence']['links'][0]['links']==2
    assert f['evidence']['links'][0]['links_with_generic_text']==1
    assert page_item(f,pages[0].url)['values']['links']==1
    assert finding_counts(f)['occurrences']==1
    # A genuine second generic occurrence remains counted; a descriptive name clears the generic-only rule.
    for extra,expected in [('<a href="/guide">Read more</a>',2),('<a href="/guide">Installation guide</a>',0)]:
        result,pages=site({'/':html(body+extra)})
        fs=[f for f in str14_anchor_text(result,CFG,pages,set()).findings if 'generic text' in f.title]
        assert (sum(finding_counts(to_jsonable(f))['occurrences'] for f in fs) if fs else 0)==expected


@pytest.mark.parametrize('body',[
    '<figure><img src="notebook-photo.png" width="700" height="600" alt=""></figure>',
    '<figure style="width:24px"><img src="cover-photo.jpg" width="900" height="900" alt=""></figure>',
    '<section><ol><li>Enter your account number</li><li>Confirm the request</li></ol><figure><img src="instructions.png" alt=""></figure></section>',
])
def test_wrapper_name_dimensions_and_nearby_prose_do_not_prove_image_role(body):
    check=images_check(body)
    assert not any(f.severity.value!='Info' for f in check.findings)
    assert check.evidence['unassessed_image_roles']
    assert check.evidence['empty_alt_not_assessed_count']==1


def test_image_function_and_informative_caption_still_detect_real_defects():
    for body in ['<a href="/apply"><img src="blank.png" alt="" width="8" height="8"></a>',
                 '<figure><img src="a.png" alt=""><figcaption>Chart: monthly revenue by department</figcaption></figure>']:
        assert any(f.severity.value=='S4' for f in images_check(body).findings)
    c=images_check('<figure><img src="chart.png" alt="" role="presentation"></figure>')
    assert c.evidence['equivalent_description_reviews'] and not c.evidence['unassessed_image_roles']


def provider(rows):
    return {'checks':[{'check_id':'DFS-5','status':'observed','summary':'Provider sample.',
        'evidence':{'data':{'table':{'columns':['Keyword','Searches a month','Position','Ranking page'],'rows':rows}}}}]}


def test_ranking_urls_prioritized_without_increasing_cap_or_trusting_foreign_media():
    rows=[['a',100,4,'https://kart.example/blog/article'],['b',200,8,'https://kart.example/branches/town'],
          ['foreign',999,1,'https://other.example/x'],['media',999,1,'https://kart.example/song.mp3']]
    section=provider(rows);before=copy.deepcopy(section)
    urls=insights.ranking_landing_pages(section,'https://kart.example',9)
    assert urls==['https://kart.example/branches/town','https://kart.example/blog/article']
    assert section==before
    q=ReadingQueue();q.add('https://kart.example/menu','link',1,True)
    q.add('https://kart.example/','start',0);q.add('https://kart.example/contact','key_page',1)
    for url in urls:q.add(url,'ranking_page',1)
    assert [q.pop()[0] for _ in range(4)]==['https://kart.example/','https://kart.example/contact',*urls]
    assert len(insights.ranking_landing_pages(section,'https://kart.example',3))==1
    assert not insights.ranking_landing_pages(section,'https://kart.example',1)


def test_editorial_ranking_is_not_a_confirmed_commercial_opportunity():
    url='https://kart.example/blog/seramik-tarihi'
    p=page(url,'Seramik tarihi nedir?');p.analysis['json_ld_blocks']=['{"@type":"Article"}']
    s=provider([['seramik tarihi nedir',5000,4,url]])
    insights.apply_relevance(s,brand='Northcard',domain='kart.example',texts=['Seramik tarihi nedir?'],pages=[p])
    d=s['checks'][0]['evidence']['data'];a=d['keyword_assessments'][0]
    assert a['dimensions']['editorial_relevance']=='supported'
    assert not d['opportunity_evidence'][a['keyword']]
    assert d['editorial_opportunities']['rows'][0][0]==a['keyword']
    strings.set_language('en')
    assert 'commercial value not established' in practical.opportunities({'checks':[{'check_id':'DFS-5','status':'observed','data':d}]},None,[])[0]
    original=copy.deepcopy(d['provider_table']);insights.refresh_relevance(s)
    assert d['table']==original and not d.get('relevance')


def test_supported_service_remains_an_opportunity_and_missing_page_uncertain():
    url='https://kart.example/kart-yukleme'
    s=provider([['kart yükleme',100,7,url],['festival gelenekleri',500,4,'https://kart.example/blog/festival']])
    insights.apply_relevance(s,brand='Northcard',domain='kart.example',texts=['Kart yükleme'],pages=[page(url,'Kart yükleme')])
    d=s['checks'][0]['evidence']['data']
    assert d['opportunity_evidence']['kart yükleme']
    assert not d['opportunity_evidence']['festival gelenekleri']
    assert d['keyword_assessments'][1]['uncertain']


def test_neutral_filename_chart_in_numeric_table_is_not_mistaken_for_category_photo():
    from test_oct18_corrections import nutrition
    body=nutrition('a.png').replace('</figure>','<figcaption>Chart of nutrient proportions</figcaption></figure>')
    assert any(f.severity.value=='S4' for f in images_check(body).findings)


def test_normal_routes_and_client_cards_agree_on_qualifying_links(demo_app, monkeypatch):
    import json
    from test_report_agreement import audit
    from maya_audit_web import demo, pdf, client_reports as C
    from maya_audit.report import problem_summary
    one=audit(demo_app,demo.SHOP);base='/api/v1/audits/'+one['id']
    path=demo_app.app.state.runner.artifacts(one['id'])/'report.json';r=json.loads(path.read_text(encoding="utf-8"))
    result,pages=site({'/':html('<a href="/guide">Read more</a><a href="/guide"><img src="a.jpg" alt=""></a>')})
    image_check=images_check('<figure><img src="photo.png" alt=""></figure><figure><img src="a.png" alt=""><figcaption>Chart of demand</figcaption></figure>')
    ck=str14_anchor_text(result,CFG,pages,set());r['checks']=[to_jsonable(ck) if c['check_id']=='STR-14' else to_jsonable(image_check) if c['check_id']=='STR-7' else c for c in r['checks']]
    fs=[f for c in r['checks']for f in c['findings']];r['problem_summary']=problem_summary(fs,pages_checked=1,checks=r['checks'])
    # Reproduce stale derived page items in already-saved audits too.
    for row in r['problem_summary']['by_page']:
        for item in row.get('items', []):
            if item.get('kind')=='links_generic':item['values']['links']=2
    r['findings_in_priority_order']=[f['id']for f in fs];path.write_text(json.dumps(r));before=path.read_bytes()
    assert demo_app.get(base+'/summary').status_code==200
    text=demo_app.get(base+'/print?full=true').text
    assert '1 link names its target only with generic text' in text
    assert '2 links name their target only with generic text' not in text
    seen=[];monkeypatch.setattr(pdf,'to_pdf',lambda text,**kw:seen.append(text) or b'%PDF-test')
    # DECISIONS 300: the concise PDF has no problems-by-page table (the key pages scorecard took its place); its card
    # gives the one occurrence, and the stale count of two is said nowhere.
    assert demo_app.get(base+'/downloads/pdf').status_code==200 and '1 generic-text link occurrence' in seen[-1]
    assert '2 links name their target' not in seen[-1]
    work=demo_app.post(base+'/client-report',json={}).json()
    card=next(c for c in C.all_cards(work['data'])if c['maya']['check_id']=='STR-14')
    assert card['counting']['occurrences']==1 and card['counting']['affected_pages']==1
    assert len(work['provenance']['image_role_gaps'])==1
    note=next(n for n in work['data']['not_measured'] if n['what']=='Görsellerin bilgi aktarma amacı')
    assert '(İngilizce)' not in note['why'] and 'gösterildikleri boyutta' in note['how_to_enable']
    assert any(c['maya']['check_id']=='STR-7' for c in C.all_cards(work['data']))
    preview=demo_app.get(base+'/client-report/preview')
    assert preview.status_code==200 and 'Değerlendirilemeyen görsel rolleri' in preview.text
    assert demo_app.get(base+'/client-report/export/html?mode=final').status_code==422
    assert path.read_bytes()==before


def test_worker_acquires_approved_sample_before_reader_and_reuses_saved_paid_result(demo_app,monkeypatch):
    import json, threading, httpx
    from test_report_agreement import audit
    from maya_audit_web import demo
    from maya_audit_web.runner import Runner
    from maya_audit.dataforseo import panel
    target='http://'+demo.SHOP+'/ranking-only'
    events=[];paid_calls=[];reader_attempts=[]
    original_backlinks=Runner._backlinks; original_firecrawl=Runner._firecrawl
    original_run=panel.run_checks; original_fc=demo._firecrawl
    def run(*args,**kw):
        paid_calls.append(1);s=original_run(*args,**kw);s['target']=demo.SHOP
        for c in s['checks']:
            if c['check_id'] in ('DFS-4','DFS-5') and c['status']=='observed':
                c['evidence']['data']['table']['rows'].insert(0,['porselen bakımı',9999,4,target])
        return s
    def backlinks(self,*args,**kw):
        events.append('paid');return original_backlinks(self,*args,**kw)
    def firecrawl(self,*args,**kw):
        events.append('reader');assert target in kw['ranking_urls']
        return original_firecrawl(self,*args,**kw)
    def fetched(request):
        asked=json.loads(request.content);reader_attempts.append(asked.get('url'))
        if asked.get('url')==target:
            return httpx.Response(200,json={'success':True,'data':{'rawHtml':'<html><head><title>Porselen bakımı</title></head><body><main><h1>Porselen bakımı</h1><p>Porselen bakımı için yazılı rehber.</p></main></body></html>','metadata':{'statusCode':200,'url':target}}})
        return original_fc(request)
    monkeypatch.setattr(panel,'run_checks',run);monkeypatch.setattr(Runner,'_backlinks',backlinks)
    monkeypatch.setattr(Runner,'_firecrawl',firecrawl)
    # Existing demo transport captured its callback when the fixture was built; replace only that mock.
    from dataclasses import replace
    demo_app.app.state.engine.firecrawl=replace(demo_app.app.state.engine.firecrawl,transport=httpx.MockTransport(fetched))
    one=audit(demo_app,demo.SHOP,search_data=True,market_default_accepted=True)
    assert events==['paid','reader'] and len(paid_calls)==1 and target in reader_attempts
    runner=demo_app.app.state.runner;folder=runner.artifacts(one['id']);r=json.loads((folder/'report.json').read_text(encoding="utf-8"))
    a=next(a for c in r['dataforseo']['checks']if c['check_id']=='DFS-5' for a in c['evidence']['data']['keyword_assessments']if a['keyword']=='porselen bakımı')
    assert a['ranking_page_status']=='saved_readable_evidence' and not a['uncertain']
    section=original_backlinks(runner,runner.store.audit(one['id']),folder,stopped=False,stop=threading.Event(),enter=lambda *_:None)
    assert section and len(paid_calls)==1
    assert r['firecrawl']['pages_read']<=r['firecrawl']['page_cap']


@pytest.mark.parametrize('url',['https://www.kart.example/branch','http://kart.example/branch','https://kart.example:444/branch'])
def test_priority_candidates_match_reader_origin_guards_without_inventing_alias_equivalence(url):
    s=provider([['town service',100,4,url],['valid',50,8,'https://kart.example/branch']])
    assert insights.ranking_landing_pages(s,'https://kart.example',9)==['https://kart.example/branch']


def test_coverage_prefers_near_page_one_sample_and_does_not_waste_a_home_slot():
    s=provider([['branch search',100,7,'https://kart.example/branches/town']])
    s['checks'].insert(0,{'check_id':'DFS-4','status':'observed','evidence':{'data':{'table':{'rows':[
        ['brand',99000,1,'https://kart.example/'],['general article',30000,1,'https://kart.example/blog/background']]}}}})
    assert insights.ranking_landing_pages(s,'https://kart.example',3)==['https://kart.example/branches/town']


def test_legacy_saved_editorial_flags_are_qualified_read_only_through_normal_routes(demo_app):
    import json
    from test_report_agreement import audit
    from maya_audit_web import demo
    one=audit(demo_app,demo.SHOP,search_data=True,market_default_accepted=True)
    folder=demo_app.app.state.runner.artifacts(one['id']);path=folder/'report.json';r=json.loads(path.read_text(encoding="utf-8"))
    row=['seramik tarihi nedir',5000,4,'https://other.example/blog/seramik','relevant']
    d={'table':{'columns':['Keyword','Searches a month','Position','Ranking page','Relevance'],'rows':[row]},
        'opportunity_evidence':{row[0]:True},'keyword_assessments':[{'keyword':row[0],'uncertain':False,
            'dimensions':{'editorial_relevance':'supported'},'sources':[{'url':row[3],'source':'saved page title'}]}]}
    ck=next(c for c in r['dataforseo']['checks']if c['check_id']=='DFS-5');ck['evidence']['data']=d
    path.write_text(json.dumps(r));before=path.read_bytes();base='/api/v1/audits/'+one['id']
    view=demo_app.get(base+'/summary').json();derived=next(c['data']for c in view['backlinks']['checks']if c['check_id']=='DFS-5')
    assert not derived['opportunity_evidence'][row[0]] and derived['editorial_opportunities']['rows']==[row[:4]]
    practical_view=demo_app.get(base+'/practical').json()
    assert any('commercial value not established' in t for t in practical_view['executive']['opportunities'])
    assert not any(row[0] in t and 'nearest gain' in t for t in practical_view['executive']['opportunities'])
    printed=demo_app.get(base+'/print?full=true').text
    assert 'Editorial topic matches (commercial value not established)' in printed
    assert not (row[0] in printed and 'nearest gain: “'+row[0] in printed)
    assert path.read_bytes()==before and d['opportunity_evidence'][row[0]] is True
    # Genuine service evidence must still qualify for an action, even when its old flag was false.
    service=copy.deepcopy(d);service_word='kart yükleme'
    service['table']['rows'][0][0]=service_word
    service['keyword_assessments'][0].update(keyword=service_word,dimensions={'service_relevance':'supported'},
        sources=[{'url':'https://other.example/kart-yukleme','source':'saved service page title'}])
    service['opportunity_evidence']={service_word:False}
    assert insights.qualified_opportunity_data(service)['opportunity_evidence'][service_word]


def test_editorial_assessment_cannot_verify_another_landing_url_for_the_same_query():
    query='festival traditions';known='https://other.example/blog/traditions';unknown='https://other.example/unread'
    d={'table':{'columns':['Keyword','Searches','Rank','URL'],'rows':[[query,100,4,known],[query,100,7,unknown]]},
        'keyword_assessments':[{'keyword':query,'ranking_url':known,'uncertain':False,'dimensions':{'editorial_relevance':'supported'}},
                               {'keyword':query,'ranking_url':unknown,'uncertain':True,'dimensions':{}}]}
    before=copy.deepcopy(d);qualified=insights.qualified_opportunity_data(d)
    assert qualified['editorial_opportunities']['rows']==[d['table']['rows'][0]]
    assert not qualified['opportunity_evidence'][query] and d==before
    # Missing assessment for the second URL cannot borrow the first URL's evidence either.
    d['keyword_assessments'].pop()
    assert insights.qualified_opportunity_data(d)['editorial_opportunities']['rows']==[d['table']['rows'][0]]
