"""Evidence-strength and concise export contracts, independent of a customer's domain."""
import copy
import re
import io
from types import SimpleNamespace as NS
import pytest
from maya_audit import external_links
from maya_audit.config import CrawlConfig
from maya_audit.fetcher import RawResponse
from maya_audit.models import Confidence, FetchClass, to_jsonable
from maya_audit.findings import Severity
from maya_audit.classify import empty_response
from maya_audit.checks.index import _empty_pages
from maya_audit.checks.structure import str8_semantic_tables
from maya_audit.analysis import analyze_html
from maya_audit_web import pdf, summary, strings
from test_false_alarms import site, html, CFG, no_lookups
from test_report_agreement import demo_app


def external(monkeypatch, replies, blocked_after=None):
    result=NS(pages=[],index=None);calls=[]
    def room(*args,**kwargs):
        return 'cap' if blocked_after is not None and len(calls)>=blocked_after else None
    monkeypatch.setattr(external_links,'room',room)
    def get(url,purpose,limit,method='GET'):
        calls.append((url,method));status,loc=replies.pop(0)
        return RawResponse(url,status,{'location':loc} if loc else {},b'<p>Valid content</p>' if status==200 else b'',False,1,None,'2026-10-19T10:00:00Z')
    row=external_links.check(NS(get=get),result,CrawlConfig(),'https://help.example/a')
    return row,calls


@pytest.mark.parametrize('get,expected',[(200,'works'),(404,'broken'),(410,'broken'),(429,'refused')])
def test_suspicious_head_requires_bounded_get(monkeypatch,get,expected):
    row,calls=external(monkeypatch,[(404,None),(get,None)])
    assert row['verdict']==expected and [c[1] for c in calls]==['HEAD','GET']
    assert len(row['attempts'])==2 and row['attempts'][0]['status']==404
    assert row['checked']==(expected in ('works','broken'))


def test_external_redirects_and_budget_missing_confirmation(monkeypatch):
    row,calls=external(monkeypatch,[(302,'https://help.example/b'),(200,None)])
    assert row['verdict']=='works' and row['final_url'].endswith('/b')
    row,calls=external(monkeypatch,[(404,None),(302,'https://help.example/a')])
    assert row['verdict']=='redirect_loop' and not row['checked']
    row,calls=external(monkeypatch,[(404,None)],blocked_after=1)
    assert row['verdict']=='uncorroborated' and len(calls)==1


def browser_answer(u,content=False):
    """index_data.empty_browser_check's record (first review C1/C2): the page asked once more as a browser."""
    return {'answers':[{'url':u,'sent':True,'status':200,'empty_response':not content,'content':content,
                        'requested_at':'2026-10-19T01:02:00Z'}],'user_agent':'browser','cap':3}


def empty_case(*,key=False,again=None,light=False,browser='empty'):
    u='https://cafe.example/menu'
    p=NS(url=u,depth=1,status=200,body_bytes=0,content_type='text/html',requested_at='2026-10-19T01:00:00Z',
         analysis={'empty_response':True},fetch_class=FetchClass.OK)
    r=NS(pages=[] if light else [p],start_url='https://cafe.example/',origin='https://cafe.example')
    row={'url':u,'status':200,'bytes':0,'content_type':'text/html','requested_at':p.requested_at,'empty':True,'fetch_class':'ok'}
    check=None if browser is None else browser_answer(u,content=browser=='content')
    d=NS(refetches=[{'url':u,'refetch':again}] if again is not None else [],sitemap_check=NS(rows=[row] if light else [],llms_rows=[]),
         empty_browser_check=check)
    obs=[];fs=_empty_pages(r,CrawlConfig(),d,{u} if key else set(),obs)
    return fs,obs


def test_empty_strength_and_importance_not_percentage():
    again={'status':200,'body_bytes':0,'empty_response':True,'requested_at':'2026-10-19T01:01:00Z'}
    fs,_=empty_case(key=True,again=again);assert fs[0].severity==Severity.S1
    fs,_=empty_case(again=again);assert fs[0].severity==Severity.S2
    fs,_=empty_case(light=True);assert fs[0].severity==Severity.S3 and fs[0].confidence==Confidence.ESTIMATED
    assert fs[0].evidence['pages'][0]['attempts'][0]['source']=='sitemap_probe'
    fs,_=empty_case(key=True,again={'status':None,'error':'timeout','empty_response':False})
    assert fs and fs[0].severity==Severity.S3 # timeout is not recovery
    fs,obs=empty_case(again={'status':200,'empty_response':False,'readable_html':True})
    assert not fs and obs
    # First review C1/C2: S1/S2 need a second client. Not asked as a browser: S3. A browser got content: the site sends
    # nothing to automated clients only, one S3 access finding, not "empty pages".
    fs,_=empty_case(key=True,again=again,browser=None)
    assert fs[0].severity==Severity.S3 and fs[0].evidence['observation_strength']=='repeated_empty_same_client_only'
    fs,_=empty_case(key=True,again=again,browser='content')
    assert [f.severity for f in fs]==[Severity.S3] and 'automated clients only' in fs[0].title
    assert fs[0].evidence['browser_check']['answers'][0]['content']
    assert not empty_response(200,'text/html',b'<p>Open nine to five.</p>',False)


