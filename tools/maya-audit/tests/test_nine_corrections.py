"""Owner's nine bounded accuracy contracts; fabricated evidence, no provider requests."""
from copy import deepcopy
from types import SimpleNamespace as NS
import io
import re
import pytest
from maya_audit.models import FetchClass, to_jsonable
from maya_audit.config import CrawlConfig
from maya_audit.judgments import qualify, qualify_report
from maya_audit_web import client_reports as C, strings, pdf
from test_client_reporting import report, finding as base_finding, URL
from test_judgment_consistency import finding
from test_false_alarms import site, html, CFG, images_check


def client_work(count=2):
    r=report('findings',base_finding())
    r['checks'][0]['check_id']='STR-2'
    r['checks'][0]['findings']=[finding('STR-2',id=f'heading-{i}',title='1 page(s) have no <h1>',
        how_to_fix="Add one meaningful <h1> naming the page topic.",expected='one meaningful main heading',
        scope={'kind':'page','count':1,'urls':[f'https://bakery.example/branch/{i}']},
        evidence={'pages':[{'url':f'https://bakery.example/branch/{i}','headings':[]}]})for i in range(count)]
    return C.generate(r,'synthetic-nine'),r


def test_turkish_client_does_not_inherit_english_ui():
    strings.set_language('en');w,r=client_work()
    text=C.html(w)
    assert 'Intent, client behavior' not in text
    assert 'broader impact and cause require separate support' not in text
    assert 'yorumu değiştirebilir. (İngilizce)' not in text
    assert 'yorumu değiştirebilir.' in text
    from maya_audit_web.summary import item
    assert 'Intent, client behavior' in ' '.join(item(r['checks'][0]['findings'][0])['judgment']['alternatives'])


def test_client_procedures_reference_own_page_target_and_distinct_verification():
    w,r=client_work(1);r['checks'][0]['findings'].append(finding())
    w=C.generate(r,'synthetic-nine');cards=C.all_cards(w['data']);a,b=cards
    assert a['verify']!=b['verify']
    assert 'https://bakery.example/branch/0' in ' '.join(a['steps'])+a['verify']
    assert 'https://help.example/document' in ' '.join(b['steps'])+b['verify']
    assert 'GET' in b['verify'] and 'h1' in a['verify']


def test_client_procedure_preserves_numeric_evidence_counts():
    w,r=client_work(1);r['checks'][0]['findings'][0]['evidence'].update(pages=6,images=2,tables=1)
    before=deepcopy(r);w=C.generate(r,'numeric-counts')
    assert 'https://bakery.example/branch/0'in ' '.join(C.all_cards(w['data'])[0]['steps'])  # CR-11: said once, in the steps
    assert r==before


def js_report(mixed=False, render=True, rnd=True, zero=False, raw_content=False):
    u='https://workshop.example/app';v='https://workshop.example/empty'
    p={'url':u,'status':200,'body_bytes':0 if zero else 70,'analysis':{'empty_response':True,'_visible_text':'Full raw repair workshop description '*10 if raw_content else '', '_raw_html':'<div id="root"></div><script src="app.js"></script>'}}
    e=finding('IDX-1',id='empty',title='2 page(s) answer with an empty page' if mixed else '1 page(s) answer with an empty page',
        scope={'kind':'pages','count':2 if mixed else 1,'urls':[u,v]if mixed else[u]},evidence={'pages':[{'url':x,'status':200,'body_bytes':0 if zero else 70}for x in([u,v]if mixed else[u])],'unique_affected_urls':2 if mixed else 1})
    r={'crawl':{'pages':[p],'render':{'pages':{u:{'ok':True,'rendered':{'_visible_text':''if zero else'Repair services and prices described in meaningful rendered text. '*15,'headings':[{'text':'Repair services'}]}}}if render else{}}},'checks':[{'check_id':'IDX-1','status':'findings','evidence':{},'findings':[e]}]}
    if rnd:r['checks'].append({'check_id':'RND-2','status':'findings','evidence':{},'findings':[finding('RND-2',id='js',title='1 rendered page(s) have headings or prices that appear only after JavaScript (automatic candidates)',scope={'kind':'page','count':1,'urls':[u]},evidence={'pages':[{'url':u,'headings_only_after_render':['Repair services']}]})]})
    return r,u,v


