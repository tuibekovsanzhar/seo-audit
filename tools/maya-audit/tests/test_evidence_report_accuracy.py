"""Evidence contracts across industries; no website/provider requests."""
from copy import deepcopy
from types import SimpleNamespace as NS
import pytest
from test_false_alarms import site,html,CFG
from test_judgment_consistency import finding
from maya_audit.checks.structure import image_file_findings,str2_headings
from maya_audit.checks.index import idx2_tls
from maya_audit.judgments import qualify


def images(body, responses=None):
    r,p=site({'/':html(body)})
    return image_file_findings(p,set(),NS(images=responses or {},image_candidates=0))


def test_format_markup_is_not_served_percentage_and_counts_resources():
    body='<img src="/bread.jpg" alt="Bread">'*8
    fs,obs,ev=images(body)
    assert ev['format_assessment']['occurrences']==8
    assert ev['format_assessment']['unique_resources']==1
    assert ev['format_assessment']['response_resources_assessed']==0
    assert ev['format_assessment']['delivery_unassessed_resources']==1
    assert all('offered in WebP'not in f.title for f in fs)


def test_jpeg_address_can_be_observed_webp_with_picture_alternatives():
    body='<picture><source type="image/avif" srcset="/bread.avif 1x"><img src="/bread.jpg" alt="Bread"></picture>'
    fs,obs,ev=images(body,{'x':{'url':'https://shop.example.test/bread.jpg','source':'fetched','status':200,'content_type':'image/webp','pages':['https://shop.example.test/'],'requested_at':'2026-10-18T09:00:00Z'}})
    a=ev['format_assessment'];assert a['response_formats']=={'image/webp':1}
    assert a['markup_modern_occurrences']==1
    assert a['response_observations'][0]['requested_at']=='2026-10-18T09:00:00Z'


def test_observed_jpeg_retains_actual_delivery_without_universal_conversion_claim():
    fs,obs,ev=images('<img src="/x" alt="Clinic map">',{'x':{'url':'https://shop.example.test/x','source':'fetched','status':200,'content_type':'image/jpeg','pages':['https://shop.example.test/']}})
    assert ev['format_assessment']['response_formats']=={'image/jpeg':1}
    assert ev['format_assessment']['delivery_unassessed_resources']==0


@pytest.mark.parametrize('tag,state',[('', 'absent'),('<h1></h1>','empty'),('<h1> \n </h1>','empty'),('<h1>Independent medical clinic</h1>','meaningful')])
def test_heading_state_is_retained_from_real_parser(tag,state):
    r,p=site({'/':html(tag+'<p>Clinic services.</p>')});c=str2_headings(r,CFG,p,set(),set())
    assert c.evidence['heading_assessments'][0]['state']==state
    if state=='meaningful':assert not c.findings
    else:
        f=c.findings[0]
        assert f.evidence['heading_assessments'][0]['state']==state
        if state=='empty':assert 'Fill' in f.how_to_fix and 'meaningful' in f.title


def test_partial_host_does_not_get_universal_success_summary():
    hosts=[{'host':'care.example','role':'start','tls':{'valid':True},'http_redirect':{'checked':True,'status':301,'redirects_to_https':True}}, {'host':'www.care.example','role':'variant','tls':{'valid':None,'error':'timeout'},'http_redirect':{'checked':False,'reason':'robots retrieval failed','robots_mode':'unreachable'}}]
    c=idx2_tls(NS(index=NS(hosts=hosts,variant_note=None)),CFG)
    assert 'on care.example, www.care.example'not in c.summary
    assert c.evidence['host_assessments'][1]['tls']=='failed'
    assert c.evidence['host_assessments'][1]['http_redirect']=='inconclusive'


def test_verified_hosts_remain_successful_and_real_http_serving_detected():
    hosts=[{'host':'bank.example','role':'start','tls':{'valid':True},'http_redirect':{'checked':True,'status':200,'redirects_to_https':False}}]
    c=idx2_tls(NS(index=NS(hosts=hosts,variant_note=None)),CFG)
    assert any('No HTTP to HTTPS' in f.title for f in c.findings)


def test_mixed_http_sample_does_not_expand_to_unevidenced_members():
    from maya_audit.related_evidence import retrieval_urls
    f=finding('IDX-1',title='2 URL(s) return a client error (4xx)',scope={'count':2,'urls':['https://a.example/1','https://a.example/2']},evidence={'pages':[{'url':'https://a.example/1','status':404}]})
    assert retrieval_urls(f)=={'https://a.example/1'}


