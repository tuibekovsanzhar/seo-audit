"""October report rule regressions; anonymized evidence structures and contrasting real defects."""
from datetime import date
from types import SimpleNamespace
import json
import pytest
from maya_audit.analysis import analyze_html
from maya_audit.checks.structure import judge_dates, parse_date, str11_markup_contradictions
from maya_audit.config import CrawlConfig
from maya_audit.checks.small_site import str19_links_to_nowhere
from maya_audit.checks.content_quality import str14_anchor_text
from maya_audit.html_links import extract_link_edges
from maya_audit.report import finding_counts
from test_false_alarms import images_check, site, html, ld, CFG
from test_keyword_actions import keywords, page
from test_report_agreement import demo_app


def row(**kw):
    return dict(url='https://other.example/',schema={'datePublished':{'date':date(2023,1,1)},'dateModified':{'date':date(2026,10,1)}},
                visible=[],sitemap=date(2025,1,1),header=date(2026,10,18),header_is_request_time=False,
                requested_day=date(2026,10,18),use_visible=True,**kw)


def test_resource_dates_are_not_editorial_conflicts_and_old_publication_is_healthy():
    assert not judge_dates([row()],date(2026,10,18),CFG)['conflicts']
    r=row();r['schema']['dateModified']['date']=date(2022,1,1)
    assert judge_dates([r],date(2026,10,18),CFG)['conflicts']


def test_iso_offsets_compare_the_same_instant_and_unknown_stays_unavailable():
    assert parse_date('2026-06-01T01:00:00+03:00')==parse_date('2026-05-31T22:00:00Z')
    assert parse_date('not a date') is None
    r=row();r.update(schema={},sitemap=None,header=None)
    assert judge_dates([r],date(2026,10,18),CFG)['compared_pages']==0


def test_same_entity_modified_conflict_survives_but_matching_zones_do_not_conflict():
    def run(a,b):
        result,pages=site({'/':html(ld({'@type':'WebPage','@id':'https://other.example/#page','dateModified':a},
                                     {'@type':'MedicalWebPage','@id':'https://other.example/#page','dateModified':b}))})
        return str11_markup_contradictions(result,CFG,pages,set(),SimpleNamespace(findings=[]))
    assert any('dateModified' in f.title for f in run('2026-01-01','2026-08-01').findings)
    assert not any('dateModified' in f.title for f in run('2026-06-01T01:00:00+03:00','2026-05-31T22:00:00Z').findings)


@pytest.mark.parametrize('name',['Tanı Yöntemleri','Diagnosis approaches','الوحدات الطبية'])
def test_structural_dropdown_children_are_not_dead_destinations(name):
    a=analyze_html(f'<nav><ul><li class="has-children"><a href="#">{name}</a><ul><li><a href="/actual">Actual page</a></li></ul></li></ul></nav><a href="#">Learn the details</a>','https://other.example/')
    assert a['dead_link_total']==1 and a['dead_links'][0]['text']=='Learn the details'
    assert a['link_controls'][0]['child_urls']==['https://other.example/actual']
    assert a['link_controls'][0]['interaction']=='not_assessed'


def test_accessible_anchor_control_is_not_a_broken_link_and_no_interaction_is_invented():
    a=analyze_html('<a href="#" role="button" aria-controls="panel" aria-expanded="false">Open</a><div id="panel">Content</div><a href="#">Essential instructions</a>','https://other.example/')
    assert a['link_control_total']==1 and a['dead_link_total']==1
    assert a['dead_links'][0]['text']=='Essential instructions'


def nutrition(src='category.jpg',linked=False):
    image=f'<img src="/{src}" alt="" width="155" height="90">'
    if linked:image='<a href="/essential">'+image+'</a>'
    return '<figure><table><tr><td>Vegetable dishes</td></tr><tr><td>'+image+'</td><td>Energy kcal</td><td>Protein</td></tr><tr><td>Beans</td><td>123</td><td>25</td></tr><tr><td>Peas</td><td>246</td><td>30</td></tr></table></figure>'