def test_shell_is_one_underlying_problem_with_raw_evidence_preserved():
    r,u,_=js_report();r['findings_in_priority_order']=['empty','js'];before=deepcopy(r);q=qualify_report(r)
    fs=[f for c in q['checks']for f in c['findings']]
    assert len(fs)==1 and fs[0]['check_id']=='RND-2'
    assert q['problem_summary']['problems']==1
    assert 'server' in fs[0]['how_to_fix'].lower()
    assert 'empty' in str(fs[0]['evidence']) and r==before
    assert q['findings_in_priority_order']==['js']


@pytest.mark.parametrize('opts',[{'zero':True},{'render':False},{'rnd':False},{'raw_content':True}])
def test_shell_contrasts_not_suppressed(opts):
    r,u,_=js_report(**opts);q=qualify_report(r)
    assert q['checks'][0]['findings']


def test_mixed_shell_only_overlapping_url_is_reconciled():
    r,u,v=js_report(mixed=True);q=qualify_report(r,{'empty':[u,v],'js':[u]})
    assert q['checks'][0]['findings'][0]['scope']['urls']==[v]
    assert all('empty'not in row['finding_ids']for row in q['problem_summary']['by_page']if row['url']==u)


def test_generic_destinations_remain_distinct_in_json_and_markdown():
    from maya_audit.reanalysis import markdown
    fs=[finding('STR-14',id=f'generic-{i}',title='1 link(s) on 1 page(s) name their target only with generic text: Read more',
        evidence={'links':[{'source':'https://cafe.example/','target':f'https://cafe.example/story/{i}','links_with_generic_text':1,'texts':['Read more']}], 'shared_element':{'type':'link','container':'div.related','target':f'https://cafe.example/story/{i}'}})for i in range(4)]
    q=[qualify(f)for f in fs];assert len({f['title']for f in q})==4
    text=markdown({'checks':[{'findings':q}]})
    for i,f in enumerate(q):assert f'https://cafe.example/story/{i}' in f['title'] and f'https://cafe.example/story/{i}' in text
    assert all(f['scope']['count']==1 for f in q)


def test_generic_aggregate_title_identifies_sample_not_an_exhaustive_url_appendix():
    targets=[f'https://publisher.example/articles/{i}/a-long-but-supported-destination-name'for i in range(35)]
    f=finding('STR-14',title='35 link(s) on 1 page(s) name their target only with generic text: Read more',
        evidence={'links':[{'source':URL,'target':u,'texts':['Read more'],'links_with_generic_text':1}for u in targets]})
    before=deepcopy(f);q=qualify(f)
    assert targets[0]in q['title'] and '(+34)'in q['title'] and len(q['title'])<300
    assert q['evidence']['links']==before['evidence']['links'] and f==before


def test_sitemap_overlap_includes_http_failures_not_distinct_states():
    urls=['https://school.example/'+v for v in('missing','gone','empty','redirect','noindex','mixed')]
    states=[('error_response',404),('error_response',410),('repeated_empty',200),('redirect_observed',302),('noindex_observed',200),('contradictory',200)]
    idx=[finding('IDX-1',id=f'i{i}',title='1 page(s) answer with an empty page'if i==2 else'1 URL(s) return a client error (4xx), linked internally or listed in the sitemap',scope={'kind':'page','count':1,'urls':[u]},evidence={'pages':[{'url':u,'status':status,'empty':i==2}]})for i,(u,(state,status))in enumerate(zip(urls,states))if i<3]
    sm=finding('IDX-5',id='map',title='6 of 6 sitemap URLs are not live, indexable pages',scope={'kind':'pages','count':6,'urls':urls},evidence={'listed_urls_assessed':6,'bad_urls':[{'url':u}for u in urls], 'sitemap_decisions':[{'url':u,'state':state,'attempts':[]}for u,(state,_)in zip(urls,states)]})
    r={'crawl':{},'checks':[{'check_id':'IDX-1','status':'findings','evidence':{},'findings':idx},{'check_id':'IDX-5','status':'findings','evidence':{},'findings':[sm]}]}
    q=qualify_report(r);f=q['checks'][1]['findings'][0]
    assert f['evidence']['reported_under_idx1']['count']==3
    assert f['evidence']['separately_actionable_urls']==urls[3:]
    assert len(f['evidence']['sitemap_decisions'])==6


