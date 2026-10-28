"""Offline client-report contract regressions; synthetic data only, no customer caches."""
import copy
import importlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / '.agents/skills/maya-audit-rapor/scripts'
sys.path.insert(0, str(SCRIPTS))
F = importlib.import_module('from_maya_report')
V = importlib.import_module('validate_cards')
R = importlib.import_module('render_report')
H = importlib.import_module('reliability')
URL = 'https://synthetic.example/'
WHEN = '2026-10-15T10:00:00+00:00'
CFG = F.load_json(F.REFS / 'onem_kurallari.json')['score']


def report(status='pass', finding=None):
    return {'schema_version': '1.14', 'scope': {'kind': 'site'},
            'crawl': {'origin': URL, 'started_at': WHEN, 'config': {'max_pages': 50}, 'pages': [
                {'url': URL, 'status': 200, 'requested_at': WHEN, 'content_checks_eligible': True,
                 'analysis': {'title': 'Örnek ücret 10 TL', 'text_sketch': [12345678, 98765432],
                              'headings': [{'level': 1, 'text': 'Örnek hizmet'}]}}]},
            'audit_status': {'content_coverage': {'level': 'complete_sample', 'pages_read': 1, 'known_urls_not_read': 0}},
            'checks': [{'check_id': 'STR-1', 'status': status, 'coverage': {'not_assessed': []},
                        'evidence': {}, 'findings': [finding] if finding else []}]}


def finding():
    return {'id': 'stable', 'check_id': 'STR-1', 'title': 'Missing title', 'severity': 'S3',
            'scope': {'kind': 'page', 'count': 1, 'urls': [URL]}, 'evidence': {}}


def scored_card():
    return {'id': 'x', 'maya': {'check_id': 'STR-1', 'severity_report': 'S3'}, 'where': {'count': 1}}


def valid_cards():
    cov = F.coverage(report())
    return {'contract_version': 2, 'meta': {'brand': 'Örnek', 'site': URL, 'audit_date': '2026-10-15', 'source': 'Sentetik denetim'},
            'coverage': cov,
            'score': {'value': 96, 'draft': True, 'status': cov['score_status'], 'scope': cov['score_reason']},
            'kpis': [{'label': 'Önce doğrulanacak bulgu', 'value': '0'},
                     {'label': 'Okunan sayfa', 'value': '1'}, {'label': 'Sorun', 'value': '1'}],
            'summary': {'one_read': 'Bir sayfa değerlendirildi. Başlık açıklık gerektiriyor.', 'bullets': []},
            'cards': [{'id': 'x', 'title': 'Başlık açıklık gerektiriyor', 'severity': 'Orta', 'maya': {'check_id':'STR-1','severity_report':'S3'}, '_scored': True,
                       'where': {'count': 1, 'examples': [URL], 'affected_urls': [URL]}, 'why': {'text': 'İçerik anlaşılır olmalıdır.'},
                       'steps': ['Başlığı düzenlemelisiniz.'], 'verify': 'Başlığı kontrol etmelisiniz.',
                       'what_to_write': {'decide': 'Karar vermelisiniz: Başlık nasıl olmalı?'},
                       'owner': 'SEO', 'effort': 'Küçük', 'evidence': {}}],
            'appendix_cards': [], 'manual_checks': [], 'not_measured': [], 'page_facts': F.page_facts_from_report(report())}


def recommendation(text='Örnek ücret 10 TL', field='title', source='native'):
    return {'text':text, 'derived_from':[{'url':URL,'field':field,'source':source,'read_at':WHEN}],
            'review':{'status':'reviewed','reviewer':'synthetic reviewer','reviewed_at':WHEN,'reason':'Kaynakla karşılaştırıldı.'}}


def errors(d):
    return V.validate(d)[0]


def test_empty_and_missing_assessment_never_score_100():
    for rep in ({}, report('not_assessed')):
        rep=copy.deepcopy(rep)
        rep.setdefault('audit_status',{})['content_coverage']={'pages_read':0,'level':'none'}
        cov=F.coverage(rep)
        assert cov['pages_read']==0
        assert F.score([],cov,CFG)[0] is None
    assert F.score([],{},CFG)[0] is None
    rep=report();rep.pop('checks')
    assert F.score([],F.coverage(rep),CFG)[0] is None


