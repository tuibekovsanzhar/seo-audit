"""Evidence-to-decision contracts, using fabricated examples and genuine contrasts."""
import copy
import pytest
from maya_audit_web import summary, client_reports
from maya_audit.dataforseo import insights
from test_report_agreement import demo_app


def finding(cid='IDX-6', **changes):
    f={'id':cid+'-case','check_id':cid,'title':'1 link(s) to other sites on 1 page(s) return 404 or 410',
       'severity':'S4','confidence':'estimated','rationale':'Hypothesis','engines':[],
       'scope':{'kind':'page','count':1,'urls':['https://cafe.example/policy']},
       'observed_at':'2026-10-19T10:00:00Z','notes':[],'launch_gated':[],
       'how_to_fix':'Remove the broken link.','expected':'working destination',
       'evidence':{'links':[{'target':'https://help.example/document','status':404,'method':'HEAD','requested_at':'2026-10-19T10:00:00Z'}]}}
    f.update(changes);return f


def test_head_only_headline_and_action_do_not_claim_deleted_destination():
    f=finding();before=copy.deepcopy(f);row=summary.item(f)
    assert 'HEAD' in row['title_shown'] and 'has removed' not in row['why'] and 'not established' in row['why']
    assert row['judgment']['status']=='diagnostic_concern'
    assert row['estimates']['owner']=='content' and row['estimates']['effort']=='S'
    assert f==before


def test_quick_win_summary_is_not_blanket_instruction_for_unknown_relevance():
    # The provider's numeric rank is not a business relevance assessment.
    reply={'tasks':[{'result':[{'total_count':10,'items':[{'keyword_data':{'keyword':'mountain legend','keyword_info':{'search_volume':900}},'ranked_serp_element':{'serp_item':{'rank_group':4,'url':'https://cafe.example/article'}}}]}]}]}
    text,data=insights._quick_wins(reply)
    assert 'improve the ranking page for each' not in text
    assert 'candidate' in text.lower() and data['listed']==1


def test_empty_h1_is_not_meaningful_heading():
    from test_false_alarms import site,html,CFG
    from maya_audit.checks.structure import str2_headings
    result,pages=site({'/':html('<h1> </h1><p>Independent repair workshop.</p>')})
    # html() supplies a heading; explicitly replace all heading observations to isolate the parser contract.
    pages[0].analysis['headings']=[{'level':1,'text':'   '}]
    c=str2_headings(result,CFG,pages,set(),set())
    assert c.findings and 'meaningful' in c.findings[0].title


def test_image_roles_are_coverage_not_pass_and_records_are_not_unique_images():
    from maya_audit.coverage import derive
    roles=[{'url':'https://cafe.example/menu','element_id':'img:1','src':'https://cafe.example/a.png'}]*2
    gaps=derive('STR-7','pass',{'unassessed_image_roles':roles},[] )['not_assessed']
    assert any(g['part']=='unresolved image roles' and g['count']==1 for g in gaps)