def frame_check(markup, incomplete=False):
    from maya_audit.checks.render import rnd4_non_text
    r,ps=site({'/':html('<main>'+markup+'</main>')});r.render=None
    for p in ps:
        p.readable_document=lambda:True;p.fetch_class=FetchClass.OK;p.content_checks_eligible=True;p.content_type='text/html';p.body_bytes=5000;p.requested_at='2026-10-21T10:00:00Z'
        if incomplete:
            for f in p.analysis['iframes']:
                for k in list(f):
                    if k not in ('src','title','in_main','in_noscript','hidden'):f.pop(k)
    return rnd4_non_text(r,CrawlConfig())


def test_iframe_accessible_name_missing_and_alternatives():
    c=frame_check('<iframe src="https://map.example/embed"></iframe>')
    assert any('accessible name' in f.title for f in c.findings)
    for attrs in ('title="Store location map"','aria-label="Store map"','aria-labelledby="frame-label"'):
        c=frame_check('<span id="frame-label">Store location map</span><iframe src="https://map.example/embed" '+attrs+'></iframe>')
        assert not any('accessible name' in f.title for f in c.findings)
    c=frame_check('<iframe src="https://map.example/embed"></iframe>',incomplete=True)
    assert not any('accessible name' in f.title for f in c.findings)
    assert c.evidence.get('iframe_names_unassessed')


@pytest.mark.parametrize('alt',['IMG_2041.jpg','IMG_1234','DSC0001','image','photo'])
def test_placeholder_alt_is_estimated_not_descriptive(alt):
    c=images_check(f'<img src="bread.jpg" alt="{alt}">')
    f=next((f for f in c.findings if 'placeholder' in f.title),None)
    assert f is not None and f.confidence.value=='estimated'
    assert alt in str(f.evidence)


@pytest.mark.parametrize('alt',['Fresh bread on the counter','A photo of fresh bread on the counter',''])
def test_meaningful_and_decorative_alt_contrasts(alt):
    role='role="presentation"'if not alt else''
    c=images_check(f'<img {role} src="bread.jpg" alt="{alt}">')
    assert not any('placeholder' in f.title for f in c.findings)


def test_partial_brand_not_a_confirmed_topic_without_independent_support():
    from test_keyword_actions import keywords, page
    for brand,token in [('Anadolu Fırın','anadolu'),('Cedar Workshop','cedar')]:
        section,data=keywords([(token,'https://kart.example/')],brand=brand,pages=[page('https://kart.example/',brand)])
        assert data['keyword_assessments'][0]['category']=='ambiguous'
        assert data['relevance']['confirmed_relevant']==0
    for q in ('anadolu fırın','ANADOLU FIRIN','anadolu firin ekmek'):
        _,d=keywords([(q,'https://kart.example/')],brand='Anadolu Fırın');assert d['keyword_assessments'][0]['category']=='branded'
    _,d=keywords([('anadolu','https://kart.example/')],brand='Anadolu Fırın',aliases=['Anadolu']);assert d['keyword_assessments'][0]['category']=='branded'


def test_real_compact_sixty_findings_and_ten_card_contrast(tmp_path):
    from pypdf import PdfReader
    w,_=client_work(60);text=C.html(w)
    content=pdf.to_pdf(text,max_pages=50);reader=PdfReader(io.BytesIO(content))
    assert len(reader.pages)<=50
    extracted='\n'.join(p.extract_text()or''for p in reader.pages)
    assert set(re.findall(r'(?<![\w-])heading-\d+(?![\w-])',extracted))=={f'heading-{i}'for i in range(60)}
    uris=[str(a.get_object().get('/A',{}).get('/URI','')) for p in reader.pages for a in p.get('/Annots',[])]
    for i in range(60):assert f'https://bakery.example/branch/{i}' in uris
    assert 'canlı' in extracted.lower() or 'doğrulan' in extracted.lower()
    (tmp_path/'sixty.pdf').write_bytes(content)
    small,_=client_work(10);rendered=C.html(small)
    # CR-04/CR-10: one main card for the check, its nine siblings in one shared-procedure block; the full export keeps ten cards.
    assert rendered.count('<section class="card ')==1 and rendered.count('data-remediation-group="true"')==1
    assert all(f'heading-{i}' in rendered for i in range(10))
    assert C.html(small,full=True).count('<section class="card ')==10
    assert 'data-remediation-group'not in C.html(w,full=True)
    (tmp_path/'ten.pdf').write_bytes(pdf.to_pdf(rendered,max_pages=50))


