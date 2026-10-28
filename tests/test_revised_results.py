"""One registered saved-evidence result, one source for every output; original remains intact."""
import copy
import hashlib
import io
import json
import shutil
from pathlib import Path
import pytest
from maya_audit.report import read_counts
from maya_audit.reanalysis import refresh_metrics
from maya_audit_web import pdf, demo, client_reports
from maya_audit_web.analyses import Registry
from test_report_agreement import demo_app, audit


def test_known_empty_ineligible_native_responses_are_not_readable_pages():
    pages = [{'url':f'https://cafe.example/empty/{i}', 'status':200,'fetch_class':'ok','error':None,
              'body_bytes':0,'analysis':{'empty_response':{'body_bytes':0}},'content_checks_eligible':False} for i in range(9)]
    reader = {'used':True, 'pages':[{'url':f'https://cafe.example/article/{i}','outcome':'read'}for i in range(50)]}
    counts = read_counts({'pages':pages},reader)
    assert counts['pages']==50 and counts['read_by']=={'maya_only':0,'firecrawl_only':50,'both':0,'firecrawl':50,'total':50}
    valid={'url':'https://cafe.example/small','status':200,'fetch_class':'ok','error':None,'body_bytes':15,
           'analysis':{'words':2},'content_type':'text/html','content_checks_eligible':True}
    assert read_counts({'pages':pages+[valid]},reader)['pages']==51
    # Any one explicit negative suffices. An HTTP200 is transport evidence only.
    for overrides in ({'body_bytes':0},{'analysis':{'empty_response':True}},{'content_checks_eligible':False}):
        assert read_counts({'pages':[{**valid,**overrides}]})['pages']==0


def registered(client, tmp_path):
    source=audit(client,demo.SHOP);original=client.app.state.runner.artifacts(source['id'])
    report=json.loads((original/'report.json').read_text(encoding="utf-8"));before=(original/'report.json').read_bytes()
    check=next(c for c in report['checks']if c['check_id']=='STR-14');old={f['id']for f in check['findings']}
    seed=copy.deepcopy(next(f for c in report['checks']for f in c['findings']))
    urls=['https://cafe.example/','https://cafe.example/articles']
    seed.update(id='STR-14-generic-test',check_id='STR-14',title='5 link(s) on 2 page(s) name their target only with generic text: "details" (5)',
        scope={'kind':'pages','count':2,'of':None,'urls':urls,'_all_urls':urls},severity='S4',confidence='verified',
        evidence={'count':2,'links':[{'source':urls[0],'target':urls[1],'links':7,'links_with_generic_text':2},
                                  {'source':urls[1],'target':urls[0],'links':8,'links_with_generic_text':3}]})
    check['findings']=[seed];report['findings_in_priority_order']=[seed['id']]+[i for i in report['findings_in_priority_order']if i not in old]
    # A stale persisted table must be refreshed in the copied report, not fixed only on screen.
    report=refresh_metrics(report);assert sum(i['values'].get('links',0)for r in report['problem_summary']['by_page']for i in r['items']if i['finding_id']==seed['id'])==5
    identity='analysis-cafe-saved-r1';root=tmp_path/'separate';folder=root/identity/'artifacts';shutil.copytree(original,folder)
    meta={'id':identity,'label':'Cafe — revised evidence r1','source_audit_id':source['id'],'analysis_version':'saved-metrics-1',
          'processed_at':'2026-10-19T12:00:00+00:00','source_report_sha256':hashlib.sha256(before).hexdigest()}
    report.setdefault('generation',{})['analysis']=copy.deepcopy(meta)
    data=json.dumps(report,ensure_ascii=False,indent=2).encode();(folder/'report.json').write_bytes(data)
    (folder/'affected-urls.json').write_text(json.dumps({seed['id']:urls}))
    meta['report_sha256']=hashlib.sha256(data).hexdigest()
    row=copy.deepcopy(client.app.state.store.audit(source['id']));row.update(id=identity,state='finished')
    (folder.parent/'analysis.json').write_text(json.dumps({'audit':row,'analysis':meta}))
    client.app.state.analyses.folder=root.resolve()
    return identity,source,before,report,folder