def test_healthy_sample_and_partial_are_explicit():
    rep=report();cov=F.coverage(rep)
    assert F.score([],cov,CFG)[0]==100 and cov['score_status']=='assessed_sample'
    rep['audit_status']['content_coverage'].update(level='partial',known_urls_not_read=99)
    cov=F.coverage(rep)
    assert F.score([],cov,CFG)[0]==100 and cov['score_status']=='partial'
    assert 'Kısmi' in cov['score_reason'] and '1 okunan sayfa' in cov['score_reason']
    assert 'kısmi' in H.score_label(100,cov)


def test_sitemap_size_cannot_dilute_content_score():
    rep=report();a=F.coverage(rep)
    rep['crawl']['sitemap_urls']=[f'{URL}{i}' for i in range(1000)]
    rep['checks'].append({'check_id':'IDX-5','status':'pass','evidence':{'listed_urls_assessed':1000}})
    b=F.coverage(rep)
    assert F.score([scored_card()],a,CFG)[0]==F.score([scored_card()],b,CFG)[0]==96


def test_explicit_zero_coverage_not_replaced_with_known_counts():
    rep=report();rep['audit_status']['content_coverage']['pages_read']=0
    rep['problem_summary']={'pages_checked':999}
    assert F.coverage(rep)['pages_read']==0


def test_diff_unassessed_vs_resolved_and_renamed():
    old=report('findings',finding())
    unknown=F.diff(report('not_assessed'),old)
    assert not unknown['fixed'] and len(unknown['unknown'])==1
    newer=report();newer['crawl']['started_at']='2026-10-15T11:00:00+00:00';newer['crawl']['pages'][0]['requested_at']='2026-10-15T11:00:00+00:00'
    resolved=F.diff(newer,old)
    assert len(resolved['fixed'])==1 and resolved['fixed'][0]['resolution']['urls']==[URL]
    renamed=copy.deepcopy(old);renamed['checks'][0]['findings'][0]['title']='Different wording'
    assert len(F.diff(renamed,old)['still_open'])==1


@pytest.mark.parametrize('change',['unread','partial','scope','truncated','provider','identity','conditions'])
def test_diff_does_not_turn_incomparable_into_fixed(change):
    old=report('findings',finding());new=report()
    if change=='unread': new['crawl']['pages']=[]
    if change=='partial': new['checks'][0]['status']='partial'
    if change=='scope': new['scope']={'kind':'single'}
    if change=='truncated': old['checks'][0]['findings'][0]['scope']['count']=10
    if change=='provider': old['dataforseo']={'status':'assessed'}
    if change=='identity':
        new=copy.deepcopy(old);new['checks'][0]['findings'][0]['id']='changed'
    if change=='conditions': new['crawl']['config']['max_pages']=5
    result=F.diff(new,old)
    assert not result['fixed'] and result['unknown']


def test_hash_sketch_not_readable_native_text_and_provider_metadata_not_document():
    rep=report()
    rep['firecrawl']={'used':True,'pages':[{'url':URL,'outcome':'read','status':200,'observed_at':WHEN,
                                          'rawHtml':'<title>Provider conflict</title>', 'analysis':{'title':'Provider conflict'}}]}
    facts=F.page_facts_from_report(rep)[URL]
    assert facts['title']=='Örnek ücret 10 TL' and facts['text_sample'] is None
    native,provider=facts['observations']
    assert native['source']=='native' and native['read_at']==WHEN
    assert provider['source']=='firecrawl' and provider['title'] is None and provider['url']==URL
    d=valid_cards();d['page_facts']=F.page_facts_from_report(rep)
    d['cards'][0]['maya']['source']={'reader':'firecrawl'}
    d['cards'][0]['what_to_write']=recommendation()
    assert any('exact URL/source/field/read_at' in e for e in errors(d))


def test_readable_title_healthy_and_no_semantic_claim():
    d=valid_cards();d['cards'][0]['what_to_write']=recommendation()
    assert errors(d)==[]
    assert 'anlamsal' in R.build(d)


@pytest.mark.parametrize('payload',['numeric','code','nested','missing','field','time','review'])
def test_unsupported_recommendations_rejected(payload):
    d=valid_cards();w=recommendation();d['cards'][0]['what_to_write']=w
    if payload=='numeric': w['text']='Örnek ücret 99 TL'
    if payload=='code': w['code']='{"fee":99}'
    if payload=='nested':
        w['items']=[{'url':URL,'field':'title','proposed':'Örnek ücret 99 TL'}]
        w['text']='Örnek ücret 10 TL';w['code']='Brand'
    if payload=='missing': d['page_facts']={}
    if payload=='field': w['derived_from'][0]['field']='description'
    if payload=='time': w['derived_from'][0]['read_at']='2026-10-14T10:00:00+00:00'
    if payload=='review': w.pop('review')
    assert errors(d)


