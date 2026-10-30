"""Evidence-to-judgment regressions and contrasting defects; no external requests."""
import copy
import json
from types import SimpleNamespace

import httpx
import pytest

from maya_audit.analysis import analyze_html
from maya_audit.dataforseo import insights
from maya_audit.urls import non_page_kind
from maya_audit.report import qualified_group_key, finding_counts
from maya_audit_web import demo, pdf
from test_keyword_actions import keywords, page, STAMP
from test_false_alarms import images_check, no_lookups  # noqa: F401
from test_review_fixes import audit as checked, page as document, TR
from test_report_agreement import demo_app, audit  # noqa: F401
from test_web_app import API, get
from test_round2_sitemap_and_llms import KAFE, OK, EMPTY, audited


@pytest.mark.parametrize('q', ['ev yemekleri sipariş', 'ev yemekleri siparis', 'en yakın ev yemekleri'])
def test_generic_service_words_in_a_name_do_not_establish_brand(q):
    url='https://kart.example/menu'
    _,data=keywords([(q,url)],brand='Zeynep Hanım Ev Yemekleri', pages=[page(url,'Ev yemekleri sipariş')])
    a=data['keyword_assessments'][0]
    assert a['category']=='relevant'
    assert a['dimensions']['brand_identity']=='not_established'
    assert a['dimensions']['service_relevance']=='supported'
    assert data['provider_table']['rows'][0][0]==q


@pytest.mark.parametrize('q', ['zeynep hanım ev yemekleri','ZEYNEP HANIM EV YEMEKLERİ'])
def test_full_identity_names_our_brand(q):
    _,d=keywords([(q,'https://kart.example/')],brand='Zeynep Hanım Ev Yemekleri')
    assert d['keyword_assessments'][0]['dimensions']['brand_identity']=='supported'


def test_other_restaurant_service_overlap_is_not_our_brand_or_confirmed_relationship():
    url='https://kart.example/menu'
    _,d=keywords([('Ayşe ev yemekleri',url)],brand='Zeynep Hanım Ev Yemekleri',pages=[page(url,'Ev yemekleri sipariş')])
    a=d['keyword_assessments'][0]
    assert a['category']=='ambiguous'
    assert a['dimensions']['brand_identity']=='not_established'
    assert a['dimensions']['related_organization']=='not_established'


def test_local_and_editorial_dimensions_require_matching_saved_context():
    url='https://kart.example/subeler/cankaya'
    local=page(url,'Çankaya restoranlar')
    local.analysis['json_ld_blocks']=[json.dumps({'@type':'Restaurant','address':{'addressLocality':'Çankaya'}})]
    _,d=keywords([('çankaya restoranlar',url)],pages=[local])
    a=d['keyword_assessments'][0]
    assert a['dimensions']['local_relevance']=='supported'
    article=page('https://kart.example/bilgi','Kumkuat nedir?')
    article.analysis['json_ld_blocks']=[json.dumps({'@type':'Article'})]
    _,d=keywords([('kumkuat nedir',article.url)],pages=[article])
    assert d['keyword_assessments'][0]['dimensions']['editorial_relevance']=='supported'
    _,d=keywords([('kumkuat nedir','https://kart.example/unknown')])
    assert d['keyword_assessments'][0]['category']=='ambiguous'


def test_nested_equivalent_image_label_and_arbitrary_nearby_text_are_different():
    html='<figure><table><tr><td><img src="/yumurta.png" width="80" height="80" alt=""><strong>Yumurta</strong></td><td><figure><img src="/fiyat-grafigi.png" width="80" height="80" alt=""><figcaption>Grafik: Aylık fiyat değişimi</figcaption></figure>Tıklayın</td></tr></table></figure>'
    a=analyze_html(html)
    assert [i['beside_label'] for i in a['images']]==[True,False]
    check=images_check(html)
    [f]=[f for f in check.findings if 'meaningful' in f.title]
    assert f.evidence['empty_alt']==1 and f.evidence['images'][0]['src']=='/fiyat-grafigi.png'


def test_column_text_is_not_automatically_an_image_description():
    a=analyze_html('<figure><table><tr><th>Yumurta</th></tr><tr><td><img src="/yumurta.png" alt=""></td></tr></table></figure>')
    assert a['images'][0]['beside_label'] is False
    assert any('meaningful' in f.title for f in images_check('<figure><img src="/allergen-chart.png" alt=""><figcaption>Chart of allergen distribution</figcaption></figure>').findings)