def test_category_illustration_has_table_equivalent_but_chart_and_image_link_remain():
    assert not any(f.severity.value!='Info' for f in images_check(nutrition()).findings)
    for body in (nutrition('chart.png').replace('</figure>', '<figcaption>Chart of nutrient distribution</figcaption></figure>'),nutrition(linked=True),'<figure><img src="/photo.jpg" alt=""><figcaption>Diagram of the booking process</figcaption></figure>'):
        assert any(f.severity.value=='S4' for f in images_check(body).findings)


@pytest.mark.parametrize('q',['festival geleneklerimiz','festival gelenekleri','festival geleneği'])
def test_turkish_morphology_matches_same_saved_editorial_topic(q):
    url='https://kart.example/blog/festival-gelenekleri'
    p=page(url,'Festival gelenekleri nedir?');p.analysis.update(json_ld_blocks=[json.dumps({'@type':'Article'})])
    _,d=keywords([(q,url)],pages=[p])
    assert d['keyword_assessments'][0]['category']=='relevant'
    assert d['provider_table']['rows'][0][0]==q


@pytest.mark.parametrize('q',['nörometri nedir','nörometri ne demek'])
def test_definition_variants_have_consistent_explanatory_dimensions(q):
    url='https://kart.example/norometri';_,d=keywords([(q,url)],pages=[page(url,'Nörometri nedir?')])
    a=d['keyword_assessments'][0]
    assert a['category']=='relevant' and a['dimensions']['editorial_relevance']=='supported'


def test_missing_ranking_evidence_is_uncertain_not_confirmed_opportunity_or_unrelated():
    _,d=keywords([('nörometri ne demek','https://kart.example/norometri')])
    a=d['keyword_assessments'][0];assert a['uncertain'] and a['evidence_gaps'][0]['url'].endswith('/norometri')
    assert not d['opportunity_evidence'][a['keyword']]
    _,d=keywords([('bilinmeyen sağlık konusu','https://kart.example/unknown')])
    assert d['keyword_assessments'][0]['category']=='ambiguous'


def test_link_titles_and_by_page_counts_use_dom_occurrences():
    result,pages=site({'/':html('<a href="/x"></a>'*6+'<a href="#">Read details</a>'*7),'/cards':html('<a href="/y">detaylı bilgi</a>'*2)})
    f=str14_anchor_text(result,CFG,pages,set()).findings
    assert any(x.title.startswith('6 link') and finding_counts({'check_id':x.check_id,'title':x.title,'scope':x.scope,'evidence':x.evidence})['occurrences']==6 for x in f)
    assert any(x.title.startswith('2 link') and x.evidence['count']==1 for x in f)
    fs=str19_links_to_nowhere(result,CFG,pages,set()).findings
    issue=next(x for x in fs if x.severity.value!='Info')
    assert issue.title.startswith('7 link') and issue.evidence['by_page'][0]['links']==7


def test_details_label_and_numeric_table_context_not_generic_previous_text():
    body=nutrition().replace('<figure>','<details open><summary>Vegetable dishes</summary><figure>').replace('</figure>','</figure></details>').replace('<tr><td>Vegetable dishes</td></tr>','<tr><td>Portion</td><td>100 gr</td></tr>')
    check=images_check(body)
    assert not any(f.severity.value!='Info' for f in check.findings)
    review=check.evidence['equivalent_description_reviews'][0]
    assert review['context']['equivalent_text']=='Vegetable dishes' and review['element_id']


def test_equal_titles_and_pages_do_not_collide_for_distinct_post_targets():
    from maya_audit.findings import Finding,Severity
    from maya_audit.models import Confidence
    def finding(target):
        return Finding('STR-14','Related post has no name',Severity.S4,Confidence.VERIFIED,'Observation',[],
                       {'count':2,'urls':['https://other.example/a','https://other.example/b']},
                       {'shared_element':{'type':'link','href':target,'block':'div.posts'}},'Name destination','Use its topic')
    assert finding('/one').id!=finding('/two').id
    assert finding('/one').id==finding('/one').id