def test_utility_noindex_action_requires_intent_even_when_observation_verified():
    f=finding('ACC-3',title='noindex via meta on 1 utility page(s)',how_to_fix='Remove noindex from these pages.',evidence={'directives':['noindex']})
    q=qualify(f)
    assert q['evidence']['judgment']['status']=='owner_context_required'
    assert 'Confirm' in q['how_to_fix'] and 'intent' in q['how_to_fix']
    f['intent']=True;q=qualify(f)
    assert 'retain' in q['how_to_fix'].lower()


def test_probe_coverage_not_relabelled_as_content_only():
    from maya_audit.coverage import settle,crawl_gap_part
    from maya_audit.findings import CheckResult
    c=CheckResult('IDX-5','Sitemap','pass','All checked',evidence={'listed_urls_assessed':245,'listed_urls_not_fetched':2,'sitemap_check':{'sampled':False,'not_checked':2,'not_checked_because':{'time_limit':2}}})
    settle(c,{'fetched':50,'readable':50,'impaired':0},crawl_gap_part(50,195,'cap'))
    assert all('this check ran on the 50'not in p['reason']for p in c.coverage['not_assessed'])
    assert c.evidence['assessment_scope']['sitemap_urls_assessed']==245


def test_equivalent_main_landmark_does_not_require_redundant_markup():
    from maya_audit.checks.render import rnd7_main_share
    from maya_audit.models import FetchClass
    r,p=site({'/':'<html><body><div role="main"><h1>Credit services</h1><p>Useful financial information for customers.</p></div></body></html>'})
    for page in p:
        page.readable_document=lambda:True;page.content_checks_eligible=True;page.content_type='text/html';page.fetch_class=FetchClass.OK
    c=rnd7_main_share(r,CFG)
    assert not any('no <main>'in f.title for f in c.findings)


@pytest.mark.parametrize('attr,extra',[('aria-label="Book a clinic consultation"',''),('aria-labelledby="name"','<span id="name">Book a clinic consultation</span>')])
def test_programmatically_named_generic_link_does_not_lose_its_name(attr,extra):
    from maya_audit.html_links import extract_link_edges
    from maya_audit.checks.content_quality import str14_anchor_text
    doc=html(f'<a href="/book" {attr}>Read more</a>{extra}')
    r,p=site({'/':doc});c=str14_anchor_text(r,CFG,p,set())
    assert not any('generic text' in f.title for f in c.findings)
    assert extract_link_edges(doc,p[0].url)[1]['anchor']=='Book a clinic consultation'


def test_unnamed_link_and_unqualified_generic_remain_detected():
    from maya_audit.checks.content_quality import str14_anchor_text
    r,p=site({'/':html('<a href="/chart"></a><a href="/offer">Read more</a>')})
    c=str14_anchor_text(r,CFG,p,set());assert any('generic text'in f.title for f in c.findings)
    assert any('no text'in f.title for f in c.findings)


def test_prf_evidence_separates_http_transport_and_empty_success():
    from maya_audit.checks.perf import prf2_reliability
    from maya_audit.models import FetchClass
    rows=[]
    for n,status,error,fc,body in [('empty',200,None,FetchClass.OK,0),('missing',404,None,FetchClass.OK,12),('failure',503,None,FetchClass.OK,10),('transport',None,'timeout',FetchClass.ERROR,0)]:
        rows.append(NS(url='https://finance.example/'+n,status=status,error=error,fetch_class=fc,body_bytes=body,body_truncated=False,requested_at='2026-10-19T09:00:00Z',ttfb_ms=None,elapsed_ms=1))
    c=prf2_reliability(NS(pages=rows,origin='https://finance.example',start_url='https://finance.example/',index=None,perf=None),CFG)
    assert c.evidence['request_outcomes']=={'transport_failures':1,'http_4xx':1,'http_5xx':1,'empty_2xx':1}
    assert c.evidence['failures']==2  # existing PRF2 transport/5xx definition, not all non-content responses
    assert '4xx' in c.evidence['failure_definition']


def test_complete_retrieval_membership_survives_display_sample_changes():
    from maya_audit.related_evidence import retrieval_urls
    us=['https://services.example/item/'+str(i)for i in range(55)]
    f=finding('IDX-1',title='55 URL(s) return a client error (4xx)',scope={'count':55,'urls':us[:20]},evidence={'retrieval_membership':{'urls':us,'complete':True},'pages':[{'url':u,'status':404}for u in us[:40]]})
    a=retrieval_urls(f);f['evidence']['pages']=f['evidence']['pages'][:1]
    assert a==retrieval_urls(f)==set(us)