@pytest.mark.parametrize('attrs',['data-gdpr_action="accept_all"','data-cookieconsent="accept"','role="button"','aria-controls="panel" aria-expanded="false"'])
def test_explicit_consent_and_accordion_controls_are_not_navigation_defects(attrs):
    a=analyze_html(f'<footer><a href="#" {attrs}>Kabul et</a><a href="#">Ürünler</a></footer>')
    assert a['dead_link_total']==1
    assert a['link_control_total']==1


def test_iframe_presence_is_uncertain_but_canvas_without_equivalent_remains_detected():
    o=checked({'/fiyatlar':document(f'<h1>Fiyatlar</h1><p>{TR}</p><iframe src="https://embed.example/list" title="Fiyatlar"></iframe><canvas id="prices"></canvas>')})
    fs=o.by_id['RND-4'].findings
    iframe=next(f for f in fs if 'iframe' in f.title)
    assert iframe.severity.value=='Info' and iframe.confidence.value=='inferred'
    assert 'not established' in iframe.title
    assert any(f.severity.value=='S4' and 'canvas' in f.title for f in fs)


@pytest.mark.parametrize('url',['https://example.test/audio.mp3?download=1','https://example.test/VIDEO.MP4','https://example.test/a.flac'])
def test_unsupported_media_is_not_a_page(url):
    assert non_page_kind(url)=='media'
    assert non_page_kind('https://example.test/article') is None


def test_llms_redirect_to_observed_healthy_destination_is_not_broken(no_lookups):
    llms='# Demo\n- [Moved](/old)\n- [Destination](/new)\n- [Broken](/bad)\n'
    o=audited({'/':OK,'/llms.txt':httpx.Response(200,headers={'content-type':'text/plain'},text=llms),'/old':httpx.Response(301,headers={'location':'/new'}),'/new':OK,'/bad':httpx.Response(404)})
    links=o.result.access.llms[0]['links']
    assert links['not_working']==1
    assert links['not_working_urls']==[KAFE+'/bad']
    old=next(r for r in links['rows'] if r['url']==KAFE+'/old')
    assert old['works'] is True and old['redirect_evidence']


def test_llms_unknown_redirect_destination_is_unassessed_not_healthy(no_lookups):
    llms='# Demo\n- [Moved](/old)\n'
    o=audited({'/':OK,'/llms.txt':httpx.Response(200,headers={'content-type':'text/plain'},text=llms),'/old':httpx.Response(301,headers={'location':'/not-requested'})})
    links=o.result.access.llms[0]['links']
    assert links['not_working']==0 and links['checked']==0
    assert links['not_checked']['redirect_destination_unassessed']==1
    assert links['rows'][0]['works'] is None


def test_semantic_identity_and_explicit_count_units():
    f={'id':'a','check_id':'STR-14','title':'1 empty link','severity':'S4','confidence':'verified','scope':{'count':2,'urls':['a','b']},'evidence':{'shared_element':{'type':'link','href':'/one','links':1,'pages':2,'where':'repeated'}}}
    other=copy.deepcopy(f);other['id']='b';other['evidence']['shared_element']['href']='/two'
    assert qualified_group_key(f)!=qualified_group_key(other)
    assert finding_counts(f)=={'occurrences':None,'affected_pages':2,'listed_unique_pages':2,'template_groups':1,'occurrences_per_template':None,'source_target_groups':None}
    f['evidence']={'by_page':[{'url':'a','links':6},{'url':'b','links':2}]}
    assert finding_counts(f)['occurrences']==8
    other['evidence']={}; f['evidence']={}
    assert qualified_group_key(f)!=qualified_group_key(other)


