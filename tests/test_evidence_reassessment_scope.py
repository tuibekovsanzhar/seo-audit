from maya_audit.analysis import analyze_html
from maya_audit.judgments import qualify_report

def test_saved_format_scope_excludes_noindex_and_names_missing_page_evidence():
    root='https://independent.example/'
    def page(url,noindex=False):
        text=('<meta name="robots" content="noindex">'if noindex else'')+'<main>'+('<img src="/x.jpg" alt="Workshop">'*8)+'</main>'
        return {'url':url,'status':200,'fetch_class':'ok','content_type':'text/html','content_checks_eligible':True,'analysis':analyze_html(text,url)}
    f={'id':'format','check_id':'STR-7','title':'0% of 16 content image(s) are offered in WebP or AVIF','how_to_fix':'Serve modern formats.','expected':'Smaller files','severity':'Info','confidence':'estimated','scope':{'kind':'pages','count':2,'urls':[root,root+'missing']},'evidence':{'images':16,'with_webp_or_avif':0}}
    r={'crawl':{'origin':root,'pages':[page(root),page(root+'utility',True)]},'checks':[{'check_id':'STR-7','status':'findings','evidence':{},'findings':[f]}]}
    q=qualify_report(r);f=q['checks'][0]['findings'][0];a=f['evidence']['format_assessment']
    assert a['occurrences']==8
    assert f['scope']['count']==1 and f['scope']['urls']==[root]
    assert a['source_pages_unassessed']==[root+'missing']


def test_full_source_image_membership_is_preserved_beyond_a_presentation_cap():
    root='https://public-library.example/'
    urls=[root+str(i)for i in range(35)]
    page={'url':urls[0],'status':200,'fetch_class':'ok','content_type':'text/html','content_checks_eligible':True,'analysis':analyze_html('<main><img src="/map.jpg" alt="Library map"></main>',urls[0])}
    f={'id':'format','check_id':'STR-7','title':'0% of 35 content image(s) are offered in WebP or AVIF','how_to_fix':'Convert images.','expected':'Smaller files','severity':'Info','confidence':'estimated','scope':{'kind':'template','count':35,'urls':urls[:20]},'evidence':{'images':35,'with_webp_or_avif':0}}
    r={'crawl':{'origin':root,'pages':[page]},'checks':[{'check_id':'STR-7','status':'findings','evidence':{},'findings':[f]}]}
    q=qualify_report(r,{'format':urls});f=q['checks'][0]['findings'][0]
    assert f['evidence']['original_format_scope']['urls']==urls
    assert f['evidence']['format_assessment']['source_pages_unassessed']==urls[1:]
    assert f['evidence']['format_assessment']['source_membership_complete'] is True