@pytest.mark.parametrize('text',['Ücret 9 TL','Ücret %5','Tarih 2025-01-01','Adet 2'])
def test_short_numbers_never_filtered_out(text):
    d=valid_cards();d['cards'][0]['what_to_write']=recommendation(text)
    assert any('sayısal' in e for e in errors(d))


def record(url=URL):
    return {'check_id':'STR-1','url':url,'what_checked':'Başlık varlığı','checked_at':WHEN,
            'method':'live_http','evidence':'GET 200; title boş','conclusion':'confirmed'}


def test_timestamp_alone_and_sample_do_not_verify_scope():
    d=valid_cards();c=d['cards'][0];c['maya']['launch_gated']=['LG-93']
    c['evidence']={'verified_live':'2026-10-15'}
    assert errors(d)
    c['evidence']={'verification':[record()]}
    assert errors(d)==[]
    c['where'].update(count=2,affected_urls=[URL,URL+'second'])
    assert any('tam kapsam' in e for e in errors(d))
    html=R.build(d,draft=True)
    assert '1 / 2 adres' in html and 'TASLAK — DOĞRULANMADI' in html
    c['evidence']['verification'][0].pop('what_checked')
    assert any('verification' in e for e in errors(d))


def test_final_api_and_cli_reject_invalid_and_do_not_mutate(tmp_path):
    d=valid_cards();d['cards'][0]['what_to_write']=recommendation('ücret 99 TL')
    before=copy.deepcopy(d)
    with pytest.raises(ValueError,match='Final rapor reddedildi'):
        R.build(d)
    assert d==before
    path=tmp_path/'invalid.json';path.write_text(json.dumps(d))
    out=tmp_path/'final.html'
    p=subprocess.run([sys.executable,str(SCRIPTS/'render_report.py'),str(path),'-o',str(out)],capture_output=True,text=True)
    assert p.returncode!=0 and 'what_to_write' in p.stderr and not out.exists()
    assert json.loads(path.read_text(encoding="utf-8"))==before
    draft=R.build(d,draft=True)
    assert 'TASLAK — DOĞRULANMADI' in draft


def test_legacy_contract_draft_only_and_malformed_error():
    d=valid_cards();d['contract_version']=1
    assert errors(d)
    assert 'MÜŞTERİYE GÖNDERİLMEMELİ' in R.build(d,draft=True)
    assert V.validate([])[0]
    assert V.validate({'cards':'invalid'})[0]


def test_converter_cli_outputs_unavailable_and_version_two(tmp_path):
    rep=report('not_assessed');rep['audit_status']['content_coverage'].update(level='none',pages_read=0)
    p=tmp_path/'report.json';p.write_text(json.dumps(rep));out=tmp_path/'cards.json'
    subprocess.run([sys.executable,str(SCRIPTS/'from_maya_report.py'),str(p),'-o',str(out)],check=True,capture_output=True)
    d=json.loads(out.read_text(encoding="utf-8"))
    assert d['contract_version']==2 and d['score']['value'] is None
    assert d['score']['status']=='unavailable' and not any('puan' in k['label'].lower() for k in d['kpis'])  # H25: not a KPI


def test_invalid_fixed_claim_rejected():
    d=valid_cards();d['changes_since_last']={'fixed':[{'title':'Düzeldi','count':1}]}
    assert any('çözülme' in e for e in errors(d))


def test_fabricated_score_and_nested_outer_placeholders_rejected():
    d=valid_cards();d['score']['value']=99
    assert any('yeniden hesaplanan' in e for e in errors(d))
    d=valid_cards();d['manual_checks']=[{'what':{'nested':'Brand'},'where':'Panel'}]
    assert errors(d)


def test_unsupported_json_business_fact_even_with_review_is_rejected():
    d=valid_cards();d['cards'][0]['what_to_write']=recommendation()
    d['cards'][0]['what_to_write']['code']='{"@context":"https://schema.org","@type":"Organization","legalName":"Invented business"}'
    assert any('kelimeler' in e for e in errors(d))