@pytest.mark.parametrize('language',['en','tr'])
def test_normal_summary_print_download_and_client_draft_retain_qualified_counts(demo_app,monkeypatch,language):
    one=audit(demo_app,demo.BANK,search_data=True,market_default_accepted=True)
    folder=demo_app.app.state.runner.artifacts(one['id']); path=folder/'report.json'
    r=json.loads(path.read_text(encoding="utf-8")); url='https://kart.example/menu'
    section,data=keywords([('ev yemekleri sipariş',url),('Ayşe ev yemekleri',url)],brand='Zeynep Hanım Ev Yemekleri',pages=[page(url,'Ev yemekleri sipariş')])
    for c in r['dataforseo']['checks']:
        if c['check_id']=='DFS-4':c['evidence']['data']=data;c['summary']=section['checks'][1]['summary']
    path.write_text(json.dumps(r)); original=path.read_bytes()
    from maya_audit_web.app import LANGUAGE_COOKIE
    demo_app.cookies.set(LANGUAGE_COOKIE,language)
    view=get(demo_app,one,'/summary')
    assert 'practical' in view
    html=demo_app.get(f'{API}/audits/{one["id"]}/print?full=true&lang={language}')
    assert html.status_code==200 and ('hizmet alakası' if language=='tr' else 'service relevance') in html.text
    assert 'Ayşe ev yemekleri' in html.text
    captured=[];monkeypatch.setattr(pdf,'to_pdf',lambda html,**kw:captured.append(html) or b'%PDF-test')
    assert demo_app.get(f'{API}/audits/{one["id"]}/downloads/pdf?lang={language}').status_code==200
    assert captured and 'ev yemekleri' in captured[0]
    assert path.read_bytes()==original


def test_reader_skips_media_without_spending_or_extending_unreadable_streak(tmp_path,no_lookups):
    from test_firecrawl_main_reader import open_site,MAIN,CFG
    from test_firecrawl import blocked_audit,client_for,Firecrawl,SITE
    from maya_audit.firecrawl import reader,panel
    o=blocked_audit(open_site)
    o.result.not_fetched_urls=['https://bank.test/podcast.mp3']
    o.result.sitemap_urls.append('https://bank.test/clip.mp4')
    api=Firecrawl(SITE)
    info=reader.apply(o,CFG,client_for(tmp_path,api),MAIN)
    assert not any(u.endswith(('.mp3','.mp4')) for u in api.urls)
    skipped=panel.section(info)['unsupported_resources']
    assert {r['kind'] for r in skipped}=={'media'}
    assert all(r['outcome']=='skipped_without_request' for r in skipped)
    assert info['coverage']['requested_without_a_readable_document']==0


def test_publication_and_modification_are_distinct_but_impossible_chronology_is_retained():
    from datetime import date
    from maya_audit.checks.structure import judge_dates
    from maya_audit.config import CrawlConfig
    def row(pub,mod):
        return {'url':'https://example.test/article','schema':{'datePublished':{'date':date.fromisoformat(pub)},'dateModified':{'date':date.fromisoformat(mod)}},'visible':[], 'sitemap':None,'header':None,'header_is_request_time':False,'requested_day':date(2026,10,16),'use_visible':True}
    assert judge_dates([row('2020-01-01','2026-01-01')],date(2026,10,16),CrawlConfig())['conflicts']==[]
    assert judge_dates([row('2026-01-01','2020-01-01')],date(2026,10,16),CrawlConfig())['conflicts']


def test_consent_category_requires_dialog_context_not_a_generic_category_link():
    a=analyze_html('<div id="gdpr-gdprmodal"><a class="btn category-header" href="#">Gerekli</a></div><nav><a class="category-header" href="#">Products</a></nav>')
    assert a['link_control_total']==1 and a['dead_link_total']==1


def test_local_and_editorial_context_uses_actual_analyzer_contract():
    from test_false_alarms import html,ld
    url='https://kart.example/subeler/cankaya'
    p=page(url,'Çankaya restoranlar')
    p.analysis=analyze_html(html('<h1>Çankaya restoranlar</h1>',head=ld({'@type':'Restaurant','address':{'@type':'PostalAddress','addressLocality':'Çankaya'}})),url)
    _,d=keywords([('cankaya restoranlar',url)],pages=[p])
    assert d['keyword_assessments'][0]['dimensions']['local_relevance']=='supported'
    p.url='https://kart.example/blog/kumkuat'
    p.analysis=analyze_html(html('<h1>Kumkuat nedir</h1>',head=ld({'@type':'Article'})),p.url)
    _,d=keywords([('kumkuat nedir',p.url)],pages=[p])
    assert d['keyword_assessments'][0]['dimensions']['editorial_relevance']=='supported'


def test_compound_turkish_image_name_matches_only_its_own_label():
    a=analyze_html('<table><tr><td><img src="/yer-fistigi.png" alt=""><strong>Yerfıstığı</strong></td><td><img src="/yer-fistigi.png" alt="">Fiyat listesi</td></tr></table>')
    assert [i['beside_label'] for i in a['images']]==[True,False]