def test_confirmed_alias_and_independent_editorial_topic_contrasts():
    from test_keyword_actions import keywords,page
    _,d=keywords([('cedar','https://kart.example/blog/cedar')],brand='Cedar Workshop',pages=[page('https://kart.example/blog/cedar','Cedar trees: timber selection','Cedar timber treatment and wood characteristics')])
    assert d['keyword_assessments'][0]['category']=='relevant'
    _,d=keywords([('cedar','https://kart.example/')],brand='Cedar Workshop',aliases=['Cedar'])
    assert d['keyword_assessments'][0]['category']=='branded'


def test_complete_sitemap_overlap_is_evidence_not_a_second_actionable_finding():
    r,_,_=js_report(rnd=False)
    u=r['crawl']['pages'][0]['url'];r['crawl']['sitemap_urls']=[u]
    r['checks'].append({'check_id':'IDX-5','status':'findings','evidence':{},'findings':[finding('IDX-5',id='map',title='1 of 1 sitemap URLs are not live, indexable pages',scope={'kind':'page','count':1,'urls':[u]},evidence={'listed_urls_assessed':1,'sitemap_decisions':[{'url':u,'state':'uncorroborated_empty','attempts':[]}]})]})
    q=qualify_report(r)
    assert not q['checks'][1]['findings']
    assert q['checks'][1]['evidence']['retrieval_overlap']['reported_under_idx1']['count']==1
    assert q['checks'][1]['status']=='observed'
    assert q['checks'][0]['findings']


def test_real_render_rule_and_root_grouping_use_same_shell_decision():
    from maya_audit.checks.render import rnd2_critical_facts
    from maya_audit.analysis import analyze_html
    from maya_audit.findings import CheckResult,Finding,Severity,scope_for
    from maya_audit.models import Confidence
    from maya_audit.root_cause import group
    u='https://workshop.example/app';raw='<div id="root"></div><script src="app.js"></script>'
    p=NS(url=u,analysis=analyze_html(raw,u),headers={},status=200,body_bytes=len(raw),content_type='text/html',readable_document=lambda:True)
    p.analysis['_raw_html']=raw
    r=NS(origin='https://workshop.example',start_url=u,pages=[p],render=NS(pages={u:{'ok':True,'rendered':analyze_html('<h1>Repair workshop</h1><p>'+'Supported service descriptions and opening information. '*20+'</p>',u)}}),sitemap_urls=[])
    rnd=rnd2_critical_facts(r,CrawlConfig())
    assert rnd.findings
    idx=CheckResult('IDX-1','Empty','findings','',findings=[Finding('IDX-1','1 page(s) answer with an empty page',Severity.S3,Confidence.ESTIMATED,'Measured',[],scope_for([u]),{'pages':[{'url':u,'status':200,'body_bytes':len(raw)}]},'content','inspect')])
    original=deepcopy(to_jsonable(idx))
    checks=[idx,rnd];group(checks,r)
    assert not idx.findings and rnd.findings[0].evidence['related_retrieval_observations']
    again=deepcopy(to_jsonable(checks));group(checks,r);assert to_jsonable(checks)==again
    assert original['findings'][0]['id'] in str(idx.evidence)


