"""Evidence scope helpers. No network, guessed formats, or inferred owner intent."""
from collections import Counter
from .urls import normalize_url

FORMAT_ACTION = 'Inspect the saved response formats and byte sizes for the same client and time. Compare suitable delivery alternatives at acceptable visual quality before choosing a conversion; markup extensions do not establish delivered format or guaranteed savings.'
FORMAT_EXPECTED = 'Image delivery choices supported by response format, size and quality evidence'
NOINDEX_ACTION = 'Confirm intended indexing with the owner. Retain intentional exclusions; change noindex only for pages confirmed to require indexing. Reconcile sitemap inclusion separately without overriding the intended policy.'


def image_formats(pages, responses):
    from .structure_data import content_images
    occurrences=[(p.url,i)for p in pages for i in content_images(p)]
    resources={i['url']for _,i in occurrences}
    observed=[]
    for row in responses:
        mime=(row.get('content_type')or'').split(';')[0].strip().lower()
        if row.get('url')not in resources or row.get('error') or not isinstance(row.get('status'),int) or not 200<=row['status']<300 or not mime.startswith('image/'):continue
        observed.append({k:row.get(k)for k in('url','source','status','requested_at','method','bytes','body_bytes','content_type','accept','vary','content_length','body_truncated','client')if k in row})
    known={r['url']for r in observed}
    return {'occurrences':len(occurrences),'unique_resources':len(resources),
            'markup_format_occurrences':dict(Counter(fmt for _,i in occurrences for fmt in set(i.get('formats')or[]))),
            'markup_modern_occurrences':sum(bool(set(i.get('formats')or[])&{'webp','avif'})for _,i in occurrences),
            'markup_references':[{'page':u,'resource':i['url'],'formats':i.get('formats')or[]}for u,i in occurrences],
            'response_resources_assessed':len(known),'delivery_unassessed_resources':len(resources-known),
            'response_formats':dict(Counter(r['content_type'].split(';')[0].strip().lower()for r in observed)),
            'response_observations':observed,
            'limits':'Markup references are not served formats. Responses describe only their recorded client/time; unobserved negotiation and alternative resources remain unassessed. Resource and occurrence counts differ.'}


def heading_state(analysis):
    elements=analysis.get('h1_elements')
    if elements is not None:
        state='meaningful'if any(e.get('text','').strip()for e in elements)else'empty'if elements else'absent'
    else:
        heads=[h for h in analysis.get('headings',[])if h['level']==1]
        state='meaningful'if any(h.get('text','').strip()for h in heads)else'empty'if heads else'no_meaningful_text_observed'
    return {'state':state,'elements':elements,'empty_kinds':[e.get('empty_kind') for e in elements or [] if not e.get('text','').strip()], 'meaningful_text':[h['text']for h in analysis.get('headings',[])if h['level']==1 and h['text'].strip()],
            'limits':None if elements is not None else 'Legacy heading extraction omitted empty elements; absence versus empty is unassessed.'}


def host_assessments(hosts):
    rows=[]
    for h in hosts:
        tls=h.get('tls')or{};red=h.get('http_redirect')or{};reason=str(red.get('reason')or'')
        mode=red.get('robots_mode')
        t='completed'if tls.get('valid')is True else'failed'if tls.get('valid')is False or tls.get('error')else'not_assessed'
        if red.get('checked'):r='completed'
        elif red.get('error'):r='failed'
        elif mode in ('unreachable','unavailable') or 'could not be read'in reason or 'unreachable'in reason or 'retrieval failed'in reason:r='inconclusive'
        elif 'disallows'in reason:r='blocked'
        else:r='not_assessed'
        rows.append({'host':h['host'],'tls':t,'http_redirect':r,'tls_evidence':tls,'http_redirect_evidence':red,'robots_interpretation':'retrieval_error_not_a_disallow_rule' if r=='inconclusive' else 'recorded_policy_or_not_assessed'})
    return rows


def membership(f):
    """Known members, complete flag. Never promote a presentation sample to full scope."""
    scope=f.get('scope')or{}
    candidates=scope.get('_all_urls')or scope.get('urls')or[]
    known=list(dict.fromkeys(normalize_url(u)or u for u in candidates))
    complete=len(known)==scope.get('count',len(known))
    return known,complete