def test_cms_article_markup_on_a_contact_page_does_not_prove_editorial_intent():
    from test_false_alarms import html,ld
    url='https://kart.example/contact'
    p=page(url,'Restoranlar ve iletişim')
    p.analysis=analyze_html(html('<h1>Ev yemekleri sipariş</h1>',head=ld({'@type':'Article'})+'<meta property="og:type" content="article">'),url)
    _,d=keywords([('ev yemekleri sipariş',url)],brand='Zeynep Hanım Ev Yemekleri',pages=[p])
    a=d['keyword_assessments'][0]
    assert a['dimensions']['service_relevance']=='supported'
    assert a['dimensions']['editorial_relevance']!='supported'


def test_editorial_body_evidence_is_readable_not_a_sketch_or_shared_furniture():
    from test_false_alarms import html,ld
    url='https://kart.example/blog/fruit'
    p=page(url,'Fruit guide')
    p.analysis=analyze_html(html('<h1>Meyve rehberi</h1><p>Kumkuat nedir? Küçük bir narenciye meyvesidir.</p>',head=ld({'@type':'Article'})),url)
    _,d=keywords([('kumkuat nedir',url)],pages=[p])
    a=d['keyword_assessments'][0]
    assert a['dimensions']['editorial_relevance']=='supported'
    assert any(s['source'].startswith('saved readable') and 'Kumkuat' in ' '.join(s['texts']) for s in a['sources'])
    p.analysis={'title':'Fruit guide','text_sketch':['kumkuat','nedir']}
    _,d=keywords([('kumkuat nedir',url)],pages=[p])
    assert d['keyword_assessments'][0]['category']=='ambiguous'


def test_link_target_groups_do_not_masquerade_as_occurrence_counts():
    from test_false_alarms import site,html
    from maya_audit.checks.content_quality import str14_anchor_text
    from maya_audit.config import CrawlConfig
    from maya_audit.models import to_jsonable
    r,pages=site({'/':html('<a href="/target">Detaylı bilgi</a><a href="/target">Detaylı bilgi</a><a href="/target"></a><a href="/empty"></a><a href="/empty"></a>')})
    fs=str14_anchor_text(r,CrawlConfig(),pages,set()).findings
    generic=next(to_jsonable(f) for f in fs if 'generic' in f.title)
    empty=next(to_jsonable(f) for f in fs if 'no text' in f.title)
    assert finding_counts(generic)['source_target_groups']==1
    assert finding_counts(generic)['occurrences']==2
    assert finding_counts(empty)['source_target_groups']==1
    assert finding_counts(empty)['occurrences']==2
    # Old generic rows do not retain empty-link counts: no invented precise denominator.
    generic['evidence']['links'][0].pop('links_with_generic_text')
    generic['evidence'].pop('occurrences')  # Legacy evidence had neither an explicit total nor per-row counts.
    assert finding_counts(generic)['occurrences'] is None


def test_service_query_on_a_branch_does_not_automatically_gain_local_intent():
    url='https://kart.example/sube/cankaya'
    _,d=keywords([('qr ödeme',url)],pages=[page(url,'QR ödeme')])
    assert d['keyword_assessments'][0]['category']=='relevant'
    assert d['keyword_assessments'][0]['dimensions']['local_relevance']!='supported'


@pytest.mark.parametrize('message,expected',[('HTTP 408: scrape timed out','provider_timeout'),('service temporarily unavailable','provider_error'),('daily credit limit reached','credit_or_request_limit')])
def test_reader_stop_causes_do_not_invent_a_credit_refusal(tmp_path,no_lookups,monkeypatch,message,expected):
    from test_firecrawl_main_reader import open_site,MAIN,CFG
    from test_firecrawl import blocked_audit,client_for,Firecrawl,SITE
    from maya_audit.firecrawl import reader
    from maya_audit.content_provider import ContentProviderError
    client=client_for(tmp_path,Firecrawl(SITE))
    def fail(url,**kwargs):raise ContentProviderError(message)
    monkeypatch.setattr(client,'scrape',fail)
    info=reader.apply(blocked_audit(open_site),CFG,client,MAIN)
    assert info['coverage']['not_requested_because']==expected
    assert info['stopped_because']==message