def test_large_group_keeps_incompatible_subtypes_separate_and_owner_edits_intact():
    w,_=client_work(60)
    cards=C.all_cards(w['data']);c=cards[-1]
    c['steps']=['Başka bir onarım için sahibinin yazdığı adım.'];c['verify']='Bu ayrı işlemi kendi koşullarında doğrulamalısınız.'
    c['title']='Özel alt başlık incelemesi'
    before=deepcopy(w)
    text=C.html(w)
    assert 'Başka bir onarım' in text and c['verify'] in text
    assert 'data-remediation-group' in text and '<section class="card ' in text
    assert w==before


def test_iframe_hidden_parent_and_decorative_role_are_not_applicable():
    for markup in ('<div hidden><iframe src="https://map.example/embed"></iframe></div>', '<iframe role="presentation" src="https://map.example/embed"></iframe>'):
        c=frame_check(markup)
        assert not any('accessible name' in f.title for f in c.findings)


def test_same_procedure_preserves_distinct_member_urls():
    a,_=client_work(2);first,second=C.all_cards(a['data'])
    assert first['_procedure']['verification']==second['_procedure']['verification']
    assert first['steps']!=second['steps']  # CR-11: each member's addresses are in its steps, said once
    assert 'branch/0' in ' '.join(first['steps']) and 'branch/1' in ' '.join(second['steps'])


def test_large_h1_and_subheadings_procedures_are_not_merged(tmp_path):
    w,r=client_work(60)
    for i,f in enumerate(r['checks'][0]['findings']):
        if i%2:
            f.update(title='1 long page(s) (>1000 words) have no subheadings',how_to_fix='Review page sections and tables before adding meaningful subheadings.')
    w=C.generate(r,'synthetic-nine-mixed')
    text=C.html(w)
    assert text.count('data-remediation-group="true"')==2
    assert 'STR-2:missing-h1' in text and 'STR-2:missing-subheadings' in text
    from pypdf import PdfReader
    raw=pdf.to_pdf(text,max_pages=50);reader=PdfReader(io.BytesIO(raw));extracted='\n'.join(p.extract_text()or''for p in reader.pages)
    assert len(reader.pages)<=50 and set(re.findall(r'(?<![\w-])heading-\d+(?![\w-])',extracted))=={f'heading-{i}'for i in range(60)}
    (tmp_path/'sixty-mixed.pdf').write_bytes(raw)


def test_internal_qualified_grouping_preserves_complete_page_scope():
    from maya_audit.findings import CheckResult,Finding,Severity,scope_for
    from maya_audit.models import Confidence
    from maya_audit.judgments import qualify_checks
    us=[f'https://repair.example/page/{i}'for i in range(90)]
    f=Finding('STR-14','90 link(s) on 90 page(s) have no text at all',Severity.S4,Confidence.VERIFIED,'Measured',[],scope_for(us),{'links':[]},'named links','name them')
    before=deepcopy(f.scope)
    c=CheckResult('STR-14','Links','findings','',findings=[f]);out=qualify_checks([c],NS(pages=[],sitemap_urls=[]))
    assert out[0].findings[0].scope==before and len(out[0].findings[0].scope['_all_urls'])==90


def test_copied_reassessment_applies_placeholder_names_and_partial_identity_without_mutation():
    from maya_audit.analysis import analyze_html
    from test_keyword_actions import keywords,page
    u='https://kart.example/'
    analysis=analyze_html('<main><h1>Anadolu Fırın</h1><iframe src="https://map.example/embed"></iframe><img src="bread.jpg" alt="IMG_2041.jpg"></main>',u)
    section,_=keywords([('anadolu',u)],brand='Anadolu Fırın',pages=[page(u,'Anadolu Fırın')])
    # A stale prior decision matching the original defect, with original provider data retained.
    data=section['checks'][1]['evidence']['data'];a=data['keyword_assessments'][0]
    a.update(category='relevant',uncertain=False);a['dimensions']['service_relevance']='supported'
    r={'brand':{'name':'Anadolu Fırın','source':'owner','confirmed':True},'crawl':{'origin':u,'pages':[{'url':u,'status':200,'fetch_class':'ok','content_type':'text/html','content_checks_eligible':True,'analysis':analysis}]},
       'checks':[{'check_id':cid,'status':'pass','evidence':{},'findings':[]}for cid in('RND-4','STR-7')],'dataforseo':section}
    before=deepcopy(r);q=qualify_report(r)
    assert r==before
    assert any('accessible name'in f['title']for f in q['checks'][0]['findings'])
    assert any('placeholder'in f['title']for f in q['checks'][1]['findings'])
    d=q['dataforseo']['checks'][1]['evidence']['data']
    assert d['keyword_assessments'][0]['category']=='ambiguous' and d['record_counts']['confirmed_relevant_records']==0, d['keyword_assessments'][0]
    assert d['provider_table']==data['provider_table']
    assert q==qualify_report(q)