def table_check(body):
    r,pages=site({'/':html(body)})
    return str8_semantic_tables(r,CFG,pages,set(),set())


def test_native_data_table_headers_and_layout():
    data='<tr><td>Nutrient</td><td>Amount</td></tr><tr><td>Protein</td><td>12 g</td></tr>'
    c=table_check('<table>'+data+'</table>')
    assert len(c.findings)==1 and c.findings[0].evidence['tables'][0]['element']=='table [table 1]'
    assert c.findings[0].engines==['screen readers']
    for body in ['<table><tr><th>Nutrient</th><th>Amount</th></tr><tr><td>Protein</td><td>12 g</td></tr></table>',
                 '<table><tr><td role="columnheader">Nutrient</td><td role="columnheader">Amount</td></tr><tr><td>Protein</td><td>12 g</td></tr></table>',
                 '<table role="presentation">'+data+'</table>',
                 '<table><tr><td>Logo</td><td>Menu</td></tr><tr><td>Contact</td><td>About</td></tr></table>']:
        assert not table_check(body).findings


def test_concise_pdf_limit_is_enforced_without_truncating():
    pytest.importorskip('playwright')
    from pypdf import PdfReader
    try:
        content=pdf.to_pdf('<html><body><p>Türkçe: ıİşğüöç</p></body></html>',max_pages=50)
    except pdf.PdfUnavailable as exc:
        if isinstance(exc,pdf.PdfPageLimit):raise
        pytest.skip(str(exc))
    assert len(PdfReader(io.BytesIO(content)).pages)==1
    with pytest.raises(pdf.PdfPageLimit,match='maximum 50'):
        pdf.to_pdf('<html><body>'+''.join('<section style="break-after:page">Finding '+str(i)+'</section>' for i in range(51))+'</body></html>',max_pages=50)


def test_read_time_historical_head_limit_survives_client_review():
    from maya_audit.evidence_quality import qualifications
    f={'id':'IDX-6-test','check_id':'IDX-6','title':'1 link(s) to other sites on 1 page(s) return 404 or 410',
       'evidence':{'links':[{'method':'HEAD','status':404}]}}
    assert qualifications(f)
    f['evidence']['links'][0]['attempts']=[{'method':'GET','status':404}]
    assert not qualifications(f)


def test_multirow_and_explicit_header_associations():
    assert not table_check('<table><tr><th colspan="2">Nutrition</th></tr><tr><th>Nutrient</th><th>Amount</th></tr><tr><td>Protein</td><td>12 g</td></tr></table>').findings
    assert not table_check('<table><tr><th id="n">Nutrient</th><th id="a">Amount</th></tr><tr><td headers="n">Protein</td><td headers="a">12 g</td></tr></table>').findings
    # A header unrelated to data does not authorize a missing header on another table.
    assert len(table_check('<table><tr><th>Other</th></tr></table><table><tr><td>Item</td><td>Price</td></tr><tr><td>Ticket</td><td>25 EUR</td></tr></table>').findings)==1


def test_sources_and_timestamps_are_not_conflated():
    r={'schema_version':'1.16','page_counts':{'pages_checked':1,'redirects':0},'crawl':{
        'started_at':'2026-10-18T00:00:00Z','finished_at':'2026-10-18T00:01:00Z','config':{},'pages':[]},
       'generation':{'whole_job_finished_at':'2026-10-18T00:03:00Z'},
       'dataforseo':{'checks':[{'check_id':i,'status':'observed'}for i in ('DFS-4','DFS-7','DFS-9')]}}
    m=summary.method(r)
    assert m['finished_at'].endswith('00:01:00Z') and m['whole_job_finished_at'].endswith('00:03:00Z')
    assert m['optional_sources']['search'] and m['optional_sources']['ai_data'] and m['optional_sources']['lighthouse']
    assert not m['optional_sources']['backlinks']