def test_query_syntax_is_not_automatically_corruption_and_real_corruption_stays_visible():
    from maya_audit.checks.index import _malformed_sitemap_urls
    result=SimpleNamespace(sitemap_urls=['https://other.example/search?interesting-topic','https://other.example/search?q=health'],origin='https://other.example')
    assert all(f.severity.value=='Info' and f.confidence.value=='inferred' for f in _malformed_sitemap_urls(result))
    result.sitemap_urls += ['https://other.example/lost\ufffdword']
    assert any(f.severity.value=='S3' for f in _malformed_sitemap_urls(result))
    from maya_audit.index_data import malformed
    assert malformed('https://other.example/search?q=health') is None
    assert malformed('https://other.example/article?lost-word')=='question_mark'
    assert malformed('https://other.example/lost\ufffdword')=='invalid_encoding'
    assert malformed('https://other.example/bad%ZZ')=='invalid_encoding'


def test_layout_headers_direction_and_url_sets_keep_occurrences_distinct():
    from maya_audit.report_layout import prepare_tables,unique_urls,evidence_parts
    text=prepare_tables('<h2>Table</h2><table><tr><th>URL</th></tr><tr><td>الوحدات الطبية</td></tr></table>')
    assert '<thead><tr><th>URL</th></tr></thead><tbody>' in text and 'dir="auto"' in text
    value={'urls':['https://other.example/a']*2,'observations':[{'url':'a'},{'url':'a'}]}
    assert len(unique_urls(value)['urls'])==1 and len(unique_urls(value)['observations'])==2
    assert len(evidence_parts({'rows':['x'*100]*80},limit=500))>10


def test_normal_summary_print_download_and_client_preserve_counts_and_uncertainty(demo_app,monkeypatch):
    from test_report_agreement import audit
    from maya_audit_web import demo,client_reports as C,pdf
    from maya_audit.report import problem_summary
    from maya_audit.models import to_jsonable
    one=audit(demo_app,demo.SHOP);base='/api/v1/audits/'+one['id']
    path=demo_app.app.state.runner.artifacts(one['id'])/'report.json';rep=json.loads(path.read_text(encoding="utf-8"))
    result,pages=site({'/':html('<a href="/x"></a>'*6+'<a href="#">Essential details</a>'*7)})
    checks=[str14_anchor_text(result,CFG,pages,set()),str19_links_to_nowhere(result,CFG,pages,set())]
    replaced={c.check_id:to_jsonable(c) for c in checks}
    rep['checks']=[replaced.get(c['check_id'],c) for c in rep['checks']]
    findings=[f for c in rep['checks'] for f in c.get('findings',[])];rep['problem_summary']=problem_summary(findings,pages_checked=1,checks=checks)
    rep['findings_in_priority_order']=[f['id'] for f in findings]
    path.write_text(json.dumps(rep));original=path.read_bytes()
    view=demo_app.get(base+'/summary').json();printed=demo_app.get(base+'/print?full=true')
    assert printed.status_code==200 and '6 links' in printed.text and '7 links' in printed.text
    assert '<thead>' in printed.text and 'Provenance' in printed.text
    seen=[];monkeypatch.setattr(pdf,'to_pdf',lambda text,**kw:seen.append(text) or b'%PDF-test')
    assert demo_app.get(base+'/downloads/pdf').status_code==200 and '6 links' in seen[0]
    work=demo_app.post(base+'/client-report',json={}).json()
    cards=C.all_cards(work['data']);link=next(c for c in cards if c['maya']['check_id']=='STR-14')
    assert link['counting']['occurrences']==6 and link['counting']['source_target_groups']==1
    assert 'Sayım birimleri' in demo_app.get(base+'/client-report/preview').text
    link['counting']['affected_pages']=99
    from maya_audit.client_reporting.validate_cards import validate
    assert any('count' in e for e in validate(work['data'])[0])
    assert demo_app.get(base+'/client-report/export/html?mode=final').status_code==422
    assert path.read_bytes()==original