def test_missing_membership_does_not_invent_complete_overlap():
    from maya_audit.related_evidence import reconcile
    f=finding('IDX-1',title='2 page(s) answer with an empty page',scope={'count':2,'urls':['https://archive.example/a','https://archive.example/b']},evidence={'pages':[{'url':'https://archive.example/a','status':200}]})
    g=finding('IDX-5',id='sitemap',title='30 of 40 sitemap URLs are not live, indexable pages',scope={'count':30,'urls':['https://archive.example/a']},evidence={'listed_urls_assessed':40})
    checks=[{'check_id':'IDX-1','findings':[f]},{'check_id':'IDX-5','findings':[g]}]
    q=reconcile(checks,{});e=q[1]['findings'][0]['evidence']
    assert 'overlap_unassessed'in e and not e.get('reported_under_idx1')
    assert q[1]['findings'][0]['scope']['count']==30


@pytest.mark.parametrize('cid,title',[('IDX-8','2 page(s) have nearly identical main content'),('STR-2','1 long page(s) (>800 words) have no subheadings'),('STR-14','1 link(s) on 1 page(s) name their target only with generic text: Read more')])
def test_contextual_observations_never_become_unconditional_repairs(cid,title):
    f=finding(cid,title=title,how_to_fix='Merge the pages and add markup.',evidence={'pages':[{'url':'https://library.example/archive'}]})
    q=qualify(f);assert q['evidence']['judgment']['status']=='diagnostic_concern'
    assert q['how_to_fix']!=f['how_to_fix']


def test_shared_new_audit_reassessment_and_bilingual_exports(tmp_path):
    from fakeserver import FakeServer, Site, Response
    from maya_audit.audit import run_audit
    from maya_audit.config import CrawlConfig
    from maya_audit.report import build_report
    from maya_audit.judgments import qualify_report
    from maya_audit_web import client_reports as C,strings
    from maya_audit.reanalysis import markdown
    from fakeserver.str_scenarios import FAST_STR
    # Use the existing fake-server scenario API; no provider can be contacted.
    scenario=Site({'/':Response(body='<html><head><title>Orion repair</title></head><body><div role="main"><h1> </h1><p>Orion bicycle repair appointments and servicing.</p><a aria-label="Book a repair" href="/book">Read more</a><picture><source type="image/avif" srcset="/repair.avif"><img src="/repair.jpg" alt="Wheel repair workshop"></picture><picture><source type="image/avif" srcset="/repair.avif"><img src="/repair.jpg" alt="Wheel repair workshop"></picture><picture><source type="image/avif" srcset="/repair.avif"><img src="/repair.jpg" alt="Wheel repair workshop"></picture><picture><source type="image/avif" srcset="/repair.avif"><img src="/repair.jpg" alt="Wheel repair workshop"></picture><picture><source type="image/avif" srcset="/repair.avif"><img src="/repair.jpg" alt="Wheel repair workshop"></picture><picture><source type="image/avif" srcset="/repair.avif"><img src="/repair.jpg" alt="Wheel repair workshop"></picture><picture><source type="image/avif" srcset="/repair.avif"><img src="/repair.jpg" alt="Wheel repair workshop"></picture><picture><source type="image/avif" srcset="/repair.avif"><img src="/repair.jpg" alt="Wheel repair workshop"></picture></div></body></html>'),'/robots.txt':Response(body='User-agent: *\nAllow: /\n',content_type='text/plain'),'/repair.jpg':Response(body='RIFFcontrolled-webp',content_type='image/webp')})
    with FakeServer(scenario)as server:
        outcome=run_audit(server.base_url+'/',CrawlConfig(**{**FAST_STR,'max_pages':1,'probes_enabled':False,'prf_enabled':False,'time_limit_s':20}))
    r=build_report(outcome.result,outcome.gates,outcome.checks);before=deepcopy(r);q=qualify_report(r)
    assert r==before
    fs=[f for c in q['checks']for f in c['findings']]
    heading=next(f for f in fs if f['check_id']=='STR-2' and 'meaningful'in f['title'])
    assert heading['evidence']['heading_assessments'][0]['state']=='empty'
    assert not any(f['check_id']=='STR-14' and 'generic'in f['title']for f in fs)
    image_check=next(c for c in q['checks']if c['check_id']=='STR-7')
    a=image_check['evidence']['format_assessment']
    assert a['occurrences']==8 and a['unique_resources']==1 and a['response_formats']=={'image/webp':1}
    assert heading['id']in markdown(q)
    strings.set_language('en');w=C.generate(q,'offline-evidence-acceptance');text=C.html(w)
    assert 'boş h1'in text and heading['id']in text