def test_sitemap_states_are_unique_scoped_and_owner_context_is_not_inferred():
    from maya_audit.judgments import sitemap_states,qualify
    root='https://workshop.example/'
    def row(path,**kw):return dict(url=root+path,status=200,fetch_class='ok',bytes=0,empty=True,requested_at='2026-10-19T09:00:00Z',**kw)
    rows=[row('once'),row('twice'),row('recovers'),row('excluded',noindex=['noindex'])]
    rows[-1].update(bytes=40,empty=False)
    rows += [dict(url=root+'old',status=301,fetch_class='ok',location=root+'new',requested_at='2026-10-19T09:00:00Z'),dict(url=root+'gone',status=404,fetch_class='ok')]
    crawl={'sitemap_urls':[r['url']for r in rows]+[root+'unknown',root+'once'],'pages':[], 'index':{'sitemap_check':{'rows':rows},'refetches':[
        {'url':root+'twice','refetch':{'status':200,'body_bytes':0,'empty_response':True,'requested_at':'2026-10-19T09:02:00Z','fetch_class':'ok'}},
        {'url':root+'recovers','refetch':{'status':200,'body_bytes':60,'empty_response':False,'requested_at':'2026-10-19T09:02:00Z','fetch_class':'ok'}}]}}
    states=sitemap_states(crawl);by={r['url'].removeprefix(root):r for r in states}
    assert len(states)==7
    assert by['twice']['state']=='repeated_empty' and by['once']['state']=='uncorroborated_empty'
    assert by['recovers']['state']=='contradictory' and by['unknown']['state']=='unknown'
    assert by['gone']['state']=='error_response' and by['old']['attempts'][0]['location']==root+'new'
    assert by['excluded']['state']=='noindex_observed' and by['excluded']['owner_indexing_requirement']=='not_recorded'
    f=finding('IDX-5',title='5 of 6 sitemap URL(s) (83%) are not live, indexable pages',evidence={'listed_urls_assessed':6})
    q=qualify(f,sitemap=states)
    assert 'differentiated review' in q['title'] and q['evidence']['sitemap_state_counts']['uncorroborated_empty']==1
    assert q['id']==f['id'] and 'Corroborate single empty' in q['how_to_fix']
    assert all(r['action']for r in q['evidence']['sitemap_decisions'])


@pytest.mark.parametrize('status',[404,410])
def test_get_confirmed_external_error_is_retained(status):
    from maya_audit.judgments import qualify
    f=finding(evidence={'links':[{'method':'GET','status':status,'target':'https://museum.example/missing','requested_at':'2026-10-19T10:00:00Z'}]})
    q=qualify(f);assert q['severity']==f['severity'] and q['evidence']['judgment']['status']=='confirmed_within_tested_scope'


def test_rate_limit_cannot_confirm_head_deletion_and_scope_verification_is_not_review():
    f=finding();f['evidence']['links'][0]['attempts']=[{'method':'GET','status':429,'requested_at':'2026-10-19T10:02:00Z'}]
    r=summary.item(f);assert r['judgment']['status']=='diagnostic_concern' and 'GET navigation is unverified'in r['title']
    assert r['judgment']['verification_status']=='recorded_evidence_only'
    assert 'not verification'in r['verification']


def test_provider_counts_never_sum_overlapping_classifications():
    rows=[['bisiklet tamiri',100,8,'https://cycle.example/repair'],['bahar efsanesi',400,5,'https://cycle.example/article']]
    data={'provider_table':{'rows':rows+[rows[0]],'columns':['Keyword','Searches','Position','URL']},'table':{'rows':rows},
          'ambiguous':{'rows':[rows[1]]},'intent_dimensions':{'rows':rows},'keyword_assessments':[
          {'keyword':rows[0][0],'ranking_url':rows[0][3],'uncertain':False,'dimensions':{'service_relevance':'supported'}},
          {'keyword':rows[1][0],'ranking_url':rows[1][3],'uncertain':True,'dimensions':{'editorial_relevance':'unknown'}}]}
    c=insights.keyword_counts(data)
    assert c['provider_records']==3 and c['unique_provider_records']==2 and c['unique_queries']==2
    assert c['confirmed_commercial_candidates']==1 and c['uncertain_candidates']==1
    assert c['intent_classification_rows']==2
    q=insights.qualified_opportunity_data({'table':{'rows':rows}})
    assert not any(q['opportunity_evidence'].values()) # rank alone is not a commercial decision


def test_qualified_reassessment_is_immutable_idempotent_and_coverage_is_not_pass():
    from maya_audit.judgments import qualify_report
    r={'crawl':{'pages':[]},'checks':[{'check_id':'STR-7','status':'pass','findings':[], 'evidence':{'unassessed_image_roles':[{
        'url':'https://gallery.example/','src':'https://gallery.example/chart.png','element_id':'image-1','source':'native','observed_at':'2026-10-18T10:00:00Z'}]}},
        {'check_id':'IDX-6','status':'findings','findings':[finding()]}]}
    before=copy.deepcopy(r);q=qualify_report(r);assert r==before and q==qualify_report(q)
    assert q['checks'][0]['status']=='partial'
    assert q['checks'][1]['findings'][0]['id']==r['checks'][1]['findings'][0]['id']


