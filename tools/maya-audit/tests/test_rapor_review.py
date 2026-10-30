"""Review r3 criticisms against shared current behavior, not brand-specific policies."""
from copy import deepcopy
import pytest
from maya_audit.judgments import qualify, qualify_report
from maya_audit_web import practical, summary
from test_judgment_consistency import finding


def test_sitemap_scope_uses_complete_states_not_truncated_legacy_sample():
    states=[{'url':'https://workshop.example/'+str(i),'state':'uncorroborated_empty'} for i in range(3)]
    states += [{'url':'https://workshop.example/healthy','state':'live_observed'}]
    f=finding('IDX-5',title='3 of 4 sitemap URLs are not live, indexable pages',
              scope={'kind':'template','count':1,'urls':[states[0]['url']]},
              evidence={'listed_urls_assessed':4})
    q=qualify(f,sitemap=states)
    assert q['scope']['count']==3 and len(q['scope']['urls'])==3
    assert q['evidence']['judgment']['source']['scope']==f['scope']
    assert qualify(q)==q
    assert qualify(f)['scope']==f['scope']  # absent states cannot invent URLs


def test_native_header_provenance_is_not_reader_content_provenance():
    f=finding('STR-6',title='Last-Modified header looks auto-stamped: 1 of 1 pages carry the audit day',
        notes=['Source: Firecrawl.'],scope={'kind':'sitewide','count':1,'urls':['https://workshop.example/']},
        evidence={'signal':'Last-Modified header','source':{'reader':'firecrawl'}})
    p={'url':'https://workshop.example/','headers':{'last-modified':'Mon, 19 Oct 2026 10:00:00 GMT'},
       'user_agent':'Maya-Audit/0.2','requested_at':'2026-10-19T10:00:00Z',
       'analysis':{'content_observation':{'reader':'firecrawl','native_requested_at':'2026-10-19T10:00:00Z'}}}
    r={'crawl':{'pages':[p]},'checks':[{'check_id':'STR-6','findings':[f]}]};before=deepcopy(r)
    q=qualify_report(r);got=q['checks'][0]['findings'][0]
    assert got['evidence']['source']['reader']=='native_crawl'
    assert got['evidence']['header_observations'][0]['observed_at']==p['requested_at']
    assert 'Source: Firecrawl.' not in got['notes'] and r==before
    assert 'incorrect edit dates' in got['evidence']['judgment']['interpretation']
    # Provider-only response does not become native simply because the check concerns a header.
    p['user_agent']='Firecrawl';p['analysis']={}
    assert qualify_report(r)['checks'][0]['findings'][0]['evidence']['source']['reader']=='firecrawl'


def test_no_invented_page_examples_or_universal_discovery_claim():
    for title in ('Long page with no subheadings','1 link has no text at all','Pages have no og:image','Page has fewer than 150 words'):
        text=practical.example_for(title)
        assert not any(s in text for s in ('/pricing','brand.example','Prices','price,'))
    from maya_audit.recommendation_catalog import note
    text=note('IDX-5','1 sitemap file named in the sitemap index could not be loaded')['why']
    assert 'hides every' not in text and 'other' in text.lower()


def test_lab_opportunity_keeps_values_and_missing_data_unavailable():
    data={'metrics':{'Performance score (0–100)':38,'Largest Contentful Paint':'7.4 s','Total Blocking Time':'1770 ms'},
          'past_good_threshold':['Largest Contentful Paint','Total Blocking Time']}
    out=practical.opportunities({'checks':[{'check_id':'DFS-9','status':'assessed','data':data}]},None,[])
    text=' '.join(out)
    assert '7.4 s' in text and '1770 ms' in text and 'Core Web Vitals' in text
    assert not practical.opportunities(None,None,[])


def test_absent_hreflang_is_not_asserted_reciprocal_and_broken_target_remains():
    from test_false_alarms import site,html,CFG
    from maya_audit.checks.structure import str9_language
    from maya_audit.structure_data import StructureData
    r,pages=site({'/':html('<h1>Cycle repair</h1>')})
    c=str9_language(r,CFG,pages,set(),StructureData())
    assert 'does not establish' in c.summary and 'are reciprocal' not in c.summary
    target='https://workshop.example/en/'
    pages[0].analysis['hreflang']=[{'hreflang':'en','href':target}]
    data=StructureData();data.links[target]={'source':'fetched','status':404}
    c=str9_language(r,CFG,pages,set(),data)
    assert any('do not return 200' in f.title for f in c.findings)


def test_ordinary_generation_and_client_keep_native_header_source():
    from maya_audit.findings import Finding,Severity
    from maya_audit.models import Confidence,to_jsonable
    from maya_audit.judgments import qualify_checks
    from maya_audit.findings import CheckResult
    from types import SimpleNamespace
    f=finding('STR-6',evidence={'signal':'Last-Modified header'},
        scope={'kind':'page','count':1,'urls':['https://cafe.example/policy']})
    item=Finding(**{k:v for k,v in f.items() if k not in ('severity','confidence')},severity=Severity.S4,confidence=Confidence.ESTIMATED)
    page=SimpleNamespace(url='https://cafe.example/policy',user_agent='Maya-Audit/0.2',
        headers={'last-modified':'Mon, 19 Oct 2026 10:00:00 GMT'},analysis={},requested_at='2026-10-19T10:00:00Z')
    result=SimpleNamespace(pages=[page],sitemap_urls=[],index={})
    checked=qualify_checks([CheckResult('STR-6','Dates','findings','Observation',[item])],result)
    out=to_jsonable(checked[0].findings[0])
    assert out['evidence']['source']['reader']=='native_crawl'
    row=summary.item(out)
    assert row['source']['reader']=='native_crawl' and 'HTTP' in row['source']['label']


def test_headline_does_not_confine_probe_findings_to_content_page_count():
    from maya_audit.report import headline
    counts={'pages_checked':2,'problems':1,'notes':0,'by_severity':{'S3':1}}
    assert 'across assessed scope; 2 pages read for content' in headline(counts)
    assert summary.headline(2,1,{'S3':1},0)==headline(counts)
    assert 'separate URL probes' in practical.t('result.partial_note')


def test_search_overlap_does_not_claim_business_competition_or_expectations():
    overlaps={'checks':[{'check_id':'DFS-6','status':'observed','data':{
        'table':{'rows':[['search-platform.example',10],['garden.example',5]]}}}]}
    text=' '.join(practical.opportunities(overlaps,None,[]))
    assert 'does not establish business competition or user expectations' in text
    assert 'garden.example' in text and 'search-platform.example' in text


@pytest.mark.parametrize('cid,title,unsupported',[
    ('RND-7','3 page(s) have no <main> or <article>','have to guess'),
    ('RND-7','3 page(s) have less than 30% of their text in the main content','harder for an engine'),
    ('STR-10','3 page(s) have no og:image','engine chooses for you'),
])
def test_structural_metadata_does_not_prove_extraction_or_display_failure(cid,title,unsupported):
    from maya_audit.recommendation_catalog import note
    text=note(cid,title)['why']
    assert unsupported not in text and 'not assessed' in text


def test_real_declared_image_failure_is_retained_without_guaranteeing_blank_preview():
    f=finding('STR-10',title='1 page(s) have an og:image that returns 404 or 410',
              evidence={'pages':[{'url':'https://garden.example/guide','og:image':'https://garden.example/missing.jpg','status':404}]})
    row=summary.item(f)
    assert row['severity']=='S4' and '404' in row['title']
    assert 'leaves the preview blank' not in row['why'] and 'failed' in row['why']