def test_old_frame_records_missing_naming_attributes_are_reassessment_gaps():
    from maya_audit.analysis import analyze_html
    u='https://bikes.example/'
    a=analyze_html('<main><iframe src="https://map.example/embed"></iframe></main>',u)
    a['iframes']=[{'src':'https://map.example/embed','title':None,'in_main':True,'in_noscript':False,'hidden':False}]
    r={'crawl':{'origin':u,'pages':[{'url':u,'status':200,'content_checks_eligible':True,'analysis':a}]},'checks':[{'check_id':'RND-4','status':'pass','evidence':{},'findings':[]}]}
    q=qualify_report(r);c=q['checks'][0]
    assert not c['findings'] and c['status']=='partial'
    assert any(g['part']=='iframe accessible names'for g in c['coverage']['not_assessed'])


def test_shell_reassessment_uses_public_recorded_render_counts_not_private_text():
    from maya_audit.analysis import analyze_html
    r,u,_=js_report()
    r['crawl']['pages'][0]['analysis']=analyze_html('<div id="root"></div><script src="app.js"></script>',u)
    r['crawl']['render']['pages'][u]['rendered']=analyze_html('<h1>Repair services</h1><p>'+'Workshop services described in complete visible sentences. '*20+'</p>',u)
    public=to_jsonable(r)
    assert '_visible_text' not in public['crawl']['render']['pages'][u]['rendered']
    q=qualify_report(public)
    assert not q['checks'][0]['findings'] and q['checks'][1]['findings']


def test_reassessment_does_not_present_processing_time_as_image_collection_time():
    from maya_audit.analysis import analyze_html
    u='https://bikes.example/';at='2026-10-01T12:30:00Z'
    r={'crawl':{'origin':u,'pages':[{'url':u,'status':200,'content_checks_eligible':True,'requested_at':at,'analysis':analyze_html('<main><img src="bike.jpg" alt="IMG_2041.jpg"></main>',u)}]},'checks':[{'check_id':'STR-7','status':'pass','evidence':{},'findings':[]}]}
    q=qualify_report(r);f=q['checks'][0]['findings'][0]
    assert f['evidence']['source_collection_times']==[at]
    assert f['evidence']['reassessment_processing_time']!=at
    f['evidence']['source_collection_times']=[]
    w=C.generate({**report('findings',base_finding()),'checks':q['checks']},'saved-time')
    assert C.all_cards(w['data'])[0]['evidence']['read_at']is None


def test_ordinary_offline_audit_and_copied_reassessment_share_new_name_and_alt_rules():
    from fakeserver import FakeServer,Response,Site
    from fakeserver.str_scenarios import FAST_STR
    from maya_audit.audit import run_audit
    from maya_audit.report import build_report
    body='<main><h1>Bicycle workshop</h1><p>'+('Bicycle repair services and wheel maintenance. '*40)+'</p><iframe src="/map"></iframe><img src="/repair.png" alt="IMG_1234"><a href="/booking"><img src="/booking.png"></a></main>'
    with FakeServer(Site({'/':Response(body=html(body)), '/robots.txt':Response(body='User-agent: *\nAllow: /\n',content_type='text/plain')}))as server:
        outcome=run_audit(server.base_url+'/',CrawlConfig(**{**FAST_STR,'max_pages':1,'probes_enabled':False,'prf_enabled':False,'time_limit_s':20}))
    r=build_report(outcome.result,outcome.gates,outcome.checks)
    by={c['check_id']:c for c in r['checks']}
    assert any('accessible name'in f['title']for f in by['RND-4']['findings'])
    assert any('placeholder'in f['title']for f in by['STR-7']['findings'])
    # A real image-only link still needs a name; placeholder detection does not swallow it.
    assert any('placeholder'not in f['title']for f in by['STR-7']['findings'])
    original=deepcopy(r);q=qualify_report(r);assert r==original
    assert {f['id']for c in q['checks']for f in c['findings']}=={f['id']for c in r['checks']for f in c['findings']}
    w=C.generate(q,'synthetic-bicycle-audit')
    assert any('iframe'in c['verify']for c in C.all_cards(w['data']))