def test_client_estimates_cannot_be_editorially_promoted_to_certainty():
    from maya_audit_web import client_reports as C
    from test_client_reporting import report,finding
    f=finding();f.update(confidence='estimated',title='1 likely meaningful image',check_id='STR-7')
    r=report('findings',f);r['checks'][0]['check_id']='STR-7'
    work=C.generate(r,'synthetic')
    C.all_cards(work['data'])[0]['title']='Görselin açıklaması yoktur.'
    C.review(work,'Owner','Reviewed')
    assert any('uncertainty' in e for e in C.validation(work)['errors'])


def test_client_occurrence_title_cannot_use_a_group_total():
    from test_client_reporting import valid_cards
    from maya_audit.client_reporting.validate_cards import validate
    d=valid_cards();c=d['cards'][0];c['title']='1 bağlantı adsız';c['counting']={'affected_pages':1,'occurrences':6,'title_unit':'DOM occurrences'}
    assert any('occurrence count' in e for e in validate(d)[0])
    c['title']='6 bağlantı adsız'
    assert not any('occurrence count' in e for e in validate(d)[0])


def test_saved_local_and_article_context_generalize_beyond_motivating_brands():
    branch='https://kart.example/subeler/erensehir';p=page(branch,'Erenşehir lokantası')
    p.analysis['json_ld_blocks']=[json.dumps({'@type':'Restaurant','address':{'@type':'PostalAddress','addressLocality':'Erenşehir'}})]
    _,d=keywords([('erenşehir lokantalar',branch)],brand='Gümüş Sofra',pages=[p])
    a=d['keyword_assessments'][0]
    assert a['category']=='relevant' and a['dimensions']['local_relevance']=='supported'
    assert a['dimensions']['brand_identity']=='not_established' and a['sources']
    _,missing=keywords([('başkaşehir lokantalar',branch)],brand='Gümüş Sofra',pages=[p])
    assert missing['keyword_assessments'][0]['category']=='ambiguous'


def test_explanatory_query_does_not_prove_landing_page_is_an_explanatory_article():
    url='https://kart.example/services/norometri';_,d=keywords([('nörometri ne demek',url)],pages=[page(url,'Nörometri hizmetleri')])
    a=d['keyword_assessments'][0]
    assert a['query_intent']=='explanatory' and a['dimensions']['editorial_relevance']!='supported'
    assert a['dimensions']['service_relevance']=='supported'


def test_provisional_topic_match_is_visible_as_uncertain_and_not_counted_as_opportunity():
    _,d=keywords([('hgs yükleme','https://kart.example/hgs-yukleme')])
    assert d['keyword_assessments'][0]['category']=='relevant' and d['keyword_assessments'][0]['uncertain']
    assert d['relevance']['confirmed_relevant']==0 and d['relevance']['provisional_relevant']==1
    assert d['table']['rows']==[] and d['ambiguous']['rows'][0][0]=='hgs yükleme'


def test_long_page_table_repeats_identity_without_inventing_pages_or_counts():
    from maya_audit_web.pdf import _by_page
    rows=[{'whole_site':False,'url':'https://other.example/one','problems':9,'worst_severity':'S3','worst_severity_label':'Medium','lines':['Observation '+str(n) for n in range(9)]}]
    table={'title':'Problems','rows':rows,'columns':['URL','Count','Severity','Observation'],'not_listed':[],'note':'Occurrences are separate'}
    text=_by_page(table,'https://other.example')
    assert text.count('/one')==3 and text.count('<td>9</td>')==1
    assert '(2/3)' in text and '(3/3)' in text and 'Observation 8' in text
    assert rows[0]['url']=='https://other.example/one' and rows[0]['problems']==9