def test_actual_concise_route_preserves_ids_and_full_companions(demo_app,monkeypatch):
    import json
    from test_report_agreement import audit
    from maya_audit_web import demo
    one=audit(demo_app,demo.SHOP);base='/api/v1/audits/'+one['id']
    path=demo_app.app.state.runner.artifacts(one['id'])/'report.json';before=path.read_bytes()
    r=json.loads(before);ids={f['id']for c in r['checks']for f in c['findings']}
    concise=demo_app.get(base+'/print?full=false');assert concise.status_code==200
    # DECISIONS 300: the concise report has at most 15 cards; every finding ID is in the XLSX appendix it names.
    from maya_audit import client_appendix
    appendix=demo_app.get(base+'/downloads/xlsx');assert appendix.status_code==200
    assert ids<=client_appendix.finding_ids(appendix.content) and '-appendix.xlsx' in concise.text
    assert 'maya-concise' in concise.text and 'Demonstration:' in concise.text
    full=demo_app.get(base+'/print?full=true');assert full.status_code==200 and 'maya-concise' not in full.text
    assert demo_app.get(base+'/downloads/json').json()==r
    assert demo_app.get(base+'/downloads/evidence').status_code==200
    captured=[]
    def bounded(text,**kw):
        captured.append(kw['max_pages']);raise pdf.PdfPageLimit('Concise PDF has 11 pages; maximum 10')
    monkeypatch.setattr(pdf,'to_pdf',bounded)
    response=demo_app.get(base+'/downloads/pdf');assert response.status_code==422 and 'maximum 10' in response.text
    assert captured==[10] and path.read_bytes()==before  # the client PDF's budget (RG-15)


def test_incomplete_headers_cannot_authorize_unrelated_columns_or_tables():
    c=table_check('<table><tr><th scope="col">Item</th><td>Price</td><td>Quantity</td></tr><tr><td>Ticket</td><td>25 EUR</td><td>3</td></tr></table>')
    assert c.findings
    r,pages=site({'/':html('<table><tr><td>Label</td><td>Explanation</td></tr><tr><td>Other</td><td>Content</td></tr></table>')})
    check=str8_semantic_tables(r,CFG,pages,set(),set())
    assert not check.findings and check.status=='partial'
    pages[0].analysis.pop('_table_semantics')
    assert str8_semantic_tables(r,CFG,pages,set(),set()).status=='partial'


def test_duplicate_empty_request_representations_are_not_repetition():
    r,pages=site({'/menu':html('hello')});p=pages[0]
    p.status=200;p.body_bytes=0;p.content_type='text/html';p.requested_at='2026-10-19T01:00:00Z';p.depth=1;p.analysis={'empty_response':True};p.fetch_class=FetchClass.OK
    row={'url':p.url,'status':200,'bytes':0,'empty':True,'fetch_class':'ok','requested_at':p.requested_at}
    d=NS(refetches=[],sitemap_check=NS(rows=[row],llms_rows=[]))
    fs=_empty_pages(r,CrawlConfig(),d,set(),[])
    assert len(fs)==1 and not fs[0].evidence['pages'][0]['repeated_empty'] and fs[0].scope['count']==1


def test_reused_redirect_is_followed_without_losing_original_get(monkeypatch):
    monkeypatch.setattr(external_links,'_from_idx6',lambda result,url:{'url':url,'status':302,'error':None,'method':'GET','location':'https://help.example/b','requested_at':'2026-10-19T01:00:00Z'})
    row,calls=external(monkeypatch,[(200,None)])
    assert calls==[('https://help.example/b','GET')] and row['verdict']=='works'
    assert row['attempts'][0]['status']==302 and len(row['attempts'])==2


def test_external_cycle_remains_a_finding_not_a_silent_skip():
    from maya_audit.checks.index import idx6_broken_links
    from maya_audit.index_data import IndexData
    r,pages=site({'/':html('A link')});r.pages=[];r.discovered_urls=[];r.sitemap_urls=[];r.index=IndexData();r.perf=None;r.structure=NS(other_site_links={'https://help.example/a':{
        'url':'https://help.example/a','verdict':'redirect_loop','pages':[pages[0].url],'links':1,'attempts':[
            {'method':'GET','url':'https://help.example/a','status':302,'location':'https://help.example/a'}]}},
        external_links_enabled=True,other_site_links_not_checked={'redirect_loop':1})
    c=idx6_broken_links(r,CFG)
    assert any('GET redirect cycle' in f.title for f in c.findings)