def test_unverified_score_unavailable_and_no_render_mutation(tmp_path):
    f=finding();f['launch_gated']=['LG-93']
    rep=report('findings',f)
    path=tmp_path/'rep.json';path.write_text(json.dumps(rep));out=tmp_path/'out.json'
    subprocess.run([sys.executable,str(SCRIPTS/'from_maya_report.py'),str(path),'-o',str(out)],check=True,capture_output=True)
    d=json.loads(out.read_text(encoding="utf-8"))
    # Preserve local safety: excluding required unverified evidence must not
    # turn an incomplete assessment into a healthy score.
    assert d['score']['value'] is None and not d['cards'] and len(d['appendix_cards'])==1
    assert d['coverage']['score_status']=='unavailable'
    assert 'doğrulanmamış' in d['coverage']['score_reason']


def test_all_verification_fields_required_and_newer_coverage_gap():
    for field in ('url','check_id','checked_at','method','evidence','conclusion','what_checked'):
        d=valid_cards();c=d['cards'][0];c['maya']['launch_gated']=['LG-93']
        r=record();r.pop(field);c['evidence']={'verification':[r]}
        assert errors(d),field
    old=report('findings',finding());new=report()
    new['checks'][0]['coverage']['not_assessed']=[{'count':1,'reason':'not read'}]
    assert F.diff(new,old)['unknown']


def test_final_valid_cli_and_draft_cli(tmp_path):
    d=valid_cards();p=tmp_path/'cards.json';p.write_text(json.dumps(d));out=tmp_path/'report.html'
    cmd=[sys.executable,str(SCRIPTS/'render_report.py'),str(p),'-o',str(out)]
    assert subprocess.run(cmd,capture_output=True).returncode==0
    assert 'TASLAK — DOĞRULANMADI' not in out.read_text(encoding="utf-8")
    d['contract_version']=1;p.write_text(json.dumps(d))
    assert subprocess.run([*cmd,'--draft'],capture_output=True).returncode==0
    assert 'TASLAK — DOĞRULANMADI' in out.read_text(encoding="utf-8")


def test_old_observations_cannot_resolve_even_with_pass():
    old=report('findings',finding());new=report()
    result=F.diff(new,old)
    assert not result['fixed'] and result['unknown']
    new['crawl']['started_at']='2026-10-15T11:00:00+00:00'
    assert F.diff(new,old)['unknown']  # page copy itself remains old


def test_ineligible_native_response_cannot_support_recommendation():
    rep=report();rep['crawl']['pages'][0]['content_checks_eligible']=False
    assert F.page_facts_from_report(rep)=={}


@pytest.mark.parametrize('text',['Örnek ücret -10 TL','Örnek ücret %10 TL','Örnek ücret 10 USD'])
def test_numeric_sign_percentage_and_short_currency_units(text):
    d=valid_cards();d['cards'][0]['what_to_write']=recommendation(text)
    assert errors(d)


def test_missing_check_denominator_makes_score_unavailable():
    cov=F.coverage(report());cov['check_denominators']={}
    assert F.score([scored_card()],cov,CFG)[0] is None


def test_unknown_coverage_not_converted_to_zero():
    cov=F.coverage({})
    assert cov['pages_read'] is None and cov['discovered_not_read'] is None and cov['sitemap_urls'] is None
    cov=F.coverage({'crawl':{'sitemap_urls':[],'not_fetched_urls':[]}})
    assert cov['sitemap_urls']==0 and cov['discovered_not_read']==0


def test_recommendation_must_cite_its_own_page():
    d=valid_cards();w=recommendation()
    w['items']=[{'url':URL+'other','field':'title','proposed':'Örnek ücret 10 TL',
                 'derived_from':w['derived_from'],'review':w['review']}]
    d['cards'][0]['what_to_write']=w
    assert any('URLsi' in e for e in errors(d))


def test_provenance_required_for_recommendation():
    d=valid_cards();d['cards'][0]['what_to_write']=recommendation()
    d['page_facts'][URL]['observations'][0].pop('provenance')
    assert any('exact URL/source/field/read_at' in e for e in errors(d))


@pytest.mark.parametrize('change',['date','scope','kpi'])
def test_invalid_required_metadata_rejected_before_render(change):
    d=valid_cards()
    if change=='date': d['meta']['audit_date']='2026-99-99'
    if change=='scope': d['coverage']['assessment_level']='none'
    if change=='kpi': d['kpis'][1].pop('label')
    with pytest.raises(ValueError,match='Final rapor reddedildi'):
        R.build(d)