def test_provider_content_time_does_not_become_the_native_response_time():
    from maya_audit.firecrawl.reader import _merged
    from maya_audit.models import PageFetch,FetchClass,Confidence
    from dataclasses import replace
    native=PageFetch(url='https://other.example/',discovered_via='start',depth=0,requested_at='2026-10-18T10:00:00Z',user_agent='Maya',status=200,error=None,elapsed_ms=1,content_type='text/html',body_bytes=1000,body_truncated=False,headers={},fetch_class=FetchClass.OK,classification_confidence=Confidence.VERIFIED,classification_evidence=[],analysis=analyze_html('<main>Native</main>','https://other.example/'))
    reader=replace(native,requested_at='2026-10-18T12:00:00Z',view='provider',user_agent='Saved reader',analysis=analyze_html('<main><figure><img src="/chart.png" alt=""><figcaption>Chart of monthly demand</figcaption></figure></main>',native.url))
    merged=_merged(native,reader,[])
    assert merged.requested_at==native.requested_at and merged.analysis['content_observation']['observed_at']==reader.requested_at
    result=SimpleNamespace(origin='https://other.example',pages=[merged])
    from maya_audit.checks.structure import str7_alt
    retained=next(f for f in str7_alt(result,CFG,[merged],set(),set()).findings if f.severity.value=='S4')
    assert retained.evidence['images'][0]['observed_at']==reader.requested_at


def test_same_entity_date_evidence_retains_original_fields_and_offsets():
    a='2026-01-01T10:00:00+03:00';b='2026-08-01T08:00:00Z'
    result,pages=site({'/':html(ld({'@type':'WebPage','@id':'https://other.example/#page','dateModified':a},{'@type':'MedicalWebPage','@id':'https://other.example/#page','dateModified':b}))})
    check=str11_markup_contradictions(result,CFG,pages,set(),SimpleNamespace(findings=[]))
    conflict=next(f for f in check.findings if 'dateModified' in f.title)
    row=conflict.evidence['contradictions'][0]
    assert row['field']=='dateModified' and {d['raw_value'] for d in row['descriptions']}=={a,b}


def test_optional_pagespeed_panel_is_not_confused_with_existing_provider_lighthouse():
    from maya_audit_web import client_reports as C
    from test_client_reporting import report
    from test_keyword_actions import lab
    r=report();r['checks'].append({'check_id':'PRF-3','title':'Core Web Vitals and Lighthouse metrics (optional)','status':'not_assessed','summary':'Optional panel not run (--pagespeed).','findings':[]})
    work=C.generate(r,'synthetic',performance={'backlinks':lab()})
    assert any('PageSpeed Insights / CrUX' in entry['what'] for entry in work['data']['not_measured'])
    assert work['performance'][0]['check_id']=='DFS-9'
    assert 'DataForSEO Lighthouse' in work['performance'][0]['fix']
    assert 'gerçek kullanıcı Core Web Vitals verisi değildir' in work['performance'][0]['why']


def test_pdf_card_and_table_continuations_preserve_identity_and_turkish_text():
    import io
    from maya_audit_web.pdf import to_pdf,PdfUnavailable
    from maya_audit.report_layout import PRINT_CSS,prepare_tables
    from pypdf import PdfReader
    body='<div style="height:620px">Örnek Çığ İşletmesi</div><section class="card" style="height:350px"><h3>CARD_START</h3><div class="coverage" style="height:250px">Source qualification</div><p>CARD_BODY</p></section>'
    table='<h2>LONG_TABLE</h2><table><tr><th>ROW_IDENTITY</th><th>Observation</th></tr>'+''.join(f'<tr><td>ROW_{i}</td><td style="height:36px">Saved observation</td></tr>' for i in range(80))+'</table>'
    html='<!doctype html><html><head><meta charset="utf-8"><style>@page{size:A4;margin:16mm}body{margin:0}'+PRINT_CSS+'</style></head><body>'+prepare_tables(body+table)+'</body></html>'
    try:data=to_pdf(html)
    except PdfUnavailable as e:pytest.skip('Optional local Chromium unavailable: '+str(e))
    texts=[p.extract_text()or'' for p in PdfReader(io.BytesIO(data)).pages]
    assert any('CARD_START' in t and 'CARD_BODY' in t for t in texts)
    assert 'Örnek Çığ İşletmesi' in ''.join(texts) and '\ufffd' not in ''.join(texts)
    assert any('LONG_TABLE' in t and 'ROW_0' in t for t in texts)
    assert sum('ROW_IDENTITY' in t for t in texts)>=2
    assert all(f'ROW_{i}' in ''.join(texts) for i in range(80))