def test_numeric_contact_layout_is_uncertain_and_table_caps_cannot_pass():
    layout='<table><tr><td><img alt="Company" src="logo.png"></td><td><a href="/contact">Contact</a></td></tr><tr><td>Copyright</td><td>2026</td></tr></table>'
    c=table_check(layout);assert not c.findings and c.status=='partial'
    rows='<tr><th>Item</th><th>Price</th></tr>'+''.join('<tr><td>Ticket</td><td>25 EUR</td></tr>' for _ in range(201))
    c=table_check('<table>'+rows+'</table>');assert c.status=='partial' and c.coverage['not_assessed']
    good='<table><tr><th>Item</th><th>Price</th></tr><tr><td>Ticket</td><td>25 EUR</td></tr></table>'
    c=table_check(good*201);assert c.status=='partial'


def test_large_synthetic_audit_rejects_oversize_concise_without_losing_findings(demo_app):
    import json
    from test_report_agreement import audit
    from maya_audit_web import demo
    one=audit(demo_app,demo.SHOP);base='/api/v1/audits/'+one['id']
    path=demo_app.app.state.runner.artifacts(one['id'])/'report.json';r=json.loads(path.read_text(encoding="utf-8"))
    seed=next(f for ch in r['checks']for f in ch['findings'])
    added=[]
    for i in range(120):
        f=copy.deepcopy(seed);f.update(id=f'IDX-1-larger-{i:04d}',check_id='IDX-1',severity='S2',confidence='estimated',
            title=f'{i+1} URL(s) consistently return a server error (5xx)',
            notes=['Synthetic continuation evidence: '+('A recorded request does not establish universal access. '*18)])
        added.append(f)
    r['checks'][0]['findings']+=added;r['findings_in_priority_order'] += [f['id']for f in added]
    path.write_text(json.dumps(r));before=path.read_bytes()
    text=demo_app.get(base+'/print?full=false').text
    # DECISIONS 300: 120 findings of one cause are one card, not 120; none is lost: all are in the appendix (RG-17).
    from maya_audit import client_appendix
    appendix=demo_app.get(base+'/downloads/xlsx');assert appendix.status_code==200
    assert {f['id'] for f in added}<=client_appendix.finding_ids(appendix.content)
    assert len(re.findall(r'<section class="issue"',text))<=15 and str(len(added)+1) not in re.findall(r'id="card-(\d+)"',text)
    response=demo_app.get(base+'/downloads/pdf')
    if response.status_code==503:pytest.skip('Chromium unavailable for oversized audit PDF check')
    assert response.status_code==200  # the cards fit the client's 10 pages; the rest is in the appendix
    from pypdf import PdfReader
    import io
    assert len(PdfReader(io.BytesIO(response.content)).pages)<=10
    assert path.read_bytes()==before and demo_app.get(base+'/downloads/json').json()==r


def test_client_export_labels_native_finish_separately(demo_app):
    from test_report_agreement import audit
    from maya_audit_web import demo
    one=audit(demo_app,demo.SHOP);base='/api/v1/audits/'+one['id']
    r=demo_app.post(base+'/client-report',json={});assert r.status_code==200
    preview=demo_app.get(base+'/client-report/preview');assert preview.status_code==200
    assert 'Yerel tarama bitişi' in preview.text and 'Tüm işin bitişi (kayıtlıysa)' in preview.text
    assert '<th>Denetim bitişi</th>' not in preview.text


def test_whitespace_header_references_do_not_establish_associations():
    td=lambda text:'<td headers="   ">'+text+'</td>'
    body='<table><tr>'+td('Item')+td('Price')+'</tr><tr>'+td('Ticket')+td('25 EUR')+'</tr><tr>'+td('Other')+'<th id="x">Unrelated</th></tr></table>'
    assert table_check(body).findings


@pytest.mark.parametrize('get_status,verdict',[(200,'works'),(404,'broken'),(429,'refused')])
def test_normal_audit_parallel_pool_corroborates_head(no_lookups,get_status,verdict):
    import httpx
    from test_false_alarms import audited, answer
    from maya_audit.other_sites import CHECK
    replies=[]
    def target(n):
        replies.append(n)
        return answer(title='Destination',status=404 if n==1 else get_status)
    outcome=audited({'/':answer('<a href="https://help.example/guide">Help</a>'),('help.example','/guide'):target})
    entry=outcome.result.structure.other_site_links['https://help.example/guide']
    assert entry['verdict']==verdict and len(entry['attempts'])==2
    assert [a['method']for a in entry['attempts']]==['HEAD','GET']
    broken=[f for f in outcome.by_id['IDX-6'].findings if 'other sites' in f.title]
    assert bool(broken)==(get_status==404)
    assert outcome.int4.state=='compliant'