def test_root_overlap_not_all_members_of_a_mixed_idx1_group():
    from maya_audit.findings import Finding,CheckResult,Severity,scope_for
    from maya_audit.models import Confidence
    from maya_audit.root_cause import group
    u='https://college.example/empty';v='https://college.example/mixed'
    f=Finding('IDX-1','2 page(s) answer with an empty page',Severity.S3,Confidence.ESTIMATED,'Measured',[],scope_for([u,v]),{'pages':[{'url':u,'status':200,'attempts':[{'status':200,'empty':True}]},{'url':v,'status':200,'attempts':[{'status':200,'empty':True},{'status':200,'empty':False}]}]},'content','inspect')
    s=Finding('IDX-5','2 of 2 sitemap URLs are not live, indexable pages',Severity.S3,Confidence.VERIFIED,'Measured',[],scope_for([u,v]),{'listed_urls_assessed':2,'bad_urls':[{'url':u},{'url':v}]},'live','inspect')
    cs=[CheckResult('IDX-1','Empty','findings','',findings=[f]),CheckResult('IDX-5','Sitemap','findings','',findings=[s])]
    group(cs,NS(pages=[],render=None,sitemap_urls=[u,v],config={}))
    assert cs[1].findings[0].scope['urls']==[v]
    assert cs[1].evidence['retrieval_overlap']['total_review_scope']['count']==2
    assert cs[1].evidence['retrieval_overlap']['reported_under_idx1']['count']==1


@pytest.mark.parametrize('state',['redirect_observed','noindex_observed','contradictory'])
def test_root_overlap_retains_separate_sitemap_state(state):
    from maya_audit.findings import Finding,CheckResult,Severity,scope_for
    from maya_audit.models import Confidence
    from maya_audit.root_cause import group
    u='https://museum.example/exhibit'
    a=Finding('IDX-1','1 URL(s) return a client error (4xx), linked internally or listed in the sitemap',Severity.S3,Confidence.VERIFIED,'Measured',[],scope_for([u]),{'pages':[{'url':u,'status':404}]},'live','inspect')
    b=Finding('IDX-5','1 of 1 sitemap URLs are not live, indexable pages',Severity.S3,Confidence.VERIFIED,'Measured',[],scope_for([u]),{'sitemap_decisions':[{'url':u,'state':state}], 'listed_urls_assessed':1},'live','inspect')
    checks=[CheckResult('IDX-1','Retrieval','findings','',findings=[a]),CheckResult('IDX-5','Map','findings','',findings=[b])]
    group(checks,NS(pages=[],render=None,sitemap_urls=[u],config={}))
    assert checks[1].findings and checks[1].findings[0].scope['urls']==[u]


def test_sitemap_independent_noindex_retained_after_http_overlap_below_threshold():
    from maya_audit.findings import Finding,CheckResult,Severity,scope_for
    from maya_audit.models import Confidence
    from maya_audit.root_cause import group
    us=['https://college.example/'+p for p in ('missing','gone','hidden')]
    a=Finding('IDX-1','2 URL(s) return a client error (4xx), linked internally or listed in the sitemap',Severity.S3,Confidence.VERIFIED,'Measured',[],scope_for(us[:2]),{'pages':[{'url':us[0],'status':404},{'url':us[1],'status':410}]},'live','inspect')
    b=Finding('IDX-5','3 of 30 sitemap URLs are not live, indexable pages',Severity.S3,Confidence.VERIFIED,'Measured',[],scope_for(us),{'listed_urls_assessed':30,'sitemap_decisions':[{'url':u,'state':'error_response'if i<2 else'noindex_observed'}for i,u in enumerate(us)]},'live','inspect')
    checks=[CheckResult('IDX-1','Retrieval','findings','',findings=[a]),CheckResult('IDX-5','Map','findings','',findings=[b])]
    group(checks,NS(pages=[],render=None,sitemap_urls=us,config={}))
    assert len(checks[1].findings)==1 and checks[1].findings[0].scope['urls']==us[2:]
    assert checks[1].evidence['retrieval_overlap']['reported_under_idx1']['count']==2