def test_context_review_keeps_distinct_targets_and_avoids_automatic_consolidation():
    from maya_audit.judgments import qualify
    f=finding('STR-14',title='2 link(s) on 1 page(s) name their target only with generic text: details',
       evidence={'links':[{'source':'https://cycle.example/','target':'https://cycle.example/repair','links':7,'links_with_generic_text':1},
                          {'source':'https://cycle.example/','target':'https://cycle.example/shop','links':3,'links_with_generic_text':1}],'count':2})
    q=qualify(f);assert q['evidence']['links']==f['evidence']['links'] and q['evidence']['judgment']['status']=='diagnostic_concern'
    assert 'surrounding text'in q['how_to_fix'] and 'retain useful distinct destinations'in q['how_to_fix']
    for cid in ('STR-15','IDX-8'):
        q=qualify(finding(cid,title='Similar or short pages',evidence={}))
        assert q['evidence']['judgment']['action']['requires_owner_or_evidence_decision']
        assert 'purpose'in q['how_to_fix'] and 'owner'in q['how_to_fix']


def test_meaningful_heading_is_retained_and_long_table_is_context_not_prose_failure():
    from test_false_alarms import site,html,CFG
    from maya_audit.checks.structure import str2_headings
    from maya_audit.judgments import qualify_checks
    r,pages=site({'/':html('<h1>Workshop prices</h1><table>'+''.join('<tr><td>Service rate listed here</td><td>25 EUR</td></tr>'for _ in range(200))+'</table>')})
    c=str2_headings(r,CFG,pages,set(),set());q=qualify_checks([c],r)[0]
    assert not any('no <h1>'in f.title or 'no meaningful <h1>'in f.title for f in q.findings)
    for f in q.findings:
        if 'no subheadings'in f.title:assert 'Tables and lists may already structure'in f.how_to_fix and f.evidence['judgment']['status']=='diagnostic_concern'


def test_ordinary_new_audit_json_markdown_actions_and_client_use_shared_decision(demo_app):
    from test_report_agreement import audit
    from maya_audit_web import demo
    one=audit(demo_app,demo.SHOP,search_data=True,market_default_accepted=True);base='/api/v1/audits/'+one['id']
    r=demo_app.get(base+'/downloads/json');assert r.status_code==200
    report=r.json();findings=[f for c in report['checks']for f in c['findings']]
    assert findings and all(f['evidence']['judgment']['version']=='judgment-v1'for f in findings)
    for check in report['dataforseo']['checks']:
        if check['check_id'] in ('DFS-4','DFS-5'):
            d=check['evidence']['data'];assert d['record_counts']==insights.keyword_counts(d)
            assert 'improve the ranking page for each' not in check['summary']
    markdown=demo_app.get(base+'/downloads/markdown');assert markdown.status_code==200
    # IDX-6's broken targets are one Markdown card (review CR-02); the JSON keeps one finding per target.
    for f in findings:assert f['title']in markdown.text or (f['check_id']=='IDX-6' and 'internal link targets return' in markdown.text)
    # Actual saved source -> draft uses the same technical action metadata, not a second owner/effort catalog.
    w=demo_app.post(base+'/client-report',json={});assert w.status_code==200
    cards=w.json()['data']['cards']+w.json()['data']['appendix_cards']
    for card in cards:
        f=next(f for f in findings if f['id']==card['id']);row=summary.item(f)
        assert card['owner']=={'developer':'Geliştirici','content':'İçerik','seo':'SEO'}[row['estimates']['owner']]
        assert card['effort']=={'S':'Küçük','M':'Orta','L':'Büyük'}[row['estimates']['effort']]
    assert w.json()['validation']['verified_findings']==0
    assert demo_app.get(base+'/client-report/export/html?mode=final').status_code==422