def test_empty_and_whitespace_heading_elements_remain_distinguishable():
    from maya_audit.analysis import analyze_html
    assert analyze_html('<h1></h1>')['h1_elements'][0]['empty_kind']=='empty'
    assert analyze_html('<h1> \n </h1>')['h1_elements'][0]['empty_kind']=='whitespace_only'


def test_sitemap_distinct_noindex_survives_a_retrieval_overlap():
    from maya_audit.related_evidence import reconcile
    u='https://college.example/utility'
    f=finding('IDX-1',title='1 URL(s) return a client error (4xx)',scope={'count':1,'urls':[u]},evidence={'pages':[{'url':u,'status':404}]})
    g=finding('IDX-5',id='map',title='1 of 1 sitemap URLs are not live, indexable pages',scope={'count':1,'urls':[u]},evidence={'listed_urls_assessed':1,'sitemap_decisions':[{'url':u,'state':'noindex_observed'}]})
    q=reconcile([{'check_id':'IDX-1','findings':[f]},{'check_id':'IDX-5','findings':[g]}],{})
    assert q[1]['findings'] and not q[1]['findings'][0]['evidence'].get('reported_under_idx1')


def test_rnd7_recommendation_does_not_require_redundant_landmark():
    q=qualify(finding('RND-7',title='1 page(s) have no <main> or <article> element',how_to_fix='Wrap everything in main.',evidence={'pages':['https://finance.example/']}))
    assert 'ARIA' in q['how_to_fix'] and q['evidence']['judgment']['status']=='informational_observation'


def test_format_reassessment_retains_source_and_historical_response_scope():
    from maya_audit.judgments import qualify_report
    from maya_audit.analysis import analyze_html
    u='https://clinic.example/';a=analyze_html('<main>'+('<img src="/x.jpg" alt="Clinic entrance">'*8)+'</main>',u)
    f=finding('STR-7',id='format',title='0% of 8 content image(s) are offered in WebP or AVIF',expected='served in smaller formats',evidence={'images':8,'with_webp_or_avif':0})
    r={'crawl':{'origin':u,'pages':[{'url':u,'status':200,'fetch_class':'ok','content_checks_eligible':True,'analysis':a}], 'structure':{'images':{u+'x.jpg':{'url':u+'x.jpg','source':'fetched','status':200,'content_type':'image/webp','requested_at':'2026-09-01T09:00:00Z'}}}},'checks':[{'check_id':'STR-7','status':'findings','evidence':{},'findings':[f]}]}
    before=deepcopy(r);q=qualify_report(r);assert r==before
    f=q['checks'][0]['findings'][0];assert 'percentage'not in f['title'] and 'delivery assessed separately'in f['title']
    assert 'quality evidence'in f['expected'] and f['evidence']['format_assessment']['response_formats']=={'image/webp':1}
    assert f['evidence']['format_assessment']['response_observations'][0]['requested_at']=='2026-09-01T09:00:00Z'


def test_saved_partial_host_coverage_does_not_call_retrieval_error_a_disallow():
    from maya_audit.evidence_accuracy import refresh_check_scope
    c={'check_id':'IDX-2','summary':'Certificates valid and http:// redirects to https:// on every host.', 'evidence':{'hosts':[{'host':'finance.example','tls':{'valid':True},'http_redirect':{'checked':False,'robots_mode':'unreachable','reason':'robots.txt disallows it: treated as unreachable'}}]},'coverage':{'not_assessed':[{'part':'TLS / HTTP→HTTPS per host','reason':'robots disallows'}]}}
    refresh_check_scope(c)
    assert 'inconclusive'in c['summary'] and 'did not establish a disallow rule'in str(c['coverage'])
    assert c['evidence']['hosts'][0]['http_redirect']['reason']=='robots.txt disallows it: treated as unreachable'


def test_legacy_format_counts_without_reference_membership_do_not_keep_delivery_percentage():
    q=qualify(finding('STR-7',title='24% of 84 content image(s) are offered in WebP or AVIF',severity='Info',evidence={'format_counts':{'webp':20,'jpeg':64}}))
    assert 'unassessed' in q['title'] and '%' not in q['title']
    assert q['evidence']['judgment']['source']['title'].startswith('24%')
    assert q['evidence']['format_counts']=={'webp':20,'jpeg':64}