def test_card_procedure_uses_existing_turkish_validator_style_without_losing_repair():
    w,r=client_work(1);f=r['checks'][0]['findings'][0]
    f.update(check_id='STR-10',title='1 page(s) have no meta description',how_to_fix='Add meta description.')
    r['checks'][0]['check_id']='STR-10';w=C.generate(r,'meta-procedure')
    c=C.all_cards(w['data'])[0]
    assert 'açıklama'in c['steps'][0].lower()
    assert not any('steps[0]'in e and 'biçiminde'in e for e in C.validation(w)['errors'])


def test_new_frame_and_placeholder_records_keep_reader_time_separate_from_native_request():
    from maya_audit.checks.render import rnd4_non_text
    from maya_audit.checks.structure import str7_alt
    native='2026-10-01T09:00:00Z';reader='2026-10-02T12:00:00Z'
    r,ps=site({'/':html('<main><h1>Workshop</h1><iframe src="https://map.example/embed"></iframe><img src="bread.jpg" alt="IMG_1234"></main>')});r.render=None
    for p in ps:
        p.readable_document=lambda:True;p.fetch_class=FetchClass.OK;p.content_checks_eligible=True;p.content_type='text/html';p.body_bytes=5000;p.requested_at=native
        p.analysis['content_observation']={'source':'firecrawl','observed_at':reader}
    checks=[rnd4_non_text(r,CrawlConfig()),str7_alt(r,CrawlConfig(),ps,set(),set())]
    for c in checks:
        f=next(f for f in c.findings if 'accessible name'in f.title or 'placeholder'in f.title)
        rows=f.evidence.get('items')or f.evidence.get('images')
        assert rows[0]['source']=='firecrawl' and rows[0]['observed_at']==reader and rows[0]['requested_at']==native
        assert f.evidence['source_collection_times']==[reader]


def test_legacy_card_uses_qualified_action_not_unsafe_original_repair():
    w,r=client_work(1)
    f=finding('IDX-1',title='1 page(s) answer with an empty page',
        how_to_fix='Restore the page if it should exist; otherwise remove it from internal links and the sitemap, or redirect it to its closest replacement.',
        evidence={'pages':[{'url':'https://legacy.example/','status':200,'body_bytes':0}]})
    r['checks'][0].update(check_id='IDX-1',findings=[f]);before=deepcopy(r)
    c=C.all_cards(C.generate(r,'legacy-empty')['data'])[0]
    assert 'Tek boş yanıta dayanarak URL kaldırmamalı'in c['steps'][0]
    assert 'GET'in c['steps'][0] and c['judgment']['status']=='diagnostic_concern'
    assert r==before


def test_sitemap_http_overlap_expansion_does_not_change_acc8_rule():
    from maya_audit.findings import Finding,CheckResult,Severity,scope_for
    from maya_audit.models import Confidence
    from maya_audit.root_cause import group
    u='https://college.example/missing'
    a=Finding('IDX-1','1 URL(s) return a client error (4xx), linked internally or listed in the sitemap',Severity.S3,Confidence.VERIFIED,'Measured',[],scope_for([u]),{'pages':[{'url':u,'status':404}]},'live','inspect')
    b=Finding('ACC-8','1 link(s) lead to pages that do not work',Severity.S3,Confidence.VERIFIED,'Measured',[],scope_for([u]),{'not_working':[{'url':u}],'file':'llms.txt'},'live','inspect')
    before=deepcopy(to_jsonable(b));checks=[CheckResult('IDX-1','Retrieval','findings','',findings=[a]),CheckResult('ACC-8','llms','findings','',findings=[b])]
    group(checks,NS(pages=[],render=None,sitemap_urls=[],config={}))
    assert to_jsonable(checks[1].findings[0])==before