def check_scope(cid, ev):
    if cid=='IDX-5':
        return {'population':'sitemap URL assessments; content reading is a separate scope','sitemap_urls_assessed':ev.get('listed_urls_assessed'),
                'sitemap_urls_unassessed':ev.get('listed_urls_not_fetched'), 'source':'native crawl and lightweight sitemap probes'}
    if cid=='IDX-1':return {'population':'native response classifications and recorded refetch attempts, including supported light probes; not limited to content-readable pages','status_counts':ev.get('status_counts'), 'extra_attempts':ev.get('attempts_counted')}
    if cid=='IDX-6':return {'population':'retained link destinations assessed by link probes; source pages read and destination requests differ','source':'check evidence links and external checks'}
    if cid=='IDX-2':return {'population':'per-host TLS and HTTP redirect assessments','host_assessments':host_assessments(ev.get('hosts')or[])}
    if cid in ('PRF-1','PRF-2'):return {'population':'native crawl, IDX-1 refetch and PRF round attempts; not sitemap probes or browser/provider requests','attempts_counted':ev.get('attempts_counted'),'sample_size':ev.get('sample_size')}
    if isinstance(ev.get('pages_checked'),int):return {'population':'eligible content pages for this check','eligible_content_pages':ev['pages_checked'],'browser_rendered_pages':ev.get('rendered_pages')}
    return None


def refresh_check_scope(check):
    """Upgrade only supported scope/outcome text, preserving raw saved summary."""
    from .coverage import PROBE_SCOPED, CRAWL_GAP_NAMES
    cid=check.get('check_id');ev=check.get('evidence')or{}
    coverage=check.setdefault('coverage',{})
    coverage.pop('assessment_scope', None)
    if cid in PROBE_SCOPED and probe_scope_recorded(cid,ev):
        coverage['not_assessed']=[p for p in coverage.get('not_assessed',[])if p.get('part')not in CRAWL_GAP_NAMES]
    sentence=scope_sentence(cid,ev)
    if sentence and sentence not in check.get('summary',''):
        check['summary']=check.get('summary','')+' '+sentence
    scope=check_scope(cid,ev)
    if scope:ev['assessment_scope']=scope
    if cid=='IDX-2' and ev.get('hosts'):
        outcomes=host_assessments(ev['hosts']);ev['host_assessments']=outcomes
        unavailable=[r for r in outcomes if r['tls']!='completed' or r['http_redirect']!='completed']
        if unavailable:
            coverage['not_assessed']=[p for p in coverage.get('not_assessed',[])if p.get('part')!='TLS / HTTP→HTTPS per host']
            coverage['not_assessed'].append({'part':'TLS / HTTP→HTTPS per host','count':len(unavailable),'reason':'; '.join(r['host']+' TLS='+r['tls']+', HTTP redirect='+r['http_redirect']+(' (robots retrieval did not establish a disallow rule)'if r['robots_interpretation']=='retrieval_error_not_a_disallow_rule'else'') for r in unavailable)})
        if any(r['tls']!='completed' or r['http_redirect']!='completed'for r in outcomes) and check.get('summary','').startswith('Certificates valid'):
            ev.setdefault('original_host_summary',check['summary'])
            check['summary']='Host assessment outcomes: '+ '; '.join(r['host']+' TLS='+r['tls']+', HTTP redirect='+r['http_redirect']for r in outcomes)+'. Incomplete assessments do not establish success.'
    check['evidence']=ev


def scope_sentence(check_id, evidence):
    """A bounded public scope statement, never borrowed from a content-read cap."""
    if check_id=='IDX-5' and isinstance(evidence.get('listed_urls_assessed'),int) and isinstance(evidence.get('listed_urls_not_fetched'),int):
        return f"Sitemap assessment: {evidence['listed_urls_assessed']} URL(s) checked; {evidence['listed_urls_not_fetched']} not assessed. Includes native responses and lightweight probes; content reads are separate."
    return None


def probe_scope_recorded(cid, ev):
    """A known request population, not merely a check ID, permits a separate scope."""
    if cid=='IDX-1':return bool(ev.get('status_counts') or ev.get('refetches'))
    if cid=='IDX-2':return bool(ev.get('hosts'))
    if cid=='IDX-5':return isinstance(ev.get('listed_urls_assessed'),int) and ev['listed_urls_assessed']>0
    if cid=='IDX-6':return 'internal_edges' in ev or bool(ev.get('links'))
    if cid=='PRF-1':return bool(ev.get('sample_size') or ev.get('measured'))
    if cid=='PRF-2':return bool(ev.get('attempts_counted'))
    return False