def test_conflicting_get_success_is_visible_without_erasing_the_request_failure():
    from maya_audit.judgments import qualify
    f=finding();f['evidence']['links'][0]['attempts']=[{'method':'GET','status':200,'requested_at':'2026-10-19T11:00:00Z','body_bytes':100}]
    q=qualify(f);assert q['evidence']['judgment']['status']=='contradictory_evidence'
    assert 'mixed HEAD/GET' in q['title'] and q['evidence']['links'][0]['status']==404


def test_unknown_200_is_not_assessed_and_unrelated_is_not_uncertain_or_relevant():
    from maya_audit.judgments import sitemap_states
    c={'sitemap_urls':['https://museum.example/a'],'pages':[{'url':'https://museum.example/a','status':200,'fetch_class':'ok'}]}
    assert sitemap_states(c)[0]['state']=='unknown'
    data={'provider_table':{'rows':[['galaxy theory',10,5,'https://museum.example/a']]},'keyword_assessments':[{
        'keyword':'galaxy theory','ranking_url':'https://museum.example/a','uncertain':False,'dimensions':{'unrelated_intent':'supported'}}]}
    counts=insights.keyword_counts(data)
    assert counts['unrelated_records']==1 and counts['confirmed_relevant_records']==counts['uncertain_candidates']==0


def test_review_does_not_authorize_uncorroborated_removal(demo_app):
    from test_client_report_app import synthetic,endpoint,card_body
    from maya_audit_web import client_reports as C
    one,path,report=synthetic(demo_app);report['checks'][0]['findings']=[finding(id='f0')]
    report['findings_in_priority_order']=['f0'];import json;path.write_text(json.dumps(report))
    base=endpoint(demo_app,one);work=demo_app.post(base,json={}).json();body=card_body(work)
    body['steps']=['Tüm URLleri sitemap dosyasından çıkarmalısınız.']
    r=demo_app.put(base+'/cards/f0',json=body);assert r.status_code==200
    work=r.json();work=demo_app.post(base+'/review',json={'revision':work['revision'],'reviewer':'Owner','reason':'Read the draft'}).json()
    assert not work['validation']['valid'] and any('consequential action' in e for e in work['validation']['errors'])
    assert work['validation']['verified_findings']==0
    assert demo_app.get(base+'/export/html?mode=final').status_code==422
    assert demo_app.get(base+'/export/html?mode=draft').status_code==200


def test_missing_support_cannot_keep_a_verified_deleted_destination_claim():
    f=finding(evidence={},confidence='verified');before=copy.deepcopy(f)
    row=summary.item(f)
    assert row['judgment']['status']=='not_assessed'
    assert row['confidence']=='not_assessed' and 'evidence unavailable' in row['title']
    assert 'has removed' not in row['why'] and f==before


def test_human_review_cannot_erase_contradictory_verified_request_context(demo_app):
    from test_client_report_app import synthetic,endpoint,card_body
    import json
    one,path,r=synthetic(demo_app)
    f=finding(id='f0',confidence='verified',evidence={'links':[{'target':'https://help.example/a','method':'GET','status':404,
       'attempts':[{'method':'GET','status':200,'body_bytes':100,'requested_at':'2026-10-19T11:00:00Z'}]}]})
    r['checks'][0]['findings']=[f];r['findings_in_priority_order']=['f0'];path.write_text(json.dumps(r));base=endpoint(demo_app,one)
    w=demo_app.post(base,json={}).json();assert (w['data']['cards']+w['data']['appendix_cards'])[0]['judgment']['status']=='contradictory_evidence'
    body=card_body(w);body.update(title='Hedef silindi.',steps=['Bağlantıyı kaldırmalısınız.'])
    w=demo_app.put(base+'/cards/f0',json=body).json();w=demo_app.post(base+'/review',json={'revision':w['revision'],'reviewer':'Owner','reason':'Read'}).json()
    assert any('source uncertainty' in e for e in w['validation']['errors'])
    assert any('consequential action' in e for e in w['validation']['errors'])
    assert demo_app.get(base+'/export/html?mode=final').status_code==422