def test_normal_pool_redirects_and_no_room_preserve_uncertainty(no_lookups):
    import httpx
    from test_false_alarms import audited, answer
    links='<a href="https://help.example/move">Help</a><a href="https://help.example/loop">Other</a>'
    routes={'/':answer(links),('help.example','/move'):httpx.Response(302,headers={'location':'/final'}),
            ('help.example','/final'):answer(title='Help content'),
            ('help.example','/loop'):httpx.Response(302,headers={'location':'/loop'})}
    o=audited(routes)
    rows=o.result.structure.other_site_links
    assert rows['https://help.example/move']['verdict']=='works'
    assert rows['https://help.example/loop']['verdict']=='redirect_loop'
    assert any('GET redirect cycle' in f.title for f in o.by_id['IDX-6'].findings)
    o=audited({'/':answer('<a href="https://help.example/gone">Help</a>'),('help.example','/gone'):answer(status=404)},external_link_checks_max=2,external_link_checks_base=2)
    entry=o.result.structure.other_site_links['https://help.example/gone']
    assert entry['verdict']=='uncorroborated' and not entry['checked']
    assert not any('other sites' in f.title for f in o.by_id['IDX-6'].findings)


def test_mixed_empty_importance_cannot_transfer_blocker_to_unknown_urls(demo_app):
    import json
    from test_report_agreement import audit
    from maya_audit_web import demo, client_reports
    urls = ['https://cafe.example/', 'https://cafe.example/unknown']
    pages = [NS(url=u, depth=i, status=200, body_bytes=0, content_type='text/html',
        requested_at='2026-10-19T01:00:00Z', analysis={'empty_response': True}, fetch_class=FetchClass.OK)
        for i,u in enumerate(urls)]
    result = NS(pages=pages, start_url=urls[0], origin='https://cafe.example')
    data = NS(refetches=[{'url':u, 'refetch':{'status':200, 'body_bytes':0, 'empty_response':True,
        'requested_at':'2026-10-19T01:01:00Z'}} for u in urls], sitemap_check=NS(rows=[],llms_rows=[]),
        empty_browser_check=browser_answer(urls[0]))
    findings = _empty_pages(result, CrawlConfig(), data, {urls[0]}, [])
    assert len(findings) == 2
    assert {f.severity: f.scope['_all_urls'] for f in findings} == {Severity.S1:[urls[0]], Severity.S2:[urls[1]]}
    assert sum(f.scope['count'] for f in findings) == 2
    assert all(len(f.evidence['pages'][0]['attempts']) == 2 for f in findings)
    # Propagation through the real saved-result, print and client-draft adapters.
    one = audit(demo_app, demo.SHOP); base = '/api/v1/audits/'+one['id']
    path = demo_app.app.state.runner.artifacts(one['id'])/'report.json'
    report = json.loads(path.read_text(encoding="utf-8"))
    check = next(c for c in report['checks'] if c['check_id']=='IDX-1')
    old = {f['id'] for f in check['findings']}
    check['findings'] = to_jsonable(findings)
    from maya_audit.report import problem_summary
    all_findings = [f for c in report['checks'] for f in c['findings']]
    report['problem_summary'] = problem_summary(all_findings, {f['id']:f['scope'].get('_all_urls') or f['scope'].get('urls') or [] for f in all_findings}, pages_checked=report['problem_summary']['pages_checked'], checks=report['checks'])
    report['findings_in_priority_order'] = [f.id for f in findings] + [fid for fid in report['findings_in_priority_order'] if fid not in old]
    path.write_text(json.dumps(report)); before = path.read_bytes()
    view = demo_app.get(base+'/summary'); assert view.status_code == 200
    listed = demo_app.get(base+'/findings?check_id=IDX-1&limit=100'); assert listed.status_code == 200
    shown = {f['id']:f for f in listed.json()['items']}
    assert set(shown) == {f.id for f in findings}
    for f in findings:
        assert shown[f.id]['severity'] == f.severity.value
        assert shown[f.id]['sample_pages'] == f.scope['_all_urls']
    printed = demo_app.get(base+'/print?full=false'); assert printed.status_code == 200
    assert all(f.id in printed.text for f in findings)
    workspace = demo_app.post(base+'/client-report',json={}); assert workspace.status_code == 200
    cards = {c['id']:c for c in client_reports.all_cards(workspace.json()['data'])}
    for f in findings:
        assert cards[f.id]['maya']['severity'] == f.severity.value
        assert cards[f.id]['where']['affected_urls'] == f.scope['_all_urls']
    assert path.read_bytes() == before