def test_legacy_card_without_declared_title_units_cannot_hide_occurrence_mismatch():
    from test_client_reporting import valid_cards
    from maya_audit.client_reporting.validate_cards import validate
    d=valid_cards();c=d['cards'][0];c['title']='1 bağlantı adsız';c['counting']={'affected_pages':1,'occurrences':6,'template_groups':0,'source_target_groups':1}
    assert any('occurrence count' in e for e in validate(d)[0])
    c['title']='1 bağlantı grubu adsız'
    assert not any('occurrence count' in e for e in validate(d)[0])


@pytest.mark.parametrize('title',['1 bağlantının adı eksik','1 bağlantıda metin yok','1 link has no name'])
def test_inflected_link_count_claims_are_also_bound_to_recorded_occurrences(title):
    from test_client_reporting import valid_cards
    from maya_audit.client_reporting.validate_cards import validate
    d=valid_cards();c=d['cards'][0];c['title']=title;c['counting']={'affected_pages':1,'occurrences':6,'template_groups':0,'source_target_groups':1}
    assert any('occurrence count' in e for e in validate(d)[0])


def test_date_only_and_offset_timestamp_keep_unknown_timezone_out_of_conflict_counts():
    from maya_audit.coverage import settle
    def run(a,b):
        result,pages=site({'/':html(ld({'@type':'WebPage','@id':'https://other.example/#page','dateModified':a},
                                     {'@type':'MedicalWebPage','@id':'https://other.example/#page','dateModified':b}))})
        check=str11_markup_contradictions(result,CFG,pages,set(),SimpleNamespace(findings=[]))
        settle(check,indexable=len(pages))
        return check
    unknown=run('2026-06-01','2026-06-01T01:00:00+03:00')
    assert not unknown.findings and unknown.status=='partial'
    assert unknown.coverage['not_assessed'] and unknown.evidence['date_precision_not_assessed_count']==1
    assert unknown.evidence['date_precision_not_assessed'][0]['raw_values']==['2026-06-01','2026-06-01T01:00:00+03:00']
    assert run('2026-06-01','2026-06-03').findings
    assert not run('2026-06-01T01:00:00+03:00','2026-05-31T22:00:00Z').findings


def test_client_draft_warning_does_not_cover_a_continuation_heading():
    import io
    from test_client_reporting import valid_cards
    from maya_audit.client_reporting.render_report import build
    from maya_audit_web.pdf import to_pdf,PdfUnavailable
    from pypdf import PdfReader
    d=valid_cards();html=build(d,draft=True).replace('</body>','<section style="break-before:page"><h2 style="margin:0">CONTINUATION_HEADING</h2><p>Content remains readable.</p></section></body>')
    try:data=to_pdf(html)
    except PdfUnavailable as e:pytest.skip('Optional local Chromium unavailable: '+str(e))
    pages=PdfReader(io.BytesIO(data)).pages;positions=[]
    def visit(text,cm,tm,font,size):
        if 'CONTINUATION_HEADING' in text or 'TASLAK' in text:
            y=tm[4]*cm[1]+tm[5]*cm[3]+cm[5]
            positions.append((text,y))
    pages[-1].extract_text(visitor_text=visit)
    heading=next(y for text,y in positions if 'CONTINUATION_HEADING' in text)
    warning=next(y for text,y in positions if 'TASLAK' in text)
    assert warning-heading>=18,positions
    assert all('TASLAK' in (p.extract_text()or'') for p in pages)
    assert 'MÜŞTERİYE GÖNDERİLMEMELİ' not in build(d,draft=False)