def test_qualified_generic_headline_keeps_numeric_page_values_independent_of_title():
    from maya_audit.judgments import qualify
    from maya_audit.report import page_item,problem_summary
    urls=['https://repair.example/','https://repair.example/services']
    f=finding('STR-14',title='5 link(s) on 2 page(s) name their target only with generic text: details',
       scope={'kind':'pages','count':2,'urls':urls},evidence={'count':2,'occurrences':5,'links':[
           {'source':urls[0],'target':urls[1],'links':7,'links_with_generic_text':2},
           {'source':urls[1],'target':urls[0],'links':8,'links_with_generic_text':3}]})
    q=qualify(f);assert 'generic-text' in q['title']
    assert [page_item(q,u)['values']['links']for u in urls]==[2,3]
    q['title']='A completely different editorial heading'
    assert [page_item(q,u)['values']['links']for u in urls]==[2,3]
    totals=problem_summary([q],{q['id']:urls},pages_checked=2)
    assert sum(i['values']['links']for row in totals['by_page']for i in row['items'])==5


def test_client_pdf_appendix_does_not_reprint_derived_judgment_as_raw_evidence(demo_app):
    from test_client_report_app import synthetic,endpoint
    import json
    one,path,r=synthetic(demo_app)
    r['checks'][0]['findings']=[finding(id='f0')];r['findings_in_priority_order']=['f0']
    path.write_text(json.dumps(r));base=endpoint(demo_app,one)
    w=demo_app.post(base,json={}).json()
    before=copy.deepcopy(w)
    rendered=demo_app.get(base+'/export/html?mode=draft&full=true')
    assert rendered.status_code==200
    text=rendered.text
    assert 'Companion JSON: evidence.judgment' in text
    assert '"method": "HEAD"' in text or '&quot;method&quot;: &quot;HEAD&quot;' in text
    assert 'Kayıtlı kaynak yargısı' in text and w==before


def test_missing_or_refused_keyword_panels_remain_unavailable_not_zero():
    section={'checks':[{'check_id':'DFS-4','status':'not_assessed','refusal':'audit cap'},
                       {'check_id':'DFS-5','status':'not_assessed','evidence':{'data':None}}]}
    before=copy.deepcopy(section)
    assert insights.qualify_section(section)==before and section==before
    # A measured empty result is different from a panel that was not requested.
    measured={'checks':[{'check_id':'DFS-4','status':'pass','evidence':{'data':{'table':{'rows':[]},'total_count':0}}}]}
    counts=insights.qualify_section(measured)['checks'][0]['evidence']['data']['record_counts']
    assert counts['provider_records']==0 and counts['provider_total']==0


def test_observation_times_accept_attempt_counts_and_request_records():
    from maya_audit.judgments import qualify
    f=finding('PRF-1',title='1 URL(s) time out on some attempts but not others',evidence={'pages':[
        {'url':'https://museum.example/tickets','attempts':3,'requested_at':'2026-10-19T10:00:00Z'},
        {'url':'https://museum.example/guide','attempts':[{'method':'GET','status':504,'requested_at':'2026-10-19T11:00:00Z'}]}]})
    before=copy.deepcopy(f);q=qualify(f)
    assert q['evidence']['judgment']['source_observation_times']==['2026-10-19T10:00:00Z','2026-10-19T11:00:00Z']
    assert q['evidence']['pages']==f['evidence']['pages'] and f==before
    assert q['severity']==f['severity'] and q['title']==f['title']


def test_qualified_observation_is_not_the_unsupported_original_headline():
    from maya_audit.judgments import qualify
    f=finding(title='1 destination was removed and navigation is broken')
    q=qualify(f);j=q['evidence']['judgment']
    assert j['source']['title']==f['title']  # Historical output stays traceable.
    assert 'HEAD' in j['observation'] and 'was removed' not in j['observation']
    measured=finding(evidence={'links':[{'target':'https://help.example/a','method':'GET','status':404}]})
    j=qualify(measured)['evidence']['judgment']
    assert 'GET' in j['observation'] and '404' in j['observation']