def test_registered_result_reuses_normal_summary_download_actions_and_client_flow(demo_app,tmp_path,monkeypatch):
    identity,source,before,report,folder=registered(demo_app,tmp_path);base='/api/v1/audits/'+identity
    assert demo_app.get('/api/v1/analyses').json()['analyses'][0]['id']==identity
    assert demo_app.get(base+'/conversation').json()['messages'][0]['kind']=='audit'
    view=demo_app.get(base+'/summary');assert view.status_code==200
    assert view.json()['audit']['analysis']['id']==identity and view.json()['firecrawl_offer'] is None
    download=demo_app.get(base+'/downloads/json');assert download.json()==report
    assert download.headers['x-maya-analysis-id']==identity and download.headers['x-maya-exported-at']
    assert identity in download.headers['content-disposition']
    assert hashlib.sha256(download.content).hexdigest()==download.headers['x-maya-report-sha256']
    assert sum(i['values'].get('links',0)for r in download.json()['problem_summary']['by_page']for i in r['items']if i['finding_id']=='STR-14-generic-test')==5
    assert demo_app.get(base+'/practical').json()['analysis']['id']==identity
    assert demo_app.get(base+'/action-plan').json()['analysis']['id']==identity
    assert 'STR-14-generic-test' in demo_app.get(base+'/action-plan').text
    printed=demo_app.get(base+'/print?full=false');assert printed.status_code==200 and identity in printed.text
    captured=[]
    monkeypatch.setattr(pdf,'to_pdf',lambda html,**kw:captured.append(html) or b'%PDF-test')
    assert demo_app.get(base+'/downloads/pdf').content==b'%PDF-test' and identity in captured[0]
    workspace=demo_app.post(base+'/client-report',json={});assert workspace.status_code==200
    assert (folder/'client-report.json').exists()
    assert workspace.json()['validation']['verified_findings']==0
    assert demo_app.get(base+'/client-report/export/html?mode=draft').status_code==200
    assert demo_app.get(base+'/client-report/export/html?mode=final').status_code==422
    for suffix,method in [('',demo_app.delete),('/resume',demo_app.post),('/firecrawl/read',demo_app.post),('/messages',demo_app.post)]:
        assert method(base+suffix, **({"json":{}} if suffix else {})).status_code==409
    assert demo_app.get('/api/v1/audits').json()['total']==1
    assert (demo_app.app.state.runner.artifacts(source['id'])/'report.json').read_bytes()==before
    assert (folder/'report.json').read_bytes()==download.content


def test_registry_rejects_unsafe_or_tampered_entries(demo_app,tmp_path):
    identity,*_,folder=registered(demo_app,tmp_path)
    assert Registry.accepts(identity) and not Registry.accepts('../private')
    (folder/'report.json').write_text('{}')
    assert demo_app.get('/api/v1/analyses').json()=={'analyses':[]}
    assert demo_app.get('/api/v1/audits/'+identity+'/downloads/json').status_code==404


def test_refresh_preserves_source_and_noncontent_counts_and_restates_coverage():
    original = {'crawl':{'pages':[{'url':'https://cafe.example/','status':200,'error':None,'fetch_class':'ok',
        'body_bytes':0,'analysis':{'empty_response':True},'content_checks_eligible':False}]},
        'audit_status':{'content_coverage':{'level':'partial','pages_read':1,'known_urls_not_read':2}},
        'checks':[{'check_id':'STR-2','status':'partial','findings':[], 'coverage':{'not_assessed':[{
            'part':'pages found but not read','reason':'this check ran on the 1 page(s) that were read; 2 more page(s) were found and not read (page cap of 1 reached).','count':2}]}}],
        'problem_summary':{'single_page':{'url':'https://cafe.example/'}}}
    before = copy.deepcopy(original)
    revised = refresh_metrics(original)
    assert original==before and revised['problem_summary']['single_page']==original['problem_summary']['single_page']
    assert revised['audit_status']['content_coverage']['pages_read']==0
    assert '0 page(s)' in revised['checks'][0]['coverage']['not_assessed'][0]['reason']
